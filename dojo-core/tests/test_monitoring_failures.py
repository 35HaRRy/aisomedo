"""Terminal job failures become durable alerts through the real publishing path.

``process_job`` records expected media and render failures itself and returns
normally, so monitoring has to read persisted state rather than worker
exceptions. These tests drive the real service against the real store, so the
guarantee shown here is the one production depends on: a failure that never
raises still alerts exactly once, and an unexpected error that never reached a
terminal state is never turned into one.
"""

from __future__ import annotations

import hashlib

import pytest
from dojo import DojoPublishing, InMemoryStore
from dojo.adapters.stubs import (
    StubMediaProcessor,
    StubMetaPublisher,
    StubNotifier,
    StubReelRenderer,
    StubSignedUrlStore,
)
from dojo.monitoring_models import ALERT_KIND_JOB_FAILED
from dojo.testing import FIXED_AT, FakeClock


def make_seam(tmp_path):
    store = InMemoryStore()
    renderer = StubReelRenderer()
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
            renderer=renderer,
        ),
        renderer,
    )


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def complete_upload(seam, tmp_path, *, filename="pic.jpg", content_type="image/jpeg"):
    seam.get_or_create_active_package()
    status = seam.start_upload(filename, content_type, 100)
    seam.append_upload_range(status.upload_id, 0, 100, sha(b"x" * 100), b"x" * 100)
    seam.complete_upload(status.upload_id)
    return status


def failure_alerts(store):
    return [
        alert
        for alert in store.recorded_alerts
        if alert.kind == ALERT_KIND_JOB_FAILED
    ]


def test_missing_staged_upload_persists_a_failed_job_and_alerts(tmp_path):
    """A job that returns normally still leaves one alert for its execution."""
    store, seam, _renderer = make_seam(tmp_path)
    status = complete_upload(seam, tmp_path)
    claimed = seam.claim_next_job()
    assert claimed is not None
    # The staged original disappeared between the claim and the render.
    (tmp_path / "tmp" / status.upload_id / "original").unlink()

    assert seam.process_job(claimed.job_id) is None  # handled internally

    failed = store.get(claimed.job_id)
    assert failed is not None and failed.status == "failed"
    (alert,) = failure_alerts(store)
    assert alert.data["kind"] == ALERT_KIND_JOB_FAILED
    assert alert.data["job_id"] == claimed.job_id
    assert alert.body == f"media.process işi başarısız oldu. İş no: {claimed.job_id}"
    # The stored reason is operator-safe: never the raw error text.
    assert failed.error_reason not in alert.body


def test_rejected_render_persists_a_failed_job_and_alerts(tmp_path):
    store, seam, renderer = make_seam(tmp_path)
    store.set("branding.logo_asset", "logo.png", updated_at=FIXED_AT)
    seam._media = StubMediaProcessor()  # noqa: SLF001 - the real seam default
    complete_upload(seam, tmp_path)
    seam.process_job(seam.claim_next_job().job_id)
    seam.render_preview()
    renderer.fail_reason = "ffmpeg exited 1: token=s3cr3t"
    job = seam.claim_next_job()
    assert job is not None and job.kind == "render"

    seam.process_job(job.job_id)  # a rejected render is handled internally

    failed = store.get(job.job_id)
    assert failed is not None and failed.status == "failed"
    (alert,) = failure_alerts(store)
    assert alert.body == f"render işi başarısız oldu. İş no: {job.job_id}"
    # The renderer's raw message, including the embedded token, stays out.
    assert "s3cr3t" not in alert.body
    assert "ffmpeg exited" not in alert.body


def test_repeated_updates_of_one_failure_do_not_duplicate_the_alert(tmp_path):
    """Re-running a scan over the same failed job alerts once, not once a scan."""
    from dataclasses import replace

    store, seam, _renderer = make_seam(tmp_path)
    status = complete_upload(seam, tmp_path)
    claimed = seam.claim_next_job()
    (tmp_path / "tmp" / status.upload_id / "original").unlink()
    seam.process_job(claimed.job_id)
    assert len(failure_alerts(store)) == 1

    # A later scan re-reads and re-persists the same failed job.
    failed = store.get(claimed.job_id)
    store.update(replace(failed, status="failed", error_reason="still broken"))

    assert len(failure_alerts(store)) == 1


def test_an_unexpected_error_without_a_terminal_state_fabricates_nothing(tmp_path):
    """An exception that never persisted a transition alerts nothing.

    The worker logs it as an execution error and the job stays claimable for
    retry. Inventing a synthetic failure here would page an operator for work
    the system may still complete.
    """

    class Boom(Exception):
        pass

    store, seam, _renderer = make_seam(tmp_path)
    complete_upload(seam, tmp_path)
    claimed = seam.claim_next_job()
    assert claimed is not None
    seam._media = StubMediaProcessor()  # noqa: SLF001

    def _explode(*_args, **_kwargs):
        raise Boom("render backend unreachable at http://internal:9000?t=abc")

    seam._media.process = _explode  # type: ignore[method-assign]  # noqa: SLF001

    with pytest.raises(Boom):
        seam.process_job(claimed.job_id)

    still_running = store.get(claimed.job_id)
    assert still_running is not None and still_running.status == "processing"
    assert failure_alerts(store) == []
