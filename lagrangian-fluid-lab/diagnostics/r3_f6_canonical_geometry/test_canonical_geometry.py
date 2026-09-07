"""Regression checks for the canonical E0 geometry evidence."""

from __future__ import annotations

import pytest

from .probe import CASE_SPECS, LAB, build_report, parse_geometry_contract


REPORT = build_report()


@pytest.mark.parametrize("case_id", sorted(CASE_SPECS))
def test_real_gencase_and_cpu_solver_artifacts(case_id: str) -> None:
    case = REPORT["cases"][case_id]
    assert case["gencase"]["return_code"] == 0
    assert case["solver"]["return_code"] == 0
    assert case["gencase"]["points_loaded"] == case["generated_summary"]["np"]
    assert case["gencase"]["final_zero_normals"]["count"] == 0
    assert case["structural"]["zero_normal_count"] == 0
    assert case["structural"]["generated_counts_match_vtk"]
    assert case["solver"]["initial_normal_files_written"]
    for key in ("normal_geometry_vtk", "normal_vtk", "ghost_vtk"):
        assert (LAB / case["evidence"][key]).is_file()


def test_named_lists_separate_float1_normal_and_actual_cylinders() -> None:
    contract = parse_geometry_contract(CASE_SPECS["canonical_float1_cylinder"]["definition"])
    assert len(contract["normal_cylinders"]) == 1
    assert len(contract["actual_cylinders"]) == 1
    assert contract["normal_cylinders"][0]["radius_m"] == pytest.approx(0.11)
    assert contract["actual_cylinders"][0]["radius_m"] == pytest.approx(0.08)
    assert contract["normal_cylinders"][0]["points"] != contract["actual_cylinders"][0]["points"]
    assert contract["normal_cylinders"][0]["mkbound"] == 5
    assert contract["actual_cylinders"][0]["mkbound"] == 5


def test_rectangular_has_no_accidental_cylinder_search() -> None:
    contract = parse_geometry_contract(CASE_SPECS["canonical_rectangular"]["definition"])
    assert contract["normal_cylinders"] == []
    assert contract["actual_cylinders"] == []
    assert contract["normal_tank"]["layers_vdp"] == [-0.5]
    assert contract["actual_tank"]["layers_vdp"] == [0.0, 1.0, 2.0]


@pytest.mark.parametrize("case_id", sorted(CASE_SPECS))
def test_vtk_reconstructs_interface_and_ghost_semantics(case_id: str) -> None:
    case = REPORT["cases"][case_id]
    structural = case["structural"]
    geometry = case["geometry"]
    assert structural["points_equal_between_files"]
    assert structural["ghost_doubling_max_abs_residual"] <= 2.0e-5
    assert geometry["tank"]["max_face_residual_m"] <= 1.0e-5
    assert geometry["tank"]["edge_or_corner_count"] > 0
    assert geometry["tank"]["normal_orientation_pass"]
    if geometry["float1_cylinder"] is not None:
        assert geometry["float1_cylinder"]["max_surface_residual_m"] <= 2.0e-3
        assert geometry["float1_cylinder"]["normal_orientation_pass"]


def test_single_half_dp_shift_is_not_double_counted() -> None:
    for spec in CASE_SPECS.values():
        contract = parse_geometry_contract(spec["definition"])
        layers = contract["layer_audit"]
        assert layers["normal_tank_vdp"] == [-0.5]
        assert layers["normal_tank_half_dp_count"] == 1
        assert layers["main_tank_vdp"] == [0.0, 1.0, 2.0]
        assert layers["main_tank_half_dp_count"] == 0
        assert layers["actual_body_half_dp_count"] == 0


def test_e0_geometry_pass_does_not_promote_physical_mdbc() -> None:
    assert REPORT["status"] == "candidate"
    for case in REPORT["cases"].values():
        assert case["geometry_gate"]["status"] == "pass"
        assert case["physical_mdbc_gate"]["status"] == "blocked"
        assert not case["physical_mdbc_gate"]["mdbc_acceptance"]
    assert REPORT["compute"]["gpu_used"] is False
    assert REPORT["compute"]["production_tracer_imported"] is False
