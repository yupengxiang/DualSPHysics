from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f7_s1_three_grid_coordinate_face_lattice_audit_v1.py"
SPEC = importlib.util.spec_from_file_location("f7_coordinate_face_lattice_audit_v1", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _selector():
    return {
        "fluid_selector_boxes": [
            {"low_m": [-0.55, -0.35, 0.05], "high_m": [0.55, 0.35, 0.482]},
        ],
        "selector_union_low_m": [-0.55, -0.35, 0.05],
        "selector_union_high_m": [0.55, 0.35, 0.482],
    }


def _frame(points):
    points = np.asarray(points, dtype=np.float64)
    total = len(points)
    fluid = total - 1
    return {
        "_ids": np.arange(total, dtype=np.int64),
        "_positions": points,
        "_types": None,
        "header": {"CaseNp": total, "CaseNfluid": fluid},
        "total_particles": total,
        "fluid_particles": fluid,
        "finite_positions": True,
        "id_unique": True,
    }


def test_per_id_faces_preserve_count_and_fixed_ulp_diagnostic():
    one_below_x = np.nextafter(MODULE.OWNER_LOW[0], -np.inf)
    one_above_y = np.nextafter(MODULE.OWNER_HIGH[1], np.inf)
    points = [
        [0.0, 0.0, 0.0],  # fixed/header row
        [one_below_x, 0.0, 0.1],
        [0.1, one_above_y, 0.1],
    ]
    result = MODULE._frame_coordinate_audit(
        _frame(points),
        {"dp_m": 0.1, "fluid_count": 2},
        _selector(),
        expected_outside=2,
        label="coarse",
    )
    assert result["outside_owner_envelope_count"] == 2
    assert result["outside_extended_4ulp_count"] == 0
    assert result["face_counts_unique_outside_ids"] == {"x_low": 1, "x_high": 0, "y_low": 0, "y_high": 1, "z_low": 0, "z_high": 0}
    assert [row["Idp"] for row in result["outside_records"]] == [1, 2]
    assert result["outside_records"][0]["face_bitmask"] == MODULE.FACE_BITS["x_low"]
    assert result["outside_records"][1]["face_bitmask"] == MODULE.FACE_BITS["y_high"]
    assert result["all_violating_faces_within_fixed_4ulp_count"] == 2
    assert result["representation_allowance"]["not_a_scientific_tolerance"] is True


def test_four_ulp_extension_is_fixed_and_does_not_change_exact_mask():
    point = MODULE.OWNER_LOW.copy()
    for _ in range(MODULE.ENDPOINT_ULP_ALLOWANCE + 1):
        point[0] = np.nextafter(point[0], -np.inf)
    result = MODULE._frame_coordinate_audit(
        _frame([[0.0, 0.0, 0.0], point]),
        {"dp_m": 0.1, "fluid_count": 1},
        _selector(),
        expected_outside=1,
        label="coarse",
    )
    assert result["outside_owner_envelope_count"] == 1
    assert result["outside_extended_4ulp_count"] == 1
    assert result["all_violating_faces_within_fixed_4ulp_count"] == 0


def test_spacing_and_phase_are_observed_diagnostics():
    result = MODULE._frame_coordinate_audit(
        _frame([[0.0, 0.0, 0.0], [0.0, 0.0, 0.1], [0.1, 0.2, 0.2]]),
        {"dp_m": 0.1, "fluid_count": 2},
        _selector(),
        expected_outside=0,
        label="original",
    )
    x = result["spacing_phase_by_axis"][0]
    assert x["declared_dp_m"] == 0.1
    assert x["coordinate_unique_count"] == 2
    assert x["spacing_distribution_m"] == [{"value": 0.1, "count": 1}]
    assert x["phase_interpretation"].startswith("observed coordinate/dp")
    assert result["sampling_diagnostic"]["inclusive_or_cell_center_mechanism"].startswith("UNKNOWN")


def test_closed_and_half_open_selector_membership_is_reported_separately():
    result = MODULE._frame_coordinate_audit(
        _frame([[0.0, 0.0, 0.0], [0.55, 0.35, 0.482]]),
        {"dp_m": 0.1, "fluid_count": 1},
        _selector(),
        expected_outside=0,
        label="fine",
    )
    membership = result["selector_vs_owner_paddle"]
    assert membership["selector_closed_hit_count"] == 1
    assert membership["selector_half_open_hit_count"] == 0
    assert membership["selector_closed_vs_half_open_disagreement_count"] == 1
