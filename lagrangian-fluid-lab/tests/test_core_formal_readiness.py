"""Regression tests for the read-only formal-readiness contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.core_formal_readiness import build_readiness, main


ROOT = Path(__file__).resolve().parents[1]
PHASE_PLAN = ROOT / "campaigns/core-v1/learning/core-phase-plan-denominator-audit-20260921.json"
ADMISSION = ROOT / "campaigns/core-v1/learning/formal-admission-audit-f3-f4-20260920.json"
REGISTRY = ROOT / "campaigns/core-v1/registry.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_real_readiness_preserves_all_formal_denominators_and_penalty_contract() -> None:
    report = build_readiness(
        data_root=ROOT,
        phase_plan=PHASE_PLAN,
        admission_audit=ADMISSION,
        registry=REGISTRY,
    )

    assert report["status"] == "blocked"
    assert report["formal_job_count"] == 0
    assert report["required_formal_job_count"] == 9
    assert report["formal_protocol"]["missing_material_case_runs"] == 288
    assert report["formal_protocol"]["observed_run_ids"] == []
    assert report["phase_plan"]["contract_passed"] is True
    assert report["evaluator_contract"]["contract_passed"] is True
    assert report["evaluator_contract"]["failure_probe"]["selection_score"] == 1.0
    assert report["evaluator_contract"]["failure_probe"]["expected_frames"] == 3
    assert {item["code"] for item in report["blockers"]} == {
        "THIRD_T1_FAMILY",
        "VALIDATION_DENOMINATOR",
        "FORMAL_RUN_DENOMINATOR",
        "MATERIAL_CASE_RUN_DENOMINATOR",
    }
    assert report["execution_constraints"] == {
        "formal_runs_started": 0,
        "formal_specs_written": False,
        "gpu_started": False,
        "ledger_written": False,
        "optimizer_started": False,
        "predictor_future_state_inputs": False,
        "read_only": True,
        "registry_written": False,
        "solver_started": False,
        "trajectory_files_opened": False,
        "trajectory_state_frames_read": 0,
    }


def test_cli_is_portable_and_does_not_mutate_registry(tmp_path: Path, monkeypatch) -> None:
    before = _sha256(REGISTRY)
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "formal-readiness.json"
    digest = tmp_path / "formal-readiness.json.sha256"
    exit_code = main([
        "--data-root", str(ROOT),
        "--phase-plan", "campaigns/core-v1/learning/core-phase-plan-denominator-audit-20260921.json",
        "--admission-audit", "campaigns/core-v1/learning/formal-admission-audit-f3-f4-20260920.json",
        "--registry", "campaigns/core-v1/registry.json",
        "--record-id", "core-formal-readiness-test-r001",
        "--output", str(output), "--sha256-output", str(digest),
    ])
    assert exit_code == 2
    report = json.loads(output.read_text())
    assert report["record_id"] == "core-formal-readiness-test-r001"
    assert report["status"] == "blocked"
    assert report["core_status"]["registry"]["path"] == "campaigns/core-v1/registry.json"
    assert digest.read_text().split()[0] == _sha256(output)
    assert _sha256(REGISTRY) == before


def test_failure_penalty_contract_rejects_no_denominator_shrink(tmp_path: Path) -> None:
    phase = {
        "schema": "core.phase_plan.v1",
        "passed": True,
        "phase_order": ["verify", "inspect", "train", "rollout", "evaluate", "reproduce"],
        "phases": [{"name": name, "future_state_inputs": False}
                   for name in ("verify", "inspect", "train", "rollout", "evaluate", "reproduce")],
        "denominator": {
            "registered_case_count": 1,
            "cases": {"case": {"expected_frames": 2, "trajectory_frames": 3, "split": "validation"}},
            "missing_denominator_case_ids": [],
            "missing_execution_preserves_expected_frames": True,
            "policy": "fixed registered future-frame denominator; never shrink on failure",
        },
        "guards": {
            "trajectory_state_frames_read": 0,
            "predictor_future_state_inputs": False,
            "future_state_inputs": False,
            "formal_training_started": False,
            "registry_written": False,
            "ledger_written": False,
        },
        "formal_readiness": {
            "formal_training": False,
            "formal_job_count": 0,
            "required_formal_job_count": 9,
        },
    }
    admission = {
        "schema": "core.formal_admission_audit.v1",
        "status": "blocked",
        "formal_admission": False,
        "formal_job_count": 0,
        "required_formal_job_count": 9,
        "family_summary": {
            "t1_families": {"F3": True},
            "validation_counts": {"F3": 1},
        },
        "formal_protocol": {},
        "blockers": [],
    }
    phase_path = tmp_path / "phase.json"
    admission_path = tmp_path / "admission.json"
    registry_path = tmp_path / "registry.json"
    phase_path.write_text(json.dumps(phase))
    admission_path.write_text(json.dumps(admission))
    registry_path.write_text("{}")
    report = build_readiness(
        data_root=tmp_path,
        phase_plan=phase_path,
        admission_audit=admission_path,
        registry=registry_path,
    )
    assert report["evaluator_contract"]["failure_probe"]["selection_score"] == 1.0
    assert report["evaluator_contract"]["failure_probe"]["raw_error_coverage"] == 0.0
    assert report["formal_protocol"]["missing_material_case_runs"] == 288


def test_phase_plan_denominator_rows_must_match_registered_frame_maps(tmp_path: Path) -> None:
    phase = {
        "schema": "core.phase_plan.v1",
        "passed": True,
        "phase_order": ["verify", "inspect", "train", "rollout", "evaluate", "reproduce"],
        "phases": [{"name": name, "future_state_inputs": False}
                   for name in ("verify", "inspect", "train", "rollout", "evaluate", "reproduce")],
        "denominator": {
            "case_ids": ["case"],
            "registered_case_count": 1,
            "expected_frames_by_case": {"case": 2},
            "trajectory_frames_by_case": {"case": 3},
            "cases": {"case": {"expected_frames": 2, "trajectory_frames": 4}},
            "missing_denominator_case_ids": [],
            "missing_execution_preserves_expected_frames": True,
            "policy": "fixed registered future-frame denominator; never shrink on failure",
        },
        "guards": {
            "trajectory_state_frames_read": 0,
            "predictor_future_state_inputs": False,
            "future_state_inputs": False,
            "formal_training_started": False,
            "registry_written": False,
            "ledger_written": False,
        },
        "formal_readiness": {
            "formal_training": False,
            "formal_job_count": 0,
            "required_formal_job_count": 9,
        },
    }
    admission = {
        "schema": "core.formal_admission_audit.v1",
        "status": "blocked",
        "formal_admission": False,
        "formal_job_count": 0,
        "required_formal_job_count": 9,
        "family_summary": {"t1_families": {"F3": True}, "validation_counts": {"F3": 1}},
        "formal_protocol": {},
        "blockers": [],
    }
    phase_path = tmp_path / "phase.json"
    admission_path = tmp_path / "admission.json"
    registry_path = tmp_path / "registry.json"
    phase_path.write_text(json.dumps(phase))
    admission_path.write_text(json.dumps(admission))
    registry_path.write_text("{}")

    report = build_readiness(
        data_root=tmp_path,
        phase_plan=phase_path,
        admission_audit=admission_path,
        registry=registry_path,
    )

    assert report["phase_plan"]["denominator_row_integrity"] is False
    assert report["phase_plan"]["contract_checks"]["denominator_row_integrity"] is False
    assert report["checks"]["phase_plan_denominator_contract"] is False
    assert any(item["code"] == "PHASE_PLAN_CONTRACT" for item in report["blockers"])
