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
    batch_size: int
    folder_cache_ttl_hours: int
    unclassified_folder_name: str
    junk_folder_name: str
    max_retries: int = 3
    retry_delay: float = 1.0
    retry_backoff: float = 2.0
    retry_jitter: float = 0.1
    metrics_enabled: bool = True
    metrics_log_level: str = "DEBUG"
    metrics_log_interval_minutes: int = 10


@dataclass
class AppConfig:
    general: GeneralConfig
    logging: LoggingConfig
    classifier: ClassifierConfig
    imap: ImapConfig
    gmail: GmailConfig
    fast_parse: FastParseConfig


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

            fast_parse_data = data.get("fast_parse", {})
            fast_parse_config = FastParseConfig(
                batch_size=fast_parse_data.get("batch_size", 500),
                folder_cache_ttl_hours=fast_parse_data.get("folder_cache_ttl_hours", 24),
                unclassified_folder_name=fast_parse_data.get("unclassified_folder_name", "Unclassified"),
                junk_folder_name=fast_parse_data.get("junk_folder_name", "Junk"),
                max_retries=fast_parse_data.get("max_retries", 3),
                retry_delay=fast_parse_data.get("retry_delay", 1.0),
                retry_backoff=fast_parse_data.get("retry_backoff", 2.0),
                retry_jitter=fast_parse_data.get("retry_jitter", 0.1),
                metrics_enabled=fast_parse_data.get("metrics_enabled", True),
                metrics_log_level=fast_parse_data.get("metrics_log_level", "DEBUG"),
                metrics_log_interval_minutes=fast_parse_data.get("metrics_log_interval_minutes", 10),
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
            )
    except (FileNotFoundError, KeyError, tomllib.TOMLDecodeError, ValueError) as e:
        raise RuntimeError(f"Failed to load or parse config file: {e}") from e


# Load the global config
try:
    CONFIG = load_config(Path("config.toml"))
except RuntimeError as e:
    print(f"Error: {e}")
    # Provide a default/fallback config or exit
    CONFIG = AppConfig(
        general=GeneralConfig(
            ollama_model="gemma3",
            api_base="http://localhost:11434",
            use_imap_folders_for_classification=True,
        ),
        logging=LoggingConfig(level="INFO", file="mailtag.log"),
        classifier=ClassifierConfig(
            ai_confidence_threshold=0.7,
            historical_confidence_threshold=0.9,
            min_count=3,
            num_ctx=8192,
        ),
        imap=ImapConfig(
            host="imap.example.com",
            user="user@example.com",
            password="",
            use_gmail_extensions=False,
        ),
        gmail=GmailConfig(
            credentials_file="credentials.json",
            token_file="token.json",
        ),
        fast_parse=FastParseConfig(
            batch_size=500,
            folder_cache_ttl_hours=24,
            unclassified_folder_name="Unclassified",
            junk_folder_name="Junk",
        ),
    )
