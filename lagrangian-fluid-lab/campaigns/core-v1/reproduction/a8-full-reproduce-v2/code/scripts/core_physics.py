"""Full-axis physical diagnostics for public state and finite geometry.

The original ``static_wall_crossings`` function is deliberately kept as the
legacy static diagnostic.  ``moving_wall_crossings`` is an explicitly
versioned extension for a declared, finite prescribed motion.  It consumes
only the two public state snapshots and the public wall poses at their times;
it never asks a CFD trajectory for an intermediate wall position.
"""
from __future__ import annotations
import numpy as np


MOVING_WALL_DIAGNOSTIC_SCHEMA = "core.physics.moving_wall_saved_step.v1"
# Public alias used by callers that name protocol identifiers as versions.
MOVING_WALL_DIAGNOSTIC_VERSION = MOVING_WALL_DIAGNOSTIC_SCHEMA
MOVING_WALL_SWEEP_SAMPLES = 17
# The shared quaternion sweep follows the shortest endpoint arc.  Splitting a
# public motion schedule at <=90 degrees makes that local path unambiguous and
# also handles schedules that reverse direction or rotate beyond 180 degrees.
MOVING_WALL_MAX_ROTATION_SEGMENT_RAD = np.pi / 2.0


def _swept_wall_operator():
    """Load the shared finite-wall space-time operator lazily.

    The lazy import keeps static physical diagnostics usable in the small
    contract bundle.  A production bundle that enables prescribed moving
    surfaces must include ``passive_tracers.py`` alongside this module; using
    the shared implementation avoids maintaining a second sweep algorithm.
    """
    try:
        from scripts.passive_tracers import (  # pylint: disable=import-outside-toplevel
            _fit_rigid_transform_for_sweep,
            _rotation_to_quaternion,
            spacetime_swept_wall_blocked,
        )
    except ModuleNotFoundError as error:  # pragma: no cover - exercised by incomplete bundles
        if error.name not in {"scripts.passive_tracers", "passive_tracers"}:
            raise
        try:
            from passive_tracers import (  # type: ignore  # pylint: disable=import-outside-toplevel
                _fit_rigid_transform_for_sweep,
                _rotation_to_quaternion,
                spacetime_swept_wall_blocked,
            )
        except ModuleNotFoundError as second:
            raise ModuleNotFoundError(
                "moving-wall diagnostics require passive_tracers.py in the runtime bundle"
            ) from second
    return spacetime_swept_wall_blocked, _fit_rigid_transform_for_sweep, _rotation_to_quaternion


def conserved_observables(state):
    active = state.valid
    mass = state.mass[active]
    total = float(mass.sum())
    return {"active_mass_kg": total, "active_particles": int(active.sum()),
            "registered_particles": state.count,
            "kinetic_energy_j": float(.5*np.sum(mass[:,None]*state.velocity[active]**2)),
            "center_of_mass_m": (np.sum(mass[:,None]*state.position[active],axis=0)/total).tolist(),
            "momentum_kg_mps": np.sum(mass[:,None]*state.velocity[active],axis=0).tolist()}


def static_wall_crossings(previous, following, geometry, *, tolerance=1e-9,
                          public_schedule_static=False):
    """Intersect saved-state chords with finite triangles, never infinite planes.

    This diagnoses saved chord intersections, not unresolved substep paths.
    Moving geometry needs a separate swept-surface implementation.  The
    ``public_schedule_static`` escape hatch is reserved for
    ``moving_wall_crossings`` after a declared motion schedule has established
    that the complete saved-step interval has zero pose path.  A caller cannot
    use it to infer static motion from an instantaneous snapshot: the default
    remains fail-closed for every nonzero wall velocity.
    """
    if not np.array_equal(previous.particle_id,following.particle_id) or not np.array_equal(previous.particle_zone,following.particle_zone):
        raise ValueError('particle identity changed during physical evaluation')
    if np.any(geometry.wall_velocity) and not public_schedule_static:
        return {"status":"unsupported_moving_surface", "particle_count":None, "mass_kg":None}
    if tolerance <= 0:
        raise ValueError('positive intersection tolerance required')
    valid = previous.valid & following.valid
    origin = previous.position[valid]
    direction = following.position[valid]-origin
    hit = np.zeros(len(origin),dtype=bool)
    for triangle in geometry.triangles:
        a,b,c=triangle
        edge1,edge2=b-a,c-a
        p=np.cross(direction,edge2)
        determinant=p@edge1
        nonparallel=np.abs(determinant)>tolerance
        inverse=np.zeros_like(determinant)
        inverse[nonparallel]=1/determinant[nonparallel]
        relative=origin-a
        u=np.einsum('ij,ij->i',relative,p)*inverse
        q=np.cross(relative,edge1)
        v=np.einsum('ij,ij->i',direction,q)*inverse
        time=(q@edge2)*inverse
        hit |= nonparallel & (u>=-tolerance) & (v>=-tolerance) & (u+v<=1+tolerance) & (time>tolerance) & (time<1-tolerance)
    return {"status":"checked_static_saved_chords", "particle_count":int(hit.sum()),
            "mass_kg":float(previous.mass[valid][hit].sum()),
            "checked_particle_count":int(valid.sum()),
            "unavailable_particle_count":int((~valid).sum()),
            "semantics":"finite surface intersections of saved chords; no exact path claim"}


def _prescribed_angle_delta(geometry, first_time, second_time):
    """Return a declared pose delta when ``geometry`` exposes one.

    This intentionally reads only the public motion schedule.  In particular,
    it never derives a pose from a reference or predicted fluid state.
    """
    times = getattr(geometry, "sample_times", None)
    angles = getattr(geometry, "sample_angles_degrees", None)
    if times is None or angles is None:
        return None
    times = np.asarray(times, dtype=np.float64)
    angles = np.asarray(angles, dtype=np.float64)
    if times.ndim != 1 or angles.shape != times.shape or len(times) < 2:
        return None
    sign = float(getattr(geometry, "rotation_sign", 1.0))
    first = float(np.interp(float(first_time), times, angles))
    second = float(np.interp(float(second_time), times, angles))
    return sign * (second - first) * np.pi / 180.0


def _prescribed_sweep_segments(geometry, first_time, second_time):
    """Materialize a public motion schedule into short rigid pose intervals.

    ``PrescribedGeometry.at`` linearly interpolates the declared angle knots.
    We retain every knot inside the saved-state interval, then subdivide each
    angle increment to at most 90 degrees.  This preserves reversals such as
    ``0 -> 90 -> 0`` and avoids asking the quaternion operator to infer a
    long (>180 degree) path from coincident endpoint poses.
    """
    times = getattr(geometry, "sample_times", None)
    angles = getattr(geometry, "sample_angles_degrees", None)
    at = getattr(geometry, "at", None)
    if times is None or angles is None or not callable(at):
        return None
    times = np.asarray(times, dtype=np.float64)
    angles = np.asarray(angles, dtype=np.float64)
    first_time = float(first_time)
    second_time = float(second_time)
    if (times.ndim != 1 or angles.shape != times.shape or len(times) < 2
            or not np.isfinite(times).all() or not np.isfinite(angles).all()
            or not np.isfinite([first_time, second_time]).all()):
        raise ValueError("invalid prescribed motion schedule for swept diagnostic")
    if second_time < first_time:
        raise ValueError("moving-wall diagnostic requires nondecreasing state times")
    sign = float(getattr(geometry, "rotation_sign", 1.0))

    knots = [first_time]
    if second_time > first_time:
        knots.extend(float(value) for value in times
                     if first_time < float(value) < second_time)
    knots.append(second_time)
    # The contract validates strictly increasing sample times.  The explicit
    # unique pass only removes a duplicate endpoint when a caller supplies a
    # time equal to a public knot.
    knots = np.asarray(sorted(set(knots)), dtype=np.float64)
    segments = []
    path_angle = 0.0
    endpoint_angle_first = sign * float(np.interp(first_time, times, angles)) * np.pi / 180.0
    endpoint_angle_second = sign * float(np.interp(second_time, times, angles)) * np.pi / 180.0
    for left, right in zip(knots[:-1], knots[1:]):
        angle_left = sign * float(np.interp(left, times, angles)) * np.pi / 180.0
        angle_right = sign * float(np.interp(right, times, angles)) * np.pi / 180.0
        delta = angle_right - angle_left
        path_angle += abs(delta)
        count = max(1, int(np.ceil(abs(delta) / MOVING_WALL_MAX_ROTATION_SEGMENT_RAD)))
        for index in range(count):
            alpha_left = float(index) / count
            alpha_right = float(index + 1) / count
            segment_left = float(left + (right - left) * alpha_left)
            segment_right = float(left + (right - left) * alpha_right)
            segment_delta = delta / count
            segments.append({
                "time_start_s": segment_left,
                "time_end_s": segment_right,
                "alpha_start": ((segment_left - first_time) / (second_time - first_time)
                                if second_time != first_time else 0.0),
                "alpha_end": ((segment_right - first_time) / (second_time - first_time)
                              if second_time != first_time else 1.0),
                "declared_delta_rad": float(segment_delta),
                "geometry_start": at(segment_left),
                "geometry_end": at(segment_right),
            })
    if not segments:
        # This is reachable only for a malformed zero-length schedule; keep a
        # finite endpoint segment so the caller can report it deterministically.
        segments.append({
            "time_start_s": first_time, "time_end_s": second_time,
            "alpha_start": 0.0, "alpha_end": 1.0,
            "declared_delta_rad": float(endpoint_angle_second - endpoint_angle_first),
            "geometry_start": at(first_time), "geometry_end": at(second_time),
        })
    return {
        "segments": segments,
        "declared_delta_rad": float(endpoint_angle_second - endpoint_angle_first),
        "declared_path_rad": float(path_angle),
        "knot_count": int(len(knots)),
        "max_declared_segment_rad": float(max(
            (abs(item["declared_delta_rad"]) for item in segments), default=0.0)),
    }


def _materialize_geometry_pair(geometry, first_time, second_time, geometry_next):
    """Resolve finite endpoint snapshots from a public geometry contract."""
    # PrescribedGeometry.at() is a pure function of the declared motion
    # schedule.  The duck-typed check also works in a copied runtime bundle,
    # where class identity can differ from the source checkout's class.
    at = getattr(geometry, "at", None)
    is_prescribed = callable(at) and hasattr(geometry, "sample_times")
    if is_prescribed:
        first = at(float(first_time))
        if geometry_next is None or geometry_next is geometry:
            second = at(float(second_time))
        elif callable(getattr(geometry_next, "at", None)) and hasattr(geometry_next, "sample_times"):
            second = geometry_next.at(float(second_time))
        else:
            second = geometry_next
    else:
        first = geometry
        second = geometry if geometry_next is None else geometry_next
    for name, value in (("first", first), ("second", second)):
        if not all(hasattr(value, field) for field in ("triangles", "component_id", "body_id", "wall_velocity")):
            raise TypeError(f"{name} geometry must expose finite triangles and identity arrays")
    return first, second


def _validate_geometry_pair(first, second):
    first_triangles = np.asarray(first.triangles, dtype=np.float64)
    second_triangles = np.asarray(second.triangles, dtype=np.float64)
    if (first_triangles.ndim != 3 or first_triangles.shape[1:] != (3, 3)
            or second_triangles.ndim != 3 or second_triangles.shape[1:] != (3, 3)):
        raise ValueError("finite moving geometry triangles must have shape [M,3,3]")
    if first_triangles.shape != second_triangles.shape:
        raise ValueError("moving geometry changes the finite triangle axis")
    for name in ("component_id", "body_id"):
        first_ids = np.asarray(getattr(first, name))
        second_ids = np.asarray(getattr(second, name))
        if first_ids.shape != (len(first_triangles),) or second_ids.shape != (len(second_triangles),):
            raise ValueError(f"moving geometry {name} axis does not match triangles")
        if not np.array_equal(first_ids, second_ids):
            raise ValueError(f"moving geometry changes finite triangle {name} identities")
    for name, value in (("first", first_triangles), ("second", second_triangles)):
        if value.size and not np.isfinite(value).all():
            raise ValueError(f"{name} moving geometry contains nonfinite triangles")
    return first_triangles, second_triangles


def _rotation_sweep_error(first, second, first_triangles, second_triangles,
                          *, motion_geometry=None, declared_angle_delta=None,
                          declared_path_angle=None, sweep_segments=None,
                          tolerance=1e-9):
    """Summarize the endpoint-pose fit used by the shared sweep operator."""
    _, fit_transform, rotation_to_quaternion = _swept_wall_operator()
    residuals = []
    angles = []
    deforming = 0
    fit_tolerances = []
    if sweep_segments is None:
        sweep_segments = [{
            "first_triangles": first_triangles,
            "second_triangles": second_triangles,
            "declared_delta_rad": declared_angle_delta,
        }]
    else:
        sweep_segments = list(sweep_segments)
    declared_increments = []
    for segment in sweep_segments:
        triangles_first = np.asarray(
            segment["first_triangles"] if "first_triangles" in segment
            else segment["geometry_start"].triangles, dtype=np.float64)
        triangles_second = np.asarray(
            segment["second_triangles"] if "second_triangles" in segment
            else segment["geometry_end"].triangles, dtype=np.float64)
        value = segment.get("declared_delta_rad")
        if value is not None:
            declared_increments.append(float(value))
        for triangle_first, triangle_second in zip(triangles_first, triangles_second):
            transform, residual = fit_transform(triangle_first, triangle_second)
            residual = float(residual)
            scale = max(float(np.ptp(triangle_first, axis=0).max()), 1.0)
            fit_tolerance = max(1e-7, 1e-6 * scale)
            residuals.append(residual)
            fit_tolerances.append(fit_tolerance)
            if residual > fit_tolerance:
                deforming += 1
            quaternion = rotation_to_quaternion(transform[:3, :3])
            angles.append(float(2.0 * np.arccos(np.clip(abs(float(quaternion[0])), -1.0, 1.0))))

    max_angle = max(angles, default=0.0)
    max_fit_residual = max(residuals, default=0.0)
    max_fit_tolerance = max(fit_tolerances, default=max(1e-7, tolerance))

    source = first if motion_geometry is None else motion_geometry
    axis_point = getattr(source, "rigid_axis_point", None)
    if axis_point is None:
        axis_point = getattr(source, "axis_point", None)
    axis_direction = getattr(source, "axis_direction", None)
    if axis_point is None:
        axis_point = getattr(first, "rigid_axis_point", None)
    if axis_direction is None:
        axis_direction = getattr(first, "axis_direction", None)
    if axis_direction is None:
        # Finite snapshots retain the axis point for pointwise wall velocity,
        # but intentionally do not claim that their angular velocity is a
        # complete motion definition.  Without the declared direction, leave
        # the rotational sagitta estimate unavailable.
        axis_status = "axis_not_declared"
        sagitta = None
    else:
        axis_point = np.asarray(axis_point, dtype=np.float64)
        axis_direction = np.asarray(axis_direction, dtype=np.float64)
        norm = float(np.linalg.norm(axis_direction))
        if (axis_point.shape != (3,) or axis_direction.shape != (3,)
                or not np.isfinite(axis_point).all() or not np.isfinite(axis_direction).all()
                or norm <= 1e-15):
            axis_status = "axis_not_declared"
            sagitta = None
        else:
            axis = axis_direction / norm
            points = np.concatenate((first_triangles.reshape(-1, 3),
                                     second_triangles.reshape(-1, 3)), axis=0)
            radius = (float(np.max(np.linalg.norm(np.cross(axis[None, :], points - axis_point), axis=1)))
                      if len(points) else 0.0)
            increment = max_angle / max(MOVING_WALL_SWEEP_SAMPLES - 1, 1)
            # This is the circular-arc midpoint sagitta for the sample
            # interval.  It is an estimate of pose interpolation error, not a
            # bound on an unknown CFD wall path.
            sagitta = float(radius * (1.0 - np.cos(increment / 2.0)))
            axis_status = "declared_axis_estimate"

    return {
        "max_rigid_fit_residual_m": float(max_fit_residual),
        "max_rigid_fit_tolerance_m": float(max_fit_tolerance),
        "deforming_triangle_count": int(deforming),
        "max_rotation_angle_rad": float(max_angle),
        "max_rotation_increment_rad": float(max_angle / max(MOVING_WALL_SWEEP_SAMPLES - 1, 1)),
        "declared_rotation_delta_rad": (None if declared_angle_delta is None
                                         else float(abs(declared_angle_delta))),
        "declared_rotation_path_rad": (None if declared_path_angle is None
                                        else float(declared_path_angle)),
        "max_rotational_sagitta_estimate_m": sagitta,
        "sagitta_status": axis_status,
        "sweep_sample_count": int(MOVING_WALL_SWEEP_SAMPLES),
        "sweep_segment_count": int(len(sweep_segments)),
        "max_declared_segment_rad": float(max(
            (abs(value) for value in declared_increments), default=0.0)),
        "exact_continuous_path": False,
    }


def _moving_result_metadata(*, status, checked, unavailable, approximation,
                            rotation_error, reason=None):
    result = {
        "schema": MOVING_WALL_DIAGNOSTIC_SCHEMA,
        "status": status,
        "particle_count": None,
        "mass_kg": None,
        "checked_particle_count": int(checked),
        "unavailable_particle_count": int(unavailable),
        "semantics": (
            "finite declared surfaces and saved particle chords; prescribed wall motion "
            "is checked with the shared endpoint-pose sweep; no exact continuous path claim"
        ),
        "saved_step_approximation": approximation,
        "rotation_sweep_error": rotation_error,
    }
    if reason is not None:
        result["reason"] = str(reason)
    return result


def moving_wall_crossings(previous, following, geometry, geometry_next=None, *, tolerance=1e-9):
    """Check saved particle chords against a declared finite moving surface.

    ``geometry`` may be a ``PrescribedGeometry``-like public schedule, in
    which case endpoint snapshots are materialized at the two state times, or
    a finite snapshot paired with ``geometry_next``.  A single moving finite
    snapshot is rejected as unsupported because inventing its future pose
    would violate the causal input contract.  The shared operator uses a
    declared schedules are split at public motion knots and at 90-degree
    angle increments, then each segment uses the shared rigid endpoint fit
    and 17 quaternion-pose samples.  Its report exposes the fit residual and
    rotational sagitta estimate so callers cannot mistake this saved-step
    audit for an exact continuous collision path.
    """
    if not np.array_equal(previous.particle_id, following.particle_id) or not np.array_equal(
            previous.particle_zone, following.particle_zone):
        raise ValueError("particle identity changed during physical evaluation")
    if tolerance <= 0:
        raise ValueError("positive intersection tolerance required")
    valid = previous.valid & following.valid
    first, second = _materialize_geometry_pair(
        geometry, previous.time_s, following.time_s, geometry_next)
    first_triangles, second_triangles = _validate_geometry_pair(first, second)
    schedule = _prescribed_sweep_segments(geometry, previous.time_s, following.time_s)
    declared_delta = (_prescribed_angle_delta(geometry, previous.time_s, following.time_s)
                      if schedule is None else schedule["declared_delta_rad"])
    declared_path = None if schedule is None else schedule["declared_path_rad"]
    first_wall_velocity = np.asarray(first.wall_velocity, dtype=np.float64)
    second_wall_velocity = np.asarray(second.wall_velocity, dtype=np.float64)
    if first_wall_velocity.shape != (len(first_triangles), 3) or second_wall_velocity.shape != (
            len(second_triangles), 3):
        raise ValueError("moving geometry wall velocity axis does not match triangles")

    endpoint_changed = not np.allclose(first_triangles, second_triangles, atol=tolerance, rtol=0.0)
    # Keep this exact rather than tolerance-based: the legacy static checker
    # treats any declared wall velocity as moving, and silently dropping a
    # small prescribed speed would reintroduce the unsupported-static path.
    endpoint_wall_velocity_nonzero = bool(np.any(first_wall_velocity != 0.0)
                                          or np.any(second_wall_velocity != 0.0))
    # A prescribed schedule is authoritative for whether the wall moved over
    # this interval.  Endpoint wall velocities can be nonzero at a knot even
    # when the pose is flat on both sides because the public derivative uses
    # neighbouring schedule samples.
    velocity_declared = endpoint_wall_velocity_nonzero if schedule is None else False
    declared_motion = (declared_path is not None
                       and declared_path > tolerance) if schedule is not None else (
                           declared_delta is not None and abs(float(declared_delta)) > tolerance)
    moving = endpoint_changed or velocity_declared or declared_motion

    approximation = {
        "particle_path": "linear chord between saved previous and following positions",
        "wall_path": "rigid endpoint fit with quaternion pose interpolation and sampled swept checks",
        "sweep_operator": "scripts.passive_tracers.spacetime_swept_wall_blocked",
        "wall_interpolation": "17 uniformly spaced endpoint-pose samples",
        "public_schedule_segmentation": "declared motion knots plus <=90 degree angle increments",
        "open_faces": "faces absent from the finite triangle contract are not tested",
        "exact_continuous_path": False,
        "future_fluid_state_used": False,
        "future_prescribed_motion_allowed": True,
    }
    if not moving:
        # Delegate the static case to the original implementation so existing
        # endpoint/intersection semantics and result values remain unchanged.
        # A public schedule is authoritative for the whole saved interval.  A
        # knot derivative can be nonzero at either endpoint even when the
        # pose path between the two public knots is flat; that endpoint value
        # must not route an otherwise static interval through the moving-surface
        # rejection.  Without a schedule, retain the legacy wall-velocity
        # rejection above and never infer a static interval from snapshots.
        legacy = static_wall_crossings(
            previous, following, first, tolerance=tolerance,
            public_schedule_static=schedule is not None)
        rotation_error = {
            "max_rigid_fit_residual_m": 0.0,
            "max_rigid_fit_tolerance_m": float(max(1e-7, tolerance)),
            "deforming_triangle_count": 0,
            "max_rotation_angle_rad": 0.0,
            "max_rotation_increment_rad": 0.0,
            "declared_rotation_delta_rad": 0.0 if declared_delta is not None else None,
            "declared_rotation_path_rad": 0.0 if declared_path is not None else None,
            "max_rotational_sagitta_estimate_m": 0.0,
            "sagitta_status": "static_degenerate",
            "sweep_sample_count": int(MOVING_WALL_SWEEP_SAMPLES),
            "sweep_segment_count": 1,
            "max_declared_segment_rad": 0.0,
            "exact_continuous_path": False,
        }
        result = dict(legacy)
        result.update({
            "schema": MOVING_WALL_DIAGNOSTIC_SCHEMA,
            "saved_step_approximation": approximation,
            "rotation_sweep_error": rotation_error,
            "moving_surface": {
                "endpoint_triangles_changed": bool(endpoint_changed),
                "declared_wall_velocity_nonzero": bool(endpoint_wall_velocity_nonzero),
                "declared_rotation_delta_rad": (
                    None if declared_delta is None else float(declared_delta)),
                "declared_rotation_path_rad": (
                    None if declared_path is None else float(declared_path)),
                "schedule_segmented": bool(schedule is not None),
                "public_schedule_authoritative_static": bool(schedule is not None),
            },
        })
        return result

    # A dynamic FiniteGeometry without an endpoint is intentionally not
    # extrapolated.  The caller may pass a PrescribedGeometry instead, in
    # which case _materialize_geometry_pair supplied the second snapshot.
    if geometry_next is None and not (
            callable(getattr(geometry, "at", None)) and hasattr(geometry, "sample_times")):
        return _moving_result_metadata(
            status="unsupported_moving_surface", checked=int(valid.sum()),
            unavailable=int((~valid).sum()), approximation=approximation,
            rotation_error={
                "max_rigid_fit_residual_m": None,
                "max_rigid_fit_tolerance_m": None,
                "deforming_triangle_count": None,
                "max_rotation_angle_rad": None,
                "max_rotation_increment_rad": None,
                "declared_rotation_delta_rad": None,
                "declared_rotation_path_rad": None,
                "max_rotational_sagitta_estimate_m": None,
                "sagitta_status": "missing_following_snapshot",
                "sweep_sample_count": int(MOVING_WALL_SWEEP_SAMPLES),
                "sweep_segment_count": 0,
                "max_declared_segment_rad": None,
                "exact_continuous_path": False,
            },
            reason="moving finite geometry requires a following public endpoint snapshot",
        )

    operator, _, _ = _swept_wall_operator()
    origin = previous.position[valid]
    endpoint = following.position[valid]
    if schedule is None:
        sweep_segments = [{
            "geometry_start": first, "geometry_end": second,
            "first_triangles": first_triangles, "second_triangles": second_triangles,
            "alpha_start": 0.0, "alpha_end": 1.0,
            "declared_delta_rad": declared_delta,
        }]
    else:
        sweep_segments = schedule["segments"]
    hit = np.zeros(len(origin), dtype=bool)
    for segment in sweep_segments:
        alpha_start = float(segment["alpha_start"])
        alpha_end = float(segment["alpha_end"])
        segment_origin = origin + alpha_start * (endpoint - origin)
        segment_endpoint = origin + alpha_end * (endpoint - origin)
        segment_start = segment["geometry_start"]
        segment_end = segment["geometry_end"]
        segment_triangles_start, segment_triangles_end = _validate_geometry_pair(
            segment_start, segment_end)
        hit |= operator(segment_origin, segment_endpoint,
                        segment_triangles_start, segment_triangles_end,
                        epsilon=tolerance)
    rotation_error = _rotation_sweep_error(
        first, second, first_triangles, second_triangles,
        motion_geometry=geometry,
        declared_angle_delta=declared_delta, declared_path_angle=declared_path,
        sweep_segments=sweep_segments, tolerance=tolerance)
    result = _moving_result_metadata(
        status="checked_prescribed_moving_saved_chords",
        checked=int(valid.sum()), unavailable=int((~valid).sum()),
        approximation=approximation, rotation_error=rotation_error)
    result["particle_count"] = int(hit.sum())
    result["mass_kg"] = float(previous.mass[valid][hit].sum())
    result["moving_surface"] = {
        "endpoint_triangles_changed": bool(endpoint_changed),
        "declared_wall_velocity_nonzero": bool(endpoint_wall_velocity_nonzero),
        "declared_rotation_delta_rad": (None if declared_delta is None else float(declared_delta)),
        "declared_rotation_path_rad": (None if declared_path is None else float(declared_path)),
        "schedule_segmented": bool(schedule is not None),
    }
    return result


# Descriptive alias for callers that use the protocol terminology.
saved_step_wall_crossings = moving_wall_crossings


def frame_physics(previous, predicted, reference, geometry, geometry_next=None):
    """Combine conservation, lifecycle and saved-step wall diagnostics.

    ``geometry`` may be a public prescribed schedule, in which case the
    moving diagnostic materializes both endpoint poses itself.  For callers
    that already resolved snapshots, ``geometry_next`` supplies the following
    finite pose explicitly.  The reference state is used for scoring
    observables only; it is never used to construct the wall path.
    """
    if not np.array_equal(predicted.particle_id,reference.particle_id) or not np.array_equal(predicted.particle_zone,reference.particle_zone):
        raise ValueError('prediction/reference identities mismatch')
    observed, expected = conserved_observables(predicted), conserved_observables(reference)
    return {"predicted":observed,"reference":expected,
            "mass_error_kg":observed['active_mass_kg']-expected['active_mass_kg'],
            "kinetic_energy_error_j":observed['kinetic_energy_j']-expected['kinetic_energy_j'],
            "validity_mismatch_count":int(np.count_nonzero(predicted.valid != reference.valid)),
            "changed_particle_mass_count":int(np.count_nonzero(predicted.mass != previous.mass)),
            "wall_chord":moving_wall_crossings(previous,predicted,geometry,geometry_next)}
