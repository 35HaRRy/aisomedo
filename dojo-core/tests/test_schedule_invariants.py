from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import timedelta
from threading import Barrier

import pytest
from dojo import InMemoryStore, ManualPublishConflict, RescheduleTimeInvalid, SchedulePlan
from dojo.model import YayinIncelemesi, YayinZamani
from dojo.testing import FakeClock
from sqlalchemy.exc import IntegrityError

from tests.test_review import claim_render, finalize_media, make_seam, monday_dt, set_logo


def ready_review(tmp_path, *, caption=None):
    store, seam, _ = make_seam(tmp_path)
    seam._clock = FakeClock(monday_dt())
    set_logo(store, "logo.png")
    finalize_media(tmp_path, seam)
    if caption is not None:
        seam.set_caption(caption)
    seam.set_plan(SchedulePlan(monday_dt().date(), monday_dt().time(), enabled=True))
    seam.evaluate_due_work()
    claim_render(seam)
    return store, seam, seam.list_pending_reviews()[0]


def test_active_plan_always_has_one_pending_regular(tmp_path):
    store, seam, _ = make_seam(tmp_path)
    now = monday_dt() + timedelta(days=35)
    seam._clock = FakeClock(now)
    seam.set_plan(SchedulePlan(monday_dt().date(), monday_dt().time(), enabled=True))
    pending = [o for o in store.list_all() if o.kind == "regular" and o.status == "pending"]
    assert [o.due_at for o in pending] == [monday_dt() + timedelta(days=42)]
    seam.evaluate_due_work()
    assert len([o for o in store.list_all() if o.kind == "regular" and o.status == "pending"]) == 1
    seam._clock = FakeClock(now + timedelta(days=14))
    seam.evaluate_due_work()
    pending = [o for o in store.list_all() if o.kind == "regular" and o.status == "pending"]
    assert [o.due_at for o in pending] == [
        monday_dt() + timedelta(days=56),
    ]


@pytest.mark.parametrize("days", [14, 15])
@pytest.mark.parametrize("empty", [False, True])
def test_reschedule_rejects_next_regular_or_later_without_writes(tmp_path, days, empty):
    if empty:
        store, seam, _ = make_seam(tmp_path)
        seam._clock = FakeClock(monday_dt())
        package = seam.get_or_create_active_package()
        seam.set_plan(SchedulePlan(monday_dt().date(), monday_dt().time(), enabled=True))
        seam.ensure_schedule_upto()
        occurrence = seam.list_due_occurrences()[0]
    else:
        store, seam, review = ready_review(tmp_path)
    before = store.list_all(), list(store._reviews), seam.list_audit()
    with pytest.raises(RescheduleTimeInvalid):
        if empty:
            seam.reschedule_empty_occurrence(
                occurrence.id, package.folder_name, monday_dt() + timedelta(days=days),
            )
        else:
            seam.reschedule(review.id, review.version, monday_dt() + timedelta(days=days))
    assert (store.list_all(), store._reviews, seam.list_audit()) == before


def test_rescheduled_oneoff_is_next_and_blocks_manual_publish(tmp_path):
    store, seam, review = ready_review(tmp_path)
    due = monday_dt() + timedelta(days=1)
    resolved = seam.reschedule(review.id, review.version, due)
    summary = seam.get_dashboard_summary()
    assert (summary.next_slot.kind, summary.next_slot.due_at) == ("oneoff", due)
    assert summary.pending_actions == []
    with pytest.raises(ManualPublishConflict):
        seam.manual_publish()
    assert [o.id for o in store.list_all() if o.kind in ("manual", "oneoff")
            and o.status == "pending"] == [resolved.oneoff_occurrence_id]


def test_active_regular_review_blocks_manual_publish(tmp_path):
    _, seam, _ = ready_review(tmp_path)
    with pytest.raises(ManualPublishConflict):
        seam.manual_publish()


def test_new_regular_skips_old_review_and_creates_only_one_pending(tmp_path):
    store, seam, old = ready_review(tmp_path)
    seam._clock = FakeClock(monday_dt() + timedelta(days=14))
    seam.evaluate_due_work()
    pending = seam.list_pending_reviews()
    assert len(pending) == 1
    assert pending[0].occurrence_id != old.occurrence_id
    assert store.get(old.id).status == "skipped"
    assert store.get(old.id).version == old.version + 1
    assert next(o for o in store.list_all() if o.id == old.occurrence_id).status == "resolved"
    seam.evaluate_due_work()
    assert seam.list_pending_reviews() == pending


def test_new_oneoff_skips_old_review_before_render_is_ready(tmp_path):
    store, seam, old = ready_review(tmp_path)
    due = monday_dt() + timedelta(days=1)
    slot = store.create(YayinZamani(0, "oneoff", due, "pending", monday_dt()))
    seam.set_caption("New render required")
    seam._clock = FakeClock(due)
    seam.evaluate_due_work()
    assert store.get(old.id).status == "skipped"
    assert seam.list_pending_reviews() == []
    claim_render(seam)
    assert [r.occurrence_id for r in seam.list_pending_reviews()] == [slot.id]


def test_render_revision_replaces_review_instead_of_adding_pending(tmp_path):
    store, seam, old = ready_review(tmp_path)
    seam.set_caption("Updated caption")
    seam.render_preview()
    claim_render(seam)
    pending = seam.list_pending_reviews()
    assert len(pending) == 1
    assert pending[0].caption == "Updated caption"
    assert store.get(old.id).status == "skipped"


def test_returning_to_superseded_revision_reopens_it_with_a_new_version(tmp_path):
    store, seam, first = ready_review(tmp_path, caption="A")
    seam.set_caption("B")
    seam.render_preview()
    claim_render(seam)
    second = seam.list_pending_reviews()[0]
    seam.set_caption("A")
    seam.render_preview()
    claim_render(seam)
    pending = seam.list_pending_reviews()
    assert len(pending) == 1
    assert pending[0].id == first.id
    assert pending[0].version == first.version + 2
    assert pending[0].resolved_at is None
    assert pending[0].resolved_by is None
    assert store.get(second.id).status == "skipped"
    assert seam.get_review_detail(first.id)["render_ready"] is True
    seam.evaluate_due_work()
    assert seam.list_pending_reviews() == pending
    seam.skip(pending[0].id, pending[0].version, confirmed=True)
    seam.evaluate_due_work()
    assert seam.list_pending_reviews() == []  # Never reopen an actual user decision.


def test_manual_requests_serialize_across_seams(tmp_path):
    _, seam, _ = make_seam(tmp_path)
    barrier = Barrier(2)

    def request(_):
        barrier.wait(timeout=10)
        try:
            return seam.manual_publish().kind
        except ManualPublishConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(request, range(2))) == ["conflict", "manual"]


def test_reschedule_rolls_back_review_if_oneoff_creation_fails(tmp_path, monkeypatch):
    store, seam, review = ready_review(tmp_path)
    original_create = store.create

    def fail_oneoff(obj):
        if isinstance(obj, YayinZamani) and obj.kind == "oneoff":
            raise OSError("schedule unavailable")
        return original_create(obj)

    before = store.list_all(), list(store._reviews)
    monkeypatch.setattr(store, "create", fail_oneoff)
    with pytest.raises(OSError, match="schedule unavailable"):
        seam.reschedule(review.id, review.version, monday_dt() + timedelta(days=1))
    assert (store.list_all(), store._reviews) == before


def test_disabled_plan_does_not_limit_reschedule_to_old_regular(tmp_path):
    _, seam, review = ready_review(tmp_path)
    seam.set_plan(replace(seam.get_plan(), enabled=False))
    result = seam.reschedule(review.id, review.version, monday_dt() + timedelta(days=30))
    assert result.status == "rescheduled"


def test_reschedule_conflicts_with_an_existing_future_exception_without_writes(tmp_path):
    store, seam, review = ready_review(tmp_path)
    store.create(YayinZamani(0, "oneoff", monday_dt() + timedelta(days=2), "pending", monday_dt()))
    before = store.list_all(), list(store._reviews), seam.list_audit()
    with pytest.raises(ManualPublishConflict):
        seam.reschedule(review.id, review.version, monday_dt() + timedelta(days=1))
    assert (store.list_all(), store._reviews, seam.list_audit()) == before


def test_future_exception_blocks_manual_even_when_regular_is_earlier(tmp_path):
    store, seam, _ = make_seam(tmp_path)
    seam._clock = FakeClock(monday_dt())
    seam.set_plan(SchedulePlan(monday_dt().date(), monday_dt().time(), enabled=True))
    store.create(YayinZamani(0, "oneoff", monday_dt() + timedelta(days=20), "pending", monday_dt()))
    summary = seam.get_dashboard_summary()
    assert summary.next_slot.kind == "regular"
    assert asdict(summary).get("manual_review_allowed") is False
    with pytest.raises(ManualPublishConflict):
        seam.manual_publish()


@pytest.fixture(params=["memory", "postgres"])
def invariant_store(request):
    return InMemoryStore() if request.param == "memory" else request.getfixturevalue("pg_store")


@pytest.mark.parametrize("kinds", [("regular", "regular"), ("manual", "oneoff"),
                                  ("oneoff", "manual"), ("oneoff", "oneoff")])
def test_store_rejects_second_pending_occurrence_on_create_and_update(invariant_store, kinds):
    store = invariant_store
    first = store.create(YayinZamani(0, kinds[0], monday_dt(), "pending", monday_dt()))
    second = YayinZamani(0, kinds[1], monday_dt() + timedelta(days=1), "pending", monday_dt())
    with pytest.raises(IntegrityError):
        store.create(second)
    resolved = store.create(replace(second, status="resolved"))
    with pytest.raises(IntegrityError):
        store.update(replace(resolved, status="pending"))
    store.update(replace(first, status="due"))
    assert store.update(replace(resolved, status="pending")).status == "pending"


@pytest.mark.parametrize("status", ["pending", "failed", "uncertain", "publishing"])
def test_store_rejects_second_actionable_review(invariant_store, status):
    store = invariant_store
    first = store.create(YayinIncelemesi(0, 1, "active", "first", None, status, monday_dt()))
    second = YayinIncelemesi(0, 2, "active", "second", None, "pending", monday_dt())
    with pytest.raises(IntegrityError):
        store.create_review_once(second)
    resolved = store.create(replace(second, status="skipped"))
    with pytest.raises(IntegrityError):
        store.update(replace(resolved, status="pending"))
    store.update(replace(first, status="skipped"))
    assert store.update(replace(resolved, status="pending")).status == "pending"
