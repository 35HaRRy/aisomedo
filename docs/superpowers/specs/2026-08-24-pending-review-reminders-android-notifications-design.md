# Pending-Review Reminders and Android Notifications - Design

Date: 2026-08-24
Source: Issue #16 (part of #1, Dojo Reel Publishing MVP), blocked by #15 (done).

## Problem

A due `Yayin Zamani` can now create one durable pending `Yayin Incelemesi`, and
administrators can approve, skip, or reschedule it. The worker does not remind
administrators about pending reviews, paired Android devices have no FCM
registration contract, and reminder cadence is not durable across worker
restarts. Administrators need configurable reminders that honor an Istanbul
delivery window and stop after review resolution.

Issue #16 also names publication success and failure notifications. Publication
execution and recovery do not exist until issues #18 and #19. By explicit scope
decision, this work does not add synthetic outcome producers or callable outcome
hooks. Those issues must add outcome notifications when terminal publication
states exist.

## Decisions

1. **Extend the existing deep `DojoPublishing` module.** Notification policy,
   push-token lifecycle, and due-reminder behavior remain behind the primary
   publishing seam. A second domain facade or notification outbox would add
   interface and persistence cost without leverage for this ticket.
2. **Persist cadence per review.** `YayinIncelemesi.last_reminded_at` records the
   latest completed reminder batch. Scheduler restarts preserve cadence. A
   resolved review leaves `list_pending_reviews()`, so approve, confirmed skip,
   and reschedule stop its reminders without a separate cancellation path.
3. **Honor the delivery window for the first and later pushes.** The default
   policy is every 360 minutes, from 08:00 inclusive until 22:00 exclusive in
   `Europe/Istanbul`. A review created outside that window waits until the next
   allowed time. Configured windows may cross midnight; equal start and end are
   invalid.
4. **One current FCM registration per paired Android client.** Registering a new
   token replaces the client's previous token. Registering a token already owned
   by an older pairing transfers it to the current client. Browser clients cannot
   register. Revoked clients are excluded from delivery.
5. **Use a batch-oriented notifier adapter.** `DojoPublishing` chooses eligible
   reviews and target registrations; a Firebase Admin adapter sends one multicast
   message and classifies delivered, invalid-token, and transient-failure results.
   The existing stub remains the deterministic test adapter.
6. **Use timestamp durability, not an outbox.** Invalid tokens are removed. A
   whole-call failure before any delivery leaves `last_reminded_at` unchanged for
   next-tick retry. A completed batch advances the timestamp, even if individual
   devices report transient failures; those devices are retried at the next normal
   interval. Per-device exactly-once retries require an outbox and are outside this
   design.
7. **Keep the worker alive on notification failure.** Reminder failures are
   logged and audited but do not prevent schedule evaluation, render processing,
   or upload cleanup.

## Domain Model

Add a frozen reminder policy:

```python
@dataclass(frozen=True)
class ReminderPolicy:
    interval_minutes: int = 360
    delivery_start: time = time(8, 0)
    delivery_end: time = time(22, 0)
    timezone: str = "Europe/Istanbul"
```

`YayinIncelemesi` gains:

```python
last_reminded_at: datetime | None = None
```

Add notification value objects representing a stable push payload and delivery
classification. FCM data values are strings and include:

- `type=review_required`
- `review_id`
- `review_version`
- `package_folder`

Notification title and body start as centralized Turkish constants. Stable data
keys, not localized text, drive Android deep links in issue #36.

## Ports and Adapters

`Notifier` changes from a title/body fire-and-forget method to a batch method that
accepts target tokens and a typed notification, then returns delivered tokens,
invalid tokens, and transiently failed tokens.

Add notification-registration storage methods behind a focused store protocol:

- register or transfer one token to a client;
- remove a client's registration;
- remove registrations by token;
- list registrations belonging to active, non-revoked Android clients.

`ReviewStore` adds a method to persist `last_reminded_at` for a pending review.
`InMemoryStore` and `PostgresStore` implement both storage surfaces.

The production Firebase adapter uses the Firebase Admin SDK and Application
Default Credentials. Worker configuration explicitly enables FCM; when enabled,
missing or invalid credentials fail worker construction rather than silently
discarding notifications. Local development and tests use the stub unless FCM is
enabled.

## Facade Interface

`DojoPublishing` gains:

- `get_reminder_policy() -> ReminderPolicy`
- `set_reminder_policy(policy, requester=None) -> ReminderPolicy`
- `register_push_token(client_id, token) -> None`
- `remove_push_token(client_id) -> None`
- `send_due_reminders() -> None`

Policy validation rejects non-positive intervals, equal delivery-window bounds,
and any timezone other than the MVP's fixed `Europe/Istanbul` timezone.

`send_due_reminders()` performs this flow:

1. Load policy and convert the injected clock to Istanbul local time.
2. Return when outside the configured delivery window.
3. Load pending reviews and select reviews never reminded or whose interval has
   elapsed.
4. Load active Android registrations.
5. If no targets exist, leave the review timestamp unset so a newly registered
   device receives the next worker tick.
6. Send one multicast message per eligible review.
7. Remove invalid tokens, audit delivery counts, and persist the completed batch
   timestamp.

## Worker Flow

The worker tick order becomes:

1. evaluate due work;
2. process one claimed job, if present;
3. dispatch due reminders;
4. sweep stale uploads.

Sending after job processing lets a review created by render completion notify in
the same tick. A review created directly from an already-current render follows
the same path.

## HTTP Contracts

Authenticated settings routes:

- `GET /api/settings/reminders`
- `PUT /api/settings/reminders`

The response and update body expose `interval_minutes`, `delivery_start`,
`delivery_end`, and fixed `timezone`. Invalid policies return `422`.

Authenticated pairing routes:

- `PUT /api/pairing/me/push-token`
- `DELETE /api/pairing/me/push-token`

The PUT body contains the current FCM token. Registration is allowed only for the
authenticated Android client. Browser registration returns `422`. Tokens are
stored because FCM requires their plaintext values, but are never returned after
registration, written to audit details, or logged.

## Persistence

Migration `0011_pending_review_notify` adds:

- `yayin_incelemesi.last_reminded_at`, nullable timezone-aware timestamp;
- `push_registrations.client_id`, primary key and foreign key to `clients.id`;
- `push_registrations.token`, unique text;
- `push_registrations.updated_at`, timezone-aware timestamp.

Reminder policy values use the existing generic settings store, so no policy table
is needed. Test database cleanup includes `push_registrations` before `clients`.

## Error Handling

- Invalid or unregistered FCM tokens are removed after a completed batch.
- Per-token transient failures are counted and audited without aborting other
  deliveries.
- A whole-call Firebase failure records a failure event and leaves reminder
  cadence unchanged for retry.
- Token registration validates paired client existence, kind, and revocation.
- Notification exceptions do not escape the worker tick.

## TDD Seams

Tests are written in vertical red-green slices at these pre-agreed seams:

1. **`DojoPublishing` seam:** fake clock, in-memory store, and `StubNotifier`
   verify first eligible delivery, quiet-window deferral, interval cadence,
   restart persistence, delivery to all active Android devices, token rotation,
   revocation exclusion, and resolution stopping reminders.
2. **FastAPI HTTP seam:** authenticated policy and token contracts, validation,
   browser rejection, and unauthorized responses.
3. **Store adapter seam:** real PostgreSQL verifies registration transfer/removal
   and reminder timestamp persistence.
4. **Worker seam:** `run_tick` verifies reminders run after job processing and
   failures do not skip cleanup.
5. **Firebase adapter seam:** an injected fake Firebase messaging client verifies
   multicast payload and response classification without network credentials.

Tests do not target private helpers, SQL query shape, or Firebase internals.
Focused test files and mypy run throughout implementation; the full suite runs
once after all slices pass.

## Out of Scope

- Publication success/failure notifications; issues #18 and #19 must emit them
  from real terminal publication states.
- Android notification receipt, durable inbox, deep-link navigation, and UI;
  issue #36 consumes this server contract.
- Web Push, email, or SMS.
- Per-device delivery outbox, immediate transient retries, or exactly-once push.
- Multi-worker scheduler leadership; issue #21 owns that deployment guarantee.
