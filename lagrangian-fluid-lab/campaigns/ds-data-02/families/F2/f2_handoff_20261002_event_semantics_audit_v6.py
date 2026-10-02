#!/usr/bin/env python3
"""Independently audit v6 crossing interpolation and physical-fate evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import h5py
import numpy as np


DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
F2_ROOT = Path(__file__).parent
V6_ROOT = DATA_ROOT / "families/F2/F2H10V2_EVENT_SEMANTICS_V6"
EVENT_CODES = {
    "cup_top_departure": 1,
    "cup_top_return": 2,
    "receiver_entry": 3,
    "receiver_exit": 4,
    "tray_entry": 5,
    "tray_exit": 6,
}
MARGIN_DATASETS = {
    1: "cup_top_signed_margin_m", 2: "cup_top_signed_margin_m",
    3: "receiver_signed_margin_m", 4: "receiver_signed_margin_m",
    5: "tray_signed_margin_m", 6: "tray_signed_margin_m",
}
UNKNOWN_REASON_CODES = {
    "none": 0,
    "native_invalid": 1,
    "native_invalid_closed_wall_crossing": 2,
    "native_invalid_legal_tray_candidate": 3,
    "native_invalid_after_open_top_or_domain": 4,
    "native_invalid_unclassified": 5,
    "lifecycle_type_change": 6,
}
DESTINATION_CODES = {"unknown": 0, "cup": 1, "receiver": 2, "tray": 3, "inflight": 4}
SAVE_HALF_WIDTH_BUDGET_S = 0.0007336390799938275
PRIMARY_MACRO_RELATIVE_BUDGET = 0.05 * 0.2


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def text(value: Any) -> str:
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)


def _finite_or_none(value: float) -> float | None:
    return float(value) if np.isfinite(value) else None


def audit_case(report_path: Path) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    labels_path = Path(report["output"]["path"])
    if not labels_path.is_file():
        raise FileNotFoundError(labels_path)
    observed: dict[str, Any] = {}
    interpolation_rows = 0
    interpolation_residual_max = 0.0
    sign_violations = 0
    bracket_violations = 0
    noncontiguous_pairs = 0
    with h5py.File(labels_path, "r") as labels:
        times = np.asarray(labels["time"][:], dtype=np.float64)
        events = np.asarray(labels["events"][:])
        if len(times) < 2 or not np.all(np.isfinite(times)) or not np.all(np.diff(times) > 0):
            raise ValueError(f"invalid time axis: {labels_path}")
        if text(labels.attrs["operator_sha256"]) != report["operator"]["sha256"]:
            raise ValueError(f"operator hash mismatch: {labels_path}")
        if text(labels.attrs["physical_condition_sha256"]) != str(report["physical_binding"]["physical_condition_hash_declared"]):
            raise ValueError(f"physical hash mismatch: {labels_path}")
        event_counts: dict[str, int] = {}
        bracket_stats: dict[str, dict[str, Any]] = {}
        for name, code in EVENT_CODES.items():
            rows = events[events["event_code"] == code]
            event_counts[name] = int(len(rows))
            stats = {
                "count": int(len(rows)),
                "min_bracket_half_width_s": None,
                "max_bracket_half_width_s": None,
                "max_abs_interpolation_residual_s": 0.0,
                "sign_violations": 0,
                "event_times_outside_bracket": 0,
                "noncontiguous_frame_pairs": 0,
            }
            if len(rows):
                margin = np.asarray(labels[MARGIN_DATASETS[code]][:], dtype=np.float64)
                before = np.asarray(rows["frame_before"], dtype=np.int64)
                after = np.asarray(rows["frame_after"], dtype=np.int64)
                particle = np.asarray(rows["particle_index"], dtype=np.int64)
                prev = margin[before, particle]
                curr = margin[after, particle]
                denominator = curr - prev
                alpha = np.divide(-prev, denominator, out=np.zeros_like(prev), where=denominator != 0.0)
                expected = times[before] + np.clip(alpha, 0.0, 1.0) * (times[after] - times[before])
                residual = np.abs(np.asarray(rows["time_s"], dtype=np.float64) - expected)
                widths = (times[after] - times[before]) / 2.0
                stats["min_bracket_half_width_s"] = float(np.min(widths))
                stats["max_bracket_half_width_s"] = float(np.max(widths))
                stats["max_abs_interpolation_residual_s"] = float(np.max(residual))
                stats["sign_violations"] = int(np.sum(
                    ((code in (1, 3, 5)) & ~((prev <= 0.0) & (curr > 0.0))) |
                    ((code in (2, 4, 6)) & ~((prev > 0.0) & (curr <= 0.0)))
                ))
                stats["event_times_outside_bracket"] = int(np.sum(
                    (np.asarray(rows["time_s"]) < times[before]) |
                    (np.asarray(rows["time_s"]) > times[after])
                ))
                stats["noncontiguous_frame_pairs"] = int(np.sum(after != before + 1))
                interpolation_rows += len(rows)
                interpolation_residual_max = max(interpolation_residual_max, float(np.max(residual)))
                sign_violations += stats["sign_violations"]
                bracket_violations += stats["event_times_outside_bracket"]
                noncontiguous_pairs += stats["noncontiguous_frame_pairs"]
            stats["all_save_brackets_within_budget"] = bool(
                stats["max_bracket_half_width_s"] is None or stats["max_bracket_half_width_s"] <= SAVE_HALF_WIDTH_BUDGET_S
            )
            bracket_stats[name] = stats

        destination = np.asarray(labels["destination_code"][:], dtype=np.int16)
        reason = np.asarray(labels["unknown_reason_code"][:], dtype=np.int16)
        reason_counts = {
            name: int(np.sum(reason == code)) for name, code in UNKNOWN_REASON_CODES.items()
        }
        invalid_reason = reason != UNKNOWN_REASON_CODES["none"]
        fate = {
            "reason_counts_by_frame_particle": reason_counts,
            "invalid_reason_destination_nonunknown_rows": int(np.sum(invalid_reason & (destination != DESTINATION_CODES["unknown"]))),
            "unknown_destination_without_reason_rows": int(np.sum((destination == DESTINATION_CODES["unknown"]) & ~invalid_reason)),
            "first_excluded_identity_count": int(np.sum(np.asarray(labels["first_invalid_frame"][:]) >= 0)),
            "first_excluded_motive_counts": {
                str(int(motive)): int(np.sum(
                    (np.asarray(labels["first_invalid_frame"][:]) >= 0) &
                    (np.asarray(labels["exclusion_motive"][:]) == motive)
                ))
                for motive in sorted(set(np.asarray(labels["exclusion_motive"][:]).tolist())) if int(motive) >= 0
            },
            "closed_wall_crossing_segment_count": report["native_exclusion_and_boundary"]["closed_wall_crossing_segment_count"],
            "physical_spill_inferred_from_invalid": report["native_exclusion_and_boundary"]["physical_spill_inferred_from_invalid"],
        }
        observed["dimensions"] = {
            "frames": int(len(times)),
            "particles": int(destination.shape[1]),
            "event_rows": int(len(events)),
            "time_start_s": float(times[0]),
            "time_end_s": float(times[-1]),
            "dt_min_s": float(np.min(np.diff(times))),
            "dt_median_s": float(np.median(np.diff(times))),
            "dt_max_s": float(np.max(np.diff(times))),
        }
        observed["event_counts_by_code"] = event_counts
        observed["interpolation"] = {
            "rows_reconstructed": interpolation_rows,
            "max_abs_residual_s": interpolation_residual_max,
            "sign_violations": sign_violations,
            "event_times_outside_bracket": bracket_violations,
            "noncontiguous_frame_pairs": noncontiguous_pairs,
            "all_rows_reconstructed": sign_violations == 0 and bracket_violations == 0 and noncontiguous_pairs == 0,
        }
        observed["bracket_stats_by_code"] = bracket_stats
        observed["fate"] = fate

    report_counts = report["event_ledger"]["counts_by_code"]
    observed["report_event_count_match"] = all(int(report_counts[name]) == count for name, count in event_counts.items())
    observed["report_bracket_stats_match"] = all(
        int(report["event_ledger"].get("observed_event_bracket_stats_s_by_code", {}).get(name, {}).get("count", -1)) == stats["count"]
        for name, stats in observed["bracket_stats_by_code"].items()
    )
    observed["report_fate_match"] = (
        int(report["native_exclusion_and_boundary"]["first_excluded_identity_count"]) == observed["fate"]["first_excluded_identity_count"] and
        report["native_exclusion_and_boundary"]["first_excluded_identity_motive_counts"] == observed["fate"]["first_excluded_motive_counts"] and
        report["native_exclusion_and_boundary"]["unknown_reason_counts_by_frame_particle"] == observed["fate"]["reason_counts_by_frame_particle"]
    )
    observed["source_binding"] = {
        "report": {"path": str(report_path.resolve()), "sha256": sha256(report_path)},
        "labels": {"path": str(labels_path.resolve()), "sha256": sha256(labels_path)},
        "trajectory": report["trajectory"],
        "owner_metadata": report["owner_metadata"],
        "operator": report["operator"],
        "physical_binding": report["physical_binding"],
    }
    return observed


def compare_macro(cases: list[dict[str, Any]]) -> dict[str, Any]:
    by_background: dict[str, dict[str, dict[str, Any]]] = {"center": {}, "offset": {}}
    for case in cases:
        ident = case["case_id"].split("_")
        background = "center" if "CENTER" in case["case_id"] else "offset"
        resolution = "coarse" if "COARSE" in case["case_id"] else "medium" if "MEDIUM" in case["case_id"] else "fine"
        by_background[background][resolution] = case
    result: dict[str, Any] = {}
    for background, rows in by_background.items():
        medium = rows.get("medium")
        if medium is None:
            continue
        initial = float(medium["report"]["source_population"]["native_header_mass_reference"]["native_header_cohort_mass_kg"])
        medium_final = medium["report"]["final_mass_kg_by_destination"]
        result[background] = {"reference_resolution": "medium", "initial_mass_kg": initial, "budget_fraction": PRIMARY_MACRO_RELATIVE_BUDGET, "resolutions": {}}
        for resolution, case in rows.items():
            final = case["report"]["final_mass_kg_by_destination"]
            relative = {name: abs(float(final.get(name, 0.0)) - float(medium_final.get(name, 0.0))) / initial for name in DESTINATION_CODES}
            result[background]["resolutions"][resolution] = {
                "relative_final_destination_mass_error": relative,
                "max_relative_error": max(relative.values()),
                "within_primary_macro_budget": max(relative.values()) <= PRIMARY_MACRO_RELATIVE_BUDGET,
            }
    return result


def build_report(*, comparison_path: Path, output_path: Path) -> dict[str, Any]:
    comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
    reports = []
    for row in comparison["inputs"]:
        report_path = Path(row["report"]["path"])
        # The producer's comparison keeps the label product in its `report`
        # field for historical compatibility; its sibling JSON is the actual
        # observation report and is bound by `report_sha256`.
        if report_path.suffix.lower() == ".h5":
            report_path = report_path.with_name("f2-v6-observations.json")
        if sha256(report_path) != row.get("report_sha256"):
            raise ValueError(f"comparison report hash mismatch: {report_path}")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        reports.append({"case_id": report["case_id"], "report": report, "audit": audit_case(report_path)})
    macro = compare_macro(reports)
    all_interpolation = all(row["audit"]["interpolation"]["all_rows_reconstructed"] for row in reports)
    all_fate = all(
        row["audit"]["report_event_count_match"] and row["audit"]["report_bracket_stats_match"] and
        row["audit"]["report_fate_match"] and row["audit"]["fate"]["invalid_reason_destination_nonunknown_rows"] == 0 and
        row["audit"]["fate"]["physical_spill_inferred_from_invalid"] is False
        for row in reports
    )
    all_brackets = all(
        all(stats["all_save_brackets_within_budget"] for stats in row["audit"]["bracket_stats_by_code"].values())
        for row in reports
    )
    all_macro = all(
        item["within_primary_macro_budget"]
        for background in macro.values() for item in background["resolutions"].values()
    )
    result = {
        "schema": "ds-data-02.f2.event-semantics.v6-crossing-audit.v1",
        "operator_version": comparison["operator_version"],
        "operator_sha256": comparison["operator_sha256"],
        "comparison_binding": {"path": str(comparison_path.resolve()), "sha256": sha256(comparison_path)},
        "quality_budget": {
            "save_half_width_budget_s": SAVE_HALF_WIDTH_BUDGET_S,
            "primary_macro_relative_budget": PRIMARY_MACRO_RELATIVE_BUDGET,
            "primary_macro_definition": "absolute final destination mass difference from same-background medium divided by exact native initial mass",
        },
        "cases": reports,
        "primary_macro_matrix": macro,
        "verdict": {
            "interpolation_rows_reconstructed": all_interpolation,
            "physical_fate_distinctions_bound": all_fate,
            "all_observed_save_brackets_within_budget": all_brackets,
            "all_primary_macro_errors_within_budget": all_macro,
            "scientific_status": "operator and physical-fate evidence only; spatial macro and legacy .01s save brackets remain outside frozen budget; Q-N and production pending",
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison", type=Path, default=V6_ROOT / "f2-v6-sixview-comparison.json")
    parser.add_argument("--output", type=Path, default=V6_ROOT / "f2-v6-crossing-audit.json")
    args = parser.parse_args()
    result = build_report(comparison_path=args.comparison.resolve(), output_path=args.output.resolve())
    print(json.dumps(result["verdict"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
