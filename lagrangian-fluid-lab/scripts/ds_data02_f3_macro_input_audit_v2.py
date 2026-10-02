#!/usr/bin/env python3
"""Audit fixed-window macro inputs before accepting their filtered rows.

The F3 fixed-window reducer filters invalid rows while computing weighted
macros.  This v2 sidecar makes that filtering explicit: every row satisfying
``initial_type == 3`` and ``valid == true`` is checked for finite position and
velocity and strictly positive finite mass.  Any violation is retained in the
report and makes the audit fail; it is never silently dropped.  Fluid identity
indices are read as contiguous HDF5 slices whenever possible, avoiding the
point-selection cost of the first implementation on multi-gigabyte inputs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import resource
from typing import Any, Sequence

import h5py
import numpy as np


SCHEMA = "ds02.f3.macro-input-audit.v1"


def _usage() -> dict[str, float]:
    out: dict[str, float] = {}
    for who, label in ((resource.RUSAGE_SELF, "self"), (resource.RUSAGE_CHILDREN, "children")):
        value = resource.getrusage(who)
        out[f"{label}_user_seconds"] = float(value.ru_utime)
        out[f"{label}_system_seconds"] = float(value.ru_stime)
        out[f"{label}_max_rss_kib"] = float(value.ru_maxrss)
    return out


def _delta(before: dict[str, float], after: dict[str, float]) -> dict[str, float]:
    return {key: float(after[key] - before[key]) for key in after}


def _contiguous_spans(indices: np.ndarray) -> list[tuple[int, int]]:
    """Return half-open contiguous spans for a sorted identity-axis subset."""

    if not len(indices):
        return []
    breaks = np.flatnonzero(np.diff(indices) != 1) + 1
    starts = np.r_[0, breaks]
    stops = np.r_[breaks, len(indices)]
    return [(int(indices[start]), int(indices[stop - 1]) + 1) for start, stop in zip(starts, stops)]


def audit_input(path: Path, *, particle_chunk: int = 65536) -> dict[str, Any]:
    if particle_chunk <= 0:
        raise ValueError("particle_chunk must be positive")
    path = Path(path).resolve()
    before = _usage()
    with h5py.File(path, "r") as h5:
        required = ("initial_type", "valid", "mass", "position", "velocity", "time")
        missing = [name for name in required if name not in h5]
        if missing:
            raise ValueError(f"{path}: missing datasets {missing}")
        initial_type = np.asarray(h5["initial_type"][:])
        fluid = np.flatnonzero(initial_type == 3)
        if not len(fluid):
            raise ValueError(f"{path}: no initial type=3 identities")
        frames, particles = h5["valid"].shape
        if tuple(h5["mass"].shape) != (frames, particles):
            raise ValueError(f"{path}: mass shape does not match valid")
        if tuple(h5["position"].shape) != (frames, particles, 3):
            raise ValueError(f"{path}: position shape does not match valid")
        if tuple(h5["velocity"].shape) != (frames, particles, 3):
            raise ValueError(f"{path}: velocity shape does not match valid")

        counts = {
            "fluid_rows_checked": 0,
            "valid_true_rows": 0,
            "valid_true_nonfinite_mass": 0,
            "valid_true_nonpositive_mass": 0,
            "valid_true_nonfinite_position": 0,
            "valid_true_nonfinite_velocity": 0,
        }
        examples: list[dict[str, Any]] = []
        spans = _contiguous_spans(fluid)
        for frame in range(frames):
            for span_start, span_stop in spans:
                for begin in range(span_start, span_stop, particle_chunk):
                    stop = min(begin + particle_chunk, span_stop)
                    ids = np.arange(begin, stop, dtype=np.int64)
                    # These are contiguous hyperslabs, rather than h5py
                    # point selections.  The identity axis remains explicit.
                    valid = np.asarray(h5["valid"][frame, begin:stop], dtype=bool)
                    mass = np.asarray(h5["mass"][frame, begin:stop], dtype=float)
                    pos = np.asarray(h5["position"][frame, begin:stop, :], dtype=float)
                    vel = np.asarray(h5["velocity"][frame, begin:stop, :], dtype=float)
                    active = valid
                    counts["fluid_rows_checked"] += int(active.size)
                    counts["valid_true_rows"] += int(active.sum())
                    bad_mass_finite = active & ~np.isfinite(mass)
                    bad_mass_positive = active & np.isfinite(mass) & (mass <= 0)
                    bad_pos = active & ~np.isfinite(pos).all(axis=1)
                    bad_vel = active & ~np.isfinite(vel).all(axis=1)
                    counts["valid_true_nonfinite_mass"] += int(bad_mass_finite.sum())
                    counts["valid_true_nonpositive_mass"] += int(bad_mass_positive.sum())
                    counts["valid_true_nonfinite_position"] += int(bad_pos.sum())
                    counts["valid_true_nonfinite_velocity"] += int(bad_vel.sum())
                    bad = bad_mass_finite | bad_mass_positive | bad_pos | bad_vel
                    if np.any(bad) and len(examples) < 8:
                        for local in np.flatnonzero(bad)[: 8 - len(examples)]:
                            examples.append({
                                "frame": frame,
                                "fluid_axis_index": begin + int(local),
                                "particle_index": int(ids[local]),
                                "mass_finite": bool(np.isfinite(mass[local])),
                                "mass_positive": bool(np.isfinite(mass[local]) and mass[local] > 0),
                                "position_finite": bool(np.isfinite(pos[local]).all()),
                                "velocity_finite": bool(np.isfinite(vel[local]).all()),
                            })

    bad_total = sum(
        value for key, value in counts.items()
        if key.startswith("valid_true_") and key != "valid_true_rows" and value
    )
    after = _usage()
    return {
        "schema": SCHEMA,
        "claim_boundary": "macro input finite/positive row audit only; no Q-N or production qualification",
        "path": str(path),
        "bytes": path.stat().st_size,
        "frames": int(frames),
        "particles": int(particles),
        "initial_fluid_particles": int(len(fluid)),
        "particle_chunk": int(particle_chunk),
        "contiguous_identity_spans": [[int(start), int(stop)] for start, stop in spans],
        "read_strategy": "contiguous_hyperslab_slices_over_sorted_initial_fluid_axis",
        "full_trajectory_materialized": False,
        "counts": counts,
        "bad_examples": examples,
        "all_valid_true_fluid_rows_finite_positive": bad_total == 0,
        "status": "pass" if bad_total == 0 else "failed",
        "q_n_status": "not_assessed",
        "resource_usage": _delta(before, after),
    }


def audit_many(paths: Sequence[Path], *, particle_chunk: int = 65536) -> dict[str, Any]:
    if not paths:
        raise ValueError("at least one input HDF5 is required")
    results = [audit_input(Path(path), particle_chunk=particle_chunk) for path in paths]
    return {
        "schema": SCHEMA,
        "claim_boundary": "macro input finite/positive row audit only; no Q-N or production qualification",
        "inputs": results,
        "status": "pass" if all(row["status"] == "pass" for row in results) else "failed",
        "q_n_status": "not_assessed",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", type=Path, required=True)
    parser.add_argument("--particle-chunk", type=int, default=65536)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = audit_many(args.input, particle_chunk=args.particle_chunk)
        args.output = Path(args.output).resolve()
        if args.output.exists():
            raise ValueError(f"refusing to overwrite {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["status"] == "pass" else 2
    except (OSError, ValueError, KeyError) as exc:
        print(f"F3 macro input audit failed: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
