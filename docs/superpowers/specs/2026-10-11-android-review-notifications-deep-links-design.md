# Android review, notifications, and deep links — issue #36

Date: 2026-10-11

Source: [issue #36](https://github.com/35HaRRy/aisomedo/issues/36), part of #1

Prerequisites: #12, #15, #16, and #32 are closed.

Status: conversational design approved; this written specification awaits review.

## Intent and scope

Let paired dojo administrators reach one exact `Yayın İncelemesi` from Dashboard,
Activity, or a notification, inspect its Reel and caption, and approve, skip, or
reschedule safely. Reviews remain discoverable after app restart or missed push.
An empty-package notification must continue through upload, render, and review
for the same `Dojo Paylaşım Paketi` and `Yayın Zamanı`.

The user approved reuse of existing backend review/push contracts, one focused
Android review screen, a durable server-backed approval inbox, and existing
session/upload infrastructure. No duplicate local inbox database or separate
notification backend is needed. Business decisions remain in `DojoPublishing`.

Full Activity browsing/settings belong to #38; general offline caching belongs
to #37. This issue adds Activity's approval-inbox section and review navigation,
not those unrelated features. Turkish strings remain externalized, and existing
phone/tablet navigation and accessibility conventions are preserved.

## Existing contracts and narrow backend extensions

Reuse:

- `GET /api/dashboard`: durable pending actions, including occurrence ID, review
  ID/version when available, package folder, and empty/preparing/ready state.
- `GET /api/reviews/pending` and `GET /api/reviews/{id}`: durable review records
  and exact review details. A detail supplies the caption, revision digest,
  readiness, authenticated preview URL, and next regular occurrence.
- `POST /api/reviews/{id}/approve`, `/skip`, and `/reschedule`: revision-aware
  resolution. Skip requires `confirmed=true`; reschedule carries a future instant.
- `PUT` and `DELETE /api/pairing/me/push-token`: one registration per device.
- Existing package upload/editor and `POST /api/packages/active/render`, guarded
  by `expected_folder_name`.
- Existing worker reminder policy, Firebase adapter, and publication outcome
  producer. Outcomes already carry `publication_confirmed` or
  `publication_failed` and `package_folder`.

Current reminders only iterate pending rendered reviews. An empty occurrence
has no review, so the backend needs a narrow extension to notify due empty
packages. Keep it behind the existing publishing seam and worker reminder turn.
Use existing generic settings storage for durable empty-occurrence cadence,
keyed by occurrence and package identity; prune obsolete cadence entries when
work is resolved or no longer empty. No new table, outbox, or scheduler is needed.
Honor the same interval and Istanbul delivery window as review reminders.
Follow existing notification failure and invalid-token handling. Failed dispatch
must never resolve an occurrence or block publication work.

Empty occurrences also have no review ID for Skip/Reschedule. Add authenticated
occurrence-specific resolution routes beside existing review routes:
`POST /api/reviews/occurrences/{occurrence_id}/skip` and `/reschedule`. Bodies
carry `expected_folder_name`, plus `confirmed` or `new_due_at`. Under the existing
package/store transaction boundary, require that this exact due occurrence is
still pending, belongs to the current package context, and has no review yet.
Reject races with render/review creation or another decision using HTTP 409;
missing occurrences return 404. Reuse review resolution's skip/one-off scheduling
semantics, future-time validation, audit attribution, and next-regular-time
response. Never create a synthetic review, change the recurring plan, or act on
a replacement package. These routes live behind `DojoPublishing`, not route-local
business rules. Generate the consumed request/response models from OpenAPI.

## Android ownership and state

Keep the existing four destinations. Review is a focused overlay/flow, not a
fifth main navigation tab. One small review state/component owns fetched detail,
loading/error state, selected action, and continuation identity. Connect it to
the existing lifecycle-owned model and session generation checks without
introducing a navigation framework or rewriting unrelated ViewModel behavior.

Persist only non-secret navigation metadata across recreation: review ID,
expected notification identity, requested action, or occurrence/package identity.
Never persist a credential, preview bytes, or an unsubmitted approval command in
saved-instance state. Rotation and process restoration reload authoritative data;
they do not submit actions. Back closes the focused flow to its owning area.

Dashboard pending rows become actionable. Activity contains an approval inbox
derived from backend pending reviews/actions, including empty and preparing
occurrences. Server persistence is the durability guarantee: restart or a missed
push does not lose a pending decision. Failed reads show unavailable/stale state,
not an invented empty inbox. Refresh on foreground return, explicit refresh,
notification receipt while active, and action completion. Use short lifecycle-
scoped polling while awaiting render or displaying a pending review; stop when
the flow is inactive. No always-running client scheduler or local mutation queue.

## Exact preview and actions

Fetch by review ID; never substitute whichever review is newest. Display the
returned package identity, caption, status, and revision-bound Reel. Only use
the same-origin authenticated preview URL returned by that review detail. Reuse
the existing authenticated transport/preview approach and native video playback;
do not expose credentials to an external browser/player or follow redirects.
Keep downloaded previews private, bounded, and cleared when their review/session
changes. Playback failure is visible and cannot be represented as successful
preview. No new player dependency is required if native playback suffices.

Approve is explicit, available only after fresh pending, render-ready detail
and successful preparation of its exact preview. Submit the displayed review
version. A notification never approves from the lock screen. Backend validation
remains the final guard against edits or concurrent actions.

Skip opens confirmation explaining that this `Yayın Zamanı` is skipped, not the
recurring plan, and displays the next regular occurrence when available.
Reschedule uses native date/time controls, labels `Europe/Istanbul`, and submits
a strictly future offset-aware instant without changing `Dojo Yayın Planı`.
Notification shortcuts open these forms; they never bypass confirmation.

Disable duplicate submission and mutations while loading, stale, disconnected,
unsupported, or unauthenticated. After success, refresh review, inbox, and
dashboard. Distinguish approval acceptance/publication in progress from confirmed
Instagram success. On HTTP 409, reload the exact review and report already
handled versus stale/unavailable render according to authoritative state. HTTP
404 explains that the requested review is unavailable. A timeout or lost response
does not automatically replay an approval; refresh before offering another action.
Existing 401/426 handling clears or blocks the entire authenticated flow.

## Notification delivery and deep links

Add the Firebase Messaging SDK, token lifecycle handling, notification channels,
and Android 13+ runtime notification permission. Firebase initialization uses
operator-supplied Android app configuration matching the backend Firebase project.
Keep configuration outside committed source; unconfigured development builds
still support review/inbox and clearly report push unavailable. Configured release
delivery requires Google Play services and notification permission on the device.

Register the latest token only for the current authenticated device. Retry failed
registration on the next active refresh; token rotation replaces registration.
On server/session changes, remove the previous registration when reachable,
clear notifications/pending destinations, and invalidate old asynchronous work.
Do not log registration tokens or put credentials in notification payloads.

Review-required messages identify `review_id`, `review_version`, and
`package_folder`. Empty-package messages identify `occurrence_id` and
`package_folder`, with stable `type=empty_package`. Push content is a hint, never
authorization or authoritative application state.

Render review and empty-package notifications in the client with Review/Upload,
Skip, and Reschedule shortcuts. These types use user-visible high-priority FCM
data messages, with title/body included for client presentation, so custom
shortcuts work in foreground and background. Extend the existing Firebase adapter
only for these message types; preserve existing mixed notification/data delivery
for publication outcomes and unrelated monitoring alerts. Test both shapes.

Use stable notification tags per review/occurrence and explicit immutable pending
intents. A shortcut identifies the target and desired form, never a POST action.
Validate identifiers and known action/type values at the intent boundary. Handle
both cold start and `onNewIntent`; also handle launcher extras from background
SDK-displayed outcome notifications. Wait for pairing/compatibility readiness
before resolving a target. Bind stored intents to the local session and discard
them after a server/session switch. Fetch and compare expected package/version;
never silently redirect a stale notification to another review.

Resolved/stale review notifications are cancelled when authoritative refresh
observes the change. Publication outcome notifications open refreshed Activity/
package context for their named package, not a different active review. A known
historical package may be identified without implementing the full completed-
package browser. Denied permission or missing Firebase must not hide the inbox.

## Empty-package continuation

1. Validate that the notified occurrence still exists in dashboard pending actions
   and that its package matches before opening upload. Otherwise show stale-target
   messaging rather than uploading into a replacement package.
2. Keep the occurrence/package identity through existing uploads and conflicts.
   No upload completion or screen visit creates a new publication occurrence.
3. Once usable media is finalized, offer Continue to Render and Review; wait for
   outstanding uploads/conflicts instead of treating queued media as finalized.
   Explicit continuation requests render with the expected folder. The existing
   worker also continues due work automatically; the client must tolerate that.
4. Refresh until the same occurrence has a ready review, then open that exact ID
   and revision. Package replacement or occurrence resolution aborts continuation.
   Render failure keeps upload/editor context and offers explicit retry.

No synthetic empty review is created. Empty-stage Skip/Reschedule shortcuts open
the same confirmation/date-time UI, then call the guarded occurrence-specific
routes. If render/review creation won the race, refresh and show the authoritative
review rather than automatically repeating the decision against its new ID.

## Verification and acceptance mapping

- API/state tests: exact review ID/version and authenticated preview binding;
  explicit approve/skip/reschedule bodies; future Istanbul validation; success,
  conflicts, missing reviews, ambiguous responses, cancellation, and session reset.
- Android UI/instrumentation: exact Reel/caption and disabled unsafe actions;
  confirmation/date-time forms; durable inbox reload; cold/warm notification
  navigation; denied permission; stale notification dismissal; no lock-screen
  mutation; rotation does not submit or lose the target.
- Backend seam/adapter tests: empty-package push identity and durable cadence;
  quiet hours; reminders stop when no longer eligible; data-message shortcuts
  versus existing outcome messages; upload/render creates a review for the same
  occurrence/package without duplicate active packages; empty-stage skip and
  reschedule race safely against render completion and each other.
- Continuation tests: delayed finalization, conflicts, render preparation/failure,
  same-occurrence review selection, and stale/replaced package rejection.
- Run affected Android unit tests, compilation/lint, available instrumentation,
  affected Python suites, and generated-client drift checks. Use existing test
  infrastructure rather than adding a new framework.

Live FCM receipt is a separate operator-assisted check on a configured physical
device: trigger review-required, empty-package, and success/failure messages;
verify foreground/background display and exact taps. Synthetic tests prove client
and sender behavior, not real provider delivery. Report unavailable configuration
or hardware as a verification limitation, not a passing acceptance criterion.

## Non-goals and chosen trade-offs

- No local approval database, offline command replay, separate push service,
  new delivery outbox, Web Push, or general Activity/settings redesign.
- Server-backed inbox requires connectivity to refresh; offline caching is #37.
- FCM is best effort, not exactly once. The inbox is the missed-push recovery path.
- Native controls/playback and existing stores win over new abstractions.
- Narrow empty-occurrence resolution is necessary for working notification
  shortcuts; it extends the existing seam rather than introducing another service.
