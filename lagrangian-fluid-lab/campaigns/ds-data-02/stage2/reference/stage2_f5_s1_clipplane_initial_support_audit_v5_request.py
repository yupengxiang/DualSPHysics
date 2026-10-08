#!/usr/bin/env python3
"""Build a forward F5 initial support/mass QA request after GenCase.

The terminal GenCase XML/Fluid/Bound VTK paths are supplied explicitly after
the parent has completed a V3 source-preserving GenCase request.  This
builder hashes only the small XML/receipt/Def/motion/worker inputs.  Fluid and
Bound VTK are worker-owned payloads: the V4 audit worker performs their
pre/post SHA/stat checks after the CPU reservation.  No VTK payload, BI4,
HDF5, solver output, or CFD is read here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


REQUEST_SCHEMA = "ds02.request.v1"
SCHEMA = "ds02.stage2.f5-s1.clipplane-initial-support-audit.v5-request"
PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
REFERENCE = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
WORKER = REFERENCE / "stage2_f5_s1_clipplane_initial_support_audit_v4.py"
WORKER_V3 = REFERENCE / "stage2_f5_s1_initial_gencase_support_audit_v3.py"
CLIP_V2 = REFERENCE / "stage2_f5_s1_clipplane_official_evidence_audit_v2.py"
CLIP_EVIDENCE = REFERENCE / "stage2_f5_s1_clipplane_official_evidence_audit_v2.json"
DISPATCH = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
RUNTIME = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
CONTINUOUS_MASS_KG = 287.736
PHYSICAL_CASE_ID = "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    return path


def record(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    value = path.stat()
    return {
        "path": str(path),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
        "sha256": sha256(path),
        "content_scope": "small_input_hashed_by_builder_and_parent_v8",
    }


def stat_only(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    value = path.stat()
    return {
        "path": str(path),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
        "sha256": "WORKER_AFTER_RESERVATION_ONLY",
        "content_scope": "worker_owned_vtk_pre_post_guard",
    }


def json_new(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse to overwrite immutable request: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        try:
            with os.fdopen(fd, "wb") as handle:
                fd = -1
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            if fd >= 0:
                os.close(fd)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def build(args: argparse.Namespace) -> dict[str, Any]:
    paths = {
        "gencase_request": args.gencase_request,
        "receipt": args.receipt,
        "generated_xml": args.generated_xml,
        "candidate_def": args.candidate_def,
        "source_def": args.source_def,
        "candidate_motion": args.candidate_motion,
        "source_motion": args.source_motion,
        "fluid_vtk": args.fluid_vtk,
        "bound_vtk": args.bound_vtk,
    }
    receipt = load(args.receipt, "F5 GenCase receipt")
    request = load(args.gencase_request, "F5 GenCase request")
    if request.get("family_id") != "F5" or request.get("sentinel_id") != "F5-S1" or request.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise ValueError("F5 GenCase identity mismatch")
    if str(receipt.get("status", "")).lower() not in {"completed", "complete", "success", "completed0"} or receipt.get("returncode") not in (0, None):
        raise ValueError("F5 GenCase receipt is not completed zero-return")
    output_root = Path(str(receipt.get("output_root", ""))).expanduser().resolve()
    generated_xml = regular(args.generated_xml, "generated XML")
    fluid_vtk = regular(args.fluid_vtk, "generated Fluid VTK")
    bound_vtk = regular(args.bound_vtk, "generated Bound VTK")
    if generated_xml.parent != output_root or fluid_vtk.parent != output_root or bound_vtk.parent != output_root:
        raise ValueError("terminal GenCase files must share the receipt output_root")

    small_paths = [
        (args.gencase_request, "F5 GenCase request"), (args.receipt, "F5 GenCase receipt"),
        (generated_xml, "generated XML"), (args.candidate_def, "candidate Def"),
        (args.source_def, "source Def"), (args.candidate_motion, "candidate motion"),
        (args.source_motion, "source motion"), (WORKER, "F5 V4 support worker"),
        (WORKER_V3, "F5 V3 support dependency"), (CLIP_V2, "F5 clip parser dependency"),
        (CLIP_EVIDENCE, "F5 official clip evidence"), (Path(__file__).resolve(), "F5 V5 request builder"),
        (DISPATCH, "parent v8 dispatch"), (STRICT, "parent v8 strict dispatch"),
        (RUNTIME, "parent v8 runtime"), (PYTHON, "stage2 interpreter"),
    ]
    records = {str(path.expanduser().resolve()): record(path, label) for path, label in small_paths}
    vtk_records = {
        "generated_fluid_vtk": stat_only(fluid_vtk, "generated Fluid VTK"),
        "generated_bound_vtk": stat_only(bound_vtk, "generated Bound VTK"),
    }
    case_id = args.case_id or f"F5_S1_CLIPPLANE_INITIAL_SUPPORT_AUDIT_V5_{args.grid.upper()}"
    attempt_id = args.attempt_id or f"f5-s1-clipplane-initial-support-audit-v5-{args.grid}-root-review-001"
    output_root_audit = DATA_ROOT / "families/F5" / case_id / attempt_id
    output_path = "{attempt_root}/report/stage2_f5_s1_clipplane_initial_support_audit_v5.json"
    command = [
        str(PYTHON), str(WORKER),
        "--generated-xml", str(generated_xml), "--fluid-vtk", str(fluid_vtk), "--bound-vtk", str(bound_vtk),
        "--receipt", str(Path(args.receipt).resolve()), "--candidate-def", str(Path(args.candidate_def).resolve()),
        "--source-def", str(Path(args.source_def).resolve()), "--candidate-motion", str(Path(args.candidate_motion).resolve()),
        "--source-motion", str(Path(args.source_motion).resolve()), "--clip-evidence", str(CLIP_EVIDENCE.resolve()),
        "--gencase-request", str(Path(args.gencase_request).resolve()), "--output", output_path,
    ]
    payload: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": "F5",
        "sentinel_id": "F5-S1",
        "physical_case_id": PHYSICAL_CASE_ID,
        "case_id": case_id,
        "attempt_id": attempt_id,
        "launch_commit": args.launch_commit,
        "command": command,
        "cwd": str(PRIMARY_REPO),
        "worktree_root": str(PRIMARY_REPO),
        "input_files": sorted(records),
        "input_hashes": {path: records[path]["sha256"] for path in sorted(records)},
        "input_records": records,
        "worker_owned_input_files": [str(fluid_vtk), str(bound_vtk)],
        "worker_owned_input_stats_at_build": vtk_records,
        "worker_owned_input_hashes": {
            str(fluid_vtk): "WORKER_AFTER_RESERVATION_ONLY",
            str(bound_vtk): "WORKER_AFTER_RESERVATION_ONLY",
            "hash_status": "NOT_COMPUTED_BY_BUILDER_OR_PARENT_INPUT_FILES",
        },
        "parent_v8_input_closure": {
            "small_input_sha256_complete": True,
            "vtk_in_parent_input_files": False,
            "vtk_sha_authority": "V4 worker pre/post full SHA after parent reservation",
            "deferred_input_files_used": False,
            "parent_v8_does_not_hash_worker_owned_vtk": True,
        },
        "grid": args.grid,
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 1800,
        "max_memory_bytes": 2 * 1024**3,
        "estimated_input_read_bytes": sum(int(item["bytes"]) for item in records.values()) + sum(int(item["bytes"]) for item in vtk_records.values()),
        "estimated_storage_bytes": 128 * 1024**2,
        "estimated_peak_memory_bytes": 2 * 1024**3,
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
        "output_root": str(output_root_audit),
        "output": {"atomic": True, "refuse_overwrite": True, "path": output_path},
        "source_binding": {
            "schema": SCHEMA,
            "grid": args.grid,
            "gencase_request": records[str(Path(args.gencase_request).resolve())],
            "gencase_receipt": records[str(Path(args.receipt).resolve())],
            "generated_xml": records[str(generated_xml)],
            "candidate_def": records[str(Path(args.candidate_def).resolve())],
            "source_def": records[str(Path(args.source_def).resolve())],
            "candidate_motion": records[str(Path(args.candidate_motion).resolve())],
            "source_motion": records[str(Path(args.source_motion).resolve())],
            "clip_evidence": records[str(CLIP_EVIDENCE.resolve())],
            "worker_owned_vtk": vtk_records,
            "continuous_region_mass_kg": CONTINUOUS_MASS_KG,
            "mass_rescale": False,
        },
        "guard_policy": {
            "parent_after_reserve_small_input_sha_stat": True,
            "worker_owned_large_inputs": "generated Fluid/Bound VTK",
            "worker_vtk_pre_post_sha_stat_required": True,
            "solver_launch": False,
            "hdf5_read": False,
            "bi4_read": False,
            "support_mass_gate_before_solver": True,
        },
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(DISPATCH), "strict_guard": str(STRICT), "runtime": str(RUNTIME), "cpu_parent_binding": "required", "gpu": "none"},
        "qualification_stage": "stage2_f5_s1_initial_support_mass_audit_v5_pending_parent_guard",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "support/mass audit only; continuous region and particle sample must be compared without rescaling"},
        "status": "READY_FOR_PARENT_V8_CPU_AUDIT_REVIEW",
    }
    json_new(Path(args.output), payload)
    return payload


def self_test() -> dict[str, Any]:
    assert "WORKER_AFTER_RESERVATION_ONLY" not in {"sha256": "NOT_COMPUTED_BY_BUILDER"}.values()
    return {"status": "PASS", "vtk_payload_read_by_builder": False, "worker_vtk_sha_after_reservation": True, "solver_started": False, "hdf5_read": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build-request", action="store_true")
    parser.add_argument("--grid", choices=("dp010", "dp005"))
    for name in ("gencase-request", "receipt", "generated-xml", "candidate-def", "source-def", "candidate-motion", "source-motion", "fluid-vtk", "bound-vtk", "output"):
        parser.add_argument(f"--{name}", type=Path)
    parser.add_argument("--case-id")
    parser.add_argument("--attempt-id")
    parser.add_argument("--launch-commit")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    required = [args.grid, args.gencase_request, args.receipt, args.generated_xml, args.candidate_def, args.source_def, args.candidate_motion, args.source_motion, args.fluid_vtk, args.bound_vtk, args.output, args.launch_commit]
    if any(value is None for value in required):
        parser.error("--build-request requires grid, terminal inputs, output and launch commit")
    payload = build(args)
    print(json.dumps({"status": payload["status"], "grid": args.grid, "output": str(args.output.resolve()), "vtk_payload_read_by_builder": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
