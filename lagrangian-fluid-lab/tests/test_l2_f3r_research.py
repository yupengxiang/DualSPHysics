from __future__ import annotations

import copy
import json
from pathlib import Path

from scripts import l2_f3r_research as f3r


HASH_A = "a" * 64
HASH_B = "b" * 64


def _recipe() -> dict:
    return {
        "recipe_id": "F3R_recipe_v1",
        "production_resolution_m": 0.0075,
        "reference_resolutions_m": [0.00818181818181818, 0.0075, 0.006],
        "solver_mode": "-mdbc_noslip:1",
        "boundary": 2,
        "slip_mode": 2,
        "no_penetration": True,
        "visco": 0.05,
        "visco_bound_factor": 1,
        "shifting": 0,
        "native_velocity_displacement_correction": True,
        "posthoc_particle_projection": False,
        "time_window_s": [0.0, 8.35],
        "output_interval_s": 0.01,
        "control_domain": [0.9, 1.1],
        "coordinate_frame": "fixed tank computational coordinates",
        "trajectory_semantics": "numerical SPH particle identity",
    }


def _canonical(case_count: int = 32) -> dict:
    recipe = _recipe()
    cases = [
        {
            "case_id": f"legacy-{index:02d}",
            "recipe_id": recipe["recipe_id"],
            "qualification_axes": {"structural": True, "T1_registered_numerical": True},
        }
        for index in range(case_count)
    ]
    return {
        "schema": "l2.f3.canonical_manifest.v1",
        "status": "registered_T1_preserved; independent_A0_audit_recorded",
        "recipe": recipe,
        "source_records": {"gate": {"path": "gate.json", "sha256": HASH_A}},
        "cases": cases,
    }


def _gate(recipe: dict | None = None) -> dict:
    recipe = recipe or _recipe()
    return {
        "schema": "f3.revision075.ref0081818.gate.v1",
        "status": "passed",
        "recipe_id": recipe["recipe_id"],
        "production_resolution_m": recipe["production_resolution_m"],
        "reference_resolutions_m": recipe["reference_resolutions_m"],
    }


def _bad_c2() -> dict:
    return {
        "design": {
            "background": "off-axis baffle connected passage",
            "connected_passage_semantics": "baffle leaves an upper passage",
        },
        "input": {"recipe_id": "L2_F3_C2_offaxis_connected_passage_dbc_native_v1_dp0p0075"},
        "audit": {
            "case_id": "c2",
            "canary_hard_integrity_pass": False,
            "independent_audit": {
                "structural_pass": False,
                "finite": {"position": False, "velocity": False, "mass": False},
                "wall_violation_count": 582,
            },
            "semantic_audit": {"source_semantics_present": True, "control_semantics_present": False},
            "control_audit": {"present": True},
        },
        "acceptance": {
            "offaxis_geometry_template_recorded": True,
            "hard_canary_pass": False,
        },
    }


def _good_candidate() -> dict:
    recipe = _recipe()
    cases = []
    for background_id in ("offaxis_baffle", "multi_axis_drive"):
        for index, resolution in enumerate(recipe["reference_resolutions_m"]):
            cases.append({
                "case_id": f"{background_id}-{index}",
                "recipe_id": recipe["recipe_id"],
                "background_id": background_id,
                "resolution_m": resolution,
                "geometry_id": f"geometry-{background_id}",
                "control_id": f"control-{background_id}",
                "hard_audit_passed": True,
                "source_hashes": [HASH_A, HASH_B],
            })
    return {
        "schema": f3r.CANDIDATE_SCHEMA,
        "recipe": {
            "recipe_card": recipe,
            "hard_audit_passed": True,
            "source_hashes": [HASH_A],
        },
        "cases": cases,
        "control_geometry": {
            "new_geometry": True,
            "topology_evidence": True,
            "new_control": True,
            "control_semantics_evidence": True,
            "hard_audit_passed": True,
            "source_hashes": [HASH_B],
        },
    }


def test_legacy_reference_is_separate_from_f3r_and_rejects_current_scope():
    report = f3r.build_report(_canonical(), _gate(), _bad_c2(), commit="fixture")

    assert report["reference_recipe"]["status"] == "qualified_reference"
    assert report["decision"] == "bounded_rejection"
    assert report["background_resolution_coverage"]["fallback_observation_used"] is True
    assert report["new_control_geometry_evidence"]["status"] == "bounded_rejection"
    assert report["receipt_policy"]["receipt_emitted"] is False
    assert any("historical_c2_hard_integrity_failed" in item["code"] for item in report["blockers"])


def test_explicit_candidate_matrix_can_pass_without_emitting_receipt():
    candidate = _good_candidate()
    report = f3r.build_report(_canonical(), _gate(), _bad_c2(), candidate=candidate, commit="fixture")

    assert report["candidate_recipe"]["status"] == "qualified_recipe"
    assert report["background_resolution_coverage"]["status"] == "passed"
    assert report["new_control_geometry_evidence"]["status"] == "passed"
    assert report["decision"] == "qualified_recipe"
    assert report["receipt_policy"]["receipt_emitted"] is False


def test_missing_background_resolution_cell_is_bounded_rejection():
    candidate = _good_candidate()
    candidate["cases"] = candidate["cases"][:-1]

    coverage = f3r.assess_background_resolution_coverage(_canonical(), candidate)

    assert coverage["status"] == "bounded_rejection"
    assert coverage["observed_background_count"] == 2
    assert coverage["complete_background_count"] == 1
    assert coverage["missing_cells"]
    assert any("complete_background_count" in error for error in coverage["errors"])


def test_candidate_hash_and_topology_contract_fails_closed():
    candidate = _good_candidate()
    candidate["recipe"]["source_hashes"] = ["not-a-hash"]
    candidate["control_geometry"]["topology_evidence"] = False
    candidate["control_geometry"]["source_hashes"] = []

    recipe = f3r.assess_candidate_recipe(candidate)
    control = f3r.assess_control_geometry_evidence(_bad_c2(), candidate)

    assert recipe["status"] == "bounded_rejection"
    assert "candidate_recipe_source_hashes_invalid" in recipe["errors"]
    assert control["status"] == "bounded_rejection"
    assert "candidate_control_geometry_topology_evidence_missing" in control["errors"]
    assert "candidate_control_geometry_source_hashes_missing" in control["errors"]


def test_report_source_refs_hash_files_and_cli_does_not_require_gpu(tmp_path: Path, monkeypatch):
    canonical_path = tmp_path / "canonical.json"
    gate_path = tmp_path / "gate.json"
    c2_path = tmp_path / "c2.json"
    canonical_path.write_text(json.dumps(_canonical()), encoding="utf-8")
    gate_path.write_text(json.dumps(_gate()), encoding="utf-8")
    c2_path.write_text(json.dumps(_bad_c2()), encoding="utf-8")

    output = tmp_path / "report.json"
    rc = f3r.main([
        "preflight",
        "--canonical", str(canonical_path),
        "--gate", str(gate_path),
        "--c2-report", str(c2_path),
        "--output", str(output),
    ])

    assert rc == 2
    report = json.loads(output.read_text(encoding="utf-8"))
    assert all(item["exists"] and item["sha256"] for item in report["source_evidence"])
    assert report["experiment_plan"]["solver_matrix_launched"] is False
    assert report["receipt_policy"]["receipt_emitted"] is False
