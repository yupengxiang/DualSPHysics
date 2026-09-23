"""Read-only one-source-interval counterfactual for R003 wall failures.

This is not a tracer worker and never writes to the historical trace. It
replays each saved first wall-occluded interval with a diagnostic, single-
nearest-wall no-slip-constrained MLS fit and stage-safe RK4 substeps.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import h5py
import numpy as np
from scipy.spatial import cKDTree

from scripts.f3_native_volume_mls import (
    F3ReferenceProvider,
    F3NativeVolumeMLS,
    F3_ORIGINAL_GATE,
    _segment_visibility,
    f3_walls,
    sha256_file,
    wendland_quintic_c2_3d,
)


EXPECTED_SOURCE_SHA256 = "fb304e0bc8e5d7f51eaab0af0d8dba8c928b8146e0bf5776002f83012e4480c4"
EXPECTED_TRACE_SHA256 = "10e5219d6821d8963a82e068135f078a696a5a111fbd79f598408508c3799366"
EXPECTED_BACKEND_SHA256 = "e1c5fc39e73781d386c7da2874c1749b5223c8209eaf8f25bb4453346df51ff9"
SOURCE_DEFAULT = Path(
    "campaigns/l1-resume/data/continuation/"
    "F3_CELL3_LONG_dp0p0075_a1p000_noslip_visco1_nopen.h5"
)
TRACE_DEFAULT = Path(
    "campaigns/core-v1/runtime/attempts/f3-material-30-canonical-s4-r003/"
    "20260923T105621-d33cb17f4735/trace.h5"
)

LOW = np.array([-0.45, -0.09, 0.0], dtype=np.float64)
HIGH = np.array([0.45, 0.09, 0.51], dtype=np.float64)
CLOSED_FACES = (
    ("xmin", 0, LOW[0], -1.0),
    ("xmax", 0, HIGH[0], 1.0),
    ("ymin", 1, LOW[1], -1.0),
    ("ymax", 1, HIGH[1], 1.0),
    ("zmin", 2, LOW[2], -1.0),
)


def _decode(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _inside_closed_domain(point: np.ndarray) -> bool:
    return bool(
        LOW[0] <= point[0] <= HIGH[0]
        and LOW[1] <= point[1] <= HIGH[1]
        and point[2] >= LOW[2]
    )


def _nearest_closed_face(point: np.ndarray) -> tuple[str, np.ndarray, np.ndarray, float]:
    choices = []
    for name, axis, value, sign in CLOSED_FACES:
        foot = np.array(point, dtype=np.float64, copy=True)
        foot[axis] = value
        for other in range(3):
            if other != axis:
                foot[other] = np.clip(foot[other], LOW[other], HIGH[other])
        normal = np.zeros(3, dtype=np.float64)
        normal[axis] = sign
        choices.append((float(np.linalg.norm(point - foot)), name, foot, normal))
    distance, name, foot, normal = min(choices, key=lambda item: item[0])
    return name, foot, normal, distance


def _constrained_velocity(
    query: np.ndarray,
    frame,
    tracer: F3NativeVolumeMLS,
    walls: np.ndarray,
) -> dict:
    """Use the native support and add u(nearest closed-wall foot)=0."""
    raw = tracer.reconstruct(query[None, :], frame, walls)
    if not raw.reliable[0]:
        return {
            "ok": False,
            "reason": str(raw.failure_reason[0]),
            "raw_result": raw,
        }
    face, foot, normal, wall_distance = _nearest_closed_face(query)
    if wall_distance > 2.0 * tracer.h_m:
        return {
            "ok": True,
            "velocity": raw.velocity[0],
            "raw_velocity": raw.velocity[0],
            "face": None,
            "normal": normal,
            "wall_distance_m": wall_distance,
            "fit_residual_mps": float(raw.reconstruction_error_mps[0]),
            "raw_fit_residual_mps": float(raw.reconstruction_error_mps[0]),
            "raw_result": raw,
        }

    tree = cKDTree(frame.position)
    pool = np.asarray(
        tree.query_ball_point(query, r=2.0 * tracer.h_m, p=2.0, eps=0.0,
                              workers=1, return_sorted=True),
        dtype=np.int64,
    )
    if not len(pool):
        return {"ok": False, "reason": "no_support", "raw_result": raw}
    visible = _segment_visibility(query, frame.position[pool], walls)
    pool = pool[visible]
    if not len(pool):
        return {"ok": False, "reason": "wall_occluded", "raw_result": raw}
    delta = frame.position[pool] - query
    distance = np.linalg.norm(delta, axis=1)
    weights = (frame.mass[pool] / frame.density[pool]) * wendland_quintic_c2_3d(
        distance, tracer.h_m
    )
    keep = np.isfinite(weights) & (weights > 0.0)
    pool, delta, weights = pool[keep], delta[keep], weights[keep]
    design = np.column_stack((np.ones(len(pool)), delta / tracer.h_m))
    sqrt_w = np.sqrt(weights)
    weighted_design = design * sqrt_w[:, None]
    weighted_values = frame.velocity[pool] * sqrt_w[:, None]
    constraint = np.concatenate(([1.0], (foot - query) / tracer.h_m))

    hessian = weighted_design.T @ weighted_design
    rhs = weighted_design.T @ weighted_values
    kkt = np.zeros((5, 5), dtype=np.float64)
    kkt[:4, :4] = hessian
    kkt[:4, 4] = constraint
    kkt[4, :4] = constraint
    kkt_rhs = np.vstack((rhs, np.zeros((1, 3), dtype=np.float64)))
    try:
        coefficients = np.linalg.solve(kkt, kkt_rhs)[:4]
    except np.linalg.LinAlgError:
        return {"ok": False, "reason": "constrained_kkt_singular", "raw_result": raw}

    residual = design @ coefficients - frame.velocity[pool]
    total_weight = float(np.sum(weights))
    fit_residual = float(
        np.sqrt(np.sum(weights[:, None] * residual**2) / total_weight)
    )
    raw_match_error = float(np.max(np.abs(raw.velocity[0] -
                                         np.linalg.lstsq(
                                             weighted_design, weighted_values,
                                             rcond=float(tracer.gate["svd_relative_cutoff"]),
                                         )[0][0])))
    return {
        "ok": True,
        "velocity": coefficients[0],
        "raw_velocity": raw.velocity[0],
        "face": face,
        "normal": normal,
        "wall_distance_m": wall_distance,
        "fit_residual_mps": fit_residual,
        "raw_fit_residual_mps": float(raw.reconstruction_error_mps[0]),
        "raw_match_error_mps": raw_match_error,
        "support_count": int(len(pool)),
        "effective_sample_size": float(total_weight**2 / np.sum(weights**2)),
        "raw_result": raw,
    }


def _trial(q: np.ndarray, step_s: float, evaluate, *, guard_domain: bool) -> dict:
    values = []
    locations = []
    stages = ("k1", "k2", "k3", "k4")
    query = q
    for index, stage in enumerate(stages):
        if guard_domain and not _inside_closed_domain(query):
            return {"ok": False, "reason": "stage_outside_domain", "stage": stage,
                    "query": query, "locations": locations, "values": values}
        item = evaluate(query)
        if not item["ok"]:
            return {"ok": False, "reason": item["reason"], "stage": stage,
                    "query": query, "locations": locations, "values": values}
        values.append(item)
        locations.append(query.copy())
        velocity = item["velocity"]
        if index == 0:
            query = q + 0.5 * step_s * velocity
        elif index == 1:
            query = q + 0.5 * step_s * velocity
        elif index == 2:
            query = q + step_s * velocity
    candidate = q + (step_s / 6.0) * (
        values[0]["velocity"] + 2.0 * values[1]["velocity"]
        + 2.0 * values[2]["velocity"] + values[3]["velocity"]
    )
    if guard_domain and not _inside_closed_domain(candidate):
        return {"ok": False, "reason": "endpoint_outside_domain", "stage": "candidate",
                "query": candidate, "candidate": candidate, "locations": locations,
                "values": values}
    return {"ok": True, "candidate": candidate, "locations": locations, "values": values}


def _baseline_first_failure(
    q: np.ndarray,
    frame,
    tracer: F3NativeVolumeMLS,
    walls: np.ndarray,
    step_s: float,
    substeps: int,
) -> dict:
    start = np.array(q, copy=True)
    for substep in range(substeps):
        trial = _trial(
            start,
            step_s,
            lambda point: _raw_evaluate(point, frame, tracer, walls),
            guard_domain=False,
        )
        if not trial["ok"]:
            return {
                **trial,
                "substep": substep,
                "substep_start": start,
                "step_s": step_s,
            }
        start = trial["candidate"]
    return {"ok": True, "substep_start": start}


def _raw_evaluate(query: np.ndarray, frame, tracer, walls) -> dict:
    result = tracer.reconstruct(query[None, :], frame, walls)
    if not result.reliable[0]:
        return {"ok": False, "reason": str(result.failure_reason[0]), "raw_result": result}
    return {
        "ok": True,
        "velocity": result.velocity[0],
        "raw_velocity": result.velocity[0],
        "raw_result": result,
    }


def _adaptive_remainder(
    q: np.ndarray,
    duration_s: float,
    base_step_s: float,
    frame,
    tracer: F3NativeVolumeMLS,
    walls: np.ndarray,
    *,
    max_halvings: int = 12,
    max_accepted_steps: int = 128,
) -> dict:
    state = np.array(q, copy=True)
    remaining = float(duration_s)
    accepted = 0
    rejected = 0
    min_accepted_step = float("inf")
    max_residual = 0.0
    max_raw_residual = 0.0
    old_gate_residual_exceedances = 0
    constrained_gate_failed = False
    max_raw_match_error = 0.0
    constrained_evaluations = 0
    constrained_outward_evaluations = 0
    face_counts: Counter = Counter()
    time_tolerance = max(1e-14, duration_s * 1e-12)
    while remaining > time_tolerance and accepted < max_accepted_steps:
        step_s = min(base_step_s, remaining)
        for level in range(max_halvings + 1):
            stage_items = []

            def evaluate(point):
                item = _constrained_velocity(point, frame, tracer, walls)
                if item["ok"] and item.get("face") is not None:
                    stage_items.append(item)
                return item

            trial = _trial(state, step_s, evaluate, guard_domain=True)
            if trial["ok"]:
                state = trial["candidate"]
                remaining = max(0.0, remaining - step_s)
                accepted += 1
                min_accepted_step = min(min_accepted_step, step_s)
                for item in stage_items:
                    constrained_evaluations += 1
                    face_counts[item["face"]] += 1
                    max_residual = max(max_residual, item["fit_residual_mps"])
                    max_raw_residual = max(max_raw_residual,
                                           item["raw_fit_residual_mps"])
                    if (item["fit_residual_mps"]
                            > F3_ORIGINAL_GATE["maximum_reconstruction_error_mps"]):
                        old_gate_residual_exceedances += 1
                        constrained_gate_failed = True
                    max_raw_match_error = max(
                        max_raw_match_error, item.get("raw_match_error_mps", 0.0)
                    )
                    normal_speed = float(np.dot(item["velocity"], item["normal"]))
                    if normal_speed > 0.0:
                        constrained_outward_evaluations += 1
                break
            rejected += 1
            # A k1 support failure is fixed at the unchanged state; shrinking
            # dt cannot make that reconstruction reliable.
            if trial.get("stage") == "k1" and trial.get("reason") not in (
                "stage_outside_domain", "endpoint_outside_domain"
            ):
                return {
                    "status": "fail_closed",
                    "reason": trial["reason"],
                    "stage": trial.get("stage"),
                    "state": state,
                    "elapsed_s": duration_s - remaining,
                    "accepted_steps": accepted,
                    "rejected_trials": rejected,
                }
            step_s *= 0.5
        else:
            return {
                "status": "fail_closed",
                "reason": trial["reason"],
                "stage": trial.get("stage"),
                "state": state,
                "elapsed_s": duration_s - remaining,
                "accepted_steps": accepted,
                "rejected_trials": rejected,
            }
    if accepted >= max_accepted_steps and remaining > time_tolerance:
        status, reason = "fail_closed", "accepted_step_cap"
    else:
        status, reason = "completed", None
    return {
        "status": status,
        "reason": reason,
        "state": state,
        "elapsed_s": duration_s - remaining,
        "accepted_steps": accepted,
        "rejected_trials": rejected,
        "minimum_accepted_step_s": None if not accepted else min_accepted_step,
        "constrained_evaluations": constrained_evaluations,
        "constrained_outward_evaluations": constrained_outward_evaluations,
        "face_evaluation_counts": dict(face_counts),
        "maximum_constrained_fit_residual_mps": max_residual,
        "maximum_raw_fit_residual_mps": max_raw_residual,
        "original_f3_residual_gate_mps": float(
            F3_ORIGINAL_GATE["maximum_reconstruction_error_mps"]
        ),
        "constrained_original_f3_residual_gate_exceedances": old_gate_residual_exceedances,
        "constrained_original_f3_residual_gate_failed": constrained_gate_failed,
        "maximum_raw_fit_match_error_mps": max_raw_match_error,
    }


def replay(source: Path, trace: Path) -> dict:
    backend_path = Path(__file__).with_name("f3_native_volume_mls.py")
    backend_sha = sha256_file(backend_path)
    if backend_sha != EXPECTED_BACKEND_SHA256:
        raise ValueError(f"registered F3 backend hash mismatch: {backend_sha}")
    trace_sha = sha256_file(trace)
    if trace_sha != EXPECTED_TRACE_SHA256:
        raise ValueError(f"R003 trace hash mismatch: {trace_sha}")

    tracer = F3NativeVolumeMLS(0.01194127788262211)
    walls = f3_walls()
    grouped: dict[int, list[dict]] = defaultdict(list)
    with h5py.File(trace, "r") as handle:
        unknown = np.asarray(handle["permanent_unknown"], dtype=bool)
        final_reason = [_decode(v) for v in handle["failure_reason"][-1]]
        trace_times = np.asarray(handle["time"], dtype=np.float64)
        for seed in np.flatnonzero(np.asarray(final_reason) == "wall_occluded"):
            rows = np.flatnonzero(unknown[:, seed])
            if not len(rows) or rows[0] == 0:
                raise ValueError(f"missing first unknown row for seed {seed}")
            output_row = int(rows[0])
            grouped[output_row - 1].append({
                "seed": int(seed),
                "output_row": output_row,
                "q": np.asarray(handle["position"][output_row - 1, seed], dtype=np.float64),
                "source_label": int(handle["source_label"][seed]),
            })
        if sum(map(len, grouped.values())) != 40:
            raise ValueError("expected exactly 40 terminal wall_occluded seeds")

    results = []
    source_failures = Counter()
    candidate_status = Counter()
    candidate_reasons = Counter()
    candidate_faces = Counter()
    baseline_faces = Counter()
    with F3ReferenceProvider(source, max_cache=1) as provider:
        if provider.source_sha256 != EXPECTED_SOURCE_SHA256:
            raise ValueError(f"R003 source hash mismatch: {provider.source_sha256}")
        if len(provider.times) != len(trace_times) or not np.allclose(
            provider.times, trace_times, atol=1e-12, rtol=0.0
        ):
            raise ValueError("trace and CFD source time axes do not match")
        for source_index in sorted(grouped):
            frame = provider.frame(source_index)
            total_dt = float(provider.times[source_index + 1] - provider.times[source_index])
            base_dt = total_dt / 4.0
            for record in sorted(grouped[source_index], key=lambda item: item["seed"]):
                baseline = _baseline_first_failure(
                    record["q"], frame, tracer, walls, base_dt, substeps=4
                )
                if baseline["ok"] or baseline["reason"] != "wall_occluded":
                    raise ValueError(
                        f"seed {record['seed']} baseline replay mismatch: "
                        f"{baseline.get('reason')}"
                    )
                source_failures[baseline["stage"]] += 1
                baseline_face, _, _, _ = _nearest_closed_face(baseline["query"])
                baseline_faces[baseline_face] += 1
                remaining = total_dt - baseline["substep"] * base_dt
                candidate = _adaptive_remainder(
                    baseline["substep_start"], remaining, base_dt,
                    frame, tracer, walls,
                )
                candidate_status[candidate["status"]] += 1
                if candidate.get("reason"):
                    candidate_reasons[candidate["reason"]] += 1
                candidate_faces.update(candidate.get("face_evaluation_counts", {}))
                face, _, normal, wall_distance = _nearest_closed_face(baseline["query"])
                candidate_record = dict(candidate)
                candidate_record["state"] = np.asarray(candidate["state"]).tolist()
                results.append({
                    "seed": record["seed"],
                    "source_label": record["source_label"],
                    "output_row": record["output_row"],
                    "source_frame": source_index,
                    "baseline_substep": baseline["substep"],
                    "baseline_failed_stage": baseline["stage"],
                    "baseline_failed_query_wall_face": face,
                    "baseline_failed_query_wall_distance_m": wall_distance,
                    "baseline_query_outward_normal_speed_mps": float(
                        np.dot(baseline["values"][-1]["velocity"], normal)
                    ),
                    "candidate_remaining_interval": candidate_record,
                })

    return {
        "schema": "f3_r003_noslip_constrained_first_failure_replay_v1",
        "source_sha256": EXPECTED_SOURCE_SHA256,
        "trace_sha256": EXPECTED_TRACE_SHA256,
        "backend_sha256": EXPECTED_BACKEND_SHA256,
        "candidate_backend_modified": False,
        "historical_trace_modified": False,
        "worker_solver_gpu_queue_started": False,
        "seed_count": len(results),
        "unique_source_frame_count": len(grouped),
        "baseline_failure_stage_counts": dict(source_failures),
        "counterfactual_interval_integrator_status_counts": dict(candidate_status),
        "candidate_failure_reason_counts": dict(candidate_reasons),
        "candidate_constrained_wall_face_evaluation_counts": dict(candidate_faces),
        "baseline_failed_query_wall_face_counts": dict(baseline_faces),
        "counterfactual_accepted_step_counts": dict(Counter(
            str(record["candidate_remaining_interval"].get("accepted_steps", 0))
            for record in results
        )),
        "counterfactual_rejected_trial_total": sum(
            int(record["candidate_remaining_interval"].get("rejected_trials", 0))
            for record in results
        ),
        "counterfactual_constrained_evaluations_total": sum(
            int(record["candidate_remaining_interval"].get(
                "constrained_evaluations", 0
            )) for record in results
        ),
        "counterfactual_seeds_with_original_residual_gate_failure": sum(
            bool(record["candidate_remaining_interval"].get(
                "constrained_original_f3_residual_gate_failed", False
            )) for record in results
        ),
        "counterfactual_constrained_outward_evaluations": sum(
            int(record["candidate_remaining_interval"].get(
                "constrained_outward_evaluations", 0
            )) for record in results
        ),
        "counterfactual_constrained_fit_residual_max_mps": max(
            float(record["candidate_remaining_interval"].get(
                "maximum_constrained_fit_residual_mps", 0.0
            )) for record in results
        ),
        "counterfactual_raw_fit_residual_max_mps": max(
            float(record["candidate_remaining_interval"].get(
                "maximum_raw_fit_residual_mps", 0.0
            )) for record in results
        ),
        "original_f3_residual_gate_mps": float(
            F3_ORIGINAL_GATE["maximum_reconstruction_error_mps"]
        ),
        "counterfactual_residual_gate_exceedance_total": sum(
            int(record["candidate_remaining_interval"].get(
                "constrained_original_f3_residual_gate_exceedances", 0
            )) for record in results
        ),
        "counterfactual_max_raw_fit_match_error_mps": max(
            float(record["candidate_remaining_interval"].get(
                "maximum_raw_fit_match_error_mps", 0.0
            )) for record in results
        ),
        "records": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_DEFAULT)
    parser.add_argument("--trace", type=Path, default=TRACE_DEFAULT)
    parser.add_argument("--include-records", action="store_true")
    args = parser.parse_args()
    result = replay(args.source, args.trace)
    if not args.include_records:
        result.pop("records")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
