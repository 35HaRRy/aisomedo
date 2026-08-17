# Montage Ordering, Video Trims, and Duration Limits — Design

Date: 2026-08-17
Source: Issue #10 (part of #1, Dojo Reel Publishing MVP), blocked by #7 (done) and #9 (done).

## Problem

The active `Dojo Paylaşım Paketi` holds ordered media but there is no way to
explicitly edit that order or to trim video clips, and nothing enforces the
Instagram duration ceiling. Administrators need to set the montage order,
trim videos when the combined duration exceeds the limit, and be blocked from
building an over-limit montage rather than having it silently truncated or
split. Order and trim edits must invalidate any stale render preview.

## Decisions

1. **Seam placement**: extend the deep `DojoPublishing` facade
   (`dojo/publishing.py`) — same as #7/#8/#9. No new facade. All montage rules
   live behind the seam; routes stay thin.
2. **Explicit order**: `set_order(order, requester)` replaces the manifest
   `order` list. It must be an exact permutation of the finalized `media_id`s
   (every finalized entry exactly once; removed ids excluded). Appending new
   uploads already happens at finalize (per #7) and is preserved.
3. **Trims**: `set_trims(trims, requester)` replaces the manifest `trims` dict.
   Trim shape is `{media_id: {"start": <float>, "end": <float>}}`. Absence of a
   key means the full clip. Only video media may carry a trim.
4. **Duration capture**: the video processor probes and records duration at
   finalize. `ProcessedMedia.duration` is populated by `_process_video`;
   `finalize_media` stores it on the media entry (`processed.duration`). Photos
   carry no duration.
5. **Duration model**: video effective duration = `duration − (end − start)`;
   photo effective duration = configured `montage.photo_duration_seconds`
   (default 3.0). Combined = Σ over `order` (finalized entries only).
6. **Limit**: configurable `montage.max_duration_seconds` (default 90.0, the
   Instagram Reel ceiling), read via the generic settings store like the
   upload limits.
7. **Over-limit behavior (option A, approved)**: `set_order` and `set_trims`
   **reject** any edit whose resulting combined duration exceeds the limit,
   raising `MontageDurationExceeded`. The message states the combined duration,
   the limit, and the excess seconds with the required action ("trim or remove
   N seconds"). Nothing is written on rejection. Over-limit montages cannot be
   created via the seam.
8. **Render stale**: any successful order or trim edit clears
   `manifest.render_revision` (set to `None`). Appending a new upload at
   finalize also clears it, because it changes the montage.
9. **No truncation/splitting**: the system never silently truncates or splits a
   montage. Over-limit is always a rejection with an actionable message.
10. **Auth**: montage routes sit behind `get_current_client`, same as every
    other `/api` business route. Equal privilege for device + browser.

## Domain model

`manifest.trims` entry shape:

```json
{
  "<media_id>": {"start": 2.0, "end": 7.5}
}
```

`manifest.media[].processed` gains a `duration` key for videos only:

```json
{
  "path": "media/<id>/processed.mp4",
  "content_type": "video/mp4",
  "size_bytes": 1234,
  "duration": 12.0
}
```

New exception (`dojo/exceptions.py`):

- `MontageDurationExceeded(DojoError)` — over-limit montage edit rejected.

## Ports

No new protocols. `SettingsStore` is reused for the two new settings keys
(`montage.max_duration_seconds`, `montage.photo_duration_seconds`). No new
tables and no migration — trims, order, duration, and render revision already
live on the manifest (filesystem), not in Postgres.

## Facade (`dojo/publishing.py`)

- `get_montage_limits()` → `MontageLimits` (max_duration_seconds,
  photo_duration_seconds), reading settings with defaults.
- `get_montage_status()` → `MontageStatus` (order, trims, per-clip durations,
  combined duration, limit, over_limit, required_action).
- `set_order(order: list[str], requester=None)` → `MontageStatus`.
- `set_trims(trims: dict[str, dict], requester=None)` → `MontageStatus`.
- `_combined_duration(order, trims) -> float` — helper used by validation and
  status.

### Rules

- `set_order` requires the active package; raises `NoActivePackage` if none.
- `set_order` raises `MediaNotFound` if any id is not a finalized media id, and
  raises a validation error if the ids are not exactly the finalized set
  (missing or duplicate ids rejected).
- `set_order` rejects removed-media ids (they are not in the finalized set).
- `set_trims` requires the active package; raises `NoActivePackage` if none.
- `set_trims` validates each key is a finalized video media id
  (`MediaNotFound`/validation otherwise), `0 <= start < end <= duration`
  (`MontageTrimInvalid`), and drops/overwrites trims for non-video or unknown
  ids rather than storing them.
- Both raise `MontageDurationExceeded` when the resulting combined duration
  exceeds the limit.
- On success both clear `render_revision`, persist the manifest, and audit
  (`montage.order_changed`, `montage.trim_changed`).
- New-upload finalize clears `render_revision`.

## Exceptions (`dojo/exceptions.py`)

- `MontageDurationExceeded(DojoError)`.
- `MontageTrimInvalid(DojoError)` — malformed trim (start >= end, out of
  range, non-video target).

## MediaProcessor (`dojo/adapters/media.py`)

- `_process_video` probes duration via `ffprobe` (`-show_entries format=duration`)
  and sets `ProcessedMedia.duration`. `StubMediaProcessor` gains an optional
  `duration` so tests can model videos.

## FastAPI integration

Extend `backend/src/backend/routes/packages.py`:

- `PUT /api/packages/active/order` — body `{"order": [...]}`. 404 no active
  package / media not found; 409 duration exceeded; 422 invalid order.
- `PUT /api/packages/active/trims` — body `{"trims": {...}}`. 404/409 as above.
- `GET /api/packages/active/montage` — current montage status.

All behind `get_current_client`.

## Testing

### Domain (`dojo-core/tests/test_montage.py`, in-memory seam)

1. Order: set_order persists permutation; new upload appends (regression);
   non-finalized/missing/duplicate ids rejected; removed ids rejected.
2. Trims: set_trims persists `{start,end}`; absent key = full clip; non-video
   target rejected; out-of-range / start>=end rejected.
3. Duration: photo default + video(duration−trim) combined math; duration
   stored on video entry at finalize.
4. Limit: over-limit order rejected with excess seconds message; over-limit
   trims rejected; under-limit allowed.
5. Stale: order edit clears render_revision; trim edit clears it; finalize
   clears it.
6. Audit: `montage.order_changed` / `montage.trim_changed` recorded with actor.
7. Completed package: montage mutations on a completed package raise
   `PackageCompleted` (read-only invariant from #9).

### Contract (`backend/tests/test_api.py`)

- Auth on all three routes (401); PUT order 409 on over-limit; GET montage
  returns combined duration.

## Out of scope

- Rendering the montage into a Reel (1080x1920 fit, watermark, blurred
  background, intro/outro) — #12.
- Caption and branding edits — #11.
- Actual video re-encoding for trims — trims are stored as metadata and applied
  by the renderer (#12), not by this ticket.
- OpenAPI contract and generated clients — #24.
- Automatic splitting into multiple Reels (explicitly out of MVP scope).
