"""Notifier wiring: real FCM is explicit, and never a silent stub.

Production monitoring sends durable operational alerts, so a disabled or
misconfigured provider must be visible: the worker either has a real
notifier or has none at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import worker.main as worker_main
from dojo import DojoPublishing
from worker.main import build_notifier


class FakeNotifier:
    def __init__(self, *, project_id: str | None = None, **kwargs: object) -> None:
        self.project_id = project_id


class BrokenNotifier:
    def __init__(self, **kwargs: object) -> None:
        raise RuntimeError("Application Default Credentials unavailable")


def test_disabled_fcm_builds_no_notifier_at_all(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FCM_ENABLED", "false")

    assert build_notifier() is None


def test_enabled_fcm_configures_project_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FCM_ENABLED", "true")
    monkeypatch.setenv("FCM_PROJECT_ID", "dojo-prod")
    monkeypatch.setattr(worker_main, "FcmNotifier", FakeNotifier)

    notifier = build_notifier()

    assert isinstance(notifier, FakeNotifier)
    assert notifier.project_id == "dojo-prod"


def test_configuration_failure_fails_startup_instead_of_falling_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("FCM_ENABLED", "true")
    monkeypatch.setenv("SKIP_CREATE_ALL", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://127.0.0.1:1/unreachable")
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path / "media"))
    monkeypatch.delenv("META_TOKEN_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("SIGNED_URL_SECRET", raising=False)
    monkeypatch.setattr(worker_main, "FcmNotifier", BrokenNotifier)

    # A stub would mark real pending alerts delivered without a provider.
    with pytest.raises(RuntimeError):
        worker_main.build_publishing()


def test_publishing_sends_through_the_real_notifier(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("FCM_ENABLED", "true")
    monkeypatch.setenv("SKIP_CREATE_ALL", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://127.0.0.1:1/unreachable")
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path / "media"))
    monkeypatch.delenv("META_TOKEN_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("SIGNED_URL_SECRET", raising=False)
    monkeypatch.setattr(worker_main, "FcmNotifier", FakeNotifier)

    publishing = worker_main.build_publishing()

    assert isinstance(publishing, DojoPublishing)
    assert isinstance(publishing._notifier, FakeNotifier)
