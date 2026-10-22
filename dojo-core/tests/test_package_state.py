import json

import pytest
from dojo import DojoPublishing, InMemoryStore
from dojo.adapters.stubs import StubMetaPublisher, StubNotifier, StubSignedUrlStore
from dojo.testing import FakeClock


@pytest.fixture(params=["memory", "postgres"])
def store(request, pg_store):
    return InMemoryStore() if request.param == "memory" else pg_store


def make_seam(tmp_path, store=None):
    store = store or InMemoryStore()
    seam = DojoPublishing(packages=store, audit=store, uploads=store, jobs=store,
                          settings=store, media_root=tmp_path, clock=FakeClock(),
                          meta=StubMetaPublisher(), notifier=StubNotifier(),
                          signed_urls=StubSignedUrlStore())
    return store, seam


def test_database_wins_over_modified_manifest(tmp_path, store):
    store, seam = make_seam(tmp_path, store)
    package = seam.ensure_active_package()
    seam.set_caption("database caption")
    path = tmp_path / package.folder_name / "manifest.json"
    document = json.loads(path.read_text())
    document["caption"] = "stale disk caption"
    path.write_text(json.dumps(document))
    assert seam.get_draft_caption() == "database caption"
    assert store.read_package_state(package.id).document["caption"] == "database caption"


def test_missing_projection_does_not_lose_state(tmp_path, store):
    store, seam = make_seam(tmp_path, store)
    package = seam.ensure_active_package()
    seam.set_caption("saved")
    path = tmp_path / package.folder_name / "manifest.json"
    path.unlink()
    before = store.read_package_state(package.id)
    assert seam.get_draft_caption() == "saved"
    seam.export_manifest(package)
    assert json.loads(path.read_text())["caption"] == "saved"
    assert store.read_package_state(package.id) == before


def test_projection_failure_after_commit_is_not_rollback(tmp_path, monkeypatch, store):
    store, seam = make_seam(tmp_path, store)
    package = seam.ensure_active_package()

    def fail(package):
        raise OSError("projection unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(seam, "export_manifest", fail, raising=False)
        with pytest.raises(OSError, match="projection unavailable"):
            seam.set_caption("committed before export")
    assert store.read_package_state(package.id).document["caption"] == "committed before export"
    seam.export_manifest(package)
    assert seam.get_draft_caption() == "committed before export"


def test_lifecycle_updates_share_state_transaction(tmp_path, monkeypatch, store):
    store, seam = make_seam(tmp_path, store)
    package = seam.ensure_active_package()
    before = store.read_package_state(package.id)
    path = tmp_path / package.folder_name / "manifest.json"
    before_projection = path.read_bytes()

    def reject(event):
        raise ValueError("audit rejected")

    with monkeypatch.context() as patch:
        patch.setattr(store, "append", reject)
        with pytest.raises(ValueError, match="audit rejected"):
            seam.set_caption("must roll back")
    assert store.read_package_state(package.id) == before
    assert path.read_bytes() == before_projection


def test_project_only_after_outer_scheduler_commit(tmp_path, store):
    store, seam = make_seam(tmp_path, store)
    package = seam.ensure_active_package()
    path = tmp_path / package.folder_name / "manifest.json"
    before = path.read_bytes()
    with pytest.raises(ValueError):
        with store.emission_transaction():
            seam.set_caption("must roll back")
            assert path.read_bytes() == before
            raise ValueError("reject turn")
    assert seam.get_draft_caption() is None
    assert path.read_bytes() == before


def test_repeated_write_does_not_advance_content_revision(tmp_path, store):
    store, seam = make_seam(tmp_path, store)
    package = seam.ensure_active_package()
    seam.set_caption("same")
    before = store.read_package_state(package.id)
    assert before is not None
    seam.set_caption("same")
    assert store.read_package_state(package.id) == before


def test_recovery_does_not_replace_known_database_package_with_newer_folder(tmp_path):
    _, seam = make_seam(tmp_path)
    package = seam.ensure_active_package()
    seam.set_caption("authoritative")
    foreign = tmp_path / "07-08-2026 14-30"
    foreign.mkdir()
    (foreign / "manifest.json").write_text('{"caption":"untrusted disk state"}')
    result = seam.repair_open_folders()
    assert result["active"] == package.folder_name
    assert seam.get_active_package() == package
    assert seam.get_draft_caption() == "authoritative"


def test_clear_removes_authoritative_package_state(tmp_path, store):
    store, seam = make_seam(tmp_path, store)
    package = seam.ensure_active_package()
    seam.clear_active_package(expected_folder_name=package.folder_name,
                              expected_package_id=package.id)
    assert store.read_package_state(package.id) is None
