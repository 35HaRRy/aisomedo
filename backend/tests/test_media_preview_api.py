from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import pytest
from dojo.adapters.stubs import StubReelRenderer
from test_package_editor_api import app


def save(client, mid, end=5):
    snapshot = client.get("/api/packages/active/editor").json()
    return client.put("/api/packages/active/edits", json={
        "expected_package_id": snapshot["package"]["id"],
        "expected_folder_name": snapshot["package"]["folder_name"],
        "base_content_revision": snapshot["content_revision"],
        "changes": [{"key": f"video:{mid}",
            "base": {"ranges": snapshot["montage"]["selections"].get(mid, [])},
            "proposed": {"ranges": [{"start": 0, "end": end}]}}],
    })


def ready(tmp_path, kind="browser"):
    client, publishing, _, _, mid = app(tmp_path, kind=kind)
    publishing._renderer = StubReelRenderer()
    assert save(client, mid).status_code == 200
    publishing.process_job(publishing.claim_next_job().job_id)
    with publishing._packages.package_lock(), publishing._packages.command_transaction():
        publishing._maintain_media_preview_jobs()
    publishing.process_job(publishing.claim_next_job().job_id)
    return client, publishing, mid


@pytest.mark.parametrize("kind", ["browser", "device"])
def test_private_original_thumbnail_sections_and_byte_ranges(tmp_path, kind):
    client, publishing, mid = ready(tmp_path, kind)
    snapshot = client.get("/api/packages/active/editor").json()
    media = next(item for item in snapshot["media"] if item["media_id"] == mid)
    before = publishing._packages.package_work(publishing.get_active_package())[1]
    original = client.get(media["original_url"])
    assert original.status_code == 200 and original.content == b"0123" * 25
    assert original.headers["content-type"] == "video/mp4"
    assert original.headers["cache-control"] == "private, no-store"
    assert media["preview_url"] != media["original_url"]
    thumbnail = client.get(media["thumbnail_url"])
    assert thumbnail.status_code == 200 and thumbnail.headers["content-type"] == "image/jpeg"
    preview = media["section_preview"]
    assert preview["status"] == "ready" and preview["duration"] == 5.0
    ranged = client.get(preview["url"], headers={"Range": "bytes=0-3"})
    assert ranged.status_code == 206 and ranged.content == b"fake"
    assert publishing._packages.package_work(publishing.get_active_package())[1] == before
    client.cookies.clear()
    client.headers.pop("Authorization", None)
    assert client.get(media["original_url"]).status_code == 401
    assert client.get(preview["url"]).status_code == 401


def test_stale_section_and_removed_media_urls_fail_closed(tmp_path):
    client, publishing, mid = ready(tmp_path)
    media = client.get("/api/packages/active/editor").json()["media"][0]
    stale = media["section_preview"]["url"]
    assert save(client, mid, end=6).status_code == 200
    assert client.get(stale).status_code == 404
    assert client.get(media["original_url"]).status_code == 200
    publishing.remove_media(mid)
    assert client.get(media["original_url"]).status_code == 404
    assert client.get(media["thumbnail_url"]).status_code == 404


def test_wrong_package_and_malformed_artifact_reference_never_serve_bytes(tmp_path):
    client, publishing, mid = ready(tmp_path)
    media = client.get("/api/packages/active/editor").json()["media"][0]
    parts = urlsplit(media["original_url"])
    params = parse_qs(parts.query)
    params["expected_package_id"] = ["999999"]
    wrong = urlunsplit(parts._replace(query=urlencode(params, doseq=True)))
    assert client.get(wrong).status_code == 409
    package = publishing.get_active_package()
    document = publishing._load_manifest(package)
    document["section_previews"][mid]["artifact_ref"] = "../private.txt"
    (tmp_path / "private.txt").write_bytes(b"not-public")
    publishing._write_manifest(package, document)
    assert client.get(media["section_preview"]["url"]).status_code == 404


def test_preview_retry_is_duplicate_safe_and_rejects_stale_saved_inputs(tmp_path):
    client, publishing, _, _, mid = app(tmp_path)
    publishing._renderer = StubReelRenderer(fail_reason="unavailable encoder")
    assert save(client, mid).status_code == 200
    publishing.process_job(publishing.claim_next_job().job_id)
    snapshot = client.get("/api/packages/active/editor").json()
    preview = snapshot["media"][0]["section_preview"]
    assert preview["status"] == "failed"
    body = {"expected_package_id": snapshot["package"]["id"],
            "expected_folder_name": snapshot["package"]["folder_name"],
            "expected_generation": preview["generation"]}
    endpoint = f"/api/packages/active/media/{mid}/sections/retry"
    first = client.post(endpoint, json=body)
    assert first.status_code == 200
    second = client.post(endpoint, json=body)
    assert second.status_code == 200
    assert (first.json()["media"][0]["section_preview"]
            == second.json()["media"][0]["section_preview"])
    assert save(client, mid, end=6).status_code == 200
    assert client.post(endpoint, json=body).status_code == 409


def test_older_cached_editor_models_keep_optional_preview_defaults(tmp_path):
    from backend.routes.package_models import ActiveEditorOut

    client, _, _, _, _ = app(tmp_path)
    snapshot = client.get("/api/packages/active/editor").json()
    snapshot.pop("render_duration", None)
    for media in snapshot["media"]:
        for key in ("original_url", "thumbnail_url", "section_preview"):
            media.pop(key, None)
    restored = ActiveEditorOut.model_validate(snapshot)
    assert restored.render_duration is None
    assert restored.media[0].original_url is None
    assert restored.media[0].section_preview is None
