# Dojo Yayın Planı and Manual Publication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the recurring `Dojo Yayın Planı` (biweekly Mondays in `Europe/Istanbul`), editable plan settings, and a manual publish action that emits a due `Yayın Zamanı` slot without shifting the recurring anchor, for issue #13.

**Architecture:** Extend the deep `DojoPublishing` facade (`dojo/publishing.py`) — same as #6/#10/#11. Plan config lives in `SettingsStore` under `schedule.*`; concrete due slots persist in a new `yayin_zamani` table behind a new `ScheduleStore` port (migration `0007`). `evaluate_due_work()` lazily backfills alternate-Monday rows up to `now` and guarantees exactly one future row (Plan C). `manual_publish()` inserts a single due-now `manual` row, rejected while one is pending. This ticket emits due slots only; `Yayın İncelemesi` creation stays in #14.

**Tech Stack:** Python 3.12 (uv workspace), FastAPI, SQLAlchemy, alembic, pytest, ruff, mypy. Domain tests via the in-memory seam with `FakeClock`; contract tests via FastAPI `TestClient`.

## Global Constraints

- Python `requires-python = ">=3.12"`.
- Domain vocabulary from `CONTEXT.md`: `Dojo Yayın Planı`, `Yayın Zamanı`. No new domain nouns.
- One primary seam: `DojoPublishing` in `dojo/publishing.py`. Tests assert externally visible outcomes, not SQL or private call order.
- Recurring plan config in `SettingsStore` keys: `schedule.enabled` (bool), `schedule.anchor_date` (`YYYY-MM-DD`), `schedule.anchor_time` (`HH:MM`).
- Concrete slots in new table `yayin_zamani`; row `kind` is `"regular"` (biweekly Monday) or `"manual"` (one-off). Manual rows never shift the anchor.
- Timezone fixed to `Europe/Istanbul` (`ISTANBUL` from `dojo/adapters/clock.py`). Occurrences stored tz-aware.
- Anchor must be a Monday (`date.weekday() == 0`); otherwise `PlanInvalid`.
- Manual publish: single pending `manual` slot allowed; a second while pending raises `ManualPublishConflict`. Independent of `enabled`.
- Materialization (Plan C): `evaluate_due_work()`/`ensure_schedule_upto(now)` backfills every occurrence from the anchor up to `now`, then guarantees exactly one future row (next Monday after `now`). Idempotent across restarts and anchor edits.
- Boundary: this ticket emits due slots only; #14 creates `Yayın İncelemesi`.
- Routes behind `get_current_client`; equal privilege; unauth → 401.
- Lint: ruff (`E,F,I,UP`). dojo-core mypy `disallow_untyped_defs`; backend mypy `strict`.
- Commands run from repo root. Tests use `FakeClock` for deterministic time.
- Every Python task: run the focused test file first, then the package's full suite, before committing.

---

### Task 1: Models and exceptions for the schedule seam

**Files:**
- Modify: `dojo-core/src/dojo/model.py`
- Modify: `dojo-core/src/dojo/exceptions.py`
- Modify: `dojo-core/src/dojo/__init__.py`
- Test: `dojo-core/tests/test_schedule_models.py`

**Interfaces:**
- Consumes: nothing new.
- Produces (imported by Tasks 2–5):
  - `SchedulePlan(anchor_date: date | None, anchor_time: time | None, enabled: bool, timezone: str)` with `.to_dict()`.
  - `YayinZamani(id: int, kind: str, due_at: datetime, status: str, created_at: datetime, resolved_at: datetime | None)`.
  - Exceptions `PlanInvalid(DojoError)`, `ManualPublishConflict(DojoError)`.
  - Exported from `dojo/__init__.py`.

- [ ] **Step 1: Write the failing tests**

Create `dojo-core/tests/test_schedule_models.py`:
```python
from __future__ import annotations

from datetime import date, time

from dojo import ManualPublishConflict, PlanInvalid, SchedulePlan, YayinZamani
from dojo.exceptions import DojoError
from dojo.testing import FIXED_AT


def test_schedule_plan_to_dict() -> None:
    plan = SchedulePlan(
        anchor_date=date(2026, 8, 3),
        anchor_time=time(10, 0),
        enabled=True,
    )
    assert plan.to_dict() == {
        "anchor_date": "2026-08-03",
        "anchor_time": "10:00:00",
        "enabled": True,
        "timezone": "Europe/Istanbul",
    }


def test_schedule_plan_defaults() -> None:
    plan = SchedulePlan()
    assert plan.anchor_date is None
    assert plan.anchor_time is None
    assert plan.enabled is True


def test_exceptions_are_dojo_errors() -> None:
    assert issubclass(PlanInvalid, DojoError)
    assert issubclass(ManualPublishConflict, DojoError)


def test_yayin_zamani_defaults() -> None:
    occ = YayinZamani(
        id=1, kind="regular", due_at=FIXED_AT, status="pending", created_at=FIXED_AT
    )
    assert occ.resolved_at is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_schedule_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'SchedulePlan' from 'dojo'`.

- [ ] **Step 3: Add models**

Append to `dojo-core/src/dojo/model.py` (after `MontageStatus`), and add `from datetime import date, time` to its imports:
```python
@dataclass(frozen=True)
class SchedulePlan:
    anchor_date: date | None = None
    anchor_time: time | None = None
    enabled: bool = True
    timezone: str = "Europe/Istanbul"

    def to_dict(self) -> dict:
        return {
            "anchor_date": self.anchor_date.isoformat() if self.anchor_date else None,
            "anchor_time": self.anchor_time.isoformat() if self.anchor_time else None,
            "enabled": self.enabled,
            "timezone": self.timezone,
        }


@dataclass(frozen=True)
class YayinZamani:
    id: int
    kind: str
    due_at: datetime
    status: str
    created_at: datetime
    resolved_at: datetime | None = None
```

- [ ] **Step 4: Add exceptions**

Append to `dojo-core/src/dojo/exceptions.py`:
```python
class PlanInvalid(DojoError):
    pass


class ManualPublishConflict(DojoError):
    pass
```

- [ ] **Step 5: Export from `__init__.py`**

In `dojo-core/src/dojo/__init__.py`, add `ManualPublishConflict`, `PlanInvalid` to the `from dojo.exceptions import (...)` block, add `SchedulePlan`, `YayinZamani` to the `from dojo.model import (...)` block, and add all four to `__all__`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_schedule_models.py -v`
Expected: PASS.

- [ ] **Step 7: Typecheck, full suite, commit**

Run: `uv run --project dojo-core mypy dojo-core/src/dojo; uv run --project dojo-core pytest dojo-core/tests -v`
Expected: pass

```bash
git add dojo-core/src/dojo/model.py dojo-core/src/dojo/exceptions.py dojo-core/src/dojo/__init__.py dojo-core/tests/test_schedule_models.py
git commit -m "feat(dojo-core): schedule models and exceptions (#13)"
```

---

### Task 2: ScheduleStore port and `yayin_zamani` migration

**Files:**
- Modify: `dojo-core/src/dojo/ports.py`
- Create: `dojo-core/migrations/versions/0007_yayin_zamani.py`
- Modify: `dojo-core/src/dojo/adapters/db.py` (add `YayinZamaniRow`)

**Interfaces:**
- Consumes: Task 1 `YayinZamani`.
- Produces (consumed by Tasks 3–5):
  - `ScheduleStore` protocol with methods:
    - `create(occurrence: YayinZamani) -> YayinZamani`
    - `max_regular_due_at() -> datetime | None`
    - `has_regular_at(due_at: datetime) -> bool`
    - `has_pending_manual() -> bool`
    - `list_due(now: datetime) -> list[YayinZamani]`
    - `list_all() -> list[YayinZamani]`

- [ ] **Step 1: Add the port**

In `dojo-core/src/dojo/ports.py`, add `YayinZamani` to the `from dojo.model import (...)` block, then append after `SettingsStore`:
```python
@runtime_checkable
class ScheduleStore(Protocol):
    def create(self, occurrence: YayinZamani) -> YayinZamani: ...
    def max_regular_due_at(self) -> datetime | None: ...
    def has_regular_at(self, due_at: datetime) -> bool: ...
    def has_pending_manual(self) -> bool: ...
    def list_due(self, now: datetime) -> list[YayinZamani]: ...
    def list_all(self) -> list[YayinZamani]: ...
```

- [ ] **Step 2: Add the ORM row**

In `dojo-core/src/dojo/adapters/db.py`, add `YayinZamani` to the `from dojo.model import (...)` block, then append after `SettingRow`:
```python
class YayinZamaniRow(Base):
    __tablename__ = "yayin_zamani"
    __table_args__ = (Index("ix_yayin_zamani_status_due", "status", "due_at"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 3: Create the migration**

Create `dojo-core/migrations/versions/0007_yayin_zamani.py`:
```python
"""yayin_zamani schedule occurrences table

Revision ID: 0007_yayin_zamani
Revises: 0006_conflict_resolution
Create Date: 2026-08-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_yayin_zamani"
down_revision: Union[str, None] = "0006_conflict_resolution"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "yayin_zamani",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_yayin_zamani_status_due", "yayin_zamani", ["status", "due_at"])


def downgrade() -> None:
    op.drop_index("ix_yayin_zamani_status_due", table_name="yayin_zamani")
    op.drop_table("yayin_zamani")
```

- [ ] **Step 4: Verify imports/typecheck**

Run: `uv run --project dojo-core mypy dojo-core/src/dojo`
Expected: no findings. (No runtime behavior yet — methods land in Task 3.)

- [ ] **Step 5: Commit**

```bash
git add dojo-core/src/dojo/ports.py dojo-core/src/dojo/adapters/db.py dojo-core/migrations/versions/0007_yayin_zamani.py
git commit -m "feat(dojo-core): schedule store port and yayin_zamani migration (#13)"
```

---

### Task 3: ScheduleStore implementations (memory + postgres)

**Files:**
- Modify: `dojo-core/src/dojo/adapters/memory.py`
- Modify: `dojo-core/src/dojo/adapters/db.py`
- Test: `dojo-core/tests/test_store_schedule.py`

**Interfaces:**
- Consumes: Task 1 `YayinZamani`; Task 2 `ScheduleStore` protocol + `YayinZamaniRow`.
- Produces: `InMemoryStore` and `PostgresStore` both satisfy `ScheduleStore`.

- [ ] **Step 1: Write the failing tests**

Create `dojo-core/tests/test_store_schedule.py`:
```python
from __future__ import annotations

from datetime import datetime, timedelta

from dojo import InMemoryStore, YayinZamani
from dojo.testing import FIXED_AT, ISTANBUL


def make_occ(store: InMemoryStore, *, kind: str, due: datetime, status: str = "pending") -> YayinZamani:
    return store.create(
        YayinZamani(
            id=0,
            kind=kind,
            due_at=due,
            status=status,
            created_at=FIXED_AT,
        )
    )


def test_create_assigns_id_and_stores() -> None:
    store = InMemoryStore()
    occ = make_occ(store, kind="manual", due=FIXED_AT)
    assert occ.id >= 1
    assert len(store.list_all()) == 1
    assert store.list_all()[0].kind == "manual"


def test_max_regular_due_at() -> None:
    store = InMemoryStore()
    make_occ(store, kind="regular", due=FIXED_AT)
    make_occ(store, kind="regular", due=FIXED_AT + timedelta(days=14))
    make_occ(store, kind="manual", due=FIXED_AT + timedelta(days=99))
    assert store.max_regular_due_at() == FIXED_AT + timedelta(days=14)


def test_max_regular_due_at_empty() -> None:
    assert InMemoryStore().max_regular_due_at() is None


def test_has_regular_at() -> None:
    store = InMemoryStore()
    make_occ(store, kind="regular", due=FIXED_AT)
    assert store.has_regular_at(FIXED_AT) is True
    assert store.has_regular_at(FIXED_AT + timedelta(days=14)) is False


def test_has_pending_manual() -> None:
    store = InMemoryStore()
    assert store.has_pending_manual() is False
    make_occ(store, kind="manual", due=FIXED_AT)
    assert store.has_pending_manual() is True


def test_list_due() -> None:
    store = InMemoryStore()
    past = make_occ(store, kind="regular", due=FIXED_AT - timedelta(days=1))
    future = make_occ(store, kind="regular", due=FIXED_AT + timedelta(days=14))
    assert [o.id for o in store.list_due(FIXED_AT)] == [past.id]
    assert all(o.id != future.id for o in store.list_due(FIXED_AT))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_store_schedule.py -v`
Expected: FAIL — `AttributeError: 'InMemoryStore' object has no attribute 'create'` handling `YayinZamani` (create raises for unknown type).

- [ ] **Step 3: Implement `InMemoryStore`**

In `dojo-core/src/dojo/adapters/memory.py`:
- Add `YayinZamani` to the `from dojo.model import (...)` block.
- In `__init__`, add `self._occurrences: list[YayinZamani] = []` and `self._next_occ_id = 1`.
- Add `YayinZamani` to the `create` overloads and the dispatch:
```python
    @overload
    def create(self, obj: YayinZamani) -> YayinZamani: ...

    def create(self, obj: Package | Upload | Job | YayinZamani) -> Package | Upload | Job | YayinZamani:
        if isinstance(obj, YayinZamani):
            created_occ = replace(obj, id=self._next_occ_id)
            self._next_occ_id += 1
            self._occurrences.append(created_occ)
            return created_occ
        if isinstance(obj, Upload):
            ...
```
- Add the schedule methods (place near `set`):
```python
    def max_regular_due_at(self) -> datetime | None:
        dates = [o.due_at for o in self._occurrences if o.kind == "regular"]
        return max(dates) if dates else None

    def has_regular_at(self, due_at: datetime) -> bool:
        return any(o.kind == "regular" and o.due_at == due_at for o in self._occurrences)

    def has_pending_manual(self) -> bool:
        return any(o.kind == "manual" and o.status == "pending" for o in self._occurrences)

    def list_due(self, now: datetime) -> list[YayinZamani]:
        return [
            o for o in self._occurrences
            if o.status == "pending" and o.due_at <= now
        ]

    def list_all(self) -> list[YayinZamani]:
        return list(self._occurrences)
```
(Note: `datetime` is already imported in memory.py.)

- [ ] **Step 4: Run memory tests to verify they pass**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_store_schedule.py -v`
Expected: PASS.

- [ ] **Step 5: Implement `PostgresStore`**

In `dojo-core/src/dojo/adapters/db.py`:
- Add `func` to the `from sqlalchemy import (...)` block.
- Add `YayinZamani` to the `from dojo.model import (...)` block.
- Add a `YayinZamani` overload and branch to `create`:
```python
    @overload
    def create(self, obj: YayinZamani) -> YayinZamani: ...

    def create(self, obj: Package | Upload | Job | YayinZamani) -> Package | Upload | Job | YayinZamani:
        if isinstance(obj, YayinZamani):
            return self._create_occurrence(obj)
        if isinstance(obj, Upload):
            ...
```
- Add `_create_occurrence` and the schedule query methods (place before `set`):
```python
    def _create_occurrence(self, occ: YayinZamani) -> YayinZamani:
        with self._session() as session:
            row = YayinZamaniRow(
                kind=occ.kind,
                due_at=occ.due_at,
                status=occ.status,
                created_at=occ.created_at,
                resolved_at=occ.resolved_at,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._occ_from_row(row)

    def max_regular_due_at(self) -> datetime | None:
        with self._session() as session:
            return session.scalar(
                select(func.max(YayinZamaniRow.due_at)).where(YayinZamaniRow.kind == "regular")
            )

    def has_regular_at(self, due_at: datetime) -> bool:
        with self._session() as session:
            return session.scalar(
                select(YayinZamaniRow.id)
                .where(YayinZamaniRow.kind == "regular", YayinZamaniRow.due_at == due_at)
                .limit(1)
            ) is not None

    def has_pending_manual(self) -> bool:
        with self._session() as session:
            return session.scalar(
                select(YayinZamaniRow.id)
                .where(YayinZamaniRow.kind == "manual", YayinZamaniRow.status == "pending")
                .limit(1)
            ) is not None

    def list_due(self, now: datetime) -> list[YayinZamani]:
        with self._session() as session:
            rows = session.scalars(
                select(YayinZamaniRow)
                .where(YayinZamaniRow.status == "pending", YayinZamaniRow.due_at <= now)
                .order_by(YayinZamaniRow.id)
            ).all()
            return [self._occ_from_row(r) for r in rows]

    def list_all(self) -> list[YayinZamani]:
        with self._session() as session:
            rows = session.scalars(select(YayinZamaniRow).order_by(YayinZamaniRow.id)).all()
            return [self._occ_from_row(r) for r in rows]

    @staticmethod
    def _occ_from_row(row: YayinZamaniRow) -> YayinZamani:
        return YayinZamani(
            id=row.id,
            kind=row.kind,
            due_at=row.due_at,
            status=row.status,
            created_at=row.created_at,
            resolved_at=row.resolved_at,
        )
```

- [ ] **Step 6: Lint, typecheck, full suite, commit**

Run: `uv run --project dojo-core ruff check dojo-core/src/dojo/adapters/memory.py dojo-core/src/dojo/adapters/db.py dojo-core/tests/test_store_schedule.py; uv run --project dojo-core mypy dojo-core/src/dojo`
Expected: no findings
Run: `uv run --project dojo-core pytest dojo-core/tests -v`
Expected: all pass

```bash
git add dojo-core/src/dojo/adapters/memory.py dojo-core/src/dojo/adapters/db.py dojo-core/tests/test_store_schedule.py
git commit -m "feat(dojo-core): schedule store implementations (#13)"
```

---

### Task 4: Seam — plan, manual publish, and due-slot emission

**Files:**
- Modify: `dojo-core/src/dojo/publishing.py`
- Create: `dojo-core/tests/test_schedule.py`

**Interfaces:**
- Consumes: Task 1 `SchedulePlan`, `YayinZamani`, `PlanInvalid`, `ManualPublishConflict`; Task 2 `ScheduleStore`; Task 3 store methods.
- Produces (consumed by Task 5):
  - `get_plan() -> SchedulePlan`
  - `set_plan(plan: SchedulePlan, requester: str | None = None) -> SchedulePlan`
  - `manual_publish(requester: str | None = None) -> YayinZamani`
  - `ensure_schedule_upto(now: datetime | None = None) -> None`
  - `list_due_occurrences(now: datetime | None = None) -> list[YayinZamani]`
  - `evaluate_due_work()` now calls `ensure_schedule_upto(now)`.

- [ ] **Step 1: Write the failing tests**

Create `dojo-core/tests/test_schedule.py`:
```python
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta

import pytest
from dojo import (
    DojoPublishing,
    InMemoryStore,
    ManualPublishConflict,
    PlanInvalid,
    SchedulePlan,
)
from dojo.adapters.stubs import (
    StubMetaPublisher,
    StubNotifier,
    StubSignedUrlStore,
)
from dojo.testing import FIXED_AT, FakeClock, ISTANBUL


def make_seam(tmp_path):
    store = InMemoryStore()
    seam = DojoPublishing(
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
    )
    return store, seam


def monday_dt() -> datetime:
    return datetime(2026, 8, 3, 10, 0, tzinfo=ISTANBUL)  # a Monday


def test_set_plan_validates_monday_anchor(tmp_path) -> None:
    _, seam = make_seam(tmp_path)
    seam.set_plan(
        SchedulePlan(anchor_date=date(2026, 8, 3), anchor_time=time(10, 0), enabled=True),
        requester="7",
    )
    with pytest.raises(PlanInvalid):
        seam.set_plan(
            SchedulePlan(anchor_date=date(2026, 8, 4), anchor_time=time(10, 0))
        )
    with pytest.raises(PlanInvalid):
        seam.set_plan(SchedulePlan(anchor_date=None, anchor_time=None))
    assert seam.list_audit()[0].action == "plan.updated"
    assert seam.list_audit()[0].actor == "7"


def test_get_plan_defaults_disabled(tmp_path) -> None:
    _, seam = make_seam(tmp_path)
    plan = seam.get_plan()
    assert plan.anchor_date is None
    assert plan.enabled is False


def test_ensure_schedule_upto_backfills_and_one_future_row(tmp_path) -> None:
    store, seam = make_seam(tmp_path)
    anchor = monday_dt()
    seam.set_plan(
        SchedulePlan(anchor_date=anchor.date(), anchor_time=anchor.time(), enabled=True)
    )
    now = anchor + timedelta(days=21)  # three Mondays later
    seam._clock = FakeClock(now)
    seam.ensure_schedule_upto(now)

    reg = [o for o in store.list_all() if o.kind == "regular"]
    due = [o.due_at for o in store.list_due(now)]
    # Mondays at +0, +14, +21(+14 would be the future row) up to now
    assert due == [anchor, anchor + timedelta(days=14)]
    # exactly one future row: the next Monday after now
    future = [o for o in reg if o.due_at > now]
    assert len(future) == 1
    assert future[0].due_at == anchor + timedelta(days=28)


def test_ensure_schedule_upto_idempotent_across_restart(tmp_path) -> None:
    store, seam = make_seam(tmp_path)
    anchor = monday_dt()
    seam.set_plan(
        SchedulePlan(anchor_date=anchor.date(), anchor_time=anchor.time(), enabled=True)
    )
    now = anchor + timedelta(days=35)
    seam._clock = FakeClock(now)
    seam.ensure_schedule_upto(now)
    count_before = len(store.list_all())

    # "restart": a fresh seam sharing the same store
    seam2 = DojoPublishing(
        packages=store, audit=store, uploads=store, jobs=store, settings=store,
        media_root=tmp_path, clock=FakeClock(now),
        meta=StubMetaPublisher(), notifier=StubNotifier(), signed_urls=StubSignedUrlStore(),
    )
    seam2.ensure_schedule_upto(now)

    assert len(store.list_all()) == count_before


def test_plan_edit_reflected_in_future_rows(tmp_path) -> None:
    store, seam = make_seam(tmp_path)
    old = monday_dt()
    seam.set_plan(
        SchedulePlan(anchor_date=old.date(), anchor_time=old.time(), enabled=True)
    )
    now = old + timedelta(days=21)
    seam._clock = FakeClock(now)
    seam.ensure_schedule_upto(now)

    # move anchor one biweekly step later
    new_anchor = old + timedelta(days=28)
    seam.set_plan(
        SchedulePlan(anchor_date=new_anchor.date(), anchor_time=new_anchor.time(), enabled=True)
    )
    seam.ensure_schedule_upto(now)

    reg = [o.due_at for o in store.list_all() if o.kind == "regular"]
    # future row now derives from the new anchor, not the old
    future = [d for d in reg if d > now]
    assert future == [new_anchor]


def test_manual_publish_creates_due_slot_without_shifting(tmp_path) -> None:
    store, seam = make_seam(tmp_path)
    anchor = monday_dt()
    seam.set_plan(
        SchedulePlan(anchor_date=anchor.date(), anchor_time=anchor.time(), enabled=True)
    )
    now = anchor + timedelta(days=21)
    seam._clock = FakeClock(now)
    seam.ensure_schedule_upto(now)
    regular_before = [o.due_at for o in store.list_all() if o.kind == "regular"]

    occ = seam.manual_publish(requester="8")

    assert occ.kind == "manual"
    assert occ.status == "pending"
    assert occ.due_at == now
    due = seam.list_due_occurrences(now)
    assert any(o.id == occ.id for o in due)
    # cadence unchanged: no new regular rows from manual publish
    regular_after = [o.due_at for o in store.list_all() if o.kind == "regular"]
    assert regular_after == regular_before
    assert seam.list_audit()[0].action == "schedule.manual_created"
    assert seam.list_audit()[0].actor == "8"


def test_second_manual_publish_conflict(tmp_path) -> None:
    store, seam = make_seam(tmp_path)
    seam.manual_publish(requester="9")
    with pytest.raises(ManualPublishConflict):
        seam.manual_publish(requester="10")
    # after resolving (marking resolved), a new manual is allowed
    pending = [o for o in store.list_all() if o.kind == "manual" and o.status == "pending"][0]
    resolved = pending.__class__(
        id=pending.id, kind=pending.kind, due_at=pending.due_at,
        status="resolved", created_at=pending.created_at, resolved_at=pending.due_at,
    )
    store._occurrences = [
        resolved if o.id == resolved.id else o for o in store._occurrences
    ]
    assert seam.manual_publish(requester="11").kind == "manual"


def test_manual_publish_allowed_when_plan_disabled(tmp_path) -> None:
    _, seam = make_seam(tmp_path)
    assert seam.manual_publish().kind == "manual"


def test_evaluate_due_work_materializes(tmp_path) -> None:
    store, seam = make_seam(tmp_path)
    anchor = monday_dt()
    seam.set_plan(
        SchedulePlan(anchor_date=anchor.date(), anchor_time=anchor.time(), enabled=True)
    )
    seam._clock = FakeClock(anchor + timedelta(days=21))
    seam.evaluate_due_work()
    assert len(store.list_all()) == 3  # two due + one future
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_schedule.py -v`
Expected: FAIL — methods missing on `DojoPublishing`.

- [ ] **Step 3: Implement the seam**

In `dojo-core/src/dojo/publishing.py`:
- Extend `from datetime import datetime, timedelta` to `from datetime import date, datetime, time, timedelta`.
- Extend the `from dojo.exceptions import (...)` block with `ManualPublishConflict`, `PlanInvalid`.
- Extend the `from dojo.model import (...)` block with `SchedulePlan`, `YayinZamani`.
- Extend the `from dojo.ports import (...)` block with `ScheduleStore`.
- In `__init__`, add a `schedule: ScheduleStore | None = None` keyword param and store it:
```python
        self._schedule: ScheduleStore = (
            schedule if schedule is not None else cast(ScheduleStore, packages)
        )
```
- Replace the `evaluate_due_work` no-op and add the schedule methods after `_write_manifest` (around line 1012):
```python
    def get_plan(self) -> SchedulePlan:
        enabled = self._settings.get("schedule.enabled")
        anchor_date_raw = self._settings.get("schedule.anchor_date")
        anchor_time_raw = self._settings.get("schedule.anchor_time")
        anchor_date = None
        anchor_time = None
        if isinstance(anchor_date_raw, str) and anchor_date_raw:
            anchor_date = date.fromisoformat(anchor_date_raw)
        if isinstance(anchor_time_raw, str) and anchor_time_raw:
            anchor_time = time.fromisoformat(anchor_time_raw)
        return SchedulePlan(
            anchor_date=anchor_date,
            anchor_time=anchor_time,
            enabled=bool(enabled) if enabled is not None else False,
        )

    def set_plan(
        self, plan: SchedulePlan, requester: str | None = None
    ) -> SchedulePlan:
        if plan.anchor_date is None or plan.anchor_time is None:
            raise PlanInvalid("anchor date and time are required")
        if plan.anchor_date.weekday() != 0:
            raise PlanInvalid(f"anchor must be a Monday, got {plan.anchor_date}")
        now = self._clock.now()
        self._settings.set("schedule.enabled", plan.enabled, updated_at=now)
        self._settings.set("schedule.anchor_date", plan.anchor_date.isoformat(), updated_at=now)
        self._settings.set("schedule.anchor_time", plan.anchor_time.isoformat(), updated_at=now)
        self._audit.append(
            AuditEvent(
                action="plan.updated",
                actor=requester or "system",
                occurred_at=now,
                details=plan.to_dict(),
            )
        )
        return self.get_plan()

    def manual_publish(self, requester: str | None = None) -> YayinZamani:
        if self._schedule.has_pending_manual():
            raise ManualPublishConflict("a manual publish slot is already pending")
        now = self._clock.now().astimezone(ISTANBUL)
        occurrence = self._schedule.create(
            YayinZamani(
                id=0, kind="manual", due_at=now, status="pending", created_at=now
            )
        )
        self._audit.append(
            AuditEvent(
                action="schedule.manual_created",
                actor=requester or "system",
                occurred_at=now,
                details={
                    "occurrence_id": occurrence.id,
                    "due_at": occurrence.due_at.isoformat(),
                },
            )
        )
        return occurrence

    def ensure_schedule_upto(self, now: datetime | None = None) -> None:
        plan = self.get_plan()
        if not plan.enabled or plan.anchor_date is None or plan.anchor_time is None:
            return
        now = (now or self._clock.now()).astimezone(ISTANBUL)
        created_now = self._clock.now().astimezone(ISTANBUL)
        anchor_dt = datetime.combine(
            plan.anchor_date, plan.anchor_time, tzinfo=ISTANBUL
        )
        occ_dt = anchor_dt
        while occ_dt <= now:
            if not self._schedule.has_regular_at(occ_dt):
                self._schedule.create(
                    YayinZamani(
                        id=0, kind="regular", due_at=occ_dt,
                        status="pending", created_at=created_now,
                    )
                )
            occ_dt += timedelta(days=14)
        next_dt = anchor_dt
        while next_dt <= now:
            next_dt += timedelta(days=14)
        if not self._schedule.has_regular_at(next_dt):
            self._schedule.create(
                YayinZamani(
                    id=0, kind="regular", due_at=next_dt,
                    status="pending", created_at=created_now,
                )
            )

    def list_due_occurrences(self, now: datetime | None = None) -> list[YayinZamani]:
        now = (now or self._clock.now()).astimezone(ISTANBUL)
        return self._schedule.list_due(now)

    def evaluate_due_work(self) -> None:
        """Scheduler trigger: materialize due and next Yayın Zamanı slots.

        Review creation from a due slot is handled by #14.
        """
        self.ensure_schedule_upto()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_schedule.py -v`
Expected: PASS. Fix any test/implementation mismatch inline (e.g. `date.fromisoformat` vs `datetime` string shapes).

- [ ] **Step 5: Lint, typecheck, full suite, commit**

Run: `uv run --project dojo-core ruff check dojo-core/src/dojo/publishing.py dojo-core/tests/test_schedule.py; uv run --project dojo-core mypy dojo-core/src/dojo`
Expected: no findings
Run: `uv run --project dojo-core pytest dojo-core/tests -v`
Expected: all pass

```bash
git add dojo-core/src/dojo/publishing.py dojo-core/tests/test_schedule.py
git commit -m "feat(dojo-core): dojo yayin plani, manual publish, and due-slot emission (#13)"
```

---

### Task 5: FastAPI routes and contract tests

**Files:**
- Modify: `backend/src/backend/routes/settings.py`
- Modify: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: Task 1 `SchedulePlan`, `PlanInvalid`, `ManualPublishConflict`; Task 4 `get_plan`, `set_plan`, `manual_publish`.
- Produces: `GET /api/settings/plan`, `PUT /api/settings/plan`, `POST /api/settings/manual-publish`.

- [ ] **Step 1: Write the failing contract tests**

Append to `backend/tests/test_api.py`:
```python
def test_plan_routes_require_auth(tmp_path: Path) -> None:
    client, _, _, _ = make_app(tmp_path)
    assert client.get("/api/settings/plan").status_code == 401
    assert client.put("/api/settings/plan", json={}).status_code == 401
    assert client.post("/api/settings/manual-publish").status_code == 401


def test_plan_roundtrip_via_api(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    resp = client.put(
        "/api/settings/plan",
        headers=bearer(token),
        json={"anchor_date": "2026-08-03", "anchor_time": "10:00", "enabled": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["anchor_date"] == "2026-08-03"
    assert body["anchor_time"] == "10:00:00"
    assert body["enabled"] is True
    assert body["timezone"] == "Europe/Istanbul"

    fetched = client.get("/api/settings/plan", headers=bearer(token)).json()
    assert fetched["anchor_date"] == "2026-08-03"


def test_set_plan_non_monday_422_via_api(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    resp = client.put(
        "/api/settings/plan",
        headers=bearer(token),
        json={"anchor_date": "2026-08-04", "anchor_time": "10:00"},
    )
    assert resp.status_code == 422


def test_manual_publish_via_api(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    resp = client.post("/api/settings/manual-publish", headers=bearer(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "manual"
    assert body["status"] == "pending"
    # second manual while pending is a conflict
    assert client.post("/api/settings/manual-publish", headers=bearer(token)).status_code == 409
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project backend pytest backend/tests/test_api.py -k "plan or manual" -v`
Expected: FAIL — routes missing (404).

- [ ] **Step 3: Add routes to `settings.py`**

Replace the contents of `backend/src/backend/routes/settings.py`:
```python
from __future__ import annotations

from datetime import date, time

from dojo import (
    Client,
    DojoPublishing,
    ManualPublishConflict,
    PlanInvalid,
    SchedulePlan,
)
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.deps import get_current_client


def get_publishing(request: Request) -> DojoPublishing:
    return request.app.state.publishing


class PlanIn(BaseModel):
    anchor_date: str | None = None
    anchor_time: str | None = None
    enabled: bool = True


class PlanOut(BaseModel):
    anchor_date: str | None
    anchor_time: str | None
    enabled: bool
    timezone: str


class OccurrenceOut(BaseModel):
    id: int
    kind: str
    due_at: str
    status: str


router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/plan", response_model=PlanOut)
def get_plan(
    _client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> PlanOut:
    return PlanOut(**publishing.get_plan().to_dict())


@router.put("/plan", response_model=PlanOut)
def set_plan(
    body: PlanIn,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> PlanOut:
    plan = SchedulePlan(
        anchor_date=date.fromisoformat(body.anchor_date) if body.anchor_date else None,
        anchor_time=time.fromisoformat(body.anchor_time) if body.anchor_time else None,
        enabled=body.enabled,
    )
    try:
        updated = publishing.set_plan(plan, requester=str(client.id))
    except PlanInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PlanOut(**updated.to_dict())


@router.post("/manual-publish", response_model=OccurrenceOut)
def manual_publish(
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> OccurrenceOut:
    try:
        occurrence = publishing.manual_publish(requester=str(client.id))
    except ManualPublishConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return OccurrenceOut(
        id=occurrence.id,
        kind=occurrence.kind,
        due_at=occurrence.due_at.isoformat(),
        status=occurrence.status,
    )
```
Note: this file previously defined branding routes. The task removes the branding routes; that is intentional ONLY if branding routes are unused. Verify first — if `settings.py` currently defines `BrandingDefaultsIn`/`get_branding_defaults`/`set_branding_defaults` (it does, per the file read), and nothing else references them, replace the whole file. If a test references branding routes, instead **append** the three new routes and keep the existing branding definitions; do not delete them.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --project backend pytest backend/tests/test_api.py -k "plan or manual" -v`
Expected: PASS.

- [ ] **Step 5: Verify branding routes intact (or appended)**

Run: `uv run --project backend pytest backend/tests/test_api.py -k branding -v`
Expected: PASS (no branding regression). If branding routes were removed and a test fails, restore them by appending the branding block back alongside the new routes.

- [ ] **Step 6: Lint, typecheck, full suite, commit**

Run: `uv run --project backend ruff check backend/src backend/tests; uv run --project backend mypy backend/src/backend`
Expected: no findings
Run: `uv run --project backend pytest backend/tests -v`
Expected: all pass

```bash
git add backend/src/backend/routes/settings.py backend/tests/test_api.py
git commit -m "feat(backend): plan and manual publish routes (#13)"
```