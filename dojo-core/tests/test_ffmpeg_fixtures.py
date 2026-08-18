from __future__ import annotations

import json
from pathlib import Path

import pytest
from dojo.testing import FFMPEG_IMAGE, probe_duration, render_test_clip


def _docker_available() -> bool:
    try:
        import docker

        docker.from_env().ping()
        return True
    except Exception:
        return False


def _docker_run(tmp_path: Path, entrypoint: str, command: list[str]) -> str:
    import docker

    client = docker.from_env()
    logs = client.containers.run(
        FFMPEG_IMAGE,
        command=command,
        volumes={str(tmp_path.resolve()): {"bind": "/work", "mode": "rw"}},
        entrypoint=entrypoint,
        remove=True,
    )
    return logs.decode()


@pytest.mark.skipif(not _docker_available(), reason="docker unavailable")
def test_ffmpeg_container_renders_deterministic_clip(tmp_path: Path) -> None:
    clip = render_test_clip(tmp_path / "fixture.mp4")

    assert clip.exists()
    assert clip.stat().st_size > 0
    assert abs(probe_duration(clip) - 1.0) < 0.05


@pytest.mark.skipif(not _docker_available(), reason="docker unavailable")
def test_reel_render_pipeline_1080x1920_with_audio(tmp_path: Path) -> None:
    """Validate the render filter graph: blurred fit, watermark, clip audio."""
    _docker_run(
        tmp_path,
        "ffmpeg",
        [
            "-y",
            "-f", "lavfi", "-i", "testsrc=duration=1:size=1080x1920:rate=25",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:v", "libx264", "-c:a", "aac",
            "-movflags", "+faststart",
            "/work/clip.mp4",
        ],
    )
    _docker_run(
        tmp_path,
        "ffmpeg",
        [
            "-y", "-f", "lavfi",
            "-i", "color=c=blue:size=1080x1920:d=1",
            "-frames:v", "1", "/work/photo.jpg",
        ],
    )
    _docker_run(
        tmp_path,
        "ffmpeg",
        [
            "-y", "-f", "lavfi",
            "-i", "color=c=red:size=100x100:d=1",
            "-frames:v", "1", "/work/logo.png",
        ],
    )

    _docker_run(
        tmp_path,
        "ffmpeg",
        [
            "-y", "-i", "/work/clip.mp4", "-i", "/work/logo.png",
            "-filter_complex",
            "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
            "boxblur=luma_radius=20:luma_power=2:chroma_radius=20:chroma_power=2[bg];"
            "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2[base];"
            "[base][1:v]overlay=W-w-48:H-h-48:format=auto[vout]",
            "-map", "[vout]", "-map", "0:a",
            "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "/work/seg-v.mp4",
        ],
    )
    _docker_run(
        tmp_path,
        "ffmpeg",
        [
            "-y", "-loop", "1", "-framerate", "25", "-i", "/work/photo.jpg",
            "-i", "/work/logo.png",
            "-f", "lavfi", "-t", "1", "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-filter_complex",
            "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
            "boxblur=luma_radius=20:luma_power=2:chroma_radius=20:chroma_power=2[bg];"
            "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2[base];"
            "[base][1:v]overlay=W-w-48:H-h-48:format=auto[vout]",
            "-map", "[vout]", "-map", "2:a",
            "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", "-t", "1",
            "/work/seg-p.mp4",
        ],
    )

    reel = tmp_path / "reel.mp4"
    (tmp_path / "concat.txt").write_text(
        "file '/work/seg-v.mp4'\nfile '/work/seg-p.mp4'\n",
        encoding="utf-8",
    )
    _docker_run(
        tmp_path,
        "ffmpeg",
        ["-y", "-f", "concat", "-safe", "0",
         "-i", "/work/concat.txt", "-c", "copy", "/work/reel.mp4"],
    )

    out = _docker_run(
        tmp_path,
        "ffprobe",
        ["-v", "error", "-print_format", "json",
         "-show_streams", "-show_format", "/work/reel.mp4"],
    )
    info = json.loads(out)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (1080, 1920)
    assert any(s["codec_type"] == "audio" for s in info["streams"])
    assert abs(float(info["format"]["duration"]) - 2.0) < 0.1
    assert reel.exists()
