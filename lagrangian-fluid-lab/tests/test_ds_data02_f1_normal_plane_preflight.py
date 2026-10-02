from pathlib import Path
import importlib.util

import numpy as np

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ds_data02_f1_normal_plane_preflight.py"
SPEC = importlib.util.spec_from_file_location("f1_normal_plane_preflight", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _vtk_points(path: Path, points: np.ndarray) -> None:
    raw = bytearray(
        f"# vtk DataFile Version 3.0\nphase test\nBINARY\nDATASET POLYDATA\nPOINTS {len(points)} float\n".encode()
    )
    raw.extend(np.asarray(points, dtype=">f4").tobytes())
    path.write_bytes(raw)


def test_binary_point_reader_and_face_plane(tmp_path: Path) -> None:
    path = tmp_path / "hdp.vtk"
    _vtk_points(path, np.asarray([
        [0.005, 0.0, 0.0], [3.225, 1.0, 1.0],
        [1.245, 0.335, 0.0], [2.055, 0.405, 0.705],
    ]))
    points = MODULE.read_binary_vtk_points(path)
    assert points.shape == (4, 3)
    result = MODULE._plane_for_face(points, "outer_x_low")
    assert abs(result["actual_plane_m"] - 0.005) < 1e-6
    result = MODULE._plane_for_face(points, "separator_y_high")
    assert abs(result["actual_plane_m"] - 0.405) < 1e-6


def test_preflight_requires_confirmed_phase_coincidence(tmp_path: Path) -> None:
    definition = tmp_path / "Def.xml"
    definition.write_text(
        "<case><casedef><geometry><commands><list name='GeometryForNormals'>"
        "<drawbox><point x='0' y='-0.005' z='-0.005'/><endpoint x='3.23' y='1.005' z='1'/><layers vdp='-0.5'/></drawbox>"
        "<drawbox><point x='1.25' y='0.34' z='0'/><endpoint x='2.05' y='0.4' z='0.7'/><layers vdp='0.5'/></drawbox>"
        "</list></commands></geometry><normals><norgeometry><distanceh v='3.0'/><svshapes v='true'/></norgeometry></normals></casedef></case>"
    )
    hdp = tmp_path / "hdp.vtk"
    _vtk_points(hdp, np.asarray([
        [0.005, 0.0, 0.0], [3.225, 1.0, 1.0],
        [1.245, 0.335, 0.0], [2.055, 0.405, 0.705],
    ]))
    prior = tmp_path / "prior.json"
    prior.write_text('{"native_result":{"finite_face_attribution":['
        '{"name":"outer_x_low","population":"outer_wall","residual_coordinate_layers_m":[{"coordinate_m":0.005}]},'
        '{"name":"separator_y_high","population":"separator","residual_coordinate_layers_m":[{"coordinate_m":0.405}]}'
        ']}}')
    output = tmp_path / "report.json"
    report = MODULE.preflight(definition_path=definition, hdp_path=hdp, prior_result_path=prior, output=output)
    assert report["decision"]["outer_x_low_and_separator_y_high_confirmed"] is True
    assert report["decision"]["candidate_change_authorized_by_evidence"] is True
