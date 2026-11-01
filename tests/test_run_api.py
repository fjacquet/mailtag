"""Tests for POST /api/v1/run and GET /api/v1/run/status."""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from loguru import logger

from mailtag.api import create_app
from mailtag.api.dependencies import app_state
from mailtag.api.routes import run as run_route
from mailtag.config import WebhookConfig

HEADERS = {"X-API-Key": "k"}


@pytest.fixture
def client():
    app_state.initialize = lambda: setattr(app_state, "classifier", MagicMock(categories=[]))
    cfg = MagicMock()
    cfg.webhook = WebhookConfig(api_key="k", allow_move=True)
    with (
        # Default stub: no test may ever reach the real mailboxes
        patch("main.start_classification_run"),
        patch("mailtag.api.CONFIG", cfg),
        patch("mailtag.api.routes.run.CONFIG", cfg),
        TestClient(create_app()) as c,
    ):
        run_route.reset()
        yield c, cfg
    app_state.classifier = None


def _wait_done(c, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = c.get("/api/v1/run/status", headers=HEADERS).json()
        if body["state"] != "running":
            return body
        time.sleep(0.02)
    raise AssertionError(f"run did not finish: {body}")


def test_status_idle_before_any_run(client):
    c, _ = client
    assert c.get("/api/v1/run/status", headers=HEADERS).json()["state"] == "idle"


def test_run_requires_api_key(client):
    c, _ = client
    assert c.post("/api/v1/run").status_code == 401


def test_run_success(client):
    c, _ = client
    with patch("main.start_classification_run") as start:
        r = c.post("/api/v1/run?provider=imap&validate=true", headers=HEADERS)
        assert r.status_code == 202
        body = _wait_done(c)
    start.assert_called_once_with("imap", True)
    assert body["state"] == "ok"
    assert body["provider"] == "imap"
    assert body["validate"] is True
    assert body["finished_at"] and body["error"] is None


def test_run_exception_is_error(client):
    c, _ = client
    with patch("main.start_classification_run", side_effect=RuntimeError("boom")):
        c.post("/api/v1/run", headers=HEADERS)
        body = _wait_done(c)
    assert body["state"] == "error"
    assert "boom" in body["error"]


def test_swallowed_error_log_is_error(client):
    """run_classification logs CRITICAL on a connection failure instead of raising."""
    c, _ = client

    def fake(provider, validate):
        logger.critical("IMAP login failed")

    with patch("main.start_classification_run", side_effect=fake):
        c.post("/api/v1/run", headers=HEADERS)
        body = _wait_done(c)
    assert body["state"] == "error"
    assert "IMAP login failed" in body["error"]


def test_second_run_while_running_is_409(client):
    c, _ = client
    release = threading.Event()
    with patch("main.start_classification_run", side_effect=lambda p, v: release.wait(5)):
        assert c.post("/api/v1/run", headers=HEADERS).status_code == 202
        assert c.post("/api/v1/run", headers=HEADERS).status_code == 409
        assert c.get("/api/v1/run/status", headers=HEADERS).json()["state"] == "running"
        release.set()
        assert _wait_done(c)["state"] == "ok"
    assert c.post("/api/v1/run", headers=HEADERS).status_code == 202
    _wait_done(c)


def test_real_run_forbidden_when_moves_disabled(client):
    c, cfg = client
    cfg.webhook = WebhookConfig(api_key="k", allow_move=False)
    assert c.post("/api/v1/run", headers=HEADERS).status_code == 403
    with patch("main.start_classification_run"):
        assert c.post("/api/v1/run?validate=true", headers=HEADERS).status_code == 202
        _wait_done(c)


def test_invalid_provider_is_422(client):
    c, _ = client
    assert c.post("/api/v1/run?provider=nope", headers=HEADERS).status_code == 422
