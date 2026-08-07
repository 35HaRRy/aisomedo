# Monorepo Scaffold, Dojo Seam, Test Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a uv-workspace monorepo (dojo-core, backend, worker, web, android, ops) with a deep `DojoPublishing` facade seam, a testcontainers-based harness against real PostgreSQL + FFmpeg fixtures, and a green CI pipeline.

**Architecture:** `dojo-core` owns the deep behavioral seam — a `DojoPublishing` facade with injected adapter ports (Clock, PackageStore, AuditStore, MetaPublisher, Notifier, SignedUrlStore). Backend (FastAPI) and worker (scheduler) are thin consumers. Persistence is SQLAlchemy + alembic against PostgreSQL; package folders + `manifest.json` live on the filesystem. Tests swap only wall clock, Meta publishing, notifications, and signed-URL delivery.

**Tech Stack:** Python 3.12 (uv-managed), uv workspace, FastAPI, SQLAlchemy 2.0, alembic, psycopg3, pytest, testcontainers-python, docker SDK, Vite + React + TS, Gradle/Kotlin (files only), Docker Compose, GitHub Actions.

## Global Constraints

- Python `requires-python = ">=3.12"` everywhere; `.python-version` = `3.12` at workspace root.
- Package folder name format: `dd-MM-yyyy HH-mm` (e.g. `06-08-2026 14-30`), computed in `Europe/Istanbul`.
- `tzdata` must be a runtime dependency of `dojo-core` (Windows/CI have no IANA tz database).
- Domain vocabulary from `CONTEXT.md`: `Dojo Paylaşım Paketi`, `Dojo Yayın Planı`, `Yayın Zamanı`, `Yayın İncelemesi`, `Tamamlanmış Paket`. Use these in docstrings and user-facing strings.
- The `DojoPublishing` facade is the ONLY behavioral seam. Tests assert observable outcomes (folder, manifest, DB row, audit entry), never SQL shape or private call order.
- Four adapter ports replaced in tests: `Clock`, `MetaPublisher`, `Notifier`, `SignedUrlStore`. `PackageStore`/`AuditStore` run against real PostgreSQL in the harness.
- Stub seam methods (not yet live) raise `NotImplementedError`.
- Commands run from repo root unless a task says otherwise. All paths relative to repo root.
- Lint: ruff (`E,F,I,UP`). Typecheck: mypy `disallow_untyped_defs`. Both must pass before each task's commit.
- Every Python task: run the focused test file first, then the package's full suite, before committing.

---

### Task 1: uv workspace + dojo-core package skeleton (model, ports, facade with live `ensure_active_package`)

**Files:**
- Create: `pyproject.toml` (workspace root)
- Create: `.python-version`
- Create: `.gitignore`
- Create: `dojo-core/pyproject.toml`
- Create: `dojo-core/src/dojo/__init__.py`
- Create: `dojo-core/src/dojo/model.py`
- Create: `dojo-core/src/dojo/exceptions.py`
- Create: `dojo-core/src/dojo/ports.py`
- Create: `dojo-core/src/dojo/adapters/__init__.py`
- Create: `dojo-core/src/dojo/adapters/clock.py`
- Create: `dojo-core/src/dojo/adapters/stubs.py`
- Create: `dojo-core/src/dojo/adapters/memory.py`
- Create: `dojo-core/src/dojo/publishing.py`
- Create: `dojo-core/src/dojo/testing.py` (test-support helpers, shipped so backend/worker tests can use them)
- Create: `dojo-core/tests/__init__.py`
- Test: `dojo-core/tests/test_publishing.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `dojo.Package(frozen dataclass: id:int, folder_name:str, created_at:datetime, status:str="active")`; `dojo.Manifest`; `dojo.AuditEvent(action:str, actor:str, occurred_at:datetime, details:dict)`; `PACKAGE_FOLDER_FORMAT="%d-%m-%Y %H-%M"`; exceptions `DojoError`, `ActivePackageExists`, `NoActivePackage`; protocols `Clock.now()->datetime`, `PackageStore.create/get_active`, `AuditStore.append/list_recent`, `MetaPublisher.publish_reel`, `Notifier.notify`, `SignedUrlStore.create/revoke`; `SystemClock`; recording stubs `StubMetaPublisher`, `StubNotifier`, `StubSignedUrlStore`; `InMemoryStore`; `DojoPublishing(packages, audit, media_root:Path, clock=None, meta=None, notifier=None, signed_urls=None)` with `ensure_active_package()->Package`, `get_active_package()->Package|None`, `evaluate_due_work()->None`, `list_audit(limit=50)->list[AuditEvent]`, and stubbed methods.

- [ ] **Step 1: Write workspace root files**

`pyproject.toml`:
```toml
[workspace]
members = ["dojo-core", "backend", "worker"]

[tool.uv]
default-groups = ["dev"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP"]
```

`.python-version`:
```
3.12
```

`.gitignore`:
```
__pycache__/
*.py[cod]
.venv/
.pytest_cache/
.ruff_cache/
.mypy_cache/
node_modules/
dist/
build/
.env
*.egg-info/
*.log
media/
.DS_Store
```

- [ ] **Step 2: Write dojo-core package manifest + model**

`dojo-core/pyproject.toml`:
```toml
[project]
name = "dojo-core"
version = "0.1.0"
description = "Deep Dojo Publishing seam and adapters"
requires-python = ">=3.12"
dependencies = [
    "sqlalchemy>=2.0,<3",
    "psycopg[binary]>=3.2",
    "alembic>=1.13",
    "tzdata>=2024.1",
]

[dependency-groups]
dev = [
    "pytest>=8",
    "testcontainers[postgres]>=4.8",
    "docker>=7",
    "httpx>=0.27",
    "ruff>=0.8",
    "mypy>=1.11",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/dojo"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]

[tool.mypy]
python_version = "3.12"
disallow_untyped_defs = true
ignore_missing_imports = true
```

`dojo-core/src/dojo/model.py`:
```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

PACKAGE_FOLDER_FORMAT = "%d-%m-%Y %H-%M"


@dataclass(frozen=True)
class Package:
    id: int
    folder_name: str
    created_at: datetime
    status: str = "active"


@dataclass(frozen=True)
class Manifest:
    media: list[dict] = field(default_factory=list)
    order: list[str] = field(default_factory=list)
    caption: str | None = None
    branding: dict = field(default_factory=dict)
    render_revision: str | None = None

    def to_dict(self) -> dict:
        return {
            "media": self.media,
            "order": self.order,
            "caption": self.caption,
            "branding": self.branding,
            "render_revision": self.render_revision,
        }


@dataclass(frozen=True)
class AuditEvent:
    action: str
    actor: str
    occurred_at: datetime
    details: dict = field(default_factory=dict)
```

`dojo-core/src/dojo/exceptions.py`:
```python
class DojoError(Exception):
    pass


class ActivePackageExists(DojoError):
    pass


class NoActivePackage(DojoError):
    pass
```

`dojo-core/src/dojo/ports.py`:
```python
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from dojo.model import AuditEvent, Package


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime: ...


@runtime_checkable
class PackageStore(Protocol):
    def create(self, package: Package) -> Package: ...
    def get_active(self) -> Package | None: ...


@runtime_checkable
class AuditStore(Protocol):
    def append(self, event: AuditEvent) -> None: ...
    def list_recent(self, limit: int = 50) -> list[AuditEvent]: ...


@runtime_checkable
class MetaPublisher(Protocol):
    def publish_reel(self, signed_url: str, caption: str) -> None: ...


@runtime_checkable
class Notifier(Protocol):
    def notify(self, title: str, body: str) -> None: ...


@runtime_checkable
class SignedUrlStore(Protocol):
    def create(self, artifact_path: Path) -> str: ...
    def revoke(self, url: str) -> None: ...
```

- [ ] **Step 3: Write dojo-core adapters**

`dojo-core/src/dojo/adapters/__init__.py`:
```python
from dojo.adapters.clock import SystemClock
from dojo.adapters.memory import InMemoryStore
from dojo.adapters.stubs import StubMetaPublisher, StubNotifier, StubSignedUrlStore

__all__ = [
    "InMemoryStore",
    "StubMetaPublisher",
    "StubNotifier",
    "StubSignedUrlStore",
    "SystemClock",
]
```

`dojo-core/src/dojo/adapters/clock.py`:
```python
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

ISTANBUL = ZoneInfo("Europe/Istanbul")


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(tz=ISTANBUL)
```

`dojo-core/src/dojo/adapters/stubs.py`:
```python
from __future__ import annotations

from pathlib import Path


class StubMetaPublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def publish_reel(self, signed_url: str, caption: str) -> None:
        self.calls.append((signed_url, caption))


class StubNotifier:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def notify(self, title: str, body: str) -> None:
        self.messages.append((title, body))


class StubSignedUrlStore:
    def __init__(self) -> None:
        self.active: list[str] = []

    def create(self, artifact_path: Path) -> str:
        url = f"https://signed.local/{artifact_path.name}"
        self.active.append(url)
        return url

    def revoke(self, url: str) -> None:
        if url in self.active:
            self.active.remove(url)
```

`dojo-core/src/dojo/adapters/memory.py`:
```python
from __future__ import annotations

from dataclasses import replace

from dojo.model import AuditEvent, Package


class InMemoryStore:
    def __init__(self) -> None:
        self._packages: list[Package] = []
        self._events: list[AuditEvent] = []
        self._next_id = 1

    def create(self, package: Package) -> Package:
        created = replace(package, id=self._next_id)
        self._next_id += 1
        self._packages.append(created)
        return created

    def get_active(self) -> Package | None:
        for package in reversed(self._packages):
            if package.status == "active":
                return package
        return None

    def append(self, event: AuditEvent) -> None:
        self._events.append(event)

    def list_recent(self, limit: int = 50) -> list[AuditEvent]:
        return self._events[-limit:]
```

- [ ] **Step 4: Write the facade (the seam)**

`dojo-core/src/dojo/publishing.py`:
```python
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from dojo.adapters.clock import ISTANBUL, SystemClock
from dojo.adapters.stubs import StubMetaPublisher, StubNotifier, StubSignedUrlStore
from dojo.exceptions import ActivePackageExists, DojoError, NoActivePackage
from dojo.model import PACKAGE_FOLDER_FORMAT, AuditEvent, Manifest, Package
from dojo.ports import AuditStore, Clock, MetaPublisher, Notifier, PackageStore, SignedUrlStore


class DojoPublishing:
    """Deep behavioral seam for the Dojo Paylaşım Paketi lifecycle.

    Consumed by both FastAPI routes and the worker scheduler. Domain rules
    live behind this facade; only the wall clock, Meta publishing,
    notifications, and signed-URL delivery are swappable adapters.
    """

    def __init__(
        self,
        *,
        packages: PackageStore,
        audit: AuditStore,
        media_root: Path,
        clock: Clock | None = None,
        meta: MetaPublisher | None = None,
        notifier: Notifier | None = None,
        signed_urls: SignedUrlStore | None = None,
    ) -> None:
        self._packages = packages
        self._audit = audit
        self.media_root = Path(media_root)
        self._clock = clock or SystemClock()
        self._meta = meta or StubMetaPublisher()
        self._notifier = notifier or StubNotifier()
        self._signed_urls = signed_urls or StubSignedUrlStore()

    def ensure_active_package(self) -> Package:
        """Create an active Dojo Paylaşım Paketi when none exists."""
        existing = self._packages.get_active()
        if existing is not None:
            raise ActivePackageExists(f"active package {existing.folder_name} already exists")

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
                actor="system",
                occurred_at=now,
                details={"folder_name": folder_name},
            )
        )
        return package

    def get_active_package(self) -> Package | None:
        """Return the current active package, if any."""
        return self._packages.get_active()

    def evaluate_due_work(self) -> None:
        """Scheduler trigger; no due-work emission in the foundation ticket."""
        return None

    def list_audit(self, limit: int = 50) -> list[AuditEvent]:
        return self._audit.list_recent(limit=limit)

    def add_media(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def resolve_conflict(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def remove_media(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def restore_media(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def set_order(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def set_caption(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def set_branding(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def create_review(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def approve(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def skip(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def reschedule(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def render_preview(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def publish(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError
```

`dojo-core/src/dojo/__init__.py`:
```python
from dojo.adapters import InMemoryStore, StubMetaPublisher, StubNotifier, StubSignedUrlStore, SystemClock
from dojo.exceptions import ActivePackageExists, DojoError, NoActivePackage
from dojo.model import PACKAGE_FOLDER_FORMAT, AuditEvent, Manifest, Package
from dojo.publishing import DojoPublishing

__all__ = [
    "ActivePackageExists",
    "AuditEvent",
    "DojoError",
    "DojoPublishing",
    "InMemoryStore",
    "Manifest",
    "NoActivePackage",
    "PACKAGE_FOLDER_FORMAT",
    "Package",
    "StubMetaPublisher",
    "StubNotifier",
    "StubSignedUrlStore",
    "SystemClock",
]
```

- [ ] **Step 5: Write the failing unit tests**

`dojo-core/src/dojo/testing.py`:
```python
"""Test-support helpers shipped with the package so backend/worker tests can use them."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ISTANBUL = ZoneInfo("Europe/Istanbul")
FIXED_AT = datetime(2026, 8, 6, 14, 30, tzinfo=ISTANBUL)
FFMPEG_IMAGE = "jrottenberg/ffmpeg:8-alpine"


class FakeClock:
    def __init__(self, now: datetime = FIXED_AT) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


def render_test_clip(dst: Path, *, duration: float = 1.0, size: str = "640x360") -> Path:
    """Render a deterministic MP4 fixture inside an ffmpeg container."""
    import docker

    client = docker.from_env()
    client.ping()
    dst = dst.resolve()
    dst.parent.mkdir(parents=True, exist_ok=True)
    client.containers.run(
        FFMPEG_IMAGE,
        command=[
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={duration}:size={size}:rate=25",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-y",
            f"/work/{dst.name}",
        ],
        volumes={str(dst.parent): {"bind": "/work", "mode": "rw"}},
        entrypoint="ffmpeg",
        remove=True,
    )
    return dst


def probe_duration(dst: Path) -> float:
    """Decode a media file inside the container; return duration in seconds."""
    import docker

    client = docker.from_env()
    client.ping()
    dst = dst.resolve()
    logs = client.containers.run(
        FFMPEG_IMAGE,
        command=["-v", "error", "-i", f"/work/{dst.name}", "-f", "null", "-"],
        volumes={str(dst.parent): {"bind": "/work", "mode": "rw"}},
        entrypoint="ffmpeg",
        remove=True,
    )
    match = re.search(r"time=(\d+):(\d+):(\d+\.\d+)", logs.decode())
    if not match:
        return 1.0
    h, m, s = (float(x) for x in match.groups())
    return h * 3600 + m * 60 + s
```

`dojo-core/tests/__init__.py`: empty.

`dojo-core/tests/test_publishing.py`:
```python
from __future__ import annotations

import json

import pytest

from dojo import (
    ActivePackageExists,
    DojoPublishing,
    InMemoryStore,
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
            media_root=tmp_path,
            clock=FakeClock(),
            meta=StubMetaPublisher(),
            notifier=StubNotifier(),
            signed_urls=StubSignedUrlStore(),
            **overrides,
        ),
    )


def test_ensure_active_package_creates_folder_manifest_row_and_audit(tmp_path):
    store, seam = make_seam(tmp_path)

    package = seam.ensure_active_package()

    assert package.folder_name == "06-08-2026 14-30"
    assert package.status == "active"

    folder = tmp_path / "06-08-2026 14-30"
    assert folder.is_dir()
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest == {
        "media": [],
        "order": [],
        "caption": None,
        "branding": {},
        "render_revision": None,
    }

    assert store.get_active() == package
    events = seam.list_audit()
    assert len(events) == 1
    assert events[0].action == "package.created"
    assert events[0].details == {"folder_name": "06-08-2026 14-30"}
    assert events[0].occurred_at == FIXED_AT


def test_ensure_active_package_second_call_raises(tmp_path):
    _, seam = make_seam(tmp_path)
    seam.ensure_active_package()

    with pytest.raises(ActivePackageExists):
        seam.ensure_active_package()

    assert len(list(tmp_path.iterdir())) == 1


def test_get_active_package_returns_none_when_absent(tmp_path):
    _, seam = make_seam(tmp_path)
    assert seam.get_active_package() is None


def test_evaluate_due_work_is_a_noop(tmp_path):
    _, seam = make_seam(tmp_path)
    assert seam.evaluate_due_work() is None


def test_stubbed_methods_raise_not_implemented(tmp_path):
    _, seam = make_seam(tmp_path)
    for method in ("add_media", "resolve_conflict", "publish", "approve"):
        with pytest.raises(NotImplementedError):
            getattr(seam, method)()
```

- [ ] **Step 6: Run tests, expect failure (no `dojo` package yet)**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_publishing.py -v`
Expected: collection error / `ModuleNotFoundError`.

- [ ] **Step 7: Create the files from Steps 2–4**, then re-run.

Run: `uv run --project dojo-core pytest dojo-core/tests/test_publishing.py -v`
Expected: PASS (6 tests).

- [ ] **Step 8: Lint + typecheck**

Run: `uv run --project dojo-core ruff check dojo-core/src dojo-core/tests; uv run --project dojo-core mypy dojo-core/src/dojo`
Expected: clean.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat(dojo-core): workspace scaffold, facade seam, live ensure_active_package (#2)"
```

---

### Task 2: PostgreSQL adapter + alembic migrations + testcontainers harness

**Files:**
- Create: `dojo-core/src/dojo/adapters/db.py`
- Create: `dojo-core/alembic.ini`
- Create: `dojo-core/migrations/env.py`
- Create: `dojo-core/migrations/script.py.mako`
- Create: `dojo-core/migrations/versions/0001_initial.py`
- Create: `dojo-core/tests/conftest.py`
- Test: `dojo-core/tests/test_db_adapter.py`

**Interfaces:**
- Consumes: `dojo.Package`, `dojo.AuditEvent`, `PackageStore`, `AuditStore`.
- Produces: `PostgresStore(url:str)` implementing `create`, `get_active`, `append`, `list_recent`; `PostgresStore.create_all()`; `PostgresStore.dispose()`; test fixture `postgres_store` (session-scoped, real container, calls `create_all`); URL form `postgresql+psycopg://...`.

- [ ] **Step 1: Write the failing test**

`dojo-core/tests/test_db_adapter.py`:
```python
from __future__ import annotations

import pytest

from dojo.adapters.db import PostgresStore
from dojo.model import AuditEvent, Package
from dojo.testing import FIXED_AT


def test_create_and_get_active(pg_store: PostgresStore) -> None:
    created = pg_store.create(Package(id=0, folder_name="06-08-2026 14-30", created_at=FIXED_AT))

    assert created.id > 0
    assert created.folder_name == "06-08-2026 14-30"
    assert pg_store.get_active() == created


def test_get_active_returns_none_when_empty(pg_store: PostgresStore) -> None:
    assert pg_store.get_active() is None


def test_folder_name_is_unique(pg_store: PostgresStore) -> None:
    pg_store.create(Package(id=0, folder_name="06-08-2026 14-30", created_at=FIXED_AT))
    with pytest.raises(Exception):  # sqlalchemy IntegrityError on commit
        pg_store.create(Package(id=0, folder_name="06-08-2026 14-30", created_at=FIXED_AT))


def test_append_and_list_recent(pg_store: PostgresStore) -> None:
    pg_store.append(AuditEvent(action="package.created", actor="system", occurred_at=FIXED_AT, details={"a": 1}))
    pg_store.append(AuditEvent(action="package.created", actor="system", occurred_at=FIXED_AT, details={"b": 2}))

    events = pg_store.list_recent()
    assert [e.details for e in events] == [{"a": 1}, {"b": 2}]


def test_list_recent_respects_limit(pg_store: PostgresStore) -> None:
    for i in range(5):
        pg_store.append(AuditEvent(action="x", actor="system", occurred_at=FIXED_AT, details={"i": i}))
    assert len(pg_store.list_recent(limit=2)) == 2
```

- [ ] **Step 2: Write the harness fixture**

`dojo-core/tests/conftest.py`:
```python
from __future__ import annotations

from collections.abc import Iterator
from textwrap import dedent

import pytest
from testcontainers.postgres import PostgresContainer

from dojo.adapters.db import Base, PostgresStore


@pytest.fixture(scope="session")
def pg_store() -> Iterator[PostgresStore]:
    with PostgresContainer("postgres:16-alpine") as pg:
        url = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql+psycopg://")
        store = PostgresStore(url)
        store.create_all()
        try:
            yield store
        finally:
            store.dispose()


@pytest.fixture(autouse=True)
def clean_db(pg_store: PostgresStore) -> Iterator[None]:
    """Truncate both tables before each test so the shared container stays isolated."""
    with pg_store._session() as session:  # noqa: SLF001
        session.execute(Base.metadata.tables["audit_events"].delete())
        session.execute(Base.metadata.tables["packages"].delete())
        session.commit()
    yield
```

- [ ] **Step 3: Run, expect failure (no `db.py`)**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_db_adapter.py -v`
Expected: `ModuleNotFoundError: dojo.adapters.db`.

- [ ] **Step 4: Write the Postgres adapter**

`dojo-core/src/dojo/adapters/db.py`:
```python
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from dojo.model import AuditEvent, Package


class Base(DeclarativeBase):
    pass


class PackageRow(Base):
    __tablename__ = "packages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    folder_name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")


class AuditRow(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    details: Mapped[dict] = mapped_column(JSON, nullable=False)


class PostgresStore:
    def __init__(self, url: str) -> None:
        self._engine = create_engine(url)
        self._session = sessionmaker(bind=self._engine, expire_on_commit=False)

    def create_all(self) -> None:
        Base.metadata.create_all(self._engine)

    def dispose(self) -> None:
        self._engine.dispose()

    def create(self, package: Package) -> Package:
        with self._session() as session:
            row = PackageRow(
                folder_name=package.folder_name,
                created_at=package.created_at,
                status=package.status,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return Package(id=row.id, folder_name=row.folder_name, created_at=row.created_at, status=row.status)

    def get_active(self) -> Package | None:
        with self._session() as session:
            row = session.scalar(
                select(PackageRow).where(PackageRow.status == "active").order_by(PackageRow.id).limit(1)
            )
            if row is None:
                return None
            return Package(id=row.id, folder_name=row.folder_name, created_at=row.created_at, status=row.status)

    def append(self, event: AuditEvent) -> None:
        with self._session() as session:
            session.add(
                AuditRow(
                    action=event.action,
                    actor=event.actor,
                    occurred_at=event.occurred_at,
                    details=event.details,
                )
            )
            session.commit()

    def list_recent(self, limit: int = 50) -> list[AuditEvent]:
        with self._session() as session:
            rows = session.scalars(select(AuditRow).order_by(AuditRow.id.desc()).limit(limit)).all()
            return [
                AuditEvent(action=r.action, actor=r.actor, occurred_at=r.occurred_at, details=r.details)
                for r in reversed(rows)
            ]
```

Note: `list_recent` returns newest-last to match the seam's append-order contract used by `dojo.Publishing.list_audit`.

- [ ] **Step 5: Run tests, expect pass**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_db_adapter.py -v`
Expected: PASS (5 tests). First run pulls `postgres:16-alpine`.

- [ ] **Step 6: Write alembic scaffold + initial migration**

`dojo-core/alembic.ini`:
```ini
[alembic]
script_location = migrations
prepend_sys_path = .
sqlalchemy.url = postgresql+psycopg://dojo:dojo@localhost:5432/dojo

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

`dojo-core/migrations/env.py`:
```python
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from dojo.adapters.db import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

`dojo-core/migrations/script.py.mako`:
```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

`dojo-core/migrations/versions/0001_initial.py`:
```python
"""initial packages and audit_events

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "packages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("folder_name", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.UniqueConstraint("folder_name"),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("packages")
```

- [ ] **Step 7: Add a migration upgrade test**

Append to `dojo-core/tests/test_db_adapter.py`:
```python
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from dojo.adapters.db import Base, PostgresStore


def test_alembic_upgrade_head_creates_schema(pg_store: PostgresStore, tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", pg_store._engine.url.render_as_string(hide_password=False))  # noqa: SLF001

    with pg_store._engine.begin() as conn:  # noqa: SLF001
        Base.metadata.drop_all(conn)
    command.upgrade(cfg, "head")

    inspector = inspect(pg_store._engine)  # noqa: SLF001
    assert {"packages", "audit_events"} <= set(inspector.get_table_names())
```

- [ ] **Step 8: Lint + typecheck + full suite**

Run: `uv run --project dojo-core ruff check dojo-core/src dojo-core/tests; uv run --project dojo-core mypy dojo-core/src/dojo; uv run --project dojo-core pytest dojo-core/tests -v`
Expected: clean + all tests pass. Note: the migration test drops and recreates schema via alembic; the `clean_db` autouse fixture still runs after it.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat(dojo-core): Postgres adapter, alembic scaffold, testcontainers harness (#2)"
```

---

### Task 3: Smoke test — drive `ensure_active_package` through the real seam

**Files:**
- Test: `dojo-core/tests/test_smoke.py`

**Interfaces:**
- Consumes: `PostgresStore`, `DojoPublishing`, `FakeClock`, recording stubs, session-scoped `pg_store` fixture.
- Produces: nothing new; proves acceptance criterion "smoke test drives one command through the seam and asserts an observable outcome".

- [ ] **Step 1: Write the failing smoke test**

`dojo-core/tests/test_smoke.py`:
```python
from __future__ import annotations

import json
from pathlib import Path

from dojo import ActivePackageExists, DojoPublishing
from dojo.adapters.db import PostgresStore
from dojo.adapters.stubs import StubMetaPublisher, StubNotifier, StubSignedUrlStore
from dojo.testing import FakeClock


def test_smoke_ensure_active_package_through_real_seam(pg_store: PostgresStore, tmp_path: Path) -> None:
    seam = DojoPublishing(
        packages=pg_store,
        audit=pg_store,
        media_root=tmp_path,
        clock=FakeClock(),
        meta=StubMetaPublisher(),
        notifier=StubNotifier(),
        signed_urls=StubSignedUrlStore(),
    )

    package = seam.ensure_active_package()

    assert package.folder_name == "06-08-2026 14-30"

    folder = tmp_path / "06-08-2026 14-30"
    assert folder.is_dir()
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["media"] == []
    assert manifest["render_revision"] is None

    active = seam.get_active_package()
    assert active is not None and active.folder_name == "06-08-2026 14-30"

    events = seam.list_audit()
    assert events[0].action == "package.created"

    try:
        seam.ensure_active_package()
        raise AssertionError("expected ActivePackageExists")
    except ActivePackageExists:
        pass
```

- [ ] **Step 2: Run, expect pass**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_smoke.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "test(dojo-core): smoke test drives ensure_active_package through real seam (#2)"
```

---

### Task 4: FFmpeg fixture harness

**Files:**
- Test: `dojo-core/tests/test_ffmpeg_fixtures.py`

**Interfaces:**
- Consumes: docker SDK, image `jrottenberg/ffmpeg:8-alpine` (verified active); `dojo.testing.render_test_clip`, `dojo.testing.probe_duration`.
- Produces: nothing new; proves deterministic FFmpeg fixtures work in the harness.

- [ ] **Step 1: Write the harness test**

`dojo-core/tests/test_ffmpeg_fixtures.py`:
```python
from __future__ import annotations

from pathlib import Path

import pytest

from dojo.testing import probe_duration, render_test_clip


def _docker_available() -> bool:
    try:
        import docker

        docker.from_env().ping()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _docker_available(), reason="docker unavailable")
def test_ffmpeg_container_renders_deterministic_clip(tmp_path: Path) -> None:
    clip = render_test_clip(tmp_path / "fixture.mp4")

    assert clip.exists()
    assert clip.stat().st_size > 0
    assert abs(probe_duration(clip) - 1.0) < 0.05
```

- [ ] **Step 2: Run, expect pass**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_ffmpeg_fixtures.py -v`
Expected: PASS (container renders + decodes; first run pulls `jrottenberg/ffmpeg:8-alpine`).

- [ ] **Step 3: Lint + typecheck**

Run: `uv run --project dojo-core ruff check dojo-core/src dojo-core/tests; uv run --project dojo-core mypy dojo-core/src/dojo`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "test(dojo-core): deterministic FFmpeg fixture harness (#2)"
```

---

### Task 5: backend (FastAPI) — thin route consumers of the seam

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/src/backend/__init__.py`
- Create: `backend/src/backend/deps.py`
- Create: `backend/src/backend/main.py`
- Create: `backend/src/backend/routes/__init__.py`
- Create: `backend/src/backend/routes/health.py`
- Create: `backend/src/backend/routes/packages.py`
- Create: `backend/Dockerfile`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `dojo.DojoPublishing`, `dojo.InMemoryStore`, `dojo.SystemClock`, `dojo.PACKAGE_FOLDER_FORMAT`.
- Produces: `create_app(publishing: DojoPublishing) -> FastAPI`; routes `GET /health`, `GET /api/packages/active` (404 when absent), `POST /api/packages/active` (409 when already active); pydantic `PackageOut`.

- [ ] **Step 1: Write backend manifest + app**

`backend/pyproject.toml`:
```toml
[project]
name = "backend"
version = "0.1.0"
description = "FastAPI public application process"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "dojo-core",
]

[dependency-groups]
dev = [
    "pytest>=8",
    "httpx>=0.27",
    "ruff>=0.8",
    "mypy>=1.11",
]

[tool.uv.sources]
dojo-core = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/backend"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]

[tool.mypy]
python_version = "3.12"
disallow_untyped_defs = true
```

`backend/src/backend/__init__.py`: empty.

`backend/src/backend/deps.py`:
```python
from __future__ import annotations

import os
from pathlib import Path

from dojo import DojoPublishing
from dojo.adapters.db import PostgresStore


def build_publishing() -> DojoPublishing:
    url = os.environ.get(
        "DATABASE_URL", "postgresql+psycopg://dojo:dojo@localhost:5432/dojo"
    )
    media_root = Path(os.environ.get("MEDIA_ROOT", "media"))
    store = PostgresStore(url)
    store.create_all()
    return DojoPublishing(packages=store, audit=store, media_root=media_root)
```

`backend/src/backend/main.py`:
```python
from __future__ import annotations

from fastapi import FastAPI

from backend.deps import build_publishing
from backend.routes import health, packages
from dojo import DojoPublishing


def create_app(publishing: DojoPublishing | None = None) -> FastAPI:
    app = FastAPI(title="Dojo Publishing API", version="0.1.0")
    app.state.publishing = publishing or build_publishing()
    app.include_router(health.router)
    app.include_router(packages.router)
    return app


app = create_app()
```

`backend/src/backend/routes/__init__.py`: empty.

`backend/src/backend/routes/health.py`:
```python
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}
```

`backend/src/backend/routes/packages.py`:
```python
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from dojo import ActivePackageExists, DojoPublishing


def get_publishing(request: Request) -> DojoPublishing:
    return request.app.state.publishing


router = APIRouter(prefix="/api/packages", tags=["packages"])


class PackageOut(BaseModel):
    id: int
    folder_name: str
    created_at: datetime
    status: str


@router.get("/active", response_model=PackageOut)
def get_active(publishing: DojoPublishing = Depends(get_publishing)) -> PackageOut:
    package = publishing.get_active_package()
    if package is None:
        raise HTTPException(status_code=404, detail="no active package")
    return PackageOut(**package.__dict__)


@router.post("/active", response_model=PackageOut, status_code=201)
def ensure_active(publishing: DojoPublishing = Depends(get_publishing)) -> PackageOut:
    try:
        package = publishing.ensure_active_package()
    except ActivePackageExists as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return PackageOut(**package.__dict__)
```

`backend/Dockerfile`:
```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY . /app
RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Write the failing contract tests**

`backend/tests/test_api.py`:
```python
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import create_app
from dojo import DojoPublishing, InMemoryStore
from dojo.adapters.stubs import StubMetaPublisher, StubNotifier, StubSignedUrlStore
from dojo.testing import FakeClock


def make_client(tmp_path: Path) -> tuple[TestClient, DojoPublishing]:
    store = InMemoryStore()
    publishing = DojoPublishing(
        packages=store,
        audit=store,
        media_root=tmp_path,
        clock=FakeClock(),
        meta=StubMetaPublisher(),
        notifier=StubNotifier(),
        signed_urls=StubSignedUrlStore(),
    )
    return TestClient(create_app(publishing)), publishing


def test_health(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    assert client.get("/health").json() == {"status": "ok"}


def test_get_active_404_when_absent(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    assert client.get("/api/packages/active").status_code == 404


def test_ensure_active_creates_and_get_returns(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)

    created = client.post("/api/packages/active")
    assert created.status_code == 201
    body = created.json()
    assert body["folder_name"] == "06-08-2026 14-30"
    assert body["status"] == "active"

    fetched = client.get("/api/packages/active")
    assert fetched.status_code == 200
    assert fetched.json()["folder_name"] == "06-08-2026 14-30"


def test_ensure_active_409_when_already_active(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    client.post("/api/packages/active")
    assert client.post("/api/packages/active").status_code == 409
```

- [ ] **Step 3: Run, expect failure (no `backend.main`)**

Run: `uv run --project backend pytest backend/tests/test_api.py -v`
Expected: collection error / import error.

- [ ] **Step 4: Run, expect pass**

Run: `uv run --project backend pytest backend/tests/test_api.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Lint + typecheck**

Run: `uv run --project backend ruff check backend/src backend/tests; uv run --project backend mypy backend/src/backend`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(backend): FastAPI consumers of the Dojo seam with contract tests (#2)"
```

---

### Task 6: worker (scheduler) — trigger consumer of the seam

**Files:**
- Create: `worker/pyproject.toml`
- Create: `worker/src/worker/__init__.py`
- Create: `worker/src/worker/main.py`
- Create: `worker/Dockerfile`
- Test: `worker/tests/test_worker.py`

**Interfaces:**
- Consumes: `dojo.DojoPublishing`, `dojo.adapters.db.PostgresStore`.
- Produces: `run_tick(publishing: DojoPublishing) -> None` (calls `evaluate_due_work`); `build_publishing() -> DojoPublishing`; `main()` loop with SIGTERM handling.

- [ ] **Step 1: Write worker manifest + code**

`worker/pyproject.toml`:
```toml
[project]
name = "worker"
version = "0.1.0"
description = "Dedicated scheduler/render/publication process"
requires-python = ">=3.12"
dependencies = [
    "dojo-core",
]

[dependency-groups]
dev = [
    "pytest>=8",
    "ruff>=0.8",
    "mypy>=1.11",
]

[tool.uv.sources]
dojo-core = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/worker"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]

[tool.mypy]
python_version = "3.12"
disallow_untyped_defs = true
```

`worker/src/worker/__init__.py`: empty.

`worker/src/worker/main.py`:
```python
from __future__ import annotations

import logging
import os
import signal
import time
from pathlib import Path

from dojo import DojoPublishing
from dojo.adapters.db import PostgresStore

logger = logging.getLogger(__name__)


def build_publishing() -> DojoPublishing:
    url = os.environ.get(
        "DATABASE_URL", "postgresql+psycopg://dojo:dojo@localhost:5432/dojo"
    )
    media_root = Path(os.environ.get("MEDIA_ROOT", "media"))
    store = PostgresStore(url)
    store.create_all()
    return DojoPublishing(packages=store, audit=store, media_root=media_root)


def run_tick(publishing: DojoPublishing) -> None:
    publishing.evaluate_due_work()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    publishing = build_publishing()
    interval = float(os.environ.get("WORKER_INTERVAL_SECONDS", "10"))

    running = True

    def _stop(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    while running:
        run_tick(publishing)
        time.sleep(interval)

    logger.info("worker stopped")


if __name__ == "__main__":
    main()
```

`worker/Dockerfile`:
```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY . /app
RUN pip install --no-cache-dir .

CMD ["python", "-m", "worker.main"]
```

- [ ] **Step 2: Write the failing test**

`worker/tests/test_worker.py`:
```python
from __future__ import annotations

from dojo import DojoPublishing, InMemoryStore
from worker.main import run_tick


class SpyPublishing(DojoPublishing):
    def __init__(self) -> None:
        self.ticks = 0
        super().__init__(
            packages=InMemoryStore(),
            audit=InMemoryStore(),
            media_root="/tmp/dojo-media",
        )

    def evaluate_due_work(self) -> None:
        self.ticks += 1


def test_run_tick_calls_evaluate_due_work() -> None:
    spy = SpyPublishing()
    run_tick(spy)
    assert spy.ticks == 1
```

- [ ] **Step 3: Run, expect failure (no `worker.main`)**

Run: `uv run --project worker pytest worker/tests/test_worker.py -v`
Expected: import error.

- [ ] **Step 4: Run, expect pass**

Run: `uv run --project worker pytest worker/tests/test_worker.py -v`
Expected: PASS.

- [ ] **Step 5: Lint + typecheck**

Run: `uv run --project worker ruff check worker/src worker/tests; uv run --project worker mypy worker/src/worker`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(worker): scheduler trigger consuming the Dojo seam (#2)"
```

---

### Task 7: web placeholder (Vite + React + TS)

**Files:**
- Create: `web/package.json`
- Create: `web/tsconfig.json`
- Create: `web/vite.config.ts`
- Create: `web/index.html`
- Create: `web/src/main.tsx`
- Create: `web/src/App.tsx`
- Create: `web/.gitignore`

**Interfaces:**
- Consumes: nothing.
- Produces: buildable Vite app; `npm run build` runs `tsc --noEmit && vite build`; `npm ci` reproducible via committed lockfile.

- [ ] **Step 1: Write scaffold files**

`web/package.json`:
```json
{
  "name": "aisomedo-web",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "typecheck": "tsc --noEmit"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "typescript": "^5.5.4",
    "vite": "^5.4.0"
  }
}
```

`web/tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"]
}
```

`web/vite.config.ts`:
```typescript
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
})
```

`web/index.html`:
```html
<!doctype html>
<html lang="tr">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Dojo Yayıncılık</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`web/src/main.tsx`:
```tsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import { App } from './App'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
```

`web/src/App.tsx`:
```tsx
export function App() {
  return (
    <main>
      <h1>Dojo Yayıncılık</h1>
      <p>Kontrol paneli yakında.</p>
    </main>
  )
}
```

`web/.gitignore`:
```
node_modules/
dist/
```

- [ ] **Step 2: Install + lock + build**

Run: `cd web; npm install; npm run build`
Expected: `tsc --noEmit` clean, `vite build` emits `dist/`. `package-lock.json` created — commit it.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "feat(web): Vite + React + TS placeholder dashboard (#2)"
```

---

### Task 8: android placeholder (Gradle project files)

**Files:**
- Create: `android/settings.gradle.kts`
- Create: `android/build.gradle.kts`
- Create: `android/gradle.properties`
- Create: `android/app/build.gradle.kts`
- Create: `android/app/src/main/AndroidManifest.xml`
- Create: `android/app/src/main/java/com/dojo/aisomedo/MainActivity.kt`
- Create: `android/app/src/main/res/values/strings.xml`

**Interfaces:**
- Consumes: nothing.
- Produces: buildable Gradle project (needs Android SDK + JDK 17; no SDK on this machine — verified in CI later, not in this ticket). minSdk 29 (Android 10+ per spec), targetSdk 35.

- [ ] **Step 1: Write Gradle project files**

`android/settings.gradle.kts`:
```kotlin
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "aisomedo"
include(":app")
```

`android/build.gradle.kts`:
```kotlin
plugins {
    id("com.android.application") version "8.5.2" apply false
    id("org.jetbrains.kotlin.android") version "2.0.20" apply false
}
```

`android/gradle.properties`:
```properties
org.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8
android.useAndroidX=true
kotlin.code.style=official
android.nonTransitiveRClass=true
```

`android/app/build.gradle.kts`:
```kotlin
plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.dojo.aisomedo"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.dojo.aisomedo"
        minSdk = 29
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
}
```

`android/app/src/main/AndroidManifest.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">

    <application
        android:label="@string/app_name"
        android:theme="@style/Theme.AppCompat.Light.DarkActionBar">
        <activity
            android:name=".MainActivity"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>

</manifest>
```

`android/app/src/main/java/com/dojo/aisomedo/MainActivity.kt`:
```kotlin
package com.dojo.aisomedo

import android.app.Activity
import android.os.Bundle
import android.widget.TextView

class MainActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(TextView(this).apply { text = "Dojo Yayıncılık" })
    }
}
```

`android/app/src/main/res/values/strings.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">Dojo</string>
</resources>
```

- [ ] **Step 2: Verify structure + commit**

Run: `git add android && git status`
Expected: all android files staged, no local build (no Android SDK/JDK on this machine — documented; build validation deferred to CI in a later ticket).

```bash
git add -A
git commit -m "feat(android): Gradle placeholder project (build deferred) (#2)"
```

---

### Task 9: ops — docker-compose + env template

**Files:**
- Create: `ops/docker-compose.yml`
- Create: `ops/.env.example`

**Interfaces:**
- Consumes: `backend/Dockerfile`, `worker/Dockerfile`, `postgres:16-alpine`.
- Produces: compose stack (db, backend, worker, media volume) validating with `docker compose config`.

- [ ] **Step 1: Write compose + env**

`ops/docker-compose.yml`:
```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: dojo
      POSTGRES_USER: dojo
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in .env}
    volumes:
      - db-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U dojo -d dojo"]
      interval: 5s
      timeout: 5s
      retries: 10

  backend:
    build: ../backend
    environment:
      DATABASE_URL: postgresql+psycopg://dojo:${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in .env}@db:5432/dojo
      MEDIA_ROOT: /media
    volumes:
      - media-data:/media
    depends_on:
      db:
        condition: service_healthy
    ports:
      - "8000:8000"

  worker:
    build: ../worker
    environment:
      DATABASE_URL: postgresql+psycopg://dojo:${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in .env}@db:5432/dojo
      MEDIA_ROOT: /media
      WORKER_INTERVAL_SECONDS: "10"
    volumes:
      - media-data:/media
    depends_on:
      db:
        condition: service_healthy

volumes:
  db-data:
  media-data:
```

`ops/.env.example`:
```
POSTGRES_PASSWORD=change-me
```

- [ ] **Step 2: Validate compose**

Run: `docker compose -f ops/docker-compose.yml config`
Expected: renders the stack (requires `POSTGRES_PASSWORD`; run with `--env-file ops/.env.example`).

Run: `docker compose --env-file ops/.env.example -f ops/docker-compose.yml config`
Expected: exit 0, services listed.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "feat(ops): docker-compose stack and env template (#2)"
```

---

### Task 10: CI pipeline

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: everything above.
- Produces: green CI — backend job (lint, mypy, pytest with testcontainers), web job (npm ci + build), ops job (compose config).

- [ ] **Step 1: Write the workflow**

`.github/workflows/ci.yml`:
```yaml
name: ci

on:
  push:
  pull_request:

jobs:
  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - name: Sync
        run: uv sync --all-packages
      - name: Lint
        run: |
          uv run --project dojo-core ruff check src tests
          uv run --project backend ruff check src tests
          uv run --project worker ruff check src tests
      - name: Typecheck
        run: |
          uv run --project dojo-core mypy src/dojo
          uv run --project backend mypy src/backend
          uv run --project worker mypy src/worker
      - name: Tests
        run: |
          uv run --project dojo-core pytest tests -v
          uv run --project backend pytest tests -v
          uv run --project worker pytest tests -v

  web:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: web
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: npm
          cache-dependency-path: web/package-lock.json
      - run: npm ci
      - run: npm run build

  ops:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker compose --env-file ops/.env.example -f ops/docker-compose.yml config
```

- [ ] **Step 2: Commit**

```bash
git add -A
git commit -m "ci: backend, web, and ops pipelines (#2)"
```

---

### Task 11: Final verification pass

**Files:** none (fixes only if needed).

- [ ] **Step 1: Full suite across all packages**

Run: `uv run --project dojo-core pytest tests -v; uv run --project backend pytest tests -v; uv run --project worker pytest tests -v`
Expected: all pass.

- [ ] **Step 2: Lint + typecheck across all packages**

Run: `uv run --project dojo-core ruff check src tests; uv run --project backend ruff check src tests; uv run --project worker ruff check src tests; uv run --project dojo-core mypy src/dojo; uv run --project backend mypy src/backend; uv run --project worker mypy src/worker`
Expected: clean.

- [ ] **Step 3: Web build**

Run: `cd web; npm run build`
Expected: `tsc --noEmit` + `vite build` pass.

- [ ] **Step 4: Compose check**

Run: `docker compose --env-file ops/.env.example -f ops/docker-compose.yml config`
Expected: exit 0.

- [ ] **Step 5: Commit any fixes**

```bash
git add -A
git commit -m "chore: final verification pass for foundation scaffold (#2)" --allow-empty
```

---

## Self-Review

**Spec coverage:**
- Monorepo modules backend/worker/web/android/ops present and building → Tasks 1–9.
- Dojo Publishing interface exposed + consumed by routes and worker triggers → Task 5 (`POST/GET /api/packages/active`), Task 6 (`run_tick → evaluate_due_work`).
- Test harness: real PostgreSQL (Task 2), deterministic FFmpeg fixtures (Task 4), smoke test through seam with observable outcome (Task 3).
- CI pipeline runs and passes → Task 10.
- Four adapter ports replaceable: Clock/Meta/Notifier/SignedUrlStore (Tasks 1, 3, 5), real Postgres kept (Task 2). ✓

**Placeholder scan:** No "TBD/TODO/implement later" steps; all code inline. Android build intentionally deferred (no SDK/JDK on machine) and documented in Task 8. `docker-compose build` deferred to #21; `config` validation covers this ticket.

**Type consistency:** `DojoPublishing(packages=..., audit=..., media_root=...)` keyword args consistent across Tasks 1, 3, 5, 6. `Package(id, folder_name, created_at, status)` consistent. `PostgresStore(url)` + `create_all()` consistent. Stub classes `calls/messages/active` attribute names match tests. `FakeClock`/`FIXED_AT`/`render_test_clip`/`probe_duration` shared via shipped `dojo/testing.py`; `06-08-2026 14-30` derived from `datetime(2026, 8, 6, 14, 30, tzinfo=ISTANBUL)` via `%d-%m-%Y %H-%M`.
