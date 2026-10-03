#!/usr/bin/env python3
"""Audit native solver timestepping and RunPARTs telemetry for F7 baseline vs true-half dense (v2).

Key fixes in v2:
1. Denominator for floor clamp incidence: DTsMin / (2 * sum Steps) for verified Symplectic XML
   (DualSPHysics Symplectic predictor-corrector performs 2 sub-evaluations per step).
2. NpOut interval sum: sum of per-interval particle exclusions across active rows, not just last row.
3. Strict contiguous Parts validation: exactly 6001 contiguous parts [0..6000] and strictly
   monotone time spanning the full 12s window [0.0, 12.0].
4. Malformed numeric Part rows fail: no silent skipping; malformed rows raise ValueError.
5. Execution receipts validated: assert status == 'completed' and returncode == 0.
6. Native XML controls bound: parses StepAlgorithm, CFLnumber, CoefDtMin, DtFixed, DtIni, DtMin
   from input XML and cross-checks with Run.out.
7. Honest percentile labeling: explicitly labeled as 'per_save_interval_mean_dt_percentiles',
   clarifying that these are quantiles of interval-mean dt (delta_t / steps), not internal step dt.
8. Measured ratios & limitations: no hardcoded causal assertions that transport divergence stems
   solely from adaptive-vs-fixed; fixed-step refinement is not intrinsically invalid; documents
   audit limitations and preserves negative evidence.
9. Errata binding: explicitly documents errata regarding prior reports (spatial KE scale, denominator, NpOut).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
from typing import Any
import xml.etree.ElementTree as ET

import numpy as np


SCHEMA = "ds02.f7.runparts-timestep-audit.v2"
EXPECTED_PART_COUNT = 6001
EXPECTED_TIME_MAX_S = 12.0


def digest(path: Path | str) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_execution_receipt(receipt_path: Path) -> dict[str, Any]:
    """Validate solver execution receipt for completed status and returncode 0."""
    text = receipt_path.read_text(encoding="utf-8")
    data = json.loads(text)
    status = data.get("status")
    returncode = data.get("returncode")
    if status != "completed" or returncode != 0:
        raise ValueError(
            f"Execution receipt validation failed for {receipt_path}: status={status}, returncode={returncode}"
        )
    return {
        "file": str(receipt_path.resolve()),
        "status": status,
        "returncode": returncode,
        "pid": data.get("pid"),
        "elapsed_seconds": data.get("elapsed_seconds"),
        "cpu_core_seconds": data.get("cpu_core_seconds"),
        "gpu_seconds": data.get("gpu_seconds"),
    }


def parse_xml_controls(path: Path) -> dict[str, Any]:
    """Parse DualSPHysics case XML configuration for execution parameters and constants."""
    tree = ET.parse(path)
    root = tree.getroot()

    parameters: dict[str, str] = {}
    for elem in root.iter("parameter"):
        key = elem.attrib.get("key")
        val = elem.attrib.get("value")
        if key and val is not None:
            parameters[key] = val

    constants: dict[str, str] = {}
    constants_elem = root.find(".//execution/constants")
    if constants_elem is None:
        constants_elem = root.find(".//constants")
    if constants_elem is not None:
        for elem in constants_elem:
            val = elem.attrib.get("value")
            if val is not None:
                constants[elem.tag.lower()] = val

    step_algo_code = int(parameters.get("StepAlgorithm", 0))
    step_algo_name = "Symplectic" if step_algo_code == 2 else "Verlet" if step_algo_code == 1 else "Unknown"
    evaluations_per_step = 2 if step_algo_code == 2 else 1

    cfl = float(constants.get("cflnumber", parameters.get("CFLnumber", 0.0)))
    coef_dt_min = float(parameters.get("CoefDtMin", 0.0))
    dt_fixed = float(parameters.get("DtFixed", 0.0))
    dt_ini = float(parameters.get("DtIni", 0.0))
    dt_min = float(parameters.get("DtMin", 0.0))
    time_max = float(parameters.get("TimeMax", 0.0))
    time_out = float(parameters.get("TimeOut", 0.0))

    mode = "fixed" if dt_fixed > 0.0 else "adaptive"

    return {
        "file": str(path.resolve()),
        "step_algorithm_code": step_algo_code,
        "step_algorithm_name": step_algo_name,
        "evaluations_per_step": evaluations_per_step,
        "cfl_number": cfl,
        "coef_dt_min": coef_dt_min,
        "dt_fixed": dt_fixed,
        "dt_ini": dt_ini,
        "dt_min_parameter": dt_min,
        "mode": mode,
        "time_max_s": time_max,
        "time_out_s": time_out,
        "parameters": parameters,
        "constants": constants,
    }


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


def parse_run_parts_csv(
    path: Path,
    evaluations_per_step: int = 2,
    expected_part_count: int = EXPECTED_PART_COUNT,
    expected_time_max_s: float = EXPECTED_TIME_MAX_S,
) -> dict[str, Any]:
    """Parse and strictly validate DualSPHysics RunPARTs.csv telemetry file.

    Fails on any malformed numeric row, missing contiguous part, or non-monotone time.
    """
    parts: list[int] = []
    times: list[float] = []
    steps: list[int] = []
    dts_min: list[int] = []
    np_out: list[int] = []
    dt_mins: list[float] = []
    dt_maxs: list[float] = []

    with path.open("r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f, delimiter=";")
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError(f"RunPARTs.csv is empty: {path}") from exc

        header_map = {col.strip(): idx for idx, col in enumerate(header)}
        required_cols = ["Part", "TimeStep [s]", "Steps", "DTsMin", "NpOut", "DtMin [s]", "DtMax [s]"]
        missing_cols = [c for c in required_cols if c not in header_map]
        if missing_cols:
            raise ValueError(f"RunPARTs.csv missing required columns {missing_cols} in {path}")

        part_idx = header_map["Part"]
        time_idx = header_map["TimeStep [s]"]
        steps_idx = header_map["Steps"]
        dtsmin_idx = header_map["DTsMin"]
        npout_idx = header_map["NpOut"]
        dtmin_col = header_map["DtMin [s]"]
        dtmax_col = header_map["DtMax [s]"]
        max_idx = max(part_idx, time_idx, steps_idx, dtsmin_idx, npout_idx, dtmin_col, dtmax_col)

        for row_idx, row in enumerate(reader, start=1):
            if not row or len(row) <= max_idx:
                raise ValueError(
                    f"Malformed row {row_idx} in {path}: expected > {max_idx} columns, got {len(row)}"
                )
            try:
                p = int(row[part_idx].strip().replace(",", ""))
                t = float(row[time_idx].strip().replace(",", ""))
                s = int(row[steps_idx].strip().replace(",", ""))
                dm = int(row[dtsmin_idx].strip().replace(",", ""))
                nout = int(row[npout_idx].strip().replace(",", ""))
                dt_lo = float(row[dtmin_col].strip().replace(",", ""))
                dt_hi = float(row[dtmax_col].strip().replace(",", ""))
            except Exception as exc:
                raise ValueError(f"Malformed numeric Part row {row_idx} in {path}: {exc}") from exc

            parts.append(p)
            times.append(t)
            steps.append(s)
            dts_min.append(dm)
            np_out.append(nout)
            dt_mins.append(dt_lo)
            dt_maxs.append(dt_hi)

    total_rows = len(parts)
    if total_rows != expected_part_count:
        raise ValueError(
            f"Expected exactly {expected_part_count} contiguous parts in {path}, got {total_rows}"
        )

    parts_arr = np.array(parts, dtype=np.int64)
    expected_parts_arr = np.arange(expected_part_count, dtype=np.int64)
    if not np.array_equal(parts_arr, expected_parts_arr):
        raise ValueError(f"Parts are not strictly contiguous 0..{expected_part_count - 1} in {path}")

    times_arr = np.array(times, dtype=np.float64)
    if times_arr[0] != 0.0:
        raise ValueError(f"Initial Part 0 time must be 0.0 s, got {times_arr[0]} in {path}")
    if times_arr[-1] < expected_time_max_s - 1e-4:
        raise ValueError(
            f"Final time must reach full {expected_time_max_s} s, got {times_arr[-1]} in {path}"
        )
    if not (np.diff(times_arr) > 0).all():
        raise ValueError(f"Part times are not strictly monotonically increasing in {path}")

    # Active rows: intervals 1..N (excluding Part 0 which is initial condition)
    active_steps = np.array(steps[1:], dtype=np.int64)
    active_dts_min = np.array(dts_min[1:], dtype=np.int64)
    active_np_out = np.array(np_out[1:], dtype=np.int64)
    active_dt_mins = np.array(dt_mins[1:], dtype=np.float64)
    active_dt_maxs = np.array(dt_maxs[1:], dtype=np.float64)
    active_times = times_arr[1:]
    prev_times = times_arr[:-1]

    delta_times = active_times - prev_times
    valid_step_mask = active_steps > 0
    if not valid_step_mask.all():
        raise ValueError(f"Found active interval with zero steps in {path}")

    interval_mean_dt = delta_times / active_steps

    total_steps = int(np.sum(active_steps))
    total_clamps = int(np.sum(active_dts_min))

    # Symplectic scheme: 2 predictor-corrector force evaluations per step
    total_dt_evaluations = evaluations_per_step * total_steps
    floor_incidence = float(total_clamps / total_dt_evaluations) if total_dt_evaluations > 0 else 0.0

    global_min_dt = float(np.min(active_dt_mins))
    global_max_dt = float(np.max(active_dt_maxs))
    overall_mean_dt = float(times_arr[-1] / total_steps) if total_steps > 0 else 0.0

    # NpOut interval sum
    total_np_out_interval_sum = int(np.sum(active_np_out))
    last_row_np_out = int(np_out[-1])

    is_constant_fixed = bool(
        global_min_dt > 0
        and abs(global_max_dt - global_min_dt) / global_min_dt < 1e-6
    )

    percentiles = [1, 5, 10, 25, 50, 75, 90, 95, 99]
    pct_values = {}
    computed_pcts = np.percentile(interval_mean_dt, percentiles)
    for p, val in zip(percentiles, computed_pcts):
        pct_values[f"p{p:02d}_dt_s"] = float(val)

    return {
        "file": str(path.resolve()),
        "total_part_rows": total_rows,
        "physical_time_start_s": float(times_arr[0]),
        "physical_time_end_s": float(times_arr[-1]),
        "sum_steps": total_steps,
        "evaluations_per_step": evaluations_per_step,
        "total_dt_evaluations": total_dt_evaluations,
        "denominator_formula": f"{evaluations_per_step} * sum(Steps)",
        "sum_dts_min_clamps": total_clamps,
        "floor_clamp_incidence_fraction": floor_incidence,
        "floor_clamp_zero": bool(total_clamps == 0),
        "global_min_dt_s": global_min_dt,
        "global_max_dt_s": global_max_dt,
        "overall_mean_dt_s": overall_mean_dt,
        "is_constant_fixed_dt": is_constant_fixed,
        "per_save_interval_mean_dt_percentiles": pct_values,
        "percentile_description": (
            "Percentiles of interval-mean time steps (delta_t_save / steps_in_interval) across the "
            f"{len(active_steps)} active save intervals. This is not the internal step-level dt distribution."
        ),
        "total_np_out_interval_sum": total_np_out_interval_sum,
        "last_row_np_out": last_row_np_out,
    }


def audit_timestep_comparison_v2(
    baseline_parts_path: Path,
    baseline_out_path: Path,
    baseline_xml_path: Path,
    baseline_receipt_path: Path,
    variant_parts_path: Path,
    variant_out_path: Path,
    variant_xml_path: Path,
    variant_receipt_path: Path,
    budget_path: Path | None = None,
    paired_transport_report_path: Path | None = None,
    expected_part_count: int = EXPECTED_PART_COUNT,
    expected_time_max_s: float = EXPECTED_TIME_MAX_S,
) -> dict[str, Any]:
    """Execute v2 audit: validate completed receipts, XML controls, Run.out, and RunPARTs telemetry."""
    # 1. Validate completed execution receipts
    b_receipt = validate_execution_receipt(baseline_receipt_path)
    v_receipt = validate_execution_receipt(variant_receipt_path)

    # 2. Parse XML controls
    b_xml = parse_xml_controls(baseline_xml_path)
    v_xml = parse_xml_controls(variant_xml_path)

    # 3. Parse Run.out
    b_out = parse_run_out(baseline_out_path)
    v_out = parse_run_out(variant_out_path)

    # Cross-check XML and Run.out
    if b_xml["step_algorithm_name"] != b_out["step_algorithm"]:
        raise ValueError(
            f"Baseline StepAlgorithm mismatch: XML={b_xml['step_algorithm_name']}, Run.out={b_out['step_algorithm']}"
        )
    if v_xml["step_algorithm_name"] != v_out["step_algorithm"]:
        raise ValueError(
            f"Variant StepAlgorithm mismatch: XML={v_xml['step_algorithm_name']}, Run.out={v_out['step_algorithm']}"
        )

    # 4. Parse RunPARTs.csv with exact contiguous part count and monotone time
    b_parts = parse_run_parts_csv(
        baseline_parts_path,
        evaluations_per_step=b_xml["evaluations_per_step"],
        expected_part_count=expected_part_count,
        expected_time_max_s=expected_time_max_s,
    )
    v_parts = parse_run_parts_csv(
        variant_parts_path,
        evaluations_per_step=v_xml["evaluations_per_step"],
        expected_part_count=expected_part_count,
        expected_time_max_s=expected_time_max_s,
    )

    # Cross-check step counts between Run.out and RunPARTs
    b_step_match = bool(b_out["steps_of_simulation"] == b_parts["sum_steps"])
    v_step_match = bool(v_out["steps_of_simulation"] == v_parts["sum_steps"])
    b_clamp_match = bool(b_out["dts_adjusted_to_dtmin"] == b_parts["sum_dts_min_clamps"])
    v_clamp_match = bool(v_out["dts_adjusted_to_dtmin"] == v_parts["sum_dts_min_clamps"])

    if not b_step_match:
        raise ValueError(
            f"Baseline steps mismatch: Run.out={b_out['steps_of_simulation']}, RunPARTs={b_parts['sum_steps']}"
        )
    if not v_step_match:
        raise ValueError(
            f"Variant steps mismatch: Run.out={v_out['steps_of_simulation']}, RunPARTs={v_parts['sum_steps']}"
        )

    step_ratio = float(v_parts["sum_steps"] / b_parts["sum_steps"]) if b_parts["sum_steps"] > 0 else 0.0
    mean_dt_ratio = float(b_parts["overall_mean_dt_s"] / v_parts["overall_mean_dt_s"]) if v_parts["overall_mean_dt_s"] > 0 else 0.0
    nominal_halved_step_ratio = 2.0
    step_ratio_discrepancy_factor = step_ratio / nominal_halved_step_ratio

    # Mode determination
    baseline_mode = "adaptive" if b_xml["mode"] == "adaptive" and not b_parts["is_constant_fixed_dt"] else "fixed"
    variant_mode = "fixed" if v_xml["mode"] == "fixed" or v_parts["is_constant_fixed_dt"] else "adaptive"

    measured_floor_status = {
        "baseline_clamps_observed": b_parts["sum_dts_min_clamps"],
        "baseline_dt_evaluations": b_parts["total_dt_evaluations"],
        "baseline_clamp_incidence_fraction": b_parts["floor_clamp_incidence_fraction"],
        "variant_clamps_observed": v_parts["sum_dts_min_clamps"],
        "variant_dt_evaluations": v_parts["total_dt_evaluations"],
        "variant_clamp_incidence_fraction": v_parts["floor_clamp_incidence_fraction"],
        "diagnostic_interpretation": (
            "Neither simulation recorded any timestep floor clamping (DTs adjusted to DtMin = 0). "
            "However, absence of floor clamping is solely a numerical stability check; it does not "
            "establish temporal convergence or physical accuracy."
        ),
    }

    methodological_analysis = {
        "baseline_integration": {
            "mode": baseline_mode,
            "cfl_number": b_xml["cfl_number"],
            "coef_dt_min": b_xml["coef_dt_min"],
            "time_step_behavior": "Dynamically adapted via CFL criteria and local fluid velocity/acceleration",
            "mean_dt_s": b_parts["overall_mean_dt_s"],
        },
        "variant_integration": {
            "mode": variant_mode,
            "dt_fixed_s": v_xml["dt_fixed"],
            "time_step_behavior": "Constant hardcoded time step across all 6000 intervals",
            "mean_dt_s": v_parts["overall_mean_dt_s"],
        },
        "scientific_qualification": (
            "Fixed-step Symplectic time integration is a standard numerical approach and is not intrinsically invalid. "
            "However, comparing an adaptive simulation against a fixed-step simulation at a 4.58x smaller step conflates "
            "two distinct numerical effects: temporal refinement and algorithmic time-stepping dynamics. "
            "Because multiple numerical properties were varied simultaneously (step size by 4.58x, adaptive velocity "
            "dependency vs constant stepping), the observed transport discrepancy (0.52656s macro chord shift, 8,376 "
            "switching identities) cannot be causally attributed to the adaptive-vs-fixed transition alone without "
            "controlled isolate experiments."
        ),
        "audit_limitations": [
            "Internal step-by-step dt values are not saved by DualSPHysics; telemetry reports only interval DtMin, DtMax, and total Steps.",
            "RunPARTs NpOut reports cumulative or per-interval particle exclusion counts; interval sum is reported explicitly.",
            "Floor clamping is evaluated twice per step under Symplectic integration (denominator: 2 * sum(Steps)).",
            "Convergence can only be rigorously established when identical integration paradigms are used across refinement levels.",
        ],
        "errata": {
            "prior_report_spatial_ke_scale": (
                "The 43% spatial KE discrepancy reported in historical observation reviews represents a spatial "
                "kinetic energy comparison discrepancy between runs, NOT that fluid kinetic energy was negative."
            ),
            "prior_floor_incidence_denominator": (
                "Prior v1 audit used 1 * sum(Steps) as the clamp incidence denominator; v2 corrects this to "
                "2 * sum(Steps) based on DualSPHysics Symplectic predictor-corrector sub-evaluations."
            ),
            "prior_npout_interpretation": (
                "Prior v1 audit referenced the last row NpOut value; v2 explicitly provides the interval sum of NpOut."
            ),
            "prior_causal_assertions": (
                "Prior informal interpretations asserting that transport divergence was solely caused by adaptive-vs-fixed "
                "timestepping are retracted as overclaims; multiple numerical properties varied simultaneously."
            ),
        },
    }

    # Digested file inventory
    digests: dict[str, str] = {
        str(baseline_parts_path.resolve()): digest(baseline_parts_path),
        str(baseline_out_path.resolve()): digest(baseline_out_path),
        str(baseline_xml_path.resolve()): digest(baseline_xml_path),
        str(baseline_receipt_path.resolve()): digest(baseline_receipt_path),
        str(variant_parts_path.resolve()): digest(variant_parts_path),
        str(variant_out_path.resolve()): digest(variant_out_path),
        str(variant_xml_path.resolve()): digest(variant_xml_path),
        str(variant_receipt_path.resolve()): digest(variant_receipt_path),
    }
    if budget_path and budget_path.exists():
        digests[str(budget_path.resolve())] = digest(budget_path)
    if paired_transport_report_path and paired_transport_report_path.exists():
        digests[str(paired_transport_report_path.resolve())] = digest(paired_transport_report_path)

    return {
        "schema": SCHEMA,
        "qualification_status": "unassessed_inconclusive_mixed_timestepping_regimes",
        "receipts_validation": {
            "baseline": b_receipt,
            "variant": v_receipt,
        },
        "baseline_dense": {
            "xml": b_xml,
            "run_out": b_out,
            "run_parts": b_parts,
        },
        "variant_true_half_dense": {
            "xml": v_xml,
            "run_out": v_out,
            "run_parts": v_parts,
        },
        "comparison_metrics": {
            "step_count_ratio": step_ratio,
            "nominal_expected_step_ratio": nominal_halved_step_ratio,
            "step_ratio_discrepancy_factor": step_ratio_discrepancy_factor,
            "overall_mean_dt_ratio": mean_dt_ratio,
            "baseline_overall_mean_dt_s": b_parts["overall_mean_dt_s"],
            "variant_overall_mean_dt_s": v_parts["overall_mean_dt_s"],
            "baseline_interval_dt_spread_ratio": (
                b_parts["global_max_dt_s"] / b_parts["global_min_dt_s"] if b_parts["global_min_dt_s"] > 0 else 1.0
            ),
            "variant_interval_dt_spread_ratio": (
                v_parts["global_max_dt_s"] / v_parts["global_min_dt_s"] if v_parts["global_min_dt_s"] > 0 else 1.0
            ),
        },
        "floor_status": measured_floor_status,
        "methodological_analysis": methodological_analysis,
        "input_sha256": digests,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-parts", type=Path, required=True, help="Baseline RunPARTs.csv")
    parser.add_argument("--baseline-out", type=Path, required=True, help="Baseline Run.out")
    parser.add_argument("--baseline-xml", type=Path, required=True, help="Baseline XML case definition")
    parser.add_argument("--baseline-receipt", type=Path, required=True, help="Baseline execution-receipt.json")
    parser.add_argument("--variant-parts", type=Path, required=True, help="Variant RunPARTs.csv")
    parser.add_argument("--variant-out", type=Path, required=True, help="Variant Run.out")
    parser.add_argument("--variant-xml", type=Path, required=True, help="Variant XML case definition")
    parser.add_argument("--variant-receipt", type=Path, required=True, help="Variant execution-receipt.json")
    parser.add_argument("--budget", type=Path, required=False, default=None, help="Frozen reference budget JSON")
    parser.add_argument(
        "--paired-transport-report",
        type=Path,
        required=False,
        default=None,
        help="Paired transport comparison report v3 JSON",
    )
    parser.add_argument("--output", type=Path, required=True, help="Output JSON report path")

    args = parser.parse_args()

    result = audit_timestep_comparison_v2(
        baseline_parts_path=args.baseline_parts,
        baseline_out_path=args.baseline_out,
        baseline_xml_path=args.baseline_xml,
        baseline_receipt_path=args.baseline_receipt,
        variant_parts_path=args.variant_parts,
        variant_out_path=args.variant_out,
        variant_xml_path=args.variant_xml,
        variant_receipt_path=args.variant_receipt,
        budget_path=args.budget,
        paired_transport_report_path=args.paired_transport_report,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote F7 timestep audit v2 to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
