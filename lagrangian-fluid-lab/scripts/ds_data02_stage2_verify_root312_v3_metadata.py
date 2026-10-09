#!/usr/bin/env python3
"""Verify ROOT312 V3's actual full-proof/subset metadata contract.

This is a metadata-only consumer for the actual ROOT296/ROOT297 lifecycle
proof shape.  It requires both producer proofs to remain complete 8/8 and
checks that only the exact 3+4 subset is assigned to the native consumer.
Summary, case-manifest, and receipt edges must be small static refs;
``records_stat_only`` remains a deferred JSONL contract.  The checker never
opens deferred records or native payloads and never treats the excluded proof
rows as extracted cases.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import ds_data02_stage2_build_root312_f4_native_extract_v2 as v2


SCRIPT = Path(__file__).resolve()
MAX_OUTPUT = 8 * 1024 * 1024


class Root312MetadataError(ValueError):
    pass


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture_ref(path: Path) -> dict[str, Any]:
    st = path.stat()
    return {"path": str(path), "bytes": st.st_size, "mtime_ns": st.st_mtime_ns, "ctime_ns": st.st_ctime_ns, "st_dev": st.st_dev, "st_ino": st.st_ino, "sha256": _sha(path)}


def inspect(proof296: Path, proof297: Path, selection: Path) -> dict[str, Any]:
    loaded = {v2.ROOT296: v2._load_full_proof(proof296, v2.ROOT296), v2.ROOT297: v2._load_full_proof(proof297, v2.ROOT297)}
    selected_by_bundle = v2._load_selection(selection)
    selected = v2._validate_selection_against_bundles(selected_by_bundle, loaded)
    if len(selected_by_bundle[v2.ROOT296]) != 3 or len(selected_by_bundle[v2.ROOT297]) != 4:
        raise Root312MetadataError("ROOT312 selection is not 3+4")
    consumer_rows: list[dict[str, Any]] = []
    excluded_rows: list[dict[str, Any]] = []
    for bundle_id, bundle in loaded.items():
        chosen = set(selected_by_bundle[bundle_id])
        for case_id, edges in bundle["row_edges"].items():
            raw_row = bundle["rows"][case_id]
            # The loader normalizes the producer records_stat_only row into
            # a deferred parent-guard edge. The producer proof keeps its
            # original stat-only shape, so inspect the normalized edge
            # instead of requiring producer output to claim consumer policy.
            raw_records = edges.get("records_stat_only")
            if not isinstance(raw_records, dict) or raw_records.get("deferred") is not True or raw_records.get("content_opened_by_preparer") is not False or raw_records.get("read_after_parent_reservation") is not True:
                raise Root312MetadataError(f"{bundle_id}/{case_id} producer records declaration is not deferred-only")
            summary = edges.get("summary")
            records = edges.get("records_stat_only")
            case_manifest = edges.get("case_manifest")
            receipt = edges.get("receipt")
            if not all(isinstance(item, dict) for item in (summary, records, case_manifest, receipt)):
                raise Root312MetadataError(f"{bundle_id}/{case_id} lacks all guard edges")
            if not summary.get("content_opened") or not case_manifest.get("content_opened") or not receipt.get("content_opened"):
                raise Root312MetadataError(f"{bundle_id}/{case_id} static guard edge is not content-bound")
            if records.get("deferred") is not True or records.get("content_opened_by_preparer") is not False or records.get("read_after_parent_reservation") is not True:
                raise Root312MetadataError(f"{bundle_id}/{case_id} records edge is not deferred-only")
            entry = {"bundle_id": bundle_id, "physical_case_id": case_id, "status": "SELECTED_ORIGINAL118_NATIVE_CONSUMER" if case_id in chosen else "EXCLUDED_DIAGNOSTIC_ONLY", "summary": summary, "records_stat_only": records, "case_manifest": case_manifest, "receipt": receipt, "source_role": "ROOT312_V2_NATIVE_EXTRACT" if case_id in chosen else "ROOT312_V2_PRODUCER_ONLY"}
            (consumer_rows if case_id in chosen else excluded_rows).append(entry)
            if case_id in chosen and raw_row.get("status") != "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY":
                raise Root312MetadataError(f"{bundle_id}/{case_id} selected row status differs")
    if len(consumer_rows) != 7 or len(excluded_rows) != 9:
        raise Root312MetadataError("ROOT312 full/selected row partition is not 7 selected + 9 excluded")
    output = {
        "schema": "ds02.stage2.root312-f4-metadata-verification.v1",
        "status": "PASS_METADATA_GUARD_COMPATIBLE",
        "producer_proofs": {bundle_id: {"full_case_count": len(bundle["rows"]), "counts": bundle["proof_value"]["counts"], "proof": bundle["proof"], "selected_case_count": len(selected_by_bundle[bundle_id]), "excluded_diagnostic_case_count": len(set(bundle["rows"]) - set(selected_by_bundle[bundle_id]))} for bundle_id, bundle in loaded.items()},
        "selected_original118_case_count": len(consumer_rows),
        "excluded_diagnostic_case_count": len(excluded_rows),
        "consumer_rows": consumer_rows,
        "excluded_rows": excluded_rows,
        "read_policy": {"proof_summary_manifest_receipt_opened": True, "records_stat_only_content_opened": False, "native_payload_opened": False, "solver_started": False},
        "claim_boundary": {"full_producer_proofs": "PRESERVED_8_OF_8_EACH", "selected_subset": "EXACT_3_PLUS_4_ONLY", "excluded_rows": "NO_CONSUMER_CREDIT", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    return output


def _write(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, str):
        path.write_text(value, encoding="utf-8")
    else:
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _fixture_proof(tmp: Path, bundle_id: str, start: int) -> Path:
    rows = []
    for offset in range(8):
        case_id = f"{bundle_id}_CASE_{start + offset}"
        summary = _write(tmp / "summary" / f"{case_id}.json", {"physical_case_id": case_id, "status": "COMPLETED"})
        records = _write(tmp / "records" / f"{case_id}.jsonl", "deferred\n")
        case_manifest = _write(tmp / "case" / f"{case_id}.json", {"physical_case_id": case_id})
        receipt = _write(tmp / "receipt" / f"{case_id}.json", {"status": "COMPLETED", "returncode": 0})
        records_ref = {**_fixture_ref(records), "rows": 2, "deferred": True, "content_opened_by_preparer": False, "read_after_parent_reservation": True}
        rows.append({"physical_case_id": case_id, "family_id": "F4", "status": "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY", "summary": str(summary), "summary_sha256": _sha(summary), "records_stat_only": records_ref, "case_manifest": str(case_manifest), "case_manifest_sha256": _sha(case_manifest), "receipt": str(receipt), "receipt_sha256": _sha(receipt), "source_H5_prepost_known_SHA_and_current_stat_equal": True, "native_cause_fate_legal_flux_dynamics": "UNKNOWN"})
    batch = _write(tmp / "batch" / f"{bundle_id}.json", {"cases_requested": 8, "completed": 8, "failed": 0})
    proof = {"schema": v2.PROOF_SCHEMA, "status": "VERIFIED_ACTUAL_F4_TYPED_LIFECYCLE_BATCH_NO_PHYSICAL_CREDIT", "counts": {"cases_requested": 8, "completed": 8, "failed": 0}, "batch_summary": str(batch), "batch_summary_sha256": _sha(batch), "report": str(batch), "report_sha256": _sha(batch), "case_verifications": rows}
    return _write(tmp / "proof" / f"{bundle_id}.json", proof)


def _fixture_selection(tmp: Path) -> Path:
    return _write(tmp / "selection.json", {"schema": v2.SELECTION_SCHEMA, "bundles": [{"bundle_id": v2.ROOT296, "selected_case_ids": [f"ROOT296_CASE_{i}" for i in range(3)]}, {"bundle_id": v2.ROOT297, "selected_case_ids": [f"ROOT297_CASE_{100 + i}" for i in range(4)]}]})


def _self_test() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        p296 = _fixture_proof(tmp, v2.ROOT296, 0)
        p297 = _fixture_proof(tmp, v2.ROOT297, 100)
        selection = _fixture_selection(tmp)
        result = inspect(p296, p297, selection)
        if result["selected_original118_case_count"] != 7 or result["excluded_diagnostic_case_count"] != 9:
            raise Root312MetadataError("fixture did not preserve 8/8 plus 3+4 partition")
        return {"schema": result["schema"], "status": "PASS", "selected_original118_case_count": 7, "excluded_diagnostic_case_count": 9, "payload_opened": False, "checks": ["counts cases_requested=8/completed=8/failed=0", "summary/records_stat_only/case_manifest/receipt guard edges", "exact 3+4 subset", "excluded diagnostic rows receive no consumer credit"]}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    inspect_parser = sub.add_parser("inspect")
    inspect_parser.add_argument("--proof296", type=Path, required=True)
    inspect_parser.add_argument("--proof297", type=Path, required=True)
    inspect_parser.add_argument("--selection", type=Path, required=True)
    inspect_parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.action == "self-test":
            value = _self_test()
        else:
            value = inspect(args.proof296.expanduser().resolve(), args.proof297.expanduser().resolve(), args.selection.expanduser().resolve())
            output = args.output.expanduser().resolve()
            if output.exists():
                raise Root312MetadataError(f"refusing to overwrite output: {output}")
            output.parent.mkdir(parents=True, exist_ok=True)
            encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            if len(encoded.encode("utf-8")) > MAX_OUTPUT:
                raise Root312MetadataError("metadata output exceeds bound")
            output.write_text(encoded, encoding="utf-8")
            value = {"status": value["status"], "output": str(output), "selected_original118_case_count": value["selected_original118_case_count"], "excluded_diagnostic_case_count": value["excluded_diagnostic_case_count"], "payload_opened": False}
    except (Root312MetadataError, v2.Root312V2Error, v2.BASE.GenericExtractError, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"ROOT312_METADATA_VERIFY_ERROR: {exc}")
        return 2
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
