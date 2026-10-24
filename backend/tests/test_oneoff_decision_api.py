from dataclasses import replace
from datetime import timedelta

import pytest
from dojo import YayinZamani
from dojo.adapters.stubs import StubReelRenderer
from dojo.testing import FIXED_AT
from test_dashboard_api import paired
from test_package_editor_api import app


def decide(client, slot, action="review", **extra):
    return client.post(f"/api/dashboard/occurrences/{slot.id}/decision", json={
        "expected_due_at": slot.due_at.isoformat(), "action": action, **extra,
    })


def future(publishing):
    return publishing._schedule.create(YayinZamani(
        0, "oneoff", FIXED_AT + timedelta(days=1), "pending", FIXED_AT,
    ))


def test_review_moves_same_occurrence_to_server_now_and_worker_creates_exact_review(tmp_path):
    client, publishing, _, _, _ = app(tmp_path)
    publishing._renderer = StubReelRenderer()
    publishing._settings.set("branding.logo_asset", "logo.png", updated_at=FIXED_AT)
    slot = future(publishing)
    response = decide(client, slot)
    assert response.status_code == 200
    assert response.json() == {
        "occurrence_id": slot.id, "due_at": FIXED_AT.isoformat(), "status": "pending",
        "package_folder": publishing.get_active_package().folder_name,
    }
    assert publishing._schedule.list_all() == [replace(slot, due_at=FIXED_AT)]
    assert publishing.list_pending_reviews() == []  # API never renders or publishes.
    assert decide(client, slot).status_code == 409
    publishing.evaluate_due_work()
    job = publishing.claim_next_job()
    while job is not None and job.kind in ("thumbnail", "section_preview"):
        publishing.process_job(job.job_id)
        job = publishing.claim_next_job()
    assert job is not None and job.kind == "render"
    publishing.process_job(job.job_id)
    publishing.evaluate_due_work()
    reviews = publishing.list_pending_reviews()
    assert len(reviews) == 1
    assert reviews[0].occurrence_id == slot.id
    assert reviews[0].status == "pending"
    assert client.get(f"/api/reviews/{reviews[0].id}").json()["render_ready"] is True


def test_skip_requires_confirmation_preserves_package_and_never_emits_review(tmp_path):
    client, publishing, _, cid, _ = app(tmp_path)
    slot = future(publishing)
    package = publishing.get_active_package()
    before = publishing._schedule.list_all(), publishing.list_audit()
    assert decide(client, slot, "skip").status_code == 400
    assert (publishing._schedule.list_all(), publishing.list_audit()) == before
    version = client.get("/api/dashboard").headers["x-resource-version"]
    response = decide(client, slot, "skip", confirmed=True)
    assert response.status_code == 200
    assert response.json()["status"] == "skipped"
    assert publishing._schedule.list_all() == [
        replace(slot, status="skipped", resolved_at=FIXED_AT),
    ]
    assert publishing.get_active_package() == package
    refreshed = client.get("/api/dashboard")
    assert int(refreshed.headers["x-resource-version"]) > int(version)
    assert refreshed.json()["next_slots"] == []
    publishing._clock._now = FIXED_AT + timedelta(days=2)
    publishing.evaluate_due_work()
    assert publishing.list_pending_reviews() == []
    assert decide(client, slot, "skip", confirmed=True).status_code == 409
    event = next(e for e in publishing.list_audit() if e.action == "occurrence.skipped")
    assert event.actor == str(cid)


@pytest.mark.parametrize("action", ["review", "skip"])
@pytest.mark.parametrize("kind,status,days", [
    ("regular", "pending", 1), ("manual", "pending", 1),
    ("oneoff", "resolved", 1), ("oneoff", "skipped", 1), ("oneoff", "due", 1),
    ("oneoff", "pending", 0), ("oneoff", "pending", -1),
])
def test_decisions_reject_non_future_oneoffs_without_writes(tmp_path, action, kind, status, days):
    client, publishing, _, _ = paired(tmp_path)
    slot = publishing._schedule.create(YayinZamani(
        0, kind, FIXED_AT + timedelta(days=days), status, FIXED_AT,
    ))
    before = publishing._schedule.list_all(), publishing.list_audit()
    assert decide(client, slot, action, confirmed=True).status_code == 409
    assert (publishing._schedule.list_all(), publishing.list_audit()) == before


def test_stale_missing_unauthenticated_and_invalid_decisions(tmp_path):
    client, publishing, pairing, cid = paired(tmp_path)
    slot = future(publishing)
    assert decide(client, replace(slot, due_at=FIXED_AT)).status_code == 409
    assert decide(client, replace(slot, id=999)).status_code == 404
    assert decide(client, slot, "approve").status_code == 422
    assert decide(client, slot, expected_due_at="2026-08-04T10:00:00").status_code == 422
    assert publishing._schedule.list_all() == [slot]
    pairing.revoke_client(client_id=cid, requester="cli")
    assert decide(client, slot).status_code == 401
