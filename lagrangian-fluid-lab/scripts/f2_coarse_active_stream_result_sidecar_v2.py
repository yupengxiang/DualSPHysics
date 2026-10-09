#!/usr/bin/env python3
"""Validate the JSON-only scientific boundary of a completed V8 stream.

This sidecar consumes only a V8 JSON report and its execution receipt.  It does
not reopen Part_*.bi4, H5, PartOut, or RunPARTs.  It is intentionally a
post-consumption interface: exact MassFluid bits and finite saved-frame fields
can be source-closed while the 153 native omissions remain a lower-bound
screen.  The frozen XML whole-initial mass denominator is used for the .003
screen; bits closure never grants QI/QN/QE or physical-fate credit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any

SCHEMA = "ds02.stage2.f2.coarse-active-stream-result-sidecar.v2"
V8_SCHEMA = "ds02.stage2.f2.coarse-active-stream.v8"
V8_STATUS = "COMPLETED_F2_COARSE_ACTIVE_FLUID_STREAM_V8_EXACT_NATIVE_MASS_BITS"
ROOT_PROOF_SCHEMA = "ds02.stage2.root-actual-verification.v1"
ROOT_PROOF_STATUS = "VERIFIED_ACTUAL_401_NATIVE_FRAME_STREAM_EXACT_MASS_ENCODING_AND_CENSOR_SCREEN_FAIL"
CASE_KEY = "F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0088_T4_COARSE_CANARY_ROOT_095"
EXPECTED_NATIVE_OMISSION_COUNT = 153
UNKNOWN_MASS_FRACTION_MAX = 0.003
MAX_SIDEcar_BYTES = 8 * 1024 * 1024


class SidecarError(ValueError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path, label: str) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise SidecarError(f"{label} is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SidecarError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise SidecarError(f"{label} is not an object: {path}")
    return value


def stat_record(path: Path) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size, "sha256": sha256(path)}


def _completed_receipt(receipt: dict[str, Any], receipt_path: Path, report_path: Path) -> dict[str, Any]:
    if receipt.get("schema") != "ds02.execution-receipt.v1":
        raise SidecarError("execution receipt schema differs")
    request = receipt.get("request")
    if not isinstance(request, dict):
        raise SidecarError("execution receipt lacks embedded request")
    if request.get("physical_case_id") != CASE_KEY:
        raise SidecarError("execution receipt case differs")
    output = request.get("output")
    if not isinstance(output, dict) or output.get("schema") != V8_SCHEMA:
        raise SidecarError("execution receipt output schema differs")
    output_root = receipt.get("output_root")
    if not isinstance(output_root, str) or Path(output_root).expanduser().resolve() != report_path.parent.resolve():
        raise SidecarError("execution receipt does not contain the supplied report")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise SidecarError("completed sidecar path requires a successful V8 receipt")
    return stat_record(receipt_path)


def _proof_binding(
    proof: dict[str, Any], proof_path: Path, report_path: Path, receipt_path: Path
) -> dict[str, Any]:
    """Bind the independent ROOT126 proof to the exact report and receipt.

    A completed-looking report/receipt pair is insufficient because a same-case
    copied JSON can otherwise receive a sidecar.  The proof is read as a small
    JSON input only; it does not authorize reopening any raw frame or H5.
    """
    if proof.get("schema") != ROOT_PROOF_SCHEMA or proof.get("status") != ROOT_PROOF_STATUS:
        raise SidecarError("ROOT126 proof is not the completed V8 verification")
    if proof.get("request_sha256") is None or proof.get("report_sha256") is None or proof.get("receipt_sha256") is None:
        raise SidecarError("ROOT126 proof lacks request/report/receipt digests")
    if proof.get("report") != str(report_path) or proof.get("receipt") != str(receipt_path):
        raise SidecarError("ROOT126 proof paths do not bind the supplied report and receipt")
    if proof.get("report_sha256") != sha256(report_path):
        raise SidecarError("ROOT126 proof report SHA differs")
    if proof.get("receipt_sha256") != sha256(receipt_path):
        raise SidecarError("ROOT126 proof receipt SHA differs")
    if proof.get("frame_count") != 401 or proof.get("exact153_native_motive_lifecycle_joins") is not True:
        raise SidecarError("ROOT126 proof does not bind the complete 401/153 stream")
    if proof.get("parent_actual_prepost_content_hashes_equal") is not True or proof.get("all401_worker_full_sha_prepost_equal") is not True:
        raise SidecarError("ROOT126 proof lacks stable worker pre/post closure")
    if proof.get("root_raw_or_h5_read_or_hash") is not False:
        raise SidecarError("ROOT126 proof widens the sidecar read scope")
    if proof.get("mass_screen") != "FAIL_OVER_FROZEN_XML_WHOLE_INITIAL_0P003":
        raise SidecarError("ROOT126 proof does not preserve the frozen mass-screen failure")
    if proof.get("scientific_qualification") != "QI/QN/QE UNKNOWN; source-field and lifecycle evidence only, physical fate/dynamics/continuous event errors remain unknown":
        raise SidecarError("ROOT126 proof widens scientific qualification")
    return stat_record(proof_path)


def _unknown_claims(report: dict[str, Any]) -> None:
    claim = report.get("claim_boundary")
    if not isinstance(claim, dict):
        raise SidecarError("V8 report lacks claim boundary")
    for key in ("physical_destination_or_legal_flux", "dynamical_impact", "QI", "QN", "QE"):
        if claim.get(key) != "UNKNOWN":
            raise SidecarError(f"V8 report widens unsupported claim: {key}")


def _validate_completed(report: dict[str, Any], report_path: Path, receipt_stat: dict[str, Any]) -> dict[str, Any]:
    if report.get("schema") != V8_SCHEMA or report.get("status") != V8_STATUS:
        raise SidecarError("V8 report is not the completed exact-bit stream product")
    if report.get("case_key") != CASE_KEY or report.get("physical_case_id") != CASE_KEY:
        raise SidecarError("V8 report physical identity differs")
    _unknown_claims(report)
    stability = report.get("input_stability")
    if not isinstance(stability, dict) or stability.get("all_equal") is not True:
        raise SidecarError("V8 report lacks complete pre/post input stability")
    stream = report.get("active_fluid_stream")
    if not isinstance(stream, dict) or stream.get("frame_count") != 401:
        raise SidecarError("V8 report does not contain the complete 401-frame stream")
    gate = stream.get("massfluid_bit_gate")
    if not isinstance(gate, dict) or gate.get("all_frames_exact_match") is not True or gate.get("absolute_tolerance") is not None or gate.get("mass_rescaling") is not False:
        raise SidecarError("V8 exact MassFluid bit gate is incomplete")
    if len(str(gate.get("expected_bits_hex", ""))) != 16:
        raise SidecarError("V8 expected MassFluid bits are missing")
    rows = (report.get("native_identity_join") or {}).get("rows")
    if not isinstance(rows, list) or len(rows) != EXPECTED_NATIVE_OMISSION_COUNT:
        raise SidecarError("V8 native omission identity count is not the bound F2 coarse 153")
    keys = {(row.get("case_key", CASE_KEY), row.get("idp")) for row in rows if isinstance(row, dict)}
    if len(keys) != EXPECTED_NATIVE_OMISSION_COUNT or any(key[0] != CASE_KEY for key in keys):
        raise SidecarError("V8 native omission rows are not unique case-qualified identities")
    material = report.get("mass_and_material")
    if not isinstance(material, dict):
        raise SidecarError("V8 report lacks mass/material ledger")
    xml_whole = float(stream.get("xml_whole_initial_fluid_mass_kg"))
    native_whole = float(stream.get("native_whole_initial_fluid_mass_kg"))
    native_massfluid = float(stream.get("native_massfluid_kg"))
    excluded_mass = float(material.get("native_excluded_mass_lower_bound_kg"))
    if not (math.isfinite(xml_whole) and math.isfinite(native_whole) and math.isfinite(native_massfluid) and math.isfinite(excluded_mass)):
        raise SidecarError("V8 mass ledger is non-finite")
    if xml_whole <= 0 or native_whole <= 0 or native_massfluid <= 0 or excluded_mass <= 0:
        raise SidecarError("V8 mass ledger is non-positive")
    observed_fraction = excluded_mass / xml_whole
    if observed_fraction <= UNKNOWN_MASS_FRACTION_MAX:
        raise SidecarError("bound F2 coarse 153 omission unexpectedly passes frozen .003 XML screen")
    screen = material.get("unknown_identity_mass_screen") or {}
    if screen.get("screen_result_only") is not False or screen.get("whole_initial_fraction_max") != UNKNOWN_MASS_FRACTION_MAX:
        raise SidecarError("V8 report does not preserve the frozen XML .003 failure")
    return {
        "status": "V8_STREAM_SOURCE_CLOSED_UNKNOWN_MASS_SCREEN_FAIL",
        "report": stat_record(report_path),
        "execution_receipt": receipt_stat,
        "frame_count": 401,
        "native_omission_count": EXPECTED_NATIVE_OMISSION_COUNT,
        "native_excluded_mass_lower_bound_kg": excluded_mass,
        "xml_whole_initial_fluid_mass_kg": xml_whole,
        "native_whole_initial_fluid_mass_kg": native_whole,
        "native_massfluid_kg": native_massfluid,
        "observed_unknown_identity_lower_bound_fraction_xml": observed_fraction,
        "frozen_unknown_identity_fraction_max": UNKNOWN_MASS_FRACTION_MAX,
        "mass_screen": "FAIL_OVER_FROZEN_XML_WHOLE_INITIAL_0P003",
        "physical_fate": "UNKNOWN",
        "legal_outflow_or_spill": "UNKNOWN",
        "dynamical_impact": "UNKNOWN",
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "meaning": "Exact native MassFluid serialization and saved-frame identity do not bound the fate or dynamical impact of the omitted 153 IDs.",
    }


def sidecar(report_path: Path, receipt_path: Path, proof_path: Path, output_path: Path) -> dict[str, Any]:
    report_path = Path(report_path).expanduser().resolve()
    receipt_path = Path(receipt_path).expanduser().resolve()
    proof_path = Path(proof_path).expanduser().resolve()
    report = read_json(report_path, "V8 report")
    receipt = read_json(receipt_path, "V8 execution receipt")
    proof = read_json(proof_path, "ROOT126 verification proof")
    receipt_stat = _completed_receipt(receipt, receipt_path, report_path)
    proof_stat = _proof_binding(proof, proof_path, report_path, receipt_path)
    result = {
        "schema": SCHEMA,
        "case_key": CASE_KEY,
        "source_scope": "JSON-only V8 report/receipt; no raw BI4/H5/PartOut/RunPARTs reopened",
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "verification_proof": proof_stat,
        "product": _validate_completed(report, report_path, receipt_stat),
        "read_policy": {"hdf5_opened": False, "raw_bi4_opened": False, "solver_started": False, "old_products_modified": False},
    }
    payload = (json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    if len(payload) > MAX_SIDEcar_BYTES:
        raise SidecarError(f"sidecar exceeds bounded JSON output size: {len(payload)}>{MAX_SIDEcar_BYTES}")
    output_path = Path(output_path).expanduser().resolve()
    if output_path.exists():
        raise SidecarError(f"refusing to overwrite sidecar: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{output_path.name}.", dir=str(output_path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output_path)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return {"schema": SCHEMA, "status": result["product"]["status"], "output": str(output_path)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--proof", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(sidecar(args.report, args.receipt, args.proof, args.output), sort_keys=True))
    except Exception as exc:
        print(f"F2 V8 result sidecar failed: {exc}", file=os.sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
