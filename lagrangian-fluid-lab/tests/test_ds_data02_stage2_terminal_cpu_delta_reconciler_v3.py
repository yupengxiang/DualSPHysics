from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_terminal_cpu_delta_reconciler_v3.py"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
REQUEST_ROOT = Path(
    "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests"
)
CASES = {
    "093": (
        REQUEST_ROOT / "f3-s2-root086-vtk-support-qa-v2-root-forward-093-001.json",
        DATA_ROOT / "families/F3/F3_S2_ROOT086_GUARDED_VTK_SUPPORT_V2_ROOT_093/"
        "f3-s2-root086-vtk-support-qa-v2-root-093-001-root-forward-030-001/execution-receipt.json",
        2.153004,
        2_376_480_000,
    ),
    "094": (
        REQUEST_ROOT / "f2-s1-generated-bi4-snapshot-v2-root-forward-094-001.json",
        DATA_ROOT / "families/F2/F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0088_BI4_SOURCE_SNAPSHOT_V2_ROOT_094/"
        "f2-s1-owner-centered-cell-selector-generated-bi4-snapshot-v2-root-094-002/execution-receipt.json",
        1.360547,
        1_594_255_000,
    ),
    "096": (
        REQUEST_ROOT / "f3-s2-owner-mass-reconciliation-v1-root-forward-096-001.json",
        DATA_ROOT / "families/F3/F3_S2_OWNER_MASS_SOURCE_RECONCILIATION_ROOT_096/"
        "f3-s2-owner-mass-reconciliation-v1-root-096-001-root-forward-030-001/execution-receipt.json",
        1.285486,
        1_502_243_000,
    ),
}


def _load():
    spec = importlib.util.spec_from_file_location("terminal_delta_v3_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V3 = _load()


def _evidence(path: Path, cpu_ns: int, request_sha: str | None = None) -> Path:
    value = {"schema": V3.EVIDENCE_SCHEMA, "CPUUsageNSec": cpu_ns}
    if request_sha is not None:
        value["request_sha256"] = request_sha
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")
    return path


def _ledger(path: Path, charge_id: str, cpu: float) -> Path:
    value = {
        "schema": "ds02.resource-ledger.test.v1",
        "charges": [{"id": charge_id, "status": "completed",
                      "cpu_core_seconds": cpu, "gpu_seconds": 0.0,
                      "new_storage_bytes": 89360}],
        "reservations": [], "attempts": [], "limits": {},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")
    return path


@pytest.mark.parametrize("case", CASES.values(), ids=CASES.keys())
def test_inspect_actual_ds02_request_and_receipt(case) -> None:
    request, receipt, cpu, cpu_ns = case
    if not request.is_file() or not receipt.is_file():
        pytest.skip("root actual small JSON receipt is not present")
    value = json.loads(request.read_text(encoding="utf-8"))
    receipt_value = json.loads(receipt.read_text(encoding="utf-8"))
    # This test only opens the request/receipt JSON and their bound runtime
    # source; it never follows deferred H5/BI4/raw/result paths.
    with tempfile.TemporaryDirectory(prefix="ds02-delta-v3-") as directory:
        evidence_path = _evidence(Path(directory) / "systemd.json", cpu_ns)
        ledger_path = _ledger(Path(directory) / "runtime" / "resource-ledger.json",
                              "/".join(value[k] for k in ("family_id", "case_id", "attempt_id")), cpu)
        inspected = V3.inspect_binding(request_path=request, receipt_path=receipt,
                                       evidence_path=evidence_path, ledger_path=ledger_path)
        assert inspected["request"]["family_id"] == value["family_id"]
        assert inspected["receipt"]["cpu_core_seconds"] == pytest.approx(cpu)
        assert inspected["systemd_evidence"]["cpu_usage_nanoseconds"] == cpu_ns
        assert inspected["delta_cpu_core_seconds"] == pytest.approx(cpu_ns / 1e9 - cpu)
        assert inspected["reservation_created"] is False


def test_reconcile_actual_093_with_synthetic_ledger_is_idempotent(tmp_path: Path) -> None:
    request, receipt, cpu, cpu_ns = CASES["093"]
    if not request.is_file() or not receipt.is_file():
        pytest.skip("root actual 093 small JSON receipt is not present")
    request_value = json.loads(request.read_text(encoding="utf-8"))
    charge_id = "/".join(request_value[key] for key in ("family_id", "case_id", "attempt_id"))
    evidence = _evidence(tmp_path / "systemd.json", cpu_ns)
    ledger = _ledger(tmp_path / "runtime" / "resource-ledger.json", charge_id, cpu)
    output = tmp_path / "reconciliation.json"
    result = V3.reconcile(request_path=request, receipt_path=receipt,
                           evidence_path=evidence, ledger_path=ledger, output=output)
    assert result["status"] == "APPENDED_SAME_PARENT_CPU_DELTA"
    saved = json.loads(ledger.read_text(encoding="utf-8"))
    rows = [row for row in saved["charges"] if row["id"].endswith("::terminal-cpu-delta-v3")]
    assert len(rows) == 1
    assert rows[0]["cpu_core_seconds"] == pytest.approx(cpu_ns / 1e9 - cpu)
    assert saved["reservations"] == []
    repeated = V3.reconcile(request_path=request, receipt_path=receipt,
                             evidence_path=evidence, ledger_path=ledger,
                             output=tmp_path / "repeated.json")
    assert repeated["status"] == "ALREADY_APPLIED_SAME_PARENT_CPU_DELTA"
    assert len([row for row in json.loads(ledger.read_text(encoding="utf-8"))["charges"]
                if row["id"].endswith("::terminal-cpu-delta-v3")]) == 1


def test_external_solver_receipt_shape_uses_same_identity_join(tmp_path: Path) -> None:
    request, _receipt, cpu, cpu_ns = CASES["093"]
    if not request.is_file():
        pytest.skip("root request is not present")
    request_value = json.loads(request.read_text(encoding="utf-8"))
    receipt = tmp_path / "external-solver-v5-receipt.json"
    receipt_value = {
        "schema": "ds02.external-solver-v5.execution-receipt.v1",
        "status": "completed", "request": request_value,
        "request_sha256": V3.sha256_file(request), "cpu_core_seconds": cpu,
        "bytes": 89360,
    }
    receipt.write_text(json.dumps(receipt_value) + "\n", encoding="utf-8")
    evidence = _evidence(tmp_path / "systemd.json", cpu_ns)
    charge_id = "/".join(request_value[key] for key in ("family_id", "case_id", "attempt_id"))
    ledger = _ledger(tmp_path / "runtime" / "resource-ledger.json", charge_id, cpu)
    value = V3.inspect_binding(request_path=request, receipt_path=receipt,
                               evidence_path=evidence, ledger_path=ledger)
    assert value["status"] == "READY_FOR_SAME_PARENT_CPU_DELTA"
    assert value["receipt"]["status"] == "completed"
