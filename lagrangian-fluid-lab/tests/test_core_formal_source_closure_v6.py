"""Read-only regression tests for the current v6 formal source closure."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.core_formal_source_closure_admission_v6 import (
    REQUIRED_CODE_FILES,
    _readiness_gates,
    verify_admission,
    verify_source_closure,
)


ROOT = Path(__file__).resolve().parents[1]
NAMESPACE = ROOT / "campaigns/core-v1/learning/formal-release-candidate-v6"
CLOSURE = NAMESPACE / "source-closure.json"
AUDIT = NAMESPACE / "source-closure-audit.json"
RECEIPT = NAMESPACE / "root-admission-receipt.json"
REGISTRY = ROOT / "campaigns/core-v1/registry.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v6_rehash_mismatch_remains_fail_closed_and_planning_only() -> None:
    closure = json.loads(CLOSURE.read_text(encoding="utf-8"))
    result = verify_source_closure(closure, data_root=ROOT)

    # The immutable v6 artifact predates the current public-reader/F7
    # contracts.  Live verification must therefore reject it rather than
    # silently treating a stale closure as a formal source snapshot.
    assert result["ok"] is False
    assert result["mismatch_files"] == [
        "scripts/core_cfd_dataset.py", "scripts/core_contract.py",
        "scripts/core_dataset.py", "scripts/core_evaluation.py",
        "scripts/core_formal_planner.py", "scripts/core_learning.py",
        "scripts/core_models.py"
    ]
    assert closure["schema"] == "core.formal_source_closure.v2"
    assert closure["namespace"] == "core-formal-release-candidate-v6"
    assert closure["required_files"] == list(REQUIRED_CODE_FILES)
    assert closure["formal_release"] is False
    assert closure["formal_training_allowed"] is False
    assert closure["formal_job_count"] == 0
    assert closure["root_admission_granted"] is False
    assert closure["closure_sha256"] == "d692701964bfd4d0ddaa2db437b8870a2ea71e4ffbb428282398573aa89a05ba"
    for row in closure["files"]:
        path = ROOT / row["relative_path"]
        if row["relative_path"] in result["mismatch_files"]:
            assert row["sha256"] != _sha256(path) or row["bytes"] != path.stat().st_size
        else:
            assert row["sha256"] == _sha256(path)
            assert row["bytes"] == path.stat().st_size


def test_v6_audit_labels_v5_differences_as_historical_only() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))

    assert audit["schema"] == "core.formal_source_closure_audit.v2"
    assert audit["namespace"] == "core-formal-release-candidate-v6"
    assert audit["status"] == "proposal_only_blocked"
    assert audit["historical_comparison"]["comparison_type"] == "historical_baseline_only"
    assert audit["historical_comparison"]["v6_current_closure_is_not_historical_baseline"] is True
    assert audit["checks"]["v6_source_closure_rehashed"] is True
    assert audit["checks"]["root_admission_granted"] is False
    assert audit["formal_job_count"] == 0
    assert audit["launch_allowed"] is False
    assert audit["execution_constraints"]["registry_written"] is False
    assert audit["execution_constraints"]["ledger_written"] is False


def test_v6_receipt_is_hash_bound_and_has_no_execution_side_effects() -> None:
    before = _sha256(REGISTRY)
    result = verify_admission(data_root=ROOT, source_closure=CLOSURE, receipt=RECEIPT)
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))

    assert result["ok"] is False
    assert result["checks"]["closure_verification"] is False
    assert receipt["schema"] == "core.formal_source_closure_admission.v2"
    assert receipt["namespace"] == "core-formal-release-candidate-v6"
    assert receipt["formal_release"] is False
    assert receipt["formal_training_allowed"] is False
    assert receipt["formal_job_count"] == 0
    assert receipt["required_formal_job_count"] == 9
    assert receipt["launch_allowed"] is False
    assert receipt["root_admission"]["granted"] is False
    assert receipt["gate_evaluation"]["third_t1_family"]["observed"] == 2
    assert receipt["gate_evaluation"]["third_t1_family"]["required"] == 3
    assert receipt["gate_evaluation"]["formal_run_denominator"]["observed"] == 0
    assert receipt["gate_evaluation"]["formal_run_denominator"]["required"] == 9
    assert receipt["execution_constraints"]["registry_written"] is False
    assert receipt["execution_constraints"]["ledger_written"] is False
    assert receipt["execution_constraints"]["formal_runs_started"] == 0
    assert receipt["execution_constraints"]["gpu_started"] is False
    assert receipt["execution_constraints"]["solver_started"] is False
    assert _sha256(REGISTRY) == before


def test_v6_sidecars_bind_the_three_immutable_json_products() -> None:
    for payload in (CLOSURE, AUDIT, RECEIPT):
        sidecar = payload.with_name(payload.name + ".sha256")
        assert sidecar.is_file()
        assert sidecar.read_text(encoding="utf-8").split()[0] == _sha256(payload)


def test_v6_resource_frontier_requires_explicit_capacity_evidence() -> None:
    readiness = json.loads(
        (ROOT / "campaigns/core-v1/learning/core-formal-readiness-audit-20260921.json")
        .read_text(encoding="utf-8")
    )
    readiness["upstream_admission_blockers"] = []
    readiness["admission_audit"]["upstream_blockers"] = []
    gates = _readiness_gates(readiness)
    assert gates["resource_frontier"]["passed"] is False

    readiness["admission_audit"]["capacity_evidence"] = {
        "schema": "core.formal_capacity_evidence.v1",
        "valid": True,
        "formal_capacity_evidence": True,
        "formal_runs_counted": 0,
        "observed_update_frontier": 32000,
    }
    gates = _readiness_gates(readiness)
    assert gates["resource_frontier"]["passed"] is True
