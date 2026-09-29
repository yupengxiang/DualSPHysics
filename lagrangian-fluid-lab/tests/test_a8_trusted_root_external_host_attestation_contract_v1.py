"""Synthetic-only tests for the A8 attestation cross-binding boundary."""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest

from scripts import a8_trusted_root_external_host_attestation_contract_v1 as contract


def test_synthetic_projection_cross_binds_but_stays_fail_closed():
    report = contract.build_report(contract.synthetic_projection())

    assert report["status"] == (
        "blocked_missing_trusted_root_external_host_and_"
        "non_diagnostic_full_product_receipt"
    )
    assert report["passed"] is True
    assert report["structural_contract_passed"] is True
    assert report["readiness_pass"] is False
    assert report["independent_reproduction"] is False
    assert report["credit"] == 0
    assert report["qualification_credit"] == 0
    assert report["checks"] == {
        "distinct_data_root_identity": True,
        "trusted_root_review_cross_binding": True,
        "external_host_attestation_cross_binding": True,
        "non_diagnostic_full_product_receipt_cross_binding": True,
        "cross_binding_identity": True,
        "trusted_root_review": False,
        "external_host_attestation": False,
        "non_diagnostic_full_product_receipt": False,
    }
    assert report["mutations"] == contract.ZERO_MUTATIONS
    assert report["execution_constraints"] == contract.EXECUTION_CONSTRAINTS
    assert contract.validate_report(report) == []


@pytest.mark.parametrize(
    ("section", "field", "value", "error_code"),
    [
        ("trusted_root_review", "authenticated", True, "TRUSTED_ROOT_CLAIM_FORBIDDEN"),
        ("external_host_attestation", "attested", True, "EXTERNAL_HOST_CLAIM_FORBIDDEN"),
        ("full_product_receipt", "non_diagnostic", True, "FULL_PRODUCT_CLAIM_FORBIDDEN"),
        ("full_product_receipt", "full_product", True, "FULL_PRODUCT_CLAIM_FORBIDDEN"),
    ],
)
def test_attestation_claims_are_never_promoted(section, field, value, error_code):
    projection = copy.deepcopy(contract.synthetic_projection())
    projection[section][field] = value

    report = contract.build_report(projection)

    assert report["passed"] is False
    assert report["readiness_pass"] is False
    assert report["independent_reproduction"] is False
    assert report["credit"] == 0
    assert report["errors"][0]["code"] == error_code
    assert contract.validate_report(report) == []


def test_cross_binding_hash_drift_is_fail_closed():
    projection = copy.deepcopy(contract.synthetic_projection())
    projection["external_host_attestation"]["cross_binding_sha256"] = "0" * 64

    report = contract.build_report(projection)

    assert report["passed"] is False
    assert report["errors"][0]["code"] == "CROSS_BINDING_HASH_MISMATCH"
    assert report["credit"] == 0


@pytest.mark.parametrize(
    ("section", "field", "value", "error_code"),
    [
        ("data_root_identity", "reproduction_host_id", "synthetic-source-host", "HOSTS_NOT_DISTINCT"),
        ("data_root_identity", "reproduction_data_root", "/synthetic/core/source-root", "DATA_ROOTS_NOT_DISTINCT"),
        ("trusted_root_review", "source_identity_sha256", "0" * 64, "TRUSTED_ROOT_IDENTITY_MISMATCH"),
        ("external_host_attestation", "host_id", "synthetic-source-host", "EXTERNAL_HOST_ID_MISMATCH"),
        ("full_product_receipt", "reproduction_identity_sha256", "0" * 64, "FULL_PRODUCT_IDENTITY_MISMATCH"),
    ],
)
def test_cross_component_identity_mismatch_is_rejected(section, field, value, error_code):
    projection = copy.deepcopy(contract.synthetic_projection())
    projection[section][field] = value

    report = contract.build_report(projection)

    assert report["passed"] is False
    assert report["errors"][0]["code"] == error_code
    assert report["readiness_pass"] is False
    assert report["credit"] == 0


def test_exact_schema_rejects_untrusted_authority_field():
    projection = copy.deepcopy(contract.synthetic_projection())
    projection["trusted_root_review"]["trusted_root"] = True

    report = contract.build_report(projection)

    assert report["passed"] is False
    assert report["errors"][0]["code"] == "FIELDS_NOT_EXACT"
    assert report["independent_reproduction"] is False


def test_cli_synthetic_audit_and_validate(tmp_path: Path):
    report_path = tmp_path / "a8-attestation.json"

    assert contract.main([
        "audit", "--synthetic", "--output", str(report_path),
    ]) == 0
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["readiness_pass"] is False
    assert payload["independent_reproduction"] is False
    assert payload["bindings"]["trusted_root_authenticated"] is False
    assert payload["bindings"]["external_host_attested"] is False
    assert payload["bindings"]["full_product_receipt_present"] is False
    assert contract.main(["validate", "--report", str(report_path)]) == 0
    report_link = tmp_path / "a8-attestation-link.json"
    report_link.symlink_to(report_path)
    assert contract.main(["validate", "--report", str(report_link)]) == 1


def test_report_validator_rejects_claim_drift():
    report = contract.build_report(contract.synthetic_projection())
    report["credit"] = 1

    assert "report.credit must remain 0" in contract.validate_report(report)


def test_report_validator_rejects_forged_binding_authority_and_digest():
    report = contract.build_report(contract.synthetic_projection())
    report["bindings"]["external_host_attested"] = True
    report["bindings"]["cross_binding_sha256"] = "0" * 64

    errors = contract.validate_report(report)

    assert "report.bindings.external_host_attested must remain false" in errors
    assert "report.bindings.cross_binding_sha256 mismatch" in errors


def test_cli_rejects_symlinked_projection_before_contract_evaluation(tmp_path: Path):
    target = tmp_path / "projection.json"
    target.write_text(json.dumps(contract.synthetic_projection()), encoding="utf-8")
    link = tmp_path / "projection-link.json"
    link.symlink_to(target)
    output = tmp_path / "report.json"

    assert contract.main([
        "audit", "--input", str(link), "--output", str(output),
    ]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "blocked_invalid_or_untrusted_projection"
    assert payload["errors"][0]["code"] == "FILE_OPEN_FAILED"


def test_report_validator_rejects_forged_status_and_structural_pass():
    report = contract.build_report(contract.synthetic_projection())
    report.update({
        "status": "trusted_external_host_ready",
        "passed": True,
        "structural_contract_passed": True,
    })

    errors = contract.validate_report(report)

    assert "report.status is unsupported" in errors


def test_module_has_no_operational_probe_imports():
    source = Path(contract.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint({"subprocess", "socket", "psutil", "torch", "h5py"})
    assert "nvidia-smi" not in source
