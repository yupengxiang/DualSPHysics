#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build a bounded JSON-only F5 Y-phase comparison request."""

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
WORKER = HERE / "stage2_f5_s1_yphase_shape_compare_v1.py"
SCHEMA = "ds02.request.v1"
VARIANT = "ds02.stage2.f5-s1.yphase-shape-compare.v1-request"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")


def load_worker():
    spec = importlib.util.spec_from_file_location("stage2_f5_yphase_compare_worker_for_request", WORKER)
    if spec is None or spec.loader is None:
        raise ImportError(WORKER)
    module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module; spec.loader.exec_module(module); return module


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
    path = regular(path, label); stat = path.stat()
    return {"path": str(path), "label": label, "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "ctime_ns": int(stat.st_ctime_ns), "st_dev": int(stat.st_dev), "st_ino": int(stat.st_ino), "sha256": sha256(path), "content_scope": "JSON-only-input-hashed-by-builder-and-parent-v8"}


def build(args: argparse.Namespace) -> dict[str, Any]:
    worker = regular(WORKER, "F5 Y-phase compare worker")
    python = regular(PYTHON, "stage2 venv interpreter")
    paths = {
        "baseline_request": regular(args.baseline_request, "baseline request"),
        "baseline_report": regular(args.baseline_report, "baseline report"),
        "candidate_request": regular(args.candidate_request, "candidate request"),
        "candidate_report": regular(args.candidate_report, "candidate report"),
    }
    # Validate identity with the worker's same small-JSON code before emitting
    # a parent request.  This does not touch XML, VTK, BI4, or HDF5 payloads.
    worker_mod = load_worker()
    for key in ("baseline_request", "candidate_request"):
        data = worker_mod.load_json(paths[key], key)
        worker_mod._require_identity(data, key)
    for key in ("baseline_report", "candidate_report"):
        data = worker_mod.load_json(paths[key], key)
        worker_mod._require_identity(data, key)
    records = {str(worker): record(worker, "F5 JSON-only shape comparison worker"), str(python): record(python, "stage2 venv interpreter")}
    records.update({str(path): record(path, f"F5 JSON-only {key}") for key, path in paths.items()})
    input_files = sorted(records)
    command = [str(python), str(worker), "--run", "--baseline-request", str(paths["baseline_request"]), "--baseline-report", str(paths["baseline_report"]), "--candidate-request", str(paths["candidate_request"]), "--candidate-report", str(paths["candidate_report"]), "--output", "{attempt_root}/report/stage2_f5_s1_yphase_shape_compare_v1.json"]
    payload: dict[str, Any] = {
        "schema": SCHEMA, "kind": "cpu", "cpu_task_kind": "audit", "family_id": "F5", "sentinel_id": "F5-S1", "physical_case_id": "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090",
        "case_id": args.case_id, "attempt_id": args.attempt_id, "launch_commit": args.launch_commit,
        "command": command, "cwd": str(HERE.parent.parent.parent), "worktree_root": str(HERE.parent.parent.parent.parent.parent),
        "input_files": input_files, "input_hashes": {path: records[path]["sha256"] for path in input_files}, "input_records": records,
        "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 600, "max_memory_bytes": 2 * 1024**3, "estimated_storage_bytes": 16 * 1024**2, "estimated_peak_memory_bytes": 256 * 1024**2,
        "estimated_input_read_bytes": sum(item["bytes"] for item in records.values()), "estimated_native_read_bytes": 0, "estimated_bi4_read_bytes": 0, "estimated_hdf5_read_bytes": 0,
        "execution_allowed": True, "launch_disabled": False, "solver_started": False, "gencase_launch": False, "solver_launch": False, "hdf5_read": False, "bi4_read": False,
        "output_root": "{attempt_root}", "output": {"atomic": True, "refuse_overwrite": True, "path": "{attempt_root}/report/stage2_f5_s1_yphase_shape_compare_v1.json"},
        "source_binding": {"schema": VARIANT, "baseline_and_candidate_reports_only": True, "payload_arrays_read": False, "vtk_read": False, "bi4_read": False, "hdf5_read": False, "required_scopes": ["fluid", "fixed_boundary", "moving_boundary", "forcing", "shape_operations"], "neighbor_grid_is_not_truth": True},
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": "parent-v8-audit", "cpu_parent_binding": "required", "solver_launch": "forbidden", "payload_read": "JSON-only"},
        "qualification_stage": "stage2_f5_s1_yphase_shape_diagnostic_v1_pending_parent_guard", "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "JSON-only report fields; no all-shape, temporal, output, or neighbor-truth qualification"},
        "status": "READY_FOR_PARENT_V8_F5_Y_PHASE_JSON_ONLY_COMPARE",
    }
    payload["sha256"] = hashlib.sha256(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return payload


def write_new(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse to overwrite immutable request: {path}")
    path.parent.mkdir(parents=True, exist_ok=True); temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1; handle.write((json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()); handle.flush(); os.fsync(handle.fileno())
    finally:
        if fd >= 0: os.close(fd)
    os.replace(temporary, path)


def self_test() -> dict[str, Any]:
    result = load_worker().self_test()
    if result.get("status") != "PASS": raise AssertionError(result)
    return {"status": "PASS", "schema": SCHEMA, "request_variant_schema": VARIANT, "payload_arrays_read": False, "solver_started": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); mode = parser.add_mutually_exclusive_group(required=True); mode.add_argument("--self-test", action="store_true"); mode.add_argument("--build-request", action="store_true")
    parser.add_argument("--baseline-request", type=Path); parser.add_argument("--baseline-report", type=Path); parser.add_argument("--candidate-request", type=Path); parser.add_argument("--candidate-report", type=Path); parser.add_argument("--output", type=Path); parser.add_argument("--case-id", default="F5_S1_Y_PHASE_SHAPE_COMPARE_ROOT"); parser.add_argument("--attempt-id", default="f5-s1-y-phase-shape-compare-v1-root-001"); parser.add_argument("--launch-commit", required=False)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    if any(value is None for value in (args.baseline_request, args.baseline_report, args.candidate_request, args.candidate_report, args.output, args.launch_commit)):
        parser.error("--build-request requires four JSON inputs, output and launch commit")
    payload = build(args); write_new(args.output, payload); print(json.dumps({"status": payload["status"], "schema": SCHEMA, "output": str(args.output.resolve())}, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
