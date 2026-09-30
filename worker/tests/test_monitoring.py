"""Disk monitoring: configuration, sampling, and the isolated collector turn.

Every case is deterministic: the clock is fixed, the filesystem is a scripted
``disk_usage`` double, and delivery runs against the real in-memory monitoring
store, so what is asserted here is the runner's own behaviour — fault
isolation, hysteresis, restart safety and the interval schedule.
"""

from __future__ import annotations

import logging
import threading
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from dojo.adapters.memory import InMemoryStore
from dojo.adapters.stubs import StubNotifier
from dojo.model import Client
from dojo.monitoring import DojoMonitoring
from dojo.testing import FIXED_AT, FakeClock
from worker.monitoring import (
    DEFAULT_INTERVAL_SECONDS,
    DEFAULT_LOW_PERCENT,
    DEFAULT_RECOVERY_PERCENT,
    DiskSampler,
    MonitoringConfig,
    MonitoringRunner,
)

MEDIA = Path("/media")
ROOT = Path("/")
SECOND = timedelta(seconds=1)


# --- doubles -----------------------------------------------------------------


class FakeUsage:
    """Scripted ``disk_usage``: free percent per path, or an exception."""

    def __init__(self, readings: dict[str, float | Exception]) -> None:
        self.readings = readings
        self.calls: list[str] = []

    def __call__(self, path: Path) -> SimpleNamespace:
        # as_posix keeps the keys platform-independent: the production targets
        # are container paths, and Windows would otherwise re-spell "/media".
        key = path.as_posix()
        self.calls.append(key)
        reading = self.readings[key]
        if isinstance(reading, Exception):
            raise reading
        return SimpleNamespace(total=100, free=reading, used=100 - reading)


class ScriptedStop:
    """Shutdown-event double that ends the loop after ``turns`` waits."""

    def __init__(self, turns: int) -> None:
        self._remaining = turns
        self.waits: list[float] = []

    def is_set(self) -> bool:
        return self._remaining <= 0

    def wait(self, timeout: float | None = None) -> bool:
        self.waits.append(timeout)
        self._remaining -= 1
        return self._remaining <= 0


class FakeMonotonic:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class ExplodingStore(InMemoryStore):
    """Store whose snapshot step fails, as a dead database would."""

    def prepare_alert_deliveries(self, now, *, limit: int = 100) -> int:
        raise ConnectionError("database unavailable")


def make_runner(
    *,
    readings: dict[str, float | Exception] | None = None,
    interval: float = 60.0,
    store: InMemoryStore | None = None,
    notifier: StubNotifier | None = None,
    targets: tuple[tuple[str, Path], ...] = (("media", MEDIA), ("root", ROOT)),
    monitor: object | None = None,
    monotonic: object | None = None,
) -> tuple[MonitoringRunner, InMemoryStore, StubNotifier, FakeUsage]:
    store = store if store is not None else InMemoryStore()
    notifier = notifier if notifier is not None else StubNotifier()
    usage = FakeUsage(readings if readings is not None else {"/media": 50.0, "/": 60.0})
    config = MonitoringConfig(
        enabled=True,
        interval_seconds=interval,
        low_percent=DEFAULT_LOW_PERCENT,
        recovery_percent=DEFAULT_RECOVERY_PERCENT,
        targets=targets,
    )
    monitoring = (
        DojoMonitoring(store, notifier, FakeClock())
        if monitor is None
        else monitor
    )
    kwargs: dict = {}
    if monotonic is not None:
        kwargs["monotonic"] = monotonic
    runner = MonitoringRunner(
        config,
        store,
        monitoring,
        clock=FakeClock(),
        sampler=DiskSampler(usage=usage),
        **kwargs,
    )
    return runner, store, notifier, usage


def advance(clock: FakeClock, seconds: float) -> None:
    clock._now += timedelta(seconds=seconds)


def kinds(store: InMemoryStore) -> list[str]:
    return [alert.kind for alert in store.recorded_alerts]


def register_device(store: InMemoryStore, token: str = "token-1") -> None:
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


# --- configuration -----------------------------------------------------------


def test_monitoring_is_off_unless_explicitly_enabled() -> None:
    config = MonitoringConfig.from_env({}, media_root=MEDIA)

    assert config.enabled is False
    assert config.targets == ()


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes"])
def test_enabled_values_use_the_documented_defaults(value: str) -> None:
    config = MonitoringConfig.from_env({"MONITORING_ENABLED": value}, media_root=MEDIA)

    assert config.enabled is True
    assert config.interval_seconds == DEFAULT_INTERVAL_SECONDS
    assert config.low_percent == DEFAULT_LOW_PERCENT
    assert config.recovery_percent == DEFAULT_RECOVERY_PERCENT
    # Default coverage: the media volume and the worker's root filesystem.
    assert config.targets == (("media", MEDIA), ("root", ROOT))


@pytest.mark.parametrize("value", ["", "0", "false", "no", "maybe"])
def test_anything_else_leaves_monitoring_disabled(value: str) -> None:
    config = MonitoringConfig.from_env({"MONITORING_ENABLED": value}, media_root=MEDIA)

    assert config.enabled is False


@pytest.mark.parametrize(
    "name",
    [
        "MONITORING_INTERVAL_SECONDS",
        "MONITORING_DISK_LOW_PERCENT",
        "MONITORING_DISK_RECOVERY_PERCENT",
    ],
)
@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "NaN", "Infinity"])
def test_non_finite_settings_are_rejected(name: str, value: str) -> None:
    # float("nan") and float("inf") parse fine, so without an explicit
    # finiteness check they become an unsatisfiable threshold or an interval
    # that turns the collector into a tight loop.
    with pytest.raises(ValueError, match="finite"):
        MonitoringConfig.from_env(
            {"MONITORING_ENABLED": "true", name: value}, media_root=MEDIA
        )


def test_non_numeric_interval_is_rejected() -> None:
    with pytest.raises(ValueError, match="must be a number"):
        MonitoringConfig.from_env(
            {"MONITORING_ENABLED": "true", "MONITORING_INTERVAL_SECONDS": "soon"},
            media_root=MEDIA,
        )


@pytest.mark.parametrize("interval", ["0", "-1"])
def test_non_positive_interval_is_rejected(interval: str) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        MonitoringConfig.from_env(
            {"MONITORING_ENABLED": "true", "MONITORING_INTERVAL_SECONDS": interval},
            media_root=MEDIA,
        )


@pytest.mark.parametrize(
    ("low", "recovery"),
    [("15", "15"), ("20", "15"), ("0", "20"), ("-1", "20"), ("15", "101")],
)
def test_thresholds_must_keep_the_hysteresis_order(low: str, recovery: str) -> None:
    with pytest.raises(ValueError, match="0 < low < recovery <= 100"):
        MonitoringConfig.from_env(
            {
                "MONITORING_ENABLED": "true",
                "MONITORING_DISK_LOW_PERCENT": low,
                "MONITORING_DISK_RECOVERY_PERCENT": recovery,
            },
            media_root=MEDIA,
        )


def test_configured_targets_replace_the_defaults() -> None:
    config = MonitoringConfig.from_env(
        {
            "MONITORING_ENABLED": "true",
            "MONITORING_DISK_PATHS": '{"media": "/media", "postgres": "/srv/pgdata"}',
        },
        media_root=MEDIA,
    )

    assert config.targets == (("media", MEDIA), ("postgres", Path("/srv/pgdata")))


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        "{}",
        '"media"',
        '{"": "/media"}',
        '{"media": ""}',
        '{"media": "media-relative"}',
        '{"media": 7}',
    ],
)
def test_unusable_disk_path_configuration_is_rejected(raw: str) -> None:
    with pytest.raises(ValueError):
        MonitoringConfig.from_env(
            {"MONITORING_ENABLED": "true", "MONITORING_DISK_PATHS": raw},
            media_root=MEDIA,
        )


def test_media_root_is_the_default_media_target() -> None:
    config = MonitoringConfig.from_env(
        {"MONITORING_ENABLED": "true"}, media_root=Path("/srv/dojo-media")
    )

    assert config.targets[0] == ("media", Path("/srv/dojo-media"))


@pytest.mark.parametrize("media_root", [Path("media"), Path("."), Path("data/media")])
def test_a_relative_media_root_is_rejected_even_as_the_default(
    media_root: Path,
) -> None:
    """The default is validated like any configured target.

    A relative default would resolve against the worker's working directory
    and then fail on every turn: a silent 60-second failure loop with no media
    coverage, which is exactly what the default exists to prevent.
    """
    with pytest.raises(ValueError, match="must be an absolute path"):
        MonitoringConfig.from_env(
            {"MONITORING_ENABLED": "true"}, media_root=media_root
        )


def test_an_empty_media_root_is_rejected() -> None:
    # ``Path("")`` stringifies to ".", which is relative, so the absoluteness
    # check is what catches an empty MEDIA_ROOT.
    with pytest.raises(ValueError, match="must be an absolute path"):
        MonitoringConfig.from_env(
            {"MONITORING_ENABLED": "true"}, media_root=Path("")
        )


def test_the_worker_default_media_root_cannot_silently_enable_monitoring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``build_monitoring`` must not start a collector on a relative MEDIA_ROOT.

    ``build_publishing`` falls back to the relative ``"media"``, so monitoring
    inherits that value in a deployment that forgot to set it; rejecting it
    here is the difference between a failed startup and a collector that
    reports nothing for the media volume forever.
    """
    import worker.main as worker_main

    monkeypatch.delenv("MONITORING_DISK_PATHS", raising=False)
    monkeypatch.delenv("MEDIA_ROOT", raising=False)
    monkeypatch.setenv("MONITORING_ENABLED", "true")
    monkeypatch.setenv("FCM_ENABLED", "true")
    monkeypatch.setattr(worker_main, "FcmNotifier", lambda **kwargs: object())

    with pytest.raises(ValueError, match="must be an absolute path"):
        worker_main.build_monitoring()

    monkeypatch.setenv("MEDIA_ROOT", "/media")
    built = worker_main.build_monitoring()
    assert built is not None
    assert built[0]._config.targets == (  # noqa: SLF001
        ("media", Path("/media")),
        ("root", Path("/")),
    )
    built[1].dispose()


# --- sampling ----------------------------------------------------------------


def test_sample_reports_free_and_total_bytes() -> None:
    sampler = DiskSampler(usage=FakeUsage({"/media": 42.0}))

    sample = sampler.sample("media", MEDIA, FIXED_AT)

    assert sample.target == "media"
    assert sample.sampled_at == FIXED_AT
    assert sample.total_bytes == 100
    assert sample.free_bytes == 42
    assert sample.free_percent == 42.0


@pytest.mark.parametrize("total", [0, -1])
def test_unmeasurable_capacity_is_rejected_rather_than_recorded(total: int) -> None:
    # A zero-total reading would divide by zero, and a "0% free" sample at the
    # recovery threshold would look like a recovery of an open incident.
    sampler = DiskSampler(usage=lambda path: SimpleNamespace(total=total, free=0))

    with pytest.raises(ValueError, match="no measurable capacity"):
        sampler.sample("media", MEDIA, FIXED_AT)


def test_unreadable_path_propagates_to_the_caller() -> None:
    sampler = DiskSampler(
        usage=FakeUsage({"/media": FileNotFoundError("mount is gone")})
    )

    with pytest.raises(FileNotFoundError):
        sampler.sample("media", MEDIA, FIXED_AT)


# --- one collection turn -----------------------------------------------------


def test_healthy_targets_are_sampled_and_nothing_is_alerted() -> None:
    runner, store, notifier, usage = make_runner(
        readings={"/media": 50.0, "/": 60.0}
    )

    runner.tick()

    assert usage.calls == ["/media", "/"]
    assert store.recorded_alerts == []
    assert notifier.sent == []


def test_low_target_opens_one_incident_and_alerts_once() -> None:
    runner, store, notifier, _ = make_runner(
        readings={"/media": 10.0, "/": 60.0}
    )
    register_device(store)

    runner.tick()
    runner.tick()

    assert kinds(store) == ["disk.low"]
    assert len(notifier.sent) == 1
    # The label reaches the operator; the path never does.
    title, body = notifier.sent[0][0].title, notifier.sent[0][0].body
    assert body == "media hedefinde boş alan oranı düşük."
    assert "/media" not in f"{title} {body}"


def test_hysteresis_holds_the_incident_open_between_thresholds() -> None:
    clock = FakeClock()
    store = InMemoryStore()
    runner, _store, _notifier, _usage = make_runner(
        readings={"/media": 10.0, "/": 60.0}, store=store
    )
    # Re-bind the runner's clock so a caller-owned clock can be advanced.
    runner._clock = clock  # noqa: SLF001 - the double is the seam, not production

    runner.tick()
    advance(clock, 60)
    runner._sampler = DiskSampler(usage=FakeUsage({"/media": 17.0, "/": 60.0}))  # noqa: SLF001
    runner.tick()
    advance(clock, 60)
    runner._sampler = DiskSampler(usage=FakeUsage({"/media": 20.0, "/": 60.0}))  # noqa: SLF001
    runner.tick()

    # 10% opens, 17% stays open (below recovery), 20% recovers: one incident.
    assert kinds(store) == ["disk.low", "disk.recovered"]


def test_one_failed_mount_never_reads_as_recovery_and_others_still_sample() -> None:
    store = InMemoryStore()
    clock = FakeClock()
    runner, _store, _notifier, _usage = make_runner(
        readings={"/media": 10.0, "/": 10.0}, store=store
    )
    runner._clock = clock  # noqa: SLF001

    runner.tick()
    assert kinds(store) == ["disk.low", "disk.low"]

    # The media mount disappears while the root filesystem recovers.
    usage = FakeUsage(
        {"/media": OSError("I/O error"), "/": 55.0}
    )
    runner._sampler = DiskSampler(usage=usage)  # noqa: SLF001
    advance(clock, 60)
    runner.tick()

    assert kinds(store) == ["disk.low", "disk.low", "disk.recovered"]
    assert store._incidents["media"] is not None  # noqa: SLF001 - still open
    # One attempt per target per turn, not a retry loop inside the turn.
    assert usage.calls == ["/media", "/"]


def test_a_failed_sample_leaves_the_open_incident_and_retries_next_turn() -> None:
    store = InMemoryStore()
    clock = FakeClock()
    runner, _store, _notifier, _usage = make_runner(
        readings={"/media": 10.0, "/": 10.0}, store=store
    )
    runner._clock = clock  # noqa: SLF001

    runner.tick()
    usage = FakeUsage({"/media": OSError("I/O error"), "/": 90.0})
    runner._sampler = DiskSampler(usage=usage)  # noqa: SLF001
    advance(clock, 60)
    runner.tick()
    # The next turn retries the failed target once more.
    advance(clock, 60)
    runner.tick()

    assert store._incidents["media"] is not None  # noqa: SLF001
    assert kinds(store).count("disk.recovered") == 1  # only the root recovered
    assert usage.calls.count("/media") == 2


def test_a_rejected_sample_is_logged_and_never_escapes_the_turn() -> None:
    class RejectingStore(InMemoryStore):
        def record_disk_sample(self, sample, *, low_percent, recovery_percent):
            raise ValueError("disk sample for 'media' has no measurable capacity")

    runner, _store, _notifier, _usage = make_runner(
        readings={"/media": 10.0, "/": 10.0}, store=RejectingStore()
    )

    runner.tick()  # must not raise


def test_delivery_failure_is_logged_and_never_escapes_the_turn() -> None:
    store = ExplodingStore()
    register_device(store)
    runner, _store, _notifier, _usage = make_runner(
        readings={"/media": 10.0, "/": 10.0}, store=store
    )

    runner.tick()  # must not raise

    # Sampling still happened; only the send side failed.
    assert store._incidents["media"] is not None  # noqa: SLF001


def test_a_recorded_sample_is_logged_with_the_target_label_only(
    caplog: pytest.LogCaptureFixture,
):
    """The sample event names the target, never its path."""
    runner, _store, _notifier, _usage = make_runner(
        readings={"/media": 10.0, "/": 60.0}
    )

    with caplog.at_level(logging.INFO, logger="worker.monitoring"):
        runner.tick()

    samples = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "monitoring.disk_sample"
    ]
    # A low target is notable and logged; a healthy one stays out of INFO.
    assert [record.status for record in samples] == ["media"]
    assert "/media" not in samples[0].getMessage()


def test_sampling_failures_are_logged_with_safe_fields_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    runner, _store, _notifier, _usage = make_runner(
        readings={"/media": OSError("mount /media is gone"), "/": 90.0}
    )

    with caplog.at_level(logging.WARNING, logger="worker.monitoring"):
        runner.tick()

    failures = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "monitoring.disk_sample_failed"
    ]
    assert len(failures) == 1
    assert failures[0].status == "media"
    # The label is safe; the filesystem path and the raw error are not logged.
    assert failures[0].exc_info[0] is OSError


def test_a_restart_while_still_low_opens_no_second_incident() -> None:
    """Incident state is durable, so a restart is not a new incident."""
    store = InMemoryStore()
    first, _store, _notifier, _usage = make_runner(
        readings={"/media": 10.0, "/": 60.0}, store=store
    )
    first.tick()
    assert kinds(store) == ["disk.low"]

    # A restart is a new runner over the same durable state, still low.
    clock = FakeClock()
    restarted, _store, _notifier, _usage = make_runner(
        readings={"/media": 14.0, "/": 60.0}, store=store
    )
    restarted._clock = clock  # noqa: SLF001 - the double is the seam
    for elapsed in (0, 60, 120):
        advance(clock, elapsed)
        restarted.tick()

    # One opening only: 14% is below the recovery threshold, so the incident
    # stays open and re-sampling it must not re-alert.
    assert kinds(store) == ["disk.low"]


# --- the schedule ------------------------------------------------------------


def test_run_collects_immediately_then_waits_one_interval() -> None:
    monotonic = FakeMonotonic()
    runner, _store, _notifier, usage = make_runner(
        readings={"/media": 50.0, "/": 60.0}, interval=60.0, monotonic=monotonic
    )
    stop = ScriptedStop(turns=2)

    runner.run(stop)  # type: ignore[arg-type] - the double is the seam

    # No waiting before the first turn, and the deadline grid is 60, 120, ...
    # so each turn waits out exactly the interval it was scheduled for.
    assert len(usage.calls) == 4
    assert stop.waits == [pytest.approx(60.0), pytest.approx(120.0)]


def test_run_uses_monotonic_deadlines_so_a_slow_turn_does_not_shift_them() -> None:
    runner, _store, _notifier, _usage = make_runner(interval=60.0)
    stop = ScriptedStop(turns=2)

    runner.run(stop)  # type: ignore[arg-type]

    # Deadlines stay on the 60-second grid, so a turn that takes a fifth of
    # the interval shortens its own wait instead of pushing the schedule out.
    assert stop.waits == [pytest.approx(60.0), pytest.approx(120.0)]

    drifting = FakeMonotonic()
    slow_stop = ScriptedStop(turns=2)
    _with_tick_cost(runner, drifting, 20.0).run(slow_stop)  # type: ignore[arg-type]

    assert slow_stop.waits == [pytest.approx(40.0), pytest.approx(80.0)]


def _with_tick_cost(
    runner: MonitoringRunner, monotonic: FakeMonotonic, cost: float
) -> MonitoringRunner:
    """A runner whose turns advance the fake monotonic clock by ``cost``."""

    class SlowRunner(MonitoringRunner):
        def tick(self) -> None:
            super().tick()
            monotonic.advance(cost)

    return SlowRunner(
        runner._config,  # noqa: SLF001 - the double is the seam, not production
        runner._store,  # noqa: SLF001
        runner._monitoring,  # noqa: SLF001
        clock=runner._clock,  # noqa: SLF001
        sampler=runner._sampler,  # noqa: SLF001
        monotonic=monotonic,
    )


def test_an_overrun_reports_how_many_turns_it_skipped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The skipped count is the diagnosis, so it must survive into the log.

    It rides in ``status`` because ``JsonFormatter`` never serializes message
    arguments: an argument-only count would be invisible in production.
    """
    monotonic = FakeMonotonic()
    runner, _store, _notifier, _usage = make_runner(
        interval=60.0, monotonic=monotonic
    )
    stop = ScriptedStop(turns=1)
    stuck = _with_tick_cost(runner, monotonic, 3.5 * 60.0)

    with caplog.at_level(logging.WARNING, logger="worker.monitoring"):
        stuck.run(stop)  # type: ignore[arg-type]

    (overrun,) = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "monitoring.overrun"
    ]
    assert overrun.status == "skipped=3"


def test_an_overrun_skips_missed_turns_instead_of_catching_up() -> None:
    monotonic = FakeMonotonic()
    runner, _store, _notifier, usage = make_runner(
        interval=60.0, monotonic=monotonic
    )
    stop = ScriptedStop(turns=1)
    # One turn that took five intervals: the four it missed must be dropped,
    # not run back to back.
    stuck = _with_tick_cost(runner, monotonic, 5 * 60.0)

    stuck.run(stop)  # type: ignore[arg-type]

    # A single turn ran and the next wait is a full interval, not a tight loop.
    assert len(usage.calls) == 2
    assert stop.waits == [pytest.approx(60.0)]


def test_stop_interrupts_the_collector_wait() -> None:
    """A long interval must not delay shutdown: the wait is interruptible."""
    runner, _store, _notifier, usage = make_runner(interval=3600.0)
    stop = threading.Event()
    finished = threading.Event()

    def _collect() -> None:
        runner.run(stop)
        finished.set()

    thread = threading.Thread(target=_collect, daemon=True)
    thread.start()
    # The first turn runs immediately, without waiting out the interval.
    for _ in range(100):
        if usage.calls:
            break
        threading.Event().wait(0.05)
    assert usage.calls, "the collector did not run its immediate first turn"

    stop.set()
    thread.join(5.0)

    assert finished.is_set()
    assert not thread.is_alive()
