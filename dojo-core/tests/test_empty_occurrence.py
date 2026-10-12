from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier

import pytest
from dojo import DojoPublishing, RescheduleTimeInvalid, SkipRequiresConfirmation, exceptions
from dojo.model import YayinIncelemesi, YayinZamani
from dojo.testing import FakeClock

from tests.test_review import (
    claim_render,
    finalize_media,
    make_seam,
    monday_dt,
    set_logo,
    set_plan_due,
)


def empty_context(tmp_path, store=None):
    if store is None:
        store, seam, _ = make_seam(tmp_path)
    else:
        seam = DojoPublishing(packages=store, audit=store, settings=store,
                              media_root=tmp_path, clock=FakeClock(monday_dt()))
    set_plan_due(seam, monday_dt())
    package = seam.get_or_create_active_package()
    seam.ensure_schedule_upto()
    occurrence = seam.list_due_occurrences()[0]
    return store, seam, package.folder_name, occurrence


def test_empty_skip_requires_confirmation_and_preserves_package(tmp_path):
    store, seam, folder, occ = empty_context(tmp_path)
    before = store.list_all()
    with pytest.raises(SkipRequiresConfirmation):
        seam.skip_empty_occurrence(occ.id, folder, confirmed=False)
    assert store.list_all() == before
    result = seam.skip_empty_occurrence(occ.id, folder, confirmed=True, requester="9")
    assert result == {
        "occurrence_id": occ.id, "package_folder": folder, "status": "skipped",
        "next_regular_at": monday_dt() + timedelta(days=14),
        "oneoff_occurrence_id": None, "new_due_at": None,
    }
    assert seam.get_active_package().folder_name == folder
    assert seam.list_pending_reviews() == []
    assert store.list_all()[0].status == "resolved"
    event = seam.list_audit()[0]
    assert (event.action, event.actor) == ("occurrence.skipped", "9")


@pytest.mark.parametrize("kind", ["regular", "manual", "oneoff"])
def test_empty_reschedule_preserves_plan_and_reuses_oneoff(tmp_path, kind):
    store, seam, folder, regular = empty_context(tmp_path)
    occ = regular if kind == "regular" else store.create(
        YayinZamani(0, kind, monday_dt(), "pending", monday_dt()),
    )
    plan = seam.get_plan()
    future = monday_dt() + timedelta(days=1)
    result = seam.reschedule_empty_occurrence(occ.id, folder, future, requester="9")
    assert result["status"] == "rescheduled"
    assert result["new_due_at"] == future
    assert seam.get_plan() == plan
    oneoffs = [o for o in store.list_all() if o.kind == "oneoff" and o.status == "pending"]
    assert len(oneoffs) == 1
    assert oneoffs[0].due_at == future
    assert result["oneoff_occurrence_id"] == oneoffs[0].id
    if kind == "oneoff":
        assert oneoffs[0].id == occ.id
    else:
        assert next(o for o in store.list_all() if o.id == occ.id).status == "resolved"
    assert seam.list_pending_reviews() == []
    assert seam.get_active_package().folder_name == folder
    assert (seam.list_audit()[0].action, seam.list_audit()[0].actor) == (
        "occurrence.rescheduled", "9",
    )


@pytest.mark.parametrize("change", ["folder", "resolved", "future", "publishing", "review"])
@pytest.mark.parametrize("action", ["skip", "reschedule"])
def test_empty_decisions_reject_changed_context_without_writes(tmp_path, change, action):
    store, seam, folder, occ = empty_context(tmp_path)
    if change == "folder":
        folder = "old-package"
    elif change == "resolved":
        store.update(replace(occ, status="resolved", resolved_at=monday_dt()))
    elif change == "future":
        store.update(replace(occ, due_at=monday_dt() + timedelta(days=1)))
    elif change == "publishing":
        store.update(replace(seam.get_active_package(), status="publishing"))
    elif change == "review":
        # Even a historical review is not the empty-stage decision contract.
        store.create(YayinIncelemesi(0, occ.id, folder, "digest", "caption", "rescheduled",
                                    monday_dt()))
    before, audit = store.list_all(), seam.list_audit()
    with pytest.raises((exceptions.OccurrenceChanged, exceptions.PublicationInProgress)):
        if action == "skip":
            seam.skip_empty_occurrence(occ.id, folder, confirmed=True)
        else:
            seam.reschedule_empty_occurrence(occ.id, folder, monday_dt() + timedelta(days=2))
    assert store.list_all() == before
    assert seam.list_audit() == audit


def test_empty_decisions_reject_missing_occurrence(tmp_path):
    _, seam, folder, _ = empty_context(tmp_path)
    with pytest.raises(exceptions.OccurrenceNotFound):
        seam.skip_empty_occurrence(999, folder, confirmed=True)
    with pytest.raises(exceptions.OccurrenceNotFound):
        seam.reschedule_empty_occurrence(999, folder, monday_dt() + timedelta(days=1))


@pytest.mark.parametrize("delta", [timedelta(), timedelta(seconds=-1)])
def test_empty_reschedule_rejects_now_and_past_without_writes(tmp_path, delta):
    store, seam, folder, occ = empty_context(tmp_path)
    before = store.list_all()
    with pytest.raises(RescheduleTimeInvalid):
        seam.reschedule_empty_occurrence(occ.id, folder, monday_dt() + delta)
    assert store.list_all() == before


@pytest.mark.parametrize("rendered", [False, True])
def test_late_empty_decision_rejects_finalized_or_reviewed_context(tmp_path, rendered):
    store, seam, folder, occ = empty_context(tmp_path)
    finalize_media(tmp_path, seam)
    if rendered:
        set_logo(store, "logo.png")
        seam.evaluate_due_work()
        claim_render(seam)
    reviews = seam.list_pending_reviews()
    with pytest.raises(exceptions.OccurrenceChanged):
        seam.skip_empty_occurrence(occ.id, folder, confirmed=True)
    with pytest.raises(exceptions.OccurrenceChanged):
        seam.reschedule_empty_occurrence(occ.id, folder, monday_dt() + timedelta(days=1))
    assert seam.list_pending_reviews() == reviews
    assert store.list_all()[0].status == "pending"


def test_empty_decision_race_has_one_winner(pg_store, tmp_path):
    _, seam, folder, occ = empty_context(tmp_path, pg_store)
    other = DojoPublishing(packages=pg_store, audit=pg_store, settings=pg_store,
                           media_root=tmp_path, clock=FakeClock(monday_dt()))
    barrier = Barrier(2)

    def decide(skip):
        barrier.wait(timeout=10)
        try:
            if skip:
                return seam.skip_empty_occurrence(occ.id, folder, confirmed=True)["status"]
            return other.reschedule_empty_occurrence(
                occ.id, folder, monday_dt() + timedelta(days=1),
            )["status"]
        except exceptions.OccurrenceChanged:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(decide, [True, False]))
    assert results.count("conflict") == 1
    assert next(o for o in pg_store.list_all() if o.id == occ.id).status == "resolved"


def test_finalization_before_empty_decision_conflicts_across_seams(pg_store, tmp_path):
    _, seam, folder, occ = empty_context(tmp_path, pg_store)
    finalize_media(tmp_path, seam)
    other = DojoPublishing(packages=pg_store, audit=pg_store, settings=pg_store,
                           media_root=tmp_path, clock=FakeClock(monday_dt()))
    with pytest.raises(exceptions.OccurrenceChanged):
        other.skip_empty_occurrence(occ.id, folder, confirmed=True)


@pytest.mark.parametrize("action", ["skip", "reschedule"])
def test_empty_decision_rolls_back_schedule_if_audit_fails(pg_store, tmp_path, monkeypatch, action):
    _, seam, folder, occ = empty_context(tmp_path, pg_store)
    before = pg_store.list_all()

    def fail(event):
        raise OSError("audit unavailable")

    monkeypatch.setattr(pg_store, "append", fail)
    with pytest.raises(OSError, match="audit unavailable"):
        if action == "skip":
            seam.skip_empty_occurrence(occ.id, folder, confirmed=True)
        else:
            seam.reschedule_empty_occurrence(occ.id, folder, monday_dt() + timedelta(days=1))
    assert pg_store.list_all() == before
