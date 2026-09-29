"""Durable operational-alert payloads: safe text, stable identity, retry timing.

Alerts are persisted before any send attempt and survive restarts, so every
field here is safe to store and to display: configured target labels and job
kind/identifier only, never filesystem paths, stored error text, or push
tokens. Notification ``data`` carries only the Android event type, the stable
alert ID used to replace duplicates, and the alert kind.

``target`` values are the configured labels from monitoring configuration, not
raw filesystem paths.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

#: Fixed Turkish notification text. Bodies interpolate only safe labels.
DISK_LOW_TITLE = "Disk alanı azalıyor"
DISK_LOW_BODY = "{target} hedefinde boş alan oranı düşük."
DISK_RECOVERED_TITLE = "Disk alanı normale döndü"
DISK_RECOVERED_BODY = "{target} hedefinde boş alan oranı normale döndü."
JOB_FAILED_TITLE = "İş başarısız oldu"
JOB_FAILED_BODY = "{kind} işi başarısız oldu. İş no: {job_id}"

ALERT_KIND_DISK_LOW = "disk.low"
ALERT_KIND_DISK_RECOVERED = "disk.recovered"
ALERT_KIND_JOB_FAILED = "job.failed"

#: Incident transitions that produce an event key suffix.
DISK_OPENED = "opened"
DISK_RECOVERED = "recovered"

#: Android switches on this ``data`` type; operational alerts carry no review ID.
ALERT_DATA_TYPE = "operational_alert"

#: Delivery states. Only ``pending`` is claimable; the others are terminal.
DELIVERY_PENDING = "pending"
DELIVERY_COMPLETE = "complete"
DELIVERY_SKIPPED = "skipped"
DELIVERY_STATUSES = (DELIVERY_PENDING, DELIVERY_COMPLETE, DELIVERY_SKIPPED)

#: Every alert kind the schema accepts, in the CHECK constraint sense.
ALERT_KINDS = (
    ALERT_KIND_DISK_LOW,
    ALERT_KIND_DISK_RECOVERED,
    ALERT_KIND_JOB_FAILED,
)


def _in_list(column: str, values: tuple[str, ...]) -> str:
    """PostgreSQL CHECK body; single-quoted and sorted for stable DDL."""
    rendered = ", ".join(f"'{value}'" for value in sorted(values))
    return f"{column} IN ({rendered})"


#: Enforced by the database, not only by the writers: a typo in either adapter
#: would otherwise persist a row nothing ever claims again.
DELIVERY_STATUS_CHECK = _in_list("status", DELIVERY_STATUSES)
DELIVERY_ATTEMPTS_CHECK = "attempts >= 0"
ALERT_KIND_CHECK = _in_list("kind", ALERT_KINDS)

DeliveryOutcome = Literal["accepted", "invalid", "retry"]

BASE_RETRY_DELAY_SECONDS = 60
MAX_RETRY_DELAY_SECONDS = 3600
#: ``60 * 2**6`` already exceeds the cap, so larger exponents never build
#: arbitrarily large integers for a delivery that retried many times.
_RETRY_CAP_EXPONENT = 6


@dataclass(frozen=True)
class DiskSample:
    """One capacity reading of a configured monitoring target."""

    target: str
    free_bytes: int
    total_bytes: int
    sampled_at: datetime

    @property
    def free_percent(self) -> float:
        if self.total_bytes <= 0:
            raise ValueError(f"disk sample for {self.target!r} has no measurable capacity")
        return self.free_bytes * 100.0 / self.total_bytes


@dataclass(frozen=True)
class OperationalAlert:
    """A persisted alert. ``alert_id`` is the Android duplicate-replacement key."""

    alert_id: str
    event_key: str
    kind: str
    title: str
    body: str
    data: dict[str, str]
    created_at: datetime


class _RedactedToken(str):
    """A token that renders as ``***`` but is still a usable ``str``.

    ``field(repr=False)`` alone hides the value from ``repr(lease)`` while
    leaving it in ``asdict()``, ``str()`` and any interpolated log line. This
    closes those paths without changing the lease's public type.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "***"

    __str__ = __repr__


@dataclass(frozen=True)
class DeliveryLease:
    """A single-recipient send claim.

    ``token`` is the current registration value for ``client_id`` at claim time.
    It exists only to reach the transport and to compare exact-token deletion;
    it never belongs in a log line or in notification data. It is excluded from
    ``repr`` and renders as ``***`` through ``str``/``asdict`` so that an
    accidental interpolation or serialization cannot leak it.
    """

    delivery_id: int
    claim_id: str
    alert: OperationalAlert
    client_id: int
    token: str = field(repr=False)
    attempt: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "token", _RedactedToken(self.token))


def disk_event_key(target: str, incident_id: str, transition: str) -> str:
    """One opening and one recovery key per incident, never one per sample."""
    return f"disk:{target}:{incident_id}:{transition}"


def job_failure_event_key(job_id: str, generation: int) -> str:
    """Durable identity of one failed execution of a job.

    The generation lets a retried job that fails again produce its own alert
    while repeated updates of an already failed job produce none.
    """
    return f"job:{job_id}:failure:{generation}"


def token_fingerprint(token: str) -> str:
    """Non-reversible handle for a delivery's token; never reversible to it."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def retry_delay_seconds(attempt: int) -> int:
    """Exponential backoff from 60 seconds, capped at 3600 seconds."""
    exponent = max(0, attempt - 1)
    if exponent >= _RETRY_CAP_EXPONENT:
        return MAX_RETRY_DELAY_SECONDS
    return min(BASE_RETRY_DELAY_SECONDS * 2**exponent, MAX_RETRY_DELAY_SECONDS)


def _alert(
    *, alert_id: str, event_key: str, kind: str, title: str, body: str,
    created_at: datetime, extra: dict[str, str] | None = None,
) -> OperationalAlert:
    return OperationalAlert(
        alert_id=alert_id,
        event_key=event_key,
        kind=kind,
        title=title,
        body=body,
        data={"type": ALERT_DATA_TYPE, "alert_id": alert_id, "kind": kind, **(extra or {})},
        created_at=created_at,
    )


def disk_low_alert(
    *, alert_id: str, event_key: str, target: str, created_at: datetime,
) -> OperationalAlert:
    return _alert(
        alert_id=alert_id,
        event_key=event_key,
        kind=ALERT_KIND_DISK_LOW,
        title=DISK_LOW_TITLE,
        body=DISK_LOW_BODY.format(target=target),
        created_at=created_at,
    )


def disk_recovered_alert(
    *, alert_id: str, event_key: str, target: str, created_at: datetime,
) -> OperationalAlert:
    return _alert(
        alert_id=alert_id,
        event_key=event_key,
        kind=ALERT_KIND_DISK_RECOVERED,
        title=DISK_RECOVERED_TITLE,
        body=DISK_RECOVERED_BODY.format(target=target),
        created_at=created_at,
    )


def job_failure_alert(
    *, alert_id: str, event_key: str, job_id: str, kind: str, created_at: datetime,
) -> OperationalAlert:
    """Safe failure alert: job kind and identifier, never the stored error text."""
    return _alert(
        alert_id=alert_id,
        event_key=event_key,
        kind=ALERT_KIND_JOB_FAILED,
        title=JOB_FAILED_TITLE,
        body=JOB_FAILED_BODY.format(kind=kind, job_id=job_id),
        created_at=created_at,
        extra={"job_id": job_id},
    )
