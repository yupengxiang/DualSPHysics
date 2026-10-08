from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import textwrap
import uuid


ROOT = Path(__file__).resolve().parents[2]
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
V13_REQUEST = ROOT / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/"
    "raw-to-label-v19-consistent/f2-s1-parent-supervised-launch-request-v13-007.json"
)
V14_SCRIPT = ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_f2_parent_launcher_v14.py"
V20_SCRIPT = ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_f2_external_supervisor_v20.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v14_builds_and_v20_binds_actual_forward_request(tmp_path: Path) -> None:
    v14 = _load("f2_parent_v14_build_test", V14_SCRIPT)
    v20 = _load("f2_supervisor_v20_build_test", V20_SCRIPT)
    v14_request = tmp_path / "v14-request.json"
    v20_request = tmp_path / "v20-request.json"
    v14_value = v14.build_request(V13_REQUEST, v14_request)
    assert v14_value["schema"] == "ds02.stage2.f2-parent-supervised-launch.v14"
    assert v14_value["execution"]["cleanup_grace_seconds"] >= 20.0
    assert any(item["role"] == "parent_launcher_v14" for item in v14_value["source_bindings"])
    external = Path(v14_value["storage_scope"]["external_filesystem"])
    output_root = external / ("f2-s1-v14-test-" + uuid.uuid4().hex)
    v20_value = v20.build_request(v14_request, v20_request, output_root=output_root)
    assert v20_value["schema"] == "ds02.stage2.f2-external-supervisor-request.v20"
    assert v20_value["execution"]["v14_cli"][2] == str(V14_SCRIPT)
    checked = v20._validate_request(v20_value, verify_content=False)
    assert checked["v14_path"] == v14_request.resolve()
    assert checked["v20_request"] == output_root / "v20-supplemental-request.json"


def test_v14_real_strace_group_cancellation_reaps_stub_bridge(tmp_path: Path) -> None:
    """Exercise v14 itself with strace and a signal-aware bridge stub.

    The stub is only the bridge payload.  The launcher, strace process group,
    PDEATHSIG pre-exec hook, signal handler, bounded group cleanup, trace, and
    sidecar are all real subprocess behavior.  No HDF5/BI4 is opened.
    """
    v14 = _load("f2_parent_v14_cancel_test", V14_SCRIPT)
    bridge = tmp_path / "stub-bridge.py"
    marker = tmp_path / "bridge-term.txt"
    trace = tmp_path / "os-open-trace.log"
    sidecar = tmp_path / "trace-finalization.json"
    request = tmp_path / "request.json"
    harness = tmp_path / "harness.py"
    bridge.write_text(textwrap.dedent(
        f"""
        import pathlib, signal, time
        marker = pathlib.Path({str(marker)!r})
        def stop(_signum, _frame):
            marker.write_text('SIGTERM')
            time.sleep(0.15)
            raise SystemExit(143)
        signal.signal(signal.SIGTERM, stop)
        while True:
            time.sleep(0.05)
        """,
    ).lstrip())
    value = {
        "schema": v14.SCHEMA,
        "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT",
        "qualification": dict(v14.UNKNOWN),
        "model_invoked": False,
        "cfd_invoked": False,
        "attempt_id": "manufactured-v14-cancel",
        "parent_boundary": {"max_wall_seconds": 30},
        "execution": {
            "python": str(PYTHON), "strace": "/usr/bin/strace",
            "bridge": str(bridge), "cleanup_grace_seconds": 20.0,
        },
        "trace": {"path": str(trace)},
        "storage_scope": {"external_filesystem": str(tmp_path),
                           "finalization_sidecar": str(sidecar)},
        "accounting": {"ledger_path": str(tmp_path / "ledger.json"),
                        "attempt_id": "manufactured-v14-cancel",
                        "home_receipt_path": str(tmp_path / "receipt.json")},
    }
    request.write_text(json.dumps(value))
    harness.write_text(textwrap.dedent(
        """
        import importlib.util, json, os, pathlib
        spec = importlib.util.spec_from_file_location('bound_v14_harness', SCRIPT_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module._validate_launch = lambda request, verify_content: (
            {'bridge_request': {'path': BRIDGE_PATH}}, None)
        module.V13.V12._storage_preflight = lambda _v11: {'fixture': True}
        module.V13._terminal_accounting_status = lambda _request: {
            'status': 'PASS_TERMINAL_CHARGE_AND_LEASE_CLEANUP', 'reason': None}
        report = module.run(pathlib.Path(REQUEST_PATH), parent_pid=os.getppid())
        print(json.dumps(report, sort_keys=True))
        """
        .replace("SCRIPT_PATH", repr(str(V14_SCRIPT)))
        .replace("BRIDGE_PATH", repr(str(bridge)))
        .replace("REQUEST_PATH", repr(str(request)))
    ).lstrip())
    process = subprocess.Popen([str(PYTHON), "-B", str(harness)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        # Let the real strace/bridge chain start before asking the launcher to
        # cancel.  The cooperative bridge exits well within the 20s grace.
        import time
        time.sleep(0.7)
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
    assert process.returncode == 0, stderr
    report = json.loads(stdout.strip())
    assert report["status"] == "FAILED_PARENT_SUPERVISED_CANCELLED"
    assert report["cleanup"]["sigterm_sent"] is True
    assert report["cleanup"]["exited_after_cleanup"] is True
    assert report["cleanup"]["forced_sigkill"] is False
    assert marker.read_text() == "SIGTERM"
    assert sidecar.is_file()
    assert report["trace"]["exists"] is True
