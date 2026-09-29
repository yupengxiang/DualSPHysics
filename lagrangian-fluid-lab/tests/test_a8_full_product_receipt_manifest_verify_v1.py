import hashlib
import json
from pathlib import Path

import pytest

from scripts import a8_full_product_receipt_manifest_verify_v1 as verifier


def _write_json(path: Path, payload: dict) -> bytes:
    raw = (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


def _ref(path: Path, root: Path) -> dict:
    raw = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


def _fixture(tmp_path: Path) -> dict:
    root = tmp_path / "synthetic-a8-fixture"
    artifacts_dir = root / "artifacts"
    package_sha = "a" * 64
    common = {
        "package_id": "a8-synthetic-package-001",
        "case_id": "case-001",
        "attempt_id": "attempt-001",
        "nonce": "nonce-001",
        "package_sha256": package_sha,
        "host_id": "reproduction-host-001",
        "physical_host_id": "reproduction-physical-001",
        "data_root": "/synthetic/reproduction-001",
        "input_origin": verifier.INPUT_ORIGIN,
        "diagnostic_only": True,
        "full_product_reproduction": False,
        "independent_reproduction": False,
        "checkpoint": 0,
        "credit": 0,
    }
    payloads = {
        "reader": {
            "schema": verifier.ROLE_SCHEMAS["reader"],
            "role": "reader",
            **common,
            "reader_complete": True,
        },
        "prediction": {
            "schema": verifier.ROLE_SCHEMAS["prediction"],
            "role": "prediction",
            **common,
            "reader_input_sha256": "0" * 64,
            "prediction_complete": True,
            "autonomous": True,
            "full_horizon": True,
            "future_state_inputs": False,
        },
        "scoring": {
            "schema": verifier.ROLE_SCHEMAS["scoring"],
            "role": "scoring",
            **common,
            "reader_input_sha256": "0" * 64,
            "prediction_input_sha256": "1" * 64,
            "scoring_complete": True,
            "denominator_closed": True,
            "cases": ["case-001"],
        },
    }
    paths = {}
    for role, payload in payloads.items():
        paths[role] = artifacts_dir / f"{role}.json"
        _write_json(paths[role], payload)

    # Close the upstream chain in dependency order: prediction embeds the
    # reader digest, and scoring embeds both upstream digests.
    reader_sha = _ref(paths["reader"], root)["sha256"]
    payloads["prediction"]["reader_input_sha256"] = reader_sha
    payloads["scoring"]["reader_input_sha256"] = reader_sha
    _write_json(paths["prediction"], payloads["prediction"])
    prediction_sha = _ref(paths["prediction"], root)["sha256"]
    payloads["scoring"]["prediction_input_sha256"] = prediction_sha
    _write_json(paths["scoring"], payloads["scoring"])

    refs = {}
    for role, path in paths.items():
        ref = _ref(path, root)
        refs[role] = {
            "role": role,
            **ref,
            "schema": payloads[role]["schema"],
            "package_id": common["package_id"],
            "case_id": common["case_id"],
            "attempt_id": common["attempt_id"],
            "nonce": common["nonce"],
            "host_id": common["host_id"],
            "physical_host_id": common["physical_host_id"],
            "data_root": common["data_root"],
            "package_sha256": package_sha,
        }

    manifest = {
        "schema": verifier.MANIFEST_SCHEMA,
        "package_id": common["package_id"],
        "case_id": common["case_id"],
        "attempt_id": common["attempt_id"],
        "nonce": common["nonce"],
        "input_origin": verifier.INPUT_ORIGIN,
        "package_sha256": package_sha,
        "source": {
            "host_id": "source-host-001",
            "physical_host_id": "source-physical-001",
            "data_root": "/synthetic/source-001",
            "package_sha256": package_sha,
        },
        "reproduction": {
            "host_id": common["host_id"],
            "physical_host_id": common["physical_host_id"],
            "data_root": common["data_root"],
            "package_sha256": package_sha,
        },
        "artifacts": refs,
        "diagnostic_only": True,
        "full_product_reproduction": False,
        "independent_reproduction": False,
        "checkpoint": 0,
        "credit": 0,
    }
    manifest_path = root / "manifest.json"
    _write_json(manifest_path, manifest)
    manifest_ref = _ref(manifest_path, root)
    receipt = {
        "schema": verifier.RECEIPT_SCHEMA,
        "package_id": common["package_id"],
        "case_id": common["case_id"],
        "attempt_id": common["attempt_id"],
        "nonce": common["nonce"],
        "input_origin": verifier.INPUT_ORIGIN,
        "package_sha256": package_sha,
        "source": dict(manifest["source"]),
        "reproduction": dict(manifest["reproduction"]),
        "manifest": manifest_ref,
        "artifact_bindings": refs,
        "chain": {
            "reader_artifact_sha256": reader_sha,
            "prediction_reader_input_sha256": reader_sha,
            "prediction_artifact_sha256": prediction_sha,
            "scoring_reader_input_sha256": reader_sha,
            "scoring_prediction_input_sha256": prediction_sha,
            "scoring_artifact_sha256": refs["scoring"]["sha256"],
        },
        "diagnostic_only": True,
        "full_product_reproduction": False,
        "independent_reproduction": False,
        "checkpoint": 0,
        "credit": 0,
    }
    receipt_path = root / "full-product-receipt.json"
    _write_json(receipt_path, receipt)
    return {
        "root": root,
        "manifest_path": manifest_path,
        "receipt_path": receipt_path,
        "manifest": manifest,
        "receipt": receipt,
        "paths": paths,
    }


def _run(fixture: dict) -> dict:
    return verifier.verify(
        fixture_root=fixture["root"],
        manifest_path=fixture["manifest_path"],
        receipt_path=fixture["receipt_path"],
    )


def _rewrite(path: Path, payload: dict) -> None:
    _write_json(path, payload)


def test_synthetic_full_product_receipt_binds_all_three_roles_fail_closed(tmp_path):
    fixture = _fixture(tmp_path)
    report = _run(fixture)

    assert report["status"] == "verified_diagnostic_only"
    assert report["passed"] is True
    assert report["package_binding_verified"] is True
    assert report["verification"] == {
        "manifest_receipt_exact": True,
        "reader_exact": True,
        "prediction_exact": True,
        "scoring_exact": True,
        "reader_prediction_scoring_chain_complete": True,
        "host_identity_distinct": True,
        "data_root_distinct": True,
    }
    assert verifier.validate_report(report) == []
    assert report["diagnostic_only"] is True
    assert report["full_product_reproduction"] is False
    assert report["independent_reproduction"] is False
    assert report["checkpoint"] == 0
    assert report["credit"] == 0


def test_receipt_artifact_map_must_equal_manifest_exactly(tmp_path):
    fixture = _fixture(tmp_path)
    receipt = json.loads(fixture["receipt_path"].read_text())
    receipt["artifact_bindings"]["reader"]["attempt_id"] = "caller-mutated-attempt"
    _rewrite(fixture["receipt_path"], receipt)

    report = _run(fixture)

    assert report["passed"] is False
    assert report["errors"][0]["code"] == "RECEIPT_ARTIFACT_MAP_MISMATCH"
    assert verifier.validate_report(report) == []


def test_reader_prediction_scoring_chain_digest_mismatch_is_rejected(tmp_path):
    fixture = _fixture(tmp_path)
    receipt = json.loads(fixture["receipt_path"].read_text())
    receipt["chain"]["scoring_prediction_input_sha256"] = "f" * 64
    _rewrite(fixture["receipt_path"], receipt)

    report = _run(fixture)

    assert report["passed"] is False
    assert report["errors"][0]["code"] == "RECEIPT_CHAIN_MISMATCH"


@pytest.mark.parametrize("field,value,code", [
    ("full_product_reproduction", True, "FULL_PRODUCT_CLAIM_FORBIDDEN"),
    ("independent_reproduction", True, "INDEPENDENT_REPRODUCTION_CLAIM_FORBIDDEN"),
    ("checkpoint", 1, "CHECKPOINT_CLAIM_FORBIDDEN"),
    ("credit", 1, "CREDIT_CLAIM_FORBIDDEN"),
])
def test_receipt_authority_mutation_is_rejected(tmp_path, field, value, code):
    fixture = _fixture(tmp_path)
    receipt = json.loads(fixture["receipt_path"].read_text())
    receipt[field] = value
    _rewrite(fixture["receipt_path"], receipt)

    report = _run(fixture)

    assert report["passed"] is False
    assert report["errors"][0]["code"] == code
    assert verifier.validate_report(report) == []


def test_unknown_caller_self_claim_is_rejected_by_exact_schema(tmp_path):
    fixture = _fixture(tmp_path)
    receipt = json.loads(fixture["receipt_path"].read_text())
    receipt["verified"] = True
    _rewrite(fixture["receipt_path"], receipt)

    report = _run(fixture)

    assert report["passed"] is False
    assert report["errors"][0]["code"] == "FIELDS_NOT_EXACT"


@pytest.mark.parametrize("identity_field,code", [
    ("host_id", "DUPLICATE_HOST_IDENTITY"),
    ("physical_host_id", "DUPLICATE_PHYSICAL_HOST_IDENTITY"),
    ("data_root", "DUPLICATE_DATA_ROOT"),
])
def test_duplicate_source_reproduction_identity_is_rejected(tmp_path, identity_field, code):
    fixture = _fixture(tmp_path)
    manifest = json.loads(fixture["manifest_path"].read_text())
    manifest["source"][identity_field] = manifest["reproduction"][identity_field]
    _rewrite(fixture["manifest_path"], manifest)

    report = _run(fixture)

    assert report["passed"] is False
    assert report["errors"][0]["code"] == code


def test_artifact_digest_and_byte_binding_is_rejected(tmp_path):
    fixture = _fixture(tmp_path)
    artifact_path = fixture["paths"]["reader"]
    payload = json.loads(artifact_path.read_text())
    payload["reader_complete"] = False
    _rewrite(artifact_path, payload)

    report = _run(fixture)

    assert report["passed"] is False
    assert report["errors"][0]["code"] in {"ARTIFACT_DIGEST_MISMATCH", "ARTIFACT_BYTES_MISMATCH"}


def test_reproduction_artifact_host_or_root_mutation_is_rejected(tmp_path):
    fixture = _fixture(tmp_path)
    manifest = json.loads(fixture["manifest_path"].read_text())
    manifest["artifacts"]["prediction"]["data_root"] = "/synthetic/duplicate-root"
    _rewrite(fixture["manifest_path"], manifest)

    report = _run(fixture)

    assert report["passed"] is False
    assert report["errors"][0]["code"] == "ARTIFACT_ROOT_MISMATCH"


def test_missing_role_fails_closed_before_any_product_claim(tmp_path):
    fixture = _fixture(tmp_path)
    manifest = json.loads(fixture["manifest_path"].read_text())
    del manifest["artifacts"]["scoring"]
    _rewrite(fixture["manifest_path"], manifest)

    report = _run(fixture)

    assert report["passed"] is False
    assert report["errors"][0]["code"] == "FIELDS_NOT_EXACT"
    assert report["full_product_reproduction"] is False
    assert report["independent_reproduction"] is False
    assert report["credit"] == 0
