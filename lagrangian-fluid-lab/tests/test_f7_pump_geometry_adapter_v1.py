from __future__ import annotations

import numpy as np
import pytest

from scripts.f7_pump_geometry_adapter_v1 import (
    DEFAULT_DEFINITION,
    DEFAULT_FIXED,
    DEFAULT_MOVING,
    DUALSPHYSICS_MVROTFILE_ROTATION_VERSION,
    load_pump_geometry,
    parse_pump_definition,
    pump_angle_degrees,
    pump_angular_velocity_degrees_per_second,
    read_polydata,
)


@pytest.fixture(scope="module")
def pump():
    return load_pump_geometry(sample_interval_s=0.25)


def test_official_polydata_parser_handles_binary_and_ascii_sources():
    fixed = read_polydata(DEFAULT_FIXED)
    moving = read_polydata(DEFAULT_MOVING)
    assert fixed["encoding"] == "BINARY"
    assert moving["encoding"] == "ASCII"
    assert fixed["point_count"] == 118075
    assert fixed["polygon_count"] == 45111
    assert fixed["raw_triangle_count"] == 46403
    assert fixed["degenerate_triangle_count"] == 462
    assert fixed["triangle_count"] == 45941
    assert moving["point_count"] == 6383
    assert moving["polygon_count"] == 12768
    assert moving["raw_triangle_count"] == 12768
    assert moving["degenerate_triangle_count"] == 2
    assert moving["triangle_count"] == 12766
    assert np.isfinite(fixed["triangles"]).all()
    assert np.isfinite(moving["triangles"]).all()


def test_xml_motion_contract_is_fixed_axis_two_stage_and_hash_bound():
    contract = parse_pump_definition(DEFAULT_DEFINITION)
    assert contract["fixed_mk"] == 0
    assert contract["moving_mk"] == 2
    assert contract["fluid_mk"] == 1
    assert contract["moving_object_ref"] == 2
    assert contract["begin_mov_id"] == 1
    assert contract["finish_s"] == pytest.approx(1000.0)
    assert contract["angle_units"] == "degrees"
    assert contract["draw_files"] == ["pump_fixed.vtk", "pump_moving.vtk"]
    assert contract["axis_point_m"] == pytest.approx([-0.0176, -0.29, -0.7275])
    assert contract["axis_direction_m"] == pytest.approx([0.0, -0.2, 0.0])
    assert contract["segments"][0]["duration_s"] == pytest.approx(2.0)
    assert contract["segments"][0]["acceleration_deg_s2"] == pytest.approx(500.0)
    assert contract["segments"][0]["initial_velocity_deg_s"] == pytest.approx(90.0)
    assert contract["segments"][0]["next_id"] == 2
    assert contract["segments"][1]["acceleration_deg_s2"] == pytest.approx(0.0)
    assert contract["segments"][1]["next_id"] is None
    assert contract["segments"][1]["initial_velocity_deg_s"] is None
    assert len(contract["motion_sha256"]) == 64


def test_official_piecewise_motion_has_static_start_acceleration_and_constant_tail():
    contract = parse_pump_definition()
    assert pump_angle_degrees(0.0, contract) == pytest.approx(0.0)
    assert pump_angle_degrees(0.5, contract) == pytest.approx(0.0)
    assert pump_angle_degrees(2.5, contract) == pytest.approx(1180.0)
    assert pump_angle_degrees(3.5, contract) == pytest.approx(2270.0)
    assert pump_angle_degrees(1001.0, contract) == pytest.approx(pump_angle_degrees(1000.0, contract))
    assert pump_angular_velocity_degrees_per_second(0.5, contract) == pytest.approx(0.0)
    assert pump_angular_velocity_degrees_per_second(1.5, contract) == pytest.approx(590.0)
    assert pump_angular_velocity_degrees_per_second(2.5, contract) == pytest.approx(1090.0)
    assert pump_angular_velocity_degrees_per_second(3.5, contract) == pytest.approx(1090.0)
    assert pump_angular_velocity_degrees_per_second(1000.0, contract) == pytest.approx(0.0)
    with pytest.raises(ValueError):
        pump_angle_degrees(-1.0, contract)


def test_adapter_returns_core_prescribed_geometry_and_metadata(pump):
    geometry, metadata = pump
    assert geometry.motion_version == DUALSPHYSICS_MVROTFILE_ROTATION_VERSION
    assert geometry.moving_body_id == 2
    assert geometry.triangles.shape == (58707, 3, 3)
    assert np.count_nonzero(geometry.body_id == 0) == 45941
    assert np.count_nonzero(geometry.body_id == 2) == 12766
    assert np.all(geometry.wall_velocity == 0.0)
    assert geometry.sample_times[0] == pytest.approx(0.0)
    assert geometry.sample_times[-1] == pytest.approx(6.0)
    assert geometry.sample_angles_degrees[-1] == pytest.approx(4995.0)
    assert metadata["combined_triangle_count"] == 58707
    assert metadata["fixed"]["raw_triangle_count"] == 46403
    assert metadata["fixed"]["degenerate_triangle_count"] == 462
    assert metadata["moving"]["raw_triangle_count"] == 12768
    assert metadata["moving"]["degenerate_triangle_count"] == 2
    assert metadata["motion_sampling"]["linear_angle_interpolation_error_bound_deg"] == pytest.approx(0.25 ** 2 * 500.0 / 8.0)
    assert metadata["motion_sampling"]["core_prescribed_geometry_uses_sampled_pose_and_gradient_velocity"] is True
    assert metadata["runtime_execution"] == {
        "read_only": True,
        "definition_written": False,
        "gencase_invoked": False,
        "native_invoked": False,
        "solver_invoked": False,
        "gpu_started": False,
        "queue_mutation": 0,
    }


def test_geometry_pose_and_wall_velocity_are_finite_and_rigid(pump):
    geometry, _ = pump
    initial = geometry.at(0.0)
    later = geometry.at(3.5)
    assert np.isfinite(initial.triangles).all()
    assert np.isfinite(later.triangles).all()
    assert np.any(np.linalg.norm(later.triangles - initial.triangles, axis=2) > 1e-8)
    assert np.any(np.linalg.norm(later.wall_velocity[geometry.moving_mask], axis=1) > 0.0)
    assert np.allclose(initial.triangles[~geometry.moving_mask], later.triangles[~geometry.moving_mask])
    pose = geometry.world_from_body_at(3.5)
    assert pose.shape == (4, 4)
    assert np.allclose(pose[3], [0.0, 0.0, 0.0, 1.0])
    assert np.isfinite(pose).all()


def test_wrong_source_names_fail_closed(tmp_path):
    with pytest.raises(ValueError, match="paths do not match"):
        load_pump_geometry(moving_geometry=tmp_path / "wrong.vtk")


def test_same_named_foreign_sources_fail_closed(tmp_path):
    with pytest.raises(ValueError, match="source directory"):
        load_pump_geometry(
            fixed_geometry=tmp_path / "pump_fixed.vtk",
            moving_geometry=tmp_path / "pump_moving.vtk",
        )
