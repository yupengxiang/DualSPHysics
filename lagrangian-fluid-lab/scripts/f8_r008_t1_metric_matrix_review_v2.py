#!/usr/bin/env python3
"""Parent-authored immutable archive of the Terra High v2 metric-matrix review."""
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

from scripts import f8_r008_t1_metric_matrix_adapter_v2 as matrix


ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/native-fluid-table-schema-v2")
OUTPUT = LAB / ROOT / "metric-matrix-review-v2/receipt.json"
ARCHIVE_TEST_PATH = "tests/test_f8_r008_t1_metric_matrix_review_v2.py"
SCHEMA = "core.cfd.f8.r008_t1_metric_matrix_implementation_review.v2"
RECORD_ID = "f8-r008-t1-metric-matrix-implementation-review-v2"
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
    matrix._load_frozen_contract()
    review_modules = (
        matrix.metric_v1_review,
        matrix.metric_review_v2,
        matrix.table_review,
    )
    for review_module in review_modules:
        review_module.verify_receipt()

    code_paths = (
        "scripts/f8_r008_t1_metric_matrix_adapter_v2.py",
        "scripts/f8_r008_native_fluid_table_metric_bundle_verifier_v2.py",
        "scripts/f8_r008_t1_metric_adapter_v2.py",
        "scripts/f8_r008_t1_metric_adapter_v1.py",
        "scripts/f8_r008_native_fluid_table_v2.py",
        "scripts/f8_r008_t1_metric_adapter_review_v1.py",
        "scripts/f8_r008_native_fluid_table_metric_review_v2.py",
        "scripts/f8_r008_native_fluid_table_schema_review_v2.py",
    )
    test_paths = (
        "tests/test_f8_r008_t1_metric_matrix_adapter_v2.py",
        "tests/test_f8_r008_native_fluid_table_metric_bundle_verifier_v2.py",
        "tests/test_f8_r008_t1_metric_adapter_v2.py",
        "tests/test_f8_r008_t1_metric_adapter_v1.py",
        ARCHIVE_TEST_PATH,
    )
    receipt_paths = tuple(
        module.OUTPUT.relative_to(LAB).as_posix() for module in review_modules
    )
    frozen_paths = (
        matrix.metric_v1.FROZEN_SCOPE_RECEIPT.relative_to(LAB).as_posix(),
        matrix.metric_v1.FROZEN_PARAMETER_CONTRACT.relative_to(LAB).as_posix(),
    )
    evidence = [_file_binding(path) for path in (*code_paths, *test_paths, *receipt_paths, *frozen_paths)]
    evidence.append(_file_binding(Path(__file__).resolve().relative_to(LAB).as_posix()))

    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "status": "static_implementation_review_passed_no_execution_or_t1_credit",
        "reviewer": REVIEWER,
        "reviewed_scope": {
            "frozen_case_denominator": 15,
            "cross_resolution_comparisons": 8,
            "time_step_control": True,
            "output_cadence_control": True,
            "bounded_nofollow_solver_audit_reader": True,
            "native_integrity_or_final_T1_adjudication": False,
        },
        "findings": [
            {
                "topic": "fixed 15-case denominator and per-case result bindings",
                "verdict": "PASS",
                "detail": "The matrix requires exactly the frozen 15 IDs, validates each zero-credit v2 per-case record against the reviewed metric contract, and rejects failed/malformed B/C/D bindings without deleting cases.",
            },
            {
                "topic": "cross-resolution and control comparisons",
                "verdict": "PASS",
                "detail": "All eight frozen pairs use the registered coefficient limits and common output grid; time-step ordering/phase and dense-output downsampling are separate predeclared controls whose failures propagate to the aggregate.",
            },
            {
                "topic": "solver timestep audit input safety",
                "verdict": "PASS",
                "detail": "Audit JSON is capped at 1 MiB, opened no-follow/nonblocking as a single-link regular file, and identity-checked before/after reading. Bound source logs are also opened no-follow/nonblocking, streamed, and checked against byte/hash bindings.",
            },
            {
                "topic": "T1 and qualification boundary",
                "verdict": "PASS",
                "detail": "Metric and comparison outcomes are reported separately from native integrity and final T1; output keeps readiness and T1 false with zero qualification credit.",
            },
        ],
        "known_limitations": [
            "The matrix consumes per-case verifier result objects; it does not reopen or independently authenticate external caller B/C/D receipts or authorization envelopes.",
            "Native-integrity gates, loaded-module/runtime identity, final T1 adjudication, and production solver evidence remain separate and unevaluated.",
            "All new matrix tests use temporary synthetic records/audits; no production bundle, solver frame, or native execution was used.",
        ],
        "reviewer_validation": {
            "command": "./.venv/bin/pytest -q tests/test_f8_r008_t1_metric_matrix_adapter_v2.py",
            "passed": 22,
            "failed": 0,
            "fixture_scope": "synthetic v2 case results and temporary audit/source-log files only",
        },
        "parent_validation": {
            "command": "./.venv/bin/pytest -q tests/test_f8_r008_native_fluid_table_v2.py tests/test_f8_r008_native_fluid_table_metric_bundle_verifier_v2.py tests/test_f8_r008_t1_metric_adapter_v1.py tests/test_f8_r008_t1_metric_adapter_v2.py tests/test_f8_r008_native_fluid_table_producer_v2.py tests/test_f8_r008_native_fluid_table_producer_review_v2.py tests/test_f8_r008_t1_metric_matrix_adapter_v2.py",
            "passed": 90,
            "failed": 0,
            "fixture_scope": "synthetic HDF5/source frames, synthetic B/C/D bundles, and temporary audit logs only",
        },
        "review_boundary": REVIEW_BOUNDARY,
        "execution_authority": EXECUTION_AUTHORITY,
        "evidence": evidence,
    }


def verify_receipt(path: Path = OUTPUT) -> dict[str, Any]:
    receipt = json.loads(Path(path).read_text(encoding="utf-8"))
    if receipt != build_receipt():
        raise ValueError("immutable Terra High R008 v2 matrix review no longer matches reviewed evidence")
    return receipt


def write_receipt(path: Path = OUTPUT) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = LAB / target
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable F8 R008 v2 matrix review: {target}")
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
