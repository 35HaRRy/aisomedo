import hashlib
import shutil
import subprocess
from array import array

import pytest
from dojo.adapters.render import FfmpegReelRenderer
from dojo.model import ReelClip
from PIL import Image

from .test_render_selections import command, make_sources, probe, sample


@pytest.fixture
def media_tools():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("Native FFmpeg unavailable: real preview encoding check not executed")
    def run(args, *, text=True):
        return subprocess.run(args, capture_output=True, text=text)

    return run


def test_section_preview_preserves_real_colors_audio_order_and_source(tmp_path, media_tools):
    base, _ = make_sources(tmp_path, media_tools)
    source = tmp_path / "tones.mp4"
    command(media_tools, ["ffmpeg", "-y", "-i", str(base),
        "-f", "lavfi", "-i", "sine=frequency=220:duration=2",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-f", "lavfi", "-i", "sine=frequency=880:duration=2",
        "-filter_complex", "[1:a][2:a][3:a]concat=n=3:v=0:a=1[a]",
        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", str(source)])
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    renderer = FfmpegReelRenderer()
    out = tmp_path / "preview.mp4"
    clips = [ReelClip(media_id="video", path=source, is_video=True, duration=0.4,
                      trim_start=start, trim_end=start + 0.4) for start in (0.0, 4.0)]
    renderer.render_sections(clips, tmp_path / "segments", out, cancelled=lambda: False)
    assert abs(renderer.probe_duration(out, cancelled=lambda: False) - 0.8) <= 1 / 25 + 0.05
    assert sample(media_tools, out, 0.1)[0] > 180
    assert sample(media_tools, out, 0.5)[2] > 180
    assert not all(value > 180 for value in sample(media_tools, out, 0.5, 950, 1790))
    for moment, low, high in [(0.1, 200, 240), (0.5, 860, 900)]:
        raw = command(media_tools, ["ffmpeg", "-v", "error", "-ss", str(moment),
            "-i", str(out), "-t", "0.2", "-vn", "-ac", "1", "-ar", "8000",
            "-f", "s16le", "pipe:1"], text=False)
        samples = array("h", raw)
        crossings = sum(a <= 0 < b for a, b in zip(samples, samples[1:]))
        assert low <= crossings * 8000 / len(samples) <= high
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert len(list((tmp_path / "segments").glob("*.mp4"))) == 2


def test_silent_section_and_reusable_thumbnail(tmp_path, media_tools):
    source, _ = make_sources(tmp_path, media_tools)
    silent = tmp_path / "silent.mp4"
    command(media_tools, ["ffmpeg", "-y", "-i", str(source), "-an", "-c:v", "copy", str(silent)])
    renderer = FfmpegReelRenderer()
    out = tmp_path / "silent-preview.mp4"
    renderer.render_sections([ReelClip(media_id="silent", path=silent, is_video=True,
        duration=0.4, trim_start=2.0, trim_end=2.4)], tmp_path / "segments", out,
        cancelled=lambda: False)
    assert any(stream["codec_type"] == "audio" for stream in probe(media_tools, out)["streams"])
    audio = command(media_tools, ["ffmpeg", "-v", "error", "-i", str(out), "-vn",
        "-ac", "1", "-f", "s16le", "pipe:1"], text=False)
    assert len(audio) > 100 and not any(audio)
    thumbnail = tmp_path / "thumbnail.jpg"
    renderer.render_thumbnail(source, thumbnail, cancelled=lambda: False)
    with Image.open(thumbnail) as image:
        assert image.format == "JPEG" and max(image.size) <= 640
