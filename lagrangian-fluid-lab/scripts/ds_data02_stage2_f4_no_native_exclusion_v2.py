#!/usr/bin/env python3
"""Source-bound zero-exclusion audit with CURRENT336 alias resolution.

The v1 audit intentionally required a solver receipt identity to equal the
scientific scan's physical ID byte-for-byte.  Some F4 completed runs use the
CURRENT336 ``runtime_case_alias`` in the solver receipt while the scan uses
the exact physical ID.  This forward-only v2 keeps the strict binding by
reading the catalog entry and accepting only the catalog's two identities.
It never changes the v1 audit or any consumed receipt.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import ds_data02_stage2_omission_bounds_diagnostic_v2 as base
import ds_data02_stage2_f4_no_native_exclusion_v1 as v1


class EvidenceError(base.EvidenceError):
    """Raised when a zero-exclusion claim is not source-bound."""


def _catalog_entry(catalog_path: Path, scan: dict, conversion_path: Path,
                   source_paths: dict[str, Path]) -> tuple[dict, dict]:
    catalog_path = base.require_file(Path(catalog_path), "CURRENT336 catalog")
    catalog = json.loads(catalog_path.read_text())
    if catalog.get("schema") != "ds02.stage2.current336.v1":
        raise EvidenceError("unsupported CURRENT336 schema")
    matches = [row for row in catalog.get("cases", [])
               if row.get("family_id") == scan.get("family_id") and
               row.get("physical_case_id") == scan.get("physical_case_id")]
    if len(matches) != 1:
        raise EvidenceError("CURRENT336 exact physical identity is absent or ambiguous")
    entry = matches[0]
    if entry.get("trajectory", {}).get("path") != scan.get("trajectory"):
        raise EvidenceError("CURRENT336 trajectory differs from completed scan")
    if entry.get("conversion_report", {}).get("path") != str(conversion_path):
        raise EvidenceError("CURRENT336 conversion report differs from bound report")
    bindings = entry.get("source_bindings", {})
    for field in ("generated_xml", "solver_receipt", "gencase_receipt"):
        if bindings.get(field, {}).get("path") != str(source_paths[field]):
            raise EvidenceError(f"CURRENT336 {field} differs from provenance")
    return catalog, entry


def audit(scan_path: Path, scan_receipt_path: Path, conversion_path: Path,
          catalog_path: Path, output: Path) -> dict:
    scan, scan_receipt, conversion = v1._scan_sources(
        scan_path, scan_receipt_path, conversion_path)
    missing = v1._final_missing_count(scan)
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
    catalog, entry = _catalog_entry(Path(catalog_path), scan, Path(conversion_path),
                                    source_paths)
    scan_command = scan_receipt.get("command", [])
    if v1._value(scan_command, "--catalog") != str(Path(catalog_path)):
        raise EvidenceError("scan receipt catalog is not the bound CURRENT336")

    solver_receipt = json.loads(source_paths["solver_receipt"].read_text())
    if solver_receipt.get("schema") != "ds02.execution-receipt.v1":
        raise EvidenceError("unsupported solver receipt schema")
    if solver_receipt.get("status") != "completed" or solver_receipt.get("returncode") != 0:
        raise EvidenceError("solver receipt is not completed")
    physical_case_id = scan.get("physical_case_id")
    runtime_alias = entry.get("runtime_case_alias")
    allowed = {physical_case_id}
    if runtime_alias:
        allowed.add(runtime_alias)
    solver_request = solver_receipt.get("request", {})
    identities = {
        solver_receipt.get("physical_case_id"),
        solver_request.get("case_id"),
        solver_request.get("physical_case_id"),
        solver_receipt.get("scientific_scope", {}).get("physical_case_id"),
        solver_request.get("scientific_scope", {}).get("physical_case_id"),
    }
    identities.discard(None)
    if not identities or not identities <= allowed:
        raise EvidenceError("solver receipt contains an identity outside CURRENT336 aliases")
    solver_root = Path(solver_receipt.get("output_root", ""))
    if solver_root != source_paths["solver_receipt"].parent:
        raise EvidenceError("solver receipt output_root is inconsistent")
    run_out_path = solver_root / "solver_output" / "Run.out"
    runparts_path = solver_root / "solver_output" / "RunPARTs.csv"
    run_out = base.parse_run_out(run_out_path)
    if run_out["case_name"] not in allowed:
        raise EvidenceError("Run.out CaseName is outside CURRENT336 aliases")
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
        "schema": "ds02.stage2.no-native-exclusion-observed.v2",
        "status": "NO_NATIVE_EXCLUSION_OBSERVED",
        "family_id": scan["family_id"],
        "physical_case_id": physical_case_id,
        "evidence": {
            "catalog": base.binding(Path(catalog_path)),
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
        "identity_binding": {
            "current_physical_case_id": physical_case_id,
            "current_runtime_case_alias": runtime_alias,
            "allowed_solver_identities": sorted(allowed),
            "observed_solver_identities": sorted(identities),
            "run_out_case_name": run_out["case_name"],
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
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"Preserve existing audit: {args.output}")
    result = audit(args.scan, args.scan_receipt, args.conversion_report,
                   args.catalog, args.output)
    base.atomic_json(args.output, result)
    print(json.dumps({"status": result["status"],
                      "case": result["physical_case_id"],
                      "runtime_alias": result["identity_binding"]["current_runtime_case_alias"],
                      "partout_required": result["native"]["partout_required"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
