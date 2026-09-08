#!/usr/bin/env python3
"""Re-audit the existing six R6 material bundles without a solver rerun.

This module makes the material evidence source-wise and full-time.  It keeps
first passage, terminal destination, active tracer unknown mass, and support
or interpolation errors as separate quantities.  Two small common-physical
point trajectory groups are optional supplemental diagnostics; they are not a
mass-transport acceptance claim.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import re
import time
from typing import Any, Sequence

import h5py
import numpy as np

try:
    from scripts.boundary_sidecars import sidecar_provider
    from scripts.passive_tracers import advect_hdf5
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from boundary_sidecars import sidecar_provider
    from passive_tracers import advect_hdf5


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "v0.1-candidate"
MATERIAL_ROOT = CAMPAIGN / "artifacts" / "r6-f1-material-task"
REPORT = CAMPAIGN / "r6-n3-material-reference.json"

MEDIUM_H5 = CAMPAIGN / "data" / "r5-f1-solver-gate" / "R4_F1_plain_dam_break_medium.h5"
FINE_H5 = CAMPAIGN / "data" / "r5-f1-solver-gate" / "R4_F1_plain_dam_break_fine.h5"
MEDIUM_SIDECAR = CAMPAIGN / "sidecars" / "r6-n2-height" / "R4_F1_plain_dam_break_medium.h5"
FINE_SIDECAR = CAMPAIGN / "sidecars" / "r6-n2-height" / "R4_F1_plain_dam_break_fine.h5"

SOURCE_LABELS = ("lower", "middle", "upper")
FRAME_STRIDE = 8
COMMON_POINT_COUNT_PER_GROUP = 32


def relpath(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(LAB.resolve()))
    except ValueError:
        return str(Path(path).resolve())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=True) + "\n")
    temporary.replace(path)


def _decode(values: Any) -> np.ndarray:
    values = np.asarray(values)
    return np.asarray([
        value.decode("utf-8") if isinstance(value, (bytes, np.bytes_)) else str(value)
        for value in values.reshape(-1)
    ], dtype=object).reshape(values.shape)


def _max_at_time(values: np.ndarray, times: np.ndarray) -> dict[str, float | None]:
    values = np.asarray(values, dtype=float)
    finite = np.isfinite(values)
    if not finite.any():
        return {"max": None, "time_s": None}
    index = int(np.nanargmax(values))
    return {"max": float(values[index]), "time_s": float(times[index])}


def _source_mass_series(weights: np.ndarray, mask: np.ndarray, labels: np.ndarray, denominators: dict[str, float]) -> dict[str, list[float]]:
    result = {}
    for label in SOURCE_LABELS:
        source = labels == label
        values = np.sum(np.where(mask[:, source], weights[source][None, :], 0.0), axis=1, dtype=np.float64)
        result[label] = (values / max(denominators[label], 1e-30)).tolist()
    return result


def _first_passage_series(first_frame: np.ndarray, labels: np.ndarray, weights: np.ndarray, denominators: dict[str, float], frame_count: int) -> dict[str, list[float]]:
    result = {}
    for label in SOURCE_LABELS:
        source = labels == label
        frames = first_frame[source]
        source_weights = weights[source]
        values = np.asarray([
            np.sum(source_weights[(frames >= 0) & (frames <= frame)], dtype=np.float64)
            / max(denominators[label], 1e-30)
            for frame in range(frame_count)
        ])
        result[label] = values.tolist()
    return result


def _source_scalar_fractions(values: np.ndarray, labels: np.ndarray, weights: np.ndarray, denominators: dict[str, float]) -> dict[str, dict[str, float]]:
    values = _decode(values)
    result = {}
    for label in SOURCE_LABELS:
        source = labels == label
        result[label] = {
            str(category): float(weights[source & (values == category)].sum(dtype=np.float64) / max(denominators[label], 1e-30))
            for category in sorted(set(str(item) for item in values))
        }
    return result


def _bundle_metadata(path: Path) -> tuple[int | None, int | None]:
    match = re.search(r"_seeds(\d+)_substeps(\d+)\.h5$", path.name)
    return (int(match.group(1)), int(match.group(2))) if match else (None, None)


def _bundle_series(path: Path) -> dict[str, Any]:
    seed_count, substeps = _bundle_metadata(path)
    with h5py.File(path, "r") as h5:
        times = np.asarray(h5["time"][:], dtype=np.float64)
        labels = _decode(h5["source_label"][:])
        weights = np.asarray(h5["mass_weight"][:], dtype=np.float64)
        valid = np.asarray(h5["valid"][:], dtype=bool)
        tracer_valid = np.asarray(h5["tracer_valid"][:], dtype=bool)
        solver_valid = np.asarray(h5["solver_identity_valid"][:], dtype=bool)
        in_destination = np.asarray(h5["destination/in_destination"][:], dtype=bool)
        first_frame = np.asarray(h5["destination/first_passage_frame"][:], dtype=np.int64)
        first_status = _decode(h5["destination/first_passage_status"][:])
        terminal = _decode(h5["destination/terminal_category"][:])
        gate_pass = np.asarray(h5["support/gate_pass"][:], dtype=bool)
        support_distance = np.asarray(h5["support/nearest_support_distance"][:], dtype=np.float64)
        failure_reason = _decode(h5["failure/reason"][:])
        first_reason = _decode(h5["failure/first_reason"][:])
        denominators = {
            label: float(weights[labels == label].sum(dtype=np.float64)) for label in SOURCE_LABELS
        }
        target = in_destination & valid
        unknown = ~valid
        solver_unknown = ~solver_valid
        error = failure_reason != "none"
        support_rejected = ~gate_pass
        target_series = _source_mass_series(weights, target, labels, denominators)
        unknown_series = _source_mass_series(weights, unknown, labels, denominators)
        solver_unknown_series = _source_mass_series(weights, solver_unknown, labels, denominators)
        error_series = _source_mass_series(weights, error, labels, denominators)
        support_series = _source_mass_series(weights, support_rejected, labels, denominators)
        first_series = _first_passage_series(first_frame, labels, weights, denominators, len(times))
        final_fractions = _source_scalar_fractions(terminal, labels, weights, denominators)
        passage_fractions = _source_scalar_fractions(first_status, labels, weights, denominators)
        support_times = times[1:] if len(times) > 1 else times
        source_extrema = {}
        for label in SOURCE_LABELS:
            source_extrema[label] = {
                "target_occupancy": _max_at_time(np.asarray(target_series[label]), times),
                "active_tracer_unknown": _max_at_time(np.asarray(unknown_series[label]), times),
                "solver_identity_unknown": _max_at_time(np.asarray(solver_unknown_series[label]), times),
                "error_active": _max_at_time(np.asarray(error_series[label]), support_times),
                "support_gate_rejected": _max_at_time(np.asarray(support_series[label]), support_times),
            }
        first_reason_fractions = _source_scalar_fractions(first_reason, labels, weights, denominators)
        closure = {
            label: float(sum(final_fractions[label].values()) - 1.0) for label in SOURCE_LABELS
        }
        return {
            "config_id": path.stem,
            "bundle": relpath(path),
            "bundle_sha256": sha256(path),
            "seed_count": seed_count,
            "substeps": substeps,
            "frames": int(len(times)),
            "time_start_s": float(times[0]),
            "time_end_s": float(times[-1]),
            "source_mass_kg": denominators,
            "first_passage_status_mass_fractions_by_source": passage_fractions,
            "terminal_category_mass_fractions_by_source": final_fractions,
            "first_failure_reason_mass_fractions_by_source": first_reason_fractions,
            "closure_error_by_source": closure,
            "source_extrema": source_extrema,
            "full_time": {
                "time_s": times.tolist(),
                "interval_time_s": support_times.tolist(),
                "target_occupancy_mass_fraction_by_source": target_series,
                "first_passage_observed_cumulative_mass_fraction_by_source": first_series,
                "active_tracer_unknown_mass_fraction_by_source": unknown_series,
                "solver_identity_unknown_mass_fraction_by_source": solver_unknown_series,
                "error_active_mass_fraction_by_source": error_series,
                "support_gate_rejected_mass_fraction_by_source": support_series,
                "support_distance_max_m": _max_at_time(np.nanmax(support_distance, axis=1), support_times),
            },
            "status": "reported_candidate_only_not_physical_acceptance",
        }


def _find_bundles() -> list[Path]:
    return sorted(MATERIAL_ROOT.glob("*/R4_F1_plain_dam_break_*_seeds*_substeps*.h5"))


def _common_points(h5_paths: Sequence[Path]) -> np.ndarray:
    bounds = []
    for path in h5_paths:
        with h5py.File(path, "r") as h5:
            fluid = np.asarray(h5["valid"][0], dtype=bool) & (np.asarray(h5["type"][0], dtype=np.int8) == 3)
            points = np.asarray(h5["position"][0, fluid], dtype=np.float64)
            bounds.append((points.min(axis=0), points.max(axis=0)))
    lower = np.max(np.asarray([item[0] for item in bounds]), axis=0)
    upper = np.min(np.asarray([item[1] for item in bounds]), axis=0)
    # Keep away from the initial support boundary while retaining one common
    # physical point set for both resolutions.
    lower = lower + 0.10 * (upper - lower)
    upper = upper - 0.10 * (upper - lower)
    axes = [np.linspace(lower[0], upper[0], 4), np.linspace(lower[1], upper[1], 2), np.linspace(lower[2], upper[2], 4)]
    return np.asarray([[x, y, z] for x in axes[0] for y in axes[1] for z in axes[2]], dtype=np.float64)


def _common_point_group(label: str, h5_path: Path, sidecar_path: Path, points: np.ndarray) -> dict[str, Any]:
    started = time.perf_counter()
    barrier = sidecar_provider(sidecar_path)
    particle_spacing_m = 0.024 if label == "medium" else 0.014
    trace = advect_hdf5(
        h5_path, points, neighbours=24, regularization=0.1 * particle_spacing_m,
        maximum_support_distance=1.75 * particle_spacing_m, frame_stride=FRAME_STRIDE,
        substeps_per_interval=1, barrier_provider=barrier,
    )
    position = np.asarray(trace["position"], dtype=np.float64)
    time_axis = np.asarray(trace["time"], dtype=np.float64)
    reliable = np.asarray(trace["reliability_history"], dtype=bool)
    support_gate = np.asarray(trace["support_gate_pass"], dtype=bool)
    crossing = np.asarray(trace["wall_crossing"], dtype=bool)
    sample_indices = np.linspace(0, len(time_axis) - 1, 21).round().astype(int)
    return {
        "group_id": f"common_physical_points_{label}",
        "resolution": label,
        "hdf5": relpath(h5_path),
        "sidecar": relpath(sidecar_path),
        "point_count": int(len(points)),
        "particle_spacing_m": particle_spacing_m,
        "points_sha256": hashlib.sha256(np.ascontiguousarray(points).tobytes()).hexdigest(),
        "frame_stride": FRAME_STRIDE,
        "trajectory_time_count": int(len(time_axis)),
        "time_start_s": float(time_axis[0]),
        "time_end_s": float(time_axis[-1]),
        "reliable_fraction_at_end": float(np.mean(reliable[-1])) if len(reliable) else None,
        "reliable_fraction_min": float(np.min(np.mean(reliable, axis=1))) if reliable.size else None,
        "support_gate_rejection_count": int(np.sum(~support_gate)),
        "wall_crossing_count": int(np.sum(crossing)),
        "support_distance_max_m": float(np.nanmax(trace["nearest_support_distance"])) if np.size(trace["nearest_support_distance"]) else None,
        "position_quantile_x_m_at_fixed_times": {
            str(float(time_axis[index])): {
                "q50": float(np.quantile(position[index, :, 0], 0.50)),
                "q90": float(np.quantile(position[index, :, 0], 0.90)),
            }
            for index in sample_indices
        },
        "status": "supplemental_trajectory_only_not_mass_acceptance",
        "elapsed_seconds": time.perf_counter() - started,
    }


def build_report(*, include_common_points: bool = True) -> dict[str, Any]:
    started = time.perf_counter()
    bundles = _find_bundles()
    configurations = [_bundle_series(path) for path in bundles]
    if include_common_points and MEDIUM_H5.is_file() and FINE_H5.is_file() and MEDIUM_SIDECAR.is_file() and FINE_SIDECAR.is_file():
        points = _common_points((MEDIUM_H5, FINE_H5))
        common_groups = [
            _common_point_group("medium", MEDIUM_H5, MEDIUM_SIDECAR, points),
            _common_point_group("fine", FINE_H5, FINE_SIDECAR, points),
        ]
    else:
        common_groups = [{"status": "blocked_missing_input"}]
    payload = {
        "schema_version": "r6-n3-p3-material-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "execution_status": "completed" if len(configurations) == 6 else "completed_with_findings",
        "acceptance_status": "candidate_t2_numerical_reference_only",
        "formal_material_target_admitted": False,
        "solver_rerun": False,
        "gpu_used": False,
        "source_semantics": {
            "labels": list(SOURCE_LABELS),
            "role": "initial-depth measurement strata, not material identity",
            "cross_resolution_policy": "only common physical point group is compared across resolutions; seed indices are never compared",
        },
        "configuration_count": len(configurations),
        "configurations": configurations,
        "supplemental_common_physical_point_groups": common_groups,
        "definitions": {
            "target_occupancy": "currently valid tracer mass inside downstream_target at each saved frame",
            "first_passage_observed": "cumulative mass whose first valid target frame is at or before the saved frame",
            "active_tracer_unknown": "currently invalid tracer mass; no survivor renormalization",
            "solver_identity_unknown": "currently missing reference solver identity",
            "error_active": "failure/reason is non-none on the saved interval; it is not collapsed into first passage",
            "support_gate_rejected": "support gate is false on the saved interval",
            "terminal_category": "last valid state or tracer_unknown under the frozen censoring contract",
        },
        "open_blockers": [
            "source labels remain measurement strata rather than physical material lineage",
            "T2 remains a numerical reference only; no external/reference anchor was added",
            "support-gate rejection and unknown/error mass remain visible and are not silently removed",
            "common physical point groups are trajectory-only supplemental diagnostics",
        ],
        "elapsed_seconds": time.perf_counter() - started,
    }
    atomic_json(REPORT, payload)
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-common-points", action="store_true")
    args = parser.parse_args(argv)
    payload = build_report(include_common_points=not args.no_common_points)
    print(json.dumps({
        "execution_status": payload["execution_status"],
        "configuration_count": payload["configuration_count"],
        "common_groups": [item.get("group_id", item.get("status")) for item in payload["supplemental_common_physical_point_groups"]],
        "report": relpath(REPORT),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
