"""Contract tests for durable operational monitoring state.

Every test runs against both stores where the semantics can be expressed
without PostgreSQL; restart, rollback and concurrency behaviour needs real
connections and is PostgreSQL only.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier

import pytest
from dojo.adapters.db import PostgresStore
from dojo.adapters.memory import InMemoryStore
from dojo.model import Client, Job
from dojo.monitoring_models import (
    DiskSample,
    OperationalAlert,
    retry_delay_seconds,
    token_fingerprint,
)
from dojo.testing import FIXED_AT
from sqlalchemy import inspect, text

TARGET = "media"
LOW = 15.0
RECOVERY = 20.0
SECOND = timedelta(seconds=1)


@pytest.fixture
def other(pg_store):
    """A second store/engine: real concurrent database connections."""
    store = PostgresStore(pg_store._engine.url.render_as_string(hide_password=False))
    yield store
    store.dispose()


def queued_job(job_id="j-1"):
    return Job(id=0, job_id=job_id, upload_id=None, kind="media.process", status="queued",
               payload={"upload_id": 7}, created_at=FIXED_AT)


def stored_job(store, job_id="j-1"):
    job = store.get(job_id)
    assert job is not None
    return job


def fail_job(store, job_id="j-1", at=FIXED_AT):
    """The durable failure transition: ``error_reason`` is stored, never alerted."""
    return store.update(
        replace(stored_job(store, job_id), status="failed", finished_at=at, error_reason="boom")
    )


def failed_alert(store, job_id="j-1"):
    """One persisted failure alert, ready for recipient snapshotting."""
    before = len(recorded_alerts(store))
    store.create(queued_job(job_id))
    fail_job(store, job_id)
    assert len(recorded_alerts(store)) == before + 1


def register_device(store, name, token, kind="device"):
    client = store.create_client(
        Client(id=0, name=name, kind=kind, created_at=FIXED_AT, created_by="cli"),
        credential_hash=f"cred-{name}",
    )
    store.register_token(client.id, token, FIXED_AT)
    return client


def persisted_alerts(store):
    """Creation-ordered alerts read straight from the test database."""
    with store._engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT alert_id, event_key, kind, title, body, data, created_at"
            "  FROM operational_alerts ORDER BY created_at, alert_id"
        )).all()
    return [
        OperationalAlert(alert_id=r[0], event_key=r[1], kind=r[2], title=r[3], body=r[4],
                         data=r[5], created_at=r[6])
        for r in rows
    ]


def recorded_alerts(store):
    return store.recorded_alerts if isinstance(store, InMemoryStore) else persisted_alerts(store)


def kinds(store):
    return [alert.kind for alert in recorded_alerts(store)]


def delivery_rows(store):
    with store._engine.connect() as conn:
        return conn.execute(text(
            "SELECT id, client_id, status, attempts, due_at, token_fingerprint,"
            "       claim_id, lease_expires_at FROM operational_deliveries ORDER BY id"
        )).all()


def sample(percent, at=FIXED_AT, target=TARGET):
    return DiskSample(target=target, free_bytes=percent * 10, total_bytes=1000, sampled_at=at)


def record(store, percent, at=FIXED_AT, target=TARGET):
    store.record_disk_sample(
        sample(percent, at, target), low_percent=LOW, recovery_percent=RECOVERY
    )


def drain(store, now=FIXED_AT):
    """Claim and accept every currently deliverable recipient."""
    leases = []
    while (lease := store.claim_alert_delivery(now)) is not None:
        assert store.finish_alert_delivery(lease, outcome="accepted", now=now) is True
        leases.append(lease)
    return leases


def contract(pg_store, memory):
    return InMemoryStore() if memory else pg_store


# --- job failure events -----------------------------------------------------


@pytest.mark.parametrize("memory", [False, True])
def test_first_failure_emits_one_alert_and_repeats_do_not(pg_store, memory):
    store = contract(pg_store, memory)
    store.create(queued_job())
    failed = fail_job(store)
    fail_job(store, at=FIXED_AT + SECOND)
    assert kinds(store) == ["job.failed"]
    alert = recorded_alerts(store)[0]
    assert alert.event_key == "job:j-1:failure:1"
    assert alert.data == {
        "type": "operational_alert", "alert_id": alert.alert_id,
        "kind": "job.failed", "job_id": "j-1",
    }
    assert alert.body == "media.process işi başarısız oldu. İş no: j-1"
    assert alert.title == "İş başarısız oldu"
    assert "boom" not in f"{alert.body}{alert.data}"
    assert stored_job(store).error_reason == failed.error_reason


@pytest.mark.parametrize("memory", [False, True])
def test_requeued_job_failure_gets_its_own_alert(pg_store, memory):
    store = contract(pg_store, memory)
    store.create(queued_job())
    fail_job(store)
    for status in ("queued", "processing"):
        store.update(replace(stored_job(store), status=status, finished_at=None))
    fail_job(store, at=FIXED_AT + SECOND)
    alerts = recorded_alerts(store)
    assert [alert.kind for alert in alerts] == ["job.failed", "job.failed"]
    assert [alert.event_key for alert in alerts] == ["job:j-1:failure:1", "job:j-1:failure:2"]
    assert len({alert.alert_id for alert in alerts}) == 2


def test_failure_alert_survives_restart_and_claims_the_latest_token(pg_store, other):
    pg_store.create(queued_job())
    fail_job(pg_store)
    device = register_device(pg_store, "phone", "token-1")

    assert other.prepare_alert_deliveries(FIXED_AT) == 1
    assert other.prepare_alert_deliveries(FIXED_AT) == 0
    leases = drain(other)
    assert [lease.client_id for lease in leases] == [device.id]
    assert leases[0].token == "token-1"
    assert leases[0].alert.kind == "job.failed"
    assert leases[0].alert.event_key == "job:j-1:failure:1"


def test_failed_transition_rollback_persists_neither_job_nor_alert(pg_store):
    pg_store.create(queued_job())
    with pytest.raises(RuntimeError, match="later step failed"):
        with pg_store.emission_transaction():
            fail_job(pg_store)
            raise RuntimeError("later step failed")
    assert stored_job(pg_store).status == "queued"
    assert persisted_alerts(pg_store) == []


def test_concurrent_failure_transitions_emit_one_alert(pg_store, other):
    pg_store.create(queued_job())
    gate = Barrier(2)

    def fail(store):
        gate.wait(timeout=10)
        with store.emission_transaction():
            fail_job(store)

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(fail, store) for store in (pg_store, other)]
        for future in futures:
            future.result(timeout=20)
    assert kinds(pg_store) == ["job.failed"]
    with pg_store._engine.connect() as conn:
        assert conn.scalar(text("SELECT failure_generation FROM jobs")) == 1


# --- disk incidents ---------------------------------------------------------


@pytest.mark.parametrize("memory", [False, True])
def test_disk_boundary_sequence_opens_once_and_recovers(pg_store, memory):
    store = contract(pg_store, memory)
    for percent, offset in [(15, 0), (14, 1), (19, 2), (20, 3)]:
        record(store, percent, FIXED_AT + offset * SECOND)
    alerts = recorded_alerts(store)
    assert [alert.kind for alert in alerts] == ["disk.low", "disk.recovered"]
    assert len({alert.event_key for alert in alerts}) == 2
    opened, recovered = (alert.event_key.split(":") for alert in alerts)
    assert opened[1] == TARGET and opened[3] == "opened"
    assert opened[2] == recovered[2]  # the same incident
    assert recovered[3] == "recovered"
    assert alerts[0].data == {
        "type": "operational_alert", "alert_id": alerts[0].alert_id, "kind": "disk.low",
    }
    assert TARGET in alerts[0].body and TARGET in alerts[1].body
    assert alerts[0].title == "Disk alanı azalıyor"
    assert alerts[1].title == "Disk alanı normale döndü"


@pytest.mark.parametrize("memory", [False, True])
def test_stale_and_equal_samples_are_ignored(pg_store, memory):
    store = contract(pg_store, memory)
    record(store, 14, FIXED_AT)
    record(store, 5, FIXED_AT - SECOND)  # older low sample: ignored
    record(store, 5, FIXED_AT)  # equal sample: ignored
    assert kinds(store) == ["disk.low"]
    record(store, 21, FIXED_AT + SECOND)
    record(store, 5, FIXED_AT)  # old low sample after recovery: ignored
    assert kinds(store) == ["disk.low", "disk.recovered"]
    record(store, 5, FIXED_AT + 2 * SECOND)  # a new low sample re-opens an incident
    assert kinds(store) == ["disk.low", "disk.recovered", "disk.low"]
    alerts = recorded_alerts(store)
    assert alerts[0].event_key.split(":")[2] != alerts[2].event_key.split(":")[2]


def test_disk_incident_survives_store_restart(pg_store, other):
    record(pg_store, 14, FIXED_AT)
    record(other, 20, FIXED_AT + SECOND)
    alerts = persisted_alerts(pg_store)
    assert [alert.kind for alert in alerts] == ["disk.low", "disk.recovered"]
    assert alerts[0].event_key.split(":")[2] == alerts[1].event_key.split(":")[2]
    record(other, 19, FIXED_AT + 2 * SECOND)  # hysteresis: still recovered
    assert kinds(pg_store) == ["disk.low", "disk.recovered"]


def test_concurrent_samples_open_one_incident(pg_store, other):
    gate = Barrier(2)

    def sample_both(store):
        gate.wait(timeout=10)
        record(store, 14, FIXED_AT)

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(sample_both, store) for store in (pg_store, other)]
        for future in futures:
            future.result(timeout=20)
    assert kinds(pg_store) == ["disk.low"]
    with pg_store._engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM monitoring_incidents")) == 1
        assert conn.scalar(text("SELECT count(DISTINCT active_incident_id)"
                                " FROM monitoring_incidents")) == 1


# --- recipient snapshots ----------------------------------------------------


@pytest.mark.parametrize("memory", [False, True])
def test_no_recipients_leaves_the_alert_pending(pg_store, memory):
    store = contract(pg_store, memory)
    failed_alert(store)
    assert store.prepare_alert_deliveries(FIXED_AT) == 0
    assert store.claim_alert_delivery(FIXED_AT) is None
    device = register_device(store, "phone", "token-1")
    assert store.prepare_alert_deliveries(FIXED_AT) == 1
    assert [lease.client_id for lease in drain(store)] == [device.id]


def test_snapshot_excludes_revoked_and_non_device_clients_and_is_taken_once(pg_store):
    failed_alert(pg_store)
    first = register_device(pg_store, "phone", "token-1")
    second = register_device(pg_store, "tablet", "token-2")
    revoked = register_device(pg_store, "old-phone", "token-3")
    register_device(pg_store, "browser", "token-4", kind="browser")
    pg_store.mark_client_revoked(revoked.id, FIXED_AT)

    assert pg_store.prepare_alert_deliveries(FIXED_AT) == 1
    late = register_device(pg_store, "late-phone", "token-5")
    assert pg_store.prepare_alert_deliveries(FIXED_AT) == 0

    leases = drain(pg_store)
    assert {lease.client_id for lease in leases} == {first.id, second.id}
    assert {lease.token for lease in leases} == {"token-1", "token-2"}
    assert late.id not in {lease.client_id for lease in leases}
    with pg_store._engine.connect() as conn:
        assert conn.scalar(text("SELECT recipients_snapshotted_at FROM operational_alerts")) \
            is not None


# --- delivery claims --------------------------------------------------------


def test_concurrent_prepares_snapshot_each_alert_once(pg_store, other):
    """Two preparers must not both claim the same alert's recipients."""
    failed_alert(pg_store)
    failed_alert(pg_store, "j-2")
    first = register_device(pg_store, "phone", "token-1")
    second = register_device(pg_store, "tablet", "token-2")
    gate = Barrier(2)

    def prepare(store):
        gate.wait(timeout=10)
        return store.prepare_alert_deliveries(FIXED_AT)

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(prepare, store) for store in (pg_store, other)]
        prepared = sum(future.result(timeout=20) for future in futures)
    assert prepared == 2
    rows = delivery_rows(pg_store)
    assert len(rows) == 4  # two alerts x two recipients, no duplicates
    assert {row[1] for row in rows} == {first.id, second.id}


def test_claim_stores_only_a_token_fingerprint(pg_store):
    failed_alert(pg_store)
    register_device(pg_store, "phone", "token-1")
    pg_store.prepare_alert_deliveries(FIXED_AT)
    lease = pg_store.claim_alert_delivery(FIXED_AT)
    assert lease is not None
    row = delivery_rows(pg_store)[0]
    assert row[5] == token_fingerprint("token-1")
    assert "token-1" not in "".join(str(value) for value in row)
    assert "token-1" not in str(lease.alert.data)
    columns = {
        column["name"]
        for column in inspect(pg_store._engine).get_columns("operational_deliveries")
    }
    assert "token" not in columns


def test_concurrent_claims_issue_one_active_lease_per_delivery(pg_store, other):
    failed_alert(pg_store)
    register_device(pg_store, "phone", "token-1")
    pg_store.prepare_alert_deliveries(FIXED_AT)
    gate = Barrier(2)

    def claim(store):
        gate.wait(timeout=10)
        return store.claim_alert_delivery(FIXED_AT)

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(claim, store) for store in (pg_store, other)]
        leases = [future.result(timeout=20) for future in futures]
    granted = [lease for lease in leases if lease is not None]
    assert len(granted) == 1
    assert granted[0].attempt == 1
    # The unclaimed window is the lease, not the row: the claim survives.
    assert other.claim_alert_delivery(FIXED_AT) is None
    assert other.claim_alert_delivery(FIXED_AT + timedelta(seconds=61)) is not None


@pytest.mark.parametrize("memory", [False, True])
def test_expired_claim_completion_returns_false_and_reclaims(pg_store, memory):
    store = contract(pg_store, memory)
    failed_alert(store)
    register_device(store, "phone", "token-1")
    store.prepare_alert_deliveries(FIXED_AT)
    lease = store.claim_alert_delivery(FIXED_AT)
    assert lease is not None
    expired = FIXED_AT + 61 * SECOND
    assert store.finish_alert_delivery(lease, outcome="accepted", now=expired) is False
    reclaimed = store.claim_alert_delivery(expired)
    assert reclaimed is not None
    assert reclaimed.claim_id != lease.claim_id
    assert reclaimed.attempt == 2
    later = FIXED_AT + 62 * SECOND
    assert store.finish_alert_delivery(lease, outcome="accepted", now=later) is False
    assert store.finish_alert_delivery(reclaimed, outcome="accepted", now=later) is True


@pytest.mark.parametrize("memory", [False, True])
def test_partial_success_is_never_reclaimed(pg_store, memory):
    store = contract(pg_store, memory)
    failed_alert(store)
    first = register_device(store, "phone", "token-1")
    second = register_device(store, "tablet", "token-2")
    store.prepare_alert_deliveries(FIXED_AT)
    accepted = store.claim_alert_delivery(FIXED_AT)
    retried = store.claim_alert_delivery(FIXED_AT)
    assert {accepted.client_id, retried.client_id} == {first.id, second.id}
    assert store.finish_alert_delivery(accepted, outcome="accepted", now=FIXED_AT) is True
    assert store.finish_alert_delivery(retried, outcome="retry", now=FIXED_AT) is True

    assert store.claim_alert_delivery(FIXED_AT + 59 * SECOND) is None
    again = store.claim_alert_delivery(FIXED_AT + 60 * SECOND)
    assert again is not None
    assert again.client_id == retried.client_id
    assert again.attempt == 2
    assert again.delivery_id == retried.delivery_id


@pytest.mark.parametrize("memory", [False, True])
def test_retry_backoff_is_exponential_and_capped(pg_store, memory):
    store = contract(pg_store, memory)
    failed_alert(store)
    register_device(store, "phone", "token-1")
    store.prepare_alert_deliveries(FIXED_AT)
    now = FIXED_AT
    for attempt, delay in enumerate([60, 120, 240, 480, 960, 1920, 3600, 3600], start=1):
        lease = store.claim_alert_delivery(now)
        assert lease is not None and lease.attempt == attempt
        assert store.finish_alert_delivery(lease, outcome="retry", now=now) is True
        assert store.claim_alert_delivery(now + timedelta(seconds=delay - 1)) is None
        now += timedelta(seconds=delay)


def test_retry_delay_is_overflow_safe():
    assert [retry_delay_seconds(attempt) for attempt in (1, 2, 6, 7, 1000, 10**6)] == \
        [60, 120, 1920, 3600, 3600, 3600]


@pytest.mark.parametrize("memory", [False, True])
def test_invalid_registration_removes_the_exact_token(pg_store, memory):
    store = contract(pg_store, memory)
    failed_alert(store)
    register_device(store, "phone", "token-1")
    store.prepare_alert_deliveries(FIXED_AT)
    lease = store.claim_alert_delivery(FIXED_AT)
    assert lease is not None
    assert store.finish_alert_delivery(lease, outcome="invalid", now=FIXED_AT) is True
    # The exact token is gone, so the recipient is not re-leased on a timer.
    assert store.list_active_device_tokens() == []
    assert store.claim_alert_delivery(FIXED_AT + 60 * SECOND) is None


@pytest.mark.parametrize("memory", [False, True])
def test_rotated_token_survives_an_invalid_outcome(pg_store, memory):
    store = contract(pg_store, memory)
    failed_alert(store)
    device = register_device(store, "phone", "token-1")
    store.prepare_alert_deliveries(FIXED_AT)
    lease = store.claim_alert_delivery(FIXED_AT)
    assert lease is not None
    store.register_token(device.id, "token-2", FIXED_AT + SECOND)

    assert store.finish_alert_delivery(lease, outcome="invalid", now=FIXED_AT) is True
    assert [reg.token for reg in store.list_active_device_tokens()] == ["token-2"]
    again = store.claim_alert_delivery(FIXED_AT + 60 * SECOND)
    assert again is not None
    assert again.token == "token-2"


@pytest.mark.parametrize("memory", [False, True])
def test_revoked_recipient_is_terminal_and_never_leased(pg_store, memory):
    store = contract(pg_store, memory)
    failed_alert(store)
    device = register_device(store, "phone", "token-1")
    store.prepare_alert_deliveries(FIXED_AT)
    store.mark_client_revoked(device.id, FIXED_AT + SECOND)
    assert store.claim_alert_delivery(FIXED_AT) is None
    assert store.claim_alert_delivery(FIXED_AT + 3600 * SECOND) is None
