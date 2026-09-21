#!/usr/bin/env python3
"""Read-only support-gate diagnosis for a terminal F4 tall-wall material run.

This tool re-evaluates the frozen baseline24 gate at the saved tracer states
and records the first failure frame, component contributions, and spatial
location.  It never changes the tracer or a threshold and never writes a
ledger.  The numerical material output remains the root-verified input.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import h5py
import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import core_material as cm
from scripts import f4_tallwall120_material as tw


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            h.update(block)
    return h.hexdigest()


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _percentiles(values: np.ndarray) -> dict:
    value = np.asarray(values, dtype=np.float64).reshape(-1)
    finite = value[np.isfinite(value)]
    if not len(finite):
        return {"count": 0, "min": None, "p50": None, "p95": None, "p99": None, "max": None}
    quantiles = np.percentile(finite, [50, 95, 99])
    return {
        "count": int(len(finite)),
        "min": float(np.min(finite)),
        "p50": float(quantiles[0]),
        "p95": float(quantiles[1]),
        "p99": float(quantiles[2]),
        "max": float(np.max(finite)),
    }


def _bool_count(mask: np.ndarray) -> int:
    return int(np.asarray(mask, dtype=bool).sum())


def _component_masks(diag: dict) -> dict[str, np.ndarray]:
    error_limit = float(cm.GATE["maximum_reconstruction_error_mps"])
    return {
        "ess_fail": ~np.isfinite(diag["effective_sample_size"]) | (diag["effective_sample_size"] < float(cm.GATE["minimum_effective_sample_size"])),
        "rank_fail": ~np.isfinite(diag["geometry_rank"]) | (diag["geometry_rank"] < int(cm.GATE["minimum_geometry_rank"])),
        "anisotropy_fail": ~np.isfinite(diag["anisotropy"]) | (diag["anisotropy"] < float(cm.GATE["minimum_anisotropy"])),
        "reconstruction_error_fail": ~np.isfinite(diag["interpolation_reconstruction_error_mps"]) | (diag["interpolation_reconstruction_error_mps"] > error_limit),
    }


def _stage_summary(active: np.ndarray, support_distance: np.ndarray, gate: np.ndarray, diag: dict) -> dict:
    active = np.asarray(active, dtype=bool)
    components = _component_masks(diag)
    return {
        "active_count": _bool_count(active),
        "support_gate_pass_count": _bool_count(active & gate),
        "support_gate_fail_count": _bool_count(active & ~gate),
        "support_distance_m": _percentiles(support_distance[active]),
        "effective_sample_size": _percentiles(diag["effective_sample_size"][active]),
        "geometry_rank": _percentiles(diag["geometry_rank"][active]),
        "anisotropy": _percentiles(diag["anisotropy"][active]),
        "reconstruction_error_mps": _percentiles(diag["interpolation_reconstruction_error_mps"][active]),
        "component_fail_counts": {name: _bool_count(active & mask) for name, mask in components.items()},
        "visible_neighbours": _percentiles(diag["visible_neighbours"][active]),
        "selected_visible_neighbours": _percentiles(diag["selected_visible_neighbours"][active]),
    }


def diagnose(source: Path, trace: Path, output: Path, *, q: float = 0.5, dp_m: float = 0.0075,
             substeps: int = 2, provider_factory=None) -> dict:
    source = Path(source).resolve()
    trace = Path(trace).resolve()
    output = Path(output).resolve()
    definition = tw._tallwall_definition(q, dp_m)
    walls = tw.tallwall_walls()
    seeds = cm.seeds_f4(512, q)
    with h5py.File(trace, "r") as material_h5:
        times = np.asarray(material_h5["time"][:], dtype=np.float64)
        positions = np.asarray(material_h5["position"][:], dtype=np.float64)
        reliable = np.asarray(material_h5["reliable"][:], dtype=bool)
        if positions.shape[1:] != (len(seeds), 3) or reliable.shape != positions.shape[:2]:
            raise ValueError("trace seed axis does not match the registered 512-seed contract")
        trace_binding = json.loads(material_h5.attrs.get("binding", "{}"))
        trace_sha = sha256(trace)

    first_failure_frame = np.full(len(seeds), -1, dtype=np.int64)
    first_failure_position = np.full((len(seeds), 3), np.nan, dtype=np.float64)
    frame_rows = []
    stage_rows = []
    mismatch_rows = []
    initial_summary = None
    make_provider = provider_factory or (lambda path: cm.ReferenceFrames(path, fluid_type=3))
    with make_provider(source) as frames:
        initial_field = frames.field(0, 0.0)
        _, initial_distance, initial_gate, initial_diag = initial_field.sample(
            seeds, walls, neighbours=tw.NEIGHBOURS, regularization=tw.REGULARIZATION_M,
            error_estimator="local_residual", return_diagnostics=True,
        )
        initial_gate &= initial_distance <= tw.MAXIMUM_SUPPORT_DISTANCE_M
        initial_summary = _stage_summary(np.ones(len(seeds), dtype=bool), initial_distance, initial_gate, initial_diag)
        for frame_index in range(len(times) - 1):
            q_position = np.array(positions[frame_index], copy=True)
            active = np.array(reliable[frame_index], copy=True)
            transition = {
                "from_frame": frame_index,
                "to_frame": frame_index + 1,
                "from_time_s": float(times[frame_index]),
                "to_time_s": float(times[frame_index + 1]),
                "input_reliable_count": _bool_count(active),
                "substeps": [],
            }
            dt = (float(times[frame_index + 1]) - float(times[frame_index])) / int(substeps)
            field0 = frames.field(frame_index, 0.0)
            for substep in range(int(substeps)):
                field1 = frames.field(frame_index, (substep + 1) / int(substeps))
                v0, d0, g0, diag0 = field0.sample(
                    q_position, walls, neighbours=tw.NEIGHBOURS,
                    regularization=tw.REGULARIZATION_M, error_estimator="local_residual",
                    return_diagnostics=True,
                )
                predictor = q_position + np.nan_to_num(v0, nan=0.0, posinf=0.0, neginf=0.0) * dt
                v1, d1, g1, diag1 = field1.sample(
                    predictor, walls, neighbours=tw.NEIGHBOURS,
                    regularization=tw.REGULARIZATION_M, error_estimator="local_residual",
                    return_diagnostics=True,
                )
                candidate = q_position + 0.5 * np.nan_to_num(v0 + v1, nan=0.0, posinf=0.0, neginf=0.0) * dt
                blocked = cm.spacetime_swept_wall_blocked(q_position, candidate, walls, walls)
                finite = (np.isfinite(v0).all(axis=1) & np.isfinite(v1).all(axis=1))
                dmax = np.maximum(d0, d1)
                usable = (
                    active & g0 & g1 & ~blocked & finite
                    & (dmax <= tw.MAXIMUM_SUPPORT_DISTANCE_M)
                )
                failing = active & ~usable
                new_failure = failing & (first_failure_frame < 0)
                first_failure_frame[new_failure] = frame_index + 1
                first_failure_position[new_failure] = q_position[new_failure]
                g0_components = _component_masks(diag0)
                g1_components = _component_masks(diag1)
                stage = {
                    "frame": frame_index,
                    "substep": substep,
                    "segment_time_s": float(times[frame_index]) + substep * dt,
                    "active_count": _bool_count(active),
                    "usable_count": _bool_count(usable),
                    "new_failure_count": _bool_count(new_failure),
                    "failure_reason_counts": {
                        "g0_support_gate_fail": _bool_count(active & ~g0),
                        "g1_support_gate_fail": _bool_count(active & ~g1),
                        "distance_gate_fail": _bool_count(active & (dmax > tw.MAXIMUM_SUPPORT_DISTANCE_M)),
                        "wall_blocked": _bool_count(active & blocked),
                        "nonfinite_velocity": _bool_count(active & ~finite),
                        "other": _bool_count(failing & g0 & g1 & ~blocked & finite & (dmax <= tw.MAXIMUM_SUPPORT_DISTANCE_M)),
                    },
                    "g0": _stage_summary(active, d0, g0, diag0),
                    "g1": _stage_summary(active, d1, g1, diag1),
                }
                stage_rows.append(stage)
                transition["substeps"].append(stage)
                q_position = np.where(usable[:, None], candidate, q_position)
                active = usable
                field0 = field1
            transition["output_reliable_count"] = _bool_count(active)
            transition["new_failure_count"] = _bool_count((reliable[frame_index] & ~reliable[frame_index + 1]))
            transition["trace_replay_reliable_match"] = bool(np.array_equal(active, reliable[frame_index + 1]))
            if not transition["trace_replay_reliable_match"]:
                mismatch_rows.append(transition["to_frame"])
            frame_rows.append(transition)

    failure_mask = first_failure_frame >= 0
    histogram = {}
    for frame in np.unique(first_failure_frame[failure_mask]):
        histogram[str(int(frame))] = int(np.sum(first_failure_frame == frame))
    location = first_failure_position[failure_mask]
    failure_location = {
        "count": int(len(location)),
        "x_m": _percentiles(location[:, 0]) if len(location) else _percentiles([]),
        "y_m": _percentiles(location[:, 1]) if len(location) else _percentiles([]),
        "z_m": _percentiles(location[:, 2]) if len(location) else _percentiles([]),
        "minimum_distance_to_interface_m": float(np.min(np.abs(location[:, 2] - tw.INTERFACE_Z_M))) if len(location) else None,
    }
    result = {
        "schema": "core.material.f4.tallwall120.diagnosis.v1",
        "created_at_utc": stamp(),
        "source": {"path": str(source), "sha256": sha256(source)},
        "trace": {"path": str(trace), "sha256": trace_sha, "binding": trace_binding},
        "code": {
            "path": str(Path(__file__).resolve()),
            "sha256": sha256(Path(__file__)),
            "tracer_sha256": sha256(Path(tw.__file__)),
        },
        "provider": {
            "path": str(Path(getattr(frames, "implementation_path", cm.__file__)).resolve()),
            "temporal_interpolation": getattr(frames, "temporal_interpolation", "linear_native_position_velocity"),
            "candidate_id": getattr(frames, "candidate_id", "baseline24"),
        },
        "scope_id": tw.SCOPE_ID,
        "backend": tw.NEIGHBOUR_BACKEND,
        "neighbours": tw.NEIGHBOURS,
        "regularization_m": tw.REGULARIZATION_M,
        "maximum_support_distance_m": tw.MAXIMUM_SUPPORT_DISTANCE_M,
        "support_gate": tw.GATE,
        "wall_definition": definition["wall_bounds_m"],
        "initial_frame": {
            "time_s": float(times[0]),
            "reliable_count": _bool_count(np.ones(len(seeds), dtype=bool)),
            "support": initial_summary,
        },
        "first_failure": {
            "seed_count": int(len(seeds)),
            "failed_seed_count": int(failure_mask.sum()),
            "surviving_seed_count": int((~failure_mask).sum()),
            "frame_histogram": histogram,
            "time_histogram_s": {str(int(frame)): float(times[int(frame)]) for frame in np.unique(first_failure_frame[failure_mask])},
            "location": failure_location,
        },
        "transitions": frame_rows,
        "replay_mismatches": mismatch_rows,
        "interpretation": {
            "thresholds_changed": False,
            "initial_support_passes": bool(initial_gate.all()),
            "first_failure_time_is_saved_frame_upper_bound": True,
            "material_reliability_claim": "uncalibrated",
            "event_claim": "none; this is support diagnosis only",
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".partial")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(output)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--q", type=float, default=0.5)
    parser.add_argument("--dp-m", type=float, default=0.0075)
    parser.add_argument("--substeps", type=int, default=2)
    args = parser.parse_args()
    result = diagnose(args.source, args.trace, args.output, q=args.q, dp_m=args.dp_m, substeps=args.substeps)
    first = result["first_failure"]
    compact = {
        "output": str(args.output.resolve()),
        "code_sha256": result["code"]["sha256"],
        "failed_seed_count": first["failed_seed_count"],
        "surviving_seed_count": first["surviving_seed_count"],
        "frame_histogram": first["frame_histogram"],
        "replay_mismatches": result["replay_mismatches"],
    }
    print(json.dumps(compact, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
