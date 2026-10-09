#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Guarded one-stream source snapshot for the F3-S2 dp=.003 BI4.

This worker is a forward-only fine-grid specialization of the consumed
ROOT132 single-file stream guard.  It validates the exact ROOT102
GenCase-request/receipt join, then streams exactly one generated BI4 after the
parent reservation.  The worker records the complete SHA and path/fd stat
identity before and after the stream.  It does not decode BI4, read VTK/HDF5,
start GenCase, or start a solver.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from stage2_f3_s2_generated_bi4_snapshot_v1 import stream_source


SCHEMA = "ds02.stage2.f3.s2.fine-bi4-source-snapshot.v1"
REQUEST_SCHEMAS = {"ds02.request.v1", "ds02.runner-request.v1"}
PASS_STATUS = "PASS_F3_S2_FINE_BI4_HASHED_STABLE"
FAIL_STATUS = "FAILED_F3_S2_FINE_BI4_SOURCE_GUARD"
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
EXPECTED_BI4_NAME = "F3_S2_P1200_AY0750_DP003_MATCHED.bi4"
EXPECTED_BYTES = 48_183_300


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    return path


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


def write_once(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    encoded = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)
    os.replace(temporary, path)


def producer_join(q_path: Path, receipt_path: Path) -> dict[str, Any]:
    """Join the actual ROOT102 request and receipt before touching the BI4."""

    q_path = regular(q_path, "ROOT102 GenCase request")
    receipt_path = regular(receipt_path, "ROOT102 GenCase receipt")
    q = load_json(q_path, "ROOT102 GenCase request")
    receipt = load_json(receipt_path, "ROOT102 GenCase receipt")
    scope = q.get("scope") if isinstance(q.get("scope"), dict) else {}
    family = q.get("family_id") or scope.get("family_id")
    sentinel = q.get("sentinel_id") or scope.get("sentinel_id")
    physical = q.get("physical_case_id") or scope.get("physical_case_id")
    if q.get("schema") not in REQUEST_SCHEMAS:
        raise ValueError(f"ROOT102 request schema unsupported: {q.get('schema')!r}")
    if family != "F3" or sentinel not in {None, "F3-S2"} or physical != PHYSICAL_CASE_ID:
        raise ValueError("ROOT102 request physical identity mismatch")
    if str(receipt.get("status", "")).lower() not in {"completed", "complete", "success", "completed0"}:
        raise ValueError("ROOT102 receipt is not terminal completed")
    if receipt.get("returncode") not in (0, None):
        raise ValueError(f"ROOT102 receipt returncode is not zero: {receipt.get('returncode')!r}")
    actual_request = receipt.get("request")
    if actual_request != q:
        raise ValueError("ROOT102 receipt.request is not exactly the supplied request")
    q_sha = sha256(q_path)
    if receipt.get("request_sha256") != q_sha:
        raise ValueError("ROOT102 receipt.request_sha256 does not match the supplied request")
    output_root = Path(str(receipt.get("output_root", ""))).expanduser().resolve()
    if not output_root.is_dir():
        raise FileNotFoundError(f"ROOT102 receipt output root is missing: {output_root}")
    return {
        "q_path": str(q_path),
        "q_sha256": q_sha,
        "receipt_path": str(receipt_path),
        "receipt_sha256": sha256(receipt_path),
        "receipt_request_exact_q": True,
        "receipt_request_sha256_exact_q": True,
        "actual_receipt_output_root": str(output_root),
        "receipt_status": receipt.get("status"),
        "receipt_returncode": receipt.get("returncode"),
        "source_request_case_id": q.get("case_id"),
        "source_request_attempt_id": q.get("attempt_id"),
        "receipt_request_case_id": actual_request.get("case_id"),
        "receipt_request_attempt_id": actual_request.get("attempt_id"),
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    join = producer_join(args.gencase_request, args.receipt)
    source = regular(args.input_bi4, "ROOT102 generated fine BI4")
    actual_root = Path(join["actual_receipt_output_root"])
    expected_path = actual_root / "worker" / "generated" / EXPECTED_BI4_NAME
    if source != expected_path:
        raise ValueError(f"ROOT102 fine BI4 path mismatch: expected {expected_path}, got {source}")
    if int(args.expected_bytes) != EXPECTED_BYTES:
        raise ValueError(f"fine BI4 expected byte binding changed: {args.expected_bytes}")

    result: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "FAILED_BEFORE_SOURCE_READ",
        "family_id": "F3",
        "sentinel_id": "F3-S2",
        "physical_case_id": PHYSICAL_CASE_ID,
        "producer_join": join,
        "source": {
            "path": str(source),
            "expected_bytes": EXPECTED_BYTES,
            "content_sha256": "NOT_COMPUTED_ON_FAILURE",
        },
        "worker_scope": {
            "single_generated_fine_bi4": True,
            "full_payload_streamed": False,
            "passes": 1,
            "estimated_single_stream_read_bytes": EXPECTED_BYTES,
            "estimated_peak_buffer_bytes": 1024 * 1024,
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
        source_record = stream_source(source, EXPECTED_BYTES)
        result["status"] = PASS_STATUS
        result["source"] = {**result["source"], **source_record, "content_sha256": source_record["sha256"]}
        result["worker_scope"]["full_payload_streamed"] = True
    except BaseException as exc:
        result["status"] = FAIL_STATUS
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
        result["failure_is_scientific_unknown"] = True
        write_once(args.output, result)
        raise
    write_once(args.output, result)
    return result


def self_test() -> dict[str, Any]:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="f3-fine-bi4-snapshot-") as directory:
        root = Path(directory)
        producer = root / "producer" / "worker" / "generated"
        producer.mkdir(parents=True)
        source = producer / EXPECTED_BI4_NAME
        # Keep the production byte contract active in the self-test.  A sparse
        # fixture avoids allocating a 48 MB Python bytes object, while the
        # stream guard still consumes exactly the production-sized payload.
        with source.open("wb") as handle:
            handle.truncate(EXPECTED_BYTES)
        q_path = root / "q.json"
        receipt_path = root / "receipt.json"
        output = root / "snapshot.json"
        q = {
            "schema": "ds02.runner-request.v1",
            "family_id": "F3",
            "sentinel_id": "F3-S2",
            "physical_case_id": PHYSICAL_CASE_ID,
            "case_id": "SELF_CASE",
            "attempt_id": "SELF_ATTEMPT",
        }
        q_path.write_text(json.dumps(q, sort_keys=True) + "\n", encoding="utf-8")
        receipt_path.write_text(
            json.dumps(
                {
                    "status": "completed",
                    "returncode": 0,
                    "request": q,
                    "request_sha256": sha256(q_path),
                    "output_root": str(root / "producer"),
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        report = build_report(
            argparse.Namespace(
                gencase_request=q_path,
                receipt=receipt_path,
                input_bi4=source,
                expected_bytes=EXPECTED_BYTES,
                output=output,
            )
        )
        if report["status"] != PASS_STATUS or report["source"]["stat_before"] != report["source"]["stat_after"]:
            raise AssertionError(report)
    return {
        "status": "PASS",
        "schema": SCHEMA,
        "full_fd_stream": True,
        "strict_q_receipt_join": True,
        "pre_post_identity": True,
        "payload_read_by_self_test_only": True,
        "solver_started": False,
    }


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
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    if any(value is None for value in (args.gencase_request, args.receipt, args.input_bi4, args.output)):
        parser.error("--gencase-request, --receipt, --input-bi4 and --output are required")
    try:
        result = build_report(args)
    except BaseException as exc:
        print(json.dumps({"status": FAIL_STATUS, "error": str(exc)}, ensure_ascii=False), flush=True)
        return 1
    print(
        json.dumps(
            {
                "status": result["status"],
                "output": str(args.output.expanduser().resolve()),
                "sha256": result["source"]["sha256"],
                "bytes": result["source"]["bytes"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
