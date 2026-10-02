import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_f1_eccentric_finite_face_audit_v2.py"
SPEC = importlib.util.spec_from_file_location("f1_eccentric_finite_face_audit_v2", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_floor_is_split_around_obstacle_footprint():
    floor = MODULE.face_definitions()["outer_z_low"]
    assert len(floor) == 4
    assert {tuple(row["low"]) + tuple(row["high"]) for row in floor} == {
        (0.0, 0.0, 0.9, 0.67),
        (1.02, 0.0, 1.6, 0.67),
        (0.9, 0.0, 1.02, 0.24),
        (0.9, 0.36, 1.02, 0.67),
    }


def test_v2_keeps_five_faces_each():
    faces = MODULE.face_definitions()
    assert len([name for name in faces if name.startswith("outer_")]) == 5
    assert len([name for name in faces if name.startswith("obstacle_")]) == 5
