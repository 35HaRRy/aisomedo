from __future__ import annotations

from dojo.adapters.db import PostgresStore
from dojo.adapters.memory import InMemoryStore
from dojo.model import ConsentAcceptance
from dojo.testing import FIXED_AT


def make_acceptance(*, version: int = 1) -> ConsentAcceptance:
    return ConsentAcceptance(
        policy_version=version,
        accepted_at=FIXED_AT,
        accepting_client_id=7,
        accepting_client_name="Phone",
        accepting_client_kind="device",
    )


def test_memory_policy_roundtrip_and_in_place_update() -> None:
    store = InMemoryStore()
    store.create_policy(version=1, text="v1", created_by="cli", created_at=FIXED_AT)
    store.create_policy(version=1, text="v1b", created_by="cli", created_at=FIXED_AT)
    found = store.get_policy(1)
    assert found is not None
    assert found.text == "v1b"
    assert found.created_by == "cli"


def test_memory_get_current_policy_returns_highest_version() -> None:
    store = InMemoryStore()
    store.create_policy(version=1, text="v1", created_by="cli", created_at=FIXED_AT)
    store.create_policy(version=3, text="v3", created_by="cli", created_at=FIXED_AT)
    current = store.get_current_policy()
    assert current is not None
    assert current.version == 3
    assert store.get_policy(2) is None


def test_memory_acceptance_idempotent() -> None:
    store = InMemoryStore()
    assert store.record_acceptance(make_acceptance()) is True
    assert store.record_acceptance(make_acceptance()) is False
    found = store.find_acceptance(1)
    assert found is not None
    assert found.accepting_client_id == 7
    assert store.find_acceptance(9) is None


def test_pg_policy_roundtrip_and_in_place_update(pg_store: PostgresStore) -> None:
    pg_store.create_policy(version=1, text="v1", created_by="cli", created_at=FIXED_AT)
    pg_store.create_policy(version=1, text="v1b", created_by="cli", created_at=FIXED_AT)
    found = pg_store.get_policy(1)
    assert found is not None
    assert found.text == "v1b"


def test_pg_get_current_policy_returns_highest_version(pg_store: PostgresStore) -> None:
    pg_store.create_policy(version=1, text="v1", created_by="cli", created_at=FIXED_AT)
    pg_store.create_policy(version=3, text="v3", created_by="cli", created_at=FIXED_AT)
    current = pg_store.get_current_policy()
    assert current is not None
    assert current.version == 3


def test_pg_acceptance_idempotent(pg_store: PostgresStore) -> None:
    pg_store.create_policy(version=1, text="v1", created_by="cli", created_at=FIXED_AT)
    assert pg_store.record_acceptance(make_acceptance()) is True
    assert pg_store.record_acceptance(make_acceptance()) is False
    found = pg_store.find_acceptance(1)
    assert found is not None
    assert found.accepting_client_id == 7