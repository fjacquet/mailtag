import logging

import pytest
from loguru import logger
from pytest_mock import MockerFixture

from tests.mock_gmail_service import MockGmailService
from tests.mock_imap_client import MockImapClient


@pytest.fixture
def caplog(caplog):
    """Fixture to capture loguru logs."""

    class PropagateHandler(logging.Handler):
        def emit(self, record):
            logging.getLogger(record.name).handle(record)

    handler_id = logger.add(PropagateHandler(), format="{message}")
    yield caplog
    logger.remove(handler_id)


# NOTE: litellm is no longer used (replaced by MLX), so this fixture is disabled
# @pytest.fixture(autouse=True)
# def mock_litellm_completion(mocker: MockerFixture):
#     """
#     Auto-mock litellm.completion for all tests to prevent real API calls.
#     This is a safeguard against hanging tests.
#     """
#     mock = mocker.patch("litellm.completion")
#     # Set a default return value for tests that don't specify one
#     mock_choice = mocker.MagicMock()
#     mock_choice.message.content = "Default/Category"
#     mock_response = mocker.MagicMock()
#     mock_response.choices = [mock_choice]
#     mock.return_value = mock_response
#     return mock


@pytest.fixture
def mock_imap_client(mocker: MockerFixture) -> MockImapClient:
    """Fixture to mock the IMAP client."""
    mock_client = MockImapClient(host="imap.test.com", port=993)
    mocker.patch("mailtag.imap_service.imaplib.IMAP4_SSL", return_value=mock_client)
    return mock_client


@pytest.fixture
def mock_gmail_service(mocker: MockerFixture) -> MockGmailService:
    """Fixture to mock the Gmail service."""
    mock_service = MockGmailService()
    mocker.patch("mailtag.gmail_service.get_gmail_service", return_value=mock_service)
    return mock_service
