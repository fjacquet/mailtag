import pytest

import mailtag.gmail_auth as gmail_auth


def test_get_gmail_service_missing_dependencies(monkeypatch):
    monkeypatch.setattr(gmail_auth, "GOOGLE_DEPS_AVAILABLE", False)
    monkeypatch.setattr(gmail_auth, "_GOOGLE_IMPORT_ERROR", ModuleNotFoundError("google"))
    with pytest.raises(ImportError, match="Google API dependencies are required"):
        gmail_auth.get_gmail_service("creds.json", "token.json")
