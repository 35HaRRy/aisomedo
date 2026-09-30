"""Durable delivery of persisted operational alerts.

Alerts are persisted before any send attempt (see
:mod:`dojo.monitoring_models`), so this service only moves durable state
forward: snapshot recipients, claim one recipient at a time, send through the
notifier seam, acknowledge the outcome. The external send and the database
commit cannot be atomic, which is why every step is idempotent and the worst
case is a duplicate notification that the Android tag replaces.

Delivery is at least once, and an accepted send means the provider accepted
it, not that any device displayed it.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime

from dojo.model import Notification
from dojo.monitoring_models import DeliveryLease, DeliveryOutcome
from dojo.monitoring_ports import MonitoringStore
from dojo.ports import Clock, Notifier

logger = logging.getLogger(__name__)

#: Monotonic budget for one invocation, checked between recipients. A single
#: send can still add its own provider timeout on top of this, so the loop is
#: bounded rather than hard-bounded.
DELIVERY_BUDGET_SECONDS = 20.0

#: Minimum seconds between two ``monitoring.delivery_rejected`` records for the
#: same alert. A rejected send is retried on a backoff that caps at one hour,
#: so the durable state is already bounded; this bound is on the log, so a
#: recipient set of any size cannot turn a permanently broken provider into a
#: per-turn flood that rotates away the records an operator needs.
DELIVERY_REJECTION_LOG_INTERVAL_SECONDS = 900.0


def _outcome(result: object, token: str) -> DeliveryOutcome:
    """Categorize one recipient from the notifier's batch result.

    Anything the notifier did not explicitly report — including an unmapped
    token — is a retry, because a retry is safe and a false success is not.
    """
    if token in (getattr(result, "delivered", None) or []):
        return "accepted"
    if token in (getattr(result, "invalid_tokens", None) or []):
        return "invalid"
    return "retry"


def _rejection_reason(result: object, token: str) -> str:
    """A categorized, non-secret reason a recipient was not accepted.

    Only which bucket the notifier filed the token under is reported. The
    provider's own message, the token itself and the credential path are never
    read, so the record cannot carry a secret. The reason rides in ``status``
    rather than in the log message, because the JSON formatter never serializes
    message text or arguments: a reason that only lived in the message would be
    invisible in production.
    """
    if token in (getattr(result, "invalid_tokens", None) or []):
        return "invalid_registration"
    if token in (getattr(result, "transient_failures", None) or []):
        return "provider_error"
    return "unreported"


class DojoMonitoring:
    """Sends persisted operational alerts to the recipients snapshotted for them.

    Notifier and transport failures are isolated per recipient: one device can
    never stop the loop, and a failed attempt stays retryable from durable
    state. A failure to snapshot propagates, because without a snapshot there
    is nothing to deliver, and the worker collector is the layer that isolates
    monitoring from publication.
    """

    def __init__(
        self,
        store: MonitoringStore,
        notifier: Notifier,
        clock: Clock,
        *,
        budget_seconds: float = DELIVERY_BUDGET_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store = store
        self._notifier = notifier
        self._clock = clock
        self._budget_seconds = budget_seconds
        self._monotonic = monotonic
        #: alert_id -> monotonic time its rejection was last logged. A
        #: permanently failing alert must stay visible without becoming a
        #: per-turn flood, and one entry per alert is bounded by the alert
        #: table rather than by the retry cadence.
        self._rejection_log: dict[str, float] = {}

    def deliver_pending(self, *, limit: int = 100) -> int:
        """Deliver at most ``limit`` due recipients; return how many were accepted.

        Recipients are snapshotted first, so an alert with no active device
        stays pending instead of counting as delivered. Each recipient is then
        claimed, sent and acknowledged on its own, which keeps a partial batch
        failure from resending to recipients that already accepted.
        """
        now = self._clock.now()
        self._store.prepare_alert_deliveries(now, limit=limit)
        deadline = self._monotonic() + self._budget_seconds
        accepted = 0
        for _recipient in range(limit):
            if self._monotonic() >= deadline:
                logger.info(
                    "monitoring delivery budget reached",
                    extra={"event": "monitoring.delivery_budget_reached"},
                )
                break
            lease = self._claim(now)
            if lease is None:
                break
            accepted += self._deliver(lease)
        return accepted

    def _claim(self, now: datetime) -> DeliveryLease | None:
        """One due delivery, or ``None`` when nothing is claimable."""
        try:
            return self._store.claim_alert_delivery(now)
        except Exception:  # noqa: BLE001 - the next invocation retries from durable state
            logger.exception(
                "alert delivery claim failed", extra={"event": "monitoring.claim_failed"}
            )
            return None

    def _deliver(self, lease: DeliveryLease) -> int:
        alert = lease.alert
        notification = Notification(
            title=alert.title, body=alert.body, data=dict(alert.data)
        )
        try:
            result = self._notifier.send(notification, [lease.token])
        except Exception:  # noqa: BLE001 - one recipient must not stop the loop
            logger.exception(
                "operational alert send failed",
                extra={
                    "event": "monitoring.delivery_send_failed",
                    "alert_id": alert.alert_id,
                    "status": "retry",
                },
            )
            outcome: DeliveryOutcome = "retry"
        else:
            outcome = _outcome(result, lease.token)
            if outcome != "accepted":
                self._log_rejection(lease, outcome, result)
        return self._acknowledge(lease, outcome)

    def _log_rejection(self, lease: DeliveryLease, outcome: DeliveryOutcome,
                       result: object) -> None:
        """One record per alert per interval for a send the provider rejected.

        A provider error arrives as a *result*, not an exception, so nothing
        else on this path produces a record: there is no ``exc_info`` to log
        and ``accepted`` stays 0, so the worker logs no delivery event either.
        Without this line a permanently failing FCM project retries an alert
        hourly and the log is indistinguishable from a quiet day, which is the
        one failure mode monitoring exists to make visible.
        """
        alert_id = lease.alert.alert_id
        now = self._monotonic()
        last = self._rejection_log.get(alert_id)
        if last is not None and now - last < DELIVERY_REJECTION_LOG_INTERVAL_SECONDS:
            return
        self._rejection_log[alert_id] = now
        reason = _rejection_reason(result, lease.token)
        # ``error_type`` is reserved for an exception class name, so the
        # categorized reason rides in ``status`` beside the durable outcome.
        # Both halves are needed: "retry" alone does not distinguish a provider
        # outage from a rejected registration.
        logger.warning(
            "operational alert was not accepted by the provider; it stays "
            "pending and will be retried with backoff",
            extra={
                "event": "monitoring.delivery_rejected",
                "alert_id": alert_id,
                "status": f"{outcome}:{reason}",
            },
        )

    def _acknowledge(self, lease: DeliveryLease, outcome: DeliveryOutcome) -> int:
        try:
            acknowledged = self._store.finish_alert_delivery(
                lease, outcome=outcome, now=self._clock.now()
            )
        except Exception:  # noqa: BLE001 - the lease expires and the send is retried
            logger.exception(
                "operational alert acknowledgement failed",
                extra={
                    "event": "monitoring.delivery_ack_failed",
                    "alert_id": lease.alert.alert_id,
                    "status": outcome,
                },
            )
            return 0
        if not acknowledged:
            # A stale, expired or superseded claim: another worker owns this
            # delivery now, so this attempt is neither durable nor counted.
            logger.warning(
                "operational alert acknowledgement refused",
                extra={
                    "event": "monitoring.delivery_ack_refused",
                    "alert_id": lease.alert.alert_id,
                    "status": outcome,
                },
            )
            return 0
        return 1 if outcome == "accepted" else 0
