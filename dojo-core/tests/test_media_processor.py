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
from PIL import Image, ImageDraw

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


@pytest.mark.parametrize("mode,extension", [
    ("RGBA", "png"), ("LA", "png"), ("P", "png"), ("RGB", "png"), ("RGBA", "webp"),
])
def test_image_transparency_preserved(tmp_path: Path, mode: str, extension: str) -> None:
    src = tmp_path / f"transparent.{extension}"
    image = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((20, 20, 80, 80), fill=(255, 255, 255, 255))
    ImageDraw.Draw(image).rectangle((40, 40, 60, 60), fill=(0, 0, 0, 0))
    image.putpixel((20, 20), (255, 255, 255, 128))
    image = image.convert(mode)
    if mode == "RGB":
        image.save(src, transparency=(0, 0, 0))
    else:
        image.save(src)
    processor = PillowFFmpegProcessor()
    out = processor.process(make_upload(src.name, f"image/{extension}"), src, tmp_path)
    with Image.open(out.processed_path) as img:
        assert img.convert("RGBA").getpixel((0, 0))[3] == 0
        assert img.convert("RGBA").getpixel((50, 50))[3] == 0
        assert img.convert("RGBA").getpixel((30, 30)) == (255, 255, 255, 255)
        if mode != "RGB":
            assert img.convert("RGBA").getpixel((20, 20))[3] == 128
        assert img.format == "PNG"
    assert out.content_type == "image/png"
    assert out.processed_path.suffix == ".png"


@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg unavailable")
def test_transparent_logo_render_ignores_hidden_rgb(tmp_path: Path) -> None:
    from dojo.adapters.render import FfmpegReelRenderer

    src = tmp_path / "logo.png"
    image = Image.new("RGBA", (108, 192), (255, 0, 255, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 10, 98, 182), fill=(255, 255, 255, 255))
    draw.rectangle((25, 25, 83, 167), fill=(255, 0, 255, 0))
    image.save(src)
    out = PillowFFmpegProcessor().process(make_upload(src.name, "image/png"), src, tmp_path)
    segment = FfmpegReelRenderer()._render_segment(
        out.processed_path, is_video=False, duration=0.12,
        logo_asset=None, work_dir=tmp_path, name="transparent",
    )
    frame = tmp_path / "frame.png"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(segment),
         "-frames:v", "1", str(frame)], check=True, capture_output=True,
    )
    with Image.open(frame) as rendered:
        assert max(rendered.getpixel((540, 960))) < 10
        assert min(rendered.getpixel((150, 960))) > 245


@pytest.mark.parametrize("mode", ["RGB", "RGBA"])
def test_dimension_cap_applied(tmp_path: Path, mode: str) -> None:
    src = tmp_path / "big.png"
    Image.new(mode, (8000, 1000), (0, 0, 255, 128) if mode == "RGBA" else "blue").save(src)
    processor = PillowFFmpegProcessor()
    out = processor.process(make_upload("big.png", "image/png"), src, tmp_path)
    with Image.open(out.processed_path) as img:
        assert max(img.size) <= 4000
        if mode == "RGBA":
            assert img.getpixel((0, 0))[3] == 128


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
