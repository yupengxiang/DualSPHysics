from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_parent_reconcile_launch_v1.py"
OLD_REQUEST = ROOT / (
    "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v34-full-chain/"
    "f2-s1-portable-executor-parent-request-v3-047.json")


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


reconcile = _load(SCRIPT, "parent_reconcile_launch_v1_test")


def test_fixed_receipt_bytes_are_stable_and_canonical() -> None:
    value = {
        "schema": reconcile.SCHEMA,
        "status": reconcile.RECONCILIATION_STATUS,
        "filesystem": {"home_receipt_bytes": 0},
        "qualification": dict(reconcile.UNKNOWN),
    }
    encoded, size = reconcile._fixed_report_bytes(value)
    assert len(encoded) == size
    assert value["sha256"] == reconcile.canonical_sha(value)


def test_systemd_command_preserves_literal_venv_and_does_not_start_service(tmp_path: Path) -> None:
    request = json.loads(OLD_REQUEST.read_text())
    request["parent_resource_binding"]["attempt_id"] = "f2-s1-portable-executor-v34-050"
    request["parent_resource_binding"]["reservation_id"] = "f2-s1-portable-executor-v34-050::f2-v34-parent-v3-reservation"
    request["parent_resource_binding"]["charge_id"] = "f2-s1-portable-executor-v34-050::f2-v34-parent-v3-charge"
    request["sha256"] = reconcile.V3.canonical_sha(request)
    path = tmp_path / "retry-request.json"
    path.write_text(json.dumps(request))
    result = reconcile.systemd_command(request_path=path, unit="ds02-test-parent-050", launcher=SCRIPT)
    argv = result["systemd_argv"]
    assert result["service_started"] is False
    assert "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python" in argv
    assert "/usr/bin/python3.10" not in argv
    assert "--property=RuntimeMaxSec=6300" in argv
    assert "--property=KillMode=mixed" in argv
    assert "--property=StandardOutput=journal" in argv


def test_observed_pid_gate_requires_absent_processes() -> None:
    assert reconcile._pid_absent(os.getpid()) is False
    assert reconcile._pid_absent(2_147_483_000) is True
