#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Guarded full-byte snapshot of the completed F3 ROOT120 generated BI4.

The parent v8 request reserves the bounded CPU attempt before this worker
opens the deferred BI4.  The worker streams exactly one regular file, checks
path and file-descriptor identity before/after the stream, and writes an
immutable SHA/stat report.  It does not decode BI4, read HDF5/VTK, start
GenCase, or start a solver.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat as stat_module
import tempfile
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f3-s2.generated-bi4-source-snapshot.v1"
REQUEST_SCHEMA = "ds02.request.v1"
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
CHUNK_BYTES = 1024 * 1024
STAT_KEYS = ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino", "st_mode")


def _stat(value: os.stat_result) -> dict[str, int]:
    return {"bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns), "st_dev": int(value.st_dev), "st_ino": int(value.st_ino), "st_mode": int(value.st_mode)}


def _lstat(path: Path, label: str) -> os.stat_result:
    value = path.lstat()
    if stat_module.S_ISLNK(value.st_mode) or not stat_module.S_ISREG(value.st_mode):
        raise RuntimeError(f"{label} must be a regular non-symlink file: {path}")
    return value


def _open(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    if not stat_module.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd); raise RuntimeError(f"opened source is not regular: {path}")
    return fd


def _same(before: dict[str, int], after: dict[str, int], label: str) -> None:
    changed = {key: (before.get(key), after.get(key)) for key in STAT_KEYS if before.get(key) != after.get(key)}
    if changed:
        raise RuntimeError(f"{label} changed during source stream: {changed}")


def stream_source(path: Path, expected_bytes: int) -> dict[str, Any]:
    path = path.expanduser().absolute()
    path_before = _stat(_lstat(path, "F3 generated.bi4")); fd = _open(path)
    try:
        fd_before = _stat(os.fstat(fd)); _same(path_before, fd_before, "path/fd pre-read identity")
        if path_before["bytes"] != expected_bytes:
            raise RuntimeError(f"expected bytes {expected_bytes} != actual {path_before['bytes']}")
        digest = hashlib.sha256(); total = 0
        while True:
            block = os.read(fd, CHUNK_BYTES)
            if not block: break
            digest.update(block); total += len(block)
        fd_after = _stat(os.fstat(fd)); path_after = _stat(_lstat(path, "F3 generated.bi4"))
        _same(fd_before, fd_after, "open-file identity")
        _same(path_before, path_after, "path identity")
        _same(path_after, fd_after, "path/fd post-read identity")
        if total != path_before["bytes"]:
            raise RuntimeError(f"streamed bytes {total} != stat bytes {path_before['bytes']}")
        return {"path": str(path), "bytes": total, "sha256": digest.hexdigest(), "stat_before": path_before, "stat_after": path_after, "fd_stat_before": fd_before, "fd_stat_after": fd_after, "pre_post_identity": "PASS_BYTES_MTIME_CTIME_DEVICE_INODE_MODE_EQUAL", "hash_scope": "ONE_COMPLETE_STREAM_AFTER_PARENT_RESERVATION"}
    finally:
        os.close(fd)


def _load(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, dict): raise ValueError(f"{label} must be an object")
    return value


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()


def strict_join(q_path: Path, receipt_path: Path) -> dict[str, Any]:
    q_path = q_path.expanduser().resolve(); receipt_path = receipt_path.expanduser().resolve()
    q = _load(q_path, "F3 GenCase request"); receipt = _load(receipt_path, "F3 GenCase receipt")
    if q.get("schema") != REQUEST_SCHEMA: raise ValueError("F3 GenCase request schema mismatch")
    scope = q.get("scope") if isinstance(q.get("scope"), dict) else {}
    family_id = q.get("family_id") or scope.get("family_id")
    sentinel_id = q.get("sentinel_id") or scope.get("sentinel_id")
    physical_case_id = q.get("physical_case_id") or scope.get("physical_case_id")
    if family_id != "F3" or sentinel_id != "F3-S2" or physical_case_id != PHYSICAL_CASE_ID:
        raise ValueError("F3 ROOT120 request identity mismatch")
    if receipt.get("request") != q: raise ValueError("receipt.request is not exactly the supplied ROOT120 request")
    q_sha = _sha(q_path)
    if receipt.get("request_sha256") != q_sha: raise ValueError("receipt.request_sha256 does not match ROOT120 request")
    if str(receipt.get("status", "")).lower() not in {"completed", "complete", "success", "completed0"} or receipt.get("returncode") not in (0, None): raise ValueError("ROOT120 receipt is not completed zero-return")
    root = Path(str(receipt.get("output_root", ""))).expanduser().resolve()
    if not root.is_dir(): raise FileNotFoundError(f"ROOT120 actual output root is missing: {root}")
    return {"q_path": str(q_path), "q_sha256": q_sha, "receipt_path": str(receipt_path), "receipt_request_exact_q": True, "receipt_request_sha256_exact_q": True, "actual_receipt_output_root": str(root), "actual_receipt_output_root_authoritative": True}


def _write(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink(): raise FileExistsError(f"refuse overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True); temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    encoded = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1; handle.write(encoded); handle.flush(); os.fsync(handle.fileno())
    finally:
        if fd >= 0: os.close(fd)
    os.replace(temporary, path)


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    join = strict_join(args.gencase_request, args.receipt)
    source = args.input_bi4.expanduser().absolute()
    actual_root = Path(join["actual_receipt_output_root"])
    if source.parent != actual_root or source.name != "generated.bi4": raise ValueError("F3 BI4 must be the generated.bi4 in ROOT120 actual output_root")
    result: dict[str, Any] = {"schema": SCHEMA, "status": "FAILED_BEFORE_SOURCE_READ", "family_id": "F3", "sentinel_id": "F3-S2", "physical_case_id": PHYSICAL_CASE_ID, "producer_join": join, "source": {"path": str(source), "expected_bytes": args.expected_bytes, "content_sha256": "NOT_COMPUTED_ON_FAILURE"}, "worker_scope": {"single_generated_bi4": True, "full_payload_streamed": False, "read_plan": {"passes": 1, "estimated_single_stream_read_bytes": args.expected_bytes, "estimated_peak_buffer_bytes": CHUNK_BYTES}, "bi4_decode": False, "vtk_read": False, "hdf5_read": False, "gencase_launch": False, "solver_launch": False, "source_sha_computed_after_parent_reservation": True, "parent_v8_deferred_hash_not_claimed": True}, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}
    try:
        source_record = stream_source(source, args.expected_bytes)
        result["status"] = "PASS_F3_GENERATED_BI4_HASHED_STABLE"; result["source"] = {**result["source"], **source_record, "content_sha256": source_record["sha256"]}; result["worker_scope"]["full_payload_streamed"] = True
    except BaseException as exc:
        result["status"] = "FAILED_F3_GENERATED_BI4_SOURCE_GUARD"; result["error"] = {"type": type(exc).__name__, "message": str(exc)}; result["failure_is_scientific_unknown"] = True; _write(args.output, result); raise
    _write(args.output, result); return result


def self_test() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="f3-bi4-snapshot-") as directory:
        root = Path(directory); producer = root / "producer"; producer.mkdir(); source = producer / "generated.bi4"; source.write_bytes(b"F3 synthetic BI4" * 97); q_path = root / "q.json"; receipt_path = root / "receipt.json"; out = root / "snapshot.json"
        q = {"schema": REQUEST_SCHEMA, "family_id": "F3", "sentinel_id": "F3-S2", "scope": {"physical_case_id": PHYSICAL_CASE_ID}, "case_id": "C", "attempt_id": "A"}; q_path.write_text(json.dumps(q, sort_keys=True) + "\n")
        receipt_path.write_text(json.dumps({"status": "completed", "returncode": 0, "request": q, "request_sha256": _sha(q_path), "output_root": str(producer)}, sort_keys=True) + "\n")
        report = build_report(argparse.Namespace(gencase_request=q_path, receipt=receipt_path, input_bi4=source, expected_bytes=source.stat().st_size, output=out))
        if report["status"] != "PASS_F3_GENERATED_BI4_HASHED_STABLE" or report["source"]["stat_before"] != report["source"]["stat_after"]: raise AssertionError(report)
    return {"status": "PASS", "schema": SCHEMA, "full_stream_hash": True, "strict_q_receipt_join": True, "pre_post_identity": True, "decoder_or_solver": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--self-test", action="store_true"); parser.add_argument("--gencase-request", type=Path); parser.add_argument("--receipt", type=Path); parser.add_argument("--input-bi4", type=Path); parser.add_argument("--expected-bytes", type=int); parser.add_argument("--output", type=Path); parser.add_argument("--case-id", default="F3_S2_OWNER_CENTERED_DP015_BI4_SOURCE_SNAPSHOT_ROOT128")
    args = parser.parse_args()
    if args.self_test: print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    if any(value is None for value in (args.gencase_request, args.receipt, args.input_bi4, args.expected_bytes, args.output)) or args.expected_bytes <= 0: parser.error("all q/receipt/input-bi4/positive expected-bytes/output are required")
    try:
        report = build_report(args)
    except BaseException as exc:
        print(json.dumps({"status": "FAILED_F3_GENERATED_BI4_SOURCE_GUARD", "error": str(exc)}, ensure_ascii=False), flush=True); return 1
    print(json.dumps({"status": report["status"], "output": str(args.output.expanduser().absolute()), "sha256": report["source"]["sha256"], "bytes": report["source"]["bytes"]}, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
