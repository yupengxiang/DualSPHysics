from __future__ import annotations

import json
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
import ds_data02_f1_eccentric_cellcenter as cellcenter  # noqa: E402


def test_design_registers_three_integer_cell_center_populations(tmp_path):
    manifest = cellcenter.design(tmp_path, cellcenter.DEFAULT_TEMPLATE)
    assert len(manifest["resolutions"]) == 3
    assert [row["counts_xyz"] for row in manifest["resolutions"]] == [[40, 67, 30], [80, 134, 60], [120, 201, 90]]
    assert [row["expected_fluid_particles"] for row in manifest["resolutions"]] == [80400, 643200, 2170800]
    assert {row["expected_fluid_mass_kg"] for row in manifest["resolutions"]} == {80.4}
    assert len({row["physical_hash"] if "physical_hash" in row else manifest["source"]["physical_hash"] for row in manifest["resolutions"]}) == 1


def test_definitions_keep_physical_geometry_and_use_half_cell_phase(tmp_path):
    manifest = cellcenter.design(tmp_path, cellcenter.DEFAULT_TEMPLATE)
    for row in manifest["resolutions"]:
        text = Path(row["definition"]).read_text(encoding="utf-8")
        dp = row["dp_m"]
        assert f'<pointmin x="{cellcenter._q(-dp / 2)}"' in text
        assert 'layers vdp="0,1,2"' in text
        assert f'<fillbox x="{cellcenter._q(dp)}"' in text
        assert '<modefill>fluid</modefill>' in text
        assert 'boundary' not in text.lower().split('<execution>', 1)[0]
        assert '<normals' not in text
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
