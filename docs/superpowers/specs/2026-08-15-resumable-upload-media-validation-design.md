# Resumable Upload, Media Validation, and Finalization — Design

Date: 2026-08-15
Source: Issue #7 (part of #1, Dojo Reel Publishing MVP), blocked by #6 (done).

## Problem

Administrators upload photos and videos into the active `Dojo Paylaşım Paketi`
from Android and the web. Uploads are large (mobile video), networks are
unreliable, and corrupt or unsupported media must never enter a Reel. The
system must support resumable chunked uploads with checksums, progress, pause,
and retry; validate real media content; normalize images and transcode video to
Instagram-compatible H.264/AAC; enforce configurable per-file and per-package
limits before transfer and at finalization; and finalize media into the active
package only after full validation, with temporary uploads cleaned up.

## Decisions

1. **Seam placement**: extend the deep `DojoPublishing` facade
   (`dojo/publishing.py`) — same as #6. No new facade. `process_job` runs
   through a swappable `MediaProcessor` adapter injected like `clock`/`meta`.
2. **Async processing**: the worker owns media validation, normalization, and
   transcode. `complete_upload` enqueues a `media.process` job; the worker
   claims, processes, and finalizes. Matches the MVP "worker owns processing"
   decision and keeps FastAPI requests fast.
3. **Processed + original stored**: the package folder holds
   `media/<media_id>/original.<ext>` and `media/<media_id>/processed.<ext>`.
   The processed artifact is used by the montage; the original is retained per
   the MVP "originals retained" wording.
4. **Offset-based resumable transfer**: client sends `offset`, `length`,
   `checksum_sha256`, and chunk bytes. Server merges ranges into
   `received_ranges`, idempotently absorbing duplicates/overlaps. Resume = GET
   current received ranges. Progress, pause, and retry are queryable state; the
   client drives pause by simply stopping. No server-side pause timer.
5. **Postgres uploads + jobs tables**: transfer state and processing state are
   durable across restarts. Exactly-once finalization via guarded status
   transitions. Staging bytes under `media_root/tmp/<upload_id>/` outside any
   package folder.
6. **Pillow for images + ffmpeg for video**: Pillow (+ pillow-heif) validates,
   decodes (incl. HEIC/HEIF), and normalizes images; ffmpeg probes and
   transcodes video. One shared toolchain in the worker.
7. **Image normalization**: decode, bake EXIF orientation into pixels, reject
   animated images, convert to canonical JPEG (RGB), cap longest side at
   4000px. Render (#12) later fits the canonical JPEG onto the 9:16 canvas.
8. **Video transcode**: re-encode to MP4 H.264/AAC (`yuv420p`,
   `+faststart`) at the original resolution. Render (#12) handles trim and
   blurred-fit at render time, so #7 does not pre-fit to 1080x1920.
9. **Limits via generic settings store**: new `settings(key, value JSON)`
   table. `upload.max_file_bytes` (default 2 GiB) and
   `upload.max_package_bytes` (default 20 GiB). Operator-configurable via a
   CLI; reused later by branding (#11), schedule (#13), onboarding (#24).
10. **Temp/cleanup**: staging under `media_root/tmp/`. Cleanup via explicit
    `abort_upload`, auto-cleanup on finalize success/failure, and a periodic
    sweep of stale `receiving`/`queued` uploads older than a 24h TTL.
11. **Finalize boundary**: finalize writes `original` + `processed` under
    `media/<media_id>/`, appends a `MediaEntry` to `manifest.media`, appends
    `media_id` to `manifest.order`, and audits `media.finalized`. Basic
    filename safety (reject path separators/control characters) is enforced at
    upload start; case-insensitive collision handling and keep/overwrite
    decisions are #8; render-fit is #12.
12. **Auth**: media routes sit behind `get_current_client`, same as every
    other `/api` business route. Equal privilege for device + browser.

## Domain model

`Manifest.media` entry shape (consistent with the #6 contract):

```python
{
    "media_id": "<uuid>",
    "filename": "<safe display name>",
    "content_type": "<original mime>",
    "size_bytes": <original size>,
    "uploaded_at": "<iso8601>",
    "status": "finalized",
    "processed": {
        "path": "media/<id>/processed.jpg|.mp4",
        "content_type": "image/jpeg|video/mp4",
        "size_bytes": <processed size>,
    },
}
```

`media_id` is a UUID generated at finalize — immutable per the MVP contract.
`manifest.order` gains the `media_id` at finalize (append, per #38 user story).

New models (`dojo/model.py`):

- `MediaEntry` — the media dict shape above (builds the manifest dict).
- `Upload` — transfer state (`upload_id`, `package_id`, `filename`,
  `content_type`, `declared_size_bytes`, `received_ranges`, `received_bytes`,
  `status`, timestamps, `error_reason`).
- `UploadStatus` — API-facing progress (`upload_id`, `received_bytes`,
  `declared_size_bytes`, `status`, `received_ranges`).
- `Job` — processing queue (`job_id`, `upload_id`, `kind`, `status`, `payload`,
  `error_reason`, timestamps).
- `ProcessedMedia` — processor result (`original_path`, `processed_path`,
  `content_type`, `size_bytes`, plus optional `dimensions`, `duration`).

`Upload` statuses: `receiving` → `queued` → `processing` → `finalized` |
`failed` | `aborted`. `Job` statuses: `queued` → `processing` → `done` |
`failed`.

## Storage

Migration `0005_media_upload` creates three tables:

```sql
CREATE TABLE uploads (
    id BIGSERIAL PRIMARY KEY,
    upload_id VARCHAR(36) NOT NULL UNIQUE,
    package_id BIGINT NOT NULL REFERENCES packages(id),
    filename VARCHAR(255) NOT NULL,
    content_type VARCHAR(128) NOT NULL,
    declared_size_bytes BIGINT NOT NULL,
    received_ranges JSON NOT NULL,
    received_bytes BIGINT NOT NULL,
    status VARCHAR(16) NOT NULL,
    error_reason VARCHAR(512),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE jobs (
    id BIGSERIAL PRIMARY KEY,
    job_id VARCHAR(36) NOT NULL UNIQUE,
    upload_id BIGINT NOT NULL REFERENCES uploads(id),
    kind VARCHAR(32) NOT NULL,
    status VARCHAR(16) NOT NULL,
    payload JSON NOT NULL,
    error_reason VARCHAR(512),
    created_at TIMESTAMPTZ NOT NULL,
    claimed_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

CREATE TABLE settings (
    key VARCHAR(64) PRIMARY KEY,
    value JSON NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
```

Plus indexes on `uploads(upload_id)`, `jobs(job_id)`, `jobs(status)`,
`uploads(status)`.

`PackageStore` and `AuditStore` unchanged. `SettingsStore` (`get`/`set`),
`UploadStore`, and `JobStore` are new protocols on `dojo/ports.py`; both
`InMemoryStore` and `PostgresStore` implement them. `PostgresStore` claims jobs
with a guarded update (`WHERE status='queued'`) for exactly-once semantics.

## Ports

New protocols (`dojo/ports.py`):

- `UploadStore` — `create(upload)`, `get(upload_id)`, `get_by_id(id)`,
  `update(upload)`, `list_active()`, `list_stale(cutoff)`.
- `JobStore` — `create(job)`, `get_by_upload(upload_id)`, `update(job)`,
  `claim_next()`.
- `SettingsStore` — `get(key, default)`, `set(key, value)`.
- `MediaProcessor` — `process(upload, original_path, work_dir) ->
  ProcessedMedia`. Real adapter `PillowFFmpegProcessor` in
  `dojo/adapters/media.py`; `StubMediaProcessor` for tests.
- `Clock`, `AuditStore` unchanged.

## Facade (`dojo/publishing.py`)

- `start_upload(filename, content_type, declared_size_bytes, requester) ->
  UploadStatus`.
- `append_upload_range(upload_id, offset, length, checksum_sha256, data) ->
  UploadStatus`.
- `get_upload_status(upload_id) -> UploadStatus`.
- `complete_upload(upload_id, requester) -> UploadStatus`.
- `abort_upload(upload_id, requester) -> None`.
- `claim_next_job() -> Job | None`.
- `process_job(job_id) -> None` — worker calls `MediaProcessor`, then
  `finalize_media` on success or marks failed on `MediaValidationError`.
- `finalize_media(job_id, processed) -> None`.
- `sweep_stale_uploads(ttl) -> int` — worker tick.
- `get_upload_limits() -> UploadLimits`.

### Rules

- Filename safety enforced at start: reject path separators, control
  characters, and empty names. `MediaValidationError`-free.
- Per-file limit checked against declared size at start (pre-transfer).
- Per-package limit: `sum(manifest.media size_bytes) + declared + in-flight
  declared` vs `max_package_bytes` at start.
- Ranges must lie within `[0, declared_size_bytes)`; checksum must match chunk
  bytes; duplicate/overlap absorbed idempotently.
- Complete requires full coverage of `[0, declared_size_bytes)`.
- Disk availability checked at finalize (`shutil.disk_usage` on `media_root`
  vs required bytes).
- Exactly-once finalize: guarded by upload `status`; a second finalize is a
  no-op/`UploadConflict`.
- Media enters the manifest only after validation succeeds (`media.finalized`).

## Exceptions (`dojo/exceptions.py`)

- `UploadNotFound(DojoError)`, `UploadNotReceiving(DojoError)`,
  `UploadChecksumMismatch(DojoError)`, `UploadTooLarge(DojoError)`,
  `PackageLimitExceeded(DojoError)`, `UploadIncomplete(DojoError)`,
  `UploadConflict(DojoError)`, `MediaValidationError(DojoError)`.

## MediaProcessor (`dojo/adapters/media.py`)

Real adapter using Pillow + ffmpeg:

- Detect real content by magic bytes/Pillow/`ffprobe`, not extension.
  Accepted: JPEG, PNG, WebP, HEIC/HEIF, MP4, MOV.
- Reject: animated images (WebP/GIF with >1 frame), corrupt files, unsupported
  codecs — each with an actionable `error_reason`.
- Normalize images: bake EXIF orientation, RGB, canonical JPEG, longest side
  cap 4000px.
- Transcode video: `ffmpeg -i <orig> -c:v libx264 -pix_fmt yuv420p -c:a aac
  -movflags +faststart <processed.mp4>`, same resolution; verify output with
  `ffprobe` (H.264/AAC).
- Return `ProcessedMedia` with original + processed paths and metadata.

Dependencies: `dojo-core` gains `pillow` and `pillow-heif`. ffmpeg tests reuse
the existing `jrottenberg/ffmpeg` docker fixture pattern (`render_test_clip`,
`probe_duration` in `dojo/testing.py`).

## Worker (`worker/src/worker/main.py`)

- `run_tick` gains media processing: `claim_next_job()` → `process_job` →
  finalize/fail; then `sweep_stale_uploads(ttl)`.
- Worker container installs ffmpeg.

## FastAPI integration

New `backend/src/backend/routes/media.py`:

- `POST /api/media/uploads` — init. Body: `filename`, `content_type`,
  `declared_size_bytes`. 400 bad filename, 413 file over limit, 409 package
  over limit.
- `PUT /api/media/uploads/{upload_id}/ranges` — chunk. Body: `offset`,
  `length`, `checksum_sha256`, `data`. 400 checksum, 404 not found, 409 wrong
  status. Chunk size bounded (≤ 8 MiB).
- `GET /api/media/uploads/{upload_id}` — progress for pause/resume.
- `POST /api/media/uploads/{upload_id}/complete` — 409 if incomplete.
- `POST /api/media/uploads/{upload_id}/abort`.
- `GET /api/media/uploads` — list in-flight uploads + progress.

All behind `get_current_client`. Routes are thin; all domain rules live in the
seam. `main.py` includes the new router.

CLI (`backend/src/backend/cli.py`): `dojo-settings set-upload-limits
--max-file-bytes --max-package-bytes`, mirroring `dojo-consent`. Defaults
seeded in code.

## Testing

### Domain (`dojo-core/tests/test_upload.py`, in-memory + `pg_store`)

1. Start: filename safety; per-file over-limit rejected pre-transfer;
   per-package limit (existing + declared + in-flight); audit `upload.started`.
2. Append: checksum mismatch rejected; out-of-range rejected; duplicate/overlap
   idempotent; progress reported; staging file assembled.
3. Complete: incomplete rejected; complete → `queued` + job created + audit;
   exactly-once (second complete no-ops).
4. Process/finalize (stub processor): artifacts under
   `media/<id>/{original,processed}`; manifest.media + order appended; upload +
   job finalized; audit `media.finalized`. Failure → job/upload failed +
   `error_reason` + staging cleaned. Exactly-once finalize.
5. Abort + sweep TTL: staging deleted, status aborted/expired, audit.
6. Disk availability at finalize (monkeypatched `shutil.disk_usage`).

### Store (`test_store_upload.py`, `test_store_jobs.py`, `test_store_settings.py`,
`test_db_adapter.py`)

- Roundtrips on both adapters; exactly-once `claim_next` under Postgres;
  settings upsert + defaults; migration creates three tables.

### MediaProcessor (`test_media_processor.py`, real Pillow + ffmpeg fixtures)

- JPEG/PNG/WebP accepted; HEIC accepted; corrupt rejected; animated rejected;
  MP4/MOV accepted; unsupported codec rejected.
- Image normalization: EXIF baked, canonical JPEG, dimension cap.
- Video transcode: H.264/AAC verified by `ffprobe`, same resolution. Skipped
  when docker unavailable.

### Contract (`backend/tests/test_api.py`, `StubMediaProcessor`)

- Auth on all routes (401); init 400/413/409; range PUT 400/404/409; complete
  409; status GET; abort.

### Worker (`worker/tests/test_worker.py`)

- Tick claims → processes → finalizes; sweep runs; failure path marks failed.

## Out of scope

- Filename conflict resolution (keep-both/selected/target, apply-to-all) — #8.
- Media removal, restoration, completed-package browsing — #9.
- Montage ordering edits, video trims, duration limits — #10.
- 9:16 canvas fit, watermark, blurred background, intro/outro — #12.
- Branding and draft configuration — #11.
- OpenAPI contract and generated clients — #24.
- Animated-image support, GIF uploads, audio-only uploads.
