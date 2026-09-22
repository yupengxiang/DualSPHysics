"""Regression tests for the preserved, historical v5 source closure."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.core_formal_source_closure_admission import (
    REQUIRED_CODE_FILES,
    _gate_snapshot,
    main,
    verify_admission,
    verify_source_closure,
)


ROOT = Path(__file__).resolve().parents[1]
CLOSURE = ROOT / "campaigns/core-v1/learning/formal-release-candidate-v5/source-closure.json"
RECEIPT = ROOT / "campaigns/core-v1/learning/formal-release-candidate-v5/root-admission-receipt.json"
REGISTRY = ROOT / "campaigns/core-v1/registry.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v5_closure_is_preserved_and_fails_closed_against_current_sources() -> None:
    closure = json.loads(CLOSURE.read_text(encoding="utf-8"))
    result = verify_source_closure(closure, data_root=ROOT)

    assert result["ok"] is False
    assert result["mismatch_files"] == [
        "scripts/core_cfd_dataset.py", "scripts/core_contract.py",
        "scripts/core_dataset.py", "scripts/core_evaluation.py",
        "scripts/core_learning.py", "scripts/core_models.py"
    ]
    assert closure["closure_version"] == "core-formal-release-candidate-v5"
    assert closure["formal_release"] is False
    assert closure["planning_only"] is True
    assert closure["planning_allowed"] is True
    assert closure["formal_training_allowed"] is False
    assert closure["formal_job_count"] == 0
    assert [row["relative_path"] for row in closure["files"]] == list(REQUIRED_CODE_FILES)

    assert closure["source_snapshot_policy"] == "fresh_code_closure_at_formal_admission"
    assert closure["generator"]["path"] == "scripts/core_formal_source_closure_admission.py"


def test_root_receipt_binds_v5_hash_and_preserves_formal_holds() -> None:
    result = verify_admission(
        data_root=ROOT,
        source_closure=CLOSURE,
        receipt=RECEIPT,
    )
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    closure = json.loads(CLOSURE.read_text(encoding="utf-8"))

    assert result["ok"] is False
    assert result["checks"]["closure_verification"] is False
    assert receipt["source_closure"]["sha256"] == _sha256(CLOSURE)
    assert receipt["source_closure"]["closure_sha256"] == closure["closure_sha256"]
    assert receipt["formal_release"] is False
    assert receipt["planning_only"] is True
    assert receipt["planning_allowed"] is True
    assert receipt["formal_training_allowed"] is False
    assert receipt["formal_job_count"] == 0
    assert receipt["required_formal_job_count"] == 9
    assert receipt["launch_allowed"] is False
    assert receipt["root_admission"]["granted"] is False

    gates = receipt["gate_evaluation"]
    assert gates["third_t1_family"]["observed"] == 2
    assert gates["third_t1_family"]["required"] == 3
    assert gates["validation_denominator"]["observed"] == 8
    assert gates["validation_denominator"]["required"] == 12
    assert gates["material_case_run_denominator"]["observed"] == 0
    assert gates["material_case_run_denominator"]["required"] == 288
    assert gates["resource_frontier"]["passed"] is False
    assert gates["formal_run_denominator"]["observed"] == 0
    assert gates["formal_run_denominator"]["required"] == 9
    assert gates["phase_plan_denominator"]["passed"] is True
    assert gates["evaluator_failure_penalty"]["passed"] is True


def test_verify_cli_is_read_only_and_detects_tampered_closure(tmp_path: Path) -> None:
    before = _sha256(REGISTRY)
    assert main([
        "--verify",
        "--data-root", str(ROOT),
        "--source-closure", str(CLOSURE),
        "--receipt", str(RECEIPT),
    ]) == 1
    assert _sha256(REGISTRY) == before

    tampered = json.loads(CLOSURE.read_text(encoding="utf-8"))
    tampered["files"][0]["sha256"] = "0" * 64
    assert verify_source_closure(tampered, data_root=ROOT)["ok"] is False
    assert _sha256(REGISTRY) == before


def test_resource_frontier_requires_explicit_capacity_evidence_not_blocker_absence() -> None:
    readiness = json.loads(
        (ROOT / "campaigns/core-v1/learning/core-formal-readiness-audit-20260921.json")
        .read_text(encoding="utf-8")
    )
    readiness["upstream_admission_blockers"] = []
    readiness["admission_audit"]["upstream_blockers"] = []
    gates = _gate_snapshot(readiness, {})
    assert gates["resource_frontier"]["passed"] is False

    readiness["admission_audit"]["capacity_evidence"] = {
        "schema": "core.formal_capacity_evidence.v1",
        "valid": True,
        "formal_capacity_evidence": True,
        "formal_runs_counted": 0,
        "observed_update_frontier": 32000,
    }
    gates = _gate_snapshot(readiness, {})
    assert gates["resource_frontier"]["passed"] is True
