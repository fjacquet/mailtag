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
[logging]
level = "WARNING"
file = "/test/log.file"

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
    for env_var in ["IMAP_USER", "IMAP_PASSWORD"]:
        monkeypatch.delenv(env_var, raising=False)

    config = load_config(mock_config_file)
    assert isinstance(config, AppConfig)
    assert config.logging.level == "WARNING"
    assert config.imap.host == "imap.test.com"
    assert config.gmail.credentials_file == "creds.json"
    assert not hasattr(config, "gmail_imap")


def test_gmail_config_defaults(mock_config_file: Path, monkeypatch):
    """`[gmail]` gains its own per-account fields for the Gmail-through-the-API taxonomy flow."""
    for env_var in ["IMAP_USER", "IMAP_PASSWORD"]:
        monkeypatch.delenv(env_var, raising=False)

    config = load_config(mock_config_file)

    assert config.gmail.pending_archive_file == "db/pending_archive_gmail.json"
    assert config.gmail.junk_folder_name == "SPAM"


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
[logging]
level = "INFO"
# file, [imap] and [gmail] are missing
"""
    config_path = tmp_path / "incomplete.toml"
    config_path.write_text(incomplete_config)
    with pytest.raises(RuntimeError, match="Failed to load or parse config file"):
        load_config(config_path)


def test_validate_config_invalid_email():
    """Tests that ValueError is raised for invalid email format."""
    from mailtag.config import ImapConfig, LoggingConfig

    config = AppConfig(
        logging=LoggingConfig(level="INFO", file="test.log"),
        imap=ImapConfig(
            host="imap.test.com",
            user="invalid-email",  # Invalid email format
            password="password123",
        ),
        gmail=None,
        fast_parse=None,
        mlx=None,
    )
    with pytest.raises(ValueError, match="Invalid email format"):
        _validate_config(config)


def test_validate_config_empty_password():
    """Tests that ValueError is raised for empty password."""
    from mailtag.config import ImapConfig, LoggingConfig

    config = AppConfig(
        logging=LoggingConfig(level="INFO", file="test.log"),
        imap=ImapConfig(
            host="imap.test.com",
            user="test@example.com",
            password="",  # Empty password
        ),
        gmail=None,
        fast_parse=None,
        mlx=None,
    )
    with pytest.raises(ValueError, match="IMAP password cannot be empty"):
        _validate_config(config)


def test_validate_config_imap_user_placeholder_allowed():
    """Unsubstituted ${IMAP_USER} placeholder (e.g. in CI) must not fail validation."""
    from mailtag.config import ImapConfig, LoggingConfig

    config = AppConfig(
        logging=LoggingConfig(level="INFO", file="test.log"),
        imap=ImapConfig(
            host="imap.test.com",
            user="${IMAP_USER}",  # Unsubstituted placeholder - should be allowed
            password="${IMAP_PASSWORD}",
        ),
        gmail=None,
        fast_parse=None,
        mlx=None,
    )
    # Should not raise - unsubstituted placeholders are tolerated
    _validate_config(config)


def test_validate_config_valid():
    """Tests that validation passes for a valid config."""
    from mailtag.config import ImapConfig, LoggingConfig

    config = AppConfig(
        logging=LoggingConfig(level="INFO", file="test.log"),
        imap=ImapConfig(
            host="imap.test.com",
            user="test@example.com",
            password="password123",
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
    assert cfg.nomic_threshold == 0.70
    assert cfg.llm_batch_size == 8
    assert cfg.archive_after_days == 7
    assert cfg.pending_archive_file == "db/pending_archive.json"
    assert cfg.legacy_folders_file == "data/legacy_folders.json"


def test_app_config_without_taxonomy_gets_default():
    from mailtag.config import (
        AppConfig,
        FastParseConfig,
        GmailConfig,
        ImapConfig,
        LoggingConfig,
        MLXConfig,
        TaxonomyConfig,
    )

    cfg = AppConfig(
        logging=LoggingConfig(level="INFO", file=""),
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
    toml = tmp_path / "config.toml"
    toml.write_text(
        '[logging]\nlevel = "INFO"\nfile = "x.log"\n'
        '[imap]\nhost = "h"\n'
        '[gmail]\ncredentials_file = "c"\ntoken_file = "t"\n'
        "[taxonomy]\nnomic_threshold = 0.72\n",
        encoding="utf-8",
    )
    cfg = load_config(toml)
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
    assert config.pending_archive_file is None and config.junk_folder_name is None


def test_old_sections_are_ignored(tmp_path, monkeypatch):
    from mailtag.config import load_config

    monkeypatch.delenv("MODEL", raising=False)
    monkeypatch.delenv("MODEL_NAME", raising=False)
    monkeypatch.setenv("IMAP_USER", "me@example.com")
    monkeypatch.setenv("IMAP_PASSWORD", "secret")
    path = tmp_path / "config.toml"
    path.write_text(
        """
[general]
ollama_model = "x"
[classifier]
min_count = 5
[logging]
level = "INFO"
file = "logs/mailtag.log"
[imap]
host = "mail.example.com"
use_gmail_extensions = false
[gmail]
credentials_file = "c.json"
token_file = "t.json"
folder_cache_file = "data/gmail_labels.json"
[fast_parse]
folder_cache_ttl_hours = 24
unclassified_folder_name = "Unclassified"
[taxonomy]
enabled = true
nomic_threshold = 0.7
""",
        encoding="utf-8",
    )

    cfg = load_config(path)

    assert cfg.imap.user == "me@example.com"
    assert cfg.gmail.junk_folder_name == "SPAM"
    assert cfg.taxonomy.nomic_threshold == 0.7
    assert not hasattr(cfg, "general")


def test_gmail_section_missing_token_file_is_a_config_error(tmp_path, monkeypatch):
    from mailtag.config import load_config

    monkeypatch.setenv("IMAP_USER", "me@example.com")
    monkeypatch.setenv("IMAP_PASSWORD", "secret")
    path = tmp_path / "config.toml"
    path.write_text(
        """
[logging]
level = "INFO"
file = "logs/mailtag.log"
[imap]
host = "mail.example.com"
[gmail]
credentials_file = "c.json"
""",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="Failed to load or parse config file"):
        load_config(path)


def test_classifier_and_laya_defaults():
    from mailtag.config import ClassifierConfig, LayaConfig, LayaThresholds

    assert ClassifierConfig().mode == "mlx"
    cfg = LayaConfig()
    assert cfg.routing == "router"
    assert cfg.device == "auto"
    assert cfg.batch_size == 16
    assert cfg.head_max_len == 512
    assert cfg.max_len == 1024
    assert cfg.rotations is False
    assert cfg.body_chars == 1500
    assert cfg.calibration == "data/laya_neutral_calibration.json"
    assert cfg.english == LayaThresholds(classify_threshold=1.01, learn_threshold=1.01)
    assert cfg.multilingual == LayaThresholds(classify_threshold=1.01, learn_threshold=1.01)


def test_laya_thresholds_by_checkpoint():
    from mailtag.config import LayaConfig, LayaThresholds

    cfg = LayaConfig(english=LayaThresholds(0.5, 0.9), multilingual=LayaThresholds(0.6, 0.95))
    assert cfg.thresholds("english") == LayaThresholds(0.5, 0.9)
    assert cfg.thresholds("multilingual") == LayaThresholds(0.6, 0.95)
    assert cfg.thresholds("typed-decisions") == LayaThresholds(0.6, 0.95)


def test_unknown_mode_or_routing_is_refused():
    from mailtag.config import ClassifierConfig, LayaConfig

    with pytest.raises(ValueError, match="mode"):
        ClassifierConfig(mode="gemma")
    with pytest.raises(ValueError, match="routing"):
        LayaConfig(routing="english")


def test_app_config_without_classifier_or_laya_gets_defaults():
    from mailtag.config import (
        AppConfig,
        ClassifierConfig,
        FastParseConfig,
        GmailConfig,
        ImapConfig,
        LayaConfig,
        LoggingConfig,
        MLXConfig,
    )

    cfg = AppConfig(
        logging=LoggingConfig(level="INFO", file=""),
        imap=ImapConfig(host="", user="", password=""),
        gmail=GmailConfig(credentials_file="", token_file=""),
        fast_parse=FastParseConfig(),
        mlx=MLXConfig(enabled=False),
    )
    assert cfg.classifier == ClassifierConfig()
    assert cfg.laya == LayaConfig()


def test_load_config_reads_classifier_and_laya(tmp_path, monkeypatch):
    from mailtag.config import LayaThresholds, load_config

    monkeypatch.setenv("IMAP_USER", "user@example.com")
    monkeypatch.setenv("IMAP_PASSWORD", "secret")
    toml = tmp_path / "config.toml"
    toml.write_text(
        """
[logging]
level = "INFO"
file = ""

[imap]
host = "imap.test.com"

[gmail]
credentials_file = "c.json"
token_file = "t.json"

[classifier]
mode = "laya"

[laya]
routing = "multilingual"
batch_size = 4
english = { classify_threshold = 0.7, learn_threshold = 0.95 }
multilingual = { classify_threshold = 0.8 }
"""
    )

    cfg = load_config(toml)

    assert cfg.classifier.mode == "laya"
    assert cfg.laya.routing == "multilingual"
    assert cfg.laya.batch_size == 4
    assert cfg.laya.english == LayaThresholds(0.7, 0.95)
    assert cfg.laya.multilingual == LayaThresholds(0.8, 1.01)


def test_load_config_refuses_unknown_mode(tmp_path, monkeypatch):
    from mailtag.config import load_config

    monkeypatch.setenv("IMAP_USER", "user@example.com")
    monkeypatch.setenv("IMAP_PASSWORD", "secret")
    toml = tmp_path / "config.toml"
    toml.write_text(
        '[logging]\nlevel = "INFO"\nfile = ""\n[imap]\nhost = "h"\n'
        '[gmail]\ncredentials_file = "c"\ntoken_file = "t"\n[classifier]\nmode = "gemma"\n'
    )

    with pytest.raises(RuntimeError, match="mode"):
        load_config(toml)


def test_logreg_defaults_and_mode():
    from mailtag.config import ClassifierConfig, LogRegConfig

    assert ClassifierConfig(mode="logreg").mode == "logreg"
    cfg = LogRegConfig()
    assert cfg.model_file == "data/taxonomy_logreg.npz"
    assert cfg.C == 100.0
    assert cfg.classify_threshold == 1.01
    assert cfg.learn_threshold == 1.01


def test_app_config_without_logreg_gets_defaults():
    from mailtag.config import (
        AppConfig,
        FastParseConfig,
        GmailConfig,
        ImapConfig,
        LoggingConfig,
        LogRegConfig,
        MLXConfig,
    )

    cfg = AppConfig(
        logging=LoggingConfig(level="INFO", file=""),
        imap=ImapConfig(host="", user="", password=""),
        gmail=GmailConfig(credentials_file="", token_file=""),
        fast_parse=FastParseConfig(),
        mlx=MLXConfig(enabled=False),
    )
    assert cfg.logreg == LogRegConfig()


def test_load_config_reads_logreg(tmp_path, monkeypatch):
    from mailtag.config import load_config

    monkeypatch.setenv("IMAP_USER", "user@example.com")
    monkeypatch.setenv("IMAP_PASSWORD", "secret")
    toml = tmp_path / "config.toml"
    toml.write_text(
        """
[logging]
level = "INFO"
file = ""

[imap]
host = "imap.test.com"

[gmail]
credentials_file = "c.json"
token_file = "t.json"

[classifier]
mode = "logreg"

[logreg]
model_file = "m.npz"
C = 10.0
classify_threshold = 0.9
"""
    )

    cfg = load_config(toml)

    assert cfg.classifier.mode == "logreg"
    assert cfg.logreg.model_file == "m.npz"
    assert cfg.logreg.C == 10.0
    assert cfg.logreg.classify_threshold == 0.9
    assert cfg.logreg.learn_threshold == 1.01


def test_logreg_per_sender_default_and_toml(tmp_path, monkeypatch):
    from mailtag.config import LogRegConfig, load_config

    assert LogRegConfig().per_sender == 10
    monkeypatch.setenv("IMAP_USER", "user@example.com")
    monkeypatch.setenv("IMAP_PASSWORD", "secret")
    toml = tmp_path / "config.toml"
    toml.write_text(
        """
[logging]
level = "INFO"
file = ""

[imap]
host = "imap.test.com"

[gmail]
credentials_file = "c.json"
token_file = "t.json"

[logreg]
per_sender = 5
"""
    )

    assert load_config(toml).logreg.per_sender == 5
