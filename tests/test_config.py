from pathlib import Path

import pytest

from mailtag.config import (
    AppConfig,
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

[preclassification]
enabled = false
min_count = 5
confidence_threshold = 0.9
"""
    config_path = tmp_path / "config.toml"
    config_path.write_text(config_content)
    return config_path


def test_load_config_success(mock_config_file: Path):
    """Tests that the config is loaded correctly from a valid file."""
    config = load_config(mock_config_file)
    assert isinstance(config, AppConfig)
    assert config.general.ollama_model == "test-model"
    assert config.logging.level == "WARNING"
    assert not config.preclassification.enabled


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
