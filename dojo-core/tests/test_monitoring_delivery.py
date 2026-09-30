"""Delivery-loop tests for durable operational alerts.

The loop runs against the real Task 3 stores with a deterministic clock and an
injected stub notifier, so every case here is a property of the service: what
it claims, what it acknowledges, and what it never counts as delivered.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import timedelta

import pytest
from dojo import DojoMonitoring
from dojo.adapters.memory import InMemoryStore
from dojo.adapters.stubs import StubNotifier
from dojo.model import Client, Job
from dojo.monitoring import DELIVERY_REJECTION_LOG_INTERVAL_SECONDS
from dojo.monitoring_models import (
    ALERT_KIND_JOB_FAILED,
    DELIVERY_COMPLETE,
    DELIVERY_PENDING,
    DELIVERY_SKIPPED,
)
from dojo.testing import FIXED_AT, FakeClock
from firebase_admin import messaging
from sqlalchemy import text

SECOND = timedelta(seconds=1)
LEASE_SECONDS = 60
RETRY_DELAYS = (60, 120, 240, 480, 960, 1920, 3600, 3600)


def queued_job(job_id: str = "j-1") -> Job:
    return Job(id=0, job_id=job_id, upload_id=None, kind="media.process",
               status="queued", payload={"upload_id": 7}, created_at=FIXED_AT)


def fail_job(store, job_id: str = "j-1", at=FIXED_AT):
    """Queue then fail one job: the durable transition that persists an alert."""
    store.create(queued_job(job_id))
    job = store.get(job_id)
    assert job is not None
    return store.update(replace(job, status="failed", finished_at=at, error_reason="boom"))


def register_device(store, name: str, token: str, kind: str = "device") -> Client:
    client = store.create_client(
        Client(id=0, name=name, kind=kind, created_at=FIXED_AT, created_by="cli"),
        credential_hash=f"cred-{name}",
    )
    store.register_token(client.id, token, FIXED_AT)
    return client


def tokens_of(store) -> list[str]:
    return [registration.token for registration in store.list_active_device_tokens()]


def status_of(store, client_id: int) -> str:
    if isinstance(store, InMemoryStore):
        return next(d.status for d in store._deliveries if d.client_id == client_id)
    with store._engine.connect() as conn:  # noqa: SLF001
        return conn.execute(
            text("SELECT status FROM operational_deliveries WHERE client_id = :c"),
            {"c": client_id},
        ).scalar_one()


def attempts_of(store, client_id: int) -> int:
    if isinstance(store, InMemoryStore):
        return next(d.attempts for d in store._deliveries if d.client_id == client_id)
    with store._engine.connect() as conn:  # noqa: SLF001
        return conn.execute(
            text("SELECT attempts FROM operational_deliveries WHERE client_id = :c"),
            {"c": client_id},
        ).scalar_one()


def contract(pg_store, memory: bool):
    return InMemoryStore() if memory else pg_store


class FakeMessaging:
    """Real SDK message types behind a recording, offline sender."""

    def __init__(self) -> None:
        self.sent: list[tuple[messaging.MulticastMessage, object]] = []

    def __getattr__(self, name: str):
        return getattr(messaging, name)

    def send_each_for_multicast(self, message, dry_run=False, app=None):
        self.sent.append((message, app))
        return messaging.BatchResponse(
            [messaging.SendResponse({"name": "n"}, None) for _ in message.tokens]
        )


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(FIXED_AT)


@pytest.fixture
def notifier() -> StubNotifier:
    """Injected explicitly: production monitoring never reaches a stub."""
    return StubNotifier()


# --- the ordinary outcomes --------------------------------------------------


@pytest.mark.parametrize("memory", [False, True])
def test_accepted_alert_sends_safe_text_and_completes_the_recipient(
    pg_store, notifier, clock, memory,
):
    store = contract(pg_store, memory)
    fail_job(store)
    device = register_device(store, "phone", "token-1")
    monitoring = DojoMonitoring(store, notifier, clock)

    assert monitoring.deliver_pending() == 1

    sent, tokens = notifier.sent[0]
    assert tokens == ["token-1"]
    assert sent.title == "İş başarısız oldu"
    assert sent.body == "media.process işi başarısız oldu. İş no: j-1"
    assert "boom" not in sent.body
    assert sent.data["type"] == "operational_alert"
    assert sent.data["kind"] == ALERT_KIND_JOB_FAILED
    assert status_of(store, device.id) == DELIVERY_COMPLETE
    # Nothing is due any more: an accepted recipient is never re-sent.
    assert monitoring.deliver_pending() == 0
    assert len(notifier.sent) == 1


@pytest.mark.parametrize("memory", [False, True])
def test_no_device_keeps_the_alert_pending_instead_of_counting_it_delivered(
    pg_store, notifier, clock, memory,
):
    store = contract(pg_store, memory)
    fail_job(store)
    monitoring = DojoMonitoring(store, notifier, clock)

    assert monitoring.deliver_pending() == 0
    assert notifier.sent == []
    # A device paired later is still a recipient: nothing was marked complete.
    register_device(store, "phone", "token-1")

    assert monitoring.deliver_pending() == 1
    assert len(notifier.sent) == 1


@pytest.mark.parametrize("memory", [False, True])
def test_partial_failure_retries_only_the_unaccepted_recipient(
    pg_store, notifier, clock, memory,
):
    store = contract(pg_store, memory)
    fail_job(store)
    first = register_device(store, "phone-a", "token-a")
    second = register_device(store, "phone-b", "token-b")
    notifier.transient_tokens.add("token-b")
    monitoring = DojoMonitoring(store, notifier, clock)

    assert monitoring.deliver_pending() == 1
    assert status_of(store, first.id) == DELIVERY_COMPLETE
    assert status_of(store, second.id) == DELIVERY_PENDING

    notifier.transient_tokens.clear()
    clock._now = FIXED_AT + timedelta(seconds=60)

    assert monitoring.deliver_pending() == 1
    # The accepted recipient is never re-sent; only the retried one is.
    assert [tokens for _sent, tokens in notifier.sent] == [
        ["token-a"], ["token-b"], ["token-b"],
    ]
    assert status_of(store, second.id) == DELIVERY_COMPLETE


@pytest.mark.parametrize("memory", [False, True])
def test_revoked_device_is_skipped_without_sending(pg_store, notifier, clock, memory):
    store = contract(pg_store, memory)
    fail_job(store)
    device = register_device(store, "phone", "token-1")
    # The recipient is snapshotted while it is still active, then revoked:
    # revocation is rechecked at claim time, not only at snapshot time.
    assert store.prepare_alert_deliveries(FIXED_AT) == 1
    store.mark_client_revoked(device.id, FIXED_AT)
    monitoring = DojoMonitoring(store, notifier, clock)

    assert monitoring.deliver_pending() == 0
    assert notifier.sent == []
    assert status_of(store, device.id) == DELIVERY_SKIPPED


@pytest.mark.parametrize("memory", [False, True])
def test_proven_invalid_registration_is_removed_and_never_counted_delivered(
    pg_store, notifier, clock, memory,
):
    store = contract(pg_store, memory)
    fail_job(store)
    device = register_device(store, "phone", "token-stale")
    notifier.invalid_tokens.add("token-stale")
    monitoring = DojoMonitoring(store, notifier, clock)

    assert monitoring.deliver_pending() == 0
    assert tokens_of(store) == []
    assert status_of(store, device.id) == DELIVERY_PENDING

    # The retry waits for its backoff, then finds the registration gone and
    # skips the recipient instead of counting it as a delivery.
    assert monitoring.deliver_pending() == 0
    assert len(notifier.sent) == 1
    assert notifier.sent[0][1] == ["token-stale"]

    clock._now = FIXED_AT + timedelta(seconds=60)
    assert monitoring.deliver_pending() == 0
    assert status_of(store, device.id) == DELIVERY_SKIPPED
    assert len(notifier.sent) == 1


@pytest.mark.parametrize("memory", [False, True])
def test_token_rotated_after_the_claim_survives_and_still_receives_the_alert(
    pg_store, notifier, clock, memory,
):
    store = contract(pg_store, memory)
    fail_job(store)
    device = register_device(store, "phone", "token-old")
    assert store.prepare_alert_deliveries(FIXED_AT) == 1
    claimed = store.claim_alert_delivery(FIXED_AT)
    assert claimed is not None
    # The device re-registers between claim and acknowledgement: deleting the
    # claimed token must not remove the newer one.
    store.register_token(device.id, "token-new", FIXED_AT)
    assert store.finish_alert_delivery(claimed, outcome="invalid", now=FIXED_AT) is True
    assert tokens_of(store) == ["token-new"]

    clock._now = FIXED_AT + timedelta(seconds=60)
    monitoring = DojoMonitoring(store, notifier, clock)

    assert monitoring.deliver_pending() == 1
    assert notifier.sent[-1][1] == ["token-new"]
    assert status_of(store, device.id) == DELIVERY_COMPLETE


# --- failure handling -------------------------------------------------------


@pytest.mark.parametrize("memory", [False, True])
def test_transport_exception_isolates_one_recipient_and_schedules_the_retry(
    pg_store, notifier, clock, memory,
):
    store = contract(pg_store, memory)
    fail_job(store)
    first = register_device(store, "phone-a", "token-a")
    second = register_device(store, "phone-b", "token-b")

    original_send = notifier.send

    def flaky(notification, tokens):
        if tokens == ["token-a"]:
            raise TimeoutError("fcm unreachable")
        return original_send(notification, tokens)

    notifier.send = flaky  # type: ignore[method-assign]
    monitoring = DojoMonitoring(store, notifier, clock)

    assert monitoring.deliver_pending() == 1
    assert status_of(store, second.id) == DELIVERY_COMPLETE
    assert status_of(store, first.id) == DELIVERY_PENDING
    assert attempts_of(store, first.id) == 1


@pytest.mark.parametrize("memory", [False, True])
def test_a_provider_error_retry_is_logged_rather_than_silent(
    pg_store, notifier, clock, memory, caplog: pytest.LogCaptureFixture,
):
    """A non-exception provider failure used to produce no record at all.

    There is no exception to log and ``accepted`` stays 0, so the worker logs no
    delivery event either: a permanently failing FCM project retried an alert
    hourly and the log looked exactly like a quiet day.
    """
    store = contract(pg_store, memory)
    fail_job(store)
    device = register_device(store, "phone", "token-1")
    notifier.transient_tokens.add("token-1")
    monitoring = DojoMonitoring(store, notifier, clock)

    with caplog.at_level(logging.WARNING, logger="dojo.monitoring"):
        assert monitoring.deliver_pending() == 0

    rejected = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "monitoring.delivery_rejected"
    ]
    assert len(rejected) == 1
    assert rejected[0].alert_id
    assert rejected[0].status == "retry:provider_error"
    # Categorized only: the token and the provider's own message never reach it.
    assert "token-1" not in caplog.text
    assert status_of(store, device.id) == DELIVERY_PENDING


@pytest.mark.parametrize("memory", [False, True])
def test_a_rejected_registration_is_logged_with_its_own_reason(
    pg_store, notifier, clock, memory, caplog: pytest.LogCaptureFixture,
):
    store = contract(pg_store, memory)
    fail_job(store)
    register_device(store, "phone", "token-stale")
    notifier.invalid_tokens.add("token-stale")
    monitoring = DojoMonitoring(store, notifier, clock)

    with caplog.at_level(logging.WARNING, logger="dojo.monitoring"):
        assert monitoring.deliver_pending() == 0

    rejected = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "monitoring.delivery_rejected"
    ]
    assert [record.status for record in rejected] == ["invalid:invalid_registration"]


@pytest.mark.parametrize("memory", [False, True])
def test_a_repeatedly_rejected_alert_is_rate_limited_per_alert(
    pg_store, notifier, clock, memory, caplog: pytest.LogCaptureFixture,
):
    """The record must not become the flood it replaced.

    The backoff already caps attempts at one per hour; this bounds the log so a
    large recipient set cannot turn a broken provider into a per-turn flood that
    rotates away the records the operator needs.
    """
    store = contract(pg_store, memory)
    fail_job(store)
    for index in range(3):
        register_device(store, f"phone-{index}", f"token-{index}")
        notifier.transient_tokens.add(f"token-{index}")
    monotonic_now = [0.0]
    monitoring = DojoMonitoring(
        store, notifier, clock, monotonic=lambda: monotonic_now[0]
    )

    def turn() -> None:
        """One delivery pass, far enough past each backoff to be claimable again."""
        assert monitoring.deliver_pending() == 0
        clock._now += timedelta(seconds=500)  # noqa: SLF001 - the double is the seam
        monotonic_now[0] += 60.0

    def rejections() -> list[pytest.LogRecord]:
        return [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "monitoring.delivery_rejected"
        ]

    with caplog.at_level(logging.WARNING, logger="dojo.monitoring"):
        # Three recipients in the first turn — three rejections of one alert —
        # then three more turns that all fall inside the 900s window.
        for _ in range(4):
            turn()

    assert len(rejections()) == 1

    # Rate-limited, not muted: past the interval the same alert is named again.
    monotonic_now[0] += DELIVERY_REJECTION_LOG_INTERVAL_SECONDS
    with caplog.at_level(logging.WARNING, logger="dojo.monitoring"):
        turn()
    assert len(rejections()) == 2


@pytest.mark.parametrize("memory", [False, True])
def test_an_accepted_send_logs_no_rejection(pg_store, notifier, clock, memory,
                                            caplog: pytest.LogCaptureFixture):
    store = contract(pg_store, memory)
    fail_job(store)
    register_device(store, "phone", "token-1")
    monitoring = DojoMonitoring(store, notifier, clock)

    with caplog.at_level(logging.WARNING, logger="dojo.monitoring"):
        assert monitoring.deliver_pending() == 1

    assert [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "monitoring.delivery_rejected"
    ] == []


@pytest.mark.parametrize("memory", [False, True])
def test_retry_boundary_after_a_first_failure(pg_store, memory):
    store = contract(pg_store, memory)
    fail_job(store)
    register_device(store, "phone", "token-1")
    assert store.prepare_alert_deliveries(FIXED_AT) == 1

    original_lease = store.claim_alert_delivery(FIXED_AT)
    assert original_lease is not None
    assert store.finish_alert_delivery(original_lease, outcome="retry", now=FIXED_AT) is True

    assert store.claim_alert_delivery(FIXED_AT + timedelta(seconds=59)) is None
    retry = store.claim_alert_delivery(FIXED_AT + timedelta(seconds=60))
    assert retry is not None
    assert retry.attempt == 2
    assert retry.alert.alert_id == original_lease.alert.alert_id


@pytest.mark.parametrize("memory", [False, True])
def test_backoff_doubles_and_caps(pg_store, notifier, clock, memory):
    store = contract(pg_store, memory)
    fail_job(store)
    device = register_device(store, "phone", "token-1")
    notifier.fail_next = RuntimeError("fcm unreachable")
    monitoring = DojoMonitoring(store, notifier, clock)

    moment = FIXED_AT
    for expected, attempt in zip(RETRY_DELAYS, range(1, len(RETRY_DELAYS) + 1), strict=True):
        notifier.fail_next = RuntimeError("fcm unreachable")
        clock._now = moment
        assert monitoring.deliver_pending() == 0
        assert attempts_of(store, device.id) == attempt
        assert store.claim_alert_delivery(moment + timedelta(seconds=expected - 1)) is None
        moment = moment + timedelta(seconds=expected)

    notifier.fail_next = RuntimeError("fcm unreachable")
    clock._now = moment
    assert monitoring.deliver_pending() == 0
    assert attempts_of(store, device.id) == len(RETRY_DELAYS) + 1


@pytest.mark.parametrize("memory", [False, True])
def test_expired_lease_is_reclaimed_and_its_stale_acknowledgement_refused(
    pg_store, memory,
):
    store = contract(pg_store, memory)
    fail_job(store)
    register_device(store, "phone", "token-1")
    assert store.prepare_alert_deliveries(FIXED_AT) == 1

    abandoned = store.claim_alert_delivery(FIXED_AT)
    assert abandoned is not None
    assert store.claim_alert_delivery(FIXED_AT + timedelta(seconds=LEASE_SECONDS - 1)) is None

    reclaimed = store.claim_alert_delivery(FIXED_AT + timedelta(seconds=LEASE_SECONDS))
    assert reclaimed is not None
    assert reclaimed.attempt == abandoned.attempt + 1

    later = FIXED_AT + timedelta(seconds=LEASE_SECONDS + 1)
    assert store.finish_alert_delivery(abandoned, outcome="accepted", now=later) is False
    assert store.finish_alert_delivery(reclaimed, outcome="accepted", now=later) is True


def _ack_fails_once(store) -> object:
    """Proxy store whose first delivery acknowledgement fails."""
    acknowledgements = {"fail": True}

    class FlakyAck:
        def __getattr__(self, name):
            return getattr(store, name)

        def finish_alert_delivery(self, lease, *, outcome, now):
            if acknowledgements["fail"]:
                acknowledgements["fail"] = False
                raise RuntimeError("database unavailable")
            return store.finish_alert_delivery(lease, outcome=outcome, now=now)

    return FlakyAck()


@pytest.mark.parametrize("memory", [False, True])
def test_lost_acknowledgement_redelivers_the_same_alert_and_tag(
    pg_store, notifier, clock, memory,
):
    from dojo.adapters.fcm import FcmNotifier

    store = contract(pg_store, memory)
    fail_job(store)
    register_device(store, "phone", "token-1")
    flaky = _ack_fails_once(store)
    monitoring = DojoMonitoring(flaky, notifier, clock)  # type: ignore[arg-type]

    # The provider accepted the send, but the acknowledgement was lost, so the
    # service must not report a durable success.
    assert monitoring.deliver_pending() == 0
    clock._now = FIXED_AT + timedelta(seconds=LEASE_SECONDS)

    assert monitoring.deliver_pending() == 1
    first, second = notifier.sent[0][0], notifier.sent[1][0]
    assert first.data["alert_id"] == second.data["alert_id"]

    tags = []
    sender = FakeMessaging()
    fcm = FcmNotifier(messaging=sender, app=object())
    for notification in (first, second):
        fcm.send(notification, ["token-1"])
        tags.append(sender.sent[-1][0].android.notification.tag)
    assert tags[0] == tags[1]
    assert tags[0] == first.data["alert_id"]
    assert isinstance(sender.sent[0][0], messaging.MulticastMessage)


# --- bounds -----------------------------------------------------------------


@pytest.mark.parametrize("memory", [False, True])
def test_limit_bounds_one_invocation(pg_store, notifier, clock, memory):
    store = contract(pg_store, memory)
    fail_job(store)
    for index in range(3):
        register_device(store, f"phone-{index}", f"token-{index}")
    monitoring = DojoMonitoring(store, notifier, clock)

    assert monitoring.deliver_pending(limit=2) == 2
    assert len(notifier.sent) == 2
    assert monitoring.deliver_pending() == 1
    assert len(notifier.sent) == 3


@pytest.mark.parametrize("memory", [False, True])
def test_invocation_stops_at_its_monotonic_budget(pg_store, notifier, clock, memory):
    store = contract(pg_store, memory)
    fail_job(store)
    for index in range(3):
        register_device(store, f"phone-{index}", f"token-{index}")
    readings = iter([0.0, 0.0, 21.0] + [21.0] * 8)
    monitoring = DojoMonitoring(
        store, notifier, clock, monotonic=lambda: next(readings, 21.0)
    )

    assert monitoring.deliver_pending() == 1
    assert len(notifier.sent) == 1
