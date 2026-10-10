#!/usr/bin/env python3
"""Prepare a parent-bound request for two-attempt scalar diagnostics.

The builder consumes only a small pair manifest and source/proof metadata. It
does not hash or open the deferred native observer reports; those reports are
read by ``stage2_rotation_invariant_native_scalar_observer_v1.py`` only after
the parent has reserved the request.  The resulting request is source
prepared, execution-disabled, and diagnostic-only.  A parent may normalize it
to a real ``audit`` task once both actual observer producer edges are closed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
WORKER = HERE / "stage2_rotation_invariant_native_scalar_observer_v2.py"
SCHEMA = "ds02.stage2.rotation-invariant-native-scalar-request.v2"
PAIR_SOURCE_SCHEMA = "ds02.stage2.rotation-invariant-native-scalar-pair.v2"
MANIFEST_SCHEMA = "ds02.stage2.rotation-invariant-native-scalar-manifest.v2"
REQUEST_SCHEMA = "ds02.request.v1"
JSON_CAP = 10 * 1024 * 1024
UNKNOWN = "UNKNOWN"
PLACEHOLDERS = {"PARENT_AFTER_RESERVATION", "PARENT_AFTER_RESERVATION_REQUIRED", "UNKNOWN"}
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYVENV = PYTHON.parent.parent / "pyvenv.cfg"


class BuildFailure(RuntimeError):
    pass


def _absolute(value: Path) -> Path:
    return value.expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino),
            "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
            "ctime_ns": int(value.st_ctime_ns)}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-fA-F]{64}", value))


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _absolute(path)
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular non-symlink JSON file: {path}")
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise BuildFailure(f"{label} exceeds the 10 MiB metadata cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after:
        raise BuildFailure(f"{label} changed while being read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildFailure(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise BuildFailure(f"{label} must be a JSON object")
    return value, {"path": str(path), "sha256": _sha(raw), "stat": after,
                   "read_mode": "bounded_small_source", "payload_read_by_builder": True}


def _source_record(path_value: Any, label: str, declared: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(path_value, Path):
        path_value = str(path_value)
    if not isinstance(path_value, str) or not path_value:
        raise BuildFailure(f"{label} lacks an explicit path")
    path = _absolute(Path(path_value))
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular source file: {path}")
    actual = _stat(path)
    if actual["bytes"] > JSON_CAP:
        raise BuildFailure(f"{label} exceeds the 10 MiB static metadata cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if actual != after:
        raise BuildFailure(f"{label} changed while being recorded: {path}")
    digest = _sha(raw)
    expected = (declared or {}).get("sha256") if isinstance(declared, dict) else None
    if _valid_sha(expected) and digest.lower() != expected.lower():
        raise BuildFailure(f"{label} SHA differs from its declared source edge")
    return {"path": str(path), "sha256": digest, "stat": after,
            "read_mode": "bounded_small_source", "payload_read_by_builder": True,
            "scope": "source_metadata_only"}


def _deferred_record(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise BuildFailure(f"{label} lacks a deferred path record")
    path = _absolute(Path(value["path"]))
    declared = value.get("sha256")
    if declared is not None and not _valid_sha(declared) and declared not in PLACEHOLDERS:
        raise BuildFailure(f"{label} has a malformed SHA")
    stat = value.get("stat") or value.get("stat_before") or value.get("stat_after")
    if not isinstance(stat, dict):
        if not path.is_file() or path.is_symlink():
            raise BuildFailure(f"{label} has neither a current file nor a declared stat")
        stat = _stat(path)
    return {"path": str(path), "sha256": declared if declared is not None else "PARENT_AFTER_RESERVATION",
            "stat": {str(key): int(value) for key, value in stat.items() if str(key) in
                     {"device", "inode", "bytes", "mtime_ns", "ctime_ns", "dev", "ino", "st_dev", "st_ino"}},
            "hash_status": "PARENT_AFTER_RESERVATION_REQUIRED",
            "read_mode": "deferred_compact_observer_report",
            "payload_read_by_builder": False, "scope": "parent_deferred_json_only"}


def _literal_python() -> dict[str, Any]:
    if not PYTHON.is_symlink() or not PYTHON.exists() or not PYVENV.is_file():
        raise BuildFailure("literal project venv or pyvenv.cfg is unavailable")
    target = PYTHON.resolve(strict=True)
    if not target.is_file():
        raise BuildFailure("literal venv target is not a regular file")
    target_record = _source_record(target, "resolved venv interpreter")
    pyvenv_record = _source_record(PYVENV, "pyvenv.cfg")
    return {"literal_argv0": str(PYTHON), "resolved_target": str(target),
            "resolved_target_sha256": target_record["sha256"],
            "target_record": target_record, "pyvenv": pyvenv_record}


def _identity(pair: dict[str, Any]) -> dict[str, Any]:
    identity = pair.get("source_identity")
    if not isinstance(identity, dict):
        raise BuildFailure("pair source_identity is missing")
    digest = identity.get("source_identity_digest")
    if not isinstance(digest, str) or not digest or digest in PLACEHOLDERS:
        raise BuildFailure("pair source identity is not bound")
    if identity.get("component_basis") != "PRODUCER_COMPONENT_XYZ":
        raise BuildFailure("pair does not declare the producer component basis")
    if identity.get("world_orientation") != "UNKNOWN":
        raise BuildFailure("world orientation must remain UNKNOWN")
    if identity.get("world_directional_claims") is not False:
        raise BuildFailure("world-directional claims must be explicitly disabled")
    if identity.get("flux_claims") is not False or identity.get("owner_mass_claims") is not False:
        raise BuildFailure("flux/owner claims must be explicitly disabled")
    return identity


def _validate_pair(pair: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    if pair.get("schema") != PAIR_SOURCE_SCHEMA:
        raise BuildFailure("pair source schema mismatch")
    identity = _identity(pair)
    attempts = pair.get("attempts")
    if not isinstance(attempts, list) or len(attempts) != 2:
        raise BuildFailure("pair source must contain exactly two attempts")
    normalized: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    for index, attempt in enumerate(attempts):
        if not isinstance(attempt, dict):
            raise BuildFailure(f"attempt {index} is malformed")
        if attempt.get("source_identity_digest") != identity["source_identity_digest"]:
            raise BuildFailure(f"attempt {index} does not use the common source identity")
        attempt_id = attempt.get("attempt_id")
        if not isinstance(attempt_id, str) or not attempt_id:
            raise BuildFailure(f"attempt {index} lacks attempt_id")
        report = _deferred_record(attempt.get("report"), f"attempt {index} report")
        normalized.append({"label": str(attempt.get("label") or attempt_id),
                           "attempt_id": attempt_id,
                           "source_identity_digest": identity["source_identity_digest"],
                           "rows_key": str(attempt.get("rows_key") or "observations"),
                           "report": report})
        deferred.append(report)
    if normalized[0]["attempt_id"] == normalized[1]["attempt_id"]:
        raise BuildFailure("attempt IDs must be distinct")
    query_times = pair.get("query_times_s")
    if not isinstance(query_times, list) or not query_times:
        raise BuildFailure("pair query_times_s is empty")
    query_numbers = [float(item) for item in query_times]
    if not all(math.isfinite(item) for item in query_numbers):
        raise BuildFailure("pair query_times_s contains nonfinite values")
    if query_numbers != sorted(set(query_numbers)):
        raise BuildFailure("pair query_times_s must be sorted and unique")
    source_refs = pair.get("source_refs", [])
    if not isinstance(source_refs, list):
        raise BuildFailure("pair source_refs must be a list")
    return identity, normalized, source_refs


def build(pair_path: Path, output_dir: Path) -> dict[str, Any]:
    pair, pair_record = _read_json(pair_path, "scalar pair source manifest")
    identity, attempts, source_refs = _validate_pair(pair)
    deferred = [attempt["report"] for attempt in attempts]
    output_dir = _absolute(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise BuildFailure(f"refusing nonempty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    worker_record = _source_record(WORKER, "scalar observer worker")
    builder_record = _source_record(Path(__file__), "scalar request builder")
    python_record = _literal_python()
    static: dict[str, dict[str, Any]] = {
        worker_record["path"]: worker_record,
        builder_record["path"]: builder_record,
        python_record["pyvenv"]["path"]: python_record["pyvenv"],
        python_record["target_record"]["path"]: python_record["target_record"],
        pair_record["path"]: pair_record,
    }
    for index, ref in enumerate(source_refs):
        if not isinstance(ref, dict):
            raise BuildFailure(f"source_refs[{index}] is not an object")
        record = _source_record(ref.get("path"), f"source_refs[{index}]", ref)
        static[record["path"]] = record
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "READY_FOR_PARENT_ROTATION_INVARIANT_NATIVE_SCALAR",
        "source_identity": identity,
        "attempts": attempts,
        "query_times_s": [float(item) for item in pair["query_times_s"]],
        "source_scope": {"pair_manifest": pair_record, "static_source_records": list(static.values()),
                         "deferred_reports": deferred, "native_bi4_payload": False,
                         "vtk_payload": False, "hdf5_payload": False},
        "metric_scope": {"rotation_invariant": ["native_sample_mass_total_kg", "velocity_norm_m_per_s",
                                                   "kinetic_energy_j", "component_com_delta_norm_m"],
                          "mass_header_semantics": "MassFluid/MassBound are per-particle weights; typed role counts or per-ID native weights are required for a sample total",
                          "header_only_total": UNKNOWN,
                          "world_directional_velocity": UNKNOWN, "flux": UNKNOWN,
                          "continuous_owner_mass": UNKNOWN, "interpolation": False,
                          "scientific_credit": 0},
        "scientific_qualification": {"QI": UNKNOWN, "QN": UNKNOWN, "QE": UNKNOWN,
                                      "scientific_credit": 0},
        "builder_provenance": {"path": builder_record["path"], "sha256": builder_record["sha256"],
                                "payload_read_by_builder": False, "execution_allowed": False},
    }
    manifest_path = output_dir / "rotation-invariant-native-scalar-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_record = _source_record(manifest_path, "final scalar manifest")
    static[manifest_record["path"]] = manifest_record
    request = {
        "schema": REQUEST_SCHEMA,
        "variant_schema": SCHEMA,
        "family_id": str(pair.get("family_id") or "infra"),
        "sentinel_id": str(pair.get("sentinel_id") or "UNASSIGNED_SCALAR_DIAGNOSTIC"),
        "case_id": str(pair.get("case_id") or "rotation-invariant-native-scalar-pair"),
        "attempt_id": str(pair.get("request_attempt_id") or "parent-after-reservation-required"),
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "execution_allowed": False,
        "solver_launch": False,
        "gencase_launch": False,
        "command": [str(PYTHON), str(WORKER), "--run", "--manifest",
                     "{attempt_root}/rotation-invariant-native-scalar-manifest.json", "--output",
                     "{attempt_root}/rotation-invariant-native-scalar-report.json"],
        "literal_python": python_record,
        "manifest": manifest_record,
        "input_files": sorted(static),
        "input_records": static,
        "input_sha256": {path: record["sha256"] for path, record in static.items()
                          if _valid_sha(record.get("sha256"))},
        "deferred_input_records": deferred,
        "estimated_resource_scope": {"cpu_seconds": 30, "memory_bytes": 512 * 1024 * 1024,
                                     "scratch_bytes": 8 * 1024 * 1024,
                                     "native_payload_reads": 0,
                                     "compact_json_report_reads": 2},
        "status": "SOURCE_PREPARED_PARENT_AFTER_RESERVATION_REQUIRED",
        "scientific_qualification": {"QI": UNKNOWN, "QN": UNKNOWN, "QE": UNKNOWN,
                                      "scientific_credit": 0},
        "source_only": True,
    }
    request_path = output_dir / "rotation-invariant-native-scalar-request.json"
    request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"manifest_path": str(manifest_path), "request_path": str(request_path),
            "manifest": manifest, "request": request}


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="rotation-invariant-request-") as value:
        root = Path(value)
        source = root / "proof.json"; source.write_text('{"status":"VERIFIED_ACTUAL_SOURCE_EDGE"}\n', encoding="utf-8")
        report_a = root / "a.json"; report_b = root / "b.json"
        report_a.write_text('{"status":"deferred"}\n', encoding="utf-8")
        report_b.write_text('{"status":"deferred"}\n', encoding="utf-8")
        def record(path: Path) -> dict[str, Any]:
            return {"path": str(path), "sha256": _sha(path.read_bytes()), "stat": _stat(path)}
        pair = {
            "schema": PAIR_SOURCE_SCHEMA,
            "family_id": "F1", "sentinel_id": "F1-S2", "case_id": "fixture-pair",
            "source_identity": {"source_identity_digest": "fixture-source-identity",
                                "physical_case_id": "fixture-case",
                                "component_basis": "PRODUCER_COMPONENT_XYZ",
                                "world_orientation": "UNKNOWN", "world_directional_claims": False,
                                "flux_claims": False, "owner_mass_claims": False},
            "attempts": [
                {"label": "same", "attempt_id": "a", "source_identity_digest": "fixture-source-identity",
                 "report": {"path": str(report_a), "sha256": "PARENT_AFTER_RESERVATION", "stat": _stat(report_a)}},
                {"label": "half", "attempt_id": "b", "source_identity_digest": "fixture-source-identity",
                 "report": {"path": str(report_b), "sha256": "PARENT_AFTER_RESERVATION", "stat": _stat(report_b)}},
            ],
            "query_times_s": [0.0, 0.25, 0.5],
            "source_refs": [record(source)],
        }
        pair_path = root / "pair.json"; pair_path.write_text(json.dumps(pair, indent=2) + "\n", encoding="utf-8")
        result = build(pair_path, root / "out")
        assert result["request"]["execution_allowed"] is False
        assert len(result["request"]["deferred_input_records"]) == 2
        assert result["manifest"]["metric_scope"]["world_directional_velocity"] == UNKNOWN
        assert result["request"]["literal_python"]["literal_argv0"] == str(PYTHON)
        bad = dict(pair); bad["source_identity"] = dict(pair["source_identity"], world_orientation="BOUND")
        bad_path = root / "bad.json"; bad_path.write_text(json.dumps(bad) + "\n", encoding="utf-8")
        try:
            build(bad_path, root / "bad-out")
        except BuildFailure:
            pass
        else:
            raise AssertionError("world-oriented pair source was accepted")
    print("PASS_ROTATION_INVARIANT_NATIVE_SCALAR_REQUEST_SOURCE_BOUND_FIXTURE")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--self-test", action="store_true")
    modes.add_argument("--build", action="store_true")
    parser.add_argument("--pair", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test(); return 0
        if args.pair is None or args.output_dir is None:
            parser.error("--build requires --pair and --output-dir")
        result = build(args.pair, args.output_dir)
        print(json.dumps({"status": result["request"]["status"],
                          "manifest": result["manifest_path"], "request": result["request_path"],
                          "scientific_credit": 0}, sort_keys=True))
        return 0
    except (BuildFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_ROTATION_INVARIANT_NATIVE_SCALAR_REQUEST: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
