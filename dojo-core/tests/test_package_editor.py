from __future__ import annotations

import hashlib
import json

import pytest
from dojo import DojoPublishing, InMemoryStore, MediaNotFound, NoActivePackage, PackageChanged
from dojo.adapters.stubs import StubMediaProcessor
from dojo.testing import FakeClock, complete_confirmed_package


def make_package(tmp_path, filename="Çalışma.MP4"):
    store = InMemoryStore()
    seam = DojoPublishing(packages=store, audit=store, settings=store, media_root=tmp_path,
                          clock=FakeClock(),
                          media=StubMediaProcessor(content_type="video/mp4", duration=30.0))
    upload = seam.start_upload(filename, "video/mp4", 100)
    data = b"x" * 100
    seam.append_upload_range(upload.upload_id, 0, 100, hashlib.sha256(data).hexdigest(), data)
    seam.complete_upload(upload.upload_id)
    seam.process_job(seam.claim_next_job().job_id)
    package = seam.get_active_package()
    path = tmp_path / package.folder_name / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    return seam, path, manifest["order"][0]


def archive(seam):
    complete_confirmed_package(seam)
    return seam.list_completed_packages()[0]


def test_editor_snapshot_reads_finalized_and_removed_without_mutation(tmp_path):
    seam, path, mid = make_package(tmp_path)
    folder = seam.get_active_package().folder_name
    seam.set_selections({mid: [{"start": 0.0, "end": 5.0}, {"start": 10.0, "end": 15.0}]},
                        expected_folder_name=folder)
    before = path.read_bytes()
    snapshot = seam.get_active_editor()
    assert snapshot["package"]["folder_name"] == folder
    assert snapshot["render_stale"] is True
    assert snapshot["montage"]["combined_duration"] == 10.0
    media = snapshot["media"][0]
    assert (media["source_duration"], media["effective_duration"], media["is_video"]) == (
        30, 10, True,
    )
    assert media["preview_ref"] == f"media/{mid}/processed.mp4"
    assert path.read_bytes() == before
    seam.remove_media(mid)
    removed_manifest = path.read_bytes()
    media = seam.get_active_editor()["media"][0]
    assert media["status"] == "removed"
    assert media["processed"]["path"] == f"media/{mid}/processed.mp4"
    assert media["preview_ref"] == f"removed/{mid}/processed.mp4"
    assert seam.get_media_preview(mid, expected_folder_name=folder).path == (
        path.parent / "removed" / mid / "processed.mp4"
    )
    assert path.read_bytes() == removed_manifest


def test_empty_editor_read_never_creates_package(tmp_path):
    store = InMemoryStore()
    seam = DojoPublishing(packages=store, audit=store, media_root=tmp_path, clock=FakeClock())
    with pytest.raises(NoActivePackage):
        seam.get_active_editor()
    assert seam.get_active_package() is None
    assert list(tmp_path.iterdir()) == []


def test_preview_checks_identity_missing_artifact_and_media(tmp_path):
    seam, path, mid = make_package(tmp_path)
    folder = seam.get_active_package().folder_name
    with pytest.raises(PackageChanged):
        seam.get_media_preview(mid, expected_folder_name="old")
    with pytest.raises(MediaNotFound):
        seam.get_media_preview("unknown", expected_folder_name=folder)
    (path.parent / "media" / mid / "processed.mp4").unlink()
    assert seam.get_active_editor()["media"][0]["preview_ref"] is None
    with pytest.raises(MediaNotFound):
        seam.get_media_preview(mid, expected_folder_name=folder)


def test_missing_processed_metadata_is_unavailable_not_server_error(tmp_path):
    seam, path, mid = make_package(tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["media"][0]["processed"] = {}
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(MediaNotFound):
        seam.get_media_preview(mid, expected_folder_name=seam.get_active_package().folder_name)


@pytest.mark.parametrize("filename, suffix", [("Çalışma.MP4", ".MP4"), ("Çalışma", ".mp4")])
def test_completed_original_and_removed_download_preserve_filename_bytes(
    tmp_path, filename, suffix,
):
    seam, path, mid = make_package(tmp_path, filename)
    seam.remove_media(mid)
    completed = archive(seam)
    root = tmp_path / completed.folder_name
    before = (root / "manifest.json").read_bytes()
    artifact = seam.resolve_completed_artifact(
        completed.folder_name, f"removed/{mid}/original{suffix}",
    )
    assert artifact.path.read_bytes() == b"x" * 100
    assert artifact.filename == filename
    assert artifact.content_type == "video/mp4"
    view = seam.browse_completed_package(completed.folder_name)
    originals = [a for a in view["artifacts"] if a["kind"] == "original"]
    assert originals[0]["available"] is True
    assert originals[0]["filename"] == filename
    assert originals[0]["artifact_ref"] == f"removed/{mid}/original{suffix}"
    render = next(a for a in view["artifacts"] if a["kind"] == "render")
    assert render["available"] is False
    assert (root / "manifest.json").read_bytes() == before


def test_completed_render_resolves_only_known_files(tmp_path):
    seam, path, mid = make_package(tmp_path)
    (path.parent / "render").mkdir()
    (path.parent / "render" / "reel.mp4").write_bytes(b"approved-reel")
    completed = archive(seam)
    artifact = seam.resolve_completed_artifact(completed.folder_name, "render/reel.mp4")
    assert artifact.path.read_bytes() == b"approved-reel"
    assert artifact.filename == "reel.mp4"
    with pytest.raises(MediaNotFound):
        seam.resolve_completed_artifact(completed.folder_name, "manifest.json")
    with pytest.raises(MediaNotFound):
        seam.resolve_completed_artifact(seam.get_active_package().folder_name, "render/reel.mp4")


@pytest.mark.parametrize("reference", ["../secret", "/absolute", "C:/secret", "media/../../secret",
                                       "media\\..\\secret", "render/../manifest.json"])
def test_completed_artifact_rejects_traversal_and_absolute_refs(tmp_path, reference):
    seam, _, _ = make_package(tmp_path)
    completed = archive(seam)
    with pytest.raises(ValueError):
        seam.resolve_completed_artifact(completed.folder_name, reference)


def test_artifact_symlink_escape_is_unavailable_and_rejected(tmp_path):
    seam, path, mid = make_package(tmp_path)
    completed = archive(seam)
    processed = tmp_path / completed.folder_name / "media" / mid / "processed.mp4"
    external = tmp_path / "private.dat"
    external.write_bytes(b"private")
    processed.unlink()
    try:
        processed.symlink_to(external)
    except OSError as exc:
        pytest.skip(f"platform symlink privileges unavailable: {exc}")
    view = seam.browse_completed_package(completed.folder_name)
    descriptor = next(a for a in view["artifacts"] if a["artifact_ref"].endswith("processed.mp4"))
    assert descriptor["available"] is False
    with pytest.raises(ValueError):
        seam.resolve_completed_artifact(completed.folder_name, f"media/{mid}/processed.mp4")


def test_snapshot_never_exposes_absolute_processed_paths(tmp_path):
    seam, path, _ = make_package(tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["media"][0]["processed"]["path"] = str(tmp_path / "private.dat")
    path.write_text(json.dumps(manifest), encoding="utf-8")
    snapshot = seam.get_active_editor()
    assert str(tmp_path) not in json.dumps(snapshot, default=str)
    assert snapshot["media"][0]["preview_ref"] is None


def test_toggles_invalidate_render_and_keep_sections(tmp_path):
    seam, path, mid = make_package(tmp_path)
    folder = seam.get_active_package().folder_name
    ranges = [{"start": 0.0, "end": 5.0}, {"start": 10.0, "end": 15.0}]
    seam.set_selections({mid: ranges}, expected_folder_name=folder)
    for toggle in (seam.remove_media, seam.restore_media):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["render_revision"] = "old-render"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        toggle(mid, expected_folder_name=folder)
        snapshot = seam.get_active_editor()
        assert snapshot["render_stale"] is True
        assert snapshot["montage"]["selections"][mid] == ranges
        assert json.loads(path.read_text())["render_revision"] is None


def test_same_minute_rollover_has_distinct_editor_identity(tmp_path):
    seam, _, _ = make_package(tmp_path)
    old = seam.get_active_package().folder_name
    archive(seam)
    assert seam.get_active_package().folder_name != old
    with pytest.raises(PackageChanged):
        seam.set_selections({}, expected_folder_name=old)
