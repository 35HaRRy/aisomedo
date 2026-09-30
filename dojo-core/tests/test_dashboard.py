from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from dojo import DojoPublishing, SchedulePlan
from dojo.model import YayinZamani
from dojo.testing import ISTANBUL, FakeClock

from tests.test_review import claim_render, finalize_media, make_seam, set_logo, set_plan_due

NOW = datetime(2026, 8, 3, 10, tzinfo=ISTANBUL)


def test_dashboard_read_does_not_create_anything(tmp_path):
    _, seam, _ = make_seam(tmp_path)
    set_plan_due(seam, NOW)
    before = seam.list_audit()
    for _ in range(2):
        summary = seam.get_dashboard_summary()
        assert summary.package is None
        assert summary.pending_actions == []
        assert summary.next_slot.due_at == datetime(2026, 8, 17, 10, tzinfo=ISTANBUL)
    assert seam.get_active_package() is None
    assert seam.list_due_occurrences() == []
    assert seam.list_pending_reviews() == []
    assert seam.claim_next_job() is None
    assert seam.list_audit() == before


@pytest.mark.parametrize("kind", ["oneoff", "manual"])
def test_future_exception_beats_regular_and_resolved_is_excluded(tmp_path, kind):
    _, seam, _ = make_seam(tmp_path)
    set_plan_due(seam, NOW)
    slot = seam._schedule.create(YayinZamani(0, kind, NOW + timedelta(days=1), "pending", NOW))
    assert seam.get_dashboard_summary().next_slot.kind == kind
    seam._schedule.update(replace(slot, status="resolved"))
    assert seam.get_dashboard_summary().next_slot.due_at.day == 17


def test_disabled_and_changed_plan_ignore_old_regular_rows(tmp_path):
    _, seam, _ = make_seam(tmp_path)
    set_plan_due(seam, NOW)
    seam.ensure_schedule_upto()
    seam.set_plan(SchedulePlan(NOW.date() + timedelta(days=7), NOW.time()))
    assert seam.get_dashboard_summary().next_slot.due_at.day == 10
    seam.set_plan(SchedulePlan(NOW.date(), NOW.time(), enabled=False))
    assert seam.get_dashboard_summary().next_slot is None


def test_overdue_empty_slot_is_pending_action_not_future(tmp_path):
    _, seam, _ = make_seam(tmp_path)
    set_plan_due(seam, NOW)
    slot = seam.manual_publish()
    summary = seam.get_dashboard_summary()
    assert summary.pending_actions[0].occurrence_id == slot.id
    assert summary.pending_actions[0].state == "empty_package"
    assert summary.pending_actions[0].review_id is None
    assert summary.next_slot.due_at > NOW


def test_due_review_refresh_retains_versions_and_resolves(tmp_path):
    store, seam, _ = make_seam(tmp_path)
    set_logo(store, "logo.png")
    finalize_media(tmp_path, seam)
    set_plan_due(seam, NOW)
    seam.evaluate_due_work()
    assert seam.get_dashboard_summary().pending_actions[0].state == "preparing"
    claim_render(seam)
    review = seam.list_pending_reviews()[0]
    action = seam.get_dashboard_summary().pending_actions[0]
    assert (action.review_id, action.version, action.state) == (review.id, 1, "review_ready")
    seam.set_caption("Changed after render")
    assert seam.get_dashboard_summary().pending_actions[0].state == "preparing"
    seam.skip(review.id, review.version, confirmed=True)
    assert seam.get_dashboard_summary().pending_actions == []


def test_multiple_reviews_and_publishing_package_remain_visible(tmp_path):
    store, seam, _ = make_seam(tmp_path)
    set_logo(store, "logo.png")
    finalize_media(tmp_path, seam)
    set_plan_due(seam, NOW)
    seam.manual_publish()
    seam.evaluate_due_work()
    claim_render(seam)
    assert len(seam.get_dashboard_summary().pending_actions) == 2
    package = seam.get_active_package()
    store.update(replace(package, status="publishing"))
    assert seam.get_dashboard_summary().package.status == "publishing"


def test_persisted_exception_visible_after_seam_restart(pg_store, tmp_path):
    seam = DojoPublishing(packages=pg_store, audit=pg_store, settings=pg_store,
                          media_root=tmp_path, clock=FakeClock(NOW))
    seam._schedule.create(YayinZamani(0, "oneoff", NOW + timedelta(days=1), "pending", NOW))
    restarted = DojoPublishing(packages=pg_store, audit=pg_store, settings=pg_store,
                               media_root=tmp_path, clock=FakeClock(NOW))
    assert restarted.get_dashboard_summary().next_slot.due_at == NOW + timedelta(days=1)
