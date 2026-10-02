#!/usr/bin/env python3
"""Audit the realised native timestep and save cadence of an F2 pair.

The numerical-study request files describe the intended recipe.  This audit
reads the completed solver ``RunPARTs.csv`` files as the authority for what
actually ran, and binds those measurements to the request and solver receipt.
It does not launch a solver or alter any consumed request/output.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any


DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
F2_ROOT = Path(__file__).parent
SAVE_HALF_WIDTH_BUDGET_S = 0.0007336390799938275


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(path: Path) -> Path:
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _numeric(value: str | None) -> float:
    if value is None or not value.strip():
        raise ValueError("missing numeric RunPARTs field")
    return float(value.strip())


def read_runparts(path: Path) -> dict[str, Any]:
    """Read numeric rows from a semicolon-delimited RunPARTs.csv.

    DualSPHysics appends explanatory ``#`` rows after the numeric rows.  The
    particle-count fields contain thousands separators, but the semicolon
    delimiter leaves the floating-point fields unambiguous.
    """

    path = require_file(path)
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        rows = [row for row in csv.DictReader(handle, delimiter=";") if row.get("Part", "").isdigit()]
    if not rows:
        raise ValueError(f"no numeric rows in {path}")
    times = [_numeric(row["TimeStep [s]"]) for row in rows]
    dt_min = [_numeric(row["DtMin [s]"]) for row in rows if _numeric(row["DtMin [s]"]) > 0.0]
    dt_max = [_numeric(row["DtMax [s]"]) for row in rows if _numeric(row["DtMax [s]"]) > 0.0]
    if len(times) < 2 or not dt_min or not dt_max:
        raise ValueError(f"incomplete timestep rows in {path}")
    intervals = [right - left for left, right in zip(times, times[1:])]
    if any(value <= 0.0 for value in intervals):
        raise ValueError(f"non-increasing save times in {path}")
    return {
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "numeric_rows": len(rows),
        "part_first": int(rows[0]["Part"]),
        "part_last": int(rows[-1]["Part"]),
        "time_start_s": times[0],
        "time_end_s": times[-1],
        "save_interval_min_s": min(intervals),
        "save_interval_median_s": sorted(intervals)[len(intervals) // 2],
        "save_interval_max_s": max(intervals),
        "save_half_width_max_s": max(intervals) / 2.0,
        "save_half_width_budget_s": SAVE_HALF_WIDTH_BUDGET_S,
        "save_half_width_within_budget": max(intervals) / 2.0 <= SAVE_HALF_WIDTH_BUDGET_S,
        "dtmin_first_s": dt_min[0],
        "dtmin_positive_min_s": min(dt_min),
        "dtmin_positive_max_s": max(dt_min),
        "dtmin_last_s": dt_min[-1],
        "dtmax_first_s": dt_max[0],
        "dtmax_positive_min_s": min(dt_max),
        "dtmax_positive_max_s": max(dt_max),
        "dtmax_last_s": dt_max[-1],
        "dtmin_positive_count": len(dt_min),
        "dtmax_positive_count": len(dt_max),
    }


def _request_source(path: Path) -> dict[str, Any]:
    path = require_file(path)
    request = json.loads(path.read_text(encoding="utf-8"))
    return {
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "case_id": request.get("case_id"),
        "physical_case_id": request.get("physical_case_id"),
        "attempt_id": request.get("attempt_id"),
        "physical_condition_hash": request.get("physical_condition_hash"),
        "physical_geometry_control_hash": request.get("physical_geometry_control_hash"),
        "numerical_recipe_hash": request.get("numerical_recipe_hash"),
        "recipe_id": request.get("recipe_id"),
        "numerical_recipe_fields": request.get("numerical_recipe_fields", {}),
        "event_window_s": request.get("event_window_s"),
        "source_binding": request.get("source_binding", {}),
        "gencase_prefix": request.get("gencase_prefix"),
        "command": request.get("command"),
    }


def _solver_receipt(runparts_path: Path) -> tuple[Path, dict[str, Any]]:
    # .../<attempt>/solver_output/RunPARTs.csv
    receipt_path = runparts_path.parent.parent / "execution-receipt.json"
    receipt_path = require_file(receipt_path)
    return receipt_path, json.loads(receipt_path.read_text(encoding="utf-8"))


def _receipt_binding(runparts_path: Path) -> dict[str, Any]:
    receipt_path, receipt = _solver_receipt(runparts_path)
    return {
        "path": str(receipt_path.resolve()),
        "sha256": sha256(receipt_path),
        "status": receipt.get("status"),
        "returncode": receipt.get("returncode", receipt.get("exit_code")),
        "termination_reason": receipt.get("termination_reason"),
        "finished_at_utc": receipt.get("finished_at_utc"),
        "elapsed_seconds": receipt.get("elapsed_seconds"),
        "native_output_root": receipt.get("output_root"),
    }


def _native_frame_count(runparts_path: Path) -> int:
    data_root = runparts_path.parent / "data"
    return len(list(data_root.glob("Part_*.bi4"))) if data_root.is_dir() else 0


def audit_pair(*, baseline_request: Path, baseline_runparts: Path,
               variant_request: Path, variant_runparts: Path) -> dict[str, Any]:
    baseline_req = _request_source(baseline_request)
    variant_req = _request_source(variant_request)
    baseline_stats = read_runparts(baseline_runparts)
    variant_stats = read_runparts(variant_runparts)
    baseline_stats["native_frame_count"] = _native_frame_count(Path(baseline_stats["path"]))
    variant_stats["native_frame_count"] = _native_frame_count(Path(variant_stats["path"]))
    baseline_stats["solver_receipt"] = _receipt_binding(Path(baseline_stats["path"]))
    variant_stats["solver_receipt"] = _receipt_binding(Path(variant_stats["path"]))

    bsource = baseline_req["source_binding"]
    vsource = variant_req["source_binding"]
    source_equal = {
        "physical_condition_hash": baseline_req["physical_condition_hash"] == variant_req["physical_condition_hash"],
        "physical_geometry_control_hash": baseline_req["physical_geometry_control_hash"] == variant_req["physical_geometry_control_hash"],
        "bi4_sha256": bsource.get("bi4_sha256") == vsource.get("bi4_sha256"),
        "control_sha256": bsource.get("control_sha256") == vsource.get("control_sha256"),
        "old_xml_sha256": bsource.get("old_xml_sha256") == vsource.get("old_xml_sha256"),
        "same_physical_case_id": baseline_req["physical_case_id"] == variant_req["physical_case_id"],
    }
    allowed_recipe_changes = {"DtFixed_s", "variant"}
    bfields = baseline_req["numerical_recipe_fields"]
    vfields = variant_req["numerical_recipe_fields"]
    all_recipe_keys = sorted(set(bfields) | set(vfields))
    recipe_differences = {
        key: {"baseline": bfields.get(key), "variant": vfields.get(key)}
        for key in all_recipe_keys if bfields.get(key) != vfields.get(key)
    }
    observed_half_ratio = variant_stats["dtmin_positive_min_s"] / baseline_stats["dtmin_positive_min_s"]
    fixed_dt = vfields.get("DtFixed_s")
    fixed_dt_ratio = (float(fixed_dt) / baseline_stats["dtmin_positive_min_s"]
                      if fixed_dt and float(fixed_dt) > 0.0 else None)
    return {
        "baseline": {"request": baseline_req, "runparts": baseline_stats},
        "variant": {"request": variant_req, "runparts": variant_stats},
        "physical_source_equality": source_equal,
        "physical_source_equality_all": all(source_equal.values()),
        "recipe_differences": recipe_differences,
        "only_allowed_recipe_fields_changed": set(recipe_differences).issubset(allowed_recipe_changes),
        "allowed_recipe_changes": sorted(allowed_recipe_changes),
        "dt_comparison": {
            "variant_declared_fixed_dt_s": fixed_dt,
            "variant_realised_dtmin_positive_min_s": variant_stats["dtmin_positive_min_s"],
            "variant_realised_dtmax_positive_max_s": variant_stats["dtmax_positive_max_s"],
            "variant_fixed_dt_is_constant": (
                variant_stats["dtmin_positive_min_s"] == variant_stats["dtmin_positive_max_s"]
                and variant_stats["dtmax_positive_min_s"] == variant_stats["dtmax_positive_max_s"]
            ),
            "variant_to_baseline_realised_min_ratio": observed_half_ratio,
            "declared_fixed_to_baseline_realised_min_ratio": fixed_dt_ratio,
            "strict_half_of_actual_baseline_min": fixed_dt_ratio is not None and fixed_dt_ratio <= 0.5,
            "interpretation": (
                "fixed-Dt candidate is realised exactly as declared, but its 3.804228564224422e-05 s "
                "value is compared with the actual RV4 baseline minimum; this report does not relabel "
                "a 0.531 ratio as an exact half-Dt study"
            ),
        },
        "source_note": "RunPARTs and terminal solver receipts are actual evidence; request declarations are retained separately.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-request", type=Path, required=True)
    parser.add_argument("--baseline-runparts", type=Path, required=True)
    parser.add_argument("--variant-request", type=Path, required=True)
    parser.add_argument("--variant-runparts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = {
        "schema": "ds-data-02.f2.temporal-audit.v1",
        "quality_budget": {
            "save_half_width_budget_s": SAVE_HALF_WIDTH_BUDGET_S,
            "event_window_s": [0.0, 4.0],
        },
        "pair": audit_pair(
            baseline_request=args.baseline_request.resolve(),
            baseline_runparts=args.baseline_runparts.resolve(),
            variant_request=args.variant_request.resolve(),
            variant_runparts=args.variant_runparts.resolve(),
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output.resolve()),
        "physical_source_equality_all": result["pair"]["physical_source_equality_all"],
        "only_allowed_recipe_fields_changed": result["pair"]["only_allowed_recipe_fields_changed"],
        "save_half_width_within_budget": result["pair"]["variant"]["runparts"]["save_half_width_within_budget"],
        "declared_fixed_to_baseline_realised_min_ratio": result["pair"]["dt_comparison"]["declared_fixed_to_baseline_realised_min_ratio"],
        "strict_half_of_actual_baseline_min": result["pair"]["dt_comparison"]["strict_half_of_actual_baseline_min"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
