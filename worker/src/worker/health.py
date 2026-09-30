from __future__ import annotations

import json
import math
import os
import sys
import tempfile
from pathlib import Path
from time import monotonic

from dojo.worker_health import HEALTH_VERSION, current_boot_id, read_worker_status

DEFAULT_PATH = Path("/tmp/dojo-worker-health.json")

def _validate_timeout(value: float, name: str) -> float:
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError(f"{name} must be a finite positive number of seconds")
    return seconds


class WorkerHealth:
    """Container-local worker progress record with idle/busy deadlines.

    ``idle()`` renews a short deadline each loop turn; ``busy()`` fixes a
    long deadline when work starts and never renews it while the tick is
    blocked, so a stuck render eventually fails the probe. Writes go
    through a same-directory temporary file plus atomic replacement.
    """

    def __init__(
        self,
        path: Path,
        *,
        idle_seconds: float = 120,
        busy_seconds: float = 3600,
    ) -> None:
        self._path = Path(path)
        self._idle_seconds = _validate_timeout(idle_seconds, "idle_seconds")
        self._busy_seconds = _validate_timeout(busy_seconds, "busy_seconds")

    def idle(self) -> None:
        self._write("idle", monotonic() + self._idle_seconds)

    def busy(self) -> None:
        existing = self._read_record()
        if (
            existing is not None
            and existing.get("phase") == "busy"
            and existing.get("boot_id") == current_boot_id()
        ):
            return
        self._write("busy", monotonic() + self._busy_seconds)

    def stopped(self) -> None:
        self._write("stopped", monotonic())

    def _write(self, phase: str, deadline: float) -> None:
        now = monotonic()
        record = {
            "version": HEALTH_VERSION,
            "phase": phase,
            "boot_id": current_boot_id(),
            "monotonic": now,
            "deadline": deadline,
        }
        payload = json.dumps(record).encode("utf-8")
        directory = self._path.parent
        directory.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(directory), prefix=self._path.name + ".", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "wb") as tmp:
                tmp.write(payload)
            os.replace(tmp_name, self._path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def _read_record(self) -> dict | None:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except OSError:
            return None
        try:
            record = json.loads(raw)
        except ValueError:
            return None
        return record if isinstance(record, dict) else None


def check_health(path: Path) -> bool:
    """True only for a fresh same-boot idle/busy record before its deadline."""
    return read_worker_status(path).status == "healthy"


def main(argv: list[str] | None = None) -> int:
    args = (sys.argv if argv is None else argv)[1:]
    if args:
        path = Path(args[0])
    else:
        path = Path(os.environ.get("WORKER_HEALTH_PATH", str(DEFAULT_PATH)))
    return 0 if check_health(path) else 1


if __name__ == "__main__":
    sys.exit(main())
