# Yayın İncelemesi Creation From a Due Time — Design

Date: 2026-08-20
Source: Issue #14 (part of #1, Dojo Reel Publishing MVP), blocked by #12 and #13 (both done).

## Problem

The system now emits due `Yayın Zamanı` slots (`#13`) but nothing turns a due slot into
a durable `Yayın İncelemesi`. Administrators need: a due time to produce at most one
durable review bound to the active package revision (idempotent across scheduler re-runs
and restarts); an empty active package at due time to offer Upload / Skip / Reschedule,
with upload continuing to render and review on the same package; and late approval to
publish immediately without a new folder or review.

## Decisions

1. **Review creation hooks into render completion.** A review is only materialized once a
   render lands, so it always references a rendered artifact. `_create_review_if_due`
   runs at the end of `_render_job` and, for already-fresh packages, during
   `evaluate_due_work` (so a package rendered earlier via preview does not need a wasteful
   re-render before its review appears).
2. **Dedicated durable table** `yayin_incelemesi` behind a new `ReviewStore` port,
   mirroring the `yayin_zamani`/`ScheduleStore` precedent (`#13`).
3. **Idempotency key** = unique `(occurrence_id, revision_digest)`. Re-runs and restarts
   at the same revision add no review (AC1). Content edited while the occurrence is still
   pending yields a new digest → a new review for that revision; the older one is inert.
4. **Empty active package at due time**: create no review; the occurrence stays `pending`
   so the UI can offer Upload / Skip / Reschedule. Once media lands, a later tick's
   non-empty branch enqueues render → review on the **same** package and occurrence. No
   second active package (AC2).
5. **Resolution stays in #15.** Review `status` is `"pending"` in #14. Approve, Skip,
   Reschedule and their state transitions are #15. Late approval (AC3) reuses the durable
   review keyed to the occurrence, not to "now", so no new folder/review is created by
   time passing.
6. **No new routes in #14.** Client-facing review display is #25; resolution is #15;
   reminders/notifications are #16. The worker already calls `evaluate_due_work` each tick,
   so no worker change is required beyond the facade.

## Domain model (`dojo/model.py`)

```python
@dataclass(frozen=True)
class YayinIncelemesi:
    id: int
    occurrence_id: int        # -> yayin_zamani.id this review answers
    package_folder: str       # the active package it reviews
    revision_digest: str      # render digest it is bound to
    caption: str | None       # snapshot for approval binding
    status: str               # "pending" now; #15 adds resolution states
    created_at: datetime
```

## Ports (`dojo/ports.py`)

New `ReviewStore(Protocol)`:

- `create(review: YayinIncelemesi) -> YayinIncelemesi`
- `get_by_occurrence(occurrence_id: int) -> YayinIncelemesi | None`
- `list_pending() -> list[YayinIncelemesi]`

Implemented by `InMemoryStore` (test seam) and `PostgresStore` (`dojo/adapters/db.py`).

## Facade (`dojo/publishing.py`)

- `_create_review_if_due(package, digest) -> YayinIncelemesi | None` — find a due,
  `pending` occurrence; if no review exists for `(occurrence_id, digest)`, create it with
  the manifest caption snapshot and audit `review.created`. Idempotent otherwise.
- `_render_job` — after writing `render_revision = digest`, call `_create_review_if_due`.
- `evaluate_due_work()` — after `ensure_schedule_upto()`, for each due `pending`
  occurrence: non-empty package → enqueue render if stale, else call
  `_create_review_if_due` directly; empty package → no-op (stays pending).

## Migration (`dojo-core/migrations/versions/0008_yayin_incelemesi.py`)

New table `yayin_incelemesi`:

- `id` integer PK autoincrement
- `occurrence_id` integer not null
- `package_folder` text not null
- `revision_digest` text not null
- `caption` text null
- `status` text not null default `pending`
- `created_at` timestamp with time zone not null
- unique `(occurrence_id, revision_digest)`; index on `status` for the pending query.

Also add `yayin_incelemesi` to the `conftest.py` TRUNCATE list.

## Testing (`dojo-core/tests/test_schedule.py`, in-memory seam + `FakeClock` + `StubReelRenderer`)

1. Due occurrence + non-empty package → exactly one review; `evaluate_due_work` re-run and
   a fresh seam "restart" over the same store add none.
2. Already-fresh package (rendered via preview) → due eval creates review without
   re-rendering.
3. Empty package at due → no review, occurrence stays pending.
4. Upload after empty-due → finalized → render completes → review on the same
   package/occurrence; still exactly one active package.
5. Late approval structural check: past-due occurrence with an existing review → re-running
   due eval creates no second review/folder.
6. `review.created` audit recorded with actor; review carries the caption snapshot.

## Out of scope

- Approve / Skip / Reschedule resolution and revision-aware atomicity — #15.
- Pending-review reminders and Android notifications — #16.
- Client-facing review endpoints / dashboard display — #25 and related.