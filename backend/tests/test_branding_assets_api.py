import subprocess
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from test_api import bearer, make_app, pair_device


def png() -> bytes:
    data = BytesIO()
    Image.new("RGB", (20, 20), "red").save(data, format="PNG")
    return data.getvalue()


def test_upload_is_independent_private_and_installable(tmp_path: Path) -> None:
    client, publishing, pairing, _ = make_app(tmp_path)
    headers = bearer(pair_device(client, pairing))
    assert client.post("/api/settings/branding/assets", content=png()).status_code == 401
    response = client.post(
        "/api/settings/branding/assets",
        headers={**headers, "Content-Type": "text/plain"},
        content=png(),
    )
    assert response.status_code == 201
    body = response.json()
    assert publishing.get_active_package() is None
    assert publishing.get_branding_defaults().logo_asset is None
    assert client.get(body["preview_url"]).status_code == 401
    preview = client.get(body["preview_url"], headers=headers)
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/png"
    installed = client.patch(
        "/api/settings/branding", headers=headers, json={"logo_asset": body["asset"]}
    )
    assert installed.status_code == 200
    assert publishing._resolve_asset(body["asset"]).is_file()
    assert (
        client.get("/api/settings/branding/assets/missing.png", headers=headers).status_code == 404
    )


@pytest.mark.parametrize(
    "data,status",
    [(b"invalid", 422), (b"x" * (10 * 1024**2 + 1), 413)],
    ids=["invalid", "oversized"],
)
def test_rejected_upload_preserves_defaults(tmp_path: Path, data: bytes, status: int) -> None:
    client, publishing, pairing, _ = make_app(tmp_path)
    headers = bearer(pair_device(client, pairing))
    before = publishing.get_branding_defaults()
    response = client.post(
        "/api/settings/branding/assets", headers=headers, content=iter([data[:20], data[20:]])
    )
    assert response.status_code == status
    assert publishing.get_branding_defaults() == before


def test_revoked_client_cannot_upload(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    headers = bearer(pair_device(client, pairing))
    pairing.revoke_client(client_id=1, requester="cli")
    assert (
        client.post("/api/settings/branding/assets", headers=headers, content=png()).status_code
        == 401
    )


@pytest.mark.parametrize("extension", ["mp4", "mov", "webm", "mkv", "avi", "legacy.mov"])
def test_video_card_upload_preview_and_logo_rejection(tmp_path: Path, extension: str) -> None:
    video = tmp_path / f"card.{extension}"
    codec = "libvpx-vp9" if extension == "webm" else "libx264"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=red:s=32x32:d=1",
                    "-c:v", codec, "-pix_fmt", "yuv420p", str(video)], check=True)
    if extension == "legacy.mov":
        data = video.read_bytes()
        video.write_bytes(data[:4] + b"free" + data[8:])
    client, _, pairing, _ = make_app(tmp_path)
    headers = bearer(pair_device(client, pairing))
    uploaded = client.post(
        "/api/settings/branding/assets", headers=headers, content=video.read_bytes()
    )
    assert uploaded.status_code == 201
    body = uploaded.json()
    preview = client.get(body["preview_url"], headers=headers)
    assert preview.headers["content-type"] == {
        "mp4": "video/mp4", "mov": "video/quicktime", "webm": "video/webm",
        "mkv": "video/x-matroska", "avi": "video/x-msvideo", "legacy.mov": "video/quicktime",
    }[extension]
    assert preview.content == video.read_bytes()
    assert client.patch("/api/settings/branding", headers=headers,
                        json={"intro_asset": body["asset"], "intro_duration": 2}).status_code == 200
    assert client.patch("/api/settings/branding", headers=headers,
                        json={"logo_asset": body["asset"]}).status_code == 422
    assert client.put("/api/settings/branding", headers=headers,
                      json={"logo_asset": body["asset"]}).status_code == 422


@pytest.mark.parametrize("data", [b"\0\0\0\x18ftypisom" + b"broken", b"\x1a\x45\xdf\xa3broken"])
def test_corrupt_video_is_rejected_and_temporary_files_are_removed(
    tmp_path: Path, data: bytes,
) -> None:
    client, publishing, pairing, _ = make_app(tmp_path)
    headers = bearer(pair_device(client, pairing))
    before = publishing.get_branding_defaults()
    response = client.post("/api/settings/branding/assets", headers=headers, content=data)
    assert response.status_code == 422
    assert publishing.get_branding_defaults() == before
    assert not list((publishing.media_root / "branding" / "assets").glob("*"))


@pytest.mark.parametrize("duration", [0, -1, 1.5, True])
def test_card_duration_requires_positive_integer(tmp_path: Path, duration: object) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    headers = bearer(pair_device(client, pairing))
    uploaded = client.post("/api/settings/branding/assets", headers=headers, content=png())
    asset = uploaded.json()["asset"]
    assert client.patch("/api/settings/branding", headers=headers,
                        json={"intro_asset": asset, "intro_duration": duration}).status_code == 422
