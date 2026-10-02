import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_f1_eccentric_finite_face_audit.py"
SPEC = importlib.util.spec_from_file_location("f1_eccentric_finite_face_audit", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_faces_include_finite_interiors_and_obstacle_five_faces():
    faces = MODULE.face_definitions()
    assert len(faces) == 10
    assert {name for name in faces if name.startswith("outer_")} == {
        "outer_x_low", "outer_x_high", "outer_y_low", "outer_y_high", "outer_z_low"
    }
    assert {name for name in faces if name.startswith("obstacle_")} == {
        "obstacle_x_low", "obstacle_x_high", "obstacle_y_low", "obstacle_y_high", "obstacle_z_high"
    }
    assert faces["obstacle_z_high"]["low"] == [0.9, 0.24]
    assert faces["obstacle_z_high"]["high"] == [1.02, 0.36]


def test_face_sampling_contract_is_not_aabb_only():
    faces = MODULE.face_definitions()
    assert faces["outer_y_high"]["low"] == [0.0, 0.0]
    assert faces["outer_y_high"]["high"] == [1.6, 0.4]
    assert faces["obstacle_x_low"]["low"] == [0.24, 0.0]
    assert faces["obstacle_x_low"]["high"] == [0.36, 0.45]
