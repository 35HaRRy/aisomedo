from __future__ import annotations

from io import BytesIO
from pathlib import Path

import dojo
import pytest
from PIL import Image


def image_bytes(format: str = "PNG", size: tuple[int, int] = (20, 20)) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, "red").save(output, format=format)
    return output.getvalue()


@pytest.mark.parametrize("format", ["PNG", "JPEG"])
def test_png_and_jpeg_roundtrip(tmp_path: Path, format: str) -> None:
    assets = dojo.BrandingAssets(tmp_path)
    saved = assets.save_image(image_bytes(format))
    path = assets.resolve(saved.asset_id)
    assert path == tmp_path / saved.reference
    assert saved.reference.startswith("branding/assets/")
    with Image.open(path) as image:
        assert image.format == format
        assert image.size == (20, 20)
    assert assets.save_image(image_bytes(format)).reference != saved.reference
    assert path.is_file()


def test_png_alpha_is_preserved(tmp_path: Path) -> None:
    data = BytesIO()
    Image.new("RGBA", (20, 20), (255, 0, 0, 100)).save(data, format="PNG")
    assets = dojo.BrandingAssets(tmp_path)
    with Image.open(assets.resolve(assets.save_image(data.getvalue()).asset_id)) as image:
        assert image.getpixel((0, 0)) == (255, 0, 0, 100)


def test_upload_byte_limit_is_enforced(tmp_path: Path) -> None:
    with pytest.raises(dojo.BrandingAssetTooLarge):
        dojo.BrandingAssets(tmp_path).save_image(b"x" * (10 * 1024**2 + 1))
    assert not list(tmp_path.rglob("*.png"))


@pytest.mark.parametrize("size", [(4097, 1), (1, 4097)])
def test_dimension_limit_rejects_oversized_image(tmp_path: Path, size: tuple[int, int]) -> None:
    with pytest.raises(dojo.BrandingAssetInvalid):
        dojo.BrandingAssets(tmp_path).save_image(image_bytes(size=size))


def test_dimension_limit_is_inclusive(tmp_path: Path) -> None:
    assets = dojo.BrandingAssets(tmp_path)
    assert assets.resolve(assets.save_image(image_bytes(size=(4096, 1))).asset_id).is_file()


@pytest.mark.parametrize(
    "data",
    [b"", b"not an image", b"<svg/>", image_bytes()[:30], image_bytes("GIF"), image_bytes("WEBP")],
)
def test_invalid_images_are_not_saved(tmp_path: Path, data: bytes) -> None:
    with pytest.raises(dojo.BrandingAssetInvalid):
        dojo.BrandingAssets(tmp_path).save_image(data)
    assert not list(tmp_path.rglob("*.png"))


def test_animated_png_is_rejected(tmp_path: Path) -> None:
    output = BytesIO()
    Image.new("RGB", (10, 10), "red").save(
        output,
        format="PNG",
        save_all=True,
        append_images=[Image.new("RGB", (10, 10), "blue")],
        duration=100,
        loop=0,
    )
    with pytest.raises(dojo.BrandingAssetInvalid):
        dojo.BrandingAssets(tmp_path).save_image(output.getvalue())


@pytest.mark.parametrize("cut", [1, 12, 20])
def test_tail_truncated_png_is_rejected(tmp_path: Path, cut: int) -> None:
    with pytest.raises(dojo.BrandingAssetInvalid):
        dojo.BrandingAssets(tmp_path).save_image(image_bytes()[:-cut])


def test_bad_png_terminal_crc_is_rejected(tmp_path: Path) -> None:
    data = bytearray(image_bytes())
    data[-1] ^= 1
    with pytest.raises(dojo.BrandingAssetInvalid):
        dojo.BrandingAssets(tmp_path).save_image(bytes(data))


@pytest.mark.parametrize("asset_id", ["../../secret.png", "C:/secret.png", "logo.png", "missing"])
def test_preview_rejects_user_paths(tmp_path: Path, asset_id: str) -> None:
    with pytest.raises(dojo.BrandingAssetNotFound):
        dojo.BrandingAssets(tmp_path).resolve(asset_id)


def test_symlink_escape_is_not_previewed(tmp_path: Path) -> None:
    assets = dojo.BrandingAssets(tmp_path)
    saved = assets.save_image(image_bytes())
    path = assets.resolve(saved.asset_id)
    outside = tmp_path / "outside.png"
    outside.write_bytes(image_bytes())
    path.unlink()
    try:
        path.symlink_to(outside)
    except OSError:
        pytest.skip("platform cannot create symlinks")
    with pytest.raises(dojo.BrandingAssetNotFound):
        assets.resolve(saved.asset_id)
