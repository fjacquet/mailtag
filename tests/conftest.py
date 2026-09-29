import logging

import pytest
from loguru import logger
from pytest_mock import MockerFixture

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


@pytest.fixture
def mock_imap_client(mocker: MockerFixture) -> MockImapClient:
    """Fixture to mock the IMAP client."""
    mock_client = MockImapClient(host="imap.test.com", port=993)
    mocker.patch("mailtag.imap_service.imaplib.IMAP4_SSL", return_value=mock_client)
    return mock_client
