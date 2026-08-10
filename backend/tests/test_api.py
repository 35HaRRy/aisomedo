from __future__ import annotations

from pathlib import Path

from dojo import DojoPairing, DojoPublishing, InMemoryStore
from dojo.adapters.stubs import StubMetaPublisher, StubNotifier, StubSignedUrlStore
from dojo.testing import FakeClock
from fastapi.testclient import TestClient

from backend.main import create_app


def make_app(tmp_path: Path) -> tuple[TestClient, DojoPublishing, DojoPairing]:
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
    pairing = DojoPairing(pairing=store, audit=store, clock=FakeClock())
    client = TestClient(create_app(publishing, pairing, cookie_secure=False))
    return client, publishing, pairing


def pair_device(client: TestClient, pairing: DojoPairing, name: str = "Phone") -> str:
    code = pairing.create_pairing_code(requester="cli").raw_code
    resp = client.post("/api/pairing/validate", json={"code": code, "kind": "device", "name": name})
    assert resp.status_code == 200
    return resp.json()["token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_health(tmp_path: Path) -> None:
    client, _, _ = make_app(tmp_path)
    assert client.get("/health").json() == {"status": "ok"}


def test_packages_require_auth(tmp_path: Path) -> None:
    client, _, _ = make_app(tmp_path)
    assert client.get("/api/packages/active").status_code == 401
    assert client.post("/api/packages/active").status_code == 401


def test_paired_device_can_use_packages(tmp_path: Path) -> None:
    client, _, pairing = make_app(tmp_path)
    token = pair_device(client, pairing)
    created = client.post("/api/packages/active", headers=bearer(token))
    assert created.status_code == 201
    fetched = client.get("/api/packages/active", headers=bearer(token))
    assert fetched.status_code == 200


def test_revoked_device_denied_on_next_request(tmp_path: Path) -> None:
    client, _, pairing = make_app(tmp_path)
    token = pair_device(client, pairing)
    assert client.post("/api/packages/active", headers=bearer(token)).status_code == 201

    clients = client.get("/api/pairing/clients", headers=bearer(token)).json()
    assert len(clients) == 1
    revoke = client.post(f"/api/pairing/clients/{clients[0]['id']}/revoke", headers=bearer(token))
    assert revoke.status_code == 200
    assert client.post("/api/packages/active", headers=bearer(token)).status_code == 401


def test_browser_session_cookie_auth(tmp_path: Path) -> None:
    client, _, pairing = make_app(tmp_path)
    code = pairing.create_pairing_code(requester="cli").raw_code
    resp = client.post(
        "/api/pairing/validate", json={"code": code, "kind": "browser", "name": "Browser"}
    )
    assert resp.status_code == 200
    assert "dojo_session" in resp.cookies
    cookie = client.cookies.get("dojo_session")
    assert cookie is not None
    assert client.post("/api/packages/active").status_code == 201


def test_browser_validate_sets_secure_http_only_cookie(tmp_path: Path) -> None:
    store = InMemoryStore()
    pairing = DojoPairing(pairing=store, audit=store, clock=FakeClock())
    client = TestClient(create_app(None, pairing, cookie_secure=True))
    code = pairing.create_pairing_code(requester="cli").raw_code
    resp = client.post(
        "/api/pairing/validate", json={"code": code, "kind": "browser", "name": "Browser"}
    )
    header = resp.headers["set-cookie"].lower()
    assert "httponly" in header
    assert "samesite=lax" in header
    assert "secure" in header


def test_me_returns_current_client(tmp_path: Path) -> None:
    client, _, pairing = make_app(tmp_path)
    token = pair_device(client, pairing)
    me = client.get("/api/pairing/me", headers=bearer(token)).json()
    assert me["kind"] == "device"
    assert me["name"] == "Phone"
    assert client.get("/api/pairing/me").status_code == 401


def test_invalid_code_returns_401(tmp_path: Path) -> None:
    client, _, _ = make_app(tmp_path)
    resp = client.post(
        "/api/pairing/validate", json={"code": "aaaaaaaa", "kind": "device", "name": "X"}
    )
    assert resp.status_code == 401


def test_unauthenticated_code_minting_rejected(tmp_path: Path) -> None:
    client, _, _ = make_app(tmp_path)
    assert client.post("/api/pairing/codes").status_code == 401
