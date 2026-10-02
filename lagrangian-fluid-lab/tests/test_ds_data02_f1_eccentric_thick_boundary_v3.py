from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
import ds_data02_f1_eccentric_thick_boundary_v3 as thick_v3  # noqa: E402


def _grid_points(point: list[float], size: list[float], dp: float) -> np.ndarray:
    axes = []
    for low, span in zip(point, size):
        count = int(round(span / dp))
        axes.append(np.linspace(low, low + span, count + 1))
    xx, yy, zz = np.meshgrid(*axes, indexing="ij")
    return np.column_stack((xx.ravel(), yy.ravel(), zz.ravel()))


@pytest.mark.parametrize(
    ("token", "counts", "particles"),
    [
        ("DP005", (80, 134, 60), 643200),
        ("DP003333333333333333", (120, 201, 90), 2170800),
    ],
)
def test_resolution_contract_and_storage_estimate(token, counts, particles):
    spec = thick_v3._resolution(token)
    assert spec.counts_xyz == counts
    assert spec.fluid_particles == particles
    assert spec.fluid_mass_kg == 80.4
    assert spec.trajectory_bytes_estimate == (particles + thick_v3._support_count_estimate(spec.dp)) * 1601 * 64
    assert spec.trajectory_bytes_estimate > particles * 1601 * 50


@pytest.mark.parametrize("token", ["DP005", "DP003333333333333333"])
def test_design_writes_independent_v3_case_and_native_padding(tmp_path, token):
    manifest = thick_v3.design(tmp_path, token, thick_v3.DEFAULT_TEMPLATE)
    spec = thick_v3._resolution(token)
    case = manifest["case"]
    metadata = json.loads(Path(case["metadata"]).read_text(encoding="utf-8"))
    xml = Path(case["definition"]).read_text(encoding="utf-8")

    assert case["case_id"] == spec.case_id
    assert manifest["variant_id"] == "003-generalized-grid"
    assert manifest["no_execution_performed_at_design"] is True
    assert metadata["physical_binding"]["physical_hash"] == "bb449a2c1d34c75ea6f94d6f5e9124c4eedf0f5b1667ec5225700e6bf11495b5"
    assert metadata["expected_initial"]["fluid_particles"] == spec.fluid_particles
    assert metadata["expected_initial"]["fluid_mass_kg"] == 80.4
    assert xml.count('cmt="v3 thick outer support') == 5
    assert xml.count('cmt="v3 thick obstacle support') == 5
    assert "internal solid layers only" in xml
    assert "external solid layers only" in xml
    assert '<parameter key="Boundary" value="1" />' in xml
    assert '<parameter key="SavePosDouble" value="1" />' in xml
    assert "<normals" not in xml
    assert metadata["numeric_binding"]["native_expected_support_bounds_m"][0] == pytest.approx([-2.5 * spec.dp] * 3)
    assert metadata["numeric_binding"]["native_expected_support_bounds_m"][1] == pytest.approx([1.6 + 2.5 * spec.dp, .67 + 2.5 * spec.dp, .4 + 2.5 * spec.dp])


@pytest.mark.parametrize("token", ["DP005", "DP003333333333333333"])
def test_internal_obstacle_faces_are_covered_from_solid_side(token):
    spec = thick_v3._resolution(token)
    rows = [
        _grid_points(slab["point"], slab["size"], spec.dp)
        for slab in thick_v3._internal_obstacle_slabs(spec.dp).values()
    ]
    fixed = np.unique(np.round(np.vstack(rows), 10), axis=0)
    assert thick_v3._obstacle_points_inside(fixed)
    report = thick_v3._internal_face_report(fixed, spec.dp)
    assert report["all_obstacle_five_covered"] is True
    for name, row in report.items():
        if name != "all_obstacle_five_covered":
            assert row["expected_support_side"] == "inside_obstacle"
            assert row["covered"] is True
            assert row["inward_orientation_fraction"] >= .90
