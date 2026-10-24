from __future__ import annotations

import json
import math
import re
import subprocess
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
_ASSET_ID = re.compile(r"[0-9a-f]{32}\.(png|jpg|mp4|mov|webm|mkv|avi)")


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
    """Independent immutable branding media, never package-media uploads."""

    def __init__(self, media_root: Path) -> None:
        self._media_root = media_root.resolve()
        self._directory = self._media_root / "branding" / "assets"

    def save_media(self, data: bytes) -> BrandingAsset:
        """Accept images or validated, self-contained video containers for cards."""
        if len(data) > MAX_BRANDING_BYTES:
            raise BrandingAssetTooLarge("branding media exceeds 10 MiB")
        if data.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8")):
            return self.save_image(data)
        self._directory.mkdir(parents=True, exist_ok=True)
        if self._directory.resolve() != self._directory:
            raise BrandingAssetInvalid("branding directory must not contain symlinks")
        identifier = uuid4().hex
        temporary = self._directory / f".{identifier}.tmp"
        restrictions = [
            "-protocol_whitelist", "file,pipe", "-format_whitelist", "mov,matroska,webm,avi",
        ]
        try:
            with temporary.open("xb") as stream:
                stream.write(data)
            probe = subprocess.run(
                ["ffprobe", "-v", "error", *restrictions, "-show_streams", "-show_format",
                 "-of", "json", str(temporary)],
                capture_output=True, check=True, timeout=30,
            )
            info = json.loads(probe.stdout)
            container = info["format"]["format_name"].split(",")
            if "mov" in container:
                brand = info["format"].get("tags", {}).get("major_brand", "qt").strip()
                extension = "mov" if brand == "qt" else "mp4"
            elif "matroska" in container or "webm" in container:
                extension = "webm" if b"webm" in data[:64] else "mkv"
            elif "avi" in container:
                extension = "avi"
            else:
                raise BrandingAssetInvalid("unsupported video container")
            video = next(stream for stream in info["streams"] if stream["codec_type"] == "video")
            duration = float(info["format"].get("duration", video.get("duration", 0)))
            if (not math.isfinite(duration) or duration <= 0
                    or not 0 < video["width"] <= MAX_BRANDING_SIDE
                    or not 0 < video["height"] <= MAX_BRANDING_SIDE):
                raise BrandingAssetInvalid("video duration or dimensions invalid")
            subprocess.run(
                ["ffmpeg", "-v", "error", "-xerror", *restrictions, "-i", str(temporary),
                 "-map", "0:v:0", "-map", "0:a?", "-f", "null", "-"],
                capture_output=True, check=True, timeout=30,
            )
            asset_id = f"{identifier}.{extension}"
            temporary.replace(self._directory / asset_id)
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, StopIteration) as exc:
            raise BrandingAssetInvalid(
                "a valid MP4, MOV, WebM, MKV or AVI video is required"
            ) from exc
        finally:
            temporary.unlink(missing_ok=True)
        content_type = {"mp4": "video/mp4", "mov": "video/quicktime", "webm": "video/webm",
                        "mkv": "video/x-matroska", "avi": "video/x-msvideo"}[extension]
        return BrandingAsset(asset_id, f"branding/assets/{asset_id}", content_type)

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
