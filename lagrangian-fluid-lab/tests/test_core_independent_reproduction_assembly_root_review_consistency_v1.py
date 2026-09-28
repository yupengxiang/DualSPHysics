"""Synthetic-only tests for the assembly/root-review consistency bridge."""

from __future__ import annotations

import copy
import inspect
import json
from pathlib import Path
from typing import Any

import pytest

from scripts import core_independent_reproduction_assembly_root_review_consistency_v1 as contract
from scripts import core_independent_reproduction_evidence_assembly_v1 as assembly


def _fixture() -> dict[str, Any]:
    return copy.deepcopy(contract.synthetic_projection())


def _refresh_assembly_hash(projection: dict[str, Any]) -> None:
    result = projection["assembly_result"]
    result["assembly_envelope_sha256"] = assembly.recompute_envelope_sha256(
        result["assembly_envelope"]
    )


def test_synthetic_projection_binds_assembly_to_update_311_root_review() -> None:
    result = contract.verify_consistency_projection(_fixture())

    assert result["schema"] == contract.SCHEMA
    assert result["status"] == contract.STATUS
    assert result["typed_evidence_categories"] == [
        "host_pair", "data_roots", "reader", "prediction", "scoring"
    ]
    assert result["typed_evidence_roles"] == [
        "source_host", "reproduction_host", "data_roots", "reader",
        "prediction", "scoring",
    ]
    assert result["cross_binding"]["consistent"] is True
    assert result["cross_binding"]["schema"] == contract.BINDING_SCHEMA
    assert result["assembly"]["envelope_sha256"] == (
        result["cross_binding"]["assembly_envelope_sha256"]
    )
    assert result["root_review"]["decision_sha256"] == (
        result["cross_binding"]["root_review_decision_sha256"]
    )


def test_fixed_non_authorizing_boundary_and_execution_constraints() -> None:
    result = contract.verify_consistency_projection(_fixture())

    assert result["non_authorizing_boundary"] == contract.NON_AUTHORIZING_BOUNDARY
    assert result["diagnostic_only"] is True
    assert result["capability_minted"] is False
    assert result["full_product_reproduction"] is False
    assert result["credit"] == 0
    assert result["execution_constraints"] == contract.EXECUTION_CONSTRAINTS
    assert result["upstream_boundary"] == contract.UPSTREAM_BOUNDARY
    assert result["root_review"]["trusted_root_authenticated"] is False
    assert result["root_review"]["caller_self_asserted_trusted_root_accepted"] is False


def test_assembly_envelope_digest_drift_fails_closed() -> None:
    projection = _fixture()
    projection["assembly_result"]["assembly_envelope"]["host_pair"]["source_host"][
        "physical_host_id"
    ] = "physical-other-001"

    with pytest.raises(contract.AssemblyRootReviewConsistencyError) as caught:
        contract.verify_consistency_projection(projection)

    assert caught.value.code == "ASSEMBLY_ENVELOPE_HASH_MISMATCH"


def test_cross_host_drift_fails_closed_after_valid_projection_rehash() -> None:
    projection = _fixture()
    projection["root_review_result"]["assembly"]["reproduction_host"][
        "physical_host_id"
    ] = "physical-other-reproduction-001"

    with pytest.raises(contract.AssemblyRootReviewConsistencyError) as caught:
        contract.verify_consistency_projection(projection)

    assert caught.value.code == "CROSS_HOST_MISMATCH"


def test_cross_data_root_manifest_drift_fails_closed() -> None:
    projection = _fixture()
    projection["assembly_result"]["assembly_envelope"]["data_roots"][
        "reproduction_data_root"
    ] = "/synthetic/core/other-reproduction"
    _refresh_assembly_hash(projection)

    with pytest.raises(contract.AssemblyRootReviewConsistencyError) as caught:
        contract.verify_consistency_projection(projection)

    assert caught.value.code == "CROSS_DATA_ROOT_MISMATCH"


def test_cross_manifest_artifact_drift_fails_closed() -> None:
    projection = _fixture()
    projection["assembly_result"]["assembly_envelope"]["manifest_artifacts"][
        "reproduction_manifest"
    ]["sha256"] = "f" * 64
    _refresh_assembly_hash(projection)

    with pytest.raises(contract.AssemblyRootReviewConsistencyError) as caught:
        contract.verify_consistency_projection(projection)

    assert caught.value.code == "CROSS_DATA_ROOT_MISMATCH"


def test_cross_reader_prediction_scoring_chain_drift_fails_closed() -> None:
    projection = _fixture()
    projection["assembly_result"]["assembly_envelope"][
        "reader_prediction_scoring_chain"
    ]["scoring_output_sha256"] = "f" * 64
    _refresh_assembly_hash(projection)

    with pytest.raises(contract.AssemblyRootReviewConsistencyError) as caught:
        contract.verify_consistency_projection(projection)

    assert caught.value.code == "CROSS_CHAIN_MISMATCH"


def test_root_review_decision_hash_drift_fails_closed() -> None:
    projection = _fixture()
    projection["root_review_result"]["root_review"]["decision"][
        "registered_comparison_pass"
    ] = False

    with pytest.raises(contract.AssemblyRootReviewConsistencyError) as caught:
        contract.verify_consistency_projection(projection)

    assert caught.value.code == "ROOT_DECISION_HASH_MISMATCH"


def test_authenticated_root_review_claim_fails_closed() -> None:
    projection = _fixture()
    projection["root_review_result"]["root_review"]["trusted_root_authenticated"] = True

    with pytest.raises(contract.AssemblyRootReviewConsistencyError) as caught:
        contract.verify_consistency_projection(projection)

    assert caught.value.code == "ROOT_TRUST_BOUNDARY_DRIFT"


def test_extra_projection_fields_fail_closed() -> None:
    projection = _fixture()
    projection["assembly_result"]["unexpected"] = True

    with pytest.raises(contract.AssemblyRootReviewConsistencyError) as caught:
        contract.verify_consistency_projection(projection)

    assert caught.value.code == "FIELDS_NOT_EXACT"


def test_noncanonical_json_value_fails_closed() -> None:
    projection = _fixture()
    projection["assembly_result"]["interpretation"] = b"not-json"

    with pytest.raises(contract.AssemblyRootReviewConsistencyError) as caught:
        contract.verify_consistency_projection(projection)

    assert caught.value.code == "NON_CANONICAL_JSON"


def test_report_is_deterministic_and_module_is_nonexecuting() -> None:
    source = inspect.getsource(contract)
    assert "import subprocess" not in source
    assert "nvidia-smi" not in source
    assert "CUDA_VISIBLE_DEVICES" not in source
    assert "import torch" not in source

    report = contract.build_report()
    assert report["schema"] == contract.REPORT_SCHEMA
    assert report["status"] == contract.REPORT_STATUS
    assert report["cross_binding"]["consistent"] is True
    assert report["non_authorizing_boundary"] == contract.NON_AUTHORIZING_BOUNDARY
    assert report["execution_constraints"] == contract.EXECUTION_CONSTRAINTS

    report_path = Path(__file__).resolve().parents[1] / (
        "reports/CORE-INDEPENDENT-REPRODUCTION-ASSEMBLY-ROOT-REVIEW-CONSISTENCY-V1-2026-09-28.json"
    )
    assert json.loads(report_path.read_text(encoding="utf-8")) == report


def test_write_json_once_refuses_to_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "receipt.json"
    output.write_text("historical\n", encoding="utf-8")

    with pytest.raises(contract.AssemblyRootReviewConsistencyError) as caught:
        contract.write_json_once(output, {"new": True})

    assert caught.value.code == "IMMUTABLE_OUTPUT_EXISTS"
    assert output.read_text(encoding="utf-8") == "historical\n"
