import pytest

from tests.github_manual import ConfigurationError, get_settings


def test_missing_settings(monkeypatch):
    monkeypatch.setattr("tests.github_manual.load_dotenv", lambda path: None)
    for name in ("GITHUB_TOKEN", "GITHUB_ALLOWED_REPO"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ConfigurationError, match="GITHUB_TOKEN"):
        get_settings()


def test_settings_hide_secrets(monkeypatch):
    monkeypatch.setattr("tests.github_manual.load_dotenv", lambda path: None)
    monkeypatch.setenv("GITHUB_TOKEN", "private-token")
    monkeypatch.setenv("GITHUB_ALLOWED_REPO", "owner/repo")
    monkeypatch.delenv("SERVICE_API_KEY", raising=False)
    settings = get_settings()
    assert settings.github_allowed_repo == "owner/repo"
    assert "private-token" not in repr(settings)
