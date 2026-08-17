from __future__ import annotations

import hashlib
import json

import pytest
from dojo import (
    DojoPublishing,
    InMemoryStore,
    UploadConflict,
    UploadDecisionInvalid,
    UploadNotFound,
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
    tmp_path, seam, *, filename="photo.jpg", content_type="image/jpeg", body: bytes | None = None
) -> str:
    """Upload + process + finalize one media file into the active package; return its media_id."""
    seam._media = StubMediaProcessor()
    seam.ensure_active_package()
    body = body or b"x" * 100
    status = seam.start_upload(filename, content_type, len(body))
    seam.append_upload_range(status.upload_id, 0, len(body), sha(body), body)
    seam.complete_upload(status.upload_id)
    claimed = seam.claim_next_job()
    assert claimed is not None
    seam.process_job(claimed.job_id)
    package = seam.get_active_package()
    media_dir = tmp_path / package.folder_name / "media"
    return next(iter(media_dir.iterdir())).name


def manifest_media(tmp_path, seam) -> list[dict]:
    package = seam.get_active_package()
    manifest = json.loads(
        (tmp_path / package.folder_name / "manifest.json").read_text(encoding="utf-8")
    )
    return manifest["media"]


def start_and_resolve(tmp_path, seam, *, decision, **kwargs) -> str:
    status = seam.start_upload("photo.jpg", "image/jpeg", 100)
    assert status.status == "conflict"
    seam.resolve_conflict(status.upload_id, decision, requester="7", **kwargs)
    seam.append_upload_range(status.upload_id, 0, 100, sha(b"x" * 100), b"x" * 100)
    seam.complete_upload(status.upload_id)
    claimed = seam.claim_next_job()
    assert claimed is not None
    seam.process_job(claimed.job_id)
    return status.upload_id


def test_start_upload_preserves_unicode_filename(tmp_path):
    _, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    status = seam.start_upload("dojo_antrenmanı.jpg", "image/jpeg", 100)
    assert status.status == "receiving"
    assert status.conflicts == []


def test_start_upload_detects_case_insensitive_collision(tmp_path):
    _, seam = make_seam(tmp_path)
    target = finalize_media(tmp_path, seam, filename="Photo.jpg")
    status = seam.start_upload("photo.JPG", "image/jpeg", 100)
    assert status.status == "conflict"
    assert status.received_bytes == 0
    assert [c["media_id"] for c in status.conflicts] == [target]
    assert status.conflicts[0]["filename"] == "Photo.jpg"


def test_start_upload_no_collision_stays_receiving(tmp_path):
    _, seam = make_seam(tmp_path)
    finalize_media(tmp_path, seam, filename="Photo.jpg")
    status = seam.start_upload("other.png", "image/png", 100)
    assert status.status == "receiving"
    assert status.conflicts == []


def test_resolve_unknown_upload_raises(tmp_path):
    _, seam = make_seam(tmp_path)
    with pytest.raises(UploadNotFound):
        seam.resolve_conflict("nope", "keep_both")


def test_resolve_non_conflict_upload_raises(tmp_path):
    _, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    status = seam.start_upload("fresh.jpg", "image/jpeg", 100)
    assert status.status == "receiving"
    with pytest.raises(UploadConflict):
        seam.resolve_conflict(status.upload_id, "keep_both")


def test_resolve_bad_decision_raises(tmp_path):
    _, seam = make_seam(tmp_path)
    finalize_media(tmp_path, seam, filename="photo.jpg")
    status = seam.start_upload("photo.jpg", "image/jpeg", 100)
    with pytest.raises(UploadDecisionInvalid):
        seam.resolve_conflict(status.upload_id, "delete_it")


def test_resolve_keep_both_suffixed_at_finalize(tmp_path):
    _, seam = make_seam(tmp_path)
    finalize_media(tmp_path, seam, filename="photo.jpg")
    start_and_resolve(tmp_path, seam, decision="keep_both")
    names = [e["filename"] for e in manifest_media(tmp_path, seam)]
    assert "photo.jpg" in names
    assert "photo (1).jpg" in names
    actions = [e.action for e in seam.list_audit()]
    assert "conflict.resolved" in actions


def test_resolve_keep_both_repeated_suffixes(tmp_path):
    _, seam = make_seam(tmp_path)
    finalize_media(tmp_path, seam, filename="photo.jpg")
    start_and_resolve(tmp_path, seam, decision="keep_both")
    start_and_resolve(tmp_path, seam, decision="keep_both")
    names = sorted(e["filename"] for e in manifest_media(tmp_path, seam))
    assert names == ["photo (1).jpg", "photo (2).jpg", "photo.jpg"]


def test_resolve_keep_selected_requires_confirmed_overwrite(tmp_path):
    _, seam = make_seam(tmp_path)
    target = finalize_media(tmp_path, seam, filename="photo.jpg")
    status = seam.start_upload("photo.jpg", "image/jpeg", 100)
    with pytest.raises(UploadDecisionInvalid):
        seam.resolve_conflict(status.upload_id, "keep_selected", target_media_id=target)
    with pytest.raises(UploadConflict):
        seam.resolve_conflict(status.upload_id, "keep_selected", confirmed_overwrite=True)


def test_resolve_keep_selected_destroys_target_and_audits(tmp_path):
    _, seam = make_seam(tmp_path)
    target = finalize_media(tmp_path, seam, filename="photo.jpg")
    package = seam.get_active_package()
    target_dir = tmp_path / package.folder_name / "media" / target
    assert target_dir.is_dir()
    status = seam.start_upload("photo.jpg", "image/jpeg", 100)
    resolved = seam.resolve_conflict(
        status.upload_id, "keep_selected", target_media_id=target, confirmed_overwrite=True
    )
    assert resolved.status == "receiving"
    seam.append_upload_range(status.upload_id, 0, 100, sha(b"x" * 100), b"x" * 100)
    seam.complete_upload(status.upload_id)
    claimed = seam.claim_next_job()
    assert claimed is not None
    seam.process_job(claimed.job_id)

    assert not target_dir.exists()
    entries = manifest_media(tmp_path, seam)
    assert len(entries) == 1
    assert entries[0]["filename"] == "photo.jpg"
    assert entries[0]["media_id"] != target
    actions = [e.action for e in seam.list_audit()]
    assert "media.overwritten" in actions


def test_resolve_keep_target_aborts_and_keeps_existing(tmp_path):
    _, seam = make_seam(tmp_path)
    target = finalize_media(tmp_path, seam, filename="photo.jpg")
    status = seam.start_upload("photo.jpg", "image/jpeg", 100)
    resolved = seam.resolve_conflict(status.upload_id, "keep_target")
    assert resolved.status == "aborted"
    assert [e["media_id"] for e in manifest_media(tmp_path, seam)] == [target]


def test_resolve_apply_to_all_keep_both(tmp_path):
    _, seam = make_seam(tmp_path)
    finalize_media(tmp_path, seam, filename="photo.jpg")
    a = seam.start_upload("photo.jpg", "image/jpeg", 100)
    b = seam.start_upload("photo.jpg", "image/jpeg", 100)
    assert a.status == "conflict"
    assert b.status == "conflict"
    resolved = seam.resolve_conflict(a.upload_id, "keep_both", apply_to_all=True)
    assert resolved.status == "receiving"
    assert seam.get_upload_status(a.upload_id).status == "receiving"
    assert seam.get_upload_status(b.upload_id).status == "receiving"


def test_resolve_apply_to_all_keep_target(tmp_path):
    _, seam = make_seam(tmp_path)
    finalize_media(tmp_path, seam, filename="photo.jpg")
    a = seam.start_upload("photo.jpg", "image/jpeg", 100)
    b = seam.start_upload("photo.jpg", "image/jpeg", 100)
    seam.resolve_conflict(a.upload_id, "keep_target", apply_to_all=True)
    assert seam.get_upload_status(a.upload_id).status == "aborted"
    assert seam.get_upload_status(b.upload_id).status == "aborted"


def test_resolve_apply_to_all_keep_selected(tmp_path):
    _, seam = make_seam(tmp_path)
    target = finalize_media(tmp_path, seam, filename="photo.jpg")
    a = seam.start_upload("photo.jpg", "image/jpeg", 100)
    b = seam.start_upload("photo.jpg", "image/jpeg", 100)
    resolved = seam.resolve_conflict(
        a.upload_id,
        "keep_selected",
        target_media_id=target,
        confirmed_overwrite=True,
        apply_to_all=True,
    )
    assert resolved.status == "receiving"
    assert seam.get_upload_status(a.upload_id).status == "receiving"
    assert seam.get_upload_status(b.upload_id).status == "receiving"