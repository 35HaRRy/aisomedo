from pathlib import Path

import pytest
from dojo.adapters.stubs import StubMediaProcessor
from test_api import bearer, finalize_via_api, make_app, pair_device


@pytest.mark.parametrize("content_type", ["image/jpeg", "video/mp4"])
def test_conflict_preview_is_private_and_supports_video_ranges(tmp_path: Path, content_type: str):
    client, publishing, pairing, _ = make_app(tmp_path)
    publishing._media = StubMediaProcessor(content_type=content_type)
    token = pair_device(client, pairing)
    finalize_via_api(client, publishing, token, filename="photo.jpg")
    conflict = client.post(
        "/api/media/uploads", headers=bearer(token),
        json={"filename": "PHOTO.JPG", "content_type": "image/jpeg", "declared_size_bytes": 100},
    ).json()
    target = conflict["conflicts"][0]["media_id"]
    url = f"/api/media/uploads/{conflict['upload_id']}/conflicts/{target}/preview"
    assert client.get(url).status_code == 401
    response = client.get(url, headers=bearer(token))
    assert response.status_code == 200
    assert response.content == b"x" * 100
    assert response.headers["content-type"] == content_type
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    ranged = client.get(url, headers={**bearer(token), "Range": "bytes=10-19"})
    assert ranged.status_code == 206
    assert ranged.content == b"x" * 10
    assert ranged.headers["content-range"] == "bytes 10-19/100"
    assert client.get(url.replace(target, "not-a-target"), headers=bearer(token)).status_code == 404
    client.post(
        f"/api/media/uploads/{conflict['upload_id']}/resolve", headers=bearer(token),
        json={"decision": "keep_target"},
    )
    assert client.get(url, headers=bearer(token)).status_code == 409
