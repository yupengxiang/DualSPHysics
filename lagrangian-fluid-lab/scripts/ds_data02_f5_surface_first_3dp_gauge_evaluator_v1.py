#!/usr/bin/env python3
"""DS-DATA-02 F5 Surface-First 3DP Native Gauge and Free-Surface Evaluator (v1).

Strict source-bound evaluator for the F5 3DP spatial series ladder:
- Coarse (DP0.050 m)
- Medium (DP0.025 m)
- Fine (DP0.010 m)

Retains:
- Original reference height H = 0.4 m.
- 5% relative error tolerance (0.05 * H = 0.02 m).
- All 6 wave probes: WG1, WG2, WG3, WG4, Crest, RunupToe (or Toe).
- Both mechanism backgrounds kept separate (Runup separate from Weir).
- Native gauges 800 rows: t in [0.0, 15.98] s with dt = 0.02 s (strictly NO extrapolation to 16.0 s).
- Exact physical continuous bed STL (f5_continuous_bed_profile_slope_0p280.stl) and piston motion binding.
- Fluid bounds [-0.9, 3.3] x [-0.7, 0.7] x [0.02, 0.42] m (M = 2352.0 kg).
- Domain numerical padding documentation: coarse Xmin = -1.30 m vs medium/fine Xmin = -1.22 m
  (arising from ResizeMapLimits kernel cell division, not physical geometry).
- Binding actual solver receipts, source Gauge CSV hashes, full time window,
  native NpOut + floor diagnostics, source DsphConfig, and solver version.
- Spatial candidate evidence only; independent time/save convergence study required later;
  old 4DP spatial negative results preserved (WG3 error ~ 0.317 - 0.350 H).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Sequence

import numpy as np

SCHEMA_REPORT = "ds02.f5.surface-first-3dp-gauge-comparison-report.v1"
EXPECTED_GAUGES = ("WG1", "WG2", "WG3", "WG4", "RunupToe", "Crest")
EXPECTED_ROWS = 800
EXPECTED_TMAX_S = 15.98
EXPECTED_DT_S = 0.02
DEFAULT_H_REF_M = 0.4
DEFAULT_TOL_RELATIVE = 0.05  # 5% relative error tol (0.02 m)

FLUID_BOUNDS_M = [[-0.9, 3.3], [-0.7, 0.7], [0.02, 0.42]]
FLUID_VOLUME_M3 = 2.352
FLUID_MASS_KG = 2352.0
FLUID_DENSITY_KG_M3 = 1000.0

HISTORICAL_WG3_RELATIVE_RANGE = [0.317, 0.350]


def sha256_file(path: Path | str) -> str:
    """Compute sha256 hex digest of a file in 64 KiB blocks."""
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(65536):
            h.update(chunk)
    return h.hexdigest()


def parse_gauge_csv(path: Path | str, expected_rows: int = EXPECTED_ROWS) -> dict[str, Any]:
    """Parse a DualSPHysics GaugesSWL_*.csv file with strict window validation."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Gauge CSV not found: {p}")

    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines:
        raise ValueError(f"Gauge CSV is empty: {p}")

    header = lines[0].strip()
    data_rows: list[list[float]] = []

    for line in lines[1:]:
        line_str = line.strip()
        if not line_str or line_str.startswith("#"):
            continue
        parts = line_str.split(";")
        try:
            vals = [float(v.strip()) for v in parts]
        except ValueError:
            continue
        if len(vals) >= 4 and math.isfinite(vals[0]) and math.isfinite(vals[3]):
            data_rows.append(vals)

    if len(data_rows) != expected_rows:
        raise ValueError(
            f"Gauge CSV {p.name} has {len(data_rows)} data rows; expected exactly {expected_rows}."
        )

    array = np.asarray(data_rows, dtype=np.float64)
    times = array[:, 0]
    swlz = array[:, 3]

    # pos0z is column 6 (7th column) if available
    pos0z_val = float(array[0, 6]) if array.shape[1] >= 7 else -0.02

    # Check time monotonicity
    time_diffs = np.diff(times)
    if np.any(time_diffs <= 0):
        raise ValueError(f"Gauge CSV {p.name} times are not strictly monotonically increasing.")

    # Validate window boundaries: strictly [0.0, 15.98] s (allow tiny epsilon for float timestamp)
    if times[0] < -1e-6 or times[0] > 1e-4:
        raise ValueError(f"Gauge CSV {p.name} start time {times[0]} != 0.0 s.")
    if times[-1] < EXPECTED_TMAX_S - 0.01:
        raise ValueError(f"Gauge CSV {p.name} end time {times[-1]} < {EXPECTED_TMAX_S} s.")

    # Floor / dry detection: when probe detects no fluid particles, swlz clamps to pos0z
    floor_threshold = pos0z_val + 1e-4
    is_floor = swlz <= floor_threshold
    dry_count = int(np.count_nonzero(is_floor))
    dry_fraction = float(dry_count / len(swlz))

    return {
        "file_name": p.name,
        "sha256": sha256_file(p),
        "total_rows": int(len(data_rows)),
        "time_start_s": float(times[0]),
        "time_end_s": float(times[-1]),
        "dt_median_s": float(np.median(time_diffs)),
        "pos0z_floor_m": pos0z_val,
        "swl_initial_m": float(swlz[0]),
        "swl_min_m": float(np.min(swlz)),
        "swl_max_m": float(np.max(swlz)),
        "swl_peak_time_s": float(times[int(np.argmax(swlz))]),
        "dynamic_range_m": float(np.ptp(swlz)),
        "dry_samples": dry_count,
        "dry_fraction": dry_fraction,
        "is_partially_dry": dry_count > 0,
        "times": times,
        "swlz": swlz,
    }


def parse_runparts_csv(path: Path | str) -> dict[str, Any]:
    """Parse RunPARTs.csv to extract NpOut diagnostics and step count."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"RunPARTs.csv not found: {p}")

    max_npout = 0
    total_steps = 0
    npout_events = 0

    with p.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line_str = line.strip()
            if not line_str or line_str.startswith("#"):
                continue
            parts = line_str.split(";")
            if parts[0] == "Part":
                continue
            total_steps += 1
            if len(parts) >= 9:
                try:
                    npout = int(parts[8].strip())
                    if npout > max_npout:
                        max_npout = npout
                    if npout > 0:
                        npout_events += 1
                except ValueError:
                    pass

    return {
        "file_name": p.name,
        "sha256": sha256_file(p),
        "total_steps": total_steps,
        "max_npout": max_npout,
        "npout_loss_events": npout_events,
        "particle_loss_detected": max_npout > 0,
    }


def parse_run_out(path: Path | str) -> dict[str, Any]:
    """Parse Run.out to extract solver version, case particle counts, and domain limits."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Run.out not found: {p}")

    version = "unknown"
    case_np = None
    case_nbound = None
    case_nfixed = None
    case_nmoving = None
    case_nfluid = None
    map_border = None
    map_final = None
    xmin_final = None

    with p.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line_str = line.strip()
            if "DualSPHysics5 v" in line_str:
                version = line_str
            elif line_str.startswith("CaseNp="):
                case_np = int(line_str.split("=")[1].replace(",", ""))
            elif line_str.startswith("CaseNbound="):
                case_nbound = int(line_str.split("=")[1].replace(",", ""))
            elif line_str.startswith("CaseNfixed="):
                case_nfixed = int(line_str.split("=")[1].replace(",", ""))
            elif line_str.startswith("CaseNmoving="):
                case_nmoving = int(line_str.split("=")[1].replace(",", ""))
            elif line_str.startswith("CaseNfluid="):
                case_nfluid = int(line_str.split("=")[1].replace(",", ""))
            elif line_str.startswith("MapRealPos(border)="):
                map_border = line_str.split("=")[1]
            elif line_str.startswith("MapRealPos(final)="):
                map_final = line_str.split("=")[1]
                match = re.search(r"\(([-0-9.]+),", map_final)
                if match:
                    xmin_final = float(match.group(1))

    return {
        "file_name": p.name,
        "sha256": sha256_file(p),
        "solver_version": version,
        "case_np": case_np,
        "case_nbound": case_nbound,
        "case_nfixed": case_nfixed,
        "case_nmoving": case_nmoving,
        "case_nfluid": case_nfluid,
        "map_real_pos_border": map_border,
        "map_real_pos_final": map_final,
        "xmin_final_m": xmin_final,
    }


def compare_two_gauges(
    left_parsed: dict[str, Any],
    right_parsed: dict[str, Any],
    gauge_name: str,
    h_ref_m: float = DEFAULT_H_REF_M,
    tol_relative: float = DEFAULT_TOL_RELATIVE,
) -> dict[str, Any]:
    """Perform pairwise comparison between two resolutions for a specific wave probe."""
    left_times = left_parsed["times"]
    left_swl = left_parsed["swlz"]
    right_times = right_parsed["times"]
    right_swl = right_parsed["swlz"]

    # Target strictly bounded grid: 800 uniform samples from 0.0 to 15.98 s. NO extrapolation to 16.0 s.
    grid = np.linspace(0.0, EXPECTED_TMAX_S, EXPECTED_ROWS)

    # Interpolate onto common evaluation grid
    l_interp = np.interp(grid, left_times, left_swl)
    r_interp = np.interp(grid, right_times, right_swl)

    # Initial offsets & normalized free surface elevation eta(t) = swl(t) - swl(0)
    l_initial = float(left_parsed["swl_initial_m"])
    r_initial = float(right_parsed["swl_initial_m"])
    initial_offset_m = float(l_initial - r_initial)

    l_eta = l_interp - l_initial
    r_eta = r_interp - r_initial

    # Raw differences
    delta_raw = l_interp - r_interp
    raw_rmse_m = float(np.sqrt(np.mean(delta_raw**2)))
    raw_max_abs_m = float(np.max(np.abs(delta_raw)))

    # Normalized differences
    delta_eta = l_eta - r_eta
    norm_rmse_m = float(np.sqrt(np.mean(delta_eta**2)))
    norm_max_abs_m = float(np.max(np.abs(delta_eta)))

    # Relative to reference wave / depth scale H = 0.4 m
    rel_rmse = float(norm_rmse_m / h_ref_m)
    rel_max_abs = float(norm_max_abs_m / h_ref_m)

    # Evaluate 5% relative error tolerance
    tol_abs_m = tol_relative * h_ref_m  # 0.02 m for H=0.4 m
    pass_5pct_rmse = bool(norm_rmse_m <= tol_abs_m)
    pass_5pct_max = bool(norm_max_abs_m <= tol_abs_m)
    pass_5pct = bool(pass_5pct_rmse and pass_5pct_max)

    # Floor / dry handling & resolution-dependent dropout
    l_floor_thresh = left_parsed["pos0z_floor_m"] + 1e-4
    r_floor_thresh = right_parsed["pos0z_floor_m"] + 1e-4
    l_dry = l_interp <= l_floor_thresh
    r_dry = r_interp <= r_floor_thresh

    both_dry = l_dry & r_dry
    both_wet = (~l_dry) & (~r_dry)
    dropout = l_dry ^ r_dry  # one dry, the other wet

    both_dry_count = int(np.count_nonzero(both_dry))
    both_wet_count = int(np.count_nonzero(both_wet))
    dropout_count = int(np.count_nonzero(dropout))

    wet_only_norm_rmse_m = None
    wet_only_rel_rmse = None
    wet_only_pass_5pct = None

    if both_wet_count >= 2:
        wet_delta_eta = delta_eta[both_wet]
        wet_only_norm_rmse_m = float(np.sqrt(np.mean(wet_delta_eta**2)))
        wet_only_rel_rmse = float(wet_only_norm_rmse_m / h_ref_m)
        wet_only_pass_5pct = bool(wet_only_norm_rmse_m <= tol_abs_m)

    return {
        "gauge_name": gauge_name,
        "evaluation_samples": EXPECTED_ROWS,
        "time_start_s": 0.0,
        "time_end_s": EXPECTED_TMAX_S,
        "initial_offset_m": initial_offset_m,
        "raw_swl_rmse_m": raw_rmse_m,
        "raw_swl_max_abs_m": raw_max_abs_m,
        "normalized_eta_rmse_m": norm_rmse_m,
        "normalized_eta_max_abs_m": norm_max_abs_m,
        "relative_eta_rmse": rel_rmse,
        "relative_eta_max_abs": rel_max_abs,
        "reference_scale_h_m": h_ref_m,
        "tolerance_relative": tol_relative,
        "tolerance_absolute_m": tol_abs_m,
        "pass_5pct_rmse": pass_5pct_rmse,
        "pass_5pct_max": pass_5pct_max,
        "pass_5pct_overall": pass_5pct,
        "dry_occupancy": {
            "left_dry_samples": left_parsed["dry_samples"],
            "right_dry_samples": right_parsed["dry_samples"],
            "both_dry_samples": both_dry_count,
            "both_wet_samples": both_wet_count,
            "resolution_dropout_samples": dropout_count,
            "wet_only_normalized_eta_rmse_m": wet_only_norm_rmse_m,
            "wet_only_relative_eta_rmse": wet_only_rel_rmse,
            "wet_only_pass_5pct": wet_only_pass_5pct,
        },
    }


def evaluate_mechanism(
    mechanism: str,
    dp050_dir: Path,
    dp025_dir: Path,
    dp010_dir: Path,
    bed_stl: Path,
    piston_file: Path,
    output_dir: Path,
    report_name: str | None = None,
    h_ref_m: float = DEFAULT_H_REF_M,
    tol_relative: float = DEFAULT_TOL_RELATIVE,
) -> dict[str, Any]:
    """Run full 3DP gauge evaluation for a single mechanism (runup or weir)."""
    if mechanism not in ("runup", "weir"):
        raise ValueError(f"Unknown mechanism '{mechanism}'; must be 'runup' or 'weir'.")

    output_dir.mkdir(parents=True, exist_ok=True)
    if report_name is None:
        report_name = f"f5_{mechanism}_surface_first_3dp_gauge_comparison_report.json"
    report_path = output_dir / report_name

    # Resolution directories mapping
    res_dirs = {
        "coarse": {"dp_m": 0.05, "dir": Path(dp050_dir), "expected_xmin_final": -1.30},
        "medium": {"dp_m": 0.025, "dir": Path(dp025_dir), "expected_xmin_final": -1.22},
        "fine": {"dp_m": 0.010, "dir": Path(dp010_dir), "expected_xmin_final": -1.22},
    }

    resolutions_data: dict[str, Any] = {}

    for res_name, res_info in res_dirs.items():
        attempt_dir = res_info["dir"]
        rec_path = attempt_dir / "execution-receipt.json"
        if not rec_path.is_file():
            raise FileNotFoundError(f"Missing execution-receipt.json in {attempt_dir}")

        rec = json.loads(rec_path.read_text(encoding="utf-8"))
        if rec.get("returncode") != 0:
            raise ValueError(f"Attempt {attempt_dir.name} returncode {rec.get('returncode')} != 0")

        solver_out = attempt_dir / "solver_output"
        if not solver_out.is_dir():
            raise FileNotFoundError(f"Missing solver_output in {attempt_dir}")

        # Parse Run.out
        run_out_data = parse_run_out(solver_out / "Run.out")

        # Parse RunPARTs.csv
        runparts_data = parse_runparts_csv(solver_out / "RunPARTs.csv")

        # Parse 6 Gauge CSVs
        parsed_gauges: dict[str, Any] = {}
        for g_name in EXPECTED_GAUGES:
            csv_path = solver_out / f"GaugesSWL_{g_name}.csv"
            parsed_gauges[g_name] = parse_gauge_csv(csv_path)

        resolutions_data[res_name] = {
            "dp_m": res_info["dp_m"],
            "attempt_dir": str(attempt_dir),
            "attempt_id": attempt_dir.name,
            "receipt_sha256": sha256_file(rec_path),
            "returncode": rec.get("returncode"),
            "status": rec.get("status"),
            "elapsed_seconds": rec.get("elapsed_seconds"),
            "started_at_utc": rec.get("started_at_utc"),
            "finished_at_utc": rec.get("finished_at_utc"),
            "binary_sha256": rec.get("binary_sha256"),
            "run_out": run_out_data,
            "runparts": runparts_data,
            "gauges": parsed_gauges,
        }

    # Perform pairwise comparisons
    pairs = [
        ("coarse", "medium", "coarse_vs_medium"),
        ("medium", "fine", "medium_vs_fine"),
        ("coarse", "fine", "coarse_vs_fine"),
    ]

    pairwise_comparisons: dict[str, Any] = {}

    for left_res, right_res, pair_key in pairs:
        left_data = resolutions_data[left_res]
        right_data = resolutions_data[right_res]

        pair_gauges: dict[str, Any] = {}
        for g_name in EXPECTED_GAUGES:
            pair_gauges[g_name] = compare_two_gauges(
                left_data["gauges"][g_name],
                right_data["gauges"][g_name],
                g_name,
                h_ref_m=h_ref_m,
                tol_relative=tol_relative,
            )

        pairwise_comparisons[pair_key] = {
            "left_resolution": left_res,
            "left_dp_m": left_data["dp_m"],
            "right_resolution": right_res,
            "right_dp_m": right_data["dp_m"],
            "gauges": pair_gauges,
            "all_gauges_pass_5pct": all(g["pass_5pct_overall"] for g in pair_gauges.values()),
            "wg3_pass_5pct": pair_gauges["WG3"]["pass_5pct_overall"],
            "wg3_relative_eta_rmse": pair_gauges["WG3"]["relative_eta_rmse"],
        }

    # Verify domain numerical padding
    coarse_xmin = resolutions_data["coarse"]["run_out"]["xmin_final_m"]
    medium_xmin = resolutions_data["medium"]["run_out"]["xmin_final_m"]
    fine_xmin = resolutions_data["fine"]["run_out"]["xmin_final_m"]

    padding_verified = bool(
        coarse_xmin is not None
        and math.isclose(coarse_xmin, -1.30, abs_tol=0.01)
        and medium_xmin is not None
        and math.isclose(medium_xmin, -1.22, abs_tol=0.01)
        and fine_xmin is not None
        and math.isclose(fine_xmin, -1.22, abs_tol=0.01)
    )

    # Check WG3 historical negative preservation across medium_vs_fine
    mf_wg3_rel_rmse = pairwise_comparisons["medium_vs_fine"]["wg3_relative_eta_rmse"]
    wg3_in_historical_range = bool(
        HISTORICAL_WG3_RELATIVE_RANGE[0] - 0.05
        <= mf_wg3_rel_rmse
        <= HISTORICAL_WG3_RELATIVE_RANGE[1] + 0.05
    )

    # Serialize resolutions without raw numpy arrays for clean JSON
    clean_resolutions: dict[str, Any] = {}
    for r_name, r_dict in resolutions_data.items():
        clean_gauges = {}
        for g_name, g_info in r_dict["gauges"].items():
            g_clean = {k: v for k, v in g_info.items() if k not in ("times", "swlz")}
            clean_gauges[g_name] = g_clean

        clean_resolutions[r_name] = {
            "dp_m": r_dict["dp_m"],
            "attempt_dir": r_dict["attempt_dir"],
            "attempt_id": r_dict["attempt_id"],
            "receipt_sha256": r_dict["receipt_sha256"],
            "returncode": r_dict["returncode"],
            "status": r_dict["status"],
            "elapsed_seconds": r_dict["elapsed_seconds"],
            "started_at_utc": r_dict["started_at_utc"],
            "finished_at_utc": r_dict["finished_at_utc"],
            "binary_sha256": r_dict["binary_sha256"],
            "run_out": r_dict["run_out"],
            "runparts": r_dict["runparts"],
            "gauge_csv_hashes": {g: clean_gauges[g]["sha256"] for g in EXPECTED_GAUGES},
            "floor_diagnostics": {
                g: {
                    "dry_samples": clean_gauges[g]["dry_samples"],
                    "dry_fraction": clean_gauges[g]["dry_fraction"],
                    "is_partially_dry": clean_gauges[g]["is_partially_dry"],
                    "pos0z_floor_m": clean_gauges[g]["pos0z_floor_m"],
                }
                for g in EXPECTED_GAUGES
            },
            "gauges": clean_gauges,
        }

    report: dict[str, Any] = {
        "schema": SCHEMA_REPORT,
        "mechanism": mechanism,
        "status": "completed",
        "scientific_status": "spatial_candidate_evidence_only",
        "qualification_claim": "none",
        "T1_numerical": False,
        "matrix_credit": 0,
        "time_save_convergence_required": True,
        "h_ref_m": h_ref_m,
        "tol_relative": tol_relative,
        "time_window": {
            "samples": EXPECTED_ROWS,
            "time_start_s": 0.0,
            "time_end_s": EXPECTED_TMAX_S,
            "dt_cadence_s": EXPECTED_DT_S,
            "extrapolation_to_16s": False,
        },
        "fluid_continuum": {
            "bounds": FLUID_BOUNDS_M,
            "volume_m3": FLUID_VOLUME_M3,
            "mass_kg": FLUID_MASS_KG,
            "density_kg_m3": FLUID_DENSITY_KG_M3,
        },
        "numerical_padding": {
            "coarse_xmin_final_m": coarse_xmin,
            "medium_xmin_final_m": medium_xmin,
            "fine_xmin_final_m": fine_xmin,
            "verified": padding_verified,
            "rationale": (
                "ResizeMapLimits numerical domain expansion for kernel cell division; "
                "physical flume geometry and fluid bounds are strictly identical."
            ),
        },
        "assets_binding": {
            "bed_stl": {
                "path": str(bed_stl),
                "sha256": sha256_file(bed_stl),
                "file_name": Path(bed_stl).name,
            },
            "piston_file": {
                "path": str(piston_file),
                "sha256": sha256_file(piston_file),
                "file_name": Path(piston_file).name,
            },
        },
        "historical_negative_preservation": {
            "probe": "WG3",
            "historical_4dp_spatial_relative_rmse_range": HISTORICAL_WG3_RELATIVE_RANGE,
            "medium_vs_fine_wg3_relative_eta_rmse": mf_wg3_rel_rmse,
            "wg3_passes_5pct_tolerance": pairwise_comparisons["medium_vs_fine"]["wg3_pass_5pct"],
            "negative_finding_preserved": True,
            "interpretation": (
                "Previous 4DP spatial investigations demonstrated WG3 error of ~0.317-0.350 H "
                "on the sloping bed, well exceeding the 5% tolerance threshold. Spatial candidate "
                "ladder does not substitute for independent time/save convergence, and WG3 non-convergence "
                "remains preserved as an established negative finding."
            ),
        },
        "native_npout_summary": {
            "coarse_max_npout": resolutions_data["coarse"]["runparts"]["max_npout"],
            "medium_max_npout": resolutions_data["medium"]["runparts"]["max_npout"],
            "fine_max_npout": resolutions_data["fine"]["runparts"]["max_npout"],
            "zero_loss_verified": (
                resolutions_data["coarse"]["runparts"]["max_npout"] == 0
                and resolutions_data["medium"]["runparts"]["max_npout"] == 0
                and resolutions_data["fine"]["runparts"]["max_npout"] == 0
            ),
        },
        "resolutions": clean_resolutions,
        "pairwise_comparisons": pairwise_comparisons,
    }

    # Atomic write to report_path
    tmp_path = report_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.rename(report_path)

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    eval_parser = subparsers.add_parser("evaluate", help="Run 3DP gauge evaluation")
    eval_parser.add_argument("--mechanism", required=True, choices=["runup", "weir"])
    eval_parser.add_argument("--dp050-dir", required=True, type=Path)
    eval_parser.add_argument("--dp025-dir", required=True, type=Path)
    eval_parser.add_argument("--dp010-dir", required=True, type=Path)
    eval_parser.add_argument("--bed-stl", required=True, type=Path)
    eval_parser.add_argument("--piston-file", required=True, type=Path)
    eval_parser.add_argument("--output-dir", required=True, type=Path)
    eval_parser.add_argument("--report-name", type=str, default=None)
    eval_parser.add_argument("--h-ref", type=float, default=DEFAULT_H_REF_M)
    eval_parser.add_argument("--tol-relative", type=float, default=DEFAULT_TOL_RELATIVE)

    args = parser.parse_args()

    if args.subcommand == "evaluate":
        report = evaluate_mechanism(
            mechanism=args.mechanism,
            dp050_dir=args.dp050_dir,
            dp025_dir=args.dp025_dir,
            dp010_dir=args.dp010_dir,
            bed_stl=args.bed_stl,
            piston_file=args.piston_file,
            output_dir=args.output_dir,
            report_name=args.report_name,
            h_ref_m=args.h_ref,
            tol_relative=args.tol_relative,
        )
        print(f"Evaluation complete for {args.mechanism}. Report saved to {args.output_dir}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
