import numpy as np
from dataclasses import replace
import pytest
from test_core_contract import example_state,example_known
from scripts.core_contract import PrescribedGeometry, State
from scripts.core_physics import (MOVING_WALL_DIAGNOSTIC_SCHEMA, conserved_observables,
                                   frame_physics, moving_wall_crossings,
                                   static_wall_crossings)


def test_open_top_is_not_wall_and_double_triangles_do_not_double_mass():
    state=example_state(); geometry=example_known().geometry
    top=replace(state,position=state.position+np.array([0,0,2]))
    assert static_wall_crossings(state,top,geometry)['particle_count']==0
    bottom=replace(state,position=state.position-np.array([0,0,2]))
    assert static_wall_crossings(state,bottom,geometry)['particle_count']==2
    assert static_wall_crossings(state,bottom,geometry)['mass_kg']==2


def test_mass_energy_and_lifecycle_failures_remain_visible():
    state=example_state();velocity=replace(state,velocity=np.ones((2,3)))
    assert conserved_observables(velocity)['kinetic_energy_j']==3
    lost=replace(velocity,valid=np.array([True,False]))
    result=frame_physics(state,lost,velocity,example_known().geometry)
    assert result['mass_error_kg']==-1
    assert result['validity_mismatch_count']==1
    assert result['wall_chord']['unavailable_particle_count']==1


def _rotating_test_geometry(*, sample_times=(0., 1.), sample_angles=(0., 90.)):
    # A single finite panel rotates about +z.  At 45 degrees it passes through
    # the stationary point below; neither endpoint contains the point.  The
    # panel is a declared public pose schedule, not a reference trajectory.
    return PrescribedGeometry(
        triangles=np.array([[[1., 0., 0.], [1., 1., 0.], [2., 0., 0.]]]),
        component_id=np.array([0]), body_id=np.array([0]),
        wall_velocity=np.zeros((1, 3)), coordinate_frame="test",
        sample_times=np.array(sample_times), sample_angles_degrees=np.array(sample_angles),
        axis_point=np.zeros(3), axis_direction=np.array([0., 0., 1.]),
        moving_body_id=0)


def test_prescribed_rotating_wall_catches_stationary_point_and_reports_approximation():
    geometry = _rotating_test_geometry()
    previous = State(0., np.array([[.7, .7, 0.]]), np.zeros((1, 3)),
                     np.array([1]), np.array([0]), np.array([2.]), np.array([True]))
    following = replace(previous, time_s=1.)
    result = moving_wall_crossings(previous, following, geometry)
    assert result["schema"] == MOVING_WALL_DIAGNOSTIC_SCHEMA
    assert result["status"] == "checked_prescribed_moving_saved_chords"
    assert result["particle_count"] == 1
    assert result["mass_kg"] == 2.
    assert result["saved_step_approximation"]["exact_continuous_path"] is False
    assert result["saved_step_approximation"]["future_fluid_state_used"] is False
    error = result["rotation_sweep_error"]
    assert error["sweep_sample_count"] == 17
    assert error["max_rotation_angle_rad"] == pytest.approx(np.pi / 2., abs=1e-8)
    assert error["max_rigid_fit_residual_m"] < 1e-12
    assert error["deforming_triangle_count"] == 0
    assert error["max_rotational_sagitta_estimate_m"] is not None
    assert error["sagitta_status"] == "declared_axis_estimate"


def test_flat_public_schedule_interval_ignores_knot_velocity_at_endpoints():
    # The pose is flat on [1, 2], while np.gradient at the two schedule knots
    # still exposes a nonzero endpoint angular speed from neighbouring samples.
    # The public pose path, rather than that instantaneous derivative, decides
    # that this saved interval is static.
    geometry = _rotating_test_geometry(
        sample_times=(0., 1., 2.), sample_angles=(0., 90., 90.))
    first_geometry = geometry.at(1.)
    second_geometry = geometry.at(2.)
    assert np.any(first_geometry.wall_velocity != 0.)
    np.testing.assert_allclose(first_geometry.triangles, second_geometry.triangles)
    previous = State(1., np.array([[-.5, 1.5, 1.]]), np.zeros((1, 3)),
                     np.array([1]), np.array([0]), np.array([2.]), np.array([True]))
    following = replace(previous, time_s=2., position=np.array([[-.5, 1.5, -1.]]))
    result = moving_wall_crossings(previous, following, geometry)
    assert result["status"] == "checked_static_saved_chords"
    assert result["particle_count"] == 1
    assert result["mass_kg"] == 2.
    assert result["rotation_sweep_error"]["declared_rotation_path_rad"] == pytest.approx(0.)
    assert result["rotation_sweep_error"]["sagitta_status"] == "static_degenerate"
    assert result["moving_surface"]["declared_wall_velocity_nonzero"] is True
    assert result["moving_surface"]["public_schedule_authoritative_static"] is True


def test_open_face_and_static_degenerate_motion_keep_legacy_chord_result():
    previous = example_state()
    following = replace(previous, position=previous.position + np.array([0., 0., 2.]))
    geometry = example_known().geometry
    legacy = static_wall_crossings(previous, following, geometry)
    result = moving_wall_crossings(previous, following, geometry)
    assert result["status"] == "checked_static_saved_chords"
    assert result["particle_count"] == legacy["particle_count"] == 0
    assert result["mass_kg"] == legacy["mass_kg"] == 0.
    assert result["rotation_sweep_error"]["sagitta_status"] == "static_degenerate"

    # A finite moving snapshot without its following public endpoint must not
    # be extrapolated from its instantaneous wall velocity.
    moving_snapshot = _rotating_test_geometry().at(.5)
    assert not hasattr(moving_snapshot, "sample_times")
    unsupported = moving_wall_crossings(previous, following, moving_snapshot)
    assert unsupported["status"] == "unsupported_moving_surface"
    assert unsupported["reason"] == "moving finite geometry requires a following public endpoint snapshot"


def test_frame_physics_materializes_prescribed_endpoints_without_future_state():
    geometry = _rotating_test_geometry()
    previous = State(0., np.array([[.7, .7, 0.]]), np.zeros((1, 3)),
                     np.array([1]), np.array([0]), np.array([1.]), np.array([True]))
    predicted = replace(previous, time_s=1.)
    reference = replace(predicted)
    result = frame_physics(previous, predicted, reference, geometry)
    assert result["wall_chord"]["status"] == "checked_prescribed_moving_saved_chords"
    assert result["wall_chord"]["particle_count"] == 1


def test_public_motion_reversal_is_not_collapsed_to_static_endpoint_pose():
    geometry = _rotating_test_geometry(sample_times=(0., .5, 1.), sample_angles=(0., 90., 0.))
    previous = State(0., np.array([[.7, .7, 0.]]), np.zeros((1, 3)),
                     np.array([1]), np.array([0]), np.array([1.]), np.array([True]))
    following = replace(previous, time_s=1.)
    result = moving_wall_crossings(previous, following, geometry)
    assert result["status"] == "checked_prescribed_moving_saved_chords"
    assert result["particle_count"] == 1
    error = result["rotation_sweep_error"]
    assert error["declared_rotation_delta_rad"] == pytest.approx(0.)
    assert error["declared_rotation_path_rad"] == pytest.approx(np.pi)
    assert error["sweep_segment_count"] == 2
    assert result["moving_surface"]["schedule_segmented"] is True


def test_public_motion_over_180_degrees_is_split_before_quaternion_sweep():
    geometry = _rotating_test_geometry(sample_angles=(0., 270.))
    previous = State(0., np.array([[.7, .7, 0.]]), np.zeros((1, 3)),
                     np.array([1]), np.array([0]), np.array([1.]), np.array([True]))
    following = replace(previous, time_s=1.)
    result = moving_wall_crossings(previous, following, geometry)
    error = result["rotation_sweep_error"]
    assert result["status"] == "checked_prescribed_moving_saved_chords"
    assert result["particle_count"] == 1
    assert error["declared_rotation_delta_rad"] == pytest.approx(3. * np.pi / 2.)
    assert error["declared_rotation_path_rad"] == pytest.approx(3. * np.pi / 2.)
    assert error["sweep_segment_count"] == 3
    assert error["max_declared_segment_rad"] <= np.pi / 2. + 1e-12
    assert error["max_rotation_angle_rad"] <= np.pi / 2. + 1e-8
