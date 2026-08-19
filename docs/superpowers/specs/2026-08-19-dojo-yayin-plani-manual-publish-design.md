# Dojo Yayın Planı and Manual Publication — Design

Date: 2026-08-19
Source: Issue #13 (part of #1, Dojo Reel Publishing MVP), blocked by #6 (done).

## Problem

The system has an active `Dojo Paylaşım Paketi` but no recurring schedule. Administrators
need a `Dojo Yayın Planı`: an explicit first date, a local Monday time, the
`Europe/Istanbul` timezone, and a biweekly (alternate-Monday) recurrence that is
deterministic. Plan settings must be editable, with future occurrences reflecting the
change. A manual publish action must prepare an extra Reel between regular slots without
shifting the recurring anchor.

## Decisions

1. **Seam placement**: extend the deep `DojoPublishing` facade
   (`dojo/publishing.py`) — same as #6/#10/#11. No new facade. Routes stay thin.
2. **Boundary with #14**: this ticket emits **due `Yayın Zamanı` slots only**. The
   actual `Yayın İncelemesi` creation from a due time is #14 (blocked by #13). AC3
   "manual publish produces a due review" is satisfied here as "produces a due slot that
   #14 will turn into a review".
3. **Recurring plan config** lives in `SettingsStore` under `schedule.*` keys, following
   the #10/#11 pattern. No migration for the plan itself.
4. **Concrete due slots** persist in a new `yayin_zamani` table behind a new
   `ScheduleStore` port. New migration `0007_yayin_zamani.py`.
5. **Occurrence kind**: a row is either `regular` (from the biweekly Monday rule) or
   `manual` (a one-off). Manual rows are excluded from regular backfill, so a manual
   publish never shifts the recurring anchor (AC3 "without shifting cadence").
6. **Materialization (Plan C)**: on each `evaluate_due_work()` tick, lazily backfill
   every alternate-Monday occurrence from the anchor up to `now`, then guarantee exactly
   one future row (the next Monday after `now`) exists. Idempotent across restarts and
   re-runs; anchor edits derive future rows automatically on the next tick.
7. **Manual publish**: `manual_publish()` inserts a single `manual` occurrence due
   immediately (`now`). A second manual publish while a `manual` row is still pending is
   rejected (`ManualPublishConflict`). It never writes to the anchor.
8. **Time zone**: occurrences are computed and stored in `Europe/Istanbul`
   (`dojo/adapters/clock.py` `ISTANBUL`). The timezone is fixed, not user-configurable.
9. **Anchor rule**: the anchor date must be a Monday; otherwise `PlanInvalid`.
   Occurrences step `+14 days` from `anchor_dt` (`anchor_date` at `anchor_time`).
10. **Auth**: plan and manual-publish routes sit behind `get_current_client`, equal
    privilege for device + browser, unauth → 401.

## Domain model

`SchedulePlan` (`dojo/model.py`):

```python
@dataclass(frozen=True)
class SchedulePlan:
    anchor_date: date | None = None
    anchor_time: time | None = None
    enabled: bool = True
    timezone: str = "Europe/Istanbul"
```

`YayinZamani` (`dojo/model.py`):

```python
@dataclass(frozen=True)
class YayinZamani:
    id: int
    kind: str            # "regular" | "manual"
    due_at: datetime     # tz-aware, Europe/Istanbul
    status: str          # "pending" | "due" | "resolved"
    created_at: datetime
    resolved_at: datetime | None = None
```

## Exceptions (`dojo/exceptions.py`)

- `PlanInvalid(DojoError)` — anchor missing or not a Monday.
- `ManualPublishConflict(DojoError)` — a pending manual slot already exists.

## Ports (`dojo/ports.py`)

New `ScheduleStore(Protocol)`:

- `create(occurrence: YayinZamani) -> YayinZamani`
- `max_regular_due_at() -> datetime | None` — highest already-materialized `regular`
  `due_at`; bounds the backfill.
- `has_pending_manual() -> bool` — any `manual` row with status `pending`.
- `list_due(now: datetime) -> list[YayinZamani]` — pending rows with `due_at <= now`.

Implemented by `InMemoryStore` (already the test seam) and `PostgresStore`
(`dojo/adapters/db.py`).

## Facade (`dojo/publishing.py`)

- `get_plan() -> SchedulePlan` — reads `schedule.*` keys, defaults to disabled with no
  anchor.
- `set_plan(plan, requester=None) -> SchedulePlan` — validates anchor is a Monday,
  persists `schedule.enabled` / `schedule.anchor_date` / `schedule.anchor_time`, audits
  `plan.updated`.
- `manual_publish(requester=None) -> YayinZamani` — raises `ManualPublishConflict` if a
  pending manual slot exists; else inserts a `manual` occurrence due `now`, audits
  `schedule.manual_created`; does not touch the anchor.
- `ensure_schedule_upto(now=None) -> None` — lazy backfill of `regular` occurrences up
  to `now`, then guarantee exactly one future row (next Monday after `now`).
- `list_due_occurrences(now=None) -> list[YayinZamani]` — via `ScheduleStore.list_due`.
- `evaluate_due_work()` — replace the no-op with `ensure_schedule_upto(now)`. (Review
  creation stays in #14.)

### Rules

- `set_plan` requires a Monday anchor; otherwise `PlanInvalid`.
- `set_plan` writes settings atomically and records one audit event.
- `ensure_schedule_upto` never re-creates an already-materialized regular row
  (`max_regular_due_at` bound) and never creates `manual` rows.
- `manual_publish` is independent of `enabled`; a disabled plan still allows a manual
  publish.
- Occurrences are stored as tz-aware `Europe/Istanbul` datetimes.

## Migration (`dojo-core/migrations/versions/0007_yayin_zamani.py`)

New table `yayin_zamani`:

- `id` integer PK autoincrement
- `kind` text not null
- `due_at` timestamp with time zone not null
- `status` text not null default `pending`
- `created_at` timestamp with time zone not null
- `resolved_at` timestamp with time zone null
- index on `status`, `due_at` for the due query.

## FastAPI integration

`backend/src/backend/routes/settings.py`:

- `GET /api/settings/plan` — returns the current `SchedulePlan`.
- `PUT /api/settings/plan` — body `{"anchor_date": "YYYY-MM-DD" | null,
  "anchor_time": "HH:MM" | null, "enabled": bool}`; 422 on `PlanInvalid`.
- `POST /api/settings/manual-publish` — 409 on `ManualPublishConflict`.

All behind `get_current_client`.

## Testing

### Domain (`dojo-core/tests/test_schedule.py`, in-memory seam + `FakeClock`)

1. Alternate-Monday math: anchor Monday → occurrences every 14 days; non-Monday anchor
   raises `PlanInvalid`.
2. Backfill: `ensure_schedule_upto(now)` materializes each due Monday; idempotent on
   repeat calls and across a fresh seam "restart" sharing the store.
3. One future row: after backfill there is exactly one `regular` row with `due_at > now`
   and it is the next Monday.
4. Plan edit: changing the anchor is reflected in future materialization; old rows are
   not disturbed.
5. Manual publish: inserts a due-now `manual` slot; does not add `regular` rows and does
   not shift `max_regular_due_at`; a second manual publish while pending raises
   `ManualPublishConflict`; after the first is resolved a new one is allowed.
6. `evaluate_due_work` materializes due and next-future rows.
7. Audit: `plan.updated`, `schedule.manual_created` recorded with actor.

### Contract (`backend/tests/test_api.py`)

- Auth on all three routes (401).
- PUT plan round-trip; 422 on non-Monday anchor.
- POST manual-publish returns a due `manual` slot; second call 409.

## Out of scope (#14/#15)

- Creating the `Yayın İncelemesi` from a due time (idempotent review, empty-package
  behavior, late approval) — #14.
- Review resolution: skip, reschedule, approve — #15.
- Pending-review reminders and Android notifications — #16.
- Dashboard "next Yayın Zamanı" display — #25.