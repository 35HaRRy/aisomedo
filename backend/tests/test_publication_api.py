from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from dojo import DojoActivity, DojoPairing, DojoPublishing, DojoSetup, InMemoryStore, SchedulePlan
from dojo.adapters.signed_urls import HmacSignedUrlStore
from dojo.adapters.stubs import (
    StubMediaProcessor,
    StubMetaPublisher,
    StubNotifier,
    StubReelRenderer,
)
from dojo.testing import FIXED_AT, ISTANBUL, FakeClock
from fastapi.testclient import TestClient

from backend.main import create_app


def make_app(tmp_path: Path):
    store = InMemoryStore()
    publishing = DojoPublishing(
        packages=store,
        audit=store,
        uploads=store,
        jobs=store,
        settings=store,
        media_root=tmp_path,
        clock=FakeClock(),
        meta=StubMetaPublisher(),
        notifier=StubNotifier(),
        signed_urls=HmacSignedUrlStore(
            base_url="http://testserver", secret="s3cret", clock=FakeClock()
        ),
        renderer=StubReelRenderer(),
    )
    pairing = DojoPairing(pairing=store, audit=store, clock=FakeClock())
    activity = DojoActivity(audit=store, pairing=store)
    setup = DojoSetup(setup=store, audit=store, pairing=store, clock=FakeClock())
    client = TestClient(create_app(publishing, pairing, activity, setup, cookie_secure=False))
    return client, publishing, pairing, store


def pair_device(client: TestClient, pairing: DojoPairing) -> str:
    code = pairing.create_pairing_code(requester="cli").raw_code
    resp = client.post(
        "/api/pairing/validate", json={"code": code, "kind": "device", "name": "Phone"}
    )
    assert resp.status_code == 200
    return resp.json()["token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Android-Version-Code": "1"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prepare_approved(tmp_path: Path, publishing: DojoPublishing):
    publishing._packages.set("branding.logo_asset", "logo.png", updated_at=FIXED_AT)
    publishing.set_plan(
        SchedulePlan(
            anchor_date=datetime(2026, 8, 3, 10, 0, tzinfo=ISTANBUL).date(),
            anchor_time=datetime(2026, 8, 3, 10, 0, tzinfo=ISTANBUL).time(),
            enabled=True,
        )
    )
    publishing._clock = FakeClock(datetime(2026, 8, 3, 10, 0, tzinfo=ISTANBUL))
    publishing._media = StubMediaProcessor(content_type="image/jpeg", duration=None)
    publishing.get_or_create_active_package()
    status = publishing.start_upload("pic.jpg", "image/jpeg", 100)
    publishing.append_upload_range(status.upload_id, 0, 100, sha(b"x" * 100), b"x" * 100)
    publishing.complete_upload(status.upload_id)
    job = publishing.claim_next_job()
    assert job is not None
    publishing.process_job(job.job_id)
    publishing.set_caption("hello")
    publishing.evaluate_due_work()
    job = publishing.claim_next_job()
    assert job is not None
    publishing.process_job(job.job_id)
    review = publishing.list_pending_reviews()[0]
    return publishing.approve(review.id, review.version, requester="7")


def test_publication_status_reports_completed(tmp_path: Path):
    client, publishing, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    prepare_approved(tmp_path, publishing)

    resp = client.get("/api/packages/active/publication", headers=bearer(token))
    assert resp.status_code == 200
    # after success a fresh active package exists; last record lives on completed
    completed = publishing._packages.list_completed()
    assert len(completed) == 1


def test_signed_fetch_serves_only_render_and_logs(tmp_path: Path):
    client, publishing, pairing, _ = make_app(tmp_path)
    pair_device(client, pairing)
    prepare_approved(tmp_path, publishing)

    # grab a fresh signed URL for the completed render
    completed = publishing._packages.list_completed()[0]
    artifact = tmp_path / completed.folder_name / "render" / "reel.mp4"
    url = publishing._signed_urls.create(artifact)
    short = url.rsplit("/pub/", 1)[-1]

    resp = client.get(f"/pub/{short}")
    assert resp.status_code == 200
    assert resp.content == b"fake-reel"
    actions = [e.action for e in publishing.list_audit()]
    assert "publication.artifact_fetched" in actions

    # raw media path can never be minted
    raw = tmp_path / completed.folder_name / "manifest.json"
    try:
        publishing._signed_urls.create(raw)
    except ValueError:
        pass
    else:
        raise AssertionError("raw path must be denied")

    # unknown token 404s
    assert client.get("/pub/nope").status_code == 404


def test_publish_route_maps_not_ready_to_409(tmp_path: Path):
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    resp = client.post("/api/packages/active/publish", headers=bearer(token))
    assert resp.status_code == 409


def test_retry_blocked_while_publishing_409(tmp_path: Path):
    # Issue #19: fresh publish/retry prohibited until reconciled.
    from dojo.adapters.stubs import StubMetaPublisher

    client, publishing, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    meta = publishing._meta
    assert isinstance(meta, StubMetaPublisher)
    orig_create = meta.create_container

    def create_then_queue(url, caption):
        cid = orig_create(url, caption)
        meta.status_queues[cid] = ["IN_PROGRESS"]
        return cid

    meta.create_container = create_then_queue  # type: ignore[method-assign]
    prepare_approved(tmp_path, publishing)

    resp = client.post("/api/packages/active/publication/retry", headers=bearer(token))
    assert resp.status_code == 409
    resp = client.post("/api/packages/active/publish", headers=bearer(token))
    assert resp.status_code == 409


def test_reconcile_poll_error_keeps_publishing_via_api(tmp_path: Path):
    # Issue #19: reconcile polling errors keep -publishing via the endpoint.
    from dojo.adapters.stubs import StubMetaPublisher

    client, publishing, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    meta = publishing._meta
    assert isinstance(meta, StubMetaPublisher)
    orig_create = meta.create_container

    def create_then_queue(url, caption):
        cid = orig_create(url, caption)
        meta.status_queues[cid] = ["IN_PROGRESS"]
        return cid

    meta.create_container = create_then_queue  # type: ignore[method-assign]
    prepare_approved(tmp_path, publishing)
    assert publishing._packages.get_publishing() is not None

    orig_status = meta.get_container_status

    def boom(container_id: str) -> str:
        raise RuntimeError("status check timed out")

    meta.get_container_status = boom  # type: ignore[method-assign]
    try:
        resp = client.post(
            "/api/packages/active/publication/reconcile", headers=bearer(token)
        )
    finally:
        meta.get_container_status = orig_status  # type: ignore[method-assign]

    assert resp.status_code == 200
    body = resp.json()["publication"]
    assert body["status"] == "uncertain"
    assert body["allowed_actions"] == ["reconcile"]
    assert publishing._packages.get_publishing() is not None
    assert publishing._packages.list_completed() == []


def test_failed_status_exposes_recovery_actions_via_api(tmp_path: Path):
    # Issue #19: definite failure exposes Retry/Review/Skip/Reschedule.
    from dojo.adapters.stubs import StubMetaPublisher
    from dojo.exceptions import MetaPublishFailed

    client, publishing, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    meta = publishing._meta
    assert isinstance(meta, StubMetaPublisher)
    meta.fail_create = MetaPublishFailed("rejected: bad video")
    prepare_approved(tmp_path, publishing)

    resp = client.get("/api/packages/active/publication", headers=bearer(token))
    assert resp.status_code == 200
    body = resp.json()["publication"]
    assert body["status"] == "failed"
    assert set(body["allowed_actions"]) >= {"retry", "review", "skip", "reschedule"}


def test_review_endpoints_manage_failed_package(tmp_path: Path):
    # Issue #19: Review/Skip/Reschedule manageable via endpoints.
    from dojo.adapters.stubs import StubMetaPublisher
    from dojo.exceptions import MetaPublishFailed

    client, publishing, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    meta = publishing._meta
    assert isinstance(meta, StubMetaPublisher)
    meta.fail_create = MetaPublishFailed("rejected: bad video")
    prepare_approved(tmp_path, publishing)

    resp = client.get("/api/reviews/pending", headers=bearer(token))
    assert resp.status_code == 200
    assert isinstance(resp.json()["reviews"], list)

    # reschedule with a past time is rejected
    resp = client.post(
        "/api/reviews/1/reschedule",
        json={"version": 1, "new_due_at": "2000-01-01T10:00:00+03:00"},
        headers=bearer(token),
    )
    assert resp.status_code in (400, 422)


def test_failed_package_recovery_skip_requires_confirmation(tmp_path: Path):
    from dojo.exceptions import MetaPublishFailed

    client, publishing, pairing, store = make_app(tmp_path)
    token = pair_device(client, pairing)
    publishing._meta.fail_create = MetaPublishFailed("bad video")
    prepare_approved(tmp_path, publishing)
    path = "/api/packages/active/publication/recover"
    resp = client.post(path, json={"action": "skip"}, headers=bearer(token))
    assert resp.status_code == 400
    response = client.post(
        path, json={"action": "skip", "confirmed": True}, headers=bearer(token)
    )
    assert response.status_code == 200
    assert response.json()["publication"]["status"] == "skipped"
    retry = client.post("/api/packages/active/publication/retry", headers=bearer(token))
    assert retry.status_code == 409
    done = client.post("/api/packages/active/complete", headers=bearer(token))
    assert done.status_code == 409
    assert store.list_completed() == []
