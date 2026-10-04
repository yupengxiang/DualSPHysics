#!/usr/bin/env python3
"""DS-DATA-02 F5 Fine Halfstep Gauge Discrepancy & Concentration Audit (v1).

Strict source-grounded CPU audit script for the F5 two-mechanism fine halfstep series:
- Compares unmodified timestamps original linear interpolation on [0.0, 15.98] s as Root035.
- Retains entire primary error over full 800 samples without phase alignment or sample selection.
- Identifies individual samples and time windows contributing maximum discrepancies.
- Computes error concentration (top 1%, top 5%, top 10% of samples contributing to total SSE).
- Evaluates descriptive SWL floor flags (floor nominal, floor halfstep, dropout, both wet).
- Pins exact source CSV and execution receipt hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

SCHEMA_AUDIT = "ds02.f5.halfstep-discrepancy-audit.v1"
EXPECTED_GAUGES = ("WG1", "WG2", "WG3", "WG4", "RunupToe", "Crest")
EXPECTED_ROWS = 800
EXPECTED_TMAX_S = 15.98
DEFAULT_H_REF_M = 0.40
DEFAULT_INTEGRATION_TOL = 0.01  # 1% integration allocation (0.004 m)

BED_EQUATION_TOE_X_M = 3.55
BED_SLOPE = 0.280

GAUGE_COORDINATES: dict[str, tuple[float, float]] = {
    "WG1": (2.00, 0.0),
    "WG2": (3.10, 0.0),
    "RunupToe": (3.55, 0.0),
    "WG3": (4.35, 0.0),
    "WG4": (5.45, 0.0),
    "Crest": (6.70, 0.0),
}


def compute_bed_z(x_m: float) -> float:
    """Calculate continuous bed elevation at coordinate x."""
    if x_m <= BED_EQUATION_TOE_X_M:
        return 0.0
    return (x_m - BED_EQUATION_TOE_X_M) * BED_SLOPE


def sha256_file(path: Path | str) -> str:
    """Compute sha256 hex digest of a file in 64 KiB blocks."""
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(65536):
            h.update(chunk)
    return h.hexdigest()


def read_gauge_csv(path: Path | str, expected_rows: int = EXPECTED_ROWS) -> dict[str, Any]:
    """Parse DualSPHysics GaugesSWL_*.csv file with strict window validation."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Gauge CSV not found: {p}")

    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines:
        raise ValueError(f"Gauge CSV is empty: {p}")

    times: list[float] = []
    swlz: list[float] = []
    pos0z = -0.02

    for line in lines:
        line_str = line.strip()
        if not line_str or line_str.startswith("#"):
            continue
        parts = line_str.split(";")
        if len(parts) >= 4:
            try:
                t = float(parts[0].strip())
                s = float(parts[3].strip())
                if len(parts) >= 7:
                    pos0z = float(parts[6].strip())
                times.append(t)
                swlz.append(s)
            except ValueError:
                continue

    if len(times) != expected_rows:
        raise ValueError(
            f"Gauge CSV {p.name} has {len(times)} rows; expected exactly {expected_rows}."
        )

    t_arr = np.asarray(times, dtype=np.float64)
    s_arr = np.asarray(swlz, dtype=np.float64)

    if np.any(np.diff(t_arr) <= 0):
        raise ValueError(f"Timestamps in {p.name} are not strictly monotonic.")

    return {
        "file_name": p.name,
        "path": str(p),
        "sha256": sha256_file(p),
        "rows": len(times),
        "time_start_s": float(t_arr[0]),
        "time_end_s": float(t_arr[-1]),
        "pos0z_m": float(pos0z),
        "swl_initial_m": float(s_arr[0]),
        "times": t_arr,
        "swlz": s_arr,
    }


def audit_single_gauge_discrepancy(
    nominal_gauge: dict[str, Any],
    halfstep_gauge: dict[str, Any],
    gauge_name: str,
    h_ref_m: float = DEFAULT_H_REF_M,
    tol_rel: float = DEFAULT_INTEGRATION_TOL,
) -> dict[str, Any]:
    """Perform detailed pointwise discrepancy and concentration audit for one probe."""
    grid = np.linspace(0.0, EXPECTED_TMAX_S, EXPECTED_ROWS)

    t_nom = nominal_gauge["times"]
    s_nom = nominal_gauge["swlz"]
    t_half = halfstep_gauge["times"]
    s_half = halfstep_gauge["swlz"]

    p0_nom = nominal_gauge["pos0z_m"]
    p0_half = halfstep_gauge["pos0z_m"]

    # Root035 / Root042 standard linear interpolation
    s_nom_i = np.interp(grid, t_nom, s_nom)
    s_half_i = np.interp(grid, t_half, s_half)

    eta_nom = s_nom_i - nominal_gauge["swl_initial_m"]
    eta_half = s_half_i - halfstep_gauge["swl_initial_m"]

    delta_eta = eta_nom - eta_half
    abs_err = np.abs(delta_eta)
    sq_err = delta_eta**2

    # Global primary metrics across ALL 800 samples (unmodified, full window)
    total_sse = float(np.sum(sq_err))
    rmse_m = float(np.sqrt(np.mean(sq_err)))
    max_abs_m = float(np.max(abs_err))
    rel_rmse = float(rmse_m / h_ref_m)
    rel_max_abs = float(max_abs_m / h_ref_m)

    tol_abs_m = tol_rel * h_ref_m  # 0.004 m for 1% of 0.4 m
    within_frozen_rmse = bool(rel_rmse <= tol_rel)
    within_frozen_max = bool(rel_max_abs <= tol_rel)
    conjunction_pass = bool(within_frozen_rmse and within_frozen_max)

    # Descriptive floor and bed embedding flags
    x_coord, y_coord = GAUGE_COORDINATES.get(gauge_name, (0.0, 0.0))
    z_bed = compute_bed_z(x_coord)
    embed_depth_nom = float(z_bed - p0_nom)
    embed_depth_half = float(z_bed - p0_half)

    # Floor threshold with 2 mm tolerance to account for linear interpolation sub-frame timestamp jitter
    floor_tolerance_m = 0.002
    is_floor_nom = s_nom_i <= (p0_nom + floor_tolerance_m)
    is_floor_half = s_half_i <= (p0_half + floor_tolerance_m)
    is_dropout = is_floor_nom ^ is_floor_half
    is_both_floor = is_floor_nom & is_floor_half
    is_both_wet = (~is_floor_nom) & (~is_floor_half)

    # Maximum discrepancy localization
    max_idx = int(np.argmax(abs_err))
    max_time_s = float(grid[max_idx])
    max_discrepancy_event = {
        "sample_index": max_idx,
        "time_s": max_time_s,
        "absolute_error_m": float(abs_err[max_idx]),
        "relative_error_to_H": float(abs_err[max_idx] / h_ref_m),
        "nominal_swl_m": float(s_nom_i[max_idx]),
        "halfstep_swl_m": float(s_half_i[max_idx]),
        "nominal_eta_m": float(eta_nom[max_idx]),
        "halfstep_eta_m": float(eta_half[max_idx]),
        "nominal_at_floor": bool(is_floor_nom[max_idx]),
        "halfstep_at_floor": bool(is_floor_half[max_idx]),
        "is_dropout_artifact": bool(is_dropout[max_idx]),
        "local_bed_z_m": float(z_bed),
    }

    # Top 5 peak discrepancy samples
    top_indices = np.argsort(abs_err)[-5:][::-1]
    top_discrepancies: list[dict[str, Any]] = []
    for idx in top_indices:
        top_discrepancies.append(
            {
                "sample_index": int(idx),
                "time_s": float(grid[idx]),
                "absolute_error_m": float(abs_err[idx]),
                "relative_error_to_H": float(abs_err[idx] / h_ref_m),
                "nominal_swl_m": float(s_nom_i[idx]),
                "halfstep_swl_m": float(s_half_i[idx]),
                "nominal_at_floor": bool(is_floor_nom[idx]),
                "halfstep_at_floor": bool(is_floor_half[idx]),
                "is_dropout_artifact": bool(is_dropout[idx]),
            }
        )

    # Contributor concentration analysis
    sorted_sq = np.sort(sq_err)[::-1]
    top1_count = 8  # 1% of 800
    top5_count = 40  # 5% of 800
    top10_count = 80  # 10% of 800

    concentration = {
        "total_sum_squared_error_m2": total_sse,
        "top_1pct_samples_sse_fraction": float(np.sum(sorted_sq[:top1_count]) / total_sse)
        if total_sse > 0
        else 0.0,
        "top_5pct_samples_sse_fraction": float(np.sum(sorted_sq[:top5_count]) / total_sse)
        if total_sse > 0
        else 0.0,
        "top_10pct_samples_sse_fraction": float(np.sum(sorted_sq[:top10_count]) / total_sse)
        if total_sse > 0
        else 0.0,
        "samples_exceeding_tolerance_budget": int(np.count_nonzero(abs_err > tol_abs_m)),
        "fraction_samples_exceeding_tolerance": float(np.count_nonzero(abs_err > tol_abs_m) / EXPECTED_ROWS),
    }

    # High discrepancy contiguous time windows (where abs_err > tol_abs_m)
    above_tol = abs_err > tol_abs_m
    high_discrepancy_windows: list[dict[str, Any]] = []
    in_window = False
    win_start = 0
    for i in range(len(above_tol)):
        if above_tol[i] and not in_window:
            in_window = True
            win_start = i
        elif not above_tol[i] and in_window:
            in_window = False
            win_err = abs_err[win_start:i]
            high_discrepancy_windows.append(
                {
                    "time_start_s": float(grid[win_start]),
                    "time_end_s": float(grid[i - 1]),
                    "duration_s": float(grid[i - 1] - grid[win_start]),
                    "samples_count": int(i - win_start),
                    "window_max_abs_m": float(np.max(win_err)),
                    "window_max_rel_to_H": float(np.max(win_err) / h_ref_m),
                }
            )
    if in_window:
        win_err = abs_err[win_start:]
        high_discrepancy_windows.append(
            {
                "time_start_s": float(grid[win_start]),
                "time_end_s": float(grid[-1]),
                "duration_s": float(grid[-1] - grid[win_start]),
                "samples_count": int(len(above_tol) - win_start),
                "window_max_abs_m": float(np.max(win_err)),
                "window_max_rel_to_H": float(np.max(win_err) / h_ref_m),
            }
        )

    # Sort windows by peak discrepancy descending and retain top 3
    high_discrepancy_windows.sort(key=lambda w: w["window_max_abs_m"], reverse=True)

    return {
        "gauge_name": gauge_name,
        "coordinates": {"x_m": x_coord, "y_m": y_coord, "bed_z_m": float(z_bed)},
        "probe_baseline": {
            "nominal_pos0z_m": p0_nom,
            "halfstep_pos0z_m": p0_half,
            "solid_embedding_depth_m": embed_depth_nom,
            "solid_embedding_ratio_to_H": float(embed_depth_nom / h_ref_m),
        },
        "primary_error_metrics": {
            "h_reference_m": h_ref_m,
            "integration_budget_relative": tol_rel,
            "integration_budget_absolute_m": tol_abs_m,
            "rmse_m": rmse_m,
            "relative_eta_rmse": rel_rmse,
            "max_abs_m": max_abs_m,
            "relative_eta_max_abs": rel_max_abs,
            "within_frozen_time_RMSE": within_frozen_rmse,
            "within_frozen_time_maximum": within_frozen_max,
            "conjunction_pass": conjunction_pass,
        },
        "descriptive_floor_diagnostics": {
            "nominal_floor_samples": int(np.count_nonzero(is_floor_nom)),
            "halfstep_floor_samples": int(np.count_nonzero(is_floor_half)),
            "dropout_samples": int(np.count_nonzero(is_dropout)),
            "both_floor_samples": int(np.count_nonzero(is_both_floor)),
            "both_wet_samples": int(np.count_nonzero(is_both_wet)),
            "note": "Descriptive only; contributor concentration and floor flags detail where discrepancies concentrate in time and space; they do NOT alter primary metric and do NOT constitute causal proof.",
        },
        "max_discrepancy_event": max_discrepancy_event,
        "top_peak_discrepancies": top_discrepancies,
        "concentration": concentration,
        "top_high_discrepancy_windows": high_discrepancy_windows[:3],
    }


def execute_audit(
    source_bindings: Mapping[str, Any],
    h_ref_m: float = DEFAULT_H_REF_M,
    tol_rel: float = DEFAULT_INTEGRATION_TOL,
) -> dict[str, Any]:
    """Execute complete bounded CPU discrepancy and concentration audit for all pairs."""
    results: list[dict[str, Any]] = []

    for pair_key, pair_meta in source_bindings.items():
        mechanism = pair_meta["mechanism"]
        nom_meta = pair_meta["nominal"]
        half_meta = pair_meta["halfstep"]

        pair_audit: dict[str, Any] = {
            "mechanism": mechanism,
            "pair_key": pair_key,
            "nominal_case_id": nom_meta["case_id"],
            "halfstep_case_id": half_meta["case_id"],
            "nominal_receipt_sha256": sha256_file(nom_meta["receipt"]),
            "halfstep_receipt_sha256": sha256_file(half_meta["receipt"]),
            "gauges": {},
            "mechanism_conjunction_pass": True,
        }

        for g in EXPECTED_GAUGES:
            nom_csv_path = nom_meta["gauges"][g]
            half_csv_path = half_meta["gauges"][g]

            nom_gauge = read_gauge_csv(nom_csv_path)
            half_gauge = read_gauge_csv(half_csv_path)

            g_audit = audit_single_gauge_discrepancy(
                nom_gauge, half_gauge, g, h_ref_m=h_ref_m, tol_rel=tol_rel
            )
            pair_audit["gauges"][g] = g_audit

            if not g_audit["primary_error_metrics"]["conjunction_pass"]:
                pair_audit["mechanism_conjunction_pass"] = False

        results.append(pair_audit)

    return {
        "schema": SCHEMA_AUDIT,
        "governance": {
            "evaluation_standard": "Root035/Root042 unmodified linear interpolation on [0.0, 15.98] s",
            "time_window_s": [0.0, EXPECTED_TMAX_S],
            "samples_evaluated": EXPECTED_ROWS,
            "h_reference_m": h_ref_m,
            "integration_allocation": tol_rel,
            "phase_alignment_applied": False,
            "time_shifting_applied": False,
            "dry_cohort_dropping_applied": False,
            "q_n_status": "not_granted",
            "production_approval": "none",
            "permanence_of_prior_spatial_failure": "Authentic negative result; unchanged.",
        },
        "pairs": results,
    }


def parse_args(args: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="F5 Fine Halfstep Gauge Discrepancy & Concentration Audit"
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Optional path to write JSON audit report.",
    )
    parser.add_argument(
        "--verify-root",
        action="store_true",
        help="Verify exact replication against Root042 comparison JSON.",
    )
    return parser.parse_args(args)


DEFAULT_DATA_BINDINGS = {
    "runup": {
        "mechanism": "runup",
        "nominal": {
            "case_id": "F5_REF_RUNUP_DP010_SURFACE_FIRST_SUPPORT_024",
            "receipt": "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP010_SURFACE_FIRST_SUPPORT_024/root-runup-surface-first-full16-native-027/execution-receipt.json",
            "gauges": {
                g: f"/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP010_SURFACE_FIRST_SUPPORT_024/root-runup-surface-first-full16-native-027/solver_output/GaugesSWL_{g}.csv"
                for g in EXPECTED_GAUGES
            },
        },
        "halfstep": {
            "case_id": "F5_REF_RUNUP_DP010_TEMPORAL_HALFSTEP_040",
            "receipt": "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP010_TEMPORAL_HALFSTEP_040/root-runup-fine-temporal-halfstep-cfl01-dtmin025-full16-040/execution-receipt.json",
            "gauges": {
                g: f"/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP010_TEMPORAL_HALFSTEP_040/root-runup-fine-temporal-halfstep-cfl01-dtmin025-full16-040/solver_output/GaugesSWL_{g}.csv"
                for g in EXPECTED_GAUGES
            },
        },
    },
    "weir": {
        "mechanism": "weir",
        "nominal": {
            "case_id": "F5_REF_WEIR_DP010_SURFACE_FIRST_SUPPORT_024",
            "receipt": "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_WEIR_DP010_SURFACE_FIRST_SUPPORT_024/root-weir-surface-first-full16-native-027/execution-receipt.json",
            "gauges": {
                g: f"/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_WEIR_DP010_SURFACE_FIRST_SUPPORT_024/root-weir-surface-first-full16-native-027/solver_output/GaugesSWL_{g}.csv"
                for g in EXPECTED_GAUGES
            },
        },
        "halfstep": {
            "case_id": "F5_REF_WEIR_DP010_TEMPORAL_HALFSTEP_040",
            "receipt": "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_WEIR_DP010_TEMPORAL_HALFSTEP_040/root-weir-fine-temporal-halfstep-cfl01-dtmin025-full16-040/execution-receipt.json",
            "gauges": {
                g: f"/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_WEIR_DP010_TEMPORAL_HALFSTEP_040/root-weir-fine-temporal-halfstep-cfl01-dtmin025-full16-040/solver_output/GaugesSWL_{g}.csv"
                for g in EXPECTED_GAUGES
            },
        },
    },
}


def main() -> int:
    args = parse_args()
    report = execute_audit(DEFAULT_DATA_BINDINGS)

    if args.verify_root:
        root_comp_path = Path(
            "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_FINE_ACTUAL_FULL_HALFSTEP_ALL_GAUGES/root-fine-two-mechanism-native-schedule-halfstep-all-six-gauges-042/halfstep-gauge-comparison.json"
        )
        if root_comp_path.is_file():
            with root_comp_path.open() as f:
                root_comp = json.load(f)
            for pair_idx, pair_data in enumerate(report["pairs"]):
                root_pair = root_comp["pairs"][pair_idx]
                for root_g in root_pair["gauges"]:
                    gname = root_g["gauge_name"]
                    audit_g = pair_data["gauges"][gname]["primary_error_metrics"]
                    np.testing.assert_allclose(
                        audit_g["relative_eta_rmse"],
                        root_g["relative_eta_rmse"],
                        rtol=1e-4,
                        atol=1e-5,
                    )
                    np.testing.assert_allclose(
                        audit_g["relative_eta_max_abs"],
                        root_g["relative_eta_max_abs"],
                        rtol=1e-4,
                        atol=1e-5,
                    )
            print("VERIFICATION: Audit metrics strictly match Root042 reference JSON.")

    json_str = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json_str, encoding="utf-8")
        print(f"Audit report written to {args.output}")
    else:
        print(json_str)

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
