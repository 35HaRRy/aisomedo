from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from threading import Event, Thread

import pytest
from dojo import DojoPublishing, InMemoryStore, MontageTrimInvalid, Package, PackageChanged
from dojo.adapters.stubs import StubMediaProcessor, StubNotifier, StubReelRenderer
from dojo.exceptions import JobNotFound, MediaNotFound, RenderFailed, UploadNotFound
from dojo.model import AuditEvent, BrandingConfig, Client, YayinIncelemesi, YayinZamani
from dojo.testing import FIXED_AT, FakeClock


def make_editor(tmp_path, store=None, renderer=None):
    store = store or InMemoryStore()
    seam = DojoPublishing(packages=store, audit=store, settings=store,
                          media_root=tmp_path, clock=FakeClock(),
                          media=StubMediaProcessor(), renderer=renderer or StubReelRenderer())
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"logo")
    seam.set_branding_defaults(BrandingConfig(logo_asset=str(logo)))
    upload = seam.start_upload("photo.jpg", "image/jpeg", 4)
    seam.append_upload_range(upload.upload_id, 0, 4, hashlib.sha256(b"1234").hexdigest(), b"1234")
    seam.complete_upload(upload.upload_id)
    job = seam.claim_next_job()
    seam.process_job(job.job_id)
    return seam, store, upload.upload_id, job.job_id, seam.get_montage_status().order[0]


def test_photo_duration_saved_removed_restored_and_rendered(tmp_path):
    renderer = StubReelRenderer()
    seam, _, _, _, mid = make_editor(tmp_path, renderer=renderer)
    folder = seam.get_active_package().folder_name
    assert seam.get_active_editor()["media"][0]["effective_duration"] == 3
    seam.set_selections({}, expected_folder_name=folder, photo_durations={mid: 4.5})
    assert seam.get_montage_status().combined_duration == 4.5
    seam.remove_media(mid)
    seam.restore_media(mid)
    seam.render_preview(expected_folder_name=folder)
    seam.process_job(seam.claim_next_job().job_id)
    assert renderer.calls[0][0].clips[0].duration == 4.5
    assert seam.get_active_editor()["render_status"] == "ready"
    assert seam.get_render_preview(expected_folder_name=folder).path.read_bytes() == b"fake-reel"
    seam.set_selections({}, expected_folder_name=folder, photo_durations={mid: 6})
    assert seam.get_active_editor()["render_status"] == "stale"
    with pytest.raises(MediaNotFound):
        seam.get_render_preview(expected_folder_name=folder)


@pytest.mark.parametrize("value", [0, -1, True, "3", float("nan"), float("inf")])
def test_photo_duration_invalid_writes_nothing(tmp_path, value):
    seam, _, _, _, mid = make_editor(tmp_path)
    folder = seam.get_active_package().folder_name
    path = tmp_path / folder / "manifest.json"
    before = path.read_bytes()
    with pytest.raises(MontageTrimInvalid):
        seam.set_selections({}, expected_folder_name=folder, photo_durations={mid: value})
    assert path.read_bytes() == before


@pytest.mark.parametrize("adapter", ["memory", "postgres"])
def test_clear_removes_only_package_files_records_and_pending_work(tmp_path, request, adapter):
    store = request.getfixturevalue("pg_store") if adapter == "postgres" else InMemoryStore()
    seam, store, upload_id, media_job_id, mid = make_editor(tmp_path, store)
    package = seam.get_active_package()
    receiving = seam.start_upload("pending.jpg", "image/jpeg", 4)
    seam.render_preview(expected_folder_name=package.folder_name)
    render = seam.claim_next_job()
    # A claimed job not yet running is also removed; delayed worker cannot recreate files.
    temp = tmp_path / "tmp" / f"render-{render.job_id}"
    temp.mkdir(parents=True)
    (temp / "segment.mp4").write_bytes(b"tmp")
    occurrence = store.create(YayinZamani(id=0, kind="manual", due_at=FIXED_AT,
                                        status="pending", created_at=FIXED_AT))
    review = store.create(YayinIncelemesi(id=0, occurrence_id=occurrence.id,
                         package_folder=package.folder_name, revision_digest="old", caption=None,
                         status="pending", created_at=FIXED_AT))
    store.append(AuditEvent(action="review.created", actor="system", occurred_at=FIXED_AT,
                            details={"review_id": review.id}))
    store.append(AuditEvent(action="unrelated", actor="system", occurred_at=FIXED_AT, details={}))
    other = tmp_path / "tmp" / "unrelated"
    other.mkdir()
    (other / "keep").write_bytes(b"keep")
    completed = store.create(replace(
        package, id=0, folder_name="archive-completed", status="completed",
    ))
    (tmp_path / completed.folder_name).mkdir()
    (tmp_path / completed.folder_name / "keep").write_bytes(b"archive")
    result = seam.clear_active_package(expected_folder_name=package.folder_name)
    assert set(result["upload_ids"]) == {upload_id, receiving.upload_id}
    assert seam.get_active_package() is None
    assert store.get_by_folder(package.folder_name) is None
    assert store.get(upload_id) is None and store.get(media_job_id) is None
    assert store.get(render.job_id) is None and store.list_pending() == []
    assert [event.action for event in store.list_recent()] == [
        "unrelated", "branding.defaults_updated",
    ]
    assert not (tmp_path / package.folder_name).exists()
    assert not (tmp_path / "tmp" / receiving.upload_id).exists() and not temp.exists()
    assert (other / "keep").read_bytes() == b"keep"
    assert (tmp_path / completed.folder_name / "keep").read_bytes() == b"archive"
    assert (tmp_path / "logo.png").exists()
    with pytest.raises(JobNotFound):
        seam.process_job(render.job_id)
    with pytest.raises(UploadNotFound):
        seam.append_upload_range(receiving.upload_id, 0, 4, "unused", b"1234")
    assert not (tmp_path / package.folder_name).exists()


def test_clear_identity_guard_preserves_files(tmp_path):
    seam, _, _, _, _ = make_editor(tmp_path)
    package = seam.get_active_package()
    with pytest.raises(PackageChanged):
        seam.clear_active_package(expected_folder_name="old-package")
    assert seam.get_active_package() == package
    assert (tmp_path / package.folder_name / "manifest.json").exists()


def test_clear_serializes_with_running_renderer(tmp_path):
    entered, release, cleared = Event(), Event(), Event()

    class SlowRenderer(StubReelRenderer):
        def render(self, build, work_dir, out_path):
            entered.set()
            assert release.wait(5)
            return super().render(build, work_dir, out_path)

    seam, _, _, _, _ = make_editor(tmp_path, renderer=SlowRenderer())
    folder = seam.get_active_package().folder_name
    seam.render_preview(expected_folder_name=folder)
    job = seam.claim_next_job()
    thread = Thread(target=lambda: seam.process_job(job.job_id))
    thread.start()
    assert entered.wait(5)
    cleanup = Thread(target=lambda: (
        seam.clear_active_package(expected_folder_name=folder), cleared.set(),
    ))
    cleanup.start()
    assert not cleared.wait(0.05)
    release.set()
    thread.join(5)
    cleanup.join(5)
    assert cleared.is_set()
    assert not (tmp_path / folder).exists()


def test_failed_render_retry_never_replaces_last_complete_preview(tmp_path):
    seam, _, _, _, _ = make_editor(tmp_path)
    folder = seam.get_active_package().folder_name
    seam.render_preview(expected_folder_name=folder)
    seam.process_job(seam.claim_next_job().job_id)

    class PartialRenderer(StubReelRenderer):
        def render(self, build, work_dir, out_path):
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"partial")
            raise RenderFailed("interrupted")

    seam._renderer = PartialRenderer()
    seam.render_preview(expected_folder_name=folder, retry=True)
    seam.process_job(seam.claim_next_job().job_id)
    assert (tmp_path / folder / "render/reel.mp4").read_bytes() == b"fake-reel"


def test_clear_purge_failure_can_retry_original_identity_after_replacement(tmp_path, monkeypatch):
    seam, _, _, _, _ = make_editor(tmp_path)
    package = seam.get_active_package()
    import shutil
    purge = shutil.rmtree
    with monkeypatch.context() as patch:
        patch.setattr(shutil, "rmtree", lambda *_args: (_ for _ in ()).throw(OSError("locked")))
        with pytest.raises(OSError):
            seam.clear_active_package(expected_folder_name=package.folder_name,
                                      expected_package_id=package.id)
    replacement = seam.ensure_active_package()
    result = seam.clear_active_package(expected_folder_name=package.folder_name,
                                      expected_package_id=package.id)
    assert result["folder_name"] == package.folder_name
    assert seam.get_active_package() == replacement
    assert not list(tmp_path.glob(".clearing-*"))
    assert (tmp_path / replacement.folder_name / "manifest.json").exists()
    assert purge is shutil.rmtree


def test_interrupted_cleanup_recovers_staging_before_retry(tmp_path, monkeypatch):
    seam, store, _, _, _ = make_editor(tmp_path)
    package = seam.get_active_package()
    with monkeypatch.context() as patch:
        def stopped(*_args):
            raise SystemExit("process stopped before database commit")
        patch.setattr(store, "delete_package_records", stopped)
        with pytest.raises(SystemExit):
            seam.clear_active_package(expected_folder_name=package.folder_name,
                                      expected_package_id=package.id)
    assert json.loads((tmp_path / f".clearing-{package.id}.json").read_text())["sources"]
    seam.clear_active_package(expected_folder_name=package.folder_name,
                              expected_package_id=package.id)
    assert seam.get_active_package() is None
    assert not list(tmp_path.glob(".clearing-*"))


def test_cleanup_journal_write_failure_leaves_retryable_package(tmp_path, monkeypatch):
    from pathlib import Path
    seam, _, _, _, _ = make_editor(tmp_path)
    package = seam.get_active_package()
    original = Path.write_text

    def fail_journal(path, *args, **kwargs):
        if path.name.startswith(".clearing-"):
            raise OSError("disk full")
        return original(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "write_text", fail_journal)
        with pytest.raises(OSError):
            seam.clear_active_package(expected_folder_name=package.folder_name,
                                      expected_package_id=package.id)
    assert (tmp_path / package.folder_name / "manifest.json").exists()
    assert not list(tmp_path.glob(".clearing-*"))
    seam.clear_active_package(expected_folder_name=package.folder_name,
                              expected_package_id=package.id)


def test_package_lock_does_not_exhaust_its_own_connection_pool(pg_store):
    from sqlalchemy import create_engine
    engine = create_engine(pg_store._engine.url, pool_size=1, max_overflow=0, pool_timeout=0.1)
    original = pg_store._engine
    pg_store._engine = engine
    pg_store._session_factory.configure(bind=engine)
    try:
        with pg_store.package_lock():
            assert pg_store.get_active() is None
            pg_store.create(Package(0, "single-connection", FIXED_AT, "active"))
        assert pg_store.get_active().folder_name == "single-connection"
    finally:
        pg_store._engine = original
        pg_store._session_factory.configure(bind=original)
        engine.dispose()


def test_repair_never_promotes_cleanup_trash_to_active_package(tmp_path, monkeypatch):
    import shutil
    seam, _, _, _, _ = make_editor(tmp_path)
    package = seam.get_active_package()
    with monkeypatch.context() as patch:
        patch.setattr(shutil, "rmtree", lambda *_args: (_ for _ in ()).throw(OSError("locked")))
        with pytest.raises(OSError):
            seam.clear_active_package(expected_folder_name=package.folder_name,
                                      expected_package_id=package.id)
    assert seam.repair_open_folders() == {"active": None, "recovered": []}
    assert seam.get_active_package() is None


def test_late_upload_init_cannot_recreate_cleared_package(tmp_path):
    seam, _, _, _, _ = make_editor(tmp_path)
    package = seam.get_active_package()
    seam.clear_active_package(expected_folder_name=package.folder_name,
                              expected_package_id=package.id)
    with pytest.raises(PackageChanged):
        seam.start_upload("late.jpg", "image/jpeg", 4, expected_package_id=package.id)
    assert seam.get_active_package() is None
    fresh = seam.start_upload("fresh.jpg", "image/jpeg", 4, expected_package_id=0)
    assert fresh.package_id != package.id


def test_render_preview_rejects_old_revision_after_rerender(tmp_path):
    seam, _, _, _, mid = make_editor(tmp_path)
    folder = seam.get_active_package().folder_name
    old = seam.render_preview(expected_folder_name=folder)["render_revision"]
    seam.process_job(seam.claim_next_job().job_id)
    seam.set_selections({}, expected_folder_name=folder, photo_durations={mid: 6})
    seam.render_preview(expected_folder_name=folder)
    seam.process_job(seam.claim_next_job().job_id)
    with pytest.raises(MediaNotFound):
        seam.get_render_preview(expected_folder_name=folder, expected_revision=old)


def test_clear_waits_for_reminder_and_deletes_its_late_audit(tmp_path):
    entered, release, cleared = Event(), Event(), Event()

    class SlowNotifier(StubNotifier):
        def send(self, notification, tokens):
            entered.set()
            assert release.wait(5)
            return super().send(notification, tokens)

    seam, store, _, _, _ = make_editor(tmp_path)
    package = seam.get_active_package()
    client = store.create_client(Client(0, "device", "device", FIXED_AT, "test"), "hash")
    store.register_token(client.id, "token", FIXED_AT)
    occurrence = store.create(YayinZamani(0, "manual", FIXED_AT, "pending", FIXED_AT))
    store.create(YayinIncelemesi(0, occurrence.id, package.folder_name, "digest", None,
                                "pending", FIXED_AT))
    seam._notifier = SlowNotifier()
    thread = Thread(target=seam.send_due_reminders)
    thread.start()
    assert entered.wait(5)
    cleanup = Thread(target=lambda: (
        seam.clear_active_package(expected_folder_name=package.folder_name), cleared.set(),
    ))
    cleanup.start()
    try:
        assert not cleared.wait(0.05)
    finally:
        release.set()
        thread.join(5)
        cleanup.join(5)
    assert cleared.is_set()
    assert all(event.action != "notification.sent" for event in store.list_recent())
