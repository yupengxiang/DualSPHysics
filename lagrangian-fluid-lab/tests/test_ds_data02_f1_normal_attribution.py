from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

from scripts.ds_data02_f1_normal_attribution import (
    _face_mask,
    read_initial_normals_vtk,
)


def _vtk_bytes(points: np.ndarray, normals: np.ndarray, normal_size: np.ndarray, mk: np.ndarray) -> bytes:
    n = len(points)
    payload = bytearray()
    payload.extend(f"# vtk DataFile Version 3.0\nnormal test\nBINARY\nDATASET POLYDATA\nPOINTS {n} float\n".encode())
    payload.extend(np.asarray(points, dtype=">f4").tobytes())
    payload.extend(f"\nPOINT_DATA {n}\nFIELD FieldData 3\nMk 1 {n} short\n".encode())
    payload.extend(np.asarray(mk, dtype=">i2").tobytes())
    payload.extend(f"\nNormal 3 {n} float\n".encode())
    payload.extend(np.asarray(normals, dtype=">f4").tobytes())
    payload.extend(f"\nNormalSize 1 {n} float\n".encode())
    payload.extend(np.asarray(normal_size, dtype=">f4").tobytes())
    payload.extend(b"\n")
    return bytes(payload)


def test_binary_vtk_parser_preserves_finite_arrays_and_typed_mk(tmp_path: Path) -> None:
    points = np.asarray([[0.005, 0.005, 0.005], [1.25, 0.405, 0.005]], dtype=float)
    normals = np.asarray([[0.0, 0.0, 0.0], [0.0, 0.005, 0.0]], dtype=float)
    sizes = np.asarray([0.0, 0.005], dtype=float)
    mk = np.asarray([10, 11], dtype=np.int16)
    path = tmp_path / "CfgInit_Normals.vtk"
    path.write_bytes(_vtk_bytes(points, normals, sizes, mk))

    parsed = read_initial_normals_vtk(path)

    assert parsed["points"].shape == (2, 3)
    assert np.array_equal(parsed["mk"], mk)
    assert np.allclose(parsed["normals"], normals)
    assert np.allclose(parsed["normal_size"], sizes)


def test_face_mask_uses_declared_plane_and_typed_population() -> None:
    from scripts.ds_data02_f1_normal_attribution import FACE_SPECS

    points = np.asarray([
        [0.005, 0.005, 0.005],  # outer x-low candidate
        [0.005, 0.005, 0.005],  # wrong typed population must be rejected
        [1.245, 0.405, 0.005],  # separator y-high edge candidate
    ])
    mk = np.asarray([10, 11, 11], dtype=np.int16)
    outer = next(spec for spec in FACE_SPECS if spec["name"] == "outer_x_low")
    separator = next(spec for spec in FACE_SPECS if spec["name"] == "separator_y_high")

    assert _face_mask(points, mk, outer, tolerance_m=0.0050001).tolist() == [True, False, False]
    assert _face_mask(points, mk, separator, tolerance_m=0.0050001).tolist() == [False, False, True]
