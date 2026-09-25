from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest
from dojo import DojoPublishing, InMemoryStore, SchedulePlan
from dojo.adapters.stubs import (
    StubMediaProcessor,
    StubMetaPublisher,
    StubNotifier,
    StubReelRenderer,
    StubSignedUrlStore,
)
from dojo.exceptions import (
    MetaPublishFailed,
    MetaPublishUncertain,
    PublicationInProgress,
    PublicationNotReady,
)
from dojo.testing import FIXED_AT, ISTANBUL, FakeClock


def make_seam(tmp_path: Path, meta: StubMetaPublisher | None = None):
    store = InMemoryStore()
    renderer = StubReelRenderer()
    meta = meta or StubMetaPublisher()
    signed = StubSignedUrlStore()
    seam = DojoPublishing(
        packages=store,
        audit=store,
        uploads=store,
        jobs=store,
        settings=store,
        media_root=tmp_path,
        clock=FakeClock(),
        meta=meta,
        notifier=StubNotifier(),
        signed_urls=signed,
        renderer=renderer,
    )
    return store, seam, renderer, meta, signed


def monday_dt() -> datetime:
    return datetime(2026, 8, 3, 10, 0, tzinfo=ISTANBUL)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def finalize_media(tmp_path, seam, *, filename="pic.jpg", content_type="image/jpeg"):
    seam._media = StubMediaProcessor(content_type=content_type, duration=None)
    seam.get_or_create_active_package()
    status = seam.start_upload(filename, content_type, 100)
    seam.append_upload_range(status.upload_id, 0, 100, sha(b"x" * 100), b"x" * 100)
    seam.complete_upload(status.upload_id)
    job = seam.claim_next_job()
    assert job is not None
    seam.process_job(job.job_id)


def claim_render(seam):
    job = seam.claim_next_job()
    assert job is not None and job.kind == "render"
    seam.process_job(job.job_id)


def prepare_approved_review(tmp_path, seam, *, caption="hello"):
    store = seam._packages
    store.set("branding.logo_asset", "logo.png", updated_at=FIXED_AT)
    seam.set_plan(
        SchedulePlan(
            anchor_date=monday_dt().date(),
            anchor_time=monday_dt().time(),
            enabled=True,
        )
    )
    seam._clock = FakeClock(monday_dt())
    finalize_media(tmp_path, seam)
    seam.set_caption(caption)
    # render file needed for publication; stub renderer writes fake-reel
    seam.evaluate_due_work()
    claim_render(seam)
    reviews = seam.list_pending_reviews()
    assert len(reviews) == 1
    review = reviews[0]
    return seam.approve(review.id, review.version, requester="7")


def test_approve_claims_publishing_persists_ids_and_completes(tmp_path):
    store, seam, _, meta, signed = make_seam(tmp_path)
    resolved = prepare_approved_review(tmp_path, seam)

    # approval triggers publication synchronously in MVP
    assert seam.get_active_package() is not None
    active = seam.get_active_package()
    assert active is not None
    # new empty active package created after completion
    assert active.status == "active"

    completed = store.list_completed()
    assert len(completed) == 1
    assert completed[0].folder_name.endswith("-completed")

    manifest = json.loads(
        (tmp_path / completed[0].folder_name / "manifest.json").read_text(encoding="utf-8")
    )
    publication = manifest["meta"]["publication"]
    assert publication["revision"] == resolved.revision_digest
    assert publication["review_id"] == resolved.id
    assert publication["container_id"].startswith("container_")
    assert publication["media_id"].startswith("media_container_")
    assert publication["status"] == "completed"

    # only approved render exposed via signed URL, then revoked after ingestion
    assert len(signed.created_paths) == 1
    assert signed.created_paths[0].name == "reel.mp4"
    assert str(signed.created_paths[0]).replace("\\", "/").endswith("render/reel.mp4")
    assert len(signed.revoked) == 1

    # container/media identifiers persisted + audited
    actions = [e.action for e in seam.list_audit()]
    assert "publication.claimed" in actions
    assert "publication.container_created" in actions
    assert "publication.confirmed" in actions
    assert "package.completed" in actions


def test_stuck_publishing_blocks_second_claim(tmp_path):
    store, seam, _, meta, _ = make_seam(tmp_path)
    meta.statuses = {"container_1": "IN_PROGRESS"}
    # first approval leaves package in publishing (uncertain)
    # use status queue to keep IN_PROGRESS
    orig_create = meta.create_container

    def create_then_queue(url, caption):
        cid = orig_create(url, caption)
        meta.status_queues[cid] = ["IN_PROGRESS"]
        return cid

    meta.create_container = create_then_queue  # type: ignore[method-assign]
    prepare_approved_review(tmp_path, seam)

    publishing = store.get_publishing()
    assert publishing is not None
    assert publishing.folder_name.endswith("-publishing")

    with pytest.raises(PublicationInProgress):
        seam.retry_publication(requester="7")
    # reconcile keeps it uncertain without duplicate publish
    before = list(meta.publish_calls)
    seam.reconcile_publication()
    assert meta.publish_calls == before


def test_definite_failure_returns_to_active_and_retry(tmp_path):
    store, seam, _, meta, _ = make_seam(tmp_path)
    meta.fail_create = MetaPublishFailed("rejected: bad video")
    # approval attempt hits definite failure -> package back to active, retry available
    store.set("branding.logo_asset", "logo.png", updated_at=FIXED_AT)
    seam.set_plan(
        SchedulePlan(
            anchor_date=monday_dt().date(), anchor_time=monday_dt().time(), enabled=True
        )
    )
    seam._clock = FakeClock(monday_dt())
    finalize_media(tmp_path, seam)
    seam.set_caption("hello")
    seam.evaluate_due_work()
    claim_render(seam)
    review = seam.list_pending_reviews()[0]
    seam.approve(review.id, review.version, requester="7")

    assert store.get_publishing() is None
    active = seam.get_active_package()
    assert active is not None and active.status == "active"
    assert store.list_completed() == []

    status = seam.get_publication_status()
    assert status is not None and status["status"] == "failed"

    # retry succeeds
    meta.fail_create = None
    seam.retry_publication(requester="7")
    assert len(store.list_completed()) == 1


def test_uncertain_publish_timeout_reconciles_without_duplicate(tmp_path):
    store, seam, _, meta, _ = make_seam(tmp_path)
    meta.fail_publish = MetaPublishUncertain("timeout before response")
    prepare_approved_review(tmp_path, seam)

    publishing = store.get_publishing()
    assert publishing is not None
    first_calls = list(meta.publish_calls)
    assert len(first_calls) == 1

    # reconcile resumes with the SAME saved container: no fresh container,
    # hence no second Reel. publish_container repeats for one container id.
    meta.fail_publish = None
    container_id = meta.created[0][2]
    meta.statuses = {container_id: "FINISHED"}
    seam.reconcile_publication()

    assert store.get_publishing() is None
    assert len(store.list_completed()) == 1
    assert len(meta.created) == 1
    assert all(call == container_id for call in meta.publish_calls)
    assert len(meta.publish_calls) == len(first_calls) + 1


def register_device(seam, store, token="tok-1"):
    from dojo.model import Client

    client = store.create_client(
        Client(id=0, name="Phone", kind="device", created_at=FIXED_AT, created_by="cli"),
        credential_hash="h",
    )
    seam.register_push_token(client.id, token)
    return client


def test_success_notifies_paired_devices(tmp_path):
    store, seam, _, _, _ = make_seam(tmp_path)
    register_device(seam, store)
    prepare_approved_review(tmp_path, seam)
    assert len(seam._notifier.sent) == 1
    assert "notification.sent" in [e.action for e in seam.list_audit()]


def test_definite_failure_notifies_paired_devices(tmp_path):
    store, seam, _, meta, _ = make_seam(tmp_path)
    register_device(seam, store)
    meta.fail_create = MetaPublishFailed("rejected: bad video")
    store.set("branding.logo_asset", "logo.png", updated_at=FIXED_AT)
    seam.set_plan(
        SchedulePlan(
            anchor_date=monday_dt().date(), anchor_time=monday_dt().time(), enabled=True
        )
    )
    seam._clock = FakeClock(monday_dt())
    finalize_media(tmp_path, seam)
    seam.set_caption("hello")
    seam.evaluate_due_work()
    claim_render(seam)
    review = seam.list_pending_reviews()[0]
    seam.approve(review.id, review.version, requester="7")
    assert len(seam._notifier.sent) == 1


def test_publish_without_approval_not_ready(tmp_path):
    store, seam, _, _, _ = make_seam(tmp_path)
    store.set("branding.logo_asset", "logo.png", updated_at=FIXED_AT)
    seam.ensure_active_package()
    with pytest.raises(PublicationNotReady):
        seam.publish(requester="7")
