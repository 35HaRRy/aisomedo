from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest
from dojo import (
    DojoPublishing,
    InMemoryStore,
    ManualPublishConflict,
    PlanInvalid,
    SchedulePlan,
)
from dojo.adapters.stubs import (
    StubMetaPublisher,
    StubNotifier,
    StubSignedUrlStore,
)
from dojo.testing import ISTANBUL, FakeClock


def make_seam(tmp_path):
    store = InMemoryStore()
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
    )
    return store, seam


def monday_dt() -> datetime:
    return datetime(2026, 8, 3, 10, 0, tzinfo=ISTANBUL)  # a Monday


def test_set_plan_validates_monday_anchor(tmp_path) -> None:
    _, seam = make_seam(tmp_path)
    seam.set_plan(
        SchedulePlan(anchor_date=date(2026, 8, 3), anchor_time=time(10, 0), enabled=True),
        requester="7",
    )
    with pytest.raises(PlanInvalid):
        seam.set_plan(
            SchedulePlan(anchor_date=date(2026, 8, 4), anchor_time=time(10, 0))
        )
    with pytest.raises(PlanInvalid):
        seam.set_plan(SchedulePlan(anchor_date=None, anchor_time=None))
    assert seam.list_audit()[0].action == "plan.updated"
    assert seam.list_audit()[0].actor == "7"


def test_get_plan_defaults_disabled(tmp_path) -> None:
    _, seam = make_seam(tmp_path)
    plan = seam.get_plan()
    assert plan.anchor_date is None
    assert plan.enabled is False


def test_ensure_schedule_upto_backfills_and_one_future_row(tmp_path) -> None:
    store, seam = make_seam(tmp_path)
    anchor = monday_dt()
    seam.set_plan(
        SchedulePlan(anchor_date=anchor.date(), anchor_time=anchor.time(), enabled=True)
    )
    now = anchor + timedelta(days=21)  # three Mondays later
    seam._clock = FakeClock(now)
    seam.ensure_schedule_upto(now)

    reg = [o for o in store.list_all() if o.kind == "regular"]
    due = [o.due_at for o in store.list_due(now)]
    # Mondays at +0, +14, +21(+14 would be the future row) up to now
    assert due == [anchor, anchor + timedelta(days=14)]
    # exactly one future row: the next Monday after now
    future = [o for o in reg if o.due_at > now]
    assert len(future) == 1
    assert future[0].due_at == anchor + timedelta(days=28)


def test_ensure_schedule_upto_idempotent_across_restart(tmp_path) -> None:
    store, seam = make_seam(tmp_path)
    anchor = monday_dt()
    seam.set_plan(
        SchedulePlan(anchor_date=anchor.date(), anchor_time=anchor.time(), enabled=True)
    )
    now = anchor + timedelta(days=35)
    seam._clock = FakeClock(now)
    seam.ensure_schedule_upto(now)
    count_before = len(store.list_all())

    # "restart": a fresh seam sharing the same store
    seam2 = DojoPublishing(
        packages=store, audit=store, uploads=store, jobs=store, settings=store,
        media_root=tmp_path, clock=FakeClock(now),
        meta=StubMetaPublisher(), notifier=StubNotifier(), signed_urls=StubSignedUrlStore(),
    )
    seam2.ensure_schedule_upto(now)

    assert len(store.list_all()) == count_before


def test_plan_edit_reflected_in_future_rows(tmp_path) -> None:
    store, seam = make_seam(tmp_path)
    old = monday_dt()
    seam.set_plan(
        SchedulePlan(anchor_date=old.date(), anchor_time=old.time(), enabled=True)
    )
    now = old + timedelta(days=21)
    seam._clock = FakeClock(now)
    seam.ensure_schedule_upto(now)

    # move anchor one biweekly step later
    new_anchor = old + timedelta(days=28)
    seam.set_plan(
        SchedulePlan(anchor_date=new_anchor.date(), anchor_time=new_anchor.time(), enabled=True)
    )
    seam.ensure_schedule_upto(now)

    reg = [o.due_at for o in store.list_all() if o.kind == "regular"]
    # future row now derives from the new anchor, not the old
    future = [d for d in reg if d > now]
    assert future == [new_anchor]


def test_forward_anchor_edit_prunes_stale_future_row(tmp_path) -> None:
    store, seam = make_seam(tmp_path)
    old = monday_dt()
    seam.set_plan(
        SchedulePlan(anchor_date=old.date(), anchor_time=old.time(), enabled=True)
    )
    now = old + timedelta(days=21)
    seam._clock = FakeClock(now)
    seam.ensure_schedule_upto(now)
    # old anchor produced a future row at old + 28
    assert store.has_regular_at(old + timedelta(days=28))

    # move the anchor forward beyond that future row
    new_anchor = old + timedelta(days=56)
    seam.set_plan(
        SchedulePlan(anchor_date=new_anchor.date(), anchor_time=new_anchor.time(), enabled=True)
    )
    seam.ensure_schedule_upto(now)

    reg = [o.due_at for o in store.list_all() if o.kind == "regular"]
    future = [d for d in reg if d > now]
    assert future == [new_anchor]  # stale old future row pruned


def test_manual_publish_creates_due_slot_without_shifting(tmp_path) -> None:
    store, seam = make_seam(tmp_path)
    anchor = monday_dt()
    seam.set_plan(
        SchedulePlan(anchor_date=anchor.date(), anchor_time=anchor.time(), enabled=True)
    )
    now = anchor + timedelta(days=21)
    seam._clock = FakeClock(now)
    seam.ensure_schedule_upto(now)
    regular_before = [o.due_at for o in store.list_all() if o.kind == "regular"]

    occ = seam.manual_publish(requester="8")

    assert occ.kind == "manual"
    assert occ.status == "pending"
    assert occ.due_at == now
    due = seam.list_due_occurrences(now)
    assert any(o.id == occ.id for o in due)
    # cadence unchanged: no new regular rows from manual publish
    regular_after = [o.due_at for o in store.list_all() if o.kind == "regular"]
    assert regular_after == regular_before
    assert seam.list_audit()[0].action == "schedule.manual_created"
    assert seam.list_audit()[0].actor == "8"


def test_second_manual_publish_conflict(tmp_path) -> None:
    store, seam = make_seam(tmp_path)
    seam.manual_publish(requester="9")
    with pytest.raises(ManualPublishConflict):
        seam.manual_publish(requester="10")
    # after resolving (marking resolved), a new manual is allowed
    pending = [o for o in store.list_all() if o.kind == "manual" and o.status == "pending"][0]
    resolved = pending.__class__(
        id=pending.id, kind=pending.kind, due_at=pending.due_at,
        status="resolved", created_at=pending.created_at, resolved_at=pending.due_at,
    )
    store._occurrences = [
        resolved if o.id == resolved.id else o for o in store._occurrences
    ]
    assert seam.manual_publish(requester="11").kind == "manual"


def test_manual_publish_allowed_when_plan_disabled(tmp_path) -> None:
    _, seam = make_seam(tmp_path)
    assert seam.manual_publish().kind == "manual"


def test_evaluate_due_work_materializes(tmp_path) -> None:
    store, seam = make_seam(tmp_path)
    anchor = monday_dt()
    seam.set_plan(
        SchedulePlan(anchor_date=anchor.date(), anchor_time=anchor.time(), enabled=True)
    )
    seam._clock = FakeClock(anchor + timedelta(days=21))
    seam.evaluate_due_work()
    assert len(store.list_all()) == 3  # two due + one future