from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pytest
import worker.main as worker_main
from dojo import DojoPublishing, InMemoryStore, Job
from dojo.adapters.stubs import StubMediaProcessor
from dojo.observability import JsonFormatter
from worker.main import (
    _emission_store,
    _maybe_create_all,
    _run_emission_turn,
    run_tick,
)


class TickSpy(DojoPublishing):
    """Controllable seam: counts every tick operation."""

    def __init__(self) -> None:
        self.evaluations = 0
        self.evaluate_failures_left = 0
        self.processed_jobs: list[str] = []
        self.reconciles = 0
        self.reminders = 0
        self.sweeps = 0
        self._claims_left = 1
        super().__init__(
            packages=InMemoryStore(),
            audit=InMemoryStore(),
            media_root="/tmp/dojo-media",
            media=StubMediaProcessor(),
        )

    def evaluate_due_work(self) -> None:
        self.evaluations += 1
        if self.evaluate_failures_left:
            self.evaluate_failures_left -= 1
            raise RuntimeError("injected emission failure")

    def claim_next_job(self) -> Job | None:
        if self._claims_left:
            self._claims_left -= 1
            return Job(
                id=1,
                job_id="j-1",
                upload_id=1,
                kind="media",
                status="queued",
                payload={},
                created_at=datetime.now(),
            )
        return None

    def process_job(self, job_id: str) -> None:
        self.processed_jobs.append(job_id)

    def reconcile_publication(self, *, requester: str | None = None) -> dict | None:
        self.reconciles += 1
        return None

    def send_due_reminders(self) -> None:
        self.reminders += 1

    def sweep_stale_uploads(self, ttl: object = None) -> int:
        self.sweeps += 1
        return 0


class MaintainSpy:
    def __init__(self) -> None:
        self.maintains = 0

    def maintain(self) -> None:
        self.maintains += 1


@contextmanager
def _patched_leadership(monkeypatch: pytest.MonkeyPatch, leader: bool) -> Iterator[None]:
    @contextmanager
    def _deny(_store: object) -> Iterator[bool]:
        yield leader

    monkeypatch.setattr(worker_main, "try_emission_leadership", _deny)
    yield


def test_follower_tick_processes_job_but_emits_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = TickSpy()
    meta = MaintainSpy()
    with _patched_leadership(monkeypatch, False):
        run_tick(spy, meta)
    assert spy.evaluations == 0
    assert spy.processed_jobs == ["j-1"]
    assert spy.reconciles == 0
    assert spy.reminders == 0
    assert spy.sweeps == 0
    assert meta.maintains == 0


def test_leader_tick_runs_emission_and_singletons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = TickSpy()
    meta = MaintainSpy()
    with _patched_leadership(monkeypatch, True):
        run_tick(spy, meta)
    assert spy.evaluations == 1
    assert spy.processed_jobs == ["j-1"]
    assert spy.reconciles == 1
    assert spy.reminders == 1
    assert spy.sweeps == 1
    assert meta.maintains == 1


def test_emission_exception_does_not_kill_tick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = TickSpy()
    spy.evaluate_failures_left = 1
    with _patched_leadership(monkeypatch, True):
        run_tick(spy, None)
        assert spy.evaluations == 1
        assert spy.processed_jobs == ["j-1"]
        run_tick(spy, None)
        assert spy.evaluations == 2


def test_tick_survives_total_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = TickSpy()

    @contextmanager
    def _broken(_store: object) -> Iterator[bool]:
        raise ConnectionError("db unavailable")

    monkeypatch.setattr(worker_main, "try_emission_leadership", _broken)
    monkeypatch.setattr(
        TickSpy, "claim_next_job", lambda self: (_ for _ in ()).throw(ConnectionError("down"))
    )
    run_tick(spy, None)


class CreateAllSpy:
    def __init__(self) -> None:
        self.calls = 0

    def create_all(self) -> None:
        self.calls += 1


def test_maybe_create_all_skips_when_env_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SKIP_CREATE_ALL", "1")
    spy = CreateAllSpy()
    _maybe_create_all(spy)  # type: ignore[arg-type]
    assert spy.calls == 0


def test_maybe_create_all_runs_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SKIP_CREATE_ALL", raising=False)
    spy = CreateAllSpy()
    _maybe_create_all(spy)  # type: ignore[arg-type]
    assert spy.calls == 1


def test_build_publishing_skips_ddl_without_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    media = tmp_path / "media-does-not-exist"
    monkeypatch.setenv("SKIP_CREATE_ALL", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://127.0.0.1:1/unreachable")
    monkeypatch.setenv("MEDIA_ROOT", str(media))
    monkeypatch.delenv("META_TOKEN_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("SIGNED_URL_SECRET", raising=False)
    publishing = worker_main.build_publishing()
    assert isinstance(publishing, DojoPublishing)


class _Coordinator:
    """Minimal coordinator-capable store for _emission_store tests."""

    def emission_transaction(self) -> object:
        return self

    def try_advisory_xact_lock(self, key: int) -> bool:
        return True


def test_emission_store_shared_instance_returned() -> None:
    from types import SimpleNamespace

    shared = _Coordinator()
    publishing = SimpleNamespace(_packages=shared, _schedule=shared)
    assert _emission_store(publishing) is shared  # type: ignore[arg-type]


def test_emission_store_split_stores_warn_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Split coordinator instances: loud warning naming ports, first wins.

    Distinct per-port stores are a supported dev/test pattern, so this warns
    instead of raising — but never silently picks first. Uses a Mock logger
    (not caplog) so the test is immune to root-logging config from other
    suites in a full run.
    """
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    mock_logger = MagicMock()
    monkeypatch.setattr(worker_main, "logger", mock_logger)
    first = _Coordinator()
    publishing = SimpleNamespace(
        _packages=first, _schedule=_Coordinator()
    )
    assert _emission_store(publishing) is first  # type: ignore[arg-type]
    mock_logger.warning.assert_called_once()
    msg = mock_logger.warning.call_args.args[0]
    assert "do not share one emission store" in msg


def test_job_outcome_is_logged_with_safe_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Job outcomes carry a stable event plus job_id/status/duration only."""
    with caplog.at_level(logging.INFO, logger="worker.main"):
        run_tick(TickSpy(), None)
    outcomes = [r for r in caplog.records if getattr(r, "event", None) == "job.outcome"]
    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome.job_id == "j-1"
    assert outcome.status == "processed"
    assert isinstance(outcome.duration_ms, float)
    assert JsonFormatter("worker").format(outcome).count("\n") == 0


def test_job_outcome_logs_raised_failure_with_error_type(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise(self: TickSpy, job_id: str) -> None:
        raise RuntimeError("render failed with token=s3cr3t-bearer-token")

    monkeypatch.setattr(TickSpy, "process_job", _raise)
    with caplog.at_level(logging.INFO, logger="worker.main"):
        run_tick(TickSpy(), None)
    (outcome,) = [r for r in caplog.records if getattr(r, "event", None) == "job.outcome"]
    assert outcome.status == "error"
    assert outcome.job_id == "j-1"
    line = JsonFormatter("worker").format(outcome)
    assert "s3cr3t-bearer-token" not in line
    assert json.loads(line)["error_type"] == "RuntimeError"


def test_no_coordinator_emits_directly_without_leadership() -> None:
    """Fallback contract: no coordinator-capable port → emit ungated.

    Dev/test-only path (production always wires PostgresStore); pinned so a
    future change to skip-instead-of-emit breaks loudly here first.
    """
    from types import SimpleNamespace

    calls = 0

    def _evaluate() -> None:
        nonlocal calls
        calls += 1

    publishing = SimpleNamespace(evaluate_due_work=_evaluate)
    assert _emission_store(publishing) is None  # type: ignore[arg-type]
    assert _run_emission_turn(publishing) is False  # type: ignore[arg-type]
    assert calls == 1
