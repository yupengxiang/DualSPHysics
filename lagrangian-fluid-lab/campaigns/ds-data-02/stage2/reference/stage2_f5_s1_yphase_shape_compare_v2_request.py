#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build the ROOT135 source-bound F5 three-source JSON-only request."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
WORKER = HERE / "stage2_f5_s1_yphase_shape_compare_v2.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
REQUEST_SCHEMA = "ds02.request.v1"
VARIANT_SCHEMA = "ds02.stage2.f5-s1.yphase-shape-compare.v2-request"
PHYSICAL_CASE_ID = "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090"


def load_worker():
    spec = importlib.util.spec_from_file_location("stage2_f5_yphase_compare_v2_worker_for_request", WORKER)
    if spec is None or spec.loader is None:
        raise ImportError(WORKER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    stat = path.stat()
    return {
        "path": str(path),
        "label": label,
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": sha256(path),
        "content_scope": "small_json_only_hashed_by_builder_and_parent_v8",
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    worker = regular(WORKER, "F5 V2 JSON-only compare worker")
    python = regular(PYTHON, "literal stage2 venv interpreter")
    paths = {
        "q117_request": regular(args.q117_request, "q117 request"),
        "q117_report": regular(args.q117_report, "q117 geometry report"),
        "q117_proof": regular(args.q117_proof, "q117 verification proof"),
        "q124_request": regular(args.q124_request, "q124 request"),
        "q124_report": regular(args.q124_report, "q124 geometry report"),
        "q124_proof": regular(args.q124_proof, "q124 verification proof"),
        "q123_request": regular(args.q123_request, "q123 request"),
        "q123_proof": regular(args.q123_proof, "q123 hard-fail proof"),
    }

    # Validate all small JSON identity/proof joins before emitting the parent
    # request.  The worker performs the same checks again after reservation.
    worker_mod = load_worker()
    worker_mod._report(paths["q117_request"], paths["q117_report"], paths["q117_proof"], "q117_yhalf_dp005", "VERIFIED_ACTUAL_F5_YHALF_GEOMETRY")
    worker_mod._report(paths["q124_request"], paths["q124_report"], paths["q124_proof"], "q124_yzero_dp005", "VERIFIED_ACTUAL_F5_YZERO_V10")
    q123 = worker_mod.load_json(paths["q123_request"], "q123 request")
    worker_mod._identity(q123, "q123 request")
    worker_mod._proof_binding(paths["q123_proof"], paths["q123_request"], None, "q123_yzero_dp005", "VERIFIED_ACTUAL_F5_YZERO_INITIAL_MASS_HARDFAIL")

    records: dict[str, dict[str, Any]] = {
        str(worker): record(worker, "F5 V2 JSON-only tri-source worker"),
        str(python): record(python, "literal stage2 venv interpreter"),
    }
    records.update({str(path): record(path, f"F5 tri-source {key}") for key, path in paths.items()})
    input_files = sorted(records)
    output = "{attempt_root}/report/stage2_f5_s1_yphase_shape_compare_v2.json"
    command = [
        str(python), str(worker), "--run",
        "--baseline-request", str(paths["q117_request"]), "--baseline-report", str(paths["q117_report"]), "--baseline-proof", str(paths["q117_proof"]),
        "--candidate-request", str(paths["q124_request"]), "--candidate-report", str(paths["q124_report"]), "--candidate-proof", str(paths["q124_proof"]),
        "--third-request", str(paths["q123_request"]), "--third-proof", str(paths["q123_proof"]),
        "--output", output,
    ]
    payload: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": "F5",
        "sentinel_id": "F5-S1",
        "physical_case_id": PHYSICAL_CASE_ID,
        "case_id": args.case_id,
        "attempt_id": args.attempt_id,
        "launch_commit": args.launch_commit,
        "request_variant_schema": VARIANT_SCHEMA,
        "command": command,
        "cwd": str(HERE.parent.parent.parent),
        "worktree_root": str(HERE.parent.parent.parent.parent.parent),
        "input_files": input_files,
        "input_hashes": {path: records[path]["sha256"] for path in input_files},
        "input_records": records,
        "parent_v8_input_closure": {
            "small_json_input_sha256_complete": True,
            "deferred_input_files_used": False,
            "payload_arrays_read": False,
            "vtk_bi4_hdf5_read": False,
            "proof_request_report_sha_joins_rechecked_by_worker": True,
        },
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 600,
        "max_memory_bytes": 2 * 1024**3,
        "estimated_storage_bytes": 16 * 1024**2,
        "estimated_peak_memory_bytes": 256 * 1024**2,
        "estimated_input_read_bytes": sum(item["bytes"] for item in records.values()),
        "estimated_native_read_bytes": 0,
        "estimated_bi4_read_bytes": 0,
        "estimated_hdf5_read_bytes": 0,
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "gencase_launch": False,
        "solver_launch": False,
        "hdf5_read": False,
        "bi4_read": False,
        "output_root": "{attempt_root}",
        "output": {"atomic": True, "refuse_overwrite": True, "path": output},
        "source_binding": {
            "schema": VARIANT_SCHEMA,
            "q117_q124_geometry_reports_and_q123_proof_only": True,
            "q124_proof_bound": str(paths["q124_proof"]),
            "q123_hardfail_anchor_preserved": True,
            "payload_arrays_read": False,
            "vtk_read": False,
            "bi4_read": False,
            "hdf5_read": False,
            "neighbor_grid_is_not_truth": True,
            "all_shapes_comparison_deferred": True,
        },
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": "parent-v8-audit",
            "cpu_parent_binding": "required",
            "solver_launch": "forbidden",
            "payload_read": "small JSON only",
        },
        "qualification_stage": "stage2_f5_s1_yphase_tri_source_shape_diagnostic_v2_pending_parent_guard",
        "scientific_qualification": {
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "reason": "q117/q124 report fields and q123 hard-fail proof are source-bound JSON diagnostics; all-shape, temporal, output and neighbor-truth qualification remain unknown",
        },
        "status": "READY_FOR_PARENT_V8_F5_TRI_SOURCE_JSON_ONLY_COMPARE",
    }
    payload["sha256"] = hashlib.sha256(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return payload


def write_new(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write((json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)
    os.replace(temporary, path)


def self_test() -> dict[str, Any]:
    result = load_worker().self_test()
    if result.get("status") != "PASS":
        raise AssertionError(result)
    return {"status": "PASS", "schema": REQUEST_SCHEMA, "request_variant_schema": VARIANT_SCHEMA, "proofs_bound": 3, "payload_arrays_read": False, "solver_started": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build-request", action="store_true")
    for name in ("q117-request", "q117-report", "q117-proof", "q124-request", "q124-report", "q124-proof", "q123-request", "q123-proof", "output"):
        parser.add_argument(f"--{name}", type=Path)
    parser.add_argument("--case-id", default="F5_S1_Y_PHASE_TRI_SOURCE_SHAPE_COMPARE_ROOT135")
    parser.add_argument("--attempt-id", default="f5-s1-y-phase-tri-source-shape-compare-v2-root135-001")
    parser.add_argument("--launch-commit", required=False)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    required = [args.q117_request, args.q117_report, args.q117_proof, args.q124_request, args.q124_report, args.q124_proof, args.q123_request, args.q123_proof, args.output, args.launch_commit]
    if any(value is None for value in required):
        parser.error("--build-request requires q117/q124 request+report+proof, q123 request+proof, output and launch commit")
    payload = build(args)
    write_new(args.output, payload)
    print(json.dumps({"status": payload["status"], "schema": REQUEST_SCHEMA, "request_variant_schema": VARIANT_SCHEMA, "output": str(args.output.resolve()), "solver_started": False, "payload_arrays_read": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
