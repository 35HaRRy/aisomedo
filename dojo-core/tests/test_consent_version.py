from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import dojo
import pytest
from dojo.adapters.db import PostgresStore
from dojo.adapters.memory import InMemoryStore
from dojo.testing import FakeClock
from sqlalchemy import event

from tests.test_setup import add_client, make_setup


def test_displayed_version_rejects_new_policy() -> None:
    store = InMemoryStore()
    setup = make_setup(store)
    client = add_client(setup, store)
    setup.set_policy(version=1, text="v1", requester="cli")
    setup.set_policy(version=2, text="v2", requester="cli")
    with pytest.raises(dojo.ConsentPolicyChanged):
        setup.accept_current_policy(client=client, version=1)
    assert store.find_acceptance(2) is None
    assert store.find_acceptance(1) is None
    assert not any(e.action == "consent.accepted" for e in store.list_recent())


def test_versioned_acceptance_is_inherited_and_idempotent() -> None:
    store = InMemoryStore()
    setup = make_setup(store)
    first = add_client(setup, store, name="First")
    second = add_client(setup, store, name="Second")
    with pytest.raises(dojo.NoConsentPolicy):
        setup.accept_current_policy(client=first, version=1)
    setup.set_policy(version=1, text="v1", requester="cli")
    accepted = setup.accept_current_policy(client=first, version=1)
    assert setup.accept_current_policy(client=second, version=1) == accepted
    assert setup.accept_current_policy(client=second) == accepted
    assert accepted.accepting_client_id == first.id
    assert accepted.accepting_client_name == "First"
    assert len([e for e in store.list_recent() if e.action == "consent.accepted"]) == 1


@pytest.mark.parametrize("persistent", [False, True])
def test_concurrent_same_version_accepts_once(
    persistent: bool, request: pytest.FixtureRequest
) -> None:
    store = request.getfixturevalue("pg_store") if persistent else InMemoryStore()
    setup = dojo.DojoSetup(setup=store, audit=store, pairing=store, clock=FakeClock())
    client = add_client(setup, store)
    setup.set_policy(version=1, text="v1", requester="cli")
    barrier = Barrier(4)

    def accept() -> dojo.ConsentAcceptance:
        barrier.wait(timeout=10)
        return setup.accept_current_policy(client=client, version=1)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(accept) for _ in range(4)]
        accepted = [f.result(timeout=20) for f in futures]
    assert all(a == accepted[0] for a in accepted)
    assert len([e for e in store.list_recent() if e.action == "consent.accepted"]) == 1


def test_postgres_policy_update_serializes_waiting_acceptance(pg_store: PostgresStore) -> None:
    setup = dojo.DojoSetup(setup=pg_store, audit=pg_store, pairing=pg_store, clock=FakeClock())
    client = add_client(setup, pg_store)
    setup.set_policy(version=1, text="v1", requester="cli")
    update_locked = Event()
    release_update = Event()
    acceptance_lock_started = Event()

    def pause_update(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if statement.startswith("INSERT INTO consent_policies"):
            update_locked.set()
            assert release_update.wait(timeout=10)
        elif statement == "SELECT pg_advisory_xact_lock(hashtext('dojo.consent-policy'))":
            acceptance_lock_started.set()

    event.listen(pg_store._engine, "before_cursor_execute", pause_update)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            update = pool.submit(setup.set_policy, version=2, text="v2", requester="cli")
            assert update_locked.wait(timeout=10)
            accept = pool.submit(setup.accept_current_policy, client=client, version=1)
            assert acceptance_lock_started.wait(timeout=10)
            release_update.set()
            update.result(timeout=10)
            with pytest.raises(dojo.ConsentPolicyChanged):
                accept.result(timeout=10)
    finally:
        release_update.set()
        event.remove(pg_store._engine, "before_cursor_execute", pause_update)
    assert pg_store.find_acceptance(1) is None
    assert pg_store.find_acceptance(2) is None


def test_memory_policy_update_serializes_waiting_acceptance() -> None:
    store = InMemoryStore()
    setup = make_setup(store)
    client = add_client(setup, store)
    setup.set_policy(version=1, text="v1", requester="cli")
    started = Event()

    def accept() -> dojo.ConsentAcceptance:
        started.set()
        return setup.accept_current_policy(client=client, version=1)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with store._consent_lock:
            future = pool.submit(accept)
            assert started.wait(timeout=10)
            setup.set_policy(version=2, text="v2", requester="cli")
        with pytest.raises(dojo.ConsentPolicyChanged):
            future.result(timeout=10)
    assert store.find_acceptance(1) is None
    assert store.find_acceptance(2) is None
