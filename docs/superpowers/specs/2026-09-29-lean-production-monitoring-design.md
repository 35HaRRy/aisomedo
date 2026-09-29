# Lean production monitoring — issue #22

## Intent and approval

Make production failures visible to the VPS operator and paired Android users.
Issue #22 requires backend, worker, and web health checks; structured logs;
disk-space and failed-job Android alerts; and an external HTTPS uptime monitor.
Issue #21 supplies the production Compose deployment and scheduler leadership.
The parent MVP explicitly excludes a full metrics platform.

The user selected hosted uptime monitoring and approved the in-chat direction:
extend the existing worker and FCM delivery, retain durable alerts, and test
health, low-disk transitions, failed jobs, and delivery retries. This document
expands that direction into a design for review. Defaults below are proposed
design decisions, not existing production settings.

## Architecture

Use three small boundaries:

1. Health probes in backend, worker, and production gateway.
2. A monitoring module behind the Dojo core boundary, with durable database
   state and the existing notifier/device registrations as delivery adapters.
3. A hosted monitor outside the VPS for public HTTPS availability.

Worker integration invokes monitoring outside scheduler database transactions.
Monitoring errors are isolated from publication and review processing. Durable
claims and uniqueness constraints protect delivery across concurrent workers;
a previously observed scheduler-leader flag alone is not a delivery lock.

Alternative: a separate monitoring container adds another process and duplicates
application failure/notification integration. A full metrics stack adds more
operational work than this MVP requires. Extend the existing worker instead.

## Health checks

- Preserve `/health` as a cheap backend liveness endpoint. Add `/ready` for a
  bounded database connectivity check, returning 503 on failure and a minimal
  response without connection details. Production backend checks use readiness.
- Give each worker a container-local, atomically written progress record. The
  probe fails for missing, malformed, or stale records. Idle-loop progress must
  advance; a heartbeat thread that stays alive while processing is stuck is not
  sufficient evidence of progress.
- Record explicit idle/busy phases. Proposed defaults: 120 seconds idle maximum
  age and 3,600 seconds busy maximum age, both configurable and validated. A
  busy deadline is fixed when work starts, not renewed by an unrelated thread.
  Long renders within the configured busy deadline remain healthy. Exceeding it
  marks the worker unhealthy; it does not automatically terminate a render.
- The gateway serves the built web frontend. Check a static health asset from
  that build, independently of the backend route. Make the probe work in both
  dedicated-domain and existing-proxy deployment modes, including host routing.
- Docker unhealthy status is diagnostic; restart policy alone does not restart
  an unhealthy but still running container. Document operator recovery steps.

## Structured logs

Backend and worker emit JSON lines to stdout/stderr with UTC timestamp, level,
service, event, and available job/alert identifiers. Cover startup, job outcome,
monitoring transitions, notification delivery outcome, and unexpected errors.
Configure server/access logging consistently and bound production container log
retention to three 10 MiB files per service.

Exclude credentials, bearer tokens, FCM tokens, OAuth codes, signed URL query
strings, and raw request bodies. Use safe error categories for alerts and
sanitized error logging. Gateway access logs must also exclude sensitive URLs.

## Disk monitoring

Every 60 seconds, sample available bytes and total capacity on configured paths.
Default checks cover the media volume and worker root filesystem. The runbook
must explicitly identify where PostgreSQL and container logs reside: when they
are on a different host filesystem, expose a read-only path for that filesystem
and configure it as an additional target. Do not claim host-wide coverage from
checking the container filesystem alone.

Open a low-space incident below 15% free. Recover at or above 20% free; this
hysteresis prevents flapping. Thresholds and sampling interval are configurable.
Persist incident state across restarts; send one opening and one recovery alert
per incident, rather than one per sample. A failed disk sample logs a monitoring
error and must not be interpreted as recovery.

## Failed-job alerts and durable delivery

Detect persisted terminal job failures, including failures handled internally
without raising from `process_job`. Cover every existing queued job kind.
Use a durable identity for each failed execution, so scans/restarts do not create
duplicate alerts and a later failed retry can produce its own alert. Discovery
must survive a crash between persisting job failure and attempting delivery.
On first activation, include existing failed jobs once and document this behavior.

Persist alert payload, incident/execution key, delivery state, attempt count,
next attempt time, and expiring claim. Resolve active paired Android recipients
through the existing push registration store. Track recipient outcomes so a
partial batch failure does not resend to already successful recipients. Remove
invalid registrations through the existing notification behavior. Recheck
revocation before delivery. No recipients means pending, not successfully sent.

Retry transient failures with exponential backoff starting at 60 seconds and
capped at 3,600 seconds. Keep pending alerts durable across restarts. External
send and database commit cannot be atomic: delivery is at least once. Include a
stable alert ID in message data so Android can replace duplicate notifications.
An FCM acceptance response means provider acceptance, not proof of display.

Use Turkish titles and concise bodies: low space, disk recovery, or failed job;
include safe job type/identifier where useful, never raw exception messages.
Operational alerts use the existing notifier transport but their own event type;
they do not inherit review reminder cadence or quiet hours. Android must display
this event type without assuming every message contains a review ID.

Production configuration must explicitly enable real FCM and mount its
credentials read-only. Keep secrets out of committed files. Verify configuration
fails clearly when real delivery is enabled without usable credentials.

## Hosted HTTPS monitoring

Use a hosted provider with HTTPS polling, certificate validation, and independent
outage/recovery notifications. Provision two checks: the public web health asset
and backend `/ready`, each at a five-minute interval or faster. Require expected
status/body; redirects or an SPA fallback must not count as application readiness.
Send availability alerts through the hosted provider's own notification channel
so VPS failure cannot suppress them.

Keep application code provider-neutral. The deployment runbook supplies exact
check URLs and expected responses, contact setup, and a controlled outage/recovery
drill. Provider/account selection and provisioning are deployment work requiring
access to the operator's hosted account. Record provider, monitor IDs, URLs, and
successful drill evidence without secrets. Documentation alone does not satisfy
the acceptance criterion that an external monitor is present.

## Verification and completion

- Backend readiness fails on unavailable database and recovers when restored.
- Worker probes reject stale/corrupt state and accept legitimate long work within
  its busy deadline; a stuck operation eventually fails the probe.
- Web health checks exercise built assets in both production proxy modes.
- JSON logs parse and sensitive test values never appear in captured output.
- Disk incident/recovery thresholds, restarts, bad samples, and deduplication are
  tested with deterministic clock and disk samples.
- Terminal failures create alerts even when job processing catches exceptions;
  repeated scans, concurrency, retries, and crashes preserve delivery semantics.
- FCM tests cover partial failures, invalid/revoked registrations, no devices,
  and retry backoff. Verify Android operational messages display correctly.
- Run relevant tests and repository checks; validate rendered production Compose.
- On the deployed stack, confirm all three health probes, receive a synthetic
  disk/job alert on an Android device, and perform the hosted outage/recovery drill.

Report code verification separately from live verification. Keep issue #22 open
until actual Android delivery and hosted monitoring are demonstrated, or explicitly
record those unmet acceptance criteria if deployment access is unavailable.
