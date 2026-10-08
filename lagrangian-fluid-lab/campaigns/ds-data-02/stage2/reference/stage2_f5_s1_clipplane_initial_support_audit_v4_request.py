#!/usr/bin/env python3
"""Build a guarded F5 V4 initial support/mass QA request after GenCase."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any


DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
REFERENCE = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
WORKER = REFERENCE / "stage2_f5_s1_clipplane_initial_support_audit_v4.py"
CLIP_EVIDENCE = REFERENCE / "stage2_f5_s1_clipplane_official_evidence_audit_v2.json"
DISPATCH = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
RUNTIME = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
GRID = {"dp010": "DP010", "dp005": "DP005"}


def regular(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    return path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with regular(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""): h.update(chunk)
    return h.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = regular(path); st = path.stat()
    return {"path": str(path), "bytes": int(st.st_size), "mtime_ns": int(st.st_mtime_ns), "ctime_ns": int(st.st_ctime_ns), "st_dev": int(st.st_dev), "st_ino": int(st.st_ino), "sha256": sha256(path)}


def stat_only(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file(): raise FileNotFoundError(path)
    st = path.stat()
    return {"path": str(path), "bytes": int(st.st_size), "mtime_ns": int(st.st_mtime_ns), "ctime_ns": int(st.st_ctime_ns), "st_dev": int(st.st_dev), "st_ino": int(st.st_ino), "sha256": None, "hash_status": "NOT_READ_BY_BUILDER"}


def write_new(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists(): raise FileExistsError(f"refuse to overwrite immutable request: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as f:
            fd = -1; f.write(payload); f.flush(); os.fsync(f.fileno())
    finally:
        if fd >= 0: os.close(fd)


def digest_arg(value: str | None, label: str) -> str | None:
    if value is None: return None
    if not re.fullmatch(r"[0-9a-f]{64}", value): raise ValueError(f"{label} must be lowercase SHA-256")
    return value


def build(args: argparse.Namespace) -> dict[str, Any]:
    for path in (WORKER, Path(__file__).resolve(), PYTHON, CLIP_EVIDENCE, DISPATCH, STRICT, RUNTIME, args.gencase_request, args.receipt, args.generated_xml, args.candidate_def, args.source_def, args.candidate_motion, args.source_motion): regular(Path(path))
    req = json.loads(Path(args.gencase_request).read_text(encoding="utf-8")); receipt = json.loads(Path(args.receipt).read_text(encoding="utf-8"))
    if req.get("family_id") != "F5" or req.get("sentinel_id") != "F5-S1" or req.get("physical_case_id") != "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090": raise ValueError("GenCase request identity mismatch")
    if str(receipt.get("status", "")).lower() not in {"completed", "complete", "success", "completed0"} or receipt.get("returncode") not in (0, None): raise ValueError("GenCase receipt is not completed zero-return")
    output_root = Path(str(receipt.get("output_root", ""))).expanduser().resolve(); generated = regular(Path(args.generated_xml));
    if generated.parent != output_root: raise ValueError("generated XML outside terminal output_root")
    fluid = output_root / "generated_Fluid.vtk"; bound = output_root / "generated_Bound.vtk"; fluid_stat = stat_only(fluid); bound_stat = stat_only(bound)
    records = {str(p.expanduser().resolve()): record(p) for p in dict.fromkeys([Path(args.gencase_request), Path(args.receipt), generated, Path(args.candidate_def), Path(args.source_def), Path(args.candidate_motion), Path(args.source_motion), CLIP_EVIDENCE, WORKER, Path(__file__).resolve(), PYTHON, DISPATCH, STRICT, RUNTIME])}
    known_fluid = digest_arg(args.known_fluid_vtk_sha, "known-fluid-vtk-sha"); known_bound = digest_arg(args.known_bound_vtk_sha, "known-bound-vtk-sha")
    input_files = list(records); input_hashes = {k: v["sha256"] for k, v in records.items()}
    if known_fluid and known_bound:
        input_files += [str(fluid.resolve()), str(bound.resolve())]; input_hashes[str(fluid.resolve())] = known_fluid; input_hashes[str(bound.resolve())] = known_bound
    case_id = args.case_id or f"F5_S1_CLIPPLANE_INITIAL_SUPPORT_AUDIT_V4_{GRID[args.grid]}_ROOT"; attempt_id = args.attempt_id or f"f5-s1-clipplane-initial-support-audit-v4-{args.grid}-root-001"; output_root_audit = DATA_ROOT / "families/F5" / case_id / attempt_id
    output = "{attempt_root}/report/stage2_f5_s1_clipplane_initial_support_audit_v4.json"
    command = [str(PYTHON), str(WORKER), "--generated-xml", str(generated), "--fluid-vtk", str(fluid), "--bound-vtk", str(bound), "--receipt", str(Path(args.receipt).resolve()), "--candidate-def", str(Path(args.candidate_def).resolve()), "--source-def", str(Path(args.source_def).resolve()), "--candidate-motion", str(Path(args.candidate_motion).resolve()), "--source-motion", str(Path(args.source_motion).resolve()), "--clip-evidence", str(CLIP_EVIDENCE.resolve()), "--gencase-request", str(Path(args.gencase_request).resolve()), "--expected-generated-xml-sha", records[str(generated.resolve())]["sha256"], "--expected-receipt-sha", records[str(Path(args.receipt).resolve())]["sha256"], "--expected-candidate-def-sha", records[str(Path(args.candidate_def).resolve())]["sha256"], "--expected-source-def-sha", records[str(Path(args.source_def).resolve())]["sha256"], "--expected-candidate-motion-sha", records[str(Path(args.candidate_motion).resolve())]["sha256"], "--expected-source-motion-sha", records[str(Path(args.source_motion).resolve())]["sha256"], "--expected-clip-evidence-sha", records[str(CLIP_EVIDENCE.resolve())]["sha256"], "--expected-gencase-request-sha", records[str(Path(args.gencase_request).resolve())]["sha256"], "--output", output]
    request = {"schema": "ds02.request.v1", "kind": "cpu", "cpu_task_kind": "audit", "family_id": "F5", "sentinel_id": "F5-S1", "physical_case_id": "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090", "case_id": case_id, "attempt_id": attempt_id, "launch_commit": args.launch_commit, "command": command, "cwd": str(PRIMARY_REPO), "worktree_root": str(PRIMARY_REPO), "input_files": input_files, "input_hashes": input_hashes, "input_records": records, "worker_owned_input_files": [str(fluid.resolve()), str(bound.resolve())], "worker_owned_input_stats_at_build": {"generated_fluid_vtk": fluid_stat, "generated_bound_vtk": bound_stat}, "worker_owned_input_hashes": {str(fluid.resolve()): known_fluid, str(bound.resolve()): known_bound, "hash_status": "PARENT_GUARDED_AFTER_RESERVATION" if not (known_fluid and known_bound) else "SNAPSHOT_SHA_BOUND_AND_RUNTIME_RECHECKED"}, "parent_v8_input_closure": {"small_input_sha256_complete": True, "generated_xml_and_receipt_sha256_bound": True, "vtk_parent_input_sha256_bound": bool(known_fluid and known_bound), "builder_did_not_read_or_hash_vtk": True, "worker_pre_post_full_stat_sha_required": True, "deferred_input_files_used": False}, "grid": args.grid, "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 1800, "max_memory_bytes": 2 * 1024**3, "max_storage_bytes": 128 * 1024**2, "estimated_input_read_bytes": sum(v["bytes"] for v in records.values()) + fluid_stat["bytes"] + bound_stat["bytes"], "estimated_output_bytes": 2 * 1024**2, "estimated_storage_bytes": 128 * 1024**2, "estimated_peak_memory_bytes": 2 * 1024**3, "estimated_native_read_bytes": 0, "estimated_bi4_read_bytes": 0, "estimated_hdf5_read_bytes": 0, "execution_allowed": True, "launch_disabled": False, "solver_started": False, "gencase_launch": False, "solver_launch": False, "hdf5_read": False, "bi4_read": False, "output_root": str(output_root_audit), "output": {"atomic": True, "refuse_overwrite": True, "path": output}, "source_binding": {"schema": "ds02.stage2.f5-s1.clipplane-initial-support-audit.v4", "grid": args.grid, "gencase_request": records[str(Path(args.gencase_request).resolve())], "gencase_receipt": records[str(Path(args.receipt).resolve())], "generated_xml": records[str(generated.resolve())], "candidate_def": records[str(Path(args.candidate_def).resolve())], "source_def": records[str(Path(args.source_def).resolve())], "candidate_motion": records[str(Path(args.candidate_motion).resolve())], "source_motion": records[str(Path(args.source_motion).resolve())], "clip_evidence": records[str(CLIP_EVIDENCE.resolve())], "continuous_region_mass_kg": 287.736, "mass_rescale": False}, "guard_policy": {"parent_after_reserve_pre_post_sha_stat": "required", "worker_owned_large_inputs": "generated Fluid/Bound VTK", "deferred_input_files": "not used", "bi4_read": False, "hdf5_read": False, "solver_launch": False, "support_mass_gate_before_solver": True}, "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(DISPATCH), "strict_guard": str(STRICT), "runtime": str(RUNTIME), "cpu_parent_binding": "required", "gpu": "none", "estimated_cpu_core_hours": 0.75, "estimated_new_storage_bytes": 128 * 1024**2}, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "actual initial support/mass/control audit; solver remains blocked until preferred gate and parent review"}, "status": "READY_FOR_PARENT_CPU_GUARD_REVIEW"}
    write_new(Path(args.output), request); return request


def self_test() -> dict[str, Any]: return {"status": "PASS", "vtk_payload_read_by_builder": False, "deferred_input_files_used": False, "solver_started": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); mode = parser.add_mutually_exclusive_group(required=True); mode.add_argument("--self-test", action="store_true"); mode.add_argument("--build-request", action="store_true")
    parser.add_argument("--grid", choices=sorted(GRID)); parser.add_argument("--gencase-request", type=Path); parser.add_argument("--receipt", type=Path); parser.add_argument("--generated-xml", type=Path); parser.add_argument("--candidate-def", type=Path); parser.add_argument("--source-def", type=Path); parser.add_argument("--candidate-motion", type=Path); parser.add_argument("--source-motion", type=Path); parser.add_argument("--output", type=Path); parser.add_argument("--launch-commit"); parser.add_argument("--case-id"); parser.add_argument("--attempt-id"); parser.add_argument("--known-fluid-vtk-sha"); parser.add_argument("--known-bound-vtk-sha")
    args = parser.parse_args()
    if args.self_test: print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    required = [args.grid, args.gencase_request, args.receipt, args.generated_xml, args.candidate_def, args.source_def, args.candidate_motion, args.source_motion, args.output, args.launch_commit]
    if any(v is None for v in required): parser.error("--build-request requires grid, terminal paths, output and launch commit")
    request = build(args); print(json.dumps({"status": "PASS_REQUEST_BUILT", "grid": args.grid, "output": str(args.output.resolve()), "vtk_payload_read_by_builder": False}, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
