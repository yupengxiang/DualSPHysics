from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np

from scripts.boundary_sidecars import (
    audit_sidecar,
    boundary_triangles,
    read_binary_vtk_polydata,
    sidecar_provider,
    write_sidecar,
)


LAB = Path(__file__).resolve().parents[1]


def test_binary_mkcells_parser_excludes_fluid_cells_and_triangulates():
    path = LAB / "cases" / "F1" / "F1_twin_obstacle" / "generated" / "F1_twin_obstacle_MkCells.vtk"
    parsed = read_binary_vtk_polydata(path)
    triangles = boundary_triangles(parsed)
    assert len(parsed["cells"]) == 68
    assert triangles["triangles"].shape[1:] == (3, 3)
    assert len(triangles["triangles"]) == 124  # 62 boundary quads -> 124 triangles
    assert not np.any(triangles["type"] == 3)
    assert set(np.unique(triangles["type"])) == {0}


def test_w06_parser_keeps_fixed_and_moving_boundary_types():
    path = (LAB / "campaigns" / "v0.1-candidate" / "artifacts" / "w06"
            / "W06_standard_slow_center" / "generated" / "W06_standard_slow_center_MkCells.vtk")
    triangles = boundary_triangles(read_binary_vtk_polydata(path))
    assert set(np.unique(triangles["type"])) == {0, 1}
    assert int(np.sum(triangles["type"] == 0)) == 40
    assert int(np.sum(triangles["type"] == 1)) == 28


def test_sidecar_round_trip_validates_frames_and_geometry(tmp_path):
    source = LAB / "cases" / "F3" / "F3_transverse_slosh" / "generated" / "F3_transverse_slosh_MkCells.vtk"
    h5_path = tmp_path / "solver.h5"
    with h5py.File(h5_path, "w") as h5:
        h5.create_dataset("time", data=np.asarray([0.0, 0.5, 1.0]))
    sidecar = tmp_path / "boundary.h5"
    summary = write_sidecar(sidecar, "F3_transverse_slosh", h5_path,
                            read_binary_vtk_polydata(source))
    assert summary["frame_count"] == 3
    assert summary["all_frames_finite"]
    assert summary["all_frames_nondegenerate"]
    checked = audit_sidecar(sidecar)
    assert checked["coordinate_frame"] == "world"
    assert checked["triangle_count"] > 0
    provider = sidecar_provider(sidecar)
    with h5py.File(h5_path, "r") as h5:
        midpoint = provider(h5, 0, 1, 0.5)
    with h5py.File(sidecar, "r") as h5:
        np.testing.assert_allclose(midpoint, h5["triangles_world"][0])
