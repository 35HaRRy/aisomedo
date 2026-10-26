"""Cancellable owned subprocesses for private media preview generation."""

from __future__ import annotations

import subprocess
import tempfile
import time
from collections.abc import Callable

from dojo.exceptions import RenderFailed

POLL_SECONDS = 0.25
TERMINATE_GRACE_SECONDS = 2.0


class PreviewCancelled(Exception):
    """A superseded generation is not an encoding failure."""


def run_preview_process(
    args: list[str], *, cancelled: Callable[[], bool], timeout_seconds: float = 900.0,
) -> str:
    if cancelled():
        raise PreviewCancelled()
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(args, stdout=stdout, stderr=stderr)
        deadline = time.monotonic() + timeout_seconds
        try:
            while process.poll() is None:
                if cancelled():
                    raise PreviewCancelled()
                if time.monotonic() >= deadline:
                    raise RenderFailed("preview encoding deadline exceeded")
                time.sleep(POLL_SECONDS)
            if cancelled():
                raise PreviewCancelled()
            if process.returncode:
                stderr.seek(0, 2)
                stderr.seek(max(0, stderr.tell() - 1024))
                reason = stderr.read().decode("utf-8", errors="replace").strip()
                raise RenderFailed(f"preview encoding failed: {reason}")
            stdout.seek(0)
            return stdout.read().decode("utf-8", errors="replace")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=TERMINATE_GRACE_SECONDS)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
