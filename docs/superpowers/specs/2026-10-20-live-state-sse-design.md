# Live State Synchronization for Web and Android

Date: 2026-10-20
Status: Approved by the user; implementation plan review and execution selection pending

## 1. Intent and agreed constraints

Replace periodic foreground data polling with event-driven updates so users can follow processing status and current record values without silently overwriting changes made elsewhere. The initial audience is 2–10 simultaneously active clients.

The agreed solution uses Server-Sent Events (SSE) for server-to-client invalidation and existing HTTP APIs for reads and commands. Both the web application and the foreground Android application are included.

Required behavior:

- No periodic live-state data queries, including a low-frequency polling fallback.
- Changes originating in either the API or worker reach connected, authorized clients.
- PostgreSQL is the source of truth for editable package state.
- Independent media edits merge; conflicting edits require an explicit decision.
- A submitted group of edits either commits completely or does not commit.
- Loss of live connectivity disables editing and state-changing actions, not only saving.
- Local drafts survive application/browser closure on the same device and profile.
- Reconnection restores current state before editing becomes available.
- Existing processing, review, and publication safety rules remain authoritative.

No application code is authorized by approval of this document alone. Implementation requires a separately reviewed plan and a selected execution method.

## 2. Scope and exclusions

### Included

- Foreground web and Android subscriptions for currently displayed data.
- Active package editing, media membership/order, retained video ranges, photo durations, caption, package-specific branding, processing/render status, and displayed review/publication state.
- Invalidation of other currently polled views, such as dashboard, settings/setup, activity, and completed packages, when their underlying state changes.
- Transactional state changes, durable change records, notification delivery, draft recovery, conflict resolution, authorization, and verification.
- Necessary schema and API contract changes for the new source of truth.

### Excluded by agreement

- Migration, backfill, cutover, maintenance-window, and backward-compatibility planning. This document does not authorize deleting or resetting existing data.
- New background push notifications or a continuously connected background Android service.
- Cross-device draft synchronization, offline editing, automatic draft submission, collaborative cursors, or CRDTs.
- Redis, a separate message broker, or a managed realtime service.
- Replacing existing worker scheduling, external-service reconciliation, or upload-transfer protocols merely because they use timers. The no-polling requirement concerns live-view data synchronization; existing background behavior is not expanded or removed here.

## 3. Existing structure and relevant findings

The repository's domain language is defined in `CONTEXT.md`. This document uses Dojo Paylaşım Paketi (publication package), Aktif Paket (active package), Yayın İncelemesi (publication review), and Tamamlanmış Paket (completed package) in that sense.

- `web/src/live.ts` currently refreshes every five seconds and reacts to foreground/connectivity events.
- `web/src/useLiveData.ts` shares that polling mechanism across several views.
- `web/src/packages/usePackageEditor.ts` preserves dirty input but broadly marks drafts stale after external content changes.
- `backend/src/backend/routes/package_models.py` identifies selection writes by package folder, without an expected editable-content revision.
- `dojo-core/src/dojo/publishing.py` replaces the selection map, validates aggregate montage duration, and invalidates render state. Editable manifest state currently lives in `manifest.json`.
- The same domain layer is consumed by API and worker processes. HTTP-route-only notification hooks would miss worker changes.
- `dojo-core/src/dojo/adapters/db.py` already stores audit events, but audit history is not an exhaustive live invalidation contract.
- `backend/src/backend/deps.py` authenticates browser sessions through a cookie and Android clients through bearer credentials.

These observations motivate a shared transactional write boundary rather than a transport-only replacement.

## 4. Architecture and ownership

### Authoritative package state

PostgreSQL owns package membership and order, video selections, photo durations, caption, package-specific branding, editable-content revision, and render/review revision associations. Media binaries and generated artifacts remain on disk.

The manifest becomes a derived representation for artifact and worker compatibility, not an independent writable source of truth. API and worker must not reread it to overwrite authoritative database state. Failure to generate a derived manifest must be surfaced as an artifact/work failure; it must not silently revert committed edits.

A content revision changes when render-relevant content changes. Processing status changes produce their own resource versions/events without unnecessarily changing editable content. Render and review identities remain tied to the exact content/artifact they describe.

### Responsibilities

| Boundary | Responsibility |
| --- | --- |
| Shared domain commands | Merge submitted edits, enforce lifecycle and montage rules, and reject conflicts. |
| PostgreSQL transaction | Serialize competing writes to the affected aggregate; commit state, revision, durable event, and notification together. |
| API-process event listener | Listen for committed PostgreSQL notifications and fan out bounded invalidations to local SSE connections. |
| SSE endpoint | Authenticate, deliver readiness/invalidation/resynchronization signals, and close unhealthy or unauthorized streams. |
| Client live coordinator | Own one foreground stream per web tab/Android app instance, route invalidations, and gate editing on synchronization health. |
| Local draft storage | Persist user input and its comparison baseline independently of the server snapshot. |

No database connection is allocated per SSE client. Each API process owns a dedicated notification listener; ordinary reads continue using the existing database access boundary.

## 5. Transactional commands and merge rules

An edit command identifies the package, carries the baseline content revision, and sends only changed edit groups with their baseline and proposed values. Client baseline values are untrusted input: validate their shape and domain constraints; never use them to bypass authorization or lifecycle checks.

Inside a transaction, the server locks the affected package state, reads its current values, and compares baseline (B), local proposal (L), and current server state (S) for each submitted group:

- If S equals B, apply L.
- If S equals L, treat the proposed result as already present.
- Otherwise, return a conflict rather than overwriting S.

Changes to groups not included in the command remain untouched. An old package revision alone does not reject an otherwise safe independent edit. Structural identity/lifecycle changes can still invalidate the entire command.

### Merge units

- All retained ranges for one video form one group. Start/end values and range-list structure do not merge independently.
- A photo's display duration forms one group.
- Montage order forms one group. Membership changes must also be checked before accepting an order.
- Caption forms one group; related package branding settings are validated as a coherent group.
- Removal of a media item conflicts with a submitted edit to that item. Completion, clearing, or replacement of the target package prevents applying its old draft to another package.

After merging, validate the entire prospective montage, including source durations, ranges, media availability, photos, intro/outro cards, and the configured duration limit. Keep the existing configured limit; do not introduce a new hardcoded limit.

Only after all checks succeed does the transaction store all submitted edits, update the content revision, append the durable change record, and issue the notification. Any conflict or validation failure rolls back the submitted batch. Other clients' previously committed work is not rolled back.

If every proposed value is already present, return the current result without advancing the content revision, producing a duplicate content-change event, or repeating side effects.

Conflict responses identify affected groups and provide current values/revision sufficient to present an explicit decision. Choosing local values is a new conditional command against the displayed current baseline, not an unconditional force-write. A new concurrent change can therefore produce another conflict.

## 6. Durable events and event-driven delivery

Store compact change records containing an event identity, resource kind/identity, resource version, and affected view categories. Do not store credentials, binary content, or signed preview URLs in these records. Keep audit history separate: an operational invalidation is not automatically a user-facing audit action.

Write the change record and invoke PostgreSQL `NOTIFY` in the same transaction as authoritative state. PostgreSQL delivers the notification only after commit. The notification can carry the event identity; listeners fetch committed event details when needed.

This is not a periodically scanned outbox. There is no timer that queries change records, package values, or revision counters. Retained events provide traceability and event-triggered lookup; they are not a promise of unlimited replay. Client recovery depends on a fresh snapshot rather than replaying every historical transition. No separate event-retention worker is introduced by this design.

Notifications cover successful state changes across shared API and worker command paths, including processing, render, review/publication, and setup changes used by subscribed views. All successful authoritative write paths in scope must emit an appropriate invalidation; failed transactions emit none.

Each API listener uses an independent session with short transactions. Database connection loss invalidates the listener's readiness. Affected SSE streams are closed or told to resynchronize; a transport heartbeat must not claim that a broken upstream subscription is healthy.

A server heartbeat writes to the stream but performs no state query. Use a 15-second heartbeat and a 45-second no-traffic deadline as initial transport defaults. Reconnection attempts use exponential backoff with jitter, starting around one second and capped at 30 seconds; attempts establish connectivity rather than polling application records. Infrastructure timeouts must accommodate these defaults.

## 7. Race-free subscription and client refresh

The API commits `LISTEN` before treating its listener as ready. A client stream registers for invalidations before receiving its ready signal. The client then reads the currently displayed resources while already receiving invalidations.

The client coordinator remembers invalidations arriving during a read. If a response could predate an observed change, it performs one deferred follow-up read. Duplicate invalidations are harmless, and resource versions prevent a late response from replacing a newer accepted snapshot. Event identifiers are identities, not an assumed database-wide commit-ordered counter.

An invalidation names what changed, not the entire record. Only active consumers of affected resources refresh. Multiple invalidations are coalesced, and each resource has at most one read in flight plus a pending refresh marker. A successful command may trigger an immediate verification read; an uncertain command result must be reconciled before another mutation.

Clients do not advertise live readiness until the stream is ready and the current view has synchronized. A failed required read keeps editing disabled. A visible retry action is allowed; no automatic periodic data-read retry loop is introduced.

Slow SSE consumers have bounded buffers. Overflow closes the stream and requires reconnection/resynchronization instead of growing memory indefinitely or silently dropping correctness-critical invalidations.

## 8. Connectivity and editing state

Both clients implement these observable states:

| State | Behavior |
| --- | --- |
| Connecting / synchronizing | Show available cached data/draft read-only; editing and mutations disabled. |
| Live | Current view synchronized; editing enabled subject to normal validation and lifecycle rules. |
| Conflict | Draft preserved; conflicting inputs require explicit resolution; batch save disabled until resolved. |
| Disconnected / unhealthy | Disable editing and mutations; preserve draft; show reconnecting status. |
| Unauthorized / revoked | Close stream, disable mutations, invalidate session, and prevent draft exposure to a different identity. |

Connectivity loss may be detected by an explicit transport error, lifecycle transition, or missed-heartbeat deadline. Detection is not instantaneous. Server-side conditional writes remain mandatory during the detection window. Heartbeat intervals and deadlines must be bounded and tested; they are transport controls, not periodic database reads.

The stream carries distinguishable readiness, resource-change, and resynchronization signals. Both clients must observe heartbeat activity; a web transport that hides heartbeat comments must expose heartbeat events instead, or use a streaming reader that can observe the traffic. A connected socket alone is not proof of application-level health.

On backgrounding, stop foreground subscriptions and mark affected views unsynchronized. On return, reconnect and reload before unlocking. A focus event alone does not start a second refresh when the same foreground instance is already live and synchronized.

An in-flight command may have committed when connectivity disappears. Preserve its proposed values and uncertainty marker durably; do not cancel-and-assume-rollback or automatically resubmit it. On recovery, reconcile server state first. Already-applied values are recognized without duplicating effects.

## 9. Durable local drafts

Persist accepted input changes during editing, not only during application shutdown. Use browser-local persistent storage and Android app-private persistent storage through small platform-specific adapters. Drafts are scoped by server/installation, paired-client identity, package identity, and draft schema version.

A draft stores edited values, comparison baselines, relevant versions, and any unresolved/uncertain state needed for safe recovery. It excludes media binaries, authentication credentials, and transient artifact URLs. Invalid or incomplete user input is still draft data and must not disappear merely because it cannot yet be submitted.

On reopening:

1. Restore the local draft read-only.
2. Establish a healthy live subscription and read current authoritative state.
3. Reconcile independent changes without losing local inputs; retain the original baseline for unresolved groups.
4. Present conflicts explicitly. A missing, completed, or replaced package leaves the draft recoverable but inapplicable; never silently retarget it.
5. Enable valid editing only after synchronization. Never automatically submit restored edits.

Persist conflict resolutions and updated safe baselines. Keep current-view and stored draft state consistent across late read/write completions. If the user edits the same draft in two web tabs, storage updates must not silently overwrite the other tab's draft: detect a changed local draft revision and surface a local conflict before replacing it.

A confirmed successful save removes only the acknowledged draft content after local state is durably updated; an explicit discard removes the selected draft content. Do not silently expire drafts. Corrupt or unsupported stored drafts must not be submitted or applied to another package. Report a recovery problem rather than silently claiming successful restoration.

If local persistence fails, visibly report that draft recovery is unavailable. Never claim an unpersisted change is protected across restart. A different pairing/session identity cannot inherit or display the previous identity's draft. Explicit unpairing clears that identity's stored drafts; revocation detected while connected invalidates access immediately.

Recovery is device/profile-local. Browser storage deletion, app-data deletion, device loss, or failure before an edit reaches durable storage is not covered by a cross-device backup guarantee.

## 10. Render and publication safety

The worker captures an immutable rendering input snapshot and content revision from PostgreSQL. It performs expensive processing outside a long database transaction. Before marking an artifact current, it conditionally checks that its input revision is still the current package revision.

If the package changed during rendering, retain or clean up the produced artifact according to existing artifact lifecycle rules, but do not label it current or attach it to a different revision. Record the actual outcome and emit a corresponding invalidation.

A Yayın İncelemesi continues to identify an immutable rendered revision and caption. Live updates never silently replace what a user is approving. Existing review version, lifecycle, and publication checks remain enforced on the server.

SSE does not provide exactly-once command execution or determine whether an external publication succeeded. Preserve existing idempotency and uncertain-publication safeguards.

## 11. Authentication and operational boundaries

Use the existing same-origin browser session cookie and Android bearer authentication. Never place credentials in stream query strings. Authenticate stream establishment and ordinary read/command requests. Limit readable resource categories using the same authorization boundary as the corresponding HTTP APIs.

Pairing revocation and session invalidation must signal the affected API processes to close existing streams, not merely reject their next connection. Session expiration must also terminate stream authorization at its deadline without relying on periodic data queries. A recovered stream must authenticate again.

Do not enable permissive credentialed cross-origin streaming. Serve streaming responses without intermediary buffering or caching; send heartbeat traffic often enough for configured infrastructure idle limits. These requirements apply to the actual hosting path, not only local development.

Existing operational worker-health reporting is not expanded into a new background monitoring system. A committed processing transition produces an immediate event; an unexpected process death is not claimed to be a committed status transition or instantaneously detectable.

## 12. Acceptance and verification

Use existing repository test infrastructure. Verification must cover both normal behavior and concurrency/failure boundaries:

1. Independent edits from two clients merge without replacing untouched selections.
2. Different edits to one video's range group produce a structured conflict; no member of the submitted batch commits.
3. Identical concurrent proposals are accepted as already applied, without duplicating command side effects.
4. Individually valid edits whose merged montage exceeds the limit cause full batch rollback.
5. Media removal, package replacement/completion, and stale order cannot silently redirect or overwrite a draft.
6. State, revision, durable event, and notification share the transaction; rollback produces no visible invalidation.
7. API- and worker-originated changes reach both foreground platforms.
8. A change during initial read, a notification during a read, and out-of-order responses converge to current state without a lost invalidation.
9. Browser/Android disconnects, listener database loss, server restart, and slow-client overflow disable editing and recover through resynchronization.
10. Draft input, incomplete values, conflicts, and uncertain writes survive close/reopen; restore never auto-submits.
11. Local persistence failure, competing tabs, corrupted storage, unpairing, and different identities do not silently lose or leak draft data.
12. A render completing after a content change is not presented as current or substituted into an existing review.
13. Revoked/expired authorization closes streams and blocks commands; credentials do not appear in stream URLs or payloads.
14. An idle foreground client produces heartbeats but no repeated application-state reads. Assert absence of client timers and backend event-table polling used for live synchronization.
15. Foreground lifecycle recovery reads current state before editing unlocks; uncertain commands reconcile without blind retries.

No tests have been run or implementation correctness claimed by this design document. Passing these checks is an implementation acceptance requirement.

## 13. Decision rationale and references

SSE matches predominantly server-to-client updates while preserving existing HTTP commands. WebSocket adds no required bidirectional behavior for this scope. Shorter polling violates the explicit no-periodic-query requirement. PostgreSQL provides the shared transactional boundary already available to API and worker; an additional broker is unnecessary at the expected scale.

Moving editable state to PostgreSQL removes the file-write/database-event gap. Durable events plus notification-driven delivery do not require a periodic dispatcher. Reconnection reads current state instead of promising delivery of every historical event.

- Domain vocabulary: `CONTEXT.md`.
- PostgreSQL 18 NOTIFY transaction semantics: https://www.postgresql.org/docs/18/sql-notify.html
- PostgreSQL 18 LISTEN startup ordering: https://www.postgresql.org/docs/18/sql-listen.html
- Android foreground/background constraints: https://developer.android.com/training/monitoring-device-state/doze-standby

## 14. Review and next-stage gate

- [x] Inspect relevant project flows and domain terminology.
- [x] Establish intent, alternatives, constraints, and section-level design approval.
- [x] Write the English specification without a transition plan.
- [x] Self-review for placeholders, contradictory guarantees, ambiguity, and scope.
- [x] User reviews and approves this written specification.
- [ ] After written-spec approval, create and review an implementation plan.
- [ ] User selects execution method before implementation begins.
