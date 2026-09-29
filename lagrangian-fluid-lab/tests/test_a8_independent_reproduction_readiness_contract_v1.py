"""Synthetic-only tests for the A8 readiness boundary."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import a8_independent_reproduction_readiness_contract_v1 as contract


def test_synthetic_projection_binds_data_roots_but_stays_fail_closed():
    report = contract.build_report(contract.synthetic_projection())

    assert report["status"] == "blocked_missing_trusted_root_and_external_host_attestation"
    assert report["passed"] is True
    assert report["structural_contract_passed"] is True
    assert report["readiness_pass"] is False
    assert report["checks"] == {
        "typed_preflight_projection": True,
        "data_root_identity_binding": True,
        "trusted_root_review": False,
        "external_host_attestation": False,
        "non_diagnostic_full_product_evidence": False,
    }
    assert report["independent_reproduction"] is False
    assert report["credit"] == 0
    assert report["qualification_credit"] == 0
    assert report["mutations"] == contract.ZERO_MUTATIONS
    assert report["execution_constraints"] == contract.EXECUTION_CONSTRAINTS
    assert contract.validate_report(report) == []


@pytest.mark.parametrize(
    ("section", "field", "value", "error_code"),
    [
        ("data_root_identity", "reproduction_identity_sha256", "0" * 64,
         "DATA_ROOT_IDENTITY_HASH_MISMATCH"),
        ("external_host_attestation", "attested", True,
         "EXTERNAL_HOST_CLAIM_FORBIDDEN"),
        ("trusted_root_review", "authenticated", True,
         "TRUSTED_ROOT_CLAIM_FORBIDDEN"),
    ],
)
def test_untrusted_or_drifted_claims_are_blocked(section, field, value, error_code):
    projection = copy.deepcopy(contract.synthetic_projection())
    projection[section][field] = value

    report = contract.build_report(projection)

    assert report["passed"] is False
    assert report["readiness_pass"] is False
    assert report["independent_reproduction"] is False
    assert report["credit"] == 0
    assert report["errors"][0]["code"] == error_code
    assert contract.validate_report(report) == []


def test_preflight_authority_claim_is_rejected():
    projection = copy.deepcopy(contract.synthetic_projection())
    projection["preflight"]["independent_reproduction"] = True

    report = contract.build_report(projection)

    assert report["passed"] is False
    assert report["errors"][0]["code"] == "PREFLIGHT_AUTHORITY_CLAIM"
    assert report["credit"] == 0


def test_root_identity_is_bound_to_preflight_roots_and_package():
    projection = copy.deepcopy(contract.synthetic_projection())
    projection["data_root_identity"]["source_data_root"] = "/synthetic/other-source"

    report = contract.build_report(projection)

    assert report["passed"] is False
    assert report["errors"][0]["code"] == "DATA_ROOT_PREFLIGHT_MISMATCH"
    assert report["independent_reproduction"] is False


def test_exact_schema_rejects_unknown_authority_fields():
    projection = copy.deepcopy(contract.synthetic_projection())
    projection["trusted_root_review"]["trusted_root"] = True

    report = contract.build_report(projection)

    assert report["passed"] is False
    assert report["errors"][0]["code"] == "FIELDS_NOT_EXACT"
    assert report["credit"] == 0


def test_cli_synthetic_audit_and_validate(tmp_path: Path):
    report_path = tmp_path / "a8-readiness.json"

    assert contract.main([
        "audit", "--synthetic", "--output", str(report_path),
    ]) == 0
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["readiness_pass"] is False
    assert payload["independent_reproduction"] is False
    assert contract.main(["validate", "--report", str(report_path)]) == 0


def test_report_validator_rejects_claim_drift():
    report = contract.build_report(contract.synthetic_projection())
    report["credit"] = 1

    assert "report.credit must remain 0" in contract.validate_report(report)


def test_report_validator_rejects_forged_status_and_structural_pass():
    report = contract.build_report(contract.synthetic_projection())
    report.update({
        "status": "trusted_external_host_ready",
        "passed": True,
        "structural_contract_passed": True,
    })

    errors = contract.validate_report(report)

    assert "report.status is unsupported" in errors
