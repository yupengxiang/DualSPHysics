#!/usr/bin/env python3
"""Prepare a bounded F2-S1 solver-ladder cost and output plan.

The plan is source-bound to the consumed v4 matrix output and uses only the
recorded Part_0000/RunPARTs/HDF5 stat evidence.  It estimates storage and wall
time for a fine spatial run and the original-dp same-CFL/half-CFL dense pair;
it never starts GenCase or the solver.  Dense output and observer-label density
are fixed before a solver request, and the coarse grid that failed the initial
sample-mass gate remains blocked.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Mapping


SCHEMA = "ds02.stage2.f2-s1.reference-ladder-plan.v1"
REQUEST_SCHEMA = "ds02.request.v1"
VENV_PYTHON = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
DEFAULT_MATRIX = DATA_ROOT / "families/F2/F2_S1_REFERENCE_MATRIX_V4/f2-s1-reference-matrix-v4-001/f2-s1-reference-matrix-v4.json"
HOME_PATH = Path("/home/jade")
GIB = 2**30
HOME_FLOOR_GIB = 500.0
STORAGE_CONTINGENCY = 0.20
TARGET_SAVE_INTERVAL_S = 0.001
TARGET_TIME_MAX_S = 4.0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refuse to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def require_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    return path


def file_record(path: Path) -> dict[str, Any]:
    require_file(path, "source")
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256_file(path)}


def repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists():
            return parent
    raise RuntimeError("repository root not found")


def git_commit() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root(), check=True, capture_output=True, text=True).stdout.strip()


def gibibytes(value: float) -> float:
    return value / GIB


def frame_count(time_max_s: float, save_interval_s: float) -> int:
    if time_max_s <= 0 or save_interval_s <= 0:
        raise ValueError("time max and save interval must be positive")
    return int(round(time_max_s / save_interval_s)) + 1


def storage_estimate(*, frame_bytes: int, frames: int, typed_hdf5_proxy_bytes: float | None = None) -> dict[str, Any]:
    raw_bytes = int(frame_bytes * frames)
    typed_bytes = int(round(typed_hdf5_proxy_bytes)) if typed_hdf5_proxy_bytes is not None else None
    known_bytes = raw_bytes + typed_bytes if typed_bytes is not None else raw_bytes
    reserved_bytes = int(math.ceil(known_bytes * (1.0 + STORAGE_CONTINGENCY)))
    return {
        "frame_bytes_basis": frame_bytes,
        "planned_frames": frames,
        "native_raw_proxy_bytes": raw_bytes,
        "native_raw_proxy_gib": gibibytes(raw_bytes),
        "typed_hdf5_proxy_bytes": typed_bytes,
        "typed_hdf5_proxy_gib": gibibytes(typed_bytes) if typed_bytes is not None else None,
        "known_proxy_bytes": known_bytes,
        "known_proxy_gib": gibibytes(known_bytes),
        "contingency_fraction": STORAGE_CONTINGENCY,
        "reserved_bytes": reserved_bytes,
        "reserved_gib": gibibytes(reserved_bytes),
        "basis_status": "PROXY_FROM_ACTUAL_PART_0000_AND_STAT_ONLY",
        "unknowns": [
            "per-frame Part bytes can vary with particle count and compression",
            "typed HDF5 proxy scales the existing 401-frame stat and is not a new HDF5 read",
            "PartVTK/observer sidecars are excluded until their pre-registered schema is supplied",
        ],
    }


def cost_estimate(*, baseline_wall_s: float, cfl_scale: float, frame_factor: float, cpu_threads: int = 2) -> dict[str, Any]:
    compute_lower_s = baseline_wall_s * cfl_scale
    planned_wall_upper_s = compute_lower_s * frame_factor
    return {
        "baseline_wall_seconds": baseline_wall_s,
        "cfl_compute_scale": cfl_scale,
        "frame_output_factor": frame_factor,
        "compute_only_lower_seconds": compute_lower_s,
        "planned_wall_upper_seconds": planned_wall_upper_s,
        "planned_wall_upper_hours": planned_wall_upper_s / 3600.0,
        "cpu_threads": cpu_threads,
        "planned_cpu_core_hours_upper": planned_wall_upper_s * cpu_threads / 3600.0,
        "basis_status": "MEASURED_BASELINE_PLUS_CONSERVATIVE_OUTPUT_FACTOR",
        "interpretation": "baseline SimRuntime is measured; CFL=.1 uses a 2x timestep-work scale and the 4001/401 output factor is a reservation upper bound, not a completed solver result",
    }


def resource_snapshot() -> dict[str, Any]:
    usage = shutil.disk_usage(HOME_PATH)
    floor_bytes = int(HOME_FLOOR_GIB * GIB)
    spare_bytes = max(0, usage.free - floor_bytes)
    return {
        "path": str(HOME_PATH),
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "free_gib": gibibytes(usage.free),
        "floor_gib": HOME_FLOOR_GIB,
        "spare_above_floor_bytes": spare_bytes,
        "spare_above_floor_gib": gibibytes(spare_bytes),
        "snapshot_basis": "shutil.disk_usage_at_plan_execution",
    }


def build_plan(matrix_path: Path) -> dict[str, Any]:
    matrix_path = require_file(matrix_path, "F2-S1 v4 matrix output")
    matrix = load_json(matrix_path)
    target = matrix["target"]
    target_frame = target["source"]["native_frame0"]
    frame_bytes = int(target_frame["bytes"])
    baseline_frames = int(target["window"]["report_frames"])
    baseline_runparts = target["source"]["runparts"]
    baseline_wall_s = float(baseline_runparts["last_row"]["SimRuntime [s]"])
    baseline_hdf5_bytes = int(target["continuous_initial_state"]["typed_hdf5"]["bytes"])
    baseline_time_max_s = float(target["window"]["nominal_time_max_s"])
    dense_frames = frame_count(TARGET_TIME_MAX_S, TARGET_SAVE_INTERVAL_S)
    dense_frame_factor = dense_frames / baseline_frames
    mass_cases = matrix.get("preflight_initial_fluid_sample_mass_gate", {}).get("cases", {})
    fine_mass = mass_cases.get("fine_dp008", {})
    coarse_mass = mass_cases.get("coarse_dp0125", {})
    fine_outputs = next((item.get("gencase_outputs", {}) for item in matrix.get("gap_requests", []) if item.get("resolution") == "fine_dp008"), {})
    fine_frame_record = fine_outputs.get("native_frame0", {})
    fine_frame_bytes = int(fine_frame_record.get("bytes", 0)) if fine_frame_record.get("bytes") else None

    baseline_storage = storage_estimate(frame_bytes=frame_bytes, frames=baseline_frames, typed_hdf5_proxy_bytes=baseline_hdf5_bytes)
    fine_storage = storage_estimate(frame_bytes=fine_frame_bytes, frames=baseline_frames) if fine_frame_bytes else {"status": "UNKNOWN"}
    dense_storage = storage_estimate(
        frame_bytes=frame_bytes,
        frames=dense_frames,
        typed_hdf5_proxy_bytes=baseline_hdf5_bytes * dense_frame_factor,
    )
    baseline_cost = cost_estimate(baseline_wall_s=baseline_wall_s, cfl_scale=1.0, frame_factor=1.0)
    dense_cfl020_cost = cost_estimate(baseline_wall_s=baseline_wall_s, cfl_scale=1.0, frame_factor=dense_frame_factor)
    dense_cfl010_cost = cost_estimate(baseline_wall_s=baseline_wall_s, cfl_scale=2.0, frame_factor=dense_frame_factor)

    dense_pair_reserved = 2 * dense_storage["reserved_bytes"]
    resources = resource_snapshot()
    remaining_after_pair = resources["spare_above_floor_bytes"] - dense_pair_reserved
    return {
        "schema": SCHEMA,
        "status": "PREPARED_NOT_SCHEDULED",
        "solver_started": False,
        "family_id": "F2",
        "sentinel_id": "F2-S1",
        "physical_case_id": matrix["target"]["physical_case_id"],
        "source": {
            "matrix_output": file_record(matrix_path),
            "matrix_schema": matrix.get("schema"),
            "source_archive": matrix.get("source_archive"),
            "target_native_frame0": target_frame,
            "target_runparts": baseline_runparts,
            "target_typed_hdf5_stat": target["continuous_initial_state"]["typed_hdf5"],
        },
        "measured_baseline": {
            "time_max_s": baseline_time_max_s,
            "save_interval_s": float(target["window"]["xml_save_interval_s"]),
            "frames": baseline_frames,
            "native_frame0_bytes": frame_bytes,
            "sim_runtime_seconds": baseline_wall_s,
            "sim_runtime_hours": baseline_wall_s / 3600.0,
            "storage_proxy": baseline_storage,
            "cost_proxy": baseline_cost,
        },
        "pre_registered_output_plan": {
            "rule": "freeze output cadence and observer label density before any solver launch; no result-driven widening or thinning",
            "baseline_reuse": {
                "status": "AVAILABLE_REUSE",
                "dp_m": 0.01,
                "cfl": 0.2,
                "save_interval_s": float(target["window"]["xml_save_interval_s"]),
                "frames": baseline_frames,
                "new_solver": False,
                "output": "reuse CURRENT336 native/typed artifacts and existing 401-row RunPARTs",
            },
            "fine_dp008_standard": {
                "status": "PREPARED_IF_PARENT_ACCEPTS",
                "dp_m": 0.008,
                "cfl": 0.2,
                "save_interval_s": 0.01,
                "frames": baseline_frames,
                "initial_mass_gate": fine_mass,
                "storage_proxy": fine_storage,
                "output": "retain 401 native frames; typed conversion and observer labels require separate guarded requests",
            },
            "native_dp010_dense_cfl020": {
                "status": "PRE_REGISTERED_SOLVER_INPUT_NOT_RUN",
                "dp_m": 0.01,
                "cfl": 0.2,
                "save_interval_s": TARGET_SAVE_INTERVAL_S,
                "frames": dense_frames,
                "storage_proxy": dense_storage,
                "cost_proxy": dense_cfl020_cost,
                "output": "retain all 4001 native frames and pre-registered dense observer labels",
            },
            "native_dp010_dense_cfl010": {
                "status": "PRE_REGISTERED_SOLVER_INPUT_NOT_RUN",
                "dp_m": 0.01,
                "cfl": 0.1,
                "save_interval_s": TARGET_SAVE_INTERVAL_S,
                "frames": dense_frames,
                "storage_proxy": dense_storage,
                "cost_proxy": dense_cfl010_cost,
                "output": "retain all 4001 native frames and the same observer label timestamps for the half-CFL comparison",
            },
            "coarse_dp0125_existing": {
                "status": "BLOCKED_FAIL_HARD_INITIAL_MASS_GATE",
                "initial_mass_gate": coarse_mass,
                "output": "retain failed GenCase evidence; do not schedule solver; replacement phase/count preflight is required",
            },
        },
        "observer_label_plan": {
            "status": "PRE_REGISTERED_NOT_RUN",
            "timestamps": {"start_s": 0.0, "end_s": TARGET_TIME_MAX_S, "interval_s": TARGET_SAVE_INTERVAL_S, "count": dense_frames},
            "fields": ["time", "position_event_features", "velocity_or_ke_at_nonzero_scale", "region_sample_mass", "event_time"],
            "calibration_owner": "consumer independent manufacturing/parser task",
            "rationale": "0.001 s dense cadence is the already declared 10x refinement of .01 s and gives fixed timestamps for the 1% event-time gate; labels are not admitted until consumer calibration freezes tolerances",
        },
        "resource_reservation": {
            "snapshot": resources,
            "dense_pair_reserved_bytes": dense_pair_reserved,
            "dense_pair_reserved_gib": gibibytes(dense_pair_reserved),
            "remaining_spare_above_floor_after_pair_bytes": remaining_after_pair,
            "remaining_spare_above_floor_after_pair_gib": gibibytes(remaining_after_pair),
            "decision": "PARENT_GLOBAL_RESOURCE_REVIEW_REQUIRED_BEFORE_SOLVER_LAUNCH",
            "gpu": "none",
            "gpu6_protected": True,
            "home_floor_respected": remaining_after_pair >= 0,
            "other_families_must_be_budgeted_separately": True,
        },
        "scope": {
            "reads": "v4 matrix JSON plus its recorded small-file stats; no HDF5 dataset read and no full HDF5 rehash",
            "full_time_scan": False,
            "full_hdf5_rehash": False,
            "solver_started": False,
            "QI_QN_QE": "NOT_ASSESSED",
        },
    }


def request_for(matrix_path: Path, output_path: Path) -> dict[str, Any]:
    root = repo_root()
    script = Path(__file__).resolve()
    matrix_path = require_file(matrix_path, "F2-S1 v4 matrix output")
    inputs = [
        root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch.py",
        root / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py",
        root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py",
        script,
        matrix_path,
    ]
    inputs = [path.resolve() for path in inputs]
    request = {
        "schema": REQUEST_SCHEMA,
        "family_id": "F2",
        "case_id": "F2_S1_REFERENCE_LADDER_PLAN_V1",
        "attempt_id": "f2-s1-reference-ladder-plan-v1-001",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 2,
        "max_wall_seconds": 300,
        "estimated_storage_bytes": 8 * 1024 * 1024,
        "worktree_root": str(root),
        "cwd": str(root),
        "command": [
            VENV_PYTHON,
            str(script),
            "--run",
            "--matrix", str(matrix_path.resolve()),
            "--output", "{attempt_root}/f2-s1-reference-ladder-plan-v1.json",
        ],
        "input_files": [str(path) for path in inputs],
        "input_hashes": {str(path): sha256_file(path) for path in inputs},
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": "ds_data02_stage2_dispatch.py",
            "strict_guard": "ds_data02_strict_dispatch_v1.py",
            "runtime": "ds_data02_runtime_v2.py",
            "launch_commit": git_commit(),
            "cpu_parent_binding": "required",
            "gpu": "none",
            "estimated_cpu_core_hours": 2 * 300 / 3600,
            "estimated_new_storage_bytes": 8 * 1024 * 1024,
            "solver_launch": "forbidden",
        },
        "scope": {
            "matrix_plan_only": True,
            "solver_started": False,
            "full_time_hdf5_read": False,
            "full_hdf5_hash": "forbidden_by_scope",
        },
    }
    atomic_json(output_path, request)
    return request


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit-request", type=Path)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.emit_request is not None:
        request = request_for(args.matrix, args.emit_request)
        print(json.dumps({"status": "PASS", "request": str(args.emit_request), "inputs": len(request["input_files"])}, ensure_ascii=False), flush=True)
        return 0
    if not args.run or args.output is None:
        raise SystemExit("choose --emit-request or --run with --output")
    value = build_plan(args.matrix)
    atomic_json(args.output, value)
    print(json.dumps({"status": "PASS", "output": str(args.output)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
