from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
import worker.health as wh
from worker.health import WorkerHealth, check_health


def _clock(monkeypatch: pytest.MonkeyPatch, now: list[float]) -> None:
    monkeypatch.setattr(wh, "monotonic", lambda: now[0])


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

