#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build the parent-v8 source snapshot request for the F3-S2 dp=.003 BI4.

This is a forward-only sibling of the consumed ROOT161 middle snapshot
builder.  It reads only the ROOT102 request/receipt and ``stat(2)`` metadata
for the generated BI4.  The BI4 is deferred to the parent reservation and is
hashed exactly once by the worker after reservation.  The request never
decodes BI4, reads VTK/HDF5, launches GenCase, or launches a solver.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
LOCAL_REPO = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
SCHEMA = "ds02.request.v1"
VARIANT = "ds02.stage2.f3.s2.fine-bi4-source-snapshot-request.v1"
EXPECTED_BYTES = 48_183_300
EXPECTED_BI4_NAME = "F3_S2_P1200_AY0750_DP003_MATCHED.bi4"

FINE_ROOT = DATA_ROOT / "families/F3/F3_S2_MATCHED_SOURCE_COMMENSURATE_DP003_GENCASE_ROOT_102/f3-s2-commensurate-dp003-gencase-v1-root-102-001-root-forward-030-001"
FINE_RECEIPT = FINE_ROOT / "execution-receipt.json"
FINE_BI4 = FINE_ROOT / "worker/generated" / EXPECTED_BI4_NAME
SOURCE_Q = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-commensurate-dp003-gencase-v1-root-forward-102-001.json"

WORKER_PRIMARY = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_fine_bi4_snapshot_v1.py"
STREAM_WORKER_PRIMARY = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_generated_bi4_snapshot_v1.py"
WORKER_LOCAL = LOCAL_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_fine_bi4_snapshot_v1.py"
STREAM_WORKER_LOCAL = LOCAL_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_generated_bi4_snapshot_v1.py"

RUNTIME_NAMES = (
    "ds_data02_runtime_v2.py",
    "ds_data02_runtime_v6.py",
    "ds_data02_runtime_v8.py",
    "ds_data02_stage2_dispatch_v8.py",
    "ds_data02_strict_dispatch_v8.py",
    "ds_data02_batch_runner.py",
)


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    return path


def primary_or_local(primary: Path, local: Path, label: str) -> Path:
    if primary.is_file() and not primary.is_symlink():
        return primary
    if local.is_file() and not local.is_symlink():
        return local
    raise FileNotFoundError(f"{label}: neither primary nor local source exists")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with regular(path, "hash input").open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def record(path: Path, label: str, max_bytes: int = 2 * 1024 * 1024) -> dict[str, Any]:
    path = regular(path, label)
    stat = path.stat()
    if stat.st_size > max_bytes:
        raise ValueError(f"{label} is unexpectedly large for a builder input: {stat.st_size}")
    return {
        "path": str(path),
        "label": label,
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": sha256(path),
        "content_scope": "small_input_hashed_by_builder_and_parent_v8",
    }


def literal_record(path: Path, label: str) -> dict[str, Any]:
    """Record the interpreter without resolving away the required venv path."""

    path = path.expanduser()
    # The venv entry may itself be a stable symlink.  Preserve the literal
    # argv path in the request while recording the target file metadata.
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
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
        "content_scope": "literal_venv_interpreter_hashed_by_builder_and_parent_v8",
    }


def deferred_stat(path: Path, label: str) -> dict[str, Any]:
    """Record only metadata; parent worker owns the later full SHA."""

    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    stat = path.stat()
    if stat.st_size != EXPECTED_BYTES:
        raise ValueError(f"{label} bytes {stat.st_size} != expected {EXPECTED_BYTES}")
    return {
        "path": str(path),
        "label": label,
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": "NOT_COMPUTED_BY_BUILDER_OR_PARENT_V8",
        "content_scope": "worker_after_parent_reservation_one_complete_stream",
    }


def validate_producer() -> dict[str, Any]:
    """Validate ROOT102 small producer metadata without reading generated BI4."""

    q = load_json(SOURCE_Q, "ROOT102 GenCase request")
    receipt = load_json(FINE_RECEIPT, "ROOT102 GenCase receipt")
    scope = q.get("scope") if isinstance(q.get("scope"), dict) else {}
    family = q.get("family_id") or scope.get("family_id")
    sentinel = q.get("sentinel_id") or scope.get("sentinel_id")
    physical = q.get("physical_case_id") or scope.get("physical_case_id")
    if q.get("schema") not in {"ds02.request.v1", "ds02.runner-request.v1"}:
        raise ValueError(f"ROOT102 request schema changed: {q.get('schema')!r}")
    if family != "F3" or sentinel not in {None, "F3-S2"} or physical != PHYSICAL_CASE_ID:
        raise ValueError("ROOT102 request physical identity mismatch")
    if str(receipt.get("status", "")).lower() not in {"completed", "complete", "success", "completed0"}:
        raise ValueError("ROOT102 receipt is not completed")
    if receipt.get("returncode") not in (0, None):
        raise ValueError(f"ROOT102 receipt returncode is not zero: {receipt.get('returncode')!r}")
    if receipt.get("request") != q:
        raise ValueError("ROOT102 receipt.request is not exactly the supplied request")
    q_sha = sha256(SOURCE_Q)
    if receipt.get("request_sha256") != q_sha:
        raise ValueError("ROOT102 receipt.request_sha256 does not match ROOT102 request")
    actual_root = Path(str(receipt.get("output_root", ""))).expanduser().resolve()
    if not actual_root.is_dir():
        raise FileNotFoundError(f"ROOT102 output root is missing: {actual_root}")
    expected_bi4 = actual_root / "worker" / "generated" / EXPECTED_BI4_NAME
    if FINE_BI4.resolve() != expected_bi4:
        raise ValueError(f"ROOT102 generated BI4 path mismatch: expected {expected_bi4}, got {FINE_BI4.resolve()}")
    source = deferred_stat(FINE_BI4, "ROOT102 generated dp=.003 BI4")
    return {
        "q_path": str(SOURCE_Q.resolve()),
        "q_sha256": q_sha,
        "receipt_path": str(FINE_RECEIPT.resolve()),
        "receipt_sha256": sha256(FINE_RECEIPT),
        "receipt_request_exact_q": True,
        "receipt_request_sha256_exact_q": True,
        "actual_receipt_output_root": str(actual_root),
        "receipt_status": receipt.get("status"),
        "receipt_returncode": receipt.get("returncode"),
        "source_request_case_id": q.get("case_id"),
        "source_request_attempt_id": q.get("attempt_id"),
        "generated_bi4": source,
    }


def canonical(value: dict[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def build(args: argparse.Namespace) -> dict[str, Any]:
    producer = validate_producer()
    worker = primary_or_local(WORKER_PRIMARY, WORKER_LOCAL, "fine BI4 snapshot worker")
    stream_worker = primary_or_local(STREAM_WORKER_PRIMARY, STREAM_WORKER_LOCAL, "ROOT132 stream guard dependency")
    runtime_dir = PRIMARY_REPO / "lagrangian-fluid-lab/scripts"
    local_runtime_dir = LOCAL_REPO / "lagrangian-fluid-lab/scripts"
    dependency_paths: list[tuple[Path, str]] = [
        (SOURCE_Q, "ROOT102 GenCase request"),
        (FINE_RECEIPT, "ROOT102 GenCase receipt"),
        (worker, "F3 fine BI4 snapshot worker"),
        (stream_worker, "ROOT132 one-stream dependency"),
    ]
    for name in RUNTIME_NAMES:
        dependency_paths.append((primary_or_local(runtime_dir / name, local_runtime_dir / name, name), name))
    records = {str(path.resolve()): record(path, label) for path, label in dependency_paths}
    py_record = literal_record(PYTHON, "literal venv interpreter")
    records[py_record["path"]] = py_record
    files = sorted(records)
    bi4_path = str(FINE_BI4.resolve())
    worker_path = str(worker.resolve())
    q_path = str(SOURCE_Q.resolve())
    receipt_path = str(FINE_RECEIPT.resolve())
    output = "{attempt_root}/fine_bi4_source_snapshot.json"
    command = [
        str(PYTHON),
        worker_path,
        "--gencase-request",
        q_path,
        "--receipt",
        receipt_path,
        "--input-bi4",
        bi4_path,
        "--expected-bytes",
        str(EXPECTED_BYTES),
        "--output",
        output,
    ]
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "variant_schema": VARIANT,
        "status": "READY_FOR_PARENT_V8_F3_FINE_BI4_SOURCE_SNAPSHOT",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": "F3",
        "sentinel_id": "F3-S2",
        "physical_case_id": PHYSICAL_CASE_ID,
        "case_id": args.case_id,
        "attempt_id": args.attempt_id,
        "launch_commit": args.launch_commit,
        "cwd": str(PRIMARY_REPO / "lagrangian-fluid-lab"),
        "worktree_root": str(PRIMARY_REPO),
        "command": command,
        "input_files": files,
        "input_hashes": {path: records[path]["sha256"] for path in files},
        "input_sha256": {path: records[path]["sha256"] for path in files},
        "input_records": records,
        "deferred_input_files": [bi4_path],
        "deferred_input_stats": {bi4_path: producer["generated_bi4"]},
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 1800,
        "max_memory_bytes": 512 * 1024**2,
        "estimated_storage_bytes": 16 * 1024**2,
        "estimated_peak_memory_bytes": 128 * 1024**2,
        "estimated_input_read_bytes": sum(item["bytes"] for item in records.values()),
        "estimated_native_read_bytes": EXPECTED_BYTES,
        "estimated_bi4_read_bytes": EXPECTED_BYTES,
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
            "schema": VARIANT,
            "root102_q_receipt_exact_join": True,
            "actual_receipt_output_root_authoritative": True,
            "generated_bi4_path": bi4_path,
            "expected_bytes": EXPECTED_BYTES,
            "worker_full_sha_after_parent_reservation": True,
            "worker_pre_post_stat_and_fd_identity": True,
            "parent_deferred_hash_not_claimed": True,
            "payload_read_by_builder": False,
            "decoder": False,
            "solver": False,
        },
        "producer_binding": producer,
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": "parent-v8-audit",
            "cpu_parent_binding": "required",
            "payload_read": "one complete dp=.003 generated BI4 stream only",
            "solver_launch": "forbidden",
        },
        "qualification_stage": "stage2_f3_s2_fine_bi4_source_snapshot_pending_parent_guard",
        "scientific_qualification": {
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "reason": "immutable source SHA/stat closure only; no decoder or scientific qualification",
        },
    }
    payload["sha256"] = canonical(payload)
    return payload


def write_once(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable request: {path}")
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
    if EXPECTED_BYTES != 48_183_300:
        raise AssertionError("dp=.003 BI4 byte binding changed")
    if not str(PYTHON).endswith("/.venv/bin/python"):
        raise AssertionError("literal venv binding changed")
    if "worker/generated/" not in str(FINE_BI4):
        raise AssertionError("fine generated BI4 path contract changed")
    return {
        "status": "PASS",
        "schema": SCHEMA,
        "variant_schema": VARIANT,
        "builder_reads_bi4": False,
        "worker_hashes_after_reservation": True,
        "strict_q_receipt_join": True,
        "solver_started": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build-request", action="store_true")
    parser.add_argument("--output", type=Path, default=LOCAL_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-fine-dp003-bi4-source-snapshot-root-169.json")
    parser.add_argument("--launch-commit")
    parser.add_argument("--case-id", default="F3_S2_FINE_DP003_BI4_SOURCE_SNAPSHOT_ROOT169")
    parser.add_argument("--attempt-id", default="f3-s2-fine-dp003-bi4-source-snapshot-root-169-001")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    if not args.launch_commit:
        parser.error("--build-request requires --launch-commit")
    payload = build(args)
    write_once(args.output, payload)
    print(json.dumps({"status": payload["status"], "output": str(args.output.expanduser().resolve()), "bi4_read_by_builder": False, "expected_bytes": EXPECTED_BYTES}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
