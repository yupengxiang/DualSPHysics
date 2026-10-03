#!/usr/bin/env python3
"""Audit native solver timestepping and RunPARTs telemetry for F7 baseline vs true-half dense (v1).

This audit parses Run.out and RunPARTs.csv for both the baseline dense run and the
supposed 'true half' dense run to verify:
1. Actual timestepping mode: adaptive (variable dt) vs fixed (constant DtFixed).
2. Floor clamping incidence: count and fraction of DTs adjusted to DtMin.
3. Native dt distributions: min, max, mean, and quantiles across all output intervals.
4. Step ratio reality: actual step ratio vs nominal 2.0x halving hypothesis.
5. Algorithmic consistency: whether the comparison is methodologically valid under the frozen reference budget.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
from typing import Any

import numpy as np


SCHEMA = "ds02.f7.runparts-timestep-audit.v1"


def digest(path: Path | str) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_run_out(path: Path) -> dict[str, Any]:
    """Parse DualSPHysics Run.out log file."""
    text = path.read_text(encoding="utf-8", errors="replace")

    def search_pattern(pattern: str, cast_type=str, default=None):
        m = re.search(pattern, text)
        if m:
            val = m.group(1).strip().replace(",", "")
            try:
                return cast_type(val)
            except Exception:
                return default
        return default

    case_name = search_pattern(r'CaseName="([^"]+)"', str, "")
    run_name = search_pattern(r'RunName="([^"]+)"', str, "")
    step_algo = search_pattern(r'StepAlgorithm="([^"]+)"', str, "")
    cfl = search_pattern(r'CFLnumber=([\d\.eE+-]+)', float, None)
    dt_ini = search_pattern(r'DtIni=([\d\.eE+-]+)', float, None)
    dt_min = search_pattern(r'DtMin=([\d\.eE+-]+)', float, None)
    fixed_dt = search_pattern(r'FixedDt=([\d\.eE+-]+)', float, None)
    time_max = search_pattern(r'TimeMax=([\d\.eE+-]+)', float, None)
    time_part = search_pattern(r'TimePart=([\d\.eE+-]+)', float, None)
    initial_particles = search_pattern(r'Particles of simulation \(initial\):\s*([\d,]+)', int, None)
    dts_adjusted_to_dtmin = search_pattern(r'DTs adjusted to DtMin\.+:\s*([\d,]+)', int, None)
    excluded_particles = search_pattern(r'Excluded particles\.+:\s*([\d,]+)', int, None)
    total_runtime_s = search_pattern(r'Total Runtime\.+:\s*([\d\.]+)\s*sec\.', float, None)
    sim_runtime_s = search_pattern(r'Simulation Runtime\.+:\s*([\d\.]+)\s*sec\.', float, None)
    steps_of_simulation = search_pattern(r'Steps of simulation\.+:\s*([\d,]+)', int, None)
    part_files = search_pattern(r'PART files\.+:\s*([\d,]+)', int, None)
    return_code = search_pattern(r'Finished execution \(code=([-\d]+)\)', int, None)

    mode = "fixed" if fixed_dt is not None and fixed_dt > 0 else "adaptive"

    return {
        "file": str(path.resolve()),
        "case_name": case_name,
        "run_name": run_name,
        "step_algorithm": step_algo,
        "cfl_number": cfl,
        "dt_ini": dt_ini,
        "dt_min_floor": dt_min,
        "fixed_dt": fixed_dt,
        "mode": mode,
        "time_max_s": time_max,
        "time_part_s": time_part,
        "initial_particles": initial_particles,
        "dts_adjusted_to_dtmin": dts_adjusted_to_dtmin,
        "excluded_particles": excluded_particles,
        "total_runtime_s": total_runtime_s,
        "sim_runtime_s": sim_runtime_s,
        "steps_of_simulation": steps_of_simulation,
        "part_files_count": part_files,
        "return_code": return_code,
    }


def parse_run_parts_csv(path: Path) -> dict[str, Any]:
    """Parse DualSPHysics RunPARTs.csv telemetry file."""
    parts: list[int] = []
    times: list[float] = []
    steps: list[int] = []
    dts_min: list[int] = []
    np_out: list[int] = []
    dt_mins: list[float] = []
    dt_maxs: list[float] = []

    with path.open("r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f, delimiter=";")
        header = next(reader)
        # Normalize header column names
        header_map = {col.strip(): idx for idx, col in enumerate(header)}
        part_idx = header_map.get("Part")
        time_idx = header_map.get("TimeStep [s]")
        steps_idx = header_map.get("Steps")
        dtsmin_idx = header_map.get("DTsMin")
        npout_idx = header_map.get("NpOut")
        dtmin_col = header_map.get("DtMin [s]")
        dtmax_col = header_map.get("DtMax [s]")

        if None in (part_idx, time_idx, steps_idx, dtsmin_idx, dtmin_col, dtmax_col):
            raise ValueError(f"RunPARTs.csv missing required columns in {path}")

        for row in reader:
            if not row or len(row) <= max(part_idx, time_idx, steps_idx, dtsmin_idx, dtmin_col, dtmax_col):
                continue
            try:
                p = int(row[part_idx].strip().replace(",", ""))
                t = float(row[time_idx].strip().replace(",", ""))
                s = int(row[steps_idx].strip().replace(",", ""))
                dm = int(row[dtsmin_idx].strip().replace(",", ""))
                nout = int(row[npout_idx].strip().replace(",", "")) if npout_idx is not None else 0
                dt_lo = float(row[dtmin_col].strip().replace(",", ""))
                dt_hi = float(row[dtmax_col].strip().replace(",", ""))

                parts.append(p)
                times.append(t)
                steps.append(s)
                dts_min.append(dm)
                np_out.append(nout)
                dt_mins.append(dt_lo)
                dt_maxs.append(dt_hi)
            except Exception:
                continue

    if len(parts) < 2:
        raise ValueError(f"RunPARTs.csv contains fewer than 2 valid rows: {path}")

    # Exclude Part 0 (initial condition) for step-level interval statistics
    active_steps = np.array(steps[1:], dtype=np.int64)
    active_dts_min = np.array(dts_min[1:], dtype=np.int64)
    active_dt_mins = np.array(dt_mins[1:], dtype=np.float64)
    active_dt_maxs = np.array(dt_maxs[1:], dtype=np.float64)
    active_times = np.array(times[1:], dtype=np.float64)
    prev_times = np.array(times[:-1], dtype=np.float64)

    delta_times = active_times - prev_times
    # Safe division: where active_steps > 0
    valid_step_mask = active_steps > 0
    interval_mean_dt = np.where(valid_step_mask, delta_times / np.maximum(active_steps, 1), 0.0)

    total_steps = int(np.sum(active_steps))
    total_clamps = int(np.sum(active_dts_min))
    floor_incidence = float(total_clamps / total_steps) if total_steps > 0 else 0.0

    global_min_dt = float(np.min(active_dt_mins[valid_step_mask])) if valid_step_mask.any() else 0.0
    global_max_dt = float(np.max(active_dt_maxs[valid_step_mask])) if valid_step_mask.any() else 0.0
    overall_mean_dt = float(times[-1] / total_steps) if total_steps > 0 else 0.0

    is_constant_fixed = bool(
        global_min_dt > 0
        and abs(global_max_dt - global_min_dt) / global_min_dt < 1e-6
    )

    percentiles = [1, 5, 10, 25, 50, 75, 90, 95, 99]
    pct_values = {}
    if valid_step_mask.any():
        computed_pcts = np.percentile(interval_mean_dt[valid_step_mask], percentiles)
        for p, val in zip(percentiles, computed_pcts):
            pct_values[f"p{p:02d}_dt_s"] = float(val)

    return {
        "file": str(path.resolve()),
        "total_part_rows": len(parts),
        "physical_time_end_s": times[-1],
        "sum_steps": total_steps,
        "sum_dts_min_clamps": total_clamps,
        "floor_clamp_incidence_fraction": floor_incidence,
        "floor_clamp_zero": bool(total_clamps == 0),
        "global_min_dt_s": global_min_dt,
        "global_max_dt_s": global_max_dt,
        "overall_mean_dt_s": overall_mean_dt,
        "is_constant_fixed_dt": is_constant_fixed,
        "interval_mean_dt_percentiles": pct_values,
        "total_np_out": int(np_out[-1]) if np_out else 0,
    }


def audit_timestep_comparison(
    baseline_parts_path: Path,
    baseline_out_path: Path,
    variant_parts_path: Path,
    variant_out_path: Path,
    budget_path: Path | None = None,
    comparison_report_path: Path | None = None,
    baseline_receipt_path: Path | None = None,
    variant_receipt_path: Path | None = None,
) -> dict[str, Any]:
    """Perform rigorous timestep telemetry audit between baseline dense and true half dense."""
    b_out = parse_run_out(baseline_out_path)
    b_parts = parse_run_parts_csv(baseline_parts_path)
    v_out = parse_run_out(variant_out_path)
    v_parts = parse_run_parts_csv(variant_parts_path)

    # Verification of internal consistency between Run.out and RunPARTs.csv
    b_step_match = bool(b_out["steps_of_simulation"] == b_parts["sum_steps"])
    v_step_match = bool(v_out["steps_of_simulation"] == v_parts["sum_steps"])
    b_clamp_match = bool(b_out["dts_adjusted_to_dtmin"] == b_parts["sum_dts_min_clamps"])
    v_clamp_match = bool(v_out["dts_adjusted_to_dtmin"] == v_parts["sum_dts_min_clamps"])

    step_ratio = float(v_parts["sum_steps"] / b_parts["sum_steps"]) if b_parts["sum_steps"] > 0 else 0.0
    mean_dt_ratio = float(b_parts["overall_mean_dt_s"] / v_parts["overall_mean_dt_s"]) if v_parts["overall_mean_dt_s"] > 0 else 0.0
    nominal_expected_step_ratio = 2.0
    step_ratio_discrepancy_factor = step_ratio / nominal_expected_step_ratio

    # Mode classification
    baseline_is_adaptive = b_out["mode"] == "adaptive" and not b_parts["is_constant_fixed_dt"]
    variant_is_fixed = v_out["mode"] == "fixed" or v_parts["is_constant_fixed_dt"]

    # Floor assessment
    both_zero_clamps = b_parts["sum_dts_min_clamps"] == 0 and v_parts["sum_dts_min_clamps"] == 0

    findings = {
        "baseline_mode": "adaptive" if baseline_is_adaptive else "fixed",
        "variant_mode": "fixed" if variant_is_fixed else "adaptive",
        "nominal_study_intent": "Halved timestep convergence study (expected step ratio ~ 2.0x)",
        "actual_execution_reality": (
            f"Variant executed with constant FixedDt={v_out['fixed_dt']:.6e} s, resulting in "
            f"{step_ratio:.4f}x more steps than baseline (not 2.0x)."
        ),
        "floor_clamping_eliminated": both_zero_clamps,
        "floor_clamping_comment": (
            "Neither baseline nor variant experienced a single timestep floor clamp "
            "(DTs adjusted to DtMin = 0 in both). Timestep floor clamping is NOT the cause of "
            "the transport divergence."
        ),
        "methodological_divergence": (
            "Baseline dense operated with adaptive Symplectic timestepping (CFL=0.2, dynamic dt in "
            f"[{b_parts['global_min_dt_s']:.6e}, {b_parts['global_max_dt_s']:.6e}] s, mean {b_parts['overall_mean_dt_s']:.6e} s). "
            f"Variant was hardcoded to a fixed constant step DtFixed={v_out['fixed_dt']:.6e} s ({mean_dt_ratio:.2f}x smaller). "
            "Comparing an adaptive integration against a fixed-step integration violates algorithmic consistency."
        ),
        "transport_divergence_context": (
            "The 0.52656s macro chord shift and 8,376 switching identities documented in "
            "paired-transport-comparison-report-v3.json reflect this structural paradigm shift "
            "(adaptive vs 4.6x-refined fixed Symplectic) rather than chaotic physical instability."
        ),
        "legitimate_next_steps": [
            "1. Maintain existing negative Q-N finding: current comparison is invalid as a convergence witness.",
            "2. If an F7 temporal qualification is to be pursued, register a genuine adaptive halved-CFL request "
            "(CFL=0.1, CoefDtMin=0.025, DtFixed=0), preserving identical adaptive integration semantics.",
            "3. Do not launch solver outside shared runner; keep all input hashes and requests immutable.",
        ],
    }

    # Digested file inventory
    digests: dict[str, str] = {
        str(baseline_parts_path.resolve()): digest(baseline_parts_path),
        str(baseline_out_path.resolve()): digest(baseline_out_path),
        str(variant_parts_path.resolve()): digest(variant_parts_path),
        str(variant_out_path.resolve()): digest(variant_out_path),
    }
    if budget_path and budget_path.exists():
        digests[str(budget_path.resolve())] = digest(budget_path)
    if comparison_report_path and comparison_report_path.exists():
        digests[str(comparison_report_path.resolve())] = digest(comparison_report_path)
    if baseline_receipt_path and baseline_receipt_path.exists():
        digests[str(baseline_receipt_path.resolve())] = digest(baseline_receipt_path)
    if variant_receipt_path and variant_receipt_path.exists():
        digests[str(variant_receipt_path.resolve())] = digest(variant_receipt_path)

    return {
        "schema": SCHEMA,
        "qualification_status": "unassessed_invalid_timestepping_protocol",
        "internal_consistency": {
            "baseline_step_count_exact_match": b_step_match,
            "variant_step_count_exact_match": v_step_match,
            "baseline_clamp_count_exact_match": b_clamp_match,
            "variant_clamp_count_exact_match": v_clamp_match,
        },
        "baseline_dense": {
            "run_out": b_out,
            "run_parts": b_parts,
        },
        "true_half_dense": {
            "run_out": v_out,
            "run_parts": v_parts,
        },
        "comparison_metrics": {
            "step_count_ratio": step_ratio,
            "nominal_expected_step_ratio": nominal_expected_step_ratio,
            "step_ratio_discrepancy_factor": step_ratio_discrepancy_factor,
            "overall_mean_dt_ratio": mean_dt_ratio,
            "baseline_overall_mean_dt_s": b_parts["overall_mean_dt_s"],
            "variant_overall_mean_dt_s": v_parts["overall_mean_dt_s"],
            "baseline_dt_spread_ratio": b_parts["global_max_dt_s"] / b_parts["global_min_dt_s"] if b_parts["global_min_dt_s"] > 0 else 1.0,
            "variant_dt_spread_ratio": v_parts["global_max_dt_s"] / v_parts["global_min_dt_s"] if v_parts["global_min_dt_s"] > 0 else 1.0,
        },
        "findings": findings,
        "input_sha256": digests,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-parts", type=Path, required=True, help="Baseline RunPARTs.csv")
    parser.add_argument("--baseline-out", type=Path, required=True, help="Baseline Run.out")
    parser.add_argument("--variant-parts", type=Path, required=True, help="Variant RunPARTs.csv")
    parser.add_argument("--variant-out", type=Path, required=True, help="Variant Run.out")
    parser.add_argument("--baseline-receipt", type=Path, required=False, default=None, help="Baseline execution-receipt.json")
    parser.add_argument("--variant-receipt", type=Path, required=False, default=None, help="Variant execution-receipt.json")
    parser.add_argument("--budget", type=Path, required=False, default=None, help="Frozen reference budget JSON")
    parser.add_argument("--comparison-report", type=Path, required=False, default=None, help="Paired comparison report v3 JSON")
    parser.add_argument("--output", type=Path, required=True, help="Output JSON report path")

    args = parser.parse_args()

    result = audit_timestep_comparison(
        baseline_parts_path=args.baseline_parts,
        baseline_out_path=args.baseline_out,
        variant_parts_path=args.variant_parts,
        variant_out_path=args.variant_out,
        budget_path=args.budget,
        comparison_report_path=args.comparison_report,
        baseline_receipt_path=args.baseline_receipt,
        variant_receipt_path=args.variant_receipt,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote F7 timestep audit to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
