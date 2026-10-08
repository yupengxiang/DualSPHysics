from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_terminal_cpu_delta_reconciler_v6.py"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
ROOT_ACCOUNTING = Path(
    "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/accounting/"
    "terminal-cpu-evidence-root-093-098-v1"
)
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
    "095": (
        REQUEST_ROOT / "f2-s1-coarse-solver-canary-v5-root-forward-095-001.json",
        DATA_ROOT / "families/F2/F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0088_T4_COARSE_CANARY_ROOT_095/"
        "f2-s1-owner-centered-cell-selector-dp0088-t4-coarse-canary-v5-root-095-001/execution-receipt.json",
        101.011758,
        101_237_047_000,
    ),
    "102": (
        REQUEST_ROOT / "f3-s2-commensurate-dp003-gencase-v1-root-forward-102-001.json",
        DATA_ROOT / "families/F3/F3_S2_MATCHED_SOURCE_COMMENSURATE_DP003_GENCASE_ROOT_102/"
        "f3-s2-commensurate-dp003-gencase-v1-root-102-001-root-forward-030-001/execution-receipt.json",
        8.377299,
        8_614_580_000,
    ),
    "103": (
        REQUEST_ROOT / "f6-fluid-owner-authority-audit-v3-root-forward-103-001.json",
        DATA_ROOT / "families/F6/F6_FLUID_OWNER_AUTHORITY_SOURCE_V3_ROOT_103/"
        "f6-fluid-owner-authority-audit-v3-root-103-001-root-forward-030-001/execution-receipt.json",
        1.239642,
        1_478_414_000,
    ),
}


def _load():
    spec = importlib.util.spec_from_file_location("terminal_delta_v6_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V6 = _load()


def _evidence(path: Path, cpu_ns: int, request: Path, receipt: Path,
              identity: dict[str, str], *, request_sha: str | None = None,
              receipt_sha: str | None = None, unit: str | None = None) -> Path:
    value = {"schema": V6.EVIDENCE_SCHEMA, "CPUUsageNSec": cpu_ns,
             "cpu_usage_nsec": cpu_ns, "terminal": True,
             "request": str(request), "request_sha256": request_sha or V6.sha256_file(request),
             "receipt": str(receipt), "receipt_sha256": receipt_sha or V6.sha256_file(receipt),
             "identity": {key: identity[key] for key in ("family_id", "case_id", "attempt_id")},
             "charge_id": "/".join(identity[key] for key in ("family_id", "case_id", "attempt_id")),
             "unit": unit or "ds02-test.service",
             "systemd_properties": {"Id": unit or "ds02-test.service",
                                     "Result": "success", "SubState": "exited",
                                     "CPUUsageNSec": str(cpu_ns),
                                     "InvocationID": "test-invocation-001",
                                     "ExecStart": f"/home/jade/.venv/bin/python --request {request}"}}
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


ACTUAL_EVIDENCE = {
    "093": ROOT_ACCOUNTING / "root-093-systemd-terminal-cpu-evidence.json",
    "094": ROOT_ACCOUNTING / "root-094-systemd-terminal-cpu-evidence.json",
    "096": ROOT_ACCOUNTING / "root-096-systemd-terminal-cpu-evidence.json",
    "095": ROOT_ACCOUNTING / "root-095-systemd-terminal-cpu-evidence.json",
    "102": Path(
        "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/accounting/"
        "terminal-cpu-evidence-root-102-v1.json"),
    "103": Path(
        "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/accounting/"
        "terminal-cpu-evidence-root-103-v1.json"),
}


@pytest.mark.parametrize("label,case", CASES.items(), ids=CASES.keys())
def test_inspect_actual_ds02_request_and_receipt(label, case) -> None:
    request, receipt, cpu, cpu_ns = case
    if not request.is_file() or not receipt.is_file():
        pytest.skip("root actual small JSON receipt is not present")
    value = json.loads(request.read_text(encoding="utf-8"))
    # This test only opens the request/receipt JSON and their bound runtime
    # source; it never follows deferred H5/BI4/raw/result paths.
    with tempfile.TemporaryDirectory(prefix="ds02-delta-v4-") as directory:
        identity = {key: value[key] for key in ("family_id", "case_id", "attempt_id")}
        evidence_path = ACTUAL_EVIDENCE[label]
        if not evidence_path.is_file():
            evidence_path = _evidence(Path(directory) / "systemd.json", cpu_ns, request, receipt, identity)
        ledger_path = _ledger(Path(directory) / "runtime" / "resource-ledger.json",
                              "/".join(value[k] for k in ("family_id", "case_id", "attempt_id")), cpu)
        inspected = V6.inspect_binding(request_path=request, receipt_path=receipt,
                                       evidence_path=evidence_path, ledger_path=ledger_path)
        assert inspected["request"]["family_id"] == value["family_id"]
        assert inspected["receipt"]["cpu_core_seconds"] == pytest.approx(cpu)
        assert inspected["systemd_evidence"]["cpu_usage_nanoseconds"] == cpu_ns
        assert inspected["delta_cpu_core_seconds"] == pytest.approx(cpu_ns / 1e9 - cpu)
        assert inspected["reservation_created"] is False
        assert inspected["systemd_evidence"]["cpu_unit"] == "nanoseconds"


def test_reconcile_actual_093_with_synthetic_ledger_is_idempotent(tmp_path: Path) -> None:
    request, receipt, cpu, cpu_ns = CASES["093"]
    if not request.is_file() or not receipt.is_file():
        pytest.skip("root actual 093 small JSON receipt is not present")
    request_value = json.loads(request.read_text(encoding="utf-8"))
    charge_id = "/".join(request_value[key] for key in ("family_id", "case_id", "attempt_id"))
    identity = {key: request_value[key] for key in ("family_id", "case_id", "attempt_id")}
    evidence = _evidence(tmp_path / "systemd.json", cpu_ns, request, receipt, identity)
    ledger = _ledger(tmp_path / "runtime" / "resource-ledger.json", charge_id, cpu)
    output = tmp_path / "reconciliation.json"
    result = V6.reconcile(request_path=request, receipt_path=receipt,
                           evidence_path=evidence, ledger_path=ledger, output=output)
    assert result["status"] == "APPENDED_SAME_PARENT_CPU_DELTA"
    saved = json.loads(ledger.read_text(encoding="utf-8"))
    rows = [row for row in saved["charges"] if row["id"].endswith("::terminal-cpu-delta-v6")]
    assert len(rows) == 1
    assert rows[0]["cpu_core_seconds"] == pytest.approx(cpu_ns / 1e9 - cpu)
    assert saved["reservations"] == []
    repeated = V6.reconcile(request_path=request, receipt_path=receipt,
                             evidence_path=evidence, ledger_path=ledger,
                             output=output)
    assert repeated["status"] == "ALREADY_APPLIED_SAME_PARENT_CPU_DELTA"
    assert len([row for row in json.loads(ledger.read_text(encoding="utf-8"))["charges"]
                if row["id"].endswith("::terminal-cpu-delta-v6")]) == 1


def test_external_solver_receipt_shape_uses_same_identity_join(tmp_path: Path) -> None:
    request, _receipt, cpu, cpu_ns = CASES["093"]
    if not request.is_file():
        pytest.skip("root request is not present")
    request_value = json.loads(request.read_text(encoding="utf-8"))
    receipt = tmp_path / "external-solver-v5-receipt.json"
    receipt_value = {
        "schema": "ds02.stage2.external-solver-report.v5",
        "status": "COMPLETED_DEVELOPMENT_UNKNOWN",
        "request": {"path": str(request), "sha256": V6.sha256_file(request)},
        "execution": {"cpu_core_seconds": cpu},
        "bytes": 89360,
    }
    receipt.write_text(json.dumps(receipt_value) + "\n", encoding="utf-8")
    identity = {key: request_value[key] for key in ("family_id", "case_id", "attempt_id")}
    evidence = _evidence(tmp_path / "systemd.json", cpu_ns, request, receipt, identity,
                         receipt_sha=V6.sha256_file(receipt))
    charge_id = "/".join(request_value[key] for key in ("family_id", "case_id", "attempt_id"))
    ledger = _ledger(tmp_path / "runtime" / "resource-ledger.json", charge_id, cpu)
    value = V6.inspect_binding(request_path=request, receipt_path=receipt,
                               evidence_path=evidence, ledger_path=ledger)
    assert value["status"] == "READY_FOR_SAME_PARENT_CPU_DELTA"
    assert value["receipt"]["status"] == "COMPLETED_DEVELOPMENT_UNKNOWN"


def test_reconcile_actual_095_external_v5_with_synthetic_ledger(tmp_path: Path) -> None:
    request, receipt, cpu, cpu_ns = CASES["095"]
    evidence = ACTUAL_EVIDENCE["095"]
    if not request.is_file() or not receipt.is_file() or not evidence.is_file():
        pytest.skip("root actual 095 small JSON evidence is not present")
    request_value = json.loads(request.read_text(encoding="utf-8"))
    charge_id = "/".join(request_value[key] for key in ("family_id", "case_id", "attempt_id"))
    ledger = _ledger(tmp_path / "runtime" / "resource-ledger.json", charge_id, cpu)
    result = V6.reconcile(request_path=request, receipt_path=receipt,
                           evidence_path=evidence, ledger_path=ledger,
                           output=tmp_path / "root095-delta.json")
    assert result["status"] == "APPENDED_SAME_PARENT_CPU_DELTA"
    assert result["request"]["schema"] == "ds02.stage2.external-solver-request.v5"
    assert result["delta_cpu_core_seconds"] == pytest.approx(0.225289, abs=1e-9)
    saved = json.loads(ledger.read_text(encoding="utf-8"))
    rows = [row for row in saved["charges"] if row["id"].endswith("::terminal-cpu-delta-v6")]
    assert len(rows) == 1 and rows[0]["new_storage_bytes"] == 0
    assert saved["reservations"] == []


def test_evidence_wrong_unit_request_or_receipt_sha_is_rejected(tmp_path: Path) -> None:
    request, receipt, cpu, cpu_ns = CASES["093"]
    if not request.is_file() or not receipt.is_file():
        pytest.skip("root actual small JSON receipt is not present")
    request_value = json.loads(request.read_text(encoding="utf-8"))
    identity = {key: request_value[key] for key in ("family_id", "case_id", "attempt_id")}
    ledger = _ledger(tmp_path / "runtime" / "resource-ledger.json",
                     "/".join(identity[key] for key in ("family_id", "case_id", "attempt_id")), cpu)
    valid = _evidence(tmp_path / "valid.json", cpu_ns, request, receipt, identity)
    for field, bad in (("unit", "seconds"), ("request_sha256", "0" * 64),
                       ("receipt_sha256", "f" * 64)):
        value = json.loads(valid.read_text(encoding="utf-8"))
        value[field] = bad
        candidate = tmp_path / f"bad-{field}.json"
        candidate.write_text(json.dumps(value) + "\n", encoding="utf-8")
        with pytest.raises(V6.ReconciliationError):
            V6.inspect_binding(request_path=request, receipt_path=receipt,
                               evidence_path=candidate, ledger_path=ledger)


def test_systemd_properties_must_bind_cpu_invocation_and_request(tmp_path: Path) -> None:
    request, receipt, cpu, cpu_ns = CASES["093"]
    if not request.is_file() or not receipt.is_file():
        pytest.skip("root actual 093 small JSON receipt is not present")
    request_value = json.loads(request.read_text(encoding="utf-8"))
    identity = {key: request_value[key] for key in ("family_id", "case_id", "attempt_id")}
    ledger = _ledger(tmp_path / "runtime" / "resource-ledger.json",
                     "/".join(identity[key] for key in ("family_id", "case_id", "attempt_id")), cpu)
    valid = _evidence(tmp_path / "valid.json", cpu_ns, request, receipt, identity)
    for label, mutate in (
        ("property-cpu", lambda value: value["systemd_properties"].update(CPUUsageNSec=str(cpu_ns + 1))),
        ("exec-start", lambda value: value["systemd_properties"].update(ExecStart="/other/request.json")),
        ("invocation", lambda value: value["systemd_properties"].pop("InvocationID")),
    ):
        value = json.loads(valid.read_text(encoding="utf-8"))
        mutate(value)
        candidate = tmp_path / f"bad-{label}.json"
        candidate.write_text(json.dumps(value) + "\n", encoding="utf-8")
        with pytest.raises(V6.ReconciliationError):
            V6.inspect_binding(request_path=request, receipt_path=receipt,
                               evidence_path=candidate, ledger_path=ledger)


def test_cross_version_supplemental_charge_is_rejected(tmp_path: Path) -> None:
    request, receipt, cpu, cpu_ns = CASES["093"]
    if not request.is_file() or not receipt.is_file():
        pytest.skip("root actual 093 small JSON receipt is not present")
    request_value = json.loads(request.read_text(encoding="utf-8"))
    charge_id = "/".join(request_value[key] for key in ("family_id", "case_id", "attempt_id"))
    identity = {key: request_value[key] for key in ("family_id", "case_id", "attempt_id")}
    evidence = _evidence(tmp_path / "systemd.json", cpu_ns, request, receipt, identity)
    ledger = _ledger(tmp_path / "runtime" / "resource-ledger.json", charge_id, cpu)
    ledger_value = json.loads(ledger.read_text(encoding="utf-8"))
    ledger_value["charges"].append({
        "id": charge_id + "::terminal-cpu-delta-v5",
        "parent_charge_id": charge_id,
        "kind": "supplemental_terminal_cpu_delta",
        "reconciliation_schema": "ds02.stage2.terminal-cpu-delta-reconciliation-v5",
        "cpu_core_seconds": 0.1,
        "new_storage_bytes": 0,
        "status": "completed",
    })
    ledger.write_text(json.dumps(ledger_value) + "\n", encoding="utf-8")
    with pytest.raises(V6.ReconciliationError, match="already has a terminal CPU reconciliation"):
        V6.inspect_binding(request_path=request, receipt_path=receipt,
                           evidence_path=evidence, ledger_path=ledger)
