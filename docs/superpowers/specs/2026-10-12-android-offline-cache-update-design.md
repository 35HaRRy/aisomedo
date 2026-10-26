# Android offline cache and update prompt — issue #37

Date: 2026-10-12

Source: [issue #37](https://github.com/35HaRRy/aisomedo/issues/37), part of #1.
Prerequisites #32 and #33 are closed.

Status: written specification approved on 2026-10-12; implementation plan awaits review.

## Intent and scope

Let paired dojo administrators inspect the last fetched Aktif Paket and recent
Activity after losing connectivity or restarting offline. Prevent stale edits and
review decisions, preserve transfer progress across reconnect, and direct an
unsupported Android installation to the configured signed release.

The approved approach is a small session-bound JSON snapshot, existing upload
storage/schedulers, and the existing update-required screen. No database, new
product dependency, offline mutation queue, or backend redesign is needed.
Cached data means metadata, not downloaded photos, videos, or review renders.

Activity is currently a placeholder. Add a read-only latest-50-events slice from
the existing Activity API so #37 has real history to cache. Full Activity browsing,
pagination, filtering, and Settings expansion remain #38. Review implementation
remains #36; this issue establishes the shared write gate its actions must honor,
without adding review actions or claiming tests of an absent review flow.

## Existing seams and ownership

- `AppViewModel.kt` owns session startup, dashboard/editor reads, configuration
  writes, session-generation fencing, and HTTP 401/426 handling.
- `DojoApi.kt` owns authenticated transport. Reuse `GET /api/activity?limit=50`;
  generate consumed Activity DTOs through the existing OpenAPI client generator.
- `DojoApp.kt` owns four destinations and the update screen. Extend its cached
  read presentation and propagate write availability to existing components.
- `UploadRuntime`, `UploadEngine`, and `UploadStore` already retain pairing
  identity, upload ID, file identity, received ranges, and user pause intent.
- `UploadScheduler` already uses network-constrained UIDT/WorkManager jobs.
  Preserve these adapters rather than adding a second transfer scheduler.

Add one small snapshot store and one application-context network monitor. The
monitor must cover background transfers as well as the foreground shell; Activity
recreation must not create duplicate observers. Expose connectivity to the model
and upload runtime, with lifecycle-safe observation and injectable test inputs.

## Durable read snapshot

Use one bounded, versioned JSON file in app-private, backup-excluded storage.
The envelope contains normalized server origin, optional opaque pairing binding, client
identity, setup summary, dashboard, active editor metadata, recent Activity,
compatibility/update information, and timestamps for successfully fetched sections.
Persist server snapshots only: credentials, local editor/configuration drafts,
pending commands, and preview bytes are excluded.

Compatibility/update state is origin-scoped and can be saved before pairing.
Protected sections require a binding; unpaired compatibility data never restores
authenticated content. Clear origin-scoped update state when changing servers.

The file is limited to 4 MiB. Use the existing atomic-write pattern: serialize and
validate, write a temporary file, sync, then atomically replace. Perform disk work
off the main thread. A failed write preserves the previous snapshot and reports
storage failure without turning a successful server action into a failed action.
Oversize, corrupt, unsupported-schema, or identity-mismatched content is a cache
miss, never a reason to crash or enable writes. This bounded metadata cache can be
expanded later if actual package sizes exceed its ceiling.

Restore protected content only after successfully reading the current credential and
matching both origin and binding. A cold offline start with a matching snapshot
opens read-only navigation; a missing cache shows an explicit unavailable state,
not invented empty history or an empty package. Sections never fetched before
remain unavailable. A successful response indicating no active package clears old
package/editor content; a failed read retains the last content with its old timestamp.

Refresh dashboard/package and Activity independently so one failed endpoint does
not erase another section. Keep dashboard and editor package identities coherent:
if dashboard identifies a replacement or absent package, invalidate the old editor
snapshot until the matching editor read succeeds. Persist the latest Activity page
on normal refresh, not only after visiting Activity.

Invalidate old protected content on server change, pairing replacement, credential
loss, or HTTP 401. Fence every read, disk commit, and UI update by captured session
generation and binding so delayed old responses cannot resurrect or overwrite
another pairing's cache. Local revocation cannot be discovered offline; restored
content is explicitly historical, and reconnect checks current authorization.

## Connectivity and write gate

Distinguish cached/stale content from authoritative, writable state. Connectivity
loss immediately makes the shell read-only while preserving navigation and data.
A network connection alone does not enable writes: reconnect triggers the existing
compatibility, identity, setup, and dashboard checks. Each resource also needs its
own successful fresh read before its actions become available; a failed editor
read cannot enable package edits. Backend unavailability keeps writes blocked even
when Android reports a connected network.

Use one shared model-level write predicate and enforce it in mutation entry points,
not only disabled buttons. Cover configuration/consent/OAuth submissions, package
order/removal/restore/ranges, new upload selection, upload retry/reselection/dismiss,
and conflict decisions. Gate local edit inputs too. Existing drafts survive a loss
of connectivity but cannot be changed or submitted until freshness is restored.
Cached pending review summaries are display-only. Review actions added by #36 must
combine this predicate with their own fresh exact-review/revision checks.

Only pause and resume of an existing transfer are allowed offline. Resume changes
local intent using the retained document; it cannot replace a document, reset an
expired transfer, or send a network request while disconnected. Notification pause
continues to work without an Activity. A server-change action may clear local
session/cache offline; it is not a backend mutation.

If connectivity disappears during a submitted write, retain existing uncertain
outcome handling and drafts, and reconcile on reconnect. Never automatically replay
configuration, package, conflict, or review commands. Ignore late results from an
obsolete connectivity/session generation when deciding write availability.

## Upload suspension and reconnect

On network loss, cancel active network attempts without calling session-stop,
clearing file identity, resetting received ranges, or changing ACTIVE intent to
user-PAUSED. Disconnected waiting must not consume retry budget. Transport errors
while offline leave eligible uploads recoverable; ordinary online server failures
retain the existing bounded retry policy.

Network restoration wakes eligible work through the existing constrained
scheduler. The engine authenticates and reconciles the existing upload ID/status
before sending missing chunks. A lost acknowledgement is reconciled against server
ranges; an acknowledged chunk must not be retransmitted as a new transfer. Explicit
user pauses survive reconnect and process restart; offline resume schedules pending
work that can run only once connected. Expired/failed uploads still require the
existing explicit online retry, rather than silent creation of a replacement.

Preserve cancellation/revision fences and both scheduler implementations. Respect
Android background restrictions and force-stop; promise recovery, not uninterrupted
execution. Avoid coupling background transfer correctness to a visible Activity.

## Unsupported-version state

Reuse the compatibility minimum-version check and HTTP 426 screen. Persist the
known minimum version and validated HTTPS update URL. Also persist a 426 rejection
for its installed version when the server supplies no new minimum, so restarting
or going offline cannot bypass the gate. Re-evaluate the minimum against the actual
installed version; a rejection of an older installed version does not permanently
block a newly installed APK.

A known unsupported installation shows the update screen instead of cached
authenticated navigation and stops transfers. Failed refresh cannot downgrade it
to a writable or ordinary connection-error screen. A fresh successful compatibility
check may clear a version-specific rejection. HTTP 401 remains credential
revocation, never a cache fallback. Background 426 reaches the same durable gate;
retain a previously known safe URL when that event supplies no URL.

Open only URLs accepted by `safeExternalUrl`; invalid or absent URLs show an
externalized explanation plus retry/server-change controls. The backend-configured
URL points to the existing GitHub signed-release distribution. APK signature
validation remains Android's installer responsibility; this task neither publishes
a release nor adds an in-app installer or signing secrets.

## Presentation

Use existing Compose components, externalized Turkish strings, four destinations,
phone/tablet layout, and accessibility conventions. Show an offline/backend-unavailable
notice and the last successful fetch time for cached package and Activity data.
Keep navigation and historical content readable; visibly disable mutation controls
with an explanation. Distinguish no cached history from a successfully fetched
empty history. Activity rows show action, time, and resolved actor; render server
text as plain text, not HTML, with no invented user-friendly action mapping.
Unavailable media playback is explained rather than represented as cached content.

## Verification and acceptance

Use existing JUnit, coroutine tests, MockWebServer, and Compose/device test setup.
Write failing checks before behavioral changes. Cover:

1. Atomic snapshot roundtrip and offline cold restart; unavailable sections,
   corrupt/oversize/schema-invalid files, write failure, and origin/binding isolation.
2. Cold and warm offline package/Activity navigation, timestamps, empty-versus-missing
   history, replacement-package invalidation, and late old-session responses.
3. Direct mutation calls and disabled UI send no requests offline; pause/resume
   remain local; reconnect and partial-read failures keep affected actions gated.
4. Transfer interruption preserves upload ID, file identity, and acknowledged
   ranges; reconnect uploads only missing chunks; user pause survives; disconnected
   waiting does not exhaust retries. Exercise both pre-34 WorkManager and 34+ UIDT.
5. Compatibility and foreground/background 426 gates survive restart/offline;
   installed-version change, safe/unsafe/missing URLs, and HTTP 401 isolation.

Run Android unit tests, debug assembly, lint, and instrumentation assembly. Run
generator regression checks if generated DTO coverage changes. Execute device
offline/reconnect checks on dedicated test emulators where available, including
background transfers and restart. Record unrun device scenarios as unverified,
not passed; no acceptance claim based only on compilation. Publish verification
notes with observed results and remaining manual checks alongside implementation.

## Workflow checklist

- [x] Inspect issue, adjacent scope, and existing seams.
- [x] Approve design direction.
- [x] Write and self-review this specification.
- [x] User approves the written specification.
- [ ] Write implementation plan; user selects execution method.
- [ ] Implement test-first and verify acceptance evidence.
