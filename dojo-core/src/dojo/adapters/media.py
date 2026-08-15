from __future__ import annotations

import subprocess
from pathlib import Path

from dojo.exceptions import MediaValidationError
from dojo.model import ProcessedMedia, Upload

IMAGE_TYPES = {"jpeg", "png", "webp", "heic", "heif", "mif1"}
VIDEO_TYPES = {"mp4", "mov", "qt"}
MAX_IMAGE_DIMENSION = 4000


def detect_container(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data.startswith(b"\x00\x00\x00") and b"ftyp" in data[:32]:
        brand = data[4:32]
        if any(name in brand for name in (b"heic", b"heix", b"heif", b"mif1")):
            return "heic"
        if b"qt  " in brand:
            return "mov"
        return "mp4"
    raise MediaValidationError("unrecognized file content")


class PillowFFmpegProcessor:
    """Validate real media content, normalize images, and transcode video."""

    def process(self, upload: Upload, original_path: Path, work_dir: Path) -> ProcessedMedia:
        data = original_path.read_bytes()[:64]
        try:
            kind = detect_container(data)
        except MediaValidationError as exc:
            raise MediaValidationError(f"{exc}: {upload.filename}") from exc
        if kind in IMAGE_TYPES:
            return self._process_image(original_path, work_dir)
        if kind in VIDEO_TYPES:
            return self._process_video(original_path, work_dir)
        raise MediaValidationError(f"unsupported media type: {kind}")

    @staticmethod
    def _process_image(original_path: Path, work_dir: Path) -> ProcessedMedia:
        import pillow_heif

        pillow_heif.register_heif_opener()
        from PIL import Image, ImageOps

        processed_path = work_dir / "processed.jpg"
        try:
            with Image.open(original_path) as src:
                if getattr(src, "n_frames", 1) > 1:
                    raise MediaValidationError("animated images are not supported")
                img = ImageOps.exif_transpose(src)
                if img.mode != "RGB":
                    img = img.convert("RGB")
                if max(img.size) > MAX_IMAGE_DIMENSION:
                    scale = MAX_IMAGE_DIMENSION / max(img.size)
                    img = img.resize(
                        (round(img.width * scale), round(img.height * scale))
                    )
                img.save(processed_path, format="JPEG", quality=90)
        except MediaValidationError:
            raise
        except Exception as exc:
            raise MediaValidationError(f"could not decode image: {exc}") from exc
        return ProcessedMedia(
            original_path=original_path,
            processed_path=processed_path,
            content_type="image/jpeg",
            size_bytes=processed_path.stat().st_size,
        )

    @staticmethod
    def _probe(path: Path) -> dict[str, str | None]:
        def probe_stream(stream: str) -> str | None:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    stream,
                    "-show_entries",
                    "stream=codec_name,width,height",
                    "-of",
                    "csv=p=0",
                    str(path),
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise MediaValidationError(f"could not probe video: {result.stderr.strip()}")
            return result.stdout.strip() or None

        video = probe_stream("v:0") or ""
        audio = probe_stream("a:0")
        codec, width, height = (video.split(",") + ["", "", ""])[:3]
        return {
            "codec": codec,
            "width": width,
            "height": height,
            "audio": audio.split(",")[0] if audio else None,
        }

    def _process_video(self, original_path: Path, work_dir: Path) -> ProcessedMedia:
        source = self._probe(original_path)
        processed_path = work_dir / "processed.mp4"
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(original_path),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(processed_path),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not processed_path.is_file():
            raise MediaValidationError(
                f"video transcoding failed: {result.stderr.strip()[:200]}"
            )
        probe = self._probe(processed_path)
        if probe["codec"] != "h264":
            raise MediaValidationError(f"transcoded video is not H.264: {probe['codec']}")
        if probe["width"] != source["width"] or probe["height"] != source["height"]:
            raise MediaValidationError(
                f"resolution changed: {source['width']}x{source['height']} -> "
                f"{probe['width']}x{probe['height']}"
            )
        if source["audio"] and probe["audio"] != "aac":
            raise MediaValidationError(
                f"audio is {probe['audio']}, expected aac"
            )
        return ProcessedMedia(
            original_path=original_path,
            processed_path=processed_path,
            content_type="video/mp4",
            size_bytes=processed_path.stat().st_size,
        )
