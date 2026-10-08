#!/usr/bin/env python3
"""Build a parent-guarded F2 middle/fine V9 support-QA request.

This builder is run only after the corresponding root GenCase receipt exists.
It hashes the small XML/receipt/source inputs, records the generated VTK paths
without reading their payloads, and leaves those large files to the V9 worker's
post-reservation pre/post SHA+stat check.  If prior guarded snapshot SHAs are
provided they are added as ordinary parent input files.  No deferred input
field is used as a substitute for ``input_files``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
WORKER = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f2_s1_owner_centered_cell_selector_support_audit_v9.py"
DISPATCH = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
RUNTIME = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
OWNER_MASS_KG = 18.876
PHYSICAL_CASE_ID = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
GRID = {"middle": ("DP0044", 0.0044, "middle"), "fine": ("DP0022", 0.0022, "fine")}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    return path


def record(path: Path) -> dict[str, Any]:
    path = regular(path)
    stat = path.stat()
    return {
        "path": str(path), "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns), "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino), "sha256": sha256(path),
    }


def stat_only(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {"path": str(path), "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "ctime_ns": int(stat.st_ctime_ns), "st_dev": int(stat.st_dev), "st_ino": int(stat.st_ino), "sha256": None, "hash_status": "NOT_READ_BY_BUILDER"}


def write_new(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refuse to overwrite immutable request: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def digest_arg(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def build(args: argparse.Namespace) -> dict[str, Any]:
    label, dp, _ = GRID[args.grid]
    for path in (PYTHON, WORKER, DISPATCH, STRICT, RUNTIME, args.gencase_request, args.receipt, args.generated_xml, args.candidate_def, args.source_def, args.candidate_motion, args.source_motion, args.owner_closure):
        regular(Path(path))
    gencase_request = json.loads(Path(args.gencase_request).read_text(encoding="utf-8"))
    if gencase_request.get("schema") != "ds02.request.v1" or gencase_request.get("family_id") != "F2" or gencase_request.get("sentinel_id") != "F2-S1":
        raise ValueError("bound GenCase request is not F2-S1 ds02.request.v1")
    if gencase_request.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise ValueError("bound GenCase physical identity mismatch")
    receipt = json.loads(Path(args.receipt).read_text(encoding="utf-8"))
    if str(receipt.get("status", "")).lower() not in {"completed", "complete", "success", "completed0"} or receipt.get("returncode") not in (0, None):
        raise ValueError("GenCase receipt is not a completed zero-return product")
    output_root = Path(str(receipt.get("output_root", ""))).expanduser().resolve()
    generated_xml = regular(Path(args.generated_xml))
    if generated_xml.parent != output_root:
        raise ValueError("generated XML is outside terminal receipt output_root")
    fluid_vtk = output_root / "generated_Fluid.vtk"
    bound_vtk = output_root / "generated_Bound.vtk"
    # VTK bytes are deliberately not read here.  The output must exist so the
    # request cannot silently refer to a future/glob-selected product.
    fluid_stat = stat_only(fluid_vtk)
    bound_stat = stat_only(bound_vtk)
    small = [Path(args.gencase_request), Path(args.receipt), generated_xml, Path(args.candidate_def), Path(args.source_def), Path(args.candidate_motion), Path(args.source_motion), Path(args.owner_closure), PYTHON, WORKER, DISPATCH, STRICT, RUNTIME, Path(__file__).resolve()]
    records = {str(p.expanduser().resolve()): record(p) for p in dict.fromkeys(small)}
    known_fluid = digest_arg(args.known_fluid_vtk_sha, "known-fluid-vtk-sha")
    known_bound = digest_arg(args.known_bound_vtk_sha, "known-bound-vtk-sha")
    input_files = list(records)
    input_hashes = {key: value["sha256"] for key, value in records.items()}
    if known_fluid is not None and known_bound is not None:
        input_files += [str(fluid_vtk.resolve()), str(bound_vtk.resolve())]
        input_hashes[str(fluid_vtk.resolve())] = known_fluid
        input_hashes[str(bound_vtk.resolve())] = known_bound
    case_id = args.case_id or f"F2_S1_OWNER_CENTERED_CELL_SELECTOR_SUPPORT_AUDIT_V9_{label}_ROOT"
    attempt_id = args.attempt_id or f"f2-s1-owner-centered-cell-selector-support-audit-v9-{args.grid}-root-001"
    output_root_audit = DATA_ROOT / "families/F2" / case_id / attempt_id
    command = [str(PYTHON), str(WORKER), "--grid", args.grid, "--generated-xml", str(generated_xml), "--fluid-vtk", str(fluid_vtk), "--bound-vtk", str(bound_vtk), "--receipt", str(Path(args.receipt).resolve()), "--candidate-def", str(Path(args.candidate_def).resolve()), "--source-def", str(Path(args.source_def).resolve()), "--candidate-motion", str(Path(args.candidate_motion).resolve()), "--source-motion", str(Path(args.source_motion).resolve()), "--gencase-request", str(Path(args.gencase_request).resolve()), "--owner-closure", str(Path(args.owner_closure).resolve()), "--expected-generated-xml-sha", records[str(generated_xml)]["sha256"], "--expected-receipt-sha", records[str(Path(args.receipt).resolve())]["sha256"], "--expected-candidate-def-sha", records[str(Path(args.candidate_def).resolve())]["sha256"], "--expected-source-def-sha", records[str(Path(args.source_def).resolve())]["sha256"], "--expected-candidate-motion-sha", records[str(Path(args.candidate_motion).resolve())]["sha256"], "--expected-source-motion-sha", records[str(Path(args.source_motion).resolve())]["sha256"], "--expected-gencase-request-sha", records[str(Path(args.gencase_request).resolve())]["sha256"], "--expected-owner-closure-sha", records[str(Path(args.owner_closure).resolve())]["sha256"], "--output", "{attempt_root}/report/f2_s1_owner_centered_cell_selector_support_audit_v9.json"]
    request = {
        "schema": "ds02.request.v1", "kind": "cpu", "cpu_task_kind": "audit",
        "family_id": "F2", "sentinel_id": "F2-S1", "physical_case_id": PHYSICAL_CASE_ID,
        "case_id": case_id, "attempt_id": attempt_id, "launch_commit": args.launch_commit,
        "command": command, "cwd": str(PRIMARY_REPO), "worktree_root": str(PRIMARY_REPO),
        "input_files": input_files, "input_hashes": input_hashes, "input_records": records,
        "worker_owned_input_files": [str(fluid_vtk.resolve()), str(bound_vtk.resolve())],
        "worker_owned_input_stats_at_build": {"generated_fluid_vtk": fluid_stat, "generated_bound_vtk": bound_stat},
        "worker_owned_input_hashes": {str(fluid_vtk.resolve()): known_fluid, str(bound_vtk.resolve()): known_bound, "hash_status": "PARENT_GUARDED_AFTER_RESERVATION" if not (known_fluid and known_bound) else "SNAPSHOT_SHA_BOUND_AND_RUNTIME_RECHECKED"},
        "parent_v8_input_closure": {"small_input_sha256_complete": True, "generated_xml_and_terminal_receipt_sha256_bound": True, "vtk_parent_input_sha256_bound": bool(known_fluid and known_bound), "vtk_source_snapshot_required_for_full_parent_binding": not bool(known_fluid and known_bound), "builder_did_not_read_or_hash_vtk": True, "worker_pre_post_full_stat_sha_required": True, "deferred_input_files_used": False},
        "candidate_grid": {"name": args.grid, "dp_m": dp, "label": label, "count_source": "actual generated XML fluid blocks", "mass_rescale": False},
        "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": args.max_wall_seconds, "max_memory_bytes": 2 * 1024**3, "max_storage_bytes": 128 * 1024**2,
        "estimated_input_read_bytes": sum(v["bytes"] for v in records.values()) + fluid_stat["bytes"] + bound_stat["bytes"], "estimated_output_bytes": 2 * 1024**2, "estimated_storage_bytes": 128 * 1024**2, "estimated_peak_memory_bytes": 2 * 1024**3,
        "estimated_native_read_bytes": 0, "estimated_bi4_read_bytes": 0, "estimated_hdf5_read_bytes": 0,
        "execution_allowed": True, "launch_disabled": False, "solver_started": False, "gencase_launch": False, "solver_launch": False, "hdf5_read": False, "bi4_read": False,
        "output_root": str(output_root_audit), "output": {"atomic": True, "refuse_overwrite": True, "path": "{attempt_root}/report/f2_s1_owner_centered_cell_selector_support_audit_v9.json"},
        "source_binding": {"schema": "ds02.stage2.f2-s1.owner-centered-cell-selector-support-audit.v9", "grid": args.grid, "registered_dp_m": dp, "owner_continuous_mass_kg": OWNER_MASS_KG, "gencase_request": records[str(Path(args.gencase_request).resolve())], "gencase_receipt": records[str(Path(args.receipt).resolve())], "generated_xml": records[str(generated_xml)], "candidate_def": records[str(Path(args.candidate_def).resolve())], "source_def": records[str(Path(args.source_def).resolve())], "candidate_motion": records[str(Path(args.candidate_motion).resolve())], "source_motion": records[str(Path(args.source_motion).resolve())], "owner_closure": records[str(Path(args.owner_closure).resolve())], "generated_fluid_vtk": fluid_stat, "generated_bound_vtk": bound_stat},
        "guard_policy": {"input_files_are_full_strings": True, "parent_after_reserve_pre_post_sha_stat": "required for every listed input; generated Fluid/Bound VTK are worker-owned unless snapshot SHA supplied", "deferred_input_files": "not used", "worker_reads": "terminal generated XML, Fluid/Bound VTK, receipt, candidate/source Def and motion, owner closure only", "no_solver_or_bi4_or_hdf5": True, "actual_count_and_selector_from_generated_inputs": True},
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(DISPATCH), "strict_guard": str(STRICT), "runtime": str(RUNTIME), "cpu_parent_binding": "required", "gpu": "none", "gencase_launch": False, "solver_launch": False, "estimated_cpu_core_hours": 0.5, "estimated_new_storage_bytes": 128 * 1024**2},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "parameterized initial XML/VTK support and frozen-owner mass/control QA; no CFD qualification"},
        "status": "READY_FOR_PARENT_CPU_GUARD_REVIEW",
    }
    write_new(Path(args.output), request)
    return request


def self_test() -> dict[str, Any]:
    if GRID["middle"][1] == GRID["fine"][1] or GRID["middle"][1] <= GRID["fine"][1]:
        raise AssertionError("F2 middle/fine registration invalid")
    with __import__("tempfile").TemporaryDirectory(prefix="f2-v9-builder-") as d:
        p = Path(d) / "x"; p.write_bytes(b"x")
        if stat_only(p)["sha256"] is not None:
            raise AssertionError("stat_only read payload")
    return {"status": "PASS", "grids": sorted(GRID), "vtk_payload_read_by_builder": False, "deferred_input_files_used": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build-request", action="store_true")
    parser.add_argument("--grid", choices=sorted(GRID))
    parser.add_argument("--gencase-request", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--generated-xml", type=Path)
    parser.add_argument("--candidate-def", type=Path)
    parser.add_argument("--source-def", type=Path)
    parser.add_argument("--candidate-motion", type=Path)
    parser.add_argument("--source-motion", type=Path)
    parser.add_argument("--owner-closure", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--launch-commit", required=False)
    parser.add_argument("--case-id")
    parser.add_argument("--attempt-id")
    parser.add_argument("--known-fluid-vtk-sha")
    parser.add_argument("--known-bound-vtk-sha")
    parser.add_argument("--max-wall-seconds", type=int, default=1800)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    needed = [args.grid, args.gencase_request, args.receipt, args.generated_xml, args.candidate_def, args.source_def, args.candidate_motion, args.source_motion, args.owner_closure, args.output, args.launch_commit]
    if any(v is None for v in needed):
        parser.error("--build-request requires grid, terminal GenCase paths, owner closure, output, and launch commit")
    request = build(args)
    print(json.dumps({"status": "PASS_REQUEST_BUILT", "grid": args.grid, "output": str(args.output.resolve()), "vtk_payload_read_by_builder": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
