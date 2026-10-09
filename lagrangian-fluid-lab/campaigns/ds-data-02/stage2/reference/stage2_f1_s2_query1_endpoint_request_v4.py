#!/usr/bin/env python3
"""Build the independent ROOT234 query-1 request.

This forward builder consumes only the existing ROOT232 source joins in a
temporary namespace and emits a fresh manifest/request pair for the one
second endpoint.  It does not use ROOT231's 2/3/4-second output as a query-1
result or open any deferred Part file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

import stage2_f1_s2_query1_endpoint_observer_v4 as worker
import stage2_f1_s2_query1_endpoint_request_v3 as base


HERE = Path(__file__).resolve().parent
WORKER = HERE / "stage2_f1_s2_query1_endpoint_observer_v4.py"
BASE_WORKER = HERE / "stage2_f1_s2_query1_endpoint_observer_v3.py"
BASE_READER = HERE / "stage2_f1_s2_query_endpoint_observer_v2.py"
BUILDER = HERE / "stage2_f1_s2_query1_endpoint_request_v4.py"
CONTRACT = HERE / "stage2_f1_s2_query1_endpoint_contract_v3.json"
PYTHON = base.PYTHON
PYTHON_TARGET = base.PYTHON_TARGET
PYVENV_CFG = base.PYVENV_CFG
ROOT = base.ROOT
REQUEST_SCHEMA = "ds02.request.v1"
VARIANT_SCHEMA = "ds02.stage2.f1-s2.query1-endpoint-request.v4"
MANIFEST_SCHEMA = "ds02.stage2.f1-s2.query1-endpoint-manifest.v3"
MAX_SMALL_BYTES = 16 * 1024 * 1024
MAX_NATIVE_BYTES = base.MAX_NATIVE_BYTES
NATIVE_READ_PASSES = base.NATIVE_READ_PASSES


class BuildError(RuntimeError):
    pass


def stable_hash(path: Path, label: str, *, max_bytes: int = MAX_SMALL_BYTES) -> dict[str, Any]:
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
    return {"path": str(path), "label": label, "bytes": int(after.st_size), "sha256": digest, "stat": {"dev": int(after.st_dev), "ino": int(after.st_ino), "bytes": int(after.st_size), "mtime_ns": int(after.st_mtime_ns), "ctime_ns": int(after.st_ctime_ns)}}


def write_once(path: Path, value: Any) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise BuildError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _decorate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    grids = manifest.get("grids")
    deferred = manifest.get("deferred_native_records")
    if not isinstance(grids, list) or len(grids) != 3:
        raise BuildError("ROOT234 requires three grid records")
    labels = [item.get("label") for item in grids if isinstance(item, dict)]
    if labels != ["coarse", "medium", "fine"]:
        raise BuildError(f"ROOT234 grid labels are not frozen: {labels!r}")
    if not isinstance(deferred, list) or len(deferred) != 6:
        raise BuildError("ROOT234 requires six deferred endpoint records")
    decorated: list[dict[str, Any]] = []
    offset = 0
    for grid in grids:
        label = grid["label"]
        query = grid.get("queries")
        if not isinstance(query, list) or len(query) != 1 or float(query[0].get("query_time_s")) != 1.0:
            raise BuildError(f"{label} lacks the frozen 1 second query")
        selected = {int(query[0]["lower"]["frame"]), int(query[0]["upper"]["frame"])}
        for record in deferred:
            # The base builder already emits grid and endpoint labels; derive
            # the final records by identity rather than trusting list order.
            if isinstance(record, dict) and record.get("grid") == label:
                existing = record.get("grid_label")
                if existing not in (None, label):
                    raise BuildError(f"{label} deferred record has conflicting grid_label")
                item = dict(record)
                item["grid"] = label
                item["grid_label"] = label
                if item.get("frame") not in selected:
                    raise BuildError(f"{label} deferred record is outside the query bracket")
                decorated.append(item)
        if len([item for item in decorated if item.get("grid") == label]) != len(selected):
            raise BuildError(f"{label} does not have exactly its lower/upper endpoint records")
        offset += len(selected)
    if len(decorated) != len(deferred):
        raise BuildError("ROOT234 deferred records contain an unknown grid")
    result = dict(manifest)
    result["schema"] = MANIFEST_SCHEMA
    result["status"] = "PREPARED_NOT_RUN_ROOT234_QUERY1_AXIS_INDEPENDENT_ENDPOINT_AUDIT"
    result["deferred_native_records"] = decorated
    result["contract"] = {"path": str(CONTRACT), "sha256": stable_hash(CONTRACT, "ROOT234 query-1 contract")["sha256"]}
    result["query"] = {"times_s": [1.0], "selection": "nearest actual RunPARTs row below/above 1 s", "interpolation": "FORBIDDEN", "extrapolation": "FORBIDDEN"}
    result["axis_scope"] = "component-space source convention only; producer world-axis orientation remains UNKNOWN"
    result["source_binding"] = {**(result.get("source_binding") if isinstance(result.get("source_binding"), dict) else {}), "root225_failure_preserved": True, "root231_query234_not_used_as_query1": True, "grid_and_grid_label_entry_bound": True}
    return result


def _records(values: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item["path"]): item for item in values if isinstance(item, dict) and isinstance(item.get("path"), str)}


def build(output_manifest: Path, output_request: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    output_manifest = output_manifest.expanduser().absolute()
    output_request = output_request.expanduser().absolute()
    with tempfile.TemporaryDirectory(prefix="root234-query1-build-") as temporary:
        temp_manifest = Path(temporary) / "manifest.json"
        temp_request = Path(temporary) / "request.json"
        _, base_request = base.build(temp_manifest, temp_request)
        manifest = json.loads(temp_manifest.read_text(encoding="utf-8"))
    manifest = _decorate_manifest(manifest)
    records = _records(base_request.get("input_records", []))
    records.pop(str(temp_manifest), None)
    records.pop(str(temp_manifest.absolute()), None)
    for path, label in (
        (WORKER, "ROOT234 query-1 observer"),
        (BASE_WORKER, "ROOT232 query-1 observer"),
        (BASE_READER, "ROOT231 axis-independent endpoint reader"),
        (BUILDER, "ROOT234 query-1 request builder"),
        (CONTRACT, "ROOT234 query-1 contract"),
        (ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py", "runtime V8"),
        (ROOT / "lagrangian-fluid-lab/scripts/ds_data02_batch_runner.py", "batch runner"),
        (ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py", "stage2 dispatch V8"),
        (ROOT / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py", "strict dispatch V8"),
        (PYVENV_CFG, "literal venv configuration"),
        (PYTHON_TARGET, "resolved Python target"),
    ):
        record = stable_hash(path, label)
        records[record["path"]] = record
    manifest["static_source_records"] = list(records.values())
    write_once(output_manifest, manifest)
    manifest_record = stable_hash(output_manifest, "ROOT234 final manifest")
    records[manifest_record["path"]] = manifest_record
    deferred = manifest["deferred_native_records"]
    native_read_bytes = len(deferred) * MAX_NATIVE_BYTES * NATIVE_READ_PASSES
    static_bytes = sum(int(item.get("bytes", 0)) for item in records.values())
    request = {
        "schema": REQUEST_SCHEMA,
        "variant_schema": VARIANT_SCHEMA,
        "status": "READY_FOR_PARENT_V8_F1_S2_QUERY1_AXIS_INDEPENDENT_ENDPOINT_AUDIT_ROOT234",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "request_id": "f1-s2-query1-axis-independent-endpoint-audit-root234-001",
        "family_id": "F1",
        "sentinel_id": "F1-S2",
        "physical_case_id": "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1",
        "case_id": "F1_S2_QUERY1_AXIS_INDEPENDENT_ENDPOINT_AUDIT_ROOT234",
        "attempt_id": "f1-s2-query1-axis-independent-endpoint-audit-root234-001",
        "cwd": str(ROOT),
        "worktree_root": str(ROOT),
        "command": [str(PYTHON), "-B", str(WORKER), "--manifest", "{attempt_root}/inputs/f1_s2_query1_endpoint_manifest_v3.json", "--attempt-root", "{attempt_root}", "--output", "{attempt_root}/observer/f1_s2_query1_endpoint_observer_v4.json"],
        "literal_venv_invocation": {"path": str(PYTHON), "argv0_literal": True, "resolved_target": str(PYTHON_TARGET), "pyvenv_cfg": str(PYVENV_CFG)},
        "input_files": sorted(records),
        "input_sha256": {path: item["sha256"] for path, item in records.items()},
        "input_records": records,
        "manifest": manifest_record,
        "deferred_input_files": sorted(item["path"] for item in deferred),
        "deferred_input_records": deferred,
        "deferred_input_policy": {"parent_after_reservation_first_sha_and_stat": True, "parent_after_child_post_sha_and_stat": True, "required_stat_fields": ["bytes", "mtime_ns", "ctime_ns", "dev", "ino"], "producer_known_sha_is_not_builder_computed": True, "source_replace_or_stat_change": "FAIL", "selected_frame_count": 6},
        "grid_label_entry_contract": {"builder_emits_both": True, "reader_requires_equal_grid_and_grid_label": True, "missing_or_conflicting": "FAIL"},
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
        "estimated_input_read_bytes_scope": "static metadata plus six deferred lower/upper Part files at the 512 MiB cap and four worker/decoder passes; actual bytes remain parent-measured",
        "estimated_hdf5_read_bytes": 0,
        "runtime_closure": {"literal_python": {"path": str(PYTHON), "resolved_target": str(PYTHON_TARGET), "pyvenv_cfg": str(PYVENV_CFG)}, "worker": str(WORKER), "base_worker": str(BASE_WORKER), "axis_independent_reader": str(BASE_READER), "calibrated_observer": str(HERE / "stage2_f1_native_selected_observer_v1.py"), "base_observer": str(HERE / "stage2_native_physical_observer_v2.py"), "parent_v8_deferred_sha_stat_gate": True},
        "storage_scope": {"output_root": "{attempt_root}", "native_payload_read": "nearest lower/upper Part files for query 1 second only", "h5_vtk_allowed": False, "full_native_tree_scan": False, "solver_launch": False},
        "source_binding": {"manifest": str(output_manifest), "root225_failure_preserved": True, "root231_query234_not_used_as_query1": True, "axis_scope": "component-space only; world-axis UNKNOWN", "query_times_s": [1.0], "interpolation": "FORBIDDEN", "neighbor_grid_truth": False},
        "scope": {"queries_s": [1.0], "nearest_lower_upper_native_frames": True, "native_mass_from_decoder": True, "science_Q": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}},
        "resources": {"gpu": False, "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 1800, "memory_max_bytes": 2 * 1024**3, "external_storage_max_bytes": 512 * 1024**2, "home_storage_max_bytes": 128 * 1024**2, "log_max_bytes": 512 * 1024, "parent_guard_required": True},
        "launch_disabled": True,
        "execution_allowed": False,
        "solver_started": False,
        "native_payload_read": False,
        "hdf5_read": False,
        "ledger_mutation": False,
        "qualification_credit": 0,
    }
    write_once(output_request, request)
    return manifest, request


def self_test() -> None:
    # Use the same shape emitted by build() and the same entry validator used
    # by the worker.  This catches a builder/reader mismatch before guard.
    grids = []
    deferred = []
    for label, lower, upper in (("coarse", 199, 200), ("medium", 99, 100), ("fine", 199, 200)):
        grids.append({"label": label, "queries": [{"query_time_s": 1.0, "lower": {"frame": lower, "time_s": 0.99}, "upper": {"frame": upper, "time_s": 1.01}, "interpolation": "NOT_PERFORMED", "extrapolation": "FORBIDDEN"}]})
        for frame in (lower, upper):
            deferred.append({"grid": label, "grid_label": label, "frame": frame, "path": f"/deferred/{label}/Part_{frame:04d}.bi4", "sha256": "PARENT_AFTER_RESERVATION"})
    manifest = {"schema": MANIFEST_SCHEMA, "status": "PREPARED_NOT_RUN_ROOT234_QUERY1_AXIS_INDEPENDENT_ENDPOINT_AUDIT", "grids": grids, "deferred_native_records": deferred}
    worker.validate_manifest_entry(manifest)
    bad = json.loads(json.dumps(manifest))
    bad["deferred_native_records"][0]["grid"] = "fine"
    try:
        worker.validate_manifest_entry(bad)
    except ValueError:
        pass
    else:
        raise AssertionError("ROOT234 accepted a builder grid mismatch")
    print("PASS_F1_S2_QUERY1_ENDPOINT_REQUEST_V4_BUILDER_READER_ENTRY_SELFTEST")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
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
    except (BuildError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"FAIL_F1_S2_QUERY1_ENDPOINT_REQUEST_V4: {exc}")
        return 2
    print(f"PASS_PREPARED_F1_S2_QUERY1_ENDPOINT_V4 {args.output_manifest} {args.output_request}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
