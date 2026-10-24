from __future__ import annotations

from dataclasses import replace

import pytest
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


@pytest.fixture(params=["memory", "postgres"])
def preview_store(request):
    return InMemoryStore() if request.param == "memory" else request.getfixturevalue("pg_store")


def preview_job(job_id="preview-a", media_id="a", kind="section_preview", package_id=1):
    return Job(id=0, job_id=job_id, upload_id=None, kind=kind, status="queued",
               payload={"package_id": package_id, "package": "preview-package",
                        "media_id": media_id, "input_digest": "saved-sections"},
               created_at=FIXED_AT)


@pytest.mark.parametrize("kind", ["section_preview", "thumbnail"])
def test_preview_active_identity_is_unique_until_terminal(preview_store, kind):
    store = preview_store
    first, created = store.create_job_once(preview_job(kind=kind))
    same, duplicate = store.create_job_once(preview_job("duplicate", kind=kind))
    assert created and not duplicate
    assert same.job_id == first.job_id
    store.claim_next(FIXED_AT)
    done = store.finish_if_processing(first.job_id, status="done", finished_at=FIXED_AT)
    assert done.status == "done"
    newer, created = store.create_job_once(preview_job("newer", kind=kind))
    assert created and newer.job_id == "newer"


def test_cancellation_is_media_package_and_kind_local(preview_store):
    store = preview_store
    for job in [preview_job(), preview_job("b", "b"),
                preview_job("other-package", package_id=2),
                preview_job("thumbnail", kind="thumbnail")]:
        store.create_job_once(job)
    assert store.claim_next(FIXED_AT).job_id == "preview-a"
    assert store.cancel_media_jobs(1, "a", kinds=("section_preview",), cancelled_at=FIXED_AT) == 1
    assert store.get("preview-a").status == "cancelled"
    assert store.get("preview-a").finished_at == FIXED_AT
    assert store.get("b").status == "queued"
    assert store.get("other-package").status == "queued"
    assert store.get("thumbnail").status == "queued"
    assert store.finish_if_processing("preview-a", status="done", finished_at=FIXED_AT) is None
    assert store.finish_if_processing("preview-a", status="failed", finished_at=FIXED_AT) is None
    assert store.claim_next(FIXED_AT).job_id == "b"


def test_cancelled_queued_jobs_are_never_claimed(preview_store):
    store = preview_store
    store.create_job_once(preview_job())
    assert store.cancel_media_jobs(1, None, kinds=("section_preview", "thumbnail"),
                                   cancelled_at=FIXED_AT) == 1
    assert store.claim_next(FIXED_AT) is None
    assert store.cancel_media_jobs(1, None, kinds=("section_preview",),
                                   cancelled_at=FIXED_AT) == 0
    assert store.finish_if_processing("missing", status="done", finished_at=FIXED_AT) is None


def test_preview_job_and_cancellation_rollback_with_events(preview_store):
    from dojo.model import AuditEvent

    store = preview_store
    store.create(Package(id=0, folder_name="preview-package", created_at=FIXED_AT))
    first, _ = store.create_job_once(preview_job())
    before = store.get_resource_version("dashboard")
    with pytest.raises(ValueError, match="reject"):
        with store.command_transaction():
            store.cancel_media_jobs(1, "a", kinds=("section_preview",), cancelled_at=FIXED_AT)
            store.create_job_once(replace(preview_job("rolled-back"), payload={
                **first.payload, "input_digest": "new-selection",
            }), audit=AuditEvent(action="preview.queued", actor="test", occurred_at=FIXED_AT))
            raise ValueError("reject")
    assert store.get(first.job_id).status == "queued"
    assert store.get("rolled-back") is None
    assert store.list_recent() == []
    assert store.get_resource_version("dashboard") == before


def test_pg_preview_index_rejects_uncoordinated_duplicate(pg_store):
    from sqlalchemy.exc import IntegrityError

    pg_store.create(preview_job())
    with pytest.raises(IntegrityError):
        pg_store.create(preview_job("uncoordinated"))


def test_pg_concurrent_preview_creation_has_one_winner(pg_store):
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(
            lambda n: pg_store.create_job_once(preview_job(f"concurrent-{n}")), range(4),
        ))
    assert sum(created for _, created in results) == 1
    assert len({job.job_id for job, _ in results}) == 1
