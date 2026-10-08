#!/usr/bin/env python3
"""Build the additive F2-S1 ROOT076 support-audit request.

The builder may hash the terminal GenCase request/receipt and generated XML,
but it never opens or hashes generated Fluid/Bound VTK.  Without externally
supplied snapshot SHAs, those two large files remain worker-owned inputs: the
V8 child hashes/stat-checks them only after its CPU reservation.  Supplying
``--known-fluid-vtk-sha`` and ``--known-bound-vtk-sha`` (from a prior guarded
source snapshot) upgrades the request to a complete strict-V8 parent input
closure without changing the worker or source files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any


PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
REFERENCE = Path(__file__).resolve().parent
WORKER = REFERENCE / "stage2_f2_s1_owner_centered_cell_selector_support_audit_v8.py"
BUILDER = Path(__file__).resolve()
ROOT_REQUEST = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f2-s1-owner-centered-cell-selector-gencase-root-forward-076-001.json"
OWNER_CLOSURE = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f2_s1_continuum_owner_closure_v1.json"
DISPATCH = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
RUNTIME_V8 = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
RUNTIME_V6 = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py"
ROOT_CASE = "F2_S1_OWNER_CENTERED_CELL_SELECTOR_SUPPORT_AUDIT_V8_ROOT_078"
ROOT_ATTEMPT = "f2-s1-owner-centered-cell-selector-support-audit-v8-root-forward-078-001"
REQUEST = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f2-s1-owner-centered-cell-selector-support-audit-v8-root-forward-078-001.json"


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
        "path": str(path),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": sha256(path),
    }


def stat_only(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": None,
        "hash_status": "NOT_READ_BY_BUILDER",
    }


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


def _digest_arg(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def build(output: Path, launch_commit: str, known_fluid_vtk_sha: str | None = None, known_bound_vtk_sha: str | None = None) -> dict[str, Any]:
    known_fluid_vtk_sha = _digest_arg(known_fluid_vtk_sha, "known-fluid-vtk-sha")
    known_bound_vtk_sha = _digest_arg(known_bound_vtk_sha, "known-bound-vtk-sha")
    for path in (ROOT_REQUEST, OWNER_CLOSURE, DISPATCH, STRICT, RUNTIME_V8, RUNTIME_V6, PYTHON, WORKER, BUILDER):
        if not path.is_file():
            raise FileNotFoundError(path)
    root_request = json.loads(ROOT_REQUEST.read_text(encoding="utf-8"))
    root_receipt = Path(str(root_request.get("output_root", ""))) / "execution-receipt.json"
    # ROOT076's request output_root is a planning path; the terminal receipt is
    # the authoritative output path.  It is deliberately explicit rather than
    # selected with a latest/glob search.
    root_receipt = DATA_ROOT / "families/F2/F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0088_ROOT_076/f2-s1-owner-centered-cell-selector-gencase-root-076-001-root-forward-030-001/execution-receipt.json"
    root_receipt = regular(root_receipt)
    receipt = json.loads(root_receipt.read_text(encoding="utf-8"))
    if str(receipt.get("status", "")).lower() not in {"completed", "complete", "success", "completed0"} or receipt.get("returncode") not in (0, None):
        raise ValueError("ROOT076 terminal GenCase receipt is not completed zero-return")
    output_root = regular(Path(str(receipt["output_root"])))
    generated_xml = regular(output_root / "generated.xml")
    fluid_vtk = regular(output_root / "generated_Fluid.vtk")
    bound_vtk = regular(output_root / "generated_Bound.vtk")
    source_binding = root_request.get("source_binding", {})
    candidate = regular(Path(source_binding["candidate_def"]["path"]))
    source_def = regular(Path(source_binding["source_def"]["path"]))
    candidate_motion = regular(Path(source_binding["candidate_motion"]["path"]))
    source_motion = regular(Path(source_binding["source_motion"]["path"]))

    static_paths = [ROOT_REQUEST, root_receipt, generated_xml, OWNER_CLOSURE, DISPATCH, STRICT, RUNTIME_V8, RUNTIME_V6, PYTHON, WORKER, BUILDER, candidate, source_def, candidate_motion, source_motion]
    static_paths = list(dict.fromkeys(path.resolve() for path in static_paths))
    records = {str(path): record(path) for path in static_paths}
    dynamic_stat = {"generated_fluid_vtk": stat_only(fluid_vtk), "generated_bound_vtk": stat_only(bound_vtk)}
    command = [
        str(PYTHON), str(WORKER),
        "--generated-xml", str(generated_xml),
        "--fluid-vtk", str(fluid_vtk),
        "--bound-vtk", str(bound_vtk),
        "--receipt", str(root_receipt),
        "--candidate-def", str(candidate),
        "--source-def", str(source_def),
        "--candidate-motion", str(candidate_motion),
        "--source-motion", str(source_motion),
        "--gencase-request", str(ROOT_REQUEST),
        "--owner-closure", str(OWNER_CLOSURE),
        "--expected-generated-xml-sha", records[str(generated_xml)]["sha256"],
        "--expected-receipt-sha", records[str(root_receipt)]["sha256"],
        "--expected-candidate-def-sha", records[str(candidate)]["sha256"],
        "--expected-source-def-sha", records[str(source_def)]["sha256"],
        "--expected-candidate-motion-sha", records[str(candidate_motion)]["sha256"],
        "--expected-source-motion-sha", records[str(source_motion)]["sha256"],
        "--expected-gencase-request-sha", records[str(ROOT_REQUEST)]["sha256"],
        "--expected-owner-closure-sha", records[str(OWNER_CLOSURE)]["sha256"],
        "--output", "{attempt_root}/report/f2_s1_owner_centered_cell_selector_support_audit_v8.json",
    ]

    input_files = list(records)
    input_hashes = {path: item["sha256"] for path, item in records.items()}
    complete_parent_vtk_binding = known_fluid_vtk_sha is not None and known_bound_vtk_sha is not None
    if complete_parent_vtk_binding:
        input_files.extend([str(fluid_vtk), str(bound_vtk)])
        input_hashes[str(fluid_vtk)] = known_fluid_vtk_sha
        input_hashes[str(bound_vtk)] = known_bound_vtk_sha

    request = {
        "schema": "ds02.request.v1",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": "F2",
        "sentinel_id": "F2-S1",
        "physical_case_id": root_request["physical_case_id"],
        "case_id": ROOT_CASE,
        "attempt_id": ROOT_ATTEMPT,
        "launch_commit": launch_commit,
        "command": command,
        "cwd": str(PRIMARY_REPO),
        "worktree_root": str(PRIMARY_REPO),
        "input_files": input_files,
        "input_hashes": input_hashes,
        "input_records": records,
        "worker_owned_input_files": [str(fluid_vtk), str(bound_vtk)],
        "worker_owned_input_stats_at_build": dynamic_stat,
        "worker_owned_input_hashes": {
            str(fluid_vtk): known_fluid_vtk_sha,
            str(bound_vtk): known_bound_vtk_sha,
            "hash_status": "PARENT_GUARDED_AFTER_RESERVATION" if not complete_parent_vtk_binding else "SNAPSHOT_SHA_BOUND_AND_RUNTIME_RECHECKED",
        },
        "parent_v8_input_closure": {
            "small_input_sha256_complete": True,
            "generated_xml_and_terminal_receipt_sha256_bound": True,
            "vtk_parent_input_sha256_bound": complete_parent_vtk_binding,
            "vtk_source_snapshot_required_for_full_parent_binding": not complete_parent_vtk_binding,
            "builder_did_not_read_or_hash_vtk": True,
            "worker_pre_post_full_stat_sha_required": True,
        },
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 1200,
        "max_memory_bytes": 512 * 1024**2,
        "max_storage_bytes": 64 * 1024**2,
        "estimated_input_read_bytes": 20 * 1024**2,
        "estimated_output_bytes": 2 * 1024**2,
        "estimated_storage_bytes": 64 * 1024**2,
        "estimated_peak_memory_bytes": 512 * 1024**2,
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
        "output_root": str(DATA_ROOT / "families/F2" / ROOT_CASE / ROOT_ATTEMPT),
        "output": {"atomic": True, "refuse_overwrite": True, "path": "{attempt_root}/report/f2_s1_owner_centered_cell_selector_support_audit_v8.json"},
        "source_binding": {
            "schema": "ds02.stage2.f2-s1.owner-centered-cell-selector-support-audit.v8",
            "gencase_request": records[str(ROOT_REQUEST)],
            "gencase_terminal_receipt": records[str(root_receipt)],
            "generated_xml": records[str(generated_xml)],
            "candidate_def": records[str(candidate)],
            "source_def": records[str(source_def)],
            "candidate_motion": records[str(candidate_motion)],
            "source_motion": records[str(source_motion)],
            "owner_closure": records[str(OWNER_CLOSURE)],
            "generated_fluid_vtk": dynamic_stat["generated_fluid_vtk"],
            "generated_bound_vtk": dynamic_stat["generated_bound_vtk"],
            "representation": root_request.get("source_binding", {}).get("representation"),
            "owner_continuous_mass_kg": 18.876,
            "mass_gate": {"preferred_fraction": 0.01, "hard_fraction": 0.02, "no_rescale": True},
            "motion_byte_identity_required": True,
        },
        "guard_policy": {
            "parent_terminal_gencase_receipt_required": True,
            "runtime_v8_input_files": "all listed small files are strict SHA-bound; VTK is listed only when supplied snapshot SHA is known",
            "worker_owned_large_inputs": "Fluid.vtk and Bound.vtk are stat-checked at build, then full pre/post SHA+stat checked after reservation by worker",
            "worker_reads": "generated.xml + Fluid.vtk + Bound.vtk + terminal receipt + small Def/motion/request/owner closure",
            "bi4_read": False,
            "hdf5_read": False,
            "solver_launch": False,
            "source_output_protection": "read-only ROOT076 product; atomic new audit report; refuse overwrite",
        },
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(DISPATCH),
            "strict_guard": str(STRICT),
            "runtime": str(RUNTIME_V8),
            "cpu_parent_binding": "required",
            "gpu": "none",
            "solver_launch": "forbidden",
            "native_or_hdf5_read": "forbidden",
        },
        "qualification_stage": "stage2_f2_s1_root076_post_gencase_support_mass_audit_pending",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "initial generated XML/VTK support and frozen-owner mass/control audit only"},
    }
    output = output.expanduser().resolve()
    write_new(output, request)
    return request


def self_test() -> dict[str, Any]:
    with __import__("tempfile").TemporaryDirectory(prefix="f2-v8-builder-") as directory:
        path = Path(directory) / "sample.bin"
        path.write_bytes(b"small")
        result = stat_only(path)
        if result["sha256"] is not None or result["hash_status"] != "NOT_READ_BY_BUILDER":
            raise AssertionError("stat_only unexpectedly read content")
    return {"status": "PASS", "vtk_builder_read": False, "worker_owned_vtk_sha": "PARENT_GUARDED_AFTER_RESERVATION"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build-request", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--launch-commit")
    parser.add_argument("--known-fluid-vtk-sha")
    parser.add_argument("--known-bound-vtk-sha")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    if args.output is None or not args.launch_commit:
        parser.error("--build-request requires --output and --launch-commit")
    request = build(args.output, args.launch_commit, args.known_fluid_vtk_sha, args.known_bound_vtk_sha)
    print(json.dumps({"status": "PASS_REQUEST_BUILT", "output": str(args.output.resolve()), "parent_vtk_sha_bound": request["parent_v8_input_closure"]["vtk_parent_input_sha256_bound"], "vtk_builder_read": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
