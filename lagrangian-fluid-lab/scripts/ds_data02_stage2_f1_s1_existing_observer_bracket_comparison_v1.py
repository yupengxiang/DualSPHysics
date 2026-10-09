#!/usr/bin/env python3
"""Compare already-produced F1 selected observers at saved-time brackets.

Only JSON reports and their immutable verification records are read.  The
worker reports endpoint values from each saved bracket and raw same-CFL versus
half-CFL deltas.  It never interpolates between saved frames, treats an
asynchronous endpoint delta as integration error, or opens a native payload.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f1.s1.existing-observer-bracket-comparison.v1"
MANIFEST_SCHEMA = "ds02.stage2.f1.s1.existing-observer-bracket-comparison.manifest.v1"
PROOF_SCHEMA = "ds02.stage2.root-actual-verification.v1"
REPORT_SCHEMA = "ds02.stage2.native-physical-observer.v2"
VARIANTS = ("dp005_same", "dp005_half", "dp0025_same", "dp0025_half")
QUERY_TIMES = (0.0, 0.4, 0.8, 1.2, 1.6)
FRAMES = (0, 79, 80, 159, 160, 239, 240, 319, 320)
METRICS = ("count", "sample_mass_kg", "centroid_m", "weighted_centroid_m", "mean_velocity_m_per_s", "weighted_velocity_m_per_s", "kinetic_energy_j")


class ComparisonError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise ComparisonError(f"missing input: {path}")
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "ctime_ns": stat.st_ctime_ns, "st_dev": stat.st_dev, "st_ino": stat.st_ino, "sha256": sha256_file(path)}


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ComparisonError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ComparisonError(f"{label} must be an object: {path}")
    return value


def expect(actual: Any, wanted: Any, label: str) -> None:
    if actual != wanted:
        raise ComparisonError(f"{label}: expected {wanted!r}, got {actual!r}")


def finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ComparisonError(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise ComparisonError(f"{label} is not finite")
    return result


def load_refs(manifest: dict[str, Any]) -> tuple[dict[str, Path], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    refs = manifest.get("source_refs")
    if not isinstance(refs, list) or not refs:
        raise ComparisonError("manifest source_refs is empty")
    paths: dict[str, Path] = {}
    records: dict[str, dict[str, Any]] = {}
    docs: dict[str, dict[str, Any]] = {}
    for ref in refs:
        if not isinstance(ref, dict) or not isinstance(ref.get("key"), str):
            raise ComparisonError("malformed source reference")
        key = ref["key"]
        if key in paths:
            raise ComparisonError(f"duplicate source reference: {key}")
        path = Path(str(ref.get("path", ""))).expanduser().resolve()
        if path.suffix.lower() != ".json":
            raise ComparisonError(f"{key} is not JSON: {path}")
        actual = record(path)
        if ref.get("sha256") not in (None, "PARENT_GUARD_COMPUTED"):
            expect(actual["sha256"], str(ref["sha256"]), f"{key} SHA")
        for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
            if ref.get(field) is not None:
                expect(actual[field], int(ref[field]), f"{key} {field}")
        paths[key] = path
        records[key] = actual
        docs[key] = read_json(path, key)
    return paths, records, docs


def bind_proof_report(proof: dict[str, Any], proof_key: str, report: dict[str, Any], report_record: dict[str, Any]) -> None:
    expect(proof.get("schema"), PROOF_SCHEMA, f"{proof_key} schema")
    expect(proof.get("status"), "PASS_ACTUAL_NINE_NATIVE_SOURCE_FIELD_SUMMARY_JOIN", f"{proof_key} status")
    expect(proof.get("H5_BI4_read_by_root"), False, f"{proof_key} payload read")
    expect(proof.get("report_sha256"), report_record["sha256"], f"{proof_key} report SHA")
    expect(report.get("schema"), REPORT_SCHEMA, f"{proof_key} report schema")
    expect(report.get("status"), "PASS_DECODED_SELECTED_NATIVE_FIELDS", f"{proof_key} report status")
    scope = report.get("scope")
    if not isinstance(scope, dict):
        raise ComparisonError(f"{proof_key} report lacks scope")
    expect(scope.get("selected_frame_count"), 9, f"{proof_key} selected frame count")
    expect(scope.get("hdf5_read"), False, f"{proof_key} HDF5 read")
    expect(scope.get("full_native_tree_scanned"), False, f"{proof_key} full tree scan")


def check_task_index(index: dict[str, Any]) -> dict[str, Any]:
    expect(index.get("schema"), "ds02.stage2.fourteen-source-status.v3", "fourteen-source index schema")
    expect(index.get("scope", {}).get("sentinel_count"), 14, "fourteen-source sentinel count")
    rows = [row for row in index.get("sentinels", []) if isinstance(row, dict) and row.get("sentinel_id") == "F1-S1"]
    if len(rows) != 1:
        raise ComparisonError("fourteen-source index lacks unique F1-S1")
    task = rows[0].get("next_guarded_task")
    if not isinstance(task, dict):
        raise ComparisonError("F1-S1 taskgraph entry is missing")
    expect(task.get("kind"), "JSON_ONLY_EXISTING_OBSERVER_COMPARISON", "F1-S1 task kind")
    return {"sentinel_id": rows[0]["sentinel_id"], "physical_case_id": rows[0]["physical_case_id"], "next_guarded_task": task, "frozen_gates": index.get("frozen_gates")}


def _vector(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ComparisonError(f"{label} is not a three-vector")
    return [finite(x, f"{label}[{i}]") for i, x in enumerate(value)]


def extract_saved_observation(observation: dict[str, Any], label: str) -> dict[str, Any]:
    time = observation.get("time")
    groups = observation.get("groups")
    if not isinstance(time, dict) or not isinstance(groups, dict) or "fluid" not in groups:
        raise ComparisonError(f"{label} lacks saved time/fluid group")
    fluid = groups["fluid"]
    if not isinstance(fluid, dict):
        raise ComparisonError(f"{label} fluid group is malformed")
    fields: dict[str, Any] = {}
    for metric in METRICS:
        value = fluid.get(metric)
        if metric in {"centroid_m", "weighted_centroid_m", "mean_velocity_m_per_s", "weighted_velocity_m_per_s"}:
            fields[metric] = _vector(value, f"{label}.{metric}")
        elif metric == "count":
            if not isinstance(value, int):
                raise ComparisonError(f"{label}.count is not an integer")
            fields[metric] = value
        else:
            fields[metric] = finite(value, f"{label}.{metric}")
    return {"frame": observation.get("frame"), "saved_time_s": finite(time.get("runparts_s"), f"{label}.runparts_s"), "decoded_time_s": finite(time.get("decoded_s"), f"{label}.decoded_s"), "fields": fields}


def delta(a: Any, b: Any) -> Any:
    if isinstance(a, list):
        return [y - x for x, y in zip(a, b)]
    return b - a


def max_abs(value: Any) -> float:
    if isinstance(value, list):
        return max(abs(float(x)) for x in value)
    return abs(float(value))


def extract_query(report: dict[str, Any], query_time: float, label: str) -> dict[str, Any]:
    queries = report.get("time_window", {}).get("queries")
    if not isinstance(queries, list):
        raise ComparisonError(f"{label} has no query brackets")
    matches = [q for q in queries if isinstance(q, dict) and float(q.get("query_time_s")) == query_time]
    if len(matches) != 1:
        raise ComparisonError(f"{label} query {query_time} is not unique")
    query = matches[0]
    lower = extract_saved_observation(query.get("lower_observation"), f"{label}@{query_time}.lower")
    upper = extract_saved_observation(query.get("upper_observation"), f"{label}@{query_time}.upper")
    return {
        "query_time_s": query_time, "status": query.get("status"),
        "lower_frame": query.get("lower_frame"), "upper_frame": query.get("upper_frame"),
        "lower_time_s": finite(query.get("lower_time_s"), f"{label}@{query_time}.lower_time"),
        "upper_time_s": finite(query.get("upper_time_s"), f"{label}@{query_time}.upper_time"),
        "bracket_width_s": finite(query.get("upper_time_s"), "upper") - finite(query.get("lower_time_s"), "lower"),
        "interpolation_performed": False,
        "lower": lower, "upper": upper,
    }


def pair_delta(left: dict[str, Any], right: dict[str, Any], label: str) -> dict[str, Any]:
    result: dict[str, Any] = {"left": label.split(" vs ")[0], "right": label.split(" vs ")[1], "lower_saved_time_delta_s": right["lower"]["saved_time_s"] - left["lower"]["saved_time_s"], "upper_saved_time_delta_s": right["upper"]["saved_time_s"] - left["upper"]["saved_time_s"], "metric_deltas": {}}
    for endpoint in ("lower", "upper"):
        result["metric_deltas"][endpoint] = {}
        for metric in METRICS:
            raw = delta(left[endpoint]["fields"][metric], right[endpoint]["fields"][metric])
            result["metric_deltas"][endpoint][metric] = {"raw_delta": raw, "max_abs_delta": max_abs(raw)}
    return result


def derive(manifest_path: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path.resolve(), "F1 comparison manifest")
    expect(manifest.get("schema"), MANIFEST_SCHEMA, "manifest schema")
    paths, records, docs = load_refs(manifest)
    index = check_task_index(docs["source_status_index"])
    cross = docs["cross_grid_proof"]
    expect(cross.get("neighbor_grid_truth_error"), "UNKNOWN", "cross-grid truth boundary")
    expect(cross.get("async_saved_times"), True, "cross-grid asynchronous time boundary")
    labels = {
        "dp005_same": ("dp005_same_proof", "dp005_same_report"),
        "dp005_half": ("dp005_half_proof", "dp005_half_report"),
        "dp0025_same": ("dp0025_same_proof", "dp0025_same_report"),
        "dp0025_half": ("dp0025_half_proof", "dp0025_half_report"),
    }
    reports: dict[str, dict[str, Any]] = {}
    report_records: dict[str, dict[str, Any]] = {}
    for label, (proof_key, report_key) in labels.items():
        proof, report = docs[proof_key], docs[report_key]
        proof_report_path = Path(str(proof.get("report", ""))).expanduser().resolve()
        expect(proof_report_path, paths[report_key], f"{label} report path")
        bind_proof_report(proof, proof_key, report, records[report_key])
        reports[label] = report
        report_records[label] = records[report_key]
        expect(report.get("source", {}).get("selected_frames"), list(FRAMES), f"{label} selected frames")
        expect(report.get("time_window", {}).get("queries", [{}])[0].get("query_time_s"), 0.0, f"{label} first query")
    common = {label: {str(query): extract_query(reports[label], query, label) for query in QUERY_TIMES} for label in VARIANTS}
    comparison_pairs = {
        "dp005_same_vs_half": ("dp005_same", "dp005_half"),
        "dp0025_same_vs_half": ("dp0025_same", "dp0025_half"),
        "same_cfl_dp005_vs_dp0025": ("dp005_same", "dp0025_same"),
        "half_cfl_dp005_vs_dp0025": ("dp005_half", "dp0025_half"),
    }
    comparisons: dict[str, Any] = {}
    for name, (left, right) in comparison_pairs.items():
        comparisons[name] = {
            "interpretation": "raw saved-endpoint comparison; asynchronous saved times are not integration error",
            "queries": [pair_delta(common[left][str(query)], common[right][str(query)], f"{left} vs {right}") for query in QUERY_TIMES],
        }
    bracket_summary = {
        label: [
            {"query_time_s": q, "status": common[label][str(q)]["status"], "bracket_width_s": common[label][str(q)]["bracket_width_s"], "lower_frame": common[label][str(q)]["lower_frame"], "upper_frame": common[label][str(q)]["upper_frame"], "lower_time_s": common[label][str(q)]["lower_time_s"], "upper_time_s": common[label][str(q)]["upper_time_s"], "interpolation_performed": False}
            for q in QUERY_TIMES
        ]
        for label in VARIANTS
    }
    return {
        "schema": SCHEMA,
        "status": "F1_SELECTED_OBSERVER_BRACKETS_COMPARED_NO_INTERPOLATION",
        "task_binding": index,
        "source_inputs": records,
        "variants": VARIANTS,
        "common_registered_queries_s": list(QUERY_TIMES),
        "selected_frames": list(FRAMES),
        "bracket_summary": bracket_summary,
        "raw_endpoint_comparisons": comparisons,
        "interpretation": {
            "exact_query_count_per_variant": 1,
            "bracketed_query_count_per_variant": 4,
            "saved_endpoint_deltas_are_not_integration_error": True,
            "spatial_and_temporal_effects_are_not_separated_by_this_consumer": True,
            "missing_brackets_remain_UNKNOWN": True,
            "no_continuous_time_interpolation": True,
            "pressure_or_EOS_not_decoded": True,
        },
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "integration_error": "UNKNOWN", "output_sampling_error": "UNKNOWN", "spatial_error": "UNKNOWN"},
        "read_policy": {"json_only": True, "native_payload_opened": False, "h5_opened": False, "bi4_opened": False, "vtk_opened": False, "solver_started": False, "old_products_modified": False},
    }


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise ComparisonError(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        atomic_json(args.output, derive(args.manifest))
    except ComparisonError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
