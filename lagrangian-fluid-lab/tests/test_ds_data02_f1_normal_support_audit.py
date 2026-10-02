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


def test_bound_vtk_field_arrays_are_retained_as_point_aligned_data(tmp_path: Path) -> None:
    """GenCase stores Mk/Type/Normal/NormalSize in FIELD after POINT_DATA."""

    n = 2
    raw = bytearray(
        f"# vtk DataFile Version 3.0\nnormal support test\nBINARY\n"
        f"DATASET POLYDATA\nPOINTS {n} float\n".encode()
    )
    raw.extend(np.asarray([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=">f4").tobytes())
    raw.extend(f"\nVERTICES {n} {2 * n}\n".encode())
    raw.extend(np.asarray([1, 0, 1, 1], dtype=">i4").tobytes())
    raw.extend(f"\nPOINT_DATA {n}\nFIELD FieldData 4\n".encode())
    raw.extend(f"Mk 1 {n} unsigned_short\n".encode())
    raw.extend(np.asarray([10, 11], dtype=">u2").tobytes())
    raw.extend(f"\nType 1 {n} unsigned_char\n".encode())
    raw.extend(np.asarray([0, 1], dtype=">u1").tobytes())
    raw.extend(f"\nNormal 3 {n} float\n".encode())
    raw.extend(np.asarray([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=">f4").tobytes())
    raw.extend(f"\nNormalSize 1 {n} float\n".encode())
    raw.extend(np.asarray([0.01, 0.02], dtype=">f4").tobytes())
    path = tmp_path / "Bound.vtk"
    path.write_bytes(raw)

    parsed = MODULE.read_binary_vtk(path)

    assert set(("Mk", "Type", "Normal", "NormalSize")) <= set(parsed["point_data"])
    assert np.array_equal(parsed["point_data"]["Mk"], np.asarray([10, 11], dtype=np.uint16))
    assert np.array_equal(parsed["point_data"]["Type"], np.asarray([0, 1], dtype=np.uint8))
    np.testing.assert_allclose(parsed["point_data"]["Normal"], [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    np.testing.assert_allclose(parsed["point_data"]["NormalSize"], [0.01, 0.02])


def test_vtk_point_shape_summary_records_actual_planes(tmp_path: Path) -> None:
    path = tmp_path / "hdp.vtk"
    raw = bytearray(
        b"# vtk DataFile Version 3.0\nshape test\nBINARY\nDATASET POLYDATA\nPOINTS 2 float\n"
    )
    raw.extend(np.asarray([[0.005, 0.0, 0.0], [3.225, 1.0, 0.705]], dtype=">f4").tobytes())
    path.write_bytes(raw)
    points = MODULE._read_vtk_points(path)
    summary = MODULE._shape_summary(points)
    assert summary["point_count"] == 2
    assert summary["finite"] is True
    np.testing.assert_allclose(summary["unique_axis_values_m"]["x"], [0.005, 3.225], rtol=0, atol=2e-7)
