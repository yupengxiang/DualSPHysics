#!/usr/bin/env python3
"""Metadata-only audit for a naturally finished Root638 renderer orphan.

The worker deliberately never opens a PNG, XDMF, H5, VTK, CSV, DAT, or BI4
payload.  It reads the old execution receipt, the renderer's JSON report, a
Root-owned lock/reconciliation sidecar, and filesystem names/stat metadata.
The old receipt remains an unknown/interrupted record; this worker owns only a
new CPU audit receipt when the shared runner launches it.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import tempfile


FRAME_RE = re.compile(r"^frame_(\d{4})\.png$")
CONTACT_RE = re.compile(r"^all_frames_(\d{3})\.png$")
EXPECTED_FRAMES = 1201
EXPECTED_CONTACT_SHEETS = 51
EXPECTED_RESERVED_CPU_SECONDS = 345600


class AuditError(RuntimeError):
    pass


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, label: str) -> dict:
    if not path.is_file():
        raise AuditError(f"missing {label}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditError(f"invalid {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AuditError(f"{label} must be a JSON object: {path}")
    return value


def require(value: bool, message: str) -> None:
    if not value:
        raise AuditError(message)


def check_reconciliation(config: dict) -> dict:
    sidecar_path = Path(config["reconciliation_sidecar"])
    sidecar = read_json(sidecar_path, "Root reconciliation sidecar")
    require(sidecar.get("schema") == "ds02.root-owned.render-orphan-reconciliation.v1",
            "unexpected reconciliation sidecar schema")
    require(sidecar.get("status") == "applied", "reconciliation is not applied")
    require(sidecar.get("orphan_terminal_state") == "unknown",
            "old render terminal state must remain unknown")
    require(sidecar.get("old_receipt_preserved") is True,
            "old receipt was not preserved")
    require(sidecar.get("no_signal_sent") is True, "reconciliation must not signal a child")
    require(sidecar.get("no_process_adoption") is True,
            "reconciliation must not adopt or reparent a child")
    lock = sidecar.get("ledger_reconciliation")
    require(isinstance(lock, dict) and lock.get("ledger_lock_held") is True,
            "ledger reconciliation was not lock-protected")
    require(lock.get("reservation_removed") is True,
            "the exact stale reservation was not released")
    require(lock.get("charge_status") == "interrupted_unfinalized",
            "stale render was charged with an invalid terminal status")
    require(lock.get("child_returncode") is None and lock.get("os_exit_zero") is False,
            "stale render was incorrectly converted to exit zero")
    require(lock.get("full_reserved_cpu_core_seconds") == EXPECTED_RESERVED_CPU_SECONDS,
            "reserved CPU charge was not preserved in full")
    require(lock.get("total_full_reserved_cpu_core_seconds") == 2 * EXPECTED_RESERVED_CPU_SECONDS,
            "the two stale reservations were not charged in full")
    samples = sidecar.get("process_census", {}).get("samples")
    require(isinstance(samples, list) and len(samples) >= 2,
            "two post-termination process census samples are required")
    require(all(sample.get("all_recorded_pids_absent") is True for sample in samples),
            "a process census sample still contains a recorded PID")
    recorded_pids = sidecar.get("process_census", {}).get("recorded_pids")
    require(isinstance(recorded_pids, list) and recorded_pids,
            "recorded renderer PIDs are missing")
    # This is a second defensive check.  It is not a substitute for the
    # Root-owned lock/census proof, because a PID can be reused after exit.
    require(all(not Path("/proc", str(pid)).exists() for pid in recorded_pids),
            "a recorded renderer PID is currently present")
    return sidecar


def check_old_receipt(config: dict) -> dict:
    receipt = read_json(Path(config["old_receipt"]), "old renderer receipt")
    require(receipt.get("status") == "running",
            "the preserved old receipt no longer has the expected unknown-running state")
    for key in ("returncode", "finished_at_utc", "termination_reason"):
        require(receipt.get(key) is None,
                f"old receipt field {key} would turn this into a fabricated terminal result")
    require(receipt.get("pid") is not None, "old renderer child PID is missing")
    return receipt


def check_report(config: dict) -> dict:
    report = read_json(Path(config["renderer_report"]), "renderer integrity report")
    require(report.get("schema") == "ds02.stage1.paraview-full-animation-integrity.v1",
            "unexpected renderer report schema")
    require(report.get("frames") == EXPECTED_FRAMES and report.get("source_frames") == EXPECTED_FRAMES,
            "renderer report does not cover all 1201 saved frames")
    require(report.get("all_frames_rendered") is True,
            "renderer report does not certify all saved frames")
    require(report.get("actual_times_preserved_exactly") is True,
            "renderer report does not preserve producer times")
    require(report.get("native_identity_axis_preserved") is True,
            "renderer report does not preserve native identity/axis metadata")
    require(report.get("source_h5_read_only") is True,
            "renderer report lacks its read-only source declaration")
    require(report.get("diagnostic_only") is False,
            "diagnostic-only output cannot close the full render audit")
    require(str(report.get("visual_review", "")).startswith("pending"),
            "this audit must not close root visual review")
    require(report.get("numerical_precision_status") == "not accepted",
            "this metadata audit must not claim numerical precision")
    if "nonfinite_active_states" in report:
        require(report["nonfinite_active_states"] == 0,
                "renderer report contains nonfinite active states")
    # Do not access source_h5_sha256, XDMF hashes, or any science payload.
    return {key: report.get(key) for key in (
        "schema", "frames", "source_frames", "all_frames_rendered",
        "actual_times_preserved_exactly", "native_identity_axis_preserved",
        "source_h5_read_only", "diagnostic_only", "visual_review",
        "numerical_precision_status", "nonfinite_active_states")}


def check_named_files(config: dict) -> tuple[int, int]:
    output = Path(config["render_output_dir"])
    frames = output / "frames"
    require(frames.is_dir(), f"missing renderer frames directory: {frames}")
    frame_numbers = []
    for path in frames.iterdir():
        if not path.is_file():
            continue
        match = FRAME_RE.fullmatch(path.name)
        if match is None:
            raise AuditError(f"unexpected file in frames directory: {path.name}")
        require(path.stat().st_size > 0, f"empty frame file: {path}")
        frame_numbers.append(int(match.group(1)))
    require(sorted(frame_numbers) == list(range(EXPECTED_FRAMES)),
            "frame filenames are not exactly frame_0000.png through frame_1200.png")

    contacts = []
    for path in output.iterdir():
        if not path.is_file():
            continue
        match = CONTACT_RE.fullmatch(path.name)
        if match is None:
            continue
        require(path.stat().st_size > 0, f"empty contact sheet: {path}")
        contacts.append(int(match.group(1)))
    require(sorted(contacts) == list(range(EXPECTED_CONTACT_SHEETS)),
            "contact sheets are not exactly all_frames_000.png through all_frames_050.png")
    return len(frame_numbers), len(contacts)


def audit(config_path: Path, output_dir: Path) -> dict:
    config = read_json(config_path, "audit configuration")
    require(config.get("schema") == "ds02.f4.root638.orphan-render-audit.v1",
            "unexpected audit configuration schema")
    require(config.get("case_id") and config.get("old_attempt_id"),
            "audit identity is incomplete")
    check_reconciliation(config)
    old_receipt = check_old_receipt(config)
    report = check_report(config)
    frames, contacts = check_named_files(config)
    output_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "schema": "ds02.f4.root638.orphan-render-audit-result.v1",
        "case_id": config["case_id"],
        "source_render_attempt_id": config["old_attempt_id"],
        "source_old_receipt_status": "unknown_preserved",
        "source_old_returncode": None,
        "reconciliation_status": "root_lock_applied_no_signal_no_adoption",
        "frame_file_count": frames,
        "contact_sheet_file_count": contacts,
        "producer_report_metadata": report,
        "png_bytes_read": False,
        "scientific_payload_read_or_hashed": False,
        "visual_review": "pending root inspection of full animation and contact sheets",
        "numerical_precision_status": "not accepted",
        "q_n_status": "not_assessed",
        "independent_case_increment": 0,
        "audit_completed": True,
        "audited_at_utc": now_utc(),
        "old_receipt_pid": old_receipt.get("pid"),
    }
    (output_dir / "root638-orphan-render-audit.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def self_test() -> None:
    """Run only synthetic metadata checks; no project data is touched."""
    with tempfile.TemporaryDirectory(prefix="ds02-root108-audit-") as temp:
        root = Path(temp)
        output = root / "render"
        frames = output / "frames"
        frames.mkdir(parents=True)
        for index in range(EXPECTED_FRAMES):
            (frames / f"frame_{index:04d}.png").write_bytes(b"x")
        for index in range(EXPECTED_CONTACT_SHEETS):
            (output / f"all_frames_{index:03d}.png").write_bytes(b"x")
        report_path = output / "paraview-full-animation-report.json"
        _write_json(report_path, {
            "schema": "ds02.stage1.paraview-full-animation-integrity.v1",
            "frames": EXPECTED_FRAMES, "source_frames": EXPECTED_FRAMES,
            "all_frames_rendered": True, "actual_times_preserved_exactly": True,
            "native_identity_axis_preserved": True, "source_h5_read_only": True,
            "diagnostic_only": False, "visual_review": "pending root inspection",
            "numerical_precision_status": "not accepted", "nonfinite_active_states": 0,
        })
        old_receipt = root / "old-receipt.json"
        _write_json(old_receipt, {"status": "running", "pid": 999999991,
                                  "returncode": None, "finished_at_utc": None,
                                  "termination_reason": None})
        sidecar = root / "reconciliation.json"
        _write_json(sidecar, {
            "schema": "ds02.root-owned.render-orphan-reconciliation.v1",
            "status": "applied", "orphan_terminal_state": "unknown",
            "old_receipt_preserved": True, "no_signal_sent": True,
            "no_process_adoption": True,
            "ledger_reconciliation": {
                "ledger_lock_held": True, "reservation_removed": True,
                "charge_status": "interrupted_unfinalized", "child_returncode": None,
                "os_exit_zero": False, "full_reserved_cpu_core_seconds": EXPECTED_RESERVED_CPU_SECONDS,
                "total_full_reserved_cpu_core_seconds": 2 * EXPECTED_RESERVED_CPU_SECONDS,
            },
            "process_census": {
                "recorded_pids": [999999991],
                "samples": [{"all_recorded_pids_absent": True}, {"all_recorded_pids_absent": True}],
            },
        })
        config = root / "config.json"
        _write_json(config, {
            "schema": "ds02.f4.root638.orphan-render-audit.v1",
            "case_id": "synthetic", "old_attempt_id": "synthetic-old",
            "old_receipt": str(old_receipt), "reconciliation_sidecar": str(sidecar),
            "renderer_report": str(report_path), "render_output_dir": str(output),
        })
        result = audit(config, root / "audit")
        assert result["audit_completed"] is True

        # Missing a frame is a hard failure.
        (frames / "frame_1200.png").unlink()
        try:
            audit(config, root / "audit-negative-frame")
        except AuditError:
            pass
        else:
            raise AssertionError("missing frame was accepted")
        (frames / "frame_1200.png").write_bytes(b"x")

        # A completed old receipt must never be treated as an orphan recovery.
        _write_json(old_receipt, {"status": "completed", "pid": 999999991,
                                  "returncode": 0, "finished_at_utc": now_utc(),
                                  "termination_reason": None})
        try:
            audit(config, root / "audit-negative-receipt")
        except AuditError:
            pass
        else:
            raise AssertionError("completed old receipt was accepted")
    print("fresh108 synthetic metadata checks: PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    parser.add_argument("--output-dir")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.config or not args.output_dir:
        parser.error("--config and --output-dir are required unless --self-test is used")
    try:
        result = audit(Path(args.config), Path(args.output_dir))
    except AuditError as exc:
        print(f"fresh108 audit refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"audit_completed": result["audit_completed"],
                      "case_id": result["case_id"],
                      "frame_file_count": result["frame_file_count"],
                      "contact_sheet_file_count": result["contact_sheet_file_count"]},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
