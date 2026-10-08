from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_parent_supplemental_charge_v13.py"
RUNTIME = ROOT / "scripts" / "ds_data02_runtime_v6.py"
SPEC = importlib.util.spec_from_file_location("supplemental_charge_v13_test_module", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
sys.path.insert(0, str(SCRIPT.parent))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    external = tmp_path / "external"
    external.mkdir()
    ledger_path = tmp_path / "data" / "runtime" / "resource-ledger.json"
    ledger_path.parent.mkdir(parents=True)
    attempt = "F2/case-v13/attempt-v12"
    ledger_path.write_text(json.dumps({
        "schema": "ds02.resource-ledger.v1",
        "campaign_id": "DS-DATA-02",
        "deadline_utc": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "limits": {"new_storage_bytes": 100_000, "cpu_core_seconds": 100_000,
                   "home_min_free_bytes": 1, "home_path": str(tmp_path),
                   "storage_policy": "home_free_floor"},
        "reservations": [],
        "charges": [{"id": attempt, "status": "failed", "new_storage_bytes": 10,
                     "cpu_core_seconds": 1.0}],
        "attempts": [{"id": attempt, "status": "failed"}],
    }))
    trace = external / "os-open-trace.log"
    trace.write_bytes(b"trace-final-012345")
    v11_path = tmp_path / "v11.json"
    bridge_path = tmp_path / "bridge.json"
    bridge_path.write_text(json.dumps({
        "guard_bindings": [{"role": "shared_runtime_v6", "path": str(RUNTIME), "sha256": _sha(RUNTIME)}]
    }))
    v11_path.write_text(json.dumps({"bridge_request": {"path": str(bridge_path)}}))
    v12_path = tmp_path / "v12.json"
    v12 = {
        "schema": MODULE.V12_SCHEMA,
        "status": "READY_FOR_PARENT_GUARD",
        "parent_resource_binding": {
            "campaign_id": "DS-DATA-02",
            "limits": {"home_path": str(tmp_path)},
        },
        "accounting": {"ledger_path": str(ledger_path), "attempt_id": attempt},
        "storage_scope": {"external_filesystem": str(external),
                           "finalization_sidecar": str(external / "os-open-trace-finalization-v12.json")},
        "trace": {"path": str(trace)},
        "v11_launch": {"path": str(v11_path)},
    }
    v12["sha256"] = MODULE.canonical_sha(v12)
    v12_path.write_text(json.dumps(v12))
    sidecar_path = external / "os-open-trace-finalization-v12.json"
    sidecar = {
        "schema": "ds02.stage2.f2-parent-trace-finalization.v12",
        "request_sha256": v12["sha256"],
        "trace": {"path": str(trace), "bytes": trace.stat().st_size},
        "bridge_receipt_trace_bytes": 5,
        "trace_growth_after_bridge_charge_bytes": trace.stat().st_size - 5,
        "cleanup": {"forced_sigkill": False},
        "parent_charge_required": True,
    }
    sidecar["sha256"] = MODULE.canonical_sha(sidecar)
    sidecar_path.write_text(json.dumps(sidecar, indent=2) + "\n")
    return v12_path, ledger_path, trace, sidecar_path


def test_build_and_apply_supplemental_charge_is_idempotent(tmp_path: Path) -> None:
    v12_path, ledger_path, trace, sidecar = _fixture(tmp_path)
    request_path = tmp_path / "supplemental-request.json"
    request = MODULE.build_request(v12_path, request_path)
    assert request["schema"] == MODULE.SCHEMA
    first = MODULE.apply_charge(request_path)
    assert first["status"] == "SUPPLEMENTAL_CHARGE_APPLIED"
    assert first["ledger_mutated"] is True
    expected_bytes = trace.stat().st_size - 5 + sidecar.stat().st_size
    assert first["charge"]["new_storage_bytes"] == expected_bytes
    assert first["charge"]["trace_growth_after_bridge_charge_bytes"] == trace.stat().st_size - 5
    assert first["charge"]["sidecar_bytes"] == sidecar.stat().st_size
    second = MODULE.apply_charge(request_path)
    assert second["status"] == "IDEMPOTENT_ALREADY_CHARGED"
    ledger = json.loads(ledger_path.read_text())
    rows = [row for row in ledger["charges"] if row.get("id") == request["accounting"]["supplemental_charge_id"]]
    assert len(rows) == 1
    assert ledger["reservations"] == []


def test_changed_trace_after_sidecar_is_rejected_without_new_charge(tmp_path: Path) -> None:
    v12_path, ledger_path, trace, _sidecar = _fixture(tmp_path)
    request_path = tmp_path / "supplemental-request.json"
    request = MODULE.build_request(v12_path, request_path)
    trace.write_bytes(trace.read_bytes() + b"late")
    with pytest.raises(MODULE.SupplementalChargeError, match="trace grew"):
        MODULE.apply_charge(request_path)
    ledger = json.loads(ledger_path.read_text())
    assert not any(row.get("id") == request["accounting"]["supplemental_charge_id"] for row in ledger["charges"])


def test_active_parent_reservation_blocks_supplemental_charge(tmp_path: Path) -> None:
    v12_path, ledger_path, _trace, _sidecar = _fixture(tmp_path)
    request_path = tmp_path / "supplemental-request.json"
    request = MODULE.build_request(v12_path, request_path)
    ledger = json.loads(ledger_path.read_text())
    ledger["reservations"].append({"id": request["accounting"]["attempt_id"], "kind": "cpu"})
    ledger_path.write_text(json.dumps(ledger))
    with pytest.raises(MODULE.SupplementalChargeError, match="reservation is still active"):
        MODULE.apply_charge(request_path)
