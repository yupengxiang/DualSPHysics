from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_portable_executor_parent_v3.py"
V34_REQUEST = ROOT / (
    "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v34-full-chain/"
    "f2-s1-portable-executor-request-v34-042.json")
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


parent = _load(SCRIPT, "parent_executor_v3_test")


def _bound(tmp_path: Path) -> dict:
    external = tmp_path / "nvme"
    home = tmp_path / "home"
    external.mkdir()
    home.mkdir()
    data_root = tmp_path / "data"
    (data_root / "runtime").mkdir(parents=True)
    ledger = data_root / "runtime" / "resource-ledger.json"
    ledger.write_text(json.dumps({
        "deadline_utc": "2099-01-01T00:00:00+00:00",
        "limits": {"storage_policy": "home_free_floor", "home_path": str(home),
                   "home_min_free_bytes": 0, "cpu_core_seconds": 1000},
        "charges": [], "reservations": [], "attempts": [],
    }) + "\n")
    request = {"storage_scope": {"external_min_free_bytes": 0},
               "execution": {"trace_path": str(external / "trace")}}
    return {
        "runtime_path": parent.RUNTIME_V6_DEFAULT,
        "runtime_sha": parent.sha256_file(parent.RUNTIME_V6_DEFAULT),
        "ledger": ledger, "external": external,
        "output_root": external / "attempt", "receipt": home / "receipt.json",
        "request": request,
        "executor": {"source_entries": [{"bytes": 8}], "fresh_roots": {}},
        "limits": json.loads(ledger.read_text())["limits"],
        "parent_attempt_id": "synthetic-parent-absent", "reservation_id": "synthetic::reservation",
        "charge_id": "synthetic::charge", "external_estimate": 100, "home_estimate": 20,
        "max_wall": 10.0, "allow_missing_parent": True,
    }


def test_dual_filesystem_v3_charge_and_release(tmp_path: Path) -> None:
    bound = _bound(tmp_path)
    parent._reserve(bound)
    (bound["external"] / "copied.bin").write_bytes(b"x" * 13)
    (tmp_path / "home" / "receipt.json").write_bytes(b"home")
    result = parent._charge(bound, status="failed", cpu_seconds=0.2,
                            external_bytes=13, home_bytes=4, trace_bytes=0,
                            copy_hash_bytes=8, allow_missing_parent=True)
    assert result["status"] == "PARENT_CHARGE_APPLIED"
    ledger = json.loads(bound["ledger"].read_text())
    assert not ledger["reservations"]
    assert ledger["charges"][-1]["storage_filesystems"] == [str(bound["external"]), str(tmp_path / "home")]


def test_child_command_preserves_literal_venv_path() -> None:
    executor = json.loads(V34_REQUEST.read_text())
    bound = {"executor": executor, "executor_script": ROOT / "scripts/ds_data02_stage2_f2_portable_executor_v34.py",
             "executor_path": V34_REQUEST, "max_wall": 1.0,
             "request": {"execution": {}}}
    command = parent._child_command(bound, os.getpid())
    assert command[0] == str(VENV)
    assert "/usr/bin/python3.10" not in command[0]


def test_child_command_uses_filtered_file_process_trace(tmp_path: Path) -> None:
    executor = json.loads(V34_REQUEST.read_text())
    trace = tmp_path / "os-trace"
    bound = {"executor": executor, "executor_script": ROOT / "scripts/ds_data02_stage2_f2_portable_executor_v34.py",
             "executor_path": V34_REQUEST, "max_wall": 1.0,
             "request": {"execution": {"strace": {"path": "/usr/bin/strace"},
                                          "trace_path": str(trace)}}}
    command = parent._child_command(bound, os.getpid())
    assert command[:2] == ["/usr/bin/strace", "-ff"]
    assert command[2:7] == ["-e", "trace=%file,%process", "-s", "4096", "-o"]
    assert command[7] == str(trace)
    assert command[9] == str(VENV)


def test_open_observation_does_not_turn_failed_child_into_false() -> None:
    assert parent._open_observation(child_launched=False, trace_bytes=0)["hdf5_opened"] == "NOT_STARTED"
    observed = parent._open_observation(child_launched=True, trace_bytes=19)
    assert observed["raw_opened"] == "MAY_HAVE_OPENED"
    assert observed["hdf5_opened"] == "MAY_HAVE_OPENED"
    assert observed["dataset_specific_open_proven"] is False


def test_stop_group_reaps_nested_helper_after_leader_exits(tmp_path: Path) -> None:
    marker = tmp_path / "term.marker"
    child_code = (
        "import pathlib,signal,time; "
        f"p=pathlib.Path({str(marker)!r}); "
        "signal.signal(signal.SIGTERM,lambda *_: p.write_text('term')); time.sleep(30)"
    )
    leader_code = (
        "import subprocess,sys,os,time; "
        f"subprocess.Popen([sys.executable,'-c',{child_code!r}]); time.sleep(.2); os._exit(0)"
    )
    proc = subprocess.Popen([sys.executable, "-c", leader_code], start_new_session=True)
    proc.wait(timeout=2)
    result = parent._stop_group(proc, grace=1.0)
    assert result["sigterm_sent"] is True
    assert result["group_gone"] is True
    assert marker.read_text() == "term"


def test_actual_owned_popen_uses_parent_death_and_single_thread_env(tmp_path: Path) -> None:
    marker = tmp_path / "env.marker"
    child_code = (
        "import os,pathlib,signal,time; "
        f"p=pathlib.Path({str(marker)!r}); "
        "p.write_text('|'.join(os.environ.get(k,'') for k in "
        "['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'])); "
        "signal.signal(signal.SIGTERM,lambda *_: None); time.sleep(30)"
    )
    wrapper_pid = os.getpid()
    env = os.environ.copy()
    env.update(parent.THREAD_ENV)
    proc = subprocess.Popen([sys.executable, "-c", child_code], start_new_session=True,
                            preexec_fn=lambda pid=wrapper_pid: parent._pdeath(pid), env=env)
    deadline = time.monotonic() + 2.0
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert marker.read_text() == "1|1|1|1"
    result = parent._stop_group(proc, grace=0.2)
    assert result["sigterm_sent"] is True
    assert result["group_gone"] is True


def test_full_report_home_size_fixed_point() -> None:
    report = {"schema": parent.REPORT_SCHEMA,
              "filesystem": {"home_receipt_bytes": None, "external_bytes": 13},
              "nested": {"message": "full object"}}
    predicted = parent._report_size_fixed_point(report)
    encoded = (json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
    assert predicted == len(encoded)
    assert report["filesystem"]["home_receipt_bytes"] == predicted
