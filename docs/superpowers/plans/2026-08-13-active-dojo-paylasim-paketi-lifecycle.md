# Active Dojo Paylaşım Paketi Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the active package lifecycle for issue #6: auto-creation on first use, a zero-or-one active invariant (facade + DB partial unique index), the full eight-key manifest contract, and `complete_active_package()` that renames the folder `-completed` and immediately creates the next empty package.

**Architecture:** Extend the existing deep `DojoPublishing` facade (`dojo/publishing.py`). The `Manifest` model grows to the full MVP contract with empty defaults; `PackageStore` gains `update()`; migration `0004` adds a partial unique index on `packages(status) WHERE status='active'`. Routes: GET auto-creates, POST stays strict, new POST `/api/packages/active/complete`. No new facade, no CLI.

**Tech Stack:** Python 3.12 (uv workspace), FastAPI, SQLAlchemy 2.0, alembic, pytest, testcontainers-python, ruff, mypy.

## Global Constraints

- Python `requires-python = ">=3.12"`.
- Domain vocabulary from `CONTEXT.md`: `Dojo Paylaşım Paketi`, active package, `Tamamlanmış Paket`. Do not invent new domain nouns.
- One active `Dojo Paylaşım Paketi` during normal operation; zero-or-one invariant enforced by the facade (`ActivePackageExists`) AND a partial unique index `ON packages(status) WHERE status='active'`.
- Active package auto-created on first use: `POST /api/packages/active` (strict, 409 on existing) and `GET /api/packages/active` (auto-creates, never 404).
- Completion (`complete_active_package`) is owned by #6: DB row flips to `completed` BEFORE the folder rename; the next empty active package is created immediately; `package.completed` audit precedes `package.created` for the next.
- Folder names use portable `dd-MM-yyyy HH-mm` (`PACKAGE_FOLDER_FORMAT`) in `Europe/Istanbul`. Same-minute collision handling is out of scope.
- Manifest holds all eight keys from day one: `media`, `order`, `trims`, `caption`, `branding`, `render_revision`, `meta`, `recovery` — empty defaults.
- Package routes sit behind `get_current_client`; equal privilege for device + browser. Unauthenticated → `401`.
- Lint: ruff (`E,F,I,UP`). dojo-core mypy with `disallow_untyped_defs`; backend mypy `strict`. Both must pass before each task's commit.
- Commands run from repo root. Tests against real Postgres via the `pg_store` fixture (testcontainers) use `FakeClock` for deterministic time.
- Every Python task: run the focused test file first, then the package's full suite, before committing.

---

### Task 1: Storage — Manifest schema, `PackageStore.update`, migration 0004

**Files:**
- Modify: `dojo-core/src/dojo/model.py`
- Modify: `dojo-core/src/dojo/ports.py`
- Create: `dojo-core/migrations/versions/0004_active_package.py`
- Modify: `dojo-core/src/dojo/adapters/memory.py`
- Modify: `dojo-core/src/dojo/adapters/db.py`
- Create: `dojo-core/tests/test_store_package.py`
- Modify: `dojo-core/tests/test_db_adapter.py`

**Interfaces:**
- Consumes: existing `InMemoryStore`/`PostgresStore`, `Base`, alembic conventions from `0003_setup`.
- Produces:
  - `Manifest` with fields `media: list[dict]`, `order: list[str]`, `trims: dict`, `caption: str | None`, `branding: dict`, `render_revision: str | None`, `meta: dict`, `recovery: dict`; `to_dict()` emits all eight keys.
  - `PackageStore.update(package: Package) -> Package` on the protocol and both adapters.
  - Migration `0004_active_package` (revision id `"0004_active_package"`, `down_revision = "0003_setup"`) creating `ix_packages_status_active`.

- [ ] **Step 1: Write the failing tests**

Create `dojo-core/tests/test_store_package.py`:
```python
from __future__ import annotations

from dataclasses import replace

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
```

In `dojo-core/tests/test_db_adapter.py`, update the schema assertion in `test_alembic_upgrade_head_creates_schema`:
```python
    inspector = inspect(pg_store._engine)  # noqa: SLF001
    assert {"packages", "audit_events", "consent_policies", "consent_acceptances"} <= set(
        inspector.get_table_names()
    )
    package_indexes = {i["name"] for i in inspector.get_indexes("packages")}
    assert "ix_packages_status_active" in package_indexes
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_store_package.py dojo-core/tests/test_db_adapter.py -v`
Expected: FAIL — `InMemoryStore`/`PostgresStore` have no `update`, `Manifest` has no `trims`/`meta`/`recovery`, and the index is absent.

- [ ] **Step 3: Extend the `Manifest` model**

In `dojo-core/src/dojo/model.py`, replace the `Manifest` dataclass:
```python
@dataclass(frozen=True)
class Manifest:
    media: list[dict] = field(default_factory=list)
    order: list[str] = field(default_factory=list)
    trims: dict = field(default_factory=dict)
    caption: str | None = None
    branding: dict = field(default_factory=dict)
    render_revision: str | None = None
    meta: dict = field(default_factory=dict)
    recovery: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "media": self.media,
            "order": self.order,
            "trims": self.trims,
            "caption": self.caption,
            "branding": self.branding,
            "render_revision": self.render_revision,
            "meta": self.meta,
            "recovery": self.recovery,
        }
```

- [ ] **Step 4: Add `update` to the `PackageStore` port**

In `dojo-core/src/dojo/ports.py`, inside the `PackageStore` protocol, add:
```python
    def update(self, package: Package) -> Package: ...
```

- [ ] **Step 5: Add the migration**

Create `dojo-core/migrations/versions/0004_active_package.py`:
```python
"""partial unique index on active packages

Revision ID: 0004_active_package
Revises: 0003_setup
Create Date: 2026-08-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_active_package"
down_revision: Union[str, None] = "0003_setup"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_packages_status_active",
        "packages",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("ix_packages_status_active", table_name="packages")
```

- [ ] **Step 6: Implement `InMemoryStore.update`**

In `dojo-core/src/dojo/adapters/memory.py`, after `get_active`, add:
```python
    def update(self, package: Package) -> Package:
        for i, existing in enumerate(self._packages):
            if existing.id == package.id:
                self._packages[i] = package
                return package
        raise ValueError(f"package {package.id} not found")
```

- [ ] **Step 7: Implement `PostgresStore.update` and model index**

In `dojo-core/src/dojo/adapters/db.py`:
- extend the sqlalchemy import: `from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, create_engine, select, text, update`
- add `__table_args__` to `PackageRow`:
```python
class PackageRow(Base):
    __tablename__ = "packages"
    __table_args__ = (
        Index(
            "ix_packages_status_active",
            "status",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )
```
- after `get_active`, add:
```python
    def update(self, package: Package) -> Package:
        with self._session() as session:
            session.execute(
                update(PackageRow)
                .where(PackageRow.id == package.id)
                .values(folder_name=package.folder_name, status=package.status)
            )
            session.commit()
            row = session.get(PackageRow, package.id)
            assert row is not None
            return Package(
                id=row.id,
                folder_name=row.folder_name,
                created_at=row.created_at,
                status=row.status,
            )
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_store_package.py dojo-core/tests/test_db_adapter.py -v`
Expected: PASS. If `pytest` is not imported in `test_store_package.py`, add `import pytest` at the top (needed by `test_pg_partial_unique_index_blocks_second_active_row`).

- [ ] **Step 9: Lint, typecheck, full suite, commit**

Run: `uv run --project dojo-core ruff check dojo-core/src dojo-core/tests; uv run --project dojo-core mypy dojo-core/src/dojo`
Expected: no findings
Run: `uv run --project dojo-core pytest dojo-core/tests -v`
Expected: all pass

```bash
git add dojo-core/src/dojo/model.py dojo-core/src/dojo/ports.py dojo-core/migrations/versions/0004_active_package.py dojo-core/src/dojo/adapters/memory.py dojo-core/src/dojo/adapters/db.py dojo-core/tests/test_store_package.py dojo-core/tests/test_db_adapter.py
git commit -m "feat(dojo-core): full manifest schema and package update store support (#6)"
```

---

### Task 2: `DojoPublishing` facade — get-or-create and complete transitions

**Files:**
- Modify: `dojo-core/src/dojo/publishing.py`
- Modify: `dojo-core/tests/test_publishing.py`

**Interfaces:**
- Consumes: `PackageStore` with `get_active`/`create`/`update`, `AuditStore.append`, `Clock.now()`, `Manifest`, `Package`, `PACKAGE_FOLDER_FORMAT`, `ISTANBUL`, exceptions `ActivePackageExists`, `NoActivePackage` (already in `dojo/exceptions.py` and exported in `dojo/__init__.py`).
- Produces:
  - `DojoPublishing.get_or_create_active_package(*, requester: str | None = None) -> Package`
  - `DojoPublishing.ensure_active_package(*, requester: str | None = None) -> Package` (unchanged public contract)
  - `DojoPublishing.complete_active_package(*, requester: str | None = None) -> Package`
  - private `_create_active_package(*, requester: str | None = None) -> Package`

- [ ] **Step 1: Write the failing tests**

Append to `dojo-core/tests/test_publishing.py` and update the existing manifest assertion:

Update `test_ensure_active_package_creates_folder_manifest_row_and_audit` manifest block to:
```python
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest == {
        "media": [],
        "order": [],
        "trims": {},
        "caption": None,
        "branding": {},
        "render_revision": None,
        "meta": {},
        "recovery": {},
    }
```

Update the import block to:
```python
from dojo import (
    ActivePackageExists,
    DojoPublishing,
    InMemoryStore,
    NoActivePackage,
)
```

Append:
```python
def test_get_or_create_returns_existing_active_package(tmp_path):
    _, seam = make_seam(tmp_path)
    first = seam.ensure_active_package()
    second = seam.get_or_create_active_package()
    assert second == first


def test_get_or_create_creates_when_absent(tmp_path):
    store, seam = make_seam(tmp_path)
    package = seam.get_or_create_active_package(requester="7")
    assert package.status == "active"
    assert package.folder_name == "06-08-2026 14-30"
    assert (tmp_path / "06-08-2026 14-30" / "manifest.json").is_file()
    events = seam.list_audit()
    assert events[0].action == "package.created"
    assert events[0].actor == "7"


def test_complete_active_package_renames_creates_next_and_audits(tmp_path):
    store, seam = make_seam(tmp_path)
    first = seam.ensure_active_package()

    next_package = seam.complete_active_package(requester="9")

    assert first.status == "active"
    completed_dir = tmp_path / "06-08-2026 14-30-completed"
    assert completed_dir.is_dir()
    assert not (tmp_path / "06-08-2026 14-30").exists()

    completed_row = [p for p in store._packages if p.status == "completed"]  # noqa: SLF001
    assert len(completed_row) == 1
    assert completed_row[0].folder_name == "06-08-2026 14-30-completed"

    assert next_package.status == "active"
    assert store.get_active() == next_package
    assert (tmp_path / next_package.folder_name / "manifest.json").is_file()

    actions = [e.action for e in seam.list_audit()]
    assert actions[0] == "package.created"  # for the next package
    assert actions[1] == "package.completed"
    completed = [e for e in seam.list_audit() if e.action == "package.completed"]
    assert completed[0].actor == "9"
    assert completed[0].details == {"folder_name": "06-08-2026 14-30-completed"}


def test_complete_active_package_without_active_raises(tmp_path):
    _, seam = make_seam(tmp_path)
    with pytest.raises(NoActivePackage):
        seam.complete_active_package()
    assert len(list(tmp_path.iterdir())) == 0


def test_zero_or_one_invariant_after_completion(tmp_path):
    _, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    with pytest.raises(ActivePackageExists):
        seam.ensure_active_package()
    seam.complete_active_package()
    assert seam.get_active_package() is not None
    assert seam.get_active_package().status == "active"
    with pytest.raises(ActivePackageExists):
        seam.ensure_active_package()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_publishing.py -v`
Expected: FAIL — `DojoPublishing` has no `get_or_create_active_package` / `complete_active_package`, and the manifest assertion fails on the extra keys.

- [ ] **Step 3: Refactor creation into a private helper and add the two methods**

In `dojo-core/src/dojo/publishing.py`:
- change the imports to:
```python
from dataclasses import replace

from dojo.adapters.clock import ISTANBUL, SystemClock
from dojo.adapters.stubs import StubMetaPublisher, StubNotifier, StubSignedUrlStore
from dojo.exceptions import ActivePackageExists, NoActivePackage
from dojo.model import PACKAGE_FOLDER_FORMAT, AuditEvent, Manifest, Package
from dojo.ports import AuditStore, Clock, MetaPublisher, Notifier, PackageStore, SignedUrlStore
```
- replace `ensure_active_package` with:
```python
    def ensure_active_package(self, *, requester: str | None = None) -> Package:
        """Create an active Dojo Paylaşım Paketi; raise if one already exists."""
        existing = self._packages.get_active()
        if existing is not None:
            raise ActivePackageExists(f"active package {existing.folder_name} already exists")
        return self._create_active_package(requester=requester)

    def get_or_create_active_package(self, *, requester: str | None = None) -> Package:
        """Return the active package, creating it when none exists."""
        existing = self._packages.get_active()
        if existing is not None:
            return existing
        return self._create_active_package(requester=requester)

    def _create_active_package(self, *, requester: str | None = None) -> Package:
        now = self._clock.now().astimezone(ISTANBUL)
        folder_name = now.strftime(PACKAGE_FOLDER_FORMAT)
        folder = self.media_root / folder_name
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "manifest.json").write_text(
            json.dumps(Manifest().to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        package = self._packages.create(
            Package(id=0, folder_name=folder_name, created_at=now, status="active")
        )
        self._audit.append(
            AuditEvent(
                action="package.created",
                actor=requester or "system",
                occurred_at=now,
                details={"folder_name": folder_name},
            )
        )
        return package

    def complete_active_package(self, *, requester: str | None = None) -> Package:
        """Complete the active package and create the next empty active package."""
        existing = self._packages.get_active()
        if existing is None:
            raise NoActivePackage("no active package to complete")

        now = self._clock.now().astimezone(ISTANBUL)
        completed_folder_name = f"{existing.folder_name}-completed"

        self._packages.update(replace(existing, status="completed"))
        (self.media_root / existing.folder_name).rename(
            self.media_root / completed_folder_name
        )
        self._packages.update(
            replace(existing, status="completed", folder_name=completed_folder_name)
        )

        self._audit.append(
            AuditEvent(
                action="package.completed",
                actor=requester or "system",
                occurred_at=now,
                details={"folder_name": completed_folder_name},
            )
        )
        return self._create_active_package(requester=requester)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_publishing.py -v`
Expected: PASS. Note: with `FakeClock` fixed at `FIXED_AT`, the next package after completion reuses the same `06-08-2026 14-30` timestamp because the completed folder was renamed away — `mkdir` succeeds and the `folder_name` DB unique constraint no longer collides.

- [ ] **Step 5: Lint, typecheck, full suite, commit**

Run: `uv run --project dojo-core ruff check dojo-core/src dojo-core/tests; uv run --project dojo-core mypy dojo-core/src/dojo`
Expected: no findings
Run: `uv run --project dojo-core pytest dojo-core/tests -v`
Expected: all pass

```bash
git add dojo-core/src/dojo/publishing.py dojo-core/tests/test_publishing.py
git commit -m "feat(dojo-core): get-or-create and complete active package transitions (#6)"
```

---

### Task 3: API routes — GET auto-create and complete endpoint

**Files:**
- Modify: `backend/src/backend/routes/packages.py`
- Modify: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `DojoPublishing.get_or_create_active_package(requester=...)`, `DojoPublishing.complete_active_package(requester=...)`, exceptions `NoActivePackage`, `ActivePackageExists`, `get_current_client`.
- Produces: `GET /api/packages/active` auto-creates; `POST /api/packages/active` unchanged; `POST /api/packages/active/complete` returns the new active package; `NoActivePackage` → 404.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_api.py`, update `test_packages_require_auth`:
```python
def test_packages_require_auth(tmp_path: Path) -> None:
    client, _, _, _ = make_app(tmp_path)
    assert client.get("/api/packages/active").status_code == 401
    assert client.post("/api/packages/active").status_code == 401
    assert client.post("/api/packages/active/complete").status_code == 401
```

Append:
```python
def test_get_active_auto_creates_when_absent(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    resp = client.get("/api/packages/active", headers=bearer(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "active"
    actions = [e["action"] for e in client.get("/api/activity", headers=bearer(token)).json()["events"]]
    assert "package.created" in actions


def test_post_active_second_ensure_returns_409(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    assert client.post("/api/packages/active", headers=bearer(token)).status_code == 201
    assert client.post("/api/packages/active", headers=bearer(token)).status_code == 409


def test_complete_active_returns_next_package(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    first = client.post("/api/packages/active", headers=bearer(token)).json()

    resp = client.post("/api/packages/active/complete", headers=bearer(token))
    assert resp.status_code == 200
    next_body = resp.json()
    assert next_body["status"] == "active"
    assert next_body["id"] != first["id"]

    fetched = client.get("/api/packages/active", headers=bearer(token)).json()
    assert fetched["id"] == next_body["id"]

    actions = [e["action"] for e in client.get("/api/activity", headers=bearer(token)).json()["events"]]
    assert "package.completed" in actions
    assert "package.created" in actions


def test_complete_active_without_package_returns_404(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    resp = client.post("/api/packages/active/complete", headers=bearer(token))
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project backend pytest backend/tests/test_api.py -v`
Expected: FAIL — `POST /api/packages/active/complete` returns `405` (route missing) and GET does not auto-create.

- [ ] **Step 3: Update the packages router**

Replace `backend/src/backend/routes/packages.py`:
```python
from __future__ import annotations

from datetime import datetime

from dojo import ActivePackageExists, Client, DojoPublishing, NoActivePackage
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.deps import get_current_client


def get_publishing(request: Request) -> DojoPublishing:
    return request.app.state.publishing


router = APIRouter(prefix="/api/packages", tags=["packages"])


class PackageOut(BaseModel):
    id: int
    folder_name: str
    created_at: datetime
    status: str


@router.get("/active", response_model=PackageOut)
def get_active(
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> PackageOut:
    package = publishing.get_or_create_active_package(requester=str(client.id))
    return PackageOut(**package.__dict__)


@router.post("/active", response_model=PackageOut, status_code=201)
def ensure_active(
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> PackageOut:
    try:
        package = publishing.ensure_active_package(requester=str(client.id))
    except ActivePackageExists as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return PackageOut(**package.__dict__)


@router.post("/active/complete", response_model=PackageOut)
def complete_active(
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> PackageOut:
    try:
        package = publishing.complete_active_package(requester=str(client.id))
    except NoActivePackage as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PackageOut(**package.__dict__)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --project backend pytest backend/tests/test_api.py -v`
Expected: PASS (walk the whole file — no `make_app` signature change is needed for this task).

- [ ] **Step 5: Lint, typecheck, full suite, commit**

Run: `uv run --project backend ruff check backend/src backend/tests; uv run --project backend mypy backend/src/backend`
Expected: no findings
Run: `uv run --project backend pytest backend/tests -v`
Expected: all pass

```bash
git add backend/src/backend/routes/packages.py backend/tests/test_api.py
git commit -m "feat(backend): active package auto-create on GET and completion endpoint (#6)"
```

---

### Task 4: Full suite, design-vs-implementation check, close out

- [ ] **Step 1: Run both full suites**

Run: `uv run --project dojo-core pytest dojo-core/tests -v`
Expected: all pass
Run: `uv run --project backend pytest backend/tests -v`
Expected: all pass

- [ ] **Step 2: Lint and typecheck everything**

Run: `uv run --project dojo-core ruff check dojo-core/src dojo-core/tests; uv run --project dojo-core mypy dojo-core/src/dojo; uv run --project backend ruff check backend/src backend/tests; uv run --project backend mypy backend/src/backend`
Expected: no findings

- [ ] **Step 3: Verify acceptance criteria against the design**

Check the spec (`docs/superpowers/specs/2026-08-13-active-dojo-paylasim-paketi-lifecycle-design.md`):
- Active package auto-created on first use when absent → `get_or_create_active_package` on GET + `ensure_active_package` on POST (Tasks 2-3 tests).
- Zero-or-one active package invariant; completion creates the next empty package → `ActivePackageExists` + partial unique index + `complete_active_package` (Tasks 1-3 tests).
- Manifest persists order, trims, caption, branding, render revision, and Meta identifiers → eight-key `Manifest` schema and initial write (Tasks 1-2 tests).
- Folder naming portable and timestamp-based → `PACKAGE_FOLDER_FORMAT` in `Europe/Istanbul`, asserted in every creation test.

- [ ] **Step 4: Commit any stragglers and note the follow-up**

No new files expected beyond Tasks 1-3. If a stray file exists, commit it. Do not close issue #6 — implementation completion is reported by the implementer, and closing is handled separately after /code-review.
