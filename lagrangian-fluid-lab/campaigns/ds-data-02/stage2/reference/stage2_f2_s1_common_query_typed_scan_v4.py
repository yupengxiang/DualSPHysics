#!/usr/bin/env python3
"""Run a bounded physical-time query scan on one converted DS-DATA-02 HDF5 (v4 strict query/canonical-v2 contract).

The trajectory is opened only by the guarded consumer run. Query times are
physical seconds; this wrapper first obtains the typed time axis and then
selects the exact/bracketing saved frames dynamically. It never maps an old
frame number to a physical time by assumption. The worker reads selected HDF5
content for the registered query, but does not compute a full HDF5 payload
digest; the parent v4 guard hashes the registered HDF5 input pre/post.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


DEFAULT_FIELDS = ("position", "velocity", "density", "mass", "valid", "type", "mk")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": sha256_file(path),
    }


def load_reader(path: Path):
    spec = importlib.util.spec_from_file_location("stage2_generic_typed_reader_v1_for_query_scan", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import generic reader: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise
    return module


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def canonical_payload_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def verify_producer_binding(trajectory: Path, conversion_report: Path, conversion_control_audit: Path,
                            source_sidecar: Path, canonical_condition: Path) -> dict[str, Any]:
    report = load_json(conversion_report)
    audit = load_json(conversion_control_audit)
    sidecar = load_json(source_sidecar)
    if sidecar.get("schema") != "ds-data-02.stage2.f2-s1.full401-effective-condition-and-material-sidecar.v3":
        raise ValueError("source sidecar is not the canonical-v2/material-semantics v3 sidecar")
    canonical = load_json(canonical_condition)
    if canonical.get("schema") != "ds-data-02.stage2.f2-s1.effective-condition-canonical.v2":
        raise ValueError("canonical condition schema is not the registered v2 schema")
    payload = canonical.get("canonical_payload")
    declared_payload_sha = canonical.get("canonical_payload_sha256")
    if not isinstance(payload, dict) or not isinstance(declared_payload_sha, str):
        raise ValueError("canonical condition has no payload or declared payload SHA")
    actual_payload_sha = canonical_payload_sha256(payload)
    if actual_payload_sha != declared_payload_sha:
        raise ValueError("canonical condition payload SHA does not match its content")
    sidecar_binding = sidecar.get("canonical_condition_binding", {})
    if sidecar_binding.get("path") and Path(str(sidecar_binding["path"])).expanduser().resolve() != canonical_condition.resolve():
        raise ValueError("sidecar canonical path does not identify the supplied canonical condition")
    canonical_file_sha = sha256_file(canonical_condition)
    if canonical_file_sha != sidecar_binding.get("file_sha256"):
        raise ValueError("canonical condition file SHA differs from sidecar binding")
    if declared_payload_sha != sidecar_binding.get("payload_sha256"):
        raise ValueError("canonical condition payload SHA differs from sidecar binding")
    expected_output = report.get("output_hdf5")
    if expected_output and Path(str(expected_output)).expanduser().resolve() != trajectory.resolve():
        raise ValueError("conversion report output_hdf5 does not identify the supplied trajectory")
    declared_sha = report.get("output_sha256")
    typed = sidecar.get("actual_conversion_binding", {}).get("typed_output", {})
    if declared_sha != typed.get("producer_declared_sha256"):
        raise ValueError("conversion report and effective-condition sidecar disagree on producer HDF5 digest")
    if int(trajectory.stat().st_size) != int(typed.get("bytes")):
        raise ValueError("typed HDF5 byte count differs from effective-condition sidecar")
    if audit.get("status") != "COMPLETED_CONVERSION_AND_CONTROL_AUDIT":
        raise ValueError("conversion control audit is not completed")
    scope = sidecar.get("scope", {})
    if scope.get("h5_payload_sha256_computed_by_worker") is not False:
        raise ValueError("source sidecar must explicitly state that the worker did not compute a full HDF5 payload hash")
    identity = sidecar.get("physical_identity", {})
    if identity.get("family_id") != "F2" or identity.get("sentinel_id") != "F2-S1":
        raise ValueError("source sidecar physical identity is not F2-S1")
    return {
        "conversion_report": record(conversion_report),
        "conversion_control_audit": record(conversion_control_audit),
        "source_sidecar": record(source_sidecar),
        "producer_declared_hdf5_sha256": declared_sha,
        "producer_declared_hdf5_bytes": int(typed["bytes"]),
        "full_hdf5_payload_sha256": "NOT_COMPUTED_BY_WORKER; parent v4 guard hashes registered H5 input",
        "control_semantics": sidecar.get("control_semantics"),
        "initial_material_mass_audit": sidecar.get("initial_material_mass_audit"),
        "effective_condition_canonical_hash": declared_payload_sha,
        "effective_condition_canonical_file": {"path": str(canonical_condition), "sha256": canonical_file_sha},
        "h5_hash_policy": "parent v4 guard hashes registered H5 input pre/post; worker does not compute payload hash",
        "canonical_mass_semantics": "continuous region target and discrete reference sample target are separate; numerical recipe and observation scope are linked metadata",
    }


def validate_query_brackets(axis: dict[str, Any], query_times: list[float]) -> list[dict[str, Any]]:
    if not query_times:
        raise ValueError("at least one physical query time is required")
    brackets = axis.get("query_time_brackets")
    if not isinstance(brackets, list) or len(brackets) != len(query_times):
        raise ValueError("reader returned an incomplete query bracket list")
    shape = axis.get("shape_contract", {})
    datasets = shape.get("datasets", {})
    time_meta = datasets.get("time_values_s", {})
    frame_count = int(shape.get("frames", 0))
    if frame_count <= 0 or int(time_meta.get("count", -1)) != frame_count:
        raise ValueError("typed time axis metadata is incomplete")
    allowed = {"EXACT_OR_LEFT", "EXACT", "BRACKETED"}
    for query, bracket in zip(query_times, brackets):
        if not isinstance(query, (int, float)) or not __import__("math").isfinite(float(query)):
            raise ValueError(f"query time is not finite: {query!r}")
        if not isinstance(bracket, dict) or bracket.get("status") not in allowed:
            raise ValueError(f"query time has no usable saved-time bracket: {query!r}: {bracket!r}")
        lower, upper = bracket.get("lower_index"), bracket.get("upper_index")
        if not isinstance(lower, int) or not isinstance(upper, int) or not (0 <= lower <= upper < frame_count):
            raise ValueError(f"query time bracket has incomplete indices: {query!r}: {bracket!r}")
    return brackets


def query_scan(reader: Any, trajectory: Path, conversion_report: Path,
               query_times: list[float], fields: tuple[str, ...],
               full_frame: bool, sample_count: int) -> dict[str, Any]:
    # First pass reads only the typed axes/identity and derives physical-time brackets.
    if not query_times:
        raise ValueError("at least one physical query time is required")
    if any(not __import__("math").isfinite(float(value)) for value in query_times):
        raise ValueError("query times must all be finite")
    axis = reader.inspect_trajectory(
        trajectory,
        conversion_report=conversion_report,
        query_times=query_times,
    )
    brackets = validate_query_brackets(axis, query_times)
    selected: set[int] = set()
    for bracket in brackets:
        if bracket.get("status") in {"EXACT_OR_LEFT", "EXACT", "BRACKETED"}:
            for key in ("lower_index", "upper_index"):
                value = bracket.get(key)
                if isinstance(value, int):
                    selected.add(value)
    indices = sorted(selected)
    scan = reader.inspect_trajectory(
        trajectory,
        conversion_report=conversion_report,
        frame_indices=indices,
        query_times=query_times,
        sample_count=sample_count,
        fields=fields,
        full_frame=full_frame,
    )
    return {
        "axis_pass": {
            "frames": axis["shape_contract"]["frames"],
            "particles": axis["shape_contract"]["particles"],
            "time_values_s": axis["shape_contract"]["datasets"]["time_values_s"],
            "query_time_brackets": brackets,
        },
        "selected_frame_indices": indices,
        "selected_frame_policy": "derived from each physical query-time bracket; no frame-index/time assumption",
        "scan": scan,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reader", type=Path, required=True)
    parser.add_argument("--trajectory", type=Path, required=True)
    parser.add_argument("--conversion-report", type=Path, required=True)
    parser.add_argument("--conversion-control-audit", type=Path, required=True)
    parser.add_argument("--source-sidecar", type=Path, required=True)
    parser.add_argument("--canonical-condition", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--query-time", type=float, action="append", required=True)
    parser.add_argument("--field", dest="fields", action="append", default=None)
    parser.add_argument("--sample-count", type=int, default=256)
    parser.add_argument("--full-frame", action="store_true")
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output}")
    trajectory = args.trajectory.expanduser().resolve()
    binding = verify_producer_binding(
        trajectory,
        args.conversion_report.expanduser().resolve(),
        args.conversion_control_audit.expanduser().resolve(),
        args.source_sidecar.expanduser().resolve(),
        args.canonical_condition.expanduser().resolve(),
    )
    reader = load_reader(args.reader.expanduser().resolve())
    fields = tuple(args.fields) if args.fields else DEFAULT_FIELDS
    result = query_scan(reader, trajectory, args.conversion_report.expanduser().resolve(),
                        [float(value) for value in args.query_time], fields,
                        bool(args.full_frame), int(args.sample_count))
    audit = {
        "schema": "ds-data-02.stage2.f2-s1.common-query-typed-scan.v4",
        "status": "STRUCTURAL_COMMON_QUERY_SCAN_PASS",
        "trajectory": {"path": str(trajectory), "bytes": trajectory.stat().st_size,
                       "producer_declared_sha256": binding["producer_declared_hdf5_sha256"],
                       "full_payload_sha256": "NOT_COMPUTED_BY_WORKER; parent v4 guard hashes registered H5 input"},
        "producer_binding": binding,
        "query_registration": {
            "query_times_s": [float(value) for value in args.query_time],
            "fields": list(fields),
            "full_frame": bool(args.full_frame),
            "sample_count": int(args.sample_count),
            "observer_calibration": "NOT_RUN",
            "canonical_condition": str(args.canonical_condition.expanduser().resolve()),
            "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
        },
        "query_scan": result,
        "scope": {
            "full_trajectory_payload": False,
            "full_hdf5_hash": "NOT_COMPUTED_BY_WORKER; parent v4 guard hashes registered H5 input",
            "solver_started": False,
            "scientific_qualification": "UNKNOWN",
            "policy": "Every registered query must have a finite exact/bracketing saved-time pair; out-of-window and malformed queries fail before output; parent guard hashes the registered H5 input; no extrapolation or reference eligibility claim.",
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": audit["status"], "output": str(output),
                      "selected_frame_indices": result["selected_frame_indices"],
                      "full_payload_sha256": "NOT_COMPUTED_BY_WORKER; parent v4 guard hashes registered H5 input"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
