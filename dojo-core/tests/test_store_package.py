from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from dojo import DojoPublishing
from dojo.adapters.db import PostgresStore
from dojo.adapters.memory import InMemoryStore
from dojo.model import Package
from dojo.testing import FIXED_AT, FakeClock


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


def test_memory_update_missing_raises_value_error() -> None:
    store = InMemoryStore()
    with pytest.raises(ValueError, match="package 999 not found"):
        store.update(Package(id=999, folder_name="missing", created_at=FIXED_AT))


def test_pg_update_missing_raises_value_error(pg_store: PostgresStore) -> None:
    with pytest.raises(ValueError, match="package 999 not found"):
        pg_store.update(Package(id=999, folder_name="missing", created_at=FIXED_AT))


def test_pg_partial_unique_index_blocks_second_active_row(pg_store: PostgresStore) -> None:
    pg_store.create(Package(id=0, folder_name="06-08-2026 14-30", created_at=FIXED_AT))
    with pytest.raises(Exception):  # IntegrityError on commit
        pg_store.create(Package(id=0, folder_name="06-08-2026 15-00", created_at=FIXED_AT))


def test_pg_complete_active_package_roundtrip(pg_store: PostgresStore, tmp_path: Path) -> None:
    seam = DojoPublishing(
        packages=pg_store,
        audit=pg_store,
        media_root=tmp_path,
        clock=FakeClock(),
    )
    first = seam.ensure_active_package()

    next_package = seam.complete_active_package(requester="9")

    completed_dir = tmp_path / f"{first.folder_name}-completed"
    assert completed_dir.is_dir()

    assert next_package.status == "active"
    assert next_package.id != first.id
    assert seam.get_active_package() == next_package
    assert pg_store.get_active() == next_package
    assert pg_store.get_active().id != first.id

    actions = [e.action for e in seam.list_audit()]
    assert actions[0] == "package.created"  # for the next package
    assert actions[1] == "package.completed"
    completed = [e for e in seam.list_audit() if e.action == "package.completed"]
    assert completed[0].actor == "9"
    assert completed[0].details == {"folder_name": f"{first.folder_name}-completed"}
