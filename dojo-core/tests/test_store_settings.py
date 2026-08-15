from __future__ import annotations

from dojo.adapters.db import PostgresStore
from dojo.adapters.memory import InMemoryStore
from dojo.testing import FIXED_AT


def test_memory_settings_get_set() -> None:
    store = InMemoryStore()
    assert store.get("upload.max_file_bytes") is None
    store.set("upload.max_file_bytes", 100, updated_at=FIXED_AT)
    assert store.get("upload.max_file_bytes") == 100
    store.set("upload.max_file_bytes", 200, updated_at=FIXED_AT)
    assert store.get("upload.max_file_bytes") == 200


def test_pg_settings_get_set(pg_store: PostgresStore) -> None:
    assert pg_store.get("upload.max_file_bytes") is None
    pg_store.set("upload.max_file_bytes", 100, updated_at=FIXED_AT)
    assert pg_store.get("upload.max_file_bytes") == 100
    pg_store.set("upload.max_file_bytes", 200, updated_at=FIXED_AT)
    assert pg_store.get("upload.max_file_bytes") == 200
