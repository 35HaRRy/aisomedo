from dataclasses import replace
from datetime import UTC, datetime

import pytest
from dojo.adapters.memory import InMemoryStore
from dojo.exceptions import OrganizationScopeRequired
from dojo.model import AuditEvent, Client, Package, PairingCode
from dojo.organizations import DojoOrganizations

NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


@pytest.fixture(params=["memory", "postgres"])
def workspaces(request):
    root = InMemoryStore() if request.param == "memory" else request.getfixturevalue("pg_registry")
    organizations = DojoOrganizations(root)
    first = organizations.create(name="First", email="first@example.com")
    second = organizations.create(name="Second", email="second@example.com")
    return root, root.for_organization(first.id), root.for_organization(second.id)


def test_two_active_packages_and_settings_are_independent(workspaces):
    _, first, second = workspaces
    a = first.create(Package(0, "same-package", NOW))
    b = second.create(Package(0, "same-package", NOW))
    first.set("caption", "first", updated_at=NOW)
    second.set("caption", "second", updated_at=NOW)
    assert first.get_active() == a
    assert second.get_active() == b
    assert a.id != b.id
    assert first.get("caption") == "first"
    assert second.get("caption") == "second"


def test_foreign_package_cannot_be_read_or_updated(workspaces):
    _, first, second = workspaces
    package = second.create(Package(0, "second-package", NOW))
    assert first.get_by_folder(package.folder_name) is None
    with pytest.raises(ValueError):
        first.update(replace(package, status="completed"))
    assert second.get_active() == package


def test_audit_history_does_not_leak(workspaces):
    _, first, second = workspaces
    first.append(AuditEvent("first", "cli", NOW))
    second.append(AuditEvent("second", "cli", NOW))
    assert [e.action for e in first.list_recent()] == ["first"]
    assert [e.action for e in second.list_recent()] == ["second"]


def test_unscoped_domain_access_fails(workspaces):
    root, _, _ = workspaces
    with pytest.raises(OrganizationScopeRequired):
        root.get_active()


def test_scope_cannot_be_reassigned(workspaces):
    _, first, _ = workspaces
    with pytest.raises(AttributeError):
        first.organization_id = 999


def test_credentials_and_codes_resolve_to_their_owner(workspaces):
    root, first, second = workspaces
    client = first.create_client(Client(0, "Browser", "browser", NOW, "cli"), "a" * 64)
    code = first.create_code(PairingCode(0, "b" * 64, NOW, "cli", NOW))
    assert client.organization_id == first.organization_id
    assert code.organization_id == first.organization_id
    assert root.find_client_by_credential_hash("a" * 64) == client
    assert root.find_code_by_hash("b" * 64) == code
    assert second.find_client_by_id(client.id) is None
    assert second.find_client_by_credential_hash("a" * 64) is None
    assert second.find_code_by_hash("b" * 64) is None


def test_foreign_upload_parent_is_rejected(workspaces):
    from dojo.model import Upload
    from sqlalchemy.exc import IntegrityError

    _, first, second = workspaces
    package = second.create(Package(0, "foreign-parent", NOW))
    upload = Upload(id=0, upload_id="foreign-upload", package_id=package.id,
                    filename="image.jpg", content_type="image/jpeg", declared_size_bytes=5,
                    received_ranges=[], received_bytes=0, status="receiving",
                    created_at=NOW, updated_at=NOW)
    with pytest.raises((ValueError, IntegrityError)):
        first.create(upload)
    assert second.list_active() == []


def test_meta_connections_are_independent(workspaces):
    _, first, second = workspaces
    first.upsert_active(ig_user_id="first", ig_username="first", page_id=None, page_name=None,
                        encrypted_token="secret-first", token_expires_at=None, health="connected",
                        last_checked_at=None, last_refreshed_at=None, last_error=None)
    second.upsert_active(ig_user_id="second", ig_username="second", page_id=None, page_name=None,
                         encrypted_token="secret-second", token_expires_at=None, health="connected",
                         last_checked_at=None, last_refreshed_at=None, last_error=None)
    assert first.get_active_snapshot()[0].ig_user_id == "first"
    assert second.get_active_snapshot()[0].ig_user_id == "second"
    assert first.get_raw_active()[0] == "secret-first"
    assert second.get_raw_active()[0] == "secret-second"


def test_package_and_scheduler_locks_do_not_block_another_organization(pg_registry):
    organizations = DojoOrganizations(pg_registry)
    a = organizations.create(name="A", email="a@example.com")
    b = organizations.create(name="B", email="b@example.com")
    first = pg_registry.for_organization(a.id)
    same = pg_registry.for_organization(a.id)
    other = pg_registry.for_organization(b.id)
    with first.package_lock():
        with other.package_lock(wait=False) as acquired:
            assert acquired is True
        with same.package_lock(wait=False) as acquired:
            assert acquired is False
    with first.emission_transaction():
        assert first.try_advisory_xact_lock(123)
        with other.emission_transaction():
            assert other.try_advisory_xact_lock(123)
        with same.emission_transaction():
            assert not same.try_advisory_xact_lock(123)


def test_inactive_organizations_are_excluded_from_atomic_job_claims(workspaces):
    from dojo.model import Job

    root, first, _ = workspaces
    job = first.create(Job(0, "queued-job", None, "render", "queued", {}, NOW))
    root.deactivate_organization(first.organization_id)
    assert first.claim_next(NOW) is None
    assert first.get(job.job_id).status == "queued"
