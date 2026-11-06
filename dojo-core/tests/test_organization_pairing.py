import pytest
from dojo import ClientNotFound, DojoPairing, PairingError
from dojo.adapters.memory import InMemoryStore
from dojo.exceptions import OrganizationInactive, OrganizationScopeRequired
from dojo.organizations import DojoOrganizations


@pytest.fixture(params=["memory", "postgres"])
def system(request):
    root = InMemoryStore() if request.param == "memory" else request.getfixturevalue("pg_registry")
    organizations = DojoOrganizations(root)
    a = organizations.create(name="A", email="a@example.com")
    b = organizations.create(name="B", email="b@example.com")
    return root, organizations, DojoPairing(pairing=root, audit=root), a, b


def test_global_pairing_cannot_issue_without_an_organization(system):
    _, _, pairing, _, _ = system
    with pytest.raises(OrganizationScopeRequired):
        pairing.create_pairing_code(requester="cli")


def test_pending_code_only_reveals_its_active_organization_without_consuming(system):
    _, organizations, pairing, a, b = system
    code = pairing.create_pairing_code(requester="cli", organization_id=a.id).raw_code
    assert pairing.pending_code_organization(code="invalid") is None
    assert pairing.pending_code_organization(code=code) == a
    pairing.validate_code(code=code, kind="browser", name="Browser")
    assert pairing.pending_code_organization(code=code) is None
    code = pairing.create_pairing_code(requester="cli", organization_id=b.id).raw_code
    organizations.deactivate("B")
    assert pairing.pending_code_organization(code=code) is None


def test_pending_code_does_not_reveal_expired_organization(system):
    from datetime import timedelta

    from dojo.pairing import CODE_TTL
    from dojo.testing import FakeClock

    _, _, pairing, a, _ = system
    clock = FakeClock()
    pairing._clock = clock
    code = pairing.create_pairing_code(requester="cli", organization_id=a.id).raw_code
    pairing._clock = FakeClock(clock.now() + CODE_TTL + timedelta(seconds=1))
    assert pairing.pending_code_organization(code=code) is None


def test_pairing_code_attaches_client_to_its_organization(system):
    root, _, pairing, a, b = system
    issued = pairing.create_pairing_code(requester="cli", organization_id=a.id)
    result = pairing.validate_code(code=issued.raw_code, kind="browser", name="Browser A")
    client = pairing.authenticate_session(result.raw_credential)
    assert client.organization_id == a.id
    assert root.for_organization(b.id).list_clients() == []
    with pytest.raises(ClientNotFound):
        pairing.revoke_client(client_id=client.id, requester="cli", organization_id=b.id)
    assert pairing.authenticate_session(result.raw_credential) is not None


@pytest.mark.parametrize("kind", ["browser", "device"])
def test_deactivation_blocks_existing_credentials_and_unused_codes(system, kind):
    _, organizations, pairing, a, b = system
    issued = pairing.create_pairing_code(requester="cli", organization_id=a.id)
    client = pairing.validate_code(code=issued.raw_code, kind=kind, name="A")
    unused = pairing.create_pairing_code(requester="cli", organization_id=a.id)
    organizations.deactivate("A")
    assert pairing.authenticate_session(client.raw_credential) is None
    assert pairing.authenticate_bearer(client.raw_credential) is None
    with pytest.raises(PairingError):
        pairing.validate_code(code=unused.raw_code, kind=kind, name="Disabled")
    with pytest.raises(OrganizationInactive):
        pairing.create_pairing_code(requester="cli", organization_id=a.id)
    other = pairing.create_pairing_code(requester="cli", organization_id=b.id)
    assert pairing.validate_code(code=other.raw_code, kind=kind, name="B").client_id > 0
