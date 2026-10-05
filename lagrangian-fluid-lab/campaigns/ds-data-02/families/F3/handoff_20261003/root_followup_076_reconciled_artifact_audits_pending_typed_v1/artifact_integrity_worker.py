#!/usr/bin/env python3
"""Root-owned opaque artifact integrity audit for a published typed result.

The audit is a new CPU fact.  It does not settle a converter reservation, edit
the old receipt, or turn an unknown converter child returncode into zero.  The
only payload operation is a bounded streaming SHA-256 of the opaque HDF5 file;
no HDF5 dataset is decoded and no numerical array is inspected.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any


SCHEMA = "ds02.strict-cpu.typed-artifact-integrity.v2"
SOURCE_RECEIPT_STATUSES = {"running", "interrupted_unfinalized"}


class AuditError(ValueError):
    """A source binding or an opaque artifact failed a strict check."""


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    """Hash a file as opaque bytes; never parse the payload."""
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


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def write_new_json(path: Path, value: dict[str, Any]) -> None:
    """Publish a new audit receipt without replacing an existing receipt."""
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


def audit(
    *,
    receipt_path: Path,
    report_path: Path,
    stdout_path: Path,
    trajectory_path: Path,
    native_receipt_path: Path,
    expected_receipt_sha256: str,
    expected_report_sha256: str,
    expected_native_receipt_sha256: str,
    expected_output_sha256: str,
    expected_report_physical_condition_sha256: str,
    expected_frames: int,
    expected_particles: int,
    physical_case_id: str,
    physical_condition_sha256: str,
    old_tool_status: int,
) -> dict[str, Any]:
    """Validate one exact published artifact binding.

    ``old_tool_status`` belongs to the prior launcher and is intentionally
    separate from this worker's eventual returncode.  In particular, a
    receipt with ``returncode: null`` remains null in the emitted audit.
    """
    _require(old_tool_status == 143, "old launcher tool status must remain recorded as 143")

    receipt_raw = receipt_path.read_bytes()
    report_raw = report_path.read_bytes()
    native_raw = native_receipt_path.read_bytes()
    _require(hashlib.sha256(receipt_raw).hexdigest() == expected_receipt_sha256,
             "old conversion receipt changed")
    _require(hashlib.sha256(report_raw).hexdigest() == expected_report_sha256,
             "published conversion report changed")
    _require(hashlib.sha256(native_raw).hexdigest() == expected_native_receipt_sha256,
             "canonical native receipt changed")

    receipt = load_json(receipt_path)
    report = load_json(report_path)
    native = load_json(native_receipt_path)
    _require(receipt.get("status") in SOURCE_RECEIPT_STATUSES,
             "source conversion receipt is outside the allowed lifecycle")
    _require(receipt.get("returncode") is None,
             "source conversion returncode must remain unknown/null")
    request = receipt.get("request", {})
    _require(isinstance(request, dict), "source conversion request must be an object")
    _require(request.get("physical_case_id") == physical_case_id,
             "source receipt physical case differs from binding")
    _require(request.get("physical_condition_sha256") == physical_condition_sha256,
             "source receipt physical condition differs from binding")
    request_frames = request.get("expected_saved_frames")
    if request_frames is None:
        request_frames = request.get("canonical_condition", {}).get("expected_saved_frames")
    if request_frames is None:
        request_frames = request.get("expected_native", {}).get("saved_frames")
    if request_frames is None:
        request_frames = request.get("expected_output", {}).get("frame_count")
    _require(request_frames == expected_frames,
             "source receipt frame expectation differs from binding")

    _require(report.get("conversion_status") == "completed",
             "published conversion report is not complete")
    _require(report.get("frames") == expected_frames,
             "published report frame count differs from binding")
    _require(report.get("particles") == expected_particles,
             "published report particle count differs from binding")
    _require(report.get("partvtk_validation", {}).get("all_passed") is True,
             "published PartVTK validation is not all_passed")
    _require(report.get("output_sha256") == expected_output_sha256,
             "report output hash differs from binding")
    _require(report.get("storage_protocol", {}).get("verified_published_output_sha256")
             == expected_output_sha256,
             "report published output hash is not closed")
    physical = report.get("hash_scopes", {}).get("physical_condition", {})
    _require(physical.get("physical_case_id") == physical_case_id,
             "report physical case differs from binding")
    _require(report.get("hash_scopes", {}).get("physical_condition_sha256")
             == expected_report_physical_condition_sha256,
             "report-internal physical-condition hash differs from binding")
    _require(report.get("output_hdf5") == str(trajectory_path),
             "report HDF5 path differs from binding")

    stdout = stdout_path.read_text(encoding="utf-8")
    _require(expected_output_sha256 in stdout,
             "conversion stdout does not carry the published output hash")

    _require(native.get("status") == "completed" and native.get("returncode") == 0,
             "canonical native receipt is not completed/0")
    native_request = native.get("request", {})
    _require(isinstance(native_request, dict), "canonical native request must be an object")
    _require(native_request.get("physical_case_id") == physical_case_id,
             "canonical native physical case differs from binding")
    _require(native_request.get("physical_condition_sha256") == physical_condition_sha256,
             "canonical native physical condition differs from binding")
    native_frames = native_request.get("expected_saved_frames")
    if native_frames is None:
        native_frames = native_request.get("expected_native", {}).get("saved_frames")
    if native_frames is None:
        native_frames = native_request.get("expected_output", {}).get("frame_count")
    _require(native_frames == expected_frames,
             "canonical native frame expectation differs from binding")

    _require(trajectory_path.is_file(), "published opaque trajectory artifact is missing")
    # This is deliberately the only operation on the large HDF5: Root's strict
    # CPU worker hashes it as opaque bytes and never decodes numerical arrays.
    actual_output_sha256 = sha256(trajectory_path)
    _require(actual_output_sha256 == expected_output_sha256,
             "opaque trajectory hash differs from published report")

    return {
        "schema": SCHEMA,
        "artifact_integrity_status": "completed",
        "worker_returncode": 0,
        "finished_at_utc": now_utc(),
        "physical_case_id": physical_case_id,
        "physical_condition_sha256": physical_condition_sha256,
        "source_conversion_attempt": request.get("attempt_id"),
        "source_conversion_lifecycle": {
            "receipt_status": receipt.get("status"),
            "receipt_returncode": receipt.get("returncode"),
            "old_tool_status": old_tool_status,
            "source_conversion_reclassified": False,
        },
        "source_receipt_sha256": expected_receipt_sha256,
        "source_report_sha256": expected_report_sha256,
        "canonical_native_receipt": {
            "path": str(native_receipt_path),
            "sha256": expected_native_receipt_sha256,
            "status": native.get("status"),
            "returncode": native.get("returncode"),
        },
        "verified_trajectory_sha256": actual_output_sha256,
        "verified_frames": expected_frames,
        "verified_particles": expected_particles,
        "partvtk_all_passed": True,
        "opaque_hash_only": True,
        "arrays_decoded": False,
        "source_receipt_edited": False,
        "source_conversion_reclassified": False,
        "independent_case_count_increment": 0,
        "production_approval": "none",
        "q_n": "not_granted",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--stdout", type=Path, required=True)
    parser.add_argument("--trajectory-h5", type=Path, required=True)
    parser.add_argument("--native-receipt", type=Path, required=True)
    parser.add_argument("--expected-receipt-sha256", required=True)
    parser.add_argument("--expected-report-sha256", required=True)
    parser.add_argument("--expected-native-receipt-sha256", required=True)
    parser.add_argument("--expected-output-sha256", required=True)
    parser.add_argument("--expected-report-physical-condition-sha256", required=True)
    parser.add_argument("--expected-frames", type=int, required=True)
    parser.add_argument("--expected-particles", type=int, required=True)
    parser.add_argument("--physical-case-id", required=True)
    parser.add_argument("--physical-condition-sha256", required=True)
    parser.add_argument("--old-tool-status", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(
        receipt_path=args.receipt,
        report_path=args.report,
        stdout_path=args.stdout,
        trajectory_path=args.trajectory_h5,
        native_receipt_path=args.native_receipt,
        expected_receipt_sha256=args.expected_receipt_sha256,
        expected_report_sha256=args.expected_report_sha256,
        expected_native_receipt_sha256=args.expected_native_receipt_sha256,
        expected_output_sha256=args.expected_output_sha256,
        expected_report_physical_condition_sha256=args.expected_report_physical_condition_sha256,
        expected_frames=args.expected_frames,
        expected_particles=args.expected_particles,
        physical_case_id=args.physical_case_id,
        physical_condition_sha256=args.physical_condition_sha256,
        old_tool_status=args.old_tool_status,
    )
    write_new_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
