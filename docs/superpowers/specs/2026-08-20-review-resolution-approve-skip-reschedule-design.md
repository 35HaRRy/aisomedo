# Review Resolution: Approve, Skip, Reschedule — Design

Date: 2026-08-20
Source: Issue #15 (part of #1, Dojo Reel Publishing MVP), blocked by #14 (done).

## Problem

A due `Yayın Zamanı` now creates one durable `Yayın İncelemesi` per revision (#14), but
the review is always `status="pending"`. Administrators need to resolve it three ways —
approve, skip, or reschedule — such that when two equal devices race the same review,
exactly one valid action wins, and the loser gets a clear "already handled by another
device" response plus refreshed authoritative state. Skip must require confirmation and
show the next regular time. Reschedule must require a future local time and never shift
the recurring plan.

## Decisions

1. **Approve is resolve-only.** `approve` marks the review `approved`, resolves the linked
   occurrence, and stops reminders (review leaves `pending`). The `-publishing` claim and
   the Instagram call belong to #18, which reads the approved review. No publish job and no
   folder rename in #15.
2. **CAS on a monotonic version counter.** `YayinIncelemesi.version` starts at 1 and
   increments on every resolution. A resolution is one atomic compare-and-set:
   `UPDATE ... SET status=?, version=version+1, ... WHERE id=? AND status='pending'
   AND version=?`. One winner; a loser (`rowcount=0`) gets `ReviewAlreadyHandled` carrying
   the authoritative current review.
3. **Stale-revision actions rejected.** If content was edited after a review was created,
   #14 creates a new review for the new digest. Acting on the old pending review raises
   `ReviewStale` (its `revision_digest` != active package `render_revision`); the client
   refreshes to the newer review. This prevents approving stale content.
4. **Skip requires an explicit `confirmed=True`.** Without it, `SkipRequiresConfirmation`.
   On success the review becomes `skipped`, the occurrence resolves (reminders stop), and
   the result carries the next regular `Yayın Zamanı` for display. The active package is
   untouched.
5. **Reschedule creates a new `oneoff` occurrence.** `new_due_at` must be strictly in the
   future (`RescheduleTimeInvalid` otherwise). The current review/occurrence resolves, and a
   new `YayinZamani` with `kind="oneoff"`, `status="pending"` is created at `new_due_at`.
   The review records `oneoff_occurrence_id`. A second reschedule **replaces** the prior
   pending one-off (same row, new `due_at`) instead of stacking. Recurring cadence is
   untouched (no new `regular` rows; `ensure_schedule_upto` pruning is unaffected).
6. **New `oneoff` kind on `YayinZamani`.** Distinct from `regular`/`manual`. Reuses the
   existing `pending`/`resolved` status + `resolved_at`. When the one-off becomes due, #14's
   scheduler logic naturally creates a review for it.
7. **Reminders stop implicitly.** Resolving sets review `status != "pending"`, so
   `list_pending_reviews()` no longer returns it; #16's reminder loop will have nothing to
   notify. No notifier call in #15.

## Domain model (`dojo/model.py`)

```python
@dataclass(frozen=True)
class YayinIncelemesi:
    id: int
    occurrence_id: int
    package_folder: str
    revision_digest: str
    caption: str | None
    status: str                     # pending | approved | skipped | rescheduled
    created_at: datetime
    version: int = 1                # CAS counter
    resolved_at: datetime | None = None
    resolved_by: str | None = None  # paired client identity
    oneoff_occurrence_id: int | None = None  # -> pending oneoff YayinZamani
```

`YayinZamani` gains a new `kind` value `"oneoff"` (no schema change to that table).

## Exceptions (`dojo/exceptions.py`)

- `SkipRequiresConfirmation(DojoError)`
- `RescheduleTimeInvalid(DojoError)`
- `ReviewStale(DojoError)`
- `ReviewAlreadyHandled(DojoError)` — carries `review` (authoritative state)
- `ReviewNotFound(DojoError)`

Exported from `dojo/__init__.py`.

## Ports (`dojo/ports.py`)

`ReviewStore` adds:
- `get(review_id: int) -> YayinIncelemesi | None`
- `resolve_if_pending(review_id: int, version: int, status: str, resolved_at: datetime,
  resolved_by: str | None) -> YayinIncelemesi | None` — atomic CAS; `None` on conflict.

`ScheduleStore` adds:
- `update(occurrence: YayinZamani) -> YayinZamani` — mark `resolved` / change oneoff `due_at`.
- `next_regular_after(now: datetime) -> YayinZamani | None` — next `regular` slot.

Implemented by `InMemoryStore` (test seam) and `PostgresStore` (`dojo/adapters/db.py`).

## Facade (`dojo/publishing.py`)

- `approve(review_id, version, requester=None) -> YayinIncelemesi`
- `skip(review_id, version, confirmed, requester=None) -> SkipResult` (`review` + `next_regular_at`)
- `reschedule(review_id, version, new_due_at, requester=None) -> YayinIncelemesi`

Shared helper `_resolve(review_id, version, to_status, requester, ...)`:
1. load review (`ReviewNotFound` if missing);
2. reject stale (`ReviewStale` if digest != active package `render_revision`);
3. CAS via `resolve_if_pending` (`ReviewAlreadyHandled` with current review if `None`);
4. resolve the linked occurrence (`ScheduleStore.update` to `resolved`);
5. audit `review.approved` / `review.skipped` / `review.rescheduled` with reviewer + digest.

Reschedule additionally validates `new_due_at > now` and manages the oneoff occurrence.

## Migration (`dojo-core/migrations/versions/0010_review_resolution.py`)

`yayin_incelemesi`:
- add `version` integer not null default 1
- add `resolved_at` timestamp null
- add `resolved_by` text null
- add `oneoff_occurrence_id` integer null

Also add nothing to conftest TRUNCATE (table already truncated).

## Testing (`dojo-core/tests/test_review_resolution.py`, seam + `FakeClock` + stubs)

1. Approve: review becomes `approved`, occurrence resolved, `list_pending_reviews` empty,
   `review.approved` audited.
2. Race: three seams each call approve/skip/reschedule against the same `version` — exactly
   one wins; the other two raise `ReviewAlreadyHandled` whose `review` reflects the winner.
3. Stale revision: edit caption after review created (new digest) → action raises
   `ReviewStale`.
4. Skip without `confirmed=True` raises; with it, resolves, returns next regular time,
   package unchanged, review leaves pending.
5. Reschedule past time raises `RescheduleTimeInvalid`; future time creates a `oneoff`
   occurrence; second reschedule replaces the prior oneoff (`oneoff_occurrence_id`
   unchanged, `due_at` updated); regular cadence unchanged.
6. DB tests (real Postgres): `resolve_if_pending` CAS win/lose; `next_regular_after`;
   migration upgrade to `head`.

## Out of scope

- `-publishing` claim, signed URLs, Instagram call, `-completed` rename — #18.
- Reminders, FCM, quiet hours — #16.
- Client-facing review endpoints / dashboard display — #25, #30, #36.
- Empty-package resolution UI path — surfaced by #30/#36; #15 only resolves existing reviews.