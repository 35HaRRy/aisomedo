from __future__ import annotations

import hashlib
import json

import pytest
from dojo import (
    DojoPublishing,
    InMemoryStore,
    LegacyTrimConflict,
    MontageDurationExceeded,
    MontageTrimInvalid,
    NoActivePackage,
    PackageChanged,
    PackageCompleted,
)
from dojo.adapters.stubs import (
    StubMediaProcessor,
    StubMetaPublisher,
    StubNotifier,
    StubSignedUrlStore,
)
from dojo.testing import FIXED_AT, FakeClock, complete_confirmed_package


def make_seam(tmp_path):
    store = InMemoryStore()
    return store, DojoPublishing(
        packages=store, audit=store, uploads=store, jobs=store, settings=store,
        media_root=tmp_path, clock=FakeClock(), meta=StubMetaPublisher(),
        notifier=StubNotifier(), signed_urls=StubSignedUrlStore(),
    )


def finalize_media(tmp_path, seam, store, *, filename="pic.jpg",
                   content_type="image/jpeg", duration=None):
    seam._media = StubMediaProcessor(content_type=content_type, duration=duration)
    seam.get_or_create_active_package()
    status = seam.start_upload(filename, content_type, 100)
    data = b"x" * 100
    seam.append_upload_range(status.upload_id, 0, 100, hashlib.sha256(data).hexdigest(), data)
    seam.complete_upload(status.upload_id)
    seam.process_job(seam.claim_next_job().job_id)
    manifest = json.loads(manifest_path(tmp_path, seam).read_text(encoding="utf-8"))
    return next(entry["media_id"] for entry in manifest["media"] if entry["filename"] == filename)


def video(tmp_path, seam, store, name="clip.mp4", duration=30.0):
    return finalize_media(tmp_path, seam, store, filename=name,
                          content_type="video/mp4", duration=duration)


def manifest_path(tmp_path, seam):
    return tmp_path / seam.get_active_package().folder_name / "manifest.json"


def select(seam, selections):
    return seam.set_selections(selections, requester="7",
                               expected_folder_name=seam.get_active_package().folder_name)


def test_selected_sections_are_retained(tmp_path):
    store, seam = make_seam(tmp_path)
    mid = video(tmp_path, seam, store)
    ranges = [{"start": 24.0, "end": 30.0}, {"start": 0.0, "end": 5.0},
              {"start": 10.0, "end": 15.0}]
    status = select(seam, {mid: ranges})
    assert status.combined_duration == 16.0
    assert status.selections[mid] == [ranges[1], ranges[2], ranges[0]]
    assert seam.get_montage_status().selections == status.selections
    assert seam.list_audit()[0].actor == "7"
    assert json.loads(manifest_path(tmp_path, seam).read_text())["render_revision"] is None


@pytest.mark.parametrize("ranges", [
    [], [{"start": -1.0, "end": 2.0}], [{"start": 1.0, "end": 1.0}],
    [{"start": 0.0, "end": 31.0}], [{"start": 0.0, "end": 0.01}],
    [{"start": True, "end": 2.0}], [{"start": 0.0, "end": float("inf")}],
    [{"start": float("nan"), "end": 2.0}], [{"start": "1", "end": 2}],
    [{"start": 0.0, "end": 5.0}, {"start": 4.0, "end": 6.0}],
    [{"start": 0.0, "end": 5.0}, {"start": 0.0, "end": 5.0}],
    [{"start": 0.0}],
])
def test_invalid_ranges_do_not_write(tmp_path, ranges):
    store, seam = make_seam(tmp_path)
    mid = video(tmp_path, seam, store)
    before = manifest_path(tmp_path, seam).read_bytes()
    with pytest.raises(MontageTrimInvalid):
        select(seam, {mid: ranges})
    assert manifest_path(tmp_path, seam).read_bytes() == before


def test_adjacent_ranges_and_one_frame_roundoff_are_valid(tmp_path):
    store, seam = make_seam(tmp_path)
    mid = video(tmp_path, seam, store)
    status = select(seam, {mid: [{"start": 10.0, "end": 10.04},
                                {"start": 10.04, "end": 11.0}]})
    assert status.combined_duration == pytest.approx(1.0)


def test_batch_selection_corrects_limit_and_rejection_is_atomic(tmp_path):
    store, seam = make_seam(tmp_path)
    a = video(tmp_path, seam, store, "a.mp4")
    b = video(tmp_path, seam, store, "b.mp4")
    store.set("montage.max_duration_seconds", 10.0, updated_at=FIXED_AT)
    before = manifest_path(tmp_path, seam).read_bytes()
    with pytest.raises(MontageDurationExceeded):
        select(seam, {a: [{"start": 0.0, "end": 5.0}]})
    assert manifest_path(tmp_path, seam).read_bytes() == before
    assert select(seam, {a: [{"start": 0.0, "end": 5.0}],
                         b: [{"start": 0.0, "end": 5.0}]}).combined_duration == 10.0


def test_removed_sections_survive_other_video_save(tmp_path):
    store, seam = make_seam(tmp_path)
    a = video(tmp_path, seam, store, "a.mp4")
    b = video(tmp_path, seam, store, "b.mp4")
    ranges = [{"start": 0.0, "end": 5.0}, {"start": 10.0, "end": 15.0}]
    select(seam, {a: ranges})
    seam.remove_media(a)
    select(seam, {b: [{"start": 0.0, "end": 2.0}]})
    seam.restore_media(a)
    status = seam.get_montage_status()
    assert status.order == [a, b]
    assert status.selections[a] == ranges
    assert status.combined_duration == 12.0


def test_legacy_interval_duration_matches_rendered_window(tmp_path):
    store, seam = make_seam(tmp_path)
    mid = video(tmp_path, seam, store)
    status = seam.set_trims({mid: {"start": 10.0, "end": 20.0}})
    assert status.combined_duration == 10.0
    assert status.selections[mid] == [{"start": 10.0, "end": 20.0}]


def test_legacy_write_cannot_erase_multiple_sections(tmp_path):
    store, seam = make_seam(tmp_path)
    mid = video(tmp_path, seam, store)
    select(seam, {mid: [{"start": 0.0, "end": 5.0}, {"start": 10.0, "end": 15.0}]})
    before = manifest_path(tmp_path, seam).read_bytes()
    with pytest.raises(LegacyTrimConflict, match="updated editor"):
        seam.set_trims({})
    assert manifest_path(tmp_path, seam).read_bytes() == before


def test_cards_count_once_and_photos_use_configured_duration(tmp_path):
    store, seam = make_seam(tmp_path)
    (tmp_path / "intro.png").touch()
    store.set("branding.intro_asset", "intro.png", updated_at=FIXED_AT)
    store.set("branding.intro_duration", 2.0, updated_at=FIXED_AT)
    mid = video(tmp_path, seam, store)
    finalize_media(tmp_path, seam, store)
    status = select(seam, {mid: [{"start": 0.0, "end": 5.0},
                                {"start": 10.0, "end": 15.0}]})
    assert status.card_duration == 2.0
    assert status.combined_duration == 15.0


@pytest.mark.parametrize("duration", [None, 0.0, float("nan")])
def test_unknown_source_duration_is_visible_and_cannot_be_saved(tmp_path, duration):
    store, seam = make_seam(tmp_path)
    mid = video(tmp_path, seam, store, duration=duration)
    assert seam.get_montage_status().duration_complete is False
    with pytest.raises(MontageTrimInvalid):
        select(seam, {mid: [{"start": 0.0, "end": 1.0}]})


def test_photo_unknown_removed_and_completed_targets_are_rejected(tmp_path):
    from dojo import MediaNotFound

    store, seam = make_seam(tmp_path)
    photo = finalize_media(tmp_path, seam, store)
    mid = video(tmp_path, seam, store)
    with pytest.raises(MontageTrimInvalid):
        select(seam, {photo: [{"start": 0.0, "end": 1.0}]})
    with pytest.raises(MediaNotFound):
        select(seam, {"missing": [{"start": 0.0, "end": 1.0}]})
    seam.remove_media(mid)
    with pytest.raises(MediaNotFound):
        select(seam, {mid: [{"start": 0.0, "end": 1.0}]})
    complete_confirmed_package(seam)
    with pytest.raises(PackageCompleted):
        select(seam, {photo: [{"start": 0.0, "end": 1.0}]})


def test_missing_package_and_rollover_guards(tmp_path):
    store, seam = make_seam(tmp_path)
    with pytest.raises(NoActivePackage):
        seam.set_selections({}, expected_folder_name="old")
    mid = video(tmp_path, seam, store)
    before = manifest_path(tmp_path, seam).read_bytes()
    for operation in [lambda: seam.set_selections({}, expected_folder_name="old"),
                      lambda: seam.set_order([mid], expected_folder_name="old"),
                      lambda: seam.remove_media(mid, expected_folder_name="old"),
                      lambda: seam.restore_media(mid, expected_folder_name="old")]:
        with pytest.raises(PackageChanged, match="package changed"):
            operation()
    assert manifest_path(tmp_path, seam).read_bytes() == before
