from __future__ import annotations

import hashlib
import json
from urllib.parse import quote

import pytest
from dojo import DojoActivity, DojoPairing, DojoPublishing, DojoSetup, InMemoryStore
from dojo.adapters.signed_urls import HmacSignedUrlStore
from dojo.adapters.stubs import StubMediaProcessor
from dojo.testing import FIXED_AT, FakeClock, complete_confirmed_package
from fastapi.testclient import TestClient

from backend.main import create_app


def app(tmp_path, *, kind="browser", finalize=True):
    store = InMemoryStore()
    publishing = DojoPublishing(
        packages=store, audit=store, settings=store, media_root=tmp_path, clock=FakeClock(),
        media=StubMediaProcessor(content_type="video/mp4", duration=30.0),
        signed_urls=HmacSignedUrlStore(
            base_url="http://testserver", secret="fixture", clock=FakeClock(),
        ),
    )
    pairing = DojoPairing(pairing=store, audit=store, clock=FakeClock())
    setup = DojoSetup(setup=store, audit=store, pairing=store, clock=FakeClock())
    client = TestClient(create_app(publishing, pairing, DojoActivity(audit=store, pairing=store),
                                   setup, cookie_secure=False))
    code = pairing.create_pairing_code(requester="cli").raw_code
    paired = client.post("/api/pairing/validate", json={
        "code": code, "name": "Editor", "kind": kind,
    })
    assert paired.status_code == 200
    if kind == "device":
        client.headers.update({"Authorization": f"Bearer {paired.json()['token']}",
                               "X-Android-Version-Code": "1"})
    mid = None
    if finalize:
        data = b"0123" * 25
        upload = publishing.start_upload("Çalışma.MP4", "video/mp4", len(data))
        publishing.append_upload_range(upload.upload_id, 0, 100,
                                       hashlib.sha256(data).hexdigest(), data)
        publishing.complete_upload(upload.upload_id)
        publishing.process_job(publishing.claim_next_job().job_id)
        mid = publishing.get_montage_status().order[0]
    return client, publishing, pairing, paired.json()["client_id"], mid


def body(publishing, mid):
    return {"expected_folder_name": publishing.get_active_package().folder_name,
            "selections": {mid: [{"start": 0.0, "end": 5.0}, {"start": 10.0, "end": 15.0}]}}


@pytest.mark.parametrize("kind", ["browser", "device"])
def test_editor_selection_preview_share_pairing_auth_and_actor(tmp_path, kind):
    client, publishing, _, cid, mid = app(tmp_path, kind=kind)
    response = client.get("/api/packages/active/editor")
    assert response.status_code == 200
    editor = response.json()
    assert editor["media"][0]["preview_url"].startswith("/api/packages/active/media/")
    response = client.put("/api/packages/active/selections", json=body(publishing, mid))
    assert response.status_code == 200
    assert response.json()["combined_duration"] == 10.0
    assert publishing.list_audit()[0].actor == str(cid)
    preview = client.get(editor["media"][0]["preview_url"], headers={"Range": "bytes=0-3"})
    assert preview.status_code == 206
    assert preview.content == b"0123"
    assert preview.headers["content-type"] == "video/mp4"
    assert preview.headers["cache-control"] == "private, no-store"
    assert preview.headers["x-content-type-options"] == "nosniff"
    assert preview.headers["content-disposition"].startswith("inline;")
    assert preview.headers["content-range"] == "bytes 0-3/100"


def test_editor_and_artifacts_deny_unpaired_and_revoked_clients(tmp_path):
    client, publishing, pairing, cid, mid = app(tmp_path)
    folder = publishing.get_active_package().folder_name
    requests = [lambda: client.get("/api/packages/active/editor"),
                lambda: client.put("/api/packages/active/selections", json=body(publishing, mid)),
                lambda: client.get(f"/api/packages/active/media/{mid}/preview",
                                    params={"expected_folder_name": folder}),
                lambda: client.get(f"/api/packages/{folder}/artifacts",
                                    params={"artifact_ref": "render/reel.mp4"})]
    pairing.revoke_client(client_id=cid, requester="cli")
    assert [request().status_code for request in requests] == [401, 401, 401, 401]
    client.cookies.clear()
    assert [request().status_code for request in requests] == [401, 401, 401, 401]


def test_missing_editor_is_404_and_does_not_create_active(tmp_path):
    client, publishing, _, _, _ = app(tmp_path, finalize=False)
    assert client.get("/api/packages/active/editor").status_code == 404
    assert publishing.get_active_package() is None


@pytest.mark.parametrize("ranges", [[], [{"start": True, "end": 2}],
                                    [{"start": "0", "end": 2}],
                                    [{"start": 0, "end": 0.01}],
                                    [{"start": 0, "end": 31}],
                                    [{"start": 0, "end": 5}, {"start": 4, "end": 6}]])
def test_invalid_selection_is_422_with_no_manifest_or_audit_write(tmp_path, ranges):
    client, publishing, _, _, mid = app(tmp_path)
    data = body(publishing, mid)
    data["selections"][mid] = ranges
    path = tmp_path / publishing.get_active_package().folder_name / "manifest.json"
    before, audits = path.read_bytes(), len(publishing.list_audit())
    assert client.put("/api/packages/active/selections", json=data).status_code == 422
    assert path.read_bytes() == before
    assert len(publishing.list_audit()) == audits


def test_limit_and_legacy_conflicts_are_409(tmp_path):
    client, publishing, _, _, mid = app(tmp_path)
    publishing._settings.set("montage.max_duration_seconds", 4, updated_at=FIXED_AT)
    response = client.put("/api/packages/active/selections", json=body(publishing, mid))
    assert response.status_code == 409
    publishing._settings.set("montage.max_duration_seconds", 90, updated_at=FIXED_AT)
    response = client.put("/api/packages/active/selections", json=body(publishing, mid))
    assert response.status_code == 200
    result = client.put("/api/packages/active/trims", json={"trims": {}})
    assert result.status_code == 409
    assert "updated editor" in result.json()["detail"]


def test_rollover_rejects_old_selection_order_toggle_and_preview(tmp_path):
    client, publishing, _, _, mid = app(tmp_path)
    data = body(publishing, mid)
    old = data["expected_folder_name"]
    complete_confirmed_package(publishing)
    assert client.put("/api/packages/active/selections", json=data).status_code == 409
    assert client.put("/api/packages/active/order", json={"order": [mid],
                      "expected_folder_name": old}).status_code == 409
    for action in ("remove", "restore", "preview"):
        url = f"/api/packages/active/media/{mid}/{action}"
        response = (client.get if action == "preview" else client.post)(
            url, params={"expected_folder_name": old},
        )
        assert response.status_code == 409


def test_legacy_mutations_without_guards_still_work(tmp_path):
    client, _, _, _, mid = app(tmp_path)
    response = client.put("/api/packages/active/trims", json={
        "trims": {mid: {"start": 1, "end": 6}},
    })
    assert response.status_code == 200
    assert client.put("/api/packages/active/order", json={"order": [mid]}).status_code == 200
    assert client.post(f"/api/packages/active/media/{mid}/remove").status_code == 200
    assert client.post(f"/api/packages/active/media/{mid}/restore").status_code == 200


def test_completed_downloads_use_private_artifacts_not_public_signer(tmp_path):
    client, publishing, _, _, mid = app(tmp_path)
    publishing.remove_media(mid)
    complete_confirmed_package(publishing)
    package = publishing.list_completed_packages()[0]
    root = tmp_path / package.folder_name
    (root / "render").mkdir()
    (root / "render" / "reel.mp4").write_bytes(b"immutable-reel")
    before = (root / "manifest.json").read_bytes()
    detail = client.get(f"/api/packages/{quote(package.folder_name)}")
    assert detail.status_code == 200
    artifacts = detail.json()["artifacts"]
    assert len(artifacts) == 3
    for artifact in artifacts:
        assert artifact["available"] and artifact["url"].startswith("/api/packages/")
        assert "/pub/" not in artifact["url"]
        response = client.get(artifact["url"])
        assert response.status_code == 200
        assert response.headers["content-disposition"].startswith("attachment;")
        expected = b"immutable-reel" if artifact["kind"] == "render" else b"0123" * 25
        assert response.content == expected
    original = next(a for a in artifacts if a["kind"] == "original")
    disposition = client.get(original["url"]).headers["content-disposition"]
    assert "filename*=utf-8''%C3%87al%C4%B1%C5%9Fma.MP4" in disposition
    result = client.post(f"/api/packages/{quote(package.folder_name)}/download",
                         json={"artifact_ref": original["artifact_ref"]})
    assert result.status_code == 200 and result.json()["url"] == original["url"]
    client.cookies.clear()
    assert client.get(original["url"]).status_code == 401
    assert (root / "manifest.json").read_bytes() == before
    with pytest.raises(ValueError, match="approved render"):
        publishing._signed_urls.create(root / original["artifact_ref"])


def test_artifact_missing_unknown_and_traversal_responses(tmp_path):
    client, publishing, _, _, mid = app(tmp_path)
    complete_confirmed_package(publishing)
    folder = publishing.list_completed_packages()[0].folder_name
    base = f"/api/packages/{quote(folder)}/artifacts"
    assert client.get(base, params={"artifact_ref": "../secret"}).status_code == 400
    assert client.get(base, params={"artifact_ref": "manifest.json"}).status_code == 404
    assert client.get(base, params={"artifact_ref": "render/reel.mp4"}).status_code == 404
    detail = client.get(f"/api/packages/{quote(folder)}").json()
    render = next(a for a in detail["artifacts"] if a["kind"] == "render")
    assert render["url"] is None and render["available"] is False


def test_unknown_nonfinite_duration_is_readable_without_json_failure(tmp_path):
    client, publishing, _, _, _ = app(tmp_path)
    path = tmp_path / publishing.get_active_package().folder_name / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["media"][0]["processed"]["duration"] = float("nan")
    path.write_text(json.dumps(manifest), encoding="utf-8")
    response = client.get("/api/packages/active/editor")
    assert response.status_code == 200
    assert response.json()["montage"]["duration_complete"] is False
    assert response.json()["media"][0]["source_duration"] is None


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_json_endpoint_is_rejected_without_server_error(tmp_path, value):
    client, publishing, _, _, mid = app(tmp_path)
    data = body(publishing, mid)
    data["selections"][mid] = [{"start": 0, "end": 1}]
    content = json.dumps(data).replace('"start": 0', f'"start": {value}')
    response = client.put("/api/packages/active/selections", content=content,
                          headers={"Content-Type": "application/json"})
    assert response.status_code == 422
