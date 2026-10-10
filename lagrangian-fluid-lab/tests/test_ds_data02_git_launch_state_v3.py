from __future__ import annotations

import importlib.util
from pathlib import Path
import os
import sys
import textwrap
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_git_launch_state_v3.py"
SPEC = importlib.util.spec_from_file_location("ds_data02_git_launch_state_v3_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.path.insert(0, str(SCRIPT.parent))
SPEC.loader.exec_module(MODULE)


def _fake_git(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "fake-git.py"
    path.write_text("#!/usr/bin/env python3\n" + textwrap.dedent(body))
    path.chmod(0o755)
    return path


def test_v3_stderr_flood_is_deadline_bounded(tmp_path: Path) -> None:
    fake = _fake_git(tmp_path, "import os\nwhile True:\n os.write(2, b'x' * 65536)\n")
    started = time.monotonic()
    report = MODULE.bounded_git_launch_state(tmp_path, timeout_seconds=0.08,
                                             max_output_bytes=1024,
                                             git_executable=fake)
    assert time.monotonic() - started < 1.0
    assert report["schema"] == "ds02.stage2.git-launch-state.v3"
    assert report["status"] == "TIMEOUT"
    assert report["commit"] is None
    assert report["cleanup"] and report["cleanup"][-1]["group_alive_after_cleanup"] is False


def test_v3_leader_exit_does_not_leave_descendant_pipe_holder(tmp_path: Path) -> None:
    pid_file = tmp_path / "child.pid"
    fake = _fake_git(tmp_path, f"""
        import os, signal, time
        child = os.fork()
        if child == 0:
            open({str(pid_file)!r}, 'w').write(str(os.getpid()))
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            while True:
                time.sleep(1)
        os._exit(0)
    """)
    report = MODULE.bounded_git_launch_state(tmp_path, timeout_seconds=0.12,
                                             git_executable=fake)
    assert report["status"] == "TIMEOUT"
    assert report["cleanup"]
    assert report["cleanup"][-1]["group_alive_after_cleanup"] is False
    deadline = time.monotonic() + 1.0
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    if pid_file.exists():
        child_pid = int(pid_file.read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)


def test_v3_rejects_non_hex_head_without_claiming_clean(tmp_path: Path) -> None:
    fake = _fake_git(tmp_path, "print('not-a-revision')\n")
    report = MODULE.bounded_git_launch_state(tmp_path, timeout_seconds=1,
                                             git_executable=fake)
    assert report["status"] == "ERROR"
    assert report["commit"] is None
    assert report["status_porcelain"] is None

