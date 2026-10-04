"""Synthetic checks for the prospective F2 batch8 plan."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "batch8_plan.py"
SPEC = importlib.util.spec_from_file_location("f2_batch8_plan", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_plan_has_eight_unique_true3d_physical_tuples():
    plan = module.build_plan()
    assert plan["status"] == "planned_not_materialized"
    assert plan["launch_allowed"] is False
    assert plan["physical_case_count"] == 8
    assert len({row["physical_condition_sha256"] for row in plan["cases"]}) == 8
    assert all(row["single_resolution_policy"]["dp_m"] == 0.01 for row in plan["cases"])
    assert all(row["single_resolution_policy"]["solver_dimension"] == 3 for row in plan["cases"])
    assert all(row["single_resolution_policy"]["xml_data2d"] is False for row in plan["cases"])
    assert all(row["single_resolution_policy"]["resolution_views_per_physical_case"] == 1 for row in plan["cases"])


def test_plan_varies_mother_tilt_control_fill_endpoints_and_interior():
    rows = module.build_plan()["cases"]
    assert {row["mother"]["mechanism_id"] for row in rows} == {"center_catch", "offset_spill"}
    assert {row["physics_tuple"]["initial_cup_tilt_deg"] for row in rows} == {-4.0, 0.0, 4.0}
    assert {row["physics_tuple"]["rotation_duration_s"] for row in rows} == {0.65, 1.2}
    assert {row["physics_tuple"]["fluid_fill_ratio"] for row in rows} == {0.8, 1.0}
    assert {row["geometry_and_endpoints"]["mouth_geometry"] for row in rows} == {"open_rim", "short_spout"}
    assert {row["geometry_and_endpoints"]["receiver_x_m"] for row in rows} == {0.45, 0.65}
    assert {row["geometry_and_endpoints"]["receiver_y_m"] for row in rows} == {0.0, 0.14, 0.22}


def test_plan_preserves_unknowns_and_has_no_execution_authority():
    plan = module.build_plan()
    assert plan["root_only"] is True
    assert plan["common_physical_contract"]["event_window_s"] == 4.0
    for row in plan["cases"]:
        policy = row["provenance_policy"]
        assert policy["unknown_excluded_uid_retained"] is True
        assert policy["physical_spill_inference"] is False
        assert policy["source_mutation_allowed"] is False
        assert policy["materialize_only_after_root_visual_scope_review"] is True
        assert policy["numerical_precision_status"] == "not accepted"


def test_invalid_tuple_is_rejected():
    bad = dict(module.CASE_TUPLES[0])
    bad["fill_ratio"] = 1.2
    with pytest.raises(ValueError, match="outside"):
        module.validate_case_tuple(bad)
