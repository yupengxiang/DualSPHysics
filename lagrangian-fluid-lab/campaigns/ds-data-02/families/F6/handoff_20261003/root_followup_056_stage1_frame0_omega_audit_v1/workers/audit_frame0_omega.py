#!/usr/bin/env python3
"""Bounded Type-2 frame-zero angular propagation audit.

The worker is deliberately narrow.  It discovers the named fields in an existing
typed trajectory, then slices only the requested particle interval for frame zero
and a small preview.  It never materialises a complete native frame, reads a fixed
or fluid range, or writes particle arrays.  Root strict dispatch must enable the
request before this file is executed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    import h5py  # type: ignore
    import numpy as np  # type: ignore
except Exception as exc:  # pragma: no cover - exercised by a dispatch environment
    h5py = None  # type: ignore
    np = None  # type: ignore
    _IMPORT_ERROR = repr(exc)
else:
    _IMPORT_ERROR = None


SCHEMA = "ds02.f6.frame0-omega-audit-result.v1"
DEFAULT_CENTER = (2.4, 1.2, 1.08)
DEFAULT_OMEGA = (0.08, 0.12, 0.06)
DEFAULT_PARTICLE_START = 73441
DEFAULT_PARTICLE_COUNT = 16384
DEFAULT_PREVIEW_FRAMES = 4
DEFAULT_ZERO_TOLERANCE = 1.0e-12


class AuditError(RuntimeError):
    """A bounded input or interpretation failure."""


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


ROLE_ALIASES: Mapping[str, Tuple[str, ...]] = {
    "position": ("position", "positions", "pos", "xyz", "coordinates"),
    "velocity": ("velocity", "velocities", "vel", "v"),
    "valid": ("valid", "isvalid", "active", "present", "alive"),
    "particle_id": (
        "particleid",
        "particleids",
        "idp",
        "uid",
        "particleuid",
        "particleindex",
        "index",
        "id",
    ),
    "particle_zone": (
        "particlezone",
        "zone",
        "mk",
        "mkfluid",
        "marker",
        "material",
    ),
    "type": ("type", "particletype", "ptype"),
    "time": ("time", "times", "t", "timestamp"),
}


def _dataset_basename(path: str) -> str:
    return _normalise(path.rsplit("/", 1)[-1])


def _discover_datasets(handle: Any) -> Dict[str, Any]:
    """Discover metadata only; no dataset values are read here."""

    candidates: Dict[str, List[Tuple[int, str, Any]]] = {
        role: [] for role in ROLE_ALIASES
    }

    def visit(name: str, obj: Any) -> None:
        if h5py is None or not isinstance(obj, h5py.Dataset):
            return
        base = _dataset_basename(name)
        for role, aliases in ROLE_ALIASES.items():
            if base in aliases:
                # Exact basename aliases are preferred.  A shorter path is a
                # deterministic tie-breaker and does not inspect values.
                rank = aliases.index(base)
                candidates[role].append((rank, name, obj))

    handle.visititems(visit)
    selected: Dict[str, Any] = {}
    for role, values in candidates.items():
        if values:
            values.sort(key=lambda item: (item[0], item[1].count("/"), item[1]))
            selected[role] = values[0][2]
    return selected


def _shape(dataset: Any) -> Tuple[int, ...]:
    return tuple(int(item) for item in dataset.shape)


def _read_vector(dataset: Any, frame: int, start: int, count: int, role: str) -> Any:
    shape = _shape(dataset)
    if len(shape) == 3 and shape[-1] == 3:
        if frame >= shape[0]:
            raise AuditError(f"{role} has no frame {frame}; shape={shape}")
        return np.asarray(dataset[frame, start : start + count, :], dtype=np.float64)
    if len(shape) == 2 and shape[-1] == 3:
        return np.asarray(dataset[start : start + count, :], dtype=np.float64)
    if len(shape) == 2 and shape[0] == 3:
        return np.asarray(dataset[:, start : start + count], dtype=np.float64).T
    raise AuditError(
        f"{role} must have [frame,particle,3] or [particle,3] shape; got {shape}"
    )


def _read_scalar(
    dataset: Any,
    frame: int,
    start: int,
    count: int,
    role: str,
    dtype: Any = None,
) -> Any:
    if dtype is None:
        dtype = np.float64
    shape = _shape(dataset)
    if len(shape) == 2:
        if frame >= shape[0]:
            raise AuditError(f"{role} has no frame {frame}; shape={shape}")
        return np.asarray(dataset[frame, start : start + count], dtype=dtype)
    if len(shape) == 1:
        return np.asarray(dataset[start : start + count], dtype=dtype)
    if len(shape) == 3 and shape[-1] == 1:
        if frame >= shape[0]:
            raise AuditError(f"{role} has no frame {frame}; shape={shape}")
        return np.asarray(dataset[frame, start : start + count, 0], dtype=dtype)
    raise AuditError(
        f"{role} must have [frame,particle] or [particle] shape; got {shape}"
    )


def _read_time(dataset: Optional[Any], max_frames: int) -> Optional[List[float]]:
    if dataset is None:
        return None
    shape = _shape(dataset)
    if len(shape) == 1:
        n = min(int(shape[0]), max_frames)
        return [float(item) for item in np.asarray(dataset[:n], dtype=np.float64)]
    if len(shape) == 2 and shape[-1] == 1:
        n = min(int(shape[0]), max_frames)
        return [
            float(item)
            for item in np.asarray(dataset[:n, 0], dtype=np.float64)
        ]
    if len(shape) == 2 and shape[0] == 1:
        n = min(int(shape[1]), max_frames)
        return [
            float(item)
            for item in np.asarray(dataset[0, :n], dtype=np.float64)
        ]
    return None


def _finite_vector(values: Any) -> Any:
    return np.isfinite(values).all(axis=1)


def _safe_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _stats(values: Any, tolerance: float) -> Dict[str, Any]:
    values = np.asarray(values, dtype=np.float64)
    if values.size == 0:
        return {
            "count": 0,
            "min": None,
            "mean": None,
            "max": None,
            "nonzero_count": 0,
            "zero_tolerance_m_per_s": tolerance,
        }
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return {
            "count": 0,
            "min": None,
            "mean": None,
            "max": None,
            "nonzero_count": 0,
            "zero_tolerance_m_per_s": tolerance,
        }
    return {
        "count": int(finite.size),
        "min": float(np.min(finite)),
        "mean": float(np.mean(finite)),
        "max": float(np.max(finite)),
        "nonzero_count": int(np.count_nonzero(finite > tolerance)),
        "zero_tolerance_m_per_s": tolerance,
    }


def _skew(vector: Any) -> Any:
    x, y, z = [float(item) for item in vector]
    return np.asarray(((0.0, -z, y), (z, 0.0, -x), (-y, x, 0.0)))


def _fit_rigid(position: Any, velocity: Any, center: Sequence[float]) -> Dict[str, Any]:
    count = int(position.shape[0])
    if count < 2:
        return {
            "status": "insufficient_valid_points",
            "valid_count": count,
            "Vcm_m_per_s": None,
            "omega_rad_s": None,
            "rank": None,
            "singular_values": [],
            "residual_rms_m_per_s": None,
            "residual_max_m_per_s": None,
        }

    design = np.zeros((3 * count, 6), dtype=np.float64)
    rhs = np.asarray(velocity, dtype=np.float64).reshape(3 * count)
    relative = np.asarray(position, dtype=np.float64) - np.asarray(center, dtype=np.float64)
    identity = np.eye(3, dtype=np.float64)
    for index, point in enumerate(relative):
        row = 3 * index
        design[row : row + 3, :3] = identity
        # cross(omega, r) = -skew(r) @ omega.
        design[row : row + 3, 3:] = -_skew(point)

    solution, _, rank, singular_values = np.linalg.lstsq(design, rhs, rcond=None)
    predicted = (design @ solution).reshape(count, 3)
    residual = np.linalg.norm(np.asarray(velocity) - predicted, axis=1)
    omega = np.asarray(solution[3:6], dtype=np.float64)
    vcm = np.asarray(solution[:3], dtype=np.float64)
    return {
        "status": "ok" if int(rank) >= 6 else "rank_deficient",
        "valid_count": count,
        "Vcm_m_per_s": [float(item) for item in vcm],
        "omega_rad_s": [float(item) for item in omega],
        "rank": int(rank),
        "singular_values": [float(item) for item in singular_values],
        "residual_rms_m_per_s": float(np.sqrt(np.mean(residual * residual))),
        "residual_max_m_per_s": float(np.max(residual)),
    }


def _uid_summary(ids: Any) -> Dict[str, Any]:
    finite = np.isfinite(ids)
    integer_ids = np.asarray(ids[finite], dtype=np.int64)
    unique_count = int(np.unique(integer_ids).size)
    sample = [int(item) for item in integer_ids[:8]]
    tail = [int(item) for item in integer_ids[-8:]] if integer_ids.size else []
    digest = hashlib.sha256(integer_ids.tobytes()).hexdigest()
    return {
        "finite_count": int(integer_ids.size),
        "unique_count": unique_count,
        "duplicate_count": int(integer_ids.size - unique_count),
        "first_values": sample,
        "last_values": tail,
        "ordered_int64_sha256": digest,
    }


def _parse_float_from_row(row: Mapping[str, str], aliases: Iterable[str]) -> Optional[float]:
    normalised = {_normalise(str(key)): value for key, value in row.items()}
    for alias in aliases:
        key = _normalise(alias)
        if key in normalised:
            value = _safe_float(normalised[key])
            if value is not None:
                return value
    return None


def _floating_info_summary(path: Path, max_rows: int) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "path": str(path),
        "read_policy": "first bounded rows only; no full CSV materialisation",
        "max_rows": int(max_rows),
    }
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = list(reader.fieldnames or [])
            rows: List[Mapping[str, str]] = []
            for row_index, row in enumerate(reader):
                if row_index >= max_rows:
                    break
                rows.append(row)
    except OSError as exc:
        summary.update({"status": "unavailable", "error": str(exc)})
        return summary

    summary["headers"] = headers
    summary["rows_examined"] = len(rows)
    if not rows:
        summary["status"] = "empty_or_header_only"
        return summary

    time_aliases = ("time", "t", "times", "time_s", "timestamp")
    omega_aliases = (
        ("angvelx", "angularvelocityx", "omegax", "wx", "omega_x"),
        ("angvely", "angularvelocityy", "omegay", "wy", "omega_y"),
        ("angvelz", "angularvelocityz", "omegaz", "wz", "omega_z"),
    )
    velocity_aliases = (
        ("velx", "velocityx", "vx", "vcmx", "linearvelocityx"),
        ("vely", "velocityy", "vy", "vcmy", "linearvelocityy"),
        ("velz", "velocityz", "vz", "vcmz", "linearvelocityz"),
    )
    parsed_times = [
        _parse_float_from_row(row, time_aliases) for row in rows
    ]
    timed = [
        (index, value)
        for index, value in enumerate(parsed_times)
        if value is not None
    ]
    if timed:
        selected_index = min(timed, key=lambda pair: abs(pair[1]))[0]
        selection_reason = "closest parsed time to zero"
    else:
        selected_index = 0
        selection_reason = "first bounded row; no time column parsed"
    selected = rows[selected_index]
    omega = [
        _parse_float_from_row(selected, aliases) for aliases in omega_aliases
    ]
    linear_velocity = [
        _parse_float_from_row(selected, aliases) for aliases in velocity_aliases
    ]
    summary.update(
        {
            "status": "ok",
            "selected_row_index": selected_index,
            "selection_reason": selection_reason,
            "selected_time_s": parsed_times[selected_index],
            "omega_rad_s": omega if all(item is not None for item in omega) else None,
            "linear_velocity_m_per_s": (
                linear_velocity
                if all(item is not None for item in linear_velocity)
                else None
            ),
        }
    )
    return summary


def _source_stat(path: Path, expected_sha256: Optional[str] = None) -> Dict[str, Any]:
    result: Dict[str, Any] = {"path": str(path), "exists": path.exists()}
    if path.exists():
        result["bytes"] = int(path.stat().st_size)
    if expected_sha256:
        result["expected_sha256"] = expected_sha256
        result["sha256_read_policy"] = "fingerprint supplied by provenance; worker does not hash source"
    return result


def _frame_record(
    datasets: Mapping[str, Any],
    frame: int,
    start: int,
    count: int,
    center: Sequence[float],
    declared_center: Sequence[float],
    tolerance: float,
    fit_center_label: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    position = _read_vector(datasets["position"], frame, start, count, "position")
    velocity = _read_vector(datasets["velocity"], frame, start, count, "velocity")
    particle_type = _read_scalar(datasets["type"], frame, start, count, "type")
    particle_id = _read_scalar(
        datasets["particle_id"], frame, start, count, "particle_id", dtype=np.int64
    )
    valid = (
        _read_scalar(datasets["valid"], frame, start, count, "valid")
        if "valid" in datasets
        else np.ones(count, dtype=np.float64)
    )
    zone = (
        _read_scalar(datasets["particle_zone"], frame, start, count, "particle_zone")
        if "particle_zone" in datasets
        else None
    )
    type_mask = np.isclose(particle_type, 2.0, rtol=0.0, atol=0.0)
    valid_mask = (valid != 0.0) & type_mask & _finite_vector(position) & _finite_vector(velocity)
    valid_position = position[valid_mask]
    valid_velocity = velocity[valid_mask]
    valid_ids = particle_id[valid_mask]
    speed = np.linalg.norm(valid_velocity, axis=1) if valid_velocity.size else np.asarray([])
    centroid = (
        [float(item) for item in np.mean(valid_position, axis=0)]
        if valid_position.size
        else None
    )
    fit = _fit_rigid(valid_position, valid_velocity, center)
    frame_data: Dict[str, Any] = {
        "frame": int(frame),
        "particle_range": {"start": int(start), "count": int(count)},
        "type_requested": 2,
        "type2_count": int(np.count_nonzero(type_mask)),
        "valid_type2_count": int(valid_position.shape[0]),
        "non_type2_count_in_requested_range": int(np.count_nonzero(~type_mask)),
        "invalid_or_nonfinite_count": int(count - valid_position.shape[0] - np.count_nonzero(~type_mask)),
        "centroid_m": centroid,
        "speed_stats_m_per_s": _stats(speed, tolerance),
        "fit_center_m": [float(item) for item in center],
        "fit_center_label": fit_center_label,
        "fit": fit,
        "uid": _uid_summary(valid_ids),
        "zone": {
            "available": zone is not None,
            "unique_values": (
                [float(item) for item in np.unique(zone[np.isfinite(zone)])[:16]]
                if zone is not None
                else []
            ),
            "expected_mk": 60,
        },
    }
    frame_internal = {
        "position": valid_position,
        "velocity": valid_velocity,
        "ids": valid_ids,
        "speed": speed,
        "declared_center": np.asarray(declared_center, dtype=np.float64),
    }
    return frame_data, frame_internal


def _run(args: argparse.Namespace) -> Dict[str, Any]:
    if np is None or h5py is None:
        raise AuditError(f"numpy/h5py import failed: {_IMPORT_ERROR}")

    trajectory = Path(args.trajectory)
    floating_info = Path(args.floating_info)
    pose_report = Path(args.pose_report)
    if not trajectory.exists():
        raise AuditError(f"trajectory does not exist: {trajectory}")

    start = int(args.particle_start)
    count = int(args.particle_count)
    preview_count = max(1, min(int(args.preview_frames), 4))
    declared_center = np.asarray(args.declared_center, dtype=np.float64)
    declared_omega = np.asarray(args.declared_omega, dtype=np.float64)
    tolerance = float(args.zero_tolerance)
    if start < 0 or count <= 0:
        raise AuditError("particle_start must be nonnegative and particle_count positive")
    if declared_center.shape != (3,) or declared_omega.shape != (3,):
        raise AuditError("declared center and omega must each contain exactly three values")

    result: Dict[str, Any] = {
        "schema": SCHEMA,
        "status": "running_bounded_audit",
        "source_policy": {
            "trajectory_slice_only": True,
            "max_preview_frames": preview_count,
            "particle_start": start,
            "particle_count": count,
            "fixed_or_fluid_arrays_read": False,
            "full_native_window_read": False,
            "particle_arrays_written": False,
            "csv_written": False,
            "h5_written": False,
        },
        "source_fingerprints": {
            "trajectory": _source_stat(trajectory, args.expected_h5_sha256),
            "floating_info": _source_stat(floating_info, args.expected_floating_info_sha256),
            "pose_report": _source_stat(pose_report, args.expected_pose_report_sha256),
        },
        "case_anchor": {
            "type": 2,
            "mk": 60,
            "declared_center_m": [float(item) for item in declared_center],
            "declared_omega_rad_s": [float(item) for item in declared_omega],
            "gencase_initial_velocity_max_m_per_s": float(args.gencase_initial_velocity_max),
            "physical_mass_kg": 128.0,
            "native_support_mass_kg": 256.0,
            "mass_rescaled": False,
        },
        "dataset_discovery": {},
        "floating_info": {},
        "pose_reference": {
            "path": str(pose_report),
            "read": False,
            "role": "corroborating reference only; no pose or Q-N claim",
        },
    }

    with h5py.File(trajectory, "r") as handle:
        datasets = _discover_datasets(handle)
        required = ("position", "velocity", "type", "particle_id")
        missing = [role for role in required if role not in datasets]
        if missing:
            raise AuditError(f"required datasets not discovered: {missing}")
        result["dataset_discovery"] = {
            role: {"path": str(dataset.name), "shape": list(_shape(dataset))}
            for role, dataset in sorted(datasets.items())
        }
        if "valid" not in datasets:
            result["dataset_discovery"]["valid"] = {
                "path": None,
                "shape": None,
                "fallback": "all selected values treated as valid; source did not expose a valid field",
            }
        times = _read_time(datasets.get("time"), preview_count)
        frame_records: List[Dict[str, Any]] = []
        internals: List[Dict[str, Any]] = []
        for frame in range(preview_count):
            center = declared_center if frame == 0 else None
            if center is None:
                # A first pass obtains the descriptive centroid for the preview.
                provisional, provisional_internal = _frame_record(
                    datasets,
                    frame,
                    start,
                    count,
                    declared_center,
                    declared_center,
                    tolerance,
                    "declared center (provisional preview read)",
                )
                if provisional["centroid_m"] is not None:
                    center = np.asarray(provisional["centroid_m"], dtype=np.float64)
                else:
                    center = declared_center
            record, internal = _frame_record(
                datasets,
                frame,
                start,
                count,
                center,
                declared_center,
                tolerance,
                "declared center" if frame == 0 else "valid Type2 centroid",
            )
            if times is not None and frame < len(times):
                record["time_s"] = float(times[frame])
            frame_records.append(record)
            internals.append(internal)

    frame0 = frame_records[0]
    frame0_fit = frame0["fit"]
    fitted_omega = frame0_fit.get("omega_rad_s")
    omega_difference: Optional[List[float]] = None
    omega_difference_norm: Optional[float] = None
    if fitted_omega is not None:
        difference = np.asarray(fitted_omega, dtype=np.float64) - declared_omega
        omega_difference = [float(item) for item in difference]
        omega_difference_norm = float(np.linalg.norm(difference))
    frame0_speed = frame0["speed_stats_m_per_s"]
    if frame0["valid_type2_count"] == 0:
        propagation = "insufficient"
    elif int(frame0_speed["nonzero_count"]) > 0:
        propagation = "yes"
    else:
        propagation = "no"
    result["frame0_audit"] = {
        "frame": 0,
        "fit": frame0_fit,
        "declared_omega_rad_s": [float(item) for item in declared_omega],
        "fitted_minus_declared_omega_rad_s": omega_difference,
        "fitted_minus_declared_omega_norm_rad_s": omega_difference_norm,
        "gen_zero_velocity_propagated_to_native0": propagation,
        "interpretation": (
            "Observed bounded native Type2 frame-zero state only; this is not a numerical validation or Q-N claim."
        ),
    }
    result["preview_frames"] = frame_records
    result["floating_info"] = _floating_info_summary(
        floating_info, int(args.max_floating_info_rows)
    )
    if fitted_omega is not None:
        fi_omega = result["floating_info"].get("omega_rad_s")
        if fi_omega is not None:
            result["floating_info"]["omega_minus_h5_fit_rad_s"] = [
                float(item)
                for item in np.asarray(fi_omega, dtype=np.float64)
                - np.asarray(fitted_omega, dtype=np.float64)
            ]
    result["status"] = "completed_bounded_audit"
    result["gates"] = {
        "launch_allowed": False,
        "independent_case_count_increment": 0,
        "production_approval": "none",
        "q_n": "not_assessed",
        "visual_review": "pending",
    }
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trajectory", required=True)
    parser.add_argument("--floating-info", required=True)
    parser.add_argument("--pose-report", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--preview-frames", type=int, default=DEFAULT_PREVIEW_FRAMES)
    parser.add_argument("--particle-start", type=int, default=DEFAULT_PARTICLE_START)
    parser.add_argument("--particle-count", type=int, default=DEFAULT_PARTICLE_COUNT)
    parser.add_argument("--declared-center", nargs=3, type=float, default=DEFAULT_CENTER)
    parser.add_argument("--declared-omega", nargs=3, type=float, default=DEFAULT_OMEGA)
    parser.add_argument("--zero-tolerance", type=float, default=DEFAULT_ZERO_TOLERANCE)
    parser.add_argument("--max-floating-info-rows", type=int, default=8)
    parser.add_argument("--gencase-initial-velocity-max", type=float, default=0.0)
    parser.add_argument("--expected-h5-sha256", default=None)
    parser.add_argument("--expected-floating-info-sha256", default=None)
    parser.add_argument("--expected-pose-report-sha256", default=None)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    output = Path(args.output)
    try:
        result = _run(args)
        exit_code = 0
    except Exception as exc:  # Keep a machine-readable failure receipt for root review.
        result = {
            "schema": SCHEMA,
            "status": "failed_bounded_audit",
            "error": {"type": type(exc).__name__, "message": str(exc)},
            "gates": {
                "launch_allowed": False,
                "independent_case_count_increment": 0,
                "production_approval": "none",
                "q_n": "not_assessed",
                "visual_review": "pending",
            },
        }
        exit_code = 1
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
