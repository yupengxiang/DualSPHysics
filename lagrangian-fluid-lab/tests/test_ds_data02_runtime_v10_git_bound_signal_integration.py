from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import time
import importlib.util


ROOT = Path(__file__).resolve().parents[1]
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
HELPER_TEST = ROOT / "tests/test_ds_data02_runtime_v10_git_bound.py"


def _helpers():
    spec = importlib.util.spec_from_file_location("v10_signal_helpers", HELPER_TEST)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_git(path: Path) -> None:
    path.write_text(
        "#!" + str(VENV) + "\n"
        "import os, signal, sys, time\n"
        "from pathlib import Path\n"
        "marker = Path(os.environ['DS02_FAKE_GIT_MARKER'])\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "    Path(str(marker) + '.child').write_text(str(os.getpid()))\n"
        "    while True: time.sleep(1)\n"
        "marker.write_text(str(os.getpid()))\n"
        "mode = os.environ.get('DS02_FAKE_GIT_MODE', 'wait')\n"
        "if mode == 'wait':\n"
        "    os.close(1); os.close(2)\n"
        "    while True: time.sleep(1)\n"
        "while True:\n"
        "    os.write(2, b'x' * 65536)\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _live_group_members(pgid: int) -> list[int]:
    members: list[int] = []
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return members
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            # stat fields after comm: state is [0], pgrp is [2].
            if len(fields) >= 3 and int(fields[2]) == pgid and fields[0] != "Z":
                members.append(int(entry.name))
        except (FileNotFoundError, PermissionError, ValueError, OSError):
            continue
    return members


def _run_cancelled(mode: str) -> tuple[dict, dict, dict, str, str]:
    helpers = _helpers()
    with __import__("tempfile").TemporaryDirectory(prefix="ds02-v10-signal-") as directory:
        tmp = Path(directory)
        repo, wrapper, scripts = helpers._make_runtime_repo(tmp)
        fake = repo / "fake-git-signal.py"
        _fake_git(fake)
        scripts.append(fake)
        data_root = tmp / "data"
        helpers._ledger(data_root)
        request_path = helpers._request(repo, scripts, data_root, "signal-" + mode)
        request = json.loads(request_path.read_text(encoding="utf-8"))
        request["git_snapshot_test_only"] = True
        request["git_snapshot_executable"] = str(fake)
        request["git_snapshot_timeout_seconds"] = 10.0
        request["max_wall_seconds"] = 15
        request_path.write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
        marker = tmp / (mode + ".marker")
        environment = dict(os.environ)
        environment["DS02_FAKE_GIT_MARKER"] = str(marker)
        environment["DS02_FAKE_GIT_MODE"] = mode
        process = subprocess.Popen(
            [str(VENV), "-B", "-I", str(wrapper), "run", "--request", str(request_path),
             "--data-root", str(data_root)],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment,
        )
        deadline = time.monotonic() + 8.0
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.is_file(), "fake Git did not enter its owned child stage"
        leader_pid = int(marker.read_text(encoding="utf-8"))
        child_marker = Path(str(marker) + ".child")
        child_deadline = time.monotonic() + 2.0
        while not child_marker.exists() and time.monotonic() < child_deadline:
            time.sleep(0.01)
        assert child_marker.is_file(), "fake Git descendant was not created"
        child_pid = int(child_marker.read_text(encoding="utf-8"))
        # The marker is written before the wait/drain boundary.  Give the
        # wrapper one scheduling turn to enter V3's process.wait or selector
        # drain, then deliver the real runtime SIGTERM.
        time.sleep(0.12)
        os.kill(process.pid, signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=8.0)
        assert process.returncode != 0, stdout + stderr
        receipt_path = (data_root / "families" / "infra" / "runtime-v10-git-bound" /
                        ("signal-" + mode) / "execution-receipt.json")
        assert receipt_path.is_file(), stdout + stderr
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        ledger = json.loads((data_root / "runtime/resource-ledger.json").read_text())
        # The process group may take a short procfs turn to disappear after
        # SIGKILL; wait boundedly and inspect live members, not a receipt flag.
        cleanup_deadline = time.monotonic() + 2.0
        members = _live_group_members(leader_pid)
        while members and time.monotonic() < cleanup_deadline:
            time.sleep(0.02)
            members = _live_group_members(leader_pid)
        return receipt, ledger, {"leader_pid": leader_pid, "child_pid": child_pid,
                                "live_members": members}, stdout, stderr


def _assert_cancelled(mode: str) -> None:
    receipt, ledger, members, stdout, stderr = _run_cancelled(mode)
    assert receipt["status"] == "failed", stdout + stderr
    assert receipt["deadline"]["status"] == "CANCELLED", receipt
    assert receipt["returncode"] is None, receipt
    assert ledger["reservations"] == []
    charges = [row for row in ledger["charges"] if row["id"].endswith("signal-" + mode)]
    assert len(charges) == 1
    assert charges[0]["status"] == "failed"
    attempt = Path(receipt["output_root"])
    assert not (attempt / "child.txt").exists(), "scientific worker ran after cancellation"
    assert members["live_members"] == [], members


def test_real_v10_sigterm_during_process_wait_closes_group_and_fee() -> None:
    _assert_cancelled("wait")


def test_real_v10_sigterm_during_pipe_drain_closes_group_and_fee() -> None:
    _assert_cancelled("drain")
