from pathlib import Path
import importlib.util

import numpy as np


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ds_data02_f1_normal_support_audit.py"
SPEC = importlib.util.spec_from_file_location("f1_normal_support_audit", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_orientation_ignores_zero_edge_dot_but_rejects_opposite() -> None:
    normals = np.asarray([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0]])
    mask = np.asarray([True, True, True])
    interior = np.asarray([True, True, True])
    result = MODULE._orientation_summary(normals, mask, interior, (1.0, 0.0, 0.0))
    assert result["positive_dot_count"] == 1
    assert result["zero_dot_count"] == 1
    assert result["negative_dot_count"] == 1
    assert result["orientation_pass"] is False


def test_orientation_passes_aligned_and_composite_vectors() -> None:
    normals = np.asarray([[1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [1.0, 0.0, 1.0]])
    mask = np.asarray([True, True, True])
    interior = np.asarray([True, True, True])
    result = MODULE._orientation_summary(normals, mask, interior, (1.0, 0.0, 0.0))
    assert result["negative_dot_count"] == 0
    assert result["aligned_fraction"] == 1.0
    assert result["orientation_pass"] is True


def test_face_specs_cover_five_outer_and_five_separator_faces() -> None:
    names = {spec["name"] for spec in MODULE.FACE_SPECS}
    assert names == {
        "outer_x_low", "outer_x_high", "outer_y_low", "outer_y_high", "outer_z_low",
        "separator_x_low", "separator_x_high", "separator_y_low", "separator_y_high", "separator_z_high",
    }
