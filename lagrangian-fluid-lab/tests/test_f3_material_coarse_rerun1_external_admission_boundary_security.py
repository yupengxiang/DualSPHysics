"""Security audit for the F3 coarse RERUN1 external-admission boundary.

This test is deliberately limited to the checked-in RERUN1 scheduler specs,
the existing fresh-root/host-I/O intake observations, and the two terminal
intake validators.  It never submits a job, opens the native source HDF5, or
creates a receipt.  The property under test is promotion safety: diagnostic
terminal evidence must not turn missing fresh-root, host-I/O, or one-shot
authority into T1/T2/formal credit.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from scripts import f3_material_coarse_s4_terminal_result_intake_v1 as s4_intake
from scripts import f3_material_coarse_terminal_result_intake_v1 as s2_intake


ROOT = Path(__file__).resolve().parents[1]
AUDIT_REPORT = ROOT / "reports/F3-MATERIAL-COARSE-RERUN1-EXTERNAL-ADMISSION-BOUNDARY-SECURITY-AUDIT-2026-09-29.json"

SPEC_PATHS = {
    "s2": ROOT / "campaigns/core-v1/material/jobs/core-f3-material-coarse-s2-rerun1.json",
    "s4": ROOT / "campaigns/core-v1/material/jobs/core-f3-material-coarse-s4-rerun1.json",
}
TERMINAL_REPORT_PATHS = {
    "s2": ROOT / "reports/F3-MATERIAL-COARSE-TERMINAL-RESULT-INTAKE-2026-09-29-RERUN1.json",
    "s4": ROOT / "reports/F3-MATERIAL-COARSE-S4-TERMINAL-RESULT-INTAKE-2026-09-29-RERUN1.json",
}
ROOT_INTAKE_PATH = ROOT / "reports/F3-MATERIAL-COARSE-ROOT-SCHEDULER-INTAKE-V1-2026-09-29-RERUN1.json"
HOST_IO_PATH = ROOT / "reports/F3-MATERIAL-COARSE-HOST-IO-ADMISSION-2026-09-29-RERUN1.json"
INTAKE_SOURCE_PATHS = {
    "s2_terminal_validator": ROOT / "scripts/f3_material_coarse_terminal_result_intake_v1.py",
    "s4_terminal_validator": ROOT / "scripts/f3_material_coarse_s4_terminal_result_intake_v1.py",
}

EXPECTED_EXTERNAL_ADMISSION = {
    "fresh_root_receipt_required": True,
    "scheduler_host_io_receipt_required": True,
    "cross_bind_current_source_and_inputs": True,
    "one_shot_namespace_required": True,
    "launch_authority_minted_by_this_spec": False,
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), path
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check(report: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    checks = report["validation"]["checks"]
    return next(item for item in checks if item["check"] == name)


def _assert_non_authorizing(report: Mapping[str, Any], validator: Any) -> None:
    assert validator.validate_report(report) == []
    assert report["status"] == "negative_diagnostic"
    assert report["runtime_reference"]["scheduler_owned"] is True
    assert report["runtime_reference"]["portable_artifact"] is False
    assert report["runtime_reference"]["static_formal_receipt"] is False
    assert report["runtime_reference"]["historical_attempt_reused"] is False
    authorization = report["authorization"]
    assert authorization["launch_admitted"] is False
    assert authorization["formal"] is False
    assert authorization["formal_eligible"] is False
    assert authorization["qualification"] is False
    assert authorization["T1_numerical"] is False
    assert authorization["T2_macro"] is False
    assert authorization["T2_path"] is False
    assert authorization["credit"] == 0
    assert _check(report, "diagnostic_non_qualification_boundary")["passed"] is True
    negative = report["validation"]["unknown_gate_negative_diagnostic"]
    assert negative["recorded"] is True
    assert negative["above_one_percent"] is True


def test_rerun_specs_keep_external_admission_explicit_and_non_authorizing() -> None:
    for path in SPEC_PATHS.values():
        spec = _load(path)
        assert spec["external_admission"] == EXPECTED_EXTERNAL_ADMISSION


def test_upstream_external_admission_is_still_missing_and_blocked() -> None:
    root_intake = _load(ROOT_INTAKE_PATH)
    host_io = _load(HOST_IO_PATH)

    assert root_intake["status"] == "blocked_missing_fresh_root_scheduler_receipts"
    assert root_intake["authorization"]["launch_admitted"] is False
    assert root_intake["authorization"]["worker_launch_authorized"] is False
    assert root_intake["authorization"]["formal"] is False
    assert root_intake["authorization"]["credit"] == 0
    assert host_io["status"] == "diagnostic_admission_blocked"
    assert host_io["decision"]["root_authorization_present"] is False
    assert host_io["decision"]["scheduler_authorization_present"] is False
    assert host_io["decision"]["launch_admitted"] is False
    assert host_io["decision"]["worker_launch_authorized"] is False
    assert host_io["decision"]["credit"] == 0


def test_s2_and_s4_terminal_intakes_cannot_promote_current_rerun1() -> None:
    s2_report = s2_intake.build_report(ROOT)
    s4_report = s4_intake.build_report(ROOT)
    assert _load(TERMINAL_REPORT_PATHS["s2"]) == s2_report
    assert _load(TERMINAL_REPORT_PATHS["s4"]) == s4_report
    _assert_non_authorizing(s2_report, s2_intake)
    _assert_non_authorizing(s4_report, s4_intake)

    for report, validator in ((s2_report, s2_intake), (s4_report, s4_intake)):
        forged = deepcopy(report)
        forged["authorization"].update(
            {
                "launch_admitted": True,
                "formal": True,
                "formal_eligible": True,
                "qualification": True,
                "T1_numerical": True,
                "T2_macro": True,
                "T2_path": True,
                "credit": 1,
            }
        )
        forged["runtime_reference"]["static_formal_receipt"] = True
        assert validator.validate_report(forged)


def test_audit_report_binds_only_existing_evidence_and_no_authority() -> None:
    audit = _load(AUDIT_REPORT)
    assert audit["schema"] == "core.security.f3.material.coarse.external_admission_boundary_audit.v1"
    assert audit["status"] == "pass_fail_closed"
    assert audit["decision"] == {
        "external_admission_bypassed_for_promotion": False,
        "promotion_admitted": False,
        "real_fix_required": False,
        "terminal_intake_role": "result_intake_not_external_admission_consumer",
    }
    assert audit["execution_constraints"] == {
        "fresh_root_receipt_created": False,
        "scheduler_host_io_receipt_created": False,
        "external_one_shot_authority_created": False,
        "scheduler_submit_called": False,
        "workload_started": False,
        "gpu_started": False,
        "source_hdf5_opened": False,
        "registry_mutations": 0,
        "ledger_mutations": 0,
        "denominator_mutations": 0,
        "gate_mutations": 0,
        "completion_mutations": 0,
        "plan_mutations": 0,
    }
    for evidence in audit["evidence"]:
        path = ROOT / evidence["path"]
        assert path.is_file()
        assert evidence["content_read"] is True
        assert evidence["sha256"] == _sha256(path)
    root_status = _load(ROOT_INTAKE_PATH)["status"]
    host_io_status = _load(HOST_IO_PATH)["status"]
    assert audit["observations"]["fresh_root_scheduler_intake_status"] == root_status
    assert audit["observations"]["host_io_admission_status"] == host_io_status
    assert audit["observations"]["terminal_intakes_are_non_authorizing"] is True
    assert audit["observations"]["missing_external_admission_is_not_satisfied"] is True
