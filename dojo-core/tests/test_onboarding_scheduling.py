from datetime import date, time
from pathlib import Path

import pytest
from dojo import DojoPublishing, SchedulePlan
from dojo.model import YayinZamani

from tests.test_onboarding import configured_setup
from tests.test_review import claim_render, finalize_media, make_seam, monday_dt, set_plan_due


def test_scheduler_requires_ready_setup_and_enabled_plan(tmp_path: Path) -> None:
    setup, store = configured_setup()
    publishing = DojoPublishing(packages=store, audit=store, media_root=tmp_path, setup=setup)
    publishing.set_plan(SchedulePlan(
        anchor_date=date(2026, 10, 5), anchor_time=time(10), enabled=False,
    ))
    publishing.ensure_schedule_upto()
    assert store.list_all() == []
    client = store.find_client_by_id(1)
    assert client is not None
    setup.set_policy(version=2, text="v2", requester="cli")
    publishing.set_plan(SchedulePlan(
        anchor_date=date(2026, 10, 5), anchor_time=time(10), enabled=True,
    ))
    publishing.evaluate_due_work()
    assert store.list_all() == []
    setup.accept_current_policy(client=client, version=2)
    publishing.ensure_schedule_upto()
    assert len(store.list_all()) > 0


@pytest.mark.parametrize("change", ["policy", "disabled"])
def test_queued_render_does_not_emit_review_after_gate_changes(
    tmp_path: Path, change: str,
) -> None:
    setup, setup_store = configured_setup()
    store, publishing, _ = make_seam(tmp_path)
    publishing._setup = setup
    store.set("branding.logo_asset", "logo.png", updated_at=publishing._clock.now())
    finalize_media(tmp_path, publishing)
    set_plan_due(publishing, monday_dt())
    publishing.evaluate_due_work()
    if change == "policy":
        setup.set_policy(version=2, text="v2", requester="cli")
    else:
        publishing.set_plan(SchedulePlan(
            anchor_date=monday_dt().date(), anchor_time=time(10), enabled=False,
        ))
    claim_render(publishing)
    assert publishing.list_pending_reviews() == []
    if change == "policy":
        client = setup_store.find_client_by_id(1)
        assert client is not None
        setup.accept_current_policy(client=client, version=2)
    else:
        publishing.set_plan(SchedulePlan(
            anchor_date=monday_dt().date(), anchor_time=time(10), enabled=True,
        ))
    publishing.evaluate_due_work()
    assert len(publishing.list_pending_reviews()) == 1
    assert publishing.claim_next_job() is None


def test_disabled_regular_plan_does_not_block_manual_occurrence(tmp_path: Path) -> None:
    store, publishing, _ = make_seam(tmp_path)
    store.set("branding.logo_asset", "logo.png", updated_at=publishing._clock.now())
    finalize_media(tmp_path, publishing)
    store.create(YayinZamani(
        id=0, kind="oneoff", due_at=publishing._clock.now(),
        status="pending", created_at=publishing._clock.now(),
    ))
    publishing.evaluate_due_work()
    claim_render(publishing)
    assert len(publishing.list_pending_reviews()) == 1
