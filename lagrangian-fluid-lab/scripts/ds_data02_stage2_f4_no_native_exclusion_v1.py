#!/usr/bin/env python3
"""Audit a completed zero-omission case without requiring PartOut_000.obi4.

The native RunPARTs counters are the authoritative exclusion observation here.
When every saved native counter is zero and the clean scientific scan reports
zero final fluid omissions, a missing raw PartOut file is an expected
no-exclusion condition, not a decoder failure.  This audit still leaves
physical fate and dynamical impact unassessed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import ds_data02_stage2_omission_bounds_diagnostic_v2 as base


class EvidenceError(base.EvidenceError):
    """Raised when a zero-exclusion claim is not source-bound."""


def _value(command: list[str], flag: str) -> str:
    for index, token in enumerate(command[:-1]):
        if token == flag:
            return command[index + 1]
    raise EvidenceError(f"producer command is missing {flag}")


def _binding(path: Path) -> dict:
    if not path.is_file():
        raise EvidenceError(f"missing evidence file: {path}")
    return base.binding(path)


def _scan_sources(scan_path: Path, receipt_path: Path, conversion_path: Path) -> tuple[dict, dict, dict]:
    scan_path = Path(scan_path)
    scan = json.loads(scan_path.read_text())
    if scan.get("schema") != "ds02.stage2.scientific-scan.v1":
        raise EvidenceError("unsupported scientific scan schema")
    if scan.get("scan_status") != "SCANNED" or scan.get("failures"):
        raise EvidenceError("scientific scan is not clean and completed")
    receipt_path = Path(receipt_path)
    receipt = json.loads(receipt_path.read_text())
    if (receipt.get("schema") != "ds02.execution-receipt.v1" or
            receipt.get("status") != "completed" or receipt.get("returncode") != 0 or
            receipt.get("output_root") != str(scan_path.parent) or
            receipt_path.parent != scan_path.parent):
        raise EvidenceError("scan completion receipt is not this completed scan")
    command = receipt.get("command", [])
    if Path(_value(command, "--output")) != scan_path:
        raise EvidenceError("scan receipt output is not this scan")
    if _value(command, "--case-id") != scan.get("physical_case_id"):
        raise EvidenceError("scan receipt case ID differs from scan")
    request = receipt.get("request", {})
    trajectory = Path(scan.get("trajectory", ""))
    if not trajectory.is_file() or str(trajectory) not in set(request.get("input_files", [])):
        raise EvidenceError("scan receipt does not bind an existing trajectory")
    key = str(trajectory)
    declared = request.get("input_sha256", {}).get(key)
    launch = receipt.get("input_hashes_at_launch", {}).get(key)
    finish = receipt.get("input_hashes_after_run", {}).get(key)
    conversion_path = Path(conversion_path)
    conversion = json.loads(conversion_path.read_text())
    if (conversion.get("conversion_status") != "completed" or
            conversion.get("output_hdf5") != str(trajectory) or
            not conversion.get("output_sha256") or
            declared != launch or declared != finish or declared != conversion.get("output_sha256")):
        raise EvidenceError("scan trajectory receipt and conversion digest are not identical")
    stat = trajectory.stat()
    if stat.st_size != scan.get("source_bytes") or stat.st_mtime_ns != scan.get("source_mtime_ns"):
        raise EvidenceError("trajectory stat metadata differs from scan")
    return scan, receipt, conversion


def _final_missing_count(scan: dict) -> int:
    fluid = scan.get("type_ledgers", {}).get("fluid", {})
    if isinstance(fluid.get("missing_at_final"), int):
        return int(fluid["missing_at_final"])
    counts = fluid.get("missing_count")
    if isinstance(counts, list) and counts:
        return int(counts[-1])
    raise EvidenceError("scientific scan has no fluid final omission count")


def audit(scan_path: Path, scan_receipt_path: Path, conversion_path: Path,
          output: Path) -> dict:
    scan, scan_receipt, conversion = _scan_sources(scan_path, scan_receipt_path,
                                                     conversion_path)
    missing = _final_missing_count(scan)
    if missing != 0:
        raise EvidenceError(f"scientific scan final fluid omission count is {missing}")
    provenance = conversion.get("source_provenance", {})
    source_paths: dict[str, Path] = {}
    for field in ("generated_xml", "solver_receipt", "gencase_receipt"):
        info = provenance.get(field, {})
        path = Path(info.get("path", ""))
        if info.get("sha256") != base.sha256(path):
            raise EvidenceError(f"{field} provenance digest changed")
        source_paths[field] = path
    solver_receipt = json.loads(source_paths["solver_receipt"].read_text())
    if solver_receipt.get("schema") != "ds02.execution-receipt.v1":
        raise EvidenceError("unsupported solver receipt schema")
    if solver_receipt.get("status") != "completed" or solver_receipt.get("returncode") != 0:
        raise EvidenceError("solver receipt is not completed")
    physical_case_id = scan.get("physical_case_id")
    solver_request = solver_receipt.get("request", {})
    solver_identities = {
        solver_receipt.get("physical_case_id"),
        solver_request.get("physical_case_id"),
        solver_receipt.get("scientific_scope", {}).get("physical_case_id"),
        solver_request.get("scientific_scope", {}).get("physical_case_id"),
    }
    solver_identities.discard(None)
    if physical_case_id not in solver_identities:
        raise EvidenceError("solver receipt physical case differs from exact scan identity")
    solver_root = Path(solver_receipt.get("output_root", ""))
    if solver_root != source_paths["solver_receipt"].parent:
        raise EvidenceError("solver receipt output_root is inconsistent")
    run_out_path = solver_root / "solver_output" / "Run.out"
    runparts_path = solver_root / "solver_output" / "RunPARTs.csv"
    run_out = base.parse_run_out(run_out_path)
    runparts = base.parse_runparts(runparts_path)
    if len(runparts["rows"]) != len(scan.get("time_s", [])):
        raise EvidenceError("RunPARTs timeline length differs from scientific scan")
    max_delta = max(abs(float(a) - row["time_s"])
                    for a, row in zip(scan["time_s"], runparts["rows"]))
    tolerance = 1e-8 * max(1.0, float(scan["time_s"][-1]))
    if max_delta > tolerance:
        raise EvidenceError(f"RunPARTs and scan time mismatch: {max_delta}")
    totals = runparts["totals"]
    if totals != {"NpOut": 0, "NpOutPos": 0, "NpOutRho": 0, "NpOutMov": 0}:
        raise EvidenceError(f"native RunPARTs reports exclusions: {totals}")
    xml = base.parse_xml(source_paths["generated_xml"])
    data_root = Path(provenance.get("data_root", ""))
    if not data_root.is_dir() or runparts_path.parent != data_root.parent:
        raise EvidenceError("RunPARTs is not under the bound solver data root")
    raw_partout = data_root / "PartOut_000.obi4"
    return {
        "schema": "ds02.stage2.no-native-exclusion-observed.v1",
        "status": "NO_NATIVE_EXCLUSION_OBSERVED",
        "family_id": scan["family_id"],
        "physical_case_id": physical_case_id,
        "evidence": {
            "scan": base.binding(Path(scan_path)),
            "scan_receipt": base.binding(Path(scan_receipt_path)),
            "conversion_report": base.binding(Path(conversion_path)),
            "generated_xml": base.binding(source_paths["generated_xml"]),
        "solver_receipt": base.binding(source_paths["solver_receipt"]),
            "gencase_receipt": base.binding(source_paths["gencase_receipt"]),
            "run_out": base.binding(run_out_path),
            "runparts": base.binding(runparts_path),
            "trajectory_h5_read": False,
        },
        "scan": {
            "frames": len(scan["time_s"]),
            "fluid_missing_at_final": 0,
            "trajectory": str(scan["trajectory"]),
            "trajectory_sha256_conversion_and_scan_receipt": conversion["output_sha256"],
            "first_missing_frame": None,
        },
        "run_out": run_out,
        "xml_geometry": xml,
        "native": {
            "runparts_totals": totals,
            "runparts_row_count": len(runparts["rows"]),
            "max_saved_time_delta_s": max_delta,
            "partout_required": False,
            "raw_partout_path": str(raw_partout),
            "raw_partout_present": raw_partout.is_file(),
            "raw_partout_interpretation": "not required when every native NpOut counter is zero",
            "solver_physical_identity_binding": physical_case_id,
        },
        "observation_impact": {
            "native_accounting": "no native exclusion observed in RunPARTs for the saved timeline",
            "mass_visibility": "no native omission mass lower bound from this case",
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "NOT_ASSESSED; zero native exclusion does not establish dynamical precision",
        },
        "physical_fate": "UNKNOWN",
        "dynamical_impact": "NOT_ASSESSED",
        "QN": "NOT_ASSESSED",
        "QE": "NOT_ASSESSED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan", type=Path, required=True)
    parser.add_argument("--scan-receipt", type=Path, required=True)
    parser.add_argument("--conversion-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"Preserve existing audit: {args.output}")
    result = audit(args.scan, args.scan_receipt, args.conversion_report, args.output)
    base.atomic_json(args.output, result)
    print(json.dumps({"status": result["status"],
                      "case": result["physical_case_id"],
                      "partout_required": result["native"]["partout_required"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
