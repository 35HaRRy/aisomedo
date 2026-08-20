from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from dojo import (
    DojoPublishing,
    InMemoryStore,
    SchedulePlan,
)
from dojo.adapters.stubs import (
    StubMediaProcessor,
    StubMetaPublisher,
    StubNotifier,
    StubReelRenderer,
    StubSignedUrlStore,
)
from dojo.testing import FIXED_AT, ISTANBUL, FakeClock


def make_seam(tmp_path):
    store = InMemoryStore()
    renderer = StubReelRenderer()
    seam = DojoPublishing(
        packages=store,
        audit=store,
        uploads=store,
        jobs=store,
        settings=store,
        media_root=tmp_path,
        clock=FakeClock(),
        meta=StubMetaPublisher(),
        notifier=StubNotifier(),
        signed_urls=StubSignedUrlStore(),
        renderer=renderer,
    )
    return store, seam, renderer


def monday_dt() -> datetime:
    return datetime(2026, 8, 3, 10, 0, tzinfo=ISTANBUL)


def set_plan_due(seam, now: datetime) -> datetime:
    anchor = monday_dt()
    seam.set_plan(
        SchedulePlan(anchor_date=anchor.date(), anchor_time=anchor.time(), enabled=True)
    )
    seam._clock = FakeClock(now)
    return now


def set_logo(store, path: str) -> None:
    store.set("branding.logo_asset", path, updated_at=FIXED_AT)


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


def test_due_occurrence_creates_one_durable_review(tmp_path) -> None:
    store, seam, renderer = make_seam(tmp_path)
    set_logo(store, "logo.png")
    finalize_media(tmp_path, seam)
    set_plan_due(seam, monday_dt())

    seam.evaluate_due_work()
    assert seam.list_pending_reviews() == []  # render not yet completed
    claim_render(seam)

    reviews = seam.list_pending_reviews()
    assert len(reviews) == 1
    assert reviews[0].status == "pending"
    assert reviews[0].package_folder == seam.get_active_package().folder_name
    assert reviews[0].revision_digest
    assert "review.created" in [e.action for e in seam.list_audit()]


def test_reviews_idempotent_across_rerun_and_restart(tmp_path) -> None:
    store, seam, renderer = make_seam(tmp_path)
    set_logo(store, "logo.png")
    finalize_media(tmp_path, seam)
    now = set_plan_due(seam, monday_dt())

    seam.evaluate_due_work()
    claim_render(seam)
    assert len(seam.list_pending_reviews()) == 1

    # scheduler re-run: render now fresh -> direct path, no new review, no new render job
    seam.evaluate_due_work()
    assert seam.claim_next_job() is None
    assert len(seam.list_pending_reviews()) == 1

    # "restart": a fresh seam sharing the same store must not add a review
    seam2 = DojoPublishing(
        packages=store, audit=store, uploads=store, jobs=store, settings=store,
        media_root=tmp_path, clock=FakeClock(now),
        meta=StubMetaPublisher(), notifier=StubNotifier(),
        signed_urls=StubSignedUrlStore(), renderer=renderer,
    )
    seam2.evaluate_due_work()
    assert len(seam2.list_pending_reviews()) == 1


def test_fresh_render_creates_review_without_rerender(tmp_path) -> None:
    store, seam, renderer = make_seam(tmp_path)
    set_logo(store, "logo.png")
    finalize_media(tmp_path, seam)
    seam.render_preview()
    claim_render(seam)  # render already materialized, no due occurrence yet

    set_plan_due(seam, monday_dt())
    seam.evaluate_due_work()

    assert seam.claim_next_job() is None  # no re-render enqueued
    assert len(seam.list_pending_reviews()) == 1


def test_review_snapshots_caption(tmp_path) -> None:
    store, seam, renderer = make_seam(tmp_path)
    set_logo(store, "logo.png")
    finalize_media(tmp_path, seam)
    seam.set_caption("dojo monday recap")
    set_plan_due(seam, monday_dt())

    seam.evaluate_due_work()
    claim_render(seam)

    reviews = seam.list_pending_reviews()
    assert len(reviews) == 1
    assert reviews[0].caption == "dojo monday recap"


def test_empty_package_at_due_creates_no_review_and_stays_pending(tmp_path) -> None:
    store, seam, renderer = make_seam(tmp_path)
    seam.get_or_create_active_package()  # empty active package
    now = set_plan_due(seam, monday_dt())

    seam.evaluate_due_work()

    assert seam.list_pending_reviews() == []
    due = seam.list_due_occurrences(now)
    assert len(due) == 1
    assert due[0].status == "pending"


def test_upload_after_empty_due_reviews_same_package(tmp_path) -> None:
    store, seam, renderer = make_seam(tmp_path)
    seam.get_or_create_active_package()
    now = set_plan_due(seam, monday_dt())

    seam.evaluate_due_work()
    assert seam.list_pending_reviews() == []
    folder_before = seam.get_active_package().folder_name

    set_logo(store, "logo.png")
    finalize_media(tmp_path, seam)  # same active package, no new folder
    assert seam.get_active_package().folder_name == folder_before

    seam.evaluate_due_work()
    claim_render(seam)

    reviews = seam.list_pending_reviews()
    assert len(reviews) == 1
    assert reviews[0].package_folder == folder_before
    assert seam.get_active_package().folder_name == folder_before
    assert len(seam.list_due_occurrences(now)) == 1


def test_review_is_durable_after_time_passes(tmp_path) -> None:
    store, seam, renderer = make_seam(tmp_path)
    set_logo(store, "logo.png")
    finalize_media(tmp_path, seam)
    now = set_plan_due(seam, monday_dt())

    seam.evaluate_due_work()
    claim_render(seam)
    assert len(seam.list_pending_reviews()) == 1

    # time passes (late approval window); the review persists with no new folder
    folder_before = seam.get_active_package().folder_name
    seam._clock = FakeClock(now + timedelta(days=3))
    seam.evaluate_due_work()
    assert len(seam.list_pending_reviews()) == 1
    assert seam.get_active_package().folder_name == folder_before