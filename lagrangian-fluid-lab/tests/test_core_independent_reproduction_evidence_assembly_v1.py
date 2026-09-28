"""Synthetic-only tests for the independent-reproduction assembly envelope."""

from __future__ import annotations

import copy
import inspect
import json
from pathlib import Path
from typing import Any

import pytest

from scripts import core_independent_reproduction_evidence_assembly_v1 as assembly


def _fixture() -> dict[str, Any]:
    return copy.deepcopy(assembly.synthetic_projection())


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
    chain = envelope["reader_prediction_scoring_chain"]
    assert chain["prediction_input_reader_output_sha256"] == chain["reader_output_sha256"]
    assert chain["scoring_input_prediction_output_sha256"] == chain["prediction_output_sha256"]
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
        "artifact_bytes_reverified": False,
    }
    constraints = result["execution_constraints"]
    assert constraints["synthetic_projection_only"] is True
    assert constraints["raw_artifacts_read"] is False
    assert constraints["production_bundle_read"] is False
    assert constraints["workload_started"] is False
    assert constraints["solver_started"] is False
    assert constraints["worker_started"] is False
    assert constraints["gpu_started"] is False
    assert constraints["queue_mutation"] == 0
    assert constraints["registry_mutation"] == 0
    assert constraints["ledger_mutation"] == 0
    assert constraints["gate_mutation"] == 0
    assert constraints["completion_mutation"] == 0


def test_missing_or_extra_role_category_or_component_fails_closed() -> None:
    fixture = _fixture()
    fixture["role_artifacts"].pop("scoring")
    with pytest.raises(assembly.EvidenceAssemblyError) as caught:
        assembly.verify_synthetic_assembly(fixture)
    assert caught.value.code == "ROLE_SET_MISMATCH"

    fixture = _fixture()
    fixture["role_artifacts"]["extra"] = copy.deepcopy(fixture["role_artifacts"]["reader"])
    with pytest.raises(assembly.EvidenceAssemblyError) as caught:
        assembly.verify_synthetic_assembly(fixture)
    assert caught.value.code == "ROLE_SET_MISMATCH"

    fixture = _fixture()
    fixture["role_artifacts"]["reader"]["category"] = "prediction"
    with pytest.raises(assembly.EvidenceAssemblyError) as caught:
        assembly.verify_synthetic_assembly(fixture)
    assert caught.value.code == "ROLE_CATEGORY_MISMATCH"

    fixture = _fixture()
    fixture["component_outputs"].pop("scoring")
    with pytest.raises(assembly.EvidenceAssemblyError) as caught:
        assembly.verify_synthetic_assembly(fixture)
    assert caught.value.code == "COMPONENT_SET_MISMATCH"


def test_same_host_or_same_canonical_root_is_rejected() -> None:
    fixture = _fixture()
    fixture["host_pair"]["source_host"]["hostname"] = fixture["host_pair"]["reproduction_host"]["hostname"]
    with pytest.raises(assembly.EvidenceAssemblyError) as caught:
        assembly.verify_synthetic_assembly(fixture)
    assert caught.value.code == "SAME_HOST_RELOCATION_REJECTED"

    fixture = _fixture()
    fixture["data_roots"]["reproduction_data_root"] = fixture["data_roots"]["source_data_root"] + "/"
    fixture["data_roots"]["manifests"]["reproduction_manifest"]["data_root"] = fixture["data_roots"]["source_data_root"]
    with pytest.raises(assembly.EvidenceAssemblyError) as caught:
        assembly.verify_synthetic_assembly(fixture)
    assert caught.value.code == "DATA_ROOTS_NOT_DISTINCT"


def test_artifact_descriptor_and_canonical_projection_are_fail_closed() -> None:
    fixture = _fixture()
    fixture["role_artifacts"]["reader"]["artifact"]["sha256"] = "0" * 63
    with pytest.raises(assembly.EvidenceAssemblyError) as caught:
        assembly.verify_synthetic_assembly(fixture)
    assert caught.value.code == "ARTIFACT_HASH_INVALID"

    fixture = _fixture()
    fixture["role_artifacts"]["reader"]["artifact"]["path"] = fixture["role_artifacts"]["scoring"]["artifact"]["path"]
    with pytest.raises(assembly.EvidenceAssemblyError) as caught:
        assembly.verify_synthetic_assembly(fixture)
    assert caught.value.code == "ARTIFACT_PATH_DUPLICATE"

    fixture = _fixture()
    fixture["component_outputs"]["reader"]["artifact"]["bytes"] = 0
    with pytest.raises(assembly.EvidenceAssemblyError) as caught:
        assembly.verify_synthetic_assembly(fixture)
    assert caught.value.code == "ARTIFACT_BYTES_INVALID"

    fixture = _fixture()
    fixture["role_artifacts"]["reader"]["artifact"]["path"] = "../reader.json"
    with pytest.raises(assembly.EvidenceAssemblyError) as caught:
        assembly.verify_synthetic_assembly(fixture)
    assert caught.value.code == "PATH_NOT_PORTABLE"


def test_reader_prediction_scoring_chain_rebind_is_rejected() -> None:
    fixture = _fixture()
    fixture["components"]["prediction"]["bindings"]["reader_output_sha256"] = "f" * 64
    with pytest.raises(assembly.EvidenceAssemblyError) as caught:
        assembly.verify_synthetic_assembly(fixture)
    assert caught.value.code == "COMPONENT_CHAIN_HASH_MISMATCH"

    fixture = _fixture()
    fixture["components"]["scoring"]["bindings"]["prediction_output_sha256"] = "e" * 64
    with pytest.raises(assembly.EvidenceAssemblyError) as caught:
        assembly.verify_synthetic_assembly(fixture)
    assert caught.value.code == "COMPONENT_CHAIN_HASH_MISMATCH"


def test_diagnostic_projection_cannot_masquerade_as_formal_product_evidence() -> None:
    fixture = _fixture()
    fixture["component_outputs"]["prediction"]["full_product_reproduction"] = True
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


def test_report_is_json_serializable() -> None:
    report = assembly.build_report()
    encoded = json.dumps(report, sort_keys=True, ensure_ascii=False)
    assert json.loads(encoded)["assembly_envelope"]["schema"] == assembly.SCHEMA


def test_committed_json_report_matches_recomputed_report() -> None:
    report_path = Path(__file__).resolve().parents[1] / (
        "reports/CORE-INDEPENDENT-REPRODUCTION-EVIDENCE-ASSEMBLY-V1-2026-09-28.json"
    )
    assert json.loads(report_path.read_text(encoding="utf-8")) == assembly.build_report()
