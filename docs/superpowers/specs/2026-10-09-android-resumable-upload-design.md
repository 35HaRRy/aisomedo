# Android resumable background uploads — issue #33

Date: 2026-10-09
Issue: https://github.com/35HaRRy/aisomedo/issues/33
Parent: #1, Dojo Reel Publishing MVP
Prerequisites: #7 and #32 are closed.
Status: conversational design approved; written spec awaiting review.

## Intent and approved scope

Dojo administrators upload photos and videos from a paired Android device into
the Aktif Paket. Success means visible progress, pause/resume/retry, recovery
without retransmitting acknowledged chunks, and oversized-file rejection before
media bytes are transferred. The user explicitly requires transfers to continue
when the app is backgrounded, including when another app is open or the screen
is off, subject to Android's execution restrictions.

The approved architecture uses one resumable transfer engine, user-initiated
data transfer (UIDT) jobs on Android 14+, and foreground WorkManager workers on
Android 10–13. Progress appears in the Aktif Paket area and an ongoing
notification with a pause action. Existing backend APIs remain authoritative.

System suspension, process death, and loss of connectivity preserve transfer
state. They are not promises of uninterrupted execution. Explicit user pause or
OS force-stop must not be bypassed; after force-stop, recovery requires reopening
the app. Reboot recovery must retain records and allow resume after reopening;
automatic immediate execution after reboot is not an acceptance requirement.

## Architecture and alternatives

Add a focused upload module under
`android/app/src/main/java/com/dojo/aisomedo/uploads/` with these responsibilities:

- Transfer engine: bounded-memory preparation, identity checks, range
  reconciliation, chunk transfer, completion, and cancellation. Neither Compose
  nor a platform scheduler owns this logic.
- Durable state: versioned upload metadata and scheduling intent in private,
  no-backup storage, written atomically. Reuse installed Kotlin serialization
  and platform file APIs; no new application database is needed.
- Platform scheduling: a UIDT JobService on API 34+ and a foreground
  CoroutineWorker on API 29–33 both invoke the same engine.
- UI adapter: observe durable upload rows and expose select, pause, resume,
  retry, and dismiss actions without tying transfers to Activity/ViewModel life.

Use one active sequential transfer queue for the current paired session. Each
file has independent progress and intent; a paused or failed file does not block
other eligible files. Stable scheduling identity and a shared execution guard
prevent duplicate engines. Work/job inputs contain a queue identity, not file
contents or credentials. UI observation is lifecycle-bound; transfers are not.

Keep `AppViewModel` responsible for existing pairing and shell state. Integrate
upload cancellation with its session-change, revocation, and update-required
paths. Extend `DojoApi` and generated contract models rather than implementing
another HTTP client. WorkManager is the only new product dependency required.

Alternatives considered:

- WorkManager on every version: fewer adapters, but long-running workers can
  exhaust Android 16 job quota. UIDT is better suited to large user-started files.
- A custom foreground service on every version: avoids that quota but adds
  manual scheduling/recovery and modern dataSync service restrictions.

Two thin platform adapters are justified by Android version requirements, not
by speculative scheduler flexibility.

## File selection, access, and identity

Use the Storage Access Framework document picker for multiple images/videos and
retain persistable read grants. Do not request broad media/storage permissions.
Guide users toward JPEG, PNG, WebP, HEIC/HEIF, MP4, and MOV; actual media validation
remains the backend's responsibility.

Retain a URI, display filename, MIME hint, and declared byte size. Require durable
read access before accepting a file for background upload. If a provider cannot
grant it, show an actionable error asking for a compatible document source;
silently falling back to Activity-only access is not acceptable. If access later
disappears, preserve the upload and request reselection of the original file.

Reject zero-length and oversized files before upload initialization or chunks.
Read provider size metadata when available. For unknown size, determine actual
length through a cancellable bounded-memory scan, stopping when the configured
file limit is exceeded. Show preparation progress/indeterminate state as needed.
Preparation also checks actual bytes against a known declared size; inaccurate
provider metadata cannot bypass limits or produce an inconsistent upload.

Prepare fixed 2 MiB chunks with SHA-256 hashes using platform MessageDigest.
Persist the ordered chunk hashes and a size/chunk-size-bound content fingerprint,
not just a filename or timestamp. Use Long for byte sizes, offsets, and progress.
Memory usage stays proportional to a chunk; do not load a whole video into RAM
or duplicate it into private storage.

Recheck content identity after source reselection or a new engine execution
before resuming a saved server upload. Verify each chunk against its prepared
hash before transmission. A changed file must not mix old and new bytes. Support
non-seekable providers by sequential streaming and skipping acknowledged chunks,
without repeatedly reopening and scanning from byte zero for every chunk.

## Backend contract and transfer semantics

Reuse these existing operations without changing their wire semantics:

- `GET /api/media/upload-limits`
- `POST /api/media/uploads`
- `GET /api/media/uploads/{upload_id}`
- `PUT /api/media/uploads/{upload_id}/ranges` with offset and checksum_sha256
- `POST /api/media/uploads/{upload_id}/complete`

Load limits before preparation/initialization; failure blocks initiation rather
than substituting defaults. Initialize with filename, content type, declared size,
and the limits response's expected active package ID. Server initialization is
the authoritative package-capacity check, including other clients' in-flight
uploads. A 413 or capacity/package-change 409 sends no chunks.

Persist the known server upload ID before transferring bytes. Reconcile status
and received ranges at every resumed attempt. Validate response identity, size,
status, and range bounds; server-confirmed received bytes drive progress. Follow
the existing backend range representation. Skip fully acknowledged chunks and
use its idempotent overlap handling for partially covered chunks.

A lost PUT response does not imply lost bytes. A lost completion response must
be reconciled with GET: queued/processing/finalized means completion succeeded;
receiving permits another complete attempt. Never create a replacement upload
because a known-ID request timed out. If initialization loses its response, no
bytes were sent and no ID is known: show retryable initiation failure; an explicit
new attempt may leave an empty orphan for existing server cleanup.

Only receiving uploads accept further chunks. Queued/processing is server work,
not upload success; only finalized means media entered the Aktif Paket. Refresh
the package summary after initialization and finalization. Refresh known server
processing states on the existing foreground refresh path; do not keep a
background transfer service alive merely to poll processing.

## Background execution and retry

Schedule UIDT from a visible user action on API 34+, declare RUN_USER_INITIATED_JOBS
and the protected JobService, supply network constraints and estimated bytes, and
post/update its required notification. Return control promptly from JobService
callbacks; engine execution uses coroutines off the main thread.

On API 29–33, enqueue unique network-constrained WorkManager work and promote it
with a dataSync foreground notification. Declare required foreground-service
permissions and service type. Both adapters publish filename and confirmed byte
progress through the same localized notification builder and durable state.

Transient connection/server failures use scheduler-supported retry with
exponential backoff, capped at five consecutive failures per file before requiring
manual retry. Reset that counter after acknowledged progress. Ambiguous
initialization without a known server ID requires explicit retry, not automatic
creation of another upload. OS constraint stops are
not user pauses or failed attempts. Restore active intent after system stops as
the scheduler permits; always reconcile server state first. Scheduling rejection
must leave a recoverable row and an actionable retry state.

Persist pause intent before cancelling that row's execution and active HTTP calls.
Cancellation propagates through hashing, file reads, and OkHttp. No next chunk
may start for that paused record. Other eligible rows continue in the shared
queue; cancel the platform task only when no eligible work remains. A late
response may be reconciled later but cannot reactivate a paused row. Explicit
resume schedules the same upload; retry is not an implicit restart.
Notification pause must use the same durable action as the UI, not merely cancel
a scheduler request whose record still says active.

Notifications and actions use Turkish externalized strings, immutable explicit
PendingIntents, a notification channel, and the required notification permission
flow on Android 13+. Permission denial must be explained without crashing or
claiming a notification is visible when Android suppresses it.

## Persistence, session safety, and errors

Records include schema version, local ID, origin, paired client ID, session
binding, URI, size/name/type, chunk hashes/fingerprint, known upload/package IDs,
server-confirmed progress/status, retry count, local intent, and action revision.
Validate records and limit their serialized size before loading. Corrupt or
unsupported records cannot schedule work. Persist identity/upload ID before the
first chunk and state after each acknowledged chunk or action. A storage failure
stops transfer with a storage error instead of claiming restart-safe recovery.

Credentials remain only in the existing encrypted SessionStore. Neither metadata,
work/job extras, notifications, nor logs contain bearer tokens. Bind records to
the pairing that created them; a new pairing at the same origin cannot inherit
old jobs. Recheck current binding before protected work and between chunks.
Cancel active calls and invalidate stale writes on session changes.

401 stops all uploads for that session, clears the credential through the shared
session path, and returns the app to pairing on next observation. 426 suspends
protected upload work until a compatible app resumes it. Ordinary network errors
preserve authentication. Cross-origin redirects remain disabled.

Use localized explanations for network failure, checksum/identity mismatch,
size/package capacity, scheduling/storage/file access, expiry, conflict, and
server failure. Display safe backend validation diagnostics as text, never as
logs containing request bodies or credentials. A filename conflict is a blocked
state with no automatic overwrite; resolution UI is outside #33.

404/aborted/failed uploads require an explicit new-upload retry, with fresh limits
and file validation. Paused receiving uploads retain their server ID. Terminal
rows can be dismissed; releasing URI grants must account for other rows sharing
the same URI. Never delete the user's original media.

## UI and accessibility

Replace the read-only placeholder in `ui/DojoApp.kt`'s Aktif Paket area with a
focused upload panel, retaining PackageSummary and the existing adaptive shell.
Show filename, bytes/percentage, phase, adjacent errors, and valid actions.
Distinguish preparing, waiting for network/system, uploading, paused, retryable,
file access required, queued, processing, finalized, failed, conflict, and expired.

Use labelled controls and progress semantics, textual status rather than color
alone, restrained live announcements for phase changes, wrapped long filenames,
and externalized Turkish copy. App navigation and rotation must not interrupt
work or create another queue. Notification tap opens the Aktif Paket area.

## Verification and scope boundaries

Use existing JUnit, coroutine test, MockWebServer, and Compose test patterns.
Add scheduler tests only where platform behavior cannot be tested through the
shared engine. Tests must cover:

1. Empty/oversized files and capacity rejection send zero media chunks.
2. Chunk hashing/ranges, ambiguous PUT/complete responses, and reconnect resume
   retain the same upload ID and skip acknowledged chunks.
3. Pause during preparation/transfer, late callbacks, retry limits, duplicate
   resume actions, revoked URI access, and wrong-file reselection are safe.
4. Durable reload and session switch/revocation prevent cross-session work;
   storage failure cannot silently discard required recovery state.
5. API-level routing chooses UIDT on 34+ and foreground WorkManager on 29–33;
   backgrounding, screen-off, and notification pause work on representative
   devices/emulators for both paths. System interruption resumes safely.
6. UI progress, Turkish actions, accessibility semantics, processing/failure
   states, and refresh after finalization match confirmed backend state.

Regenerate API artifacts through `backend/scripts/generate_clients.py` if the
Kotlin generator needs existing upload schemas included; FastAPI stays the source
of truth. Verify generation drift, Android unit tests, debug build/lint, and
available instrumentation tests. Record any unavailable device verification
explicitly rather than claiming background behavior was tested.

Out of scope: backend/schema redesign, full-media local copies, Wi-Fi-only policy
controls, background processing polling, package editing, conflict resolution,
and guaranteed execution after user force-stop.

## Platform references

Official documentation checked on 2026-10-09:

- UIDT scheduling, notifications, system stops, and pre-14 WorkManager fallback:
  https://developer.android.com/develop/background-work/background-tasks/uidt
- Long-running workers, foreground services, and Android 16 job quota warning:
  https://developer.android.com/develop/background-work/background-tasks/persistent/how-to/long-running
