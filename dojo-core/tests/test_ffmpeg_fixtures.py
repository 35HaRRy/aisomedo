from __future__ import annotations

from pathlib import Path

import pytest
from dojo.testing import probe_duration, render_test_clip


def _docker_available() -> bool:
    try:
        import docker

        docker.from_env().ping()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _docker_available(), reason="docker unavailable")
def test_ffmpeg_container_renders_deterministic_clip(tmp_path: Path) -> None:
    clip = render_test_clip(tmp_path / "fixture.mp4")

    assert clip.exists()
    assert clip.stat().st_size > 0
    assert abs(probe_duration(clip) - 1.0) < 0.05
