#!/usr/bin/env python3
"""Build a V4 request whose command actually consumes V2 deferred records.

This builder is source-only.  It reads only the small V2 request/manifest and
small code/configuration files.  It stats, but never opens or hashes, the 25
deferred native inputs.  Runtime v8 still sees only small ``input_files``;
``stage2_f1_native_selected_observer_guarded_v4.py`` consumes the deferred
records after reservation and invokes the immutable V1 worker.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import os
import tempfile
from typing import Any


REQUEST_SCHEMA = "ds02.request.v1"
VARIANT_SCHEMA = "ds02.stage2.f1.native-selected-observer-request.v4"
MANIFEST_SCHEMA = "ds02.stage2.f1.native-selected-observer-manifest.v2"
OLD_VARIANT = "ds02.stage2.f1.native-selected-observer-request.v2"
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
OLD_REFERENCE = Path("/home/jade/.codex/worktrees/ds-data-02-stage2-reference/DualSPHysics")
REFERENCE = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
REQUESTS = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests"
WRAPPER = REFERENCE / "stage2_f1_native_selected_observer_guarded_v4.py"
BUILDER = REFERENCE / "stage2_f1_native_selected_observer_request_v4.py"
CONTRACT = REFERENCE / "stage2_f1_native_selected_observer_contract_v4.json"
STATUS_SIDECAR = REFERENCE / "stage2_f1_native_selected_observer_v3_launch_status_v4.json"
V1_WORKER = REFERENCE / "stage2_f1_native_selected_observer_v1.py"
V1_BUILDER = REFERENCE / "stage2_f1_native_selected_observer_request_v1.py"
V1_CONTRACT = REFERENCE / "stage2_f1_native_selected_observer_contract_v1.json"
V2_BUILDER = REFERENCE / "stage2_f1_native_selected_observer_request_v2.py"
V2_CONTRACT = REFERENCE / "stage2_f1_native_selected_observer_contract_v2.json"
BASE_OBSERVER = REFERENCE / "stage2_native_physical_observer_v2.py"
RUNTIME = PRIMARY / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
RUNNER = PRIMARY / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT_GUARD = PRIMARY / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYVENV = PYTHON.parent.parent / "pyvenv.cfg"
FORBIDDEN = {".bi4", ".h5", ".hdf5", ".vtk", ".vtu"}
MAX_SMALL = 8 * 1024 * 1024
MAX_METADATA = 10 * 1024 * 1024
DEFERRED_COUNT = 25
NATIVE_PASSES = 4
SCRATCH_CAP = 256 * 1024 * 1024
MEMORY_CAP = 2 * 1024 * 1024 * 1024


class BuildFailure(RuntimeError):
    pass


def _path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def _remap(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(str(OLD_REFERENCE)):
        return str(PRIMARY / value[len(str(OLD_REFERENCE)):].lstrip("/"))
    if isinstance(value, list):
        return [_remap(item) for item in value]
    if isinstance(value, dict):
        return {key: _remap(item) for key, item in value.items()}
    return value


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular file: {path}")
    if path.stat().st_size > MAX_SMALL:
        raise BuildFailure(f"{label} exceeds small-file limit: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BuildFailure(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise BuildFailure(f"{label} is not an object")
    return value


def _small_record(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular non-symlink file: {path}")
    if path.suffix.lower() in FORBIDDEN:
        raise BuildFailure(f"native payload leaked into input_files: {path}")
    value = path.stat()
    if value.st_size > MAX_SMALL:
        raise BuildFailure(f"{label} exceeds source-only limit: {path}")
    data = path.read_bytes()
    return {
        "path": str(path),
        "label": label,
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "device": int(value.st_dev),
        "inode": int(value.st_ino),
        "sha256": hashlib.sha256(data).hexdigest(),
        "content_scope": "small_source_hashed_by_v4_builder",
    }


def _hex(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise BuildFailure(f"{label} is not a SHA256 digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise BuildFailure(f"{label} is not hexadecimal") from exc
    return value.lower()


def _write_once(path: Path, value: Any) -> None:
    if path.exists() or path.is_symlink():
        raise BuildFailure(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _deferred_from(v2: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    records = v2.get("deferred_input_records")
    if not isinstance(records, dict):
        records = manifest.get("native_deferred_records")
    if not isinstance(records, dict) or len(records) != DEFERRED_COUNT:
        raise BuildFailure("V2 source does not carry exactly 25 deferred records")
    output: dict[str, Any] = {}
    for key, raw in records.items():
        if not isinstance(raw, dict) or not isinstance(raw.get("path"), str):
            raise BuildFailure(f"deferred record {key!r} is malformed")
        path = _path(raw["path"])
        if path.suffix.lower() != ".bi4" or path.is_symlink() or not path.is_file():
            raise BuildFailure(f"deferred source is not a regular BI4 file: {path}")
        if str(path) != str(_path(str(key))):
            raise BuildFailure(f"deferred record key/path mismatch: {key}")
        known = raw.get("known_sha256", raw.get("sha256"))
        _hex(known, f"deferred known SHA {path}")
        # This is deliberately stat-only.  Opening the Part here would make
        # the builder an unreserved native reader.
        stat_value = path.stat()
        expected_bytes = int(raw.get("bytes", -1))
        expected_mtime = int(raw.get("mtime_ns", -1))
        if int(stat_value.st_size) != expected_bytes or int(stat_value.st_mtime_ns) != expected_mtime:
            raise BuildFailure(f"deferred metadata changed before V4 request build: {path}")
        output[str(path)] = _remap(raw)
        output[str(path)]["path"] = str(path)
    if len(output) != DEFERRED_COUNT:
        raise BuildFailure("deferred source paths are not unique")
    return output


def _closure_paths(v2: dict[str, Any], v2_path: Path, manifest_path: Path) -> list[Path]:
    paths: list[Path] = []
    for raw in v2.get("input_files", []):
        if not isinstance(raw, str):
            raise BuildFailure("V2 input_files contains a non-string")
        paths.append(_path(_remap(raw)))
    paths.extend([
        v2_path,
        manifest_path,
        WRAPPER,
        BUILDER,
        CONTRACT,
        STATUS_SIDECAR,
        V1_WORKER,
        V1_BUILDER,
        V1_CONTRACT,
        V2_BUILDER,
        V2_CONTRACT,
        BASE_OBSERVER,
        RUNTIME,
        RUNNER,
        STRICT_GUARD,
        PYVENV,
    ])
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        path = _path(path)
        if str(path) in seen:
            continue
        seen.add(str(path))
        unique.append(path)
    return unique


def build(v2_request_path: Path, *, output_request: Path, case_id: str, attempt_id: str) -> dict[str, Any]:
    v2_path = _path(v2_request_path)
    v2_raw = _read_json(v2_path, "V2 request")
    v2 = _remap(v2_raw)
    if v2.get("schema") != REQUEST_SCHEMA or v2.get("variant_schema") != OLD_VARIANT:
        raise BuildFailure("input request is not the immutable ROOT204 V2 request")
    manifest_obj = v2.get("manifest")
    if not isinstance(manifest_obj, dict) or not isinstance(manifest_obj.get("path"), str):
        raise BuildFailure("V2 request has no manifest path")
    manifest_path = _path(manifest_obj["path"])
    manifest = _read_json(manifest_path, "V2 manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise BuildFailure(f"expected V2 manifest schema, got {manifest.get('schema')!r}")
    deferred = _deferred_from(v2, manifest)
    closure = _closure_paths(v2, v2_path, manifest_path)
    records: dict[str, dict[str, Any]] = {}
    old_sha = {str(_path(_remap(k))): value for k, value in (v2.get("input_sha256") or {}).items()}
    metadata_bytes = 0
    for path in closure:
        if path.suffix.lower() in FORBIDDEN:
            raise BuildFailure(f"payload present in input closure: {path}")
        if not path.is_file() or path.is_symlink():
            raise BuildFailure(f"source closure path is not a regular file: {path}")
        if str(path) in old_sha:
            digest = _hex(old_sha[str(path)], f"V2 input SHA {path}")
            stat_value = path.stat()
            if stat_value.st_size > MAX_SMALL:
                raise BuildFailure(f"source closure path is too large: {path}")
            records[str(path)] = {
                "path": str(path),
                "label": "inherited V2 small closure",
                "bytes": int(stat_value.st_size),
                "mtime_ns": int(stat_value.st_mtime_ns),
                "ctime_ns": int(stat_value.st_ctime_ns),
                "device": int(stat_value.st_dev),
                "inode": int(stat_value.st_ino),
                "sha256": digest,
                "content_scope": "inherited_v2_parent_hash_required",
            }
        else:
            record = _small_record(path, "V4 wrapper/runtime closure")
            metadata_bytes += int(record["bytes"])
            records[str(path)] = record
    if metadata_bytes > MAX_METADATA:
        raise BuildFailure(f"new V4 source metadata read exceeded 10 MiB: {metadata_bytes}")

    input_files = sorted(records)
    if any(Path(path).suffix.lower() in FORBIDDEN for path in input_files):
        raise BuildFailure("native/H5/VTK payload leaked into V4 input_files")
    deferred_bytes = sum(int(record.get("bytes", 0)) for record in deferred.values())
    native_bytes = deferred_bytes * NATIVE_PASSES
    output_path = "{attempt_root}/observer/f1_native_selected_observer_v4.json"
    command = [
        str(PYTHON),
        str(WRAPPER),
        "--run",
        "--manifest", str(manifest_path),
        "--attempt-root", "{attempt_root}",
        "--output", output_path,
        "--v1-worker", str(V1_WORKER),
        "--python", str(PYTHON),
        "--cwd", str(PRIMARY),
        "--max-scratch-bytes", str(SCRATCH_CAP),
        "--max-log-bytes", str(1024 * 1024),
        "--timeout-seconds", "1800",
    ]
    return {
        "schema": REQUEST_SCHEMA,
        "variant_schema": VARIANT_SCHEMA,
        "status": "READY_FOR_PARENT_GUARD_SOURCE_BOUND_NATIVE_SELECTED_OBSERVER_V4",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "omp_threads": 1,
        "family_id": v2.get("family_id", "F1"),
        "sentinel_id": v2.get("sentinel_id", "F1-S1+F1-S2"),
        "physical_case_id": "F1_NATIVE_HEADER_SELECTED_DIAGNOSTIC_V4_GUARDED_CHILD",
        "case_id": case_id,
        "attempt_id": attempt_id,
        "cwd": str(PRIMARY),
        "worktree_root": str(PRIMARY),
        "command": command,
        "input_files": input_files,
        "input_sha256": {path: records[path]["sha256"] for path in input_files},
        "input_records": records,
        "manifest": records[str(manifest_path)],
        "deferred_input_files": sorted(deferred),
        "deferred_input_records": deferred,
        "deferred_input_policy": {
            "runtime_v8_consumes_deferred_records": False,
            "child_wrapper_consumes_deferred_records_after_parent_reservation": True,
            "pre_sha_and_full_stat": ["bytes", "mtime_ns", "ctime_ns", "device", "inode"],
            "post_sha_and_full_stat": ["bytes", "mtime_ns", "ctime_ns", "device", "inode"],
            "exact_pre_post_source_identity_required": True,
            "unknown_sha_or_stat_change": "FAIL",
        },
        "native_read_accounting": {
            "selected_native_frame_count": len(deferred),
            "selected_native_source_bytes": deferred_bytes,
            "estimated_native_read_passes": NATIVE_PASSES,
            "estimated_native_read_bytes": native_bytes,
            "pass_semantics": [
                "wrapper_pre_sha256_and_full_stat",
                "official_decoder_input_read_inside_v1",
                "v1_worker_base_sha256_file_after_decode",
                "wrapper_post_sha256_and_full_stat",
            ],
            "v8_parent_deferred_hashing": False,
            "estimate_is_conservative_transfer_proxy_not_measured_device_io": True,
        },
        "estimated_native_read_bytes": native_bytes,
        "estimated_native_read_passes": NATIVE_PASSES,
        "estimated_input_read_bytes": native_bytes + sum(int(records[path]["bytes"]) for path in input_files),
        "estimated_input_read_bytes_scope": "four native source passes plus v8-hashed small closure",
        "estimated_hdf5_read_bytes": 0,
        "estimated_storage_bytes": 512 * 1024 * 1024,
        "estimated_scratch_bytes": SCRATCH_CAP,
        "estimated_peak_memory_bytes": MEMORY_CAP,
        "max_wall_seconds": 1800,
        "max_memory_bytes": MEMORY_CAP,
        "max_storage_bytes": 512 * 1024 * 1024,
        "output": {"path": output_path, "atomic": True, "refuse_overwrite": True},
        "wrapper": {
            "path": str(WRAPPER),
            "schema": "ds02.stage2.f1.native-selected-observer-guarded-wrapper.v4",
            "v1_worker_is_immutable": True,
            "temporary_v1_manifest_inside_attempt_root": True,
            "bounded_child_stdout_tail_bytes": 1024 * 1024,
            "scratch_cap_bytes": SCRATCH_CAP,
            "parent_death_and_signal_cleanup": True,
        },
        "source_binding": {
            "v2_request": str(v2_path),
            "v2_manifest": str(manifest_path),
            "v2_launch_status": str(STATUS_SIDECAR),
            "old_v2_bytes_immutable": True,
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "runtime_closure": {
            "literal_python": str(PYTHON),
            "literal_python_resolved_path": str(PYTHON.resolve()),
            "literal_python_parent_pre_entry_hash_required": True,
            "literal_python_is_not_rehashed_by_source_only_builder": True,
            "pyvenv_cfg": str(PYVENV),
            "runner": str(RUNNER),
            "runtime": str(RUNTIME),
            "strict_guard": str(STRICT_GUARD),
            "wrapper": str(WRAPPER),
            "v1_worker": str(V1_WORKER),
            "base_observer": str(BASE_OBSERVER),
            "all_small_source_paths_are_in_input_files": True,
            "literal_python_binary_is_parent_rechecked_separately": True,
        },
        "resource_guard": {
            "gpu": "none",
            "single_heavy_io_child": True,
            "parent_reservation_required": True,
            "deferred_source_guard_after_reservation": True,
            "source_replace_or_stat_change": "FAIL",
        },
        "launch_disabled": True,
        "execution_allowed": False,
        "solver_started": False,
        "native_payload_read": False,
        "hdf5_read": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "builder_source": str(BUILDER),
        "builder_source_sha256": records[str(BUILDER)]["sha256"],
        "preparation_scope": {
            "production_native_payload_read": False,
            "production_native_sha_computed": False,
            "deferred_native_stat_only": True,
            "new_source_bytes_read_by_builder": metadata_bytes,
        },
    }


def self_test() -> dict[str, Any]:
    # Deliberately no production paths or payload reads.  This test exercises
    # the schema boundary that prevented the V2 request from being launchable.
    records = []
    with tempfile.TemporaryDirectory(prefix="root204-v4-builder-") as directory:
        root = Path(directory)
        for frame in range(DEFERRED_COUNT):
            path = root / f"Part_{frame:04d}.bi4"
            path.write_bytes(f"fixture-{frame}".encode())
            records.append({"path": str(path), "bytes": path.stat().st_size, "mtime_ns": path.stat().st_mtime_ns, "sha256": "0" * 64})
        fixture_manifest = {"schema": MANIFEST_SCHEMA, "native_deferred_records": {record["path"]: record for record in records}}
        assert len(_deferred_from({"deferred_input_records": fixture_manifest["native_deferred_records"]}, fixture_manifest)) == DEFERRED_COUNT
        assert all(Path(path).suffix == ".bi4" for path in fixture_manifest["native_deferred_records"])
    return {
        "schema": VARIANT_SCHEMA,
        "status": "PASS",
        "deferred_records": DEFERRED_COUNT,
        "native_read_passes": NATIVE_PASSES,
        "v8_deferred_hashing": False,
        "production_payload_read": False,
        "solver_started": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--v2-request", type=Path)
    parser.add_argument("--output-request", type=Path)
    parser.add_argument("--case-id", default="F1_S1_S2_NATIVE_HEADER_SELECTED_ROOT204_V4")
    parser.add_argument("--attempt-id", default="f1-s1-s2-native-header-selected-root204-v4-primary-001")
    args = parser.parse_args()
    if args.self_test:
        result = self_test()
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.v2_request is None or args.output_request is None:
        parser.error("--v2-request and --output-request are required for --build")
    try:
        result = build(args.v2_request, output_request=args.output_request, case_id=args.case_id, attempt_id=args.attempt_id)
        _write_once(_path(args.output_request), result)
        print(json.dumps({"status": result["status"], "request": str(_path(args.output_request)), "deferred_records": len(result["deferred_input_records"]), "estimated_native_read_bytes": result["estimated_native_read_bytes"], "production_payload_read": False}, sort_keys=True))
    except Exception as exc:
        print(json.dumps({"status": "FAILED_V4_BUILD", "error": {"type": type(exc).__name__, "message": str(exc)}}, sort_keys=True))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
