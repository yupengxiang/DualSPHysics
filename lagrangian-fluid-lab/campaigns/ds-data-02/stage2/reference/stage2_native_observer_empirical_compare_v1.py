#!/usr/bin/env python3
"""Compare selected native observer fields at actual saved-time brackets.

The worker consumes JSON sidecars produced by the bounded native observer and
the corresponding small ``RunPARTs.csv`` files.  It verifies each query
bracket from the actual saved times, keeps ``mkfluid_relative`` and
``mk_absolute`` in separate keys, and reports measured endpoint differences.
It never interpolates particle fields, treats adjacent grids as truth, reads
HDF5/BI4, or assigns QI/QN/QE.  A difference between endpoints whose actual
saved times are not equal is retained as a diagnostic with scientific error
status ``UNKNOWN_TIME_ALIGNMENT``.
"""

from __future__ import annotations

import argparse
import bisect
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any


SCHEMA = "ds02.stage2.native-observer-empirical-compare.v1"
OBSERVER_SCHEMA = "ds02.stage2.native-physical-observer.v2"
TIME_TOLERANCE_S = 1.0e-10
DEFAULT_OUTPUT = Path("native_observer_empirical_compare_v1.json")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    path = path.expanduser()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"required sidecar must be a regular non-symlink file: {path}")
    path = path.resolve()
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256(path)}


def read_runparts(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    record = file_record(path)
    lines = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    if not lines:
        raise ValueError(f"RunPARTs has no rows: {path}")
    reader = csv.DictReader(lines, delimiter=";")
    rows: list[dict[str, Any]] = []
    for raw in reader:
        values = {(key or "").strip(): (value or "").strip() for key, value in raw.items()}
        part_text = values.get("Part", "").split("#", 1)[0].strip()
        time_text = values.get("TimeStep [s]", "").split("#", 1)[0].strip()
        if not part_text or not time_text or not part_text.lstrip("-").isdigit():
            continue
        part = int(part_text)
        time_s = float(time_text)
        if part < 0 or not math.isfinite(time_s):
            raise ValueError(f"invalid RunPARTs row in {path}: {raw}")
        rows.append({"part": part, "time_s": time_s})
    rows.sort(key=lambda row: row["part"])
    if not rows or [row["part"] for row in rows] != list(range(len(rows))):
        raise ValueError(f"RunPARTs parts are not contiguous from zero: {path}")
    if any(right["time_s"] <= left["time_s"] for left, right in zip(rows, rows[1:])):
        raise ValueError(f"RunPARTs times are not strictly increasing: {path}")
    return record, rows


def bracket(rows: list[dict[str, Any]], query: float) -> dict[str, Any]:
    if not math.isfinite(query):
        raise ValueError(f"non-finite query time: {query}")
    times = [row["time_s"] for row in rows]
    if query < times[0] or query > times[-1]:
        return {"query_time_s": query, "status": "OUTSIDE_SAVED_WINDOW"}
    right = bisect.bisect_left(times, query)
    if right == 0:
        return {"query_time_s": query, "status": "EXACT_OR_LEFT", "lower_frame": 0, "upper_frame": 0,
                "lower_time_s": times[0], "upper_time_s": times[0]}
    if right == len(times):
        right -= 1
    if abs(times[right] - query) <= TIME_TOLERANCE_S:
        return {"query_time_s": query, "status": "EXACT", "lower_frame": right, "upper_frame": right,
                "lower_time_s": times[right], "upper_time_s": times[right]}
    left = right - 1
    return {"query_time_s": query, "status": "BRACKETED", "lower_frame": left, "upper_frame": right,
            "lower_time_s": times[left], "upper_time_s": times[right],
            "bracket_width_s": times[right] - times[left]}


def finite_leaf(value: Any, path: str) -> float | list[float] | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise ValueError(f"non-finite observable at {path}")
        return float(value)
    if isinstance(value, list) and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value):
        result = [float(item) for item in value]
        if not all(math.isfinite(item) for item in result):
            raise ValueError(f"non-finite observable at {path}")
        return result
    return None


METRIC_KEYS = ("weighted_centroid_m", "weighted_velocity_m_per_s", "kinetic_energy_j", "sample_mass_kg")


def metrics_from_observation(observation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    groups = observation.get("groups")
    if not isinstance(groups, dict):
        raise ValueError("observer observation has no groups")
    metrics: dict[str, dict[str, Any]] = {}
    for group_kind, group in groups.items():
        if not isinstance(group, dict):
            continue
        for coordinate_key, entries in (
            ("mkfluid_relative", group.get("by_mkfluid_relative", {})),
            ("mk_absolute", group.get("by_mk_absolute", {})),
        ):
            if not isinstance(entries, dict):
                continue
            for label, entry in entries.items():
                if not isinstance(entry, dict):
                    continue
                key = f"{group_kind}/{coordinate_key}/{label}"
                values: dict[str, Any] = {}
                for metric in METRIC_KEYS:
                    if metric in entry:
                        parsed = finite_leaf(entry[metric], f"{key}/{metric}")
                        if parsed is not None:
                            values[metric] = parsed
                if values:
                    metrics[key] = values
    return metrics


def observation_from_query(query: dict[str, Any], side: str) -> dict[str, Any]:
    observation = query.get(f"{side}_observation")
    if not isinstance(observation, dict):
        raise ValueError(f"query has no {side}_observation")
    if not isinstance(observation.get("frame"), int):
        raise ValueError(f"{side} observation has no integer frame")
    time = observation.get("time")
    if not isinstance(time, dict) or not isinstance(time.get("runparts_s"), (int, float)):
        raise ValueError(f"{side} observation has no RunPARTs time")
    if not math.isfinite(float(time["runparts_s"])):
        raise ValueError(f"{side} observation has non-finite time")
    observation["_metrics"] = metrics_from_observation(observation)
    return observation


def query_map(report: dict[str, Any]) -> dict[float, dict[str, Any]]:
    queries = report.get("time_window", {}).get("queries")
    if not isinstance(queries, list) or not queries:
        raise ValueError("observer report has no time_window.queries")
    result: dict[float, dict[str, Any]] = {}
    for query in queries:
        if not isinstance(query, dict) or not isinstance(query.get("query_time_s"), (int, float)):
            raise ValueError("observer report contains malformed query")
        time_s = float(query["query_time_s"])
        if not math.isfinite(time_s) or time_s in result:
            raise ValueError("observer report contains duplicate/non-finite query")
        result[time_s] = query
    return result


def compare_metric(left: Any, right: Any) -> dict[str, Any]:
    if isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        difference = [float(a) - float(b) for a, b in zip(left, right)]
        magnitude = math.sqrt(sum(float(value) ** 2 for value in difference))
        scale = max(math.sqrt(sum(float(value) ** 2 for value in left)),
                    math.sqrt(sum(float(value) ** 2 for value in right)))
    elif isinstance(left, (int, float)) and isinstance(right, (int, float)):
        difference = float(left) - float(right)
        magnitude = abs(difference)
        scale = max(abs(float(left)), abs(float(right)))
    else:
        return {"status": "UNKNOWN_INCOMPATIBLE_METRIC_SHAPE"}
    return {
        "status": "MEASURED",
        "left": left,
        "right": right,
        "absolute_difference": difference,
        "absolute_norm": magnitude,
        "relative_difference_nonzero_scale": magnitude / scale if scale > 0 else None,
    }


def compare_pair(left: dict[str, Any], right: dict[str, Any], left_name: str, right_name: str,
                 query_time_s: float, left_query: dict[str, Any], right_query: dict[str, Any]) -> dict[str, Any]:
    sides: list[dict[str, Any]] = []
    for side_name, query in (("lower", left_query), ("upper", right_query)):
        left_observation = observation_from_query(left_query, side_name)
        right_observation = observation_from_query(right_query, side_name)
        left_time = float(left_observation["time"]["runparts_s"])
        right_time = float(right_observation["time"]["runparts_s"])
        aligned = abs(left_time - right_time) <= TIME_TOLERANCE_S
        left_metrics = left_observation["_metrics"]
        right_metrics = right_observation["_metrics"]
        metric_rows: dict[str, Any] = {}
        for key in sorted(set(left_metrics) & set(right_metrics)):
            metric_rows[key] = {
                metric: ({**compare_metric(left_metrics[key][metric], right_metrics[key][metric]),
                          "scientific_error_status": "MEASURED_ALIGNED_TIME" if aligned else "UNKNOWN_TIME_ALIGNMENT"})
                for metric in sorted(set(left_metrics[key]) & set(right_metrics[key]))
            }
        sides.append({
            "side": side_name,
            "left_frame": left_observation["frame"],
            "right_frame": right_observation["frame"],
            "left_saved_time_s": left_time,
            "right_saved_time_s": right_time,
            "time_difference_s": left_time - right_time,
            "time_alignment_status": "ALIGNED_WITHIN_TOLERANCE" if aligned else "NOT_ALIGNED",
            "metrics": metric_rows,
            "unmatched_metric_keys": sorted((set(left_metrics) ^ set(right_metrics))),
        })
    return {
        "left_observer": left_name,
        "right_observer": right_name,
        "query_time_s": query_time_s,
        "query_brackets": {
            "left": {key: value for key, value in left_query.items() if not key.endswith("_observation")},
            "right": {key: value for key, value in right_query.items() if not key.endswith("_observation")},
        },
        "field_interpolation": "NOT_PERFORMED",
        "adjacent_grid_as_truth": "FORBIDDEN",
        "endpoint_comparisons": sides,
    }


def build_report(observer_paths: list[Path], output: Path, characteristic_length_m: float | None = None,
                 characteristic_time_s: float | None = None,
                 expected_physical_case_id: str | None = None) -> dict[str, Any]:
    if not observer_paths:
        raise ValueError("at least two observer reports are required")
    if len(observer_paths) < 2:
        raise ValueError("comparison needs at least two observer reports")
    if output.exists():
        raise FileExistsError(f"refuse to overwrite immutable comparison: {output}")
    reports: list[tuple[Path, dict[str, Any], dict[float, dict[str, Any]], list[dict[str, Any]], dict[str, Any]]] = []
    physical_ids: set[str] = set()
    for path in observer_paths:
        path = path.resolve()
        report_record = file_record(path)
        report = json.loads(path.read_text(encoding="utf-8"))
        if report.get("schema") != OBSERVER_SCHEMA or report.get("status") != "PASS_DECODED_SELECTED_NATIVE_FIELDS":
            raise ValueError(f"observer report is not a decoded native report: {path}")
        source = report.get("source")
        if not isinstance(source, dict) or not isinstance(source.get("runparts", {}).get("path"), str):
            raise ValueError(f"observer report lacks source RunPARTs binding: {path}")
        runparts_path = Path(source["runparts"]["path"]).resolve()
        runparts_record, rows = read_runparts(runparts_path)
        declared_runparts_sha = source["runparts"].get("sha256")
        if declared_runparts_sha and declared_runparts_sha != runparts_record["sha256"]:
            raise ValueError(f"RunPARTs digest differs from observer report: {path}")
        query_index = query_map(report)
        physical_id = str(report.get("physical_case_id") or source.get("physical_case_id") or
                          source.get("particle_range_semantics", {}).get("physical_case_id") or "UNKNOWN")
        if expected_physical_case_id is not None and physical_id not in {"UNKNOWN", expected_physical_case_id}:
            raise ValueError(f"observer physical identity differs from explicit binding: {path}")
        physical_ids.add(physical_id)
        for query_time, query in query_index.items():
            actual = bracket(rows, query_time)
            declared_status = query.get("status")
            if declared_status != actual["status"]:
                raise ValueError(f"observer bracket status disagrees with RunPARTs at {query_time}: {path}")
            if actual["status"] == "OUTSIDE_SAVED_WINDOW":
                raise ValueError(f"observer query outside saved window at {query_time}: {path}")
            for side in ("lower", "upper"):
                obs = observation_from_query(query, side)
                expected_frame = actual[f"{side}_frame"]
                if obs["frame"] != expected_frame:
                    raise ValueError(f"observer {side} frame disagrees with RunPARTs at {query_time}: {path}")
        reports.append((path, report, query_index, rows, {"observer": report_record, "runparts": runparts_record}))
    if expected_physical_case_id is None and physical_ids == {"UNKNOWN"}:
        raise ValueError("physical_case_id is absent; provide --physical-case-id instead of comparing unknown identities")
    if len(physical_ids) != 1:
        raise ValueError(f"comparison must stay within one physical_case_id, found {sorted(physical_ids)}")
    physical_case_id = expected_physical_case_id or next(iter(physical_ids))
    common_queries = set(reports[0][2])
    for _, _, index, _, _ in reports[1:]:
        common_queries &= set(index)
    if not common_queries:
        raise ValueError("observer reports have no common physical query time")
    comparisons: list[dict[str, Any]] = []
    for query_time in sorted(common_queries):
        for left_index in range(len(reports)):
            for right_index in range(left_index + 1, len(reports)):
                left = reports[left_index]
                right = reports[right_index]
                comparisons.append(compare_pair(left[1], right[1], str(left[0]), str(right[0]), query_time,
                                                left[2][query_time], right[2][query_time]))
    budget = {
        "position_relative_scale": "2% characteristic L",
        "event_position_relative_scale": "5% characteristic L",
        "velocity_or_ke_nonzero_scale": "5% nonzero scale",
        "event_time_characteristic_scale": "1% characteristic T",
        "time_and_output_budget": "each <= one quarter of total gate; not evaluated by this worker",
        "characteristic_length_m": characteristic_length_m,
        "characteristic_time_s": characteristic_time_s,
        "acceptance": "NOT_EVALUATED; measured comparisons do not grant QI/QN/QE",
    }
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "PASS_MEASURED_BRACKETED_COMPARISON_SCIENTIFIC_QUALIFICATION_UNKNOWN",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_reports": [record for _, _, _, _, record in reports],
        "physical_case_id": physical_case_id,
        "comparison_scope": {
            "observer_count": len(reports),
            "common_query_times_s": sorted(common_queries),
            "runparts_revalidated": True,
            "field_interpolation": "NOT_PERFORMED",
            "time_alignment": "only exact actual saved-time endpoints are scientifically aligned; other endpoint differences remain UNKNOWN_TIME_ALIGNMENT",
            "hdf5_read": False,
            "bi4_read": False,
            "adjacent_grid_as_truth": False,
        },
        "error_budget_registration": budget,
        "comparisons": comparisons,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    temporary = output.with_name(output.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_bytes(encoded)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return result


def manufactured_self_test() -> dict[str, Any]:
    """Validate time-bracket and MK-axis guards without native payloads."""
    with tempfile.TemporaryDirectory(prefix="ds02-observer-compare-") as root_text:
        root = Path(root_text)
        runparts = root / "RunPARTs.csv"
        runparts.write_text("Part;TimeStep [s]\n0;0.0\n1;1.0\n", encoding="utf-8")

        def observation(frame: int, time_s: float, value: float) -> dict[str, Any]:
            return {
                "frame": frame,
                "time": {"runparts_s": time_s, "decoded_s": time_s},
                "groups": {"fluid": {"by_mkfluid_relative": {"0": {
                    "weighted_centroid_m": [value, 0.0, 0.0],
                    "weighted_velocity_m_per_s": [1.0, 0.0, 0.0],
                    "kinetic_energy_j": value + 1.0,
                    "sample_mass_kg": 2.0,
                }}, "by_mk_absolute": {"1": {
                    "weighted_centroid_m": [value, 0.0, 0.0],
                    "weighted_velocity_m_per_s": [1.0, 0.0, 0.0],
                    "kinetic_energy_j": value + 1.0,
                    "sample_mass_kg": 2.0,
                }}}},
            }

        def report(path: Path, value: float) -> None:
            q = {"query_time_s": 0.5, "status": "BRACKETED", "lower_frame": 0, "upper_frame": 1,
                 "lower_time_s": 0.0, "upper_time_s": 1.0,
                 "lower_observation": observation(0, 0.0, value),
                 "upper_observation": observation(1, 1.0, value + 0.1)}
            path.write_text(json.dumps({
                "schema": OBSERVER_SCHEMA, "status": "PASS_DECODED_SELECTED_NATIVE_FIELDS",
                "source": {"runparts": {"path": str(runparts.resolve()), "sha256": sha256(runparts)},
                           "particle_range_semantics": {"physical_case_id": "SELF"}},
                "time_window": {"queries": [q]},
            }), encoding="utf-8")

        left = root / "left.json"; right = root / "right.json"
        report(left, 1.0); report(right, 1.25)
        output = root / "out.json"
        result = build_report([left, right], output, characteristic_length_m=1.0, characteristic_time_s=1.0)
        assert result["comparison_scope"]["common_query_times_s"] == [0.5]
        row = result["comparisons"][0]["endpoint_comparisons"][0]
        assert row["time_alignment_status"] == "ALIGNED_WITHIN_TOLERANCE"
        assert "fluid/mkfluid_relative/0" in row["metrics"]
        assert "fluid/mk_absolute/1" in row["metrics"]
        # Outside-window queries are rejected before any comparison is emitted.
        bad = root / "bad.json"
        bad.write_text(json.dumps({
            "schema": OBSERVER_SCHEMA, "status": "PASS_DECODED_SELECTED_NATIVE_FIELDS",
            "source": {"runparts": {"path": str(runparts.resolve()), "sha256": sha256(runparts)},
                       "particle_range_semantics": {"physical_case_id": "SELF"}},
            "time_window": {"queries": [{"query_time_s": 2.0, "status": "OUTSIDE_SAVED_WINDOW"}]},
        }), encoding="utf-8")
        try:
            build_report([left, bad], root / "bad-out.json")
        except ValueError:
            outside_rejected = True
        else:
            outside_rejected = False
        assert outside_rejected
        return {"status": "PASS", "aligned_endpoint_checked": True, "relative_absolute_axes_kept": True, "outside_window_rejected": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observer", action="append", type=Path, default=[])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--characteristic-length-m", type=float)
    parser.add_argument("--characteristic-time-s", type=float)
    parser.add_argument("--physical-case-id")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(manufactured_self_test(), indent=2))
        return 0
    if len(args.observer) < 2:
        parser.error("at least two --observer paths are required")
    result = build_report(args.observer, args.output, args.characteristic_length_m, args.characteristic_time_s,
                          args.physical_case_id)
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve()),
                      "comparisons": len(result["comparisons"]), "hdf5_read": False, "bi4_read": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
