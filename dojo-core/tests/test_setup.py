from __future__ import annotations

import threading

import pytest
from dojo import ConsentPolicyDowngrade, DojoPairing, DojoSetup, NoConsentPolicy
from dojo.adapters.db import PostgresStore
from dojo.adapters.memory import InMemoryStore
from dojo.model import Client, ConsentAcceptance
from dojo.testing import FakeClock


def make_setup(store: InMemoryStore) -> DojoSetup:
    return DojoSetup(setup=store, audit=store, pairing=store, clock=FakeClock())


def make_pairing(store: InMemoryStore) -> DojoPairing:
    return DojoPairing(pairing=store, audit=store, clock=FakeClock())


def add_client(setup: DojoSetup, store: InMemoryStore, *, name: str = "Phone") -> Client:
    pairing = make_pairing(store)
    code = pairing.create_pairing_code(requester="cli").raw_code
    result = pairing.validate_code(code=code, kind="device", name=name)
    client = store.find_client_by_id(result.client_id)
    assert client is not None
    return client


def test_set_policy_creates_current_policy_and_audits() -> None:
    store = InMemoryStore()
    setup = make_setup(store)
    policy = setup.set_policy(version=1, text="Riza metni", requester="cli")
    assert policy.version == 1
    assert policy.text == "Riza metni"
    assert setup.current_policy() == policy
    events = [e for e in store.list_recent() if e.action == "consent.policy_updated"]
    assert len(events) == 1
    assert events[0].actor == "cli"
    assert events[0].details["version"] == 1


def test_set_policy_same_version_updates_text_in_place() -> None:
    store = InMemoryStore()
    setup = make_setup(store)
    setup.set_policy(version=1, text="v1", requester="cli")
    setup.set_policy(version=1, text="v1b", requester="cli")
    policy = setup.current_policy()
    assert policy is not None and policy.text == "v1b"
    updated = [e for e in store.list_recent() if e.action == "consent.policy_updated"]
    assert len(updated) == 2


def test_set_policy_rejects_downgrade() -> None:
    store = InMemoryStore()
    setup = make_setup(store)
    setup.set_policy(version=3, text="v3", requester="cli")
    with pytest.raises(ConsentPolicyDowngrade):
        setup.set_policy(version=2, text="v2", requester="cli")


def test_accept_current_policy_records_once_and_is_idempotent() -> None:
    store = InMemoryStore()
    setup = make_setup(store)
    setup.set_policy(version=1, text="v1", requester="cli")
    client = add_client(setup, store)

    acceptance = setup.accept_current_policy(client=client)
    again = setup.accept_current_policy(client=client)

    assert isinstance(acceptance, ConsentAcceptance)
    assert acceptance.policy_version == 1
    assert acceptance.accepting_client_id == client.id
    assert acceptance.accepting_client_name == "Phone"
    assert acceptance.accepting_client_kind == "device"
    assert again == acceptance
    accepted = [e for e in store.list_recent() if e.action == "consent.accepted"]
    assert len(accepted) == 1
    assert accepted[0].actor == str(client.id)
    assert accepted[0].details["version"] == 1


def test_accept_without_policy_raises() -> None:
    store = InMemoryStore()
    setup = make_setup(store)
    client = add_client(setup, store)
    with pytest.raises(NoConsentPolicy):
        setup.accept_current_policy(client=client)


def test_new_version_requires_fresh_acceptance() -> None:
    store = InMemoryStore()
    setup = make_setup(store)
    setup.set_policy(version=1, text="v1", requester="cli")
    client = add_client(setup, store)
    setup.accept_current_policy(client=client)
    setup.set_policy(version=2, text="v2", requester="cli")
    assert setup.checklist_item("consent").complete is False
    setup.accept_current_policy(client=client)
    assert setup.checklist_item("consent").complete is True


def test_checklist_pairing_tracks_non_revoked_clients() -> None:
    store = InMemoryStore()
    setup = make_setup(store)
    assert setup.checklist_item("pairing").complete is False
    client = add_client(setup, store)
    assert setup.checklist_item("pairing").complete is True
    make_pairing(store).revoke_client(client_id=client.id, requester="cli")
    assert setup.checklist_item("pairing").complete is False


def test_checklist_consent_requires_current_version_accepted() -> None:
    store = InMemoryStore()
    setup = make_setup(store)
    add_client(setup, store)
    assert setup.checklist_item("consent").complete is False
    setup.set_policy(version=1, text="v1", requester="cli")
    assert setup.checklist_item("consent").complete is False
    client = add_client(setup, store)
    setup.accept_current_policy(client=client)
    assert setup.checklist_item("consent").complete is True


def test_is_ready_requires_all_items() -> None:
    store = InMemoryStore()
    setup = make_setup(store)
    assert setup.is_ready() is False
    add_client(setup, store)
    assert setup.is_ready() is False
    setup.set_policy(version=1, text="v1", requester="cli")
    client = store.find_client_by_id(1)
    assert client is not None
    setup.accept_current_policy(client=client)
    assert setup.is_ready() is True


def test_acceptance_over_postgres_once_per_version(pg_store: PostgresStore) -> None:
    setup = DojoSetup(setup=pg_store, audit=pg_store, pairing=pg_store, clock=FakeClock())
    pairing = DojoPairing(pairing=pg_store, audit=pg_store, clock=FakeClock())
    setup.set_policy(version=1, text="v1", requester="cli")
    code = pairing.create_pairing_code(requester="cli").raw_code
    result = pairing.validate_code(code=code, kind="device", name="Phone")

    client = pg_store.find_client_by_id(result.client_id)
    assert client is not None
    setup.accept_current_policy(client=client)
    setup.accept_current_policy(client=client)

    sources = pg_store.find_acceptance(1)
    assert sources is not None
    events = pg_store.list_recent()
    accepted = [e for e in events if e.action == "consent.accepted"]
    assert len(accepted) == 1


def test_concurrent_acceptance_records_single_row(pg_store: PostgresStore) -> None:
    setup = DojoSetup(setup=pg_store, audit=pg_store, pairing=pg_store, clock=FakeClock())
    setup.set_policy(version=1, text="v1", requester="cli")
    clients = pg_store.list_clients()
    assert not clients
    # Seed one client through the real pairing path
    pairing = DojoPairing(pairing=pg_store, audit=pg_store, clock=FakeClock())
    rt = pairing.create_pairing_code(requester="cli").raw_code
    pairing.validate_code(code=rt, kind="device", name="Phone")
    client = pg_store.find_client_by_id(1)
    assert client is not None

    results: list[bool] = []
    barrier = threading.Barrier(2)

    def attempt() -> None:
        barrier.wait(timeout=10)
        try:
            setup.accept_current_policy(client=client)
            results.append(True)
        except NoConsentPolicy:
            results.append(False)

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == [True, True]
    assert pg_store.find_acceptance(1) is not None
    accepted = [e for e in pg_store.list_recent() if e.action == "consent.accepted"]
    assert len(accepted) == 1
