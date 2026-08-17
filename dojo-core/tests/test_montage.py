from __future__ import annotations

import hashlib
import json

import pytest
from dojo import (
    DojoPublishing,
    InMemoryStore,
    MediaNotFound,
    MontageDurationExceeded,
    MontageOrderInvalid,
    MontageTrimInvalid,
    NoActivePackage,
    PackageCompleted,
)
from dojo.adapters.stubs import (
    StubMediaProcessor,
    StubMetaPublisher,
    StubNotifier,
    StubSignedUrlStore,
)
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


def load_manifest(tmp_path, seam):
    package = seam.get_active_package()
    return json.loads(
        (tmp_path / package.folder_name / "manifest.json").read_text(encoding="utf-8")
    )


def test_set_order_persists_permutation(tmp_path):
    store, seam = make_seam(tmp_path)
    first = finalize_media(tmp_path, seam, store, filename="a.jpg")
    second = finalize_media(tmp_path, seam, store, filename="b.jpg")
    third = finalize_media(tmp_path, seam, store, filename="c.jpg")

    seam.set_order([third, first, second], requester="7")

    assert load_manifest(tmp_path, seam)["order"] == [third, first, second]
    actions = [e.action for e in seam.list_audit()]
    assert actions[0] == "montage.order_changed"
    assert seam.list_audit()[0].actor == "7"


def test_set_order_requires_exact_finalized_set(tmp_path):
    store, seam = make_seam(tmp_path)
    first = finalize_media(tmp_path, seam, store, filename="a.jpg")
    second = finalize_media(tmp_path, seam, store, filename="b.jpg")

    with pytest.raises(MontageOrderInvalid):
        seam.set_order([first])  # missing second
    with pytest.raises(MontageOrderInvalid):
        seam.set_order([first, second, second])  # duplicate
    with pytest.raises(MontageOrderInvalid):
        seam.set_order([first, second, "unknown"])  # unknown id


def test_set_order_rejects_removed_ids(tmp_path):
    store, seam = make_seam(tmp_path)
    first = finalize_media(tmp_path, seam, store, filename="a.jpg")
    second = finalize_media(tmp_path, seam, store, filename="b.jpg")
    seam.remove_media(second)

    with pytest.raises(MontageOrderInvalid):
        seam.set_order([first, second])


def test_set_trims_persists_and_requires_video(tmp_path):
    store, seam = make_seam(tmp_path)
    video = finalize_media(
        tmp_path, seam, store, filename="clip.mp4",
        content_type="video/mp4", duration=10.0,
    )
    photo = finalize_media(tmp_path, seam, store, filename="pic.jpg")

    seam.set_trims({video: {"start": 1.0, "end": 6.0}}, requester="8")

    manifest = load_manifest(tmp_path, seam)
    assert manifest["trims"] == {video: {"start": 1.0, "end": 6.0}}
    actions = [e.action for e in seam.list_audit()]
    assert actions[0] == "montage.trim_changed"
    assert seam.list_audit()[0].actor == "8"

    with pytest.raises(MontageTrimInvalid):
        seam.set_trims({photo: {"start": 0.0, "end": 1.0}})


def test_set_trims_requires_video_duration_known(tmp_path):
    store, seam = make_seam(tmp_path)
    video = finalize_media(
        tmp_path, seam, store, filename="clip.mp4",
        content_type="video/mp4", duration=10.0,
    )

    with pytest.raises(MontageTrimInvalid):
        seam.set_trims({video: {"start": 9.0, "end": 11.0}})  # beyond duration
    with pytest.raises(MontageTrimInvalid):
        seam.set_trims({video: {"start": 5.0, "end": 5.0}})  # start == end
    with pytest.raises(MontageTrimInvalid):
        seam.set_trims({video: {"start": -1.0, "end": 2.0}})  # negative start


def test_set_trims_unknown_media_raises(tmp_path):
    store, seam = make_seam(tmp_path)
    finalize_media(tmp_path, seam, store, filename="a.jpg")
    with pytest.raises(MediaNotFound):
        seam.set_trims({"nope": {"start": 0.0, "end": 1.0}})


def test_combined_duration_math(tmp_path):
    store, seam = make_seam(tmp_path)
    video = finalize_media(
        tmp_path, seam, store, filename="clip.mp4",
        content_type="video/mp4", duration=10.0,
    )
    _photo = finalize_media(tmp_path, seam, store, filename="pic.jpg")

    seam.set_trims({video: {"start": 1.0, "end": 6.0}})
    status = seam.get_montage_status()
    # photo default 3.0 + video (10 - (6-1)) = 5.0
    assert abs(status.combined_duration - 8.0) < 1e-6


def test_over_limit_order_rejected_with_action(tmp_path):
    store, seam = make_seam(tmp_path)
    store.set("montage.max_duration_seconds", 5.0, updated_at=FIXED_AT)
    a = finalize_media(tmp_path, seam, store, filename="a.jpg")
    b = finalize_media(tmp_path, seam, store, filename="b.jpg")
    # photo default 3.0 each -> 6.0 > 5.0

    with pytest.raises(MontageDurationExceeded) as exc_info:
        seam.set_order([a, b])
    assert "trim or remove" in str(exc_info.value)
    assert "1.0" in str(exc_info.value)
    assert load_manifest(tmp_path, seam)["order"] == [a, b]  # unchanged (append order)


def test_over_limit_trims_rejected_and_unchanged(tmp_path):
    store, seam = make_seam(tmp_path)
    store.set("montage.max_duration_seconds", 6.0, updated_at=FIXED_AT)
    video = finalize_media(
        tmp_path, seam, store, filename="clip.mp4",
        content_type="video/mp4", duration=10.0,
    )
    seam.set_trims({video: {"start": 0.0, "end": 9.0}})  # effective 1.0s, valid
    # Shrinking the trim window lengthens the clip; pushing effective past 6s.
    with pytest.raises(MontageDurationExceeded):
        seam.set_trims({video: {"start": 0.0, "end": 1.0}})  # effective 9.0s > 6s
    manifest = load_manifest(tmp_path, seam)
    assert manifest["trims"] == {video: {"start": 0.0, "end": 9.0}}  # unchanged


def test_order_and_trim_edits_clear_render_revision(tmp_path):
    store, seam = make_seam(tmp_path)
    a = finalize_media(tmp_path, seam, store, filename="a.jpg")
    video = finalize_media(
        tmp_path, seam, store, filename="clip.mp4",
        content_type="video/mp4", duration=10.0,
    )
    manifest_path = tmp_path / seam.get_active_package().folder_name / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["render_revision"] = "rev-1"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    seam.set_order([video, a])
    assert load_manifest(tmp_path, seam)["render_revision"] is None

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["render_revision"] = "rev-2"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    seam.set_trims({video: {"start": 0.0, "end": 5.0}})
    assert load_manifest(tmp_path, seam)["render_revision"] is None


def test_get_montage_status_reports_over_limit_and_action(tmp_path):
    store, seam = make_seam(tmp_path)
    store.set("montage.max_duration_seconds", 2.0, updated_at=FIXED_AT)
    finalize_media(tmp_path, seam, store, filename="a.jpg")
    status = seam.get_montage_status()
    assert status.over_limit is True
    assert status.required_action is not None
    assert "trim or remove" in status.required_action


def test_montage_mutation_on_completed_package_raises(tmp_path):
    store, seam = make_seam(tmp_path)
    media_id = finalize_media(tmp_path, seam, store, filename="a.jpg")
    seam.complete_active_package(requester="9")
    with pytest.raises(PackageCompleted):
        seam.set_order([media_id])
    with pytest.raises(PackageCompleted):
        seam.set_trims({media_id: {"start": 0.0, "end": 1.0}})


def test_montage_without_active_package_raises(tmp_path):
    _, seam = make_seam(tmp_path)
    with pytest.raises(NoActivePackage):
        seam.set_order([])
    with pytest.raises(NoActivePackage):
        seam.set_trims({})
    with pytest.raises(NoActivePackage):
        seam.get_montage_status()