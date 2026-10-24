import importlib
import subprocess
import sys

import pytest
from dojo.exceptions import RenderFailed


def capture_children(monkeypatch, module, *, stubborn=False):
    children = []
    popen = subprocess.Popen

    def start(*args, **kwargs):
        child = popen(*args, **kwargs)
        if stubborn:
            child.terminate = lambda: None
        children.append(child)
        return child

    monkeypatch.setattr(module.subprocess, "Popen", start)
    monkeypatch.setattr(module, "POLL_SECONDS", 0.01)
    monkeypatch.setattr(module, "TERMINATE_GRACE_SECONDS", 0.02)
    return children


@pytest.mark.parametrize("stubborn", [False, True])
def test_cancellation_terminates_and_reaps_the_real_child(tmp_path, monkeypatch, stubborn):
    module = importlib.import_module("dojo.adapters.preview_process")
    children = capture_children(monkeypatch, module, stubborn=stubborn)
    marker = tmp_path / "started"
    script = f"from pathlib import Path; Path({str(marker)!r}).touch(); import time; time.sleep(60)"
    with pytest.raises(module.PreviewCancelled):
        module.run_preview_process([sys.executable, "-c", script], cancelled=marker.exists)
    assert marker.is_file()
    assert len(children) == 1 and children[0].poll() is not None


def test_large_stderr_does_not_block_successful_probe(monkeypatch):
    module = importlib.import_module("dojo.adapters.preview_process")
    children = capture_children(monkeypatch, module)
    result = module.run_preview_process([
        sys.executable, "-c", "import sys; sys.stderr.write('x'*1048576); print('probe-result')",
    ], cancelled=lambda: False)
    assert result.strip() == "probe-result"
    assert children[0].returncode == 0


def test_deadline_kills_and_reaps_the_real_child(monkeypatch):
    module = importlib.import_module("dojo.adapters.preview_process")
    children = capture_children(monkeypatch, module)
    with pytest.raises(RenderFailed, match="deadline"):
        module.run_preview_process([sys.executable, "-c", "import time; time.sleep(60)"],
                                   cancelled=lambda: False, timeout_seconds=0.05)
    assert len(children) == 1 and children[0].poll() is not None


def test_failed_control_check_stops_the_child(tmp_path, monkeypatch):
    module = importlib.import_module("dojo.adapters.preview_process")
    children = capture_children(monkeypatch, module)
    marker = tmp_path / "started"

    def check():
        if marker.exists():
            raise RuntimeError("control database unavailable")
        return False

    script = f"from pathlib import Path; Path({str(marker)!r}).touch(); import time; time.sleep(60)"
    with pytest.raises(RuntimeError, match="control database"):
        module.run_preview_process([sys.executable, "-c", script], cancelled=check)
    assert len(children) == 1 and children[0].poll() is not None


def test_failed_encoder_reports_a_bounded_error(monkeypatch):
    module = importlib.import_module("dojo.adapters.preview_process")
    capture_children(monkeypatch, module)
    with pytest.raises(RenderFailed) as rejected:
        module.run_preview_process([
            sys.executable, "-c", "import sys; sys.stderr.write('x'*1048576); sys.exit(7)",
        ], cancelled=lambda: False)
    assert len(str(rejected.value)) < 2000


def test_already_cancelled_work_never_launches_a_child(tmp_path):
    module = importlib.import_module("dojo.adapters.preview_process")
    marker = tmp_path / "must-not-start"
    with pytest.raises(module.PreviewCancelled):
        module.run_preview_process([
            sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()",
        ], cancelled=lambda: True)
    assert not marker.exists()
