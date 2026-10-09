#!/usr/bin/env python3
"""V8-shaped ROOT229 request builder.

ROOT229's original builder/worker already avoids the calibrated observer's
world-axis gate by using component-space helpers directly.  This additive
builder preserves that manifest and worker, then supplies the top-level
``kind=cpu``/runtime/read-accounting fields needed by the parent V8 guard.
The three native frame-0 files remain deferred and are never opened here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

import stage2_f1_s2_initial_support_request_v1 as legacy


HERE = Path(__file__).resolve().parent
BUILDER = HERE / "stage2_f1_s2_initial_support_request_v2.py"
ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYTHON_TARGET = Path("/usr/bin/python3.10")
PYVENV_CFG = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/pyvenv.cfg")
MAX_NATIVE_BYTES = 512 * 1024 * 1024
NATIVE_READ_PASSES = 4
REQUEST_SCHEMA = "ds02.request.v1"
VARIANT_SCHEMA = "ds02.stage2.f1-s2.initial-support-request.v2"


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
    before_sig = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    after_sig = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    if before_sig != after_sig:
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


def build(output_manifest: Path, output_request: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    output_manifest = output_manifest.expanduser().absolute()
    output_request = output_request.expanduser().absolute()
    # Let the consumed V1 builder construct the exact ROOT227/207/217 joins
    # and deferred Part paths.  Only the new request envelope is changed.
    with tempfile.TemporaryDirectory(prefix="root229-v2-request-") as temporary:
        temp_request = Path(temporary) / "legacy-request.json"
        manifest, _ = legacy.build(output_manifest, temp_request)
        request = json.loads(temp_request.read_text(encoding="utf-8"))
    if manifest.get("status") != "PREPARED_NOT_RUN_ROOT229_INITIAL_SUPPORT_SOURCE_AUDIT":
        raise BuildError("ROOT229 V1 manifest status unexpectedly changed")
    deferred = manifest.get("deferred_native_records")
    if not isinstance(deferred, list) or len(deferred) != 3:
        raise BuildError("ROOT229 V2 requires exactly three deferred frame-0 Part records")
    static_records = [item for item in manifest.get("static_source_records", []) if isinstance(item, dict)]
    manifest_record = stable_hash(output_manifest, "ROOT229 V2 manifest")
    builder_record = stable_hash(BUILDER, "ROOT229 V2 request builder")
    records: dict[str, dict[str, Any]] = {str(item["path"]): item for item in static_records if isinstance(item.get("path"), str)}
    records[manifest_record["path"]] = manifest_record
    records[builder_record["path"]] = builder_record
    # The V1 manifest already contains the calibrated worker/base source
    # records.  Keep their paths and hashes; adding this builder is the only
    # new source closure edge.
    worker_path = str((HERE / "stage2_f1_s2_initial_support_observer_v1.py").resolve())
    if worker_path not in records:
        records[worker_path] = stable_hash(Path(worker_path), "ROOT229 observer worker")
    native_read_bytes = len(deferred) * MAX_NATIVE_BYTES * NATIVE_READ_PASSES
    static_bytes = sum(int(item.get("bytes", 0)) for item in records.values())
    request.update({
        "schema": REQUEST_SCHEMA,
        "variant_schema": VARIANT_SCHEMA,
        "status": "READY_FOR_PARENT_V8_F1_S2_INITIAL_SUPPORT",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "request_id": "f1-s2-initial-support-audit-root229-v2-001",
        "case_id": "F1_S2_INITIAL_SUPPORT_AUDIT_ROOT229_V2",
        "attempt_id": "f1-s2-initial-support-audit-root229-v2-001",
        "cwd": str(ROOT),
        "worktree_root": str(ROOT),
        "command": [str(PYTHON), "-B", worker_path, "--manifest", "{attempt_root}/inputs/f1_s2_initial_support_manifest_v1.json", "--attempt-root", "{attempt_root}", "--output", "{attempt_root}/observer/f1_s2_initial_support_observer_v1.json"],
        "literal_venv_invocation": {"path": str(PYTHON), "argv0_literal": True, "resolved_target": str(PYTHON_TARGET), "pyvenv_cfg": str(PYVENV_CFG)},
        "input_files": sorted(records),
        "input_sha256": {path: item["sha256"] for path, item in records.items()},
        "input_records": records,
        "manifest": manifest_record,
        "deferred_input_files": sorted(item["path"] for item in deferred),
        "deferred_input_records": deferred,
        "deferred_input_policy": {"parent_after_reservation_first_sha_and_stat": True, "parent_after_child_post_sha_and_stat": True, "required_stat_fields": ["bytes", "mtime_ns", "ctime_ns", "dev", "ino"], "producer_known_sha_is_not_builder_computed": True, "source_replace_or_stat_change": "FAIL", "selected_frame_count": 3},
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
        "estimated_input_read_bytes_scope": "static metadata plus three deferred Part files at the 512 MiB cap and four worker/decoder passes; actual bytes remain parent-measured",
        "estimated_hdf5_read_bytes": 0,
        "runtime_closure": {"literal_python": {"path": str(PYTHON), "resolved_target": str(PYTHON_TARGET), "pyvenv_cfg": str(PYVENV_CFG)}, "worker": worker_path, "calibrated_observer": str((HERE / "stage2_f1_native_selected_observer_v1.py").resolve()), "base_observer": str((HERE / "stage2_native_physical_observer_v2.py").resolve()), "parent_v8_deferred_sha_stat_gate": True},
        "storage_scope": {"output_root": "{attempt_root}", "native_payload_read": "three deferred frame-0 Part_0000.bi4 files only", "h5_vtk_allowed": False, "full_native_tree_scan": False, "solver_launch": False},
        "source_binding": {**request.get("source_binding", {}), "axis_scope": "component-space support only; producer world-axis remains UNKNOWN", "native_mass_is_separate_from_continuous_owner": True, "position_support_tolerance_is_not_task_error": True},
        "resources": {"gpu": False, "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 1800, "memory_max_bytes": 2 * 1024**3, "external_storage_max_bytes": 512 * 1024**2, "home_storage_max_bytes": 128 * 1024**2, "log_max_bytes": 512 * 1024, "parent_guard_required": True},
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
    assert MAX_NATIVE_BYTES * NATIVE_READ_PASSES * 3 > 0
    assert VARIANT_SCHEMA.endswith(".v2")
    print("PASS_F1_S2_INITIAL_SUPPORT_REQUEST_V2_SELFTEST")


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
        print(f"FAIL_F1_S2_INITIAL_SUPPORT_REQUEST_V2: {exc}")
        return 2
    print(f"PASS_PREPARED_F1_S2_INITIAL_SUPPORT_V2 {args.output_manifest} {args.output_request}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
