#!/usr/bin/env python3
"""Bind F5 Root455 native metadata to later producer JSON, without payload I/O.

The source side may read JSON receipts/reports and hash those JSON files.  It
does not open or hash BI4/H5/CSV/VTK/DAT files.  A native-only invocation is
the expected fresh105 handoff.  Root can later supply all five typed/XMF/bed
JSON metadata files; the result remains a review record and never enables a
runner request or grants full801/Q-N acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


HEX = set("0123456789abcdefABCDEF")
FRAMES = 51
COUNTS = {"total": 194427, "fixed": 158559, "moving": 4210, "floating": 0, "fluid": 31658}
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
SCIENCE_SUFFIXES = {".bi4", ".csv", ".h5", ".hdf5", ".vtk", ".vtu", ".npy", ".npz", ".dat"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_json(path: Path) -> dict[str, Any]:
    require(path.suffix.lower() == ".json", f"JSON metadata only: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def json_sha(path: Path) -> str:
    require(path.suffix.lower() == ".json", f"JSON digest only: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(value: Any, label: str) -> str:
    require(isinstance(value, str) and len(value) == 64 and set(value) <= HEX, f"{label} must be a producer SHA-256")
    return value


def completed(receipt: Mapping[str, Any], label: str) -> None:
    require(receipt.get("status") == "completed", f"{label} status is not completed")
    code = receipt.get("returncode", receipt.get("return_code", receipt.get("exit_code")))
    require(code is not None and int(code) == 0, f"{label} return code is not zero")


def identity(receipt: Mapping[str, Any]) -> dict[str, Any]:
    req = receipt.get("request")
    req = req if isinstance(req, dict) else {}
    return {
        "attempt_id": req.get("attempt_id") or receipt.get("attempt_id"),
        "case_id": req.get("case_id") or receipt.get("case_id"),
        "candidate_id": req.get("candidate_id"),
        "output_root": receipt.get("output_root") or req.get("output_root"),
    }


def check_native(receipt_path: Path, expected_attempt: str, candidate: str) -> dict[str, Any]:
    receipt = load_json(receipt_path)
    completed(receipt, "Root455 native receipt")
    ident = identity(receipt)
    require(ident["attempt_id"] == expected_attempt and ident["case_id"] == CASE, f"{candidate}: native identity mismatch")
    req = receipt.get("request")
    require(isinstance(req, dict), f"{candidate}: native nested request missing")
    require(req.get("expected_frames") == FRAMES and req.get("expected_dimension") == 3, f"{candidate}: native frame/dimension contract")
    require(req.get("actual_counts") == {**COUNTS, "dimension": 3}, f"{candidate}: native actual counts mismatch")
    require(receipt.get("production_product_acceptance") in {"not_assessed", None}, f"{candidate}: native acceptance was unexpectedly granted")
    return {
        "candidate": candidate,
        "receipt_path": str(receipt_path),
        "receipt_sha256": json_sha(receipt_path),
        "identity": ident,
        "actual_counts": {**COUNTS, "dimension": 3},
        "frames": FRAMES,
        "solver_dimension": 3,
        "solver_output_root": str(Path(str(ident["output_root"])) / "solver_output"),
        "saved_state_metadata": "Root must verify the actual 51 Part_*.bi4 files and first-state zero-velocity QA before enabling typed conversion",
        "q_n_granted": False,
        "full801_authorized": False,
    }


def typed_metadata(report_path: Path, receipt_path: Path, candidate: str) -> dict[str, Any]:
    report = load_json(report_path)
    receipt = load_json(receipt_path)
    completed(receipt, "typed receipt")
    require(report.get("schema") == "ds-data-02.bi4-direct-conversion.v1", f"{candidate}: typed report schema")
    require(report.get("conversion_status") == "completed" and int(report.get("frames", -1)) == FRAMES, f"{candidate}: typed producer status/frames")
    require(int(report.get("particles", -1)) == COUNTS["total"], f"{candidate}: typed particle axis")
    dim = report.get("solver_dimension")
    require(isinstance(dim, dict) and int(dim.get("solver_dimension", -1)) == 3, f"{candidate}: typed solver_dimension evidence")
    require(3 in {int(v) for v in dim.get("run_out_dimensions", [])} and str(dim.get("xml_data2d", "")).lower() in {"false", "0"}, f"{candidate}: typed N3 evidence")
    ident = identity(receipt)
    require(ident["case_id"] == CASE, f"{candidate}: typed receipt case")
    ti = report.get("typed_identity")
    require(isinstance(ti, dict), f"{candidate}: typed identity missing")
    mks = {int(v) for v in ti.get("observed_mks", [])}
    types = {int(v) for v in ti.get("observed_types", [])}
    require(50 in mks and {0, 1, 3}.issubset(types), f"{candidate}: typed marker/type identity incomplete")
    output_sha = digest(report.get("output_sha256"), f"{candidate}: typed output_sha256")
    return {
        "report_path": str(report_path), "report_sha256": json_sha(report_path),
        "receipt_path": str(receipt_path), "receipt_sha256": json_sha(receipt_path),
        "receipt_identity": ident, "schema": report["schema"], "frames": FRAMES,
        "particles": int(report["particles"]), "solver_dimension": dim,
        "producer_h5_sha256": output_sha, "observed_mks": sorted(mks), "observed_types": sorted(types),
        "mass_policy": "producer report only; no rescale",
    }


def xmf_metadata(manifest_path: Path, receipt_path: Path, typed: Mapping[str, Any], candidate: str) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    receipt = load_json(receipt_path)
    completed(receipt, "XMF receipt")
    require(manifest.get("schema") == "ds02.stage1.paraview-temporal-product.v1", f"{candidate}: XMF schema")
    require(int(manifest.get("frames", -1)) == FRAMES and int(manifest.get("particles", -1)) == COUNTS["total"], f"{candidate}: XMF frame/axis")
    require(manifest.get("source_h5_sha256") == typed["producer_h5_sha256"], f"{candidate}: XMF source H5 does not match typed producer SHA")
    canonical = digest(manifest.get("canonical_physical_condition_sha256"), f"{candidate}: XMF canonical physical hash")
    source = digest(manifest.get("source_h5_physical_condition_sha256"), f"{candidate}: XMF legacy H5 scope hash")
    require(canonical != source, f"{candidate}: XMF collapsed canonical/legacy physical identity")
    semantics = manifest.get("physical_condition_hash_semantics")
    require(isinstance(semantics, dict), f"{candidate}: XMF hash semantics missing")
    require(semantics.get("canonical_owner_sha256") == canonical and semantics.get("source_h5_sha256") == source, f"{candidate}: XMF semantic sidecar mismatch")
    return {
        "manifest_path": str(manifest_path), "manifest_sha256": json_sha(manifest_path),
        "receipt_path": str(receipt_path), "receipt_sha256": json_sha(receipt_path),
        "receipt_identity": identity(receipt), "schema": manifest["schema"], "frames": FRAMES,
        "particles": COUNTS["total"], "source_h5_sha256": typed["producer_h5_sha256"],
        "canonical_physical_condition_sha256": canonical, "source_h5_physical_condition_sha256": source,
        "derived_view_only": True, "visual_status": manifest.get("visual_status", "pending"),
    }


def bed_metadata(report_path: Path, candidate: str) -> dict[str, Any]:
    report = load_json(report_path)
    require(report.get("diagnostic_only") is True, f"{candidate}: bed report not diagnostic-only")
    require(report.get("full16_authorized") is False, f"{candidate}: bed report grants full16")
    scan = report.get("scan")
    require(isinstance(scan, dict) and int(scan.get("frames_scanned", -1)) == FRAMES, f"{candidate}: bed report did not scan 51 frames")
    diag = report.get("dynamic_bed_diagnostic")
    require(isinstance(diag, dict) and diag.get("thresholds_are_diagnostic_only") is True, f"{candidate}: bed threshold semantics changed")
    return {
        "report_path": str(report_path), "report_sha256": json_sha(report_path),
        "schema": report.get("schema"), "frames_scanned": FRAMES, "diagnostic_only": True,
        "dynamic_acceptance": "not granted; Root visual and framewise review required",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", choices=("A080", "A120"), required=True)
    parser.add_argument("--native-receipt", type=Path, required=True)
    parser.add_argument("--native-attempt", required=True)
    parser.add_argument("--typed-report", type=Path)
    parser.add_argument("--typed-receipt", type=Path)
    parser.add_argument("--xmf-manifest", type=Path)
    parser.add_argument("--xmf-receipt", type=Path)
    parser.add_argument("--bed-report", type=Path)
    parser.add_argument("--output-summary", type=Path, required=True)
    args = parser.parse_args()
    native = check_native(args.native_receipt, args.native_attempt, args.candidate)
    future = (args.typed_report, args.typed_receipt, args.xmf_manifest, args.xmf_receipt, args.bed_report)
    require(all(v is None for v in future) or all(v is not None for v in future), "bind all typed/XMF/bed JSON metadata together or bind none")
    result: dict[str, Any] = {
        "schema": "ds02.f5.c082s1.fresh105.downstream-binding.v1",
        "status": "native_bound_downstream_products_pending" if all(v is None for v in future) else "root_review_required_products_bound",
        "source_only": True, "candidate": args.candidate, "case_id": CASE,
        "native": native, "typed": None, "xmf": None, "bed_audit": None,
        "future_hashes": None, "q_n_granted": False, "full801_authorized": False,
        "independent_case_count_increment": 0, "science_payloads_read_or_hashed_by_binder": False,
        "exact_dp_lattice_diagnostic": {"threshold": 1e-6, "historical_negative_retained": True, "stage1_gate_relaxed": False},
    }
    if all(v is not None for v in future):
        typed = typed_metadata(args.typed_report, args.typed_receipt, args.candidate)
        xmf = xmf_metadata(args.xmf_manifest, args.xmf_receipt, typed, args.candidate)
        bed = bed_metadata(args.bed_report, args.candidate)
        result.update({"typed": typed, "xmf": xmf, "bed_audit": bed,
                       "status": "root_review_required_products_bound",
                       "future_hashes": {"typed_h5_sha256": typed["producer_h5_sha256"], "xmf_manifest_sha256": xmf["manifest_sha256"], "bed_report_sha256": bed["report_sha256"]},
                       "acceptance_boundary": "typed/XMF/bed products are derived/diagnostic; full801 and Q-N remain ungranted"})
    args.output_summary.parent.mkdir(parents=True, exist_ok=True)
    args.output_summary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "candidate": args.candidate, "science_payloads_read_or_hashed_by_binder": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
