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
        return self._acknowledge(lease, outcome)

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
