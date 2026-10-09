#!/usr/bin/env python3
"""Bounded F4-S1 common-time/output-readiness audit.

This forward worker consumes the already-produced selected-observer JSON
sidecars and their small ``RunPARTs.csv`` time axes.  It deliberately does
not open BI4, PartVTK, HDF5, or any native particle payload.  It records
actual Part IDs and timestamps for the registered common queries, then
reports which adjacent native rows are still missing for the preregistered
2x/4x output-subsampling diagnostic.  No interpolation, particle pairing,
error bound, or QI/QN/QE credit is produced here.

The worker is intended for a bounded parent-guarded CPU audit.  Its input
files are small metadata/observer artifacts; every file is read through a
before/read/after stat+SHA stability check and an existing output is always
rejected.
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
DEFAULT_V1 = REFERENCE / "stage2_f4_actual_common_time_calibration_v1.json"
DEFAULT_V4 = REFERENCE / "stage2_f4_late_common_time_calibration_v4.json"

SCHEMA = "ds02.stage2.f4-s1-common-time-output-calibration.v5"
EXPECTED_LABELS = ("dp0_same_cfl", "dp0_half_cfl", "coarse_same_cfl", "fine_same_cfl")
EXPECTED_SELECTED_FRAMES = (0, 599, 600, 1199, 1200, 1799, 1800, 2399, 2400)
QUERY_TIMES_S = (0.3, 0.6, 0.9, 1.2)
SUBSAMPLE_FACTORS = (2, 4)
WINDOW_RADIUS_FRAMES = 4
TIME_TOLERANCE_S = 1.0e-12


class InputChangedError(RuntimeError):
    """Raised when a bounded input changes during a read."""


def _stat(path: Path) -> dict[str, Any]:
    path = path.resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    value = path.stat()
    return {
        "path": str(path),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "dev": int(value.st_dev),
        "ino": int(value.st_ino),
    }


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_stable(path: Path) -> tuple[bytes, dict[str, Any]]:
    before = _stat(path)
    data = path.read_bytes()
    after = _stat(path)
    if before != after:
        raise InputChangedError(f"input changed during read: {path}")
    record = dict(after)
    record["sha256"] = _sha_bytes(data)
    return data, record


def _read_json(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    data, record = _read_stable(path)
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON input: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON input is not an object: {path}")
    return value, record


def _read_text(path: Path) -> tuple[str, dict[str, Any]]:
    data, record = _read_stable(path)
    return data.decode("utf-8", errors="replace"), record


def _atomic_json(path: Path, value: Any) -> None:
    path = path.resolve()
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _finite(value: Any, label: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} is non-finite")
    return result


def _vector(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{label} is not a 3-vector")
    return [_finite(item, label) for item in value]


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _assert_unknown(value: Any, label: str) -> None:
    if value != {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}:
        raise ValueError(f"{label} has non-UNKNOWN qualification markers")


def _load_reports(v1_path: Path, v4_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    v1, v1_record = _read_json(v1_path)
    v4, v4_record = _read_json(v4_path)
    if v1.get("schema") != "ds02.stage2.f4-actual-common-time-calibration.v1":
        raise ValueError(f"unexpected F4 v1 schema: {v1.get('schema')!r}")
    if v4.get("schema") != "ds02.stage2.f4-late-common-time-calibration.v4":
        raise ValueError(f"unexpected F4 v4 schema: {v4.get('schema')!r}")
    for report, label in ((v1, "v1"), (v4, "v4")):
        if report.get("sentinel_id") != "F4-S1" or report.get("family_id") != "F4":
            raise ValueError(f"{label} report F4 identity mismatch")
        _assert_unknown(report.get("scientific_qualification"), f"{label}.scientific_qualification")
    # v4 is a forward lineage report that predates the v1 physical-case field;
    # when present it must agree, while absence is retained as a provenance
    # limitation rather than silently inventing an identity.
    v4_physical_case = v4.get("physical_case_id")
    if v4_physical_case is not None and v1.get("physical_case_id") != v4_physical_case:
        raise ValueError("v1/v4 physical case identity mismatch")
    if tuple(v1.get("runs", {})) != EXPECTED_LABELS or tuple(v4.get("runs", {})) != EXPECTED_LABELS:
        raise ValueError("F4 reports do not carry the frozen four-run label set")
    source_v1 = v4.get("source_v1_report", {})
    if source_v1.get("sha256") != v1_record["sha256"]:
        raise ValueError("v4 source_v1_report SHA does not match the supplied v1 report")
    budget = v4.get("frozen_error_budget", {})
    if budget.get("time_budget_fraction_of_campaign") != 0.25 or budget.get("output_budget_fraction_of_campaign") != 0.25:
        raise ValueError("F4 v4 time/output budget shares drifted")
    if "not per-bracket" not in str(budget.get("time_output_budget_semantics", "")):
        raise ValueError("F4 v4 budget semantics lost the non-bracket-error disclaimer")
    for label in EXPECTED_LABELS:
        source = v1["runs"][label]
        v4_run = v4["runs"][label]
        if v4_run.get("observer", {}).get("path") != str(Path(source["observer"]["path"]).resolve()):
            raise ValueError(f"{label}: v4 observer path is not the supplied v1 source")
        if v4_run.get("runparts", {}).get("path") != str(Path(source["source_runparts"]["path"]).resolve()):
            raise ValueError(f"{label}: v4 RunPARTs path is not the supplied v1 source")
    return v1, v4, v1_record, v4_record


def _read_runparts(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    text, record = _read_text(path)
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not lines:
        raise ValueError(f"empty RunPARTs CSV: {path}")
    rows: list[dict[str, Any]] = []
    for raw in csv.DictReader(lines, delimiter=";"):
        part_raw = str(raw.get("Part", "")).strip()
        time_raw = str(raw.get("TimeStep [s]", "")).strip()
        part_match = re.match(r"^(\d+)", part_raw)
        time_match = re.match(r"^([^#\s]+)", time_raw)
        if not part_match or not time_match:
            continue
        part = int(part_match.group(1))
        time_s = _finite(time_match.group(1), f"{path}: Part {part} time")
        rows.append({"frame": part, "time_s": time_s})
    if not rows:
        raise ValueError(f"RunPARTs has no numeric rows: {path}")
    rows.sort(key=lambda row: row["frame"])
    if [row["frame"] for row in rows] != list(range(len(rows))):
        raise ValueError(f"RunPARTs frame IDs are not contiguous from zero: {path}")
    if any(right["time_s"] <= left["time_s"] for left, right in zip(rows, rows[1:])):
        raise ValueError(f"RunPARTs times are not strictly increasing: {path}")
    return rows, record


def _read_observer(path: Path) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    value, record = _read_json(path)
    if value.get("schema") != "ds02.stage2.f4-physical-observer.v1":
        raise ValueError(f"unexpected selected-observer schema: {path}")
    if value.get("status") != "PASS_DECODED_SELECTED_NATIVE_FIELDS":
        raise ValueError(f"selected observer is not completed: {path}")
    scope = value.get("scope", {})
    if scope.get("selected_frames_only") is not True or scope.get("hdf5_read") is not False:
        raise ValueError(f"selected observer scope is not native-selected/no-H5: {path}")
    if value.get("source_deleted") is True:
        raise ValueError(f"selected observer marks its source deleted: {path}")
    observations = value.get("observations")
    if not isinstance(observations, list) or len(observations) != len(EXPECTED_SELECTED_FRAMES):
        raise ValueError(f"selected observer does not contain the frozen nine rows: {path}")
    result: dict[int, dict[str, Any]] = {}
    for row in observations:
        frame = row.get("frame")
        if not isinstance(frame, int) or frame in result or frame not in EXPECTED_SELECTED_FRAMES:
            raise ValueError(f"unexpected selected observer frame {frame!r}: {path}")
        timing = row.get("time", {})
        runparts_s = _finite(timing.get("runparts_s"), f"{path}: frame {frame} RunPARTs time")
        decoded_s = _finite(timing.get("decoded_s"), f"{path}: frame {frame} decoded time")
        if abs(runparts_s - decoded_s) > TIME_TOLERANCE_S:
            raise ValueError(f"observer decoded/RunPARTs mismatch at frame {frame}: {path}")
        fluid = row.get("groups", {}).get("fluid", {})
        if not isinstance(fluid, dict):
            raise ValueError(f"observer fluid group missing at frame {frame}: {path}")
        _vector(fluid.get("weighted_centroid_m"), f"{path}: frame {frame} centroid")
        _vector(fluid.get("weighted_velocity_m_per_s"), f"{path}: frame {frame} velocity")
        _finite(fluid.get("kinetic_energy_j"), f"{path}: frame {frame} KE")
        sample_mass = _finite(fluid.get("sample_mass_kg"), f"{path}: frame {frame} mass")
        digest = row.get("raw_field_digest_sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"observer raw field digest missing/invalid at frame {frame}: {path}")
        result[frame] = {
            "frame": frame,
            "runparts_time_s": runparts_s,
            "decoded_time_s": decoded_s,
            "raw_field_digest_sha256": digest,
            "sample_mass_kg": sample_mass,
        }
    if tuple(sorted(result)) != EXPECTED_SELECTED_FRAMES:
        raise ValueError(f"selected observer frame contract mismatch: {path}")
    return result, record


def _bracket(rows: list[dict[str, Any]], query: float) -> dict[str, Any]:
    if not math.isfinite(query):
        return {"query_time_s": query, "status": "REJECT_NONFINITE_QUERY"}
    if query < rows[0]["time_s"] or query > rows[-1]["time_s"]:
        return {
            "query_time_s": query,
            "status": "OUTSIDE_SAVED_WINDOW",
            "window_s": [rows[0]["time_s"], rows[-1]["time_s"]],
        }
    for index, row in enumerate(rows):
        if abs(row["time_s"] - query) <= TIME_TOLERANCE_S:
            return {
                "query_time_s": query,
                "status": "EXACT",
                "lower_frame": row["frame"],
                "upper_frame": row["frame"],
                "lower_time_s": row["time_s"],
                "upper_time_s": row["time_s"],
                "bracket_width_s": 0.0,
            }
        if row["time_s"] > query:
            lower = rows[index - 1]
            return {
                "query_time_s": query,
                "status": "BRACKETED",
                "lower_frame": lower["frame"],
                "upper_frame": row["frame"],
                "lower_time_s": lower["time_s"],
                "upper_time_s": row["time_s"],
                "bracket_width_s": row["time_s"] - lower["time_s"],
                "interpolation_fraction": (query - lower["time_s"]) / (row["time_s"] - lower["time_s"]),
            }
    raise AssertionError("query bracket search fell through")


def _required_window(rows: list[dict[str, Any]], selected: set[int], query: float) -> dict[str, Any]:
    bracket = _bracket(rows, query)
    if bracket["status"] not in {"EXACT", "BRACKETED"}:
        return {
            "bracket": bracket,
            "status": "UNKNOWN_QUERY_NOT_BRACKETED",
            "required_native_frame_ids": [],
            "missing_from_existing_observer": [],
        }
    anchor = int(bracket["lower_frame"] if bracket["status"] == "EXACT" else bracket["upper_frame"])
    start = max(0, anchor - WINDOW_RADIUS_FRAMES)
    end = min(len(rows) - 1, anchor + WINDOW_RADIUS_FRAMES)
    required = list(range(start, end + 1))
    missing = [frame for frame in required if frame not in selected]
    return {
        "bracket": bracket,
        "anchor_frame_id": anchor,
        "window_radius_frames": WINDOW_RADIUS_FRAMES,
        "required_native_frame_ids": required,
        "required_native_frame_times_s": [rows[frame]["time_s"] for frame in required],
        "existing_selected_frame_ids": sorted(selected),
        "missing_from_existing_observer": missing,
        "status": "READY_FOR_NATIVE_ROWS" if not missing else "UNKNOWN_MISSING_NATIVE_ROWS",
    }


def _manufactured_self_test() -> dict[str, Any]:
    rows = [{"frame": i, "time_s": float(i)} for i in range(5)]
    cases = [
        ("exact", 0.0, "EXACT"),
        ("bracketed", 1.5, "BRACKETED"),
        ("outside", 6.0, "OUTSIDE_SAVED_WINDOW"),
        ("nonfinite", float("nan"), "REJECT_NONFINITE_QUERY"),
    ]
    bracket_cases = []
    for name, query, expected in cases:
        actual = _bracket(rows, query)["status"]
        bracket_cases.append({"name": name, "expected": expected, "actual": actual, "pass": actual == expected})
    missing = _required_window(rows, {0, 1, 2, 3, 4}, 1.5)
    # The tiny fixture has a complete local window; this is a guard against
    # accidentally reporting missing rows when the source is complete.
    window_pass = missing["status"] == "READY_FOR_NATIVE_ROWS"
    return {
        "status": "PASS" if all(item["pass"] for item in bracket_cases) and window_pass else "FAIL",
        "brackets": bracket_cases,
        "complete_window_status": missing["status"],
        "scope": "classification and native-row availability only; no field interpolation",
    }


def run(v1_path: Path = DEFAULT_V1, v4_path: Path = DEFAULT_V4) -> dict[str, Any]:
    v1, v4, v1_record, v4_record = _load_reports(v1_path.resolve(), v4_path.resolve())
    runs: dict[str, Any] = {}
    common_brackets: dict[str, dict[str, Any]] = {str(query): {} for query in QUERY_TIMES_S}
    all_common_bracketed = True
    total_input_bytes = v1_record["bytes"] + v4_record["bytes"]
    input_records: dict[str, Any] = {
        "v1_report": v1_record,
        "v4_report": v4_record,
    }

    for label in EXPECTED_LABELS:
        metadata = v1["runs"][label]
        observer_path = Path(metadata["observer"]["path"]).resolve()
        runparts_path = Path(metadata["source_runparts"]["path"]).resolve()
        observer, observer_record = _read_observer(observer_path)
        rows, runparts_record = _read_runparts(runparts_path)
        v4_run = v4["runs"][label]
        if v4_run["observer"].get("sha256") != observer_record["sha256"]:
            raise ValueError(f"{label}: v4 observer SHA does not match current observer")
        if v4_run["runparts"].get("sha256") != runparts_record["sha256"]:
            raise ValueError(f"{label}: v4 RunPARTs SHA does not match current RunPARTs")
        expected_count = int(metadata.get("full_runparts_frame_count", len(rows)))
        if len(rows) != expected_count:
            raise ValueError(f"{label}: RunPARTs count {len(rows)} != v1 count {expected_count}")
        for frame, selected_row in observer.items():
            source_row = rows[frame]
            if abs(source_row["time_s"] - selected_row["runparts_time_s"]) > TIME_TOLERANCE_S:
                raise ValueError(f"{label}: observer frame {frame} is not bound to RunPARTs")
        selected_ids = set(observer)
        per_query: dict[str, Any] = {}
        for query in QUERY_TIMES_S:
            value = _required_window(rows, selected_ids, query)
            per_query[str(query)] = {
                "bracket": value["bracket"],
                "anchor_frame_id": value.get("anchor_frame_id"),
                "required_native_frame_ids": value["required_native_frame_ids"],
                "required_native_frame_times_s": value.get("required_native_frame_times_s", []),
                "existing_selected_frame_ids": value["existing_selected_frame_ids"],
                "missing_from_existing_observer": value["missing_from_existing_observer"],
                "status": value["status"],
                "subsample_factors": list(SUBSAMPLE_FACTORS),
                "field_error_status": "UNKNOWN_NO_ADJACENT_NATIVE_FIELDS",
            }
            bracket = value["bracket"]
            common_brackets[str(query)][label] = bracket
            if bracket.get("status") not in {"EXACT", "BRACKETED"}:
                all_common_bracketed = False
        source_key = label
        input_records[f"{source_key}.observer"] = observer_record
        input_records[f"{source_key}.runparts"] = runparts_record
        total_input_bytes += observer_record["bytes"] + runparts_record["bytes"]
        runs[label] = {
            "observer": observer_record,
            "runparts": runparts_record,
            "selected_frame_ids": sorted(selected_ids),
            "selected_frame_count": len(selected_ids),
            "full_runparts_frame_count": len(rows),
            "terminal_time_s": rows[-1]["time_s"],
            "query_windows": per_query,
            "output_calibration": {
                "status": "UNKNOWN_MISSING_NATIVE_ROWS",
                "subsample_factors": list(SUBSAMPLE_FACTORS),
                "local_window_radius_frames": WINDOW_RADIUS_FRAMES,
                "native_field_comparison_performed": False,
                "interpolation_performed": False,
                "next_required_action": "bounded decode of the listed missing Part IDs, then compare actual saved rows at their own RunPARTs times",
            },
        }

    return {
        "schema": SCHEMA,
        "status": "COMPLETED_SOURCE_ONLY_COMMON_TIME_OUTPUT_READINESS",
        "preparation_source_commit": _git_head(),
        "sentinel_id": "F4-S1",
        "family_id": "F4",
        "physical_case_id": v1.get("physical_case_id"),
        "source_reports": {
            "v1": v1_record,
            "v4": v4_record,
            "v4_budget_lineage_checked": True,
        },
        "input_records": input_records,
        "input_bytes_total": total_input_bytes,
        "scope": {
            "native_payload_read_by_worker": False,
            "bi4_read": False,
            "partvtk_read": False,
            "hdf5_read": False,
            "full_native_tree_scanned": False,
            "observer_json_and_runparts_only": True,
            "field_interpolation_performed": False,
            "particle_id_pairing_performed": False,
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "frozen_error_budget": {
            "position_relative_to_L": 0.02,
            "event_position_relative_to_L": 0.05,
            "velocity_and_ke_nonzero_scale": 0.05,
            "regional_mass_fraction_of_whole_initial_fluid": 0.03,
            "event_time_fraction": 0.01,
            "time_budget_fraction_of_campaign": 0.25,
            "output_budget_fraction_of_campaign": 0.25,
            "time_output_budget_is_not_bracket_error_bound": True,
        },
        "common_time": {
            "query_times_s": list(QUERY_TIMES_S),
            "all_runs_exact_or_bracketed": all_common_bracketed,
            "brackets_by_query": common_brackets,
            "rule": "actual RunPARTs timestamps and native Part IDs; no frame-index pairing, extrapolation, or interpolation",
        },
        "runs": runs,
        "output_calibration_plan": {
            "status": "PREPARED_BOUNDED_FOLLOWUP",
            "purpose": "separate saved-output sampling diagnostics from time integration and physical/grid error",
            "subsample_factors": list(SUBSAMPLE_FACTORS),
            "local_window_radius_frames": WINDOW_RADIUS_FRAMES,
            "current_observer_limitation": "existing observer has only nine selected rows; missing adjacent rows are enumerated per query and grid",
            "required_followup": "guarded selected-native decode of missing rows only, followed by a separate consumer comparison at actual saved timestamps",
            "no_claim": "no QI/QN/QE, no bracket-error bound, no integration-error bound, no spatial-truth claim",
        },
        "manufactured_selftest": _manufactured_self_test(),
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v1-report", type=Path, default=DEFAULT_V1)
    parser.add_argument("--v4-report", type=Path, default=DEFAULT_V4)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(_manufactured_self_test(), indent=2, sort_keys=True))
        return 0
    if args.output is None:
        parser.error("--output is required unless --self-test is used")
    value = run(args.v1_report, args.v4_report)
    _atomic_json(args.output, value)
    print(json.dumps({"status": value["status"], "output": str(args.output.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
