from __future__ import annotations

import hashlib
import json

import pytest
from dojo import (
    DojoPublishing,
    InMemoryStore,
    LogoNotConfigured,
    MontageDurationExceeded,
    NoActivePackage,
    ReelBuild,
    RenderFailed,
)
from dojo.adapters.stubs import (
    StubMediaProcessor,
    StubMetaPublisher,
    StubNotifier,
    StubReelRenderer,
    StubSignedUrlStore,
)
from dojo.testing import FIXED_AT, FakeClock


def make_seam(tmp_path, **overrides):
    store = InMemoryStore()
    renderer = StubReelRenderer()
    return (
        store,
        DojoPublishing(
            packages=store,
            audit=store,
            uploads=store,
            jobs=store,
            settings=store,
            media_root=tmp_path,
            clock=FakeClock(),
            meta=StubMetaPublisher(),
            notifier=StubNotifier(),
            signed_urls=StubSignedUrlStore(),
            renderer=renderer,
            **overrides,
        ),
        renderer,
    )


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def finalize_media(
    tmp_path, seam, *, filename="pic.jpg",
    content_type="image/jpeg", duration=None,
) -> str:
    seam._media = StubMediaProcessor(content_type=content_type, duration=duration)
    seam.get_or_create_active_package()
    status = seam.start_upload(filename, content_type, 100)
    seam.append_upload_range(status.upload_id, 0, 100, sha(b"x" * 100), b"x" * 100)
    seam.complete_upload(status.upload_id)
    job = seam.claim_next_job()
    assert job is not None
    seam.process_job(job.job_id)
    package = seam.get_active_package()
    manifest = json.loads(
        (tmp_path / package.folder_name / "manifest.json").read_text(encoding="utf-8")
    )
    return next(e["media_id"] for e in manifest["media"] if e["filename"] == filename)


def set_logo(store, path: str | None) -> None:
    store.set("branding.logo_asset", path, updated_at=FIXED_AT)


def load_manifest(tmp_path, seam):
    package = seam.get_active_package()
    return json.loads(
        (tmp_path / package.folder_name / "manifest.json").read_text(encoding="utf-8")
    )


def claim_render(seam):
    job = seam.claim_next_job()
    assert job is not None
    assert job.kind == "render"
    seam.process_job(job.job_id)
    return job


def test_render_requires_active_package(tmp_path):
    _, seam, _ = make_seam(tmp_path)
    with pytest.raises(NoActivePackage):
        seam.render_preview()


def test_render_requires_logo(tmp_path):
    _, seam, _ = make_seam(tmp_path)
    seam.get_or_create_active_package()
    with pytest.raises(LogoNotConfigured):
        seam.render_preview()


def test_preview_enqueues_render_when_stale(tmp_path):
    store, seam, renderer = make_seam(tmp_path)
    set_logo(store, "logo.png")
    finalize_media(tmp_path, seam)

    result = seam.render_preview()

    assert result["stale"] is True
    assert result["render_revision"]
    job = seam.claim_next_job()
    assert job is not None and job.kind == "render"
    assert job.payload["digest"] == result["render_revision"]
    assert "render.queued" in [e.action for e in seam.list_audit()]


def test_preview_noop_when_fresh(tmp_path):
    store, seam, renderer = make_seam(tmp_path)
    set_logo(store, "logo.png")
    finalize_media(tmp_path, seam)
    seam.render_preview()
    claim_render(seam)

    result = seam.render_preview()

    assert result["stale"] is False
    assert seam.claim_next_job() is None


def test_render_job_writes_artifact_and_sets_digest(tmp_path):
    store, seam, renderer = make_seam(tmp_path)
    set_logo(store, "logo.png")
    finalize_media(tmp_path, seam)
    preview = seam.render_preview()
    claim_render(seam)

    package = seam.get_active_package()
    artifact = tmp_path / package.folder_name / "render" / "reel.mp4"
    assert artifact.is_file()
    assert artifact.read_bytes() == b"fake-reel"
    manifest = load_manifest(tmp_path, seam)
    assert manifest["render_revision"] == preview["render_revision"]
    assert "render.completed" in [e.action for e in seam.list_audit()]


def test_render_job_failure_marks_job_failed(tmp_path):
    store, seam, renderer = make_seam(tmp_path)
    set_logo(store, "logo.png")
    finalize_media(tmp_path, seam)
    seam.render_preview()
    renderer.fail_reason = "boom"
    job = seam.claim_next_job()
    assert job is not None
    seam.process_job(job.job_id)

    failed = seam._jobs.get(job.job_id)
    assert failed is not None and failed.status == "failed"
    assert failed.error_reason == "boom"
    manifest = load_manifest(tmp_path, seam)
    assert manifest["render_revision"] is None
    assert "render.rejected" in [e.action for e in seam.list_audit()]


def test_digest_changes_on_input_edit(tmp_path):
    store, seam, renderer = make_seam(tmp_path)
    set_logo(store, "logo.png")
    a = finalize_media(tmp_path, seam, filename="a.jpg")
    b = finalize_media(tmp_path, seam, filename="b.jpg")
    seam.render_preview()
    claim_render(seam)
    digest_a = load_manifest(tmp_path, seam)["render_revision"]

    seam.set_order([b, a])
    digest_order = load_manifest(tmp_path, seam)
    assert digest_order["render_revision"] is None
    seam.render_preview()
    claim_render(seam)
    digest_b = load_manifest(tmp_path, seam)["render_revision"]
    assert digest_b != digest_a


def test_build_reel_resolves_clip_paths_and_assets(tmp_path):
    store, seam, renderer = make_seam(tmp_path)
    set_logo(store, "assets/logo.png")
    finalize_media(tmp_path, seam, filename="a.jpg")
    finalize_media(tmp_path, seam, filename="clip.mp4",
                   content_type="video/mp4", duration=10.0)
    package = seam.get_active_package()
    manifest = load_manifest(tmp_path, seam)

    build = seam._build_reel(package, manifest)

    assert isinstance(build, ReelBuild)
    assert len(build.clips) == 2
    assert build.logo_asset == (tmp_path / "assets" / "logo.png")
    assert build.clips[0].path.is_absolute()
    assert build.clips[1].is_video is True
    assert build.clips[1].duration == 10.0
    assert build.clips[0].duration == build.photo_duration


def test_render_preview_rejects_over_limit(tmp_path):
    store, seam, renderer = make_seam(tmp_path)
    store.set("montage.max_duration_seconds", 2.0, updated_at=FIXED_AT)
    set_logo(store, "logo.png")
    finalize_media(tmp_path, seam)  # photo default 3.0s > 2.0s limit

    with pytest.raises(MontageDurationExceeded):
        seam.render_preview()


def test_render_job_stamps_digest_of_current_manifest(tmp_path):
    store, seam, renderer = make_seam(tmp_path)
    set_logo(store, "logo.png")
    a = finalize_media(tmp_path, seam, filename="a.jpg")
    b = finalize_media(tmp_path, seam, filename="b.jpg")
    seam.render_preview()  # enqueues digest D1
    seam.set_order([b, a])  # inputs change after enqueue

    job = seam.claim_next_job()
    assert job is not None and job.kind == "render"
    seam.process_job(job.job_id)

    manifest = load_manifest(tmp_path, seam)
    assert manifest["render_revision"] == seam.render_preview()["render_revision"]
    assert manifest["render_revision"] != job.payload["digest"]


def test_build_reel_requires_watermark(tmp_path):
    store, seam, renderer = make_seam(tmp_path)
    finalize_media(tmp_path, seam)
    package = seam.get_active_package()
    manifest = load_manifest(tmp_path, seam)

    with pytest.raises(RenderFailed):
        seam._build_reel(package, manifest)