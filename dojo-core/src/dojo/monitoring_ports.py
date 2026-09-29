"""Storage boundary for durable operational monitoring state.

Both ``PostgresStore`` and ``InMemoryStore`` satisfy this protocol, so the
collector and delivery services in :mod:`dojo.monitoring` stay persistence
agnostic. Send operations belong to the transport, not to these methods: a
claim returns the lease, the caller performs the external call, and the
acknowledgement is a separate call.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from dojo.monitoring_models import DeliveryLease, DeliveryOutcome, DiskSample


@runtime_checkable
class MonitoringStore(Protocol):
    def record_disk_sample(
        self, sample: DiskSample, *, low_percent: float, recovery_percent: float,
    ) -> None:
        """Record one capacity reading for a target.

        Samples at or before the stored timestamp are ignored, so out-of-order
        readings cannot duplicate an incident or fake a recovery. Opening below
        ``low_percent`` and recovering at or above ``recovery_percent`` each
        emit exactly one alert per incident, atomically with the state change.
        """
        ...

    def prepare_alert_deliveries(self, now: datetime, *, limit: int = 100) -> int:
        """Snapshot the active paired device clients for unsnapshotted alerts.

        Returns the number of alerts that gained recipients. An alert with no
        active recipient stays pending: absence of recipients is not delivery.
        """
        ...

    def claim_alert_delivery(
        self, now: datetime, *, lease_seconds: int = 60,
    ) -> DeliveryLease | None:
        """Claim one due delivery for one recipient, with a fenced lease.

        One recipient per claim keeps the number of external send calls
        bounded and lets the caller acknowledge each attempt separately.
        """
        ...

    def finish_alert_delivery(
        self, lease: DeliveryLease, *, outcome: DeliveryOutcome, now: datetime,
    ) -> bool:
        """Acknowledge the current unexpired claim for ``lease``.

        ``accepted`` completes the recipient permanently; ``invalid`` deletes
        exactly the registration token that was used and retries; ``retry``
        schedules the next attempt with capped exponential backoff. Returns
        ``False`` for a stale, expired or superseded claim.
        """
        ...
