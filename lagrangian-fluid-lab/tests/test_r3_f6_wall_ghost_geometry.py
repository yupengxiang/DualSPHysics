"""CPU-only regression tests for the F6 wall/ghost geometry audit."""

from __future__ import annotations

import numpy as np

from diagnostics.r3_f6_wall_ghost_geometry.probe import (
    LAB,
    build_report,
    read_binary_vtk_fields,
)


def test_binary_vtk_field_parser_exposes_boundary_and_ghost_arrays():
    report = build_report()
    for variant in report["variants"].values():
        normal = read_binary_vtk_fields(
            LAB / variant["source_files"]["boundary_normals_vtk"]
        )
        ghost = read_binary_vtk_fields(
            LAB / variant["source_files"]["ghost_normals_vtk"]
        )
        assert normal["count"] == ghost["count"]
        assert {"Mk", "Normal", "NormalSize"}.issubset(normal["arrays"])
        assert np.array_equal(normal["points"], ghost["points"])


def test_solver_doubling_and_interface_are_explicit():
    report = build_report()
    baseline = report["variants"]["baseline"]
    candidate = report["variants"]["inward_030"]
    assert baseline["interpretation"]["effective_interface"].startswith("x_gamma")
    assert baseline["structural"]["zero_normal_count"] == 792
    assert candidate["structural"]["zero_normal_count"] == 0
    assert candidate["structural"]["ghost_doubling_ratio_min"] == 2.0
    assert candidate["structural"]["ghost_doubling_ratio_max"] == 2.0
    assert candidate["gate"]["overall_geometry_gate_pass"] is False
    assert candidate["gate"]["independent_ghost_coordinate_observed"] is False


def test_component_and_wetting_counts_are_not_hidden_in_an_overall_percentage():
    report = build_report()
    for label, variant in report["variants"].items():
        structural = variant["structural"]
        geometry = variant["geometry"]
        assert structural["boundary_count"] == structural["fixed_count"] + structural["floating_count"]
        assert sum(structural["zero_normal_by_mk"].values()) == structural["zero_normal_count"]
        waterline = geometry["waterline_partition"]
        assert waterline["boundary_below_count"] + waterline["boundary_at_or_above_count"] == structural["floating_count"]
        assert waterline["interface_below_count"] + waterline["interface_at_or_above_count"] == structural["floating_count"]


def test_no_variant_is_promoted_to_physical_acceptance():
    report = build_report()
    assert report["candidate_only"] is True
    assert report["acceptance_status"] == "candidate_geometry_only_rejected"
    assert all(not item["gate"]["overall_geometry_gate_pass"] for item in report["variants"].values())
    assert report["compute"]["gpu_used"] is False
    assert report["compute"]["cfd_solver_run"] is False
