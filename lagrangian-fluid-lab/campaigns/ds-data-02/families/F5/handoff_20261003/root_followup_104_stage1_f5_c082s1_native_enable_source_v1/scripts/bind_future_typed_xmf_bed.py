#!/usr/bin/env python3
"""Metadata-only future typed/XMF/bed receipt binder for F5 fresh103.

The source agent may read JSON receipts/reports and producer-declared output
digests. It never opens, decodes, or hashes BI4/CSV/H5/VTK/XMF science
payloads. With no product arguments it emits a null future binding plan. With
Root-supplied JSON metadata it validates the producer schema and emits a
reviewable summary; it does not enable a runner request or grant acceptance.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

HEX = set("0123456789abcdefABCDEF")
SCIENCE_SUFFIXES = {".bi4", ".csv", ".h5", ".hdf5", ".vtk", ".vtu", ".npy", ".npz", ".dat"}
EXPECTED_FRAMES = 51


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_json(path: Path) -> dict[str, Any]:
    require(path.suffix.lower() == ".json", f"JSON metadata only: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def completed(receipt: Mapping[str, Any], label: str) -> None:
    require(receipt.get("status") == "completed", f"{label} status is not completed")
    code = receipt.get("returncode", receipt.get("return_code", receipt.get("exit_code")))
    require(code is not None and int(code) == 0, f"{label} return code is not zero: {code!r}")


def receipt_identity(receipt: Mapping[str, Any]) -> dict[str, Any]:
    request = receipt.get("request")
    request = request if isinstance(request, dict) else {}
    return {
        "attempt_id": request.get("attempt_id") or receipt.get("attempt_id"),
        "case_id": request.get("case_id") or receipt.get("case_id"),
        "output_root": receipt.get("output_root") or request.get("output_root"),
    }


def digest_from_report(value: Any, label: str) -> str:
    require(isinstance(value, str) and len(value) == 64 and set(value) <= HEX,
            f"{label} must be a producer-declared SHA-256")
    return value


def gencase_metadata(receipt: Mapping[str, Any], prepared: Mapping[str, Any],
                     candidate_id: str) -> dict[str, Any]:
    """Validate producer JSON for GenCase without opening XML/BI4 payloads."""
    completed(receipt, "GenCase receipt")
    identity = receipt_identity(receipt)
    require(identity["attempt_id"] and identity["case_id"],
            "GenCase receipt lacks nested request identity")
    total = int(receipt.get("total_particles", -1))
    fluid = int(receipt.get("fluid_particles", -1))
    dimension = int(receipt.get("solver_dimension_from_gencase", -1))
    require(total > 0 and 0 < fluid < total, "GenCase receipt has invalid producer counts")
    require(dimension == 3, "GenCase producer is not 3-D")
    report_total = int(prepared.get("actual_total_particles", -1))
    report_counts = prepared.get("generated_xml_particle_counts")
    require(report_total == total and isinstance(report_counts, dict),
            "prepared GenCase report does not expose actual counts")
    fixed = int(report_counts.get("fixed", -1))
    moving = int(report_counts.get("moving", -1))
    floating = int(report_counts.get("floating", -1))
    report_fluid = int(report_counts.get("fluid", -1))
    require(min(fixed, moving, floating, report_fluid) >= 0,
            "prepared GenCase report has invalid particle categories")
    require(report_fluid == fluid and fixed + moving + floating + report_fluid == total,
            "GenCase receipt/prepared report count mismatch")
    constants = prepared.get("actual_generated_constants", {})
    data2d = constants.get("data2d", {}).get("value") if isinstance(constants, dict) else None
    require(str(data2d).lower() in {"false", "0"}, "GenCase prepared report is marked 2-D")
    return {
        "candidate_id": candidate_id,
        "receipt_identity": identity,
        "schema": prepared.get("schema"),
        "actual_counts": {
            "total": total,
            "fixed": fixed,
            "moving": moving,
            "fluid": fluid,
            "floating": floating,
        },
        "solver_dimension_from_gencase": dimension,
        "data2d": False,
        "producer_xml_sha256": digest_from_report(prepared.get("xml_sha256"),
                                                   "prepared XML SHA-256"),
        "producer_bi4_sha256": digest_from_report(prepared.get("bi4_sha256"),
                                                  "prepared BI4 SHA-256"),
        "counts_source": "actual GenCase receipt and prepared-input-report; no source-agent payload read",
    }


def report_metadata(report: Mapping[str, Any], label: str) -> dict[str, Any]:
    """Keep QA reports opaque except for their producer-declared status/schema."""
    status = report.get("status", report.get("gate_status", report.get("result")))
    require(status is not None, f"{label} has no status/gate_status/result field")
    return {
        "schema": report.get("schema"),
        "status": status,
        "producer_report_identity": report.get("attempt_id") or report.get("case_id"),
    }


def typed_metadata(report: Mapping[str, Any], candidate_id: str) -> dict[str, Any]:
    require(report.get("schema") == "ds-data-02.bi4-direct-conversion.v1",
            "typed report schema is not the registered direct-conversion producer schema")
    require(report.get("conversion_status") == "completed", "typed conversion is not completed")
    require(int(report.get("frames", -1)) == EXPECTED_FRAMES, "typed report is not 51 saved states")
    particles = int(report.get("particles", -1))
    require(particles > 0, "typed report has no producer particle axis")
    dim = report.get("solver_dimension")
    require(isinstance(dim, dict), "solver_dimension must remain the producer evidence object")
    require(int(dim.get("solver_dimension", -1)) == 3, "typed producer is not 3-D")
    run_out = dim.get("run_out_dimensions")
    require(isinstance(run_out, list) and 3 in {int(v) for v in run_out},
            "typed producer Run.out dimensions lack 3")
    require(str(dim.get("xml_data2d", "")).lower() in {"false", "0"},
            "typed producer is marked 2-D")
    identity = report.get("typed_identity")
    require(isinstance(identity, dict), "typed report lacks typed_identity")
    blocks = identity.get("blocks")
    require(isinstance(blocks, list), "typed report lacks typed_identity.blocks")
    observed_mks = {int(v) for v in identity.get("observed_mks", [])}
    observed_types = {int(v) for v in identity.get("observed_types", [])}
    require(50 in observed_mks, "typed producer lacks native Mk50")
    require({0, 1, 3}.issubset(observed_types), "typed producer type identity is incomplete")
    output_sha = digest_from_report(report.get("output_sha256"), "typed report output_sha256")
    return {
        "candidate_id": candidate_id,
        "schema": report.get("schema"),
        "frames": EXPECTED_FRAMES,
        "particles": particles,
        "solver_dimension": {
            "producer_field_shape": "evidence_object",
            "solver_dimension": 3,
            "run_out_dimensions": [int(v) for v in run_out],
            "xml_data2d": dim.get("xml_data2d"),
        },
        "producer_h5_sha256": output_sha,
        "observed_mks": sorted(observed_mks),
        "observed_types": sorted(observed_types),
        "mass_policy": "copied from producer report; no rescale",
    }


def xmf_metadata(manifest: Mapping[str, Any], typed: Mapping[str, Any], candidate_id: str) -> dict[str, Any]:
    require(manifest.get("schema") == "ds02.stage1.paraview-temporal-product.v1",
            "XMF manifest schema is not the registered temporal product schema")
    require(int(manifest.get("frames", -1)) == EXPECTED_FRAMES, "XMF manifest is not 51 frames")
    require(int(manifest.get("particles", -1)) == int(typed["particles"]),
            "XMF particle axis differs from typed producer report")
    require(manifest.get("source_h5_sha256") == typed["producer_h5_sha256"],
            "XMF source H5 digest is not the typed producer digest")
    canonical = manifest.get("canonical_physical_condition_sha256")
    require(isinstance(canonical, str) and len(canonical) == 64, "XMF canonical physical hash missing")
    source = manifest.get("source_h5_physical_condition_sha256")
    require(isinstance(source, str) and len(source) == 64 and source != canonical,
            "XMF legacy H5 scope is missing or collapsed into canonical identity")
    semantics = manifest.get("physical_condition_hash_semantics")
    require(isinstance(semantics, dict), "XMF physical hash semantics missing")
    require(semantics.get("canonical_owner_sha256") == canonical and
            semantics.get("source_h5_sha256") == source,
            "XMF canonical/legacy semantic sidecar mismatch")
    return {
        "candidate_id": candidate_id,
        "schema": manifest.get("schema"),
        "frames": EXPECTED_FRAMES,
        "particles": int(typed["particles"]),
        "source_h5_sha256": typed["producer_h5_sha256"],
        "canonical_physical_condition_sha256": canonical,
        "source_h5_physical_condition_sha256": source,
        "visual_status": manifest.get("visual_status", "pending"),
        "derived_view_only": True,
    }


def bed_metadata(report: Mapping[str, Any], candidate_id: str) -> dict[str, Any]:
    require(report.get("diagnostic_only") is True, "bed report is not diagnostic-only")
    require(report.get("full16_authorized") is False, "bed report grants full16 unexpectedly")
    scan = report.get("scan", {})
    require(isinstance(scan, dict) and int(scan.get("frames_scanned", -1)) == EXPECTED_FRAMES,
            "bed report did not scan all 51 frames")
    diagnostic = report.get("dynamic_bed_diagnostic", {})
    require(isinstance(diagnostic, dict) and diagnostic.get("thresholds_are_diagnostic_only") is True,
            "bed report changed penetration threshold semantics")
    return {
        "candidate_id": candidate_id,
        "frames_scanned": EXPECTED_FRAMES,
        "diagnostic_only": True,
        "full16_authorized": False,
        "dynamic_acceptance": "not granted; Root visual and framewise review required",
        "report_schema": report.get("schema"),
    }


def make_null_plan(candidate_id: str) -> dict[str, Any]:
    return {
        "schema": "ds02.f5.c082s1.fresh103.future-binding-plan.v1",
        "status": "awaiting_root_bound_products",
        "source_only": True,
        "candidate_id": candidate_id,
        "science_arrays_read_or_hashed_by_binder": False,
        "future_counts": None,
        "future_hashes": None,
        "upstream": None,
        "typed": None,
        "xmf": None,
        "bed_audit": None,
        "acceptance": "not granted",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", choices=("A080", "A120"), required=True)
    parser.add_argument("--gencase-receipt", type=Path)
    parser.add_argument("--prepared-report", type=Path)
    parser.add_argument("--initial-qa-report", type=Path)
    parser.add_argument("--short-receipt", type=Path)
    parser.add_argument("--typed-report", type=Path)
    parser.add_argument("--typed-receipt", type=Path)
    parser.add_argument("--xmf-manifest", type=Path)
    parser.add_argument("--xmf-receipt", type=Path)
    parser.add_argument("--bed-report", type=Path)
    parser.add_argument("--output-summary", type=Path, required=True)
    args = parser.parse_args()
    upstream_args = (args.gencase_receipt, args.prepared_report,
                     args.initial_qa_report, args.short_receipt)
    require((args.gencase_receipt is None) == (args.prepared_report is None),
            "bind GenCase receipt and prepared-input-report together")
    require(args.initial_qa_report is None or args.gencase_receipt is not None,
            "initial QA metadata requires actual GenCase metadata")
    require(args.short_receipt is None or args.initial_qa_report is not None,
            "short-native receipt requires actual initial-QA metadata")
    upstream = None
    if any(value is not None for value in upstream_args):
        require(args.gencase_receipt is not None and args.prepared_report is not None,
                "partial upstream binding is not allowed")
        gencase_receipt = load_json(args.gencase_receipt)
        prepared_report = load_json(args.prepared_report)
        upstream = {
            "gencase": gencase_metadata(gencase_receipt, prepared_report, args.candidate),
        }
        if args.initial_qa_report is not None:
            upstream["initial_qa"] = report_metadata(load_json(args.initial_qa_report),
                                                      "initial QA report")
        if args.short_receipt is not None:
            short_receipt = load_json(args.short_receipt)
            completed(short_receipt, "short-native receipt")
            upstream["short_native"] = {
                "receipt_identity": receipt_identity(short_receipt),
                "frames": short_receipt.get("frames"),
                "dimension": short_receipt.get("solver_dimension"),
            }
    supplied = (args.typed_report, args.typed_receipt, args.xmf_manifest,
                args.xmf_receipt, args.bed_report)
    if not any(supplied):
        result = make_null_plan(args.candidate)
        result["upstream"] = upstream
    else:
        require(all(supplied), "bind all typed/XMF/bed JSON metadata together or bind none")
        typed_report = load_json(args.typed_report)
        typed_receipt = load_json(args.typed_receipt)
        xmf_manifest = load_json(args.xmf_manifest)
        xmf_receipt = load_json(args.xmf_receipt)
        bed_report = load_json(args.bed_report)
        completed(typed_receipt, "typed receipt")
        completed(xmf_receipt, "XMF receipt")
        typed_id = receipt_identity(typed_receipt)
        xmf_id = receipt_identity(xmf_receipt)
        require(typed_id["case_id"] and xmf_id["case_id"] == typed_id["case_id"],
                "typed/XMF receipt case identity mismatch")
        typed = typed_metadata(typed_report, args.candidate)
        xmf = xmf_metadata(xmf_manifest, typed, args.candidate)
        bed = bed_metadata(bed_report, args.candidate)
        result = {
            "schema": "ds02.f5.c082s1.fresh103.future-binding-plan.v1",
            "status": "root_review_required",
            "source_only": True,
            "candidate_id": args.candidate,
            "science_arrays_read_or_hashed_by_binder": False,
            "producer_receipt_identities": {"typed": typed_id, "xmf": xmf_id},
            "upstream": upstream,
            "future_counts": {"typed_particles": typed["particles"]},
            "future_hashes": {
                "typed_h5_sha256": typed["producer_h5_sha256"],
                "xmf_source_h5_sha256": xmf["source_h5_sha256"],
                "bed_report_sha256": None,
            },
            "typed": typed,
            "xmf": xmf,
            "bed_audit": bed,
            "acceptance": "not granted; this metadata binder does not enable requests or certify penetration",
        }
    args.output_summary.parent.mkdir(parents=True, exist_ok=True)
    args.output_summary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
