from __future__ import annotations

import hashlib
from pathlib import Path

from dojo import DojoActivity, DojoPairing, DojoPublishing, DojoSetup, InMemoryStore
from dojo.adapters.stubs import (
    StubMediaProcessor,
    StubMetaPublisher,
    StubNotifier,
    StubSignedUrlStore,
)
from dojo.testing import FakeClock
from fastapi.testclient import TestClient

from backend.main import create_app


def make_app(tmp_path: Path) -> tuple[TestClient, DojoPublishing, DojoPairing, DojoSetup]:
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
    client = TestClient(create_app(publishing, pairing, activity, setup, cookie_secure=False))
    return client, publishing, pairing, setup


def pair_device(client: TestClient, pairing: DojoPairing, name: str = "Phone") -> str:
    code = pairing.create_pairing_code(requester="cli").raw_code
    resp = client.post("/api/pairing/validate", json={"code": code, "kind": "device", "name": name})
    assert resp.status_code == 200
    return resp.json()["token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_health(tmp_path: Path) -> None:
    client, _, _, _ = make_app(tmp_path)
    assert client.get("/health").json() == {"status": "ok"}


def test_packages_require_auth(tmp_path: Path) -> None:
    client, _, _, _ = make_app(tmp_path)
    assert client.get("/api/packages/active").status_code == 401
    assert client.post("/api/packages/active").status_code == 401
    assert client.post("/api/packages/active/complete").status_code == 401


def test_get_active_auto_creates_when_absent(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    resp = client.get("/api/packages/active", headers=bearer(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "active"
    events = client.get("/api/activity", headers=bearer(token)).json()["events"]
    actions = [e["action"] for e in events]
    assert "package.created" in actions


def test_post_active_second_ensure_returns_409(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    assert client.post("/api/packages/active", headers=bearer(token)).status_code == 201
    assert client.post("/api/packages/active", headers=bearer(token)).status_code == 409


def test_complete_active_returns_next_package(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    first = client.post("/api/packages/active", headers=bearer(token)).json()

    resp = client.post("/api/packages/active/complete", headers=bearer(token))
    assert resp.status_code == 200
    next_body = resp.json()
    assert next_body["status"] == "active"
    assert next_body["id"] != first["id"]

    fetched = client.get("/api/packages/active", headers=bearer(token)).json()
    assert fetched["id"] == next_body["id"]

    events = client.get("/api/activity", headers=bearer(token)).json()["events"]
    actions = [e["action"] for e in events]
    assert "package.completed" in actions
    assert "package.created" in actions


def test_complete_active_without_package_returns_404(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    resp = client.post("/api/packages/active/complete", headers=bearer(token))
    assert resp.status_code == 404


def test_paired_device_can_use_packages(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    created = client.post("/api/packages/active", headers=bearer(token))
    assert created.status_code == 201
    fetched = client.get("/api/packages/active", headers=bearer(token))
    assert fetched.status_code == 200


def test_revoked_device_denied_on_next_request(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    assert client.post("/api/packages/active", headers=bearer(token)).status_code == 201

    clients = client.get("/api/pairing/clients", headers=bearer(token)).json()
    assert len(clients) == 1
    revoke = client.post(f"/api/pairing/clients/{clients[0]['id']}/revoke", headers=bearer(token))
    assert revoke.status_code == 200
    assert client.post("/api/packages/active", headers=bearer(token)).status_code == 401


def test_browser_session_cookie_auth(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    code = pairing.create_pairing_code(requester="cli").raw_code
    resp = client.post(
        "/api/pairing/validate", json={"code": code, "kind": "browser", "name": "Browser"}
    )
    assert resp.status_code == 200
    assert "dojo_session" in resp.cookies
    cookie = client.cookies.get("dojo_session")
    assert cookie is not None
    assert client.post("/api/packages/active").status_code == 201


def test_browser_session_cookie_refreshed_on_auth(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    code = pairing.create_pairing_code(requester="cli").raw_code
    paired = client.post(
        "/api/pairing/validate", json={"code": code, "kind": "browser", "name": "Browser"}
    )
    assert paired.status_code == 200
    resp = client.get("/api/pairing/me")
    assert resp.status_code == 200
    assert "dojo_session" in resp.headers["set-cookie"]


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
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    me = client.get("/api/pairing/me", headers=bearer(token)).json()
    assert me["kind"] == "device"
    assert me["name"] == "Phone"
    assert client.get("/api/pairing/me").status_code == 401


def test_invalid_code_returns_401(tmp_path: Path) -> None:
    client, _, _, _ = make_app(tmp_path)
    resp = client.post(
        "/api/pairing/validate", json={"code": "aaaaaaaa", "kind": "device", "name": "X"}
    )
    assert resp.status_code == 401


def test_unauthenticated_code_minting_rejected(tmp_path: Path) -> None:
    client, _, _, _ = make_app(tmp_path)
    assert client.post("/api/pairing/codes").status_code == 401


def test_validate_throttled_per_ip(tmp_path: Path) -> None:
    client, _, _, _ = make_app(tmp_path)
    body = {"code": "aaaaaaaa", "kind": "device", "name": "X"}
    for _ in range(10):
        resp = client.post("/api/pairing/validate", json=body)
        assert resp.status_code == 401
    resp = client.post("/api/pairing/validate", json=body)
    assert resp.status_code == 429


def test_activity_requires_auth(tmp_path: Path) -> None:
    client, _, _, _ = make_app(tmp_path)
    assert client.get("/api/activity").status_code == 401


def test_paired_device_sees_resolved_activity(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    assert client.post("/api/packages/active", headers=bearer(token)).status_code == 201

    events = client.get("/api/activity", headers=bearer(token)).json()["events"]
    actions = [e["action"] for e in events]
    assert "package.created" in actions
    assert "pairing.client_paired" in actions
    created = next(e for e in events if e["action"] == "package.created")
    assert created["actor"]["kind"] == "device"
    assert created["actor"]["name"] == "Phone"
    me = client.get("/api/pairing/me", headers=bearer(token)).json()
    assert created["actor"]["id"] == me["id"]


def test_activity_cursor_pages_no_overlap(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    assert client.post("/api/packages/active", headers=bearer(token)).status_code == 201

    first = client.get(
        "/api/activity", headers=bearer(token), params={"limit": 1}
    ).json()
    assert len(first["events"]) == 1
    assert first["next_cursor"] is not None

    second = client.get(
        "/api/activity",
        headers=bearer(token),
        params={"limit": 1, "before_id": first["next_cursor"]},
    ).json()
    assert second["events"]
    ids = [e["id"] for e in first["events"]] + [e["id"] for e in second["events"]]
    assert len(set(ids)) == 2
    assert first["events"][0]["id"] > second["events"][0]["id"]


def test_browser_session_sees_activity(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    code = pairing.create_pairing_code(requester="cli").raw_code
    paired = client.post(
        "/api/pairing/validate", json={"code": code, "kind": "browser", "name": "Browser"}
    )
    assert paired.status_code == 200
    assert client.get("/api/activity").json()["events"]


def test_setup_routes_require_auth(tmp_path: Path) -> None:
    client, _, _, _ = make_app(tmp_path)
    assert client.get("/api/setup").status_code == 401
    assert client.get("/api/setup/consent").status_code == 401
    assert client.post("/api/setup/consent/accept").status_code == 401


def test_setup_without_policy_shows_incomplete(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    body = client.get("/api/setup", headers=bearer(token)).json()
    assert body["ready"] is False
    keys = {item["key"]: item["complete"] for item in body["checklist"]}
    assert keys["pairing"] is True
    assert keys["consent"] is False


def test_consent_404_until_policy_configured(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    assert client.get("/api/setup/consent", headers=bearer(token)).status_code == 404
    assert client.post("/api/setup/consent/accept", headers=bearer(token)).status_code == 404


def test_device_accepts_consent_and_setup_becomes_ready(tmp_path: Path) -> None:
    client, _, pairing, setup = make_app(tmp_path)
    token = pair_device(client, pairing)
    me = client.get("/api/pairing/me", headers=bearer(token)).json()
    setup.set_policy(version=1, text="Riza metni", requester=str(me["id"]))

    consent = client.get("/api/setup/consent", headers=bearer(token)).json()
    assert consent["version"] == 1
    assert consent["accepted_at"] is None

    accepted = client.post("/api/setup/consent/accept", headers=bearer(token))
    assert accepted.status_code == 200
    assert accepted.json()["version"] == 1

    again = client.post("/api/setup/consent/accept", headers=bearer(token))
    assert again.status_code == 200
    assert again.json()["accepted_at"] == accepted.json()["accepted_at"]

    consent = client.get("/api/setup/consent", headers=bearer(token)).json()
    assert consent["accepted_at"] == accepted.json()["accepted_at"]

    body = client.get("/api/setup", headers=bearer(token)).json()
    keys = {item["key"]: item["complete"] for item in body["checklist"]}
    assert keys["consent"] is True
    assert body["ready"] is True


def test_browser_session_accepts_consent(tmp_path: Path) -> None:
    client, _, pairing, setup = make_app(tmp_path)
    code = pairing.create_pairing_code(requester="cli").raw_code
    client.post("/api/pairing/validate", json={"code": code, "kind": "browser", "name": "Browser"})
    setup.set_policy(version=1, text="Riza metni", requester="cli")
    resp = client.post("/api/setup/consent/accept")
    assert resp.status_code == 200
    assert resp.json()["version"] == 1


def test_media_routes_require_auth(tmp_path: Path) -> None:
    client, _, _, _ = make_app(tmp_path)
    assert client.post("/api/media/uploads", json={}).status_code == 401
    assert client.put("/api/media/uploads/x/ranges", json={}).status_code == 401
    assert client.get("/api/media/uploads/x").status_code == 401
    assert client.post("/api/media/uploads/x/complete").status_code == 401
    assert client.post("/api/media/uploads/x/abort").status_code == 401
    assert client.get("/api/media/uploads").status_code == 401


def test_init_upload_then_range_then_complete(tmp_path: Path) -> None:
    client, publishing, pairing, _ = make_app(tmp_path)
    publishing._media = StubMediaProcessor()
    token = pair_device(client, pairing)
    init = client.post(
        "/api/media/uploads",
        headers=bearer(token),
        json={"filename": "pic.jpg", "content_type": "image/jpeg", "declared_size_bytes": 100},
    )
    assert init.status_code == 201
    body = init.json()
    assert body["status"] == "receiving"
    assert body["received_bytes"] == 0

    chunk = b"x" * 100
    progress = client.put(
        f"/api/media/uploads/{body['upload_id']}/ranges",
        headers=bearer(token),
        content=chunk,
        params={"offset": 0, "checksum_sha256": hashlib.sha256(chunk).hexdigest()},
    )
    assert progress.status_code == 200
    assert progress.json()["received_bytes"] == 100

    complete = client.post(
        f"/api/media/uploads/{body['upload_id']}/complete", headers=bearer(token)
    )
    assert complete.status_code == 200
    assert complete.json()["status"] == "queued"


def test_init_upload_too_large_413(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    resp = client.post(
        "/api/media/uploads",
        headers=bearer(token),
        json={
            "filename": "big.mp4",
            "content_type": "video/mp4",
            "declared_size_bytes": 2 * 1024**3 + 1,
        },
    )
    assert resp.status_code == 413


def test_init_upload_bad_filename_400(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    resp = client.post(
        "/api/media/uploads",
        headers=bearer(token),
        json={"filename": "a/b.jpg", "content_type": "image/jpeg", "declared_size_bytes": 10},
    )
    assert resp.status_code == 400


def test_range_checksum_mismatch_400(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    init = client.post(
        "/api/media/uploads",
        headers=bearer(token),
        json={"filename": "pic.jpg", "content_type": "image/jpeg", "declared_size_bytes": 100},
    ).json()
    resp = client.put(
        f"/api/media/uploads/{init['upload_id']}/ranges",
        headers=bearer(token),
        content=b"x" * 100,
        params={"offset": 0, "checksum_sha256": "deadbeef"},
    )
    assert resp.status_code == 400


def test_complete_incomplete_409(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    init = client.post(
        "/api/media/uploads",
        headers=bearer(token),
        json={"filename": "pic.jpg", "content_type": "image/jpeg", "declared_size_bytes": 100},
    ).json()
    resp = client.post(f"/api/media/uploads/{init['upload_id']}/complete", headers=bearer(token))
    assert resp.status_code == 409


def test_upload_status_and_list(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    init = client.post(
        "/api/media/uploads",
        headers=bearer(token),
        json={"filename": "pic.jpg", "content_type": "image/jpeg", "declared_size_bytes": 100},
    ).json()
    got = client.get(f"/api/media/uploads/{init['upload_id']}", headers=bearer(token))
    assert got.status_code == 200
    listed = client.get("/api/media/uploads", headers=bearer(token))
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_abort_upload(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    init = client.post(
        "/api/media/uploads",
        headers=bearer(token),
        json={"filename": "pic.jpg", "content_type": "image/jpeg", "declared_size_bytes": 100},
    ).json()
    abort = client.post(f"/api/media/uploads/{init['upload_id']}/abort", headers=bearer(token))
    assert abort.status_code == 200
    got = client.get(f"/api/media/uploads/{init['upload_id']}", headers=bearer(token)).json()
    assert got["status"] == "aborted"


def test_missing_upload_404(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    assert client.get("/api/media/uploads/nope", headers=bearer(token)).status_code == 404


def finalize_via_api(client, publishing, token, *, filename: str) -> str:
    init = client.post(
        "/api/media/uploads",
        headers=bearer(token),
        json={"filename": filename, "content_type": "image/jpeg", "declared_size_bytes": 100},
    ).json()
    chunk = b"x" * 100
    client.put(
        f"/api/media/uploads/{init['upload_id']}/ranges",
        headers=bearer(token),
        content=chunk,
        params={"offset": 0, "checksum_sha256": hashlib.sha256(chunk).hexdigest()},
    )
    client.post(f"/api/media/uploads/{init['upload_id']}/complete", headers=bearer(token))
    claimed = publishing.claim_next_job()
    assert claimed is not None
    publishing.process_job(claimed.job_id)
    return init["upload_id"]


def test_conflicting_upload_listed_with_targets(tmp_path: Path) -> None:
    client, publishing, pairing, _ = make_app(tmp_path)
    publishing._media = StubMediaProcessor()
    token = pair_device(client, pairing)
    finalize_via_api(client, publishing, token, filename="photo.jpg")

    init = client.post(
        "/api/media/uploads",
        headers=bearer(token),
        json={"filename": "photo.jpg", "content_type": "image/jpeg", "declared_size_bytes": 100},
    ).json()
    assert init["status"] == "conflict"
    assert len(init["conflicts"]) == 1
    assert init["conflicts"][0]["filename"] == "photo.jpg"

    listed = client.get("/api/media/uploads", headers=bearer(token)).json()
    assert any(u["status"] == "conflict" for u in listed)


def test_resolve_conflict_keep_both(tmp_path: Path) -> None:
    client, publishing, pairing, _ = make_app(tmp_path)
    publishing._media = StubMediaProcessor()
    token = pair_device(client, pairing)
    finalize_via_api(client, publishing, token, filename="photo.jpg")
    init = client.post(
        "/api/media/uploads",
        headers=bearer(token),
        json={"filename": "photo.jpg", "content_type": "image/jpeg", "declared_size_bytes": 100},
    ).json()
    assert init["status"] == "conflict"

    resp = client.post(
        f"/api/media/uploads/{init['upload_id']}/resolve",
        headers=bearer(token),
        json={"decision": "keep_both"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "receiving"


def test_resolve_conflict_bad_decision_400(tmp_path: Path) -> None:
    client, publishing, pairing, _ = make_app(tmp_path)
    publishing._media = StubMediaProcessor()
    token = pair_device(client, pairing)
    finalize_via_api(client, publishing, token, filename="photo.jpg")
    init = client.post(
        "/api/media/uploads",
        headers=bearer(token),
        json={"filename": "photo.jpg", "content_type": "image/jpeg", "declared_size_bytes": 100},
    ).json()
    assert init["status"] == "conflict"

    resp = client.post(
        f"/api/media/uploads/{init['upload_id']}/resolve",
        headers=bearer(token),
        json={"decision": "nope"},
    )
    assert resp.status_code == 400


def test_resolve_keep_selected_without_confirm_400(tmp_path: Path) -> None:
    client, publishing, pairing, _ = make_app(tmp_path)
    publishing._media = StubMediaProcessor()
    token = pair_device(client, pairing)
    finalize_via_api(client, publishing, token, filename="photo.jpg")
    init = client.post(
        "/api/media/uploads",
        headers=bearer(token),
        json={"filename": "photo.jpg", "content_type": "image/jpeg", "declared_size_bytes": 100},
    ).json()
    assert init["status"] == "conflict"
    target = init["conflicts"][0]["media_id"]

    resp = client.post(
        f"/api/media/uploads/{init['upload_id']}/resolve",
        headers=bearer(token),
        json={"decision": "keep_selected", "target_media_id": target},
    )
    assert resp.status_code == 400
