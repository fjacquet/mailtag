import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass
class LoggingConfig:
    level: str
    file: str


@dataclass
class GeneralConfig:
    ollama_model: str
    api_base: str
    use_imap_folders_for_classification: bool = True


@dataclass
class ClassifierConfig:
    ai_confidence_threshold: float
    historical_confidence_threshold: float
    min_count: int
    num_ctx: int = 8192  # AI model context window size


@dataclass
class ImapConfig:
    host: str
    user: str
    password: str
    use_gmail_extensions: bool = False


@dataclass
class GmailConfig:
    credentials_file: str
    token_file: str


@dataclass
class FastParseConfig:
    batch_size: int = 500
    folder_cache_ttl_hours: int = 24
    unclassified_folder_name: str = "Unclassified"
    junk_folder_name: str = "Junk"
    max_retries: int = 3
    retry_delay: float = 1.0
    retry_backoff: float = 2.0
    retry_jitter: float = 0.1
    metrics_enabled: bool = True
    metrics_log_level: str = "DEBUG"
    metrics_log_interval_minutes: int = 10


@dataclass
class MLXConfig:
    """Configuration for MLX-based classification (Apple Silicon optimized)."""

    enabled: bool = True
    # Semantic Router (Signal 5) - embedding-based classification
    embedding_model: str = "nomic-ai/nomic-embed-text-v1.5"
    score_threshold: float = 0.75
    embeddings_file: str = "data/category_embeddings.npz"
    # LLM Fallback (Signal 6) - text generation
    llm_model: str = "mlx-community/gemma-4-e4b-it-OptiQ-4bit"
    llm_confidence: float = 0.85
    llm_max_tokens: int = 256
    llm_temperature: float = 0.2


@dataclass
class WebhookConfig:
    """Configuration for the webhook API server."""

    host: str = "127.0.0.1"
    port: int = 8000
    api_key: str = ""
    allow_move: bool = True
    max_batch_size: int = 50


@dataclass
class AppConfig:
    general: GeneralConfig
    logging: LoggingConfig
    classifier: ClassifierConfig
    imap: ImapConfig
    gmail: GmailConfig
    fast_parse: FastParseConfig
    mlx: MLXConfig
    webhook: WebhookConfig = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.webhook is None:
            self.webhook = WebhookConfig()


def _dataclass_from_dict(cls, data: dict):
    """Create a dataclass from a dict, ignoring unknown keys and using dataclass defaults for missing ones."""
    return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def load_config(path: Path) -> AppConfig:
    """Loads the application configuration from a TOML file."""
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)

            # Allow MODEL or MODEL_NAME from .env to override config.toml
            ollama_model = (
                os.getenv("MODEL") or os.getenv("MODEL_NAME") or data["general"].get("ollama_model")
            )
            if not ollama_model:
                raise ValueError("MODEL not found in environment or config file.")

            # API base is optional - required for Ollama, not needed for Gemini/others
            ollama_api_url = (
                os.getenv("OLLAMA_API_URL") or os.getenv("API_BASE") or data["general"].get("api_base", "")
            )

            imap_user = os.getenv("IMAP_USER", data["imap"].get("user"))
            if not imap_user:
                raise ValueError("IMAP_USER not found in environment or config file.")

            imap_password = os.getenv("IMAP_PASSWORD", data["imap"].get("password"))
            if not imap_password:
                raise ValueError("IMAP_PASSWORD not found in environment or config file.")

            fast_parse_config = _dataclass_from_dict(FastParseConfig, data.get("fast_parse", {}))
            mlx_config = _dataclass_from_dict(MLXConfig, data.get("mlx", {}))

            # Allow MLX_ENABLED env var to override config (for Docker/non-Apple-Silicon)
            mlx_enabled_env = os.getenv("MLX_ENABLED")
            if mlx_enabled_env is not None:
                mlx_config = MLXConfig(
                    enabled=mlx_enabled_env.lower() in ("true", "1", "yes"),
                    embedding_model=mlx_config.embedding_model,
                    score_threshold=mlx_config.score_threshold,
                    embeddings_file=mlx_config.embeddings_file,
                    llm_model=mlx_config.llm_model,
                    llm_confidence=mlx_config.llm_confidence,
                    llm_max_tokens=mlx_config.llm_max_tokens,
                    llm_temperature=mlx_config.llm_temperature,
                )

            webhook_config = _dataclass_from_dict(WebhookConfig, data.get("webhook", {}))
            # Resolve API key from environment
            webhook_api_key = os.getenv("WEBHOOK_API_KEY", webhook_config.api_key)
            if webhook_api_key.startswith("${"):
                webhook_api_key = ""
            webhook_config = WebhookConfig(
                host=webhook_config.host,
                port=webhook_config.port,
                api_key=webhook_api_key,
                allow_move=webhook_config.allow_move,
                max_batch_size=webhook_config.max_batch_size,
            )

            return AppConfig(
                general=GeneralConfig(
                    ollama_model=ollama_model,
                    api_base=ollama_api_url,
                    use_imap_folders_for_classification=data["general"].get(
                        "use_imap_folders_for_classification", True
                    ),
                ),
                logging=LoggingConfig(
                    level=data["logging"]["level"],
                    file=data["logging"]["file"],
                ),
                classifier=ClassifierConfig(
                    ai_confidence_threshold=data["classifier"]["ai_confidence_threshold"],
                    historical_confidence_threshold=data["classifier"]["historical_confidence_threshold"],
                    min_count=data["classifier"]["min_count"],
                    num_ctx=data["classifier"].get("num_ctx", 8192),
                ),
                imap=ImapConfig(
                    host=data["imap"]["host"],
                    user=imap_user,
                    password=imap_password,
                    use_gmail_extensions=data["imap"].get("use_gmail_extensions", False),
                ),
                gmail=GmailConfig(
                    credentials_file=data["gmail"]["credentials_file"],
                    token_file=data["gmail"]["token_file"],
                ),
                fast_parse=fast_parse_config,
                mlx=mlx_config,
                webhook=webhook_config,
            )
    except (FileNotFoundError, KeyError, tomllib.TOMLDecodeError, ValueError) as e:
        raise RuntimeError(f"Failed to load or parse config file: {e}") from e


def _validate_config(config: AppConfig) -> None:
    """Validate configuration values.

    Args:
        config: Configuration object to validate

    Raises:
        ValueError: If any configuration value is invalid
    """
    import re

    # Check email format
    email_regex = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    if not re.match(email_regex, config.imap.user):
        raise ValueError(f"Invalid email format: {config.imap.user}")

    # Check non-empty password
    if not config.imap.password:
        raise ValueError("IMAP password cannot be empty. Set IMAP_PASSWORD environment variable.")

    # Validate API base URL format (if provided and not empty)
    # Empty string is valid for non-Ollama providers like Gemini
    # Skip validation for template placeholders like ${VARIABLE}
    if (
        config.general.api_base
        and config.general.api_base.strip()
        and not config.general.api_base.startswith(("http://", "https://", "${"))
    ):
        raise ValueError(f"Invalid API base URL: {config.general.api_base}")

    # Validate thresholds (0-1 range)
    if not 0 <= config.classifier.historical_confidence_threshold <= 1:
        raise ValueError(
            f"Historical confidence threshold must be 0-1, "
            f"got: {config.classifier.historical_confidence_threshold}"
        )

    if not 0 <= config.classifier.ai_confidence_threshold <= 1:
        raise ValueError(
            f"AI confidence threshold must be 0-1, got: {config.classifier.ai_confidence_threshold}"
        )


# Load the global config
CONFIG = load_config(Path("config.toml"))
_validate_config(CONFIG)
