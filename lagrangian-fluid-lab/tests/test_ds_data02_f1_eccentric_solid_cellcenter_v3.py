from __future__ import annotations

import json
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
import ds_data02_f1_eccentric_solid_cellcenter_v3 as cellcenter  # noqa: E402


def test_repair003_design_registers_three_integer_solid_drawbox_populations(tmp_path):
    manifest = cellcenter.design(tmp_path, cellcenter.DEFAULT_TEMPLATE)
    assert len(manifest["resolutions"]) == 3
    assert [row["counts_xyz"] for row in manifest["resolutions"]] == [[40, 67, 30], [80, 134, 60], [120, 201, 90]]
    assert [row["expected_fluid_particles"] for row in manifest["resolutions"]] == [80400, 643200, 2170800]
    assert {row["expected_fluid_mass_kg"] for row in manifest["resolutions"]} == {80.4}
    assert len({row["physical_hash"] if "physical_hash" in row else manifest["source"]["physical_hash"] for row in manifest["resolutions"]}) == 1


def test_repair003_definitions_keep_geometry_and_redraw_outer_faces(tmp_path):
    manifest = cellcenter.design(tmp_path, cellcenter.DEFAULT_TEMPLATE)
    for row in manifest["resolutions"]:
        text = Path(row["definition"]).read_text(encoding="utf-8")
        dp = row["dp_m"]
        assert f'<pointmin x="{cellcenter._q(-dp / 2)}"' in text
        assert 'layers vdp="0,1,2"' in text
        assert '<fillbox' not in text
        assert '<setmkfluid mk="0" />' in text
        assert '<drawbox cmt="Cell-centre fluid population; numeric solid drawbox only">' in text
        assert '<boxfill>solid</boxfill>' in text
        assert 'boundary' not in text.lower().split('<execution>', 1)[0]
        assert '<normals' not in text
        assert 'Repair-003: redraw physical outer faces outside solid fluid; vdp=-1 only' in text
        assert text.count('<layers vdp="-1" />') == 1
        assert 'point x="0" y="0" z="0"' in text
        assert 'size x="1.6" y="0.67" z="0.4"' in text
        metadata = json.loads(Path(row["metadata"]).read_text(encoding="utf-8"))
        assert metadata["physical_binding"]["continuous_fluid_mass_kg"] == 80.4
        assert metadata["physical_binding"]["mass_normalization"] == "forbidden"


def test_finite_face_sampling_contract_covers_obstacle_five_faces():
    assert len(cellcenter.OBSTACLE_FACE_BOXFILL.split(" | ")) == 5
    assert len(cellcenter.OUTER_FACE_BOXFILL.split(" | ")) == 5
    assert cellcenter.OBSTACLE_LOW == (0.9, 0.24, 0.0)
    assert cellcenter.OBSTACLE_SIZE == (0.12, 0.12, 0.45)


def test_wetted_floor_diagnostic_excludes_only_frozen_obstacle_intersection():
    dp = 0.01
    xs = [i * dp for i in range(161)]
    ys = [i * dp for i in range(68)]
    points = []
    for x in xs:
        for y in ys:
            if 0.9 - 1e-12 <= x <= 1.02 + 1e-12 and 0.24 - 1e-12 <= y <= 0.36 + 1e-12:
                continue
            points.append((x, y, 0.0))
    cloud = cellcenter.np.asarray(points, dtype=float)
    full = cellcenter.finite_face_report(cloud, dp)
    wetted = cellcenter.wetted_face_report(cloud, dp)
    assert full["outer_faces"]["z_low"]["covered"] is False
    assert wetted["physical_partition"]["floor_intersection_rule"].startswith("exclude exactly")
    assert wetted["z_low_wetted_diagnostic"]["covered"] is True
    assert wetted["qualification_effect"].startswith("diagnostic only")
