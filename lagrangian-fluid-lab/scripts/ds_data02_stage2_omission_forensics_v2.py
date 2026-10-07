#!/usr/bin/env python3
"""Source-bound native omission join for a completed Stage2 scan.

This version preserves the consumed v1 join implementation and adds a
fail-closed check for the scientific-scan producer receipt.  It accepts a
native cause only when the exact scan output, physical case ID, trajectory
hashes, and trajectory stat metadata are all bound to that producer receipt.
It never opens trajectory.h5 and it does not interpret native exclusion as
physical spill or as a dynamical error bound.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import ds_data02_stage2_omission_forensics_v1 as base


class EvidenceError(ValueError):
    """Raised when the scan producer cannot be source-bound."""


def _command_value(command: list[str], flag: str) -> str:
    for index, value in enumerate(command[:-1]):
        if value == flag:
            return command[index + 1]
    raise EvidenceError(f"scan producer command is missing {flag}")


def _scan_producer_binding(scan_path: Path, conversion_path: Path) -> dict:
    scan_path = Path(scan_path)
    scan = json.loads(scan_path.read_text())
    if scan.get("schema") != "ds02.stage2.scientific-scan.v1":
        raise EvidenceError("unsupported scientific scan schema")
    if scan.get("scan_status") != "SCANNED" or scan.get("failures"):
        raise EvidenceError("scientific scan is not clean and completed")
    receipt_path = scan_path.parent / "execution-receipt.json"
    if not receipt_path.is_file():
        raise EvidenceError("scientific scan producer receipt is missing")
    receipt = json.loads(receipt_path.read_text())
    if (receipt.get("schema") != "ds02.execution-receipt.v1" or
            receipt.get("status") != "completed" or
            receipt.get("returncode") != 0 or
            receipt.get("output_root") != str(scan_path.parent)):
        raise EvidenceError("scientific scan producer receipt is not this completed scan")
    command = receipt.get("command", [])
    if Path(_command_value(command, "--output")) != scan_path:
        raise EvidenceError("scan producer output is not this scan")
    if _command_value(command, "--case-id") != scan.get("physical_case_id"):
        raise EvidenceError("scan producer case ID differs from scan")
    request = receipt.get("request", {})
    trajectory = Path(scan.get("trajectory", ""))
    if not trajectory.is_file():
        raise EvidenceError("scan trajectory is missing")
    if str(trajectory) not in set(request.get("input_files", [])):
        raise EvidenceError("scan producer request does not bind this trajectory")
    conversion = json.loads(Path(conversion_path).read_text())
    if (conversion.get("conversion_status") != "completed" or
            conversion.get("output_hdf5") != str(trajectory)):
        raise EvidenceError("conversion output is not this scan trajectory")
    expected = conversion.get("output_sha256")
    key = str(trajectory)
    declared = request.get("input_sha256", {}).get(key)
    launch = receipt.get("input_hashes_at_launch", {}).get(key)
    finish = receipt.get("input_hashes_after_run", {}).get(key)
    if not expected or declared != expected or launch != expected or finish != expected:
        raise EvidenceError("scan producer and conversion trajectory hashes differ")
    stat = trajectory.stat()
    if (stat.st_size != scan.get("source_bytes") or
            stat.st_mtime_ns != scan.get("source_mtime_ns")):
        raise EvidenceError("scan trajectory stat metadata differs from scan")
    return {
        "scan": base.binding(scan_path),
        "receipt": base.binding(receipt_path),
        "trajectory": {
            "path": str(trajectory),
            "sha256": expected,
            "bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        },
        "physical_case_id": scan.get("physical_case_id"),
        "receipt_command": command,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan", type=Path, required=True)
    parser.add_argument("--partout", type=Path, required=True)
    parser.add_argument("--runparts", type=Path, required=True)
    parser.add_argument("--conversion-report", type=Path, required=True)
    parser.add_argument("--decoder-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Preserve existing sidecar: " + str(args.output))
    producer = _scan_producer_binding(args.scan, args.conversion_report)
    result = base.reconcile(
        json.loads(args.scan.read_text()), base.read_partout(args.partout),
        base.read_runparts(args.runparts), json.loads(args.conversion_report.read_text()),
        json.loads(args.decoder_receipt.read_text()), args.scan, args.partout,
        args.runparts, args.conversion_report, args.decoder_receipt,
    )
    result["scan_producer_binding"] = producer
    result["join_implementation"] = {
        "module": str(Path(__file__).resolve()),
        "version": "ds02.stage2.omission-forensics.v2",
        "trajectory_h5_read": False,
    }
    base.atomic_json(args.output, result)
    print(json.dumps({"status": result["status"],
                      "case": result["physical_case_id"],
                      "missing_fluid": result["typed_identity"]["missing_fluid_count"],
                      "motives": result["native_decode"]["runparts_totals"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
