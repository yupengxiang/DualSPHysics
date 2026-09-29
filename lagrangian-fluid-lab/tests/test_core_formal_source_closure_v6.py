"""Read-only regression tests for the current v6 formal source closure."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest

from scripts.core_formal_source_closure_admission_v6 import (
    REQUIRED_CODE_FILES,
    _snapshot_comparison,
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


def _expected_mismatch(closure: dict, current_files: list[dict]) -> list[str]:
    old = {
        row["relative_path"]: row["sha256"]
        for row in closure.get("files", [])
        if isinstance(row, dict) and isinstance(row.get("relative_path"), str)
        and isinstance(row.get("sha256"), str)
    }
    now = {
        row["relative_path"]: row["sha256"]
        for row in current_files
        if isinstance(row, dict) and isinstance(row.get("relative_path"), str)
        and isinstance(row.get("sha256"), str)
    }
    return sorted(name for name in set(old) | set(now) if old.get(name) != now.get(name))


def test_v6_rehash_mismatch_remains_fail_closed_and_planning_only() -> None:
    closure = json.loads(CLOSURE.read_text(encoding="utf-8"))
    result = verify_source_closure(closure, data_root=ROOT)

    # The immutable v6 artifact predates the current public-reader/F7
    # contracts.  Live verification must therefore reject it rather than
    # silently treating a stale closure as a formal source snapshot.
    assert result["ok"] is False
    assert result["mismatch_files"] == _expected_mismatch(closure, result["current_files"])
    assert closure["schema"] == "core.formal_source_closure.v2"
    assert closure["namespace"] == "core-formal-release-candidate-v6"
    assert closure["required_files"] == [row["relative_path"] for row in closure["files"]]
    assert "scripts/core_strict_json.py" not in closure["required_files"]
    assert "scripts/core_strict_json.py" in REQUIRED_CODE_FILES
    assert closure["formal_release"] is False
    assert closure["formal_training_allowed"] is False
    assert closure["formal_job_count"] == 0
    assert result["checks"]["launch_is_closed"] is False
    assert closure["root_admission_granted"] is False
    assert closure["closure_sha256"] == "d692701964bfd4d0ddaa2db437b8870a2ea71e4ffbb428282398573aa89a05ba"
    for row in closure["files"]:
        path = ROOT / row["relative_path"]
        if row["relative_path"] in result["mismatch_files"]:
            assert row["sha256"] != _sha256(path) or row["bytes"] != path.stat().st_size
        else:
            assert row["sha256"] == _sha256(path)
            assert row["bytes"] == path.stat().st_size


def test_explicit_v7_namespace_is_planning_only_and_live_bound(tmp_path: Path) -> None:
    from scripts.core_formal_source_closure_admission_v6 import (
        build_audit,
        materialize_source_closure,
    )

    namespace = "core-formal-source-closure-v7-test"
    closure_path = tmp_path / "source-closure.json"
    closure = materialize_source_closure(data_root=ROOT, namespace=namespace)
    verification = verify_source_closure(closure, data_root=ROOT, namespace=namespace)
    assert verification["ok"] is True
    assert verification["checks"]["required_file_count"] is True
    assert verification["checks"]["launch_is_closed"] is True

    tampered = {**closure, "files": [*closure["files"], None]}
    tampered_verification = verify_source_closure(
        tampered, data_root=ROOT, namespace=namespace
    )
    assert tampered_verification["ok"] is False
    assert tampered_verification["checks"]["declared_rows_are_objects"] is False

    closure_path.write_text(json.dumps(closure), encoding="utf-8")
    audit = build_audit(
        data_root=ROOT,
        source_closure=closure_path,
        historical_snapshot=CLOSURE,
        readiness=ROOT / "campaigns/core-v1/learning/core-formal-readiness-audit-20260921.json",
        launch_contract=ROOT / "campaigns/core-v1/learning/core-formal-launch-contract-20260921.json",
        namespace=namespace,
        record_date="20990101",
    )
    assert audit["namespace"] == namespace
    assert audit["record_id"].endswith("20990101")
    assert audit["live_source_closure"]["namespace"] == namespace
    historical = json.loads(CLOSURE.read_text(encoding="utf-8"))
    assert audit["historical_baseline"]["closure_version"] == historical["closure_version"]
    assert audit["historical_comparison"]["comparison_type"] == "historical_baseline_only"
    assert audit["formal_release"] is False
    assert audit["formal_training_allowed"] is False
    assert audit["formal_job_count"] == 0
    assert audit["launch_allowed"] is False
    assert audit["root_admission_granted"] is False


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


@pytest.mark.parametrize("mutation, expected_error", [
    (lambda snapshot: snapshot.update(
        files=[snapshot["files"][0], snapshot["files"][0], snapshot["files"][1]]
    ), "file_count"),
    (lambda snapshot: snapshot.update(closure_sha256="0" * 64), "closure_sha256"),
])
def test_v6_historical_snapshot_integrity_rejects_duplicate_rows_and_bad_closure(
        mutation, expected_error) -> None:
    rows = [
        {"relative_path": "scripts/a.py", "sha256": "a" * 64, "bytes": 1},
        {"relative_path": "scripts/b.py", "sha256": "b" * 64, "bytes": 2},
    ]
    closure_sha256 = hashlib.sha256(json.dumps([
        {"relative_path": row["relative_path"], "sha256": row["sha256"]}
        for row in rows
    ], sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    current = {
        "required_files": [row["relative_path"] for row in rows],
        "files": rows,
        "closure_sha256": closure_sha256,
    }
    snapshot = {
        "schema": "core.formal_source_closure.v1",
        "closure_version": "test",
        "hash_algorithm": "sha256",
        "required_files": list(current["required_files"]),
        "files": [dict(row) for row in rows],
        "missing_files": [],
        "complete": True,
        "closure_sha256": closure_sha256,
    }
    mutation(snapshot)

    comparison = _snapshot_comparison(current, snapshot, {"path": "snapshot.json"})

    assert comparison["matches_current"] is False
    assert comparison["fresh_snapshot_required"] is True
    assert comparison["snapshot_integrity_valid"] is False
    assert expected_error in comparison["snapshot_integrity_errors"]
