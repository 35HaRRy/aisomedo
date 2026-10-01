from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from zlib import crc32

from PIL import Image, UnidentifiedImageError

from dojo.exceptions import BrandingAssetInvalid, BrandingAssetNotFound, BrandingAssetTooLarge

MAX_BRANDING_BYTES = 10 * 1024**2
MAX_BRANDING_SIDE = 4096
_ASSET_ID = re.compile(r"[0-9a-f]{32}\.(png|jpg)")


def _validate_png_container(data: bytes) -> None:
    """Pillow tolerates missing terminal chunks; uploads must be complete."""
    offset = 8
    while offset + 12 <= len(data):
        length = int.from_bytes(data[offset:offset + 4], "big")
        end = offset + 12 + length
        if end > len(data):
            break
        kind = data[offset + 4:offset + 8]
        expected = int.from_bytes(data[end - 4:end], "big")
        if crc32(data[offset + 4:end - 4]) != expected:
            raise BrandingAssetInvalid("invalid PNG checksum")
        if kind == b"IEND":
            if length == 0 and end == len(data):
                return
            break
        offset = end
    raise BrandingAssetInvalid("incomplete PNG container")


@dataclass(frozen=True)
class BrandingAsset:
    asset_id: str
    reference: str
    content_type: str


class BrandingAssets:
    """Independent immutable branding images, never package-media uploads."""

    def __init__(self, media_root: Path) -> None:
        self._media_root = media_root.resolve()
        self._directory = self._media_root / "branding" / "assets"

    def save_image(self, data: bytes) -> BrandingAsset:
        if len(data) > MAX_BRANDING_BYTES:
            raise BrandingAssetTooLarge("branding image exceeds 10 MiB")
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            _validate_png_container(data)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(data), formats=["PNG", "JPEG"]) as image:
                    if (
                        image.width > MAX_BRANDING_SIDE
                        or image.height > MAX_BRANDING_SIDE
                        or getattr(image, "n_frames", 1) != 1
                    ):
                        raise BrandingAssetInvalid("image dimensions or frame count invalid")
                    image.load()
                    format = image.format
                    mode = (
                        "RGBA"
                        if format == "PNG"
                        and ("A" in image.getbands() or "transparency" in image.info)
                        else "RGB"
                    )
                    clean = image.convert(mode)
                    clean.info.clear()
                    output = BytesIO()
                    clean.save(output, format=format)
        except (
            UnidentifiedImageError,
            OSError,
            ValueError,
            Image.DecompressionBombWarning,
            Image.DecompressionBombError,
        ) as exc:
            raise BrandingAssetInvalid(
                "a valid single-frame PNG or JPEG image is required"
            ) from exc
        extension = "png" if format == "PNG" else "jpg"
        asset_id = f"{uuid4().hex}.{extension}"
        self._directory.mkdir(parents=True, exist_ok=True)
        if self._directory.resolve() != self._directory:
            raise BrandingAssetInvalid("branding directory must not contain symlinks")
        target = self._directory / asset_id
        temporary = self._directory / f".{asset_id}.tmp"
        try:
            with temporary.open("xb") as stream:
                stream.write(output.getvalue())
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return BrandingAsset(
            asset_id,
            f"branding/assets/{asset_id}",
            f"image/{'png' if extension == 'png' else 'jpeg'}",
        )

    def resolve(self, asset_id: str) -> Path:
        if not _ASSET_ID.fullmatch(asset_id):
            raise BrandingAssetNotFound("branding asset not found")
        path = self._directory / asset_id
        if (
            self._directory.resolve() != self._directory
            or path.is_symlink()
            or path.resolve().parent != self._directory
            or not path.is_file()
        ):
            raise BrandingAssetNotFound("branding asset not found")
        return path
