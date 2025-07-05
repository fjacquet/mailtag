import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class LoggingConfig:
    level: str
    file: str


@dataclass
class GeneralConfig:
    ollama_model: str
    api_base: str


@dataclass
class PreclassificationConfig:
    enabled: bool
    min_count: int
    confidence_threshold: float


@dataclass
class AppConfig:
    general: GeneralConfig
    logging: LoggingConfig
    preclassification: PreclassificationConfig


def load_config(path: Path) -> AppConfig:
    """Loads the application configuration from a TOML file."""
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
            return AppConfig(
                general=GeneralConfig(
                    ollama_model=data["general"]["ollama_model"],
                    api_base=data["general"]["api_base"],
                ),
                logging=LoggingConfig(
                    level=data["logging"]["level"],
                    file=data["logging"]["file"],
                ),
                preclassification=PreclassificationConfig(
                    enabled=data["preclassification"]["enabled"],
                    min_count=data["preclassification"]["min_count"],
                    confidence_threshold=data["preclassification"]["confidence_threshold"],
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
            ollama_model="gemma3",
            api_base="http://localhost:11434",
        ),
        logging=LoggingConfig(level="INFO", file="mailtag.log"),
        preclassification=PreclassificationConfig(enabled=True, min_count=3, confidence_threshold=0.8),
    )
