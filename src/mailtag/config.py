import dataclasses
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass
class LoggingConfig:
    level: str
    file: str


@dataclass
class ImapConfig:
    host: str
    user: str
    password: str
    # Per-account overrides (the Gmail account sets them; None = the global setting)
    pending_archive_file: str | None = None
    junk_folder_name: str | None = None


@dataclass
class GmailConfig:
    credentials_file: str
    token_file: str
    # Gmail through the API (docs/superpowers/specs/2026-09-28-gmail-api-taxonomy-design.md)
    pending_archive_file: str | None = "db/pending_archive_gmail.json"
    junk_folder_name: str | None = "SPAM"


@dataclass
class FastParseConfig:
    batch_size: int = 500
    junk_folder_name: str = "Junk"


@dataclass
class MLXConfig:
    """Configuration for MLX-based classification (Apple Silicon optimized)."""

    enabled: bool = True
    # Semantic Router (Signal 5) - embedding-based classification
    embedding_model: str = "nomic-ai/nomic-embed-text-v1.5"
    # Gemma (Signal 6) - answers by category number
    llm_model: str = "mlx-community/gemma-4-e4b-it-OptiQ-4bit"


@dataclass
class ClassifierConfig:
    """Pass 3 model: "mlx" (nomic + Gemma) or "laya" (docs/superpowers/specs/2026-10-01-laya-*)."""

    mode: str = "mlx"

    def __post_init__(self):
        if self.mode not in ("mlx", "laya"):
            raise ValueError(f"[classifier] mode must be 'mlx' or 'laya', got {self.mode!r}")


@dataclass
class LayaThresholds:
    """Per-checkpoint thresholds on Laya's answer_confidence (1.01 = never)."""

    classify_threshold: float = 1.01
    learn_threshold: float = 1.01


@dataclass
class LayaConfig:
    """Laya classifier (mode = "laya"); thresholds come from `scripts/eval_embeddings.py laya`."""

    routing: str = "router"  # "router" (language → english/multilingual) | "multilingual"
    device: str = "auto"  # auto | mps | cpu
    batch_size: int = 16
    head_max_len: int = 512
    max_len: int = 1024
    rotations: bool = False
    body_chars: int = 1500
    calibration: str = "data/laya_neutral_calibration.json"  # "" = the checkpoints' shipped temperatures
    english: LayaThresholds = field(default_factory=LayaThresholds)
    multilingual: LayaThresholds = field(default_factory=LayaThresholds)

    def __post_init__(self):
        if self.routing not in ("router", "multilingual"):
            raise ValueError(f"[laya] routing must be 'router' or 'multilingual', got {self.routing!r}")

    def thresholds(self, checkpoint: str) -> LayaThresholds:
        """Thresholds of `checkpoint`; anything but "english" is the multilingual checkpoint."""
        return self.english if checkpoint == "english" else self.multilingual


@dataclass
class WebhookConfig:
    """Configuration for the webhook API server."""

    host: str = "127.0.0.1"
    port: int = 8000
    api_key: str = ""
    allow_move: bool = True
    max_batch_size: int = 50


@dataclass
class TaxonomyConfig:
    """19-category taxonomy with action folders (see docs/superpowers/specs/2026-09-27-*)."""

    nomic_threshold: float = 0.70
    llm_batch_size: int = 8
    archive_after_days: int = 7
    pending_archive_file: str = "db/pending_archive.json"
    legacy_folders_file: str = "data/legacy_folders.json"
    taxonomy_db_dir: str = "db/taxonomy"
    centroids_file: str = "data/taxonomy_centroids.npz"
    learn_min_agreements: int = 2
    domain_min_purity: float = 0.90
    sender_min_mails: int = 2
    # The owner's addresses: their mails say nothing about the category (NAS alerts, notes to self)
    own_addresses: list[str] = field(default_factory=list)


@dataclass
class AppConfig:
    logging: LoggingConfig
    imap: ImapConfig
    gmail: GmailConfig
    fast_parse: FastParseConfig
    mlx: MLXConfig
    webhook: WebhookConfig = None  # type: ignore[assignment]
    taxonomy: TaxonomyConfig = None  # type: ignore[assignment]
    classifier: ClassifierConfig = None  # type: ignore[assignment]
    laya: LayaConfig = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.webhook is None:
            self.webhook = WebhookConfig()
        if self.taxonomy is None:
            self.taxonomy = TaxonomyConfig()
        if self.classifier is None:
            self.classifier = ClassifierConfig()
        if self.laya is None:
            self.laya = LayaConfig()


def _dataclass_from_dict(cls, data: dict):
    """Create a dataclass from a dict, ignoring unknown keys and using dataclass defaults for missing ones."""
    return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def _laya_config(data: dict) -> LayaConfig:
    """`[laya]`, with its per-checkpoint threshold tables turned into LayaThresholds."""
    thresholds = {
        name: _dataclass_from_dict(LayaThresholds, data[name])
        for name in ("english", "multilingual")
        if name in data
    }
    return _dataclass_from_dict(LayaConfig, {**data, **thresholds})


def load_config(path: Path) -> AppConfig:
    """Loads the application configuration from a TOML file (unknown keys are ignored)."""
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)

        imap_user = os.getenv("IMAP_USER", data["imap"].get("user"))
        if not imap_user:
            raise ValueError("IMAP_USER not found in environment or config file.")
        imap_password = os.getenv("IMAP_PASSWORD", data["imap"].get("password"))
        if not imap_password:
            raise ValueError("IMAP_PASSWORD not found in environment or config file.")

        mlx_config = _dataclass_from_dict(MLXConfig, data.get("mlx", {}))
        # Allow MLX_ENABLED env var to override config (for Docker/non-Apple-Silicon)
        mlx_enabled_env = os.getenv("MLX_ENABLED")
        if mlx_enabled_env is not None:
            mlx_config = dataclasses.replace(
                mlx_config, enabled=mlx_enabled_env.lower() in ("true", "1", "yes")
            )

        webhook_config = _dataclass_from_dict(WebhookConfig, data.get("webhook", {}))
        webhook_api_key = os.getenv("WEBHOOK_API_KEY", webhook_config.api_key)
        if webhook_api_key.startswith("${"):
            webhook_api_key = ""
        webhook_config = dataclasses.replace(webhook_config, api_key=webhook_api_key)

        return AppConfig(
            logging=LoggingConfig(level=data["logging"]["level"], file=data["logging"]["file"]),
            imap=ImapConfig(host=data["imap"]["host"], user=imap_user, password=imap_password),
            gmail=_dataclass_from_dict(GmailConfig, data["gmail"]),
            fast_parse=_dataclass_from_dict(FastParseConfig, data.get("fast_parse", {})),
            mlx=mlx_config,
            webhook=webhook_config,
            taxonomy=_dataclass_from_dict(TaxonomyConfig, data.get("taxonomy", {})),
            classifier=_dataclass_from_dict(ClassifierConfig, data.get("classifier", {})),
            laya=_laya_config(data.get("laya", {})),
        )
    except (FileNotFoundError, KeyError, TypeError, tomllib.TOMLDecodeError, ValueError) as e:
        raise RuntimeError(f"Failed to load or parse config file: {e}") from e


def _validate_config(config: AppConfig) -> None:
    """Validate configuration values.

    Raises:
        ValueError: If any configuration value is invalid
    """
    import re

    # Check email format. Skip unsubstituted template placeholders like
    # ${IMAP_USER} (e.g. in CI where the env var is unset).
    email_regex = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    if not config.imap.user.startswith("${") and not re.match(email_regex, config.imap.user):
        raise ValueError(f"Invalid email format: {config.imap.user}")

    if not config.imap.password:
        raise ValueError("IMAP password cannot be empty. Set IMAP_PASSWORD environment variable.")


# Load the global config
CONFIG = load_config(Path("config.toml"))
_validate_config(CONFIG)
