#!/usr/bin/env python3
"""ROOT219 adapter for the exact F6 S0875 typed/native saved-frame join.

The established DXYZ crosscheck worker already implements the guarded,
single-pass typed-record/PartOut/RunPARTs join.  This adapter binds that code
to the separate S0875 CURRENT case and ROOT210 proof, including the existing
completed scientific-scan and PartVTKOut receipt.  Prepare mode reads only
bounded JSON/XML metadata and stats deferred payloads.  Audit mode is the
only path that opens the 417 MB typed JSONL, scan JSON, PartOut.csv, and
RunPARTs.csv after the parent reservation; it never opens H5 or BI4.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import ds_data02_stage2_f6_dxyz_typed_native_crosscheck_v3 as _base


SCRIPT = Path(__file__).resolve()
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
CASE_ID = "F6_STAGE1_ANGULAR_RELEASE_DYXZ_S0875_YAWP06_DP025"
FAMILY_ID = "F6"
CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
ROOT210_PROOF_SHA256 = "4c02c64912a46523d94c71c1836f807508d10079051a74fb5ec65f739ec0f5e5"
ROOT210_SUMMARY_SHA256 = "58c8c29dc816d87f154186f5e3c64a645ead972ed28903c061c1ebd82ed59e1c"
NATIVE_REPORT_SHA256 = "a733c30adc9e9710e022b2ce8af8921c1a1226c988366f98faa90cfe0246a65a"
SCAN_SHA256 = "7a66b9a53b7c09459a88f9b0fae22d1aa4e24c970fb189ff04f22d416a149bde"
SCAN_RECEIPT_SHA256 = "36f5d67b498bd13cc5136a2b01c24404ce707c766212dfe8a4cb0b371b887f6c"
CONVERSION_SHA256 = "33ef430b1d7c78a82e3beaa0649859df5855e359c5da2b054b1321d817da6d37"
GENERATED_XML_SHA256 = "728108c499545101c87149da838467cfdcd22451370b76efa96ea25f781e82e5"
GENCASE_RECEIPT_SHA256 = "d04fc3e7d421bfa1b76d3db4dd1673fbe0731241c2eaa550f2e398fa3d42f718"
SOLVER_RECEIPT_SHA256 = "4085f67c0b6c7e58fb3eb1e2aaff6f9b5994ff7262eb2c85d7648d1e5a94c63d"
NATIVE_DECODER_RECEIPT_SHA256 = "4c31739c34364c534ca5c1cca0663fe97f75553d8d5917c50b0425ea47cac268"
SCOPE_SHA256 = "7d0df4943329a5a1e7e52cc91bc2e8be68a4d039e027d548bd29f079b06b1eb3"
PARTOUT_SHA256 = "bbec1024312a31ee078f4c080faacaa571d5578f0ee76d6928b9887705f6d912"
PARTOUT_BYTES = 470
RUNPARTS_SHA256 = "06b3f87bb328dd0d6f3d110f96e2390df52ad50cee39a5eaf25b45b66027e137"
RUNPARTS_BYTES = 52394
RUNPARTS_ROWS = 241
RECORDS_SHA256 = "d92908cfb590905dd55ad613eaec8d40e98aee4b4ae75385b988940d4dc32617"
RECORDS_BYTES = 417443839
RECORDS_ROWS = 417505
PARTVTKOUT_SHA256 = "62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00"
PARTVTKOUT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64")


def _configure_base() -> None:
    """Set target constants once, preserving the consumed DXYZ module."""
    _base.SCRIPT = SCRIPT
    _base.VENV = VENV
    _base.CASE_ID = CASE_ID
    _base.FAMILY_ID = FAMILY_ID
    _base.CURRENT_SHA256 = CURRENT_SHA256
    _base.ROOT203_PROOF_SHA256 = ROOT210_PROOF_SHA256
    _base.ROOT203_SUMMARY_SHA256 = ROOT210_SUMMARY_SHA256
    _base.NATIVE_REPORT_SHA256 = NATIVE_REPORT_SHA256
    _base.SCAN_SHA256 = SCAN_SHA256
    _base.CONVERSION_SHA256 = CONVERSION_SHA256
    _base.GENERATED_XML_SHA256 = GENERATED_XML_SHA256
    _base.PARTOUT_SHA256 = PARTOUT_SHA256
    _base.RUNPARTS_SHA256 = RUNPARTS_SHA256
    _base.RECORDS_SHA256 = RECORDS_SHA256
    _base.SCHEMA = "ds02.stage2.f6-s0875-typed-native-crosscheck.v1"
    # The shared worker's small-input helper is JSON-only.  The generated XML
    # is a bounded source file, so retain the same stat/SHA contract while
    # validating its bytes as XML text rather than trying json.loads().
    if getattr(_base, "_s0875_xml_patch", False):
        return
    original = _base._hash_small_json

    def hash_small_json_or_xml(path: Path, label: str, expected: str) -> dict[str, Any]:
        if Path(path).suffix.lower() == ".xml":
            checked = _base._stat(Path(path), label)
            if checked["bytes"] > _base.MAX_SMALL_BYTES:
                raise _base.CrosscheckError(f"{label} exceeds bounded source size")
            actual = _base._sha256_file(Path(path), max_bytes=_base.MAX_SMALL_BYTES)
            if actual != _base._sha(expected, f"{label} expected SHA"):
                raise _base.CrosscheckError(f"{label} SHA differs")
            return {**checked, "sha256": actual, "content_opened": True, "format": "xml"}
        return original(path, label, expected)

    _base._hash_small_json = hash_small_json_or_xml
    _base._s0875_xml_patch = True


def _augment_contract(contract: dict[str, Any]) -> dict[str, Any]:
    inputs = contract.setdefault("inputs", {})
    tool_stat = _base._stat(PARTVTKOUT, "official PartVTKOut binary")
    inputs["partvtkout_binary"] = {**tool_stat, "sha256": PARTVTKOUT_SHA256, "content_opened": False, "role": "official_partvtkout_decoder_source"}
    base_script = Path(__file__).resolve().with_name("ds_data02_stage2_f6_dxyz_typed_native_crosscheck_v3.py")
    base_stat = _base._stat(base_script, "crosscheck worker dependency")
    inputs["crosscheck_worker_dependency"] = {**base_stat, "sha256": _base._sha256_file(base_script, max_bytes=_base.MAX_SMALL_BYTES), "content_opened": True, "role": "shared_crosscheck_worker_source"}
    native_edge = contract.setdefault("source_edges", {}).setdefault("native_decode", {})
    native_edge["partvtkout_tool"] = {"path": str(PARTVTKOUT), "sha256": PARTVTKOUT_SHA256, "content_opened": False, "reuse_existing_completed_decode": True}
    native_edge["existing_decode_receipt_status"] = "completed; CSV output reused, decoder is not relaunched by ROOT219"
    scan_ref = inputs.get("scientific_scan")
    if not isinstance(scan_ref, dict):
        raise _base.CrosscheckError("ROOT219 scientific scan input edge is missing")
    contract.setdefault("deferred_inputs", {})["scan_json"] = {
        **scan_ref,
        "content_opened": False,
        "read_policy": "DEFERRED_AFTER_PARENT_RESERVATION_SINGLE_PASS",
    }
    contract["comparison"]["native_output_scope"] = "existing completed PartVTKOut PartOut.csv only; no 241-frame BI4 decode"
    contract["adapter_schema"] = "ds02.stage2.f6-s0875-typed-native-crosscheck.v1"
    contract["worker_version"] = "f6-s0875-typed-native-crosscheck.v1"
    # This is one physical CURRENT case with three fluid identities.  Keep the
    # case/identity distinction explicit so the three rows cannot be reported
    # as three physical cases or as a new 65-case cause closure.
    contract["target_scope"] = {
        "physical_case_count": 1,
        "target_identity_count": 3,
        "target_role": "fluid",
        "target_identity_key": "(Zone,Idp)",
        "target_ids_are_physical_cases": False,
    }
    records_bytes = int(contract["deferred_inputs"]["typed_records"]["bytes"])
    partout_bytes = int(contract["deferred_inputs"]["partout_csv"]["bytes"])
    runparts_bytes = int(contract["deferred_inputs"]["runparts_csv"]["bytes"])
    scan_bytes = int(scan_ref["bytes"])
    # The future guarded audit reads each deferred artifact once: the full
    # typed JSONL, the small scan JSON, PartOut.csv, and RunPARTs.csv.  The
    # typed pass dominates cost (~417 MB); report the complete byte estimate
    # instead of silently omitting the scan pass.
    contract["resource_policy"].update({
        "scan_json_passes_minimum": 1,
        "scan_json_bytes": scan_bytes,
        "typed_records_passes_minimum": 1,
        "partout_passes_minimum": 1,
        "runparts_passes_minimum": 1,
        "deferred_input_passes_minimum": 4,
        "estimated_deferred_read_bytes": records_bytes + scan_bytes + partout_bytes + runparts_bytes,
        "estimated_input_read_bytes": records_bytes + scan_bytes + partout_bytes + runparts_bytes,
        "native_bi4_read": False,
        "h5_content_read": False,
        "solver_launch": False,
    })
    contract["claim_boundary"].update({
        "target_scope": "one physical case; three (Zone,Idp) fluid identities",
        "target_identity_count": 3,
        "physical_case_count": 1,
        "three_ids_are_not_three_cases": True,
        "typed_native_saved_frame_join": "DIAGNOSTIC_ONLY",
    })
    # Keep request accounting synchronized with the contract after the scan
    # became an explicit deferred one-pass input.
    records_bytes = int(contract["deferred_inputs"]["typed_records"]["bytes"])
    scan_bytes = int(contract["deferred_inputs"]["scan_json"]["bytes"])
    partout_bytes = int(contract["deferred_inputs"]["partout_csv"]["bytes"])
    runparts_bytes = int(contract["deferred_inputs"]["runparts_csv"]["bytes"])
    contract["resource_policy"].update({
        "scan_json_passes_minimum": 1,
        "scan_json_bytes": scan_bytes,
        "typed_records_passes_minimum": 1,
        "partout_passes_minimum": 1,
        "runparts_passes_minimum": 1,
        "deferred_input_passes_minimum": 4,
        "estimated_deferred_read_bytes": records_bytes + scan_bytes + partout_bytes + runparts_bytes,
        "estimated_input_read_bytes": records_bytes + scan_bytes + partout_bytes + runparts_bytes,
        "native_bi4_read": False,
        "h5_content_read": False,
        "solver_launch": False,
    })
    contract["claim_boundary"]["scientific_scan"] = "source-bound saved-frame scan rows only; scan status does not prove physical fate"
    return contract


def _read_scan_after_reservation(contract: dict[str, Any]) -> dict[str, Any]:
    deferred = contract.get("deferred_inputs", {}).get("scan_json")
    if not isinstance(deferred, dict):
        raise _base.CrosscheckError("ROOT219 deferred scientific scan edge is missing")
    path = Path(deferred["path"]).expanduser().resolve()
    before = _base._stat(path, "scientific scan", allow_deferred=True)
    if before["bytes"] != int(deferred.get("bytes", -1)):
        raise _base.CrosscheckError("scientific scan bytes differ before pass")
    expected_sha = _base._sha(deferred.get("sha256"), "scientific scan expected SHA")
    raw = path.read_bytes()
    actual_sha = hashlib.sha256(raw).hexdigest()
    if actual_sha != expected_sha:
        raise _base.CrosscheckError("scientific scan SHA differs")
    try:
        scan = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise _base.CrosscheckError("scientific scan is not valid JSON") from exc
    if not isinstance(scan, dict):
        raise _base.CrosscheckError("scientific scan must be a JSON object")
    after = _base._stat(path, "scientific scan after pass", allow_deferred=True)
    _base._require_same_stat(after, deferred, "scientific scan after pass")
    return {"path": str(path), "sha256": actual_sha, "bytes": after["bytes"], "pre_stat": before, "post_stat": after, "single_pass": True, "scan": scan}


def _enrich_with_scan(base_output_path: Path, final_output_path: Path, scan_evidence: dict[str, Any]) -> None:
    data = json.loads(base_output_path.read_text(encoding="utf-8"))
    scan = scan_evidence.pop("scan")
    if scan.get("schema") != "ds02.stage2.scientific-scan.v1" or scan.get("scan_status") != "SCANNED":
        raise _base.CrosscheckError("ROOT219 scientific scan schema/status differs")
    if scan.get("physical_case_id") != CASE_ID or scan.get("family_id") != FAMILY_ID:
        raise _base.CrosscheckError("ROOT219 scientific scan identity differs")
    missing = scan.get("missing_id_records")
    if not isinstance(missing, list) or len(missing) != 3:
        raise _base.CrosscheckError("ROOT219 scientific scan must contain exactly three missing records")
    scan_rows = {}
    for row in missing:
        if not isinstance(row, dict):
            raise _base.CrosscheckError("ROOT219 scientific scan missing row is malformed")
        key = (int(row.get("zone")), int(row.get("idp")))
        if key in scan_rows:
            raise _base.CrosscheckError(f"duplicate scientific scan identity: {key}")
        if row.get("native_exit_cause") != "EVIDENCE_UNKNOWN" or row.get("physical_fate") != "UNKNOWN":
            raise _base.CrosscheckError(f"scientific scan row {key} grants unsupported physical credit")
        scan_rows[key] = row
    output_rows = {(int(row["zone"]), int(row["idp"])): row for row in data.get("rows", [])}
    if set(output_rows) != set(scan_rows):
        raise _base.CrosscheckError("scientific scan identity set differs from typed/native rows")
    comparisons = []
    for key in sorted(scan_rows):
        row = scan_rows[key]
        joined = output_rows[key]
        scan_frame = row.get("first_missing_frame")
        scan_bracket = row.get("first_missing_bracket_s")
        if joined.get("typed_first_disappeared_frame") != scan_frame:
            raise _base.CrosscheckError(f"scientific scan/typed first frame differs for {key}")
        if joined.get("typed_first_disappeared_bracket_s") != scan_bracket:
            raise _base.CrosscheckError(f"scientific scan/typed bracket differs for {key}")
        comparisons.append({"zone": key[0], "idp": key[1], "scan_first_missing_frame": scan_frame, "scan_first_missing_bracket_s": scan_bracket, "scan_native_cause": row.get("native_exit_cause"), "typed_native_saved_frame_join": True, "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN"})
    data["scientific_scan_evidence"] = {**scan_evidence, "identity_count": len(comparisons), "rows": comparisons, "source_native_cause_credit": "NONE; scan rows retain EVIDENCE_UNKNOWN"}
    data["claim_boundary"]["scientific_scan_saved_frame_join"] = "DIAGNOSTIC_ONLY"
    _base._atomic_json(final_output_path, data, max_bytes=_base.MAX_OUTPUT_BYTES)


def _request_from_contract(contract_path: Path, request_path: Path, python_path: Path | None) -> dict[str, Any]:
    contract = _base._read_small_json(contract_path, "ROOT219 S0875 contract")
    declared_python = VENV if python_path is None else Path(python_path).expanduser()
    resolved_python = declared_python.resolve()
    if not resolved_python.is_file():
        raise _base.CrosscheckError(f"interpreter is missing: {declared_python}")
    request = _base._request_from_contract(contract_path, request_path, SCRIPT, declared_python)
    request["worker_version"] = "f6-s0875-typed-native-crosscheck.v1"
    request["command"] = [str(declared_python), str(SCRIPT), "audit", "--contract", str(contract_path.expanduser().absolute()), "--output", "{attempt_root}/f6-s0875-typed-native-crosscheck-v1.json"]
    request["physical_case_id"] = CASE_ID
    request["family_id"] = FAMILY_ID
    request["deferred_input_files"].append(str(Path(contract["deferred_inputs"]["scan_json"]["path"]).expanduser().resolve()))
    request["deferred_input_sha256"][str(Path(contract["deferred_inputs"]["scan_json"]["path"]).expanduser().resolve())] = contract["deferred_inputs"]["scan_json"]["sha256"]
    request["resource_policy"].update({
        "scan_json_passes_minimum": 1,
        "scan_json_bytes": int(contract["deferred_inputs"]["scan_json"]["bytes"]),
        "native_bi4_read": False,
        "h5_content_read": False,
        "solver_launch": False,
    })
    # Keep the request's identity/claim boundary and cost fields exactly in
    # step with the prepared contract; three IDs remain one physical case.
    request["target_scope"] = contract.get("target_scope", {"physical_case_count": 1, "target_identity_count": 3, "target_ids_are_physical_cases": False})
    request["claim_boundary"].update(contract.get("claim_boundary", {}))
    request["claim_boundary"].update({"typed_native_saved_frame_join": "DIAGNOSTIC_ONLY", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"})
    request["launch_allowed"] = False
    return request


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    _configure_base()
    contract = _augment_contract(_base._build_contract(args))
    output = Path(args.output).expanduser().resolve()
    _base._atomic_json(output, contract, max_bytes=_base.MAX_OUTPUT_BYTES)
    result: dict[str, Any] = {"status": contract["status"], "contract": str(output), "contract_sha256": _base._sha256_file(output, max_bytes=_base.MAX_OUTPUT_BYTES)}
    if args.request_output:
        request_output = Path(args.request_output).expanduser().resolve()
        request = _request_from_contract(output, request_output, Path(args.python).expanduser() if args.python else None)
        _base._atomic_json(request_output, request, max_bytes=_base.MAX_OUTPUT_BYTES)
        result.update({"request": str(request_output), "request_sha256": _base._sha256_file(request_output, max_bytes=_base.MAX_OUTPUT_BYTES)})
    return result


def audit(contract_path: Path, output_path: Path) -> dict[str, Any]:
    _configure_base()
    contract = _base._read_small_json(contract_path, "ROOT219 S0875 contract")
    scan_evidence = _read_scan_after_reservation(contract)
    temporary = output_path.with_name(f".{output_path.name}.base")
    temporary.unlink(missing_ok=True)
    try:
        result = _base.audit(contract_path, temporary)
        _enrich_with_scan(temporary, output_path, scan_evidence)
        result["output"] = str(output_path.resolve())
        result["scientific_scan_join_count"] = 3
        return result
    finally:
        temporary.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    _configure_base()
    parser = _base._parser()
    # The shared parser's prepare flags are retained for exact source role
    # binding; ROOT219 maps root210-labelled flags to the actual ROOT210 files.
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_base()
    args = _parser().parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare(args)
        else:
            # Audit uses the same contract checks and exact deferred joins;
            # ROOT219 must bind all target constants before reading anything.
            result = audit(args.contract, args.output)
    except (_base.CrosscheckError, OSError) as exc:
        print(f"{type(exc).__name__}: {exc}", flush=True)
        return 2
    import json
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
