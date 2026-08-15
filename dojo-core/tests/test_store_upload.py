from __future__ import annotations

from datetime import timedelta

from dojo.adapters.db import PostgresStore
from dojo.adapters.memory import InMemoryStore
from dojo.model import Package, Upload
from dojo.testing import FIXED_AT


def make_upload(upload_id: str = "u-1") -> Upload:
    return Upload(
        id=0,
        upload_id=upload_id,
        package_id=1,
        filename="ok.jpg",
        content_type="image/jpeg",
        declared_size_bytes=100,
        received_ranges=[[0, 50]],
        received_bytes=50,
        status="receiving",
        created_at=FIXED_AT,
        updated_at=FIXED_AT,
    )


def test_memory_upload_roundtrip() -> None:
    store = InMemoryStore()
    created = store.create(make_upload())
    assert created.id > 0
    assert store.get("u-1") == created
    assert store.get("missing") is None
    assert store.get_by_pk(created.id) == created
    assert store.list_active() == [created]


def test_memory_upload_update() -> None:
    store = InMemoryStore()
    created = store.create(make_upload())
    updated = store.update(
        Upload(
            id=created.id,
            upload_id="u-1",
            package_id=1,
            filename="ok.jpg",
            content_type="image/jpeg",
            declared_size_bytes=100,
            received_ranges=[[0, 100]],
            received_bytes=100,
            status="queued",
            created_at=FIXED_AT,
            updated_at=FIXED_AT,
        )
    )
    assert updated.status == "queued"
    assert updated.received_bytes == 100
    assert store.get("u-1").received_bytes == 100


def test_memory_upload_list_stale() -> None:
    store = InMemoryStore()
    store.create(make_upload("u-1"))
    stale = store.list_stale(FIXED_AT + timedelta(seconds=1))
    assert [u.upload_id for u in stale] == ["u-1"]
    assert store.list_stale(FIXED_AT) == []


def test_memory_list_active_includes_processing() -> None:
    store = InMemoryStore()
    created = store.create(make_upload("u-1"))
    store.update(
        Upload(
            id=created.id,
            upload_id="u-1",
            package_id=1,
            filename="ok.jpg",
            content_type="image/jpeg",
            declared_size_bytes=100,
            received_ranges=[[0, 100]],
            received_bytes=100,
            status="processing",
            created_at=FIXED_AT,
            updated_at=FIXED_AT,
        )
    )
    assert [u.upload_id for u in store.list_active()] == ["u-1"]
    assert store.list_stale(FIXED_AT + timedelta(hours=25)) == []


def test_pg_upload_roundtrip(pg_store: PostgresStore) -> None:
    pg_store.create(Package(id=0, folder_name="06-08-2026 14-30", created_at=FIXED_AT))
    created = pg_store.create(make_upload())
    assert created.id > 0
    assert pg_store.get("u-1") == created
    assert pg_store.get_by_pk(created.id) == created
    assert pg_store.get("missing") is None


def test_pg_upload_update(pg_store: PostgresStore) -> None:
    pg_store.create(Package(id=0, folder_name="06-08-2026 14-30", created_at=FIXED_AT))
    created = pg_store.create(make_upload())
    updated = pg_store.update(
        Upload(
            id=created.id,
            upload_id="u-1",
            package_id=1,
            filename="ok.jpg",
            content_type="image/jpeg",
            declared_size_bytes=100,
            received_ranges=[[0, 100]],
            received_bytes=100,
            status="queued",
            created_at=FIXED_AT,
            updated_at=FIXED_AT,
        )
    )
    assert updated.status == "queued"
