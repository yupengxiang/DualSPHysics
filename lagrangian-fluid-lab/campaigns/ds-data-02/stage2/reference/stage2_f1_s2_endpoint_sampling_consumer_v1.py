#!/usr/bin/env python3
"""Consume bounded F1-S2 endpoint reports without inventing an error bound.

This sidecar is deliberately downstream of the ROOT231/232 native readers.
It reads only their compact JSON reports and their small producer evidence
files.  For each registered query it reports the actual lower/upper saved
times and the observed component-space differences when both endpoint fields
are present.  It never interpolates, reads Part/H5/VTK payloads, compares a
neighbouring grid as truth, or turns a bracket width into a field-error bound.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f1-s2.endpoint-sampling-consumer.v1"
MANIFEST_SCHEMA = "ds02.stage2.f1-s2.endpoint-sampling-manifest.v1"
PASS_STATUS = "COMPLETE_F1_S2_ENDPOINT_OBSERVED_TIME_DIAGNOSTICS_NO_SCIENTIFIC_Q"
FAIL_STATUS = "FAILED_F1_S2_ENDPOINT_SAMPLING_CONSUMER"
MAX_SMALL_BYTES = 32 * 1024 * 1024
ALLOWED_LABELS = {"coarse", "medium", "fine"}
FIELDS = ("weighted_centroid_m", "weighted_velocity_m_per_s", "kinetic_energy_j")


class ConsumerFailure(RuntimeError):
    pass


def _stat_tuple(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _stat_dict(value: os.stat_result) -> dict[str, int]:
    return {
        "dev": int(value.st_dev),
        "ino": int(value.st_ino),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
    }


def _read_stable(path: Path, label: str, *, max_bytes: int = MAX_SMALL_BYTES) -> tuple[bytes, dict[str, Any]]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise ConsumerFailure(f"{label} is not a regular non-symlink file: {path}")
    before = path.stat()
    if before.st_size > max_bytes:
        raise ConsumerFailure(f"{label} exceeds the bounded report read: {path}")
    digest = hashlib.sha256()
    chunks: list[bytes] = []
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            chunks.append(chunk)
    after = path.stat()
    if _stat_tuple(before) != _stat_tuple(after):
        raise ConsumerFailure(f"{label} changed while being read: {path}")
    return b"".join(chunks), {"path": str(path), "sha256": digest.hexdigest(), "stat": _stat_dict(after)}


def _record(path_record: dict[str, Any], label: str) -> tuple[Any, dict[str, Any]]:
    if not isinstance(path_record, dict) or not isinstance(path_record.get("path"), str):
        raise ConsumerFailure(f"{label} is missing a path record")
    payload, actual = _read_stable(Path(path_record["path"]), label)
    expected_sha = path_record.get("sha256")
    if not isinstance(expected_sha, str) or actual["sha256"] != expected_sha:
        raise ConsumerFailure(f"{label} SHA does not match the bound producer record")
    expected_stat = path_record.get("stat")
    if isinstance(expected_stat, dict):
        for key in ("dev", "ino", "bytes", "mtime_ns", "ctime_ns"):
            if key in expected_stat and int(actual["stat"][key]) != int(expected_stat[key]):
                raise ConsumerFailure(f"{label} {key} changed since binding")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConsumerFailure(f"{label} is not bounded JSON metadata: {exc}") from exc
    return value, actual


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ConsumerFailure(f"{label} is boolean")
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ConsumerFailure(f"{label} is not numeric") from exc
    if not math.isfinite(value):
        raise ConsumerFailure(f"{label} is non-finite")
    return value


def _vector(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ConsumerFailure(f"{label} is not a 3-vector")
    return [_finite_number(item, f"{label}[{index}]") for index, item in enumerate(value)]


def _difference(left: Any, right: Any, label: str) -> dict[str, Any]:
    if left is None or right is None:
        return {"status": "UNKNOWN_MISSING_ENDPOINT_FIELD", "value": None, "field": label}
    if label == "kinetic_energy_j":
        a = _finite_number(left, f"lower {label}")
        b = _finite_number(right, f"upper {label}")
        return {"status": "OBSERVED_ENDPOINT_DIFFERENCE", "value": abs(b - a), "lower": a, "upper": b, "field": label}
    a = _vector(left, f"lower {label}")
    b = _vector(right, f"upper {label}")
    delta = [abs(b[i] - a[i]) for i in range(3)]
    return {"status": "OBSERVED_ENDPOINT_DIFFERENCE", "value": delta, "norm2": math.sqrt(sum(item * item for item in delta)), "lower": a, "upper": b, "field": label}


def _find_grid(report: dict[str, Any], label: str) -> dict[str, Any]:
    grids = report.get("grids")
    if isinstance(grids, list):
        matches = [item for item in grids if isinstance(item, dict) and item.get("label") == label]
        if len(matches) == 1:
            return matches[0]
    grid = report.get("grid")
    if isinstance(grid, dict) and grid.get("label") == label:
        return grid
    raise ConsumerFailure(f"producer report has no unique {label} grid")


def _case_observations(grid: dict[str, Any]) -> dict[int, dict[str, Any]]:
    case = grid.get("calibrated_v1_case_result")
    if not isinstance(case, dict):
        raise ConsumerFailure(f"{grid.get('label')} report has no calibrated case result")
    rows = case.get("selected_observations")
    if not isinstance(rows, list) or not rows:
        raise ConsumerFailure(f"{grid.get('label')} report has no selected native observations")
    result: dict[int, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ConsumerFailure(f"{grid.get('label')} selected observation is not an object")
        frame = row.get("frame")
        if isinstance(frame, bool) or not isinstance(frame, int) or frame in result:
            raise ConsumerFailure(f"{grid.get('label')} selected frame IDs are missing or duplicated")
        observables = row.get("observables")
        if not isinstance(observables, dict):
            raise ConsumerFailure(f"{grid.get('label')} selected observation lacks observables")
        fluid = observables.get("fluid_observable_using_native_MassFluid")
        if not isinstance(fluid, dict):
            raise ConsumerFailure(f"{grid.get('label')} selected observation lacks native-mass fluid fields")
        result[frame] = {"row": row, "fluid": fluid}
    return result


def _query_diagnostic(grid: dict[str, Any], query: dict[str, Any], observations: dict[int, dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(query, dict):
        raise ConsumerFailure(f"{grid.get('label')} query is not an object")
    query_time = _finite_number(query.get("query_time_s"), "query_time_s")
    lower = query.get("lower")
    upper = query.get("upper")
    if not isinstance(lower, dict) or not isinstance(upper, dict):
        raise ConsumerFailure(f"{grid.get('label')} query lacks lower/upper saved rows")
    lower_frame = lower.get("frame")
    upper_frame = upper.get("frame")
    if not isinstance(lower_frame, int) or not isinstance(upper_frame, int):
        raise ConsumerFailure(f"{grid.get('label')} query frame identifiers are not native frame IDs")
    if lower_frame not in observations or upper_frame not in observations:
        raise ConsumerFailure(f"{grid.get('label')} query endpoint field is not in the selected observations")
    lower_time = _finite_number(lower.get("time_s"), "lower saved time")
    upper_time = _finite_number(upper.get("time_s"), "upper saved time")
    if lower_time > query_time or upper_time < query_time or upper_time < lower_time:
        raise ConsumerFailure(f"{grid.get('label')} query bracket does not contain its registered time")
    if query.get("interpolation") != "NOT_PERFORMED" or query.get("extrapolation") not in (None, "FORBIDDEN"):
        raise ConsumerFailure(f"{grid.get('label')} query is not a no-interpolation bracket")
    left = observations[lower_frame]["fluid"]
    right = observations[upper_frame]["fluid"]
    differences = {field: _difference(left.get(field), right.get(field), field) for field in FIELDS}
    return {
        "query_time_s": query_time,
        "lower": {"native_frame": lower_frame, "saved_time_s": lower_time},
        "upper": {"native_frame": upper_frame, "saved_time_s": upper_time},
        "saved_time_gap_s": upper_time - lower_time,
        "fields": differences,
        "interpretation": "observed endpoint change only; not an interpolation error or truth estimate",
    }


def _consume_producer(producer: dict[str, Any], registered_queries: list[float]) -> dict[str, Any]:
    label = producer.get("label")
    if label not in ALLOWED_LABELS:
        raise ConsumerFailure(f"invalid producer grid label: {label!r}")
    report, report_actual = _record(producer.get("report"), f"{label} endpoint report")
    if not str(report.get("schema", "")).startswith("ds02.stage2.f1-s2.query"):
        raise ConsumerFailure(f"{label} report schema is not an F1-S2 endpoint report")
    if report.get("status", "").startswith("FAILED"):
        raise ConsumerFailure(f"{label} endpoint producer failed: {report.get('status')}")
    qualification = report.get("scientific_qualification")
    if isinstance(qualification, dict) and any(qualification.get(key) not in (None, "UNKNOWN") for key in ("QI", "QN", "QE")):
        raise ConsumerFailure(f"{label} endpoint report has unauthorized scientific qualification")
    # Proof/request/receipt are optional for a compact diagnostic sidecar, but
    # when supplied their hashes are checked and their evidence is preserved.
    evidence: dict[str, Any] = {"report": report_actual}
    for key in ("proof", "request", "receipt"):
        if key in producer:
            value, actual = _record(producer[key], f"{label} {key}")
            evidence[key] = actual
            if key == "proof" and isinstance(value, dict):
                bound_sha = value.get("report_sha256")
                if isinstance(bound_sha, str) and bound_sha != report_actual["sha256"]:
                    raise ConsumerFailure(f"{label} proof does not bind the supplied report")
    grid = _find_grid(report, label)
    queries = grid.get("actual_saved_window", {}).get("queries")
    if not isinstance(queries, list):
        raise ConsumerFailure(f"{label} report has no actual saved-window queries")
    by_time = {round(_finite_number(item.get("query_time_s"), f"{label} query time"), 12): item for item in queries}
    observations = _case_observations(grid)
    diagnostics: list[dict[str, Any]] = []
    for query_time in registered_queries:
        item = by_time.get(round(query_time, 12))
        if item is None:
            diagnostics.append({"query_time_s": query_time, "status": "UNKNOWN_QUERY_NOT_PRESENT_IN_PRODUCER"})
        else:
            diagnostics.append(_query_diagnostic(grid, item, observations))
    return {
        "label": label,
        "report": evidence,
        "diagnostics": diagnostics,
        "selected_frame_count": len(observations),
        "axis_scope": "component-space only; world-axis orientation remains UNKNOWN",
    }


def _write_once(path: Path, value: Any) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise ConsumerFailure(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def run(manifest_path: Path, output: Path) -> dict[str, Any]:
    payload, manifest_record = _read_stable(manifest_path, "F1-S2 endpoint sampling manifest")
    manifest = json.loads(payload.decode("utf-8"))
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "PREPARED_NOT_RUN_F1_S2_ENDPOINT_SAMPLING_CONSUMER":
        raise ConsumerFailure("endpoint sampling manifest schema/status mismatch")
    registered = manifest.get("registered_query_times_s")
    if not isinstance(registered, list) or not registered or len(registered) > 8:
        raise ConsumerFailure("registered query times must be a bounded non-empty list")
    registered_queries = [_finite_number(value, "registered query time") for value in registered]
    if registered_queries != sorted(set(registered_queries)):
        raise ConsumerFailure("registered query times must be sorted and unique")
    producers = manifest.get("producers")
    if not isinstance(producers, list) or len(producers) != 3 or {item.get("label") for item in producers if isinstance(item, dict)} != ALLOWED_LABELS:
        raise ConsumerFailure("exactly coarse/medium/fine endpoint producers are required")
    outputs = [_consume_producer(item, registered_queries) for item in producers]
    result = {
        "schema": SCHEMA,
        "status": PASS_STATUS,
        "manifest": manifest_record,
        "registered_query_times_s": registered_queries,
        "producers": outputs,
        "diagnostic_semantics": {
            "saved_time_source": "producer RunPARTs-derived actual saved times",
            "interpolation": "FORBIDDEN",
            "extrapolation": "FORBIDDEN",
            "bracket_width_is_field_error": False,
            "endpoint_difference_is_integrator_error": False,
            "neighbor_grid_is_truth": False,
            "event_time": "UNKNOWN_UNREGISTERED",
        },
        "error_bound_status": "NOT_IDENTIFIABLE_FROM_ENDPOINTS",
        "registered_task_tolerances": {"position_m": "UNKNOWN_UNREGISTERED", "velocity_m_per_s": "UNKNOWN_UNREGISTERED", "kinetic_energy_j": "UNKNOWN_UNREGISTERED"},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
        "read_scope": {"report_json_only": True, "native_payload_read": False, "hdf5_read": False, "vtk_read": False, "interpolation": False, "solver_launch": False},
    }
    _write_once(output, result)
    return result


def _fixture_report(label: str) -> dict[str, Any]:
    rows = []
    for frame, time_s, x in ((0, 0.99, 1.0), (1, 1.01, 1.2)):
        rows.append({"frame": frame, "time_s": time_s, "observables": {"fluid_observable_using_native_MassFluid": {"weighted_centroid_m": [x, 2.0, 3.0], "weighted_velocity_m_per_s": [0.1 * x, 0.2, 0.3], "kinetic_energy_j": x}}})
    return {"schema": "ds02.stage2.f1-s2.query1-endpoint-observer.v3", "status": "COMPLETE_QUERY1_NATIVE_COMPONENT_DIAGNOSTICS_NO_SCIENTIFIC_Q", "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}, "grids": [{"label": label, "actual_saved_window": {"queries": [{"query_time_s": 1.0, "lower": {"frame": 0, "time_s": 0.99}, "upper": {"frame": 1, "time_s": 1.01}, "interpolation": "NOT_PERFORMED", "extrapolation": "FORBIDDEN"}]}, "calibrated_v1_case_result": {"selected_observations": rows}}]}


def self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="f1-s2-endpoint-consumer-") as temporary:
        root = Path(temporary)
        producers = []
        for label in ("coarse", "medium", "fine"):
            report_path = root / f"{label}.json"
            report_path.write_text(json.dumps(_fixture_report(label), sort_keys=True) + "\n", encoding="utf-8")
            stat = report_path.stat()
            digest = hashlib.sha256(report_path.read_bytes()).hexdigest()
            producers.append({"label": label, "report": {"path": str(report_path), "sha256": digest, "stat": _stat_dict(stat)}})
        manifest_path = root / "manifest.json"
        manifest_path.write_text(json.dumps({"schema": MANIFEST_SCHEMA, "status": "PREPARED_NOT_RUN_F1_S2_ENDPOINT_SAMPLING_CONSUMER", "registered_query_times_s": [1.0], "producers": producers}, sort_keys=True) + "\n", encoding="utf-8")
        result = run(manifest_path, root / "out.json")
        assert result["error_bound_status"] == "NOT_IDENTIFIABLE_FROM_ENDPOINTS"
        assert result["producers"][0]["diagnostics"][0]["fields"]["kinetic_energy_j"]["value"] == 0.19999999999999996
        bad = json.loads(manifest_path.read_text(encoding="utf-8"))
        bad["producers"][0]["report"]["sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(bad, sort_keys=True) + "\n", encoding="utf-8")
        try:
            run(manifest_path, root / "bad.json")
        except ConsumerFailure:
            pass
        else:
            raise AssertionError("changed producer report was accepted")
    print("PASS_F1_S2_ENDPOINT_SAMPLING_CONSUMER_SELFTEST")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.manifest is None or args.output is None:
        parser.error("--manifest and --output are required unless --self-test is used")
    try:
        result = run(args.manifest, args.output)
    except Exception as exc:
        print(f"FAIL_F1_S2_ENDPOINT_SAMPLING_CONSUMER: {exc}")
        return 2
    print(json.dumps({"status": result["status"], "output": str(args.output.expanduser().absolute())}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
