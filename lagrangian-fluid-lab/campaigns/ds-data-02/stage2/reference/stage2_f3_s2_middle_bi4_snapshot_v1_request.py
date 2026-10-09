#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build the parent-v8 source snapshot request for ROOT086 middle BI4."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any


PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
LOCAL_REPO = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
SCHEMA = "ds02.request.v1"
VARIANT = "ds02.stage2.f3.s2.middle-bi4-source-snapshot-request.v1"
EXPECTED_BYTES = 9_227_118

MIDDLE_ROOT = DATA_ROOT / "families/F3/F3_S2_P1200_AY0750_MATCHED_SOURCE_GENCASE_ROOT_086/f3-s2-source-clone-gencase-v1-root-086-001-root-forward-030-001"
MIDDLE_RECEIPT = MIDDLE_ROOT / "execution-receipt.json"
MIDDLE_BI4 = MIDDLE_ROOT / "generated/F3_S2_P1200_AY0750_MATCHED.bi4"
SOURCE_Q = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-source-clone-gencase-v1-root-forward-082-001/f3-s2-source-clone-gencase-v1-request.json"
WORKER = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_middle_bi4_snapshot_v1.py"
OLD_STREAM_WORKER = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_generated_bi4_snapshot_v1.py"
SOURCE_CARD = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-middle-external-v5-source-card-v1.json"
RUNTIME_V2 = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
RUNTIME_V6 = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py"
RUNTIME_V8 = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
BATCH = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_batch_runner.py"
DISPATCH = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"

# The parent tree may not contain these newly delivered files until the
# additive commit is cherry-picked.  During local validation use the exact
# files beside this builder; the generated parent request will still point at
# PRIMARY_REPO after integration.  This fallback never reads the deferred BI4.
LOCAL_WORKER = LOCAL_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_middle_bi4_snapshot_v1.py"
LOCAL_OLD_STREAM_WORKER = LOCAL_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_generated_bi4_snapshot_v1.py"
LOCAL_SOURCE_CARD = LOCAL_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-middle-external-v5-source-card-v1.json"


def primary_or_local(primary: Path, local: Path, label: str) -> Path:
    """Resolve a newly delivered source without weakening its file contract."""
    if primary.is_file() and not primary.is_symlink():
        return primary
    if local.is_file() and not local.is_symlink():
        return local
    raise FileNotFoundError(f"{label}: neither primary nor local source exists")


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with regular(path, "hash input").open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record_literal(path: Path, label: str) -> dict[str, Any]:
    """Record the venv under its literal argv path, preserving the ABI binding."""
    path = path.expanduser()
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
        "content_scope": "small_input_hashed_by_builder_and_parent_v8",
    }


def record(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    stat = path.stat()
    return {"path": str(path), "label": label, "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "ctime_ns": int(stat.st_ctime_ns), "st_dev": int(stat.st_dev), "st_ino": int(stat.st_ino), "sha256": sha256(path), "content_scope": "small_input_hashed_by_builder_and_parent_v8"}


def stat_record(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    stat = path.stat()
    return {"path": str(path), "label": label, "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "ctime_ns": int(stat.st_ctime_ns), "st_dev": int(stat.st_dev), "st_ino": int(stat.st_ino), "sha256": "NOT_COMPUTED_BY_BUILDER_OR_PARENT_V8", "content_scope": "parent_worker_after_reservation_full_stream"}


def load(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def validate_source() -> dict[str, Any]:
    q = load(SOURCE_Q, "ROOT086 source request")
    receipt = load(MIDDLE_RECEIPT, "ROOT086 receipt")
    scope = q.get("scope") if isinstance(q.get("scope"), dict) else {}
    if q.get("schema") not in {"ds02.request.v1", "ds02.runner-request.v1"} or (q.get("family_id") or scope.get("family_id")) != "F3" or (q.get("sentinel_id") or scope.get("sentinel_id")) not in {None, "F3-S2"} or (q.get("physical_case_id") or scope.get("physical_case_id")) != PHYSICAL_CASE_ID:
        raise ValueError("ROOT086 source request identity mismatch")
    actual = receipt.get("request")
    if not isinstance(actual, dict) or actual.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise ValueError("ROOT086 receipt request identity mismatch")
    forward = actual.get("root_forward_provenance")
    if not isinstance(forward, dict) or Path(str(forward.get("source_request", ""))).expanduser().resolve() != SOURCE_Q.resolve() or str(forward.get("source_request_sha256")) != sha256(SOURCE_Q):
        raise ValueError("ROOT086 receipt does not bind source request path/SHA")
    output_root = Path(str(receipt.get("output_root", ""))).expanduser().resolve()
    if output_root != MIDDLE_ROOT.resolve() or not output_root.is_dir():
        raise ValueError("ROOT086 receipt output root differs")
    bi4 = regular(MIDDLE_BI4, "ROOT086 middle BI4")
    if bi4.parent != output_root / "generated" or bi4.name != "F3_S2_P1200_AY0750_MATCHED.bi4":
        raise ValueError("ROOT086 middle BI4 path differs")
    stat = bi4.stat()
    if int(stat.st_size) != EXPECTED_BYTES:
        raise ValueError("ROOT086 middle BI4 byte count changed")
    if str(receipt.get("status", "")).lower() not in {"completed", "complete", "success", "completed0"} or receipt.get("returncode") not in (0, None):
        raise ValueError("ROOT086 receipt is not completed zero-return")
    return {"q": q, "receipt": receipt, "output_root": str(output_root), "bi4": stat_record(bi4, "ROOT086 generated middle BI4")}


def canonical(value: dict[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False, default=str).encode()).hexdigest()


def build(args: argparse.Namespace) -> dict[str, Any]:
    source = validate_source()
    worker = primary_or_local(WORKER, LOCAL_WORKER, "middle BI4 snapshot worker")
    old_stream_worker = primary_or_local(OLD_STREAM_WORKER, LOCAL_OLD_STREAM_WORKER, "ROOT132 stream guard dependency")
    source_card = primary_or_local(SOURCE_CARD, LOCAL_SOURCE_CARD, "F3 middle source card")
    paths = [
        (SOURCE_Q, "ROOT086 source request"), (MIDDLE_RECEIPT, "ROOT086 receipt"),
        (worker, "middle BI4 snapshot worker"), (old_stream_worker, "ROOT132 stream guard dependency"),
        (source_card, "F3 middle source card"), (RUNTIME_V2, "runtime v2"), (RUNTIME_V6, "runtime v6"),
        (RUNTIME_V8, "runtime v8"), (BATCH, "batch runner"), (DISPATCH, "dispatch v8"), (STRICT, "strict dispatch v8"),
        (PYTHON, "literal venv interpreter"),
    ]
    records = {str(regular(path, label)): record(path, label) for path, label in paths if path != PYTHON}
    records[str(PYTHON)] = record_literal(PYTHON, "literal venv interpreter")
    worker_path = str(worker.resolve())
    q_path = str(SOURCE_Q.resolve())
    receipt_path = str(MIDDLE_RECEIPT.resolve())
    bi4_path = str(MIDDLE_BI4.resolve())
    command = [str(PYTHON), worker_path, "--gencase-request", q_path, "--receipt", receipt_path, "--input-bi4", bi4_path, "--expected-bytes", str(EXPECTED_BYTES), "--output", "{attempt_root}/native_source_snapshot.json"]
    files = sorted(records)
    expected = {path: records[path]["sha256"] for path in files}
    payload: dict[str, Any] = {
        "schema": SCHEMA, "variant_schema": VARIANT, "status": "READY_FOR_PARENT_V8_F3_MIDDLE_BI4_SOURCE_SNAPSHOT",
        "kind": "cpu", "cpu_task_kind": "audit", "family_id": "F3", "sentinel_id": "F3-S2", "physical_case_id": PHYSICAL_CASE_ID,
        "case_id": args.case_id, "attempt_id": args.attempt_id, "launch_commit": args.launch_commit,
        "cwd": str(PRIMARY_REPO / "lagrangian-fluid-lab"), "worktree_root": str(PRIMARY_REPO), "command": command,
        "input_files": files, "input_hashes": expected, "input_sha256": expected, "input_records": records,
        "deferred_input_files": [bi4_path], "deferred_input_stats": {bi4_path: source["bi4"]},
        "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 1800, "max_memory_bytes": 512 * 1024**2,
        "estimated_storage_bytes": 16 * 1024**2, "estimated_peak_memory_bytes": 128 * 1024**2,
        "estimated_input_read_bytes": sum(item["bytes"] for item in records.values()), "estimated_native_read_bytes": EXPECTED_BYTES,
        "estimated_bi4_read_bytes": EXPECTED_BYTES, "estimated_hdf5_read_bytes": 0,
        "execution_allowed": True, "launch_disabled": False, "solver_started": False, "gencase_launch": False, "solver_launch": False,
        "hdf5_read": False, "bi4_read": False, "output_root": "{attempt_root}",
        "output": {"atomic": True, "refuse_overwrite": True, "path": "{attempt_root}/native_source_snapshot.json"},
        "source_binding": {
            "schema": VARIANT, "root086_source_request_path": q_path, "root086_source_request_sha256": sha256(SOURCE_Q),
            "root086_receipt_path": receipt_path, "root086_receipt_sha256": sha256(MIDDLE_RECEIPT),
            "receipt_request_alias_join": "root_forward_provenance.source_request_path_and_sha256", "actual_receipt_output_root": source["output_root"],
            "generated_bi4_path": bi4_path, "expected_bytes": EXPECTED_BYTES, "worker_full_sha_after_reservation": True,
            "worker_pre_post_fd_and_complete_stat": True, "parent_deferred_hash_not_claimed": True, "decoder": False, "solver": False,
        },
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": "parent-v8-audit", "cpu_parent_binding": "required", "payload_read": "one complete middle BI4 stream only", "solver_launch": "forbidden"},
        "qualification_stage": "stage2_f3_s2_middle_bi4_source_snapshot_pending_parent_guard",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "source hash/stat closure only; no native decode or solver qualification"},
    }
    payload["sha256"] = canonical(payload)
    return payload


def write_once(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable request: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def self_test() -> dict[str, Any]:
    if EXPECTED_BYTES != 9_227_118 or not str(PYTHON).endswith("/.venv/bin/python"):
        raise AssertionError("middle snapshot binding changed")
    return {"status": "PASS", "schema": SCHEMA, "variant_schema": VARIANT, "builder_reads_bi4": False, "worker_hashes_after_reservation": True, "solver_started": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True); mode.add_argument("--self-test", action="store_true"); mode.add_argument("--build-request", action="store_true")
    parser.add_argument("--output", type=Path, default=LOCAL_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-middle-bi4-snapshot-v1-root161.json")
    parser.add_argument("--launch-commit", required=False)
    parser.add_argument("--case-id", default="F3_S2_MATCHED_MIDDLE_DP006_BI4_SOURCE_SNAPSHOT_ROOT161")
    parser.add_argument("--attempt-id", default="f3-s2-matched-middle-dp006-bi4-source-snapshot-root-161-001")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    if not args.launch_commit:
        parser.error("--build-request requires --launch-commit")
    payload = build(args); write_once(args.output, payload)
    print(json.dumps({"status": payload["status"], "output": str(args.output.resolve()), "bi4_read_by_builder": False, "expected_bytes": EXPECTED_BYTES}, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
