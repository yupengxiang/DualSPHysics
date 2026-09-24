"""Close Terra High v1 findings without launching any native executable."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from scripts import f8_r008_bi4_format_static_audit_v1 as v1


LAB = v1.LAB
OUTPUT = (
    LAB
    / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/"
    "bi4-format-static-audit-v2/receipt.json"
)
SCHEMA = "core.cfd.f8.r008_bi4_format_static_audit.v2"
PRIOR_RECEIPT = v1.OUTPUT


def build_receipt() -> dict[str, Any]:
    receipt = v1.build_receipt()
    receipt["schema"] = SCHEMA
    receipt["status"] = (
        "format_contract_bounded_safe_decoder_prerequisite_open_"
        "historical_binary_build_linkage_unverified"
    )
    receipt["prior_audit_implementation"] = receipt["audit_implementation"]
    receipt["audit_implementation"] = v1._fingerprint(
        Path(__file__), "Terra High v1 findings correction and full-payload verifier"
    )
    receipt["supersedes"] = {
        "receipt": v1._fingerprint(PRIOR_RECEIPT, "preserved v1 audit receipt reviewed REVISE"),
        "review": {
            "reviewer": "Terra High",
            "model": "gpt-5.6-terra",
            "effort": "high",
            "verdict": "REVISE",
            "findings": [
                "v1 verify_receipt did not compare the full canonical contract payload.",
                "bi4_dump writes BI4-controlled item/array names through unchecked path concatenation; a post-run manifest cannot prevent out-of-namespace writes.",
            ],
            "execution_authority_granted": False,
        },
    }
    receipt["decoder_path_security"] = {
        "current_decoder_source": "scripts/native/bi4_dump.cpp",
        "current_decoder_source_sha256": v1.PINNED_EVIDENCE["decoder_source"][1],
        "current_source_path_names_validated": False,
        "current_source_uses_dirfd_openat_and_nofollow": False,
        "current_source_checks_output_stream_errors": False,
        "postrun_manifest_prevents_escape_writes": False,
        "unsafe_decoder_authorized_for_future_input": False,
        "execution_blocked_until": [
            "A reviewed decoder adapter validates every item/array name as a single safe path component before any filesystem write.",
            "Output is rooted in an exclusively created directory and written via directory-relative no-follow/exclusive opens; symlink traversal and overwrite are impossible.",
            "All directory/file creation, writes, flush/close, type/count/size limits, and namespace closure fail closed.",
            "The exact safe decoder binary hash/build identity is recorded at invocation and bound to its reviewed source/build inputs.",
        ],
        "minimum_name_policy": {
            "allowed": "bounded ASCII path-component allowlist for the R008 item/array names",
            "rejected": [
                "empty",
                ".",
                "..",
                "/",
                "\\",
                "NUL",
                "control bytes",
                "absolute/separator-containing names",
                "overlong names",
                "duplicates",
            ],
            "validation_order": "validate the entire decoded item/array tree before creating any output",
        },
        "minimum_filesystem_policy": [
            "fresh output target exclusively created beneath an approved parent",
            "openat/mkdirat relative to held directory descriptors",
            "O_NOFOLLOW and O_EXCL on every created object",
            "fstat regular-file and st_nlink==1 checks",
            "bounded recursion, file count, per-file bytes, and total output bytes",
            "check every mkdir/open/write/flush/close result",
        ],
    }
    receipt["future_per_case_acceptance_contract"]["predecode_safety_gate"] = (
        "Do not feed BI4 to the existing bi4_dump binary. Run only a separately reviewed safe decoder/adapter after complete item and array name validation; post-run manifest remains necessary but is not a path-traversal defense."
    )
    receipt["readiness_effect"]["safe_decoder_prerequisite_closed"] = False
    receipt["readiness_effect"]["readiness_pass"] = False
    return receipt


def verify_receipt(receipt: dict[str, Any]) -> bool:
    """Require exact equality with the complete canonical audit payload."""
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
    parser.add_argument("--write", action="store_true", help="write the immutable v2 audit receipt")
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
