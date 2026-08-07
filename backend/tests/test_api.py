from __future__ import annotations

from pathlib import Path

from backend.main import create_app
from dojo import DojoPublishing, InMemoryStore
from dojo.adapters.stubs import StubMetaPublisher, StubNotifier, StubSignedUrlStore
from dojo.testing import FakeClock
from fastapi.testclient import TestClient


def make_client(tmp_path: Path) -> tuple[TestClient, DojoPublishing]:
    store = InMemoryStore()
    publishing = DojoPublishing(
        packages=store,
        audit=store,
        media_root=tmp_path,
        clock=FakeClock(),
        meta=StubMetaPublisher(),
        notifier=StubNotifier(),
        signed_urls=StubSignedUrlStore(),
    )
    return TestClient(create_app(publishing)), publishing


def test_health(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    assert client.get("/health").json() == {"status": "ok"}


def test_get_active_404_when_absent(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    assert client.get("/api/packages/active").status_code == 404


def test_ensure_active_creates_and_get_returns(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)

    created = client.post("/api/packages/active")
    assert created.status_code == 201
    body = created.json()
    assert body["folder_name"] == "06-08-2026 14-30"
    assert body["status"] == "active"

    fetched = client.get("/api/packages/active")
    assert fetched.status_code == 200
    assert fetched.json()["folder_name"] == "06-08-2026 14-30"


def test_ensure_active_409_when_already_active(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    client.post("/api/packages/active")
    assert client.post("/api/packages/active").status_code == 409
