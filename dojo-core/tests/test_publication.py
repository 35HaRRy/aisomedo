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


def finalize_media(
    tmp_path, seam, *, filename="pic.jpg", content_type="image/jpeg", seed=b"x" * 100
):
    seam._media = StubMediaProcessor(content_type=content_type, duration=None)
    seam.get_or_create_active_package()
    status = seam.start_upload(filename, content_type, len(seed))
    seam.append_upload_range(status.upload_id, 0, len(seed), sha(seed), seed)
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


@pytest.mark.parametrize("uncertain", [False, True])
@pytest.mark.parametrize("action", ["approve", "skip", "reschedule"])
def test_publication_error_status_snapshot_and_decisions(tmp_path, uncertain, action):
    from dataclasses import asdict
    from datetime import timedelta

    store, seam, _, meta, _ = make_seam(tmp_path)
    meta.fail_create = (MetaPublishUncertain if uncertain else MetaPublishFailed)("bad response")
    review = prepare_approved_review(tmp_path, seam)
    expected = "uncertain" if uncertain else "failed"
    assert review.status == expected
    assert review.instagram_fail_message and "bad response" in review.instagram_fail_message
    assert review.resolved_at is None
    assert store.get_publishing() is None
    assert seam.list_pending_reviews() == [review]
    assert seam.get_dashboard_summary().pending_actions[0].review_status == expected
    assert seam.get_review_detail(review.id)["render_ready"]
    snapshot = json.loads(json.dumps(asdict(review), default=lambda value: value.isoformat()))
    event = next(e for e in seam.list_audit() if e.action == f"review.{expected}")
    assert event.details == snapshot
    meta.fail_create = None
    if action == "approve":
        completed = seam.approve(review.id, review.version)
        assert completed.status == "approved"
        assert completed.instagram_fail_message is None
    elif action == "skip":
        assert seam.skip(review.id, review.version, confirmed=True).review.status == "skipped"
    else:
        resolved = seam.reschedule(review.id, review.version, monday_dt() + timedelta(hours=1))
        assert resolved.status == "rescheduled"


def test_review_is_publishing_before_external_request_and_blocks_decisions(tmp_path):
    from datetime import timedelta

    store, seam, _, meta, _ = make_seam(tmp_path)
    create = meta.create_container

    def check_publishing(url, caption):
        from concurrent.futures import ThreadPoolExecutor

        review = store._reviews[0]
        assert review.status == "publishing"
        assert review.instagram_fail_message is None
        for decision in (
            lambda: seam.approve(review.id, review.version),
            lambda: seam.skip(review.id, review.version, confirmed=True),
            lambda: seam.reschedule(review.id, review.version, monday_dt() + timedelta(hours=1)),
        ):
            with pytest.raises(PublicationInProgress):
                decision()
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            detail = executor.submit(seam.get_review_detail, review.id).result(timeout=2)
            assert detail["review"]["status"] == "publishing"
            future = executor.submit(seam.skip, review.id, review.version, confirmed=True)
            with pytest.raises(PublicationInProgress):
                future.result(timeout=2)
        finally:
            executor.shutdown(wait=False)
        return create(url, caption)

    meta.create_container = check_publishing
    assert prepare_approved_review(tmp_path, seam).status == "approved"


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


@pytest.mark.parametrize("action", ["approve", "skip", "reschedule"])
def test_failed_upload_preserves_review_and_allows_same_version_decision(tmp_path, action):
    from datetime import timedelta

    store, seam, _, meta, _ = make_seam(tmp_path)
    meta.fail_create = MetaPublishFailed("rejected: bad video")
    result = prepare_approved_review(tmp_path, seam)
    review = store.get(result.id)
    assert review == result
    assert review.status == "failed"
    assert review.version == 1
    assert review.resolved_at is None and review.resolved_by is None
    occurrence = next(o for o in store.list_all() if o.id == review.occurrence_id)
    assert occurrence.status == "due" and occurrence.resolved_at is None
    assert seam.get_review_detail(review.id)["render_ready"]
    assert not any(e.action == "review.approved" for e in seam.list_audit())
    seam.evaluate_due_work()
    assert seam.list_pending_reviews() == [review]

    if action == "approve":
        meta.fail_create = None
        assert seam.approve(review.id, review.version).status == "approved"
        assert len(store.list_completed()) == 1
    elif action == "skip":
        assert seam.skip(review.id, review.version, confirmed=True).review.status == "skipped"
        with pytest.raises(PublicationNotReady):
            seam.retry_publication()
    else:
        assert seam.reschedule(
            review.id, review.version, monday_dt() + timedelta(hours=1),
        ).status == "rescheduled"
        with pytest.raises(PublicationNotReady):
            seam.retry_publication()


def test_signed_url_failure_preserves_open_review(tmp_path):
    store, seam, _, meta, signed = make_seam(tmp_path)

    def fail_url(_):
        raise ValueError("PUBLIC_BASE_URL must use publicly reachable HTTPS")

    signed.create = fail_url
    result = prepare_approved_review(tmp_path, seam)
    assert result.status == "failed" and result.version == 1
    assert seam.list_pending_reviews() == [result]
    assert store.get_publishing() is None
    assert seam.get_review_detail(result.id)["render_ready"]
    assert seam.get_publication_status()["status"] == "failed"
    assert meta.created == []


def test_uncertain_publish_timeout_requires_manual_decision(tmp_path):
    store, seam, _, meta, _ = make_seam(tmp_path)
    meta.fail_publish = MetaPublishUncertain("timeout before response")
    review = prepare_approved_review(tmp_path, seam)
    assert review.status == "uncertain"

    publishing = store.get_publishing()
    assert publishing is None
    first_calls = list(meta.publish_calls)
    assert len(first_calls) == 1

    # No background replay: the user must check Instagram and decide.
    meta.fail_publish = None
    container_id = meta.created[0][2]
    meta.statuses = {container_id: "FINISHED"}
    seam.reconcile_publication()

    assert store.get_publishing() is None
    assert meta.publish_calls == first_calls
    meta.statuses[container_id] = "PUBLISHED"
    seam.reconcile_publication()
    assert store.get_publishing() is None
    assert len(store.list_completed()) == 0
    assert len(meta.created) == 1
    assert all(call == container_id for call in meta.publish_calls)
    assert meta.publish_calls == first_calls
    assert store.get(review.id).status == "uncertain"
    assert next(o for o in store.list_all() if o.id == review.occurrence_id).status == "due"


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


def test_failed_publication_can_be_reviewed_again_after_edit(tmp_path):
    store, seam, _, meta, _ = make_seam(tmp_path)
    meta.fail_create = MetaPublishFailed("bad video")
    prepare_approved_review(tmp_path, seam)
    seam.set_caption("corrected caption")
    with pytest.raises(PublicationNotReady):
        seam.retry_publication()
    seam.recover_publication("review")
    claim_render(seam)
    review = next(
        r for r in seam.list_pending_reviews() if seam.get_review_detail(r.id)["render_ready"]
    )
    assert review.caption == "corrected caption"
    seam.approve(review.id, review.version)
    assert len(store.list_completed()) == 1


@pytest.mark.parametrize("action", ["skip", "reschedule"])
def test_failed_recovery_actions_keep_package_incomplete(tmp_path, action):
    from datetime import timedelta

    store, seam, _, meta, _ = make_seam(tmp_path)
    meta.fail_create = MetaPublishFailed("bad video")
    prepare_approved_review(tmp_path, seam)
    result = seam.recover_publication(
        action, confirmed=True, new_due_at=monday_dt() + timedelta(hours=1)
    )
    assert result["status"] == ("skipped" if action == "skip" else "rescheduled")
    assert store.list_completed() == []
    with pytest.raises(PublicationNotReady):
        seam.retry_publication()
    with pytest.raises(PublicationNotReady):
        seam.complete_active_package()


def test_status_poll_transient_returns_uncertain_review_to_active(tmp_path):
    store, seam, _, meta, _ = make_seam(tmp_path)

    orig_status = meta.get_container_status

    def boom(container_id: str) -> str:
        raise RuntimeError("transient network error")

    meta.get_container_status = boom  # type: ignore[method-assign]
    try:
        prepare_approved_review(tmp_path, seam)
    finally:
        meta.get_container_status = orig_status  # type: ignore[method-assign]

    publishing = store.get_publishing()
    assert publishing is None
    status = seam.get_publication_status()
    assert status is not None and status["status"] == "uncertain"
    assert status["allowed_actions"] == ["retry", "review", "skip", "reschedule"]
    assert seam.list_pending_reviews()[0].status == "uncertain"


def test_publish_container_failure_is_uncertain_without_automatic_replay(tmp_path):

    store, seam, _, meta, _ = make_seam(tmp_path)
    meta.fail_publish = RuntimeError("response lost")
    prepare_approved_review(tmp_path, seam)

    publishing = store.get_publishing()
    assert publishing is None
    status = seam.get_publication_status()
    assert status is not None and status["status"] == "uncertain"
    assert store.list_completed() == []

    containers_before = len(meta.created)
    container_id = meta.created[0][2]
    meta.statuses = {container_id: "FINISHED"}
    seam.reconcile_publication()
    assert len(meta.created) == containers_before
    assert all(call == container_id for call in meta.publish_calls)
    assert len(meta.publish_calls) == 1


def test_worker_restart_leaves_uncertain_review_for_manual_decision(tmp_path):
    from worker.main import run_tick

    store, seam, renderer, meta, signed = make_seam(tmp_path)
    meta.fail_publish = MetaPublishUncertain("lost response")
    prepare_approved_review(tmp_path, seam)
    restarted = DojoPublishing(
        packages=store, audit=store, uploads=store, jobs=store, settings=store,
        media_root=tmp_path, clock=FakeClock(monday_dt()), meta=meta,
        signed_urls=signed, renderer=renderer,
    )
    run_tick(restarted)
    run_tick(restarted)
    assert len(meta.publish_calls) == 1
    assert store.list_completed() == []
    meta.statuses[meta.created[0][2]] = "PUBLISHED"
    run_tick(restarted)
    assert len(store.list_completed()) == 0
    assert len(meta.publish_calls) == 1


def test_unknown_creation_error_allows_explicit_retry(tmp_path):
    store, seam, _, meta, _ = make_seam(tmp_path)
    meta.fail_create = RuntimeError("lost response")
    prepare_approved_review(tmp_path, seam)
    assert store.get_publishing() is None
    assert seam.list_pending_reviews()[0].status == "uncertain"
    meta.fail_create = None
    seam.retry_publication()
    assert len(store.list_completed()) == 1


def test_reconcile_poll_error_restores_uncertain_review(tmp_path):
    store, seam, _, meta, _ = make_seam(tmp_path)
    meta.statuses = {"container_1": "IN_PROGRESS"}
    orig_create = meta.create_container

    def create_then_queue(url, caption):
        cid = orig_create(url, caption)
        meta.status_queues[cid] = ["IN_PROGRESS"]
        return cid

    meta.create_container = create_then_queue  # type: ignore[method-assign]
    prepare_approved_review(tmp_path, seam)
    publishing = store.get_publishing()
    assert publishing is not None

    orig_status = meta.get_container_status

    def boom(container_id: str) -> str:
        raise RuntimeError("status check timed out")

    meta.get_container_status = boom  # type: ignore[method-assign]
    try:
        seam.reconcile_publication()
    finally:
        meta.get_container_status = orig_status  # type: ignore[method-assign]

    assert store.get_publishing() is None
    status = seam.get_publication_status()
    assert status is not None and status["status"] == "uncertain"
    assert store.list_completed() == []


def test_publication_status_exposes_allowed_recovery_actions(tmp_path):
    # Issue #19: definite failure -> Retry/Review/Skip/Reschedule;
    # uncertain/publishing -> reconcile only, fresh publish prohibited.
    from dojo.exceptions import MetaPublishFailed as Failed

    store, seam, _, meta, _ = make_seam(tmp_path)
    meta.fail_create = Failed("rejected: bad video")
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

    status = seam.get_publication_status()
    assert status is not None and status["status"] == "failed"
    actions = set(status.get("allowed_actions") or [])
    assert {"retry", "review", "skip", "reschedule"} <= actions
    assert "publish" not in actions

    # uncertain state exposes reconcile only
    meta.fail_create = None
    seam.retry_publication(requester="7")
    assert len(store.list_completed()) == 1


def test_non_confirmed_packages_never_completed(tmp_path):
    # Issue #19: skipped/rescheduled/failed/auth-blocked never appear completed.
    from dojo.exceptions import MetaPublishFailed as Failed

    store, seam, _, meta, _ = make_seam(tmp_path)
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
    seam.skip(review.id, review.version, confirmed=True, requester="7")
    assert store.list_completed() == []

    # auth-blocked definite failure on a fresh seam also never completes
    second_root = tmp_path / "second"
    second_root.mkdir(exist_ok=True)
    store2, seam2, _, meta2, _ = make_seam(second_root)
    store2.set("branding.logo_asset", "logo.png", updated_at=FIXED_AT)
    seam2.set_plan(
        SchedulePlan(
            anchor_date=monday_dt().date(), anchor_time=monday_dt().time(), enabled=True
        )
    )
    seam2._clock = FakeClock(monday_dt())
    finalize_media(second_root, seam2, filename="pic2.jpg", seed=b"y" * 100)
    seam2.set_caption("again")
    seam2.evaluate_due_work()
    job = seam2.claim_next_job()
    assert job is not None
    seam2.process_job(job.job_id)
    review2 = seam2.list_pending_reviews()[0]
    meta2.fail_create = Failed("auth blocked: token invalid")
    seam2.approve(review2.id, review2.version, requester="7")
    assert store2.list_completed() == []
    status = seam2.get_publication_status()
    assert status is not None and status["status"] == "failed"
