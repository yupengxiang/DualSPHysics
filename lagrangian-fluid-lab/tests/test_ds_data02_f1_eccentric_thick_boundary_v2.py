from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
import ds_data02_f1_eccentric_thick_boundary as thick  # noqa: E402
import ds_data02_f1_eccentric_thick_boundary_v2 as thick_v2  # noqa: E402


def _grid_points(point: list[float], size: list[float], dp: float) -> np.ndarray:
    axes = []
    for low, span in zip(point, size):
        count = int(round(span / dp))
        axes.append(np.linspace(low, low + span, count + 1))
    xx, yy, zz = np.meshgrid(*axes, indexing="ij")
    return np.column_stack((xx.ravel(), yy.ravel(), zz.ravel()))


def test_static_design_keeps_outer_support_external_and_obstacle_support_internal(tmp_path):
    manifest = thick_v2.design(tmp_path, thick_v2.DEFAULT_TEMPLATE)
    case = manifest["case"]
    xml = Path(case["definition"]).read_text(encoding="utf-8")
    metadata = json.loads(Path(case["metadata"]).read_text(encoding="utf-8"))

    assert manifest["variant_id"] == "002-obstacle-internal-solid-support"
    assert manifest["recipe"]["fluid_particles"] == 80400
    assert manifest["recipe"]["fluid_mass_kg"] == 80.4
    assert manifest["recipe"]["outer_support_side"] == "outside_tank"
    assert manifest["recipe"]["obstacle_support_side"] == "inside_obstacle"
    assert manifest["no_execution_performed"] is True
    assert xml.count('cmt="thick outer support') == 5
    assert xml.count('cmt="thick obstacle support') == 5
    assert "external solid layers only" in xml
    assert "internal solid layers only" in xml
    assert 'cmt="thick obstacle support x_low; internal solid layers only"' in xml
    assert '<parameter key="Boundary" value="1" />' in xml
    assert '<parameter key="SavePosDouble" value="1" />' in xml
    assert "<normals" not in xml
    assert metadata["numeric_binding"]["obstacle_support_side"] == "inside obstacle continuous solid"
    assert metadata["numeric_binding"]["obstacle_support_layers"] == 3
    assert metadata["physical_binding"]["continuous_fluid_mass_kg"] == 80.4


def test_obstacle_support_slabs_are_three_rows_inside_and_cover_five_faces():
    dp = thick_v2.base.DP_M
    slabs = thick_v2._internal_obstacle_slabs(dp)
    lo = np.asarray(thick.OBSTACLE_LOW)
    hi = lo + np.asarray(thick.OBSTACLE_SIZE)
    rows = [_grid_points(slab["point"], slab["size"], dp) for slab in slabs.values()]
    fixed = np.unique(np.vstack(rows), axis=0)

    assert len(slabs) == 5
    assert np.all(fixed >= lo - 1e-12)
    assert np.all(fixed <= hi + 1e-12)
    assert thick_v2._obstacle_points_inside(fixed)
    assert np.isclose(slabs["x_low"]["point"][0], lo[0] + 0.5 * dp)
    assert np.isclose(slabs["x_high"]["point"][0] + slabs["x_high"]["size"][0], hi[0] - 0.5 * dp)
    assert np.isclose(slabs["y_low"]["point"][1], lo[1] + 0.5 * dp)
    assert np.isclose(slabs["y_high"]["point"][1] + slabs["y_high"]["size"][1], hi[1] - 0.5 * dp)
    assert np.isclose(slabs["z_high"]["point"][2] + slabs["z_high"]["size"][2], hi[2] - 0.5 * dp)

    report = thick_v2._internal_face_report(fixed, dp)
    assert report["all_obstacle_five_covered"] is True
    for name, row in report.items():
        if name != "all_obstacle_five_covered":
            assert row["expected_support_side"] == "inside_obstacle"
            assert row["covered"] is True
            assert row["inward_orientation_fraction"] >= 0.90


def test_obstacle_support_semantics_reject_external_rows():
    dp = thick_v2.base.DP_M
    external = [
        _grid_points(slab["point"], slab["size"], dp)
        for slab in thick_v2.base._obstacle_slabs(dp).values()
    ]
    fixed = np.unique(np.vstack(external), axis=0)
    report = thick_v2._internal_face_report(fixed, dp)
    assert report["all_obstacle_five_covered"] is False
    assert thick_v2._obstacle_points_inside(fixed) is False
