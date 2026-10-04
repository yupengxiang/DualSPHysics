#!/usr/bin/env python3
"""Bounded frame-zero support audit for the existing F2 typed trajectory.

This worker is intentionally sample-limited.  It reads at most ``sample_count``
rows from the configured fixed-wall and fluid ranges at one frame, summarizes
position, velocity, and kinetic energy, and computes nearest distances only
between those two sampled sets.  It never claims a global nearest neighbour and
never materialises a complete native frame.
"""

from __future__ import annotations

import argparse
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
except Exception as exc:  # pragma: no cover
    h5py = None  # type: ignore
    np = None  # type: ignore
    IMPORT_ERROR = repr(exc)
else:
    IMPORT_ERROR = None


SCHEMA = "ds02.f2.initial-support-audit-result.v1"


class AuditError(RuntimeError):
    pass


def normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


ALIASES: Mapping[str, Tuple[str, ...]] = {
    "position": ("position", "positions", "pos", "xyz", "coordinates"),
    "velocity": ("velocity", "velocities", "vel", "v"),
    "particle_id": ("particleid", "particleids", "idp", "uid", "particleuid", "id"),
    "particle_zone": ("particlezone", "zone", "mk", "mkfluid", "material"),
    "initial_mk": ("initialmk", "initialzone", "initialparticlezone"),
    "mass": ("mass", "masses", "particlemass"),
    "valid": ("valid", "isvalid", "active", "present", "alive"),
    "type": ("type", "particletype", "ptype"),
    "time": ("time", "times", "t", "timestamp"),
}


def shape(dataset: Any) -> Tuple[int, ...]:
    return tuple(int(item) for item in dataset.shape)


def discover(handle: Any) -> Dict[str, Any]:
    candidates: Dict[str, List[Tuple[int, str, Any]]] = {role: [] for role in ALIASES}

    def visit(name: str, obj: Any) -> None:
        if h5py is None or not isinstance(obj, h5py.Dataset):
            return
        base = normalise(name.rsplit("/", 1)[-1])
        for role, aliases in ALIASES.items():
            if base in aliases:
                candidates[role].append((aliases.index(base), name, obj))

    handle.visititems(visit)
    selected: Dict[str, Any] = {}
    for role, entries in candidates.items():
        if entries:
            entries.sort(key=lambda item: (item[0], item[1].count("/"), item[1]))
            selected[role] = entries[0][2]
    return selected


def read_vector(dataset: Any, frame: int, start: int, count: int, role: str) -> Any:
    dims = shape(dataset)
    if len(dims) == 3 and dims[-1] == 3:
        if frame >= dims[0]:
            raise AuditError(f"{role} has no requested frame {frame}: shape={dims}")
        return np.asarray(dataset[frame, start : start + count, :], dtype=np.float64)
    if len(dims) == 2 and dims[-1] == 3:
        return np.asarray(dataset[start : start + count, :], dtype=np.float64)
    if len(dims) == 2 and dims[0] == 3:
        return np.asarray(dataset[:, start : start + count], dtype=np.float64).T
    raise AuditError(f"unsupported {role} shape {dims}; expected vector field")


def read_scalar(
    dataset: Any,
    frame: int,
    start: int,
    count: int,
    role: str,
    dtype: Any = None,
) -> Any:
    if dtype is None:
        dtype = np.float64
    dims = shape(dataset)
    if len(dims) == 2:
        if frame >= dims[0]:
            raise AuditError(f"{role} has no requested frame {frame}: shape={dims}")
        return np.asarray(dataset[frame, start : start + count], dtype=dtype)
    if len(dims) == 1:
        return np.asarray(dataset[start : start + count], dtype=dtype)
    if len(dims) == 3 and dims[-1] == 1:
        if frame >= dims[0]:
            raise AuditError(f"{role} has no requested frame {frame}: shape={dims}")
        return np.asarray(dataset[frame, start : start + count, 0], dtype=dtype)
    raise AuditError(f"unsupported {role} shape {dims}; expected scalar field")


def read_time(dataset: Optional[Any], frame: int) -> Optional[float]:
    if dataset is None:
        return None
    dims = shape(dataset)
    if len(dims) == 1 and frame < dims[0]:
        return float(dataset[frame])
    if len(dims) == 2 and dims[-1] == 1 and frame < dims[0]:
        return float(dataset[frame, 0])
    if len(dims) == 2 and dims[0] == 1 and frame < dims[1]:
        return float(dataset[0, frame])
    return None


def finite_rows(position: Any, velocity: Any, valid: Any, types: Any, expected: int) -> Any:
    return (
        (valid != 0.0)
        & (types == float(expected))
        & np.isfinite(position).all(axis=1)
        & np.isfinite(velocity).all(axis=1)
    )


def sample_rows(
    position: Any,
    velocity: Any,
    ids: Any,
    zone: Any,
    initial_mk: Any,
    mass: Any,
    valid: Any,
    types: Any,
    mask: Any,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for index in np.flatnonzero(mask):
        speed = float(np.linalg.norm(velocity[index]))
        mass_value = float(mass[index]) if math.isfinite(float(mass[index])) else None
        rows.append(
            {
                "sample_index": int(index),
                "particle_id": int(ids[index]),
                "particle_zone": float(zone[index]) if math.isfinite(float(zone[index])) else None,
                "initial_mk": float(initial_mk[index]) if math.isfinite(float(initial_mk[index])) else None,
                "type": float(types[index]),
                "valid": bool(valid[index] != 0.0),
                "position_m": [float(item) for item in position[index]],
                "velocity_m_per_s": [float(item) for item in velocity[index]],
                "speed_m_per_s": speed,
                "mass_kg": mass_value,
                "kinetic_energy_j": (
                    0.5 * mass_value * speed * speed if mass_value is not None else None
                ),
            }
        )
    return rows


def group_summary(rows: List[Dict[str, Any]], label: str, expected_type: int) -> Dict[str, Any]:
    speeds = np.asarray([row["speed_m_per_s"] for row in rows], dtype=np.float64)
    kinetic = [row["kinetic_energy_j"] for row in rows if row["kinetic_energy_j"] is not None]
    positions = np.asarray([row["position_m"] for row in rows], dtype=np.float64)
    return {
        "label": label,
        "expected_type": expected_type,
        "sample_count": len(rows),
        "rows": rows,
        "position_min_m": (
            [float(item) for item in np.min(positions, axis=0)] if len(rows) else None
        ),
        "position_max_m": (
            [float(item) for item in np.max(positions, axis=0)] if len(rows) else None
        ),
        "speed_m_per_s": (
            {
                "min": float(np.min(speeds)),
                "mean": float(np.mean(speeds)),
                "max": float(np.max(speeds)),
                "nonzero_count": int(np.count_nonzero(speeds > 1.0e-12)),
            }
            if len(rows)
            else None
        ),
        "kinetic_energy_j": {
            "available_count": len(kinetic),
            "sum": float(sum(kinetic)) if kinetic else None,
            "max": float(max(kinetic)) if kinetic else None,
        },
    }


def sampled_nearest(fixed: List[Dict[str, Any]], fluid: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not fixed or not fluid:
        return {
            "status": "insufficient_sample",
            "global_sample_min_distance_m": None,
            "nearest_fluid_rows": [],
        }
    fixed_position = np.asarray([row["position_m"] for row in fixed], dtype=np.float64)
    fluid_position = np.asarray([row["position_m"] for row in fluid], dtype=np.float64)
    distances = np.linalg.norm(fluid_position[:, None, :] - fixed_position[None, :, :], axis=2)
    nearest_index = np.argmin(distances, axis=1)
    nearest_rows = []
    for fluid_index, fixed_index in enumerate(nearest_index):
        nearest_rows.append(
            {
                "fluid_particle_id": fluid[fluid_index]["particle_id"],
                "fixed_particle_id": fixed[int(fixed_index)]["particle_id"],
                "distance_m": float(distances[fluid_index, fixed_index]),
            }
        )
    return {
        "status": "sample_only",
        "global_sample_min_distance_m": float(np.min(distances)),
        "nearest_fluid_rows": nearest_rows,
        "qualifier": "nearest distances are only between the first bounded samples; no global nearest-neighbour claim",
    }


def source_stat(path: Path, expected_sha256: Optional[str]) -> Dict[str, Any]:
    result = {"path": str(path), "exists": path.exists()}
    if path.exists():
        result["bytes"] = int(path.stat().st_size)
    if expected_sha256:
        result["expected_sha256"] = expected_sha256
        result["sha256_read_policy"] = "fingerprint supplied by provenance; worker does not hash source"
    return result


def run(args: argparse.Namespace) -> Dict[str, Any]:
    if np is None or h5py is None:
        raise AuditError(f"numpy/h5py import failed: {IMPORT_ERROR}")
    trajectory = Path(args.trajectory)
    if not trajectory.exists():
        raise AuditError(f"trajectory does not exist: {trajectory}")
    sample_count = max(1, min(int(args.sample_count), 51))
    frame = int(args.frame)
    result: Dict[str, Any] = {
        "schema": SCHEMA,
        "status": "running_bounded_audit",
        "source_policy": {
            "frame": frame,
            "sample_count_per_type": sample_count,
            "fixed_range": {"start": int(args.fixed_start), "count": sample_count},
            "fluid_range": {"start": int(args.fluid_start), "count": sample_count},
            "full_native_frame_read": False,
            "raw_bi4_read": False,
            "particle_arrays_written": False,
            "csv_written": False,
            "global_nearest_neighbor_claim": False,
        },
        "source_fingerprint": source_stat(trajectory, args.expected_h5_sha256),
        "interpretation": "Sample-limited frame-zero positions and kinematics only; no acceptance, root-cause, Q-I, or Q-N claim.",
    }
    with h5py.File(trajectory, "r") as handle:
        datasets = discover(handle)
        required = ("position", "velocity", "particle_id", "type")
        missing = [role for role in required if role not in datasets]
        if missing:
            raise AuditError(f"required datasets not discovered: {missing}")
        result["dataset_discovery"] = {
            role: {"path": str(dataset.name), "shape": list(shape(dataset))}
            for role, dataset in sorted(datasets.items())
        }
        if "valid" not in datasets:
            result["dataset_discovery"]["valid"] = {"path": None, "fallback": "all sampled rows treated as valid"}
        if "mass" not in datasets:
            result["dataset_discovery"]["mass"] = {"path": None, "fallback": "kinetic energy unavailable"}

        groups: Dict[str, Dict[str, Any]] = {}
        for label, expected_type, start in (
            ("fixed_wall", int(args.fixed_type), int(args.fixed_start)),
            ("fluid", int(args.fluid_type), int(args.fluid_start)),
        ):
            position = read_vector(datasets["position"], frame, start, sample_count, "position")
            velocity = read_vector(datasets["velocity"], frame, start, sample_count, "velocity")
            ids = read_scalar(datasets["particle_id"], frame, start, sample_count, "particle_id", dtype=np.int64)
            types = read_scalar(datasets["type"], frame, start, sample_count, "type")
            valid = (
                read_scalar(datasets["valid"], frame, start, sample_count, "valid")
                if "valid" in datasets
                else np.ones(sample_count, dtype=np.float64)
            )
            zone = (
                read_scalar(datasets["particle_zone"], frame, start, sample_count, "particle_zone")
                if "particle_zone" in datasets
                else np.full(sample_count, np.nan)
            )
            initial_mk = (
                read_scalar(datasets["initial_mk"], frame, start, sample_count, "initial_mk")
                if "initial_mk" in datasets
                else zone
            )
            mass = (
                read_scalar(datasets["mass"], frame, start, sample_count, "mass")
                if "mass" in datasets
                else np.full(sample_count, np.nan)
            )
            mask = finite_rows(position, velocity, valid, types, expected_type)
            rows = sample_rows(position, velocity, ids, zone, initial_mk, mass, valid, types, mask)
            groups[label] = {
                "summary": group_summary(rows, label, expected_type),
                "requested_type_count": int(np.count_nonzero(types == float(expected_type))),
                "nonfinite_or_invalid_count": int(sample_count - len(rows) - np.count_nonzero(types != float(expected_type))),
            }
        result["time_s"] = read_time(datasets.get("time"), frame)
        result["groups"] = groups
        result["sampled_nearest"] = sampled_nearest(
            groups["fixed_wall"]["summary"]["rows"], groups["fluid"]["summary"]["rows"]
        )
    result["status"] = "completed_bounded_audit"
    result["gates"] = {
        "launch_allowed": False,
        "independent_case_count_increment": 0,
        "production_approval": "none",
        "q_i": "not_granted",
        "q_n": "not_assessed",
        "visual_review": "pending",
    }
    return result


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--trajectory", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--frame", type=int, default=0)
    p.add_argument("--sample-count", type=int, default=51)
    p.add_argument("--fixed-start", type=int, default=0)
    p.add_argument("--fixed-type", type=int, default=0)
    p.add_argument("--fluid-start", type=int, default=396990)
    p.add_argument("--fluid-type", type=int, default=3)
    p.add_argument("--expected-h5-sha256", default=None)
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parser().parse_args(argv)
    output = Path(args.output)
    try:
        result = run(args)
        code = 0
    except Exception as exc:  # keep a machine-readable disabled-run failure receipt
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
            },
        }
        code = 1
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    sys.exit(main())
