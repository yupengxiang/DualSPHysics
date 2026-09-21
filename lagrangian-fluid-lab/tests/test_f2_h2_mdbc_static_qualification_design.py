from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.f2_h2_mdbc_static_qualification_design import build_design


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ref(path: Path, role: str) -> dict:
    return {"path": str(path.resolve()), "sha256": _digest(path), "bytes": path.stat().st_size, "role": role}


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = tmp_path / "source_Def.xml"
    source.write_text("<definition><normal-support vdp=\"-0.5\" distanceh=\"3\" /></definition>\n")
    canary = tmp_path / "prepared.json"
    canary.write_text(json.dumps({
        "schema": "core.cfd.v1",
        "config": {
            "family": "F2",
            "scope_id": "F2_H2_mdbc_boundary_repair_canary_v1",
            "case_id": "CORE_F2_H2_mdbc_boundary_repair_dp0p007500000000_canary",
            "boundary_method": 2,
            "runtime_domain": {"changed_zmax": 2.4},
            "cup": {"low": [0.0, -0.15, 0.65], "size": [0.425, 0.30, 0.45], "mkbound": 0},
            "receiver": {"low": [0.45, -0.30, 0.0], "size": [1.10, 0.60, 0.45], "mkbound": 1},
            "tray": {"low": [-0.60, -0.55, -0.20], "size": [2.60, 1.10, 0.10], "mkbound": 2},
        },
        "preflight_pass": True,
        "mass_preflight": {"mass_rescaling": False},
        "native_initial": {"zero_boundary_normals": 0},
        "static_diagnostic_preflight": {"mdbc_normals_complete_nonzero": True},
        "source_template": str(source.resolve()),
        "source_template_sha256": _digest(source),
    }, indent=2) + "\n")
    review = tmp_path / "root-review.json"
    review.write_text(json.dumps({
        "schema": "core.root_review.v1",
        "scope_id": "F2_H2_mdbc_boundary_repair_canary_v1",
        "decision": "approved_for_runtime_smoke",
        "authorized_cell_indices": [0],
        "registry_mutation": 0,
        "qualification_claim": "none",
    }, indent=2) + "\n")
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({
        "schema": "core.f2.h2_mdbc_boundary_repair.canary_evidence.v1",
        "scope_id": "F2_H2_mdbc_boundary_repair_canary_v1",
        "case_id": "CORE_F2_H2_mdbc_boundary_repair_dp0p007500000000_canary",
        "prepared": _ref(canary, "prepared"),
        "root_review": _ref(review, "root review"),
        "scientific_status": {"T1_numerical": False, "registry_mutation": 0, "event_window_complete": False},
        "decision": {"qualification_scope_ready": False, "expand_to_15_cell_matrix": False},
        "diagnostics": {"minimum_cup_retention_mass_fraction": 0.9668},
    }, indent=2) + "\n")
    return canary, evidence, review


def test_design_is_independent_15_cell_cpu_only_plan(tmp_path: Path) -> None:
    canary, evidence, review = _fixture(tmp_path)
    design = build_design(canary, evidence, review)
    qualification = design["qualification_design"]
    cells = qualification["cells"]

    assert design["schema"] == "core.f2.h2_mdbc_static_qualification_design.v1"
    assert qualification["cell_count"] == 15
    assert len(cells) == 15
    assert [cell["index"] for cell in cells] == list(range(15))
    assert {cell["q"] for cell in cells[:9]} == {0.0, 0.5, 1.0}
    assert {cell["dp_m"] for cell in cells[:9]} == {0.01, 0.0075, 0.005}
    assert {cell["q"] for cell in cells[9:13]} == {0.25, 0.75}
    assert [cell["design_cell"] for cell in cells[13:]] == ["internal_time", "native_output"]
    assert cells[13]["output_interval_s"] == 0.02
    assert cells[14]["output_interval_s"] == 0.01
    assert len({cell["design_cell_sha256"] for cell in cells}) == 15
    assert all(cell["prepared"] is None and cell["job"] is None for cell in cells)
    assert all(cell["materialization"]["reuse_canary_trajectory"] is False for cell in cells)
    assert design["failure_denominator"]["fixed"] == 15
    assert len(design["failure_denominator"]["rows"]) == 15
    assert design["failure_denominator"]["survivor_renormalization"] is False
    assert design["normal_contract"]["zero_boundary_normals_max"] == 0
    assert design["normal_contract"]["normal_count_equals_boundary_count"] is True
    assert design["admission_controls"]["solver_launch_allowed"] is False
    assert design["admission_controls"]["gpu_launch_allowed"] is False
    assert design["admission_controls"]["job_spec_creation_allowed"] is False
    assert design["execution_controls"]["gencase_invoked"] is False
    assert design["execution_controls"]["native_decoder_invoked"] is False
    assert design["execution_controls"]["registry_mutation"] == 0
    assert design["materialization_decision"]["cpu_materialization_safe_now"] is False


def test_design_rejects_changed_hash_bound_canary(tmp_path: Path) -> None:
    canary, evidence, review = _fixture(tmp_path)
    payload = json.loads(canary.read_text())
    payload["tampered"] = True
    canary.write_text(json.dumps(payload, indent=2) + "\n")
    with pytest.raises(ValueError, match="prepared.*hash mismatch"):
        build_design(canary, evidence, review)
