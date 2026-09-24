#!/usr/bin/env python3
"""Archive Terra High's read-only review of F8 R008 B/C/D table orchestration."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB))
ROOT = Path(
    "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/"
    "native-fluid-table-schema-v2"
)
OUTPUT = LAB / ROOT / "bundle-review-v1/receipt.json"
SCHEMA = "core.cfd.f8.r008_native_fluid_table_bundle_implementation_review.v1"
RECORD_ID = "f8-r008-native-fluid-table-bundle-implementation-review-v1"
REVIEWER = {
    "model": "gpt-5.6-terra",
    "reasoning_effort": "high",
    "agent_id": "01a0d2a7-a95a-72d0-bdc2-7192cf9900ba",
    "verdict": "PASS",
    "review_mode": "read_only_static_implementation_review",
    "reviewer_ran_tests": False,
    "execution_or_evidence_mutation": False,
}
REVIEW_BOUNDARY = {
    "production_bundle_read": False,
    "native_tools_invoked": False,
    "solver_or_worker_invoked": False,
    "gpu_or_queue_invoked": False,
    "registry_or_ledger_mutated": False,
    "qualification_credit": 0,
}
EVIDENCE_PATHS = (
    "scripts/f8_r008_native_fluid_table_bundle_verifier_v1.py",
    "tests/test_f8_r008_native_fluid_table_bundle_verifier_v1.py",
    "scripts/f8_r008_native_fluid_table_v2.py",
    "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/native-fluid-table-schema-v2/schema.json",
    "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/native-fluid-table-schema-v2/design-review-v2/receipt.json",
    "scripts/f8_r008_per_case_bundle_verifier_v1.py",
    "scripts/f8_r008_safe_bi4_decoder_v1.py",
    "scripts/f8_r008_safe_bi4_metadata_binding_v1.py",
    "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/per-case-provenance-implementation-review-v2/receipt.json",
    "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/definition-control-pack-v1/receipt.json",
    "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/t1-scope-design-v1/receipt.json",
    "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/parameter-contract-v1.json",
    "scripts/f8_r008_native_fluid_table_bundle_review_v1.py",
    "tests/test_f8_r008_native_fluid_table_bundle_review_v1.py",
)


def _binding(relative_path: str) -> dict[str, Any]:
    path = LAB / relative_path
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ValueError(f"review evidence must be a single-link regular file: {relative_path}")
        digest = hashlib.sha256()
        size = 0
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                break
            size += len(block)
            digest.update(block)
        after = os.fstat(fd)
        named = os.stat(path, follow_symlinks=False)
        identity = lambda st: (
            st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_nlink,
        )
        if identity(before) != identity(after) or identity(after) != identity(named):
            raise ValueError(f"review evidence changed while binding: {relative_path}")
        if size != before.st_size:
            raise ValueError(f"review evidence byte count changed while binding: {relative_path}")
        return {"path": relative_path, "bytes": size, "sha256": digest.hexdigest()}
    finally:
        os.close(fd)


def _validate_parent_reviews() -> None:
    from scripts import f8_r008_native_fluid_table_schema_review_v2 as table_review
    from scripts import f8_r008_per_case_provenance_implementation_review_v2 as chain_review

    table_receipt = table_review.verify_receipt()
    if table_receipt["reviewer"]["verdict"] != "PASS":
        raise ValueError("standalone native-table review is not PASS")
    chain_receipt = chain_review.verify_receipt()
    if chain_receipt["reviewer"]["verdict"] != "PASS":
        raise ValueError("B/C/D provenance verifier review is not PASS")


def build_receipt() -> dict[str, Any]:
    from scripts import f8_r008_native_fluid_table_bundle_verifier_v1 as verifier

    _validate_parent_reviews()
    if verifier.SCHEMA != "core.cfd.f8.r008_native_fluid_table_bundle_verifier.v1":
        raise ValueError("bundle integration schema changed")
    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "status": "static_implementation_review_passed_no_execution_or_t1_credit",
        "reviewer": REVIEWER,
        "reviewed_scope": {
            "revalidated_B_C_D_provenance_chain": True,
            "frozen_definition_and_control_source_bytes": True,
            "native_fluid_table_v2_semantics_from_C_raw_frames": True,
            "synthetic_and_adversarial_integration_tests": True,
            "solver_or_T1_adjudication": False,
        },
        "findings": [
            {
                "topic": "frozen B inputs",
                "verdict": "PASS",
                "detail": "B Definition/control receipt bindings are matched to the frozen R008 pack row, then the actual source bytes and pinned parameter contract are reread and hashed before and after semantic verification.",
            },
            {
                "topic": "B/C/D composition",
                "verdict": "PASS",
                "detail": "The wrapper composes the reviewed stage verifier, re-derives fluid IDs and MassFluid from B, streams held-FD C raw frames into the standalone v2 HDF5 verifier, binds the result to D, and revalidates the full chain after the pass.",
            },
            {
                "topic": "mutation and descriptor closure",
                "verdict": "PASS",
                "detail": "Receipt, manifest, source and table bindings are checked across the semantic pass; the source-frame generator and per-frame raw file descriptor close on success and injected midstream failure.",
            },
            {
                "topic": "negative integration coverage",
                "verdict": "PASS",
                "detail": "Synthetic fixtures exercise successful B/C/D composition and reject drift in frozen Definition/control, trusted table-review binding, parameter contract, D table binding, and final chain digests.",
            },
        ],
        "known_boundary": "Authorization authenticity, wrapper/module code identity, and runtime assumptions remain caller-supplied trust inputs. No production bundle or solver frame was read; this wrapper performs no native integrity adjudication, metric evaluation, readiness decision, T1 qualification, or credit assignment.",
        "parent_validation": {
            "command": "./.venv/bin/python -m pytest -q tests/test_f8_r008_native_fluid_table_bundle_verifier_v1.py",
            "passed": 10,
            "failed": 0,
            "reviewer_ran_tests": False,
            "fixture_scope": "temporary synthetic B/C/D receipts, BI4, and HDF5 only",
        },
        "review_boundary": REVIEW_BOUNDARY,
        "execution_authority": {
            "solver": False,
            "worker": False,
            "gpu": False,
            "queue": False,
            "T1_numerical": False,
            "qualification_credit": 0,
        },
        "evidence": [_binding(path) for path in EVIDENCE_PATHS],
    }


def verify_receipt(path: Path = OUTPUT) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if value != build_receipt():
        raise ValueError("immutable B/C/D native-table review no longer matches reviewed evidence")
    return value


def write_receipt(path: Path = OUTPUT) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = LAB / target
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable bundle review: {target}")
    payload = json.dumps(build_receipt(), indent=2, sort_keys=True, allow_nan=False) + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        target,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        0o644,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            os.close(descriptor)
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
