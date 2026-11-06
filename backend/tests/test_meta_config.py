"""Compose injects unset Meta settings as empty strings; that must mean "unset"."""

from dojo.adapters import meta as adapters


def test_build_meta_falls_back_when_meta_app_credentials_are_empty(monkeypatch):
    monkeypatch.setenv("META_TOKEN_ENCRYPTION_KEY", adapters.FernetCipher.generate_key())
    monkeypatch.setenv("META_APP_ID", "")
    monkeypatch.setenv("META_APP_SECRET", "")
    monkeypatch.setenv("META_REDIRECT_URI", "")
    monkeypatch.setenv("SKIP_CREATE_ALL", "1")

    from backend.deps import build_meta

    assert build_meta() is not None
