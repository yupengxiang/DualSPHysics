#!/usr/bin/env python3
"""Derive a runtime-compatible GenCase semantic receipt from metadata.

The Root353/354 raw execution receipt is immutable and intentionally lacks the
three fields consumed by the qualification runtime.  This worker joins that
receipt with the Root-owned prepared-input report and fresh102 sidecar, then
writes a separate receipt containing the actual producer-recorded 3-D/count
evidence.  It never patches the raw receipt and never opens or hashes BI4,
DAT, CSV, H5, VTK or solver output.  XML/JSON/Python inputs are metadata.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping
import xml.etree.ElementTree as ET


SCHEMA = "ds02.f2.stage1.fresh105.gencase-semantic-receipt.v1"
STATIC_SUFFIXES = {".json", ".xml", ".py", ".md", ".txt"}
RAW_SUFFIXES = {".dat", ".bi4", ".ibi4", ".h5", ".hdf5", ".csv", ".vtk", ".vtu", ".vtp", ".xmf", ".png", ".gif"}
COUNT_KEYS = ("fixed", "moving", "floating", "fluid")


class SemanticEvidenceError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SemanticEvidenceError(message)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def sha_static(path: Path) -> str:
    path = Path(path).resolve()
    require(path.suffix.lower() in STATIC_SUFFIXES and path.suffix.lower() not in RAW_SUFFIXES, f"scientific/non-static path refused: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def xml_dimension(path: Path) -> tuple[int, str]:
    """Read only the generated XML constants needed for the 3-D claim."""
    root = ET.parse(path).getroot()
    node = root.find(".//execution/constants/data2d")
    if node is None:
        node = root.find(".//constants/data2d")
    value = str(node.get("value", "")).lower() if node is not None else ""
    require(value == "false", f"generated XML is not explicitly 3-D: {path}")
    return 3, sha_static(path)


def producer_counts(report: Mapping[str, Any]) -> tuple[dict[str, int], int]:
    counts = report.get("generated_xml_particle_counts")
    total = report.get("actual_total_particles")
    require(isinstance(counts, dict), "prepared report lacks generated XML particle counts")
    parsed: dict[str, int] = {}
    for key in COUNT_KEYS:
        value = counts.get(key)
        require(isinstance(value, int) and value >= 0, f"prepared count is not a non-negative integer: {key}")
        parsed[key] = value
    require(isinstance(total, int) and total > 0, "prepared report lacks positive actual total")
    require(sum(parsed.values()) == total, "prepared XML count closure failed")
    require(parsed["fluid"] > 0, "prepared report lacks positive fluid count")
    return parsed, total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--gencase-receipt", required=True, type=Path)
    parser.add_argument("--prepared-input-report", required=True, type=Path)
    parser.add_argument("--runtime-evidence", required=True, type=Path)
    parser.add_argument("--generated-xml", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    raw = load_json(args.gencase_receipt)
    report = load_json(args.prepared_input_report)
    side = load_json(args.runtime_evidence)
    require(raw.get("status") == "completed" and raw.get("returncode") == 0, "raw GenCase execution receipt is not completed/0")
    require(side.get("source_only") is True and side.get("execution_allowed") is False, "fresh102 sidecar provenance changed")
    require(side.get("contract_checks", {}).get("root353_solver_dimension_three") is True, "fresh102 3-D producer evidence missing")
    require(side.get("raw_gencase_receipt", {}).get("raw_receipt_immutable") is True, "raw receipt immutability evidence missing")
    require(report.get("case_id") == args.case_id, "prepared report case identity mismatch")
    counts, total = producer_counts(report)
    dimension, xml_sha = xml_dimension(args.generated_xml)
    # The only payload digest carried here is the producer-recorded BI4 digest;
    # this worker deliberately does not recompute it.
    bi4_digest = report.get("bi4_sha256")
    require(isinstance(bi4_digest, str) and len(bi4_digest) == 64, "prepared report lacks producer-recorded BI4 digest")
    output = {
        "schema": SCHEMA,
        "case_id": args.case_id,
        "status": "completed",
        "returncode": 0,
        "solver_dimension_from_gencase": dimension,
        "total_particles": total,
        "fluid_particles": counts["fluid"],
        "fixed_particles": counts["fixed"],
        "moving_particles": counts["moving"],
        "floating_particles": counts["floating"],
        "provenance": {
            "semantic_derivation": "Root353/354 raw receipt + prepared-input-report + fresh102 runtime evidence sidecar",
            "raw_receipt_immutable": True,
            "raw_receipt_rewritten": False,
            "raw_receipt": {"path": str(args.gencase_receipt.resolve()), "sha256": sha_static(args.gencase_receipt), "status": raw.get("status"), "returncode": raw.get("returncode")},
            "prepared_input_report": {"path": str(args.prepared_input_report.resolve()), "sha256": sha_static(args.prepared_input_report)},
            "runtime_evidence_sidecar": {"path": str(args.runtime_evidence.resolve()), "sha256": sha_static(args.runtime_evidence)},
            "generated_xml": {"path": str(args.generated_xml.resolve()), "sha256": xml_sha, "data2d": "false"},
            "producer_recorded_bi4_sha256": bi4_digest,
            "bi4_read_or_rehashed_here": False,
        },
        "field_provenance": {
            "solver_dimension_from_gencase": "prepared report actual_generated_constants.data2d + generated XML data2d=false; corroborated by fresh102 root353_solver_dimension_three",
            "total_particles": "prepared_input_report.actual_total_particles",
            "partition_counts": "prepared_input_report.generated_xml_particle_counts",
            "fluid_particles": "prepared_input_report.generated_xml_particle_counts.fluid",
        },
        "runtime_qualification_compatibility": {
            "fields_supplied_in_this_separate_receipt": ["status", "returncode", "solver_dimension_from_gencase", "total_particles", "fluid_particles"],
            "raw_receipt_fields_not_filled": True,
            "requires_root_review_before_native_enable": True,
        },
        "scientific_payloads_read_or_hashed_here": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
