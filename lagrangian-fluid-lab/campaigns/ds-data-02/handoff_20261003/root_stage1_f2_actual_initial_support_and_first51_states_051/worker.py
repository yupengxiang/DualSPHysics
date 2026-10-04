#!/usr/bin/env python3
"""Bounded native frame-zero wall and saved-frame 0..50 audit for F2.

The worker is disabled by its request in this source handoff.  When Root
strictly enables it, the trajectory is opened read-only.  Frame zero is read
in particle chunks to retain every finite valid type-0/type-1 boundary point
and every finite valid type-3 fluid point.  A cKDTree is queried in chunks for
the frame-zero native boundary distance.  Saved frames 0..50 are then scanned
for all valid finite type-3 fluid rows and only summary statistics are written.
No particle arrays, CSV, H5, BI4, solver, GenCase, or rendering output is
written.  The declared-envelope bins are descriptive overlays, not masks or
precision gates.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    import h5py  # type: ignore
    import numpy as np  # type: ignore
    from scipy.spatial import cKDTree  # type: ignore
except Exception as exc:  # pragma: no cover - exercised by dispatch environment
    h5py = None  # type: ignore
    np = None  # type: ignore
    cKDTree = None  # type: ignore
    _IMPORT_ERROR = repr(exc)
else:
    _IMPORT_ERROR = None


SCHEMA = "ds02.f2.frame0-wall-and-frames50-audit-result.v1"


class AuditError(RuntimeError):
    """A bounded input or interpretation failure."""


ROLE_ALIASES: Mapping[str, Tuple[str, ...]] = {
    "position": ("position", "positions", "pos", "xyz", "coordinates"),
    "velocity": ("velocity", "velocities", "vel", "v"),
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
    "type": ("type", "particletype", "ptype"),
    "valid": ("valid", "isvalid", "active", "present", "alive"),
    "particle_zone": (
        "particlezone",
        "zone",
        "mk",
        "mkfluid",
        "marker",
        "material",
    ),
    "time": ("time", "times", "t", "timestamp"),
}


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _shape(dataset: Any) -> Tuple[int, ...]:
    return tuple(int(item) for item in dataset.shape)


def _discover_datasets(handle: Any) -> Dict[str, Any]:
    """Discover dataset names and shapes without reading dataset values."""

    candidates: Dict[str, List[Tuple[int, str, Any]]] = {
        role: [] for role in ROLE_ALIASES
    }

    def visit(name: str, obj: Any) -> None:
        if h5py is None or not isinstance(obj, h5py.Dataset):
            return
        basename = _normalise(name.rsplit("/", 1)[-1])
        for role, aliases in ROLE_ALIASES.items():
            if basename in aliases:
                candidates[role].append((aliases.index(basename), name, obj))

    handle.visititems(visit)
    selected: Dict[str, Any] = {}
    for role, entries in candidates.items():
        if entries:
            entries.sort(key=lambda item: (item[0], item[1].count("/"), item[1]))
            selected[role] = entries[0][2]
    return selected


def _position_axis(dataset: Any) -> Tuple[int, int]:
    """Return (frame_count, particle_count) for a vector dataset."""

    dims = _shape(dataset)
    if len(dims) == 3 and dims[-1] == 3:
        return dims[0], dims[1]
    if len(dims) == 2 and dims[-1] == 3:
        return 1, dims[0]
    if len(dims) == 2 and dims[0] == 3:
        return 1, dims[1]
    raise AuditError(f"position must have [frame,particle,3] or [particle,3]; shape={dims}")


def _read_vector(dataset: Any, frame: int, start: int, count: int, role: str) -> Any:
    dims = _shape(dataset)
    if len(dims) == 3 and dims[-1] == 3:
        if frame >= dims[0]:
            raise AuditError(f"{role} has no frame {frame}; shape={dims}")
        return np.asarray(dataset[frame, start : start + count, :], dtype=np.float64)
    if len(dims) == 2 and dims[-1] == 3:
        return np.asarray(dataset[start : start + count, :], dtype=np.float64)
    if len(dims) == 2 and dims[0] == 3:
        return np.asarray(dataset[:, start : start + count], dtype=np.float64).T
    raise AuditError(f"unsupported {role} shape {dims}; expected vector field")


def _read_scalar(
    dataset: Any,
    frame: int,
    start: int,
    count: int,
    role: str,
    particle_count: int,
    frame_count: int,
    dtype: Any = None,
) -> Any:
    if dtype is None:
        dtype = np.float64
    dims = _shape(dataset)
    if len(dims) == 1:
        return np.asarray(dataset[start : start + count], dtype=dtype)
    if len(dims) == 3 and dims[-1] == 1:
        if frame >= dims[0]:
            raise AuditError(f"{role} has no frame {frame}; shape={dims}")
        return np.asarray(dataset[frame, start : start + count, 0], dtype=dtype)
    if len(dims) == 2:
        # Prefer the orientation whose particle axis matches the position
        # dataset.  This keeps static [particle,frame] fields deterministic.
        if dims[1] == particle_count and dims[0] >= frame_count:
            return np.asarray(dataset[frame, start : start + count], dtype=dtype)
        if dims[0] == particle_count and dims[1] >= frame_count:
            return np.asarray(dataset[start : start + count, frame], dtype=dtype)
        if frame < dims[0]:
            return np.asarray(dataset[frame, start : start + count], dtype=dtype)
    raise AuditError(f"unsupported {role} shape {dims}; expected scalar field")


def _read_time(dataset: Optional[Any], frame: int) -> Optional[float]:
    if dataset is None:
        return None
    dims = _shape(dataset)
    if len(dims) == 1 and frame < dims[0]:
        return float(dataset[frame])
    if len(dims) == 2 and dims[-1] == 1 and frame < dims[0]:
        return float(dataset[frame, 0])
    if len(dims) == 2 and dims[0] == 1 and frame < dims[1]:
        return float(dataset[0, frame])
    return None


def _finite_vector(values: Any) -> Any:
    return np.isfinite(values).all(axis=1)


def _percentile_stats(values: Any) -> Dict[str, Any]:
    array = np.asarray(values, dtype=np.float64).reshape(-1)
    finite = array[np.isfinite(array)]
    if finite.size == 0:
        return {
            "count": 0,
            "min": None,
            "mean": None,
            "max": None,
            "percentiles": {},
        }
    levels = (0, 1, 5, 10, 25, 50, 75, 90, 95, 99, 100)
    quantiles = np.percentile(finite, levels)
    return {
        "count": int(finite.size),
        "min": float(np.min(finite)),
        "mean": float(np.mean(finite)),
        "max": float(np.max(finite)),
        "percentiles": {
            f"p{level:02d}": float(value) for level, value in zip(levels, quantiles)
        },
    }


def _position_summary(position: Any, ids: Any) -> Dict[str, Any]:
    if position is None or len(position) == 0:
        return {
            "count": 0,
            "com_m": None,
            "min_m": None,
            "max_m": None,
            "uid_first": [],
            "uid_last": [],
            "uid_unique_count": 0,
        }
    values = np.asarray(position, dtype=np.float64)
    uid_values = np.asarray(ids, dtype=np.int64)
    unique_count = int(np.unique(uid_values).size)
    return {
        "count": int(values.shape[0]),
        "com_m": [float(item) for item in np.mean(values, axis=0)],
        "min_m": [float(item) for item in np.min(values, axis=0)],
        "max_m": [float(item) for item in np.max(values, axis=0)],
        "uid_first": [int(item) for item in uid_values[:8]],
        "uid_last": [int(item) for item in uid_values[-8:]],
        "uid_unique_count": unique_count,
        "uid_duplicate_count": int(uid_values.size - unique_count),
    }


def _signed_cup_clearance(position: Any, low: Any, high: Any) -> Any:
    lower_gap = np.asarray(position, dtype=np.float64) - low
    upper_gap = high - np.asarray(position, dtype=np.float64)
    return np.min(np.minimum(lower_gap, upper_gap), axis=1)


def _near_interior_summary(clearance: Any, threshold: float) -> Dict[str, Any]:
    values = np.asarray(clearance, dtype=np.float64)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return {
            "threshold_m": float(threshold),
            "count": 0,
            "near_cup_wall_or_outside_count": 0,
            "interior_beyond_threshold_count": 0,
            "outside_declared_envelope_count": 0,
            "clearance_stats_m": _percentile_stats([]),
        }
    near = finite <= threshold
    interior = finite > threshold
    outside = finite < 0.0
    return {
        "threshold_m": float(threshold),
        "count": int(finite.size),
        "near_cup_wall_or_outside_count": int(np.count_nonzero(near)),
        "interior_beyond_threshold_count": int(np.count_nonzero(interior)),
        "outside_declared_envelope_count": int(np.count_nonzero(outside)),
        "near_fraction": float(np.mean(near)),
        "interior_fraction": float(np.mean(interior)),
        "clearance_stats_m": _percentile_stats(finite),
    }


def _source_stat(path: Path, expected_sha256: Optional[str]) -> Dict[str, Any]:
    result: Dict[str, Any] = {"path": str(path), "exists": path.exists()}
    if path.exists():
        result["bytes"] = int(path.stat().st_size)
    if expected_sha256:
        result["expected_sha256"] = expected_sha256
        result["sha256_read_policy"] = "fingerprint supplied by provenance; worker does not hash source"
    return result


def _type_coordinate_summary(
    position: Any,
    ids: Any,
    requested_count: int,
    retained_count: int,
    label: str,
    native_type: int,
) -> Dict[str, Any]:
    summary = _position_summary(position, ids)
    summary.update(
        {
            "label": label,
            "native_type": int(native_type),
            "requested_count": int(requested_count),
            "retained_finite_valid_coordinate_count": int(retained_count),
            "coordinate_output": "summary only; no coordinate array written",
        }
    )
    return summary


def _scan_frame(
    datasets: Mapping[str, Any],
    frame: int,
    particle_count: int,
    frame_count: int,
    chunk_size: int,
    fluid_type: int,
    fixed_type: int,
    moving_type: int,
    expected_fluid_count: int,
    cup_low: Any,
    cup_high: Any,
    near_threshold: float,
    retain_frame0_boundary: bool,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    position_chunks: List[Any] = []
    id_chunks: List[Any] = []
    boundary_chunks: Dict[int, List[Any]] = {fixed_type: [], moving_type: []}
    boundary_id_chunks: Dict[int, List[Any]] = {fixed_type: [], moving_type: []}
    boundary_requested: Dict[int, int] = {fixed_type: 0, moving_type: 0}
    boundary_retained: Dict[int, int] = {fixed_type: 0, moving_type: 0}
    v2_chunks: List[Any] = []
    total_type3 = 0
    valid_type3 = 0
    nonfinite_type3 = 0
    valid_finite_type3 = 0
    time_s = _read_time(datasets.get("time"), frame)

    for start in range(0, particle_count, chunk_size):
        count = min(chunk_size, particle_count - start)
        positions = _read_vector(datasets["position"], frame, start, count, "position")
        velocities = _read_vector(datasets["velocity"], frame, start, count, "velocity")
        ids = _read_scalar(
            datasets["particle_id"],
            frame,
            start,
            count,
            "particle_id",
            particle_count,
            frame_count,
            dtype=np.int64,
        )
        types = _read_scalar(
            datasets["type"], frame, start, count, "type", particle_count, frame_count
        )
        if "valid" in datasets:
            valid = _read_scalar(
                datasets["valid"],
                frame,
                start,
                count,
                "valid",
                particle_count,
                frame_count,
            )
        else:
            valid = np.ones(count, dtype=np.float64)

        finite_position = _finite_vector(positions)
        finite_velocity = _finite_vector(velocities)
        valid_native = valid != 0.0
        fluid_requested = types == float(fluid_type)
        fluid_valid = fluid_requested & valid_native
        fluid_finite = fluid_valid & finite_position & finite_velocity
        total_type3 += int(np.count_nonzero(fluid_requested))
        valid_type3 += int(np.count_nonzero(fluid_valid))
        valid_finite_type3 += int(np.count_nonzero(fluid_finite))
        nonfinite_type3 += int(
            np.count_nonzero(fluid_valid & ~(finite_position & finite_velocity))
        )

        if np.any(fluid_finite):
            fluid_positions = positions[fluid_finite]
            fluid_ids = ids[fluid_finite]
            fluid_velocity = velocities[fluid_finite]
            position_chunks.append(fluid_positions)
            id_chunks.append(fluid_ids)
            v2_chunks.append(np.sum(fluid_velocity * fluid_velocity, axis=1))

        if retain_frame0_boundary:
            for boundary_type in (fixed_type, moving_type):
                requested = types == float(boundary_type)
                retained = requested & valid_native & finite_position
                boundary_requested[boundary_type] += int(np.count_nonzero(requested))
                boundary_retained[boundary_type] += int(np.count_nonzero(retained))
                if np.any(retained):
                    boundary_chunks[boundary_type].append(positions[retained])
                    boundary_id_chunks[boundary_type].append(ids[retained])

    fluid_position = (
        np.concatenate(position_chunks, axis=0) if position_chunks else np.empty((0, 3))
    )
    fluid_ids = np.concatenate(id_chunks, axis=0) if id_chunks else np.empty((0,), dtype=np.int64)
    v2 = np.concatenate(v2_chunks, axis=0) if v2_chunks else np.empty((0,), dtype=np.float64)
    clearance = _signed_cup_clearance(fluid_position, cup_low, cup_high)
    active_missing = max(expected_fluid_count - valid_finite_type3, 0)
    frame_record: Dict[str, Any] = {
        "frame": int(frame),
        "time_s": time_s,
        "particle_count": int(particle_count),
        "type3_requested_count": int(total_type3),
        "valid_type3_count": int(valid_type3),
        "valid_finite_type3_count": int(valid_finite_type3),
        "nonfinite_valid_type3_count": int(nonfinite_type3),
        "active_fluid_count_for_denominator": int(valid_finite_type3),
        "expected_initial_fluid_count": int(expected_fluid_count),
        "missing_fluid_count": int(active_missing),
        "active_minus_expected": int(valid_finite_type3 - expected_fluid_count),
        "v2_m2_per_s2": _percentile_stats(v2),
        "fluid_position": _position_summary(fluid_position, fluid_ids),
        "declared_cup_signed_clearance_m": _near_interior_summary(
            clearance, near_threshold
        ),
        "selection_policy": "native type-3 and valid/finite position+velocity status; all retained rows contribute to global summaries",
    }
    internal: Dict[str, Any] = {
        "fluid_position": fluid_position,
        "fluid_ids": fluid_ids,
        "boundary_position": {},
        "boundary_ids": {},
        "boundary_requested": boundary_requested,
        "boundary_retained": boundary_retained,
        "type_coordinate_summary": {},
    }
    if retain_frame0_boundary:
        for boundary_type, label in (
            (fixed_type, "fixed_type0"),
            (moving_type, "moving_type1"),
        ):
            points = (
                np.concatenate(boundary_chunks[boundary_type], axis=0)
                if boundary_chunks[boundary_type]
                else np.empty((0, 3))
            )
            boundary_ids = (
                np.concatenate(boundary_id_chunks[boundary_type], axis=0)
                if boundary_id_chunks[boundary_type]
                else np.empty((0,), dtype=np.int64)
            )
            internal["boundary_position"][boundary_type] = points
            internal["boundary_ids"][boundary_type] = boundary_ids
            internal["type_coordinate_summary"][label] = _type_coordinate_summary(
                points,
                boundary_ids,
                boundary_requested[boundary_type],
                boundary_retained[boundary_type],
                label,
                boundary_type,
            )
        internal["boundary_position"]["combined"] = np.concatenate(
            [internal["boundary_position"][fixed_type], internal["boundary_position"][moving_type]],
            axis=0,
        )
        internal["boundary_ids"]["combined"] = np.concatenate(
            [internal["boundary_ids"][fixed_type], internal["boundary_ids"][moving_type]],
            axis=0,
        )
        internal["boundary_types"] = np.concatenate(
            [
                np.full(internal["boundary_ids"][fixed_type].shape, fixed_type, dtype=np.int64),
                np.full(internal["boundary_ids"][moving_type].shape, moving_type, dtype=np.int64),
            ],
            axis=0,
        )
    return frame_record, internal


def _native_distance_summary(
    fluid_position: Any,
    fluid_ids: Any,
    boundary_position: Any,
    boundary_ids: Any,
    boundary_types: Any,
    query_chunk_size: int,
) -> Dict[str, Any]:
    if cKDTree is None:
        raise AuditError(f"scipy.spatial.cKDTree import failed: {_IMPORT_ERROR}")
    if fluid_position.shape[0] == 0 or boundary_position.shape[0] == 0:
        return {
            "status": "insufficient_retained_coordinates",
            "fluid_query_count": int(fluid_position.shape[0]),
            "boundary_pool_count": int(boundary_position.shape[0]),
            "distance_m": _percentile_stats([]),
            "nearest_sample_uids": [],
        }
    tree = cKDTree(boundary_position)
    distances = np.empty(fluid_position.shape[0], dtype=np.float64)
    indices = np.empty(fluid_position.shape[0], dtype=np.int64)
    for start in range(0, fluid_position.shape[0], query_chunk_size):
        stop = min(start + query_chunk_size, fluid_position.shape[0])
        chunk_distance, chunk_index = tree.query(fluid_position[start:stop], k=1)
        distances[start:stop] = np.asarray(chunk_distance, dtype=np.float64)
        indices[start:stop] = np.asarray(chunk_index, dtype=np.int64)
    order = np.argsort(distances, kind="stable")
    samples: List[Dict[str, Any]] = []
    for row in order[: min(8, order.size)]:
        boundary_index = int(indices[row])
        fluid_index = int(row)
        samples.append(
            {
                "distance_m": float(distances[fluid_index]),
                "fluid_uid": int(fluid_ids[fluid_index]),
                "boundary_uid": int(boundary_ids[boundary_index]),
                "boundary_type": int(boundary_types[boundary_index]),
                "fluid_position_m": [float(item) for item in fluid_position[fluid_index]],
                "boundary_position_m": [
                    float(item) for item in boundary_position[boundary_index]
                ],
            }
        )
    unique_types, type_counts = np.unique(boundary_types[indices], return_counts=True)
    return {
        "status": "completed_chunked_kdtree_query",
        "fluid_query_count": int(fluid_position.shape[0]),
        "boundary_pool_count": int(boundary_position.shape[0]),
        "query_chunk_size": int(query_chunk_size),
        "distance_m": _percentile_stats(distances),
        "nearest_boundary_type_counts": {
            str(int(kind)): int(count) for kind, count in zip(unique_types, type_counts)
        },
        "nearest_sample_uids": samples,
        "qualifier": "global over the complete retained frame-zero native type-0/type-1 coordinate pool; not a CAD-face reconstruction",
    }


def _run(args: argparse.Namespace) -> Dict[str, Any]:
    if np is None or h5py is None or cKDTree is None:
        raise AuditError(f"numpy/h5py/scipy import failed: {_IMPORT_ERROR}")
    trajectory = Path(args.trajectory)
    if not trajectory.exists():
        raise AuditError(f"trajectory does not exist: {trajectory}")
    frame_start = int(args.frame_start)
    frame_end = int(args.frame_end)
    chunk_size = max(1, int(args.chunk_size))
    query_chunk_size = max(1, int(args.query_chunk_size))
    if frame_start < 0 or frame_end < frame_start:
        raise AuditError("frame range must be nonnegative and ordered")
    if frame_end - frame_start + 1 > 51:
        raise AuditError("bounded worker allows at most 51 saved frames")
    cup_low = np.asarray(args.cup_low, dtype=np.float64)
    cup_size = np.asarray(args.cup_size, dtype=np.float64)
    cup_high = cup_low + cup_size
    if cup_low.shape != (3,) or cup_size.shape != (3,) or np.any(cup_size <= 0.0):
        raise AuditError("cup low and size must each contain three positive geometry values")
    near_threshold = (
        float(args.near_wall_threshold)
        if args.near_wall_threshold is not None
        else float(3.0 * args.dp)
    )
    if near_threshold < 0.0:
        raise AuditError("near-wall threshold must be nonnegative")

    result: Dict[str, Any] = {
        "schema": SCHEMA,
        "status": "running_bounded_audit",
        "source_policy": {
            "trajectory": "read-only H5 source",
            "frame0_all_native_particles_visited": True,
            "frame0_boundary_types": [int(args.fixed_type), int(args.moving_type)],
            "frame0_fluid_type": int(args.fluid_type),
            "saved_frame_range": [frame_start, frame_end],
            "chunk_size": chunk_size,
            "query_chunk_size": query_chunk_size,
            "coordinate_arrays_written": False,
            "particle_arrays_written": False,
            "csv_written": False,
            "h5_written": False,
            "bi4_read": False,
            "mask_policy": "native type/valid/finite eligibility only; declared-envelope bins do not alter global denominators",
            "mass_rescaled": False,
            "generic_precision_gate": False,
        },
        "source_fingerprint": _source_stat(trajectory, args.expected_h5_sha256),
        "declared_source_geometry": {
            "cup_low_m": [float(item) for item in cup_low],
            "cup_size_m": [float(item) for item in cup_size],
            "cup_high_m": [float(item) for item in cup_high],
            "dp_m": float(args.dp),
            "near_wall_threshold_m": near_threshold,
            "threshold_source": "explicit request value or nominal three-layer span 3*dp",
        },
        "interpretation": "Descriptive native-support and first-51-saved-frame audit only; no wall-overlap, non-equilibrium-cause, explosion, invalid-state, Q-I, Q-N, production, or acceptance claim.",
        "dataset_discovery": {},
    }

    with h5py.File(trajectory, "r") as handle:
        datasets = _discover_datasets(handle)
        required = ("position", "velocity", "particle_id", "type")
        missing = [role for role in required if role not in datasets]
        if missing:
            raise AuditError(f"required datasets not discovered: {missing}")
        frame_count, particle_count = _position_axis(datasets["position"])
        if frame_end >= frame_count:
            raise AuditError(
                f"requested frame {frame_end} exceeds position frame count {frame_count}"
            )
        result["dataset_discovery"] = {
            role: {"path": str(dataset.name), "shape": list(_shape(dataset))}
            for role, dataset in sorted(datasets.items())
        }
        if "valid" not in datasets:
            result["dataset_discovery"]["valid"] = {
                "path": None,
                "fallback": "all rows treated as valid; active count remains a source fallback",
            }
        result["native_axis"] = {
            "frame_count": int(frame_count),
            "particle_count": int(particle_count),
            "requested_frame_count": int(frame_end - frame_start + 1),
        }

        frame0_record, frame0_internal = _scan_frame(
            datasets,
            frame_start,
            particle_count,
            frame_count,
            chunk_size,
            int(args.fluid_type),
            int(args.fixed_type),
            int(args.moving_type),
            int(args.expected_fluid_count),
            cup_low,
            cup_high,
            near_threshold,
            retain_frame0_boundary=True,
        )
        frame_records = [frame0_record]
        for frame in range(frame_start + 1, frame_end + 1):
            frame_record, _ = _scan_frame(
                datasets,
                frame,
                particle_count,
                frame_count,
                chunk_size,
                int(args.fluid_type),
                int(args.fixed_type),
                int(args.moving_type),
                int(args.expected_fluid_count),
                cup_low,
                cup_high,
                near_threshold,
                retain_frame0_boundary=False,
            )
            frame_records.append(frame_record)

        boundary_position = frame0_internal["boundary_position"]["combined"]
        boundary_ids = frame0_internal["boundary_ids"]["combined"]
        boundary_types = frame0_internal["boundary_types"]
        result["frame0_native"] = {
            "frame": int(frame_start),
            "boundary_pool": {
                "types": {
                    "fixed_type0": frame0_internal["type_coordinate_summary"]["fixed_type0"],
                    "moving_type1": frame0_internal["type_coordinate_summary"]["moving_type1"],
                },
                "combined_count": int(boundary_position.shape[0]),
                "coordinate_policy": "all retained finite valid native type-0/type-1 coordinates; no declared-envelope geometric mask",
            },
            "fluid": frame0_record["fluid_position"],
            "native_boundary_distance": _native_distance_summary(
                frame0_internal["fluid_position"],
                frame0_internal["fluid_ids"],
                boundary_position,
                boundary_ids,
                boundary_types,
                query_chunk_size,
            ),
        }
    result["saved_frames"] = frame_records
    result["gates"] = {
        "launch_allowed": False,
        "independent_case_count_increment": 0,
        "production_approval": "none",
        "q_i": "not_granted",
        "q_n": "not_assessed",
        "visual_review": "pending",
        "root_cause": "undetermined",
    }
    result["status"] = "completed_bounded_audit"
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trajectory", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--frame-start", type=int, default=0)
    parser.add_argument("--frame-end", type=int, default=50)
    parser.add_argument("--fixed-type", type=int, default=0)
    parser.add_argument("--moving-type", type=int, default=1)
    parser.add_argument("--fluid-type", type=int, default=3)
    parser.add_argument("--expected-fluid-count", type=int, default=24576)
    parser.add_argument("--cup-low", nargs=3, type=float, default=(0.0, -0.15, 0.65))
    parser.add_argument("--cup-size", nargs=3, type=float, default=(0.425, 0.3, 0.45))
    parser.add_argument("--dp", type=float, default=0.01)
    parser.add_argument("--near-wall-threshold", type=float, default=None)
    parser.add_argument("--chunk-size", type=int, default=32768)
    parser.add_argument("--query-chunk-size", type=int, default=32768)
    parser.add_argument("--expected-h5-sha256", default=None)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    output = Path(args.output)
    try:
        result = _run(args)
        code = 0
    except Exception as exc:  # keep a machine-readable failed receipt
        result = {
            "schema": SCHEMA,
            "status": "failed_bounded_audit",
            "error": {"type": type(exc).__name__, "message": str(exc)},
            "gates": {
                "launch_allowed": False,
                "independent_case_count_increment": 0,
                "production_approval": "none",
                "q_i": "not_granted",
                "q_n": "not_assessed",
                "visual_review": "pending",
                "root_cause": "undetermined",
            },
        }
        code = 1
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    sys.exit(main())
