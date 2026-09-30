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


class NoProjectNotifier:
    """What the real adapter does when no project id can be resolved."""

    def __init__(self, *, project_id: str | None = None, **kwargs: object) -> None:
        if not project_id:
            raise RuntimeError("FCM is enabled but no Firebase project id is configured")


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


def test_fcm_enabled_without_any_project_id_fails_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An enabled deployment with no resolvable project must not boot.

    Monitoring records alerts durably and would then report them as pending
    forever while the operator believed FCM was live. Failing here is the only
    outcome that cannot silently lose an alert.
    """
    monkeypatch.setenv("FCM_ENABLED", "true")
    monkeypatch.delenv("FCM_PROJECT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.setattr(worker_main, "FcmNotifier", NoProjectNotifier)

    with pytest.raises(RuntimeError, match="firebase_admin not configured"):
        build_notifier()


def test_an_empty_project_id_does_not_count_as_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A blank FCM_PROJECT_ID is the shape an operator leaves behind after
    # clearing a secret, and it must read as absent rather than as a project.
    monkeypatch.setenv("FCM_ENABLED", "true")
    monkeypatch.setenv("FCM_PROJECT_ID", "   ")
    monkeypatch.setattr(worker_main, "FcmNotifier", NoProjectNotifier)

    with pytest.raises(RuntimeError):
        build_notifier()


def test_google_cloud_project_stands_in_for_the_fcm_project_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # ADC environments export GOOGLE_CLOUD_PROJECT; requiring FCM_PROJECT_ID
    # as well would refuse a correctly configured deployment.
    monkeypatch.setenv("FCM_ENABLED", "true")
    monkeypatch.delenv("FCM_PROJECT_ID", raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "dojo-prod")
    monkeypatch.setattr(worker_main, "FcmNotifier", FakeNotifier)

    notifier = build_notifier()

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
