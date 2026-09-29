"""Focused tests for the non-authorizing formal-training admission join."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from scripts import core_formal_training_release_root_admission_v1 as admission


ROOT = Path(__file__).resolve().parents[1]


def _current_report() -> dict:
    return admission.build_report(ROOT)


def test_current_join_reports_the_real_five_input_gap_and_stays_closed() -> None:
    report = _current_report()

    assert report["schema"] == admission.SCHEMA
    assert report["scope"]["run_count"] == 9
    assert report["missing_blockers"] == [
        "FORMAL_DATASET_RELEASE_NOT_GRANTED",
        "TRUSTED_ROOT_ATTESTATION_MISSING",
        "TRUSTED_ROOT_AUTHENTICATION_NOT_INTEGRATED",
        "SOURCE_CLOSURE_RELEASE_OR_ROOT_GATE_MISSING",
        "TERMINAL_EVIDENCE_MATRIX_MISSING",
        "TERMINAL_ARTIFACT_REVERIFICATION_NOT_INTEGRATED",
        "MATRIX_TRUSTED_ROOT_ROLE_REFERENCE_MISSING",
        "MATRIX_TERMINAL_EVIDENCE_ROLE_REFERENCE_MISSING",
    ]
    assert report["cross_bindings"]["dataset_manifest_to_matrix"] is True
    assert report["cross_bindings"]["source_closure_to_matrix"] is True
    assert report["cross_bindings"]["trusted_root_role_to_matrix"] is False
    assert report["cross_bindings"]["terminal_evidence_role_to_matrix"] is False
    assert report["decision"]["launch_allowed"] is False
    assert report["decision"]["formal_eligible"] is False
    assert report["decision"]["credit"] == 0
    assert report["execution_constraints"]["hdf5_opened"] is False
    assert report["execution_constraints"]["checkpoint_opened"] is False
    assert admission.validate_report(report, ROOT) == []


def test_matrix_scope_mutation_is_rejected_without_replaying_a_run_auditor() -> None:
    matrix_path = ROOT / admission.DEFAULT_INPUT_PATHS["model_seed_matrix"]
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    matrix["scope"]["run_ids"][0] = "graph_raw-seed999"

    observation = admission._matrix_observation(matrix)

    assert observation["matrix_valid"] is False
    assert observation["rows_exact"] is True
    assert observation["scope_checks"]["run_ids_exact"] is False


def test_caller_root_claim_is_never_promoted_to_authenticated_trust() -> None:
    expected = {
        "dataset_manifest_sha256": "1" * 64,
        "source_closure_file_sha256": "2" * 64,
        "source_closure_sha256": "3" * 64,
        "terminal_evidence_sha256": "4" * 64,
        "model_seed_matrix_sha256": "5" * 64,
    }
    payload = {
        "schema": admission.TRUSTED_ROOT_SCHEMA,
        "status": "verified",
        "trusted_root": {
            "authority": "external_root",
            "authenticated": True,
            "signature_verified": True,
            "attestation": {"signature": "synthetic"},
        },
        "decision": {"granted": True, "subject": dict(expected)},
    }

    observation = admission._root_observation(payload, expected_subject=expected)

    assert observation["structurally_bound"] is True
    assert observation["trusted_root_authenticated"] is False
    assert observation["admission_ready"] is False


def test_synthetic_terminal_matrix_can_be_shape_bound_but_never_authorizes() -> None:
    report = _current_report()
    references = {
        role: report["inputs"][role]["reference"]
        for role in report["inputs"]
    }
    matrix = json.loads(
        (ROOT / admission.DEFAULT_INPUT_PATHS["model_seed_matrix"]).read_text(
            encoding="utf-8"
        )
    )
    rows = []
    for run_id in admission.RUN_IDS:
        model, seed_text = run_id.rsplit("-seed", 1)
        rows.append({
            "run_id": run_id,
            "model": model,
            "seed": int(seed_text),
            "status": "terminal",
            "terminal_evidence": True,
            "evidence": {"path": f"synthetic/{run_id}.json", "sha256": "a" * 64, "bytes": 1},
        })
    terminal = {
        "schema": admission.TERMINAL_EVIDENCE_SCHEMA,
        "status": "terminal_matrix",
        "dataset_manifest_sha256": references["formal_dataset_release_manifest"]["sha256"],
        "source_closure_file_sha256": references["source_closure"]["sha256"],
        "trusted_root_sha256": references["trusted_root"]["sha256"],
        "model_seed_matrix_sha256": references["model_seed_matrix"]["sha256"],
        "runs": rows,
    }

    observation = admission._terminal_observation(
        terminal,
        dataset_ref=references["formal_dataset_release_manifest"],
        closure_ref=references["source_closure"],
        root_ref=references["trusted_root"],
        matrix_ref=references["model_seed_matrix"],
        matrix_payload=matrix,
    )

    assert observation["complete"] is True
    assert observation["terminal_artifacts_reverified"] is False
    assert observation["admission_ready"] is False


def test_report_validator_rejects_permission_mutation() -> None:
    report = deepcopy(_current_report())
    report["decision"]["credit"] = 1
    report["decision"]["formal_eligible"] = True
    report["decision"]["launch_allowed"] = True

    errors = admission.validate_report(report, ROOT)

    assert "decision launch_allowed is not fail-closed" in errors
    assert "decision formal_eligible is not fail-closed" in errors
    assert "decision credit is not fail-closed" in errors


def test_checked_in_gap_report_and_campaign_are_planning_only() -> None:
    report_path = ROOT / admission.REPORT_REL
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert admission.validate_report(report, ROOT) == []

    campaign_path = ROOT / (
        "campaigns/core-v1/learning/"
        "core-formal-training-release-root-admission-v1.json"
    )
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    assert campaign["synthetic_only"] is True
    assert campaign["status"] == "planning_only_blocked"
    assert campaign["default_decision"] == {
        "launch_allowed": False,
        "formal_eligible": False,
        "qualification_credit": 0,
        "credit": 0,
        "non_authorizing": True,
    }
