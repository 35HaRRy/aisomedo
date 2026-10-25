import shutil
import subprocess
import threading
from datetime import timedelta
from types import SimpleNamespace

import pytest
from dojo.adapters.stubs import StubReelRenderer
from dojo.testing import complete_confirmed_package

from .test_section_previews import save_sections, state
from .test_selections import make_seam, video


def prepared(tmp_path):
    store, seam = make_seam(tmp_path)
    mid = video(tmp_path, seam, store)
    renderer = StubReelRenderer()
    seam._renderer = renderer
    save_sections(seam, mid, [{"start": 0, "end": 5}])
    return store, seam, mid, renderer


def test_worker_attaches_only_saved_sections_as_derived_state(tmp_path):
    store, seam, mid, renderer = prepared(tmp_path)
    before = state(store, seam)
    job = seam.claim_next_job()
    seam.process_job(job.job_id)
    after = state(store, seam)
    record = after.document["section_previews"][mid]
    assert store.get(job.job_id).status == "done"
    assert record["status"] == "ready" and record["duration"] == 5.0
    assert (tmp_path / seam.get_active_package().folder_name / record["artifact_ref"]).is_file()
    assert after.content_revision == before.content_revision
    assert after.view_revision > before.view_revision
    clips, _ = renderer.section_calls[0]
    assert [(clip.trim_start, clip.trim_end) for clip in clips] == [(0.0, 5.0)]
    assert renderer.calls == []
    assert not (tmp_path / "tmp" / f"section-preview-{job.job_id}").exists()


def test_changed_sections_delete_retired_output_only_after_commit(tmp_path, monkeypatch):
    store, seam, mid, _ = prepared(tmp_path)
    seam.process_job(seam.claim_next_job().job_id)
    package = seam.get_active_package()
    record = state(store, seam).document["section_previews"][mid]
    retired = tmp_path / package.folder_name / record["artifact_ref"]
    original = seam.get_active_media_artifact(mid, "original", expected_package_id=package.id,
                                              expected_folder_name=package.folder_name).path
    review = tmp_path / package.folder_name / "reviews" / "immutable.mp4"
    review.parent.mkdir()
    review.write_bytes(b"immutable-review")
    enqueue = store.create_job_once

    def rejected(*args, **kwargs):
        raise RuntimeError("queue write failed")

    monkeypatch.setattr(store, "create_job_once", rejected)
    with pytest.raises(RuntimeError, match="queue write failed"):
        save_sections(seam, mid, [{"start": 10, "end": 15}])
    assert retired.is_file()
    monkeypatch.setattr(store, "create_job_once", enqueue)
    save_sections(seam, mid, [{"start": 10, "end": 15}])
    assert not retired.exists()
    seam.process_job(seam.claim_next_job().job_id)
    current = state(store, seam).document["section_previews"][mid]
    assert (tmp_path / package.folder_name / current["artifact_ref"]).is_file()
    assert original.is_file() and review.read_bytes() == b"immutable-review"


def test_worker_maintenance_retries_retired_file_locked_during_save(tmp_path, monkeypatch):
    from pathlib import Path

    store, seam, mid, _ = prepared(tmp_path)
    seam.process_job(seam.claim_next_job().job_id)
    record = state(store, seam).document["section_previews"][mid]
    retired = tmp_path / seam.get_active_package().folder_name / record["artifact_ref"]
    unlink = Path.unlink

    def locked(path, *args, **kwargs):
        if path == retired:
            raise PermissionError("player has the file open")
        return unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", locked)
        save_sections(seam, mid, [{"start": 10, "end": 15}])
    assert retired.is_file()
    seam.evaluate_due_work()
    assert not retired.exists()


@pytest.mark.parametrize("change", ["aba", "remove", "clear", "complete", "source"])
def test_late_encoder_results_cannot_revive_obsolete_work(tmp_path, change):
    store, seam, mid, renderer = prepared(tmp_path)
    job = seam.claim_next_job()
    original_render = renderer.render_sections

    def render(*args, **kwargs):
        path = original_render(*args, **kwargs)
        if change == "aba":
            save_sections(seam, mid, [{"start": 10, "end": 15}])
            save_sections(seam, mid, [{"start": 0, "end": 5}])
        elif change == "remove":
            seam.remove_media(mid)
        elif change == "clear":
            package = seam.get_active_package()
            seam.clear_active_package(expected_package_id=package.id,
                                      expected_folder_name=package.folder_name)
        elif change == "complete":
            complete_confirmed_package(seam)
        else:
            document = state(store, seam).document
            document["media"][0]["processed"]["size_bytes"] += 1
            seam._write_manifest(seam.get_active_package(), document)
        return path

    renderer.render_sections = render
    seam.process_job(job.job_id)
    old = store.get(job.job_id)
    assert old is None or old.status == "cancelled"
    assert not list(tmp_path.glob(f"**/previews/{job.job_id}.*"))
    assert not (tmp_path / "tmp" / f"section-preview-{job.job_id}").exists()
    if change == "aba":
        assert state(store, seam).document["section_previews"][mid]["generation"] != job.job_id
    assert store.recorded_alerts == []


def test_other_card_edits_and_order_do_not_cancel_an_independent_preview(tmp_path):
    store, seam = make_seam(tmp_path)
    a = video(tmp_path, seam, store, "a.mp4")
    b = video(tmp_path, seam, store, "b.mp4")
    renderer = StubReelRenderer()
    seam._renderer = renderer
    save_sections(seam, a, [{"start": 0, "end": 5}])
    job = seam.claim_next_job()
    render = renderer.render_sections

    def with_other_edit(*args, **kwargs):
        path = render(*args, **kwargs)
        save_sections(seam, b, [{"start": 2, "end": 6}])
        seam.set_order([b, a])
        return path

    renderer.render_sections = with_other_edit
    seam.process_job(job.job_id)
    assert store.get(job.job_id).status == "done"
    assert state(store, seam).document["section_previews"][a]["status"] == "ready"
    assert state(store, seam).document["section_previews"][b]["status"] == "queued"


def test_preview_failure_keeps_saved_edits_and_can_retry(tmp_path):
    store, seam, mid, renderer = prepared(tmp_path)
    renderer.fail_reason = "encoding failed"
    job = seam.claim_next_job()
    seam.process_job(job.job_id)
    assert store.get(job.job_id).status == "failed"
    assert state(store, seam).document["section_previews"][mid]["status"] == "failed"
    assert seam.get_montage_status().selections[mid] == [{"start": 0.0, "end": 5.0}]
    assert store.package_work(seam.get_active_package())[0][0].status == "finalized"
    package = seam.get_active_package()
    seam.retry_section_preview(mid, expected_package_id=package.id,
        expected_folder_name=package.folder_name, expected_generation=job.job_id)
    assert state(store, seam).document["section_previews"][mid]["status"] == "queued"


def test_failed_worker_control_read_never_publishes_output(tmp_path, monkeypatch):
    from contextlib import contextmanager

    store, seam, mid, renderer = prepared(tmp_path)
    job = seam.claim_next_job()
    snapshot = store.read_snapshot
    unavailable = False

    @contextmanager
    def read_snapshot():
        nonlocal unavailable
        if unavailable:
            unavailable = False
            raise ConnectionError("preview control read unavailable")
        with snapshot():
            yield

    monkeypatch.setattr(store, "read_snapshot", read_snapshot)

    def render(*args, cancelled, **kwargs):
        nonlocal unavailable
        unavailable = True
        cancelled()
        raise AssertionError("an unverified encoder must stop")

    renderer.render_sections = render
    seam.process_job(job.job_id)
    assert store.get(job.job_id).status == "failed"
    assert state(store, seam).document["section_previews"][mid]["artifact_ref"] is None
    assert not list(tmp_path.glob(f"**/previews/{job.job_id}.*"))


def test_thumbnail_backfill_works_before_publication_setup_and_is_not_repeated(tmp_path):
    store, seam = make_seam(tmp_path)
    mid = video(tmp_path, seam, store)
    seam._setup = SimpleNamespace(is_ready=lambda: False)
    seam._renderer = StubReelRenderer()
    before = state(store, seam)
    seam.evaluate_due_work()
    seam.evaluate_due_work()
    jobs = store.package_work(seam.get_active_package())[1]
    assert len([job for job in jobs if job.kind == "thumbnail"]) == 1
    thumbnail = seam.claim_next_job()
    assert thumbnail.kind == "thumbnail"
    seam.process_job(thumbnail.job_id)
    record = state(store, seam).document["thumbnails"][mid]
    assert record["status"] == "ready"
    assert (tmp_path / seam.get_active_package().folder_name / record["artifact_ref"]).is_file()
    assert state(store, seam).content_revision == before.content_revision


def test_expired_generation_is_retryable_and_failed_thumbnail_is_not_looped(tmp_path):
    store, seam, mid, renderer = prepared(tmp_path)
    seam._setup = SimpleNamespace(is_ready=lambda: False)
    job = seam.claim_next_job()
    seam._clock._now += timedelta(seconds=906)
    seam.evaluate_due_work()
    assert store.get(job.job_id).status == "failed"
    assert state(store, seam).document["section_previews"][mid]["status"] == "failed"
    thumbnail = seam.claim_next_job()
    renderer.fail_reason = "thumbnail unavailable"
    seam.process_job(thumbnail.job_id)
    assert state(store, seam).document["thumbnails"][mid]["status"] == "failed"
    seam.evaluate_due_work()
    assert seam.claim_next_job() is None
    assert store.package_work(seam.get_active_package())[0][0].status == "finalized"


def test_legacy_saved_sections_receive_one_initial_generation(tmp_path):
    store, seam, mid, _ = prepared(tmp_path)
    seam._setup = SimpleNamespace(is_ready=lambda: False)
    old = state(store, seam).document["section_previews"][mid]["generation"]
    store.cancel_media_jobs(seam.get_active_package().id, mid, kinds=("section_preview",),
                            cancelled_at=seam._clock.now())
    document = state(store, seam).document
    document.pop("section_previews")
    seam._write_manifest(seam.get_active_package(), document)
    seam.evaluate_due_work()
    seam.evaluate_due_work()
    record = state(store, seam).document["section_previews"][mid]
    assert record["generation"] != old
    jobs = store.package_work(seam.get_active_package())[1]
    assert len([j for j in jobs if j.kind == "section_preview" and j.status == "queued"]) == 1


def test_worker_supersession_stops_an_actual_ffmpeg_process(tmp_path, monkeypatch):
    if not shutil.which("ffmpeg"):
        pytest.skip("Native FFmpeg unavailable: actual cancellation check not executed")
    from dojo.adapters import preview_process

    store, seam, mid, renderer = prepared(tmp_path)
    launched = threading.Event()
    children = []
    popen = subprocess.Popen

    def start(*args, **kwargs):
        child = popen(*args, **kwargs)
        children.append(child)
        launched.set()
        return child

    monkeypatch.setattr(preview_process.subprocess, "Popen", start)

    def encode(*args, cancelled, **kwargs):
        preview_process.run_preview_process(["ffmpeg", "-v", "error", "-re", "-f", "lavfi",
            "-i", "testsrc=size=32x32:rate=1", "-t", "60", "-f", "null", "-"],
            cancelled=cancelled)
        raise AssertionError("superseded encoder should not finish")

    renderer.render_sections = encode
    job = seam.claim_next_job()

    def supersede():
        assert launched.wait(5)
        save_sections(seam, mid, [{"start": 10, "end": 15}])

    writer = threading.Thread(target=supersede)
    writer.start()
    try:
        seam.process_job(job.job_id)
    finally:
        writer.join(timeout=5)
    assert not writer.is_alive()
    assert len(children) == 1 and children[0].poll() is not None
    assert store.get(job.job_id).status == "cancelled"
    assert store.recorded_alerts == []
