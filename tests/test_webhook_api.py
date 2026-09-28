"""Tests for the MailTag webhook API."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from mailtag.api.dependencies import app_state
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
    WebhookConfig,
)

TEST_API_KEY = "test-api-key-12345"


def _real_config(*, taxonomy_enabled: bool, allow_move: bool = True) -> AppConfig:
    """A real AppConfig (not a MagicMock) so `dataclasses.replace` works on it."""
    return AppConfig(
        general=GeneralConfig(ollama_model="m", api_base=""),
        logging=LoggingConfig(level="DEBUG", file=""),
        classifier=ClassifierConfig(
            ai_confidence_threshold=0.7, historical_confidence_threshold=0.9, min_count=3
        ),
        imap=ImapConfig(host="imap.test.com", user="u@test.com", password="p"),
        gmail=GmailConfig(credentials_file="creds.json", token_file="token.json"),
        fast_parse=FastParseConfig(),
        mlx=MLXConfig(enabled=False),
        webhook=WebhookConfig(api_key=TEST_API_KEY, allow_move=allow_move, max_batch_size=5),
        taxonomy=TaxonomyConfig(enabled=taxonomy_enabled),
    )


@pytest.fixture
def mock_classifier():
    """Create a mock Classifier."""
    classifier = MagicMock()
    classifier.categories = ["Finance/Invoices", "Services/Email", "Shopping/Online"]
    classifier.classify_email.return_value = "Finance/Invoices"
    classifier.classify_emails_batch.return_value = ["Finance/Invoices", "Services/Email"]
    return classifier


@pytest.fixture
def mock_database():
    """Create a mock ClassificationDatabase."""
    return MagicMock()


def _make_client(mock_classifier, mock_database, api_key):
    """Create a TestClient with mocked app_state and config."""
    original_init = app_state.initialize

    def mock_initialize():
        app_state.database = mock_database
        app_state.classifier = mock_classifier

    app_state.initialize = mock_initialize

    mock_config = MagicMock()
    mock_config.webhook = WebhookConfig(api_key=api_key, max_batch_size=5)
    mock_config.imap = MagicMock(host="imap.test.com")
    mock_config.gmail = MagicMock(credentials_file="creds.json")
    mock_config.fast_parse = MagicMock()

    with (
        patch("mailtag.api.CONFIG", mock_config),
        patch("mailtag.api.routes.classify.CONFIG", mock_config),
        patch("mailtag.api.routes.health.CONFIG", mock_config),
    ):
        from mailtag.api import create_app

        app = create_app()
        with TestClient(app) as client:
            yield client

    # Restore original initialize and reset state
    app_state.initialize = original_init
    app_state.classifier = None
    app_state.database = None
    app_state.legacy_classifier = None


@pytest.fixture
def api_client(mock_classifier, mock_database):
    """Create a test client with mocked dependencies and API key auth."""
    yield from _make_client(mock_classifier, mock_database, TEST_API_KEY)


@pytest.fixture
def api_client_no_auth(mock_classifier, mock_database):
    """Create a test client without API key auth."""
    yield from _make_client(mock_classifier, mock_database, "")


def _auth_headers():
    return {"X-API-Key": TEST_API_KEY}


def _sample_email():
    return {
        "msg_id": "12345",
        "subject": "Your Invoice #001",
        "sender_address": "billing@example.com",
        "sender_name": "Billing Dept",
        "body": "Please find your invoice attached.",
        "labels": ["INBOX"],
    }


# --- Health endpoint tests ---


class TestHealth:
    def test_health_no_auth_required(self, api_client):
        """Health endpoint should work without API key."""
        response = api_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["classifier_ready"] is True
        assert data["database_loaded"] is True
        assert "version" in data
        assert "uptime_seconds" in data

    def test_status_requires_auth(self, api_client):
        """Status endpoint should require API key."""
        response = api_client.get("/api/v1/status")
        assert response.status_code == 401

    def test_status_with_auth(self, api_client):
        """Status endpoint returns detailed info with valid key."""
        response = api_client.get("/api/v1/status", headers=_auth_headers())
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["categories_count"] == 3
        assert "providers" in data


# --- Authentication tests ---


class TestAuth:
    def test_classify_requires_auth(self, api_client):
        """Classify endpoint should reject requests without API key."""
        response = api_client.post("/api/v1/classify", json=_sample_email())
        assert response.status_code == 401

    def test_classify_invalid_key(self, api_client):
        """Classify endpoint should reject invalid API key."""
        response = api_client.post(
            "/api/v1/classify",
            json=_sample_email(),
            headers={"X-API-Key": "wrong-key"},
        )
        assert response.status_code == 401

    def test_no_auth_mode(self, api_client_no_auth):
        """When no API key is configured, requests should pass without auth."""
        response = api_client_no_auth.post("/api/v1/classify", json=_sample_email())
        assert response.status_code == 200


# --- Classify endpoint tests ---


class TestClassify:
    def test_classify_single_email(self, api_client, mock_classifier):
        """Classify a single email successfully."""
        response = api_client.post(
            "/api/v1/classify",
            json=_sample_email(),
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["msg_id"] == "12345"
        assert data["category"] == "Finance/Invoices"
        mock_classifier.classify_email.assert_called_once()

    def test_classify_minimal_fields(self, api_client):
        """Classify with only required fields."""
        response = api_client.post(
            "/api/v1/classify",
            json={
                "msg_id": "1",
                "subject": "Test",
                "sender_address": "test@example.com",
            },
            headers=_auth_headers(),
        )
        assert response.status_code == 200

    def test_classify_missing_required_field(self, api_client):
        """Missing required fields should return 422."""
        response = api_client.post(
            "/api/v1/classify",
            json={"msg_id": "1"},
            headers=_auth_headers(),
        )
        assert response.status_code == 422


# --- Batch endpoint tests ---


class TestClassifyBatch:
    def test_classify_batch(self, api_client, mock_classifier):
        """Classify a batch of emails."""
        response = api_client.post(
            "/api/v1/classify-batch",
            json={
                "emails": [
                    _sample_email(),
                    {
                        "msg_id": "12346",
                        "subject": "Newsletter",
                        "sender_address": "news@company.com",
                        "sender_name": "News",
                    },
                ]
            },
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["results"]) == 2
        mock_classifier.classify_emails_batch.assert_called_once()

    def test_classify_batch_exceeds_max(self, api_client):
        """Batch exceeding max_batch_size should return 400."""
        emails = [
            {"msg_id": str(i), "subject": f"Test {i}", "sender_address": f"user{i}@test.com"}
            for i in range(10)
        ]
        response = api_client.post(
            "/api/v1/classify-batch",
            json={"emails": emails},
            headers=_auth_headers(),
        )
        assert response.status_code == 400
        assert "exceeds maximum" in response.json()["detail"]

    def test_classify_batch_empty(self, api_client):
        """Empty batch should return 422 (min_length=1)."""
        response = api_client.post(
            "/api/v1/classify-batch",
            json={"emails": []},
            headers=_auth_headers(),
        )
        assert response.status_code == 422


# --- Classify-and-move endpoint tests ---


class TestClassifyAndMove:
    def test_classify_and_move_success(self, api_client, mock_classifier):
        """Classify and move via IMAP provider."""
        with patch("mailtag.api.routes.classify.ImapService") as mock_imap:
            mock_provider = MagicMock()
            mock_provider.connect.return_value.__enter__ = MagicMock(return_value=mock_provider)
            mock_provider.connect.return_value.__exit__ = MagicMock(return_value=False)
            mock_imap.return_value = mock_provider

            payload = _sample_email()
            payload["provider"] = "imap"
            response = api_client.post(
                "/api/v1/classify-and-move",
                json=payload,
                headers=_auth_headers(),
            )
            assert response.status_code == 200
            data = response.json()
            assert data["category"] == "Finance/Invoices"
            assert data["moved"] is True

    def test_classify_and_move_files_a_category_into_its_para_folder(self, api_client, mock_classifier):
        mock_classifier.classify_email.return_value = "Santé"
        with (
            patch("mailtag.api.routes.classify.ImapService") as mock_imap,
            patch("mailtag.api.routes.classify.CONFIG.taxonomy.enabled", True),
        ):
            mock_provider = MagicMock()
            mock_provider.connect.return_value.__enter__ = MagicMock(return_value=mock_provider)
            mock_provider.connect.return_value.__exit__ = MagicMock(return_value=False)
            mock_imap.return_value = mock_provider

            payload = _sample_email()
            payload["provider"] = "imap"
            response = api_client.post("/api/v1/classify-and-move", json=payload, headers=_auth_headers())

            assert response.status_code == 200
            assert mock_provider.move_email.call_args.args[1] == "Domaines/Santé"

    def test_classify_and_move_unactionable(self, api_client, mock_classifier):
        """Unactionable category should not trigger a move."""
        mock_classifier.classify_email.return_value = "À Classer"
        payload = _sample_email()
        payload["provider"] = "imap"
        response = api_client.post(
            "/api/v1/classify-and-move",
            json=payload,
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["moved"] is False
        assert data["error"] == "Category not actionable for move"

    def test_classify_and_move_disabled(self, api_client):
        """When allow_move is False, should return 403."""
        with patch("mailtag.api.routes.classify.CONFIG") as mock_config:
            mock_config.webhook = WebhookConfig(api_key=TEST_API_KEY, allow_move=False)
            payload = _sample_email()
            payload["provider"] = "imap"
            response = api_client.post(
                "/api/v1/classify-and-move",
                json=payload,
                headers=_auth_headers(),
            )
            assert response.status_code == 403

    def test_classify_and_move_invalid_provider(self, api_client):
        """Invalid provider should return 422 (regex validation)."""
        payload = _sample_email()
        payload["provider"] = "outlook"
        response = api_client.post(
            "/api/v1/classify-and-move",
            json=payload,
            headers=_auth_headers(),
        )
        assert response.status_code == 422

    def test_classify_and_move_connection_error(self, api_client, mock_classifier):
        """Provider connection failure should return moved=False with error."""
        with patch("mailtag.api.routes.classify.ImapService") as mock_imap:
            mock_imap.return_value.connect.side_effect = ConnectionError("IMAP connection refused")

            payload = _sample_email()
            payload["provider"] = "imap"
            response = api_client.post(
                "/api/v1/classify-and-move",
                json=payload,
                headers=_auth_headers(),
            )
            assert response.status_code == 200
            data = response.json()
            assert data["moved"] is False
            assert "connection refused" in data["error"].lower()


# --- classify-batch: taxonomy review category is not "classified" ---


class TestClassifyBatchTaxonomyReview:
    def test_review_category_not_counted_as_classified(self, api_client, mock_classifier):
        """mailtag.taxonomy.REVIEW ('5-A revoir') must not count towards `classified`."""
        mock_classifier.classify_emails_batch.return_value = ["Finance/Invoices", "5-A revoir"]
        response = api_client.post(
            "/api/v1/classify-batch",
            json={
                "emails": [
                    _sample_email(),
                    {
                        "msg_id": "12346",
                        "subject": "Newsletter",
                        "sender_address": "news@company.com",
                        "sender_name": "News",
                    },
                ]
            },
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert data["classified"] == 1


# --- classify-and-move: Gmail stays on the legacy (non-taxonomy) flow ---


class TestClassifyAndMoveGmailTaxonomy:
    def _gmail_payload(self):
        payload = _sample_email()
        payload["provider"] = "gmail"
        return payload

    def test_gmail_uses_legacy_classifier_when_taxonomy_enabled(
        self, api_client, mock_classifier, mock_database
    ):
        """Gmail must never classify with the taxonomy-enabled main classifier."""
        with (
            patch("mailtag.api.routes.classify.CONFIG", _real_config(taxonomy_enabled=True)),
            patch("mailtag.api.routes.classify.Classifier") as mock_classifier_cls,
            patch("mailtag.api.routes.classify.GmailService") as mock_gmail,
        ):
            legacy_classifier = MagicMock()
            legacy_classifier.classify_email.return_value = "Finance/Invoices"
            mock_classifier_cls.return_value = legacy_classifier

            mock_provider = MagicMock()
            mock_provider.connect.return_value.__enter__ = MagicMock(return_value=mock_provider)
            mock_provider.connect.return_value.__exit__ = MagicMock(return_value=False)
            mock_gmail.return_value = mock_provider

            response = api_client.post(
                "/api/v1/classify-and-move",
                json=self._gmail_payload(),
                headers=_auth_headers(),
            )

            assert response.status_code == 200
            legacy_classifier.classify_email.assert_called_once()
            mock_classifier.classify_email.assert_not_called()
            # Built once, config taxonomy disabled, reusing the shared database.
            mock_classifier_cls.assert_called_once()
            args, _ = mock_classifier_cls.call_args
            legacy_config = args[0]
            assert legacy_config.taxonomy.enabled is False
            assert args[1] is mock_database

    def test_imap_uses_main_classifier_when_taxonomy_enabled(self, api_client, mock_classifier):
        """IMAP keeps using the main (taxonomy-enabled) classifier, never the legacy one."""
        with (
            patch("mailtag.api.routes.classify.CONFIG", _real_config(taxonomy_enabled=True)),
            patch("mailtag.api.routes.classify.Classifier") as mock_classifier_cls,
            patch("mailtag.api.routes.classify.ImapService") as mock_imap,
        ):
            mock_provider = MagicMock()
            mock_provider.connect.return_value.__enter__ = MagicMock(return_value=mock_provider)
            mock_provider.connect.return_value.__exit__ = MagicMock(return_value=False)
            mock_imap.return_value = mock_provider

            payload = _sample_email()
            payload["provider"] = "imap"
            response = api_client.post(
                "/api/v1/classify-and-move",
                json=payload,
                headers=_auth_headers(),
            )

            assert response.status_code == 200
            mock_classifier.classify_email.assert_called_once()
            mock_classifier_cls.assert_not_called()

    def test_taxonomy_disabled_never_builds_second_classifier(self, api_client, mock_classifier):
        """When taxonomy mode is off, Gmail requests use the single main classifier."""
        with (
            patch("mailtag.api.routes.classify.CONFIG", _real_config(taxonomy_enabled=False)),
            patch("mailtag.api.routes.classify.Classifier") as mock_classifier_cls,
            patch("mailtag.api.routes.classify.GmailService") as mock_gmail,
        ):
            mock_provider = MagicMock()
            mock_provider.connect.return_value.__enter__ = MagicMock(return_value=mock_provider)
            mock_provider.connect.return_value.__exit__ = MagicMock(return_value=False)
            mock_gmail.return_value = mock_provider

            response = api_client.post(
                "/api/v1/classify-and-move",
                json=self._gmail_payload(),
                headers=_auth_headers(),
            )

            assert response.status_code == 200
            mock_classifier.classify_email.assert_called_once()
            mock_classifier_cls.assert_not_called()


# --- Swagger / OpenAPI tests ---


class TestSwagger:
    def test_openapi_schema(self, api_client):
        """OpenAPI schema should be accessible without auth."""
        response = api_client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        assert schema["info"]["title"] == "MailTag API"
        assert schema["info"]["version"] == "1.0.0"

    def test_docs_accessible(self, api_client):
        """Swagger UI should be accessible without auth."""
        response = api_client.get("/docs")
        assert response.status_code == 200

    def test_redoc_accessible(self, api_client):
        """ReDoc should be accessible without auth."""
        response = api_client.get("/redoc")
        assert response.status_code == 200

    def test_openapi_tags_present(self, api_client):
        """OpenAPI schema should have tag descriptions."""
        response = api_client.get("/openapi.json")
        schema = response.json()
        tag_names = [t["name"] for t in schema.get("tags", [])]
        assert "health" in tag_names
        assert "classification" in tag_names

    def test_openapi_has_classify_endpoint(self, api_client):
        """OpenAPI schema should document the classify endpoint."""
        response = api_client.get("/openapi.json")
        schema = response.json()
        assert "/api/v1/classify" in schema["paths"]
        assert "/api/v1/classify-batch" in schema["paths"]
        assert "/api/v1/classify-and-move" in schema["paths"]
