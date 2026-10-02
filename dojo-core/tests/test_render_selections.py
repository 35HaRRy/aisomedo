from __future__ import annotations

import hashlib
import json
from datetime import datetime
from types import SimpleNamespace

import pytest
from dojo import (
    DojoPublishing,
    InMemoryStore,
    MontageTrimInvalid,
    ReelBuild,
    ReelClip,
    ReviewStale,
    SchedulePlan,
)
from dojo.adapters import render as render_module
from dojo.adapters.stubs import StubMediaProcessor, StubReelRenderer
from dojo.testing import FIXED_AT, ISTANBUL, FakeClock

from tests.ffmpeg_transport import FfmpegTransport, docker_available


def make_video(tmp_path, duration=30.0):
    store = InMemoryStore()
    renderer = StubReelRenderer()
    store.set("branding.logo_asset", "logo.png", updated_at=FIXED_AT)
    seam = DojoPublishing(
        packages=store, audit=store, uploads=store, jobs=store, settings=store,
        media_root=tmp_path, clock=FakeClock(), renderer=renderer,
        media=StubMediaProcessor(content_type="video/mp4", duration=duration),
    )
    seam.get_or_create_active_package()
    upload = seam.start_upload("clip.mp4", "video/mp4", 100)
    data = b"x" * 100
    seam.append_upload_range(upload.upload_id, 0, 100, hashlib.sha256(data).hexdigest(), data)
    seam.complete_upload(upload.upload_id)
    seam.process_job(seam.claim_next_job().job_id)
    path = tmp_path / seam.get_active_package().folder_name / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    return store, seam, renderer, path, manifest["order"][0]


def run_render(seam):
    seam.render_preview()
    job = seam.claim_next_job()
    assert job is not None and job.kind == "render"
    seam.process_job(job.job_id)
    assert seam._jobs.get(job.job_id).status == "done"


def test_render_build_expands_sections_without_changing_sources(tmp_path):
    _, seam, renderer, path, mid = make_video(tmp_path)
    original = path.parent / "media" / mid / "original.mp4"
    before = original.read_bytes()
    seam.set_selections({mid: [{"start": 24.0, "end": 30.0},
                              {"start": 0.0, "end": 5.0},
                              {"start": 10.0, "end": 15.0}]},
                        expected_folder_name=seam.get_active_package().folder_name)
    run_render(seam)
    build = renderer.calls[0][0]
    assert [(c.trim_start, c.trim_end) for c in build.clips] == [
        (0.0, 5.0), (10.0, 15.0), (24.0, 30.0),
    ]
    assert [c.media_id for c in build.clips] == [mid, mid, mid]
    assert sum(c.duration for c in build.clips) == 16.0
    assert original.read_bytes() == before


def test_legacy_digest_and_manifest_survive_reads_until_explicit_edit(tmp_path):
    _, seam, _, path, mid = make_video(tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["trims"] = {mid: {"start": 10.0, "end": 20.0}}
    manifest.pop("selections", None)
    entry = manifest["media"][0]
    old_inputs = {
        "order": [{"media_id": mid, "filename": "clip.mp4", "content_type": "video/mp4",
                   "duration": 30.0, "is_video": True}],
        "trims": manifest["trims"], "branding": manifest["branding"],
        "caption": manifest["caption"], "photo_duration": 3.0,
    }
    old_digest = hashlib.sha256(json.dumps(old_inputs, sort_keys=True,
                                          ensure_ascii=False).encode()).hexdigest()
    manifest["render_revision"] = old_digest
    path.write_text(json.dumps(manifest), encoding="utf-8")
    before = path.read_bytes()
    assert seam.get_montage_status().combined_duration == 10.0
    assert seam.render_preview() == {"stale": False, "render_revision": old_digest}
    assert path.read_bytes() == before
    assert entry["processed"]["duration"] == 30.0
    seam.set_selections({mid: [{"start": 10.0, "end": 20.0}]},
                        expected_folder_name=seam.get_active_package().folder_name)
    assert seam.render_preview()["render_revision"] != old_digest


def test_section_edit_changes_digest_and_prevents_old_review_approval(tmp_path):
    _, seam, _, _, mid = make_video(tmp_path)
    monday = datetime(2026, 8, 3, 10, 0, tzinfo=ISTANBUL)
    seam._clock = FakeClock(monday)
    seam.set_plan(SchedulePlan(anchor_date=monday.date(), anchor_time=monday.time(), enabled=True))
    seam.evaluate_due_work()
    run_render(seam)
    review = seam.list_pending_reviews()[0]
    seam.set_selections({mid: [{"start": 0.0, "end": 5.0},
                              {"start": 10.0, "end": 15.0}]},
                        expected_folder_name=seam.get_active_package().folder_name)
    first_digest = seam.render_preview()["render_revision"]
    seam.set_selections({mid: [{"start": 0.0, "end": 4.0},
                              {"start": 10.0, "end": 15.0}]},
                        expected_folder_name=seam.get_active_package().folder_name)
    assert seam.render_preview()["render_revision"] != first_digest
    with pytest.raises(ReviewStale):
        seam.approve(review.id, review.version)


def test_unknown_duration_blocks_preview_and_render_build(tmp_path):
    _, seam, _, path, _ = make_video(tmp_path, duration=None)
    with pytest.raises(MontageTrimInvalid):
        seam.render_preview()
    with pytest.raises(MontageTrimInvalid):
        seam._build_reel(seam.get_active_package(), json.loads(path.read_text()))


@pytest.fixture
def ffmpeg(tmp_path, monkeypatch):
    if not docker_available():
        pytest.skip("Docker unavailable: real production renderer verification not executed")
    transport = FfmpegTransport(tmp_path)
    monkeypatch.setattr(render_module, "subprocess", SimpleNamespace(run=transport.run))
    yield transport.run
    transport.close()


def command(run, args, *, text=True):
    result = run(args, text=text)
    assert result.returncode == 0, result.stderr
    return result.stdout


def make_sources(tmp_path, run):
    source = tmp_path / "source.mp4"
    logo = tmp_path / "logo.png"
    inputs = [arg for color in ("red", "lime", "blue")
              for arg in ("-f", "lavfi", "-i", f"color=c={color}:s=160x90:d=2:r=25")]
    command(run, ["ffmpeg", "-y", *inputs, "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
                  "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
                  "-map", "[v]", "-map", "3:a", "-c:v", "libx264", "-c:a", "aac",
                  "-pix_fmt", "yuv420p", "-threads", "2", str(source)])
    command(run, ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=white:s=100x100:d=1",
                  "-frames:v", "1", str(logo)])
    return source, logo


def sample(run, path, time, x=540, y=960):
    return command(run, ["ffmpeg", "-v", "error", "-ss", str(time), "-i", str(path),
                         "-frames:v", "1", "-vf", f"crop=2:2:{x}:{y},scale=1:1",
                         "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"], text=False)


def probe(run, path):
    return json.loads(command(run, ["ffprobe", "-v", "error", "-show_streams", "-show_format",
                                   "-of", "json", str(path)]))


@pytest.mark.parametrize("cards", [False, True])
def test_production_render_keeps_color_order_audio_watermark_and_cards(tmp_path, ffmpeg, cards):
    source, logo = make_sources(tmp_path, ffmpeg)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    clips = [ReelClip(media_id="same-video", path=source, is_video=True, duration=0.4,
                      trim_start=start, trim_end=start + 0.4) for start in (0.0, 2.0, 4.0)]
    build = ReelBuild(clips=clips, photo_duration=3.0, logo_asset=logo,
                      intro_asset=logo if cards else None, intro_duration=0.2,
                      outro_asset=logo if cards else None, outro_duration=0.2)
    work, out = tmp_path / "segments", tmp_path / "reel.mp4"
    render_module.FfmpegReelRenderer().render(build, work, out)
    info = probe(ffmpeg, out)
    assert abs(float(info["format"]["duration"]) - (1.6 if cards else 1.2)) < 0.15
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"], video["codec_name"]) == (1080, 1920, "h264")
    assert next(s for s in info["streams"] if s["codec_type"] == "audio")["codec_name"] == "aac"
    for index, moment in enumerate((0.1, 0.5, 0.9)):
        rgb = sample(ffmpeg, out, moment + (0.2 if cards else 0))
        assert len(rgb) == 3
        assert rgb[index] > 180 and all(rgb[i] < 80 for i in range(3) if i != index)
    assert all(value > 180 for value in sample(ffmpeg, out, 0.3, 950, 1790))
    audio = command(ffmpeg, ["ffmpeg", "-v", "error", "-i", str(out), "-vn", "-f", "s16le",
                             "-ac", "1", "pipe:1"], text=False)
    assert any(audio)
    assert len(list(work.glob("*.mp4"))) == (5 if cards else 3)
    if cards:
        assert all(v > 180 for v in sample(ffmpeg, out, 0.04))
        assert all(v > 180 for v in sample(ffmpeg, out, 1.5))
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before


def test_production_nonzero_seek_preserves_generated_silent_audio(tmp_path, ffmpeg):
    source, logo = make_sources(tmp_path, ffmpeg)
    silent = tmp_path / "silent.mp4"
    command(ffmpeg, ["ffmpeg", "-y", "-i", str(source), "-an", "-c:v", "copy", str(silent)])
    build = ReelBuild(clips=[ReelClip(media_id="silent", path=silent, is_video=True, duration=0.4,
                                     trim_start=2.0, trim_end=2.4)], photo_duration=3,
                      logo_asset=logo)
    out = tmp_path / "silent-reel.mp4"
    render_module.FfmpegReelRenderer().render(build, tmp_path / "segments", out)
    info = probe(ffmpeg, out)
    assert abs(float(info["format"]["duration"]) - 0.4) < 0.1
    assert next(s for s in info["streams"] if s["codec_type"] == "audio")["codec_name"] == "aac"
    audio = command(ffmpeg, ["ffmpeg", "-v", "error", "-i", str(out), "-vn", "-f", "s16le",
                             "-ac", "1", "pipe:1"], text=False)
    assert len(audio) > 100
    assert not any(audio)
