from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

import pytest
from dojo import RenderFailed

from .test_render import finalize_media, make_seam


@pytest.mark.parametrize(
    "change", ["duration", "order", "remove", "restore", "upload", "selections"],
)
def test_media_changes_clear_reel_and_wait_for_review_to_render(tmp_path, change):
    from datetime import timedelta

    from dojo.exceptions import MediaNotFound
    from dojo.model import YayinZamani

    store, seam, renderer = make_seam(tmp_path)
    photo = finalize_media(tmp_path, seam)
    video = finalize_media(tmp_path, seam, filename="video.mp4",
                           content_type="video/mp4", duration=30)
    store.set("branding.logo_asset", "logo.png", updated_at=seam._clock.now())
    if change == "restore":
        seam.remove_media(photo)
    seam.render_preview()
    seam.process_job(seam.claim_next_job().job_id)
    folder = seam.get_active_package().folder_name
    artifact = seam.get_render_preview(expected_folder_name=folder).path
    due_at = seam._clock.now() + timedelta(hours=1)
    store.create(YayinZamani(0, "oneoff", due_at, "pending", seam._clock.now()))

    if change == "duration":
        seam.set_selections({}, expected_folder_name=folder, photo_durations={photo: 6})
    elif change == "order":
        seam.set_order([video, photo])
    elif change == "remove":
        seam.remove_media(photo)
    elif change == "restore":
        seam.restore_media(photo)
    elif change == "upload":
        finalize_media(tmp_path, seam, filename="new.jpg")
    else:
        seam.set_selections({video: [{"start": 1, "end": 5}]}, expected_folder_name=folder)

    seam.evaluate_due_work()
    jobs = store.package_work(seam.get_active_package())[1]
    assert not [j for j in jobs if j.kind == "render" and j.status in ("queued", "processing")]
    assert not artifact.exists()
    assert seam.get_active_editor()["render_status"] == "missing"
    with pytest.raises(MediaNotFound):
        seam.get_render_preview(expected_folder_name=folder)
    assert len(renderer.calls) == 1

    seam._clock._now = due_at
    seam.evaluate_due_work()
    jobs = store.package_work(seam.get_active_package())[1]
    assert not [j for j in jobs if j.kind == "render" and j.status in ("queued", "processing")]
    assert seam.get_active_editor()["render_status"] == "missing"
    seam.render_preview(expected_folder_name=folder)
    while (job := seam.claim_next_job()) is not None:
        seam.process_job(job.job_id)
    assert seam.get_active_editor()["render_status"] == "ready"
    assert artifact.is_file()
    assert len(renderer.calls) == 2
    assert len(seam.list_pending_reviews()) == 1


def test_default_logo_is_part_of_the_render_digest(tmp_path):
    _, seam, _ = make_seam(tmp_path)
    finalize_media(tmp_path, seam)
    seam._settings.set("branding.logo_asset", "first.png", updated_at=seam._clock.now())
    first = seam.render_preview()["render_revision"]
    seam._settings.set("branding.logo_asset", "second.png", updated_at=seam._clock.now())
    second = seam.render_preview()["render_revision"]
    assert first != second


def test_edit_during_render_is_not_blocked_or_overwritten(tmp_path):
    store, seam, renderer = make_seam(tmp_path)
    finalize_media(tmp_path, seam)
    seam._settings.set("branding.logo_asset", "logo.png", updated_at=seam._clock.now())
    seam.render_preview()
    job = seam.claim_next_job()
    entered, release, edited = Event(), Event(), Event()
    original = renderer.render

    def render(*args):
        entered.set()
        assert release.wait(5), "test must release the renderer"
        return original(*args)

    renderer.render = render
    before = store.read_package_state(seam.get_active_package().id).content_revision
    with ThreadPoolExecutor(2) as pool:
        rendering = pool.submit(seam.process_job, job.job_id)
        assert entered.wait(2)

        def change():
            seam.set_caption("changed during rendering")
            edited.set()

        editing = pool.submit(change)
        try:
            assert edited.wait(2), "editing must not wait for expensive rendering"
        finally:
            release.set()
        editing.result(timeout=5)
        rendering.result(timeout=5)
    snapshot = seam.get_active_editor()
    assert snapshot["content_revision"] > before
    assert seam.get_draft_caption() == "changed during rendering"
    assert snapshot["render_status"] != "ready"


def test_duplicate_render_job_does_not_replace_ready_artifact(tmp_path):
    store, seam, renderer = make_seam(tmp_path)
    finalize_media(tmp_path, seam)
    seam._settings.set("branding.logo_asset", "logo.png", updated_at=seam._clock.now())
    seam.render_preview()
    job = seam.claim_next_job()
    seam.process_job(job.job_id)
    artifact = seam.get_render_preview(expected_folder_name=seam.get_active_package().folder_name)
    before = artifact.path.read_bytes()
    original = renderer.render

    def render(*args):
        output = original(*args)
        output.write_bytes(b"must-not-replace-reviewed-output")
        return output

    renderer.render = render
    store.create(replace(job, id=0, job_id="duplicate", status="queued", claimed_at=None))
    duplicate = seam.claim_next_job()
    seam.process_job(duplicate.job_id)
    assert artifact.path.read_bytes() == before


def test_superseded_render_failure_does_not_mark_new_content_failed(tmp_path):
    _, seam, renderer = make_seam(tmp_path)
    finalize_media(tmp_path, seam)
    seam._settings.set("branding.logo_asset", "logo.png", updated_at=seam._clock.now())
    seam.render_preview()
    job = seam.claim_next_job()

    def fail(*args):
        seam.set_caption("new content is not the failed render input")
        raise RenderFailed("old input failed")

    renderer.render = fail
    seam.process_job(job.job_id)
    assert seam.get_active_editor()["render_status"] != "failed"
    package = seam.get_active_package()
    assert seam._render_failed_digest(package) != seam._render_digest(
        package, seam._load_manifest(package),
    )


def test_concurrent_same_digest_completion_keeps_first_ready_artifact(tmp_path):
    store, seam, renderer = make_seam(tmp_path)
    finalize_media(tmp_path, seam)
    store.set("branding.logo_asset", "logo.png", updated_at=seam._clock.now())
    seam.render_preview()
    job = seam.claim_next_job()
    # Exercise the completion fence even if a stale/recovered worker races a
    # second render; normal scheduler uniqueness must not be the only guard.
    duplicate = store.create(replace(job, id=0, job_id="duplicate", status="done"))
    entered, release = Event(), Event()
    original = renderer.render

    def render(build, work, staged):
        if "duplicate" in str(work):
            entered.set()
            assert release.wait(5)
        output = original(build, work, staged)
        output.write_bytes(b"second" if "duplicate" in str(work) else b"first")
        return output

    renderer.render = render
    with ThreadPoolExecutor(1) as pool:
        second = pool.submit(seam._render_job, duplicate, seam.get_active_package().folder_name)
        assert entered.wait(2)
        try:
            seam.process_job(job.job_id)
        finally:
            release.set()
        second.result(timeout=5)
    artifact = seam.get_render_preview(expected_folder_name=seam.get_active_package().folder_name)
    assert artifact.path.read_bytes() == b"first"


def test_scheduler_never_renders_even_with_an_actual_due_occurrence(tmp_path):
    from dojo.model import YayinZamani

    store, seam, renderer = make_seam(tmp_path)
    finalize_media(tmp_path, seam)
    store.set("branding.logo_asset", "logo.png", updated_at=seam._clock.now())
    seam.evaluate_due_work()
    seam.evaluate_due_work()
    jobs = store.package_work(seam.get_active_package())[1]
    assert [job for job in jobs if job.kind == "render"] == []
    now = seam._clock.now()
    store.create(YayinZamani(0, "oneoff", now, "pending", now))
    seam.evaluate_due_work()
    seam.evaluate_due_work()
    jobs = store.package_work(seam.get_active_package())[1]
    assert [job for job in jobs if job.kind == "render"] == []
    seam.render_preview()
    seam.render_preview()
    jobs = store.package_work(seam.get_active_package())[1]
    assert len([job for job in jobs if job.kind == "render"]) == 1
    job = seam.claim_next_job()
    seam.process_job(job.job_id)
    seam.evaluate_due_work()
    assert len(seam.list_pending_reviews()) == 1
    assert len(renderer.calls) == 1
    assert seam._meta.created == []


def test_reel_duration_comes_from_output_probe_not_calculated_montage(tmp_path):
    store, seam, renderer = make_seam(tmp_path)
    finalize_media(tmp_path, seam)
    store.set("branding.logo_asset", "logo.png", updated_at=seam._clock.now())
    renderer.probe_duration = lambda path, *, cancelled: 3.08
    seam.render_preview()
    seam.process_job(seam.claim_next_job().job_id)
    editor = seam.get_active_editor()
    assert editor["render_status"] == "ready"
    assert editor["render_duration"] == 3.08
    assert editor["montage"]["combined_duration"] == 3.0


@pytest.mark.parametrize("automatic", [False, True])
def test_render_recovers_a_missing_current_artifact(tmp_path, automatic):
    from dojo.model import YayinZamani

    store, seam, _ = make_seam(tmp_path)
    finalize_media(tmp_path, seam)
    store.set("branding.logo_asset", "logo.png", updated_at=seam._clock.now())
    seam.render_preview()
    seam.process_job(seam.claim_next_job().job_id)
    output = seam.get_render_preview(expected_folder_name=seam.get_active_package().folder_name)
    output.path.unlink()
    if automatic:
        now = seam._clock.now()
        store.create(YayinZamani(0, "oneoff", now, "pending", now))
        seam.evaluate_due_work()
    seam.render_preview()
    job = seam.claim_next_job()
    assert job is not None and job.kind == "render"
    seam.process_job(job.job_id)
    assert seam.get_active_editor()["render_status"] == "ready"


def test_ready_legacy_render_does_not_invent_missing_output_duration(tmp_path):
    store, seam, _ = make_seam(tmp_path)
    finalize_media(tmp_path, seam)
    store.set("branding.logo_asset", "logo.png", updated_at=seam._clock.now())
    seam.render_preview()
    seam.process_job(seam.claim_next_job().job_id)
    package = seam.get_active_package()
    document = seam._load_manifest(package)
    document.pop("render_duration")
    seam._write_manifest(package, document)
    editor = seam.get_active_editor()
    assert editor["render_status"] == "ready"
    assert editor["render_duration"] is None


def test_section_preview_completion_keeps_the_ready_reel_and_its_duration(tmp_path):
    store, seam, _ = make_seam(tmp_path)
    mid = finalize_media(tmp_path, seam, filename="video.mp4",
                         content_type="video/mp4", duration=30)
    store.set("branding.logo_asset", "logo.png", updated_at=seam._clock.now())
    seam.set_selections({mid: [{"start": 0, "end": 5}]},
                         expected_folder_name=seam.get_active_package().folder_name)
    section_job = seam.claim_next_job()
    assert section_job.kind == "section_preview"
    seam.render_preview()
    seam.process_job(seam.claim_next_job().job_id)
    before = seam.get_active_editor()
    seam.process_job(section_job.job_id)
    after = seam.get_active_editor()
    assert after["render_status"] == "ready"
    assert after["render_revision"] == before["render_revision"]
    assert after["render_duration"] == 5.0
    assert after["content_revision"] == before["content_revision"]
