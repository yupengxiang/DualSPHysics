"""Synthetic-only tests for the independent-reproduction evidence preflight."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.core_independent_reproduction_preflight import (
    ROLES,
    build_preflight,
)
from scripts.core_runtime import digest


def _write(path: Path, payload: dict) -> dict:
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return {"path": path.name, "sha256": digest(path), "bytes": path.stat().st_size}


def _fixture(tmp_path: Path) -> dict[str, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    source_root = "/datasets/core-source"
    reproduction_root = "/scratch/core-relocated"
    source_manifest_path = tmp_path / "source-manifest.json"
    reproduction_manifest_path = tmp_path / "reproduction-manifest.json"
    package_ref = _write(tmp_path / "package.json", {
        "schema": "fixture.package.v1",
        "package": "same-content-package",
    })
    package_hash = package_ref["sha256"]
    common_markers = {
        "diagnostic_only": True,
        "formal": False,
        "full_product_reproduction": False,
        "input_origin": "synthetic_fixture",
    }
    source_manifest = _write(source_manifest_path, {
        "schema": "core.reproduction.package_manifest.v1",
        "passed": True,
        "data_root": source_root,
        "package_sha256": package_hash,
        "package_artifact": package_ref,
        **common_markers,
    })
    reproduction_manifest = _write(reproduction_manifest_path, {
        "schema": "core.reproduction.package_manifest.v1",
        "passed": True,
        "data_root": reproduction_root,
        "package_sha256": package_hash,
        "package_artifact": package_ref,
        **common_markers,
    })
    _write(tmp_path / "source-host.json", {
        "schema": "core.reproduction.host_identity.v1",
        "role": "source_host",
        "category": "host_pair",
        "passed": True,
        "hostname": "source-host",
        "physical_host_id": "physical-source",
        **common_markers,
    })
    _write(tmp_path / "reproduction-host.json", {
        "schema": "core.reproduction.host_identity.v1",
        "role": "reproduction_host",
        "category": "host_pair",
        "passed": True,
        "hostname": "reproduction-host",
        "physical_host_id": "physical-reproduction",
        **common_markers,
    })
    _write(tmp_path / "data-roots.json", {
        "schema": "core.reproduction.data_roots.v1",
        "role": "data_roots",
        "category": "data_roots",
        "passed": True,
        "source_data_root": source_root,
        "reproduction_data_root": reproduction_root,
        "different_data_root": True,
        "package_sha256": package_hash,
        "source_manifest": source_manifest,
        "reproduction_manifest": reproduction_manifest,
        "source_manifest_sha256": source_manifest["sha256"],
        "reproduction_manifest_sha256": reproduction_manifest["sha256"],
        **common_markers,
    })

    source_payloads = {
        "reader": {"schema": "fixture.reader.source.v1", "passed": True},
        "prediction": {"schema": "fixture.prediction.source.v1", "passed": True},
        "scoring": {"schema": "fixture.scoring.source.v1", "passed": True},
    }
    source_refs = {
        component: _write(tmp_path / f"{component}-source.json", payload)
        for component, payload in source_payloads.items()
    }
    output_payloads = {
        "reader": {
            "schema": "core.reader_reproduction.v1",
            "component": "reader",
            "passed": True,
            "physical_host_id": "physical-reproduction",
            "data_root": reproduction_root,
            "future_state_inputs": False,
            "source_artifact": source_refs["reader"],
            **common_markers,
        },
        "prediction": {
            "schema": "core.model_reproduction.v1",
            "component": "prediction",
            "passed": True,
            "physical_host_id": "physical-reproduction",
            "data_root": reproduction_root,
            "autonomous": True,
            "full_horizon": True,
            "future_state_inputs": False,
            "predictor_future_state_inputs": False,
            "source_artifact": source_refs["prediction"],
            **common_markers,
        },
        "scoring": {
            "schema": "core.model_reproduction.score.v1",
            "component": "scoring",
            "passed": True,
            "physical_host_id": "physical-reproduction",
            "data_root": reproduction_root,
            "metrics": {
                "registered_cases": 1,
                "complete_fraction": 1.0,
                "missing_execution": 0,
            },
            "cases": ["case-0"],
            "predictor_future_state_inputs": False,
            "source_artifact": source_refs["scoring"],
            **common_markers,
        },
    }
    paths = {
        "source_host": tmp_path / "source-host.json",
        "reproduction_host": tmp_path / "reproduction-host.json",
        "data_roots": tmp_path / "data-roots.json",
    }
    reproduction_host_id = "physical-reproduction"
    output_refs = {}
    for component, output_payload in output_payloads.items():
        output_ref = _write(tmp_path / f"{component}-output.json", output_payload)
        output_refs[component] = output_ref
    for component in output_payloads:
        bindings = {
            "reader": {
                "reproduction_manifest_sha256": reproduction_manifest["sha256"],
                "source_artifact_sha256": source_refs["reader"]["sha256"],
            },
            "prediction": {
                "reader_output_sha256": output_refs["reader"]["sha256"],
                "source_artifact_sha256": source_refs["prediction"]["sha256"],
            },
            "scoring": {
                "reader_output_sha256": output_refs["reader"]["sha256"],
                "prediction_output_sha256": output_refs["prediction"]["sha256"],
                "source_artifact_sha256": source_refs["scoring"]["sha256"],
            },
        }[component]
        evidence = {
            "schema": "core.reproduction.component.v1",
            "role": component,
            "category": component,
            "component": component,
            "passed": True,
            "reader_reproduced": component == "reader",
            "prediction_reproduced": component == "prediction",
            "scoring_reproduced": component == "scoring",
            "physical_host_id": reproduction_host_id,
            "data_root": reproduction_root,
            "output_report": output_refs[component],
            "bindings": bindings,
            **common_markers,
        }
        paths[component] = tmp_path / f"{component}-evidence.json"
        _write(paths[component], evidence)
    return paths


def test_preflight_structurally_assembles_all_five_roles_without_capability(tmp_path: Path):
    paths = _fixture(tmp_path)

    result = build_preflight(data_root=tmp_path, evidence_paths=paths)

    assert result["schema"] == "core.reproduction.independent_preflight.v1"
    assert result["status"] == "pass"
    assert result["structural_preflight_passed"] is True
    assert set(result["supporting_evidence"]) == set(ROLES)
    assert result["assembly"]["distinct_physical_hosts"] is True
    assert result["assembly"]["distinct_data_roots"] is True
    assert result["assembly"]["autonomous_prediction_typed"] is True
    assert result["assembly"]["typed_chain"]["chain_complete"] is True
    assert result["capability_minted"] is False
    assert result["independent_reproduction"] is False
    assert result["full_product_reproduction"] is False
    assert result["formal_admission"] is False
    assert result["formal_training_admission"] is False
    assert result["credit"] == 0
    assert result["qualification_credit"] == 0
    assert all(value in (False, 0, True) for value in result["execution_constraints"].values())
    assert result["execution_constraints"]["registry_mutation"] == 0
    assert result["execution_constraints"]["ledger_mutation"] == 0


def test_preflight_fails_closed_on_missing_role_and_same_root(tmp_path: Path):
    paths = _fixture(tmp_path)
    missing_role = dict(paths)
    missing_role.pop("scoring")

    result = build_preflight(data_root=tmp_path, evidence_paths=missing_role)

    assert result["status"] == "blocked"
    assert result["structural_preflight_passed"] is False
    assert result["errors"][0]["code"] == "EVIDENCE_ROLE_SET_MISMATCH"
    assert result["capability_minted"] is False

    roots_path = paths["data_roots"]
    roots = json.loads(roots_path.read_text(encoding="utf-8"))
    roots["reproduction_data_root"] = roots["source_data_root"]
    roots["different_data_root"] = True
    roots_path.write_text(json.dumps(roots, sort_keys=True) + "\n", encoding="utf-8")
    result = build_preflight(data_root=tmp_path, evidence_paths=paths)
    assert result["status"] == "blocked"
    assert result["errors"][0]["code"] == "DATA_ROOTS_NOT_DISTINCT"


def test_preflight_rejects_non_autonomous_or_untyped_component_output(tmp_path: Path):
    paths = _fixture(tmp_path)
    prediction_evidence_path = paths["prediction"]
    prediction_evidence = json.loads(
        prediction_evidence_path.read_text(encoding="utf-8")
    )
    prediction_ref = prediction_evidence["output_report"]
    prediction_path = tmp_path / prediction_ref["path"]
    prediction = json.loads(prediction_path.read_text(encoding="utf-8"))
    prediction["autonomous"] = False
    prediction_path.write_text(json.dumps(prediction, sort_keys=True) + "\n", encoding="utf-8")
    prediction_evidence["output_report"] = _write(
        prediction_path, prediction
    )
    prediction_evidence_path.write_text(
        json.dumps(prediction_evidence, sort_keys=True) + "\n", encoding="utf-8"
    )
    result = build_preflight(data_root=tmp_path, evidence_paths=paths)
    assert result["status"] == "blocked"
    assert result["errors"][0]["code"] == "PREDICTION_NOT_AUTONOMOUS"

    paths = _fixture(tmp_path / "untyped")
    scoring_output_ref = json.loads(
        paths["scoring"].read_text(encoding="utf-8")
    )["output_report"]
    scoring_output = tmp_path / "untyped" / scoring_output_ref["path"]
    scoring_output.write_text(json.dumps({"status": "passed"}) + "\n", encoding="utf-8")
    result = build_preflight(data_root=tmp_path / "untyped", evidence_paths=paths)
    assert result["status"] == "blocked"
    assert result["errors"][0]["code"] == "HASH_MISMATCH"


def test_preflight_rejects_chain_rebind_and_role_category_drift(tmp_path: Path):
    paths = _fixture(tmp_path)
    prediction_path = paths["prediction"]
    prediction = json.loads(prediction_path.read_text(encoding="utf-8"))
    prediction["bindings"]["reader_output_sha256"] = "f" * 64
    prediction_path.write_text(json.dumps(prediction, sort_keys=True) + "\n", encoding="utf-8")

    result = build_preflight(data_root=tmp_path, evidence_paths=paths)

    assert result["status"] == "blocked"
    assert result["errors"][0]["code"] == "COMPONENT_CHAIN_HASH_MISMATCH"

    paths = _fixture(tmp_path / "category-drift")
    reader_path = paths["reader"]
    reader = json.loads(reader_path.read_text(encoding="utf-8"))
    reader["category"] = "prediction"
    reader_path.write_text(json.dumps(reader, sort_keys=True) + "\n", encoding="utf-8")
    result = build_preflight(data_root=tmp_path / "category-drift", evidence_paths=paths)

    assert result["status"] == "blocked"
    assert result["errors"][0]["code"] == "CATEGORY_IDENTITY_MISMATCH"


def test_preflight_rejects_formal_marker_and_oversized_input(tmp_path: Path):
    paths = _fixture(tmp_path)
    scoring_evidence = json.loads(
        paths["scoring"].read_text(encoding="utf-8")
    )
    scoring_output_path = tmp_path / scoring_evidence["output_report"]["path"]
    scoring_output = json.loads(scoring_output_path.read_text(encoding="utf-8"))
    scoring_output["full_product_reproduction"] = True
    scoring_output_path.write_text(
        json.dumps(scoring_output, sort_keys=True) + "\n", encoding="utf-8"
    )
    scoring_evidence["output_report"] = _write(scoring_output_path, scoring_output)
    paths["scoring"].write_text(
        json.dumps(scoring_evidence, sort_keys=True) + "\n", encoding="utf-8"
    )
    result = build_preflight(data_root=tmp_path, evidence_paths=paths)
    assert result["status"] == "blocked"
    assert result["errors"][0]["code"] == "PRODUCT_MARKER_CONFLICT"

    oversized_root = tmp_path / "oversized"
    paths = _fixture(oversized_root)
    oversized = oversized_root / "source-host.json"
    oversized.write_bytes(b"{" + b"x" * (4 * 1024 * 1024) + b"}")
    paths["source_host"] = oversized
    result = build_preflight(data_root=oversized_root, evidence_paths=paths)
    assert result["status"] == "blocked"
    assert result["errors"][0]["code"] == "ARTIFACT_SIZE_OUT_OF_BOUNDS"


def test_preflight_rejects_duplicate_json_keys(tmp_path: Path):
    paths = _fixture(tmp_path)
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"schema":"core.reproduction.host_identity.v1",'
        '"schema":"core.reproduction.host_identity.v1"}\n',
        encoding="utf-8",
    )
    paths["source_host"] = duplicate

    result = build_preflight(data_root=tmp_path, evidence_paths=paths)

    assert result["status"] == "blocked"
    assert result["errors"][0]["code"] == "INVALID_JSON"
