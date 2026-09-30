# Contract: operational alert push messages

Client-facing contract for the FCM messages the worker sends for operational
alerts (low disk, disk recovery, failed job). The Android client must satisfy
this to display them correctly.

An **operational alert** is not a review reminder. It carries no review ID, no
package ID and no review action, and it is not subject to review reminder
cadence or quiet hours. Any client code that assumes every push contains a
review ID will mis-handle these messages.

## Message shape

All alert data travels in the FCM `data` map (not `notification`), so the client
reads every field from `data` and uses the notification payload only for the
visible text.

| `data` key | Type | Required | Meaning |
|---|---|---|---|
| `type` | string | yes | Always `operational_alert`. This is the switch a receiver must branch on. |
| `alert_id` | string | yes | Stable, durable alert identity. Also sent as the FCM Android notification **tag**. |
| `kind` | string | yes | One of `disk.low`, `disk.recovered`, `job.failed`. |
| `job_id` | string | only for `job.failed` | Identifier of the failed job. Absent for disk alerts. |

Never present: review ID, package ID, any exception text, any filesystem path,
any credential, and any push token. Bodies interpolate only safe labels (a disk
target name, a job kind, a job ID).

### Notification tag

The adapter sends `alert_id` as the Android notification `tag`. The client must
rely on this rather than generating its own: a redelivery of the same alert
replaces the existing notification instead of stacking a duplicate. Delivering
the same alert twice is expected behavior (delivery is at least once), so a
client that appends without honoring the tag will show duplicates.

Notification **ID** is the client's choice; only the tag must come from
`alert_id`. Do not derive a numeric ID from the alert kind, or a recovery
alert and its preceding low-space alert would collide.

## Kinds and text

Text is Turkish and fixed in the backend; the client displays it verbatim and
must not translate or re-word it.

| `kind` | Title | Body shape |
|---|---|---|
| `disk.low` | `Disk alanı azalıyor` | `<target> hedefinde boş alan oranı düşük.` |
| `disk.recovered` | `Disk alanı normale döndü` | `<target> hedefinde boş alan oranı normale döndü.` |
| `job.failed` | `İş başarısız oldu` | `<kind> işi başarısız oldu. İş no: <job_id>` |

For `job.failed`, the `kind` in the body is the job's type (for example a
package render), which is not the same field as the `data.kind` value.

## Tapping a notification

Tapping any operational alert opens the **app dashboard**. There is no review
detail screen and no review action: an operational alert describes the state of
the server, and the fix is made in the dashboard (or on the VPS, per the
runbook). A receiver must not navigate to a review screen when
`type=operational_alert` and no review ID is present.

## What a successful send does and does not mean

An accepted FCM response means the provider accepted the message. It does not
mean a device displayed it: a revoked token, a device offline for days, or the
user disabling notifications all produce an accepted send. Never treat provider
acceptance as delivery confirmation, and never show an operator "alert
delivered" based on it.

## Retry semantics the client can observe

- Transient failures retry with exponential backoff starting at 60 seconds,
  capped at 3600 seconds. A device can therefore receive the same alert many
  minutes after the incident.
- An invalid/revoked registration is removed, so a device that re-pairs starts
  receiving alerts again without operator action.
- Partial batch failure is tracked per recipient: a device that already
  accepted is not resent to.
- With no paired recipients, an alert stays **pending**. It is not lost, and it
  is not marked delivered; it goes out when a device pairs.

## Prerequisites and acceptance

This contract is not implementable on the client yet. The Android app in this
repository is a single activity showing a label; the two open issues below
must land first, and the acceptance steps below are executed as part of #22's
live verification:

- **#32** — device pairing/registration shell, which produces the push tokens
  that make delivery possible at all.
- **#36** — FCM receiver, which is where this contract is implemented.

Acceptance steps once both are in place:

1. **Foreground** — app open and on screen, a synthetic `disk.low` alert arrives
   and is displayed with its Turkish title and body, and the notification tag
   equals `alert_id`.
2. **Background** — app backgrounded (and separately, killed), the same alert
   arrives in the notification tray and tapping it opens the dashboard.
3. **Replacement** — force a redelivery of the same alert and confirm one
   notification, not two.
4. **No review assumption** — confirm the receiver does not attempt a review
   navigation for these messages.

Steps 1-4 need a real paired device and real FCM delivery. They are live
verification, not code verification, and #22 stays open until they are
demonstrated. See [`docs/rehberler/production-monitoring.md`](../rehberler/production-monitoring.md)
for the operator-side setup and the hosted HTTPS checks.
