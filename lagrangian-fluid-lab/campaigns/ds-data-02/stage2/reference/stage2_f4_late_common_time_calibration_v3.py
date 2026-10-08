#!/usr/bin/env python3
"""Forward audit of F4 late common-time and output-time alignment.

This worker reads the immutable v1 calibration report, its four completed
selected-observer JSON sidecars, and their small RunPARTs CSV files.  It does
not open BI4/H5 payloads.  It validates that the late queries 0.9 s and 1.2 s
are bracketed by actual saved timestamps, checks that the selected observer
rows are bound to those exact RunPARTs rows, and records the empirical output
spacing.  The spacing is a resolution diagnostic only; it is not a bound on
field interpolation or physical observer error.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
from typing import Any


REPO = Path(__file__).resolve().parents[5]
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
V1_REPORT = REFERENCE / "stage2_f4_actual_common_time_calibration_v1.json"
REPORT = REFERENCE / "stage2_f4_late_common_time_calibration_v2.json"
SCHEMA = "ds02.stage2.f4-late-common-time-calibration.v3"
EXPECTED_LABELS = ("dp0_same_cfl", "dp0_half_cfl", "coarse_same_cfl", "fine_same_cfl")
EXPECTED_FRAMES = (0, 599, 600, 1199, 1200, 1799, 1800, 2399, 2400)
LATE_QUERIES = (0.9, 1.2)
TIME_TOLERANCE_S = 1.0e-12
TOTAL_REFERENCE_WINDOW_S = 1.2


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "sha256": sha256_file(path),
    }


def atomic_json(path: Path, value: Any) -> None:
    encoded = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() == encoded:
            return
        raise FileExistsError(f"refusing to overwrite existing artifact: {path}")
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def git_head() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()


def finite(value: Any, label: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} is non-finite")
    return result


def load_v1() -> dict[str, Any]:
    value = json.loads(V1_REPORT.read_text(encoding="utf-8"))
    if value.get("schema") != "ds02.stage2.f4-actual-common-time-calibration.v1":
        raise ValueError("unexpected v1 calibration schema")
    runs = value.get("runs")
    if not isinstance(runs, dict) or tuple(runs) != EXPECTED_LABELS:
        raise ValueError(f"v1 run labels are not the frozen four-grid set: {tuple(runs or {})}")
    return value


def read_runparts(path: Path) -> list[dict[str, Any]]:
    lines = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not lines:
        raise ValueError(f"empty RunPARTs: {path}")
    reader = csv.DictReader(lines, delimiter=";")
    rows: list[dict[str, Any]] = []
    for row in reader:
        part_raw = str(row.get("Part", "")).strip()
        time_raw = str(row.get("TimeStep [s]", "")).strip()
        match = re.match(r"^(-?\d+)", part_raw)
        time_match = re.match(r"^([^#\s]+)", time_raw)
        if not match or not time_match:
            continue
        part = int(match.group(1))
        time_s = finite(time_match.group(1), f"{path}: Part {part} time")
        rows.append({"part": part, "time_s": time_s})
    if not rows:
        raise ValueError(f"RunPARTs has no numeric rows: {path}")
    rows.sort(key=lambda item: item["part"])
    if [row["part"] for row in rows] != list(range(len(rows))):
        raise ValueError(f"RunPARTs parts are not contiguous from zero: {path}")
    if any(right["time_s"] <= left["time_s"] for left, right in zip(rows, rows[1:])):
        raise ValueError(f"RunPARTs times are not strictly increasing: {path}")
    return rows


def bracket(rows: list[dict[str, Any]], query: float) -> dict[str, Any]:
    if not math.isfinite(query):
        return {"query_time_s": query, "status": "REJECT_NONFINITE_QUERY"}
    if query < rows[0]["time_s"] or query > rows[-1]["time_s"]:
        return {"query_time_s": query, "status": "OUTSIDE_SAVED_WINDOW", "window_s": [rows[0]["time_s"], rows[-1]["time_s"]]}
    for index, row in enumerate(rows):
        if row["time_s"] == query:
            return {
                "query_time_s": query,
                "status": "EXACT",
                "lower_frame": row["part"],
                "upper_frame": row["part"],
                "lower_time_s": row["time_s"],
                "upper_time_s": row["time_s"],
                "bracket_width_s": 0.0,
            }
        if row["time_s"] > query:
            lower = rows[index - 1]
            return {
                "query_time_s": query,
                "status": "BRACKETED",
                "lower_frame": lower["part"],
                "upper_frame": row["part"],
                "lower_time_s": lower["time_s"],
                "upper_time_s": row["time_s"],
                "bracket_width_s": row["time_s"] - lower["time_s"],
                "interpolation_fraction": (query - lower["time_s"]) / (row["time_s"] - lower["time_s"]),
            }
    raise AssertionError("query bracket search fell through")


def selected_rows(observer: dict[str, Any]) -> dict[int, dict[str, Any]]:
    rows = observer.get("observations")
    if not isinstance(rows, list) or len(rows) != len(EXPECTED_FRAMES):
        raise ValueError("observer does not contain the frozen nine selected rows")
    result: dict[int, dict[str, Any]] = {}
    for row in rows:
        frame = int(row["frame"])
        if frame in result or frame not in EXPECTED_FRAMES:
            raise ValueError(f"unexpected or duplicate selected frame: {frame}")
        runparts_time = finite(row["time"]["runparts_s"], f"observer frame {frame} RunPARTs time")
        decoded_time = finite(row["time"]["decoded_s"], f"observer frame {frame} decoded time")
        if abs(runparts_time - decoded_time) > TIME_TOLERANCE_S:
            raise ValueError(f"observer frame {frame} decoded time mismatch")
        fluid = row.get("groups", {}).get("fluid", {})
        for field in ("weighted_centroid_m", "weighted_velocity_m_per_s", "kinetic_energy_j"):
            value = fluid.get(field)
            if isinstance(value, list):
                [finite(item, f"observer frame {frame} {field}") for item in value]
            else:
                finite(value, f"observer frame {frame} {field}")
        result[frame] = {
            "frame": frame,
            "runparts_time_s": runparts_time,
            "decoded_time_s": decoded_time,
            "raw_field_digest_sha256": row.get("raw_field_digest_sha256"),
            "weighted_fluid_mass_kg": fluid.get("sample_mass_kg"),
        }
    if tuple(sorted(result)) != EXPECTED_FRAMES:
        raise ValueError(f"observer selected frame contract mismatch: {tuple(sorted(result))}")
    return result


def manufactured_bracket_selftest() -> dict[str, Any]:
    rows = [{"part": 0, "time_s": 0.0}, {"part": 1, "time_s": 0.5}, {"part": 2, "time_s": 1.0}]
    cases = [
        ("exact_zero", 0.0, "EXACT"),
        ("bracket_midpoint", 0.25, "BRACKETED"),
        ("outside_right", 1.1, "OUTSIDE_SAVED_WINDOW"),
        ("nonfinite", float("nan"), "REJECT_NONFINITE_QUERY"),
    ]
    result = []
    for name, query, expected in cases:
        actual = bracket(rows, query)
        result.append({"name": name, "expected": expected, "actual": actual["status"], "pass": actual["status"] == expected})
    return {"status": "PASS" if all(item["pass"] for item in result) else "FAIL", "cases": result, "scope": "bracket classification only; no field-error calibration"}


def run() -> dict[str, Any]:
    v1 = load_v1()
    runs = v1["runs"]
    output: dict[str, Any] = {}
    all_bracketed = True
    all_selected_bound = True
    for label in EXPECTED_LABELS:
        metadata = runs[label]
        observer_path = Path(metadata["observer"]["path"])
        runparts_path = Path(metadata["source_runparts"]["path"])
        observer = json.loads(observer_path.read_text(encoding="utf-8"))
        if observer.get("status") != "PASS_DECODED_SELECTED_NATIVE_FIELDS":
            raise ValueError(f"observer is not a completed selected decode: {observer_path}")
        selected = selected_rows(observer)
        runparts = read_runparts(runparts_path)
        for frame, row in selected.items():
            source_row = runparts[frame]
            if abs(source_row["time_s"] - row["runparts_time_s"]) > TIME_TOLERANCE_S:
                raise ValueError(f"{label} selected observer frame {frame} is not bound to RunPARTs")
        brackets = {str(query): bracket(runparts, query) for query in LATE_QUERIES}
        if any(item["status"] not in {"EXACT", "BRACKETED"} for item in brackets.values()):
            all_bracketed = False
        all_selected_bound = all_selected_bound and tuple(sorted(selected)) == EXPECTED_FRAMES
        spacings = [right["time_s"] - left["time_s"] for left, right in zip(runparts, runparts[1:])]
        local_spacing = {
            str(query): next(item["bracket_width_s"] for item in brackets.values() if item["query_time_s"] == query)
            for query in LATE_QUERIES
        }
        terminal_time = runparts[-1]["time_s"]
        output[label] = {
            "observer": record(observer_path),
            "runparts": record(runparts_path),
            "selected_frame_contract": {
                "frames": list(EXPECTED_FRAMES),
                "all_exact_runparts_bindings": True,
                "selected_field_digests": {str(frame): selected[frame]["raw_field_digest_sha256"] for frame in EXPECTED_FRAMES},
            },
            "runparts_contract": {
                "frame_count": len(runparts),
                "terminal_time_s": terminal_time,
                "source_window_endpoint_delta_from_1p2_s": terminal_time - 1.2,
                "global_saved_spacing_s": {"min": min(spacings), "max": max(spacings), "median": sorted(spacings)[len(spacings) // 2]},
                "late_query_brackets": brackets,
                "late_local_spacing_s": local_spacing,
            },
            "source_output_parameters": metadata.get("actual_output_parameters", {}),
            "time_resolution_status": {
                "status": "OBSERVED_BRACKET_WIDTH_RECORDED_NO_PER_BRACKET_ACCEPTANCE_GATE",
                "gate_s": "NOT_APPLICABLE_TIME_OUTPUT_BUDGET_IS_NOT_A_BRACKET_ERROR_BOUND",
                "observed_bracket_widths_s": local_spacing,
                "interpretation": "saved-time spacing is a resolution diagnostic; the preregistered one-quarter time/output figures are campaign budget shares, not a per-query bracket or field-error bound",
            },
            "field_output_status": "UNKNOWN_NO_INDEPENDENT_REAL_FIELD_INTERPOLATION_CALIBRATION",
        }

    late_comparison = {
        str(query): {
            label: output[label]["runparts_contract"]["late_query_brackets"][str(query)]
            for label in EXPECTED_LABELS
        }
        for query in LATE_QUERIES
    }
    return {
        "schema": SCHEMA,
        "status": "ACTUAL_LATE_COMMON_TIME_OUTPUT_RESOLUTION_AUDIT",
        "preparation_source_commit": git_head(),
        "source_v1_report": record(V1_REPORT),
        "sentinel_id": "F4-S1",
        "family_id": "F4",
        "scope": {
            "native_or_h5_read_by_this_worker": False,
            "inputs": "immutable v1 report, four completed selected-observer JSONs, four RunPARTs CSVs",
            "full_native_tree_scanned": False,
            "field_interpolation_performed": False,
            "frame_index_pairing": False,
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "late_common_queries": {
            "query_times_s": list(LATE_QUERIES),
            "all_runs_have_exact_or_bracketed_query": all_bracketed,
            "brackets_by_query": late_comparison,
            "common_physical_time_rule": "query is usable only when every run has an actual saved-time bracket; no extrapolation",
        },
        "frozen_error_budget": {
            "position_relative_to_L": 0.02,
            "event_position_relative_to_L": 0.05,
            "velocity_and_ke_nonzero_scale": 0.05,
            "regional_mass_fraction_of_whole_initial_fluid": 0.03,
            "event_time_fraction": 0.01,
            "time_budget_fraction_of_campaign": 0.25,
            "output_budget_fraction_of_campaign": 0.25,
            "time_output_budget_semantics": "resource/uncertainty allocation shares; not per-bracket error tolerances and not a claim that 0.3 s is acceptable time error",
            "field_and_event_error_status": "UNKNOWN_PENDING_CONSUMER_CALIBRATION",
        },
        "manufactured_bracket_selftest": manufactured_bracket_selftest(),
        "runs": output,
        "interpretation": {
            "time": "All four actual 2401-row RunPARTs windows bracket 0.9 s and 1.2 s; widths are recorded per run. The event-time tolerance remains the frozen 0.01 characteristic-time fraction; no T/4 bracket gate is applied.",
            "output": "The selected 9 observer frames are exact native fields at their own saved times; late common-time values are not declared exact unless the bracket says EXACT. The one-quarter output figure is a campaign budget share, not a resolution acceptance threshold.",
            "qualification": "No QI/QN/QE credit; bracket width and manufactured classification do not calibrate real observer interpolation or event error.",
        },
        "forward_empirical_output_calibration": {
            "status": "PREPARED_LAUNCH_DISABLED",
            "purpose": "calibrate output/subsampling error separately from manufactured bracket classification",
            "source_run": "one same physical F4-S1 dense native run per grid, actual RunPARTs timestamps retained",
            "query_times_s": [0.3, 0.6, 0.9, 1.2],
            "native_selection": "decode bounded adjacent saved frames immediately below/above each query; do not interpolate in this worker",
            "subsampling_factors": [2, 4],
            "comparison": "compare exact native observer aggregates at the retained rows against 2x/4x frame subsamples at the same actual saved rows; field/time calibration remains UNKNOWN until a guarded consumer produces both sides",
            "storage_scope": "bounded selected frames only; no new CFD and no full H5/native scan by this preparation worker",
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "all_selected_observer_bindings_exact": all_selected_bound,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=REPORT)
    args = parser.parse_args()
    value = run()
    atomic_json(args.output, value)
    print(json.dumps({"status": value["status"], "output": str(args.output.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
