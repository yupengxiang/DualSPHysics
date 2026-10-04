"""DS-DATA-02 F2 Single-Case Exact True-Halfstep XML Transformer.

Audits and transforms the authoritative F2 RV4EQ DP005 OFFSET baseline execution parameters
for genuine independent adaptive time-step control:
- Halves execution CFL (0.2 -> 0.1)
- Halves coupled floor CoefDtMin (0.05 -> 0.025)
- Preserves DtFixed=0, DtIni=0, DtMin=0 (pure adaptive time stepping, retaining old clamps negative)
- Verifies exact whole-XML reversibility and ElementTree roundtrip undo
- Preserves all geometry, particles, motion bindings, and case definitions unchanged
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any
import xml.etree.ElementTree as E

# Authoritative native source paths and fingerprints
F2_OFFSET_FINE_XML_PATH = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_DP005_NATIVE_INPUTS_20261002/F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001/F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001.xml"
)
F2_OFFSET_FINE_XML_SHA256 = "f57c5e5fcf6c7c374ae14a8b28ae40b9e080554e2dfae8824253ae32e42b49cd"

F2_OFFSET_FINE_BI4_PATH = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_DP005_NATIVE_INPUTS_20261002/F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001/F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001.bi4"
)
F2_OFFSET_FINE_BI4_SHA256 = "efa7d2a296ed3de308c93b598e47225b36865006977caaa6a9a8898099b922a6"
F2_OFFSET_FINE_BI4_BYTES = 73360382

F2_OFFSET_FINE_MOTION_PATH = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_DP005_NATIVE_INPUTS_20261002/F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001/F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001_motion.dat"
)
F2_OFFSET_FINE_MOTION_SHA256 = "ff966330e01e565987ebf182a7dfd7401d76577ae1c266894fc7db4aa34c5b70"
F2_OFFSET_FINE_MOTION_BYTES = 18799

# Receipts pinning provenance across integration family folders
F2_OFFSET_GENCASE_RECEIPT_PATH = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_DP005_OFFSET_V1/gencase-f2_rv4eq_dp005_offset_v1-20261002-001/execution-receipt.json"
)
F2_OFFSET_GENCASE_RECEIPT_SHA256 = "f973b151cadea0d97b1f6c0726dec27490764fb91d9855e95fd8483eb9513ac7"

F2_OFFSET_SOLVER_RECEIPT_PATH = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001/qualification-f2_rv4eq_dp005_offset_v1-baseline-save001-native-fullstate-v1/execution-receipt.json"
)
F2_OFFSET_SOLVER_RECEIPT_SHA256 = "ad826271229884cc0ecc7245d6fc4f97a888d799fa3596d806ba3e4587b5c9a7"

F2_OFFSET_POSE_013_RECEIPT_PATH = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001/root-offset-fine-actual-native-pose-v1-013/execution-receipt.json"
)
F2_OFFSET_POSE_013_RECEIPT_SHA256 = "9b16197cb574f50e1ece72e08601769c4eab74506ed4f11f2dc0b95e37c3cd46"

F2_OFFSET_REPORT_024_RECEIPT_PATH = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001/root-offset-fine-full401-frozen-events-native-weights-024/execution-receipt.json"
)
F2_OFFSET_REPORT_024_RECEIPT_SHA256 = "e3f3a39c741b02d74a81a4d3b9832474a171f1a4980cf9b5b14ffa20c6a48710"

F2_OFFSET_DENSE_018_RECEIPT_PATH = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001/root-offset-fine-effective-dense-save001-full4-native-018/execution-receipt.json"
)
F2_OFFSET_DENSE_018_RECEIPT_SHA256 = "b4fd368774eb0ed908bfe3f484af4a4e956ec1c45f5c6f7def223cd0caddd511"

F2_OFFSET_POSE_022_RECEIPT_PATH = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001/root-offset-fine-full4001-actual-pose-13-bitwise-payload-singlecopy-022/execution-receipt.json"
)
F2_OFFSET_POSE_022_RECEIPT_SHA256 = "c82580ded03bb6a01fbc8d6a377ca82198a485b0d36bdf65143c98a6bae1334e"

F2_OFFSET_REPORT_025_RECEIPT_PATH = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001/root-offset-fine-full4001-frozen-events-native-weights-025/execution-receipt.json"
)
F2_OFFSET_REPORT_025_RECEIPT_SHA256 = "ea85d05c84f34bcb50e0c4c14e84a43f593bd00cdd74c6a74c7c1b1191c791be"

F2_OFFSET_SAVE_COMPARISON_027_PATH = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_DP005_OFFSET_V1_ACTUAL_NATIVE_SAVE_COMPARISON/root-offset-fine-full401-vs4001-native-per-uid-residence-save-comparison-027/save-comparison.json"
)
F2_OFFSET_SAVE_COMPARISON_027_SHA256 = "2f1a19acfd9d02fc8b45c5144937335c10a33c00a9fb352786345977995eebe8"

# Tokens for transformation and undo verification
CASEDEF_CFL_TOKEN = '<cflnumber value="0.2" />'
CASEDEF_MOTION_FILE_TOKEN = '<file name="F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001_motion.dat" />'

EXECUTION_COEFDTMIN_ORIGINAL = '<parameter key="CoefDtMin" value="0.05" />'
EXECUTION_COEFDTMIN_MUTATED = '<parameter key="CoefDtMin" value="0.025" />'

EXECUTION_CFL_ORIGINAL = '<cflnumber value="0.2" />'
EXECUTION_CFL_MUTATED = '<cflnumber value="0.1" />'

# Clamps ensuring no fixedDt floor or artificial clamps
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
    1. Historical <casedef> cflnumber (0.2) and motion binding are preserved verbatim.
    2. Only execution/parameters/CoefDtMin (0.05 -> 0.025) and execution/constants/cflnumber (0.2 -> 0.1) are altered.
    3. DtIni, DtMin, DtFixed remain 0 (pure adaptive timestep, no unintended fixedDt floor).
    4. Whole-XML reverse byte roundtrip is verified in-memory.
    5. ElementTree structural roundtrip is verified in-memory.
    """
    orig_sha256 = compute_bytes_sha256(xml_bytes)
    xml_text = xml_bytes.decode("utf-8")

    if "<execution>" not in xml_text or "</execution>" not in xml_text:
        raise ValueError("Malformed XML: missing <execution> block")

    parts = xml_text.split("<execution>", 1)
    casedef_block = parts[0]
    execution_block = parts[1]

    # Verify casedef contains historical cfl and motion file reference
    if CASEDEF_CFL_TOKEN not in casedef_block:
        raise ValueError(f"casedef block missing expected historical token: {CASEDEF_CFL_TOKEN}")
    if CASEDEF_MOTION_FILE_TOKEN not in casedef_block:
        raise ValueError(f"casedef block missing expected motion file token: {CASEDEF_MOTION_FILE_TOKEN}")

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

    # Reversibility verification at byte level
    reverted_execution = mutated_execution.replace(
        EXECUTION_COEFDTMIN_MUTATED, EXECUTION_COEFDTMIN_ORIGINAL, 1
    )
    reverted_execution = reverted_execution.replace(
        EXECUTION_CFL_MUTATED, EXECUTION_CFL_ORIGINAL, 1
    )
    reverted_text = casedef_block + "<execution>" + reverted_execution
    reverted_bytes = reverted_text.encode("utf-8")

    if reverted_bytes != xml_bytes:
        raise AssertionError("Byte reversibility verification FAILED: reverted bytes do not match original!")

    if compute_bytes_sha256(reverted_bytes) != orig_sha256:
        raise AssertionError("Byte reversibility verification FAILED: reverted SHA256 does not match original!")

    # Verify casedef historical cfl and motion binding unchanged in mutated output
    mut_casedef_part = mutated_text.split("<execution>", 1)[0]
    if CASEDEF_CFL_TOKEN not in mut_casedef_part:
        raise AssertionError("casedef historical CFL was corrupted during mutation!")
    if CASEDEF_MOTION_FILE_TOKEN not in mut_casedef_part:
        raise AssertionError("casedef motion file binding was corrupted during mutation!")

    # ElementTree structural roundtrip proof (Root run.py contract)
    before = E.fromstring(xml_bytes)
    after = E.fromstring(mutated_bytes)
    restored = E.fromstring(mutated_bytes)

    cfl_node = after.find("./execution/constants/cflnumber")
    params = {x.get("key"): x for x in after.findall("./execution/parameters/parameter")}

    if float(cfl_node.get("value")) != 0.1:
        raise ValueError(f"Mutated execution CFL is {cfl_node.get('value')}, expected 0.1")
    if float(params["CoefDtMin"].get("value")) != 0.025:
        raise ValueError(f"Mutated execution CoefDtMin is {params['CoefDtMin'].get('value')}, expected 0.025")
    for k in ["DtFixed", "DtIni", "DtMin"]:
        if float(params[k].get("value")) != 0:
            raise ValueError(f"Execution parameter {k} is non-zero: {params[k].get('value')}")

    restored.find("./execution/constants/cflnumber").set(
        "value", before.find("./execution/constants/cflnumber").get("value")
    )
    rp = {x.get("key"): x for x in restored.findall("./execution/parameters/parameter")}
    bp = {x.get("key"): x for x in before.findall("./execution/parameters/parameter")}
    rp["CoefDtMin"].set("value", bp["CoefDtMin"].get("value"))

    if E.tostring(restored) != E.tostring(before):
        raise AssertionError("ElementTree structural roundtrip FAILED: restored tree does not match before tree!")

    meta = {
        "original_sha256": orig_sha256,
        "mutated_sha256": mutated_sha256,
        "original_byte_count": len(xml_bytes),
        "mutated_byte_count": len(mutated_bytes),
        "byte_delta": len(mutated_bytes) - len(xml_bytes),
        "reversibility_verified": True,
        "elementtree_undo_verified": True,
        "casedef_historical_cfl_preserved": "0.2",
        "casedef_motion_binding_preserved": "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001_motion.dat",
        "execution_cfl_mutated": "0.1",
        "execution_coefdtmin_mutated": "0.025",
        "dt_fixed_floor_safe": {
            "DtFixed": "0",
            "DtIni": "0",
            "DtMin": "0",
            "unintended_fixed_dt_floor": False,
        },
        "time_max_s": 4.0,
        "time_out_s": 0.01,
        "expected_frames": 401,
    }
    return mutated_bytes, meta


def audit_sources() -> dict[str, Any]:
    """Audit primary Root native sources and receipts, verifying SHA256 integrity."""
    files = {
        "source_xml": {
            "path": str(F2_OFFSET_FINE_XML_PATH),
            "expected_sha256": F2_OFFSET_FINE_XML_SHA256,
            "actual_sha256": compute_sha256(F2_OFFSET_FINE_XML_PATH) if F2_OFFSET_FINE_XML_PATH.is_file() else None,
            "exists": F2_OFFSET_FINE_XML_PATH.is_file(),
        },
        "source_bi4": {
            "path": str(F2_OFFSET_FINE_BI4_PATH),
            "expected_sha256": F2_OFFSET_FINE_BI4_SHA256,
            "actual_sha256": compute_sha256(F2_OFFSET_FINE_BI4_PATH) if F2_OFFSET_FINE_BI4_PATH.is_file() else None,
            "bytes": F2_OFFSET_FINE_BI4_PATH.stat().st_size if F2_OFFSET_FINE_BI4_PATH.is_file() else None,
            "expected_bytes": F2_OFFSET_FINE_BI4_BYTES,
            "exists": F2_OFFSET_FINE_BI4_PATH.is_file(),
        },
        "source_motion": {
            "path": str(F2_OFFSET_FINE_MOTION_PATH),
            "expected_sha256": F2_OFFSET_FINE_MOTION_SHA256,
            "actual_sha256": compute_sha256(F2_OFFSET_FINE_MOTION_PATH) if F2_OFFSET_FINE_MOTION_PATH.is_file() else None,
            "bytes": F2_OFFSET_FINE_MOTION_PATH.stat().st_size if F2_OFFSET_FINE_MOTION_PATH.is_file() else None,
            "expected_bytes": F2_OFFSET_FINE_MOTION_BYTES,
            "exists": F2_OFFSET_FINE_MOTION_PATH.is_file(),
        },
        "source_gencase_receipt": {
            "path": str(F2_OFFSET_GENCASE_RECEIPT_PATH),
            "expected_sha256": F2_OFFSET_GENCASE_RECEIPT_SHA256,
            "actual_sha256": compute_sha256(F2_OFFSET_GENCASE_RECEIPT_PATH) if F2_OFFSET_GENCASE_RECEIPT_PATH.is_file() else None,
            "exists": F2_OFFSET_GENCASE_RECEIPT_PATH.is_file(),
        },
        "source_solver_receipt": {
            "path": str(F2_OFFSET_SOLVER_RECEIPT_PATH),
            "expected_sha256": F2_OFFSET_SOLVER_RECEIPT_SHA256,
            "actual_sha256": compute_sha256(F2_OFFSET_SOLVER_RECEIPT_PATH) if F2_OFFSET_SOLVER_RECEIPT_PATH.is_file() else None,
            "exists": F2_OFFSET_SOLVER_RECEIPT_PATH.is_file(),
        },
        "source_pose_013_receipt": {
            "path": str(F2_OFFSET_POSE_013_RECEIPT_PATH),
            "expected_sha256": F2_OFFSET_POSE_013_RECEIPT_SHA256,
            "actual_sha256": compute_sha256(F2_OFFSET_POSE_013_RECEIPT_PATH) if F2_OFFSET_POSE_013_RECEIPT_PATH.is_file() else None,
            "exists": F2_OFFSET_POSE_013_RECEIPT_PATH.is_file(),
        },
        "source_report_024_receipt": {
            "path": str(F2_OFFSET_REPORT_024_RECEIPT_PATH),
            "expected_sha256": F2_OFFSET_REPORT_024_RECEIPT_SHA256,
            "actual_sha256": compute_sha256(F2_OFFSET_REPORT_024_RECEIPT_PATH) if F2_OFFSET_REPORT_024_RECEIPT_PATH.is_file() else None,
            "exists": F2_OFFSET_REPORT_024_RECEIPT_PATH.is_file(),
        },
        "source_dense_018_receipt": {
            "path": str(F2_OFFSET_DENSE_018_RECEIPT_PATH),
            "expected_sha256": F2_OFFSET_DENSE_018_RECEIPT_SHA256,
            "actual_sha256": compute_sha256(F2_OFFSET_DENSE_018_RECEIPT_PATH) if F2_OFFSET_DENSE_018_RECEIPT_PATH.is_file() else None,
            "exists": F2_OFFSET_DENSE_018_RECEIPT_PATH.is_file(),
        },
        "source_pose_022_receipt": {
            "path": str(F2_OFFSET_POSE_022_RECEIPT_PATH),
            "expected_sha256": F2_OFFSET_POSE_022_RECEIPT_SHA256,
            "actual_sha256": compute_sha256(F2_OFFSET_POSE_022_RECEIPT_PATH) if F2_OFFSET_POSE_022_RECEIPT_PATH.is_file() else None,
            "exists": F2_OFFSET_POSE_022_RECEIPT_PATH.is_file(),
        },
        "source_report_025_receipt": {
            "path": str(F2_OFFSET_REPORT_025_RECEIPT_PATH),
            "expected_sha256": F2_OFFSET_REPORT_025_RECEIPT_SHA256,
            "actual_sha256": compute_sha256(F2_OFFSET_REPORT_025_RECEIPT_PATH) if F2_OFFSET_REPORT_025_RECEIPT_PATH.is_file() else None,
            "exists": F2_OFFSET_REPORT_025_RECEIPT_PATH.is_file(),
        },
        "source_save_comparison_027": {
            "path": str(F2_OFFSET_SAVE_COMPARISON_027_PATH),
            "expected_sha256": F2_OFFSET_SAVE_COMPARISON_027_SHA256,
            "actual_sha256": compute_sha256(F2_OFFSET_SAVE_COMPARISON_027_PATH) if F2_OFFSET_SAVE_COMPARISON_027_PATH.is_file() else None,
            "exists": F2_OFFSET_SAVE_COMPARISON_027_PATH.is_file(),
        },
    }

    all_verified = True
    for item in files.values():
        ok = item["exists"] and item["expected_sha256"] == item["actual_sha256"]
        item["verified"] = ok
        if not ok:
            all_verified = False

    return {
        "schema": "ds02.f2.offset-fine-temporal-control-source-audit.v1",
        "files": files,
        "all_sources_verified": all_verified,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="DS-DATA-02 F2 Single-Case Exact True-Halfstep Transformer")
    parser.add_argument("--audit", action="store_true", help="Audit source XML, BI4, motion, and receipts")
    parser.add_argument("--dry-run", action="store_true", help="Perform in-memory transformation and reverse proof")
    args = parser.parse_args()

    audit_result = audit_sources()
    if args.audit or not args.dry_run:
        print(json.dumps(audit_result, indent=2))
        if not audit_result["all_sources_verified"]:
            print("ERROR: Source verification failed!", file=sys.stderr)
            return 1

    if args.dry_run or not args.audit:
        print("\n--- F2 RV4EQ DP005 OFFSET True-Halfstep Execution Transformation ---")
        xml_bytes = F2_OFFSET_FINE_XML_PATH.read_bytes()
        mutated_bytes, meta = transform_execution_xml_bytes(xml_bytes)
        print(json.dumps(meta, indent=2))
        print(f"Original SHA256: {meta['original_sha256']}")
        print(f"Mutated SHA256:  {meta['mutated_sha256']}")
        print(f"Byte reversibility check: PASSED ({meta['reversibility_verified']})")
        print(f"ElementTree undo check:  PASSED ({meta['elementtree_undo_verified']})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
