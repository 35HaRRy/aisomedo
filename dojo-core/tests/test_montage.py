from __future__ import annotations

import hashlib
import json

from dojo import (
    DojoPublishing,
    InMemoryStore,
)
from dojo.adapters.stubs import (
    StubMediaProcessor,
    StubMetaPublisher,
    StubNotifier,
    StubSignedUrlStore,
)
from dojo.testing import FakeClock


def make_seam(tmp_path, **overrides):
    store = InMemoryStore()
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
            **overrides,
        ),
    )


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def finalize_media(
    tmp_path, seam, store, *, filename="pic.jpg",
    content_type="image/jpeg", duration=None,
) -> str:
    """Upload + process one media and return its media_id."""
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


def test_video_entry_stores_duration(tmp_path):
    store, seam = make_seam(tmp_path)
    media_id = finalize_media(
        tmp_path, seam, store, filename="clip.mp4",
        content_type="video/mp4", duration=12.0,
    )
    package = seam.get_active_package()
    manifest = json.loads(
        (tmp_path / package.folder_name / "manifest.json").read_text(encoding="utf-8")
    )
    entry = next(e for e in manifest["media"] if e["media_id"] == media_id)
    assert entry["processed"]["duration"] == 12.0


def test_photo_entry_has_no_duration(tmp_path):
    store, seam = make_seam(tmp_path)
    media_id = finalize_media(tmp_path, seam, store, filename="pic.jpg")
    package = seam.get_active_package()
    manifest = json.loads(
        (tmp_path / package.folder_name / "manifest.json").read_text(encoding="utf-8")
    )
    entry = next(e for e in manifest["media"] if e["media_id"] == media_id)
    assert "duration" not in entry["processed"]


def test_finalize_clears_render_revision(tmp_path):
    store, seam = make_seam(tmp_path)
    seam.get_or_create_active_package()
    status = seam.start_upload("a.jpg", "image/jpeg", 100)
    seam.append_upload_range(status.upload_id, 0, 100, sha(b"x" * 100), b"x" * 100)
    seam.complete_upload(status.upload_id)
    job = seam.claim_next_job()
    assert job is not None
    package = seam.get_active_package()
    manifest_path = tmp_path / package.folder_name / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["render_revision"] = "rev-1"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    seam._media = StubMediaProcessor()
    seam.process_job(job.job_id)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["render_revision"] is None