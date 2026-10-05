#!/usr/bin/env python3
"""Strict CPU opaque-artifact audit for the old P03 full401 conversion.

The worker is intended for a fresh Root-owned ``audit`` attempt. It never
edits the source conversion receipt, never changes a ledger, and never decodes
particle arrays. A successful worker returncode is deliberately separate from
the old converter's unknown child returncode and running receipt.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any


SCHEMA = "ds02.strict-cpu.typed-artifact-integrity.v1"


class AuditError(ValueError):
    pass


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AuditError(f"JSON object required: {path}")
    return value


def write_new_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        offset = 0
        while offset < len(data):
            offset += os.write(fd, data[offset:])
        os.fsync(fd)
    finally:
        os.close(fd)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def audit(*, receipt_path: Path, report_path: Path, stdout_path: Path,
          trajectory_path: Path, expected_receipt_sha256: str,
          expected_report_sha256: str, expected_output_sha256: str,
          old_tool_status: int) -> dict[str, Any]:
    if old_tool_status != 143:
        raise AuditError("old launcher tool status must remain separately recorded as 143")
    receipt_raw = receipt_path.read_bytes()
    report_raw = report_path.read_bytes()
    if hashlib.sha256(receipt_raw).hexdigest() != expected_receipt_sha256:
        raise AuditError("old conversion receipt changed")
    if hashlib.sha256(report_raw).hexdigest() != expected_report_sha256:
        raise AuditError("conversion report changed")
    receipt = load_json(receipt_path)
    report = load_json(report_path)
    if receipt.get("status") != "running" or receipt.get("returncode") is not None:
        raise AuditError("old conversion lifecycle is no longer the bound unknown state")
    if report.get("conversion_status") != "completed":
        raise AuditError("existing conversion report is not completed")
    if report.get("frames") != 401 or report.get("particles") != 418104:
        raise AuditError("existing report does not bind P03 full401 facts")
    if report.get("partvtk_validation", {}).get("all_passed") is not True:
        raise AuditError("existing PartVTK validation is not all_passed")
    if report.get("output_sha256") != expected_output_sha256:
        raise AuditError("report output hash differs from request")
    if report.get("storage_protocol", {}).get("verified_published_output_sha256") != expected_output_sha256:
        raise AuditError("report published output hash is not closed")
    stdout = stdout_path.read_text(encoding="utf-8")
    if expected_output_sha256 not in stdout:
        raise AuditError("stdout does not carry the published output hash")
    if not trajectory_path.is_file():
        raise AuditError("opaque trajectory artifact is missing")
    actual_output_sha256 = sha256(trajectory_path)
    if actual_output_sha256 != expected_output_sha256:
        raise AuditError("opaque trajectory hash differs from report")
    return {
        "schema": SCHEMA,
        "artifact_integrity_status": "completed",
        "worker_returncode": 0,
        "finished_at_utc": now_utc(),
        "source_conversion_attempt": receipt.get("request", {}).get("attempt_id"),
        "source_receipt_status": receipt.get("status"),
        "source_receipt_returncode": receipt.get("returncode"),
        "source_os_exit_zero": False,
        "source_tool_status": old_tool_status,
        "source_receipt_sha256": expected_receipt_sha256,
        "source_report_sha256": expected_report_sha256,
        "verified_trajectory_sha256": actual_output_sha256,
        "verified_frames": report["frames"],
        "verified_particles": report["particles"],
        "partvtk_all_passed": True,
        "opaque_hash_only": True,
        "source_conversion_reclassified": False,
        "production_approval": "none",
        "q_n": "not_granted",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--stdout", type=Path, required=True)
    parser.add_argument("--trajectory-h5", type=Path, required=True)
    parser.add_argument("--expected-receipt-sha256", required=True)
    parser.add_argument("--expected-report-sha256", required=True)
    parser.add_argument("--expected-output-sha256", required=True)
    parser.add_argument("--old-tool-status", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(receipt_path=args.receipt, report_path=args.report,
                   stdout_path=args.stdout, trajectory_path=args.trajectory_h5,
                   expected_receipt_sha256=args.expected_receipt_sha256,
                   expected_report_sha256=args.expected_report_sha256,
                   expected_output_sha256=args.expected_output_sha256,
                   old_tool_status=args.old_tool_status)
    write_new_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
