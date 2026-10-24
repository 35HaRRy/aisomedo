from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import date, time, timedelta

import pytest
from dojo import SchedulePlan
from dojo.adapters.stubs import StubMetaPublisher, StubReelRenderer
from dojo.exceptions import MetaPublishFailed, MetaPublishUncertain
from dojo.testing import FIXED_AT
from test_package_editor_api import app


@pytest.mark.parametrize("action", ["skip", "reschedule"])
def test_empty_decisions_require_pairing_and_exact_folder(tmp_path, action):
    client, publishing, pairing, cid, _ = app(tmp_path, kind="device", finalize=False)
    folder = publishing.get_or_create_active_package().folder_name
    occ = publishing.manual_publish()
    path = f"/api/reviews/occurrences/{occ.id}/{action}"
    body = {"expected_folder_name": folder, "confirmed": True,
            "new_due_at": (FIXED_AT + timedelta(days=1)).isoformat()}
    before = publishing._schedule.list_all()
    bad = body | {"expected_folder_name": "old-package"}
    assert client.post(path, json=bad).status_code == 409
    assert publishing._schedule.list_all() == before
    if action == "skip":
        assert client.post(path, json=body | {"confirmed": False}).status_code == 400
    else:
        past = body | {"new_due_at": FIXED_AT.isoformat()}
        assert client.post(path, json=past).status_code == 400
    assert client.post(path.replace(str(occ.id), "999"), json=body).status_code == 404
    response = client.post(path, json=body)
    assert response.status_code == 200
    assert response.json()["status"] == ("skipped" if action == "skip" else "rescheduled")
    assert response.json()["package_folder"] == folder
    assert response.json()["occurrence_id"] == occ.id
    assert publishing.list_audit()[0].actor == str(cid)
    assert client.post(path, json=body).status_code == 409
    pairing.revoke_client(client_id=cid, requester="cli")
    assert client.post(path, json=body).status_code == 401



def ready_review(tmp_path):
    client, publishing, pairing, cid, _ = app(tmp_path)
    publishing._renderer = StubReelRenderer()
    publishing._settings.set("branding.logo_asset", "logo.png", updated_at=FIXED_AT)
    publishing.set_caption("Exact caption\n#dojo")
    occurrence = publishing.manual_publish()
    publishing.render_preview()
    publishing.process_job(publishing.claim_next_job().job_id)
    review = publishing.list_pending_reviews()[0]
    return client, publishing, pairing, cid, replace(occurrence, status="due"), review


@pytest.mark.parametrize("days", [0, 1])
def test_reschedule_api_rejects_next_regular_or_later_without_resolving_review(tmp_path, days):
    client, publishing, _, _, occurrence, review = ready_review(tmp_path)
    publishing.set_plan(SchedulePlan(date(2026, 8, 3), time(10), enabled=True))
    regular = publishing._schedule.next_regular_after(FIXED_AT)
    response = client.post(f"/api/reviews/{review.id}/reschedule", json={
        "version": review.version,
        "new_due_at": (regular.due_at + timedelta(days=days)).isoformat(),
    })
    assert response.status_code == 400
    assert publishing.list_pending_reviews() == [review]
    assert next(o for o in publishing._schedule.list_all() if o.id == occurrence.id) == occurrence


def test_reschedule_api_lists_oneoff_and_blocks_manual_request(tmp_path):
    client, publishing, _, _, _, review = ready_review(tmp_path)
    publishing.set_plan(SchedulePlan(date(2026, 8, 3), time(10), enabled=True))
    due = FIXED_AT + timedelta(days=1)
    response = client.post(f"/api/reviews/{review.id}/reschedule", json={
        "version": review.version, "new_due_at": due.isoformat(),
    })
    assert response.status_code == 200
    dashboard = client.get("/api/dashboard").json()
    assert dashboard["next_slot"] == {
        "kind": "oneoff", "due_at": due.isoformat(), "occurrence_id": None,
    }
    assert dashboard["pending_actions"] == []
    assert dashboard["manual_review_allowed"] is False
    assert client.post("/api/settings/manual-publish").status_code == 409


def test_review_detail_binds_caption_and_authenticated_render_to_revision(tmp_path):
    client, publishing, _, _, occurrence, review = ready_review(tmp_path)
    response = client.get(f"/api/reviews/{review.id}")
    assert response.status_code == 200
    detail = response.json()
    assert detail["review"]["caption"] == "Exact caption\n#dojo"
    assert detail["review"]["occurrence_id"] == occurrence.id
    assert detail["render_ready"] is True
    assert review.revision_digest in detail["preview_url"]
    assert client.get(detail["preview_url"]).content == b"fake-reel"
    assert publishing.list_pending_reviews()[0].status == "pending"

    publishing.set_caption("Changed after review")
    detail = client.get(f"/api/reviews/{review.id}").json()
    assert detail["review"]["caption"] == "Exact caption\n#dojo"
    assert detail["render_ready"] is False
    assert detail["preview_url"] is None
    assert client.get(response.json()["preview_url"]).status_code == 404


def test_review_detail_requires_pairing_and_keeps_resolved_identity(tmp_path):
    client, publishing, pairing, cid, _, review = ready_review(tmp_path)
    publishing.skip(review.id, review.version, confirmed=True)
    detail = client.get(f"/api/reviews/{review.id}").json()
    assert detail["review"]["status"] == "skipped"
    assert detail["render_ready"] is False
    assert detail["preview_url"] is None
    assert client.get("/api/reviews/999").status_code == 404
    pairing.revoke_client(client_id=cid, requester="cli")
    assert client.get(f"/api/reviews/{review.id}").status_code == 401


def test_approval_rejects_invalidated_render_without_resolving_review(tmp_path):
    client, publishing, _, _, _, review = ready_review(tmp_path)
    publishing.set_caption("Unrendered edit")
    response = client.post(f"/api/reviews/{review.id}/approve", json={"version": review.version})
    assert response.status_code == 409
    assert publishing.list_pending_reviews()[0].status == "pending"


@pytest.mark.parametrize("action", ["approve", "skip", "reschedule"])
@pytest.mark.parametrize("uncertain", [False, True])
def test_failed_upload_leaves_exact_review_and_all_decisions_available(tmp_path, action, uncertain):
    client, publishing, _, _, occurrence, review = ready_review(tmp_path)
    publishing._meta = StubMetaPublisher()
    error_type = MetaPublishUncertain if uncertain else MetaPublishFailed
    publishing._meta.fail_create = error_type("bad video")
    before = client.get(f"/api/reviews/{review.id}").json()
    response = client.post(f"/api/reviews/{review.id}/approve", json={"version": review.version})
    assert response.status_code == 200
    expected = "uncertain" if uncertain else "failed"
    assert response.json()["publication"]["status"] == expected
    message = response.json()["review"]["instagram_fail_message"]
    assert "bad video" in message
    before["review"].update(status=expected, instagram_fail_message=message)
    assert response.json()["review"].items() >= before["review"].items()
    assert client.get(f"/api/reviews/{review.id}").json() == before
    assert next(o for o in publishing._schedule.list_all() if o.id == occurrence.id) == occurrence
    pending = client.get("/api/dashboard").json()["pending_actions"]
    assert pending[0]["review_id"] == review.id
    assert pending[0]["state"] == "review_ready"
    publishing._meta.fail_create = None
    response = client.post(f"/api/reviews/{review.id}/{action}", json={
        "version": review.version, "confirmed": True,
        "new_due_at": (FIXED_AT + timedelta(days=1)).isoformat(),
    })
    assert response.status_code == 200
    assert response.json()["review"]["status"] == {
        "approve": "approved", "skip": "skipped", "reschedule": "rescheduled",
    }[action]


@pytest.mark.parametrize("action", ["approve", "skip", "reschedule"])
def test_stale_versions_reject_actions_without_resolving_review(tmp_path, action):
    client, publishing, _, _, _, review = ready_review(tmp_path)
    response = client.post(f"/api/reviews/{review.id}/{action}", json={
        "version": review.version + 1, "confirmed": True,
        "new_due_at": "2099-08-04T10:00:00+03:00",
    })
    assert response.status_code == 409
    assert publishing.list_pending_reviews()[0].status == "pending"


def test_empty_due_upload_renders_review_for_same_occurrence_and_package(tmp_path):
    client, publishing, _, _, _ = app(tmp_path, finalize=False)
    package = publishing.get_or_create_active_package()
    occurrence = publishing.manual_publish()
    assert client.get("/api/dashboard").json()["pending_actions"][0]["state"] == "empty_package"
    publishing._renderer = StubReelRenderer()
    publishing._settings.set("branding.logo_asset", "logo.png", updated_at=FIXED_AT)
    data = b"x" * 100
    upload = publishing.start_upload("clip.mp4", "video/mp4", len(data))
    publishing.append_upload_range(upload.upload_id, 0, len(data),
                                  hashlib.sha256(data).hexdigest(), data)
    publishing.complete_upload(upload.upload_id)
    publishing.process_job(publishing.claim_next_job().job_id)
    response = client.post("/api/packages/active/render", json={
        "expected_folder_name": package.folder_name, "retry": False,
    })
    assert response.status_code == 200
    publishing.process_job(publishing.claim_next_job().job_id)
    action = client.get("/api/dashboard").json()["pending_actions"][0]
    assert action["occurrence_id"] == occurrence.id
    assert action["package_folder"] == package.folder_name
    assert action["state"] == "review_ready"
    assert client.get(f"/api/reviews/{action['review_id']}").status_code == 200
    assert publishing.get_active_package().id == package.id
    assert len(publishing._schedule.list_all()) == 1
    assert len(publishing.list_pending_reviews()) == 1
