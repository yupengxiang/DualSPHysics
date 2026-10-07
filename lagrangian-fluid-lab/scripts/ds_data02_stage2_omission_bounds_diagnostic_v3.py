#!/usr/bin/env python3
"""Source-bound wrapper for the Stage2 omission bounds diagnostic.

The consumed v2 diagnostic is intentionally left byte-for-byte unchanged.  This
version adds a producer-receipt check before delegating to it: the scientific
scan must be the output of the receipt bound by the omission sidecar, its
command must carry the exact physical case ID, and the trajectory digest must
be stable from launch through completion.  The trajectory itself is not read.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import ds_data02_stage2_omission_bounds_diagnostic_v2 as base


class EvidenceError(base.EvidenceError):
    """Raised when the producer receipt cannot establish exact provenance."""


def _command_value(command: list[str], flag: str) -> str:
    for index, value in enumerate(command[:-1]):
        if value == flag:
            return command[index + 1]
    raise EvidenceError(f"scan producer command is missing {flag}")


def _scan_producer_binding(sidecar: dict) -> dict:
    """Validate the scan receipt that produced the bound scientific scan.

    This checks receipt metadata and filesystem stat metadata only.  Rehashing
    a multi-gigabyte trajectory here would duplicate the scientific scan I/O;
    the receipt's launch/end digest equality plus the scan source bytes/mtime
    are the producer evidence used by this audit.
    """
    scan_info = sidecar.get("scan", {})
    scan_path = Path(scan_info.get("path", ""))
    if not scan_path.is_file():
        raise EvidenceError("bound scientific scan is missing")
    if scan_info.get("sha256") != base.sha256(scan_path):
        raise EvidenceError("bound scientific scan digest changed")
    scan = json.loads(scan_path.read_text())
    if scan.get("schema") != "ds02.stage2.scientific-scan.v1":
        raise EvidenceError("unsupported scientific scan schema")
    if scan.get("family_id") != sidecar.get("family_id"):
        raise EvidenceError("scan producer family differs from sidecar")
    if scan.get("physical_case_id") != sidecar.get("physical_case_id"):
        raise EvidenceError("scan producer physical_case_id differs from sidecar")

    completion_info = sidecar.get("scan_completion", {}).get("receipt", {})
    receipt_path = Path(completion_info.get("path", ""))
    if not receipt_path.is_file() or receipt_path.parent != scan_path.parent:
        raise EvidenceError("scan completion receipt is not the scan's producer receipt")
    if completion_info.get("sha256") != base.sha256(receipt_path):
        raise EvidenceError("scan completion receipt digest changed")
    receipt = json.loads(receipt_path.read_text())
    if receipt.get("schema") != "ds02.execution-receipt.v1":
        raise EvidenceError("unsupported scan completion receipt schema")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise EvidenceError("scan completion receipt is not successful")
    if receipt.get("output_root") != str(scan_path.parent):
        raise EvidenceError("scan receipt output_root is not this scan directory")

    command = receipt.get("command", [])
    if Path(_command_value(command, "--output")) != scan_path:
        raise EvidenceError("scan receipt output is not this scientific scan")
    if _command_value(command, "--case-id") != sidecar.get("physical_case_id"):
        raise EvidenceError("scan receipt case ID is not the exact physical case")

    request = receipt.get("request", {})
    request_command = request.get("command", [])
    expanded = [value.replace("{attempt_root}", str(scan_path.parent))
                for value in request_command]
    if expanded and expanded != command:
        raise EvidenceError("scan receipt command differs from its request")

    trajectory = Path(scan.get("trajectory", ""))
    if not trajectory.is_file():
        raise EvidenceError("scientific scan trajectory is missing")
    input_files = set(request.get("input_files", []))
    trajectory_key = str(trajectory)
    if trajectory_key not in input_files:
        raise EvidenceError("scan receipt does not bind its scientific trajectory")
    declared = request.get("input_sha256", {}).get(trajectory_key)
    launch = receipt.get("input_hashes_at_launch", {}).get(trajectory_key)
    finish = receipt.get("input_hashes_after_run", {}).get(trajectory_key)
    expected = sidecar.get("trajectory", {}).get("sha256")
    if not declared or declared != launch or declared != finish or declared != expected:
        raise EvidenceError("scan trajectory digest is not stable or conversion-bound")
    stat = trajectory.stat()
    if stat.st_size != scan.get("source_bytes") or stat.st_mtime_ns != scan.get("source_mtime_ns"):
        raise EvidenceError("trajectory stat metadata differs from scientific scan")
    completion = sidecar.get("scan_completion", {})
    if (completion.get("trajectory_sha256_launch") != launch or
            completion.get("trajectory_sha256_end") != finish):
        raise EvidenceError("sidecar scan-completion digests differ from producer receipt")
    return {
        "path": str(receipt_path),
        "sha256": completion_info["sha256"],
        "trajectory_path": str(trajectory),
        "trajectory_sha256": declared,
        "command_case_id": _command_value(command, "--case-id"),
        "launch_end_digest_equal": launch == finish,
    }


def diagnose(sidecar_path: Path) -> dict:
    sidecar_path = Path(sidecar_path)
    sidecar = json.loads(sidecar_path.read_text())
    producer = _scan_producer_binding(sidecar)
    # base.diagnose performs the complete no-H5 join, including current raw,
    # RunPARTs, XML, solver, decoder and exact-ID checks.
    result = base.diagnose(sidecar_path)
    result["schema"] = "ds02.stage2.omission-bounds-diagnostic.v2"
    result["source_binding_validation"] = {
        "version": "producer-receipt-v3",
        "trajectory_read": False,
        "scientific_scan_producer": producer,
    }
    # Keep the wetted wall and physical boundary continuous in the proposed
    # geometry control.  A moved bottom is a separate physical-condition
    # study, not a one-factor numerical support/boundary control.
    result["paired_control_plan"]["geometry_pair"] = {
        "hold": "same wetted wall location, continuous physical boundary, numerical domain, thresholds, source cohort, and time window",
        "vary": "one numerical geometry factor at a time: wall thickness, discrete boundary support, or boundary treatment",
        "separate_physical_condition": "moving the bottom/wetted wall is a separate control because it changes the physical condition",
        "readout": "compare exact typed Idp survival, first-gap identity, native motive counts, wall relation, and post-gap observables",
        "interpretation": "survival changes establish numerical sensitivity only; they do not prove physical spill or zero dynamical impact",
        "status": "PROPOSAL_ONLY_NOT_RUN",
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sidecar", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"Preserve existing diagnostic: {args.output}")
    result = diagnose(args.sidecar)
    base.atomic_json(args.output, result)
    print(json.dumps({"status": result["status"],
                      "case": result["physical_case_id"],
                      "producer_bound": True,
                      "credit": result["diagnostic"]["numerical_cause_credit_count"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
