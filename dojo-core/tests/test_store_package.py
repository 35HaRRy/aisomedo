from __future__ import annotations

from dataclasses import replace

import pytest
from dojo.adapters.db import PostgresStore
from dojo.adapters.memory import InMemoryStore
from dojo.model import Package
from dojo.testing import FIXED_AT


def test_memory_update_replaces_row() -> None:
    store = InMemoryStore()
    created = store.create(
        Package(id=0, folder_name="06-08-2026 14-30", created_at=FIXED_AT)
    )
    updated = store.update(
        replace(created, status="completed", folder_name="06-08-2026 14-30-completed")
    )
    assert updated.id == created.id
    assert updated.status == "completed"
    assert updated.folder_name == "06-08-2026 14-30-completed"
    assert store.get_active() is None


def test_pg_update_replaces_row(pg_store: PostgresStore) -> None:
    created = pg_store.create(
        Package(id=0, folder_name="06-08-2026 14-30", created_at=FIXED_AT)
    )
    updated = pg_store.update(
        replace(created, status="completed", folder_name="06-08-2026 14-30-completed")
    )
    assert updated.id == created.id
    assert updated.status == "completed"
    assert updated.folder_name == "06-08-2026 14-30-completed"
    assert pg_store.get_active() is None


def test_pg_partial_unique_index_blocks_second_active_row(pg_store: PostgresStore) -> None:
    pg_store.create(Package(id=0, folder_name="06-08-2026 14-30", created_at=FIXED_AT))
    with pytest.raises(Exception):  # IntegrityError on commit
        pg_store.create(Package(id=0, folder_name="06-08-2026 15-00", created_at=FIXED_AT))
