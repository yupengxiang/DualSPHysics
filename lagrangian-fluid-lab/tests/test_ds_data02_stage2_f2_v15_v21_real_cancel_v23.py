from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import os
import subprocess
import textwrap
import time


ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
V10_TEST = ROOT / "tests/test_ds_data02_stage2_f2_v10_real_cancel_v22.py"
V14 = ROOT / "scripts/ds_data02_stage2_f2_parent_launcher_v14.py"
V15 = ROOT / "scripts/ds_data02_stage2_f2_parent_launcher_v15.py"
V21 = ROOT / "scripts/ds_data02_stage2_f2_external_supervisor_v21.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_real_v15_v14_v10_chain_cancels_and_closes_new_ledger_attempt(tmp_path: Path):
    """Run the real v15→v14→strace→v10 path with no prewritten terminal row.

    The only fixture substitution is v14's expensive scientific closure
    validator and storage preflight.  The bridge is the committed v10 code:
    it creates the reservation, receives SIGTERM, writes the receipt/hash and
    applies the actual CPU/storage charge.  v15's adapter and v14's 20-second
    cleanup then observe that terminal state through the real v12 predicate.
    """
    base = _load("v10_fixture_helpers_v23", V10_TEST)
    adapter = _load("v15_chain_v23", V15)
    supervisor = _load("v21_group_v23", V21)
    request_path, attempt, marker = base._make_request(tmp_path)
    v10_request = json.loads(request_path.read_text())
    external = Path(v10_request["external_storage_scope"]["filesystem"])
    ledger = Path(v10_request["parent_resource_binding"]["path"])
    # v10's immutable receipt namespace is part of its real accounting
    # contract; the v14 predicate must bind that exact path rather than the
    # fixture's illustrative external-scope value.
    receipt = (Path(v10_request["data_root"]) / "families/F2/F2_S1_PORTABLE_RAW_TO_LABEL_V10"
               / attempt / "execution-receipt.json")
    v14_request = tmp_path / "v14-chain-request.json"
    v14_value = {
        "schema": "ds02.stage2.f2-parent-supervised-launch.v14",
        "status": "READY_FOR_PARENT_GUARD", "role": "DEVELOPMENT",
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "model_invoked": False, "cfd_invoked": False,
        "attempt_id": attempt,
        "parent_boundary": {"max_wall_seconds": 30, "parent_pid_required": True},
        "execution": {"python": str(PYTHON), "strace": "/usr/bin/strace",
                       "bridge": str(base.V10_PATH), "cleanup_grace_seconds": 20.0},
        "trace": {"path": str(external / "os-open-trace-v14-real.log")},
        "storage_scope": {"external_filesystem": str(external),
                           "finalization_sidecar": str(external / "v14-real-finalization.json")},
        "accounting": {"ledger_path": str(ledger), "attempt_id": attempt,
                        "home_receipt_path": str(receipt)},
        "source_bindings": [adapter._binding(V15, adapter.WRAPPER_ROLE)],
    }
    v14_value["sha256"] = adapter.canonical_sha(v14_value)
    v14_request.write_text(json.dumps(v14_value, indent=2, sort_keys=True) + "\n")
    harness = tmp_path / "v15-chain-harness.py"
    harness_ready = tmp_path / "v15-chain-ready.marker"
    harness.write_text(textwrap.dedent(f"""
        import importlib.util, json, os, pathlib, sys
        spec = importlib.util.spec_from_file_location('bound_v15_v23', {str(V15)!r})
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        # Only the scientific closure is fixture-bound.  v14 child launch,
        # strace, v10 reservation/charge, and v12 terminal predicate are real.
        module.V14._validate_launch = lambda request, verify_content: (
            dict(bridge_request={{'path': {str(request_path)!r}}}), None)
        module.V14.V13.V12._storage_preflight = lambda _v11: dict(fixture=True)
        pathlib.Path({str(harness_ready)!r}).write_text('READY')
        result = module.run({str(v14_request)!r}, parent_pid=int(sys.argv[1]))
        pathlib.Path({str(tmp_path / 'v15-report.json')!r}).write_text(json.dumps(result, sort_keys=True))
    """).lstrip())
    parent_wrapper = tmp_path / "v15-parent-wrapper.py"
    parent_wrapper.write_text(textwrap.dedent(f"""
        import os, pathlib, subprocess, time
        import signal
        subprocess.Popen([{str(PYTHON)!r}, '-B', {str(harness)!r}, str(os.getpid())],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def stop(_signum, _frame):
            # The child v15/v14/V10 chain receives SIGTERM concurrently and
            # settles its real receipt.  Keep this parent group alive for
            # three seconds so the old two-second cleanup cannot pass.
            time.sleep(3.0)
            raise SystemExit(143)
        signal.signal(signal.SIGTERM, stop)
        deadline = time.time() + 10
        while time.time() < deadline and not pathlib.Path({str(marker)!r}).exists():
            time.sleep(.02)
        while True:
            time.sleep(.05)
    """).lstrip())
    parent = subprocess.Popen([str(PYTHON), "-B", str(parent_wrapper)], start_new_session=True,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and not marker.exists():
        time.sleep(.02)
    assert marker.is_file()
    started = time.monotonic()
    cleanup = supervisor._stop_group(parent, grace=supervisor.V21_CHILD_CLEANUP_GRACE_SECONDS)
    elapsed = time.monotonic() - started
    assert cleanup["sigterm_sent"] is True
    assert cleanup["sigkill_sent"] is False
    assert cleanup["reaped"] is True
    assert cleanup["grace_seconds"] >= 25.0
    assert elapsed >= 2.5
    report_path = tmp_path / "v15-report.json"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not report_path.exists():
        time.sleep(.1)
    assert report_path.is_file()
    report = json.loads(report_path.read_text())
    assert report["status"] == "FAILED_PARENT_SUPERVISED_CANCELLED"
    assert report["cleanup"]["sigterm_sent"] is True
    assert report["cleanup"]["exited_after_cleanup"] is True
    assert report["cleanup"]["grace_seconds"] >= 20.0
    assert report["terminal_accounting"]["status"] == "PASS_TERMINAL_CHARGE_AND_LEASE_CLEANUP"
    assert report["trace_finalization_sidecar"]
    ledger_value = json.loads(ledger.read_text())
    charge = [row for row in ledger_value["charges"] if row.get("id") == attempt]
    assert len(charge) == 1 and charge[0]["status"] == "failed"
    assert charge[0]["cpu_core_seconds"] > 0.0 and charge[0]["new_storage_bytes"] > 0
    assert not any(row.get("id") == attempt for row in ledger_value["reservations"])
    assert receipt.is_file()
    receipt_value = json.loads(receipt.read_text())
    assert receipt_value["parent_ledger"]["reservation_registered"] is True
    assert receipt_value["deadline"]["status"] == "CANCELLED"
    assert receipt_value["filesystem"]["measured_total_bytes"] > 0
