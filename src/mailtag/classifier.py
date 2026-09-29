import threading
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from .config import AppConfig
from .models import Email
from .taxonomy import (
    REVIEW,
    TAXONOMY,
    llm_email_part,
    llm_static_prompt,
    nomic_text,
    parse_category_number,
    to_category,
)
from .taxonomy_store import TaxonomyStore
from .utils.text_utils import smart_truncate

if TYPE_CHECKING:
    from .mlx_provider import MLXLLM, MLXEmbedder
    from .semantic_router import SemanticRouter


class Classifier:
    """Classifies emails into the 19-category taxonomy.

    Rules first (validated sender, learned sender, domain), then nomic embeddings above the
    threshold, else nomic and the LLM must agree; anything else goes to review.
    """

    def __init__(self, config: AppConfig, read_only: bool = False):
        self.config = config
        self._mlx_lock = threading.RLock()  # Reentrant lock for MLX initialization

        # MLX components (lazy loaded)
        self._embedder: MLXEmbedder | None = None
        self._semantic_router: SemanticRouter | None = None
        self._mlx_llm: MLXLLM | None = None
        self._mlx_initialized = False

        self.categories = list(TAXONOMY)
        self.taxonomy_store = TaxonomyStore(
            Path(config.taxonomy.taxonomy_db_dir),
            min_agreements=config.taxonomy.learn_min_agreements,
            own_addresses=config.taxonomy.own_addresses,
            read_only=read_only,
        )
        logger.info(f"Using the {len(self.categories)}-category taxonomy")

    def _embeddings_path(self) -> Path:
        """The 19 real-mail centroids."""
        return Path(self.config.taxonomy.centroids_file)

    def _init_mlx_components(self) -> bool:
        """Lazy initialize MLX components when first needed (thread-safe).

        Returns:
            True if initialization successful, False otherwise
        """
        with self._mlx_lock:
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
                self._semantic_router = SemanticRouter(self._embedder)

                # Try to load pre-computed embeddings
                embeddings_path = self._embeddings_path()
                if embeddings_path.exists():
                    if self._semantic_router.load_embeddings(embeddings_path):
                        num_cats = self._semantic_router.num_categories
                        logger.info(f"Loaded {num_cats} category embeddings from {embeddings_path}")
                    else:
                        logger.warning(f"Failed to load embeddings from {embeddings_path}")
                else:
                    logger.warning(
                        f"No embeddings file found at {embeddings_path}. "
                        "Run 'python scripts/taxonomy_setup.py build' to generate."
                    )

                # Initialize LLM for fallback
                logger.info(f"Initializing MLX LLM with model: {self.config.mlx.llm_model}")
                self._mlx_llm = MLXLLM(model_name=self.config.mlx.llm_model)

                logger.info("MLX components initialized successfully")
                return True

            except ImportError as e:
                logger.warning(f"MLX dependencies not available: {e}")
                return False
            except (OSError, RuntimeError, ValueError) as e:
                logger.error(f"Failed to initialize MLX components: {e}")
                return False

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

    def _rule_category(self, email: Email) -> str | None:
        """Signals 1, 3 and 4 from the taxonomy store (Signal 2, labels, is not used in taxonomy mode)."""
        return self.taxonomy_store.category_for(email.sender_address)

    def _nomic_top(self, emails: list[Email]) -> list[tuple[str | None, float]]:
        """Signal 5: nearest centroid (a category, or a legacy folder mapped to its category),
        with its similarity."""
        unavailable = [(None, 0.0)] * len(emails)
        if not self._init_mlx_components() or not self._semantic_router:
            return unavailable
        if self._semantic_router.num_categories == 0:
            return unavailable
        texts = [nomic_text(e.sender_name, e.sender_address, e.subject, e.body) for e in emails]
        try:
            top = self._semantic_router.top_batch(texts)
        except (RuntimeError, ValueError, AttributeError, OSError) as e:
            logger.error(f"Semantic router failed, sending emails to review: {e}")
            return unavailable
        return [(to_category(label), score) for label, score in top]

    def _llm_categories(self, emails: list[Email]) -> list[str | None]:
        """Signal 6: one category (or None) per email from the LLM, answered by number."""
        if not self._init_mlx_components() or self._mlx_llm is None:
            return [None] * len(emails)
        parts = [
            llm_email_part(
                e.subject,
                f"{e.sender_name} <{e.sender_address}>" if e.sender_name else e.sender_address,
                self._truncate_body(e.body, max_chars=500),
            )
            for e in emails
        ]
        try:
            answers = self._mlx_llm.classify_batch(
                llm_static_prompt(), parts, batch_size=self.config.taxonomy.llm_batch_size
            )
        except (RuntimeError, ValueError, KeyError, AttributeError, TypeError) as e:
            logger.error(f"LLM batch failed, sending emails to review: {e}")
            return [None] * len(emails)
        return [parse_category_number(answer) for answer in answers]

    def _classify_uncertain_detailed(self, emails: list[Email]) -> list[tuple[str, bool]]:
        """Signals 5-6: (category, nomic and LLM agreed) — nomic above threshold, else LLM agreement."""
        results: list[tuple[str, bool]] = [(REVIEW, False)] * len(emails)
        need_llm: list[tuple[int, str]] = []
        for i, (category, score) in enumerate(self._nomic_top(emails)):
            if category and score >= self.config.taxonomy.nomic_threshold:
                results[i] = (category, False)
            elif category:  # without a nomic category the LLM cannot agree with it
                need_llm.append((i, category))
        if need_llm:
            answers = self._llm_categories([emails[i] for i, _ in need_llm])
            for (i, nomic_category), llm_category in zip(need_llm, answers, strict=True):
                if llm_category and llm_category == nomic_category:
                    results[i] = (llm_category, True)
        return results

    def classify_detailed(self, emails: list[Email]) -> list[tuple[str, bool]]:
        """(category, nomic and LLM agreed) per email: rules, then the nomic/LLM chain. Learns nothing."""
        results: list[tuple[str, bool] | None] = [
            (category, False) if (category := self._rule_category(e)) else None for e in emails
        ]
        pending = [i for i, result in enumerate(results) if result is None]
        if pending:
            for i, result in zip(pending, self._classify_uncertain_detailed([emails[i] for i in pending])):
                results[i] = result
        logger.info(
            f"Taxonomy batch: {len(emails) - len(pending)} by rules, "
            f"{sum(1 for i in pending if results[i][0] != REVIEW)} by models, "
            f"{sum(1 for r in results if r[0] == REVIEW)} to review"
        )
        return results  # type: ignore[return-value]

    def learn(self, emails: list[Email], results: list[tuple[str, bool]]) -> None:
        """Record the agreements of `classify_detailed` results, so their senders can become rules."""
        for email, (category, agreed) in zip(emails, results, strict=True):
            if agreed:
                self.taxonomy_store.record_agreement(email.sender_address, category)
        self.taxonomy_store.save()

    def classify_emails_batch(self, emails: list[Email]) -> list[str]:
        """One category per email: rules, then the nomic/LLM chain; agreements teach the sender rules."""
        results = self.classify_detailed(emails)
        self.learn(emails, results)
        return [category for category, _ in results]

    def classify_email(self, email: Email) -> str:
        return self.classify_emails_batch([email])[0]
