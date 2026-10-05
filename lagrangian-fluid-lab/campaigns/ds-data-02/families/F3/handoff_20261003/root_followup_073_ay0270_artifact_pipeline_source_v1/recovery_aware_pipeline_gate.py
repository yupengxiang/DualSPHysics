#!/usr/bin/env python3
"""Prepare a post-audit pipeline binding without rewriting conversion facts.

This helper reads only JSON receipts/reports.  It does not open HDF5, XDMF,
BI4, CSV, or any numerical array.  It allows a recovered conversion whose
runtime receipt remains ``running``/``returncode: null`` (or is explicitly
settled as ``interrupted_unfinalized``) when an independent artifact audit has
completed with returncode 0.  It never emits ``converter_completed: true``.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any


SCHEMA = "ds02.fresh073.recovery-aware-pipeline-binding.v1"
ALLOWED_SOURCE_STATUSES = {"running", "interrupted_unfinalized"}


class PipelineGateError(ValueError):
    """A lifecycle or identity fact is not sufficient for post-audit use."""


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PipelineGateError(f"JSON object required: {path}")
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PipelineGateError(message)


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


def prepare(
    *,
    stage: str,
    source_receipt_path: Path,
    report_path: Path,
    audit_path: Path,
    native_receipt_path: Path,
    physical_case_id: str,
    physical_condition_sha256: str,
    expected_frames: int,
    expected_particles: int,
) -> dict[str, Any]:
    """Validate JSON lifecycle facts and return a new, disabled stage binding."""
    _require(stage in {"normal", "export", "render"}, "unsupported post-audit stage")
    source = load_json(source_receipt_path)
    report = load_json(report_path)
    audit = load_json(audit_path)
    native = load_json(native_receipt_path)
    source_status = source.get("status")
    _require(source_status in ALLOWED_SOURCE_STATUSES,
             "source conversion lifecycle is not recovery-aware")
    _require(source.get("returncode") is None,
             "source conversion returncode must stay unknown/null")
    source_request = source.get("request", {})
    _require(isinstance(source_request, dict), "source request must be an object")
    _require(source_request.get("physical_case_id") == physical_case_id,
             "source receipt physical case differs from stage binding")
    _require(source_request.get("physical_condition_sha256") == physical_condition_sha256,
             "source receipt physical condition differs from stage binding")
    source_frames = source_request.get("expected_saved_frames")
    if source_frames is None:
        source_frames = source_request.get("canonical_condition", {}).get("expected_saved_frames")
    if source_frames is None:
        source_frames = source_request.get("expected_native", {}).get("saved_frames")
    if source_frames is None:
        source_frames = source_request.get("expected_output", {}).get("frame_count")
    _require(source_frames == expected_frames,
             "source receipt frame expectation differs from stage binding")
    _require(report.get("conversion_status") == "completed",
             "published report must be complete before post-audit use")
    _require(report.get("frames") == expected_frames and report.get("particles") == expected_particles,
             "published report dimensions differ from stage binding")
    _require(audit.get("schema") == "ds02.strict-cpu.typed-artifact-integrity.v2",
             "independent audit schema is not fresh073-compatible")
    _require(audit.get("artifact_integrity_status") == "completed",
             "independent artifact audit is not completed")
    _require(audit.get("worker_returncode") == 0,
             "independent artifact audit did not return 0")
    _require(audit.get("source_conversion_reclassified") is False,
             "independent audit reclassified the source conversion")
    lifecycle = audit.get("source_conversion_lifecycle", {})
    _require(lifecycle.get("receipt_returncode") is None,
             "audit does not preserve the unknown source returncode")
    _require(native.get("status") == "completed" and native.get("returncode") == 0,
             "canonical native receipt is not completed/0")
    native_request = native.get("request", {})
    _require(isinstance(native_request, dict), "native request must be an object")
    _require(native_request.get("physical_case_id") == physical_case_id,
             "native physical case differs from stage binding")
    _require(native_request.get("physical_condition_sha256") == physical_condition_sha256,
             "native physical condition differs from stage binding")
    native_frames = native_request.get("expected_saved_frames")
    if native_frames is None:
        native_frames = native_request.get("expected_native", {}).get("saved_frames")
    if native_frames is None:
        native_frames = native_request.get("expected_output", {}).get("frame_count")
    _require(native_frames == expected_frames,
             "native frame expectation differs from stage binding")
    _require(audit.get("physical_case_id") == physical_case_id,
             "audit physical case differs from stage binding")
    _require(audit.get("physical_condition_sha256") == physical_condition_sha256,
             "audit physical condition differs from stage binding")
    _require(audit.get("verified_frames") == expected_frames and
             audit.get("verified_particles") == expected_particles,
             "audit dimensions differ from stage binding")

    return {
        "schema": SCHEMA,
        "fresh_id": "fresh073",
        "stage": stage,
        "prepared_at_utc": datetime.now(timezone.utc).isoformat(),
        "family_id": "F3",
        "physical_case_id": physical_case_id,
        "physical_condition_sha256": physical_condition_sha256,
        "expected_frames": expected_frames,
        "expected_particles": expected_particles,
        "source_conversion_lifecycle": {
            "receipt_status": source_status,
            "receipt_returncode": None,
            "converter_completed_claim": False,
            "source_receipt_must_remain_unchanged": True,
            "tool_status_is_historical_and_separate": True,
        },
        "independent_artifact_audit": {
            "path": str(audit_path),
            "status": "completed",
            "worker_returncode": 0,
            "source_conversion_reclassified": False,
        },
        "canonical_native_receipt": {
            "path": str(native_receipt_path),
            "status": "completed",
            "returncode": 0,
        },
        "input_reports": {
            "source_receipt": str(source_receipt_path),
            "conversion_report": str(report_path),
        },
        "output_contract": {
            "status": "prepared_disabled",
            "manifest": None,
            "xdmf": None,
            "render_outputs": None,
            "sha256": None,
        },
        "production_approval": "none",
        "q_n": "not_granted",
        "independent_case_count_increment": 0,
        "launch_allowed": False,
        "execution_allowed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("normal", "export", "render"), required=True)
    parser.add_argument("--source-receipt", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--native-receipt", type=Path, required=True)
    parser.add_argument("--physical-case-id", required=True)
    parser.add_argument("--physical-condition-sha256", required=True)
    parser.add_argument("--expected-frames", type=int, required=True)
    parser.add_argument("--expected-particles", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(
        stage=args.stage,
        source_receipt_path=args.source_receipt,
        report_path=args.report,
        audit_path=args.audit,
        native_receipt_path=args.native_receipt,
        physical_case_id=args.physical_case_id,
        physical_condition_sha256=args.physical_condition_sha256,
        expected_frames=args.expected_frames,
        expected_particles=args.expected_particles,
    )
    write_new_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
