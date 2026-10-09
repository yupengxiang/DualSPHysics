#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Bind the F3-S2 external request to a completed ROOT120 BI4 snapshot.

This is an additive adapter over the consumed V6 request builder.  The
builder reads only the small snapshot JSON; it never opens or hashes the
generated BI4.  A parent-v8 source-snapshot worker must first stream that
single BI4 and emit a stable full SHA.  The resulting external request then
uses that worker-owned SHA as the expected materializer input and records the
snapshot JSON as its small source-provenance input.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
V6_REQUEST = HERE / "stage2_f3_s2_external_solver_v6_request.py"
V6 = None


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V6 = load_module("stage2_f3_external_solver_v6_for_snapshot_v7", V6_REQUEST)

REQUEST_SCHEMA = "ds02.stage2.external-solver-request.v5"
VARIANT_SCHEMA = "ds02.stage2.f3.s2.external-solver-request.v7-bi4-snapshot"
SNAPSHOT_SCHEMA = "ds02.stage2.f3-s2.generated-bi4-source-snapshot.v1"
SNAPSHOT_STATUS = "PASS_F3_GENERATED_BI4_HASHED_STABLE"
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
HEX64 = re.compile(r"^[0-9a-f]{64}$")


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


def load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def small_record(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
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
        "content_scope": "small_snapshot_json_hashed_by_builder_and_parent",
        "content_read_by_builder": True,
    }


def _same_stat(left: Any, right: Any) -> bool:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    keys = ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino", "st_mode")
    return all(left.get(key) == right.get(key) for key in keys)


def validate_snapshot(snapshot_path: Path, gencase_request: Path, receipt: Path, generated_bi4: Path) -> dict[str, Any]:
    snapshot_path = regular(snapshot_path, "F3 generated BI4 snapshot")
    snapshot = load_json(snapshot_path, "F3 generated BI4 snapshot")
    if snapshot.get("schema") != SNAPSHOT_SCHEMA:
        raise ValueError(f"BI4 snapshot schema mismatch: {snapshot.get('schema')!r}")
    if snapshot.get("status") != SNAPSHOT_STATUS:
        raise ValueError(f"BI4 snapshot is not terminal: {snapshot.get('status')!r}")
    if snapshot.get("family_id") != "F3" or snapshot.get("sentinel_id") != "F3-S2" or snapshot.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise ValueError("BI4 snapshot physical identity mismatch")

    q_path = regular(gencase_request, "ROOT120 GenCase request")
    receipt_path = regular(receipt, "ROOT120 receipt")
    source_path = regular(generated_bi4, "ROOT120 generated BI4")
    producer_join = snapshot.get("producer_join")
    if not isinstance(producer_join, dict):
        raise ValueError("BI4 snapshot has no producer join")
    expected_q_sha = sha256(q_path)
    if producer_join.get("q_path") != str(q_path) or producer_join.get("q_sha256") != expected_q_sha:
        raise ValueError("BI4 snapshot q path/SHA does not match supplied ROOT120 request")
    if producer_join.get("receipt_path") != str(receipt_path) or producer_join.get("receipt_request_exact_q") is not True or producer_join.get("receipt_request_sha256_exact_q") is not True:
        raise ValueError("BI4 snapshot receipt join is not exact")
    source = snapshot.get("source")
    if not isinstance(source, dict):
        raise ValueError("BI4 snapshot source record is missing")
    if source.get("path") != str(source_path):
        raise ValueError("BI4 snapshot source path does not match generated BI4")
    content_sha = source.get("content_sha256") or source.get("sha256")
    if not isinstance(content_sha, str) or HEX64.fullmatch(content_sha) is None:
        raise ValueError("BI4 snapshot has no valid full content SHA")
    if source.get("sha256") not in (None, content_sha):
        raise ValueError("BI4 snapshot content SHA aliases disagree")
    if source.get("stat_before") != source.get("stat_after") or not _same_stat(source.get("stat_before"), source.get("stat_after")):
        raise ValueError("BI4 snapshot source stat changed during stream")
    if source.get("fd_stat_before") != source.get("fd_stat_after") or not _same_stat(source.get("fd_stat_before"), source.get("fd_stat_after")):
        raise ValueError("BI4 snapshot open-file stat changed during stream")
    if source.get("pre_post_identity") != "PASS_BYTES_MTIME_CTIME_DEVICE_INODE_MODE_EQUAL":
        raise ValueError("BI4 snapshot did not record the required pre/post identity proof")
    if snapshot.get("worker_scope", {}).get("full_payload_streamed") is not True:
        raise ValueError("BI4 snapshot did not stream the complete payload")
    return {
        "path": str(snapshot_path),
        "sha256": sha256(snapshot_path),
        "schema": SNAPSHOT_SCHEMA,
        "status": SNAPSHOT_STATUS,
        "source_path": str(source_path),
        "source_bytes": source.get("bytes"),
        "source_sha256": content_sha,
        "source_stat_pre_post_equal": True,
        "worker_full_stream": True,
        "producer_join": producer_join,
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    snapshot_binding = None
    if args.bi4_snapshot is not None:
        snapshot_binding = validate_snapshot(args.bi4_snapshot, args.gencase_request, args.receipt, args.generated_bi4)
        generated_sha = snapshot_binding["source_sha256"]
    else:
        generated_sha = args.generated_bi4_sha256
        if not isinstance(generated_sha, str) or HEX64.fullmatch(generated_sha) is None:
            raise ValueError("one of --bi4-snapshot or an explicit lowercase --generated-bi4-sha256 is required")
    staging = args.output.with_name(f".{args.output.name}.{os.getpid()}.v7-staging.json")
    adapted = argparse.Namespace(**vars(args))
    adapted.output = staging
    adapted.generated_bi4_sha256 = generated_sha
    V6.build(adapted)
    request = load_json(staging, "staged external solver v6 request")
    staging.unlink(missing_ok=True)
    if request.get("schema") != REQUEST_SCHEMA:
        raise ValueError("delegated external request schema changed")
    request["request_variant_schema"] = VARIANT_SCHEMA
    request["status"] = "READY_FOR_PARENT_EXTERNAL_V5_F3_COARSE_AFTER_ROOT128_SUPPORT_AND_BI4_SNAPSHOT"
    request["source_provenance"] = dict(request.get("source_provenance", {}))
    if snapshot_binding is not None:
        snapshot_record = small_record(args.bi4_snapshot, "F3 generated BI4 source snapshot")
        request["input_files"] = sorted(set(list(request.get("input_files", [])) + [snapshot_record["path"]]))
        request["input_sha256"] = dict(request.get("input_sha256", {}))
        request["input_sha256"][snapshot_record["path"]] = snapshot_record["sha256"]
        request["input_content_scope"] = dict(request.get("input_content_scope", {}))
        request["input_content_scope"][snapshot_record["path"]] = snapshot_record["content_scope"]
        request["source_provenance"]["generated_bi4_snapshot"] = snapshot_binding
        request["bi4_snapshot_binding"] = {
            "snapshot_json": snapshot_record,
            "source_path": snapshot_binding["source_path"],
            "source_sha256": snapshot_binding["source_sha256"],
            "worker_full_stream_and_stable_stat": True,
            "bi4_payload_read_by_this_builder": False,
        }
    request["qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    request["physical_qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "source-bound coarse development canary; BI4 source SHA is parent snapshot evidence, not scientific qualification"}
    request["sha256"] = hashlib.sha256(json.dumps({key: value for key, value in request.items() if key != "sha256"}, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()).hexdigest()
    return request


def write_new(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse overwrite: {path}")
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
    # Validate the snapshot contract without a producer, payload read, or solver.
    import tempfile

    with tempfile.TemporaryDirectory(prefix="f3-v7-snapshot-") as directory:
        root = Path(directory)
        q = root / "q.json"
        receipt = root / "receipt.json"
        bi4 = root / "generated.bi4"
        snapshot = root / "snapshot.json"
        q_value = {"schema": "ds02.request.v1", "family_id": "F3", "sentinel_id": "F3-S2", "physical_case_id": PHYSICAL_CASE_ID}
        q.write_text(json.dumps(q_value, sort_keys=True) + "\n", encoding="utf-8")
        bi4.write_bytes(b"fixture")
        receipt.write_text(json.dumps({"request": q_value, "request_sha256": sha256(q), "receipt_path": str(receipt), "q_path": str(q), "output_root": str(root), "status": "completed", "returncode": 0}, sort_keys=True) + "\n", encoding="utf-8")
        stat = bi4.stat()
        stat_value = {"bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "ctime_ns": stat.st_ctime_ns, "st_dev": stat.st_dev, "st_ino": stat.st_ino, "st_mode": stat.st_mode}
        source = {"path": str(bi4), "bytes": stat.st_size, "sha256": sha256(bi4), "content_sha256": sha256(bi4), "stat_before": stat_value, "stat_after": stat_value, "fd_stat_before": stat_value, "fd_stat_after": stat_value, "pre_post_identity": "PASS_BYTES_MTIME_CTIME_DEVICE_INODE_MODE_EQUAL"}
        snapshot.write_text(json.dumps({"schema": SNAPSHOT_SCHEMA, "status": SNAPSHOT_STATUS, "family_id": "F3", "sentinel_id": "F3-S2", "physical_case_id": PHYSICAL_CASE_ID, "producer_join": {"q_path": str(q), "q_sha256": sha256(q), "receipt_path": str(receipt), "receipt_request_exact_q": True, "receipt_request_sha256_exact_q": True}, "source": source, "worker_scope": {"full_payload_streamed": True}}, sort_keys=True) + "\n", encoding="utf-8")
        result = validate_snapshot(snapshot, q, receipt, bi4)
        if result["source_sha256"] != sha256(bi4):
            raise AssertionError(result)
        broken = json.loads(snapshot.read_text(encoding="utf-8")); broken["source"]["stat_after"]["bytes"] += 1
        snapshot.write_text(json.dumps(broken), encoding="utf-8")
        try:
            validate_snapshot(snapshot, q, receipt, bi4)
        except ValueError:
            pass
        else:
            raise AssertionError("changed-stat snapshot was accepted")
    return {"status": "PASS", "schema": REQUEST_SCHEMA, "request_variant_schema": VARIANT_SCHEMA, "snapshot_required_or_explicit_sha": True, "bi4_read_by_builder": False, "solver_started": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build-request", action="store_true")
    for name in ("gencase-request", "receipt", "generated-xml", "generated-bi4", "support-report", "source-xml", "source-control", "output", "bi4-snapshot"):
        parser.add_argument(f"--{name}", type=Path)
    parser.add_argument("--generated-bi4-sha256")
    parser.add_argument("--cost-basis-receipt", type=Path)
    parser.add_argument("--launch-commit")
    parser.add_argument("--case-id", default="F3_S2_OWNER_CENTERED_DP015_FULL_CFD_CANARY_ROOT128")
    parser.add_argument("--attempt-id", default="f3-s2-owner-centered-dp015-full-cfd-canary-v7-root128-001")
    parser.add_argument("--external-filesystem", default="/var/tmp/ds02-stage2")
    parser.add_argument("--external-reserve-bytes", type=int, default=2 * 1024**3)
    parser.add_argument("--home-receipt-reserve-bytes", type=int, default=8 * 1024**2)
    parser.add_argument("--max-wall-seconds", type=float, default=1800.0)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    required = [args.gencase_request, args.receipt, args.generated_xml, args.generated_bi4, args.support_report, args.output, args.launch_commit]
    if any(value is None for value in required) or (args.bi4_snapshot is None and args.generated_bi4_sha256 is None):
        parser.error("--build-request requires ROOT120 q/receipt/XML/BI4, ROOT128 support, output, launch commit, and either --bi4-snapshot or --generated-bi4-sha256")
    request = build(args)
    write_new(args.output, request)
    print(json.dumps({"status": request["status"], "schema": REQUEST_SCHEMA, "request_variant_schema": VARIANT_SCHEMA, "output": str(args.output.resolve()), "solver_started": False, "bi4_read": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
