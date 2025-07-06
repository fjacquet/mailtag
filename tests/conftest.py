import logging

import pytest
from loguru import logger
from pytest_mock import MockerFixture


@pytest.fixture
def caplog(caplog):
    """Fixture to capture loguru logs."""

    class PropagateHandler(logging.Handler):
        def emit(self, record):
            logging.getLogger(record.name).handle(record)

    handler_id = logger.add(PropagateHandler(), format="{message}")
    yield caplog
    logger.remove(handler_id)


@pytest.fixture(autouse=True)
def mock_litellm_completion(mocker: MockerFixture):
    """
    Auto-mock litellm.completion for all tests to prevent real API calls.
    This is a safeguard against hanging tests.
    """
    mock = mocker.patch("litellm.completion")
    # Set a default return value for tests that don't specify one
    mock_choice = mocker.MagicMock()
    mock_choice.message.content = "Default/Category"
    mock_response = mocker.MagicMock()
    mock_response.choices = [mock_choice]
    mock.return_value = mock_response
    return mock
