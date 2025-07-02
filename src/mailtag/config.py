import tomllib
from pathlib import Path
from dataclasses import dataclass


@dataclass
class LoggingConfig:
    level: str
    file: str


@dataclass
class GeneralConfig:
    mail_dir: Path
    ollama_model: str
    temp_db_prefix: str


@dataclass
class AppConfig:
    general: GeneralConfig
    logging: LoggingConfig


def load_config(path: Path) -> AppConfig:
    """Loads the application configuration from a TOML file."""
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
            return AppConfig(
                general=GeneralConfig(
                    mail_dir=Path(data["general"]["mail_dir"]).expanduser(),
                    ollama_model=data["general"]["ollama_model"],
                    temp_db_prefix=data["general"]["temp_db_prefix"],
                ),
                logging=LoggingConfig(
                    level=data["logging"]["level"],
                    file=data["logging"]["file"],
                ),
            )
    except (FileNotFoundError, KeyError, tomllib.TOMLDecodeError) as e:
        raise RuntimeError(f"Failed to load or parse config file: {e}") from e


# Load the global config
try:
    CONFIG = load_config(Path("config.toml"))
except RuntimeError as e:
    print(f"Error: {e}")
    # Provide a default/fallback config or exit
    CONFIG = AppConfig(
        general=GeneralConfig(
            mail_dir=Path.home() / "Library/Mail",
            ollama_model="gemma3",
            temp_db_prefix="EnvelopeIndex_copy",
        ),
        logging=LoggingConfig(level="INFO", file="mailtag.log"),
    )
