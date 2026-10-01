"""Shared read-only worker progress probe; independent of worker execution."""

import json
import math
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Literal

HEALTH_VERSION = 1
_BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")


def current_boot_id() -> str:
    try:
        boot_id = _BOOT_ID_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        boot_id = ""
    if boot_id:
        return boot_id
    import socket
    import uuid

    return f"fallback-{socket.gethostname()}-{uuid.getnode():x}"


@dataclass(frozen=True)
class WorkerStatus:
    status: Literal["healthy", "unhealthy", "unknown"]
    phase: Literal["idle", "busy", "stopped"] | None = None


def read_worker_status(path: Path | None) -> WorkerStatus:
    if path is None:
        return WorkerStatus("unknown")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return WorkerStatus("unknown")
    except (OSError, ValueError):
        return WorkerStatus("unhealthy")
    if not isinstance(record, dict):
        return WorkerStatus("unhealthy")
    phase = record.get("phase")
    if phase not in ("idle", "busy", "stopped"):
        return WorkerStatus("unhealthy")
    unhealthy = WorkerStatus("unhealthy", phase)
    if (record.get("version") != HEALTH_VERSION or phase == "stopped"
            or record.get("boot_id") != current_boot_id()):
        return unhealthy
    written, deadline = record.get("monotonic"), record.get("deadline")
    if (not isinstance(written, (int, float)) or isinstance(written, bool)
            or not isinstance(deadline, (int, float)) or isinstance(deadline, bool)
            or not math.isfinite(written) or not math.isfinite(deadline)):
        return unhealthy
    return WorkerStatus("healthy", phase) if written <= monotonic() < deadline else unhealthy
