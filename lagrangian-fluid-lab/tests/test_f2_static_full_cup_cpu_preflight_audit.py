"""Regression tests for the read-only F2 static CPU/native closure audit."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.f2_static_full_cup_cpu_preflight_audit import _audit_cell, audit


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "campaigns/core-v1/cfd/f2-static-full-cup-volume-hold-candidate-v1.json"
ADMISSION = ROOT / "campaigns/core-v1/cfd/f2-static-full-cup-qualification-admission-v1.json"
ROOT_REVIEW = ROOT / "campaigns/core-v1/cfd/f2-static-full-cup-root-review-v1.json"
SCOPE_REVIEW = ROOT / "campaigns/core-v1/cfd/f2-static-full-cup-root-scope-review-v1.json"
MATRIX = ROOT / "campaigns/core-v1/cfd/f2-static-full-cup-matrix-prepared-v4/matrix-preparation.json"
MATRIX_AUDIT = ROOT / "campaigns/core-v1/cfd/f2-static-full-cup-matrix-prepared-v4/matrix-preparation-audit.json"
AUDIT_ARTIFACT = ROOT / "campaigns/core-v1/evidence/f2-static-full-cup-cpu-preflight-v1.json"


def _real_audit() -> dict:
    return audit(
        lab_root=ROOT,
        candidate=CANDIDATE,
        admission=ADMISSION,
        root_review=ROOT_REVIEW,
        scope_review=SCOPE_REVIEW,
        matrix_report=MATRIX,
        matrix_audit=MATRIX_AUDIT,
    )


def test_existing_v4_closure_is_15_of_15_and_canary_reviewable() -> None:
    report = _real_audit()
    assert report["status"] == "ready_for_root_canary_review"
    assert report["blocker_codes"] == []
    denominator = report["failure_denominator"]
    assert denominator["registered_cell_count"] == 15
    assert denominator["included_cell_count"] == 15
    assert denominator["passed_cell_count"] == 15
    assert denominator["failed_or_unresolved_cell_count"] == 0
    assert denominator["all_rows_retained"] is True
    assert denominator["failed_rows_are_not_dropped"] is True
    assert denominator["survivor_renormalization"] is False
    assert all(row["status"] == "passed" for row in denominator["rows"])
    assert all(row["resource"]["hash_closure_declared_count"] == 23 for row in denominator["rows"])
    assert all(row["resource"]["hash_closure_verified_count"] == 23 for row in denominator["rows"])
    assert report["scope"]["dynamic_qualification_admitted"] is False
    assert report["canary_recommendation"]["first_cell_index"] == 0
    assert report["canary_recommendation"]["worth_requesting_separate_root_approval"] is True
    assert report["canary_recommendation"]["current_runtime_authorized"] is False
    assert report["execution_constraints"]["solver_invoked"] is False
    assert report["execution_constraints"]["gpu_invoked"] is False
    assert report["execution_constraints"]["queue_mutation"] == 0
    assert report["execution_constraints"]["ledger_mutation"] == 0
    assert report["execution_constraints"]["registry_mutation"] == 0


def test_resource_observation_is_artifact_size_plus_reserved_envelope() -> None:
    report = json.loads(AUDIT_ARTIFACT.read_text(encoding="utf-8"))
    totals = report["resource_estimate"]["totals"]
    assert totals["observed_artifact_bytes"] > 1_000_000_000
    assert totals["maximum_cell_artifact_mib"] > 130.0
    assert totals["maximum_ram_mib_reserved"] == 24576
    assert totals["reservation_timeout_seconds_sum"] == 36000
    assert report["resource_estimate"]["gpu_fields_are_estimates_only"] is True
    assert "no solver/GPU timing" in totals["resource_measurement_scope"]


def test_a_tampered_row_remains_a_failed_denominator_entry() -> None:
    card = json.loads(CANDIDATE.read_text(encoding="utf-8"))
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    row = dict(matrix["cells"][0])
    row["prepared_sha256"] = "0" * 64
    denominator_row = dict(matrix["failure_denominator"]["rows"][0])
    result, _resource = _audit_cell(row, denominator_row, root=ROOT, candidate=card)
    assert result["status"] == "failed"
    assert result["denominator_included"] is True
    assert result["failure"]["type"] == "CPU_PREFLIGHT_AUDIT_FAILURE"
    assert any("prepared binding" in message for message in result["errors"])

