# Web resumable upload flow — issue #27

Date: 2026-10-01
Issue: https://github.com/35HaRRy/aisomedo/issues/27
Parent: #1, Dojo Reel Publishing MVP
Prerequisites: #7 and #25 are closed.
Status: design, written spec, and implementation plan approved; Native execution selected in an isolated worktree.

## Intent and approved decisions

Dojo administrators upload photos and videos from a paired browser into the
Aktif Paket. Success means visible progress, pause/resume/retry, recovery after
network interruptions and page reload, oversized-file rejection before media
bytes transfer, and backend-authoritative validation feedback.

The user selected metadata-only persistence: after reload, users reselect the
original file. Do not persist file contents or require filesystem permissions.
The approved design uses sequential, checksummed 2 MiB chunks, a chunk-based
file fingerprint, the existing Current Package area, Turkish-first strings,
and minimal additive backend APIs. Filename-conflict resolution remains #28.

## Architecture and alternatives

Add a focused upload module under `web/src/uploads/`. Its public interface
exposes upload rows and select, pause, resume, retry, and dismiss operations.
Keep transfer scheduling, fingerprinting, range reconciliation, and durable
metadata independent of React rendering so these behaviors can be tested with
fake transport and storage. A thin React adapter binds it to session lifetime.

Mount the adapter inside the paired shell so navigation between its four areas
does not discard selected files or interrupt transfers. Current Package renders
the upload controls and rows using the existing visual language. Session loss
or shell unmount aborts requests and drops in-memory File references. Stale
responses cannot update a newer controller or session generation.

Reuse generated API types and the existing same-origin request helper. Backend
routes remain adapters over `DojoPublishing`; worker validation/finalization
and durable server upload records remain unchanged.

Alternatives considered:

- Persist entire files in IndexedDB: automatic recovery without reselection,
  but large videos require quota handling and potentially duplicate gigabytes.
- Rely only on in-memory state: simpler, but cannot recover after reload.

Metadata-only persistence provides reload recovery without either trade-off.
No new frontend state library, worker service, or product dependency is required.

## User flow and scope

Current Package exposes a labelled multiple-file picker with supported-format
guidance: JPEG, PNG, WebP, HEIC/HEIF, MP4, and MOV. The picker accept attribute
is a convenience, not media validation. Do not claim a file is valid based on
extension or supplied MIME type; the backend inspects actual content.

Each selected file has an independent row showing filename, byte progress,
percentage, current phase, and available actions. Transfers run sequentially
across files; queued server processing does not block transferring the next
file. Failed or paused rows do not prevent other eligible rows from continuing.

Distinct phases include preparing/fingerprinting, waiting, uploading, paused,
file reselection required, retryable transfer error, queued, processing,
finalized, failed validation, filename conflict, and expired/aborted.

- Pause cancels the active request and prevents subsequent chunks for that row.
- Resume/retry reconciles server status before scheduling more work.
- After reload, receiving rows require explicit file reselection and resume.
- Retry after failed validation starts a new upload only through an explicit
  user action with a selected file; a failed server upload is not resumable.
- Dismiss removes terminal rows and their metadata. Paused receiving rows remain
  recoverable rather than being silently abandoned.
- Filename conflicts show an explanatory blocked state. No automatic rename,
  overwrite, resolution request, or repeated transfer retry is permitted.

Uploading into an empty installation uses the existing start-upload behavior
that creates an Aktif Paket. Refresh the package summary after initialization
and finalization. No package-selection UI, ordering, trims, media deletion,
background Web Push, or Android UI changes belong to this issue.

## Limits and pre-transfer checks

Add authenticated `GET /api/media/upload-limits`, outside the dynamic upload-ID
route. Return `max_file_bytes` and `max_package_bytes` from the existing public
`DojoPublishing.get_upload_limits()` method. Reads must not create packages,
uploads, jobs, or audit events.

Load limits before permitting upload initiation. Reject an empty file or a file
larger than the configured per-file limit locally, before fingerprinting or
sending media bytes. Display the configured file and package limits. If limits
cannot be loaded, show retry rather than silently substituting default limits.

Initialize each upload with the existing filename, content type, and declared
size request before sending any chunk. Backend initialization remains the
authoritative per-file/package capacity check, including in-flight uploads and
changes made by other clients. HTTP 413 or package-capacity HTTP 409 produces
clear feedback and zero chunk requests. Do not attempt to infer remaining
package capacity from dashboard data. Recheck limits for explicit new-upload
retries; resumed receiving uploads follow their existing server state.

## File identity and bounded-memory preparation

Read the file in fixed 2 MiB slices and compute each slice's SHA-256 using Web
Crypto. Fingerprint the ordered chunk-hash sequence together with file size
and chunk size. This is a content identity, not merely a filename/timestamp
comparison, and is not advertised as the conventional whole-file SHA-256.

Persist the resulting fingerprint and chunk hashes as metadata. Preparation
and reselection verification use bounded buffers; never call arrayBuffer on
the entire file. Preparation is visible and cancellable. Transfer reads chunks
again, an accepted extra local-file pass that avoids multi-gigabyte buffering.

After reload, verify filename, size, and the content fingerprint before sending
any bytes to the saved upload ID. Modification time may be recorded for display
but is not sufficient proof of identity. A mismatched selection leaves the saved
upload unchanged and requests the original file. Hash failure or unavailable
Web Crypto yields actionable feedback; never bypass checksums.

## Transfer, reconciliation, and ambiguous responses

Use `PUT /api/media/uploads/{upload_id}/ranges` with the existing offset and
checksum query parameters and raw chunk bytes. A chunk is at most 2 MiB, below
the backend's 8 MiB ceiling. The last chunk may be shorter. Retain bounded
memory and one transfer request at a time; prevent duplicate user actions.

Server `received_ranges` and `received_bytes` determine confirmed progress.
Check the implementation's range representation rather than inventing another
wire format. Skip fully acknowledged chunks; retransmit a partially covered
chunk using existing idempotent overlap handling. Upload progress reaches 100%
only when all media bytes are acknowledged, not when validation succeeds.

Pause, timeout, connection loss, or an aborted PUT may occur after the server
stored bytes. Before continuation, GET the known upload ID and reconcile ranges.
Do not assume a lost response means the server received nothing. Explicit retry
is sufficient; unbounded automatic retry loops are forbidden.

Once coverage is complete, POST complete exactly once per active attempt.
If its response is lost, GET status: queued/processing/finalized means completion
was accepted; receiving permits another complete request. Never create a new
upload merely because a chunk or completion response was lost.

Persist a known upload ID before starting transfer. If initialization itself
loses its response, no media bytes have been sent and no recoverable ID is known.
Report initiation failure; an explicit new attempt may create another empty
upload. Existing backend stale-upload cleanup handles the orphan. This issue
does not introduce an initialization idempotency protocol.

404 or aborted/expired status means the saved upload cannot resume. Show a
new-upload action requiring explicit consent rather than silently starting over.
A filename conflict or other non-receiving status prevents all further chunks.

## Persistence and session safety

Use versioned, validated localStorage records partitioned by paired client ID.
Records contain upload ID when known, file name/size/type/modification time,
chunk size, chunk hashes, fingerprint, and last known server status/progress.
No File/Blob contents, session cookie, credential, or access token is stored.

Validate parsed records, bounds, hash shapes, and supported schema version;
ignore malformed records safely. Backend status overrides stored progress.
Do not automatically attach a new file to an upload using filename alone.
Recovery targets only IDs recorded by this browser; it need not reconstruct
another device's uploads from the server's active-upload list.

Persist metadata before first transfer and after acknowledged progress/status
changes. Storage failure must not crash the shell: show that reload recovery
is unavailable while allowing in-memory transfer. Never claim metadata was
saved when a write failed. Retain records through temporary session expiry,
but only show them after authentication as the same client.

HTTP 401 cancels all protected upload work, clears visible rows and File
references, invalidates the existing session, and returns to pairing. Ordinary
network errors do not invalidate authentication. No background transfer occurs
after reload or shell teardown. Coordinating independent tabs is out of scope;
server range idempotency remains the safety boundary for duplicate bytes.

## Validation, refresh, and error presentation

Completion queues worker processing. Poll known queued/processing IDs on the
existing five-second foreground cadence, immediately on visibility return,
focus, and reconnect. Coalesce triggers and avoid overlapping status requests.
Hide/cleanup cancels polling; visible retryable errors preserve last known state.
Pause of a browser transfer does not pretend to pause server processing.

Only server `finalized` means media entered the package. Show queued and
processing separately. On `failed`, display backend `error_reason` as escaped
diagnostic text beneath localized explanatory copy, never as HTML. Do not
replace backend validation with a client-side format guess. Finalization updates
the package summary; failure must not be shown as package media success.

Extend `ApiError` additively to retain safe textual HTTP detail when supplied,
preserving existing status-based callers. Upload UI uses localized messages for
authentication, network, file-size, package-capacity, checksum, expiry, conflict,
and server failures. Raw media rejection diagnostics are displayed as data;
request bodies and credentials are never included in errors or logs.

## Accessibility and visual behavior

Reuse existing summary-sheet, notice, button, and responsive shell conventions.
All authored copy and accessibility labels live in the Turkish string catalog.
Use labelled controls, filename-labelled native progress elements, textual
status, keyboard-operable actions, visible focus, and polite phase announcements.
Do not announce every acknowledged byte as a screen-reader alert. Errors are
announced and remain adjacent to their row. Long filenames wrap at mobile widths;
status must not depend on color alone. No visual redesign is required.

## Contract compatibility

FastAPI remains the source of truth. Regenerate committed OpenAPI, TypeScript,
and Kotlin artifacts for the new limits operation. Existing init/range/status/
complete/abort/resolve endpoints retain their wire semantics. No database
migration, Android minimum-version bump, or changes to processing formats.

## Verification and acceptance mapping

### Progress, pause, retry

- Multiple files transfer sequentially; each exposes confirmed byte progress.
- Pause aborts in-flight work and schedules no more chunks for that row.
- Resume/retry rechecks status, skips confirmed chunks, and handles partial ranges.
- An acknowledged-on-server/lost-response PUT does not duplicate progress.
- Complete response loss reconciles without creating another upload/job.
- Navigation preserves selected files; session changes reject obsolete responses.

### Interruption recovery and size rejection

- Reload restores metadata and prompts for reselection; identical content resumes.
- Same name/size but changed content is rejected before any resume PUT.
- Fingerprinting never buffers the full file; preparation can be cancelled.
- Configured oversize and zero-byte files create no upload or chunk requests.
- Backend 413/package-capacity 409 sends no chunks; limits failure exposes retry.
- Corrupt/unavailable storage, unknown IDs, expiry, and 401 have explicit outcomes.

### Backend-consistent feedback

- Queued/processing is not displayed as finalized; finalized refreshes the package.
- Real backend validation failure shows its escaped actionable reason.
- Filename conflict blocks transfer without invoking #28 resolution.
- Foreground polling pauses when hidden, resumes promptly, and never overlaps.

Backend tests verify limits authentication, configured/default values, read-only
semantics, and contract freshness. Web tests use deterministic transport/storage
and File fixtures to cover the behaviors above through the public module and UI.
Run web tests, typecheck/build, affected backend tests, Python lint/type checks,
and generated-contract drift checks. Browser verification covers desktop/mobile,
keyboard controls, progress/error states, and reload/reselection using fixtures;
real multi-gigabyte files or Instagram credentials are not required.

## Out of scope

Filename-conflict decisions (#28), media management/ordering/trims (#29), review
actions (#30), persistent media blobs, filesystem-access permissions, background
uploads, automatic retry policies, cross-tab locks, initialization idempotency,
and unrelated upload-backend concurrency or cleanup redesigns.
