from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
import ds_data02_f1_eccentric_thick_boundary as thick  # noqa: E402


def _grid_points(point: list[float], size: list[float], dp: float) -> np.ndarray:
    axes = []
    for low, span in zip(point, size):
        count = int(round(span / dp))
        axes.append(np.linspace(low, low + span, count + 1))
    xx, yy, zz = np.meshgrid(*axes, indexing="ij")
    return np.column_stack((xx.ravel(), yy.ravel(), zz.ravel()))


def test_static_design_is_three_layer_external_dbc_recipe(tmp_path):
    manifest = thick.design(tmp_path, thick.DEFAULT_TEMPLATE)
    case = manifest["case"]
    xml = Path(case["definition"]).read_text(encoding="utf-8")
    metadata = json.loads(Path(case["metadata"]).read_text(encoding="utf-8"))

    assert manifest["recipe"]["fluid_particles"] == 80400
    assert manifest["recipe"]["fluid_mass_kg"] == 80.4
    assert manifest["recipe"]["support_layers"] == 3
    assert manifest["recipe"]["uses_vdp"] is False
    assert '<pointref x="0.005" y="0.005" z="0.005" />' in xml
    assert '<parameter key="Boundary" value="1" />' in xml
    assert '<parameter key="SavePosDouble" value="1" />' in xml
    assert "<normals" not in xml
    assert xml.count('<boxfill>solid</boxfill>') == 12
    assert xml.count('cmt="thick outer support') == 5
    assert xml.count('cmt="thick obstacle support') == 5
    assert '<point x="0.005" y="0.005" z="0.005" />' in xml
    assert '<size x="0.39" y="0.66" z="0.29" />' in xml
    assert metadata["physical_binding"]["continuous_fluid_mass_kg"] == 80.4
    assert metadata["physical_binding"]["mass_normalization"] == "forbidden"
    assert metadata["numeric_binding"]["nearest_fixed_offset_m"] == 0.005


def test_external_slabs_have_no_fluid_row_and_cover_frozen_faces():
    fixed_rows = []
    for slab in thick._slab_geometry(thick.DP_M).values():
        fixed_rows.append(_grid_points(slab["point"], slab["size"], thick.DP_M))
    for slab in thick._obstacle_slabs(thick.DP_M).values():
        fixed_rows.append(_grid_points(slab["point"], slab["size"], thick.DP_M))
    fixed = np.unique(np.vstack(fixed_rows), axis=0)
    report = thick.finite_face_report(fixed)

    assert report["all_outer_five_covered"] is True
    assert report["all_obstacle_five_covered"] is True
    for row in list(report["outer"].values()) + list(report["obstacle"].values()):
        assert row["external_orientation"] is True
        assert row["near_plane_fixed_points"] > 0
    fluid = _grid_points([0.005, 0.005, 0.005], [0.39, 0.66, 0.29], thick.DP_M)
    assert len(fluid) == 80400
    # The nearest external support row is one dp away from the first fluid
    # row; no support point may coincide with a source fluid centre.
    assert float(thick.cKDTree(fixed).query(fluid, workers=1)[0].min()) >= 0.009999


def test_source_binding_rejects_mdbc_or_changed_continuous_boxes(tmp_path):
    source = tmp_path / "source.xml"
    source.write_text(thick.DEFAULT_TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
    text = source.read_text(encoding="utf-8").replace('gravity x="0" y="0" z="-9.81"', 'gravity x="0" y="0" z="-8.81"', 1)
    source.write_text(text, encoding="utf-8")
    try:
        thick.inspect_source(source)
    except ValueError:
        pass
    else:
        raise AssertionError("changed ECC continuous control was accepted")

