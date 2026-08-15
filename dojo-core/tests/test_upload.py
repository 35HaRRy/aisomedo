from __future__ import annotations

import hashlib

import pytest
from dojo import (
    DojoPublishing,
    InMemoryStore,
    PackageLimitExceeded,
    UploadChecksumMismatch,
    UploadConflict,
    UploadIncomplete,
    UploadInvalidFilename,
    UploadNotFound,
    UploadNotReceiving,
    UploadTooLarge,
)
from dojo.adapters.stubs import StubMetaPublisher, StubNotifier, StubSignedUrlStore
from dojo.testing import FIXED_AT, FakeClock


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


def test_start_upload_creates_staging_and_audits(tmp_path):
    store, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    status = seam.start_upload("pic.jpg", "image/jpeg", 100, requester="7")
    assert status.declared_size_bytes == 100
    assert status.received_bytes == 0
    assert status.status == "receiving"
    staging = tmp_path / "tmp" / status.upload_id
    assert staging.is_dir()
    events = seam.list_audit()
    assert events[0].action == "upload.started"
    assert events[0].actor == "7"


def test_start_upload_rejects_unsafe_filename(tmp_path):
    _, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    for bad in ("a/b.jpg", "a\\b.jpg", "a\x00b.jpg", "a\x01b.jpg", ""):
        with pytest.raises(UploadInvalidFilename):
            seam.start_upload(bad, "image/jpeg", 100)


def test_start_upload_rejects_file_over_limit(tmp_path):
    _, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    with pytest.raises(UploadTooLarge):
        seam.start_upload("big.mp4", "video/mp4", 2 * 1024**3 + 1)


def test_start_upload_rejects_package_over_limit(tmp_path):
    store, seam = make_seam(tmp_path)
    store.set("upload.max_package_bytes", 150, updated_at=FIXED_AT)
    seam.ensure_active_package()
    seam.start_upload("a.jpg", "image/jpeg", 100)
    with pytest.raises(PackageLimitExceeded):
        seam.start_upload("b.jpg", "image/jpeg", 100)


def test_append_range_writes_and_merges(tmp_path):
    _, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    status = seam.start_upload("pic.jpg", "image/jpeg", 100)
    body = b"x" * 50
    progress = seam.append_upload_range(status.upload_id, 0, 50, sha(body), body)
    assert progress.received_bytes == 50
    staged = tmp_path / "tmp" / status.upload_id / "original"
    assert staged.read_bytes() == body
    progress2 = seam.append_upload_range(status.upload_id, 50, 50, sha(b"y" * 50), b"y" * 50)
    assert progress2.received_bytes == 100
    assert progress2.received_ranges == [[0, 100]]
    assert staged.read_bytes() == body + b"y" * 50


def test_append_range_out_of_order_writes_at_offset(tmp_path):
    _, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    status = seam.start_upload("pic.jpg", "image/jpeg", 100)
    seam.append_upload_range(status.upload_id, 0, 50, sha(b"a" * 50), b"a" * 50)
    seam.append_upload_range(status.upload_id, 60, 40, sha(b"b" * 40), b"b" * 40)
    seam.append_upload_range(status.upload_id, 50, 10, sha(b"c" * 10), b"c" * 10)
    staged = tmp_path / "tmp" / status.upload_id / "original"
    assert staged.read_bytes() == b"a" * 50 + b"c" * 10 + b"b" * 40
    assert seam.get_upload_status(status.upload_id).received_ranges == [[0, 100]]
    assert seam.get_upload_status(status.upload_id).received_bytes == 100


def test_append_range_overlap_rewrites_content(tmp_path):
    _, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    status = seam.start_upload("pic.jpg", "image/jpeg", 100)
    seam.append_upload_range(status.upload_id, 0, 100, sha(b"x" * 100), b"x" * 100)
    seam.append_upload_range(status.upload_id, 0, 50, sha(b"y" * 50), b"y" * 50)
    staged = tmp_path / "tmp" / status.upload_id / "original"
    assert staged.read_bytes() == b"y" * 50 + b"x" * 50
    assert seam.get_upload_status(status.upload_id).received_ranges == [[0, 100]]
    assert seam.get_upload_status(status.upload_id).received_bytes == 100


def test_append_range_duplicate_is_idempotent(tmp_path):
    _, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    status = seam.start_upload("pic.jpg", "image/jpeg", 100)
    body = b"x" * 50
    seam.append_upload_range(status.upload_id, 0, 50, sha(body), body)
    again = seam.append_upload_range(status.upload_id, 0, 50, sha(body), body)
    assert again.received_bytes == 50
    assert again.received_ranges == [[0, 50]]


def test_append_range_checksum_mismatch_rejected(tmp_path):
    _, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    status = seam.start_upload("pic.jpg", "image/jpeg", 100)
    with pytest.raises(UploadChecksumMismatch):
        seam.append_upload_range(status.upload_id, 0, 50, sha(b"wrong"), b"actual")


def test_append_range_out_of_declared_rejected(tmp_path):
    _, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    status = seam.start_upload("pic.jpg", "image/jpeg", 100)
    body = b"x" * 10
    with pytest.raises(UploadConflict):
        seam.append_upload_range(status.upload_id, 95, 10, sha(body), body)


def test_append_range_unknown_upload(tmp_path):
    _, seam = make_seam(tmp_path)
    with pytest.raises(UploadNotFound):
        seam.append_upload_range("nope", 0, 1, "abc", b"x")


def test_append_after_complete_rejected(tmp_path):
    _, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    status = seam.start_upload("pic.jpg", "image/jpeg", 100)
    seam.append_upload_range(status.upload_id, 0, 100, sha(b"x" * 100), b"x" * 100)
    seam.complete_upload(status.upload_id)
    with pytest.raises(UploadNotReceiving):
        seam.append_upload_range(status.upload_id, 0, 1, sha(b"x"), b"x")


def test_complete_upload_requires_full_coverage(tmp_path):
    _, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    status = seam.start_upload("pic.jpg", "image/jpeg", 100)
    seam.append_upload_range(status.upload_id, 0, 50, sha(b"x" * 50), b"x" * 50)
    with pytest.raises(UploadIncomplete):
        seam.complete_upload(status.upload_id)


def test_complete_upload_creates_job_and_audits(tmp_path):
    store, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    status = seam.start_upload("pic.jpg", "image/jpeg", 100)
    seam.append_upload_range(status.upload_id, 0, 100, sha(b"x" * 100), b"x" * 100)
    result = seam.complete_upload(status.upload_id)
    assert result.status == "queued"
    job = store.get_by_upload(store.get(status.upload_id).id)
    assert job is not None
    assert job.kind == "media.process"
    assert job.status == "queued"
    actions = [e.action for e in seam.list_audit()]
    assert actions[0] == "upload.completed"


def test_complete_upload_exactly_once(tmp_path):
    _, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    status = seam.start_upload("pic.jpg", "image/jpeg", 100)
    seam.append_upload_range(status.upload_id, 0, 100, sha(b"x" * 100), b"x" * 100)
    seam.complete_upload(status.upload_id)
    with pytest.raises(UploadConflict):
        seam.complete_upload(status.upload_id)


def test_get_upload_status(tmp_path):
    _, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    status = seam.start_upload("pic.jpg", "image/jpeg", 100)
    fetched = seam.get_upload_status(status.upload_id)
    assert fetched.upload_id == status.upload_id
    with pytest.raises(UploadNotFound):
        seam.get_upload_status("missing")


def test_abort_upload_cleans_staging(tmp_path):
    _, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    status = seam.start_upload("pic.jpg", "image/jpeg", 100)
    staging = tmp_path / "tmp" / status.upload_id
    assert staging.is_dir()
    seam.abort_upload(status.upload_id, requester="7")
    assert not staging.exists()
    assert seam.get_upload_status(status.upload_id).status == "aborted"
    actions = [e.action for e in seam.list_audit()]
    assert actions[0] == "upload.aborted"
    assert seam.list_audit()[0].actor == "7"


def test_get_upload_limits_defaults_and_settings(tmp_path):
    store, seam = make_seam(tmp_path)
    limits = seam.get_upload_limits()
    assert limits.max_file_bytes == 2 * 1024**3
    assert limits.max_package_bytes == 20 * 1024**3
    store.set("upload.max_file_bytes", 42, updated_at=FIXED_AT)
    assert seam.get_upload_limits().max_file_bytes == 42
