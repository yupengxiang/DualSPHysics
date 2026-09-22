#!/usr/bin/env python3
"""Causal, closed-lifecycle material observations for the F7 Pump hypothesis.

The observer consumes one trajectory HDF5 and an explicit body-frame region
contract.  It keeps every initial fluid particle in the denominator, detects
unknown exits instead of renormalizing survivors, uses conservative linear
segment crossings for unsaved passages, and reports pump-control correlations
as descriptive evidence only.  It never writes an HDF5 file or changes any
Core registry, ledger, matrix, or denominator.
"""

from __future__ import annotations

import hashlib
import json
import math
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from scripts.passive_tracers import validate_rigid_transform


SCHEMA = "core.f7.pump.transport_observer.v1"
CONTROL_SIDECAR_SCHEMA = "core.f7.pump.causal_sidecar.v1"
IDENTITY = "particle_zone,particle_id"
BODY_FRAME_SEMANTICS = "world_from_body"
ANGULAR_CONTROL_SEMANTICS = "pump_body_angular_velocity_rad_s_world_frame"
TORQUE_SEMANTICS = "pump_body_external_torque_n_m_world_frame"


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_array(value: np.ndarray) -> str:
    array = np.ascontiguousarray(np.asarray(value))
    digest = hashlib.sha256()
    digest.update(str(array.dtype).encode("ascii"))
    digest.update(repr(tuple(array.shape)).encode("ascii"))
    digest.update(array.tobytes())
    return digest.hexdigest()


def _vector(region: dict[str, Any], key: str) -> np.ndarray:
    value = np.asarray(region.get(key), dtype=np.float64)
    if value.shape != (3,) or not np.isfinite(value).all():
        raise ValueError(f"region {key} must be a finite three-vector")
    return value


def validate_region(region: dict[str, Any], *, role: str) -> None:
    if not isinstance(region, dict) or not isinstance(region.get("name"), str):
        raise ValueError(f"{role} must have a name")
    kind = region.get("type")
    if kind == "aabb":
        lower, upper = _vector(region, "min"), _vector(region, "max")
        if np.any(upper < lower):
            raise ValueError(f"{role} max must be >= min")
    elif kind == "halfspace":
        normal = _vector(region, "normal")
        if np.linalg.norm(normal) <= 0:
            raise ValueError(f"{role} normal must be nonzero")
        offset = region.get("offset")
        if not isinstance(offset, (int, float)) or not math.isfinite(float(offset)):
            raise ValueError(f"{role} offset must be finite")
        if region.get("side") not in {"le", "ge"}:
            raise ValueError(f"{role} side must be le or ge")
    elif kind == "sphere":
        _vector(region, "center")
        radius = region.get("radius")
        if not isinstance(radius, (int, float)) or not math.isfinite(float(radius)) or float(radius) <= 0:
            raise ValueError(f"{role} radius must be positive and finite")
    else:
        raise ValueError(f"{role} has unsupported region type {kind!r}")


def _region_mask(points: np.ndarray, region: dict[str, Any]) -> np.ndarray:
    points = np.asarray(points, dtype=np.float64)
    kind = region["type"]
    if kind == "aabb":
        return np.all((points >= _vector(region, "min")) & (points <= _vector(region, "max")), axis=-1)
    if kind == "halfspace":
        signed = np.einsum("...i,i->...", points, _vector(region, "normal")) - float(region["offset"])
        return signed <= 0 if region["side"] == "le" else signed >= 0
    return np.linalg.norm(points - _vector(region, "center"), axis=-1) <= float(region["radius"])


def _segment_region_intersection(start: np.ndarray, end: np.ndarray, region: dict[str, Any]) -> np.ndarray:
    """Conservatively detect a straight-line passage through a body-frame region."""
    start = np.asarray(start, dtype=np.float64)
    end = np.asarray(end, dtype=np.float64)
    kind = region["type"]
    if kind == "aabb":
        direction = end - start
        lower, upper = _vector(region, "min"), _vector(region, "max")
        t_min = np.zeros(start.shape[:-1], dtype=np.float64)
        t_max = np.ones(start.shape[:-1], dtype=np.float64)
        for axis in range(3):
            parallel = np.abs(direction[..., axis]) <= 1e-15
            outside = parallel & ((start[..., axis] < lower[axis]) | (start[..., axis] > upper[axis]))
            inv = np.divide(1.0, direction[..., axis], out=np.zeros_like(direction[..., axis]), where=~parallel)
            near = (lower[axis] - start[..., axis]) * inv
            far = (upper[axis] - start[..., axis]) * inv
            axis_min, axis_max = np.minimum(near, far), np.maximum(near, far)
            t_min = np.maximum(t_min, np.where(parallel, 0.0, axis_min))
            t_max = np.minimum(t_max, np.where(parallel, 1.0, axis_max))
            t_max[outside] = -1.0
        return t_max >= t_min
    if kind == "halfspace":
        signed_start = np.einsum("...i,i->...", start, _vector(region, "normal")) - float(region["offset"])
        signed_end = np.einsum("...i,i->...", end, _vector(region, "normal")) - float(region["offset"])
        if region["side"] == "le":
            return (signed_start <= 0) | (signed_end <= 0) | ((signed_start < 0) != (signed_end < 0))
        return (signed_start >= 0) | (signed_end >= 0) | ((signed_start > 0) != (signed_end > 0))
    centre = _vector(region, "center")
    radius = float(region["radius"])
    offset = start - centre
    direction = end - start
    a = np.sum(direction * direction, axis=-1)
    b = 2.0 * np.sum(offset * direction, axis=-1)
    c = np.sum(offset * offset, axis=-1) - radius * radius
    discriminant = b * b - 4.0 * a * c
    intersects = c <= 0
    moving = a > 1e-30
    root = np.sqrt(np.maximum(discriminant, 0.0))
    first = np.divide(-b - root, 2.0 * a, out=np.full_like(a, np.inf), where=moving)
    last = np.divide(-b + root, 2.0 * a, out=np.full_like(a, -np.inf), where=moving)
    return intersects | (moving & (discriminant >= 0) & (last >= 0) & (first <= 1))


def _validate_spec(spec: dict[str, Any]) -> None:
    if not isinstance(spec, dict) or spec.get("schema") != SCHEMA:
        raise ValueError(f"spec schema must be {SCHEMA}")
    if spec.get("lifecycle_model") != "closed":
        raise ValueError("F7 observer only accepts the closed lifecycle")
    if spec.get("source_mode") != "all_initial_fluid":
        raise ValueError("F7 denominator must be all_initial_fluid")
    for key in ("intake_region", "discharge_region", "return_region", "residence_region"):
        validate_region(spec.get(key), role=key)
    frame_dataset = spec.get("body_frame_dataset")
    control_dataset = spec.get("angular_control_dataset")
    if not isinstance(frame_dataset, str) or not frame_dataset:
        raise ValueError("body_frame_dataset is required")
    if not isinstance(control_dataset, str) or not control_dataset:
        raise ValueError("angular_control_dataset is required")
    if spec.get("body_frame_semantics") != BODY_FRAME_SEMANTICS:
        raise ValueError("body_frame_semantics must declare world_from_body")
    if spec.get("angular_control_semantics") != ANGULAR_CONTROL_SEMANTICS:
        raise ValueError("angular_control_semantics must declare world-frame pump angular velocity")
    if spec.get("body_frame_time_dataset") != "time" or spec.get("angular_control_time_dataset") != "time":
        raise ValueError("body frame and angular control must use the trajectory time dataset")
    if spec.get("identity_semantics") != "fixed_particle_columns":
        raise ValueError("identity_semantics must declare fixed particle columns")
    for key in ("particle_id_frame_dataset", "particle_zone_frame_dataset"):
        if not isinstance(spec.get(key), str) or not spec[key]:
            raise ValueError(f"{key} is required for cross-frame identity binding")
    for key in ("trajectory_sha256", "body_frame_sha256", "angular_control_sha256"):
        value = spec.get(key)
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdefABCDEF" for c in value):
            raise ValueError(f"{key} must be a SHA-256 binding")
    regions = {key: spec[key] for key in ("intake_region", "discharge_region", "return_region", "residence_region")}
    region_hash = spec.get("region_contract_sha256")
    if not isinstance(region_hash, str) or len(region_hash) != 64 or region_hash.lower() != canonical_hash(regions).lower():
        raise ValueError("region_contract_sha256 does not match the declared regions")
    window = spec.get("event_window_s")
    if not isinstance(window, (list, tuple)) or len(window) != 2:
        raise ValueError("event_window_s must be [start,end]")
    start, end = float(window[0]), float(window[1])
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
        raise ValueError("event_window_s must be finite and increasing")
    bound = spec.get("unknown_exit_max_fraction", 0.0)
    if not isinstance(bound, (int, float)) or not math.isfinite(float(bound)) or not 0 <= float(bound) <= 1:
        raise ValueError("unknown_exit_max_fraction must be finite in [0,1]")
    torque_dataset = spec.get("torque_dataset")
    if torque_dataset:
        for key in ("torque_sha256", "torque_time_sha256"):
            value = spec.get(key)
            if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdefABCDEF" for c in value):
                raise ValueError(f"{key} must be a SHA-256 binding when torque is declared")
        if spec.get("torque_time_dataset") != "time":
            raise ValueError("torque must use the trajectory time dataset")
        if spec.get("torque_units") != "N m":
            raise ValueError("torque_units must be N m")
        if spec.get("torque_body_id") != 2:
            raise ValueError("torque_body_id must identify Pump moving body 2")
        if spec.get("torque_semantics") != TORQUE_SEMANTICS:
            raise ValueError("torque_semantics must identify the Pump body external torque")


def _blocked(status: str, reason: str, *, bindings: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": status,
        "reason": reason,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "bindings": {} if bindings is None else bindings,
        "execution_controls": {
            "trajectory_written": False,
            "central_registry_mutation": 0,
            "central_ledger_mutation": 0,
            "central_matrix_mutation": 0,
            "solver_invoked": False,
            "gpu_started": False,
            "queue_mutation": 0,
        },
    }


def _world_to_body(positions: np.ndarray, transforms: np.ndarray) -> np.ndarray:
    positions = np.asarray(positions, dtype=np.float64)
    transforms = np.asarray(transforms, dtype=np.float64)
    result = np.empty_like(positions)
    for frame, transform in enumerate(transforms):
        validated = validate_rigid_transform(transform)
        rotation = validated[:3, :3]
        translation = validated[:3, 3]
        result[frame] = (positions[frame] - translation) @ rotation
    return result


def _first_index(mask: np.ndarray) -> np.ndarray:
    result = np.full(mask.shape[1], -1, dtype=np.int64)
    for index in range(mask.shape[1]):
        found = np.flatnonzero(mask[:, index])
        if len(found):
            result[index] = int(found[0])
    return result


def _correlation(left: np.ndarray, right: np.ndarray) -> float | None:
    left, right = np.asarray(left, dtype=float), np.asarray(right, dtype=float)
    if len(left) < 2 or np.std(left) <= 0 or np.std(right) <= 0:
        return None
    return float(np.corrcoef(left, right)[0, 1])


def audit_pump_transport(
    h5_path: Path,
    spec: dict[str, Any],
    *,
    control_sidecar_path: Path | None = None,
) -> dict[str, Any]:
    """Audit all initial fluid mass against causal pump-frame events.

    A companion control sidecar is accepted only when it binds byte-for-byte
    to this trajectory and its exact time axis.  It contributes prescribed
    kinematic controls only; it cannot contribute torque or runtime provenance.
    """
    try:
        _validate_spec(spec)
    except (TypeError, ValueError) as error:
        return _blocked("blocked_invalid_spec", str(error))

    h5_path = Path(h5_path)
    try:
        observed_trajectory_hash = sha256_file(h5_path)
    except OSError as error:
        return _blocked("blocked_unreadable_trajectory", str(error))
    if observed_trajectory_hash.lower() != spec["trajectory_sha256"].lower():
        return _blocked(
            "blocked_trajectory_hash_mismatch",
            "trajectory bytes do not match the declared source binding",
            bindings={"observed_trajectory_sha256": observed_trajectory_hash},
        )

    control_sidecar_binding: dict[str, Any] | None = None
    try:
        with h5py.File(h5_path, "r") as h5, ExitStack() as resources:
            required = {"time", "position", "valid", "type", "mass", "particle_id", "particle_zone"}
            missing = sorted(required - set(h5.keys()))
            if missing:
                return _blocked("blocked_missing_native_fields", f"missing fields: {missing}")
            times = np.asarray(h5["time"][:], dtype=np.float64)
            positions = np.asarray(h5["position"][:], dtype=np.float64)
            valid_raw = np.asarray(h5["valid"][:])
            if valid_raw.dtype.kind not in "biu" or not np.isin(valid_raw, [0, 1]).all():
                return _blocked("blocked_invalid_valid_dtype", "valid must be a boolean or binary integer dataset")
            valid = np.asarray(valid_raw, dtype=bool)
            particle_type = np.asarray(h5["type"][:])
            mass = np.asarray(h5["mass"][:], dtype=np.float64)
            particle_id = np.asarray(h5["particle_id"][:])
            particle_zone = np.asarray(h5["particle_zone"][:])
            particle_id_frame_dataset = spec["particle_id_frame_dataset"]
            particle_zone_frame_dataset = spec["particle_zone_frame_dataset"]
            if particle_id_frame_dataset not in h5 or particle_zone_frame_dataset not in h5:
                return _blocked("blocked_missing_identity_history", "cross-frame particle identity datasets are required")
            particle_id_by_frame = np.asarray(h5[particle_id_frame_dataset][:])
            particle_zone_by_frame = np.asarray(h5[particle_zone_frame_dataset][:])
            frame_dataset = spec["body_frame_dataset"]
            control_dataset = spec["angular_control_dataset"]
            control_h5 = h5
            if control_sidecar_path is not None:
                try:
                    sidecar_path = Path(control_sidecar_path)
                    control_h5 = resources.enter_context(h5py.File(sidecar_path, "r"))
                except OSError as error:
                    return _blocked("blocked_unreadable_control_sidecar", str(error))
                try:
                    if control_h5.attrs.get("f7_causal_sidecar_schema") != CONTROL_SIDECAR_SCHEMA:
                        return _blocked("blocked_invalid_control_sidecar", "control sidecar schema is unsupported")
                    if control_h5.attrs.get("f7_source_trajectory_sha256", "").lower() != observed_trajectory_hash.lower():
                        return _blocked("blocked_control_sidecar_trajectory_mismatch", "control sidecar is bound to a different trajectory")
                    if "time" not in control_h5:
                        return _blocked("blocked_control_sidecar_missing_time", "control sidecar has no /time dataset")
                    sidecar_times = np.asarray(control_h5["time"][:], dtype=np.float64)
                    if not np.array_equal(sidecar_times, times):
                        return _blocked("blocked_control_sidecar_time_mismatch", "control sidecar time differs from trajectory time")
                    if control_h5.attrs.get("f7_control_time_sha256", "").lower() != sha256_array(times).lower():
                        return _blocked("blocked_control_sidecar_time_hash_mismatch", "control sidecar time hash is invalid")
                    if bool(control_h5.attrs.get("f7_torque_dataset_present", True)):
                        return _blocked("blocked_control_sidecar_torque_claim", "control sidecar must not claim a torque dataset")
                    control_sidecar_binding = {
                        "path": str(sidecar_path),
                        "sha256": sha256_file(sidecar_path),
                        "trajectory_sha256": observed_trajectory_hash,
                        "time_sha256": sha256_array(times),
                        "schema": CONTROL_SIDECAR_SCHEMA,
                        "runtime_evidence": False,
                    }
                except (KeyError, TypeError, ValueError) as error:
                    return _blocked("blocked_invalid_control_sidecar", str(error))
            if frame_dataset not in control_h5 or control_dataset not in control_h5:
                return _blocked(
                    "blocked_missing_causal_control",
                    "body pose and angular control datasets are required; future motion cannot be inferred",
                )
            transforms = np.asarray(control_h5[frame_dataset][:], dtype=np.float64)
            angular = np.asarray(control_h5[control_dataset][:], dtype=np.float64)
            torque_dataset = spec.get("torque_dataset")
            torque = None if not torque_dataset or torque_dataset not in h5 else np.asarray(h5[torque_dataset][:], dtype=np.float64)
            if torque_dataset and torque_dataset not in h5:
                return _blocked("blocked_missing_torque", "declared Pump torque dataset is missing")
    except OSError as error:
        return _blocked("blocked_unreadable_trajectory", str(error))

    if times.ndim != 1 or len(times) < 2 or not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
        return _blocked("blocked_invalid_time_axis", "trajectory time must be finite, increasing, and have at least two frames")
    if positions.ndim != 3 or positions.shape[-1] != 3 or positions.shape[0] != len(times):
        return _blocked("blocked_invalid_position_axis", "position must have shape [T,N,3]")
    frame_count, particle_count = positions.shape[:2]
    if valid.shape != (frame_count, particle_count):
        return _blocked("blocked_invalid_valid_axis", "valid must have shape [T,N]")
    if particle_type.shape == (particle_count,):
        particle_type = np.broadcast_to(particle_type[None, :], (frame_count, particle_count))
    if particle_type.shape != (frame_count, particle_count):
        return _blocked("blocked_invalid_type_axis", "type must have shape [T,N] or [N]")
    if mass.shape == (frame_count, particle_count):
        initial_mass = mass[0]
    elif mass.shape == (particle_count,):
        initial_mass = mass
    else:
        return _blocked("blocked_invalid_mass_axis", "mass must have shape [N] or [T,N]")
    if particle_id.shape != (particle_count,) or particle_zone.shape != (particle_count,):
        return _blocked("blocked_invalid_identity_axis", "particle identities must have shape [N]")
    if particle_id.dtype.kind not in "iu" or particle_zone.dtype.kind not in "iu":
        return _blocked("blocked_noninteger_identity", "particle identities must be integer arrays")
    identity = np.column_stack((particle_zone, particle_id))
    if len(np.unique(identity, axis=0)) != particle_count:
        return _blocked("blocked_duplicate_identity", f"{IDENTITY} is not unique")
    if (particle_id_by_frame.shape != (frame_count, particle_count)
            or particle_zone_by_frame.shape != (frame_count, particle_count)):
        return _blocked("blocked_invalid_identity_history", "cross-frame identity datasets must have shape [T,N]")
    if particle_id_by_frame.dtype.kind not in "iu" or particle_zone_by_frame.dtype.kind not in "iu":
        return _blocked("blocked_noninteger_identity_history", "cross-frame identities must be integer arrays")
    if (not np.array_equal(particle_id_by_frame, np.broadcast_to(particle_id[None, :], particle_id_by_frame.shape))
            or not np.array_equal(particle_zone_by_frame, np.broadcast_to(particle_zone[None, :], particle_zone_by_frame.shape))):
        return _blocked("blocked_identity_reordering", "particle row identity changes across trajectory frames")
    if transforms.shape != (frame_count, 4, 4) or not np.isfinite(transforms).all():
        return _blocked("blocked_invalid_body_frame", "body frame must have shape [T,4,4] and finite values")
    if angular.shape != (frame_count, 3) or not np.isfinite(angular).all():
        return _blocked("blocked_invalid_angular_control", "angular control must have shape [T,3] and finite values")
    try:
        for transform in transforms:
            validate_rigid_transform(transform)
    except ValueError as error:
        return _blocked("blocked_nonrigid_body_frame", str(error))
    frame_hash = sha256_array(transforms)
    control_hash = sha256_array(angular)
    if frame_hash.lower() != spec["body_frame_sha256"].lower():
        return _blocked("blocked_body_frame_hash_mismatch", "body pose dataset hash mismatch")
    if control_hash.lower() != spec["angular_control_sha256"].lower():
        return _blocked("blocked_angular_control_hash_mismatch", "angular control dataset hash mismatch")
    torque_hash = None
    torque_time_hash = None
    if spec.get("torque_dataset"):
        if torque is None or torque.shape != (frame_count, 3) or not np.isfinite(torque).all():
            return _blocked("blocked_invalid_torque", "declared torque must have shape [T,3] and finite values")
        torque_hash = sha256_array(torque)
        torque_time_hash = sha256_array(times)
        if torque_hash.lower() != spec["torque_sha256"].lower():
            return _blocked("blocked_torque_hash_mismatch", "torque dataset hash mismatch")
        if torque_time_hash.lower() != spec["torque_time_sha256"].lower():
            return _blocked("blocked_torque_time_hash_mismatch", "torque time binding mismatch")
    start_s, end_s = map(float, spec["event_window_s"])
    if times[0] > start_s + 1e-12 or times[-1] < end_s - 1e-12:
        return _blocked("blocked_event_window_incomplete", "actual trajectory does not bracket the declared event window")
    in_window = (times >= start_s - 1e-12) & (times <= end_s + 1e-12)
    active = valid & np.isfinite(positions).all(axis=2)
    if np.any(valid & ~np.isfinite(positions).all(axis=2)):
        return _blocked(
            "blocked_nonfinite_valid_position",
            "valid particles must have finite positions; ambiguous observations are not unobserved mass",
        )
    if not np.isfinite(initial_mass).all() or np.any(initial_mass <= 0):
        return _blocked("blocked_nonfinite_initial_mass", "initial particle masses must be finite and positive")
    if not np.array_equal(valid[0], active[0]):
        return _blocked("blocked_nonfinite_initial_state", "initial active positions are not finite")

    try:
        body_positions = _world_to_body(positions, transforms)
    except ValueError as error:
        return _blocked("blocked_invalid_body_pose", str(error))

    initial_fluid = particle_type[0] == 3
    source_indices = np.flatnonzero(initial_fluid)
    if not len(source_indices):
        return _blocked("blocked_empty_initial_fluid", "trajectory has no initial fluid particles")
    source_mass = initial_mass[source_indices]
    denominator = float(np.sum(source_mass))
    regions = {
        name: spec[f"{name}_region"]
        for name in ("intake", "discharge", "return", "residence")
    }
    for name, region in regions.items():
        validate_region(region, role=name)
    source_body_positions = body_positions[:, source_indices]
    source_valid = active[:, source_indices]
    invalid = ~source_valid
    invalid_frame = _first_index(invalid)
    frame_indices = np.arange(frame_count, dtype=np.int64)[:, None]
    observed = source_valid & in_window[:, None] & ((invalid_frame[None, :] < 0) | (frame_indices < invalid_frame[None, :]))
    sampled_masks = {
        name: _region_mask(source_body_positions, region) & observed
        for name, region in regions.items()
    }
    event_masks: dict[str, np.ndarray] = {}
    for name, region in regions.items():
        crossing = _segment_region_intersection(
            source_body_positions[:-1], source_body_positions[1:], region
        ) & observed[:-1] & observed[1:]
        event_mask = sampled_masks[name].copy()
        event_mask[1:] |= crossing
        event_masks[name] = event_mask
    masks = event_masks
    discharge_frame = _first_index(masks["discharge"])
    return_frame = np.full(len(source_indices), -1, dtype=np.int64)
    for index, first_discharge in enumerate(discharge_frame):
        if first_discharge >= 0:
            found = np.flatnonzero(masks["return"][first_discharge + 1:, index])
            if len(found):
                return_frame[index] = int(first_discharge + 1 + found[0])
    residence_time = np.zeros(len(source_indices), dtype=np.float64)
    interval_dt = np.diff(times)
    residence_intervals = (
        sampled_masks["residence"][:-1]
        & sampled_masks["residence"][1:]
        & source_valid[:-1]
        & source_valid[1:]
        & in_window[:-1, None]
        & in_window[1:, None]
    )
    residence_time += np.sum(residence_intervals * interval_dt[:, None], axis=0)
    categories = np.full(len(source_indices), "observed_without_target", dtype=object)
    categories[discharge_frame >= 0] = "discharged"
    categories[return_frame >= 0] = "returned"
    categories[invalid_frame >= 0] = "unknown_exit"
    category_mass = {
        name: float(np.sum(source_mass[categories == name]))
        for name in ("returned", "discharged", "observed_without_target", "unknown_exit")
    }
    residence_event_mass = float(np.sum(source_mass[np.any(masks["residence"], axis=0)]))
    closure_error = float(sum(category_mass.values()) - denominator)
    first_discharge_mass = np.zeros(frame_count, dtype=np.float64)
    for index, frame in enumerate(discharge_frame):
        if frame >= 0:
            first_discharge_mass[frame] += source_mass[index]
    angular_speed = np.linalg.norm(angular, axis=1)
    unknown_fraction = category_mass["unknown_exit"] / max(denominator, 1e-30)
    intake_initial_mask = _region_mask(source_body_positions[0], regions["intake"]) & source_valid[0]
    intake_initial_count = int(np.count_nonzero(intake_initial_mask))
    torque_present = torque is not None and torque.shape == (frame_count, 3) and np.isfinite(torque).all()
    torque_nonzero = bool(torque_present and np.any(np.linalg.norm(torque, axis=1) > 1e-12))
    unknown_exit_bound_pass = unknown_fraction <= float(spec.get("unknown_exit_max_fraction", 0.0)) + 1e-12
    pump_gate = {
        "angular_control_nonzero": bool(np.any(angular_speed > 1e-12)),
        "intake_initial_observed": bool(intake_initial_count > 0),
        "intake_initial_count": intake_initial_count,
        "discharge_first_passage_observed": bool(np.any(discharge_frame > 0)),
        "return_passage_observed": bool(np.any(return_frame >= 0)),
        "torque_dataset_present_and_finite": bool(torque_present),
        "torque_dataset_hash_bound": bool(torque_hash is not None),
        "torque_time_axis_hash_bound": bool(torque_time_hash is not None),
        "torque_nonzero": torque_nonzero,
        "torque_provenance_verified": False,
        "unknown_exit_bound_pass": unknown_exit_bound_pass,
        "physical_independence_contract_satisfied": bool(
            np.any(angular_speed > 1e-12)
            and intake_initial_count > 0
            and np.any(discharge_frame > 0)
            and np.any(return_frame >= 0)
            and torque_present
            and torque_nonzero
            and unknown_exit_bound_pass
        ),
        "physical_independence_proven": False,
        "interpretation": "descriptive causal-input contract only; root review must verify torque provenance and family independence",
    }
    return {
        "schema": SCHEMA,
        "status": "observer_complete_but_root_gate_blocked" if not pump_gate["physical_independence_contract_satisfied"] else "observer_contract_pass_pending_root_review",
        "case_id": str(h5_path),
        "identity_key": IDENTITY,
        "lifecycle_model": "closed",
        "region_contract_sha256": spec["region_contract_sha256"],
        "region_manifest_provenance_verified": False,
        "event_window_s": [start_s, end_s],
        "actual_time_axis_s": [float(times[0]), float(times[-1])],
        "source_denominator": {
            "mode": "all_initial_fluid",
            "initial_fluid_count": int(len(source_indices)),
            "initial_fluid_mass_kg": denominator,
            "survivor_renormalization": False,
        },
        "intake": {
            "region": regions["intake"],
            "initial_count": intake_initial_count,
            "initial_mass_kg": float(np.sum(source_mass[intake_initial_mask])),
        },
        "classification": {
            "mass_kg": category_mass,
            "mass_fraction": {key: value / max(denominator, 1e-30) for key, value in category_mass.items()},
            "closure_error_kg": closure_error,
            "first_discharge_frame_count": int(np.count_nonzero(discharge_frame >= 0)),
            "first_return_frame_count": int(np.count_nonzero(return_frame >= 0)),
            "unknown_exit_count": int(np.count_nonzero(invalid_frame >= 0)),
            "unknown_exit_fraction": unknown_fraction,
            "unknown_exit_bound": float(spec.get("unknown_exit_max_fraction", 0.0)),
            "unknown_exit_bound_pass": unknown_exit_bound_pass,
            "residence_event_mass_kg": residence_event_mass,
            "residence_event_count": int(np.count_nonzero(np.any(masks["residence"], axis=0))),
            "linear_segment_crossing_detection": True,
            "residence_time_mass_weighted_s": float(np.sum(residence_time * source_mass) / max(denominator, 1e-30)),
        },
        "pump_control_observation": {
            "angular_control_dataset": spec["angular_control_dataset"],
            "angular_control_sha256": control_hash,
            "angular_control_semantics": spec["angular_control_semantics"],
            "angular_control_time_dataset": spec["angular_control_time_dataset"],
            "trajectory_time_sha256": sha256_array(times),
            "angular_speed_rad_s_min": float(np.min(angular_speed)),
            "angular_speed_rad_s_max": float(np.max(angular_speed)),
            "first_discharge_mass_by_frame_kg": first_discharge_mass.tolist(),
            "angular_speed_discharge_mass_correlation": _correlation(angular_speed, first_discharge_mass),
            "torque_dataset": spec.get("torque_dataset"),
            "torque_sha256": torque_hash,
            "torque_time_sha256": torque_time_hash,
            "torque_semantics": spec.get("torque_semantics"),
            "torque_units": spec.get("torque_units"),
            "torque_body_id": spec.get("torque_body_id"),
            "torque_provenance_verified": False,
            "gate": pump_gate,
            "correlation_is_causal_claim": False,
        },
        "body_frame_binding": {
            "dataset": spec["body_frame_dataset"],
            "sha256": frame_hash,
            "time_dataset": spec["body_frame_time_dataset"],
            "time_sha256": sha256_array(times),
            "semantics": spec["body_frame_semantics"],
            "inverse_used_for_body_frame_regions": True,
            "source_manifest_provenance_verified": False,
        },
        "trajectory_binding": {
            "path": str(h5_path),
            "sha256": observed_trajectory_hash,
            "time_sha256": sha256_array(times),
        },
        "control_sidecar_binding": control_sidecar_binding,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "execution_controls": {
            "trajectory_written": False,
            "central_registry_mutation": 0,
            "central_ledger_mutation": 0,
            "central_matrix_mutation": 0,
            "solver_invoked": False,
            "gpu_started": False,
            "queue_mutation": 0,
        },
    }
