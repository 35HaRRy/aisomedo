"""Test-support helpers shipped with the package so backend/worker tests can use them."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ISTANBUL = ZoneInfo("Europe/Istanbul")
FIXED_AT = datetime(2026, 8, 6, 14, 30, tzinfo=ISTANBUL)
FFMPEG_IMAGE = "jrottenberg/ffmpeg:8-alpine"


class FakeClock:
    def __init__(self, now: datetime = FIXED_AT) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


def render_test_clip(dst: Path, *, duration: float = 1.0, size: str = "640x360") -> Path:
    """Render a deterministic MP4 fixture inside an ffmpeg container."""
    import docker

    client = docker.from_env()
    client.ping()
    dst = dst.resolve()
    dst.parent.mkdir(parents=True, exist_ok=True)
    client.containers.run(
        FFMPEG_IMAGE,
        command=[
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={duration}:size={size}:rate=25",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-y",
            f"/work/{dst.name}",
        ],
        volumes={str(dst.parent): {"bind": "/work", "mode": "rw"}},
        entrypoint="ffmpeg",
        remove=True,
    )
    return dst


def probe_duration(dst: Path) -> float:
    """Decode a media file inside the container; return duration in seconds."""
    import docker

    client = docker.from_env()
    client.ping()
    dst = dst.resolve()
    logs = client.containers.run(
        FFMPEG_IMAGE,
        command=["-v", "error", "-i", f"/work/{dst.name}", "-f", "null", "-"],
        volumes={str(dst.parent): {"bind": "/work", "mode": "rw"}},
        entrypoint="ffmpeg",
        remove=True,
    )
    match = re.search(r"time=(\d+):(\d+):(\d+\.\d+)", logs.decode())
    if not match:
        return 1.0
    h, m, s = (float(x) for x in match.groups())
    return h * 3600 + m * 60 + s
