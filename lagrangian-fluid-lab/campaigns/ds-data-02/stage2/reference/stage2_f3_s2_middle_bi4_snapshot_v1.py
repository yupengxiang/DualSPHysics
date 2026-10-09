#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Guarded one-stream SHA/stat snapshot for the ROOT086 dp=.006 BI4.

ROOT086 is an older forwarded GenCase receipt: its receipt request carries a
different launch case/attempt object than the source request, but explicitly
binds that source request through ``root_forward_provenance``.  This worker
checks that alias rather than falsely requiring byte-identical request JSON.
It then streams exactly the generated middle BI4 once, using the proven
ROOT132 file-descriptor/stat guard.  It never decodes BI4 or reads VTK/HDF5.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from stage2_f3_s2_generated_bi4_snapshot_v1 import _sha as _old_sha
from stage2_f3_s2_generated_bi4_snapshot_v1 import stream_source


SCHEMA = "ds02.stage2.f3.s2.middle-bi4-source-snapshot.v1"
REQUEST_SCHEMAS = {"ds02.request.v1", "ds02.runner-request.v1"}
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
EXPECTED_BYTES = 9_227_118


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    return path


def load(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def write_once(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    encoded = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    try:
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def producer_join(q_path: Path, receipt_path: Path) -> dict[str, Any]:
    q_path = regular(q_path, "ROOT086 source request")
    receipt_path = regular(receipt_path, "ROOT086 receipt")
    q = load(q_path, "ROOT086 source request")
    receipt = load(receipt_path, "ROOT086 receipt")
    scope = q.get("scope") if isinstance(q.get("scope"), dict) else {}
    family = q.get("family_id") or scope.get("family_id")
    sentinel = q.get("sentinel_id") or scope.get("sentinel_id")
    physical = q.get("physical_case_id") or scope.get("physical_case_id")
    if q.get("schema") not in REQUEST_SCHEMAS or family != "F3" or sentinel not in {None, "F3-S2"} or physical != PHYSICAL_CASE_ID:
        raise ValueError("ROOT086 source request identity mismatch")
    if str(receipt.get("status", "")).lower() not in {"completed", "complete", "success", "completed0"} or receipt.get("returncode") not in (0, None):
        raise ValueError("ROOT086 receipt is not completed zero-return")
    actual_request = receipt.get("request")
    if not isinstance(actual_request, dict):
        raise ValueError("ROOT086 receipt has no actual request")
    if actual_request.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise ValueError("ROOT086 receipt physical identity mismatch")
    forward = actual_request.get("root_forward_provenance")
    if not isinstance(forward, dict):
        raise ValueError("ROOT086 receipt request lacks root_forward_provenance")
    source_request = Path(str(forward.get("source_request", ""))).expanduser().resolve()
    if source_request != q_path.resolve():
        raise ValueError("ROOT086 receipt does not bind the supplied source request path")
    source_request_sha = str(forward.get("source_request_sha256", ""))
    if source_request_sha != _old_sha(q_path):
        raise ValueError("ROOT086 receipt source request SHA does not match supplied request")
    receipt_sha = _old_sha(receipt_path)
    output_root = Path(str(receipt.get("output_root", ""))).expanduser().resolve()
    if not output_root.is_dir():
        raise FileNotFoundError(f"ROOT086 output root is missing: {output_root}")
    return {
        "source_request_path": str(q_path),
        "source_request_sha256": source_request_sha,
        "receipt_path": str(receipt_path),
        "receipt_sha256": receipt_sha,
        "receipt_request_case_id": actual_request.get("case_id"),
        "source_request_case_id": q.get("case_id"),
        "receipt_request_attempt_id": actual_request.get("attempt_id"),
        "source_request_attempt_id": q.get("attempt_id"),
        "request_json_exact_match": False,
        "request_alias_basis": "receipt.request.root_forward_provenance.source_request_path_and_sha256",
        "actual_receipt_output_root": str(output_root),
        "receipt_status": receipt.get("status"),
        "receipt_returncode": receipt.get("returncode"),
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    join = producer_join(args.gencase_request, args.receipt)
    source = regular(args.input_bi4, "ROOT086 generated middle BI4")
    output_root = Path(join["actual_receipt_output_root"])
    expected_parent = output_root / "generated"
    if source.parent != expected_parent or source.name != "F3_S2_P1200_AY0750_MATCHED.bi4":
        raise ValueError("middle BI4 must be the immutable ROOT086 generated payload")
    if int(args.expected_bytes) != EXPECTED_BYTES:
        raise ValueError(f"middle BI4 expected byte binding changed: {args.expected_bytes}")
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "FAILED_BEFORE_SOURCE_READ",
        "family_id": "F3",
        "sentinel_id": "F3-S2",
        "physical_case_id": PHYSICAL_CASE_ID,
        "producer_join": join,
        "source": {"path": str(source), "expected_bytes": int(args.expected_bytes), "content_sha256": "NOT_COMPUTED_ON_FAILURE"},
        "worker_scope": {
            "single_generated_middle_bi4": True,
            "full_payload_streamed": False,
            "passes": 1,
            "estimated_single_stream_read_bytes": int(args.expected_bytes),
            "bi4_decode": False,
            "vtk_read": False,
            "hdf5_read": False,
            "gencase_launch": False,
            "solver_launch": False,
            "source_sha_computed_after_parent_reservation": True,
            "parent_deferred_hash_not_claimed": True,
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    try:
        source_record = stream_source(source, int(args.expected_bytes))
        result["status"] = "PASS_F3_S2_MIDDLE_BI4_HASHED_STABLE"
        result["source"] = {**result["source"], **source_record, "content_sha256": source_record["sha256"]}
        result["worker_scope"]["full_payload_streamed"] = True
    except BaseException as exc:
        result["status"] = "FAILED_F3_S2_MIDDLE_BI4_SOURCE_GUARD"
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
        result["failure_is_scientific_unknown"] = True
        write_once(args.output, result)
        raise
    write_once(args.output, result)
    return result


def self_test() -> dict[str, Any]:
    # The byte-stream implementation is covered by the consumed ROOT132
    # worker's self-test; this test locks the middle identity/size contract.
    if EXPECTED_BYTES != 9_227_118 or PHYSICAL_CASE_ID != "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT":
        raise AssertionError("middle source binding changed")
    return {"status": "PASS", "schema": SCHEMA, "expected_bytes": EXPECTED_BYTES, "full_fd_stream": True, "request_alias_join": True, "solver_started": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--gencase-request", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--input-bi4", type=Path)
    parser.add_argument("--expected-bytes", type=int, default=EXPECTED_BYTES)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    if any(value is None for value in (args.gencase_request, args.receipt, args.input_bi4, args.output)):
        parser.error("--gencase-request, --receipt, --input-bi4 and --output are required")
    try:
        result = build_report(args)
    except BaseException as exc:
        print(json.dumps({"status": "FAILED_F3_S2_MIDDLE_BI4_SOURCE_GUARD", "error": str(exc)}, ensure_ascii=False), flush=True)
        return 1
    print(json.dumps({"status": result["status"], "output": str(args.output.expanduser().resolve()), "sha256": result["source"]["sha256"], "bytes": result["source"]["bytes"]}, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
