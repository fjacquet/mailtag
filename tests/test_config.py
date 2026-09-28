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
    assert not hasattr(config, "gmail_imap")


def test_gmail_config_defaults(mock_config_file: Path, monkeypatch):
    """`[gmail]` gains four fields for the Gmail-through-the-API taxonomy flow."""
    for env_var in ["MODEL", "MODEL_NAME", "OLLAMA_API_URL", "API_BASE", "IMAP_USER", "IMAP_PASSWORD"]:
        monkeypatch.delenv(env_var, raising=False)

    config = load_config(mock_config_file)

    assert config.gmail.pending_archive_file == "db/pending_archive_gmail.json"
    assert config.gmail.folder_cache_file == "data/gmail_labels.json"
    assert config.gmail.junk_folder_name == "SPAM"
    assert config.gmail.use_gmail_extensions is False


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


def test_taxonomy_config_defaults():
    from mailtag.config import TaxonomyConfig

    cfg = TaxonomyConfig()
    assert cfg.enabled is False
    assert cfg.nomic_threshold == 0.70
    assert cfg.llm_batch_size == 8
    assert cfg.archive_after_days == 7
    assert cfg.pending_archive_file == "db/pending_archive.json"
    assert cfg.legacy_folders_file == "data/legacy_folders.json"


def test_app_config_without_taxonomy_gets_default():
    from mailtag.config import (
        AppConfig,
        ClassifierConfig,
        FastParseConfig,
        GeneralConfig,
        GmailConfig,
        ImapConfig,
        LoggingConfig,
        MLXConfig,
        TaxonomyConfig,
    )

    cfg = AppConfig(
        general=GeneralConfig(ollama_model="m", api_base=""),
        logging=LoggingConfig(level="INFO", file=""),
        classifier=ClassifierConfig(
            ai_confidence_threshold=0.7, historical_confidence_threshold=0.9, min_count=3
        ),
        imap=ImapConfig(host="", user="", password=""),
        gmail=GmailConfig(credentials_file="", token_file=""),
        fast_parse=FastParseConfig(),
        mlx=MLXConfig(enabled=False),
    )
    assert cfg.taxonomy == TaxonomyConfig()


def test_load_config_reads_taxonomy_section(tmp_path, monkeypatch):
    from mailtag.config import load_config

    monkeypatch.setenv("IMAP_USER", "user@example.com")
    monkeypatch.setenv("IMAP_PASSWORD", "secret")
    monkeypatch.setenv("MODEL", "test-model")
    toml = tmp_path / "config.toml"
    toml.write_text(
        '[general]\napi_base = ""\n'
        '[logging]\nlevel = "INFO"\nfile = "x.log"\n'
        "[classifier]\nai_confidence_threshold = 0.7\nhistorical_confidence_threshold = 0.9\nmin_count = 3\n"
        '[imap]\nhost = "h"\n'
        '[gmail]\ncredentials_file = "c"\ntoken_file = "t"\n'
        "[taxonomy]\nenabled = true\nnomic_threshold = 0.72\n",
        encoding="utf-8",
    )
    cfg = load_config(toml)
    assert cfg.taxonomy.enabled is True
    assert cfg.taxonomy.nomic_threshold == 0.72
    assert cfg.taxonomy.llm_batch_size == 8


def test_taxonomy_signal_defaults():
    from mailtag.config import TaxonomyConfig

    cfg = TaxonomyConfig()
    assert cfg.taxonomy_db_dir == "db/taxonomy"
    assert cfg.centroids_file == "data/taxonomy_centroids.npz"
    assert cfg.learn_min_agreements == 2
    assert cfg.domain_min_purity == 0.90
    assert cfg.sender_min_mails == 2


def test_own_addresses_default_empty():
    from mailtag.config import TaxonomyConfig

    assert TaxonomyConfig().own_addresses == []


def test_imap_config_defaults_keep_infomaniak_behaviour():
    from mailtag.config import ImapConfig

    config = ImapConfig(host="h", user="u", password="p")
    assert config.folder_cache_file == "data/imap_folders.json"
    assert config.pending_archive_file is None and config.junk_folder_name is None
