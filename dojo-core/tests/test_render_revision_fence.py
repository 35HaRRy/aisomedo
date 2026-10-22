from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

from dojo import RenderFailed

from .test_render import finalize_media, make_seam


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
