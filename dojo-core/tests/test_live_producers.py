"""Write-path coverage (actual commands, both store adapters).

View                    Producer exercised
package/dashboard       caption, source metadata, upload finalization, jobs
completed               package create/update/delete
review/publication      occurrence, review create/update, publication record
settings/setup          setting, Meta connection/health, consent acceptance
activity                audit append coalesced with the command
upload:<id>             upload create/update and its worker job transitions
auth                    pairing client creation/revocation; touch is silent

Worker entry-point coverage also lives in worker/tests/test_worker.py.
Transport/read-version coverage belongs to backend SSE/snapshot tests.
"""

from dataclasses import replace

import pytest
from dojo import DojoPublishing
from dojo.adapters.db import LiveChangeEventRow
from dojo.adapters.memory import InMemoryStore
from dojo.model import AuditEvent, Client, Job, Package, Upload, YayinIncelemesi, YayinZamani
from dojo.testing import FIXED_AT, FakeClock
from sqlalchemy import select


@pytest.fixture(params=["memory", "postgres"])
def store(request, pg_store):
    return InMemoryStore() if request.param == "memory" else pg_store


def events(store):
    if isinstance(store, InMemoryStore):
        return list(store._live_events.values())
    with store._session() as session:
        ids = list(session.scalars(select(LiveChangeEventRow.event_id)))
    return [store.get_change(identity) for identity in ids]


def test_package_and_audit_changes_share_one_invalidation(store, tmp_path):
    seam = DojoPublishing(packages=store, audit=store, settings=store,
                          media_root=tmp_path, clock=FakeClock())
    package = seam.ensure_active_package()
    before = {e.event_id for e in events(store)}
    seam.set_caption("changed")
    emitted = [e for e in events(store) if e.event_id not in before]
    assert len(emitted) == 1
    assert emitted[0].versions.keys() >= {"dashboard", f"package:{package.id}", "activity"}


def test_setting_and_audit_updates_are_one_transaction_and_rollback(store):
    before = len(events(store))
    with pytest.raises(ValueError):
        with store.command_transaction():
            store.set("branding.caption_template", "rejected", updated_at=FIXED_AT)
            store.append(AuditEvent(action="settings.changed", actor="cli",
                                    occurred_at=FIXED_AT, details={}))
            raise ValueError("reject")
    assert store.get("branding.caption_template") is None
    assert len(events(store)) == before
    with store.command_transaction():
        store.set("branding.caption_template", "saved", updated_at=FIXED_AT)
        store.append(AuditEvent(action="settings.changed", actor="cli",
                                occurred_at=FIXED_AT, details={}))
    emitted = events(store)
    assert len(emitted) == before + 1
    assert emitted[-1].versions.keys() >= {"settings", "setup", "dashboard", "activity"}


def test_job_queue_claim_completion_and_failure_emit_dashboard(store):
    job = Job(id=0, job_id="j1", upload_id=None, kind="render", status="queued",
              payload={"package": "missing", "digest": "d"}, created_at=FIXED_AT)
    before = store.get_resource_version("dashboard")
    created, inserted = store.create_job_once(job)
    assert inserted
    assert store.get_resource_version("dashboard") == before + 1
    _, inserted = store.create_job_once(job)
    assert not inserted
    assert store.get_resource_version("dashboard") == before + 1
    claimed = store.claim_next(FIXED_AT)
    assert claimed.id == created.id
    assert store.get_resource_version("dashboard") == before + 2
    store.update(replace(claimed, status="done", finished_at=FIXED_AT))
    assert store.get_resource_version("dashboard") == before + 3
    store.update(replace(claimed, status="failed", finished_at=FIXED_AT))
    assert store.get_resource_version("dashboard") == before + 4
    assert store.claim_next(FIXED_AT) is None
    assert store.get_resource_version("dashboard") == before + 4


def test_revocation_contains_target_identity_but_no_credential(store):
    client = store.create_client(Client(id=0, name="browser", kind="browser", created_at=FIXED_AT,
                                        created_by="cli", last_seen_at=FIXED_AT), "private-hash")
    before = {e.event_id for e in events(store)}
    store.mark_client_revoked(client.id, FIXED_AT)
    emitted = [e for e in events(store) if e.event_id not in before]
    assert len(emitted) == 1
    assert emitted[0].revoked_client_ids == [client.id]
    assert "auth" in emitted[0].versions
    assert "private-hash" not in repr(emitted)


def test_meta_connection_and_health_updates_invalidate_setup(store):
    before = store.get_resource_version("setup")
    store.upsert_active(
        ig_user_id="ig-1", ig_username="dojo", page_id=None, page_name=None,
        encrypted_token="encrypted-private", token_expires_at=None, health="healthy",
        last_checked_at=FIXED_AT, last_refreshed_at=None, last_error=None,
    )
    assert store.get_resource_version("setup") == before + 1
    store.update_health("unhealthy", FIXED_AT, "expired")
    assert store.get_resource_version("setup") == before + 2
    assert "encrypted-private" not in repr(events(store))


def test_publication_record_invalidates_publication_view(store, tmp_path):
    seam = DojoPublishing(packages=store, audit=store, settings=store,
                          media_root=tmp_path, clock=FakeClock())
    package = seam.ensure_active_package()
    before = {e.event_id for e in events(store)}
    seam._save_publication_record(package, {"status": "uncertain", "container_id": "c1"})
    emitted = [e for e in events(store) if e.event_id not in before]
    assert len(emitted) == 1
    assert emitted[0].versions.keys() >= {"publication", "dashboard", f"package:{package.id}"}


@pytest.mark.parametrize("kind", ["package", "upload", "job", "occurrence", "review"])
def test_authoritative_mutation_resource_table(store, kind):
    package = store.create(Package(0, "package", FIXED_AT))
    upload = store.create(Upload(0, "upload", package.id, "clip.mp4", "video/mp4", 4,
                                 [], 0, "receiving", FIXED_AT, FIXED_AT))
    occurrence = store.create(YayinZamani(0, "oneoff", FIXED_AT, "pending", FIXED_AT))
    values = {
        "package": (replace(package, status="completed"),
                    {"dashboard", "completed", "publication", f"package:{package.id}"}),
        "upload": (replace(upload, status="finalized"),
                   {"dashboard", f"package:{package.id}", "upload:upload"}),
        "job": (Job(0, "job", upload.id, "media", "queued", {}, FIXED_AT),
                {"dashboard", "publication", f"package:{package.id}", "upload:upload"}),
        "occurrence": (replace(occurrence, status="skipped"), {"dashboard", "publication"}),
        "review": (YayinIncelemesi(0, occurrence.id, package.folder_name, "digest", "caption",
                                  "pending", FIXED_AT), {"dashboard", "publication"}),
    }
    value, expected = values[kind]
    before = {e.event_id for e in events(store)}
    saved = store.create(value) if kind in {"job", "review"} else store.update(value)
    if kind == "review":
        expected.add(f"review:{saved.id}")
    emitted = [e for e in events(store) if e.event_id not in before]
    assert len(emitted) == 1
    assert set(emitted[0].versions) == expected
    before = {e.event_id for e in events(store)}
    store.update(saved)
    emitted = [e for e in events(store) if e.event_id not in before]
    assert len(emitted) == 1
    assert set(emitted[0].versions) == expected


def test_client_touch_does_not_emit_an_invalidation(store):
    client = store.create_client(Client(0, "browser", "browser", FIXED_AT, "cli"), "hash")
    before = {e.event_id for e in events(store)}
    store.touch_client(client.id, FIXED_AT)
    assert {e.event_id for e in events(store)} == before


def test_consent_acceptance_emits_once_and_duplicate_is_silent(store):
    client = store.create_client(Client(0, "browser", "browser", FIXED_AT, "cli"), "hash")
    store.create_policy(version=1, text="policy", created_by="cli", created_at=FIXED_AT)
    before = {e.event_id for e in events(store)}
    _, inserted = store.accept_policy_version(client=client, version=1, accepted_at=FIXED_AT)
    assert inserted
    emitted = [e for e in events(store) if e.event_id not in before]
    assert len(emitted) == 1
    assert set(emitted[0].versions) == {"setup", "settings", "dashboard"}
    before = {e.event_id for e in events(store)}
    _, inserted = store.accept_policy_version(client=client, version=1, accepted_at=FIXED_AT)
    assert not inserted
    assert {e.event_id for e in events(store)} == before


def test_source_metadata_change_advances_content_revision(store, tmp_path):
    seam = DojoPublishing(packages=store, audit=store, settings=store,
                          media_root=tmp_path, clock=FakeClock())
    package = seam.ensure_active_package()
    document = seam._load_manifest(package)
    document["media"] = [{"media_id": "clip", "status": "finalized",
                          "content_type": "video/mp4", "processed": {"duration": 10}}]
    seam._write_manifest(package, document)
    first = store.read_package_state(package.id)
    document["media"][0]["processed"]["duration"] = 8
    seam._write_manifest(package, document)
    assert store.read_package_state(package.id).content_revision == first.content_revision + 1
