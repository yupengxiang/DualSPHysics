"""Minimal regression tests for the bounded T1 typed-evidence gap intake."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from scripts import t1_observed_model_case_run_evidence_binding_v1 as intake


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / (
    "campaigns/core-v1/cfd/t1-evidence/"
    "observed-model-case-run-binding-v1.json"
)


def test_current_contract_produces_one_zero_credit_432_row_gap_inventory() -> None:
    report = intake.build_report(ROOT, CAMPAIGN)

    assert intake.validate_report(report) == []
    assert report["status"] == "typed_evidence_gap_fail_closed"
    assert report["observed_case_runs"] == 0
    assert report["required_case_runs"] == 432
    assert report["missing_case_runs"] == 432
    assert report["T1_numerical"] is False
    assert report["credit"] == 0
    assert report["fixed_t1_projection"]["family_counts"] == {"F3": 288, "F4": 144}
    assert len(report["fixed_t1_projection"]["rows"]) == 432
    assert {row["model_kind"] for row in report["fixed_t1_projection"]["rows"]} == set(intake.MODEL_KINDS)
    assert {row["seed"] for row in report["fixed_t1_projection"]["rows"]} == set(intake.SEEDS)
    codes = {item["code"] for item in report["gap_findings"]}
    assert "NO_OBSERVED_MODEL_CASE_RUN_RECEIPTS" in codes
    assert "MATRIX_PLANS_ARE_NOT_TERMINAL_EVIDENCE" in codes
    assert "F4_SOURCE_READER_MANIFEST_SHA_DRIFT" in codes
    assert report["input_boundary"]["hdf5_content_opened"] is False
    assert report["protected_state"] == {
        "registry_mutations": 0,
        "ledger_mutations": 0,
        "denominator_mutations": 0,
        "gate_mutations": 0,
        "completion_mutations": 0,
        "plan_mutations": 0,
    }


def test_candidate_without_typed_terminal_and_reader_is_blocked_without_observation() -> None:
    report = intake.build_report(ROOT, CAMPAIGN)
    expected = report["fixed_t1_projection"]["rows"][0]
    candidate = {
        "schema": intake.CANDIDATE_SCHEMA,
        "family": expected["family"],
        "scope_id": expected["scope_id"],
        "case_id": expected["case_id"],
        "split": expected["split"],
        "model_kind": expected["model_kind"],
        "seed": expected["seed"],
    }

    projection = intake.project_candidate(candidate, expected)

    assert projection["status"] == "blocked_fail_closed"
    assert projection["typed_binding_valid"] is False
    assert projection["observed_case_run"] is False
    assert projection["t1"] is False
    assert projection["credit"] == 0


def test_candidate_unknown_field_is_fail_closed() -> None:
    report = intake.build_report(ROOT, CAMPAIGN)
    expected = report["fixed_t1_projection"]["rows"][0]
    candidate = {"schema": intake.CANDIDATE_SCHEMA, "unexpected": True}

    with pytest.raises(intake.BindingError, match="unknown field"):
        intake.validate_candidate(candidate, expected)


def test_report_validation_rejects_any_observed_or_credit_mutation() -> None:
    report = intake.build_report(ROOT, CAMPAIGN)
    mutated = copy.deepcopy(report)
    mutated["observed_case_runs"] = 1
    assert "observed/required/missing fixed T1 counts drift" in intake.validate_report(mutated)
    mutated = copy.deepcopy(report)
    mutated["credit"] = 1
    assert "credit must be 0" in intake.validate_report(mutated)
