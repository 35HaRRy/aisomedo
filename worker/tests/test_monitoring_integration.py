"""Worker integration: monitoring is isolated from the main tick.

The collector exists because a render can block the main tick for an hour, so
these tests block one and show that disk sampling still happens, that its
activity never renews the busy health deadline, and that a monitoring failure
of any kind never skips a job.
"""

from __future__ import annotations

import json
import signal
import threading
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import worker.main as worker_main
from dojo import DojoPublishing, InMemoryStore, Job
from dojo.adapters.stubs import StubMediaProcessor, StubNotifier
from dojo.model import Client
from dojo.monitoring import DojoMonitoring
from dojo.testing import FIXED_AT, FakeClock
from worker.main import run_tick, start_monitoring
from worker.monitoring import (
    DEFAULT_LOW_PERCENT,
    DEFAULT_RECOVERY_PERCENT,
    DiskSampler,
    MonitoringConfig,
    MonitoringRunner,
)

MEDIA = Path("/media")
ROOT = Path("/")


class BlockingPublishing(DojoPublishing):
    """A main tick whose job blocks until the test releases it."""

    def __init__(self, gate: threading.Event) -> None:
        self._gate = gate
        self.entered = threading.Event()
        self.ticks = 0
        self.processed: list[str] = []
        self._claims_left = 1
        super().__init__(
            packages=InMemoryStore(),
            audit=InMemoryStore(),
            media_root="/tmp/dojo-media",
            media=StubMediaProcessor(),
        )

    def evaluate_due_work(self) -> None:
        self.ticks += 1

    def claim_next_job(self) -> Job | None:
        if not self._claims_left:
            return None
        self._claims_left -= 1
        return Job(
            id=1,
            job_id="j-1",
            upload_id=1,
            kind="render",
            status="queued",
            payload={"package": "pkg", "digest": "d-1"},
            created_at=datetime.now(),
        )

    def process_job(self, job_id: str) -> None:
        self.entered.set()
        self._gate.wait(10)
        self.processed.append(job_id)

    def sweep_stale_uploads(self, ttl: object = None) -> int:
        return 0


class UsageRecorder:
    """``disk_usage`` double that records when each path was sampled."""

    def __init__(self, free: float = 50.0) -> None:
        self.free = free
        self.calls: list[str] = []

    def __call__(self, path: Path) -> SimpleNamespace:
        # as_posix keeps the keys platform-independent: production targets are
        # container paths, and Windows would otherwise re-spell "/media".
        self.calls.append(path.as_posix())
        return SimpleNamespace(total=100, free=self.free, used=100 - self.free)


class PhaseRecorder:
    """Health double: records phase order like the real record would."""

    def __init__(self) -> None:
        self.phases: list[str] = []

    def idle(self) -> None:
        self.phases.append("idle")

    def busy(self) -> None:
        self.phases.append("busy")

    def stopped(self) -> None:
        self.phases.append("stopped")


class FakeDelivery:
    """Delivery-service double: counts turns, optionally fails."""

    def __init__(self, *, fail: bool = False) -> None:
        self.turns = 0
        self.accepted = 0
        self.fail = fail

    def deliver_pending(self, *, limit: int = 100) -> int:
        self.turns += 1
        if self.fail:
            raise ConnectionError("database unavailable")
        return self.accepted


def make_runner(store, delivery, usage, *, interval: float = 3600.0):
    config = MonitoringConfig(
        enabled=True,
        interval_seconds=interval,
        low_percent=DEFAULT_LOW_PERCENT,
        recovery_percent=DEFAULT_RECOVERY_PERCENT,
        targets=(("media", MEDIA), ("root", ROOT)),
    )
    return MonitoringRunner(
        config,
        store,
        delivery,
        sampler=DiskSampler(usage=usage),
    )


def _wait_until(predicate, *, attempts: int = 100) -> bool:
    """Bounded poll so a threaded assertion cannot hang the suite."""
    for _ in range(attempts):
        if predicate():
            return True
        threading.Event().wait(0.05)
    return predicate()


def test_a_blocked_render_does_not_suppress_disk_sampling():
    """The collector's own thread samples while the main tick is stuck."""
    gate = threading.Event()
    publishing = BlockingPublishing(gate)
    store = InMemoryStore()
    usage = UsageRecorder()
    runner = make_runner(store, FakeDelivery(), usage)
    stop = threading.Event()

    # The main tick, in its own thread, blocks inside process_job.
    tick_thread = threading.Thread(
        target=run_tick, args=(publishing, None), daemon=True
    )
    tick_thread.start()
    assert publishing.entered.wait(5)

    collector = start_monitoring(runner, stop)
    try:
        # One turn happens immediately, without waiting for the render.
        assert _wait_until(lambda: bool(usage.calls)), (
            "collector did not sample while the render blocked"
        )
    finally:
        stop.set()
        collector.join(5)
        gate.set()
        tick_thread.join(5)

    assert publishing.processed == ["j-1"]  # the job still completed


def test_collector_activity_never_renews_the_worker_busy_deadline(
    tmp_path, monkeypatch,
):
    """Busy health covers the main tick only; a sampling turn is not a heartbeat."""
    monkeypatch.setenv("WORKER_HEALTH_PATH", str(tmp_path / "health.json"))
    monkeypatch.setenv("WORKER_HEALTH_IDLE_SECONDS", "120")
    monkeypatch.setenv("WORKER_HEALTH_BUSY_SECONDS", "3600")
    health = worker_main.build_worker_health(interval_seconds=10)
    health.busy()
    record = json.loads((tmp_path / "health.json").read_text(encoding="utf-8"))
    busy_deadline = record["deadline"]

    usage = UsageRecorder()
    runner = make_runner(InMemoryStore(), FakeDelivery(), usage)
    stop = threading.Event()
    collector = start_monitoring(runner, stop)
    try:
        assert _wait_until(lambda: bool(usage.calls))
    finally:
        stop.set()
        collector.join(5)

    after = json.loads((tmp_path / "health.json").read_text(encoding="utf-8"))
    # Sampling wrote nothing at all, so the busy deadline cannot have moved.
    assert after == record
    assert after["deadline"] == busy_deadline


def test_monitoring_failures_never_skip_the_job():
    """A collector that fails every turn leaves publication untouched."""
    usage = UsageRecorder()
    # A failing delivery logs on every turn, so the interval is kept wide: a
    # 0.01s interval turns this into a ten-second wall of warnings and asserts
    # nothing extra.
    runner = make_runner(
        InMemoryStore(), FakeDelivery(fail=True), usage, interval=0.05
    )
    gate = threading.Event()
    gate.set()  # the job completes at once; the test is about isolation
    publishing = BlockingPublishing(gate)
    stop = threading.Event()
    collector = start_monitoring(runner, stop)
    try:
        run_tick(publishing, None)
    finally:
        stop.set()
        collector.join(5)

    assert publishing.processed == ["j-1"]
    assert publishing.ticks == 1


class ProtocolOnlyStore:
    """Store that implements exactly ``MonitoringStore`` and nothing else.

    Any member outside the protocol is recorded in ``borrowed`` and answered
    with a stand-in, rather than raised: the runner isolates store failures, so
    a raise here would only be logged and the turn would still look successful.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.borrowed: list[str] = []

    def record_disk_sample(self, sample, *, low_percent, recovery_percent) -> None:
        self.calls.append(f"sample:{sample.target}")

    def prepare_alert_deliveries(self, now, *, limit: int = 100) -> int:
        self.calls.append("prepare")
        return 0

    def claim_alert_delivery(self, now, *, lease_seconds: int = 60):
        self.calls.append("claim")
        return None

    def finish_alert_delivery(self, lease, *, outcome, now) -> bool:
        self.calls.append("finish")
        return False

    def __getattr__(self, name: str) -> object:
        self.borrowed.append(name)
        return None


def test_monitoring_touches_only_the_monitoring_store_protocol():
    """A whole turn, delivery included, stays inside the monitoring protocol.

    The main tick owns the emission transaction, so a collector that borrowed
    ``emission_transaction``, ``try_advisory_xact_lock`` or ``create_all`` would
    run its sample and its send inside that connection: rolled back with the
    tick, and holding a transaction across a provider send.
    """
    usage = UsageRecorder()
    store = ProtocolOnlyStore()
    monitoring = DojoMonitoring(store, StubNotifier(), FakeClock())
    runner = make_runner(store, monitoring, usage)

    runner.tick()

    assert usage.calls == ["/media", "/"]
    assert store.calls == ["sample:media", "sample:root", "prepare", "claim"]
    assert store.borrowed == []


def _fail_one_job(store, job_id: str = "j-1") -> None:
    """Persist one terminal job failure, which is what monitoring alerts on."""
    store.create(
        Job(
            id=0,
            job_id=job_id,
            upload_id=None,
            kind="media.process",
            status="queued",
            payload={},
            created_at=FIXED_AT,
        )
    )
    job = store.get(job_id)
    store.update(
        replace(job, status="failed", finished_at=FIXED_AT, error_reason="x")
    )


def _register_device(store, token: str = "token-1") -> None:
    """Pair a device, so an alert has a recipient and delivery is reachable."""
    client = store.create_client(
        Client(
            id=0,
            name="phone",
            kind="device",
            created_at=FIXED_AT,
            created_by="cli",
        ),
        credential_hash="cred-phone",
    )
    store.register_token(client.id, token, FIXED_AT)


def test_a_second_worker_delivers_the_same_alert_without_a_duplicate_claim():
    """Followers may deliver too; the store's leases stop a double send."""
    store = InMemoryStore()
    _fail_one_job(store)
    _register_device(store)

    notifier = StubNotifier()
    usage = UsageRecorder()
    leader = make_runner(store, DojoMonitoring(store, notifier, FakeClock()), usage)
    follower = make_runner(store, DojoMonitoring(store, notifier, FakeClock()), usage)

    leader.tick()
    follower.tick()

    # One send in total: the second worker found the recipient already done.
    assert len(notifier.sent) == 1
    assert notifier.sent[0][1] == ["token-1"]


def test_disabled_monitoring_neither_samples_nor_acknowledges(monkeypatch):
    """A disabled deployment builds no collector, so its alerts stay pending.

    A device is paired on purpose. With no recipient, delivery is impossible
    whatever monitoring does, so an assertion about "not sent" would hold
    either way. The control turn at the end is what makes this test
    discriminating: the same store, alert and notifier are delivered the
    moment a collector runs, so nothing about the fixture blocks delivery.
    """
    monkeypatch.setenv("MEDIA_ROOT", "/media")
    monkeypatch.delenv("MONITORING_ENABLED", raising=False)
    assert worker_main.build_monitoring() is None

    store = InMemoryStore()
    notifier = StubNotifier()
    _fail_one_job(store)
    _register_device(store, "token-1")
    usage = UsageRecorder()
    runner = make_runner(store, DojoMonitoring(store, notifier, FakeClock()), usage)

    # Disabled: no collector was built, so nothing sampled and nothing sent.
    assert notifier.sent == []
    assert not usage.calls
    # No recipient row exists, so the alert was never even snapshotted: it is
    # pending, not acknowledged. A snapshot is what creates these rows.
    assert store._deliveries == []  # noqa: SLF001 - the store is the fixture

    # Control: an enabled collector over the same fixture delivers it, so the
    # assertions above are about monitoring being off, not about delivery being
    # impossible.
    runner.tick()

    assert [tokens for _note, tokens in notifier.sent] == [["token-1"]]
    assert usage.calls == ["/media", "/"]
    assert store._deliveries  # noqa: SLF001 - now snapshotted and claimed


def test_monitoring_enabled_without_fcm_fails_startup(
    monkeypatch, caplog: pytest.LogCaptureFixture
):
    """Silent alert loss is a configuration fault, not a degraded mode.

    The failure is also a structured record, not only a bare traceback: this is
    a configuration state with no credential text to leak, and an operator
    greps the JSON log, not the process's stderr.
    """
    monkeypatch.setenv("MONITORING_ENABLED", "true")
    monkeypatch.setenv("MONITORING_DISK_PATHS", '{"media": "/media", "root": "/"}')
    monkeypatch.setenv("FCM_ENABLED", "false")

    with caplog.at_level("ERROR", logger="worker.main"):
        with pytest.raises(RuntimeError, match="FCM_ENABLED"):
            worker_main.build_monitoring()

    (record,) = [
        captured
        for captured in caplog.records
        if getattr(captured, "event", None) == "monitoring.notifier_missing"
    ]
    assert record.status == "error"


def test_monitoring_uses_its_own_store_not_publishings_ports(monkeypatch):
    built: list[str] = []
    real_store = worker_main.PostgresStore

    class RecordingStore(real_store):  # type: ignore[misc]
        def __init__(self, url: str) -> None:
            built.append(url)
            super().__init__(url)

    monkeypatch.setattr(worker_main, "PostgresStore", RecordingStore)
    monkeypatch.setenv("MONITORING_ENABLED", "true")
    monkeypatch.setenv("FCM_ENABLED", "true")
    monkeypatch.setenv("FCM_PROJECT_ID", "dojo-prod")
    monkeypatch.setenv("SKIP_CREATE_ALL", "1")
    monkeypatch.setenv("MEDIA_ROOT", "/media")
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://127.0.0.1:1/unreachable"
    )
    monkeypatch.setattr(worker_main, "FcmNotifier", lambda **kwargs: object())

    result = worker_main.build_monitoring()

    assert result is not None
    runner, store = result
    assert built == ["postgresql+psycopg://127.0.0.1:1/unreachable"]
    # The collector holds its own store, and never the publishing ports.
    assert runner._store is store
    assert runner._monitoring._store is store  # noqa: SLF001
    store.dispose()


class DisposableStore(InMemoryStore):
    """In-memory store that records disposal."""

    def __init__(self) -> None:
        super().__init__()
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


def test_a_collector_that_outlives_the_join_is_logged(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A truncated shutdown is visible, not silently clean.

    Disposing the pool under a live collector loses whatever that turn was
    doing, which is safe (the next turn re-samples; a delivery stays pending
    behind its lease) but must never look like an orderly stop. The join bound
    is shortened so the test costs milliseconds instead of the production ten
    seconds.
    """
    monkeypatch.setattr(worker_main, "MONITORING_JOIN_SECONDS", 0.05)
    store = DisposableStore()
    released = threading.Event()
    collector = threading.Thread(
        target=lambda: released.wait(30), name="dojo-monitoring", daemon=True
    )
    collector.start()

    with caplog.at_level("WARNING", logger="worker.main"):
        worker_main._stop_monitoring(collector, store)  # noqa: SLF001
    released.set()
    collector.join(5)

    (record,) = [
        captured
        for captured in caplog.records
        if getattr(captured, "event", None) == "monitoring.shutdown_incomplete"
    ]
    assert record.status == "alive"
    assert store.disposed is True  # disposal still happened, as documented


def test_a_clean_join_logs_no_incomplete_shutdown(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = DisposableStore()
    stop = threading.Event()
    stop.set()
    collector = start_monitoring(
        make_runner(InMemoryStore(), FakeDelivery(), UsageRecorder()), stop
    )
    collector.join(5)

    with caplog.at_level("WARNING", logger="worker.main"):
        worker_main._stop_monitoring(collector, store)  # noqa: SLF001

    assert not [
        captured
        for captured in caplog.records
        if getattr(captured, "event", None) == "monitoring.shutdown_incomplete"
    ]


def test_worker_start_and_stop_the_collector_with_the_shutdown_event(monkeypatch):
    """main() starts one collector and joins it on the same SIGTERM event."""
    handlers: dict[int, object] = {}
    runner = make_runner(InMemoryStore(), FakeDelivery(), UsageRecorder())
    store = DisposableStore()
    health = PhaseRecorder()
    started: list[tuple[object, threading.Thread]] = []

    real_start = worker_main.start_monitoring

    def start(runner_arg, stop_arg):
        # Recorded rather than stubbed: the thread really runs, so the test
        # sees the same shutdown event the main loop waits on.
        thread = real_start(runner_arg, stop_arg)
        started.append((stop_arg, thread))
        return thread

    monkeypatch.setenv("WORKER_INTERVAL_SECONDS", "0.01")
    monkeypatch.setattr(worker_main, "build_publishing", lambda: object())
    monkeypatch.setattr(worker_main, "build_meta", lambda: None)
    monkeypatch.setattr(worker_main, "build_worker_health", lambda interval: health)
    monkeypatch.setattr(worker_main, "build_monitoring", lambda: (runner, store))
    monkeypatch.setattr(worker_main, "start_monitoring", start)

    def tick(publishing: object, meta: object) -> None:
        handlers[signal.SIGTERM](None, None)  # request stop after one turn

    monkeypatch.setattr(worker_main, "run_tick", tick)
    monkeypatch.setattr(
        worker_main.signal,
        "signal",
        lambda signum, handler: handlers.setdefault(signum, handler),
    )

    worker_main.main()

    assert signal.SIGTERM in handlers and signal.SIGINT in handlers
    assert health.phases == ["idle", "busy", "idle", "stopped"]
    (stop, thread) = started[0]
    # The collector saw the same shutdown event and was joined before exit.
    assert stop.is_set()
    assert not thread.is_alive()
    # Its own store was released, not left to process exit.
    assert store.disposed is True
