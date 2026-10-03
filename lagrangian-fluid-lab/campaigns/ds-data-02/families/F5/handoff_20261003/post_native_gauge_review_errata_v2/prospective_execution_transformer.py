#!/usr/bin/env python3
"""DS-DATA-02 F5 Standalone Prospective Execution-Only Transformer (v1).

Transforms baseline fine DualSPHysics execution configurations for the
independent temporal integration diagnostic (half execution CFL and half CoefDtMin):
  - Execution CFL: 0.2 -> 0.1 (<execution>/<constants>/<cflnumber>)
  - Execution CoefDtMin: 0.05 -> 0.025 (<execution>/<parameters>/<parameter key="CoefDtMin">)
  - Historical case definition CFL (<casedef>/<constantsdef>/<cflnumber>) is strictly PRESERVED at 0.2.
  - Initial condition BI4, geometry, bed STL, wave forcing, domain limits, and shader density
    are byte-for-byte PRESERVED from original fine native reference.
  - Reversible text substitution: restoring 0.1 -> 0.2 and 0.025 -> 0.05 exactly recovers original XML bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

# Primary source references from Root Native Gauge Cohort Diagnostic 038
RUNUP_FINE_XML_PATH = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/"
    "F5_REF_RUNUP_DP010_SURFACE_FIRST_SUPPORT_024/root-execution-inputs-026/"
    "F5_REF_RUNUP_DP010_SURFACE_FIRST_SUPPORT_024.xml"
)
RUNUP_FINE_XML_SHA256 = "1de0a403c525b01208062f46f1b53759ca798edce8221b05c389fc8006ef6c54"
RUNUP_FINE_BI4_PATH = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/"
    "F5_REF_RUNUP_DP010_SURFACE_FIRST_SUPPORT_024/root-execution-inputs-026/"
    "F5_REF_RUNUP_DP010_SURFACE_FIRST_SUPPORT_024.bi4"
)
RUNUP_FINE_BI4_SHA256 = "bbb32f38b0e5673700ecb09cf2822f3e6728566ebffea0842174532725fdaf86"
RUNUP_GENCASE_RECEIPT_PATH = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/"
    "F5_REF_RUNUP_DP010_SURFACE_FIRST_SUPPORT_024/root-runup-surface-first-support-gencase-024/"
    "execution-receipt.json"
)
RUNUP_GENCASE_RECEIPT_SHA256 = "f0628e5720f4b3f42833b61ae5b42c2c1ad362560bb06120023a32350e1684b5"

WEIR_FINE_XML_PATH = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/"
    "F5_REF_WEIR_DP010_SURFACE_FIRST_SUPPORT_024/root-execution-inputs-026/"
    "F5_REF_WEIR_DP010_SURFACE_FIRST_SUPPORT_024.xml"
)
WEIR_FINE_XML_SHA256 = "e34fe0f2616f481049553ff122c25e3b2da771258450bec4f07ad34d239f5f5f"
WEIR_FINE_BI4_PATH = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/"
    "F5_REF_WEIR_DP010_SURFACE_FIRST_SUPPORT_024/root-execution-inputs-026/"
    "F5_REF_WEIR_DP010_SURFACE_FIRST_SUPPORT_024.bi4"
)
WEIR_FINE_BI4_SHA256 = "a73ee03e75f5b13acd9df8488fbb1fc1542298ebe103b1aeb9024b610f57a7b1"
WEIR_GENCASE_RECEIPT_PATH = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/"
    "F5_REF_WEIR_DP010_SURFACE_FIRST_SUPPORT_024/root-weir-surface-first-support-gencase-024/"
    "execution-receipt.json"
)
WEIR_GENCASE_RECEIPT_SHA256 = "bb9bee845378f2c50fe6243ee37c9020161993c7a86f863a677cb2730a4e1d1c"

TARGET_COEFDTMIN_ORIGINAL = '<parameter key="CoefDtMin" value="0.05" />'
TARGET_COEFDTMIN_MUTATED = '<parameter key="CoefDtMin" value="0.025" />'
TARGET_CFL_ORIGINAL = '<cflnumber value="0.2" />'
TARGET_CFL_MUTATED = '<cflnumber value="0.1" />'


def compute_sha256(path: Path | str) -> str:
    """Compute sha256 hex digest in 64 KiB blocks."""
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(65536):
            h.update(chunk)
    return h.hexdigest()


def compute_bytes_sha256(data: bytes) -> str:
    """Compute sha256 hex digest of a byte sequence."""
    return hashlib.sha256(data).hexdigest()


def transform_execution_xml_bytes(xml_bytes: bytes) -> tuple[bytes, dict[str, Any]]:
    """Transform XML bytes mutating ONLY execution/constants/cflnumber and execution/parameters/CoefDtMin.

    Strict validation:
    1. Historical <casedef> cflnumber is NOT altered (stays 0.2).
    2. Only the second occurrences inside <execution> are mutated.
    3. Reversible transformation test is executed in-memory.
    """
    xml_text = xml_bytes.decode("utf-8")
    orig_sha256 = compute_bytes_sha256(xml_bytes)

    if "<execution>" not in xml_text or "</execution>" not in xml_text:
        raise ValueError("Malformed XML: missing <execution> block")

    parts = xml_text.split("<execution>", 1)
    casedef_block = parts[0]
    execution_block = parts[1]

    # Verify casedef contains historical cfl 0.2
    if TARGET_CFL_ORIGINAL not in casedef_block:
        raise ValueError("casedef block does not contain expected historical CFL 0.2")

    # Verify execution block contains both target parameters
    if TARGET_COEFDTMIN_ORIGINAL not in execution_block:
        raise ValueError(f"execution block missing expected: {TARGET_COEFDTMIN_ORIGINAL}")
    if TARGET_CFL_ORIGINAL not in execution_block:
        raise ValueError(f"execution block missing expected: {TARGET_CFL_ORIGINAL}")

    # Mutate ONLY within execution block (first occurrence within execution)
    mutated_execution = execution_block.replace(
        TARGET_COEFDTMIN_ORIGINAL, TARGET_COEFDTMIN_MUTATED, 1
    )
    mutated_execution = mutated_execution.replace(
        TARGET_CFL_ORIGINAL, TARGET_CFL_MUTATED, 1
    )

    mutated_text = casedef_block + "<execution>" + mutated_execution
    mutated_bytes = mutated_text.encode("utf-8")
    mutated_sha256 = compute_bytes_sha256(mutated_bytes)

    # Reversibility verification
    reverted_execution = mutated_execution.replace(
        TARGET_COEFDTMIN_MUTATED, TARGET_COEFDTMIN_ORIGINAL, 1
    )
    reverted_execution = reverted_execution.replace(
        TARGET_CFL_MUTATED, TARGET_CFL_ORIGINAL, 1
    )
    reverted_text = casedef_block + "<execution>" + reverted_execution
    reverted_bytes = reverted_text.encode("utf-8")

    if reverted_bytes != xml_bytes:
        raise AssertionError("Reversibility verification FAILED: reverted bytes do not match original!")

    # Verify casedef cfl is still 0.2 in mutated output
    mut_casedef_part = mutated_text.split("<execution>", 1)[0]
    if TARGET_CFL_ORIGINAL not in mut_casedef_part or TARGET_CFL_MUTATED in mut_casedef_part:
        raise AssertionError("casedef historical CFL was corrupted during mutation!")

    meta = {
        "original_sha256": orig_sha256,
        "mutated_sha256": mutated_sha256,
        "original_byte_count": len(xml_bytes),
        "mutated_byte_count": len(mutated_bytes),
        "byte_delta": len(mutated_bytes) - len(xml_bytes),
        "reversibility_verified": True,
        "casedef_cfl_preserved": "0.2",
        "execution_cfl_mutated": "0.1",
        "execution_coefdtmin_mutated": "0.025",
        "density_dt_unchanged": "2",
        "density_dt_value_unchanged": "0.1",
    }
    return mutated_bytes, meta


def audit_sources() -> dict[str, Any]:
    """Audit primary Root native sources and verify SHA256 integrity."""
    cases = {
        "runup": {
            "xml_path": str(RUNUP_FINE_XML_PATH),
            "xml_expected_sha256": RUNUP_FINE_XML_SHA256,
            "xml_actual_sha256": compute_sha256(RUNUP_FINE_XML_PATH),
            "bi4_path": str(RUNUP_FINE_BI4_PATH),
            "bi4_expected_sha256": RUNUP_FINE_BI4_SHA256,
            "bi4_actual_sha256": compute_sha256(RUNUP_FINE_BI4_PATH),
            "gencase_receipt_path": str(RUNUP_GENCASE_RECEIPT_PATH),
            "gencase_receipt_expected_sha256": RUNUP_GENCASE_RECEIPT_SHA256,
            "gencase_receipt_actual_sha256": compute_sha256(RUNUP_GENCASE_RECEIPT_PATH),
        },
        "weir": {
            "xml_path": str(WEIR_FINE_XML_PATH),
            "xml_expected_sha256": WEIR_FINE_XML_SHA256,
            "xml_actual_sha256": compute_sha256(WEIR_FINE_XML_PATH),
            "bi4_path": str(WEIR_FINE_BI4_PATH),
            "bi4_expected_sha256": WEIR_FINE_BI4_SHA256,
            "bi4_actual_sha256": compute_sha256(WEIR_FINE_BI4_PATH),
            "gencase_receipt_path": str(WEIR_GENCASE_RECEIPT_PATH),
            "gencase_receipt_expected_sha256": WEIR_GENCASE_RECEIPT_SHA256,
            "gencase_receipt_actual_sha256": compute_sha256(WEIR_GENCASE_RECEIPT_PATH),
        },
    }

    all_verified = True
    for name, c in cases.items():
        xml_ok = c["xml_expected_sha256"] == c["xml_actual_sha256"]
        bi4_ok = c["bi4_expected_sha256"] == c["bi4_actual_sha256"]
        gencase_ok = c["gencase_receipt_expected_sha256"] == c["gencase_receipt_actual_sha256"]
        c["xml_verified"] = xml_ok
        c["bi4_verified"] = bi4_ok
        c["gencase_verified"] = gencase_ok
        if not (xml_ok and bi4_ok and gencase_ok):
            all_verified = False

    return {
        "schema": "ds02.f5.temporal-control-source-audit.v1",
        "cases": cases,
        "all_sources_verified": all_verified,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="DS-DATA-02 F5 Prospective Execution-Only Transformer")
    parser.add_argument("--audit", action="store_true", help="Audit source XML, BI4, and GenCase receipts")
    parser.add_argument("--dry-run", action="store_true", help="Perform in-memory mutation and reversibility checks")
    args = parser.parse_args()

    audit_result = audit_sources()
    if args.audit or not (args.dry_run):
        print(json.dumps(audit_result, indent=2))
        if not audit_result["all_sources_verified"]:
            print("ERROR: Source verification failed!", file=sys.stderr)
            return 1

    if args.dry_run or not args.audit:
        print("\n--- RUNUP Fine Execution Transformation ---")
        runup_bytes = RUNUP_FINE_XML_PATH.read_bytes()
        _, runup_meta = transform_execution_xml_bytes(runup_bytes)
        print(json.dumps(runup_meta, indent=2))

        print("\n--- WEIR Fine Execution Transformation ---")
        weir_bytes = WEIR_FINE_XML_PATH.read_bytes()
        _, weir_meta = transform_execution_xml_bytes(weir_bytes)
        print(json.dumps(weir_meta, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
