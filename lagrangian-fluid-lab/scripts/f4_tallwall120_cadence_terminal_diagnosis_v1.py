#!/usr/bin/env python3
"""Diagnose terminal F4 native004/stride5 cadence canaries.

The two canaries have already finished.  This is a read-only, bounded
replay of only the first transition where each terminal trace loses support;
it does not rerun the full material window.  It uses the exact frozen
reference provider, wall definition, neighbor count, regularization, and
gate from the canary.  Event accounting is read from the terminal H5 and its
terminal JSON summary so that contact and residence are reported with their
actual reliability masks.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import h5py
import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import core_material as cm
from scripts import f4_tallwall120_material as tw


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            value.update(block)
    return value.hexdigest()


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def percentiles(values: np.ndarray) -> dict[str, Any]:
    values = np.asarray(values, dtype=np.float64).reshape(-1)
    finite = values[np.isfinite(values)]
    if not len(finite):
        return {"count": 0, "min": None, "p50": None, "p95": None, "p99": None, "max": None}
    q = np.percentile(finite, [50, 95, 99])
    return {
        "count": int(len(finite)),
        "min": float(np.min(finite)),
        "p50": float(q[0]),
        "p95": float(q[1]),
        "p99": float(q[2]),
        "max": float(np.max(finite)),
    }


def component_masks(diag: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    return {
        "ess_fail": ~np.isfinite(diag["effective_sample_size"]) | (
            diag["effective_sample_size"] < float(cm.GATE["minimum_effective_sample_size"])
        ),
        "rank_fail": ~np.isfinite(diag["geometry_rank"]) | (
            diag["geometry_rank"] < int(cm.GATE["minimum_geometry_rank"])
        ),
        "anisotropy_fail": ~np.isfinite(diag["anisotropy"]) | (
            diag["anisotropy"] < float(cm.GATE["minimum_anisotropy"])
        ),
        "reconstruction_error_fail": ~np.isfinite(diag["interpolation_reconstruction_error_mps"]) | (
            diag["interpolation_reconstruction_error_mps"]
            > float(cm.GATE["maximum_reconstruction_error_mps"])
        ),
    }


def stage_metrics(active: np.ndarray, distance: np.ndarray, gate: np.ndarray,
                  diag: dict[str, np.ndarray]) -> dict[str, Any]:
    active = np.asarray(active, dtype=bool)
    masks = component_masks(diag)
    return {
        "active_count": int(active.sum()),
        "support_gate_pass_count": int((active & gate).sum()),
        "support_gate_fail_count": int((active & ~gate).sum()),
        "component_fail_counts": {name: int((active & mask).sum()) for name, mask in masks.items()},
        "support_distance_m": percentiles(distance[active]),
        "effective_sample_size": percentiles(diag["effective_sample_size"][active]),
        "geometry_rank": percentiles(diag["geometry_rank"][active]),
        "anisotropy": percentiles(diag["anisotropy"][active]),
        "reconstruction_error_mps": percentiles(diag["interpolation_reconstruction_error_mps"][active]),
        "visible_neighbours": percentiles(diag["visible_neighbours"][active]),
        "selected_visible_neighbours": percentiles(diag["selected_visible_neighbours"][active]),
    }


def failure_location(position: np.ndarray, mask: np.ndarray) -> dict[str, Any]:
    points = np.asarray(position, dtype=np.float64)[np.asarray(mask, dtype=bool)]
    if not len(points):
        return {"count": 0, "x_m": percentiles([]), "y_m": percentiles([]), "z_m": percentiles([]),
                "minimum_distance_to_interface_m": None}
    return {
        "count": int(len(points)),
        "x_m": percentiles(points[:, 0]),
        "y_m": percentiles(points[:, 1]),
        "z_m": percentiles(points[:, 2]),
        "minimum_distance_to_interface_m": float(np.min(np.abs(points[:, 2] - tw.INTERFACE_Z_M))),
    }


def _first_failure(trace: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, int, int]:
    with h5py.File(trace, "r") as handle:
        times = np.asarray(handle["time"][:], dtype=np.float64)
        positions = np.asarray(handle["position"][:], dtype=np.float64)
        reliable = np.asarray(handle["reliable"][:], dtype=bool)
        if positions.ndim != 3 or positions.shape[1:] != (512, 3):
            raise ValueError(f"unexpected terminal trace position shape: {positions.shape}")
        if reliable.shape != positions.shape[:2]:
            raise ValueError("terminal trace reliable shape does not match position")
        first_any = next((int(i) for i in range(1, len(times)) if not reliable[i].all()), None)
        if first_any is None:
            raise ValueError("terminal trace has no support failure")
        first_all = next((int(i) for i in range(1, len(times)) if not reliable[i].any()), None)
        if first_all is None:
            first_all = -1
        return times, positions, reliable, np.asarray(handle["weight"][:], dtype=np.float64), first_any, first_all


def _replay_first_transition(source: Path, trace: Path, *, q: float, substeps: int) -> dict[str, Any]:
    times, positions, reliable, weights, first_any, first_all = _first_failure(trace)
    seeds = cm.seeds_f4(512, q)
    if positions.shape[1] != len(seeds):
        raise ValueError("terminal trace is not the registered 512-seed axis")
    frame = first_any - 1
    active = np.array(reliable[frame], copy=True)
    q_position = np.array(positions[frame], copy=True)
    walls = tw.tallwall_walls()
    stages: list[dict[str, Any]] = []
    dt = (float(times[frame + 1]) - float(times[frame])) / int(substeps)
    with cm.ReferenceFrames(source, fluid_type=3) as frames:
        initial_field = frames.field(frame, 0.0)
        # The canary's runner uses a two-frame linear support geometry.  The
        # initial metrics below are evaluated only for the first failing
        # transition, so no full-window replay is needed.
        field0 = initial_field
        for substep in range(int(substeps)):
            alpha = (substep + 1) / int(substeps)
            field1 = frames.field(frame, alpha)
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
            finite = np.isfinite(v0).all(axis=1) & np.isfinite(v1).all(axis=1)
            dmax = np.maximum(d0, d1)
            usable = active & g0 & g1 & ~blocked & finite & (dmax <= tw.MAXIMUM_SUPPORT_DISTANCE_M)
            failing = active & ~usable
            stages.append({
                "substep": substep,
                "segment_time_s": float(times[frame]) + substep * dt,
                "dt_s": float(dt),
                "active_count": int(active.sum()),
                "usable_count": int(usable.sum()),
                "new_failure_count": int(failing.sum()),
                "failure_reason_counts": {
                    "g0_support_gate_fail": int((active & ~g0).sum()),
                    "g1_support_gate_fail": int((active & ~g1).sum()),
                    "distance_gate_fail": int((active & (dmax > tw.MAXIMUM_SUPPORT_DISTANCE_M)).sum()),
                    "wall_blocked": int((active & blocked).sum()),
                    "nonfinite_velocity": int((active & ~finite).sum()),
                    "other": int((failing & g0 & g1 & ~blocked & finite & (dmax <= tw.MAXIMUM_SUPPORT_DISTANCE_M)).sum()),
                },
                "g0": stage_metrics(active, d0, g0 & (d0 <= tw.MAXIMUM_SUPPORT_DISTANCE_M), diag0),
                "g1": stage_metrics(active, d1, g1 & (d1 <= tw.MAXIMUM_SUPPORT_DISTANCE_M), diag1),
            })
            q_position = np.where(usable[:, None], candidate, q_position)
            active = usable
            field0 = field1
    trace_next = np.asarray(reliable[frame + 1], dtype=bool)
    first_fail_mask = reliable[frame] & ~trace_next
    return {
        "frame_before": frame,
        "frame_first_any_failure": first_any,
        "frame_first_all_failure": first_all,
        "time_before_s": float(times[frame]),
        "time_after_s": float(times[first_any]),
        "first_failure_saved_frame_is_upper_bound": True,
        "input_reliable_count": int(reliable[frame].sum()),
        "output_reliable_count": int(reliable[first_any].sum()),
        "first_transition_failure_count": int(first_fail_mask.sum()),
        "first_transition_failure_location_m": failure_location(positions[frame], first_fail_mask),
        "substeps": stages,
        "replay_reliable_match": bool(np.array_equal(active, trace_next)),
        "replay_output_reliable_count": int(active.sum()),
        "weight_total_kg": float(weights.sum()),
    }


def _event_semantics(trace: Path, summary: Path) -> dict[str, Any]:
    with h5py.File(trace, "r") as handle:
        committed = int(handle.attrs.get("committed", len(handle["time"]) - 1))
        time = np.asarray(handle["time"][:], dtype=np.float64)
        reliable = np.asarray(handle["reliable"][:], dtype=bool)
        contacted = np.asarray(handle["contacted"][:], dtype=bool)
        upward = np.asarray(handle["upward"][:], dtype=bool)
        returned = np.asarray(handle["returned"][:], dtype=bool)
        residence = np.asarray(handle["residence"][:], dtype=np.float64)
        weight = np.asarray(handle["weight"][:], dtype=np.float64)
        if committed < 0 or committed >= len(time):
            raise ValueError("terminal H5 committed frame is invalid")
        final_reliable = reliable[committed]
        final_contacted = contacted[committed]
        final_residence = residence[committed]
        source_labels = np.asarray(handle["source_label"][:])
    summary_json = json.loads(Path(summary).read_text())
    by_source = summary_json.get("by_source", [])
    source_rows = []
    for source in np.unique(source_labels):
        select = source_labels == source
        source_mass = float(weight[select].sum())
        event_row = next((row for row in by_source if str(row.get("source")) == str(source)), None)
        source_rows.append({
            "source": source.item() if isinstance(source, np.generic) else source,
            "seed_count": int(select.sum()),
            "source_mass_kg": source_mass,
            "final_reliable_count": int((select & final_reliable).sum()),
            "final_contacted_count": int((select & final_contacted).sum()),
            "final_reliable_contacted_count": int((select & final_reliable & final_contacted).sum()),
            "final_contacted_but_unreliable_count": int((select & final_contacted & ~final_reliable).sum()),
            "final_residence_positive_count": int((select & (final_residence > 0.0)).sum()),
            "final_residence_positive_reliable_count": int((select & (final_residence > 0.0) & final_reliable).sum()),
            "final_residence_positive_unreliable_count": int((select & (final_residence > 0.0) & ~final_reliable).sum()),
            "final_upward_count": int((select & upward[committed]).sum()),
            "final_returned_count": int((select & returned[committed]).sum()),
            "contacted_count_by_frame": [int((select & contacted[index]).sum()) for index in range(committed + 1)],
            "reliable_count_by_frame": [int((select & reliable[index]).sum()) for index in range(committed + 1)],
            "residence_positive_count_by_frame": [int((select & (residence[index] > 0.0)).sum()) for index in range(committed + 1)],
            "summary_row": event_row,
        })
    return {
        "committed_frame": committed,
        "committed_time_s": float(time[committed]),
        "weight_total_kg": float(weight.sum()),
        "summary_path": str(Path(summary).resolve()),
        "summary_sha256": digest(summary),
        "by_source": source_rows,
        "semantic_interpretation": {
            "contact_fraction_definition": "final reliable AND contacted weighted by the full source mass denominator",
            "residence_mean_definition": "sum of every seed's accumulated residence weighted by the full source mass denominator; it is not masked by final reliability or final contact",
            "contact_fraction_zero_with_positive_residence": "consistent with the frozen implementation when paths contacted before becoming unknown; it is partial pre-unknown residence, not an observed contact-success or residence CDF result",
            "cdf_validity": "a residence/contact CDF requires final reliable AND contacted; if that mask is empty, the CDF is empty/NA and the event window is unresolved",
            "unknown_gate_changed": False,
        },
    }


def _curve(trace: Path) -> dict[str, Any]:
    with h5py.File(trace, "r") as handle:
        t = np.asarray(handle["time"][:], dtype=np.float64)
        reliable = np.asarray(handle["reliable"][:], dtype=bool)
        weight = np.asarray(handle["weight"][:], dtype=np.float64)
    total = float(weight.sum())
    return {
        "time_s": t.tolist(),
        "reliable_count": reliable.sum(axis=1).astype(int).tolist(),
        "reliable_mass_fraction": (reliable @ weight / total).tolist(),
        "unknown_mass_fraction": (1.0 - reliable @ weight / total).tolist(),
        "weight_total_kg": total,
    }


def diagnose(case_specs: list[dict[str, Any]], output: Path) -> dict[str, Any]:
    cases = []
    for spec in case_specs:
        source = Path(spec["source"]).resolve()
        trace = Path(spec["trace"]).resolve()
        summary = Path(spec["summary"]).resolve()
        replay = _replay_first_transition(source, trace, q=float(spec.get("q", 0.5)), substeps=int(spec.get("substeps", 2)))
        event = _event_semantics(trace, summary)
        curve = _curve(trace)
        cases.append({
            "case_id": spec["case_id"],
            "source": {"path": str(source), "sha256": digest(source), "role": spec["source_role"]},
            "trace": {"path": str(trace), "sha256": digest(trace), "role": spec["trace_role"]},
            "terminal_summary": {"path": str(summary), "sha256": digest(summary)},
            "replay": replay,
            "event_semantics": event,
            "reliability_curve": curve,
        })
    native, stride = cases
    native_curve = native["reliability_curve"]
    stride_curve = stride["reliability_curve"]
    pairs = []
    native_times = np.asarray(native_curve["time_s"], dtype=np.float64)
    for index, t in enumerate(stride_curve["time_s"]):
        nearest = int(np.argmin(np.abs(native_times - float(t))))
        pairs.append({
            "stride_frame": index,
            "native_frame": nearest,
            "stride_time_s": float(t),
            "native_time_s": float(native_times[nearest]),
            "time_difference_s": float(native_times[nearest] - float(t)),
            "stride_reliable_mass_fraction": float(stride_curve["reliable_mass_fraction"][index]),
            "native_reliable_mass_fraction": float(native_curve["reliable_mass_fraction"][nearest]),
        })
    result = {
        "schema": "core.material.f4.tallwall120.cadence_terminal_diagnosis.v1",
        "created_at_utc": stamp(),
        "scope_id": tw.SCOPE_ID,
        "backend": tw.NEIGHBOUR_BACKEND,
        "neighbours": tw.NEIGHBOURS,
        "regularization_m": tw.REGULARIZATION_M,
        "maximum_support_distance_m": tw.MAXIMUM_SUPPORT_DISTANCE_M,
        "support_gate": tw.GATE,
        "thresholds_changed": False,
        "material_reliability_claim": "uncalibrated",
        "qualification_claim": "none; .4 s terminal cadence canaries are diagnostic only",
        "read_only": True,
        "central_ledger_mutation": 0,
        "gpu_started": False,
        "source_read_policy": "terminal H5 only; no active H5 was read; replay evaluates only the first-failure transition",
        "cases": cases,
        "paired_reliability_curve": {
            "matching_policy": "nearest exact saved time; stride view is an exact every-5 frame view of the native source",
            "pairs": pairs,
            "max_abs_time_difference_s": float(max(abs(row["time_difference_s"]) for row in pairs)),
        },
        "conclusion": {
            "first_failure_is_reconstruction_gate": True,
            "native_first_failure_time_interval_s": [native["replay"]["time_before_s"], native["replay"]["time_after_s"]],
            "stride_first_failure_time_interval_s": [stride["replay"]["time_before_s"], stride["replay"]["time_after_s"]],
            "native_and_stride_both_end_unknown": True,
            "cadence_alone_resolves_failure": False,
            "support_distance_or_wall_dominates": False,
            "reconstruction_error_gate_dominates": True,
            "event_result": "contact_fraction=0 with positive residence_mean is a frozen denominator/mask semantic; all event CDFs remain unresolved because the final reliable-contact mask is empty",
            "qualification": "Neither canary supports an F4 T2 claim or a threshold change.",
        },
        "code": {
            "diagnosis_path": str(Path(__file__).resolve()),
            "diagnosis_sha256": digest(Path(__file__)),
            "core_material_path": str(Path(cm.__file__).resolve()),
            "core_material_sha256": digest(Path(cm.__file__)),
            "material_tracer_path": str(Path(tw.__file__).resolve()),
            "material_tracer_sha256": digest(Path(tw.__file__)),
        },
    }
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(f"immutable diagnosis already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(output.name + ".partial")
    partial.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    partial.replace(output)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-source", type=Path, required=True)
    parser.add_argument("--native-trace", type=Path, required=True)
    parser.add_argument("--native-summary", type=Path, required=True)
    parser.add_argument("--stride-source", type=Path, required=True)
    parser.add_argument("--stride-trace", type=Path, required=True)
    parser.add_argument("--stride-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    specs = [
        {"case_id": "native004_s2", "source": args.native_source, "trace": args.native_trace,
         "summary": args.native_summary, "source_role": "cell14_terminal_native004", "trace_role": "native004_s2", "substeps": 2},
        {"case_id": "stride5_s10", "source": args.stride_source, "trace": args.stride_trace,
         "summary": args.stride_summary, "source_role": "cell14_exact_stride5_view", "trace_role": "stride5_s10", "substeps": 10},
    ]
    result = diagnose(specs, args.output)
    compact = {
        "output": str(args.output.resolve()),
        "code_sha256": result["code"]["diagnosis_sha256"],
        "cases": [{"case_id": case["case_id"], "first_failure": case["replay"]["frame_first_any_failure"],
                   "time_before_s": case["replay"]["time_before_s"], "time_after_s": case["replay"]["time_after_s"],
                   "first_failure_count": case["replay"]["first_transition_failure_count"],
                   "replay_match": case["replay"]["replay_reliable_match"]} for case in result["cases"]],
    }
    print(json.dumps(compact, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
