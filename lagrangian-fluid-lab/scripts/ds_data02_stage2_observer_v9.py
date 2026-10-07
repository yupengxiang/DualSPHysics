#!/usr/bin/env python3
"""Frozen, source-bound observers for the DS-DATA-02 development reference.

The v9 module is additive.  It leaves the consumed v5--v8 modules unchanged
and keeps the real scientific qualification state ``UNKNOWN``.  It provides
two small, model-free operators:

* mass-weighted fronts and fixed physical-scale mass distributions, with an
  explicit denominator and unknown buckets; and
* SO(3) pose/velocity errors for a rigid-body observer.

The operators are calibrated on independent manufactured data.  The F2
scientific sidecar and the F6 FloatingInfo CSV are source-bound observations;
neither path opens a trajectory HDF5 file.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence
import xml.etree.ElementTree as ET

import numpy as np


PROFILE_SCHEMA = "ds02.stage2.reference-observer-profile.v9"
MASS_RESULT_SCHEMA = "ds02.stage2.mass-observer-result.v9"
SO3_RESULT_SCHEMA = "ds02.stage2.so3-observer-result.v9"
CALIBRATION_SCHEMA = "ds02.stage2.observer-calibration.v9"
F6_TELEMETRY_SCHEMA = "ds02.stage2.f6-rigid-telemetry.v9"
F2_SUMMARY_SCHEMA = "ds02.stage2.f2-scan-summary.v9"
_HEX64 = __import__("re").compile(r"^[0-9a-f]{64}$")


class ObserverV9BindingError(ValueError):
    """Raised when an observer input is not bound or physically well formed."""


def sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.number)):
        raise ObserverV9BindingError(f"{name} must be finite numeric data")
    result = float(value)
    if not math.isfinite(result):
        raise ObserverV9BindingError(f"{name} must be finite numeric data")
    return result


def _array(value: Any, name: str, *, ndim: int | None = None) -> np.ndarray:
    try:
        result = np.asarray(value, dtype="float64")
    except (TypeError, ValueError) as error:
        raise ObserverV9BindingError(f"{name} must be numeric") from error
    if ndim is not None and result.ndim != ndim:
        raise ObserverV9BindingError(f"{name} must have ndim={ndim}")
    return result


def _finite_array(value: Any, shape: tuple[int, ...] | None, name: str) -> np.ndarray:
    result = _array(value, name)
    if shape is not None and result.shape != shape:
        raise ObserverV9BindingError(f"{name} shape {result.shape} differs from {shape}")
    if not np.isfinite(result).all():
        raise ObserverV9BindingError(f"{name} contains non-finite data")
    return result


def _bool_mask(value: Any, n: int, name: str) -> np.ndarray:
    result = np.asarray(value, dtype=bool)
    if result.shape != (n,):
        raise ObserverV9BindingError(f"{name} shape {result.shape} differs from {(n,)}")
    return result


def _strict_edges(value: Any, name: str = "normalized_bin_edges") -> np.ndarray:
    edges = _finite_array(value, None, name).reshape(-1)
    if edges.size < 2 or np.any(np.diff(edges) <= 0):
        raise ObserverV9BindingError(f"{name} must contain at least two strictly increasing values")
    return edges


def _require_sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        raise ObserverV9BindingError(f"{name} must be a lowercase SHA-256")
    return value


def _verify_file(path: Path | str, expected: str, name: str, *, allow_hdf5: bool = False) -> dict[str, Any]:
    resolved = Path(path).resolve()
    if not resolved.exists() or not resolved.is_file():
        raise ObserverV9BindingError(f"{name} is missing: {resolved}")
    if not allow_hdf5 and resolved.suffix.lower() in {".h5", ".hdf5"}:
        raise ObserverV9BindingError(f"{name} may not bind a trajectory HDF5")
    actual = sha256(resolved)
    _require_sha(expected, f"{name}.sha256")
    if actual != expected:
        raise ObserverV9BindingError(f"{name} SHA-256 differs from its frozen binding")
    stat = resolved.stat()
    return {"path": str(resolved), "sha256": actual, "bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns}


def _source_files(profile: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    source_files = profile.get("source_files")
    if not isinstance(source_files, list) or not source_files:
        raise ObserverV9BindingError("profile source_files are required")
    result = []
    for index, item in enumerate(source_files):
        if not isinstance(item, Mapping) or not isinstance(item.get("path"), str):
            raise ObserverV9BindingError(f"source_files[{index}] is malformed")
        _require_sha(item.get("sha256"), f"source_files[{index}].sha256")
        result.append(item)
    return result


def validate_profile(profile: Mapping[str, Any], *, verify_sources: bool = False) -> dict[str, Any]:
    """Validate a frozen profile and optionally verify all small source files."""
    if not isinstance(profile, Mapping) or profile.get("schema") != PROFILE_SCHEMA:
        raise ObserverV9BindingError("unsupported v9 observer profile schema")
    if not isinstance(profile.get("profile_id"), str) or not profile["profile_id"]:
        raise ObserverV9BindingError("profile_id is required")
    if not isinstance(profile.get("physical_case_id"), str) or not profile["physical_case_id"]:
        raise ObserverV9BindingError("physical_case_id is required")
    if profile.get("role") != "DEVELOPMENT" or profile.get("frozen") is not True:
        raise ObserverV9BindingError("only a frozen DEVELOPMENT profile is accepted")
    qualification = profile.get("qualification")
    if not isinstance(qualification, Mapping) or any(qualification.get(key) != "UNKNOWN" for key in ("QI", "QN", "QE")):
        raise ObserverV9BindingError("v9 profile qualification must remain UNKNOWN")
    scales = profile.get("characteristic_scales_m")
    if not isinstance(scales, Mapping):
        raise ObserverV9BindingError("characteristic_scales_m are required")
    for name in ("position", "mass_distribution", "feature_time"):
        if _finite(scales.get(name), f"characteristic_scales_m.{name}") <= 0:
            raise ObserverV9BindingError(f"characteristic_scales_m.{name} must be positive")
    quantiles = profile.get("mass_quantiles")
    if not isinstance(quantiles, Sequence) or isinstance(quantiles, (str, bytes)) or not quantiles:
        raise ObserverV9BindingError("mass_quantiles are required")
    for index, value in enumerate(quantiles):
        q = _finite(value, f"mass_quantiles[{index}]")
        if not 0.0 <= q <= 1.0:
            raise ObserverV9BindingError("mass quantiles must lie in [0,1]")
    distribution = profile.get("mass_distribution")
    if not isinstance(distribution, Mapping):
        raise ObserverV9BindingError("mass_distribution is required")
    axis = distribution.get("axis")
    if axis not in ("x", "y", "z"):
        raise ObserverV9BindingError("mass_distribution.axis must be x, y, or z")
    edges = _strict_edges(distribution.get("normalized_bin_edges"))
    scale = _finite(distribution.get("physical_scale_m"), "mass_distribution.physical_scale_m")
    if scale <= 0:
        raise ObserverV9BindingError("mass_distribution.physical_scale_m must be positive")
    if not isinstance(distribution.get("boundary_policy"), str) or "lower-inclusive" not in distribution["boundary_policy"]:
        raise ObserverV9BindingError("mass_distribution boundary policy must be explicit")
    frame = profile.get("frame_policy")
    if not isinstance(frame, Mapping) or frame.get("moving_frame") not in ("REQUIRE_EXPLICIT_POSE", "STATIC_WORLD"):
        raise ObserverV9BindingError("frame_policy must explicitly bind moving-frame semantics")
    tolerance = profile.get("tolerance_profile")
    if not isinstance(tolerance, Mapping) or tolerance.get("mutable") is not False:
        raise ObserverV9BindingError("tolerance_profile must be frozen")
    if verify_sources:
        verified = [_verify_file(item["path"], item["sha256"], f"source_files[{i}]")
                    for i, item in enumerate(_source_files(profile))]
    else:
        verified = []
        _source_files(profile)
    result = dict(profile)
    result["_validated_edges"] = edges.tolist()
    result["_verified_sources"] = verified
    return result


def validate_observation_contract(profile: Mapping[str, Any], observations: Mapping[str, Any]) -> dict[str, Any]:
    """Bind names, shapes, fixed scales, and query times to the frozen profile.

    This deliberately validates an observation *payload* rather than trusting
    a reference's self-reported shape or feature time.  Empty query sets,
    shortened first dimensions, scale changes, and an arbitrary event time
    therefore fail before any score is produced.
    """
    validated = validate_profile(profile, verify_sources=False)
    contract = validated.get("observation_contract")
    if not isinstance(contract, Mapping):
        raise ObserverV9BindingError("profile observation_contract is required")
    expected_times = _finite_array(contract.get("query_times_s"), None, "contract.query_times_s").reshape(-1)
    if not len(expected_times):
        raise ObserverV9BindingError("contract query_times_s must be nonempty")
    supplied_times = _finite_array(observations.get("query_times_s"), None, "observations.query_times_s").reshape(-1)
    if not len(supplied_times) or supplied_times.shape != expected_times.shape or not np.array_equal(supplied_times, expected_times):
        raise ObserverV9BindingError("observations query_times_s differ from frozen profile")
    names = contract.get("fixed_observation_names")
    if not isinstance(names, Sequence) or isinstance(names, (str, bytes)) or not names:
        raise ObserverV9BindingError("contract fixed_observation_names must be nonempty")
    shapes = contract.get("shapes")
    if not isinstance(shapes, Mapping):
        raise ObserverV9BindingError("contract shapes are required")
    checked: dict[str, list[int]] = {}
    for name in names:
        if not isinstance(name, str) or name not in observations:
            raise ObserverV9BindingError(f"observation {name!r} is absent")
        expected_shape = tuple(int(item) for item in shapes.get(name, []))
        if not expected_shape:
            raise ObserverV9BindingError(f"observation shape for {name} is absent")
        value = _array(observations[name], f"observations.{name}")
        if value.shape != expected_shape:
            raise ObserverV9BindingError(f"observations.{name} shape {value.shape} differs from {expected_shape}")
        if not np.isfinite(value).all():
            raise ObserverV9BindingError(f"observations.{name} contains non-finite data")
        checked[name] = list(value.shape)
    fixed = contract.get("fixed_scales")
    if not isinstance(fixed, Mapping):
        raise ObserverV9BindingError("contract fixed_scales are required")
    supplied_scales = observations.get("scales")
    if not isinstance(supplied_scales, Mapping):
        raise ObserverV9BindingError("observations scales are required")
    for name, expected in fixed.items():
        if name not in supplied_scales or not math.isclose(_finite(supplied_scales[name], f"scales.{name}"),
                                                           _finite(expected, f"contract.fixed_scales.{name}"),
                                                           rel_tol=0.0, abs_tol=1e-15):
            raise ObserverV9BindingError(f"observation scale {name} differs from frozen profile")
    feature_time = _finite(observations.get("feature_time_s"), "observations.feature_time_s")
    frozen_feature_time = _finite(contract.get("feature_time_s"), "contract.feature_time_s")
    if not math.isclose(feature_time, frozen_feature_time, rel_tol=0.0, abs_tol=1e-15):
        raise ObserverV9BindingError("feature_time_s differs from frozen profile")
    return {"schema": "ds02.stage2.observation-contract-validation.v9",
            "status": "PASS_FROZEN_CONTRACT",
            "query_times_s": expected_times.tolist(), "shapes": checked,
            "feature_time_s": frozen_feature_time,
            "quality": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
            "qualification_status": "UNKNOWN"}


def bind_first_passage_first_bracket(*, crossing_times_s: Sequence[float],
                                     saved_brackets: Sequence[Sequence[float]],
                                     event_time_s: float | None = None) -> dict[str, Any]:
    """Bind an observed event to the first candidate's first saved bracket."""
    candidates = _finite_array(crossing_times_s, None, "crossing_times_s").reshape(-1)
    if not len(candidates) or np.any(np.diff(candidates) <= 0):
        raise ObserverV9BindingError("crossing_times_s must be nonempty and min-first ordered")
    bracket_array = _array(saved_brackets, "saved_brackets")
    if bracket_array.ndim != 2 or bracket_array.shape[1] != 2 or not len(bracket_array):
        raise ObserverV9BindingError("saved_brackets must have shape (n,2) and be nonempty")
    if not np.isfinite(bracket_array).all() or np.any(bracket_array[:, 1] <= bracket_array[:, 0]):
        raise ObserverV9BindingError("saved_brackets contain invalid endpoints")
    if np.any(bracket_array[1:, 0] < bracket_array[:-1, 1]):
        raise ObserverV9BindingError("saved_brackets overlap or are out of order")
    first = float(candidates[0])
    if not bracket_array[0, 0] <= first <= bracket_array[0, 1]:
        raise ObserverV9BindingError("first crossing candidate is not in the first saved bracket")
    if np.sum((candidates >= bracket_array[0, 0]) & (candidates <= bracket_array[0, 1])) != 1:
        raise ObserverV9BindingError("first saved bracket contains multiple crossing candidates")
    event = first if event_time_s is None else _finite(event_time_s, "event_time_s")
    if not math.isclose(event, first, rel_tol=0.0, abs_tol=1e-12):
        raise ObserverV9BindingError("event_time_s differs from the first crossing candidate")
    return {"status": "observed", "event_time_s": event,
            "first_saved_bracket_s": bracket_array[0].tolist(),
            "crossing_candidate_times_s": candidates.tolist(),
            "feature_time_source": "first_candidate_in_first_saved_bracket"}


def _rotation_matrix(value: Any, name: str = "rotation_matrix", *, atol: float = 1e-8) -> np.ndarray:
    matrix = _finite_array(value, (3, 3), name)
    if not np.allclose(matrix.T @ matrix, np.eye(3), rtol=0.0, atol=atol):
        raise ObserverV9BindingError(f"{name} is not orthonormal")
    determinant = float(np.linalg.det(matrix))
    if not math.isclose(determinant, 1.0, rel_tol=0.0, abs_tol=atol):
        raise ObserverV9BindingError(f"{name} must have determinant +1")
    return matrix


def points_in_frame(points: Any, *, pose: Mapping[str, Any] | None = None,
                    source_frame: str = "world", target_frame: str = "world") -> np.ndarray:
    """Transform world points to an explicit moving body frame.

    A missing pose is accepted only for a world-to-world observation.  The
    inverse map is ``R.T @ (x_world - translation)`` and requires a proper
    rotation matrix, so a changing origin or a scale/shear cannot be silently
    treated as a moving frame.
    """
    values = _array(points, "points")
    if values.ndim != 2 or values.shape[1] != 3 or not len(values):
        raise ObserverV9BindingError("points must have shape (n,3) and be nonempty")
    if source_frame == target_frame:
        if not np.isfinite(values).all():
            raise ObserverV9BindingError("points contain non-finite values")
        if pose is not None:
            raise ObserverV9BindingError("a pose cannot be silently ignored when source and target frames match")
        return values
    if source_frame != "world" or target_frame != "body" or not isinstance(pose, Mapping):
        raise ObserverV9BindingError("moving-frame transform needs world -> body pose")
    if not np.isfinite(values).all():
        raise ObserverV9BindingError("points contain non-finite values")
    rotation = _rotation_matrix(pose.get("rotation_matrix"), "pose.rotation_matrix")
    translation = _finite_array(pose.get("translation_m"), (3,), "pose.translation_m")
    return (rotation.T @ (values - translation).T).T


def _axis_number(axis: str | int) -> int:
    if isinstance(axis, bool):
        raise ObserverV9BindingError("axis must be x, y, z, or an integer 0..2")
    if isinstance(axis, str) and axis in {"x", "y", "z"}:
        return {"x": 0, "y": 1, "z": 2}[axis]
    if isinstance(axis, int) and axis in (0, 1, 2):
        return axis
    raise ObserverV9BindingError("axis must be x, y, z, or an integer 0..2")


def observe_mass_point_cloud(points: Any, masses: Any, *, axis: str | int,
                             quantiles: Sequence[float], physical_scale_m: float,
                             normalized_bin_edges: Sequence[float],
                             initial_mass_denominator_kg: float,
                             missing_mass_kg: float = 0.0,
                             velocities: Any | None = None,
                             velocity_missing_mass_kg: float = 0.0,
                             frame_pose: Mapping[str, Any] | None = None,
                             source_frame: str = "world",
                             target_frame: str = "world") -> dict[str, Any]:
    """Compute mass-weighted fronts and bins without particle-ID assumptions.

    Finite positive masses attached to non-finite positions are retained in an
    explicit invalid bucket.  Mass outside the fixed edges is retained in an
    out-of-range bucket.  ``initial_mass_denominator_kg`` is caller supplied;
    it is never replaced by the sum of observed particles.
    """
    raw_points = _array(points, "points")
    if raw_points.ndim != 2 or raw_points.shape[1] != 3 or not len(raw_points):
        raise ObserverV9BindingError("points must have shape (n,3) and be nonempty")
    weights = _array(masses, "masses").reshape(-1)
    if weights.shape != (len(raw_points),):
        raise ObserverV9BindingError("masses must have one entry per point")
    axis_index = _axis_number(axis)
    scale = _finite(physical_scale_m, "physical_scale_m")
    if scale <= 0:
        raise ObserverV9BindingError("physical_scale_m must be positive")
    edges = _strict_edges(normalized_bin_edges)
    denominator = _finite(initial_mass_denominator_kg, "initial_mass_denominator_kg")
    explicit_missing = _finite(missing_mass_kg, "missing_mass_kg")
    explicit_velocity_missing = _finite(velocity_missing_mass_kg, "velocity_missing_mass_kg")
    if denominator <= 0 or explicit_missing < 0 or explicit_velocity_missing < 0:
        raise ObserverV9BindingError("mass denominator and missing buckets are invalid")
    transformed = points_in_frame(raw_points, pose=frame_pose, source_frame=source_frame,
                                  target_frame=target_frame) if frame_pose is not None or source_frame != target_frame else raw_points
    finite_position = np.isfinite(transformed).all(axis=1)
    finite_mass = np.isfinite(weights) & (weights > 0)
    valid = finite_position & finite_mass
    # Non-finite masses have no defensible weight and therefore cannot enter a
    # numeric bucket; finite non-positive masses are invalid, while finite
    # positive masses with a bad position remain countable as invalid mass.
    positive_mass = np.isfinite(weights) & (weights > 0)
    invalid_positive_position_mass = float(weights[positive_mass & ~finite_position].sum())
    invalid_nonpositive_mass = float(weights[np.isfinite(weights) & ~positive_mass].sum())
    invalid_mass = invalid_positive_position_mass + max(0.0, invalid_nonpositive_mass)
    known_positions = transformed[valid]
    known_weights = weights[valid]
    known_mass = float(known_weights.sum())
    if known_mass <= 0:
        raise ObserverV9BindingError("no finite positive mass remains for an observer")
    coordinate = known_positions[:, axis_index] / scale
    bins = np.zeros(edges.size - 1, dtype="float64")
    for index in range(len(bins)):
        mask = (coordinate >= edges[index]) & (coordinate < edges[index + 1])
        if index == len(bins) - 1:
            mask |= coordinate == edges[index + 1]
        bins[index] = float(known_weights[mask].sum())
    out_of_range = float(known_weights[(coordinate < edges[0]) | (coordinate > edges[-1])].sum())
    sorted_order = np.argsort(coordinate, kind="stable")
    sorted_coordinate = coordinate[sorted_order]
    cumulative = np.cumsum(known_weights[sorted_order])
    fronts: dict[str, float] = {}
    for raw_q in quantiles:
        q = _finite(raw_q, "mass_quantile")
        if not 0.0 <= q <= 1.0:
            raise ObserverV9BindingError("mass quantile must lie in [0,1]")
        index = int(np.searchsorted(cumulative, q * known_mass, side="left"))
        index = min(index, len(sorted_coordinate) - 1)
        fronts[str(q)] = float(sorted_coordinate[index] * scale)
    observed_mass = known_mass + explicit_missing + invalid_mass
    if observed_mass > denominator + 1e-12 * max(1.0, denominator):
        raise ObserverV9BindingError("observed and explicit unknown mass exceeds initial denominator")
    denominator_unobserved = max(0.0, denominator - observed_mass)
    result: dict[str, Any] = {
        "schema": MASS_RESULT_SCHEMA,
        "axis": ("xyz"[axis_index]),
        "source_frame": source_frame,
        "target_frame": target_frame,
        "frame_transform": "world_to_body_R_transpose_x_minus_t" if source_frame != target_frame else "identity",
        "known_mass_kg": known_mass,
        "initial_mass_denominator_kg": denominator,
        "missing_mass_bucket_kg": explicit_missing,
        "invalid_mass_bucket_kg": invalid_mass,
        "out_of_range_mass_bucket_kg": out_of_range,
        "denominator_unobserved_mass_kg": denominator_unobserved,
        "velocity_missing_mass_bucket_kg": explicit_velocity_missing,
        "mass_accounting": {
            "known_finite_position_mass_kg": known_mass,
            "explicit_missing_mass_kg": explicit_missing,
            "invalid_mass_kg": invalid_mass,
            "denominator_unobserved_mass_kg": denominator_unobserved,
            "denominator_conserved": math.isclose(observed_mass + denominator_unobserved,
                                                   denominator, rel_tol=0.0, abs_tol=1e-12),
        },
        "mass_weighted_com_m": ((known_positions * known_weights[:, None]).sum(axis=0) / known_mass).tolist(),
        "mass_quantile_front_m": fronts,
        "mass_quantile_definition": "lower weighted empirical CDF over finite positive observed positions",
        "mass_distribution_normalized_edges": edges.tolist(),
        "mass_distribution_physical_edges_m": (edges * scale).tolist(),
        "mass_distribution_kg": bins.tolist(),
        "boundary_policy": "each bin lower-inclusive; upper-exclusive except final upper-inclusive",
        "identity_binding": "source-region and mass distribution; no particle IDs",
        "quality": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "qualification_status": "UNKNOWN",
        "model_invoked": False,
    }
    if velocities is not None:
        velocity = _array(velocities, "velocities")
        if velocity.shape != raw_points.shape:
            raise ObserverV9BindingError("velocities shape must match points")
        finite_velocity = np.isfinite(velocity).all(axis=1)
        active_velocity = valid & finite_velocity
        velocity_missing_from_rows = float(weights[valid & ~finite_velocity].sum())
        if active_velocity.any():
            vw = weights[active_velocity]
            vv = velocity[active_velocity]
            v_mass = float(vw.sum())
            result["mass_weighted_mean_velocity_m_s"] = (vv * vw[:, None]).sum(axis=0).tolist()
            result["mass_weighted_kinetic_energy_J"] = float(0.5 * (vw * (vv * vv).sum(axis=1)).sum())
        else:
            result["mass_weighted_mean_velocity_m_s"] = None
            result["mass_weighted_kinetic_energy_J"] = None
        result["velocity_missing_mass_from_rows_kg"] = velocity_missing_from_rows
        result["velocity_observation_status"] = (
            "COMPLETE_FOR_OBSERVED_POSITIONS" if velocity_missing_from_rows == 0.0 else
            "PARTIAL_VELOCITY_OBSERVATION_EXPLICIT_BUCKET")
    return result


def _canonical_quaternion(quaternion: Any) -> np.ndarray:
    values = _finite_array(quaternion, (4,), "quaternion")
    norm = float(np.linalg.norm(values))
    if norm <= 0:
        raise ObserverV9BindingError("quaternion has zero norm")
    values = values / norm
    for value in values:
        if abs(float(value)) > 1e-15:
            if value < 0:
                values = -values
            break
    return values


def quaternion_to_matrix(quaternion: Any) -> np.ndarray:
    w, x, y, z = _canonical_quaternion(quaternion)
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ], dtype="float64")


def so3_geodesic_angle_rad(reference_rotation: Any, predicted_rotation: Any) -> float:
    reference = _rotation_matrix(reference_rotation, "reference_rotation")
    predicted = _rotation_matrix(predicted_rotation, "predicted_rotation")
    relative = reference.T @ predicted
    cosine = float(np.clip((np.trace(relative) - 1.0) / 2.0, -1.0, 1.0))
    return float(math.acos(cosine))


def _shortest_angle_degrees(delta: np.ndarray) -> np.ndarray:
    return (delta + 180.0) % 360.0 - 180.0


def euler_wrap_error_degrees(reference: Any, predicted: Any) -> list[float]:
    ref = _finite_array(reference, (3,), "reference_euler_degrees")
    pred = _finite_array(predicted, (3,), "predicted_euler_degrees")
    return _shortest_angle_degrees(pred - ref).tolist()


def observe_rigid_pose(reference: Mapping[str, Any], predicted: Mapping[str, Any]) -> dict[str, Any]:
    """Compare pose and velocities after binding a proper SO(3) representation."""
    if not isinstance(reference, Mapping) or not isinstance(predicted, Mapping):
        raise ObserverV9BindingError("rigid pose inputs must be mappings")
    ref_position = _finite_array(reference.get("position_m"), (3,), "reference.position_m")
    pred_position = _finite_array(predicted.get("position_m"), (3,), "predicted.position_m")
    if "quaternion" in reference:
        ref_rotation = quaternion_to_matrix(reference["quaternion"])
    else:
        ref_rotation = _rotation_matrix(reference.get("rotation_matrix"), "reference.rotation_matrix")
    if "quaternion" in predicted:
        pred_rotation = quaternion_to_matrix(predicted["quaternion"])
    else:
        pred_rotation = _rotation_matrix(predicted.get("rotation_matrix"), "predicted.rotation_matrix")
    result: dict[str, Any] = {
        "schema": SO3_RESULT_SCHEMA,
        "translation_error_m": float(np.linalg.norm(pred_position - ref_position)),
        "so3_geodesic_angle_rad": so3_geodesic_angle_rad(ref_rotation, pred_rotation),
        "pose_representation": "proper_rotation_matrix_or_quaternion; q_and_minus_q_identical",
        "quality": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "qualification_status": "UNKNOWN",
        "model_invoked": False,
    }
    for field, output in (("linear_velocity_m_s", "linear_velocity_error_m_s"),
                          ("angular_velocity_rad_s", "angular_velocity_error_rad_s")):
        if field in reference or field in predicted:
            ref = _finite_array(reference.get(field), (3,), f"reference.{field}")
            pred = _finite_array(predicted.get(field), (3,), f"predicted.{field}")
            result[output] = float(np.linalg.norm(pred - ref))
    if "euler_degrees" in reference or "euler_degrees" in predicted:
        result["euler_wrap_error_degrees"] = euler_wrap_error_degrees(
            reference.get("euler_degrees"), predicted.get("euler_degrees"))
    return result


def manufactured_mass_calibration() -> dict[str, Any]:
    """Independent hand-calculated unequal-mass point-cloud calibration."""
    points = [[-1.0, 0.0, 0.0], [0.0, 0.0, 0.0], [1.0, 0.0, 0.0],
              [2.0, 0.0, 0.0], [2.5, 0.0, 0.0], [float("nan"), 0.0, 0.0]]
    masses = [1.0, 2.0, 3.0, 4.0, 5.0, 0.5]
    actual = observe_mass_point_cloud(
        points, masses, axis="x", quantiles=[0.5, 0.75, 1.0], physical_scale_m=2.0,
        normalized_bin_edges=[-0.4, 0.0, 0.5, 1.0, 1.25],
        initial_mass_denominator_kg=16.0, missing_mass_kg=0.5,
    )
    expected = {
        "known_mass_kg": 15.0,
        "invalid_mass_bucket_kg": 0.5,
        "missing_mass_bucket_kg": 0.5,
        "out_of_range_mass_bucket_kg": 1.0,
        "mass_distribution_kg": [0.0, 2.0, 3.0, 9.0],
        "mass_weighted_com_m": [1.5, 0.0, 0.0],
        "mass_quantile_front_m": {"0.5": 2.0, "0.75": 2.5, "1.0": 2.5},
        "initial_mass_denominator_kg": 16.0,
    }
    checks = []
    for name, expected_value in expected.items():
        actual_value = actual[name]
        if isinstance(expected_value, Mapping):
            passed = set(actual_value) == set(expected_value) and all(
                math.isclose(float(actual_value[key]), float(expected_value[key]), rel_tol=0.0, abs_tol=1e-12)
                for key in expected_value)
        else:
            passed = bool(np.allclose(np.asarray(actual_value, dtype="float64"),
                                      np.asarray(expected_value, dtype="float64"), rtol=0.0, atol=1e-12))
        checks.append({"name": name, "status": "PASS" if passed else "FAIL",
                       "expected": expected_value, "actual": actual_value})
    return {"schema": CALIBRATION_SCHEMA,
            "mass_status": "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL",
            "mass_checks": checks,
            "mass_fixture": "unequal masses; exact bin boundaries; out-of-range point; NaN position; explicit missing denominator",
            "model_invoked": False}


def manufactured_so3_calibration() -> dict[str, Any]:
    """Independent SO(3) calibration including antipodal and pi cases."""
    identity = np.eye(3)
    q = [math.cos(math.pi / 4), 0.0, 0.0, math.sin(math.pi / 4)]
    checks: list[dict[str, Any]] = []
    checks.append({"name": "q_and_minus_q_same_rotation", "status":
                   "PASS" if np.allclose(quaternion_to_matrix(q), quaternion_to_matrix([-v for v in q]), atol=1e-12) else "FAIL"})
    pi_q = [0.0, 1.0, 0.0, 0.0]
    checks.append({"name": "angle_pi", "status":
                   "PASS" if math.isclose(so3_geodesic_angle_rad(identity, quaternion_to_matrix(pi_q)), math.pi,
                                           rel_tol=0.0, abs_tol=1e-12) else "FAIL"})
    checks.append({"name": "euler_wrap", "status":
                   "PASS" if np.allclose(euler_wrap_error_degrees([359.0, -179.0, 1.0],
                                                                    [-1.0, 181.0, 361.0]), [0.0, 0.0, 0.0], atol=1e-12) else "FAIL"})
    try:
        _rotation_matrix([[1.0, 0.1, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    except ObserverV9BindingError:
        checks.append({"name": "nonorthogonal_rejected", "status": "PASS"})
    else:
        checks.append({"name": "nonorthogonal_rejected", "status": "FAIL"})
    pose = observe_rigid_pose(
        {"position_m": [0.0, 0.0, 0.0], "quaternion": q,
         "linear_velocity_m_s": [1.0, 2.0, 3.0], "angular_velocity_rad_s": [0.1, 0.2, 0.3]},
        {"position_m": [0.01, 0.0, 0.0], "quaternion": [-v for v in q],
         "linear_velocity_m_s": [1.0, 2.0, 3.0], "angular_velocity_rad_s": [0.1, 0.2, 0.3]},
    )
    checks.append({"name": "pose_antipodal_translation_only", "status":
                   "PASS" if math.isclose(pose["so3_geodesic_angle_rad"], 0.0, abs_tol=1e-12)
                   and math.isclose(pose["translation_error_m"], 0.01, abs_tol=1e-12) else "FAIL"})
    return {"schema": CALIBRATION_SCHEMA,
            "so3_status": "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL",
            "so3_checks": checks,
            "so3_fixture": "q/-q; angle-pi quaternion; Euler wrap; nonorthogonal rejection; pose and velocity errors",
            "model_invoked": False}


def summarize_f2_scan_sidecar(path: Path | str, profile: Mapping[str, Any]) -> dict[str, Any]:
    """Bind the existing F2 macro sidecar without opening trajectory.h5."""
    validated = validate_profile(profile, verify_sources=False)
    source = next((item for item in _source_files(validated) if item.get("role") == "scientific_scan_sidecar"), None)
    if source is None or Path(source["path"]).resolve() != Path(path).resolve():
        raise ObserverV9BindingError("F2 scan path is not the frozen sidecar binding")
    source_audit = _verify_file(path, source["sha256"], "F2 scientific scan sidecar")
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema") != "ds02.stage2.scientific-scan.v1":
        raise ObserverV9BindingError("unsupported F2 scan sidecar schema")
    if payload.get("physical_case_id") != validated["physical_case_id"]:
        raise ObserverV9BindingError("F2 scan physical_case_id differs from profile")
    times = _finite_array(payload.get("time_s"), None, "scan.time_s").reshape(-1)
    if not len(times) or np.any(np.diff(times) <= 0):
        raise ObserverV9BindingError("F2 scan time axis is not strictly increasing")
    macros = payload.get("macros")
    if not isinstance(macros, list) or len(macros) != len(times):
        raise ObserverV9BindingError("F2 macro rows do not match the time axis")
    for index, row in enumerate(macros):
        if not isinstance(row, Mapping) or not math.isclose(_finite(row.get("time_s"), f"macros[{index}].time_s"),
                                                             float(times[index]), rel_tol=0.0, abs_tol=1e-12):
            raise ObserverV9BindingError("F2 macro time does not match source time")
    required = ("active_fluid_mass_kg", "active_fluid_com_m", "active_fluid_mean_velocity_m_s",
                "active_fluid_kinetic_energy_J")
    for index, row in enumerate(macros):
        for key in required:
            if key not in row:
                raise ObserverV9BindingError(f"F2 macro row {index} lacks {key}")
            if key.endswith("_m") or key.endswith("_m_s"):
                _finite_array(row[key], (3,), f"macros[{index}].{key}")
            else:
                _finite(row[key], f"macros[{index}].{key}")
    return {"schema": F2_SUMMARY_SCHEMA,
            "physical_case_id": validated["physical_case_id"],
            "source": source_audit,
            "frames": len(times),
            "time_window_s": [float(times[0]), float(times[-1])],
            "mass_observer_status": "OPERATOR_CALIBRATED_REAL_SPATIAL_INPUT_MISSING",
            "mass_observer_reason": "scientific-scan sidecar stores macros, not per-particle positions and masses",
            "trajectory_hdf5_read": False,
            "quality": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
            "qualification_status": "UNKNOWN",
            "model_invoked": False}


def _xml_float(value: Any, name: str) -> float:
    try:
        return _finite(float(value), name)
    except (TypeError, ValueError) as error:
        raise ObserverV9BindingError(f"{name} is not numeric XML data") from error


def _f6_mass_semantics(xml_path: Path) -> dict[str, Any]:
    root = ET.parse(xml_path).getroot()
    body_mass = None
    support_mass = None
    support_count = None
    inertia = None
    for element in root.iter():
        if element.tag.split("}")[-1].lower() != "floating":
            continue
        child = {item.tag.split("}")[-1].lower(): item for item in element}
        if "massbody" in child:
            body_mass = _xml_float(child["massbody"].attrib.get("value"), "massbody")
            if "inertia" in child:
                inertia = [_xml_float(child["inertia"].attrib.get(axis), f"inertia.{axis}") for axis in ("x", "y", "z")]
        if "masspart" in child:
            support_mass = _xml_float(child["masspart"].attrib.get("value"), "masspart")
            support_count = int(element.attrib.get("count", "0"))
    if body_mass is None or support_mass is None or not support_count:
        raise ObserverV9BindingError("F6 XML lacks both massbody and floating support metadata")
    return {"massbody_kg": body_mass,
            "support_particle_mass_kg": support_mass,
            "support_particle_count": support_count,
            "support_particle_weight_sum_kg": support_mass * support_count,
            "inertia_kg_m2": inertia,
            "mass_semantics": "massbody is rigid physical mass; support_particle_weight_sum is SPH support weight",
            "rigid_mass_must_not_be_inferred_from_support_sum": True}


def load_f6_source_bound_telemetry(profile: Mapping[str, Any]) -> dict[str, Any]:
    """Read only the small official FloatingInfo CSV and bound its provenance."""
    validated = validate_profile(profile, verify_sources=False)
    sources = {item.get("role"): item for item in _source_files(validated)}
    verified = {role: _verify_file(item["path"], item["sha256"], f"F6 {role}")
                for role, item in sources.items()}
    report_item = sources.get("floatinginfo_report")
    csv_item = sources.get("floatinginfo_csv")
    xml_item = sources.get("generated_xml")
    if not report_item or not csv_item or not xml_item:
        raise ObserverV9BindingError("F6 profile must bind XML, FloatingInfo report, and CSV")
    report = json.loads(Path(report_item["path"]).read_text(encoding="utf-8"))
    if report.get("schema") != "ds02.f6.fulltime-floatinginfo-worker-result.v1" or report.get("status") != "completed":
        raise ObserverV9BindingError("F6 FloatingInfo report is not a completed official export")
    case = report.get("case", {})
    if case.get("case_id") != validated["physical_case_id"] or case.get("physical_case_id") != validated["physical_case_id"]:
        raise ObserverV9BindingError("F6 FloatingInfo report case binding differs from profile")
    if case.get("family_id") != "F6":
        raise ObserverV9BindingError("F6 FloatingInfo report family_id is not F6")
    assigned_family = case.get("assigned_family")
    manifest_item = sources.get("manifest")
    if manifest_item:
        manifest = json.loads(Path(manifest_item["path"]).read_text(encoding="utf-8"))
        if (manifest.get("family_id"), manifest.get("physical_case_id")) != ("F6", validated["physical_case_id"]):
            raise ObserverV9BindingError("F6 manifest family/case does not match CURRENT-bound profile")
    current_item = sources.get("current_catalog")
    if current_item:
        catalog = json.loads(Path(current_item["path"]).read_text(encoding="utf-8"))
        matching_rows = [row for row in catalog.get("cases", [])
                         if isinstance(row, Mapping) and row.get("physical_case_id") == validated["physical_case_id"]]
        if len(matching_rows) != 1:
            raise ObserverV9BindingError("CURRENT catalog does not contain exactly one F6 physical case row")
        current_row = matching_rows[0]
        for key in ("family_id", "frames", "particles"):
            expected = {"family_id": "F6", "frames": validated.get("expected_frames"),
                        "particles": validated.get("expected_particles")}[key]
            if expected is not None and current_row.get(key) != expected:
                raise ObserverV9BindingError(f"CURRENT catalog {key} differs from frozen F6 profile")
    for role in ("gencase_receipt", "solver_receipt"):
        receipt_item = sources.get(role)
        if receipt_item:
            receipt = json.loads(Path(receipt_item["path"]).read_text(encoding="utf-8"))
            if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
                raise ObserverV9BindingError(f"F6 {role} is not a completed successful receipt")
    run_csv_item = sources.get("run_csv")
    if run_csv_item:
        run_text = Path(run_csv_item["path"]).read_text(encoding="utf-8", errors="replace")
        for token in validated.get("run_csv_required_tokens", []):
            if str(token) not in run_text:
                raise ObserverV9BindingError(f"F6 Run.csv lacks frozen solver token {token!r}")
    inventory_item = sources.get("partfloat_inventory")
    partfloat_item = sources.get("partfloat_info")
    if inventory_item and partfloat_item:
        inventory = json.loads(Path(inventory_item["path"]).read_text(encoding="utf-8"))
        entries = [entry for entry in inventory.get("entries", [])
                   if isinstance(entry, Mapping) and entry.get("physical_case_id") == validated["physical_case_id"]]
        if len(entries) != 1 or entries[0].get("sha256") != partfloat_item["sha256"]:
            raise ObserverV9BindingError("PartFloatInfo inventory does not bind the frozen F6 case/hash")
    xml_text = Path(xml_item["path"]).read_text(encoding="utf-8", errors="replace")
    if validated["physical_case_id"] not in xml_text:
        raise ObserverV9BindingError("F6 generated XML does not contain the frozen physical case id")
    output = report.get("output", {})
    if output.get("sha256") != csv_item["sha256"] or int(output.get("bytes", -1)) != verified["floatinginfo_csv"]["bytes"]:
        raise ObserverV9BindingError("F6 FloatingInfo report does not bind the frozen CSV")
    native = report.get("native_receipt", {})
    native_item = sources.get("solver_receipt")
    if not native_item or native.get("expected_sha256") != native_item["sha256"] or native.get("actual_sha256") != native_item["sha256"]:
        raise ObserverV9BindingError("F6 FloatingInfo report/native receipt hash binding is incomplete")
    semantics = _f6_mass_semantics(Path(xml_item["path"]))
    required_columns = {
        "part", "time [s]", "fvel.x [m/s]", "fvel.y [m/s]", "fvel.z [m/s]",
        "fomega.x [rad/s]", "fomega.y [rad/s]", "fomega.z [rad/s]",
        "center.x [m]", "center.y [m]", "center.z [m]", "roll [deg]", "pitch [deg]", "yaw [deg]",
    }
    rows: list[dict[str, Any]] = []
    with Path(csv_item["path"]).open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream, delimiter=";")
        if not reader.fieldnames or not required_columns.issubset(reader.fieldnames):
            raise ObserverV9BindingError("F6 FloatingInfo CSV header lacks required pose/velocity columns")
        for row_number, row in enumerate(reader):
            def number(column: str) -> float:
                raw = row.get(column)
                try:
                    parsed = float(raw)
                except (TypeError, ValueError) as error:
                    raise ObserverV9BindingError(
                        f"FloatingInfo row {row_number} {column} is not numeric") from error
                return _finite(parsed, f"FloatingInfo row {row_number} {column}")
            rows.append({
                "part": int(number("part")),
                "time_s": number("time [s]"),
                "linear_velocity_m_s": [number(f"fvel.{axis} [m/s]") for axis in "xyz"],
                "angular_velocity_rad_s": [number(f"fomega.{axis} [rad/s]") for axis in "xyz"],
                "center_m": [number(f"center.{axis} [m]") for axis in "xyz"],
                "euler_degrees": [number(f"{axis} [deg]") for axis in ("roll", "pitch", "yaw")],
            })
    expected_rows = int(report.get("parse", {}).get("rows_examined", len(rows)))
    if len(rows) != expected_rows or len(rows) != int(validated.get("expected_frames", expected_rows)):
        raise ObserverV9BindingError("F6 FloatingInfo row count differs from frozen report/profile")
    times = np.asarray([row["time_s"] for row in rows], dtype="float64")
    if np.any(np.diff(times) <= 0) or [row["part"] for row in rows] != list(range(len(rows))):
        raise ObserverV9BindingError("F6 FloatingInfo rows are not in official chronological order")
    initial_angular_velocity = validated.get("initial_angular_velocity_rad_s")
    initial_tolerance = _finite(validated.get("initial_angular_velocity_tolerance_rad_s", 1e-7),
                                "initial_angular_velocity_tolerance_rad_s")
    if initial_angular_velocity is not None and not np.allclose(rows[0]["angular_velocity_rad_s"],
                                                                  np.asarray(initial_angular_velocity, dtype="float64"),
                                                                  rtol=0.0, atol=initial_tolerance):
        raise ObserverV9BindingError("F6 initial angular velocity differs from the bound XML/CURRENT value")
    return {"schema": F6_TELEMETRY_SCHEMA,
            "physical_case_id": validated["physical_case_id"],
            "source_hashes": {role: item["sha256"] for role, item in sources.items()},
            "source_files": verified,
            "frames": len(rows),
            "time_window_s": [float(times[0]), float(times[-1])],
            "first": rows[0],
            "last": rows[-1],
            "mass_semantics": semantics,
            "family_binding": {"CURRENT_family": "F6", "report_family_id": case.get("family_id"),
                               "report_assigned_family": assigned_family,
                               "status": "REVIEW_REQUIRED_ASSIGNED_FAMILY_DIFFERS" if assigned_family not in (None, "F6") else "CONSISTENT"},
            "pose_velocity_status": "SOURCE_BOUND_OBSERVATION_ONLY",
            "force_pose_credit": "UNKNOWN",
            "rigid_force_credit": "UNKNOWN",
            "trajectory_hdf5_read": False,
            "quality": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
            "qualification_status": "UNKNOWN",
            "model_invoked": False}
