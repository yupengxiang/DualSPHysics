#!/usr/bin/env python3
"""Review existing RV4 coarse/medium native labels without rewriting them.

This is a read-only evidence summarizer for the four completed RV4 labels
(CENTER/OFFSET × COARSE/MEDIUM).  It verifies H5 dimensions, event rows,
destination mass, source-layer mass, native unknown/exclusion queues, save
brackets, and the physical-scale bindings already present in each report.
The result records measured coarse-versus-medium differences; it does not
grant Q-I, Q-N, or production eligibility.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

import h5py
import numpy as np


DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
F2_DATA = DATA_ROOT / "families/F2"
OUTPUT_ROOT = DATA_ROOT / "families/F2/F2_RV4EQ_COARSE_MEDIUM_REVIEW_20261002"
SCHEMA = "ds-data-02.f2.rv4eq-coarse-medium-review.v1"
SAVE_HALF_WIDTH_BUDGET_S = 0.0007336390799938275
MACRO_RELATIVE_BUDGET = 0.01
DESTINATION_NAMES = ("unknown", "cup", "receiver", "tray", "inflight")
EVENT_NAMES = {
    1: "cup_top_departure",
    2: "cup_top_return",
    3: "receiver_entry",
    4: "receiver_exit",
    5: "tray_entry",
    6: "tray_exit",
}
CASE_ROOTS = {
    ("CENTER", "COARSE"): F2_DATA / "F2H10V2_CENTER_V1_COARSE_RV4D1_BASELINE_SAVE001",
    ("CENTER", "MEDIUM"): F2_DATA / "F2H10V2_CENTER_V1_MEDIUM_RV4D1_BASELINE_SAVE001",
    ("OFFSET", "COARSE"): F2_DATA / "F2H10V2_OFFSET_V1_COARSE_RV4D1_BASELINE_SAVE001",
    ("OFFSET", "MEDIUM"): F2_DATA / "F2H10V2_OFFSET_V1_MEDIUM_RV4D1_BASELINE_SAVE001",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def require(path: Path, label: str) -> Path:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    return path


def report_path(case_root: Path) -> Path:
    candidates = sorted(case_root.glob("labels-*/f2-v6-observations.json"))
    if len(candidates) != 1:
        raise ValueError(f"expected one v6 observation report under {case_root}, got {candidates}")
    return require(candidates[0], "v6 observation report")


def labels_path(case_root: Path) -> Path:
    candidates = sorted(case_root.glob("labels-*/f2-v6-labels.h5"))
    if len(candidates) != 1:
        raise ValueError(f"expected one v6 labels H5 under {case_root}, got {candidates}")
    return require(candidates[0], "v6 labels H5")


def destination_dict(values: list[float]) -> dict[str, float]:
    if len(values) != len(DESTINATION_NAMES):
        raise ValueError(f"destination vector has {len(values)} values")
    return {name: float(values[index]) for index, name in enumerate(DESTINATION_NAMES)}


def event_bracket_budget(report: dict[str, Any]) -> dict[str, Any]:
    stats = report["event_ledger"].get("observed_event_bracket_stats_s_by_code", {})
    rows: dict[str, Any] = {}
    all_pass = True
    for name, value in stats.items():
        maximum = value.get("max_s")
        passed = maximum is None or float(maximum) <= SAVE_HALF_WIDTH_BUDGET_S
        rows[name] = {**value, "within_frozen_save_half_width_budget": passed}
        all_pass = all_pass and passed
    return {"budget_s": SAVE_HALF_WIDTH_BUDGET_S, "by_event": rows, "all_within_budget": all_pass}


def physical_scale(report: dict[str, Any]) -> dict[str, Any]:
    geometry = report["geometry_and_pose"]
    source = report["source_population"]
    binding = report["physical_binding"]
    return {
        "continuous_initial_mass_kg": float(source["continuous_mass_kg"]),
        "native_initial_mass_kg": float(source["initial_native_mass_kg"]),
        "event_window_s": float(report["residence"]["time_window_s"]),
        "geometry_and_pose": geometry,
        "motion_control_sha256": binding["motion_control_sha256"],
        "physical_binding_sha256": binding["physical_binding_sha256"],
        "source_h5_physical_condition_sha256": binding["source_h5_physical_condition_sha256"],
        "source_h5_geometry_sha256": binding["source_h5_geometry_sha256"],
        "source_h5_control_sha256": binding["source_h5_control_sha256"],
        "declared_report_physical_condition_sha256": binding["physical_condition_hash_declared"],
        "physical_geometry_hash": canonical_hash(geometry),
    }


def read_case(background: str, resolution: str) -> dict[str, Any]:
    root = CASE_ROOTS[(background, resolution)]
    report_file = report_path(root)
    labels_file = labels_path(root)
    report = json.loads(report_file.read_text(encoding="utf-8"))
    with h5py.File(labels_file, "r") as labels:
        times = np.asarray(labels["time"][:], dtype=np.float64)
        destination_mass = np.asarray(labels["destination_mass_kg"][-1, :], dtype=np.float64)
        event_rows = np.asarray(labels["events"][:])
        reason = np.asarray(labels["unknown_reason_code"][:], dtype=np.uint8)
        first_invalid = np.asarray(labels["first_invalid_frame"][:], dtype=np.int64)
        lifecycle = np.asarray(labels["lifecycle_type_change"][:], dtype=bool)
        source_mk = np.asarray(labels["source_mk"][:], dtype=np.int64)
        h5_attrs = {str(key): value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value.item() if isinstance(value, np.generic) else value for key, value in labels.attrs.items()}
        h5_event_counts = {name: int(np.sum(event_rows["event_code"] == code)) for code, name in EVENT_NAMES.items()}
        reason_codes = {
            "none": 0,
            "native_invalid": 1,
            "native_invalid_closed_wall_crossing": 2,
            "native_invalid_legal_tray_candidate": 3,
            "native_invalid_after_open_top_or_domain": 4,
            "native_invalid_unclassified": 5,
            "lifecycle_type_change": 6,
        }
        h5_reason_counts = {name: int(np.sum(reason == code)) for name, code in reason_codes.items()}
        actual = {
            "frames": int(labels["destination_code"].shape[0]),
            "fluid_particles": int(labels["destination_code"].shape[1]),
            "coordinate_components": 3,
            "time_start_s": float(times[0]),
            "time_end_s": float(times[-1]),
            "destination_mass_kg": destination_dict(destination_mass.tolist()),
            "event_counts": h5_event_counts,
            "reason_counts_by_frame_particle": h5_reason_counts,
            "first_invalid_identity_count": int(np.sum(first_invalid >= 0)),
            "lifecycle_type_change_count": int(np.sum(lifecycle)),
            "source_mk_counts": {str(int(mk)): int(np.sum(source_mk == mk)) for mk in sorted(set(source_mk.tolist()))},
            "h5_attrs": h5_attrs,
        }
    report_destination = {name: float(report["final_mass_kg_by_destination"][name]) for name in DESTINATION_NAMES}
    report_event_counts = {name: int(report["event_ledger"]["counts_by_code"][name]) for name in EVENT_NAMES.values()}
    report_reasons = {name: int(report["native_exclusion_and_boundary"]["unknown_reason_counts_by_frame_particle"][name]) for name in ("none", "native_invalid", "native_invalid_closed_wall_crossing", "native_invalid_legal_tray_candidate", "native_invalid_after_open_top_or_domain", "native_invalid_unclassified", "lifecycle_type_change")}
    binding = physical_scale(report)
    checks = {
        "h5_dimensions_match_report": actual["frames"] == int(report["dimensions"]["frames"]) and actual["fluid_particles"] == int(report["dimensions"]["initial_fluid_particles"]),
        "h5_end_time_match_report": abs(actual["time_end_s"] - float(report["residence"]["time_window_s"])) <= 1e-12,
        "h5_destination_mass_match_report": all(abs(actual["destination_mass_kg"][name] - report_destination[name]) <= 1e-9 for name in DESTINATION_NAMES),
        "h5_event_counts_match_report": actual["event_counts"] == report_event_counts,
        "h5_reason_counts_match_report": actual["reason_counts_by_frame_particle"] == report_reasons,
        "h5_source_cohort_counts_match_report": sum(actual["source_mk_counts"].values()) == actual["fluid_particles"],
        "all_observed_save_brackets_within_budget": event_bracket_budget(report)["all_within_budget"],
        "no_unknown_reason_rows": all(value == 0 for name, value in actual["reason_counts_by_frame_particle"].items() if name != "none"),
        "no_lifecycle_type_changes": actual["lifecycle_type_change_count"] == 0,
    }
    checks["label_declared_physical_hash_matches_source"] = (
        str(binding["declared_report_physical_condition_sha256"]) == str(binding["source_h5_physical_condition_sha256"])
    )
    structural_checks = {name: value for name, value in checks.items() if name != "label_declared_physical_hash_matches_source"}
    return {
        "case_id": report["case_id"],
        "background": background,
        "resolution": resolution,
        "report": {"path": str(report_file), "sha256": sha256(report_file)},
        "labels": {"path": str(labels_file), "sha256": sha256(labels_file)},
        "physical_scale": binding,
        "source_population": report["source_population"],
        "actual_h5": actual,
        "reported": {
            "destination_mass_kg": report_destination,
            "event_counts": report_event_counts,
            "native_exclusion": report["native_exclusion_and_boundary"],
        },
        "event_bracket_budget": event_bracket_budget(report),
        "checks": checks,
        "structural_checks_pass": all(structural_checks.values()),
        "all_checks_pass": all(checks.values()),
    }


def compare_resolution(cases: list[dict[str, Any]]) -> dict[str, Any]:
    by_background = {background: {row["resolution"]: row for row in cases if row["background"] == background} for background in ("CENTER", "OFFSET")}
    comparisons: dict[str, Any] = {}
    for background, rows in by_background.items():
        coarse = rows["COARSE"]
        medium = rows["MEDIUM"]
        initial = float(medium["actual_h5"]["destination_mass_kg"]["unknown"] + medium["actual_h5"]["destination_mass_kg"]["cup"] + medium["actual_h5"]["destination_mass_kg"]["receiver"] + medium["actual_h5"]["destination_mass_kg"]["tray"] + medium["actual_h5"]["destination_mass_kg"]["inflight"])
        destination_delta = {
            name: float(coarse["actual_h5"]["destination_mass_kg"][name] - medium["actual_h5"]["destination_mass_kg"][name])
            for name in DESTINATION_NAMES
        }
        destination_relative = {name: abs(value) / 24.576 for name, value in destination_delta.items()}
        coarse_events = coarse["reported"]["event_counts"]
        medium_events = medium["reported"]["event_counts"]
        event_count_delta = {name: int(coarse_events[name] - medium_events[name]) for name in EVENT_NAMES.values()}
        first_times = {}
        coarse_report = json.loads(Path(coarse["report"]["path"]).read_text(encoding="utf-8"))
        medium_report = json.loads(Path(medium["report"]["path"]).read_text(encoding="utf-8"))
        for name in EVENT_NAMES.values():
            c = coarse_report["event_ledger"]["first_event_time_s_by_code"].get(name)
            m = medium_report["event_ledger"]["first_event_time_s_by_code"].get(name)
            first_times[name] = None if c is None or m is None else float(c) - float(m)
        comparisons[background] = {
            "reference": "MEDIUM",
            "initial_mass_denominator_kg": initial,
            "destination_mass_delta_coarse_minus_medium_kg": destination_delta,
            "destination_mass_relative_error_to_medium": destination_relative,
            "max_destination_relative_error": max(destination_relative.values()),
            "within_frozen_macro_budget": max(destination_relative.values()) <= MACRO_RELATIVE_BUDGET,
            "event_count_delta_coarse_minus_medium": event_count_delta,
            "first_event_time_delta_coarse_minus_medium_s": first_times,
            "interpretation": "measured numerical-resolution difference; this comparison is not an automatic Q-N pass",
        }
    return comparisons


def build(output: Path = OUTPUT_ROOT / "rv4eq-coarse-medium-review.json") -> dict[str, Any]:
    cases = [read_case(background, resolution) for background, resolution in CASE_ROOTS]
    physical_scales = {
        f"{row['background']}_{row['resolution']}": row["physical_scale"] for row in cases
    }
    by_background: dict[str, list[dict[str, Any]]] = {"CENTER": [], "OFFSET": []}
    for row in cases:
        by_background[row["background"]].append(row)
    scale_checks = {}
    for background, rows in by_background.items():
        reference = next(row for row in rows if row["resolution"] == "MEDIUM")["physical_scale"]
        scale_checks[background] = {
            "physical_binding_sha256_equal": all(row["physical_scale"]["physical_binding_sha256"] == reference["physical_binding_sha256"] for row in rows),
            "source_h5_physical_condition_equal": all(row["physical_scale"]["source_h5_physical_condition_sha256"] == reference["source_h5_physical_condition_sha256"] for row in rows),
            "motion_control_equal": all(row["physical_scale"]["motion_control_sha256"] == reference["motion_control_sha256"] for row in rows),
            "geometry_and_pose_equal": all(row["physical_scale"]["physical_geometry_hash"] == reference["physical_geometry_hash"] for row in rows),
            "label_declared_hash_mismatches": [row["case_id"] for row in rows if not row["checks"]["label_declared_physical_hash_matches_source"]],
        }
    result = {
        "schema": SCHEMA,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope_id": "F2_SCOPE_RV4_EQUIVALENT_DP005_PRECHECK_20261002",
        "physical_scale_frozen_before_comparison": {
            "continuous_initial_mass_kg": 24.576,
            "length_unit": "m",
            "time_unit": "s",
            "event_window_s": 4.0,
            "destination_mass_unit": "kg",
            "residence_unit": "kg*s",
            "unknown_mass_remains_in_initial_denominator": True,
            "motion_and_geometry_are_bound_per_background": True,
            "operator_is_not_part_of_physical_hash": True,
        },
        "case_count": len(cases),
        "cases": cases,
        "physical_scale_checks": scale_checks,
        "coarse_medium_comparisons": compare_resolution(cases),
        "verdict": {
            "all_h5_structural_checks_pass": all(row["structural_checks_pass"] for row in cases),
            "all_physical_scope_checks_pass": all(
                value[key]
                for value in scale_checks.values()
                for key in ("physical_binding_sha256_equal", "source_h5_physical_condition_equal", "motion_control_equal", "geometry_and_pose_equal")
            ),
            "metadata_binding_mismatch_present": any(bool(value["label_declared_hash_mismatches"]) for value in scale_checks.values()),
            "coarse_medium_macro_within_budget": all(value["within_frozen_macro_budget"] for value in compare_resolution(cases).values()),
            "native_exclusion_unknowns_are_separate": True,
            "q_n_status": "pending; coarse/medium spatial differences are measured evidence, not a qualification grant",
            "production_status": "not_evaluated",
        },
    }
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result["output"] = {"path": str(output), "sha256": sha256(output)}
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT / "rv4eq-coarse-medium-review.json")
    args = parser.parse_args()
    result = build(args.output)
    print(json.dumps(result["verdict"], ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
