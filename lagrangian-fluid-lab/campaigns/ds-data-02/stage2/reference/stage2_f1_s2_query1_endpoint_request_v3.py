#!/usr/bin/env python3
"""Build the independent ROOT232 query-1 endpoint request.

The implementation delegates source joins and RunPARTs parsing to the
consumed-and-tested ROOT231 builder in a temporary output namespace, then
rebinds the manifest/request to this query-1 contract.  No production Part
file is opened or hashed during preparation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

import stage2_f1_s2_query_endpoint_request_v2 as _base


HERE = Path(__file__).resolve().parent
BUILDER = HERE / "stage2_f1_s2_query1_endpoint_request_v3.py"
WORKER = HERE / "stage2_f1_s2_query1_endpoint_observer_v3.py"
V2_OBSERVER = HERE / "stage2_f1_s2_query_endpoint_observer_v2.py"
CONTRACT = HERE / "stage2_f1_s2_query1_endpoint_contract_v2.json"
PYTHON = _base.PYTHON
PYTHON_TARGET = _base.PYTHON_TARGET
PYVENV_CFG = _base.PYVENV_CFG
ROOT = _base.ROOT
REQUEST_SCHEMA = "ds02.request.v1"
VARIANT_SCHEMA = "ds02.stage2.f1-s2.query1-endpoint-request.v3"
MANIFEST_SCHEMA = "ds02.stage2.f1-s2.query1-endpoint-manifest.v2"
QUERY_TIMES_S = (1.0,)
MAX_NATIVE_BYTES = _base.MAX_NATIVE_BYTES
NATIVE_READ_PASSES = _base.NATIVE_READ_PASSES


class BuildError(RuntimeError):
    pass


def stable_hash(path: Path, label: str, *, max_bytes: int = 16 * 1024 * 1024) -> dict[str, Any]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise BuildError(f"{label} is not a regular non-symlink file: {path}")
    before = path.stat()
    if before.st_size > max_bytes:
        raise BuildError(f"{label} exceeds bounded preparation read: {path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise BuildError(f"{label} changed while being read: {path}")
    return {"path": str(path), "label": label, "bytes": int(after.st_size), "sha256": digest, "stat": {"dev": int(after.st_dev), "ino": int(after.st_ino), "mtime_ns": int(after.st_mtime_ns), "ctime_ns": int(after.st_ctime_ns)}}


def write_once(path: Path, value: Any) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise BuildError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _configure_base() -> None:
    _base.CONTRACT = CONTRACT
    _base.WORKER = WORKER
    _base.VARIANT_SCHEMA = VARIANT_SCHEMA
    _base.MANIFEST_SCHEMA = MANIFEST_SCHEMA
    _base.QUERY_TIMES_S = QUERY_TIMES_S


def build(output_manifest: Path, output_request: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    _configure_base()
    output_manifest = output_manifest.expanduser().absolute()
    output_request = output_request.expanduser().absolute()
    with tempfile.TemporaryDirectory(prefix="root232-query1-build-") as temporary:
        temp_manifest = Path(temporary) / "manifest.json"
        temp_request = Path(temporary) / "request.json"
        manifest, _ = _base.build(temp_manifest, temp_request)
        request = json.loads(temp_request.read_text(encoding="utf-8"))
    manifest["schema"] = MANIFEST_SCHEMA
    manifest["status"] = "PREPARED_NOT_RUN_ROOT232_QUERY1_AXIS_INDEPENDENT_ENDPOINT_AUDIT"
    manifest["contract"] = {"path": str(CONTRACT), "sha256": stable_hash(CONTRACT, "ROOT232 query1 contract")["sha256"]}
    manifest["query"] = {"times_s": [1.0], "selection": "nearest actual RunPARTs row at or below and at or above 1 s", "interpolation": "FORBIDDEN", "extrapolation": "FORBIDDEN"}
    manifest["axis_scope"] = "component-space source convention only; producer world-axis orientation remains UNKNOWN"
    write_once(output_manifest, manifest)
    manifest_record = stable_hash(output_manifest, "ROOT232 manifest")

    static_records = [item for item in manifest.get("static_source_records", []) if isinstance(item, dict) and isinstance(item.get("path"), str)]
    records = {str(item["path"]): item for item in static_records}
    records[manifest_record["path"]] = manifest_record
    v2_record = stable_hash(V2_OBSERVER, "ROOT231 axis-independent reader dependency")
    builder_record = stable_hash(BUILDER, "ROOT232 query1 request builder")
    records[v2_record["path"]] = v2_record
    records[builder_record["path"]] = builder_record
    deferred = manifest.get("deferred_native_records")
    if not isinstance(deferred, list) or len(deferred) == 0 or len(deferred) > 6:
        raise BuildError(f"ROOT232 deferred native record count outside [1,6]: {len(deferred) if isinstance(deferred, list) else 'invalid'}")
    static_bytes = sum(int(item.get("bytes", 0)) for item in records.values())
    native_read_bytes = 6 * MAX_NATIVE_BYTES * NATIVE_READ_PASSES
    request.update({
        "schema": REQUEST_SCHEMA,
        "variant_schema": VARIANT_SCHEMA,
        "status": "READY_FOR_PARENT_V8_F1_S2_QUERY1_AXIS_INDEPENDENT_ENDPOINT_AUDIT",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "request_id": "f1-s2-query1-axis-independent-endpoint-audit-root232-001",
        "case_id": "F1_S2_QUERY1_AXIS_INDEPENDENT_ENDPOINT_AUDIT_ROOT232",
        "attempt_id": "f1-s2-query1-axis-independent-endpoint-audit-root232-001",
        "command": [str(PYTHON), "-B", str(WORKER), "--manifest", "{attempt_root}/inputs/f1_s2_query1_endpoint_manifest_v2.json", "--attempt-root", "{attempt_root}", "--output", "{attempt_root}/observer/f1_s2_query1_endpoint_observer_v3.json"],
        "literal_venv_invocation": {"path": str(PYTHON), "argv0_literal": True, "resolved_target": str(PYTHON_TARGET), "pyvenv_cfg": str(PYVENV_CFG)},
        "input_files": sorted(records),
        "input_sha256": {path: item["sha256"] for path, item in records.items()},
        "input_records": records,
        "manifest": manifest_record,
        "deferred_input_files": sorted(item["path"] for item in deferred),
        "deferred_input_records": deferred,
        "deferred_input_policy": {"parent_after_reservation_first_sha_and_stat": True, "parent_after_child_post_sha_and_stat": True, "required_stat_fields": ["bytes", "mtime_ns", "ctime_ns", "dev", "ino"], "producer_known_sha_is_not_builder_computed": True, "source_replace_or_stat_change": "FAIL", "selected_frame_count_upper_bound": 6},
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 1800,
        "max_memory_bytes": 2 * 1024**3,
        "max_storage_bytes": 512 * 1024**2,
        "estimated_peak_memory_bytes": 2 * 1024**3,
        "estimated_scratch_bytes": 512 * 1024**2,
        "estimated_storage_bytes": 512 * 1024**2,
        "estimated_native_read_passes": NATIVE_READ_PASSES,
        "estimated_native_read_bytes": native_read_bytes,
        "estimated_native_read_bytes_is_conservative_upper_bound": True,
        "estimated_input_read_bytes": static_bytes + native_read_bytes,
        "estimated_input_read_bytes_scope": "static metadata plus at most six deferred native files at the 512 MiB cap and four worker/decoder passes; actual bytes remain parent-measured",
        "estimated_hdf5_read_bytes": 0,
        "runtime_closure": {"literal_python": {"path": str(PYTHON), "resolved_target": str(PYTHON_TARGET), "pyvenv_cfg": str(PYVENV_CFG)}, "worker": str(WORKER), "axis_independent_reader": str(V2_OBSERVER), "calibrated_observer": str((HERE / "stage2_f1_native_selected_observer_v1.py").resolve()), "base_observer": str((HERE / "stage2_native_physical_observer_v2.py").resolve()), "parent_v8_deferred_sha_stat_gate": True},
        "storage_scope": {"output_root": "{attempt_root}", "native_payload_read": "nearest lower/upper Part files for query 1 second only", "h5_vtk_allowed": False, "full_native_tree_scan": False, "solver_launch": False},
        "source_binding": {**request.get("source_binding", {}), "manifest": str(output_manifest), "axis_scope": "component-space only; world-axis UNKNOWN", "query_times_s": [1.0], "interpolation": "FORBIDDEN", "neighbor_grid_truth": False, "root225_failure_preserved": True, "root231_query234_bytes_preserved": True},
        "scope": {"queries_s": [1.0], "nearest_lower_upper_native_frames": True, "native_mass_from_decoder": True, "science_Q": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}},
        "launch_disabled": True,
        "execution_allowed": False,
        "solver_started": False,
        "native_payload_read": False,
        "hdf5_read": False,
        "ledger_mutation": False,
        "qualification_credit": 0,
    })
    write_once(output_request, request)
    return manifest, request


def self_test() -> None:
    _configure_base()
    assert QUERY_TIMES_S == (1.0,)
    assert VARIANT_SCHEMA.endswith(".v3")
    print("PASS_F1_S2_QUERY1_ENDPOINT_REQUEST_V3_SELFTEST")


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--output-manifest", type=Path)
    parser.add_argument("--output-request", type=Path)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.output_manifest is None or args.output_request is None:
        parser.error("--output-manifest and --output-request are required with --build")
    try:
        build(args.output_manifest, args.output_request)
    except (BuildError, OSError, ValueError, KeyError) as exc:
        print(f"FAIL_F1_S2_QUERY1_ENDPOINT_REQUEST_V3: {exc}")
        return 2
    print(f"PASS_PREPARED_F1_S2_QUERY1_ENDPOINT {args.output_manifest} {args.output_request}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
