import struct
import sys
from pathlib import Path

import h5py
import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import ds_data02_f1_eccentric_reference_audit as audit  # noqa: E402


def _write_vtk(path: Path, points: np.ndarray) -> None:
    with path.open("wb") as stream:
        stream.write(b"# vtk DataFile Version 3.0\npoints\nBINARY\nDATASET POLYDATA\n")
        stream.write(f"POINTS {len(points)} float\n".encode())
        stream.write(struct.pack(f">{points.size}f", *points.astype(np.float32).ravel()))


def test_binary_vtk_reader_and_finite_face_metric(tmp_path):
    points = np.asarray(
        [[0.0, y, z] for y in (0.0, 0.5, 0.67) for z in (0.0, 0.2, 0.4)],
        dtype=np.float32,
    )
    path = tmp_path / "Bound.vtk"
    _write_vtk(path, points)
    decoded = audit._read_vtk_points(path)
    assert decoded.shape == (9, 3)
    metric = audit._face_metric(
        decoded, "outer_x_low", 0, 0.0, ((0.0, 0.67), (0.0, 0.4)), 0.01
    )
    assert metric["pass"] is True
    assert metric["native_interior_count"] > 0


def test_geometry_check_excludes_dp_from_continuous_signature(tmp_path):
    def make(path: Path, dp: str) -> None:
        path.write_text(
            f'''<case><casedef><constantsdef><gravity x="0" y="0" z="-9.81"/></constantsdef></casedef>
            <geometry><definition dp="{dp}"><pointmin x="-0.05" y="-0.05" z="-0.05"/><pointmax x="2" y="1" z="1"/></definition>
            <commands><mainlist><setmkfluid mk="0"/><drawbox><boxfill>solid</boxfill><point x="0" y="0" z="0"/><size x="0.4" y="0.67" z="0.3"/></drawbox>
            <setmkbound mk="0"/><drawbox><boxfill>bottom | left | right | front | back</boxfill><point x="0" y="0" z="0"/><size x="1.6" y="0.67" z="0.4"/></drawbox>
            <setmkvoid/><drawbox><boxfill>solid</boxfill><point x="0.9" y="0.24" z="0"/><size x="0.12" y="0.12" z="0.45"/></drawbox>
            <setmkbound mk="1"/><drawbox><boxfill>top | left | right | front | back</boxfill><point x="0.9" y="0.24" z="0"/><size x="0.12" y="0.12" z="0.45"/></drawbox></mainlist></commands></geometry>
            <execution><motion/><parameters><parameter key="TimeMax" value="1.6"/><parameter key="TimeOut" value="0.01"/><parameter key="DtFixed" value="0"/></parameters></execution>
            <data2d value="false"/></case>''',
            encoding="utf-8",
        )

    coarse = tmp_path / "coarse.xml"
    fine = tmp_path / "fine.xml"
    make(coarse, "0.02")
    make(fine, "0.01")
    first = audit._geometry_checks(coarse)
    second = audit._geometry_checks(fine)
    assert first["expected_continuous_draws_match"]
    assert first["geometry_signature_sha256"] == second["geometry_signature_sha256"]
    assert first["control_signature_sha256"] == second["control_signature_sha256"]
    assert first["flags"]["dp_m"] != second["flags"]["dp_m"]


def test_hdf5_first_frame_preserves_native_mass_and_typed_identity(tmp_path):
    path = tmp_path / "trajectory.h5"
    n = 4
    with h5py.File(path, "w") as handle:
        handle.create_dataset("density", data=np.ones((2, n), dtype=np.float32) * 1000)
        handle.create_dataset("mass", data=np.asarray([[1.0, 1.0, 0.5, 0.5], [1.0, 1.0, 0.5, 0.5]], dtype=np.float32))
        handle.create_dataset("mk", data=np.zeros((2, n), dtype=np.int16))
        handle.create_dataset("particle_id", data=np.arange(n, dtype=np.int64))
        handle.create_dataset("particle_zone", data=np.zeros(n, dtype=np.int16))
        handle.create_dataset("position", data=np.zeros((2, n, 3), dtype=np.float32))
        handle.create_dataset("pressure", data=np.zeros((2, n), dtype=np.float32))
        handle.create_dataset("time", data=np.asarray([0.0, 0.1]))
        handle.create_dataset("type", data=np.asarray([[3, 3, 2, 1], [3, 3, 2, 1]], dtype=np.int8))
        handle.create_dataset("valid", data=np.ones((2, n), dtype=bool))
        handle.create_dataset("velocity", data=np.zeros((2, n, 3), dtype=np.float32))
        handle.attrs["solver_dimension"] = 3
        handle.attrs["coordinate_frame"] = "DualSPHysics case Cartesian coordinates (x,y,z)"
    result = audit._hdf5_first_frame(
        path,
        {"source_hdf5_sha256": "report-sha", "source_hdf5_bytes": path.stat().st_size},
    )
    assert result["initial_fluid_type3_count"] == 2
    assert result["initial_fluid_mass_kg"] == 2.0
    assert result["initial_type2_count"] == 1
    assert result["typed_identity_unique"]
    assert result["active_mass_positive"]
