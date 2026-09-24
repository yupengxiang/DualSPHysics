#!/usr/bin/env python3
"""Parent-authored immutable archive of the Terra High v2 producer review."""
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

from scripts import f8_r008_native_fluid_table_schema_review_v2 as schema_review
from scripts import f8_r008_native_fluid_table_v2 as table_v2


ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/native-fluid-table-schema-v2")
OUTPUT = LAB / ROOT / "producer-review-v2/receipt.json"
PRODUCER_PATH = "scripts/f8_r008_native_fluid_table_producer_v2.py"
SOURCE_VERIFIER_PATH = "scripts/f8_r008_native_fluid_table_v2.py"
SOURCE_DECODER_PATH = "scripts/f8_r008_safe_bi4_decoder_v1.py"
SOURCE_FIXTURE_PATH = "tests/test_f8_r008_native_fluid_table_v2.py"
TEST_PATH = "tests/test_f8_r008_native_fluid_table_producer_v2.py"
ARCHIVE_TEST_PATH = "tests/test_f8_r008_native_fluid_table_producer_review_v2.py"
SCHEMA = "core.cfd.f8.r008_native_fluid_table_producer_implementation_review.v2"
RECORD_ID = "f8-r008-native-fluid-table-producer-implementation-review-v2"
REVIEWER = {
    "model": "gpt-5.6-terra",
    "reasoning_effort": "high",
    "agent_id": "01a0d2ed-c88b-76c0-9ec5-38077fa80a7a",
    "verdict": "PASS",
    "review_mode": "read_only_static_implementation_review",
    "reviewer_ran_tests": True,
    "execution_or_evidence_mutation": False,
    "archive_note": "Parent-authored source-hash archive; not represented as reviewer-authored content.",
}
REVIEW_BOUNDARY = {
    "production_bundle_read": False,
    "native_solver_frame_read": False,
    "gencase_invoked": False,
    "native_decoder_invoked": False,
    "solver_or_worker_invoked": False,
    "gpu_or_queue_invoked": False,
    "registry_or_ledger_mutated": False,
    "native_integrity_evaluated": False,
    "T1_numerical": False,
    "qualification_credit": 0,
}
EXECUTION_AUTHORITY = {
    "solver": False,
    "worker": False,
    "gpu": False,
    "queue": False,
    "T1_numerical": False,
    "qualification_credit": 0,
}


def _file_binding(relative_path: str) -> dict[str, Any]:
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
        identity = lambda value: (
            value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
            value.st_ctime_ns, value.st_nlink,
        )
        if identity(before) != identity(after) or identity(after) != identity(named) or size != before.st_size:
            raise ValueError(f"review evidence changed while hashed: {relative_path}")
        return {"path": relative_path, "bytes": size, "sha256": digest.hexdigest()}
    finally:
        os.close(fd)


def build_receipt() -> dict[str, Any]:
    schema_receipt = schema_review.verify_receipt()
    if table_v2.TABLE_SCHEMA != "core.cfd.f8.r008_native_fluid_frame_table.v2":
        raise ValueError("reviewed v2 table schema dependency changed")
    source_paths = (
        PRODUCER_PATH, SOURCE_VERIFIER_PATH, SOURCE_DECODER_PATH,
        SOURCE_FIXTURE_PATH, TEST_PATH, ARCHIVE_TEST_PATH,
    )
    evidence = [_file_binding(path) for path in source_paths]
    schema_receipt_binding = _file_binding(schema_review.OUTPUT.relative_to(LAB).as_posix())
    evidence.extend([schema_receipt_binding,
                     _file_binding(Path(__file__).resolve().relative_to(LAB).as_posix())])
    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "status": "static_implementation_review_passed_no_execution_or_t1_credit",
        "reviewer": REVIEWER,
        "reviewed_scope": {
            "table_schema": table_v2.TABLE_SCHEMA,
            "bounded_streaming_serialization": True,
            "two_pass_source_recomputation": True,
            "independent_semantic_verifier": True,
            "verified_B_C_D_orchestration": False,
            "authorization_authenticity": False,
            "native_integrity_or_T1_adjudication": False,
        },
        "findings": [
            {
                "topic": "v2 serialization contract",
                "verdict": "PASS",
                "detail": "The writer emits the exact reviewed attribute/dataset inventory, dtypes, row chunks, compression and native boolean enums under the table-v2 verifier contract.",
            },
            {
                "topic": "raw source projection",
                "verdict": "PASS",
                "detail": "Every source pass checks the complete time axis, full CaseNp uint32 ID permutation, B-bound CaseNp/MassFluid, selected fluid IDs, and finite typed position/velocity/density rows; the independent verifier recomputes the generated table against the second stream.",
            },
            {
                "topic": "completion and publication atomicity",
                "verdict": "PASS",
                "detail": "The temporary HDF5 image starts with conversion_complete false, is made true only after all rows are durable, and is semantically verified before no-replace link publication. Inode-bound cleanup preserves pre-existing/rebound names.",
            },
            {
                "topic": "caller-context boundary",
                "verdict": "PASS",
                "detail": "The primitive reports that B/C provenance, authorization authenticity, native integrity, T1, and qualification credit are not established; safe reopening and hash authentication of both source-factory passes remain caller responsibilities.",
            },
        ],
        "known_limitations": [
            "This primitive does not verify B/C/D provenance, authorization authenticity, or loaded-module/runtime identity.",
            "The caller's source_frames_factory must independently reopen and hash-bind the exact C inputs on both invocations.",
            "No production bundle, solver frame, native decoder, solver, worker, GPU, or queue was used.",
        ],
        "schema_review_receipt_sha256": schema_receipt_binding["sha256"],
        "reviewer_validation": {
            "command": "./.venv/bin/pytest -q tests/test_f8_r008_native_fluid_table_producer_v2.py",
            "passed": 7,
            "failed": 0,
            "fixture_scope": "temporary synthetic source frames and HDF5 output only",
        },
        "parent_validation": {
            "command": "./.venv/bin/pytest -q tests/test_f8_r008_native_fluid_table_producer_v2.py",
            "passed": 7,
            "failed": 0,
            "fixture_scope": "temporary synthetic source frames and HDF5 output only",
        },
        "review_boundary": REVIEW_BOUNDARY,
        "execution_authority": EXECUTION_AUTHORITY,
        "evidence": evidence,
    }


def verify_receipt(path: Path = OUTPUT) -> dict[str, Any]:
    receipt = json.loads(Path(path).read_text(encoding="utf-8"))
    if receipt != build_receipt():
        raise ValueError("immutable Terra High R008 v2 producer review no longer matches reviewed evidence")
    return receipt


def write_receipt(path: Path = OUTPUT) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = LAB / target
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable F8 R008 v2 producer review: {target}")
    payload = json.dumps(build_receipt(), indent=2, sort_keys=True, allow_nan=False) + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                 | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0), 0o644)
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
    parser.add_argument("--write", action="store_true", help="write the immutable Terra High receipt once")
    args = parser.parse_args()
    if args.write:
        print(write_receipt().relative_to(LAB))
    else:
        print(json.dumps(build_receipt(), indent=2, sort_keys=True))
