from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.readiness import DatabaseReadiness


def test_unready_backend_keeps_liveness() -> None:
    client = TestClient(create_app(readiness=lambda: False))
    assert client.get("/ready").status_code == 503
    assert client.get("/ready").json() == {"status": "unavailable"}
    assert client.get("/health").json() == {"status": "ok"}


def test_ready_ok_when_probe_passes() -> None:
    client = TestClient(create_app(readiness=lambda: True))
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_exception_maps_to_503_with_redacted_body() -> None:
    def boom() -> bool:
        raise RuntimeError("connect failed password=supersecret-123")

    client = TestClient(create_app(readiness=boom))
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert "supersecret-123" not in response.text


def test_ready_recovers_when_probe_recovers() -> None:
    state = {"ok": False}
    client = TestClient(create_app(readiness=lambda: state["ok"]))
    assert client.get("/ready").status_code == 503
    state["ok"] = True
    assert client.get("/ready").status_code == 200
    assert client.get("/ready").json() == {"status": "ok"}


def test_liveness_unchanged_regardless_of_readiness() -> None:
    for probe in (lambda: True, lambda: False):
        client = TestClient(create_app(readiness=probe))
        assert client.get("/health").status_code == 200
        assert client.get("/health").json() == {"status": "ok"}


def test_ready_without_probe_is_unavailable_not_liveness() -> None:
    client = TestClient(create_app())
    assert client.get("/ready").status_code == 503
    assert client.get("/ready").json() == {"status": "unavailable"}
    assert client.get("/health").json() == {"status": "ok"}


def test_readiness_engine_timeout_budget() -> None:
    probe = DatabaseReadiness("postgresql+psycopg://u:p@127.0.0.1:1/db")
    try:
        assert probe.pool_timeout == 0.5
        assert probe.connect_args["connect_timeout"] == 2
        options = probe.connect_args["options"]
        assert isinstance(options, str) and "statement_timeout=1000" in options
        assert 0.5 + 2 + 1 < 5
    finally:
        probe.close()


def test_readiness_check_false_on_unreachable_database() -> None:
    probe = DatabaseReadiness("postgresql+psycopg://u:p@127.0.0.1:1/db")
    try:
        started = time.monotonic()
        assert probe.check() is False
        assert time.monotonic() - started < 5
    finally:
        probe.close()


def test_readiness_rejects_url_whose_driver_ignores_connect_args() -> None:
    with pytest.raises(ValueError, match="postgresql") as excinfo:
        DatabaseReadiness("sqlite+pysqlite:///./dojo.db")
    # The message must name the scheme only: no DSN, no credentials.
    assert "dojo.db" not in str(excinfo.value)
    assert "sqlite" in str(excinfo.value)


def test_readiness_logs_non_secret_failure_reason_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    probe = DatabaseReadiness("postgresql+psycopg://dojo:supersecret@127.0.0.1:1/db")
    try:
        with caplog.at_level("WARNING"):
            assert probe.check() is False
            assert probe.check() is False
    finally:
        probe.close()
    reasons = [r for r in caplog.records if "readiness probe failed" in r.getMessage()]
    assert len(reasons) == 1  # one line per outage streak, not per probe
    assert "OperationalError" in reasons[0].getMessage()
    assert "supersecret" not in caplog.text
    assert "postgresql+psycopg" not in caplog.text


def test_lifespan_installs_and_disposes_real_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[Any] = []

    class FakeProbe:
        def __init__(self, url: str) -> None:
            self.url = url
            self.closed = False
            created.append(self)

        def check(self) -> bool:
            return True

        def close(self) -> None:
            self.closed = True

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/dojo")
    monkeypatch.setattr("backend.readiness.DatabaseReadiness", FakeProbe)
    app = create_app(
        publishing=SimpleNamespace(repair_open_folders=lambda requester: None),
        pairing=object(),
        activity=object(),
        setup=SimpleNamespace(_meta=object()),
        meta=object(),
    )
    with TestClient(app) as client:
        assert len(created) == 1
        assert created[0].url == "postgresql+psycopg://u:p@db:5432/dojo"
        assert app.state.readiness() is True
        assert client.get("/ready").json() == {"status": "ok"}
        assert created[0].closed is False
    assert created[0].closed is True


def test_lifespan_keeps_injected_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected(url: str) -> None:  # pragma: no cover - must never run
        raise AssertionError("real probe built despite injected readiness")

    monkeypatch.setattr("backend.readiness.DatabaseReadiness", unexpected)
    app = create_app(
        publishing=SimpleNamespace(repair_open_folders=lambda requester: None),
        pairing=object(),
        activity=object(),
        setup=SimpleNamespace(_meta=object()),
        meta=object(),
        readiness=lambda: False,
    )
    with TestClient(app) as client:
        assert client.get("/ready").status_code == 503
