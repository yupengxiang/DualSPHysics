"""Synthetic mutation tests for the A8 full-product/root/host join gap."""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest

from scripts import a8_full_product_external_host_root_join_gap_v1 as contract


def _report(projection: dict) -> dict:
    return contract.build_report(projection)


def test_synthetic_join_binds_full_product_chain_and_stays_fail_closed():
    report = _report(contract.synthetic_projection())

    assert report["status"] == contract.STRUCTURAL_BLOCKED_STATUS
    assert report["passed"] is True
    assert report["structural_contract_passed"] is True
    assert report["checks"] == {
        "package_run_identity": True,
        "reader_prediction_scoring_chain": True,
        "distinct_data_root_identity": True,
        "trusted_root_cross_binding": True,
        "external_host_cross_binding": True,
        "full_product_receipt_cross_binding": True,
        "cross_binding_identity": True,
        "trusted_root_authenticated": False,
        "external_host_attested": False,
        "full_product_terminal_receipt": False,
    }
    assert report["diagnostic_only"] is True
    assert report["readiness_pass"] is False
    assert report["independent_reproduction"] is False
    assert report["credit"] == 0
    assert report["qualification_credit"] == 0
    assert report["mutations"] == contract.ZERO_MUTATIONS
    assert report["execution_constraints"] == contract.EXECUTION_CONSTRAINTS
    assert contract.validate_report(report) == []


@pytest.mark.parametrize(
    ("section", "field", "value", "error_code"),
    [
        (
            "external_host_attestation",
            "artifact_chain_sha256",
            "0" * 64,
            "EXTERNAL_HOST_ARTIFACT_CHAIN_MISMATCH",
        ),
        (
            "trusted_root_review",
            "source_manifest_sha256",
            "0" * 64,
            "TRUSTED_ROOT_MANIFEST_MISMATCH",
        ),
        (
            "full_product_join_receipt",
            "artifact_chain_sha256",
            "0" * 64,
            "JOIN_ARTIFACT_CHAIN_MISMATCH",
        ),
        (
            "external_host_attestation",
            "attempt_id",
            "caller-mutated-attempt",
            "PACKAGE_RUN_ID_MISMATCH",
        ),
        (
            "full_product_join_receipt",
            "full_product_reproduction",
            True,
            "FULL_PRODUCT_CLAIM_FORBIDDEN",
        ),
    ],
)
def test_cross_component_mutations_fail_closed(section, field, value, error_code):
    projection = copy.deepcopy(contract.synthetic_projection())
    projection[section][field] = value

    report = _report(projection)

    assert report["passed"] is False
    assert report["structural_contract_passed"] is False
    assert report["errors"][0]["code"] == error_code
    assert report["independent_reproduction"] is False
    assert report["credit"] == 0
    assert contract.validate_report(report) == []


@pytest.mark.parametrize(
    ("field", "error_code"),
    [
        ("data_root", "PACKAGE_DATA_ROOTS_NOT_DISTINCT"),
        ("physical_host_id", "PACKAGE_PHYSICAL_HOSTS_NOT_DISTINCT"),
    ],
)
def test_package_duplicate_identity_is_rejected(field, error_code):
    projection = copy.deepcopy(contract.synthetic_projection())
    projection["package_boundary"]["source"][field] = projection["package_boundary"][
        "reproduction"
    ][field]

    report = _report(projection)

    assert report["passed"] is False
    assert report["errors"][0]["code"] == error_code
    assert report["credit"] == 0


def test_cross_binding_digest_drift_is_rejected():
    projection = copy.deepcopy(contract.synthetic_projection())
    projection["external_host_attestation"]["cross_binding_sha256"] = "0" * 64

    report = _report(projection)

    assert report["passed"] is False
    assert report["errors"][0]["code"] == "CROSS_BINDING_HASH_MISMATCH"
    assert report["credit"] == 0


def test_unknown_caller_authority_field_is_rejected():
    projection = copy.deepcopy(contract.synthetic_projection())
    projection["full_product_join_receipt"]["trusted_root"] = True

    report = _report(projection)

    assert report["passed"] is False
    assert report["errors"][0]["code"] == "FIELDS_NOT_EXACT"
    assert report["independent_reproduction"] is False


def test_terminal_receipt_claim_is_rejected():
    projection = copy.deepcopy(contract.synthetic_projection())
    projection["full_product_join_receipt"]["terminal_receipt_present"] = True
    projection["full_product_join_receipt"]["terminal_receipt_sha256"] = "a" * 64

    report = _report(projection)

    assert report["passed"] is False
    assert report["errors"][0]["code"] == "FULL_PRODUCT_CLAIM_FORBIDDEN"
    assert report["credit"] == 0


def test_report_validator_rejects_claim_drift():
    report = _report(contract.synthetic_projection())
    report["credit"] = 1

    errors = contract.validate_report(report)

    assert "report.credit must remain 0" in errors


def test_cli_synthetic_audit_and_validate(tmp_path: Path):
    report_path = tmp_path / "a8-full-product-root-join.json"

    assert contract.main([
        "audit", "--synthetic", "--output", str(report_path),
    ]) == 0
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["status"] == contract.STRUCTURAL_BLOCKED_STATUS
    assert payload["readiness_pass"] is False
    assert payload["checks"]["reader_prediction_scoring_chain"] is True
    assert payload["checks"]["trusted_root_authenticated"] is False
    assert contract.main(["validate", "--report", str(report_path)]) == 0


def test_cli_rejects_symlinked_projection(tmp_path: Path):
    target = tmp_path / "projection.json"
    target.write_text(
        json.dumps(contract.synthetic_projection(), sort_keys=True), encoding="utf-8"
    )
    link = tmp_path / "projection-link.json"
    link.symlink_to(target)
    output = tmp_path / "report.json"

    assert contract.main([
        "audit", "--input", str(link), "--output", str(output),
    ]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == contract.INVALID_BLOCKED_STATUS
    assert payload["errors"][0]["code"] == "FILE_OPEN_FAILED"
    assert contract.validate_report(payload) == []


def test_cli_rejects_symlinked_report(tmp_path: Path):
    target = tmp_path / "report.json"
    contract.write_json(target, _report(contract.synthetic_projection()))
    link = tmp_path / "report-link.json"
    link.symlink_to(target)

    assert contract.main(["validate", "--report", str(link)]) == 1


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
    assert "Popen" not in source
    assert "nvidia-smi" not in source
