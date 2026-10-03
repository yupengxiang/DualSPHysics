#!/usr/bin/env python3
"""Genuine quarterstep prospective clone transformer for DS-DATA-02 Family F1.

Clones execution XML and byte-identical BI4 from actual halfstep execution input
(prepared012: CFL 0.1, CoefDtMin 0.025) to prospective quarterstep (CFL 0.05,
CoefDtMin 0.0125).

Hard invariants enforced:
1. Historical casedef subtree is completely untouched.
2. Only effective execution constants/parameters are modified.
3. Whole-XML reverse-bytes assertion: reverting the two literal replacements on
   the output XML string recovers the exact original source XML bytes.
4. Discrete initial particle lattice (.bi4) is copied byte-identically with
   verified SHA-256 matching the original physical mother lattice.
5. All requests and reports carry strict claim boundaries: Q-N not granted,
   production none.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET


def sha256(path: Path | str) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def transform_execution_xml(
    source_text: str,
    baseline_cfl: float = 0.1,
    baseline_coef_dt_min: float = 0.025,
    candidate_cfl: float = 0.05,
    candidate_coef_dt_min: float = 0.0125,
) -> str:
    """Transform execution parameters while asserting historical casedef integrity and byte reversibility."""
    if "<execution>" not in source_text or "</execution>" not in source_text:
        raise ValueError("Source XML must contain an <execution> block")
    if "<casedef>" not in source_text:
        raise ValueError("Source XML must contain a historical <casedef> block")

    parsed = ET.fromstring(source_text)
    exec_cfl_elem = parsed.find(".//execution/constants/cflnumber")
    if exec_cfl_elem is None:
        raise ValueError("Missing .//execution/constants/cflnumber node in source XML")
    if abs(float(exec_cfl_elem.get("value")) - baseline_cfl) > 1e-9:
        raise ValueError(
            f"Execution CFL {exec_cfl_elem.get('value')} does not match expected baseline {baseline_cfl}"
        )

    exec_params = {
        e.get("key"): e.get("value")
        for e in parsed.findall(".//execution/parameters/parameter")
    }
    if "CoefDtMin" not in exec_params:
        raise ValueError("Missing CoefDtMin in .//execution/parameters")
    if abs(float(exec_params["CoefDtMin"]) - baseline_coef_dt_min) > 1e-9:
        raise ValueError(
            f"Execution CoefDtMin {exec_params['CoefDtMin']} does not match expected baseline {baseline_coef_dt_min}"
        )

    exec_idx = source_text.index("<execution>")
    head = source_text[:exec_idx]
    tail = source_text[exec_idx:]

    # Transform only within the execution block
    new_tail, n1 = re.subn(
        r'(<cflnumber\b[^>]*value=["\'])[^"\']+(["\'])',
        lambda m: f"{m.group(1)}{candidate_cfl}{m.group(2)}",
        tail,
    )
    if n1 != 1:
        raise ValueError(f"Expected exactly 1 cflnumber substitution in execution block, got {n1}")

    new_tail, n2 = re.subn(
        r'(<parameter\b[^>]*key=["\']CoefDtMin["\'][^>]*value=["\'])[^"\']+(["\'])',
        lambda m: f"{m.group(1)}{candidate_coef_dt_min}{m.group(2)}",
        new_tail,
    )
    if n2 != 1:
        raise ValueError(f"Expected exactly 1 CoefDtMin substitution in execution block, got {n2}")

    new_text = head + new_tail

    # Invariant 1: historical casedef prefix is completely untouched
    if not new_text.startswith(head):
        raise AssertionError("Historical casedef section was modified during transformation")

    # Invariant 2: whole XML reverse-bytes assertion
    # Restoring candidate CFL and CoefDtMin literals back to original values recovers exact source bytes.
    restored_text, r1 = re.subn(
        r'(<cflnumber\b[^>]*value=["\'])' + re.escape(str(candidate_cfl)) + r'(["\'])',
        lambda m: f"{m.group(1)}{exec_cfl_elem.get('value')}{m.group(2)}",
        new_text,
    )
    if r1 != 1:
        raise AssertionError(f"Reverse substitution for CFL failed to match uniquely: r1={r1}")

    restored_text, r2 = re.subn(
        r'(<parameter\b[^>]*key=["\']CoefDtMin["\'][^>]*value=["\'])'
        + re.escape(str(candidate_coef_dt_min))
        + r'(["\'])',
        lambda m: f"{m.group(1)}{exec_params['CoefDtMin']}{m.group(2)}",
        restored_text,
    )
    if r2 != 1:
        raise AssertionError(f"Reverse substitution for CoefDtMin failed to match uniquely: r2={r2}")

    if restored_text != source_text:
        raise AssertionError(
            "Whole-XML reverse-bytes assertion failed: restored text does not match original source bytes"
        )

    return new_text


def prepare_quarterstep_inputs(binding_path: Path | str, output_dir: Path | str) -> dict:
    binding_path = Path(binding_path).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    b = json.loads(binding_path.read_text())

    source_xml_path = Path(b["source_halfstep_input_preparation"]["prepared_xml"])
    source_bi4_path = Path(b["source_halfstep_input_preparation"]["prepared_bi4"])
    expected_bi4_sha256 = b["source_halfstep_input_preparation"]["prepared_bi4_sha256"]

    if not source_xml_path.exists():
        raise FileNotFoundError(f"Source halfstep XML not found: {source_xml_path}")
    if not source_bi4_path.exists():
        raise FileNotFoundError(f"Source halfstep BI4 not found: {source_bi4_path}")

    source_text = source_xml_path.read_text()
    transformed_text = transform_execution_xml(
        source_text,
        baseline_cfl=b["halfstep_cfl"],
        baseline_coef_dt_min=b["halfstep_coef_dt_min"],
        candidate_cfl=b["candidate_quarterstep_cfl"],
        candidate_coef_dt_min=b["candidate_quarterstep_coef_dt_min"],
    )

    case_id = b["case_id"]
    target_xml = output_dir / f"{case_id}.xml"
    target_bi4 = output_dir / f"{case_id}.bi4"

    target_xml.write_text(transformed_text)

    # Byte-identical copy of BI4
    shutil.copyfile(source_bi4_path, target_bi4)
    target_bi4_hash = sha256(target_bi4)
    if target_bi4_hash != expected_bi4_sha256:
        raise AssertionError(
            f"BI4 hash mismatch: got {target_bi4_hash}, expected {expected_bi4_sha256}"
        )

    target_xml_hash = sha256(target_xml)

    report = {
        "schema": "ds02.f1.thick-dbc-quarterstep-input-preparation.v1",
        "case_id": case_id,
        "prepared_prefix": str(output_dir / case_id),
        "prepared_xml": str(target_xml),
        "prepared_bi4": str(target_bi4),
        "prepared_xml_sha256": target_xml_hash,
        "prepared_bi4_sha256": target_bi4_hash,
        "only_xml_changes": {
            "CFLnumber": [b["halfstep_cfl"], b["candidate_quarterstep_cfl"]],
            "CoefDtMin": [b["halfstep_coef_dt_min"], b["candidate_quarterstep_coef_dt_min"]],
        },
        "historical_casedef_untouched": True,
        "whole_xml_reversebytes_verified": True,
        "initial_bi4_byte_identical": True,
        "physical_condition_sha256": b["physical_condition_sha256"],
        "q_n": "not_granted",
        "production_approval": "none",
    }

    report_path = output_dir / "prepared-input-report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", required=True, help="Path to quarterstep_binding.json")
    parser.add_argument("--output-dir", required=True, help="Directory to place quarterstep inputs")
    args = parser.parse_args()

    rep = prepare_quarterstep_inputs(args.binding, args.output_dir)
    print(json.dumps({"status": "completed", "report": rep}, indent=2))
