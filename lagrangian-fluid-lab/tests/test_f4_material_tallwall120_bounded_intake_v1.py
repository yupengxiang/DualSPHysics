"""CPU-only tests for the non-authorizing F4 Tallwall120 bounded intake."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

from scripts import f4_material_tallwall120_bounded_intake_v1 as module


ROOT = module.LAB_ROOT


def test_current_receipts_are_fail_closed_and_zero_credit() -> None:
    report = module.build_report(ROOT)

    assert report["schema"] == module.SCHEMA
    assert report["status"] == "blocked_fail_closed"
    assert report["structural_intake"]["structural_intake_ready"] is False
    assert report["authorization"] == {
        "structural_intake_ready": False,
        "launch_admitted": False,
        "worker_launch_authorized": False,
        "actual_sidecar_execution_allowed": False,
        "formal": False,
        "formal_eligible": False,
        "qualification": False,
        "T1": False,
        "T2": False,
        "T2_macro": False,
        "T2_path": False,
        "credit": 0,
        "qualification_credit": 0,
    }
    assert report["case_matrix"]["expected_case_count"] == 32
    assert len(report["case_matrix"]["case_rows"]) == 32
    assert report["case_matrix"]["observed_sidecar_count"] == 0
    assert report["case_matrix"]["complete_sidecar_count"] == 0
    assert len(report["case_matrix"]["missing_case_ids"]) == 32
    assert "source_collection_archives_v1_vs_archives_v2_drift" in report["blockers"]
    assert "missing_or_invalid_root_scheduler_receipts" in report["blockers"]
    assert "missing_or_incomplete_terminal_evidence" in report["blockers"]
    assert "missing_or_incomplete_32_case_sidecars" in report["blockers"]


def test_source_root_scheduler_terminal_blockers_are_explicit() -> None:
    report = module.build_report(ROOT)

    assert report["source"]["checks"]["reader_manifest_sha_exact"] is False
    assert report["source"]["checks"]["archives_receipt_path_exact"] is False
    root = report["authority_blockers"]["root_scheduler"]
    assert root["fresh_root_receipt_present"] is False
    assert root["scheduler_receipt_present"] is False
    assert root["scheduler_owned_host_io_valid"] is False
    terminal = report["authority_blockers"]["terminal"]
    assert terminal["fresh_terminal_present"] is False
    assert terminal["event_window_complete"] is False
    assert report["required_external_receipts"][-1]["present"] is False


def test_every_case_is_source_bound_to_the_fixed_matrix() -> None:
    report = module.build_report(ROOT)
    rows = report["case_matrix"]["case_rows"]

    assert [row["case_id"] for row in rows] == list(module.CASE_IDS)
    assert [row["split"] for row in rows] == list(module.CASE_SPLITS)
    assert all(row["credit"] == 0 for row in rows)
    assert all("missing_or_incomplete_material_sidecar" in row["blocking_reasons"] for row in rows)
    assert all("source_path_drift" in row["blocking_reasons"] for row in rows)


def test_structural_pass_cannot_mint_launch_or_t2() -> None:
    payloads = {name: {} for name in module.INPUTS}
    # Start from the real receipts so the test remains coupled to their
    # schema, then remove only the known blockers from the in-memory projection
    # to exercise the unconditional authorization boundary.
    for name, spec in module.INPUTS.items():
        payloads[name] = json.loads((ROOT / spec["path"]).read_text(encoding="utf-8"))
    matrix = payloads["sidecar_matrix"]
    matrix["fixed_matrix"]["case_ids"] = list(module.CASE_IDS)
    matrix["fixed_matrix"]["case_splits"] = dict(module.EXPECTED_CASE_SPLITS)
    matrix["scope"]["case_count"] = module.CASE_COUNT
    matrix["matrix_summary"].update(
        {
            "observed_sidecar_count": module.CASE_COUNT,
            "complete_sidecar_count": module.CASE_COUNT,
            "full_event_window_complete_count": module.CASE_COUNT,
            "mass_closed_count": module.CASE_COUNT,
            "unknown_fraction_pass_count": module.CASE_COUNT,
            "reliable_coverage_pass_count": module.CASE_COUNT,
            "right_censor_clear_count": module.CASE_COUNT,
            "split_counts_observed": dict(module.EXPECTED_SPLIT_COUNTS),
        }
    )
    matrix["source_binding"]["reader"].update({"path_exact": True, "sha256_exact": True})
    matrix["source_binding"]["dev07"].update(
        {
            "collection_source_hdf5": module.SOURCE_PATH,
            "proposal_source_hdf5": module.SOURCE_PATH,
            "collection_source_sha256": module.SOURCE_SHA256,
            "proposal_source_sha256": module.SOURCE_SHA256,
        }
    )
    for row in matrix["source_binding"]["source_matrix"]:
        row["collection_source_path"] = row["expected_source_path"]
        row["source_exact"] = True
    for row in matrix["material_sidecars"]["cases"]:
        row["status"] = "complete"
        row["material_markers"] = {
            "mass_closure_pass": True,
            "unknown_fraction_pass": True,
            "reliable_coverage_pass": True,
            "right_censor_pass": True,
        }
    payloads["source_drift"]["source_reconciliation"]["ready"] = True
    payloads["receipt_consistency"]["archives_path_binding"].update(
        {"exact_path_match": True, "source_sha256_match": True}
    )
    payloads["root_scheduler"]["validation"]["checks"].update(
        {
            "source_identity_contract_valid": True,
            "reader_identity_bound": True,
            "future_root_receipt_present": True,
            "future_root_receipt_valid": True,
            "future_scheduler_receipt_present": True,
            "future_scheduler_receipt_valid": True,
            "receipt_pair_cross_binding_valid": True,
            "scheduler_owned_host_io_reservation_valid": True,
        }
    )
    payloads["terminal_evidence"]["terminal_evidence_intake"].update(
        {
            "present": True,
            "status": "complete",
            "gate_projection": {
                "event_window_complete": True,
                "mass_closure": True,
                "unknown_gate": True,
                "reliable_coverage": True,
                "right_censor_clear": True,
            },
        }
    )
    payloads["terminal_evidence"]["fresh_attempt_contract"]["terminal_evidence_ref"]["exists"] = True
    payloads["case_sidecar_intake"]["case_sidecar_intake"].update({"present": True, "status": "complete"})
    payloads["case_sidecar_intake"]["source_binding"]["proposal_target"].update(
        {"source_hdf5": module.SOURCE_PATH, "source_sha256": module.SOURCE_SHA256}
    )
    result = module.evaluate_receipts(payloads)

    assert result["structural_intake"]["structural_intake_ready"] is True
    assert result["status"] == "structural_intake_ready_non_authorizing"
    assert result["authorization"]["launch_admitted"] is False
    assert result["authorization"]["worker_launch_authorized"] is False
    assert result["authorization"]["T2_macro"] is False
    assert result["authorization"]["T2_path"] is False
    assert result["authorization"]["credit"] == 0


def test_hdf5_and_effect_boundary_is_fail_closed() -> None:
    payloads = {name: {} for name in module.INPUTS}
    payloads["readiness_projection"] = {"input_boundary": {"production_hdf5_content_read": True}}
    result = module.evaluate_receipts(payloads)

    assert result["structural_intake"]["structural_intake_ready"] is False
    assert result["authorization"]["launch_admitted"] is False
    assert result["authorization"]["credit"] == 0
    assert "forbidden_effect_or_credit_observed" in result["blockers"]


def test_missing_input_is_reported_without_authorization(tmp_path: Path) -> None:
    root = tmp_path / "lab"
    (root / "reports").mkdir(parents=True)
    report = module.build_report(root)

    assert report["status"] == "blocked_fail_closed"
    assert report["input_boundary"]["input_errors"]
    assert report["authorization"]["launch_admitted"] is False
    assert report["authorization"]["credit"] == 0


def test_symlink_and_hardlink_inputs_are_not_consumed(tmp_path: Path) -> None:
    root = tmp_path / "lab"
    reports = root / "reports"
    reports.mkdir(parents=True)
    real = reports / "real.json"
    real.write_text(json.dumps({"schema": module.INPUTS["readiness_projection"]["schema"]}), encoding="utf-8")
    alias = reports / module.INPUTS["readiness_projection"]["path"].name
    alias.symlink_to(real)
    report = module.build_report(root)
    assert "readiness_projection:symlink_path" in report["input_boundary"]["input_errors"]

    alias.unlink()
    os.link(real, alias)
    report = module.build_report(root)
    assert "readiness_projection:hardlink_file" in report["input_boundary"]["input_errors"]


def test_report_validator_keeps_non_authorizing_boundary() -> None:
    report = module.build_report(ROOT)
    assert module.validate_report(report) == []

    forged = copy.deepcopy(report)
    forged["authorization"]["launch_admitted"] = True
    assert "authorization.launch_admitted" in module.validate_report(forged)
