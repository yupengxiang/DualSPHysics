"""Synthetic-only tests for the independent-reproduction assembly envelope."""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
from pathlib import Path
from typing import Any

import pytest

from scripts import core_independent_reproduction_evidence_assembly_v1 as assembly


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    return json.loads(row["raw"].decode("utf-8"))


def _rewrite(row: dict[str, Any], payload: dict[str, Any]) -> None:
    raw = assembly.canonical_json_bytes(payload)
    row["raw"] = raw
    row["bytes"] = len(raw)
    row["sha256"] = hashlib.sha256(raw).hexdigest()


def _fixture() -> dict[str, Any]:
    return copy.deepcopy(assembly.synthetic_fixture())


def test_envelope_is_recomputable_and_contains_all_roles_categories_and_chain() -> None:
    result = assembly.verify_synthetic_assembly(_fixture())
    envelope = result["assembly_envelope"]

    assert result["schema"] == assembly.SCHEMA
    assert result["status"] == assembly.STATUS
    assert envelope["typed_evidence_categories"] == list(assembly.CATEGORIES)
    assert envelope["typed_evidence_roles"] == list(assembly.ROLES)
    assert set(envelope["role_artifacts"]) == set(assembly.ROLES)
    assert envelope["host_pair"]["distinct_physical_hosts"] is True
    assert envelope["data_roots"]["distinct_data_roots"] is True
    assert envelope["reader_prediction_scoring_chain"]["chain_complete"] is True
    assert (
        envelope["reader_prediction_scoring_chain"]["prediction_input_reader_output_sha256"]
        == envelope["reader_prediction_scoring_chain"]["reader_output_sha256"]
    )
    assert (
        envelope["reader_prediction_scoring_chain"]["scoring_input_prediction_output_sha256"]
        == envelope["reader_prediction_scoring_chain"]["prediction_output_sha256"]
    )
    assert assembly.recompute_envelope_sha256(envelope) == result["assembly_envelope_sha256"]
    assert result["envelope_hash_recomputed"] is True


def test_boundary_is_fixed_non_authorizing_and_old_layers_are_not_consumed() -> None:
    result = assembly.verify_synthetic_assembly(_fixture())

    assert result["diagnostic_only"] is True
    assert result["capability_minted"] is False
    assert result["full_product_reproduction"] is False
    assert result["credit"] == 0
    assert result["qualification_credit"] == 0
    assert result["non_authorizing_boundary"] == assembly.NON_AUTHORIZING_BOUNDARY
    assert result["upstream_boundary"] == {
        "update_300_preflight_consumed": False,
        "update_311_root_review_consumed": False,
        "root_review_authenticated": False,
        "capability_consumer_present": False,
    }
    assert result["execution_constraints"]["production_bundle_read"] is False
    assert result["execution_constraints"]["workload_started"] is False
    assert result["execution_constraints"]["solver_started"] is False
    assert result["execution_constraints"]["worker_started"] is False
    assert result["execution_constraints"]["gpu_started"] is False
    assert result["execution_constraints"]["queue_mutation"] == 0
    assert result["execution_constraints"]["registry_mutation"] == 0
    assert result["execution_constraints"]["ledger_mutation"] == 0
    assert result["execution_constraints"]["gate_mutation"] == 0
    assert result["execution_constraints"]["completion_mutation"] == 0


def test_missing_or_extra_role_category_or_component_fails_closed() -> None:
    fixture = _fixture()
    fixture["typed_evidence"].pop("scoring")
    with pytest.raises(assembly.EvidenceAssemblyError) as caught:
        assembly.verify_synthetic_assembly(fixture)
    assert caught.value.code == "ROLE_SET_MISMATCH"

    fixture = _fixture()
    fixture["typed_evidence"]["extra"] = copy.deepcopy(fixture["typed_evidence"]["reader"])
    with pytest.raises(assembly.EvidenceAssemblyError) as caught:
        assembly.verify_synthetic_assembly(fixture)
    assert caught.value.code == "ROLE_SET_MISMATCH"

    fixture = _fixture()
    reader = _payload(fixture["typed_evidence"]["reader"])
    reader["category"] = "prediction"
    _rewrite(fixture["typed_evidence"]["reader"], reader)
    with pytest.raises(assembly.EvidenceAssemblyError) as caught:
        assembly.verify_synthetic_assembly(fixture)
    assert caught.value.code == "ROLE_BINDING_MISMATCH"

    fixture = _fixture()
    fixture["component_outputs"].pop("scoring")
    with pytest.raises(assembly.EvidenceAssemblyError) as caught:
        assembly.verify_synthetic_assembly(fixture)
    assert caught.value.code == "COMPONENT_SET_MISMATCH"


def test_same_host_or_same_canonical_root_is_rejected() -> None:
    fixture = _fixture()
    source = _payload(fixture["typed_evidence"]["source_host"])
    reproduction = _payload(fixture["typed_evidence"]["reproduction_host"])
    source["hostname"] = reproduction["hostname"]
    _rewrite(fixture["typed_evidence"]["source_host"], source)
    with pytest.raises(assembly.EvidenceAssemblyError) as caught:
        assembly.verify_synthetic_assembly(fixture)
    assert caught.value.code == "SAME_HOST_RELOCATION_REJECTED"

    fixture = _fixture()
    roots = _payload(fixture["typed_evidence"]["data_roots"])
    reproduction_manifest = _payload(fixture["manifest_artifacts"]["reproduction_manifest"])
    roots["reproduction_data_root"] = roots["source_data_root"] + "/"
    reproduction_manifest["data_root"] = roots["source_data_root"]
    _rewrite(fixture["manifest_artifacts"]["reproduction_manifest"], reproduction_manifest)
    ref = {
        key: fixture["manifest_artifacts"]["reproduction_manifest"][key]
        for key in ("path", "sha256", "bytes")
    }
    roots["reproduction_manifest"] = ref
    roots["reproduction_manifest_sha256"] = ref["sha256"]
    _rewrite(fixture["typed_evidence"]["data_roots"], roots)
    with pytest.raises(assembly.EvidenceAssemblyError) as caught:
        assembly.verify_synthetic_assembly(fixture)
    assert caught.value.code == "DATA_ROOTS_NOT_DISTINCT"


def test_artifact_integrity_and_canonical_json_are_fail_closed() -> None:
    fixture = _fixture()
    fixture["typed_evidence"]["reader"]["sha256"] = "0" * 64
    with pytest.raises(assembly.EvidenceAssemblyError) as caught:
        assembly.verify_synthetic_assembly(fixture)
    assert caught.value.code == "ARTIFACT_HASH_MISMATCH"

    fixture = _fixture()
    row = fixture["typed_evidence"]["reader"]
    row["raw"] = row["raw"] + b"\n"
    row["bytes"] += 1
    row["sha256"] = hashlib.sha256(row["raw"]).hexdigest()
    with pytest.raises(assembly.EvidenceAssemblyError) as caught:
        assembly.verify_synthetic_assembly(fixture)
    assert caught.value.code == "NON_CANONICAL_JSON"

    fixture = _fixture()
    fixture["component_outputs"]["scoring"]["path"] = (
        fixture["component_outputs"]["reader"]["path"]
    )
    with pytest.raises(assembly.EvidenceAssemblyError) as caught:
        assembly.verify_synthetic_assembly(fixture)
    assert caught.value.code == "ARTIFACT_PATH_DUPLICATE"


def test_reader_prediction_scoring_chain_rebind_is_rejected() -> None:
    fixture = _fixture()
    prediction = _payload(fixture["typed_evidence"]["prediction"])
    prediction["bindings"]["reader_output_sha256"] = "f" * 64
    _rewrite(fixture["typed_evidence"]["prediction"], prediction)

    with pytest.raises(assembly.EvidenceAssemblyError) as caught:
        assembly.verify_synthetic_assembly(fixture)
    assert caught.value.code == "COMPONENT_CHAIN_HASH_MISMATCH"

    fixture = _fixture()
    scoring = _payload(fixture["typed_evidence"]["scoring"])
    scoring["bindings"]["prediction_output_sha256"] = "e" * 64
    _rewrite(fixture["typed_evidence"]["scoring"], scoring)
    with pytest.raises(assembly.EvidenceAssemblyError) as caught:
        assembly.verify_synthetic_assembly(fixture)
    assert caught.value.code == "COMPONENT_CHAIN_HASH_MISMATCH"


def test_diagnostic_payload_cannot_masquerade_as_formal_product_evidence() -> None:
    fixture = _fixture()
    output = _payload(fixture["component_outputs"]["prediction"])
    output["full_product_reproduction"] = True
    _rewrite(fixture["component_outputs"]["prediction"], output)
    prediction = _payload(fixture["typed_evidence"]["prediction"])
    prediction["output_report"] = {
        key: fixture["component_outputs"]["prediction"][key]
        for key in ("path", "sha256", "bytes")
    }
    _rewrite(fixture["typed_evidence"]["prediction"], prediction)

    with pytest.raises(assembly.EvidenceAssemblyError) as caught:
        assembly.verify_synthetic_assembly(fixture)
    assert caught.value.code == "DIAGNOSTIC_FORMAL_CONFLICT"


def test_report_is_deterministic_and_module_is_non_executing() -> None:
    source = inspect.getsource(assembly)
    assert "from scripts.core_independent_reproduction_preflight import" not in source
    assert "from scripts.core_independent_reproduction_root_review_adapter_v1 import" not in source
    assert "import subprocess" not in source
    assert "import torch" not in source
    assert "CUDA_VISIBLE_DEVICES =" not in source

    report = assembly.build_report()
    assert report["schema"] == assembly.REPORT_SCHEMA
    assert report["status"] == assembly.REPORT_STATUS
    assert report["assembly_envelope_sha256"] == assembly.recompute_envelope_sha256(
        report["assembly_envelope"]
    )
    assert report["non_authorizing_boundary"] == assembly.NON_AUTHORIZING_BOUNDARY


def test_write_json_once_refuses_to_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "receipt.json"
    output.write_text("historical\n", encoding="utf-8")
    with pytest.raises(assembly.EvidenceAssemblyError) as caught:
        assembly.write_json_once(output, {"new": True})
    assert caught.value.code == "IMMUTABLE_OUTPUT_EXISTS"
    assert output.read_text(encoding="utf-8") == "historical\n"
