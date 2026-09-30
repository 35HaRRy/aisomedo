from __future__ import annotations

from pathlib import Path

from dojo import DojoActivity, DojoPairing, DojoPublishing, DojoSetup, InMemoryStore
from dojo.adapters.stubs import StubMetaPublisher, StubNotifier, StubSignedUrlStore
from dojo.testing import FakeClock
from fastapi.testclient import TestClient

from backend.main import create_app

UPDATE_URL = "https://example.com/dojo-latest.apk"


def make_contract_app(tmp_path: Path) -> TestClient:
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
    activity = DojoActivity(audit=store, pairing=store)
    setup = DojoSetup(setup=store, audit=store, pairing=store, clock=FakeClock())
    return TestClient(create_app(publishing, pairing, activity, setup, cookie_secure=False))


def pair_device(client: TestClient, pairing: DojoPairing) -> str:
    code = pairing.create_pairing_code(requester="cli").raw_code
    resp = client.post(
        "/api/pairing/validate", json={"code": code, "kind": "device", "name": "Phone"}
    )
    assert resp.status_code == 200
    return resp.json()["token"]


def device_headers(token: str, version: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Android-Version-Code": version}


def test_compat_exposes_minimum_version(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ANDROID_CURRENT_VERSION_CODE", "5")
    monkeypatch.setenv("ANDROID_UPDATE_URL", UPDATE_URL)
    monkeypatch.delenv("ANDROID_MIN_VERSION_CODE", raising=False)
    client = make_contract_app(tmp_path)
    resp = client.get("/api/compat")
    assert resp.status_code == 200
    body = resp.json()
    assert body["android_current_version_code"] == 5
    assert body["android_min_version_code"] == 4
    assert body["update_url"] == UPDATE_URL
    assert body["api_version"]


def test_current_and_previous_accepted(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ANDROID_CURRENT_VERSION_CODE", "5")
    monkeypatch.setenv("ANDROID_UPDATE_URL", UPDATE_URL)
    monkeypatch.delenv("ANDROID_MIN_VERSION_CODE", raising=False)
    client = make_contract_app(tmp_path)
    token = pair_device(client, client.app.state.pairing)  # type: ignore[attr-defined]
    assert client.get("/api/packages/active", headers=device_headers(token, "5")).status_code != 426
    assert client.get("/api/packages/active", headers=device_headers(token, "4")).status_code != 426


def test_below_min_blocked_with_update_url(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ANDROID_CURRENT_VERSION_CODE", "5")
    monkeypatch.setenv("ANDROID_UPDATE_URL", UPDATE_URL)
    monkeypatch.delenv("ANDROID_MIN_VERSION_CODE", raising=False)
    client = make_contract_app(tmp_path)
    token = pair_device(client, client.app.state.pairing)  # type: ignore[attr-defined]
    resp = client.get("/api/packages/active", headers=device_headers(token, "3"))
    assert resp.status_code == 426
    assert resp.json()["update_url"] == UPDATE_URL


def test_missing_version_header_blocked(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ANDROID_CURRENT_VERSION_CODE", "5")
    monkeypatch.setenv("ANDROID_UPDATE_URL", UPDATE_URL)
    monkeypatch.delenv("ANDROID_MIN_VERSION_CODE", raising=False)
    client = make_contract_app(tmp_path)
    token = pair_device(client, client.app.state.pairing)  # type: ignore[attr-defined]
    resp = client.get("/api/packages/active", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 426


def test_browser_session_exempt(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ANDROID_CURRENT_VERSION_CODE", "5")
    monkeypatch.setenv("ANDROID_UPDATE_URL", UPDATE_URL)
    monkeypatch.delenv("ANDROID_MIN_VERSION_CODE", raising=False)
    client = make_contract_app(tmp_path)
    pairing = client.app.state.pairing  # type: ignore[attr-defined]
    code = pairing.create_pairing_code(requester="cli").raw_code
    resp = client.post(
        "/api/pairing/validate", json={"code": code, "kind": "browser", "name": "Web"}
    )
    assert resp.status_code == 200
    resp = client.get("/api/packages/active")
    assert resp.status_code != 426


def test_compat_and_health_exempt_without_header(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ANDROID_CURRENT_VERSION_CODE", "5")
    monkeypatch.setenv("ANDROID_UPDATE_URL", UPDATE_URL)
    monkeypatch.delenv("ANDROID_MIN_VERSION_CODE", raising=False)
    client = make_contract_app(tmp_path)
    assert client.get("/api/compat").status_code == 200
    assert client.get("/health").status_code == 200
