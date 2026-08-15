# Resumable Upload, Media Validation, and Finalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship resumable chunked uploads, media validation/normalization/transcode, limits, and package finalization for issue #7: `start_upload` → `append_upload_range` → `complete_upload` → worker `process_job` → `finalize_media` into the active package, with per-file/per-package limits, staging cleanup, and audit.

**Architecture:** Extend the deep `DojoPublishing` facade (`dojo/publishing.py`). Three new Postgres tables (`uploads`, `jobs`, `settings`) via migration `0005_media_upload`; new protocols `UploadStore`/`JobStore`/`SettingsStore`/`MediaProcessor` on `dojo/ports.py` implemented by `InMemoryStore` and `PostgresStore`. Staging under `media_root/tmp/<upload_id>/`; worker claims `media.process` jobs, runs the Pillow+ffmpeg `PillowFFmpegProcessor`, and finalizes original+processed artifacts into `package/media/<media_id>/`. Routes under `/api/media/uploads`; CLI `dojo-settings set-upload-limits`.

**Tech Stack:** Python 3.12 (uv workspace), FastAPI, SQLAlchemy 2.0, alembic, pytest, testcontainers-python, Pillow + pillow-heif, ffmpeg/ffprobe (worker container + docker test fixtures), ruff, mypy.

## Global Constraints

- Python `requires-python = ">=3.12"`.
- Domain vocabulary from `CONTEXT.md` / `docs/specs/dojo-reel-publishing-mvp.md`: active `Dojo Paylaşım Paketi`, `media_id` (immutable UUID), manifest contract. Do not invent new domain nouns.
- One primary seam: `DojoPublishing` in `dojo/publishing.py`. Tests assert externally visible domain outcomes through this interface, not SQL/private methods.
- Accepted formats: JPEG, PNG, WebP, HEIC/HEIF, MP4, MOV. Validate real content (magic bytes), not extension. Reject animated images, corrupt media, unsupported codecs — with actionable `error_reason`.
- Image normalization: canonical JPEG (RGB), EXIF orientation baked into pixels, longest side cap 4000px.
- Video transcode: MP4 H.264/AAC, `yuv420p`, `+faststart`, same resolution; verified with ffprobe.
- Limits: `upload.max_file_bytes` default `2 * 1024**3`; `upload.max_package_bytes` default `20 * 1024**3`; overrides in `settings` table; enforced at start (declared size) and finalize (actual size + `shutil.disk_usage`).
- Filename safety at start: reject empty, `/`, `\`, and control characters (`ord(c) < 32`).
- Upload statuses: `receiving` → `queued` → `processing` → `finalized` | `failed` | `aborted`. Job statuses: `queued` → `processing` → `done` | `failed`. Exactly-once complete/finalize via status guards.
- Staging under `media_root/tmp/<upload_id>/`; cleanup on abort, finalize, validation failure, and a 24h TTL sweep.
- Routes behind `get_current_client`; equal privilege device + browser; unauth → 401. Chunk size ≤ 8 MiB.
- dojo-core deps gain `pillow>=11` and `pillow-heif>=0.16`. Worker Dockerfile installs `ffmpeg`.
- Lint: ruff (`E,F,I,UP`). dojo-core mypy with `disallow_untyped_defs`; backend mypy `strict`. Both must pass before each task's commit.
- Commands run from repo root. Tests against real Postgres via the `pg_store` fixture use `FakeClock` for deterministic time.
- Every Python task: run the focused test file first, then the package's full suite, before committing.

---

### Task 1: Storage — models, ports, migration 0005, both adapters

**Files:**
- Modify: `dojo-core/src/dojo/model.py`
- Modify: `dojo-core/src/dojo/ports.py`
- Modify: `dojo-core/src/dojo/exceptions.py`
- Create: `dojo-core/migrations/versions/0005_media_upload.py`
- Modify: `dojo-core/src/dojo/adapters/memory.py`
- Modify: `dojo-core/src/dojo/adapters/db.py`
- Create: `dojo-core/tests/test_store_upload.py`
- Create: `dojo-core/tests/test_store_jobs.py`
- Create: `dojo-core/tests/test_store_settings.py`
- Modify: `dojo-core/tests/test_db_adapter.py`

**Interfaces:**
- Consumes: existing `InMemoryStore`/`PostgresStore`, `Base`, alembic conventions from `0004_active_package`, `FIXED_AT`.
- Produces:
  - Models `MediaEntry`, `Upload`, `UploadStatus`, `Job`, `ProcessedMedia`, `UploadLimits`.
  - Exceptions `UploadNotFound`, `UploadNotReceiving`, `UploadChecksumMismatch`, `UploadTooLarge`, `PackageLimitExceeded`, `UploadIncomplete`, `UploadConflict`, `UploadInvalidFilename`, `JobNotFound`, `MediaValidationError` (all subclass `DojoError`).
  - Protocols `UploadStore` (`create`, `get`, `get_by_pk`, `update`, `list_active`, `list_stale`), `JobStore` (`create`, `get`, `get_by_upload`, `update`, `claim_next`), `SettingsStore` (`get`, `set`), `MediaProcessor` (`process`).
  - Migration `0005_media_upload` (`down_revision = "0004_active_package"`).
  - `InMemoryStore` and `PostgresStore` implement the three new store protocols.

- [ ] **Step 1: Write the failing store tests**

Create `dojo-core/tests/test_store_upload.py`:
```python
from __future__ import annotations

import pytest
from dojo.adapters.db import PostgresStore
from dojo.adapters.memory import InMemoryStore
from dojo.model import Upload
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
    from datetime import timedelta

    stale = store.list_stale(FIXED_AT + timedelta(seconds=1))
    assert [u.upload_id for u in stale] == ["u-1"]
    assert store.list_stale(FIXED_AT) == []


def test_pg_upload_roundtrip(pg_store: PostgresStore) -> None:
    created = pg_store.create(make_upload())
    assert created.id > 0
    assert pg_store.get("u-1") == created
    assert pg_store.get_by_pk(created.id) == created
    assert pg_store.get("missing") is None


def test_pg_upload_update(pg_store: PostgresStore) -> None:
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
```

Create `dojo-core/tests/test_store_jobs.py`:
```python
from __future__ import annotations

from dojo.adapters.db import PostgresStore
from dojo.adapters.memory import InMemoryStore
from dojo.model import Job
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
    created = pg_store.create(make_job())
    assert pg_store.get("j-1") == created
    assert pg_store.get_by_upload(7) == created
    claimed = pg_store.claim_next(FIXED_AT)
    assert claimed is not None
    assert claimed.status == "processing"
    assert pg_store.claim_next(FIXED_AT) is None
```

Create `dojo-core/tests/test_store_settings.py`:
```python
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
```

In `dojo-core/tests/test_db_adapter.py`, extend `test_alembic_upgrade_head_creates_schema`:
```python
    assert {"packages", "audit_events", "consent_policies", "consent_acceptances",
            "uploads", "jobs", "settings"} <= set(inspector.get_table_names())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_store_upload.py dojo-core/tests/test_store_jobs.py dojo-core/tests/test_store_settings.py dojo-core/tests/test_db_adapter.py -v`
Expected: FAIL — models/protocols/methods absent, tables missing.

- [ ] **Step 3: Add models to `dojo/model.py`**

Append after `ConsentAcceptance`:
```python
@dataclass(frozen=True)
class MediaEntry:
    media_id: str
    filename: str
    content_type: str
    size_bytes: int
    uploaded_at: datetime
    status: str = "finalized"
    processed: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "media_id": self.media_id,
            "filename": self.filename,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "uploaded_at": self.uploaded_at.isoformat(),
            "status": self.status,
            "processed": self.processed,
        }


@dataclass(frozen=True)
class Upload:
    id: int
    upload_id: str
    package_id: int
    filename: str
    content_type: str
    declared_size_bytes: int
    received_ranges: list[list[int]]
    received_bytes: int
    status: str
    created_at: datetime
    updated_at: datetime
    error_reason: str | None = None


@dataclass(frozen=True)
class UploadStatus:
    upload_id: str
    received_bytes: int
    declared_size_bytes: int
    status: str
    received_ranges: list[list[int]]


@dataclass(frozen=True)
class Job:
    id: int
    job_id: str
    upload_id: int
    kind: str
    status: str
    payload: dict
    created_at: datetime
    claimed_at: datetime | None = None
    finished_at: datetime | None = None
    error_reason: str | None = None


@dataclass(frozen=True)
class ProcessedMedia:
    original_path: Path
    processed_path: Path
    content_type: str
    size_bytes: int
    dimensions: tuple[int, int] | None = None
    duration: float | None = None


@dataclass(frozen=True)
class UploadLimits:
    max_file_bytes: int
    max_package_bytes: int
```

Add `from pathlib import Path` to the top imports.

- [ ] **Step 4: Add exceptions to `dojo/exceptions.py`**

Append:
```python
class UploadNotFound(DojoError):
    pass


class UploadNotReceiving(DojoError):
    pass


class UploadChecksumMismatch(DojoError):
    pass


class UploadTooLarge(DojoError):
    pass


class PackageLimitExceeded(DojoError):
    pass


class UploadIncomplete(DojoError):
    pass


class UploadConflict(DojoError):
    pass


class UploadInvalidFilename(DojoError):
    pass


class JobNotFound(DojoError):
    pass


class MediaValidationError(DojoError):
    pass
```

- [ ] **Step 5: Add protocols to `dojo/ports.py`**

Add imports: `from dojo.model import Job, Upload`. Append:
```python
@runtime_checkable
class UploadStore(Protocol):
    def create(self, upload: Upload) -> Upload: ...
    def get(self, upload_id: str) -> Upload | None: ...
    def get_by_pk(self, upload_pk: int) -> Upload | None: ...
    def update(self, upload: Upload) -> Upload: ...
    def list_active(self) -> list[Upload]: ...
    def list_stale(self, cutoff: datetime) -> list[Upload]: ...


@runtime_checkable
class JobStore(Protocol):
    def create(self, job: Job) -> Job: ...
    def get(self, job_id: str) -> Job | None: ...
    def get_by_upload(self, upload_pk: int) -> Job | None: ...
    def update(self, job: Job) -> Job: ...
    def claim_next(self, claimed_at: datetime) -> Job | None: ...


@runtime_checkable
class SettingsStore(Protocol):
    def get(self, key: str) -> object | None: ...
    def set(self, key: str, value: object, *, updated_at: datetime) -> None: ...


@runtime_checkable
class MediaProcessor(Protocol):
    def process(
        self, upload: Upload, original_path: Path, work_dir: Path
    ) -> ProcessedMedia: ...
```

Add `ProcessedMedia` and `Upload` to the `from dojo.model import` line.

- [ ] **Step 6: Write the migration**

Create `dojo-core/migrations/versions/0005_media_upload.py`:
```python
"""uploads, jobs, and settings tables

Revision ID: 0005_media_upload
Revises: 0004_active_package
Create Date: 2026-08-15

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_media_upload"
down_revision: Union[str, None] = "0004_active_package"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "uploads",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("upload_id", sa.String(length=36), nullable=False),
        sa.Column("package_id", sa.BigInteger(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("declared_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("received_ranges", sa.JSON(), nullable=False),
        sa.Column("received_bytes", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_reason", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["package_id"], ["packages.id"]),
        sa.UniqueConstraint("upload_id"),
    )
    op.create_index("ix_uploads_upload_id", "uploads", ["upload_id"])
    op.create_index("ix_uploads_status", "uploads", ["status"])
    op.create_table(
        "jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("upload_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("error_reason", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["upload_id"], ["uploads.id"]),
        sa.UniqueConstraint("job_id"),
    )
    op.create_index("ix_jobs_job_id", "jobs", ["job_id"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("settings")
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_index("ix_jobs_job_id", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_uploads_status", table_name="uploads")
    op.drop_index("ix_uploads_upload_id", table_name="uploads")
    op.drop_table("uploads")
```

- [ ] **Step 7: Implement `InMemoryStore` upload/job/settings methods**

In `dojo-core/src/dojo/adapters/memory.py`: extend imports with `Job`, `Upload`; add state and methods. Add to `__init__`:
```python
        self._uploads: list[Upload] = []
        self._jobs: list[Job] = []
        self._settings: dict[str, object] = {}
        self._next_upload_id = 1
        self._next_job_id = 1
```
Append methods:
```python
    def create(self, upload: Upload) -> Upload:
        created = replace(upload, id=self._next_upload_id)
        self._next_upload_id += 1
        self._uploads.append(created)
        return created

    def get(self, upload_id: str) -> Upload | None:
        return next((u for u in self._uploads if u.upload_id == upload_id), None)

    def get_by_pk(self, upload_pk: int) -> Upload | None:
        return next((u for u in self._uploads if u.id == upload_pk), None)

    def update(self, upload: Upload) -> Upload:
        for i, existing in enumerate(self._uploads):
            if existing.id == upload.id:
                self._uploads[i] = upload
                return upload
        raise ValueError(f"upload {upload.id} not found")

    def list_active(self) -> list[Upload]:
        return [u for u in self._uploads if u.status in ("receiving", "queued")]

    def list_stale(self, cutoff: datetime) -> list[Upload]:
        return [
            u
            for u in self._uploads
            if u.status in ("receiving", "queued") and u.updated_at < cutoff
        ]

    def create(self, job: Job) -> Job:
        created = replace(job, id=self._next_job_id)
        self._next_job_id += 1
        self._jobs.append(created)
        return created

    def get(self, job_id: str) -> Job | None:
        return next((j for j in self._jobs if j.job_id == job_id), None)

    def get_by_upload(self, upload_pk: int) -> Job | None:
        return next((j for j in self._jobs if j.upload_id == upload_pk), None)

    def update(self, job: Job) -> Job:
        for i, existing in enumerate(self._jobs):
            if existing.id == job.id:
                self._jobs[i] = job
                return job
        raise ValueError(f"job {job.id} not found")

    def claim_next(self, claimed_at: datetime) -> Job | None:
        for i, job in enumerate(self._jobs):
            if job.status == "queued":
                claimed = replace(job, status="processing", claimed_at=claimed_at)
                self._jobs[i] = claimed
                return claimed
        return None

    def get(self, key: str) -> object | None:
        return self._settings.get(key)

    def set(self, key: str, value: object, *, updated_at: datetime) -> None:
        self._settings[key] = value
```

- [ ] **Step 8: Implement `PostgresStore` upload/job/settings methods**

In `dojo-core/src/dojo/adapters/db.py`: extend the `from dojo.model import` block with `Job`, `Upload`. Add rows after `ConsentAcceptanceRow`:
```python
class UploadRow(Base):
    __tablename__ = "uploads"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    upload_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    package_id: Mapped[int] = mapped_column(ForeignKey("packages.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    declared_size_bytes: Mapped[int] = mapped_column(nullable=False)
    received_ranges: Mapped[list] = mapped_column(JSON, nullable=False)
    received_bytes: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class JobRow(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    error_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SettingRow(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[object] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

Add `Objectionable` mapping helpers and methods on `PostgresStore` (after `record_acceptance`):
```python
    def create(self, upload: Upload) -> Upload:
        with self._session() as session:
            row = UploadRow(
                upload_id=upload.upload_id,
                package_id=upload.package_id,
                filename=upload.filename,
                content_type=upload.content_type,
                declared_size_bytes=upload.declared_size_bytes,
                received_ranges=upload.received_ranges,
                received_bytes=upload.received_bytes,
                status=upload.status,
                error_reason=upload.error_reason,
                created_at=upload.created_at,
                updated_at=upload.updated_at,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._upload_from_row(row)

    def get(self, upload_id: str) -> Upload | None:
        with self._session() as session:
            row = session.scalar(select(UploadRow).where(UploadRow.upload_id == upload_id))
            return self._upload_from_row(row) if row is not None else None

    def get_by_pk(self, upload_pk: int) -> Upload | None:
        with self._session() as session:
            row = session.get(UploadRow, upload_pk)
            return self._upload_from_row(row) if row is not None else None

    def update(self, upload: Upload) -> Upload:
        with self._session() as session:
            row = session.get(UploadRow, upload.id)
            if row is None:
                raise ValueError(f"upload {upload.id} not found")
            row.upload_id = upload.upload_id
            row.package_id = upload.package_id
            row.filename = upload.filename
            row.content_type = upload.content_type
            row.declared_size_bytes = upload.declared_size_bytes
            row.received_ranges = upload.received_ranges
            row.received_bytes = upload.received_bytes
            row.status = upload.status
            row.error_reason = upload.error_reason
            row.created_at = upload.created_at
            row.updated_at = upload.updated_at
            session.commit()
            return upload

    def list_active(self) -> list[Upload]:
        with self._session() as session:
            rows = session.scalars(
                select(UploadRow).where(UploadRow.status.in_(["receiving", "queued"]))
            ).all()
            return [self._upload_from_row(r) for r in rows]

    def list_stale(self, cutoff: datetime) -> list[Upload]:
        with self._session() as session:
            rows = session.scalars(
                select(UploadRow).where(
                    UploadRow.status.in_(["receiving", "queued"]),
                    UploadRow.updated_at < cutoff,
                )
            ).all()
            return [self._upload_from_row(r) for r in rows]

    def create(self, job: Job) -> Job:
        with self._session() as session:
            row = JobRow(
                job_id=job.job_id,
                upload_id=job.upload_id,
                kind=job.kind,
                status=job.status,
                payload=job.payload,
                error_reason=job.error_reason,
                created_at=job.created_at,
                claimed_at=job.claimed_at,
                finished_at=job.finished_at,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._job_from_row(row)

    def get(self, job_id: str) -> Job | None:
        with self._session() as session:
            row = session.scalar(select(JobRow).where(JobRow.job_id == job_id))
            return self._job_from_row(row) if row is not None else None

    def get_by_upload(self, upload_pk: int) -> Job | None:
        with self._session() as session:
            row = session.scalar(select(JobRow).where(JobRow.upload_id == upload_pk))
            return self._job_from_row(row) if row is not None else None

    def update(self, job: Job) -> Job:
        with self._session() as session:
            row = session.get(JobRow, job.id)
            if row is None:
                raise ValueError(f"job {job.id} not found")
            row.job_id = job.job_id
            row.upload_id = job.upload_id
            row.kind = job.kind
            row.status = job.status
            row.payload = job.payload
            row.error_reason = job.error_reason
            row.created_at = job.created_at
            row.claimed_at = job.claimed_at
            row.finished_at = job.finished_at
            session.commit()
            return job

    def claim_next(self, claimed_at: datetime) -> Job | None:
        with self._session() as session:
            row = session.scalar(
                select(JobRow)
                .where(JobRow.status == "queued")
                .order_by(JobRow.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if row is None:
                return None
            row.status = "processing"
            row.claimed_at = claimed_at
            session.commit()
            return self._job_from_row(row)

    def get(self, key: str) -> object | None:
        with self._session() as session:
            row = session.get(SettingRow, key)
            return row.value if row is not None else None

    def set(self, key: str, value: object, *, updated_at: datetime) -> None:
        with self._session() as session:
            stmt = pg_insert(SettingRow).values(key=key, value=value, updated_at=updated_at)
            stmt = stmt.on_conflict_do_update(
                index_elements=[SettingRow.key],
                set_={"value": stmt.excluded.value, "updated_at": stmt.excluded.updated_at},
            )
            session.execute(stmt)
            session.commit()

    @staticmethod
    def _upload_from_row(row: UploadRow) -> Upload:
        return Upload(
            id=row.id,
            upload_id=row.upload_id,
            package_id=row.package_id,
            filename=row.filename,
            content_type=row.content_type,
            declared_size_bytes=row.declared_size_bytes,
            received_ranges=row.received_ranges,
            received_bytes=row.received_bytes,
            status=row.status,
            error_reason=row.error_reason,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _job_from_row(row: JobRow) -> Job:
        return Job(
            id=row.id,
            job_id=row.job_id,
            upload_id=row.upload_id,
            kind=row.kind,
            status=row.status,
            payload=row.payload,
            error_reason=row.error_reason,
            created_at=row.created_at,
            claimed_at=row.claimed_at,
            finished_at=row.finished_at,
        )
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_store_upload.py dojo-core/tests/test_store_jobs.py dojo-core/tests/test_store_settings.py dojo-core/tests/test_db_adapter.py -v`
Expected: PASS. Note: the shared Postgres session fixture truncates all tables before each `pg_store` test — add `uploads, jobs, settings` to the TRUNCATE list in `dojo-core/tests/conftest.py`:
```python
            text("TRUNCATE TABLE consent_acceptances, consent_policies, pairing_codes, "
                 "clients, audit_events, packages, uploads, jobs, settings RESTART IDENTITY")
```

- [ ] **Step 10: Export new symbols, lint, typecheck, full suite, commit**

In `dojo-core/src/dojo/__init__.py`, add the new models and exceptions to imports and `__all__`: `MediaEntry`, `Upload`, `UploadStatus`, `Job`, `ProcessedMedia`, `UploadLimits`, and `UploadNotFound`, `UploadNotReceiving`, `UploadChecksumMismatch`, `UploadTooLarge`, `PackageLimitExceeded`, `UploadIncomplete`, `UploadConflict`, `UploadInvalidFilename`, `JobNotFound`, `MediaValidationError`.

Run: `uv run --project dojo-core ruff check dojo-core/src dojo-core/tests; uv run --project dojo-core mypy dojo-core/src/dojo`
Expected: no findings
Run: `uv run --project dojo-core pytest dojo-core/tests -v`
Expected: all pass

```bash
git add dojo-core/src/dojo/model.py dojo-core/src/dojo/ports.py dojo-core/src/dojo/exceptions.py dojo-core/migrations/versions/0005_media_upload.py dojo-core/src/dojo/adapters/memory.py dojo-core/src/dojo/adapters/db.py dojo-core/src/dojo/__init__.py dojo-core/tests/test_store_upload.py dojo-core/tests/test_store_jobs.py dojo-core/tests/test_store_settings.py dojo-core/tests/test_db_adapter.py dojo-core/tests/conftest.py
git commit -m "feat(dojo-core): upload, job, and settings storage (#7)"
```

---

### Task 2: Seam — upload lifecycle (start, append, status, complete, abort, limits)

**Files:**
- Modify: `dojo-core/src/dojo/publishing.py`
- Create: `dojo-core/tests/test_upload.py`

**Interfaces:**
- Consumes: `UploadStore`/`JobStore`/`SettingsStore`/`Clock` from Task 1; models `Upload`, `UploadStatus`, `Job`, `UploadLimits`, `AuditEvent`; exceptions from Task 1; existing `get_or_create_active_package`.
- Produces:
  - `DojoPublishing.__init__` gains keyword args `uploads`, `jobs`, `settings`, `media` (each defaulting to `None`; `uploads`/`jobs`/`settings` fall back to the `packages` store, `media` resolves lazily in `process_job`).
  - `start_upload(filename, content_type, declared_size_bytes, requester) -> UploadStatus`
  - `append_upload_range(upload_id, offset, length, checksum_sha256, data) -> UploadStatus`
  - `get_upload_status(upload_id) -> UploadStatus`
  - `list_active_uploads() -> list[UploadStatus]`
  - `complete_upload(upload_id, requester) -> UploadStatus`
  - `abort_upload(upload_id, requester) -> None`
  - `get_upload_limits() -> UploadLimits`
  - module function `merge_ranges(existing, new_start, new_end) -> list[list[int]]`

- [ ] **Step 1: Write the failing tests**

Create `dojo-core/tests/test_upload.py`:
```python
from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest
from dojo import (
    ActivePackageExists,
    DojoPublishing,
    InMemoryStore,
    PackageLimitExceeded,
    UploadChecksumMismatch,
    UploadConflict,
    UploadIncomplete,
    UploadInvalidFilename,
    UploadNotFound,
    UploadNotReceiving,
    UploadTooLarge,
)
from dojo.adapters.stubs import StubMetaPublisher, StubNotifier, StubSignedUrlStore
from dojo.testing import FIXED_AT, FakeClock


def make_seam(tmp_path, **overrides):
    store = InMemoryStore()
    return (
        store,
        DojoPublishing(
            packages=store,
            audit=store,
            uploads=store,
            jobs=store,
            settings=store,
            media_root=tmp_path,
            clock=FakeClock(),
            meta=StubMetaPublisher(),
            notifier=StubNotifier(),
            signed_urls=StubSignedUrlStore(),
            **overrides,
        ),
    )


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_start_upload_creates_staging_and_audits(tmp_path):
    store, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    status = seam.start_upload("pic.jpg", "image/jpeg", 100, requester="7")
    assert status.declared_size_bytes == 100
    assert status.received_bytes == 0
    assert status.status == "receiving"
    staging = tmp_path / "tmp" / status.upload_id
    assert staging.is_dir()
    events = seam.list_audit()
    assert events[0].action == "upload.started"
    assert events[0].actor == "7"


def test_start_upload_rejects_unsafe_filename(tmp_path):
    _, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    for bad in ("a/b.jpg", "a\\b.jpg", "a\x00b.jpg", "a\x01b.jpg", ""):
        with pytest.raises(UploadInvalidFilename):
            seam.start_upload(bad, "image/jpeg", 100)


def test_start_upload_rejects_file_over_limit(tmp_path):
    _, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    with pytest.raises(UploadTooLarge):
        seam.start_upload("big.mp4", "video/mp4", 2 * 1024**3 + 1)


def test_start_upload_rejects_package_over_limit(tmp_path):
    store, seam = make_seam(tmp_path)
    store.set("upload.max_package_bytes", 150, updated_at=FIXED_AT)
    seam.ensure_active_package()
    seam.start_upload("a.jpg", "image/jpeg", 100)
    with pytest.raises(PackageLimitExceeded):
        seam.start_upload("b.jpg", "image/jpeg", 100)


def test_append_range_writes_and_merges(tmp_path):
    _, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    status = seam.start_upload("pic.jpg", "image/jpeg", 100)
    body = b"x" * 50
    progress = seam.append_upload_range(status.upload_id, 0, 50, sha(body), body)
    assert progress.received_bytes == 50
    staged = tmp_path / "tmp" / status.upload_id / "original"
    assert staged.read_bytes() == body
    progress2 = seam.append_upload_range(status.upload_id, 50, 50, sha(b"y" * 50), b"y" * 50)
    assert progress2.received_bytes == 100
    assert progress2.received_ranges == [[0, 100]]
    assert staged.read_bytes() == body + b"y" * 50


def test_append_range_duplicate_is_idempotent(tmp_path):
    _, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    status = seam.start_upload("pic.jpg", "image/jpeg", 100)
    body = b"x" * 50
    seam.append_upload_range(status.upload_id, 0, 50, sha(body), body)
    again = seam.append_upload_range(status.upload_id, 0, 50, sha(body), body)
    assert again.received_bytes == 50
    assert again.received_ranges == [[0, 50]]


def test_append_range_checksum_mismatch_rejected(tmp_path):
    _, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    status = seam.start_upload("pic.jpg", "image/jpeg", 100)
    with pytest.raises(UploadChecksumMismatch):
        seam.append_upload_range(status.upload_id, 0, 50, sha(b"wrong"), b"actual")


def test_append_range_out_of_declared_rejected(tmp_path):
    _, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    status = seam.start_upload("pic.jpg", "image/jpeg", 100)
    body = b"x" * 10
    with pytest.raises(UploadConflict):
        seam.append_upload_range(status.upload_id, 95, 10, sha(body), body)


def test_append_range_unknown_upload(tmp_path):
    _, seam = make_seam(tmp_path)
    with pytest.raises(UploadNotFound):
        seam.append_upload_range("nope", 0, 1, "abc", b"x")


def test_append_after_complete_rejected(tmp_path):
    _, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    status = seam.start_upload("pic.jpg", "image/jpeg", 100)
    seam.append_upload_range(status.upload_id, 0, 100, sha(b"x" * 100), b"x" * 100)
    seam.complete_upload(status.upload_id)
    with pytest.raises(UploadNotReceiving):
        seam.append_upload_range(status.upload_id, 0, 1, sha(b"x"), b"x")


def test_complete_upload_requires_full_coverage(tmp_path):
    _, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    status = seam.start_upload("pic.jpg", "image/jpeg", 100)
    seam.append_upload_range(status.upload_id, 0, 50, sha(b"x" * 50), b"x" * 50)
    with pytest.raises(UploadIncomplete):
        seam.complete_upload(status.upload_id)


def test_complete_upload_creates_job_and_audits(tmp_path):
    store, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    status = seam.start_upload("pic.jpg", "image/jpeg", 100)
    seam.append_upload_range(status.upload_id, 0, 100, sha(b"x" * 100), b"x" * 100)
    result = seam.complete_upload(status.upload_id)
    assert result.status == "queued"
    job = store.get_by_upload(store.get(status.upload_id).id)
    assert job is not None
    assert job.kind == "media.process"
    assert job.status == "queued"
    actions = [e.action for e in seam.list_audit()]
    assert actions[0] == "upload.completed"


def test_complete_upload_exactly_once(tmp_path):
    _, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    status = seam.start_upload("pic.jpg", "image/jpeg", 100)
    seam.append_upload_range(status.upload_id, 0, 100, sha(b"x" * 100), b"x" * 100)
    seam.complete_upload(status.upload_id)
    with pytest.raises(UploadConflict):
        seam.complete_upload(status.upload_id)


def test_get_upload_status(tmp_path):
    _, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    status = seam.start_upload("pic.jpg", "image/jpeg", 100)
    fetched = seam.get_upload_status(status.upload_id)
    assert fetched.upload_id == status.upload_id
    with pytest.raises(UploadNotFound):
        seam.get_upload_status("missing")


def test_abort_upload_cleans_staging(tmp_path):
    _, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    status = seam.start_upload("pic.jpg", "image/jpeg", 100)
    staging = tmp_path / "tmp" / status.upload_id
    assert staging.is_dir()
    seam.abort_upload(status.upload_id, requester="7")
    assert not staging.exists()
    assert seam.get_upload_status(status.upload_id).status == "aborted"
    actions = [e.action for e in seam.list_audit()]
    assert actions[0] == "upload.aborted"
    assert seam.list_audit()[0].actor == "7"


def test_get_upload_limits_defaults_and_settings(tmp_path):
    store, seam = make_seam(tmp_path)
    limits = seam.get_upload_limits()
    assert limits.max_file_bytes == 2 * 1024**3
    assert limits.max_package_bytes == 20 * 1024**3
    store.set("upload.max_file_bytes", 42, updated_at=FIXED_AT)
    assert seam.get_upload_limits().max_file_bytes == 42
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_upload.py -v`
Expected: FAIL — methods missing on `DojoPublishing`.

- [ ] **Step 3: Implement the seam upload lifecycle**

In `dojo-core/src/dojo/publishing.py`:
- extend imports:
```python
import hashlib
import uuid
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from dojo.adapters.clock import ISTANBUL, SystemClock
from dojo.adapters.stubs import StubMetaPublisher, StubNotifier, StubSignedUrlStore
from dojo.exceptions import (
    ActivePackageExists,
    MediaValidationError,
    NoActivePackage,
    PackageLimitExceeded,
    UploadChecksumMismatch,
    UploadConflict,
    UploadIncomplete,
    UploadInvalidFilename,
    UploadNotFound,
    UploadNotReceiving,
    UploadTooLarge,
)
from dojo.model import (
    PACKAGE_FOLDER_FORMAT,
    AuditEvent,
    Manifest,
    MediaEntry,
    Package,
    ProcessedMedia,
    Upload,
    UploadLimits,
    UploadStatus,
)
from dojo.ports import (
    AuditStore,
    Clock,
    JobStore,
    MediaProcessor,
    MetaPublisher,
    Notifier,
    PackageStore,
    SettingsStore,
    SignedUrlStore,
    UploadStore,
)

DEFAULT_MAX_FILE_BYTES = 2 * 1024**3
DEFAULT_MAX_PACKAGE_BYTES = 20 * 1024**3
STALE_TTL = timedelta(hours=24)
```
- in `__init__`, add params and fields:
```python
        uploads: UploadStore | None = None,
        jobs: JobStore | None = None,
        settings: SettingsStore | None = None,
        media: MediaProcessor | None = None,
```
```python
        self._uploads: UploadStore = uploads if uploads is not None else packages
        self._jobs: JobStore = jobs if jobs is not None else packages
        self._settings: SettingsStore = settings if settings is not None else packages
        self._media = media
```
- add a module-level range helper:
```python
def merge_ranges(existing: list[list[int]], new_start: int, new_end: int) -> list[list[int]]:
    """Merge [new_start, new_end) into a sorted list of disjoint [start, end) ranges."""
    merged: list[list[int]] = []
    for start, end in existing:
        if end < new_start or new_end < start:
            merged.append([start, end])
        else:
            new_start = min(new_start, start)
            new_end = max(new_end, end)
    merged.append([new_start, new_end])
    merged.sort()
    return merged
```
- add the public methods (place after `get_active_package`):
```python
    def get_upload_limits(self) -> UploadLimits:
        max_file = self._settings.get("upload.max_file_bytes") or DEFAULT_MAX_FILE_BYTES
        max_package = self._settings.get("upload.max_package_bytes") or DEFAULT_MAX_PACKAGE_BYTES
        return UploadLimits(
            max_file_bytes=int(max_file), max_package_bytes=int(max_package)
        )

    def start_upload(
        self,
        filename: str,
        content_type: str,
        declared_size_bytes: int,
        requester: str | None = None,
    ) -> UploadStatus:
        if not filename or any(c in filename for c in ("/", "\\")) or any(
            ord(c) < 32 for c in filename
        ):
            raise UploadInvalidFilename(f"unsafe filename: {filename!r}")
        limits = self.get_upload_limits()
        if declared_size_bytes > limits.max_file_bytes:
            raise UploadTooLarge(
                f"file {declared_size_bytes} bytes exceeds limit {limits.max_file_bytes}"
            )
        package = self.get_or_create_active_package(requester=requester)
        used = self._package_used_bytes(package)
        in_flight = sum(
            u.declared_size_bytes for u in self._uploads.list_active()
            if u.package_id == package.id
        )
        if used + in_flight + declared_size_bytes > limits.max_package_bytes:
            raise PackageLimitExceeded(
                f"package limit {limits.max_package_bytes} would be exceeded"
            )
        now = self._clock.now()
        upload_id = uuid.uuid4().hex
        staging = self.media_root / "tmp" / upload_id
        staging.mkdir(parents=True, exist_ok=True)
        upload = self._uploads.create(
            Upload(
                id=0,
                upload_id=upload_id,
                package_id=package.id,
                filename=filename,
                content_type=content_type,
                declared_size_bytes=declared_size_bytes,
                received_ranges=[],
                received_bytes=0,
                status="receiving",
                created_at=now,
                updated_at=now,
            )
        )
        self._audit.append(
            AuditEvent(
                action="upload.started",
                actor=requester or "system",
                occurred_at=now,
                details={
                    "upload_id": upload_id,
                    "filename": filename,
                    "content_type": content_type,
                    "declared_size_bytes": declared_size_bytes,
                },
            )
        )
        return self._status(upload)

    def append_upload_range(
        self,
        upload_id: str,
        offset: int,
        length: int,
        checksum_sha256: str,
        data: bytes,
    ) -> UploadStatus:
        upload = self._uploads.get(upload_id)
        if upload is None:
            raise UploadNotFound(f"upload {upload_id} not found")
        if upload.status != "receiving":
            raise UploadNotReceiving(f"upload {upload_id} is {upload.status}")
        if offset < 0 or offset + length > upload.declared_size_bytes:
            raise UploadConflict(
                f"range [{offset}, {offset + length}) exceeds declared size"
            )
        actual = hashlib.sha256(data).hexdigest()
        if actual != checksum_sha256:
            raise UploadChecksumMismatch(
                f"checksum mismatch for upload {upload_id}: got {actual[:8]}"
            )
        staged = self.media_root / "tmp" / upload_id / "original"
        staged.touch()
        with staged.open("r+b") as fh:
            fh.seek(offset)
            fh.write(data)
        now = self._clock.now()
        ranges = merge_ranges(upload.received_ranges, offset, offset + length)
        received = sum(end - start for start, end in ranges)
        updated = self._uploads.update(
            replace(upload, received_ranges=ranges, received_bytes=received, updated_at=now)
        )
        return self._status(updated)

    def get_upload_status(self, upload_id: str) -> UploadStatus:
        upload = self._uploads.get(upload_id)
        if upload is None:
            raise UploadNotFound(f"upload {upload_id} not found")
        return self._status(upload)

    def list_active_uploads(self) -> list[UploadStatus]:
        return [self._status(u) for u in self._uploads.list_active()]

    def complete_upload(
        self, upload_id: str, requester: str | None = None
    ) -> UploadStatus:
        upload = self._uploads.get(upload_id)
        if upload is None:
            raise UploadNotFound(f"upload {upload_id} not found")
        if upload.status != "receiving":
            raise UploadConflict(f"upload {upload_id} is {upload.status}")
        if upload.received_bytes < upload.declared_size_bytes:
            raise UploadIncomplete(
                f"upload {upload_id} has {upload.received_bytes} of "
                f"{upload.declared_size_bytes} bytes"
            )
        now = self._clock.now()
        queued = self._uploads.update(
            replace(upload, status="queued", updated_at=now)
        )
        self._jobs.create(
            Job(
                id=0,
                job_id=uuid.uuid4().hex,
                upload_id=queued.id,
                kind="media.process",
                status="queued",
                payload={"upload_id": upload_id},
                created_at=now,
            )
        )
        self._audit.append(
            AuditEvent(
                action="upload.completed",
                actor=requester or "system",
                occurred_at=now,
                details={"upload_id": upload_id, "filename": upload.filename},
            )
        )
        return self._status(queued)

    def abort_upload(self, upload_id: str, requester: str | None = None) -> None:
        upload = self._uploads.get(upload_id)
        if upload is None:
            raise UploadNotFound(f"upload {upload_id} not found")
        if upload.status == "finalized":
            raise UploadConflict(f"upload {upload_id} is finalized")
        now = self._clock.now()
        self._uploads.update(replace(upload, status="aborted", updated_at=now))
        staging = self.media_root / "tmp" / upload_id
        import shutil

        shutil.rmtree(staging, ignore_errors=True)
        self._audit.append(
            AuditEvent(
                action="upload.aborted",
                actor=requester or "system",
                occurred_at=now,
                details={"upload_id": upload_id},
            )
        )

    def _package_used_bytes(self, package: Package) -> int:
        manifest_path = self.media_root / package.folder_name / "manifest.json"
        if not manifest_path.is_file():
            return 0
        import json

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return sum(int(entry.get("size_bytes", 0)) for entry in manifest.get("media", []))

    @staticmethod
    def _status(upload: Upload) -> UploadStatus:
        return UploadStatus(
            upload_id=upload.upload_id,
            received_bytes=upload.received_bytes,
            declared_size_bytes=upload.declared_size_bytes,
            status=upload.status,
            received_ranges=upload.received_ranges,
        )
```

Note: `test_start_upload_rejects_package_over_limit` passes a no-op `settings_overrides={}` kwarg — remove that from the test; the seam falls back to `packages` store which is the same `InMemoryStore` used via `seam.settings`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_upload.py -v`
Expected: PASS (walk the file and fix any test/implementation mismatches inline).

- [ ] **Step 5: Update the `__init__` import of `Job`**

`dojo-core/src/dojo/publishing.py` imports `Job` from `dojo.model` (used in `complete_upload`). Add `Job` to the `from dojo.model import` list if not present.

- [ ] **Step 6: Lint, typecheck, full suite, commit**

Run: `uv run --project dojo-core ruff check dojo-core/src dojo-core/tests; uv run --project dojo-core mypy dojo-core/src/dojo`
Expected: no findings
Run: `uv run --project dojo-core pytest dojo-core/tests -v`
Expected: all pass

```bash
git add dojo-core/src/dojo/publishing.py dojo-core/tests/test_upload.py
git commit -m "feat(dojo-core): resumable upload lifecycle in the publishing seam (#7)"
```

---

### Task 3: Seam — media processing, finalize, sweep, StubMediaProcessor

**Files:**
- Modify: `dojo-core/src/dojo/publishing.py`
- Modify: `dojo-core/src/dojo/adapters/stubs.py`
- Modify: `dojo-core/tests/test_upload.py`

**Interfaces:**
- Consumes: `JobStore.claim_next` (Task 1), `MediaProcessor` protocol (Task 1), `MediaEntry`/`ProcessedMedia` (Task 1), `MediaValidationError` (Task 1).
- Produces:
  - `DojoPublishing.claim_next_job() -> Job | None`
  - `DojoPublishing.process_job(job_id) -> None`
  - `DojoPublishing.finalize_media(job_id, processed) -> None`
  - `DojoPublishing.sweep_stale_uploads(ttl=STALE_TTL) -> int`
  - `StubMediaProcessor` in `dojo/adapters/stubs.py`.

- [ ] **Step 1: Add `StubMediaProcessor` to `dojo/adapters/stubs.py`**

```python
class StubMediaProcessor:
    def __init__(self, *, content_type: str = "image/jpeg", fail_reason: str | None = None) -> None:
        self.calls: list[tuple[object, Path]] = []
        self.content_type = content_type
        self.fail_reason = fail_reason

    def process(self, upload: object, original_path: Path, work_dir: Path) -> object:
        from dojo.model import ProcessedMedia

        self.calls.append((upload, original_path))
        if self.fail_reason is not None:
            from dojo.exceptions import MediaValidationError

            raise MediaValidationError(self.fail_reason)
        processed = work_dir / "processed.jpg"
        shutil.copyfile(original_path, processed)
        return ProcessedMedia(
            original_path=original_path,
            processed_path=processed,
            content_type=self.content_type,
            size_bytes=processed.stat().st_size,
            dimensions=(100, 100),
        )
```
Add `import shutil` to the top of the file.

- [ ] **Step 2: Write the failing tests**

Append to `dojo-core/tests/test_upload.py`:
```python
from dojo.adapters.stubs import StubMediaProcessor


def complete(tmp_path, seam, *, content_type="image/jpeg", body=b"x" * 100):
    seam.ensure_active_package()
    status = seam.start_upload("pic.jpg", content_type, len(body))
    seam.append_upload_range(status.upload_id, 0, len(body), sha(body), body)
    seam.complete_upload(status.upload_id)
    return status


def test_process_job_finalizes_into_package(tmp_path):
    store, seam = make_seam(tmp_path)
    seam._media = StubMediaProcessor()
    status = complete(tmp_path, seam)
    claimed = seam.claim_next_job()
    assert claimed is not None
    seam.process_job(claimed.job_id)

    package = seam.get_active_package()
    media_dir = tmp_path / package.folder_name / "media"
    entries = list(media_dir.iterdir())
    assert len(entries) == 1
    media_id = entries[0].name
    assert (media_dir / media_id / "original").is_file()
    assert (media_dir / media_id / "processed.jpg").is_file()

    manifest = json.loads(
        (tmp_path / package.folder_name / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["order"] == [media_id]
    assert len(manifest["media"]) == 1
    entry = manifest["media"][0]
    assert entry["media_id"] == media_id
    assert entry["status"] == "finalized"
    assert entry["processed"]["content_type"] == "image/jpeg"

    assert seam.get_upload_status(status.upload_id).status == "finalized"
    assert store.get_by_upload(store.get(status.upload_id).id).status == "done"
    assert not (tmp_path / "tmp" / status.upload_id).exists()
    actions = [e.action for e in seam.list_audit()]
    assert actions[0] == "media.finalized"


def test_process_job_validation_failure_marks_failed_and_cleans(tmp_path):
    store, seam = make_seam(tmp_path)
    status = complete(tmp_path, seam)
    claimed = seam.claim_next_job()
    assert claimed is not None
    seam._media = StubMediaProcessor(fail_reason="unsupported codec: not-h264")

    seam.process_job(claimed.job_id)

    assert seam.get_upload_status(status.upload_id).status == "failed"
    assert seam.get_upload_status(status.upload_id).error_reason == "unsupported codec: not-h264"
    failed_job = store.get_by_upload(store.get(status.upload_id).id)
    assert failed_job.status == "failed"
    assert not (tmp_path / "tmp" / status.upload_id).exists()
    actions = [e.action for e in seam.list_audit()]
    assert actions[0] == "upload.rejected"
    assert not (tmp_path / seam.get_active_package().folder_name / "media").exists()


def test_claim_next_job_returns_one_job(tmp_path):
    store, seam = make_seam(tmp_path)
    status = complete(tmp_path, seam)
    claimed = seam.claim_next_job()
    assert claimed is not None
    assert claimed.kind == "media.process"
    assert seam.claim_next_job() is None


def test_process_job_missing_upload_marks_failed(tmp_path):
    store, seam = make_seam(tmp_path)
    status = complete(tmp_path, seam)
    claimed = seam.claim_next_job()
    assert claimed is not None
    seam._media = StubMediaProcessor(fail_reason="original missing")
    (tmp_path / "tmp" / status.upload_id / "original").unlink()
    seam.process_job(claimed.job_id)
    assert seam.get_upload_status(status.upload_id).status == "failed"


def test_sweep_stale_uploads_cleans_expired(tmp_path):
    store, seam = make_seam(tmp_path)
    status = complete(tmp_path, seam)
    from datetime import timedelta

    upload = store.get(status.upload_id)
    store.update(replace(upload, status="receiving", updated_at=FIXED_AT - timedelta(hours=25)))
    swept = seam.sweep_stale_uploads(ttl=timedelta(hours=24))
    assert swept == 1
    assert seam.get_upload_status(status.upload_id).status == "aborted"
    assert not (tmp_path / "tmp" / status.upload_id).exists()
    actions = [e.action for e in seam.list_audit()]
    assert actions[0] == "upload.expired"
```

Also add `import json` to the top of `test_upload.py` (already imported in `test_publishing.py`; ensure `test_upload.py` has it).

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_upload.py -v`
Expected: FAIL — `claim_next_job`/`process_job`/`finalize_media`/`sweep_stale_uploads` missing, `seam._media` attribute error.

- [ ] **Step 4: Implement processing, finalize, sweep in the seam**

Append to `dojo-core/src/dojo/publishing.py`:
```python
    def claim_next_job(self) -> Job | None:
        return self._jobs.claim_next(self._clock.now())

    def process_job(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFound(f"job {job_id} not found")
        if job.status != "processing":
            raise UploadConflict(f"job {job_id} is {job.status}")
        upload = self._uploads.get_by_pk(job.upload_id)
        if upload is None:
            self._fail_job(job, "upload missing")
            return
        now = self._clock.now()
        self._uploads.update(replace(upload, status="processing", updated_at=now))
        original = self.media_root / "tmp" / upload.upload_id / "original"
        if not original.is_file():
            self._fail_job(job, "staged original missing")
            return
        try:
            processor = self._media
            if processor is None:
                from dojo.adapters.media import PillowFFmpegProcessor

                processor = PillowFFmpegProcessor()
            processed = processor.process(upload, original, self.media_root / "tmp" / upload.upload_id)
        except MediaValidationError as exc:
            self._fail_job(job, str(exc))
            return
        self.finalize_media(job.job_id, processed)

    def finalize_media(self, job_id: str, processed: ProcessedMedia) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFound(f"job {job_id} not found")
        upload = self._uploads.get_by_pk(job.upload_id)
        if upload is None or upload.status != "processing":
            raise UploadConflict(f"upload for job {job_id} is not processing")
        import shutil

        required = upload.declared_size_bytes + processed.size_bytes
        free = shutil.disk_usage(self.media_root).free
        if free < required:
            self._fail_job(job, f"insufficient disk space: {free} free, {required} needed")
            return
        package = self._packages.get_active()
        if package is None:
            self._fail_job(job, "no active package")
            return
        now = self._clock.now()
        media_id = uuid.uuid4().hex
        media_dir = self.media_root / package.folder_name / "media" / media_id
        media_dir.mkdir(parents=True, exist_ok=True)
        original_ext = Path(upload.filename).suffix or _ext_for(upload.content_type)
        processed_ext = _ext_for(processed.content_type)
        original_dst = media_dir / f"original{original_ext}"
        processed_dst = media_dir / f"processed{processed_ext}"
        shutil.move(str(processed.original_path), str(original_dst))
        shutil.move(str(processed.processed_path), str(processed_dst))

        entry = MediaEntry(
            media_id=media_id,
            filename=upload.filename,
            content_type=upload.content_type,
            size_bytes=upload.declared_size_bytes,
            uploaded_at=upload.created_at,
            status="finalized",
            processed={
                "path": f"media/{media_id}/processed{processed_ext}",
                "content_type": processed.content_type,
                "size_bytes": processed.size_bytes,
            },
        ).to_dict()

        manifest_path = self.media_root / package.folder_name / "manifest.json"
        import json

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.setdefault("media", []).append(entry)
        manifest.setdefault("order", []).append(media_id)
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        self._uploads.update(replace(upload, status="finalized", updated_at=now))
        self._jobs.update(
            replace(job, status="done", finished_at=now, error_reason=None)
        )
        staging = self.media_root / "tmp" / upload.upload_id
        shutil.rmtree(staging, ignore_errors=True)
        self._audit.append(
            AuditEvent(
                action="media.finalized",
                actor="worker",
                occurred_at=now,
                details={
                    "media_id": media_id,
                    "upload_id": upload.upload_id,
                    "filename": upload.filename,
                    "package": package.folder_name,
                },
            )
        )

    def sweep_stale_uploads(self, ttl: timedelta = STALE_TTL) -> int:
        cutoff = self._clock.now() - ttl
        stale = self._uploads.list_stale(cutoff)
        for upload in stale:
            now = self._clock.now()
            self._uploads.update(replace(upload, status="aborted", updated_at=now))
            import shutil

            shutil.rmtree(self.media_root / "tmp" / upload.upload_id, ignore_errors=True)
            self._audit.append(
                AuditEvent(
                    action="upload.expired",
                    actor="worker",
                    occurred_at=now,
                    details={"upload_id": upload.upload_id},
                )
            )
        return len(stale)

    def _fail_job(self, job: Job, reason: str) -> None:
        upload = self._uploads.get_by_pk(job.upload_id)
        now = self._clock.now()
        if upload is not None:
            self._uploads.update(
                replace(upload, status="failed", error_reason=reason, updated_at=now)
            )
        self._jobs.update(
            replace(job, status="failed", error_reason=reason, finished_at=now)
        )
        import shutil

        if upload is not None:
            shutil.rmtree(self.media_root / "tmp" / upload.upload_id, ignore_errors=True)
        self._audit.append(
            AuditEvent(
                action="upload.rejected",
                actor="worker",
                occurred_at=now,
                details={"job_id": job.job_id, "reason": reason},
            )
        )
```

Add module-level helper near `merge_ranges`:
```python
def _ext_for(content_type: str) -> str:
    mapping = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/heic": ".heic",
        "image/heif": ".heif",
        "video/mp4": ".mp4",
        "video/quicktime": ".mov",
    }
    return mapping.get(content_type, "")
```

Update imports: add `Job` to `from dojo.model import`, add `JobNotFound`, `MediaValidationError` to the exceptions import, add `timedelta` (already added in Task 2 Step 3).

In `test_upload.py`, the `make_seam` must accept passing `media=` override via `**overrides`; the tests set `seam._media` directly, which requires `_media` to be a public attribute. Name it `_media` (private) and access it in tests as `seam._media` — add `# noqa: SLF001`? Ruff doesn't enable SLF. Keep as-is.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_upload.py -v`
Expected: PASS.

- [ ] **Step 6: Lint, typecheck, full suite, commit**

Run: `uv run --project dojo-core ruff check dojo-core/src dojo-core/tests; uv run --project dojo-core mypy dojo-core/src/dojo`
Expected: no findings
Run: `uv run --project dojo-core pytest dojo-core/tests -v`
Expected: all pass

```bash
git add dojo-core/src/dojo/publishing.py dojo-core/src/dojo/adapters/stubs.py dojo-core/tests/test_upload.py
git commit -m "feat(dojo-core): media processing jobs, finalize, and staging sweep (#7)"
```

---

### Task 4: MediaProcessor — real Pillow + ffmpeg adapter

**Files:**
- Modify: `dojo-core/pyproject.toml`
- Create: `dojo-core/src/dojo/adapters/media.py`
- Create: `dojo-core/tests/test_media_processor.py`

**Interfaces:**
- Consumes: `Upload`, `ProcessedMedia`, `MediaValidationError` (Task 1).
- Produces: `PillowFFmpegProcessor` implementing the `MediaProcessor` protocol; `ImageMagic`/`VideoMagic` helpers.

- [ ] **Step 1: Add dependencies**

In `dojo-core/pyproject.toml`, extend `dependencies`:
```toml
    "pillow>=11",
    "pillow-heif>=0.16",
```
Run: `uv lock` then `uv sync --project dojo-core`

- [ ] **Step 2: Write the failing tests**

Create `dojo-core/tests/test_media_processor.py`:
```python
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from dojo.adapters.media import PillowFFmpegProcessor
from dojo.exceptions import MediaValidationError
from dojo.model import Upload
from dojo.testing import FIXED_AT, render_test_clip
from PIL import Image

from dojo.adapters.stubs import StubMediaProcessor


def make_upload(filename: str, content_type: str) -> Upload:
    return Upload(
        id=1,
        upload_id="u-1",
        package_id=1,
        filename=filename,
        content_type=content_type,
        declared_size_bytes=0,
        received_ranges=[],
        received_bytes=0,
        status="queued",
        created_at=FIXED_AT,
        updated_at=FIXED_AT,
    )


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _docker_available() -> bool:
    try:
        import docker

        docker.from_env().ping()
        return True
    except Exception:
        return False


def test_jpeg_accepted_and_normalized(tmp_path: Path) -> None:
    src = tmp_path / "input.jpg"
    Image.new("RGB", (2000, 1000), "red").save(src, format="JPEG")
    processor = PillowFFmpegProcessor()
    out = processor.process(make_upload("input.jpg", "image/jpeg"), src, tmp_path)
    with Image.open(out.processed_path) as img:
        assert img.format == "JPEG"
        assert img.mode == "RGB"
    assert out.content_type == "image/jpeg"


def test_dimension_cap_applied(tmp_path: Path) -> None:
    src = tmp_path / "big.png"
    Image.new("RGB", (8000, 1000), "blue").save(src, format="PNG")
    processor = PillowFFmpegProcessor()
    out = processor.process(make_upload("big.png", "image/png"), src, tmp_path)
    with Image.open(out.processed_path) as img:
        assert max(img.size) <= 4000


def test_heic_accepted(tmp_path: Path) -> None:
    src = tmp_path / "input.heic"
    Image.new("RGB", (300, 300), "green").save(src, format="HEIF")
    processor = PillowFFmpegProcessor()
    out = processor.process(make_upload("input.heic", "image/heic"), src, tmp_path)
    with Image.open(out.processed_path) as img:
        assert img.format == "JPEG"


def test_corrupt_image_rejected(tmp_path: Path) -> None:
    src = tmp_path / "bad.jpg"
    src.write_bytes(b"not an image at all")
    processor = PillowFFmpegProcessor()
    with pytest.raises(MediaValidationError):
        processor.process(make_upload("bad.jpg", "image/jpeg"), src, tmp_path)


def test_animated_webp_rejected(tmp_path: Path) -> None:
    src = tmp_path / "anim.webp"
    frames = [Image.new("RGB", (50, 50), color) for color in ("red", "blue", "green")]
    frames[0].save(src, format="WEBP", save_all=True, append_images=frames[1:], duration=100)
    processor = PillowFFmpegProcessor()
    with pytest.raises(MediaValidationError):
        processor.process(make_upload("anim.webp", "image/webp"), src, tmp_path)


def test_unsupported_format_rejected(tmp_path: Path) -> None:
    src = tmp_path / "file.bmp"
    Image.new("RGB", (10, 10)).save(src, format="BMP")
    processor = PillowFFmpegProcessor()
    with pytest.raises(MediaValidationError):
        processor.process(make_upload("file.bmp", "image/bmp"), src, tmp_path)


@pytest.mark.skipif(not _docker_available(), reason="docker unavailable")
@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg unavailable")
def test_video_transcoded_to_h264_aac(tmp_path: Path) -> None:
    clip = render_test_clip(tmp_path / "fixture.mp4")
    processor = PillowFFmpegProcessor()
    out = processor.process(make_upload("fixture.mp4", "video/mp4"), clip, tmp_path)
    assert out.content_type == "video/mp4"
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height",
            "-of",
            "csv=p=0",
            str(out.processed_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert probe.stdout.strip().startswith("h264")


@pytest.mark.skipif(not _docker_available(), reason="docker unavailable")
@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg unavailable")
def test_video_mov_accepted(tmp_path: Path) -> None:
    clip = render_test_clip(tmp_path / "fixture.mov")
    processor = PillowFFmpegProcessor()
    out = processor.process(make_upload("fixture.mov", "video/quicktime"), clip, tmp_path)
    assert out.content_type == "video/mp4"
```

Note: remove the unused `StubMediaProcessor` import at the top (left intentionally to keep the import block parallel to the seam tests — delete it if ruff flags F401).

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_media_processor.py -v`
Expected: FAIL — `dojo.adapters.media` missing.

- [ ] **Step 4: Implement `PillowFFmpegProcessor`**

Create `dojo-core/src/dojo/adapters/media.py`:
```python
from __future__ import annotations

import subprocess
from pathlib import Path

from dojo.exceptions import MediaValidationError
from dojo.model import ProcessedMedia, Upload

IMAGE_TYPES = {"jpeg", "png", "webp", "heic", "heif", "mif1"}
VIDEO_TYPES = {"mp4", "mov", "qt"}
MAX_IMAGE_DIMENSION = 4000


def detect_container(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data.startswith(b"\x00\x00\x00") and b"ftyp" in data[:32]:
        brand = data[4:32]
        if any(name in brand for name in (b"heic", b"heix", b"heif", b"mif1")):
            return "heic"
        if b"qt  " in brand:
            return "mov"
        return "mp4"
    raise MediaValidationError("unrecognized file content")


class PillowFFmpegProcessor:
    """Validate real media content, normalize images, and transcode video."""

    def process(self, upload: Upload, original_path: Path, work_dir: Path) -> ProcessedMedia:
        data = original_path.read_bytes()[:64]
        try:
            kind = detect_container(data)
        except MediaValidationError as exc:
            raise MediaValidationError(f"{exc}: {upload.filename}") from exc
        if kind in IMAGE_TYPES:
            return self._process_image(original_path, work_dir)
        if kind in VIDEO_TYPES:
            return self._process_video(original_path, work_dir)
        raise MediaValidationError(f"unsupported media type: {kind}")

    @staticmethod
    def _process_image(original_path: Path, work_dir: Path) -> ProcessedMedia:
        from PIL import Image

        processed_path = work_dir / "processed.jpg"
        try:
            with Image.open(original_path) as img:
                if getattr(img, "n_frames", 1) > 1:
                    raise MediaValidationError("animated images are not supported")
                img = ImageOps.exif_transpose(img)
                if img.mode != "RGB":
                    img = img.convert("RGB")
                if max(img.size) > MAX_IMAGE_DIMENSION:
                    scale = MAX_IMAGE_DIMENSION / max(img.size)
                    img = img.resize(
                        (round(img.width * scale), round(img.height * scale))
                    )
                img.save(processed_path, format="JPEG", quality=90)
        except MediaValidationError:
            raise
        except Exception as exc:
            raise MediaValidationError(f"could not decode image: {exc}") from exc
        return ProcessedMedia(
            original_path=original_path,
            processed_path=processed_path,
            content_type="image/jpeg",
            size_bytes=processed_path.stat().st_size,
        )

    @staticmethod
    def _probe(path: Path) -> str:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name,width,height",
                "-of",
                "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise MediaValidationError(f"could not probe video: {result.stderr.strip()}")
        return result.stdout.strip()

    def _process_video(self, original_path: Path, work_dir: Path) -> ProcessedMedia:
        self._probe(original_path)
        processed_path = work_dir / "processed.mp4"
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(original_path),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(processed_path),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not processed_path.is_file():
            raise MediaValidationError(
                f"video transcoding failed: {result.stderr.strip()[:200]}"
            )
        probe = self._probe(processed_path)
        if not probe.startswith("h264"):
            raise MediaValidationError(f"transcoded video is not H.264: {probe}")
        return ProcessedMedia(
            original_path=original_path,
            processed_path=processed_path,
            content_type="video/mp4",
            size_bytes=processed_path.stat().st_size,
        )
```

Add `from PIL import ImageOps` in the import inside `_process_image` (move both to the function-level import block):
```python
        from PIL import Image, ImageOps
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_media_processor.py -v`
Expected: PASS. Note: `pillow-heif` registers the HEIF format on import; the `save(..., format="HEIF")` in the test requires `import pillow_heif` somewhere. Add `import pillow_heif` at the top of `_process_image` and in the test file after imports:
```python
import pillow_heif  # noqa: F401  (registers HEIF plugin)
```

- [ ] **Step 6: Lint, typecheck, full suite, commit**

Run: `uv run --project dojo-core ruff check dojo-core/src dojo-core/tests; uv run --project dojo-core mypy dojo-core/src/dojo`
Expected: no findings
Run: `uv run --project dojo-core pytest dojo-core/tests -v`
Expected: all pass

```bash
git add dojo-core/pyproject.toml dojo-core/uv.lock dojo-core/src/dojo/adapters/media.py dojo-core/tests/test_media_processor.py
git commit -m "feat(dojo-core): Pillow+ffmpeg media validation and normalization processor (#7)"
```

---

### Task 5: Worker integration

**Files:**
- Modify: `worker/src/worker/main.py`
- Modify: `worker/Dockerfile`
- Modify: `worker/tests/test_worker.py`

**Interfaces:**
- Consumes: `claim_next_job`, `process_job`, `sweep_stale_uploads` (Task 3).
- Produces: worker tick that claims, processes, and sweeps.

- [ ] **Step 1: Write the failing tests**

Replace `worker/tests/test_worker.py`:
```python
from __future__ import annotations

from dojo import DojoPublishing, InMemoryStore
from dojo.adapters.stubs import StubMediaProcessor
from worker.main import run_tick


class SpyPublishing(DojoPublishing):
    def __init__(self) -> None:
        self.ticks = 0
        self.processed_jobs: list[str] = []
        self._claims_left = 1
        super().__init__(
            packages=InMemoryStore(),
            audit=InMemoryStore(),
            media_root="/tmp/dojo-media",
            media=StubMediaProcessor(),
        )

    def evaluate_due_work(self) -> None:
        self.ticks += 1

    def claim_next_job(self) -> object:
        if self._claims_left:
            self._claims_left -= 1
            return {"job_id": "j-1"}
        return None

    def process_job(self, job_id: str) -> None:
        self.processed_jobs.append(job_id)

    def sweep_stale_uploads(self, ttl: object = None) -> int:
        return 0


def test_run_tick_calls_evaluate_due_work() -> None:
    spy = SpyPublishing()
    run_tick(spy)
    assert spy.ticks == 1


def test_run_tick_processes_claimed_job() -> None:
    spy = SpyPublishing()
    run_tick(spy)
    assert spy.processed_jobs == ["j-1"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project worker pytest worker/tests -v`
Expected: FAIL — `run_tick` does not call `claim_next_job`/`process_job`.

- [ ] **Step 3: Update `run_tick`**

In `worker/src/worker/main.py`, replace `run_tick`:
```python
def run_tick(publishing: DojoPublishing) -> None:
    publishing.evaluate_due_work()
    job = publishing.claim_next_job()
    if job is not None:
        publishing.process_job(job.job_id)
    publishing.sweep_stale_uploads()
```

- [ ] **Step 4: Add ffmpeg to the worker image**

In `worker/Dockerfile`, change the base image line to install ffmpeg:
```dockerfile
FROM python:3.12.14-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --project worker pytest worker/tests -v`
Expected: PASS.

- [ ] **Step 6: Lint, typecheck, full suite, commit**

Run: `uv run --project worker ruff check worker/src worker/tests; uv run --project worker mypy worker/src/worker`
Expected: no findings
Run: `uv run --project worker pytest worker/tests -v`
Expected: all pass

```bash
git add worker/src/worker/main.py worker/Dockerfile worker/tests/test_worker.py
git commit -m "feat(worker): claim and process media jobs, sweep stale uploads (#7)"
```

---

### Task 6: FastAPI routes + CLI

**Files:**
- Create: `backend/src/backend/routes/media.py`
- Modify: `backend/src/backend/main.py`
- Modify: `backend/src/backend/deps.py`
- Modify: `backend/src/backend/cli.py`
- Modify: `backend/pyproject.toml`
- Modify: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: seam methods from Tasks 2–3; `StubMediaProcessor` from Task 3.
- Produces: routes under `/api/media/uploads`; CLI `dojo-settings`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_api.py`:
```python
def test_media_routes_require_auth(tmp_path: Path) -> None:
    client, _, _, _ = make_app(tmp_path)
    assert client.post("/api/media/uploads", json={}).status_code == 401
    assert client.put("/api/media/uploads/x/ranges", json={}).status_code == 401
    assert client.get("/api/media/uploads/x").status_code == 401
    assert client.post("/api/media/uploads/x/complete").status_code == 401
    assert client.post("/api/media/uploads/x/abort").status_code == 401
    assert client.get("/api/media/uploads").status_code == 401


def test_init_upload_then_range_then_complete(tmp_path: Path) -> None:
    client, publishing, pairing, _ = make_app(tmp_path)
    publishing._media = StubMediaProcessor()
    token = pair_device(client, pairing)
    init = client.post(
        "/api/media/uploads",
        headers=bearer(token),
        json={"filename": "pic.jpg", "content_type": "image/jpeg", "declared_size_bytes": 100},
    )
    assert init.status_code == 201
    body = init.json()
    assert body["status"] == "receiving"
    assert body["received_bytes"] == 0

    chunk = b"x" * 100
    progress = client.put(
        f"/api/media/uploads/{body['upload_id']}/ranges",
        headers=bearer(token),
        content=chunk,
        params={"offset": 0, "checksum_sha256": hashlib.sha256(chunk).hexdigest()},
    )
    assert progress.status_code == 200
    assert progress.json()["received_bytes"] == 100

    complete = client.post(
        f"/api/media/uploads/{body['upload_id']}/complete", headers=bearer(token)
    )
    assert complete.status_code == 200
    assert complete.json()["status"] == "queued"


def test_init_upload_too_large_413(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    resp = client.post(
        "/api/media/uploads",
        headers=bearer(token),
        json={"filename": "big.mp4", "content_type": "video/mp4", "declared_size_bytes": 2 * 1024**3 + 1},
    )
    assert resp.status_code == 413


def test_init_upload_bad_filename_400(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    resp = client.post(
        "/api/media/uploads",
        headers=bearer(token),
        json={"filename": "a/b.jpg", "content_type": "image/jpeg", "declared_size_bytes": 10},
    )
    assert resp.status_code == 400


def test_range_checksum_mismatch_400(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    init = client.post(
        "/api/media/uploads",
        headers=bearer(token),
        json={"filename": "pic.jpg", "content_type": "image/jpeg", "declared_size_bytes": 100},
    ).json()
    resp = client.put(
        f"/api/media/uploads/{init['upload_id']}/ranges",
        headers=bearer(token),
        content=b"x" * 100,
        params={"offset": 0, "checksum_sha256": "deadbeef"},
    )
    assert resp.status_code == 400


def test_complete_incomplete_409(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    init = client.post(
        "/api/media/uploads",
        headers=bearer(token),
        json={"filename": "pic.jpg", "content_type": "image/jpeg", "declared_size_bytes": 100},
    ).json()
    resp = client.post(f"/api/media/uploads/{init['upload_id']}/complete", headers=bearer(token))
    assert resp.status_code == 409


def test_upload_status_and_list(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    init = client.post(
        "/api/media/uploads",
        headers=bearer(token),
        json={"filename": "pic.jpg", "content_type": "image/jpeg", "declared_size_bytes": 100},
    ).json()
    got = client.get(f"/api/media/uploads/{init['upload_id']}", headers=bearer(token))
    assert got.status_code == 200
    listed = client.get("/api/media/uploads", headers=bearer(token))
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_abort_upload(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    init = client.post(
        "/api/media/uploads",
        headers=bearer(token),
        json={"filename": "pic.jpg", "content_type": "image/jpeg", "declared_size_bytes": 100},
    ).json()
    abort = client.post(f"/api/media/uploads/{init['upload_id']}/abort", headers=bearer(token))
    assert abort.status_code == 200
    got = client.get(f"/api/media/uploads/{init['upload_id']}", headers=bearer(token)).json()
    assert got["status"] == "aborted"


def test_missing_upload_404(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    assert client.get("/api/media/uploads/nope", headers=bearer(token)).status_code == 404
```

Add `import hashlib` to the top of `test_api.py`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project backend pytest backend/tests/test_api.py -v`
Expected: FAIL — routes missing (405/404), auth checks fail because route absent.

- [ ] **Step 3: Create the media router**

Create `backend/src/backend/routes/media.py`:
```python
from __future__ import annotations

from typing import Any

from dojo import (
    Client,
    DojoPublishing,
    PackageLimitExceeded,
    UploadChecksumMismatch,
    UploadConflict,
    UploadIncomplete,
    UploadInvalidFilename,
    UploadNotFound,
    UploadNotReceiving,
    UploadTooLarge,
)
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.deps import get_current_client


def get_publishing(request: Request) -> DojoPublishing:
    return request.app.state.publishing


router = APIRouter(prefix="/api/media/uploads", tags=["media"])


class UploadInitIn(BaseModel):
    filename: str
    content_type: str
    declared_size_bytes: int


class UploadOut(BaseModel):
    upload_id: str
    received_bytes: int
    declared_size_bytes: int
    status: str
    received_ranges: list[list[int]]
    error_reason: str | None = None


def _out(status: Any) -> UploadOut:
    return UploadOut(**status.__dict__)


@router.post("", response_model=UploadOut, status_code=201)
def init_upload(
    body: UploadInitIn,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> UploadOut:
    try:
        status = publishing.start_upload(
            body.filename, body.content_type, body.declared_size_bytes, requester=str(client.id)
        )
    except UploadInvalidFilename as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UploadTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except PackageLimitExceeded as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _out(status)


@router.put("/{upload_id}/ranges", response_model=UploadOut)
async def append_range(
    upload_id: str,
    offset: int,
    checksum_sha256: str,
    request: Request,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> UploadOut:
    body = await request.body()
    length = len(body)
    if length > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="chunk exceeds 8 MiB limit")
    try:
        status = publishing.append_upload_range(
            upload_id, offset, length, checksum_sha256, body
        )
    except UploadNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UploadNotReceiving as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except UploadChecksumMismatch as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UploadConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _out(status)


@router.get("", response_model=list[UploadOut])
def list_uploads(
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> list[UploadOut]:
    return [_out(status) for status in publishing.list_active_uploads()]


@router.get("/{upload_id}", response_model=UploadOut)
def get_upload(
    upload_id: str,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> UploadOut:
    try:
        status = publishing.get_upload_status(upload_id)
    except UploadNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _out(status)


@router.post("/{upload_id}/complete", response_model=UploadOut)
def complete_upload(
    upload_id: str,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> UploadOut:
    try:
        status = publishing.complete_upload(upload_id, requester=str(client.id))
    except UploadNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UploadConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except UploadIncomplete as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _out(status)


@router.post("/{upload_id}/abort", status_code=200)
def abort_upload(
    upload_id: str,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, str]:
    try:
        publishing.abort_upload(upload_id, requester=str(client.id))
    except UploadNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UploadConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "aborted"}
```

The router imports `UploadStatus`? No — the `_out` helper converts a seam `UploadStatus` (from `dojo.model`) into the pydantic `UploadOut` via `__dict__`. Import `UploadStatus` is not needed in the route file; the seam returns it and `_out` reads `status.__dict__`.

- [ ] **Step 4: Wire the router into `backend/src/backend/main.py`**

Add import and include:
```python
from backend.routes import media as media_router
...
    app.include_router(media_router.router, dependencies=[Depends(get_current_client)])
```

- [ ] **Step 5: Update `backend/src/backend/deps.py` build functions**

Pass the new stores so uploads/jobs/settings resolve to Postgres:
```python
def build_publishing() -> DojoPublishing:
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    media_root = Path(os.environ.get("MEDIA_ROOT", "media"))
    store = PostgresStore(url)
    store.create_all()
    return DojoPublishing(packages=store, audit=store, uploads=store, jobs=store, settings=store, media_root=media_root)
```

- [ ] **Step 6: Add the `dojo-settings` CLI**

In `backend/src/backend/cli.py`, add a new main:
```python
def settings_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dojo-settings")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_URL),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    limits = subparsers.add_parser("set-upload-limits")
    limits.add_argument("--max-file-bytes", type=int)
    limits.add_argument("--max-package-bytes", type=int)
    args = parser.parse_args(argv)

    store = PostgresStore(args.database_url)
    store.create_all()
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Europe/Istanbul"))
    if args.max_file_bytes is not None:
        store.set("upload.max_file_bytes", args.max_file_bytes, updated_at=now)
    if args.max_package_bytes is not None:
        store.set("upload.max_package_bytes", args.max_package_bytes, updated_at=now)
    print("upload limits saved")
    return 0
```
Register in `backend/pyproject.toml`:
```toml
dojo-settings = "backend.cli:settings_main"
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run --project backend pytest backend/tests/test_api.py -v`
Expected: PASS.

- [ ] **Step 8: Lint, typecheck, full suite, commit**

Run: `uv run --project backend ruff check backend/src backend/tests; uv run --project backend mypy backend/src/backend`
Expected: no findings
Run: `uv run --project backend pytest backend/tests -v`
Expected: all pass

```bash
git add backend/src/backend/routes/media.py backend/src/backend/main.py backend/src/backend/deps.py backend/src/backend/cli.py backend/pyproject.toml backend/tests/test_api.py
git commit -m "feat(backend): resumable media upload API and settings CLI (#7)"
```

---

### Task 7: Full suite, design-vs-implementation check, close out

- [ ] **Step 1: Run all three full suites**

Run: `uv run --project dojo-core pytest dojo-core/tests -v`
Expected: all pass
Run: `uv run --project backend pytest backend/tests -v`
Expected: all pass
Run: `uv run --project worker pytest worker/tests -v`
Expected: all pass

- [ ] **Step 2: Lint and typecheck everything**

Run: `uv run --project dojo-core ruff check dojo-core/src dojo-core/tests; uv run --project dojo-core mypy dojo-core/src/dojo; uv run --project backend ruff check backend/src backend/tests; uv run --project backend mypy backend/src/backend; uv run --project worker ruff check worker/src worker/tests; uv run --project worker mypy worker/src/worker`
Expected: no findings

- [ ] **Step 3: Verify acceptance criteria against the design**

Check the spec (`docs/superpowers/specs/2026-08-15-resumable-upload-media-validation-design.md`):
- Chunked upload resumes after interruption; duplicate chunks handled; checksum mismatch rejected → `append_upload_range` idempotent ranges + `UploadChecksumMismatch` (Task 2).
- Progress, pause, and retry surfaced through the API → `get_upload_status` + GET routes + `received_ranges` (Tasks 2, 6).
- Valid formats accepted; invalid or unsupported media rejected with a clear reason → `PillowFFmpegProcessor` + `MediaValidationError` with `error_reason` (Task 4).
- Per-file and per-package limits enforced; oversize rejected pre-transfer; disk availability checked at finalization → `start_upload` limits + `finalize_media` disk check (Tasks 2, 3).
- Finalized media enters the active package only after full validation; temporary uploads cleaned up → `finalize_media` guarded by `processing` status, staging cleanup, `media.finalized` audit (Task 3).

- [ ] **Step 4: Commit any stragglers and note the follow-up**

No new files expected beyond Tasks 1–6. If a stray file exists, commit it. Do not close issue #7 — implementation completion is reported by the implementer, and closing is handled separately after /code-review.
