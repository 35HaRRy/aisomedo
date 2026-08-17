from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pillow_heif
import pytest
from dojo.adapters.media import PillowFFmpegProcessor
from dojo.exceptions import MediaValidationError
from dojo.model import Upload
from dojo.testing import FIXED_AT, render_test_clip
from PIL import Image

pillow_heif.register_heif_opener()


def make_upload(filename: str, content_type: str) -> Upload:
    return Upload(
        id=1,
        upload_id="u-1",
        package_id=1,
        filename=filename,
        content_type=content_type,
        declared_size_bytes=0,
        received_ranges=[],
        received_bytes=0,
        status="queued",
        created_at=FIXED_AT,
        updated_at=FIXED_AT,
    )


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _docker_available() -> bool:
    try:
        import docker

        docker.from_env().ping()
        return True
    except Exception:
        return False


def test_jpeg_accepted_and_normalized(tmp_path: Path) -> None:
    src = tmp_path / "input.jpg"
    Image.new("RGB", (2000, 1000), "red").save(src, format="JPEG")
    processor = PillowFFmpegProcessor()
    out = processor.process(make_upload("input.jpg", "image/jpeg"), src, tmp_path)
    with Image.open(out.processed_path) as img:
        assert img.format == "JPEG"
        assert img.mode == "RGB"
    assert out.content_type == "image/jpeg"


def test_rgba_png_accepted(tmp_path: Path) -> None:
    src = tmp_path / "rgba.png"
    Image.new("RGBA", (100, 100), (255, 0, 0, 128)).save(src, format="PNG")
    processor = PillowFFmpegProcessor()
    out = processor.process(make_upload("rgba.png", "image/png"), src, tmp_path)
    with Image.open(out.processed_path) as img:
        assert img.format == "JPEG"
        assert img.mode == "RGB"
    assert out.content_type == "image/jpeg"


def test_dimension_cap_applied(tmp_path: Path) -> None:
    src = tmp_path / "big.png"
    Image.new("RGB", (8000, 1000), "blue").save(src, format="PNG")
    processor = PillowFFmpegProcessor()
    out = processor.process(make_upload("big.png", "image/png"), src, tmp_path)
    with Image.open(out.processed_path) as img:
        assert max(img.size) <= 4000


def test_heic_accepted(tmp_path: Path) -> None:
    src = tmp_path / "input.heic"
    Image.new("RGB", (300, 300), "green").save(src, format="HEIF")
    processor = PillowFFmpegProcessor()
    out = processor.process(make_upload("input.heic", "image/heic"), src, tmp_path)
    with Image.open(out.processed_path) as img:
        assert img.format == "JPEG"


def test_corrupt_image_rejected(tmp_path: Path) -> None:
    src = tmp_path / "bad.jpg"
    src.write_bytes(b"not an image at all")
    processor = PillowFFmpegProcessor()
    with pytest.raises(MediaValidationError):
        processor.process(make_upload("bad.jpg", "image/jpeg"), src, tmp_path)


def test_animated_webp_rejected(tmp_path: Path) -> None:
    src = tmp_path / "anim.webp"
    frames = [Image.new("RGB", (50, 50), color) for color in ("red", "blue", "green")]
    frames[0].save(src, format="WEBP", save_all=True, append_images=frames[1:], duration=100)
    processor = PillowFFmpegProcessor()
    with pytest.raises(MediaValidationError):
        processor.process(make_upload("anim.webp", "image/webp"), src, tmp_path)


def test_unsupported_format_rejected(tmp_path: Path) -> None:
    src = tmp_path / "file.bmp"
    Image.new("RGB", (10, 10)).save(src, format="BMP")
    processor = PillowFFmpegProcessor()
    with pytest.raises(MediaValidationError):
        processor.process(make_upload("file.bmp", "image/bmp"), src, tmp_path)


@pytest.mark.skipif(not _docker_available(), reason="docker unavailable")
@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg unavailable")
def test_video_transcoded_to_h264_aac(tmp_path: Path) -> None:
    clip = render_test_clip(tmp_path / "fixture.mp4")
    processor = PillowFFmpegProcessor()
    out = processor.process(make_upload("fixture.mp4", "video/mp4"), clip, tmp_path)
    assert out.content_type == "video/mp4"
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height",
            "-of",
            "csv=p=0",
            str(out.processed_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert probe.stdout.strip().startswith("h264")
    assert out.duration is not None
    assert out.duration > 0.0


@pytest.mark.skipif(not _docker_available(), reason="docker unavailable")
@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg unavailable")
def test_video_mov_accepted(tmp_path: Path) -> None:
    clip = render_test_clip(tmp_path / "fixture.mov")
    processor = PillowFFmpegProcessor()
    out = processor.process(make_upload("fixture.mov", "video/quicktime"), clip, tmp_path)
    assert out.content_type == "video/mp4"
