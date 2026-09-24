"""Add pre-allocation BI4 resource bounds to the reviewed v1/v2 audit chain."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from scripts import f8_r008_bi4_format_static_audit_v2 as v2


LAB = v2.LAB
OUTPUT = (
    LAB
    / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/"
    "bi4-format-static-audit-v3/receipt.json"
)
SCHEMA = "core.cfd.f8.r008_bi4_format_static_audit.v3"

RESOURCE_LIMITS = {
    "raw_input_bytes_max": 64 * 1024 * 1024,
    "header_bytes_exact": 64,
    "si64_header_mode": "reject; R008 input is bounded far below the JBinaryData 32-bit size threshold",
    "byte_order": "little",
    "item_nodes_max_including_root": 2,
    "item_depth_max_including_root": 2,
    "arrays_total_max": 64,
    "values_per_item_max": 128,
    "name_bytes_max": 128,
    "metadata_string_bytes_max": 4096,
    "metadata_bytes_total_max": 2 * 1024 * 1024,
    "array_count_max": 10752,
    "fixed_type_element_bytes_max": 24,
    "single_array_payload_bytes_max": 10752 * 24,
    "aggregate_numeric_payload_bytes_max": 16 * 1024 * 1024,
    "decoded_files_max_including_xml": 65,
    "decoded_directories_max_including_part_item": 2,
    "decoded_output_bytes_max": 24 * 1024 * 1024,
    "text_arrays": "reject as unsupported for R008 native particle frames; scalar text metadata remains individually and cumulatively bounded",
}


def build_receipt() -> dict[str, Any]:
    receipt = v2.build_receipt()
    receipt["schema"] = SCHEMA
    receipt["status"] = (
        "format_contract_bounded_safe_streaming_preflight_required_"
        "historical_binary_build_linkage_unverified"
    )
    receipt["prior_audit_implementation"] = receipt["audit_implementation"]
    receipt["audit_implementation"] = v2.v1._fingerprint(
        Path(__file__), "Terra High v2 finding correction and bounded-preflight contract"
    )
    receipt["supersedes"]["prior_v2_receipt"] = v2.v1._fingerprint(
        v2.OUTPUT, "preserved BI4 static audit v2 receipt reviewed REVISE"
    )
    receipt["supersedes"]["prior_v2_review"] = {
        "reviewer": "Terra High",
        "model": "gpt-5.6-terra",
        "effort": "high",
        "verdict": "REVISE",
        "finding": (
            "The safe adapter must bound raw input/header/tree/count/array/total bytes before full load or allocation; validating names only after LoadFile(..., true) is too late."
        ),
        "execution_authority_granted": False,
    }
    receipt["bounded_streaming_preflight"] = {
        "required_order": [
            "Open the exact raw BI4 with openat/O_NOFOLLOW as a regular single-link file under the approved raw-output root; fstat and bind its SHA-256 on that descriptor.",
            "Before full load or large allocation, validate exact 64-byte JBinaryData header, magic/filecode, little-endian byte order, supported non-si64 mode, and raw file size cap.",
            "Use a bounded streaming parser over that same descriptor. Before allocating any item/array/value object or payload, check recursion depth, item/array/value counts, bounded strings/names, type allowlist, overflow-safe count*type-size, declared payload within remaining file, per-array cap, cumulative cap, and exact EOF.",
            "Validate the complete item/array tree and all output path components before the first output filesystem mutation.",
            "Only then stream a second pass from the same stable input descriptor into exclusively created files rooted at held dirfds using mkdirat/openat with O_NOFOLLOW/O_EXCL; check every read/write/flush/close and re-fstat/hash the same input descriptor.",
            "Finally enforce recursive XML-to-file manifest equality, output size/file caps, per-file hash/type/count/bytes, and st_nlink==1.",
        ],
        "resource_limits": RESOURCE_LIMITS,
        "limit_basis": {
            "r008_generated_total_particles": 10752,
            "r008_generated_fixed_particles": 4096,
            "largest_supported_fixed_type_bytes": 24,
            "max_single_array_bytes_calculation": "10752 * 24 = 258048",
            "max_aggregate_array_bytes_calculation": "64 * 258048 = 16515072 < 16777216 (16 MiB)",
            "raw_file_cap_margin": "64 MiB is over 120x the existing 523703-byte GenCase initial BI4 while still bounding memory and parser work; actual solver artifacts must fit or fail closed pending a new reviewed cap.",
            "tree_shape": "R008 JPartDataBi4 file contains one root JPartDataBi4 item and one PART_#### child; any additional nesting/items fail closed.",
            "unsupported_extensions": "If a future official R008 writer introduces a valid frame exceeding these caps or text-array payloads, reject and review a new schema/cap instead of widening silently.",
        },
        "existing_parser_caveat": {
            "JBinaryData_LoadFile_memory_true": "allocates a buffer sized from the whole file before structural bounds are checked; not acceptable as the preflight parser for untrusted input.",
            "JBinaryData_OpenFileStructure": "does not load array payloads but still materializes metadata/tree nodes without these R008-specific count/depth/name/aggregate caps; not sufficient by itself as an adversarial-input preflight.",
            "required_implementation": "A separately reviewed bounded streaming scanner/parser or equivalent modifications that enforce all caps before allocation; no existing decoder invocation is authorized by this audit.",
        },
    }
    receipt["readiness_effect"]["bounded_safe_decoder_implemented"] = False
    receipt["readiness_effect"]["bounded_safe_decoder_independently_reviewed"] = False
    receipt["readiness_effect"]["readiness_pass"] = False
    receipt["readiness_effect"]["qualification_credit"] = 0
    receipt["readiness_effect"]["solver_execution_authorized"] = False
    return receipt


def verify_receipt(receipt: dict[str, Any]) -> bool:
    """Reject every divergence from the complete canonical v3 payload."""
    try:
        return receipt == build_receipt()
    except (OSError, ValueError):
        return False


def write_immutable_receipt(path: Path = OUTPUT) -> dict[str, Any]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_receipt()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", closefd=False) as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(fd)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the immutable v3 audit receipt")
    args = parser.parse_args(argv)
    if args.write:
        receipt = write_immutable_receipt()
        print(json.dumps({"status": receipt["status"], "output": str(OUTPUT)}))
    else:
        receipt = build_receipt()
        print(json.dumps({"status": receipt["status"], "evidence_count": len(receipt["evidence"])}))
    return 0 if verify_receipt(receipt) else 1


if __name__ == "__main__":
    raise SystemExit(main())
