"""Read-only boundary-layer and time-refinement diagnostics for R003 failures.

This bounded sweep revisits only the 40 saved first wall-occluded intervals.
It reads frozen source/trace HDF5 inputs and prints diagnostics; it never
updates a trace, starts a worker, or changes an F3 acceptance gate.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import h5py
import numpy as np

from scripts.f3_native_volume_mls import (
    F3_ORIGINAL_GATE,
    F3NativeVolumeMLS,
    F3ReferenceProvider,
    f3_walls,
    sha256_file,
)
from scripts.f3_r003_noslip_constrained_first_failure_replay_v1 import (
    EXPECTED_BACKEND_SHA256,
    EXPECTED_SOURCE_SHA256,
    EXPECTED_TRACE_SHA256,
    SOURCE_DEFAULT,
    TRACE_DEFAULT,
    _adaptive_remainder,
    _baseline_first_failure,
    _constrained_velocity,
    _decode,
    _nearest_closed_face,
)


H_M = 0.01194127788262211
TIME_REFINEMENT_FACTORS = (1, 2, 4, 8, 16)
BOUNDARY_OFFSETS_H = (0.25, 0.5, 1.0, 1.5, 1.9)


def _finite_or_none(value) -> float | None:
    number = float(value)
    return number if np.isfinite(number) else None


def _mls_diagnostic(result, row: int = 0) -> dict:
    velocity = np.asarray(result.velocity[row], dtype=np.float64)
    return {
        "reliable": bool(result.reliable[row]),
        "failure_reason": str(result.failure_reason[row]),
        "velocity_mps": velocity.tolist() if np.isfinite(velocity).all() else None,
        "speed_mps": _finite_or_none(np.linalg.norm(velocity)),
        "support_count": int(result.support_count[row]),
        "candidate_count": int(result.candidate_count[row]),
        "wall_rejected_count": int(result.wall_rejected_count[row]),
        "effective_sample_size": _finite_or_none(result.effective_sample_size[row]),
        "geometry_rank": int(result.geometry_rank[row]),
        "condition_number": _finite_or_none(result.condition_number[row]),
        "residual_mps": _finite_or_none(result.reconstruction_error_mps[row]),
    }


def _boundary_layer_profile(query: np.ndarray, frame, tracer, walls: np.ndarray) -> dict:
    """Compare raw field extrapolation at the wall with interior constrained fits."""
    face, foot, outward_normal, wall_distance = _nearest_closed_face(query)
    wall_fit = tracer.reconstruct(foot[None, :], frame, walls)
    wall_diag = _mls_diagnostic(wall_fit)
    if wall_diag["velocity_mps"] is None:
        wall_normal_speed = None
        wall_tangent_speed = None
    else:
        velocity = np.asarray(wall_diag["velocity_mps"], dtype=np.float64)
        wall_normal_speed = float(np.dot(velocity, outward_normal))
        tangent = velocity - wall_normal_speed * outward_normal
        wall_tangent_speed = float(np.linalg.norm(tangent))

    offsets = []
    for offset_h in BOUNDARY_OFFSETS_H:
        distance = offset_h * tracer.h_m
        inward_query = foot - outward_normal * distance
        item = _constrained_velocity(inward_query, frame, tracer, walls)
        raw_diag = _mls_diagnostic(item["raw_result"])
        record = {
            "offset_h": offset_h,
            "query": inward_query.tolist(),
            "inside_nearest_wall_distance_m": float(distance),
            "raw_fit": raw_diag,
        }
        if item["ok"]:
            constrained_velocity = np.asarray(item["velocity"], dtype=np.float64)
            normal_speed = float(np.dot(constrained_velocity, outward_normal))
            record.update({
                "constrained_fit_available": True,
                "constrained_velocity_mps": constrained_velocity.tolist(),
                "constrained_speed_mps": float(np.linalg.norm(constrained_velocity)),
                "constrained_normal_speed_mps": normal_speed,
                "constrained_tangent_speed_mps": float(np.linalg.norm(
                    constrained_velocity - normal_speed * outward_normal
                )),
                "constrained_residual_mps": float(item["fit_residual_mps"]),
                "support_count": int(item.get("support_count", 0)),
                "effective_sample_size": _finite_or_none(
                    item.get("effective_sample_size", np.nan)
                ),
            })
        else:
            record.update({
                "constrained_fit_available": False,
                "constrained_failure_reason": str(item["reason"]),
            })
        offsets.append(record)

    return {
        "face": face,
        "original_query_wall_distance_m": float(wall_distance),
        "foot": foot.tolist(),
        "prescribed_stationary_wall_velocity_mps": [0.0, 0.0, 0.0],
        "unconstrained_mls_at_wall_foot": wall_diag,
        "unconstrained_wall_normal_speed_mps": wall_normal_speed,
        "unconstrained_wall_tangent_speed_mps": wall_tangent_speed,
        "offsets": offsets,
    }


def _time_refinement(q: np.ndarray, duration_s: float, native_dt_s: float,
                     frame, tracer, walls: np.ndarray) -> list[dict]:
    results = []
    for factor in TIME_REFINEMENT_FACTORS:
        candidate = _adaptive_remainder(
            q,
            duration_s,
            native_dt_s / (4.0 * factor),
            frame,
            tracer,
            walls,
            max_halvings=12,
            max_accepted_steps=256,
        )
        state = np.asarray(candidate["state"], dtype=np.float64)
        results.append({
            "refinement_factor": factor,
            "status": str(candidate["status"]),
            "reason": candidate.get("reason"),
            "state": state.tolist() if np.isfinite(state).all() else None,
            "elapsed_s": _finite_or_none(candidate.get("elapsed_s", np.nan)),
            "accepted_steps": int(candidate.get("accepted_steps", 0)),
            "rejected_trials": int(candidate.get("rejected_trials", 0)),
            "minimum_accepted_step_s": _finite_or_none(
                candidate.get("minimum_accepted_step_s", np.nan)
            ),
            "constrained_evaluations": int(candidate.get("constrained_evaluations", 0)),
            "constrained_outward_evaluations": int(
                candidate.get("constrained_outward_evaluations", 0)
            ),
            "maximum_constrained_fit_residual_mps": _finite_or_none(
                candidate.get("maximum_constrained_fit_residual_mps", np.nan)
            ),
            "residual_gate_exceedances": int(candidate.get(
                "constrained_original_f3_residual_gate_exceedances", 0
            )),
            "residual_gate_failed": bool(candidate.get(
                "constrained_original_f3_residual_gate_failed", False
            )),
        })
    return results


def _time_summary(records: list[dict]) -> dict:
    by_factor: dict[int, list[dict]] = defaultdict(list)
    for record in records:
        for result in record["time_refinement"]:
            by_factor[int(result["refinement_factor"])].append(result)

    factor_summary = {}
    endpoint_errors = {}
    for factor in TIME_REFINEMENT_FACTORS:
        trials = by_factor[factor]
        factor_summary[str(factor)] = {
            "status_counts": dict(Counter(item["status"] for item in trials)),
            "seeds_with_residual_gate_failure": sum(
                item["residual_gate_failed"] for item in trials
            ),
            "residual_gate_exceedance_total": sum(
                item["residual_gate_exceedances"] for item in trials
            ),
            "constrained_outward_evaluation_total": sum(
                item["constrained_outward_evaluations"] for item in trials
            ),
            "maximum_constrained_residual_mps": max(
                (item["maximum_constrained_fit_residual_mps"] or 0.0 for item in trials),
                default=0.0,
            ),
            "accepted_step_count_max": max(
                (item["accepted_steps"] for item in trials), default=0
            ),
        }

    reference_factor = max(TIME_REFINEMENT_FACTORS)
    reference = {
        record["seed"]: result
        for record in records
        for result in record["time_refinement"]
        if result["refinement_factor"] == reference_factor
    }
    for factor in TIME_REFINEMENT_FACTORS[:-1]:
        differences = []
        for record in records:
            current = next(
                item for item in record["time_refinement"]
                if item["refinement_factor"] == factor
            )
            fine = reference[record["seed"]]
            if current["status"] == fine["status"] == "completed":
                differences.append(float(np.linalg.norm(
                    np.asarray(current["state"]) - np.asarray(fine["state"])
                )))
        endpoint_errors[str(factor)] = {
            "compared_seed_count": len(differences),
            "max_distance_to_factor_16_endpoint_m": max(differences, default=None),
            "rms_distance_to_factor_16_endpoint_m": (
                float(np.sqrt(np.mean(np.square(differences)))) if differences else None
            ),
        }
    return {"by_refinement_factor": factor_summary,
            "endpoint_difference_vs_factor_16": endpoint_errors}


def _boundary_summary(records: list[dict]) -> dict:
    profiles = [record["boundary_layer"] for record in records]
    wall_fits = [profile["unconstrained_mls_at_wall_foot"] for profile in profiles]
    available = [fit for fit in wall_fits if fit["reliable"] and fit["speed_mps"] is not None]
    result = {
        "nearest_face_counts": dict(Counter(profile["face"] for profile in profiles)),
        "raw_wall_foot_reliable_count": len(available),
        "raw_wall_foot_unreliable_count": len(records) - len(available),
        "raw_wall_foot_speed_max_mps": max(
            (fit["speed_mps"] for fit in available), default=None
        ),
        "raw_wall_foot_speed_median_mps": (
            float(np.median([fit["speed_mps"] for fit in available]))
            if available else None
        ),
        "raw_wall_foot_residual_max_mps": max(
            (fit["residual_mps"] for fit in available
             if fit["residual_mps"] is not None), default=None
        ),
        "offsets": {},
    }
    for index, offset_h in enumerate(BOUNDARY_OFFSETS_H):
        rows = [profile["offsets"][index] for profile in profiles]
        fitted = [row for row in rows if row["constrained_fit_available"]]
        speeds = [row["constrained_speed_mps"] for row in fitted]
        residuals = [row["constrained_residual_mps"] for row in fitted]
        gate = float(F3_ORIGINAL_GATE["maximum_reconstruction_error_mps"])
        result["offsets"][str(offset_h)] = {
            "fit_available_count": len(fitted),
            "failure_reason_counts": dict(Counter(
                row["constrained_failure_reason"] for row in rows
                if not row["constrained_fit_available"]
            )),
            "constrained_speed_max_mps": max(speeds, default=None),
            "constrained_speed_median_mps": (
                float(np.median(speeds)) if speeds else None
            ),
            "residual_max_mps": max(residuals, default=None),
            "residual_gate_exceedance_count": sum(value > gate for value in residuals),
            "outward_normal_query_count": sum(
                row.get("constrained_normal_speed_mps", 0.0) > 0.0 for row in fitted
            ),
        }
    return result


def sweep(source: Path, trace: Path, *, include_records: bool = False) -> dict:
    backend_path = Path(__file__).with_name("f3_native_volume_mls.py")
    if sha256_file(backend_path) != EXPECTED_BACKEND_SHA256:
        raise ValueError("registered F3 backend hash mismatch")
    if sha256_file(trace) != EXPECTED_TRACE_SHA256:
        raise ValueError("R003 trace hash mismatch")

    grouped: dict[int, list[dict]] = defaultdict(list)
    with h5py.File(trace, "r") as handle:
        trace_times = np.asarray(handle["time"], dtype=np.float64)
        unknown = np.asarray(handle["permanent_unknown"], dtype=bool)
        final_reason = [_decode(value) for value in handle["failure_reason"][-1]]
        for seed in np.flatnonzero(np.asarray(final_reason) == "wall_occluded"):
            rows = np.flatnonzero(unknown[:, seed])
            if not len(rows) or rows[0] == 0:
                raise ValueError(f"missing first unknown row for seed {seed}")
            output_row = int(rows[0])
            grouped[output_row - 1].append({
                "seed": int(seed),
                "output_row": output_row,
                "q": np.asarray(handle["position"][output_row - 1, seed], dtype=np.float64),
            })
    if sum(map(len, grouped.values())) != 40:
        raise ValueError("expected exactly 40 terminal wall_occluded seeds")

    tracer = F3NativeVolumeMLS(H_M)
    walls = f3_walls()
    records = []
    with F3ReferenceProvider(source, max_cache=1) as provider:
        if provider.source_sha256 != EXPECTED_SOURCE_SHA256:
            raise ValueError("R003 source hash mismatch")
        if len(provider.times) != len(trace_times) or not np.allclose(
            provider.times, trace_times, atol=1e-12, rtol=0.0
        ):
            raise ValueError("trace and CFD source time axes do not match")
        for source_index in sorted(grouped):
            frame = provider.frame(source_index)
            native_dt = float(provider.times[source_index + 1] - provider.times[source_index])
            base_dt = native_dt / 4.0
            for row in sorted(grouped[source_index], key=lambda item: item["seed"]):
                baseline = _baseline_first_failure(
                    row["q"], frame, tracer, walls, base_dt, substeps=4
                )
                if baseline["ok"] or baseline["reason"] != "wall_occluded":
                    raise ValueError(f"seed {row['seed']} baseline no longer replays")
                duration = native_dt - int(baseline["substep"]) * base_dt
                records.append({
                    "seed": row["seed"],
                    "output_row": row["output_row"],
                    "source_frame": source_index,
                    "baseline_failed_stage": str(baseline["stage"]),
                    "baseline_failed_query": np.asarray(baseline["query"]).tolist(),
                    "boundary_layer": _boundary_layer_profile(
                        np.asarray(baseline["query"], dtype=np.float64),
                        frame, tracer, walls,
                    ),
                    "time_refinement": _time_refinement(
                        np.asarray(baseline["substep_start"], dtype=np.float64),
                        duration, native_dt, frame, tracer, walls,
                    ),
                })

    output = {
        "schema": "f3_r003_noslip_refinement_sweep_v1",
        "source_sha256": EXPECTED_SOURCE_SHA256,
        "trace_sha256": EXPECTED_TRACE_SHA256,
        "backend_sha256": EXPECTED_BACKEND_SHA256,
        "seed_count": len(records),
        "unique_source_frame_count": len(grouped),
        "time_refinement_factors": list(TIME_REFINEMENT_FACTORS),
        "boundary_offsets_h": list(BOUNDARY_OFFSETS_H),
        "original_f3_residual_gate_mps": float(
            F3_ORIGINAL_GATE["maximum_reconstruction_error_mps"]
        ),
        "time_refinement_summary": _time_summary(records),
        "boundary_layer_summary": _boundary_summary(records),
        "historical_trace_modified": False,
        "registered_backend_modified": False,
        "worker_solver_gpu_queue_started": False,
        "qualification_credit": 0,
        "t2_credit": 0,
    }
    if include_records:
        output["records"] = records
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_DEFAULT)
    parser.add_argument("--trace", type=Path, default=TRACE_DEFAULT)
    parser.add_argument("--include-records", action="store_true")
    args = parser.parse_args()
    print(json.dumps(sweep(args.source, args.trace, include_records=args.include_records),
                     indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
