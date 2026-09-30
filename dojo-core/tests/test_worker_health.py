import importlib
import json

import pytest


@pytest.mark.parametrize("phase,elapsed,expected", [
    ("idle", 119, "healthy"), ("idle", 120, "unhealthy"),
    ("busy", 121, "healthy"), ("busy", 3600, "unhealthy"),
])
def test_progress_deadlines(tmp_path, monkeypatch, phase, elapsed, expected):
    health = importlib.import_module("dojo.worker_health")
    monkeypatch.setattr(health, "monotonic", lambda: 1000 + elapsed)
    path = tmp_path / "health.json"
    path.write_text(json.dumps({"version": 1, "phase": phase, "boot_id": health.current_boot_id(),
                               "monotonic": 1000, "deadline": 1120 if phase == "idle" else 4600}))
    assert health.read_worker_status(path).status == expected


@pytest.mark.parametrize("changes", [
    {"phase": "stopped"}, {"boot_id": "old"}, {"version": 2},
    {"monotonic": True}, {"deadline": False}, {"monotonic": 1002},
    {"deadline": float("nan")}, {"deadline": "oops"},
])
def test_invalid_progress_never_healthy(tmp_path, monkeypatch, changes):
    health = importlib.import_module("dojo.worker_health")
    monkeypatch.setattr(health, "monotonic", lambda: 1001)
    path = tmp_path / "health.json"
    record = {"version": 1, "phase": "idle", "boot_id": health.current_boot_id(),
              "monotonic": 1000, "deadline": 1120}
    path.write_text(json.dumps(record | changes))
    assert health.read_worker_status(path).status == "unhealthy"


def test_missing_unknown_corruption_unhealthy(tmp_path):
    health = importlib.import_module("dojo.worker_health")
    path = tmp_path / "health.json"
    assert health.read_worker_status(None).status == "unknown"
    assert health.read_worker_status(path).status == "unknown"
    path.write_text("{")
    assert health.read_worker_status(path).status == "unhealthy"
