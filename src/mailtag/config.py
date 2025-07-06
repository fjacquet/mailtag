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


@dataclass
class ClassifierConfig:
    ai_confidence_threshold: float
    historical_confidence_threshold: float
    min_count: int


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

            ollama_api_url = os.getenv("OLLAMA_API_URL", data["general"].get("api_base"))
            if not ollama_api_url:
                raise ValueError("OLLAMA_API_URL not found in environment or config file.")

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
            )

            return AppConfig(
                general=GeneralConfig(
                    ollama_model=data["general"]["ollama_model"],
                    api_base=ollama_api_url,
                ),
                logging=LoggingConfig(
                    level=data["logging"]["level"],
                    file=data["logging"]["file"],
                ),
                classifier=ClassifierConfig(
                    ai_confidence_threshold=data["classifier"]["ai_confidence_threshold"],
                    historical_confidence_threshold=data["classifier"]["historical_confidence_threshold"],
                    min_count=data["classifier"]["min_count"],
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
        ),
        logging=LoggingConfig(level="INFO", file="mailtag.log"),
        classifier=ClassifierConfig(
            ai_confidence_threshold=0.7,
            historical_confidence_threshold=0.9,
            min_count=3,
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
        ),
    )
