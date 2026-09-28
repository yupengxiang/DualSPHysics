"""Synthetic-only tests for the Core typed-evidence/root-review sidecar."""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
from pathlib import Path
from typing import Any

import pytest

from scripts import core_independent_reproduction_root_review_adapter_v1 as adapter


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    return json.loads(row["raw"].decode("utf-8"))


def _rewrite(row: dict[str, Any], payload: dict[str, Any]) -> None:
    raw = adapter.canonical_json_bytes(payload)
    row["raw"] = raw
    row["bytes"] = len(raw)
    row["sha256"] = hashlib.sha256(raw).hexdigest()


def _fixture() -> dict[str, Any]:
    return copy.deepcopy(adapter.synthetic_fixture())


def test_synthetic_fixture_binds_all_roles_to_diagnostic_root_decision() -> None:
    result = adapter.bind_synthetic_typed_evidence_root_review(_fixture())

    assert result["schema"] == adapter.SCHEMA
    assert result["status"] == adapter.STATUS
    assert result["typed_evidence_categories"] == list(adapter.CATEGORIES)
    assert result["typed_evidence_roles"] == list(adapter.ROLES)
    assert result["evidence_manifest"]["category_count"] == 5
    assert result["evidence_manifest"]["role_count"] == 6
    assert result["assembly"]["distinct_physical_hosts"] is True
    assert result["assembly"]["distinct_data_roots"] is True
    assert result["root_review"]["decision_bound"] is True
    assert result["root_review"]["decision"]["schema"] == adapter.ROOT_REVIEW_SCHEMA
    assert result["root_review"]["decision"]["diagnostic_only"] is True
    assert result["root_review"]["decision"]["formal_training_count"] == 0
    assert result["root_review"]["decision"]["full_core_reproduction_proven"] is False
    assert result["root_review"]["trusted_root_authenticated"] is False
    assert result["root_review"]["caller_self_asserted_trusted_root_accepted"] is False
    assert result["diagnostic_only"] is True
    assert result["capability_minted"] is False
    assert result["formal_training_count"] == 0
    assert result["full_product_reproduction"] is False
    assert result["credit"] == 0
    assert result["non_authorizing_boundary"] == adapter.NON_AUTHORIZING_BOUNDARY


def test_missing_or_extra_role_fails_closed() -> None:
    fixture = _fixture()
    fixture["typed_evidence"].pop("scoring")
    with pytest.raises(adapter.TypedEvidenceRootReviewAdapterError) as caught:
        adapter.bind_synthetic_typed_evidence_root_review(fixture)
    assert caught.value.code == "ROLE_SET_MISMATCH"

    fixture = _fixture()
    fixture["typed_evidence"]["extra"] = copy.deepcopy(fixture["typed_evidence"]["reader"])
    with pytest.raises(adapter.TypedEvidenceRootReviewAdapterError) as caught:
        adapter.bind_synthetic_typed_evidence_root_review(fixture)
    assert caught.value.code == "ROLE_SET_MISMATCH"


def test_same_host_relocation_is_rejected() -> None:
    fixture = _fixture()
    source = _payload(fixture["typed_evidence"]["source_host"])
    reproduction = _payload(fixture["typed_evidence"]["reproduction_host"])
    source["hostname"] = reproduction["hostname"]
    _rewrite(fixture["typed_evidence"]["source_host"], source)

    with pytest.raises(adapter.TypedEvidenceRootReviewAdapterError) as caught:
        adapter.bind_synthetic_typed_evidence_root_review(fixture)
    assert caught.value.code == "SAME_HOST_RELOCATION_REJECTED"


def test_path_or_hash_mismatch_is_rejected_before_any_claim_is_used() -> None:
    fixture = _fixture()
    fixture["typed_evidence"]["reader"]["sha256"] = "0" * 64
    with pytest.raises(adapter.TypedEvidenceRootReviewAdapterError) as caught:
        adapter.bind_synthetic_typed_evidence_root_review(fixture)
    assert caught.value.code == "ARTIFACT_HASH_MISMATCH"

    fixture = _fixture()
    roots = _payload(fixture["typed_evidence"]["data_roots"])
    roots["source_manifest"]["path"] = "manifests/other.json"
    _rewrite(fixture["typed_evidence"]["data_roots"], roots)
    with pytest.raises(adapter.TypedEvidenceRootReviewAdapterError) as caught:
        adapter.bind_synthetic_typed_evidence_root_review(fixture)
    assert caught.value.code == "NESTED_ARTIFACT_BINDING_MISMATCH"


def test_diagnostic_output_cannot_masquerade_as_formal_product_evidence() -> None:
    fixture = _fixture()
    prediction_output = _payload(fixture["component_outputs"]["prediction"])
    prediction_output["full_product_reproduction"] = True
    _rewrite(fixture["component_outputs"]["prediction"], prediction_output)
    prediction = _payload(fixture["typed_evidence"]["prediction"])
    prediction["output_report"] = {
        key: fixture["component_outputs"]["prediction"][key]
        for key in ("path", "sha256", "bytes")
    }
    _rewrite(fixture["typed_evidence"]["prediction"], prediction)

    with pytest.raises(adapter.TypedEvidenceRootReviewAdapterError) as caught:
        adapter.bind_synthetic_typed_evidence_root_review(fixture)
    assert caught.value.code == "DIAGNOSTIC_FORMAL_CONFLICT"


def test_reader_prediction_scoring_hash_chain_is_exact() -> None:
    fixture = _fixture()
    prediction = _payload(fixture["typed_evidence"]["prediction"])
    prediction["bindings"]["reader_output_sha256"] = "f" * 64
    _rewrite(fixture["typed_evidence"]["prediction"], prediction)

    with pytest.raises(adapter.TypedEvidenceRootReviewAdapterError) as caught:
        adapter.bind_synthetic_typed_evidence_root_review(fixture)
    assert caught.value.code == "COMPONENT_CHAIN_HASH_MISMATCH"


def test_caller_self_asserted_trusted_root_is_rejected() -> None:
    fixture = _fixture()
    root = _payload(fixture["root_review"])
    root["trusted_root"] = True
    _rewrite(fixture["root_review"], root)

    with pytest.raises(adapter.TypedEvidenceRootReviewAdapterError) as caught:
        adapter.bind_synthetic_typed_evidence_root_review(fixture)
    assert caught.value.code == "CALLER_TRUSTED_ROOT_REJECTED"


def test_root_review_decision_and_exact_binding_claim_are_hash_bound() -> None:
    fixture = _fixture()
    root = _payload(fixture["root_review"])
    root["full_core_reproduction_proven"] = True
    _rewrite(fixture["root_review"], root)
    with pytest.raises(adapter.TypedEvidenceRootReviewAdapterError) as caught:
        adapter.bind_synthetic_typed_evidence_root_review(fixture)
    assert caught.value.code == "ROOT_REVIEW_SCOPE_INVALID"

    fixture = _fixture()
    claim = _payload(fixture["binding_claim"])
    claim["root_review_decision_sha256"] = "e" * 64
    _rewrite(fixture["binding_claim"], claim)
    with pytest.raises(adapter.TypedEvidenceRootReviewAdapterError) as caught:
        adapter.bind_synthetic_typed_evidence_root_review(fixture)
    assert caught.value.code == "EXACT_BINDING_CLAIM_MISMATCH"


def test_noncanonical_bytes_and_duplicate_role_paths_fail_closed() -> None:
    fixture = _fixture()
    row = fixture["typed_evidence"]["reader"]
    row["raw"] = row["raw"] + b"\n"
    row["bytes"] += 1
    row["sha256"] = hashlib.sha256(row["raw"]).hexdigest()
    with pytest.raises(adapter.TypedEvidenceRootReviewAdapterError) as caught:
        adapter.bind_synthetic_typed_evidence_root_review(fixture)
    assert caught.value.code == "NON_CANONICAL_JSON"

    fixture = _fixture()
    fixture["typed_evidence"]["scoring"]["path"] = (
        fixture["typed_evidence"]["reader"]["path"]
    )
    with pytest.raises(adapter.TypedEvidenceRootReviewAdapterError) as caught:
        adapter.bind_synthetic_typed_evidence_root_review(fixture)
    assert caught.value.code == "ARTIFACT_PATH_DUPLICATE"


def test_report_is_fixed_non_authorizing_and_adapter_is_disjoint() -> None:
    source = inspect.getsource(adapter)
    assert "from scripts.core_cross_host_root_review import" not in source
    assert "from scripts.core_independent_reproduction_preflight import" not in source
    assert "subprocess" not in source
    assert "torch" not in source
    assert "CUDA_VISIBLE_DEVICES" not in source

    report = adapter.build_report()
    assert report["schema"] == adapter.REPORT_SCHEMA
    assert report["status"] == adapter.REPORT_STATUS
    assert report["non_authorizing_boundary"] == adapter.NON_AUTHORIZING_BOUNDARY
    assert report["root_review"]["decision_bound"] is True
    assert report["root_review"]["trusted_root_authenticated"] is False
    assert report["execution_constraints"]["synthetic_in_memory_only"] is True
    assert report["execution_constraints"]["workload_started"] is False

    report_path = Path(__file__).resolve().parents[1] / (
        "reports/CORE-INDEPENDENT-REPRODUCTION-ROOT-REVIEW-ADAPTER-V1-2026-09-28.json"
    )
    assert json.loads(report_path.read_text(encoding="utf-8")) == report
