#!/usr/bin/env python3
"""Archive Terra High's static review of the bounded F8 R008 BI4 decoder."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB))

ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008")
SCRIPT = Path(__file__).resolve().relative_to(LAB)
TEST = Path("tests/test_f8_r008_safe_bi4_decoder_review_v1.py")
DECODER = Path("scripts/f8_r008_safe_bi4_decoder_v1.py")
DECODER_TEST = Path("tests/test_f8_r008_safe_bi4_decoder_v1.py")
OUTPUT = LAB / ROOT / "safe-bi4-decoder-review-v1/receipt.json"
SCHEMA = "core.cfd.f8.r008_safe_bi4_decoder_review.v1"
REVIEWER_ID = "01a0d167-4db5-7f90-aee2-94547602a273"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with (LAB / path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def binding(path: Path, role: str) -> dict[str, Any]:
    absolute = LAB / path
    payload = absolute.read_bytes()
    return {
        "path": path.as_posix(),
        "role": role,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def build_receipt() -> dict[str, Any]:
    from scripts import f8_r008_execution_readiness_audit_v4 as audit

    current_audit = audit.verify_audit()
    if current_audit.get("readiness_pass") is not False or current_audit.get("qualification_credit") != 0:
        raise ValueError("the current F8 R008 readiness audit must remain blocked and zero-credit")

    evidence = [
        binding(DECODER, "reviewed bounded streaming BI4 scanner and safe materializer"),
        binding(DECODER_TEST, "synthetic BI4 wire-format, bound, mutation, and output-closure tests"),
        binding(Path("vendor/official/DualSPHysics_v5.4/src/source/JBinaryData.cpp"), "pinned official JBinaryData writer/parser source"),
        binding(Path("vendor/official/DualSPHysics_v5.4/src/source/JBinaryData.h"), "pinned official JBinaryData types and wire declarations"),
        binding(Path("vendor/official/DualSPHysics_v5.4/src/source/JPartDataBi4.cpp"), "pinned official R008 particle-item layout source"),
        binding(Path("scripts/f8_r008_bi4_format_static_audit_v3.py"), "frozen bounded BI4 format contract"),
        binding(Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/bi4-format-static-audit-v3/receipt.json"), "immutable v3 format audit and resource-cap receipt"),
        binding(Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/bi4-format-static-audit-review-v3/receipt.json"), "Terra High PASS for the static format contract only"),
        binding(Path("reports/F8-R008-PER-CASE-PROVENANCE-DESIGN-PROPOSAL-V2-2026-09-24.zh-CN.md"), "reviewed boundary between decode materialization and later provenance/T1 gates"),
        binding(Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/t1-per-case-provenance-design-review-v2/receipt.json"), "Terra High PASS for static provenance design only"),
        binding(Path("scripts/f8_r008_execution_readiness_audit_v4.py"), "current readiness/zero-credit gate implementation"),
        binding(Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/t1-execution-readiness-audit-v4/receipt.json"), "current immutable R008 readiness receipt"),
        binding(SCRIPT, "parent-authored archive builder, not reviewer-authored content"),
        binding(TEST, "review archive immutability and canonical binding tests"),
    ]
    return {
        "schema": SCHEMA,
        "record_id": "f8-r008-safe-bi4-decoder-review-v1",
        "scope_id": "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008",
        "status": "static_safe_decoder_review_passed_no_native_execution",
        "reviewer": {
            "name": "Terra High",
            "model": "gpt-5.6-terra",
            "reasoning_effort": "high",
            "agent_id": REVIEWER_ID,
            "review_thread_note": "Follow-up in the same Terra High thread as the R008 format/design reviews; not a newly independent reviewer.",
            "verdict": "PASS",
            "review_mode": "read_only_static_code_review",
            "reviewer_ran_tests": False,
            "reviewer_read_production_bi4": False,
            "reviewer_modified_files": False,
        },
        "parent_validation": {
            "decoder_tests": {
                "command": "PYTHONPATH=. .venv/bin/pytest -q tests/test_f8_r008_safe_bi4_decoder_v1.py",
                "passed": 17,
                "failed": 0,
                "input_scope": "temporary synthetic BI4 byte fixtures only",
            },
            "r008_regression": {
                "command": ".venv/bin/pytest -q tests/test_f8_r008_*.py -k 'not test_v3_native_commands_use_absolute_paths_and_the_verified_cap and not test_v3_supersedes_unexecuted_v2_and_grants_no_execution_or_credit and not test_v3_hash_closes_inputs_v2_request_builder_and_tests and not test_v3_rejects_a_changed_superseded_request and not test_authorization_builder_verifies_frozen_request_and_review'",
                "passed": 128,
                "failed": 0,
                "deselected": 5,
                "deselection_reason": "one-time prelaunch request/authorization tests require an absent R008 runtime namespace; the already-consumed namespace is intentionally preserved and was not reset or retried",
            },
            "python_bytecode_validation": "passed",
        },
        "review_findings": [
            {
                "topic": "bounded pre-allocation parser",
                "verdict": "PASS",
                "detail": "Same-descriptor hash/fstat checks, fixed header validation, bounded metadata/tree/count/type checks and streaming array payload handling precede output creation; no whole-file native JBinaryData load is used.",
            },
            {
                "topic": "filesystem threat model and output closure",
                "verdict": "PASS",
                "detail": "Input is opened beneath a held root with no-follow checks and st_nlink==1. Output uses exclusive no-follow creation, 0700 child directories, exact manifest/tree/hash verification, and an explicit caller precondition for a dedicated parent with no ACL/capability/privileged cross-UID writer; same-UID writers are trusted.",
            },
            {
                "topic": "official metadata and visibility fidelity",
                "verdict": "PASS",
                "detail": "Item and array visibility flags are kept distinct. The R008 subset pins and tests the official JBinaryData default float/double formats (%.7E/%.15E) and rejects format deviations before materialization.",
            },
            {
                "topic": "mutation, resource and adversarial fixture coverage",
                "verdict": "PASS",
                "detail": "Synthetic tests cover byte/count mismatch, path traversal, hard links/symlinks, hash mismatch, unsupported endian/SI64, invalid XML metadata, long sidecar names, shared writable output parents, and input mutation between bounded array reads.",
            },
        ],
        "remaining_limitations": [
            "This is a pure-Python narrow safe scanner/materializer; it does not invoke, replace, or establish historical source/build provenance for the existing bi4_dump executable.",
            "No production R008 BI4 was read or decoded; generated XML/array output was exercised only with temporary synthetic fixtures.",
            "No R008 per-case materialization/solver/decode provenance verifier, provenance-v2 table, solver frames, or formal 15-row T1 result exists yet.",
            "readiness_pass remains false, qualification credit remains zero, and all native/solver/worker/GPU/queue execution remains unauthorized by this review.",
        ],
        "execution_controls": {
            "production_bi4_read": False,
            "native_decoder_invoked": False,
            "gencase_invoked": False,
            "solver_invoked": False,
            "worker_started": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "qualification_credit": 0,
        },
        "readiness_effect": {
            "readiness_pass": False,
            "qualification_credit": 0,
            "execution_authority_granted": False,
        },
        "evidence": evidence,
    }


def verify_receipt(path: Path = OUTPUT) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if value.get("schema") != SCHEMA or value != build_receipt():
        raise ValueError("safe BI4 decoder review receipt no longer matches reviewed evidence")
    return value


def write_receipt(path: Path = OUTPUT) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = LAB / target
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable safe BI4 decoder review: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(build_receipt(), indent=2, sort_keys=True, allow_nan=False) + "\n"
    fd = os.open(
        target,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o644,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        raise
    return target


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the immutable review receipt once")
    args = parser.parse_args()
    if args.write:
        print(write_receipt().relative_to(LAB))
    else:
        print(json.dumps(build_receipt(), indent=2, sort_keys=True))
