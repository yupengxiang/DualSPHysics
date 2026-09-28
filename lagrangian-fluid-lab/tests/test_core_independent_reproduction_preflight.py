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
    return {"path": path.name, "sha256": digest(path)}


def _fixture(tmp_path: Path) -> dict[str, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    source_root = "/datasets/core-source"
    reproduction_root = "/scratch/core-relocated"
    package_hash = "a" * 64
    source_manifest_path = tmp_path / "source-manifest.json"
    reproduction_manifest_path = tmp_path / "reproduction-manifest.json"
    source_manifest = _write(source_manifest_path, {
        "schema": "core.reproduction.package_manifest.v1",
        "data_root": source_root,
        "package_sha256": package_hash,
    })
    reproduction_manifest = _write(reproduction_manifest_path, {
        "schema": "core.reproduction.package_manifest.v1",
        "data_root": reproduction_root,
        "package_sha256": package_hash,
    })
    _write(tmp_path / "source-host.json", {
        "schema": "core.reproduction.host_identity.v1",
        "passed": True,
        "hostname": "source-host",
        "physical_host_id": "physical-source",
    })
    _write(tmp_path / "reproduction-host.json", {
        "schema": "core.reproduction.host_identity.v1",
        "passed": True,
        "hostname": "reproduction-host",
        "physical_host_id": "physical-reproduction",
    })
    _write(tmp_path / "data-roots.json", {
        "schema": "core.reproduction.data_roots.v1",
        "passed": True,
        "source_data_root": source_root,
        "reproduction_data_root": reproduction_root,
        "different_data_root": True,
        "source_manifest": source_manifest,
        "reproduction_manifest": reproduction_manifest,
        "source_manifest_sha256": source_manifest["sha256"],
        "reproduction_manifest_sha256": reproduction_manifest["sha256"],
    })

    output_payloads = {
        "reader": {
            "schema": "core.reader_reproduction.v1",
            "passed": True,
        },
        "prediction": {
            "schema": "core.model_reproduction.v1",
            "passed": True,
            "full_horizon_reproduction": True,
            "full_product_reproduction": True,
            "paired_diagnostic_cross_host": False,
            "predictor_future_state_inputs": False,
        },
        "scoring": {
            "schema": "core.model_reproduction.score.v1",
            "metrics": {
                "registered_cases": 1,
                "complete_fraction": 1.0,
                "missing_execution": 0,
            },
            "cases": ["case-0"],
            "predictor_future_state_inputs": False,
        },
    }
    paths = {
        "source_host": tmp_path / "source-host.json",
        "reproduction_host": tmp_path / "reproduction-host.json",
        "data_roots": tmp_path / "data-roots.json",
    }
    reproduction_host_id = "physical-reproduction"
    for component, output_payload in output_payloads.items():
        output_ref = _write(tmp_path / f"{component}-output.json", output_payload)
        evidence = {
            "schema": "core.reproduction.component.v1",
            "component": component,
            "passed": True,
            f"{component}_reproduced": True,
            "physical_host_id": reproduction_host_id,
            "data_root": reproduction_root,
            "output_report": output_ref,
        }
        if component == "prediction":
            evidence.update({
                "autonomous": True,
                "full_horizon": True,
                "future_state_inputs": False,
            })
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
    assert result["capability_minted"] is False
    assert result["formal_admission"] is False
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
    prediction_path = paths["prediction"]
    prediction = json.loads(prediction_path.read_text(encoding="utf-8"))
    prediction["autonomous"] = False
    prediction_path.write_text(json.dumps(prediction, sort_keys=True) + "\n", encoding="utf-8")
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
