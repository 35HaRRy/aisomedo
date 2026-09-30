"""Disk-state collection for the worker, on its own thread and its own store.

A render can block the worker's main tick for as long as the render takes, and
disk pressure during a long render is exactly when an operator needs to hear
about it. The collector therefore runs outside the main tick: it never renews
the worker health deadline, never joins an emission transaction and never
shares a session with publication. It reads the filesystem, records samples
through the monitoring store (which owns incident state and thresholds) and
drives alert delivery. Everything it does is fault-isolated, because a
monitoring failure must never affect publication.
"""

from __future__ import annotations

import json
import logging
import math
import os
import shutil
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from dojo.adapters.clock import SystemClock
from dojo.monitoring import DojoMonitoring
from dojo.monitoring_models import DiskSample
from dojo.monitoring_ports import MonitoringStore
from dojo.ports import Clock

logger = logging.getLogger(__name__)

#: Accepted ``MONITORING_ENABLED`` spellings, matching the FCM switch. Any
#: other value leaves the collector off, so monitoring is opt-in everywhere.
ENABLED_VALUES = ("1", "true", "yes")

DEFAULT_INTERVAL_SECONDS = 60.0
DEFAULT_LOW_PERCENT = 15.0
DEFAULT_RECOVERY_PERCENT = 20.0
DEFAULT_ROOT_PATH = "/"

#: Minimum seconds between two ``monitoring.disk_sample_failed`` records for the
#: same target. A non-existent target fails every turn, so an unbounded record
#: is one warning a minute per target forever — easily lost to the 3 × 10 MiB
#: rotation, which is exactly how "this filesystem is not covered" turns into a
#: claim instead of a fact. The first failure of each target is logged in full
#: with ``exc_info``; after that the record repeats at most this often.
SAMPLE_FAILURE_LOG_INTERVAL_SECONDS = 900.0


def _number(raw: str | None, default: float, name: str) -> float:
    """Parse one numeric setting, rejecting NaN/infinity explicitly.

    ``float("nan")`` and ``float("inf")`` parse successfully, so a typo would
    otherwise become a threshold no sample can satisfy, or an interval that
    turns the collector into a tight loop.
    """
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {raw!r}")
    return value


@dataclass(frozen=True)
class MonitoringConfig:
    """Validated disk-monitoring settings for one worker process."""

    enabled: bool
    interval_seconds: float
    low_percent: float
    recovery_percent: float
    #: ``(target label, path)`` in configured order. The label is what reaches
    #: alerts and logs; the path never does.
    targets: tuple[tuple[str, Path], ...] = ()

    @classmethod
    def from_env(
        cls, env: Mapping[str, str], *, media_root: Path
    ) -> MonitoringConfig:
        """Read monitoring settings, validating everything an enabled collector uses.

        A disabled collector is exactly the documented defaults: a deployment
        that never turns monitoring on must not be blocked by a threshold it
        would never apply.
        """
        enabled = (
            (env.get("MONITORING_ENABLED") or "false").strip().lower()
            in ENABLED_VALUES
        )
        if not enabled:
            return cls(
                enabled=False,
                interval_seconds=DEFAULT_INTERVAL_SECONDS,
                low_percent=DEFAULT_LOW_PERCENT,
                recovery_percent=DEFAULT_RECOVERY_PERCENT,
            )
        interval = _number(
            env.get("MONITORING_INTERVAL_SECONDS"),
            DEFAULT_INTERVAL_SECONDS,
            "MONITORING_INTERVAL_SECONDS",
        )
        low = _number(
            env.get("MONITORING_DISK_LOW_PERCENT"),
            DEFAULT_LOW_PERCENT,
            "MONITORING_DISK_LOW_PERCENT",
        )
        recovery = _number(
            env.get("MONITORING_DISK_RECOVERY_PERCENT"),
            DEFAULT_RECOVERY_PERCENT,
            "MONITORING_DISK_RECOVERY_PERCENT",
        )
        if interval <= 0:
            raise ValueError(
                f"MONITORING_INTERVAL_SECONDS must be positive, got {interval}"
            )
        if not 0 < low < recovery <= 100:
            raise ValueError(
                "disk thresholds must satisfy 0 < low < recovery <= 100, got "
                f"low={low} recovery={recovery}"
            )
        return cls(
            enabled=True,
            interval_seconds=interval,
            low_percent=low,
            recovery_percent=recovery,
            targets=cls._targets(env, media_root),
        )

    @staticmethod
    def _targets(
        env: Mapping[str, str], media_root: Path
    ) -> tuple[tuple[str, Path], ...]:
        """Configured ``name -> path`` targets, defaulting to media and root.

        Paths must be absolute: a relative disk target resolves against the
        worker's working directory, which is not a filesystem the operator
        chose, and the sample would quietly describe the wrong disk.
        """
        raw = env.get("MONITORING_DISK_PATHS")
        if raw is None or not raw.strip():
            # The defaults go through the same validation as configured ones.
            # Returning them unchecked would let an unset or relative
            # ``MEDIA_ROOT`` produce a relative target, which resolves against
            # the worker's working directory and then fails on every turn: a
            # silent failure loop with no media coverage at all.
            return MonitoringConfig._validated(
                {"media": str(media_root), "root": DEFAULT_ROOT_PATH}
            )
        try:
            decoded = json.loads(raw)
        except ValueError as exc:
            raise ValueError(
                "MONITORING_DISK_PATHS must be a JSON object of target name to path"
            ) from exc
        if not isinstance(decoded, dict) or not decoded:
            raise ValueError("MONITORING_DISK_PATHS must be a non-empty JSON object")
        return MonitoringConfig._validated(
            {str(name): str(value) for name, value in decoded.items()}
        )

    @staticmethod
    def _validated(raw: Mapping[str, str]) -> tuple[tuple[str, Path], ...]:
        """Named, nonempty, absolute targets, in configured order."""
        targets: list[tuple[str, Path]] = []
        for name, value in raw.items():
            label = str(name).strip()
            if not label:
                raise ValueError("monitoring target names must not be empty")
            text = str(value).strip()
            if not text:
                raise ValueError(f"monitoring target {label!r} has no path")
            if not os.path.isabs(text):
                raise ValueError(
                    f"monitoring target {label!r} must be an absolute path"
                )
            targets.append((label, Path(text)))
        return tuple(targets)


class DiskSampler:
    """Reads free and total bytes for one configured target."""

    def __init__(self, *, usage: Callable[[Path], Any] = shutil.disk_usage) -> None:
        self._usage = usage

    def sample(self, target: str, path: Path, at: datetime) -> DiskSample:
        """One reading for ``target``.

        Raises ``ValueError`` when the filesystem reports no measurable
        capacity, and lets an unreadable path raise: the caller logs it and
        leaves incident state alone, because an unsampleable target is never
        evidence of recovery.
        """
        stats = self._usage(Path(path))
        total = int(stats.total)
        free = int(stats.free)
        if total <= 0:
            raise ValueError(
                f"disk target {target!r} reported no measurable capacity"
            )
        return DiskSample(
            target=target, free_bytes=free, total_bytes=total, sampled_at=at
        )


class MonitoringRunner:
    """Samples every configured target, then drives alert delivery.

    Sampling and delivery are independently fault-isolated: a mount that
    cannot be read, a rejected sample or a failing transport each leave the
    rest of the turn running and never propagate into job processing.
    """

    def __init__(
        self,
        config: MonitoringConfig,
        store: MonitoringStore,
        monitoring: DojoMonitoring,
        *,
        clock: Clock | None = None,
        sampler: DiskSampler | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._store = store
        self._monitoring = monitoring
        self._clock = clock if clock is not None else SystemClock()
        self._sampler = sampler if sampler is not None else DiskSampler()
        self._monotonic = monotonic
        #: target -> monotonic time its last sampling failure was logged. The
        #: runner owns this state because the collector is one long-lived
        #: object; the collector thread is the only writer.
        self._sample_failure_log: dict[str, float] = {}

    def tick(self) -> None:
        """One collection turn. Never raises."""
        for target, path in self._config.targets:
            self._sample(target, path)
        self._deliver()

    def run(self, stop: threading.Event) -> None:
        """Collect immediately, then on ``interval`` deadlines until ``stop``.

        Deadlines are monotonic and absolute, so a slow turn does not shift the
        schedule. A turn that overruns its deadline skips the turns it missed
        instead of running them back to back: a collector that was stuck for
        an hour must not spend the next hour catching up.
        """
        interval = self._config.interval_seconds
        deadline = self._monotonic()
        while not stop.is_set():
            self.tick()
            deadline += interval
            now = self._monotonic()
            if now >= deadline:
                missed = int((now - deadline) // interval) + 1
                deadline += missed * interval
                # The count is the diagnosis: one skipped turn is ordinary
                # jitter, a run of them means a turn is far too slow for the
                # configured interval. It rides in ``status`` as well as the
                # message because JsonFormatter never serializes message args,
                # so an argument-only count would be invisible in production.
                logger.warning(
                    "monitoring turn overran its interval; skipped %d turn(s)",
                    missed,
                    extra={"event": "monitoring.overrun", "status": f"skipped={missed}"},
                )
            if stop.wait(max(0.0, deadline - self._monotonic())):
                return

    def _sample(self, target: str, path: Path) -> None:
        try:
            sample = self._sampler.sample(target, path, self._clock.now())
        except Exception:  # noqa: BLE001 - one unreadable target is not the turn
            # A path that does not exist is a configuration fault — a typo, or
            # a missing bind mount the runbook tells operators to add — and it
            # is the one failure that means this filesystem is not covered at
            # all. It is therefore named in ``status`` separately from a
            # transient read error, which is only a missed sample.
            self._log_sample_failure(
                target,
                status=f"{target}:missing"
                if not path.exists()
                else f"{target}:unreadable",
                message="disk target does not exist or cannot be read; this "
                "filesystem is not being monitored",
            )
            return
        try:
            self._store.record_disk_sample(
                sample,
                low_percent=self._config.low_percent,
                recovery_percent=self._config.recovery_percent,
            )
        except Exception:  # noqa: BLE001 - a rejected sample opens nothing
            self._log_sample_failure(
                target,
                status=f"{target}:rejected",
                message="disk sample not recorded; incident state left unchanged",
            )
            return
        # The store owns incident state and does not report whether this sample
        # opened or closed an incident, so the runner logs the reading and
        # leaves the transition to the durable alert and its delivery result.
        # A target below the low threshold is logged at INFO; everything else
        # stays at DEBUG, so two targets a minute cannot bury a real event.
        free = sample.free_percent
        (logger.info if free < self._config.low_percent else logger.debug)(
            "disk sample recorded: %s free %.1f%%",
            target,
            free,
            extra={"event": "monitoring.disk_sample", "status": target},
        )
        # A target that samples again is healthy: clear its throttle so a later
        # failure is reported in full rather than being swallowed by the
        # interval its previous failure started.
        self._sample_failure_log.pop(target, None)

    def _log_sample_failure(self, target: str, *, status: str, message: str) -> None:
        """One record per target per interval, with the failure kind in ``status``.

        Incident state is left untouched either way: an unsampleable target is
        never evidence of recovery. What the log has to carry is *which kind* of
        failure it was, because "the path does not exist" is an operator action
        and "the read failed" is not — and ``status`` is the only field the JSON
        formatter keeps, since the message text is never serialized.
        """
        now = self._monotonic()
        last = self._sample_failure_log.get(target)
        self._sample_failure_log[target] = now
        if last is not None and now - last < SAMPLE_FAILURE_LOG_INTERVAL_SECONDS:
            return
        logger.warning(
            message,
            exc_info=True,
            extra={"event": "monitoring.disk_sample_failed", "status": status},
        )

    def _deliver(self) -> None:
        try:
            accepted = self._monitoring.deliver_pending()
        except Exception:  # noqa: BLE001 - durable state retries next turn
            logger.warning(
                "operational alert delivery failed; will retry",
                exc_info=True,
                extra={"event": "monitoring.delivery_failed", "status": "error"},
            )
            return
        if accepted:
            logger.info(
                "operational alerts accepted by the provider",
                extra={"event": "monitoring.delivery", "status": "accepted"},
            )
