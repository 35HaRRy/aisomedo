from __future__ import annotations

from dojo.adapters.db import PostgresStore
from dojo.model import Client, PairingCode
from dojo.testing import FIXED_AT


def test_code_roundtrip(pg_store: PostgresStore) -> None:
    code = pg_store.create_code(
        PairingCode(
            id=0,
            code_hash="abc123",
            expires_at=FIXED_AT,
            created_by="cli",
            created_at=FIXED_AT,
        )
    )
    assert code.id > 0
    found = pg_store.find_code_by_hash("abc123")
    assert found is not None
    assert found.created_by == "cli"
    assert pg_store.find_code_by_hash("nope") is None


def test_mark_consumed_single_use(pg_store: PostgresStore) -> None:
    code = pg_store.create_code(
        PairingCode(
            id=0,
            code_hash="h1",
            expires_at=FIXED_AT,
            created_by="cli",
            created_at=FIXED_AT,
        )
    )
    assert pg_store.mark_code_consumed(code.id, FIXED_AT) is True
    assert pg_store.mark_code_consumed(code.id, FIXED_AT) is False
    found = pg_store.find_code_by_hash("h1")
    assert found is not None
    assert found.consumed_at is not None


def test_client_roundtrip_and_lookup(pg_store: PostgresStore) -> None:
    client = pg_store.create_client(
        Client(id=0, name="Phone", kind="device", created_at=FIXED_AT, created_by="cli"),
        credential_hash="credhash1",
    )
    assert client.id > 0
    by_hash = pg_store.find_client_by_credential_hash("credhash1")
    assert by_hash is not None
    assert by_hash.name == "Phone"
    by_id = pg_store.find_client_by_id(client.id)
    assert by_id is not None
    assert pg_store.find_client_by_credential_hash("nope") is None


def test_list_revoke_touch(pg_store: PostgresStore) -> None:
    first = pg_store.create_client(
        Client(id=0, name="Phone", kind="device", created_at=FIXED_AT, created_by="cli"),
        credential_hash="h1",
    )
    pg_store.create_client(
        Client(id=0, name="Browser", kind="browser", created_at=FIXED_AT, created_by="cli"),
        credential_hash="h2",
    )
    assert len(pg_store.list_clients()) == 2

    pg_store.mark_client_revoked(first.id, FIXED_AT)
    revoked = pg_store.find_client_by_id(first.id)
    assert revoked is not None
    assert revoked.revoked_at is not None

    pg_store.touch_client(first.id, FIXED_AT)
    touched = pg_store.find_client_by_id(first.id)
    assert touched is not None
    assert touched.last_seen_at == FIXED_AT
