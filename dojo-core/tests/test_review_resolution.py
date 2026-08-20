from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

import pytest
from dojo import (
    DojoPublishing,
    InMemoryStore,
    RescheduleTimeInvalid,
    ReviewAlreadyHandled,
    ReviewNotFound,
    ReviewStale,
    SchedulePlan,
    SkipRequiresConfirmation,
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


def create_due_review(tmp_path, seam, *, caption=None):
    seam.set_plan(
        SchedulePlan(
            anchor_date=monday_dt().date(),
            anchor_time=monday_dt().time(),
            enabled=True,
        )
    )
    seam._clock = FakeClock(monday_dt())
    finalize_media(tmp_path, seam)
    if caption is not None:
        seam.set_caption(caption)
    seam.evaluate_due_work()
    claim_render(seam)
    reviews = seam.list_pending_reviews()
    assert len(reviews) == 1
    return reviews[0]


def test_approve_resolves_review_and_occurrence(tmp_path) -> None:
    store, seam, _ = make_seam(tmp_path)
    store.set("branding.logo_asset", "logo.png", updated_at=FIXED_AT)
    review = create_due_review(tmp_path, seam)

    resolved = seam.approve(review.id, review.version, requester="7")

    assert resolved.status == "approved"
    assert resolved.resolved_by == "7"
    assert resolved.version == review.version + 1
    assert resolved.resolved_at == monday_dt()
    assert seam.list_pending_reviews() == []
    occ = [o for o in store.list_all() if o.id == review.occurrence_id][0]
    assert occ.status == "resolved"
    assert occ.resolved_at == monday_dt()
    actions = [e.action for e in seam.list_audit()]
    assert "review.approved" in actions


def test_racing_approve_skip_reschedule_exactly_one_winner(tmp_path) -> None:
    store, seam, _ = make_seam(tmp_path)
    store.set("branding.logo_asset", "logo.png", updated_at=FIXED_AT)
    review = create_due_review(tmp_path, seam)
    version = review.version

    # three independent seams sharing one store race the same review+version
    seam2 = DojoPublishing(
        packages=store, audit=store, uploads=store, jobs=store, settings=store,
        media_root=tmp_path, clock=FakeClock(monday_dt()),
        meta=StubMetaPublisher(), notifier=StubNotifier(),
        signed_urls=StubSignedUrlStore(), renderer=StubReelRenderer(),
    )
    seam3 = DojoPublishing(
        packages=store, audit=store, uploads=store, jobs=store, settings=store,
        media_root=tmp_path, clock=FakeClock(monday_dt()),
        meta=StubMetaPublisher(), notifier=StubNotifier(),
        signed_urls=StubSignedUrlStore(), renderer=StubReelRenderer(),
    )

    approved = seam.approve(review.id, version, requester="A")
    with pytest.raises(ReviewAlreadyHandled) as skip_err:
        seam2.skip(review.id, version, confirmed=True, requester="B")
    with pytest.raises(ReviewAlreadyHandled) as resched_err:
        seam3.reschedule(
            review.id,
            version,
            monday_dt() + timedelta(days=1),
            requester="C",
        )

    # one winner: the approved review
    assert approved.status == "approved"
    # losers carry the authoritative winning state
    assert skip_err.value.review.status == "approved"
    assert resched_err.value.review.status == "approved"
    assert len(seam.list_pending_reviews()) == 0
    # the approved review is resolved; losers added no occurrence changes
    occ = [o for o in store.list_all() if o.id == review.occurrence_id][0]
    assert occ.status == "resolved"


def test_stale_review_action_rejected(tmp_path) -> None:
    store, seam, _ = make_seam(tmp_path)
    store.set("branding.logo_asset", "logo.png", updated_at=FIXED_AT)
    review = create_due_review(tmp_path, seam, caption="dojo recap")

    # content edited after review was created -> new digest -> stale action
    seam.set_caption("dojo recap edited")
    seam.render_preview()
    claim_render(seam)

    with pytest.raises(ReviewStale):
        seam.approve(review.id, review.version, requester="7")


def test_approve_unknown_review_raises(tmp_path) -> None:
    _, seam, _ = make_seam(tmp_path)
    with pytest.raises(ReviewNotFound):
        seam.approve(999, 1)


def test_skip_requires_confirmation(tmp_path) -> None:
    store, seam, _ = make_seam(tmp_path)
    store.set("branding.logo_asset", "logo.png", updated_at=FIXED_AT)
    review = create_due_review(tmp_path, seam)

    with pytest.raises(SkipRequiresConfirmation):
        seam.skip(review.id, review.version, confirmed=False)

    # nothing changed
    assert seam.list_pending_reviews()[0].status == "pending"


def test_skip_resolves_and_returns_next_regular_time(tmp_path) -> None:
    store, seam, _ = make_seam(tmp_path)
    store.set("branding.logo_asset", "logo.png", updated_at=FIXED_AT)
    review = create_due_review(tmp_path, seam)
    folder_before = seam.get_active_package().folder_name

    result = seam.skip(review.id, review.version, confirmed=True, requester="9")

    assert result.review.status == "skipped"
    # next regular occurrence: two weeks later
    assert result.next_regular_at == monday_dt() + timedelta(days=14)
    assert seam.list_pending_reviews() == []
    assert seam.get_active_package().folder_name == folder_before
    occ = [o for o in store.list_all() if o.id == review.occurrence_id][0]
    assert occ.status == "resolved"


def test_reschedule_requires_future_time(tmp_path) -> None:
    store, seam, _ = make_seam(tmp_path)
    store.set("branding.logo_asset", "logo.png", updated_at=FIXED_AT)
    review = create_due_review(tmp_path, seam)

    with pytest.raises(RescheduleTimeInvalid):
        seam.reschedule(
            review.id, review.version, monday_dt() - timedelta(hours=1)
        )
    with pytest.raises(RescheduleTimeInvalid):
        seam.reschedule(review.id, review.version, monday_dt())


def test_reschedule_creates_oneoff_and_replaces_prior(tmp_path) -> None:
    store, seam, _ = make_seam(tmp_path)
    store.set("branding.logo_asset", "logo.png", updated_at=FIXED_AT)
    review = create_due_review(tmp_path, seam)
    regular_before = [
        o.due_at for o in store.list_all() if o.kind == "regular"
    ]

    first_time = monday_dt() + timedelta(days=1)
    resolved = seam.reschedule(review.id, review.version, first_time, requester="5")

    oneoff = [o for o in store.list_all() if o.kind == "oneoff"]
    assert len(oneoff) == 1
    assert oneoff[0].status == "pending"
    assert oneoff[0].due_at == first_time
    assert resolved.status == "rescheduled"
    assert resolved.oneoff_occurrence_id == oneoff[0].id
    # recurring cadence unchanged
    regular_after = [o.due_at for o in store.list_all() if o.kind == "regular"]
    assert regular_after == regular_before
    # original occurrence resolved
    occ = [o for o in store.list_all() if o.id == review.occurrence_id][0]
    assert occ.status == "resolved"

    # second reschedule replaces the prior one-off via a new review created
    # for the pending oneoff (as #14 would when it becomes due)
    oneoff_id = oneoff[0].id
    seam._clock = FakeClock(first_time)
    seam.evaluate_due_work()
    new_reviews = seam.list_pending_reviews()
    assert len(new_reviews) == 1
    new_review = new_reviews[0]
    assert new_review.occurrence_id == oneoff_id

    second_time = monday_dt() + timedelta(days=2)
    resolved2 = seam.reschedule(
        new_review.id, new_review.version, second_time, requester="6"
    )
    oneoff_after = [o for o in store.list_all() if o.kind == "oneoff"]
    assert len(oneoff_after) == 1
    assert oneoff_after[0].id == oneoff_id
    assert oneoff_after[0].due_at == second_time
    assert resolved2.oneoff_occurrence_id == oneoff_id


def test_reschedule_naive_time_treated_as_local_zone(tmp_path) -> None:
    store, seam, _ = make_seam(tmp_path)
    store.set("branding.logo_asset", "logo.png", updated_at=FIXED_AT)
    review = create_due_review(tmp_path, seam)

    naive_future = monday_dt().replace(tzinfo=None) + timedelta(days=1)
    resolved = seam.reschedule(review.id, review.version, naive_future)

    assert resolved.status == "rescheduled"
    oneoff = [o for o in store.list_all() if o.kind == "oneoff"][0]
    assert oneoff.due_at == naive_future.replace(tzinfo=ISTANBUL)


def test_reschedule_emits_single_audit_event(tmp_path) -> None:
    store, seam, _ = make_seam(tmp_path)
    store.set("branding.logo_asset", "logo.png", updated_at=FIXED_AT)
    review = create_due_review(tmp_path, seam)

    seam.reschedule(
        review.id, review.version, monday_dt() + timedelta(days=1), requester="5"
    )

    events = [e for e in seam.list_audit() if e.action == "review.rescheduled"]
    assert len(events) == 1