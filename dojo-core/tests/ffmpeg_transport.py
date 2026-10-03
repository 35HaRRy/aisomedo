"""Run production FFmpeg subprocess commands via Docker when binaries are absent."""
from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

import docker
from dojo.testing import FFMPEG_IMAGE


def docker_available() -> bool:
    try:
        client = docker.from_env()
        try:
            client.ping()
        finally:
            client.close()
        return True
    except Exception:
        return False


class FfmpegTransport:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.client = docker.from_env()

    def close(self):
        self.client.close()

    def run(self, args: list[str], *, capture_output=True, text=True):
        def translate(value: str) -> str:
            return value.replace(str(self.root), "/work").replace(
                self.root.as_posix(), "/work"
            ).replace("\\", "/")

        command = [translate(str(arg)) for arg in args]
        binary_output = None
        if not text and args[-1] == "pipe:1":
            # Docker's log driver repairs invalid UTF-8, corrupting raw RGB/PCM.
            # Capture binary subprocess stdout through the mounted filesystem.
            binary_output = self.root / f"stdout-{uuid.uuid4().hex}.bin"
            command[-1] = translate(str(binary_output))
        if "concat" in args:
            index = args.index("-i") + 1
            listing = Path(args[index])
            mounted = listing.with_suffix(".docker.txt")
            mounted.write_text(translate(listing.read_text(encoding="utf-8")), encoding="utf-8")
            command[index] = translate(str(mounted))
        container = self.client.containers.run(
            FFMPEG_IMAGE, command=command[1:], entrypoint=command[0], detach=True,
            volumes={str(self.root): {"bind": "/work", "mode": "rw"}},
        )
        try:
            code = container.wait(timeout=120)["StatusCode"]
            stdout = container.logs(stdout=True, stderr=False)
            stderr = container.logs(stdout=False, stderr=True)
        finally:
            container.remove()
        if binary_output is not None and binary_output.exists():
            stdout = binary_output.read_bytes()
            binary_output.unlink()
        return subprocess.CompletedProcess(
            args, code, stdout.decode() if text else stdout, stderr.decode() if text else stderr,
        )
