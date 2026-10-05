#!/usr/bin/env python3
"""Audit an actual motion-safe prepared-input-report without scientific reads."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

REQUIRED = (
    "schema", "case_id", "prefix", "definition_sha256", "xml_sha256",
    "bi4_sha256", "generated_xml_particle_counts", "actual_total_particles",
    "assets", "native_initial_typed_QA", "mass_evidence", "q_n",
    "production_approval", "independent_case_count_increment",
)
COUNT_KEYS = ("fixed", "moving", "floating", "fluid")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"JSON object required: {path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--prepared-input-report", required=True)
    parser.add_argument("--gencase-receipt", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report_path = Path(args.prepared_input_report).resolve()
    receipt_path = Path(args.gencase_receipt).resolve()
    report = load(report_path)
    receipt = load(receipt_path)
    errors: list[str] = []
    missing = [key for key in REQUIRED if key not in report]
    if missing:
        errors.append(f"missing report fields: {missing}")
    if report.get("schema") != "ds02.root.actual-native-source-preflight.v1":
        errors.append("prepared report schema mismatch")
    if report.get("case_id") != args.case_id:
        errors.append("prepared report case_id mismatch")
    counts = report.get("generated_xml_particle_counts")
    values = []
    if not isinstance(counts, Mapping):
        errors.append("generated_xml_particle_counts must be an object")
    else:
        for key in COUNT_KEYS:
            value = counts.get(key)
            if not isinstance(value, int) or value < 0:
                errors.append(f"count {key} is not a nonnegative integer")
            else:
                values.append(value)
    total = report.get("actual_total_particles")
    if not isinstance(total, int) or total <= 0 or sum(values) != total:
        errors.append("actual_total_particles does not close against XML counts")
    for key in ("definition_sha256", "xml_sha256", "bi4_sha256"):
        if not isinstance(report.get(key), str) or len(report[key]) != 64:
            errors.append(f"{key} must be an actual producer digest")
    assets = report.get("assets")
    if not isinstance(assets, list) or not assets:
        errors.append("motion asset list is missing")
    else:
        for index, asset in enumerate(assets):
            if not isinstance(asset, Mapping):
                errors.append(f"asset {index} is not an object")
                continue
            for key in ("source", "sha256", "relative_name", "copied_to",
                        "verified_post_gencase_sha256"):
                if key not in asset:
                    errors.append(f"asset {index} missing {key}")
            for key in ("sha256", "verified_post_gencase_sha256"):
                if key in asset and (not isinstance(asset[key], str) or len(asset[key]) != 64):
                    errors.append(f"asset {index} {key} is not a digest")
    if report.get("native_initial_typed_QA") != "pending actual arrays":
        errors.append("GenCase report must not claim native initial QA")
    if report.get("q_n") != "not_granted" or report.get("production_approval") != "none":
        errors.append("prepared report contains an approval claim")
    if report.get("independent_case_count_increment") != 0:
        errors.append("GenCase report must not increment case count")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        errors.append("GenCase receipt is not completed/0")
    output = {
        "schema": "ds02.f2.stage1.fresh100.prepared-report-contract-audit.v1",
        "case_id": args.case_id,
        "status": "pass" if not errors else "fail",
        "source_only_worker": False,
        "scientific_array_read": False,
        "claim": "actual prepared-input-report and GenCase receipt contract only; native QA remains downstream",
        "prepared_input_report": {"path": str(report_path), "sha256": sha256(report_path)},
        "gencase_receipt": {"path": str(receipt_path), "sha256": sha256(receipt_path)},
        "observed_report_fields": sorted(report.keys()),
        "checks": {
            "required_report_fields": not missing,
            "schema_and_identity": report.get("schema") == "ds02.root.actual-native-source-preflight.v1" and report.get("case_id") == args.case_id,
            "counts_close": not any("count" in error or "total_particles" in error for error in errors),
            "producer_digests_present": all(isinstance(report.get(key), str) and len(report[key]) == 64 for key in ("xml_sha256", "bi4_sha256")),
            "motion_assets_digest_bound": isinstance(assets, list) and bool(assets),
            "receipt_completed_zero": receipt.get("status") == "completed" and receipt.get("returncode") == 0,
            "no_scientific_claim": report.get("native_initial_typed_QA") == "pending actual arrays" and report.get("q_n") == "not_granted",
        },
        "errors": errors,
    }
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
