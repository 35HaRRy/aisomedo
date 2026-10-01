from __future__ import annotations

import json
import math
from collections.abc import Callable
from pathlib import Path

import dojo.worker_health as shared_health
import pytest
import worker.health as wh
from worker.health import WorkerHealth, check_health


def _clock(monkeypatch: pytest.MonkeyPatch, now: list[float]) -> None:
    monkeypatch.setattr(wh, "monotonic", lambda: now[0])
    monkeypatch.setattr(shared_health, "monotonic", lambda: now[0])


def test_idle_boundary_119_healthy_120_not(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1000.0]
    _clock(monkeypatch, now)
    path = tmp_path / "health.json"
    WorkerHealth(path).idle()
    now[0] = 1000.0 + 119
    assert check_health(path) is True
    now[0] = 1000.0 + 120
    assert check_health(path) is False


def test_busy_boundary_121_healthy_3600_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1000.0]
    _clock(monkeypatch, now)
    path = tmp_path / "health.json"
    WorkerHealth(path).busy()
    now[0] = 1000.0 + 121
    assert check_health(path) is True
    now[0] = 1000.0 + 3600
    assert check_health(path) is False


def test_missing_record_is_unhealthy(tmp_path: Path) -> None:
    assert check_health(tmp_path / "nope.json") is False


def test_corrupt_record_is_unhealthy(tmp_path: Path) -> None:
    path = tmp_path / "health.json"
    path.write_text("{not json", encoding="utf-8")
    assert check_health(path) is False


def test_wrong_boot_id_is_unhealthy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1000.0]
    _clock(monkeypatch, now)
    path = tmp_path / "health.json"
    WorkerHealth(path).idle()
    record = json.loads(path.read_text(encoding="utf-8"))
    record["boot_id"] = "wrong-boot-id"
    path.write_text(json.dumps(record), encoding="utf-8")
    assert check_health(path) is False


def test_stopped_phase_is_unhealthy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1000.0]
    _clock(monkeypatch, now)
    path = tmp_path / "health.json"
    health = WorkerHealth(path)
    health.idle()
    assert check_health(path) is True
    health.stopped()
    assert check_health(path) is False


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, -1.0, 0.0])
def test_nonfinite_or_nonpositive_timeouts_rejected(tmp_path: Path, bad: float) -> None:
    with pytest.raises(ValueError):
        WorkerHealth(tmp_path / "a.json", idle_seconds=bad)
    with pytest.raises(ValueError):
        WorkerHealth(tmp_path / "b.json", busy_seconds=bad)


def test_blocked_tick_cannot_renew_busy_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1000.0]
    _clock(monkeypatch, now)
    path = tmp_path / "health.json"
    health = WorkerHealth(path)
    health.busy()
    first_deadline = json.loads(path.read_text(encoding="utf-8"))["deadline"]
    # Tick still blocked 100s later; a renewed busy mark must not extend it.
    now[0] = 1100.0
    health.busy()
    assert json.loads(path.read_text(encoding="utf-8"))["deadline"] == first_deadline
    now[0] = 1000.0 + 3600
    assert check_health(path) is False


def test_record_contains_required_fields_and_no_temp_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1000.0]
    _clock(monkeypatch, now)
    path = tmp_path / "health.json"
    WorkerHealth(path).idle()
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["version"] == 1
    assert record["phase"] == "idle"
    assert isinstance(record["boot_id"], str) and record["boot_id"]
    assert record["monotonic"] == 1000.0
    assert record["deadline"] == 1000.0 + 120
    assert list(tmp_path.iterdir()) == [path]


def test_busy_then_idle_transitions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1000.0]
    _clock(monkeypatch, now)
    path = tmp_path / "health.json"
    health = WorkerHealth(path)
    health.busy()
    assert json.loads(path.read_text(encoding="utf-8"))["phase"] == "busy"
    now[0] = 1100.0
    health.idle()
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["phase"] == "idle"
    assert record["deadline"] == 1100.0 + 120
    assert check_health(path) is True


def _write_record(path: Path, **overrides: object) -> None:
    record = {
        "version": 1,
        "phase": "idle",
        "boot_id": wh.current_boot_id(),
        "monotonic": 1000.0,
        "deadline": 1120.0,
    }
    record.update(overrides)
    path.write_text(json.dumps(record), encoding="utf-8")


@pytest.mark.parametrize(
    "overrides",
    [
        {"version": 2},  # unknown record version
        {"phase": "stopped"},  # clean shutdown is not "in progress"
        {"phase": "who-knows"},  # unknown phase
        {"boot_id": "another-boot"},
        {"monotonic": "not-a-number"},
        {"deadline": "not-a-number"},
        {"monotonic": math.nan},
        {"deadline": math.inf},
        {"deadline": 1000.0},  # deadline not after the write time
        {"monotonic": 900.0, "deadline": 1000.0},  # deadline already reached
    ],
)
def test_malformed_record_fields_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, overrides: dict[str, object]
) -> None:
    now = [1000.0]
    _clock(monkeypatch, now)
    path = tmp_path / "health.json"
    _write_record(path, **overrides)
    assert check_health(path) is False


def test_non_object_record_and_unreadable_path_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1000.0]
    _clock(monkeypatch, now)
    path = tmp_path / "health.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")  # valid JSON, wrong shape
    assert check_health(path) is False
    assert check_health(tmp_path) is False  # a directory is unreadable


def test_cli_main_exits_0_healthy_1_stale(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1000.0]
    _clock(monkeypatch, now)
    path = tmp_path / "health.json"
    WorkerHealth(path).idle()
    assert wh.main(["worker.health", str(path)]) == 0
    now[0] = 1000.0 + 120
    assert wh.main(["worker.health", str(path)]) == 1
    assert wh.main(["worker.health", str(tmp_path / "missing.json")]) == 1


def test_worker_health_idle_must_exceed_tick_interval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import worker.main as worker_main

    monkeypatch.setenv("WORKER_HEALTH_PATH", str(tmp_path / "h.json"))
    monkeypatch.setenv("WORKER_HEALTH_IDLE_SECONDS", "10")
    monkeypatch.setenv("WORKER_HEALTH_BUSY_SECONDS", "3600")
    with pytest.raises(RuntimeError):
        worker_main.build_worker_health(interval_seconds=10)
    monkeypatch.setenv("WORKER_HEALTH_IDLE_SECONDS", "11")
    assert isinstance(worker_main.build_worker_health(interval_seconds=10), WorkerHealth)


def test_worker_writes_the_file_the_cli_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import worker.main as worker_main

    path = tmp_path / "health.json"
    monkeypatch.setenv("WORKER_HEALTH_PATH", str(path))
    health = worker_main.build_worker_health(interval_seconds=10)
    health.idle()
    # No CLI argument: the probe must resolve the same container-local file.
    assert wh.main(["worker.health"]) == 0
    health.stopped()
    assert wh.main(["worker.health"]) == 1


class _RecordingHealth:
    """Health record double: records phase order, optionally failing writes."""

    def __init__(self, fail_writes: bool = False) -> None:
        self.phases: list[str] = []
        self.fail_writes = fail_writes

    def _record(self, phase: str) -> None:
        self.phases.append(phase)
        if self.fail_writes:
            raise OSError(28, "No space left on device")

    def idle(self) -> None:
        self._record("idle")

    def busy(self) -> None:
        self._record("busy")

    def stopped(self) -> None:
        self._record("stopped")


def _run_worker_main(
    monkeypatch: pytest.MonkeyPatch,
    health: _RecordingHealth,
    tick: object,
    handlers: dict[int, object],
) -> dict[int, object]:
    """Drive ``worker.main.main`` with fake boot wiring; fills ``handlers``."""
    import worker.main as worker_main

    monkeypatch.setenv("WORKER_INTERVAL_SECONDS", "0.01")
    monkeypatch.setattr(worker_main, "build_publishing", lambda: object())
    monkeypatch.setattr(worker_main, "build_meta", lambda: None)
    monkeypatch.setattr(worker_main, "build_worker_health", lambda interval: health)
    monkeypatch.setattr(worker_main, "run_tick", tick)
    monkeypatch.setattr(
        worker_main.signal,
        "signal",
        lambda signum, handler: handlers.setdefault(signum, handler),
    )
    worker_main.main()
    return handlers


def test_main_marks_busy_before_tick_idle_after_and_stopped_last(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import signal

    health = _RecordingHealth()
    phases_at_tick: list[str] = []
    handlers: dict[int, object] = {}

    def tick(publishing: object, meta: object) -> None:
        phases_at_tick.append(health.phases[-1])
        handlers[signal.SIGTERM](None, None)  # request stop after one turn

    _run_worker_main(monkeypatch, health, tick, handlers)
    assert signal.SIGTERM in handlers and signal.SIGINT in handlers
    assert health.phases[0] == "idle"  # healthy before the first turn
    assert phases_at_tick == ["busy"]  # busy fixed before the tick starts
    assert health.phases[-2:] == ["idle", "stopped"]  # idle after, stopped at exit


def test_main_survives_health_write_failures(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import signal

    health = _RecordingHealth(fail_writes=True)
    ticks: list[None] = []
    handlers: dict[int, object] = {}

    def tick(publishing: object, meta: object) -> None:
        ticks.append(None)
        handlers[signal.SIGTERM](None, None)

    with caplog.at_level("WARNING"):
        _run_worker_main(monkeypatch, health, tick, handlers)
    assert ticks == [None]  # the loop kept running despite every write failing
    assert health.phases == ["idle", "busy", "idle", "stopped"]
    assert "No space left on device" in caplog.text
    assert "worker health" in caplog.text


def _always_failing(error: OSError) -> Callable[[], None]:
    """A health write double that always raises the given error."""

    def write() -> None:
        raise error

    return write


def test_a_repeatedly_failing_health_write_is_rate_limited(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unwritable health record must not evict the evidence for its cause.

    A full or read-only /tmp fails every write, twice per tick: unbounded, that
    is ~17 000 records/hour rotating away the monitoring.* and job.outcome lines
    the operator needs for that very incident. First failure per phase is
    logged in full; the rest are rate-limited.
    """
    import worker.main as worker_main

    worker_main._reset_health_failure_log()  # noqa: SLF001
    clock = [1000.0]
    failing = _always_failing(OSError(28, "No space left on device"))

    with caplog.at_level("WARNING", logger="worker.main"):
        for _ in range(50):
            worker_main._mark_health(failing, "idle", monotonic=lambda: clock[0])  # noqa: SLF001
            clock[0] += 10.0  # 50 ticks' worth inside one window

    writes = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "worker.health_write_failed"
    ]
    assert len(writes) == 1
    assert writes[0].status == "idle"
    assert writes[0].exc_info[0] is OSError

    # Rate-limited, not muted: the same phase is reported again past the window.
    clock[0] += worker_main.HEALTH_FAILURE_LOG_INTERVAL_SECONDS
    with caplog.at_level("WARNING", logger="worker.main"):
        worker_main._mark_health(failing, "idle", monotonic=lambda: clock[0])  # noqa: SLF001
    assert len(
        [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "worker.health_write_failed"
        ]
    ) == 2


def test_each_phase_is_rate_limited_independently(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """busy and idle alternate every tick; each must still speak for itself."""
    import worker.main as worker_main

    worker_main._reset_health_failure_log()  # noqa: SLF001
    clock = [0.0]
    failing = _always_failing(OSError(13, "Permission denied"))

    with caplog.at_level("WARNING", logger="worker.main"):
        for _ in range(3):
            for phase in ("idle", "busy", "stopped"):
                worker_main._mark_health(failing, phase, monotonic=lambda: clock[0])  # noqa: SLF001
                clock[0] += 1.0

    statuses = [
        record.status
        for record in caplog.records
        if getattr(record, "event", None) == "worker.health_write_failed"
    ]
    # Three distinct phases, three first-failure records, nothing after them.
    assert statuses == ["idle", "busy", "stopped"]


def test_the_unwritable_health_state_is_reported_once_per_process(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """One record names the degraded state; it is a state, not an event stream."""
    import worker.main as worker_main

    worker_main._reset_health_failure_log()  # noqa: SLF001
    clock = [0.0]
    failing = _always_failing(OSError(28, "No space left on device"))

    with caplog.at_level("WARNING", logger="worker.main"):
        for _ in range(20):
            worker_main._mark_health(failing, "busy", monotonic=lambda: clock[0])  # noqa: SLF001
            clock[0] += worker_main.HEALTH_FAILURE_LOG_INTERVAL_SECONDS

    unwritable = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "worker.health_state_unwritable"
    ]
    # 20 windows elapsed, so 20 rate-limited warnings — but the degraded-state
    # record is written once, because after it there is nothing new to say.
    assert len(unwritable) == 1
    assert unwritable[0].levelname == "ERROR"
    assert unwritable[0].status == "busy"


def test_a_recovered_health_write_reports_its_next_failure_in_full(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The throttle belongs to a failure, not to the phase it happened in."""
    import worker.main as worker_main

    worker_main._reset_health_failure_log()  # noqa: SLF001
    clock = [0.0]
    failing = _always_failing(OSError(28, "No space left on device"))

    with caplog.at_level("WARNING", logger="worker.main"):
        worker_main._mark_health(failing, "idle", monotonic=lambda: clock[0])  # noqa: SLF001
        worker_main._mark_health(lambda: None, "idle", monotonic=lambda: clock[0])  # noqa: SLF001
        clock[0] += 1.0
        worker_main._mark_health(failing, "idle", monotonic=lambda: clock[0])  # noqa: SLF001

    assert len(
        [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "worker.health_write_failed"
        ]
    ) == 2


def test_failed_stopped_write_does_not_mask_inflight_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import threading

    import worker.main as worker_main

    class BoomEvent(threading.Event):
        def wait(self, timeout: float | None = None) -> bool:
            raise RuntimeError("in-flight boom")

    health = _RecordingHealth(fail_writes=True)
    monkeypatch.setenv("WORKER_INTERVAL_SECONDS", "0.01")
    monkeypatch.setattr(worker_main, "build_publishing", lambda: object())
    monkeypatch.setattr(worker_main, "build_meta", lambda: None)
    monkeypatch.setattr(worker_main, "build_worker_health", lambda interval: health)
    monkeypatch.setattr(worker_main, "run_tick", lambda publishing, meta: None)
    monkeypatch.setattr(worker_main.threading, "Event", BoomEvent)
    monkeypatch.setattr(worker_main.signal, "signal", lambda signum, handler: None)
    with caplog.at_level("WARNING"), pytest.raises(RuntimeError, match="in-flight boom"):
        worker_main.main()
    assert health.phases[-1] == "stopped"  # cleanup still attempted
    assert "worker health" in caplog.text  # and its failure only logged


