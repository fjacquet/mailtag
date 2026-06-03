from pathlib import Path

import pytest

from mailtag.config import (
    AppConfig,
    _validate_config,
    load_config,
)


@pytest.fixture
def mock_config_file(tmp_path: Path) -> Path:
    """Creates a mock config.toml file."""
    config_content = """
[general]
ollama_model = "test-model"
api_base = "http://test-host:1234"

[logging]
level = "WARNING"
file = "/test/log.file"

[classifier]
ai_confidence_threshold = 0.7
historical_confidence_threshold = 0.9
min_count = 3

[preclassification]
enabled = false
min_count = 5
confidence_threshold = 0.9

[imap]
host = "imap.test.com"
user = "test@user.com"
password = "password"

[gmail]
credentials_file = "creds.json"
token_file = "token.json"
"""
    config_path = tmp_path / "config.toml"
    config_path.write_text(config_content)
    return config_path


def test_load_config_success(mock_config_file: Path, monkeypatch):
    """Tests that the config is loaded correctly from a valid file."""
    # Clear environment variables that override config file
    for env_var in ["MODEL", "MODEL_NAME", "OLLAMA_API_URL", "API_BASE", "IMAP_USER", "IMAP_PASSWORD"]:
        monkeypatch.delenv(env_var, raising=False)

    config = load_config(mock_config_file)
    assert isinstance(config, AppConfig)
    assert config.general.ollama_model == "test-model"
    assert config.logging.level == "WARNING"
    assert config.classifier.ai_confidence_threshold == 0.7
    assert config.imap.host == "imap.test.com"
    assert config.gmail.credentials_file == "creds.json"


def test_load_config_file_not_found():
    """Tests that a RuntimeError is raised when the config file is not found."""
    with pytest.raises(RuntimeError, match="Failed to load or parse config file"):
        load_config(Path("non_existent_file.toml"))


def test_load_config_invalid_toml(tmp_path: Path):
    """Tests that a RuntimeError is raised for an invalid TOML file."""
    invalid_config_path = tmp_path / "invalid.toml"
    invalid_config_path.write_text("this is not valid toml")
    with pytest.raises(RuntimeError, match="Failed to load or parse config file"):
        load_config(invalid_config_path)


def test_load_config_missing_key(tmp_path: Path):
    """Tests that a RuntimeError is raised if a key is missing."""
    incomplete_config = """
[general]
ollama_model = "test-model"
# api_base is missing
"""
    config_path = tmp_path / "incomplete.toml"
    config_path.write_text(incomplete_config)
    with pytest.raises(RuntimeError, match="Failed to load or parse config file"):
        load_config(config_path)


def test_validate_config_invalid_email():
    """Tests that ValueError is raised for invalid email format."""
    from mailtag.config import ClassifierConfig, GeneralConfig, ImapConfig, LoggingConfig

    config = AppConfig(
        general=GeneralConfig(
            ollama_model="test-model",
            api_base="http://localhost:11434",
        ),
        logging=LoggingConfig(level="INFO", file="test.log"),
        classifier=ClassifierConfig(
            ai_confidence_threshold=0.85,
            historical_confidence_threshold=0.9,
            min_count=3,
            num_ctx=8192,
        ),
        imap=ImapConfig(
            host="imap.test.com",
            user="invalid-email",  # Invalid email format
            password="password123",
            use_gmail_extensions=False,
        ),
        gmail=None,
        fast_parse=None,
        mlx=None,
    )
    with pytest.raises(ValueError, match="Invalid email format"):
        _validate_config(config)


def test_validate_config_empty_password():
    """Tests that ValueError is raised for empty password."""
    from mailtag.config import ClassifierConfig, GeneralConfig, ImapConfig, LoggingConfig

    config = AppConfig(
        general=GeneralConfig(
            ollama_model="test-model",
            api_base="http://localhost:11434",
        ),
        logging=LoggingConfig(level="INFO", file="test.log"),
        classifier=ClassifierConfig(
            ai_confidence_threshold=0.85,
            historical_confidence_threshold=0.9,
            min_count=3,
            num_ctx=8192,
        ),
        imap=ImapConfig(
            host="imap.test.com",
            user="test@example.com",
            password="",  # Empty password
            use_gmail_extensions=False,
        ),
        gmail=None,
        fast_parse=None,
        mlx=None,
    )
    with pytest.raises(ValueError, match="IMAP password cannot be empty"):
        _validate_config(config)


def test_validate_config_invalid_api_base():
    """Tests that ValueError is raised for invalid API base URL."""
    from mailtag.config import ClassifierConfig, GeneralConfig, ImapConfig, LoggingConfig

    config = AppConfig(
        general=GeneralConfig(
            ollama_model="test-model",
            api_base="not-a-url",  # Invalid URL (no http/https)
        ),
        logging=LoggingConfig(level="INFO", file="test.log"),
        classifier=ClassifierConfig(
            ai_confidence_threshold=0.85,
            historical_confidence_threshold=0.9,
            min_count=3,
            num_ctx=8192,
        ),
        imap=ImapConfig(
            host="imap.test.com",
            user="test@example.com",
            password="password123",
            use_gmail_extensions=False,
        ),
        gmail=None,
        fast_parse=None,
        mlx=None,
    )
    with pytest.raises(ValueError, match="Invalid API base URL"):
        _validate_config(config)


def test_validate_config_invalid_threshold():
    """Tests that ValueError is raised for thresholds outside 0-1 range."""
    from mailtag.config import ClassifierConfig, GeneralConfig, ImapConfig, LoggingConfig

    config = AppConfig(
        general=GeneralConfig(
            ollama_model="test-model",
            api_base="http://localhost:11434",
        ),
        logging=LoggingConfig(level="INFO", file="test.log"),
        classifier=ClassifierConfig(
            ai_confidence_threshold=1.5,  # Invalid: >1
            historical_confidence_threshold=0.9,
            min_count=3,
            num_ctx=8192,
        ),
        imap=ImapConfig(
            host="imap.test.com",
            user="test@example.com",
            password="password123",
            use_gmail_extensions=False,
        ),
        gmail=None,
        fast_parse=None,
        mlx=None,
    )
    with pytest.raises(ValueError, match="AI confidence threshold must be 0-1"):
        _validate_config(config)


def test_validate_config_template_placeholder_allowed():
    """Tests that template placeholders like ${VAR} are allowed in API base."""
    from mailtag.config import ClassifierConfig, GeneralConfig, ImapConfig, LoggingConfig

    config = AppConfig(
        general=GeneralConfig(
            ollama_model="test-model",
            api_base="${OLLAMA_API_URL}",  # Template placeholder - should be allowed
        ),
        logging=LoggingConfig(level="INFO", file="test.log"),
        classifier=ClassifierConfig(
            ai_confidence_threshold=0.85,
            historical_confidence_threshold=0.9,
            min_count=3,
            num_ctx=8192,
        ),
        imap=ImapConfig(
            host="imap.test.com",
            user="test@example.com",
            password="password123",
            use_gmail_extensions=False,
        ),
        gmail=None,
        fast_parse=None,
        mlx=None,
    )
    # Should not raise any exception - template placeholders are allowed
    _validate_config(config)


def test_validate_config_imap_user_placeholder_allowed():
    """Unsubstituted ${IMAP_USER} placeholder (e.g. in CI) must not fail validation."""
    from mailtag.config import ClassifierConfig, GeneralConfig, ImapConfig, LoggingConfig

    config = AppConfig(
        general=GeneralConfig(ollama_model="test-model", api_base=""),
        logging=LoggingConfig(level="INFO", file="test.log"),
        classifier=ClassifierConfig(
            ai_confidence_threshold=0.85,
            historical_confidence_threshold=0.9,
            min_count=3,
            num_ctx=8192,
        ),
        imap=ImapConfig(
            host="imap.test.com",
            user="${IMAP_USER}",  # Unsubstituted placeholder - should be allowed
            password="${IMAP_PASSWORD}",
            use_gmail_extensions=False,
        ),
        gmail=None,
        fast_parse=None,
        mlx=None,
    )
    # Should not raise - unsubstituted placeholders are tolerated
    _validate_config(config)


def test_validate_config_valid():
    """Tests that validation passes for a valid config."""
    from mailtag.config import ClassifierConfig, GeneralConfig, ImapConfig, LoggingConfig

    config = AppConfig(
        general=GeneralConfig(
            ollama_model="test-model",
            api_base="http://localhost:11434",
        ),
        logging=LoggingConfig(level="INFO", file="test.log"),
        classifier=ClassifierConfig(
            ai_confidence_threshold=0.85,
            historical_confidence_threshold=0.9,
            min_count=3,
            num_ctx=8192,
        ),
        imap=ImapConfig(
            host="imap.test.com",
            user="test@example.com",
            password="password123",
            use_gmail_extensions=False,
        ),
        gmail=None,
        fast_parse=None,
        mlx=None,
    )
    # Should not raise any exception
    _validate_config(config)
