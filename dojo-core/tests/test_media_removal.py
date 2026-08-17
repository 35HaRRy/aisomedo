from __future__ import annotations

import hashlib
import json

import pytest
from dojo import (
    DojoPublishing,
    InMemoryStore,
    MediaNotFound,
    MediaNotRemovable,
    MediaNotRestorable,
    NoActivePackage,
    PackageCompleted,
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


def finalize_one(tmp_path, seam, store, *, filename="pic.jpg") -> str:
    """Upload + process one image and return its media_id."""
    seam._media = StubMediaProcessor()
    seam.get_or_create_active_package()
    status = seam.start_upload(filename, "image/jpeg", 100)
    seam.append_upload_range(status.upload_id, 0, 100, sha(b"x" * 100), b"x" * 100)
    seam.complete_upload(status.upload_id)
    job = seam.claim_next_job()
    assert job is not None
    seam.process_job(job.job_id)
    package = seam.get_active_package()
    manifest = json.loads(
        (tmp_path / package.folder_name / "manifest.json").read_text(encoding="utf-8")
    )
    return next(
        e["media_id"] for e in manifest["media"] if e["filename"] == filename
    )


def test_remove_media_excludes_from_order_but_keeps_entry(tmp_path):
    store, seam = make_seam(tmp_path)
    media_id = finalize_one(tmp_path, seam, store)
    package = seam.get_active_package()

    seam.remove_media(media_id, requester="7")

    manifest = json.loads(
        (tmp_path / package.folder_name / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["order"] == []
    entry = manifest["media"][0]
    assert entry["media_id"] == media_id
    assert entry["status"] == "removed"
    assert (tmp_path / package.folder_name / "media" / media_id).exists() is False
    assert (tmp_path / package.folder_name / "removed" / media_id).is_dir()
    actions = [e.action for e in seam.list_audit()]
    assert actions[0] == "media.removed"
    assert seam.list_audit()[0].actor == "7"


def test_remove_media_preserves_other_media_and_order(tmp_path):
    store, seam = make_seam(tmp_path)
    first = finalize_one(tmp_path, seam, store, filename="a.jpg")
    second = finalize_one(tmp_path, seam, store, filename="b.jpg")
    package = seam.get_active_package()

    seam.remove_media(first)

    manifest = json.loads(
        (tmp_path / package.folder_name / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["order"] == [second]
    statuses = {e["media_id"]: e["status"] for e in manifest["media"]}
    assert statuses[first] == "removed"
    assert statuses[second] == "finalized"


def test_remove_media_restores_moves_back_and_reappends_to_order(tmp_path):
    store, seam = make_seam(tmp_path)
    media_id = finalize_one(tmp_path, seam, store)
    package = seam.get_active_package()
    seam.remove_media(media_id)

    seam.restore_media(media_id, requester="8")

    manifest = json.loads(
        (tmp_path / package.folder_name / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["order"] == [media_id]
    entry = manifest["media"][0]
    assert entry["status"] == "finalized"
    assert (tmp_path / package.folder_name / "media" / media_id).is_dir()
    assert (tmp_path / package.folder_name / "removed" / media_id).exists() is False
    actions = [e.action for e in seam.list_audit()]
    assert actions[0] == "media.restored"
    assert seam.list_audit()[0].actor == "8"


def test_remove_media_unknown_raises(tmp_path):
    store, seam = make_seam(tmp_path)
    finalize_one(tmp_path, seam, store)
    with pytest.raises(MediaNotFound):
        seam.remove_media("does-not-exist")


def test_remove_media_without_active_package_raises(tmp_path):
    store, seam = make_seam(tmp_path)
    with pytest.raises(NoActivePackage):
        seam.remove_media("any")


def test_remove_media_already_removed_raises(tmp_path):
    store, seam = make_seam(tmp_path)
    media_id = finalize_one(tmp_path, seam, store)
    seam.remove_media(media_id)
    with pytest.raises(MediaNotRemovable):
        seam.remove_media(media_id)


def test_restore_media_non_removed_raises(tmp_path):
    store, seam = make_seam(tmp_path)
    media_id = finalize_one(tmp_path, seam, store)
    with pytest.raises(MediaNotRestorable):
        seam.restore_media(media_id)


def test_restore_media_unknown_raises(tmp_path):
    store, seam = make_seam(tmp_path)
    finalize_one(tmp_path, seam, store)
    with pytest.raises(MediaNotFound):
        seam.restore_media("does-not-exist")


def test_restore_media_returns_to_original_position(tmp_path):
    store, seam = make_seam(tmp_path)
    first = finalize_one(tmp_path, seam, store, filename="a.jpg")
    second = finalize_one(tmp_path, seam, store, filename="b.jpg")
    third = finalize_one(tmp_path, seam, store, filename="c.jpg")
    package = seam.get_active_package()

    seam.remove_media(second)
    seam.restore_media(second)

    manifest = json.loads(
        (tmp_path / package.folder_name / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["order"] == [first, second, third]


def test_remove_and_restore_on_completed_package_raises(tmp_path):
    store, seam = make_seam(tmp_path)
    media_id = finalize_one(tmp_path, seam, store)
    seam.complete_active_package(requester="9")

    with pytest.raises(PackageCompleted):
        seam.remove_media(media_id)
    with pytest.raises(PackageCompleted):
        seam.restore_media(media_id)


def test_list_completed_packages_returns_completed_only(tmp_path):
    store, seam = make_seam(tmp_path)
    finalize_one(tmp_path, seam, store)
    seam.complete_active_package(requester="9")

    completed = seam.list_completed_packages()

    assert len(completed) == 1
    assert completed[0].status == "completed"
    assert completed[0].folder_name.endswith("-completed")


def test_browse_completed_package_returns_manifest_view(tmp_path):
    store, seam = make_seam(tmp_path)
    media_id = finalize_one(tmp_path, seam, store)
    seam.complete_active_package(requester="9")
    completed = seam.list_completed_packages()[0]

    view = seam.browse_completed_package(completed.folder_name)

    assert view["folder_name"] == completed.folder_name
    assert view["order"] == [media_id]
    assert len(view["media"]) == 1
    assert view["media"][0]["media_id"] == media_id


def test_browse_non_completed_or_missing_package_raises(tmp_path):
    store, seam = make_seam(tmp_path)
    finalize_one(tmp_path, seam, store)
    with pytest.raises(MediaNotFound):
        seam.browse_completed_package("06-08-2026 14-30")
    with pytest.raises(MediaNotFound):
        seam.browse_completed_package("nope")


def test_create_download_url_resolves_processed_and_removed(tmp_path):
    store, seam = make_seam(tmp_path)
    media_id = finalize_one(tmp_path, seam, store)
    seam.complete_active_package(requester="9")
    completed = seam.list_completed_packages()[0]

    url = seam.create_download_url(completed.folder_name, f"media/{media_id}/processed.jpg")
    assert url.startswith("https://signed.local/")


def test_create_download_url_rejects_traversal(tmp_path):
    store, seam = make_seam(tmp_path)
    finalize_one(tmp_path, seam, store)
    seam.complete_active_package(requester="9")
    completed = seam.list_completed_packages()[0]

    for ref in ("../secret", "media/../../outside", "/abs/path"):
        with pytest.raises(ValueError):
            seam.create_download_url(completed.folder_name, ref)


def test_create_download_url_rejects_non_file_in_package(tmp_path):
    store, seam = make_seam(tmp_path)
    finalize_one(tmp_path, seam, store)
    seam.complete_active_package(requester="9")
    completed = seam.list_completed_packages()[0]

    with pytest.raises(MediaNotFound):
        seam.create_download_url(completed.folder_name, "media")


def test_create_download_url_rejects_unknown_file(tmp_path):
    store, seam = make_seam(tmp_path)
    media_id = finalize_one(tmp_path, seam, store)
    seam.complete_active_package(requester="9")
    completed = seam.list_completed_packages()[0]

    with pytest.raises(MediaNotFound):
        seam.create_download_url(completed.folder_name, f"media/{media_id}/missing.jpg")