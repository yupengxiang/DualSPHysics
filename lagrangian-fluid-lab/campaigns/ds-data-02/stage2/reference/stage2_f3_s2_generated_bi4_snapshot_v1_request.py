#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build the parent-v8 F3 ROOT120 generated-BI4 source snapshot request."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
WORKER = HERE / "stage2_f3_s2_generated_bi4_snapshot_v1.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
SCHEMA = "ds02.request.v1"
VARIANT = "ds02.stage2.f3-s2.generated-bi4-source-snapshot.v1-request"
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file(): raise FileNotFoundError(f"{label} must be a regular file: {path}")
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()


def record(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label); stat = path.stat()
    return {"path": str(path), "label": label, "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "ctime_ns": int(stat.st_ctime_ns), "st_dev": int(stat.st_dev), "st_ino": int(stat.st_ino), "sha256": sha256(path), "content_scope": "small_input_hashed_by_builder_and_parent_v8"}


def build(args: argparse.Namespace) -> dict[str, Any]:
    q = regular(args.gencase_request, "ROOT120 GenCase request"); receipt = regular(args.receipt, "ROOT120 receipt"); bi4 = regular(args.input_bi4, "ROOT120 generated BI4")
    qv = json.loads(q.read_text(encoding="utf-8")); rv = json.loads(receipt.read_text(encoding="utf-8"))
    if qv.get("schema") != SCHEMA or qv.get("family_id") != "F3" or qv.get("sentinel_id") != "F3-S2" or qv.get("scope", {}).get("physical_case_id") != PHYSICAL_CASE_ID: raise ValueError("ROOT120 q identity mismatch")
    if rv.get("request") != qv or rv.get("request_sha256") != sha256(q): raise ValueError("ROOT120 receipt exact q/SHA join failed")
    root = Path(str(rv.get("output_root", ""))).expanduser().resolve()
    if bi4.parent != root or bi4.name != "generated.bi4": raise ValueError("BI4 must be ROOT120 actual generated.bi4")
    stat = bi4.stat(); worker = regular(WORKER, "F3 BI4 snapshot worker"); python = regular(PYTHON, "stage2 venv interpreter")
    records = {str(q): record(q, "ROOT120 GenCase request"), str(receipt): record(receipt, "ROOT120 GenCase receipt"), str(worker): record(worker, "F3 generated BI4 snapshot worker"), str(python): record(python, "stage2 venv interpreter")}
    files = sorted(records)
    output = "{attempt_root}/native_source_snapshot.json"
    command = [str(python), str(worker), "--gencase-request", str(q), "--receipt", str(receipt), "--input-bi4", str(bi4), "--expected-bytes", str(int(stat.st_size)), "--output", output, "--case-id", args.case_id]
    payload: dict[str, Any] = {"schema": SCHEMA, "kind": "cpu", "cpu_task_kind": "audit", "family_id": "F3", "sentinel_id": "F3-S2", "physical_case_id": PHYSICAL_CASE_ID, "case_id": args.case_id, "attempt_id": args.attempt_id, "launch_commit": args.launch_commit, "command": command, "cwd": str(HERE.parent.parent.parent.parent), "worktree_root": str(HERE.parent.parent.parent.parent.parent), "input_files": files, "input_hashes": {path: records[path]["sha256"] for path in files}, "input_records": records, "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 1800, "max_memory_bytes": 512 * 1024**2, "estimated_storage_bytes": 16 * 1024**2, "estimated_peak_memory_bytes": 128 * 1024**2, "estimated_input_read_bytes": sum(item["bytes"] for item in records.values()), "estimated_native_read_bytes": int(stat.st_size), "estimated_bi4_read_bytes": int(stat.st_size), "estimated_hdf5_read_bytes": 0, "execution_allowed": True, "launch_disabled": False, "solver_started": False, "gencase_launch": False, "solver_launch": False, "hdf5_read": False, "bi4_read": False, "output_root": "{attempt_root}", "output": {"atomic": True, "refuse_overwrite": True, "path": output}, "deferred_input_files": [str(bi4)], "deferred_input_stats": {str(bi4): {"path": str(bi4), "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "ctime_ns": int(stat.st_ctime_ns), "st_dev": int(stat.st_dev), "st_ino": int(stat.st_ino), "sha256": "NOT_COMPUTED_BY_BUILDER_OR_PARENT_V8"}}, "source_binding": {"schema": VARIANT, "root120_q_receipt_exact_join": True, "actual_receipt_output_root_authoritative": True, "generated_bi4_path": str(bi4), "expected_bytes": int(stat.st_size), "worker_full_sha_after_reservation": True, "worker_pre_post_stat_and_fd_identity": True, "decoder": False, "solver": False}, "resource_guard": {"owner": "stage2-reference-preparation", "runner": "parent-v8-audit", "cpu_parent_binding": "required", "payload_read": "one complete BI4 stream only", "solver_launch": "forbidden"}, "qualification_stage": "stage2_f3_s2_generated_bi4_source_snapshot_pending_parent_guard", "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "immutable source hash/stat closure only; no decoder or scientific qualification"}, "status": "READY_FOR_PARENT_V8_F3_BI4_SOURCE_SNAPSHOT"}
    payload["sha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest(); return payload


def write_new(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink(): raise FileExistsError(f"refuse overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True); temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp"); fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1; handle.write((json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()); handle.flush(); os.fsync(handle.fileno())
    finally:
        if fd >= 0: os.close(fd)
    os.replace(temporary, path)


def self_test() -> dict[str, Any]:
    worker = regular(WORKER, "F3 BI4 snapshot worker")
    if not worker.is_file(): raise AssertionError(worker)
    return {"status": "PASS", "schema": SCHEMA, "request_variant_schema": VARIANT, "builder_does_not_hash_bi4": True, "worker_hash_after_reservation": True, "solver_started": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); mode = parser.add_mutually_exclusive_group(required=True); mode.add_argument("--self-test", action="store_true"); mode.add_argument("--build-request", action="store_true")
    parser.add_argument("--gencase-request", type=Path); parser.add_argument("--receipt", type=Path); parser.add_argument("--input-bi4", type=Path); parser.add_argument("--output", type=Path); parser.add_argument("--launch-commit", required=False); parser.add_argument("--case-id", default="F3_S2_OWNER_CENTERED_DP015_BI4_SOURCE_SNAPSHOT_ROOT128"); parser.add_argument("--attempt-id", default="f3-s2-owner-centered-dp015-bi4-source-snapshot-v1-root128-001")
    args = parser.parse_args()
    if args.self_test: print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    if any(value is None for value in (args.gencase_request, args.receipt, args.input_bi4, args.output, args.launch_commit)): parser.error("--build-request requires ROOT120 q/receipt/BI4/output/launch commit")
    payload = build(args); write_new(args.output, payload); print(json.dumps({"status": payload["status"], "schema": SCHEMA, "output": str(args.output.resolve()), "bi4_read_by_builder": False}, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
