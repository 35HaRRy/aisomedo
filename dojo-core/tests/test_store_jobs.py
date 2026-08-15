from __future__ import annotations

from dojo.adapters.db import PostgresStore
from dojo.adapters.memory import InMemoryStore
from dojo.model import Job, Package, Upload
from dojo.testing import FIXED_AT


def make_job(job_id: str = "j-1", upload_id: int = 7) -> Job:
    return Job(
        id=0,
        job_id=job_id,
        upload_id=upload_id,
        kind="media.process",
        status="queued",
        payload={"upload_id": 7},
        created_at=FIXED_AT,
    )


def test_memory_job_roundtrip() -> None:
    store = InMemoryStore()
    created = store.create(make_job())
    assert created.id > 0
    assert store.get("j-1") == created
    assert store.get_by_upload(7) == created
    assert store.get("missing") is None


def test_memory_claim_next_marks_processing() -> None:
    store = InMemoryStore()
    store.create(make_job("j-1"))
    claimed = store.claim_next(FIXED_AT)
    assert claimed is not None
    assert claimed.status == "processing"
    assert claimed.claimed_at == FIXED_AT
    assert store.claim_next(FIXED_AT) is None


def test_pg_job_roundtrip_and_claim(pg_store: PostgresStore) -> None:
    pg_store.create(Package(id=0, folder_name="06-08-2026 14-30", created_at=FIXED_AT))
    upload = pg_store.create(
        Upload(
            id=0,
            upload_id="u-1",
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
    )
    created = pg_store.create(make_job(upload_id=upload.id))
    assert pg_store.get("j-1") == created
    assert pg_store.get_by_upload(upload.id) == created
    claimed = pg_store.claim_next(FIXED_AT)
    assert claimed is not None
    assert claimed.status == "processing"
    assert pg_store.claim_next(FIXED_AT) is None
