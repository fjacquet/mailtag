import hashlib
import time
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from loguru import logger

from .config import AppConfig
from .database import ClassificationDatabase
from .folder_analyzer import FolderAnalyzer
from .metrics import METRICS
from .models import Email
from .utils.domain_utils import extract_domain, is_non_commercial_domain_cached
from .utils.text_utils import smart_truncate

if TYPE_CHECKING:
    from .mlx_provider import MLXLLM, MLXEmbedder
    from .semantic_router import SemanticRouter


class Classifier:
    """
    Classifies emails using a multi-signal strategy, prioritizing server-side
    labels, then historical data, semantic routing, and finally an AI model.
    """

    def __init__(self, config: AppConfig, database: ClassificationDatabase):
        self.config = config
        self.proposal_file = Path("proposals.log")
        self.database = database
        self.ai_cache = {}  # Simple in-memory cache for AI responses

        # MLX components (lazy loaded)
        self._embedder: MLXEmbedder | None = None
        self._semantic_router: SemanticRouter | None = None
        self._mlx_llm: MLXLLM | None = None
        self._mlx_initialized = False

        # Use either folder analyzer or static schema based on configuration
        if config.general.use_imap_folders_for_classification:
            self.folder_analyzer = FolderAnalyzer()
            self.categories = self.folder_analyzer.get_all_categories()
            logger.info(f"Using dynamic IMAP folder structure with {len(self.categories)} categories")
        else:
            self.folder_analyzer = None
            self.categories = self._load_categories_from_schema()
            logger.info(f"Using static classification schema with {len(self.categories)} categories")

    def _init_mlx_components(self) -> bool:
        """Lazy initialize MLX components when first needed.

        Returns:
            True if initialization successful, False otherwise
        """
        if self._mlx_initialized:
            return self._semantic_router is not None

        self._mlx_initialized = True

        if not self.config.mlx.enabled:
            logger.debug("MLX classification is disabled in config")
            return False

        try:
            from .mlx_provider import MLXLLM, MLXEmbedder
            from .semantic_router import SemanticRouter

            # Initialize embedder
            logger.info(f"Initializing MLX embedder with model: {self.config.mlx.embedding_model}")
            self._embedder = MLXEmbedder(self.config.mlx.embedding_model)

            # Initialize semantic router
            self._semantic_router = SemanticRouter(
                self._embedder,
                score_threshold=self.config.mlx.score_threshold,
            )

            # Try to load pre-computed embeddings
            embeddings_path = Path(self.config.mlx.embeddings_file)
            if embeddings_path.exists():
                if self._semantic_router.load_embeddings(embeddings_path):
                    num_cats = self._semantic_router.num_categories
                    logger.info(f"Loaded {num_cats} category embeddings from {embeddings_path}")
                else:
                    logger.warning(f"Failed to load embeddings from {embeddings_path}")
            else:
                logger.warning(
                    f"No embeddings file found at {embeddings_path}. "
                    "Run 'python scripts/build_category_embeddings.py' to generate."
                )

            # Initialize LLM for fallback
            logger.info(f"Initializing MLX LLM with model: {self.config.mlx.llm_model}")
            self._mlx_llm = MLXLLM(
                model_name=self.config.mlx.llm_model,
                max_tokens=self.config.mlx.llm_max_tokens,
                temperature=self.config.mlx.llm_temperature,
            )

            logger.info("MLX components initialized successfully")
            return True

        except ImportError as e:
            logger.warning(f"MLX dependencies not available: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize MLX components: {e}")
            return False

    def _load_categories_from_schema(self) -> list[str]:
        """Loads classification categories from the YAML file (legacy method)."""
        schema_path = Path("data/classification_schema.yml")
        if not schema_path.exists():
            logger.error(f"Classification schema not found at {schema_path}")
            return []
        with schema_path.open("r", encoding="utf-8") as f:
            schema = yaml.safe_load(f)

        categories = []
        for category in schema:
            if "sublabels" in category and category["sublabels"]:
                for sublabel in category["sublabels"]:
                    categories.append(f"{category['name']}/{sublabel['name']}")
            else:
                categories.append(category["name"])
        return categories

    def _get_category_from_validated_db(self, email: Email) -> str | None:
        """
        Signal 1: Check for a classification from the validated database.
        """
        return self.database.get_dominant_classification(email.sender_address)

    def _get_category_from_labels(self, email: Email) -> str | None:
        """
        Signal 2: Check for an existing server-side label that matches a known category.
        """
        for label in email.labels:
            if label in self.categories:
                logger.debug(f"Found matching server-side label: {label}")
                return label
        return None

    def _get_category_from_history(self, email: Email) -> str | None:
        """
        Signal 3: Check for a high-confidence classification from the sender's history in the suggestion DB.
        """
        sender_classifications = self.database.suggestion_db.get(email.sender_address)
        if not sender_classifications:
            return None

        total_count = sum(sender_classifications.values())
        if total_count < self.config.classifier.min_count:
            return None

        most_common_category = max(sender_classifications, key=sender_classifications.get)
        confidence = sender_classifications[most_common_category] / total_count

        if confidence >= self.config.classifier.historical_confidence_threshold:
            logger.info(
                f"Found high-confidence historical category for {email.sender_address}: "
                f"{most_common_category} ({confidence:.2f} confidence)."
            )
            return most_common_category
        return None

    def _get_category_from_domain(self, email: Email) -> str | None:
        """
        Signal 4: Check for domain-based classification.
        Skip non-commercial domains (gmail.com, yahoo.com, etc.)
        """
        if not email.sender_address:
            return None

        domain = extract_domain(email.sender_address)
        if not domain:
            return None

        # Skip non-commercial domains (personal email providers)
        if is_non_commercial_domain_cached(domain):
            logger.debug(f"Skipping non-commercial domain: {domain}")
            return None

        # Look up domain classification
        category = self.database.get_category_by_domain(domain)
        if category:
            logger.info(
                f"Found domain-based classification for {email.sender_address}: {category} (domain: {domain})"
            )
            return category

        logger.debug(f"No domain classification found for: {domain}")
        return None

    def _get_category_from_semantic_router(self, email: Email) -> tuple[str | None, float]:
        """
        Signal 5: Use semantic router for embedding-based classification.

        Returns:
            Tuple of (category, confidence_score) or (None, 0.0) if no match
        """
        if not self._init_mlx_components():
            return None, 0.0

        if self._semantic_router is None or self._semantic_router.num_categories == 0:
            logger.debug("Semantic router not available or no categories loaded")
            return None, 0.0

        # Build query text from email
        sender = email.sender_name or email.sender_address or "Unknown"
        query_text = f"Email from {sender}: {email.subject}"

        # Add truncated body if available
        if email.body:
            truncated_body = self._truncate_body(email.body, max_chars=500)
            if truncated_body:
                query_text += f"\n{truncated_body}"

        # Route using semantic similarity
        category, score = self._semantic_router.route(query_text)

        if category:
            # Validate category exists in our known categories
            if category in self.categories:
                logger.debug(
                    f"Semantic router matched '{category}' with score {score:.3f}"
                )
                return category, score
            else:
                logger.debug(
                    f"Semantic router suggested unknown category '{category}', ignoring"
                )

        return None, score

    def _get_cache_key(self, email: Email) -> str:
        """Generate a cache key for AI responses based on sender and subject."""
        sender = email.sender_address or "Unknown"
        subject = email.subject or "No Subject"
        # Create a hash of sender + subject for caching
        cache_input = f"{sender.lower()}:{subject.lower()}"
        return hashlib.md5(cache_input.encode()).hexdigest()

    def _truncate_body(self, body: str, max_chars: int = 1500) -> str:
        """Intelligently truncate email body to preserve important content.

        Uses smart_truncate to:
        - Remove quoted replies and signatures
        - Extract key paragraphs and sentences
        - Preserve high-signal keywords

        Default increased from 500 to 1500 chars for better context.
        """
        if not body:
            return ""
        return smart_truncate(body, max_chars=max_chars)

    def _parse_ai_json_response(self, raw_response: str) -> tuple[str, float, str]:
        """
        Parse JSON response from AI model.

        Returns:
            Tuple of (category, confidence, reason)
        """
        import json
        import re

        # Extract JSON from response (handles markdown code blocks)
        json_match = re.search(r"\{[^}]+\}", raw_response, re.DOTALL)
        if not json_match:
            # Fallback: try to parse the entire response
            json_match = re.search(r"\{.*\}", raw_response, re.DOTALL)

        if json_match:
            try:
                result = json.loads(json_match.group(0))
                category = result.get("category", "").strip()
                confidence = float(result.get("confidence", 0.0))
                reason = result.get("reason", "")

                # Validate confidence range
                if not 0.0 <= confidence <= 1.0:
                    logger.warning(f"AI confidence {confidence} out of range [0,1], clamping")
                    confidence = max(0.0, min(1.0, confidence))

                return category, confidence, reason
            except (json.JSONDecodeError, ValueError, KeyError) as e:
                logger.debug(f"JSON parse error: {e}, falling back to legacy parsing")
                return "", 0.0, ""

        return "", 0.0, ""

    def _parse_legacy_ai_response(self, raw_response: str) -> str:
        """
        Fallback parser for non-JSON responses (legacy format).

        Returns:
            Category string or empty string if invalid
        """
        category = raw_response.strip()

        # Handle legacy UNCERTAIN format
        if category.startswith("UNCERTAIN"):
            return ""

        # Handle folder-based classification responses
        if self.config.general.use_imap_folders_for_classification and self.folder_analyzer:
            if category.startswith("Parent/NewSub"):
                return ""

        return category

    def _get_category_from_ai(self, email: Email) -> str:
        """
        Signal 6: Fallback to the MLX LLM for classification with confidence scoring.
        """
        sender = (
            f"{email.sender_name} <{email.sender_address}>"
            if email.sender_name
            else email.sender_address or "Unknown"
        )
        logger.debug(f"Using MLX LLM classification for email from {sender}")

        # Ensure MLX is initialized
        if not self._init_mlx_components():
            logger.warning("MLX LLM not available")
            return "(Model Error)"

        if self._mlx_llm is None:
            logger.warning("MLX LLM not initialized")
            return "(Model Error)"

        # Check cache first
        cache_key = self._get_cache_key(email)
        if cache_key in self.ai_cache:
            logger.debug(f"Using cached AI response for {email.sender_address}")
            return self.ai_cache[cache_key]

        # Truncate email body for better performance
        truncated_body = self._truncate_body(email.body)

        if self.folder_analyzer:
            # Use dynamic folder structure
            all_folders = self.folder_analyzer.get_all_categories()
            parent_folders = self.folder_analyzer.get_parent_folders()

            # Create a more concise list for the prompt
            category_list = "\n".join([f"- {cat}" for cat in sorted(all_folders)])

            prompt = (
                f"Sujet: {email.subject}\n"
                f"De: {sender}\n"
                f"Corps: {truncated_body}\n\n"
                "Classe dans une des catégories suivantes (la plus spécifique possible):\n"
                f"{category_list}\n\n"
                "Si aucune catégorie n'existe, propose un sous-dossier: 'Parent/NewSub'\n"
                f"Parents valides: {', '.join(sorted(parent_folders))}\n\n"
                "IMPORTANT: Réponds en format JSON structuré:\n"
                "{\n"
                '  "category": "NomExactCategorie",\n'
                '  "confidence": 0.95,\n'
                '  "reason": "brève explication (optionnel)"\n'
                "}\n\n"
                "- category: nom exact ou 'Parent/NewSub' pour nouveau sous-dossier\n"
                "- confidence: score entre 0.0 et 1.0 (0.0 = incertain, 1.0 = très confiant)\n"
                "- reason: pourquoi cette catégorie (1 phrase courte, optionnel)\n\n"
                "N'invente PAS de nouvelles catégories qui ne sont pas dans la liste."
            )
        else:
            # Legacy behavior using static schema
            category_list = "\n".join([f"- {cat}" for cat in self.categories])

            prompt = (
                f"Sujet: {email.subject}\n"
                f"De: {sender}\n"
                f"Corps: {truncated_body}\n\n"
                "Classe dans une catégorie de la liste suivante:\n"
                f"{category_list}\n\n"
                "IMPORTANT: Réponds en format JSON structuré:\n"
                "{\n"
                '  "category": "NomExactCategorie",\n'
                '  "confidence": 0.95,\n'
                '  "reason": "brève explication (optionnel)"\n'
                "}\n\n"
                "- category: nom exact de la liste ci-dessus\n"
                "- confidence: score entre 0.0 et 1.0 (0.0 = incertain, 1.0 = très confiant)\n"
                "- reason: pourquoi cette catégorie (1 phrase courte, optionnel)\n\n"
                "N'invente PAS de nouvelles catégories qui ne sont pas dans la liste."
            )

        try:
            # Use MLX LLM classify method
            category, confidence, reason = self._mlx_llm.classify(prompt)

            if category:
                logger.debug(
                    f"MLX LLM classification: category='{category}', "
                    f"confidence={confidence:.2f}, reason='{reason}'"
                )

                # Check against confidence threshold
                confidence_threshold = self.config.mlx.llm_confidence
                if confidence < confidence_threshold:
                    logger.info(
                        f"MLX LLM confidence {confidence:.2f} below threshold "
                        f"{confidence_threshold:.2f}, routing to 'À Classer'"
                    )
                    self._log_proposal(email, f"{category} (confidence: {confidence:.2f}, reason: {reason})")
                    return "À Classer"

                # Validate category exists or is a new folder proposal
                if self.config.general.use_imap_folders_for_classification and self.folder_analyzer:
                    # Handle new subfolder suggestions
                    if "/" in category and category not in self.categories:
                        parts = category.split("/", 1)
                        if len(parts) == 2:
                            parent, _subfolder = parts
                            if self.folder_analyzer.is_valid_parent_folder(parent):
                                logger.debug(f"Valid new folder proposal: '{category}'")
                                self._log_proposal(
                                    email, f"{category} (confidence: {confidence:.2f}, reason: {reason})"
                                )
                                return "À Classer"

                    # Check if category exists
                    if category not in self.categories:
                        logger.warning(f"MLX LLM suggested invalid category: '{category}'")
                        self._log_proposal(
                            email, f"{category} (confidence: {confidence:.2f}, reason: {reason})"
                        )
                        return "À Classer"
                else:
                    # Static schema mode
                    if category not in self.categories:
                        logger.warning(f"MLX LLM suggested invalid category: '{category}'")
                        self._log_proposal(
                            email, f"{category} (confidence: {confidence:.2f}, reason: {reason})"
                        )
                        return "À Classer"

                # Cache and return valid classification
                self.ai_cache[cache_key] = category
                return category

            else:
                # Empty category means parsing failed or uncertain
                logger.debug("MLX LLM returned empty category")
                self._log_proposal(email, f"(empty response, confidence: {confidence:.2f})")
                return "À Classer"

        except Exception as e:
            logger.error(f"Error calling MLX LLM: {e}")
            return "(Model Error)"

    def classify_email(self, email: Email) -> str:
        """
        Classifies an email using the Adaptive Multi-Signal Classification (AMSC) strategy.
        Tracks classification metrics for each signal.
        """
        start_time = time.perf_counter()

        # Signal 1: Validated Database
        category = self._get_category_from_validated_db(email)
        if category:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.info(f"Classified via Validated DB: {category}")
            METRICS.classification_metrics.record_classification(
                email_id=email.msg_id,
                signal="validated_db",
                category=category,
                confidence=1.0,  # Validated = 100% confidence
                processing_time_ms=elapsed_ms,
            )
            return category

        # Signal 2: Server-Side Label
        category = self._get_category_from_labels(email)
        if category:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.info(f"Classified via Server Label: {category}")
            self.database.update_suggestion(email.sender_address, category)
            METRICS.classification_metrics.record_classification(
                email_id=email.msg_id,
                signal="server_labels",
                category=category,
                confidence=0.95,  # High confidence from user's existing organization
                processing_time_ms=elapsed_ms,
            )
            return category

        # Signal 3: Historical Suggestion Database
        category = self._get_category_from_history(email)
        if category:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.info(f"Classified via History: {category}")

            # Calculate actual confidence from historical data
            sender_classifications = self.database.suggestion_db.get(email.sender_address, {})
            total_count = sum(sender_classifications.values())
            confidence = sender_classifications.get(category, 0) / total_count if total_count > 0 else 0.0

            METRICS.classification_metrics.record_classification(
                email_id=email.msg_id,
                signal="historical_db",
                category=category,
                confidence=confidence,
                processing_time_ms=elapsed_ms,
            )
            return category

        # Signal 4: Domain-based Classification
        category = self._get_category_from_domain(email)
        if category:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.info(f"Classified via Domain: {category}")
            self.database.update_suggestion(email.sender_address, category)
            METRICS.classification_metrics.record_classification(
                email_id=email.msg_id,
                signal="domain_db",
                category=category,
                confidence=0.90,  # Domain rules are high confidence
                processing_time_ms=elapsed_ms,
            )
            return category

        # Signal 5: Semantic Router (Embedding-based classification)
        category, semantic_score = self._get_category_from_semantic_router(email)
        if category:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.info(f"Classified via Semantic Router: {category} (score: {semantic_score:.3f})")
            self.database.update_suggestion(email.sender_address, category)
            METRICS.classification_metrics.record_classification(
                email_id=email.msg_id,
                signal="semantic_router",
                category=category,
                confidence=semantic_score,
                processing_time_ms=elapsed_ms,
            )
            return category

        # Signal 6: MLX LLM (Fallback)
        logger.debug("No high-confidence signals found, falling back to MLX LLM.")
        category = self._get_category_from_ai(email)
        total_elapsed_ms = (time.perf_counter() - start_time) * 1000

        logger.info(f"Classified via MLX LLM: {category}")

        if category not in ["À Classer", "(Model Error)"]:
            self.database.update_suggestion(email.sender_address, category)
            METRICS.classification_metrics.record_classification(
                email_id=email.msg_id,
                signal="mlx_llm",
                category=category,
                confidence=None,  # Confidence already tracked in _get_category_from_ai
                processing_time_ms=total_elapsed_ms,
            )
        elif category == "(Model Error)":
            METRICS.classification_metrics.record_error("mlx_llm_error", email.sender_address)
        else:
            # "À Classer" - low confidence or uncertain
            METRICS.classification_metrics.record_error("mlx_llm_uncertain", email.sender_address)

        return category

    def _log_proposal(self, email: Email, proposal: str):
        """Logs a classification proposal to a file."""
        sender = (
            f"{email.sender_name} <{email.sender_address}>" if email.sender_name else email.sender_address
        )
        with self.proposal_file.open("a", encoding="utf-8") as f:
            f.write("=" * 80 + "\n")
            f.write(f"From: {sender}\n")
            f.write(f"Subject: {email.subject}\n")
            f.write(f"Proposed Category: {proposal}\n")
            f.write(f"Body:\n{email.body}\n\n")

    def export_metrics(self, output_dir: Path = Path("data/metrics")) -> Path:
        """Export classification metrics to JSON file.

        Args:
            output_dir: Directory to save metrics file

        Returns:
            Path to exported metrics file
        """
        from datetime import datetime

        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = output_dir / f"classification_metrics_{timestamp}.json"

        METRICS.classification_metrics.export_to_json(filepath)
        logger.info(f"Exported classification metrics to {filepath}")

        return filepath

    def log_metrics_summary(self, log_level: str = "INFO"):
        """Log a formatted summary of classification metrics.

        Args:
            log_level: Log level to use for output
        """
        METRICS.classification_metrics.log_summary(log_level)
