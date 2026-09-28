"""Synthetic-only tests for the F4 DEV_07 coarse material proposal."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.core_contract import contract_hash
from scripts.core_dataset import known_inputs_from_dict
from scripts.f4_tallwall120_material_coarse_proposal_v1 import (
    DEFAULT_OUTPUT_NAMESPACE,
    build_proposal,
    sha256_file,
)


QUALIFICATION_CLAIM = "none; one case cannot establish range/temporal/reference qualification"


def _known_inputs() -> dict:
    triangle = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    return {
        "contract_version": "core.inputs.v1",
        "coordinate_frame": "synthetic tank frame",
        "geometry": {
            "version": "core.finite_geometry.v1",
            "coordinate_frame": "synthetic tank frame",
            "triangles": [triangle for _ in range(10)],
            "component_id": [0] * 10,
            "body_id": [0] * 10,
            "wall_velocity": [[0.0, 0.0, 0.0] for _ in range(10)],
        },
        "control": {
            "centre": [0.45, 0.0, 0.0],
            "samples": [
                [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            ],
            "semantics": "dualsphysics_f3_accinput_v1",
        },
        "physics": {
            "family": "F4",
            "gravity_mps2": [0.0, 0.0, -9.81],
            "physical_kinematic_viscosity_m2_s": 1.0e-6,
            "reference_density_kgm3": 1000.0,
            "scope_id": "synthetic_f4_scope",
            "viscosity_formulation": "laminar",
            "viscosity_source": "synthetic_fixture",
        },
        "numerics": {
            "dp_m": 0.01,
            "h_m": 0.02,
            "native_velocity_correction": True,
            "recipe_id": "synthetic_f4_recipe",
            "viscosity_coefficient": 0.1,
        },
    }


def _fixture(tmp_path: Path, *, declared_hdf5: str | None = None) -> dict:
    source_rel = "data/target/trajectory.h5"
    source_sha = "a" * 64
    source_bytes = 5
    source = tmp_path / source_rel
    source.parent.mkdir(parents=True)
    source.write_bytes(b"HDF5")
    # The planner only stats this placeholder; it never opens it as HDF5.
    source.write_bytes(b"HDF5!")

    archive_rel = "data/target/archive.json"
    result_rel = "data/target/result.json"
    audit_rel = "data/target/audit.json"
    archive = tmp_path / archive_rel
    result = tmp_path / result_rel
    audit = tmp_path / audit_rel
    archive_payload = {
        "schema": "core.verified_archive.v1",
        "execution_status": "succeeded",
        "job_id": "f4-tallwall120-production-dev-07",
        "outputs": [{"path": "product/trajectory.h5", "bytes": source_bytes, "sha256": source_sha}],
    }
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_text(json.dumps(archive_payload), encoding="utf-8")
    result.write_text(json.dumps({
        "schema": "core.cfd.v1",
        "case_id": "synthetic-case",
        "conversion": {"sha256": source_sha, "frames": 3, "particle_count": 2},
        "hard_integrity_pass": True,
        "source_mass_gate_pass": True,
        "qualified": False,
        "qualification_claim": QUALIFICATION_CLAIM,
    }), encoding="utf-8")
    audit.write_text(json.dumps({
        "schema": "core.cfd.v1",
        "case_id": "synthetic-case",
        "hard_integrity_pass": True,
        "source_mass_gate_pass": True,
        "qualified": False,
    }), encoding="utf-8")

    prepared = tmp_path / "data/target/prepared.json"
    prepared.write_text(json.dumps({
        "config": {
            "case_id": "synthetic-case",
            "scope_id": "synthetic_scope",
            "recipe_id": "synthetic_recipe",
            "parameter": {"q": 0.23437500000000008, "value": 0.3015625},
            "qualification_inheritance": False,
        }
    }), encoding="utf-8")

    known = _known_inputs()
    known_hash = contract_hash(known_inputs_from_dict(known))
    target = {
        "family": "F4",
        "case_id": "synthetic-case",
        "physical_case_id": "synthetic-case",
        "lineage_group_id": "synthetic-lineage",
        "source_hdf5": source_rel,
        "source_sha256": source_sha,
        "source_bytes": source_bytes,
        "frames": 3,
        "transitions": 2,
        "particle_count": 2,
        "time_start_s": 0.0,
        "time_end_s": 0.2,
        "split": "train",
        "recipe_id": "synthetic_recipe",
        "scope_id": "synthetic_scope",
    }
    collection = tmp_path / "data/collection.json"
    collection.write_text(json.dumps({
        "schema": "core.f4.tallwall120.production_collection.v1",
        "reader_manifest": {
            "formal_eligible": False,
            "cases": [{
                "case_id": target["case_id"],
                "physical_case_id": target["physical_case_id"],
                "lineage_group_id": target["lineage_group_id"],
                "family": "F4",
                "split": "train",
                "hdf5": declared_hdf5 or source_rel,
                "sha256": source_sha,
                "known_inputs": known,
                "known_inputs_sha256": known_hash,
                "provenance": {
                    "prepared": {
                        "path": "data/target/prepared.json",
                        "sha256": sha256_file(prepared),
                    }
                },
            }],
        },
    }), encoding="utf-8")

    code_paths = {}
    for index in range(2):
        relative = f"code/implementation-{index}.py"
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# synthetic {index}\n", encoding="utf-8")
        code_paths[relative] = "synthetic code"
    return {
        "target": target,
        "collection": collection,
        "archive": archive,
        "result": result,
        "audit": audit,
        "code_paths": code_paths,
        "known_hash": known_hash,
        "source_rel": source_rel,
    }


def _build(tmp_path: Path, fixture: dict, *, namespace: str = "proposals/synthetic") -> dict:
    return build_proposal(
        tmp_path,
        target=fixture["target"],
        collection_manifest="data/collection.json",
        source_archive="data/target/archive.json",
        source_result="data/target/result.json",
        source_audit="data/target/audit.json",
        expected_collection_sha256=sha256_file(fixture["collection"]),
        expected_archive_sha256=sha256_file(fixture["archive"]),
        expected_result_sha256=sha256_file(fixture["result"]),
        expected_audit_sha256=sha256_file(fixture["audit"]),
        expected_known_inputs_sha256=fixture["known_hash"],
        fresh_output_namespace=namespace,
        code_paths=fixture["code_paths"],
    )


def test_synthetic_proposal_is_bound_but_never_qualifying(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    proposal = _build(tmp_path, fixture)

    assert proposal["schema"] == "core.material.f4.tallwall120.coarse_proposal.v1"
    assert proposal["status"] == "blocked_fail_closed"
    assert proposal["proposal_only"] is True
    assert proposal["diagnostic_only"] is True
    assert proposal["formal_eligible"] is False
    assert proposal["qualification"]["credit"] == 0
    assert proposal["qualification"]["material_labels_created"] is False
    assert proposal["source"]["known_inputs_contract"]["contract_valid"] is True
    assert all(item["passed"] for item in proposal["admission"]["static_checks"])
    assert proposal["execution_controls"]["gpu_started"] is False
    assert proposal["execution_controls"]["queue_mutation"] is False
    assert proposal["planned_output_namespace"]["namespace"] == "proposals/synthetic"
    assert proposal["planned_output_namespace"]["namespace_policy"]["overwrite_allowed"] is False
    assert "fresh_resource_admission_and_runtime_authorization_missing" in proposal["admission"]["blocking_reasons"]
    assert DEFAULT_OUTPUT_NAMESPACE not in proposal["argv_contract"]["material_trace"]


def test_collection_path_alias_is_a_fail_closed_blocker(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, declared_hdf5="data/old/trajectory.h5")
    proposal = _build(tmp_path, fixture, namespace="proposals/alias")

    path_check = next(
        item for item in proposal["admission"]["static_checks"]
        if item["check"] == "collection_source_path_exact"
    )
    assert path_check["passed"] is False
    assert "collection_manifest_path_alias_must_be_replaced_or_root_explicitly_rebind_it" in proposal["admission"]["blocking_reasons"]
    assert proposal["qualification"]["T2"] is False


def test_known_input_future_state_is_rejected(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    payload = json.loads(fixture["collection"].read_text(encoding="utf-8"))
    payload["reader_manifest"]["cases"][0]["known_inputs"]["physics"]["future_state"] = {"x": 1}
    fixture["collection"].write_text(json.dumps(payload), encoding="utf-8")
    proposal = _build(tmp_path, fixture, namespace="proposals/future-field")

    contract_check = next(
        item for item in proposal["admission"]["static_checks"]
        if item["check"] == "known_inputs_contract"
    )
    assert contract_check["passed"] is False
    assert proposal["source"]["known_inputs_contract"]["contract_valid"] is False


def test_relative_paths_are_fail_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    with pytest.raises(ValueError, match="relative|dot segments"):
        _build(tmp_path, fixture, namespace="../escape")
