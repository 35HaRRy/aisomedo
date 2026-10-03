from __future__ import annotations

import hashlib

import pytest
from dojo.adapters.stubs import StubReelRenderer
from dojo.testing import FIXED_AT
from test_package_editor_api import app


def ready_review(tmp_path):
    client, publishing, pairing, cid, _ = app(tmp_path)
    publishing._renderer = StubReelRenderer()
    publishing._settings.set("branding.logo_asset", "logo.png", updated_at=FIXED_AT)
    publishing.set_caption("Exact caption\n#dojo")
    occurrence = publishing.manual_publish()
    publishing.render_preview()
    publishing.process_job(publishing.claim_next_job().job_id)
    review = publishing.list_pending_reviews()[0]
    return client, publishing, pairing, cid, occurrence, review


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
