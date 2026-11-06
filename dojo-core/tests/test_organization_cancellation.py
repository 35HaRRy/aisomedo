import httpx
import pytest
from dojo.adapters.preview_process import PreviewCancelled
from dojo.exceptions import OrganizationInactive
from dojo.model import Job
from dojo.organizations import DojoOrganizations
from dojo.testing import FIXED_AT

from tests.test_meta_publisher import make_publisher
from tests.test_render import finalize_media, make_seam, set_logo


def test_inactive_organization_jobs_remain_unclaimed(tmp_path):
    store, publishing, _ = make_seam(tmp_path)
    job = store.create(Job(0, "queued", None, "render", "queued", {}, FIXED_AT))
    DojoOrganizations(store).deactivate("Test Dojo")
    assert publishing.claim_next_job() is None
    assert store.get(job.job_id).status == "queued"


def test_deactivation_during_render_cancels_without_attaching_or_deleting_old_artifact(tmp_path):
    store, publishing, renderer = make_seam(tmp_path)
    set_logo(store, "logo.png")
    finalize_media(tmp_path, publishing)
    publishing.render_preview()
    job = publishing.claim_next_job()
    artifact = tmp_path / publishing.get_active_package().folder_name / "render" / "reel.mp4"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"old approved render")

    def render(build, work_dir, out_path, *, cancelled=None):
        DojoOrganizations(store).deactivate("Test Dojo")
        assert cancelled is not None and cancelled()
        raise PreviewCancelled()

    renderer.render = render
    publishing.process_job(job.job_id)
    stored = store.get(job.job_id)
    assert stored.status == "cancelled"
    assert stored.error_reason == "organization_inactive"
    assert artifact.read_bytes() == b"old approved render"
    assert not (tmp_path / "tmp" / f"render-{job.job_id}").exists()
    assert not any(e.action == "render.completed" for e in store.list_recent())


def test_deactivation_before_publish_prevents_external_publish_request():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"id": "container"})

    publisher, store = make_publisher(handler)
    publisher.create_container("https://example.com/pub/token", "caption")
    DojoOrganizations(store).deactivate("Test Dojo")
    with pytest.raises(OrganizationInactive):
        publisher.publish_container("container")
    assert len(calls) == 1


def test_media_processing_receives_cancellation_and_keeps_the_uploaded_original(tmp_path):
    import hashlib
    from types import SimpleNamespace

    store, publishing, _ = make_seam(tmp_path)
    publishing.get_or_create_active_package()
    upload = publishing.start_upload("image.jpg", "image/jpeg", 3)
    publishing.append_upload_range(
        upload.upload_id, 0, 3, hashlib.sha256(b"abc").hexdigest(), b"abc",
    )
    publishing.complete_upload(upload.upload_id)
    job = publishing.claim_next_job()

    def process(upload, original_path, work_dir, *, cancelled=None):
        DojoOrganizations(store).deactivate("Test Dojo")
        assert cancelled is not None and cancelled()
        raise PreviewCancelled()

    publishing._media = SimpleNamespace(process=process)
    publishing.process_job(job.job_id)
    assert store.get(job.job_id).status == "cancelled"
    assert (tmp_path / "tmp" / upload.upload_id / "original").read_bytes() == b"abc"


def test_inactive_organization_cannot_maintain_instagram_credentials():
    from dojo import DojoMetaConnection
    from dojo.adapters.meta import FernetCipher, StubMetaOAuthProvider
    from dojo.testing import scoped_memory_store

    store = scoped_memory_store()
    provider = StubMetaOAuthProvider()
    connection = DojoMetaConnection(store=store, provider=provider,
        cipher=FernetCipher(FernetCipher.generate_key()), app_id="test", app_secret="test",
        redirect_uri="https://example.test/callback")
    DojoOrganizations(store).deactivate("Test Dojo")
    with pytest.raises(OrganizationInactive):
        connection.maintain()
    assert provider.calls == []


def test_initial_organization_repair_never_moves_other_organization_media(tmp_path):
    _, publishing, _ = make_seam(tmp_path)
    publishing.get_or_create_active_package()
    foreign = tmp_path / "organizations" / "2" / "foreign-package" / "original.jpg"
    foreign.parent.mkdir(parents=True)
    foreign.write_bytes(b"other organization")
    result = publishing.repair_open_folders()
    assert result["recovered"] == []
    assert foreign.read_bytes() == b"other organization"


def test_deactivation_after_preview_encoding_prevents_attachment(tmp_path):
    from tests.test_preview_worker import prepared, state

    store, publishing, mid, renderer = prepared(tmp_path)
    job = publishing.claim_next_job()
    probe = renderer.probe_duration

    def deactivate_after_probe(*args, **kwargs):
        duration = probe(*args, **kwargs)
        DojoOrganizations(store).deactivate("Test Dojo")
        return duration

    renderer.probe_duration = deactivate_after_probe
    publishing.process_job(job.job_id)
    assert store.get(job.job_id).status == "cancelled"
    record = state(store, publishing).document["section_previews"][mid]
    assert record["status"] != "ready"
    assert not record.get("artifact_ref")


@pytest.mark.parametrize("kind", ["recovery", "publication"])
def test_domain_push_rechecks_deactivation_after_recipient_lookup(tmp_path, kind):
    from dojo.model import Client

    store, publishing, _ = make_seam(tmp_path)
    client = store.create_client(Client(0, "Phone", "device", FIXED_AT, "cli"), "phone")
    store.register_token(client.id, "phone-token", FIXED_AT)
    recipients = store.list_active_device_tokens

    def deactivate_after_lookup():
        result = recipients()
        DojoOrganizations(store).deactivate("Test Dojo")
        return result

    store.list_active_device_tokens = deactivate_after_lookup
    if kind == "recovery":
        publishing._notify_recovery(active="package", recovered=["old-package"])
    else:
        publishing._notify_publication_outcome(succeeded=True, package_folder="package")
    assert publishing._notifier.sent == []
