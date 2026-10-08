from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import signal
import subprocess
import textwrap
import time
import uuid

import pytest


ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
V14_SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_parent_launcher_v14.py"
V15_SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_parent_launcher_v15.py"
V21_SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_external_supervisor_v21.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v21_real_process_group_waits_for_cooperative_child_beyond_old_two_seconds(tmp_path: Path):
    """The cleanup assertion uses the real v21 process-group helper.

    The child is a real subprocess with a SIGTERM handler and a three-second
    terminalization delay.  This catches the consumed v20 ``grace=2`` path;
    no launcher function is monkeypatched or bypassed.
    """
    module = _load("external_supervisor_v21_group_test", V21_SCRIPT)
    child_script = tmp_path / "cooperative-child.py"
    marker = tmp_path / "term.marker"
    ready = tmp_path / "ready.marker"
    child_script.write_text(textwrap.dedent(f"""
        import pathlib, signal, time
        marker = pathlib.Path({str(marker)!r})
        pathlib.Path({str(ready)!r}).write_text('READY')
        def stop(_signum, _frame):
            marker.write_text('SIGTERM')
            time.sleep(3.0)
            raise SystemExit(143)
        signal.signal(signal.SIGTERM, stop)
        while True:
            time.sleep(.05)
    """).lstrip())
    child = subprocess.Popen([str(PYTHON), "-B", str(child_script)],
                             start_new_session=True, text=True)
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and not ready.exists():
        time.sleep(.02)
    assert ready.is_file()
    started = time.monotonic()
    cleanup = module._stop_group(child, grace=module.V21_CHILD_CLEANUP_GRACE_SECONDS)
    elapsed = time.monotonic() - started
    assert cleanup["sigterm_sent"] is True
    assert cleanup["sigkill_sent"] is False
    assert cleanup["reaped"] is True
    assert marker.read_text() == "SIGTERM"
    assert elapsed >= 2.5
    assert cleanup["grace_seconds"] >= 20.0


def _write_terminal_ledger(tmp_path: Path, attempt: str) -> tuple[Path, Path]:
    ledger = tmp_path / "resource-ledger.json"
    receipt = tmp_path / "home-receipt.json"
    ledger.write_text(json.dumps({
        "limits": {"storage_policy": "home_free_floor", "home_path": str(tmp_path)},
        "reservations": [],
        "charges": [{"id": attempt, "status": "failed", "cpu_core_seconds": 0.2}],
        "attempts": [{"id": attempt, "status": "failed"}],
    }))
    receipt.write_text(json.dumps({"status": "FAILED_DEVELOPMENT_UNKNOWN", "attempt_id": attempt}))
    return ledger, receipt


def test_v14_real_launcher_signal_writes_terminal_fee_and_nested_trace(tmp_path: Path):
    """Run v14 itself with an actual strace/bridge chain and real accounting.

    Only the expensive scientific preflight is replaced by a fixture bridge
    binding.  The launcher, strace process group, signal handler, PDEATHSIG
    pre-exec hook, sidecar writer, and terminal fee predicate execute from the
    committed implementation.
    """
    module = _load("parent_launcher_v14_terminal_fee_test", V14_SCRIPT)
    adapter = _load("parent_launcher_v15_terminal_fee_test", V15_SCRIPT)
    bridge = tmp_path / "bridge.py"
    marker = tmp_path / "bridge.term"
    bridge_ready = tmp_path / "bridge.ready"
    trace = tmp_path / "os-open-trace.log"
    sidecar = tmp_path / "trace-finalization.json"
    attempt = "manufactured-v14-real-terminal-fee"
    ledger, receipt = _write_terminal_ledger(tmp_path, attempt)
    request = tmp_path / "request.json"
    harness = tmp_path / "harness.py"
    harness_ready = tmp_path / "harness.ready"
    bridge.write_text(textwrap.dedent(f"""
        import pathlib, signal, time
        marker = pathlib.Path({str(marker)!r})
        pathlib.Path({str(bridge_ready)!r}).write_text('READY')
        def stop(_signum, _frame):
            marker.write_text('SIGTERM')
            time.sleep(3.0)
            raise SystemExit(143)
        signal.signal(signal.SIGTERM, stop)
        while True:
            time.sleep(.05)
    """).lstrip())
    request_value = {
        "schema": module.SCHEMA, "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT", "qualification": dict(module.UNKNOWN),
        "model_invoked": False, "cfd_invoked": False,
        "attempt_id": attempt, "parent_boundary": {"max_wall_seconds": 30},
        "execution": {"python": str(PYTHON), "strace": "/usr/bin/strace",
                       "bridge": str(bridge), "cleanup_grace_seconds": 20.0},
        "trace": {"path": str(trace)},
        "storage_scope": {"external_filesystem": str(tmp_path),
                           "finalization_sidecar": str(sidecar)},
        "accounting": {"ledger_path": str(ledger), "attempt_id": attempt,
                        "home_receipt_path": str(receipt)},
        "source_bindings": [adapter._binding(V15_SCRIPT, adapter.WRAPPER_ROLE)],
    }
    request_value["sha256"] = module.canonical_sha(request_value)
    request.write_text(json.dumps(request_value))
    harness.write_text(textwrap.dedent(f"""
        import importlib.util, json, os, pathlib, sys
        spec = importlib.util.spec_from_file_location('bound_v15_harness', {str(V15_SCRIPT)!r})
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        module.V14._validate_launch = lambda request, verify_content: (
            dict(bridge_request=dict(path={str(bridge)!r})), None)
        module.V14.V13.V12._storage_preflight = lambda _v11: dict(fixture=True)
        pathlib.Path({str(harness_ready)!r}).write_text('READY')
        result = module.run({str(request)!r}, parent_pid=int(sys.argv[1]))
        pathlib.Path({str(tmp_path / 'report.json')!r}).write_text(json.dumps(result, sort_keys=True))
    """).lstrip())
    # The wrapper is a real parent process.  It exits immediately, so v14's
    # actual PDEATHSIG path must cancel its nested strace/bridge group.
    wrapper = tmp_path / "parent-wrapper.py"
    wrapper.write_text(textwrap.dedent(f"""
        import os, subprocess
        child = subprocess.Popen([{str(PYTHON)!r}, '-B', {str(harness)!r}, str(os.getpid())],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        import time
        deadline = time.time() + 5.0
        while time.time() < deadline and not __import__('pathlib').Path({str(bridge_ready)!r}).exists():
            time.sleep(.02)
    """).lstrip())
    parent = subprocess.run([str(PYTHON), "-B", str(wrapper)], timeout=5)
    assert parent.returncode == 0
    report_path = tmp_path / "report.json"
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline and not report_path.exists():
        time.sleep(.1)
    assert report_path.is_file()
    report = json.loads(report_path.read_text())
    assert report["status"] == "FAILED_PARENT_SUPERVISED_CANCELLED"
    assert report["cleanup"]["sigterm_sent"] is True
    assert report["cleanup"]["exited_after_cleanup"] is True
    assert report["cleanup"]["grace_seconds"] >= 20.0
    assert marker.read_text() == "SIGTERM"
    assert report["terminal_accounting"]["status"] == "PASS_TERMINAL_CHARGE_AND_LEASE_CLEANUP"
    assert report["trace_finalization_sidecar"]["schema"].endswith("v14")
    assert sidecar.is_file()
    assert trace.is_file()


@pytest.mark.skipif(not Path("/usr/bin/strace").is_file(), reason="strace is required")
def test_v21_request_requires_twenty_second_cleanup_grace():
    module = _load("external_supervisor_v21_grace_contract_test", V21_SCRIPT)
    assert module.V21_CHILD_CLEANUP_GRACE_SECONDS >= 20.0


def test_v27_adapter_and_supervisor_bind_real_v25_graph(tmp_path: Path):
    v15 = _load("parent_launcher_v15_graph_test", ROOT / "scripts" / "ds_data02_stage2_f2_parent_launcher_v15.py")
    v21 = _load("external_supervisor_v21_graph_test", V21_SCRIPT)
    v26_v14 = ROOT / (
        "campaigns/ds-data-02/stage2/native-reconstruction/"
        "raw-to-label-v26-supervised-chain/f2-s1-parent-supervised-launch-request-v14-013.json")
    if not v26_v14.is_file():
        pytest.skip("v26 metadata chain is not present in this isolated checkout")
    v15_path = tmp_path / "v15-adapter-request.json"
    v15_value = v15.build_request(v26_v14, v15_path)
    external = Path("/var/tmp/ds02-stage2/ds-data-02/families/F2/STAGE2_F2_S1_PORTABLE_RAW_TO_LABEL_V5")
    output_root = external / ("v27-test-" + uuid.uuid4().hex)
    v21_path = tmp_path / "v21-request.json"
    v21_value = v21.build_request(v15_path, v21_path, output_root=output_root,
                                  max_wall_seconds=6000.0)
    assert v15_value["execution"]["v15_accounting_adapter"] == str((ROOT / "scripts" / "ds_data02_stage2_f2_parent_launcher_v15.py").resolve())
    assert v21_value["execution"]["child_cleanup_grace_seconds"] >= 20.0
    assert any(item["role"] == "v15_accounting_adapter"
               for item in v21_value["static_bindings"])
    checked = v21._validate_request(v21_value, verify_content=True)
    assert checked["child_cleanup_grace_seconds"] == 25.0
