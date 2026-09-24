#!/usr/bin/env python3
"""Parent-authored immutable archive of the Terra High R008 v2 metric review."""
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

from scripts import f8_r008_native_fluid_table_metric_bundle_verifier_v2 as verifier
from scripts import f8_r008_t1_metric_adapter_v2 as adapter


ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/native-fluid-table-schema-v2")
OUTPUT = LAB / ROOT / "metric-review-v2/receipt.json"
TEST_PATHS = (
    "tests/test_f8_r008_t1_metric_adapter_v2.py",
    "tests/test_f8_r008_native_fluid_table_metric_bundle_verifier_v2.py",
)
ARCHIVE_TEST_PATH = "tests/test_f8_r008_native_fluid_table_metric_review_v2.py"
SCHEMA = verifier.METRIC_REVIEW_SCHEMA
RECORD_ID = verifier.METRIC_REVIEW_RECORD_ID
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
REVIEW_SCOPE = {
    "consumer_schema": "core.cfd.f8.r008_native_fluid_frame_table.v2",
    "B_C_D_chain_closed_on_held_table_fd": True,
    "v2_case_metric_gates": True,
    "15_case_matrix_adjudication": False,
    "native_integrity_or_T1_adjudication": False,
}
REVIEW_BOUNDARY = {
    "production_bundle_read": False,
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
    if verifier.METRIC_CODE_PATHS != {
        "bundle_metric_verifier": "scripts/f8_r008_native_fluid_table_metric_bundle_verifier_v2.py",
        "metric_adapter": "scripts/f8_r008_t1_metric_adapter_v2.py",
        "reviewed_v1_metric_helpers": "scripts/f8_r008_t1_metric_adapter_v1.py",
    }:
        raise ValueError("versioned v2 metric review source inventory changed")
    code_evidence = [
        _file_binding(path) for path in verifier.METRIC_CODE_PATHS.values()
    ]
    test_evidence = [_file_binding(path) for path in (*TEST_PATHS, ARCHIVE_TEST_PATH)]
    archive_evidence = [_file_binding(Path(__file__).resolve().relative_to(LAB).as_posix())]
    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "status": "static_metric_implementation_review_passed_no_execution_or_t1_credit",
        "reviewer": REVIEWER,
        "reviewed_scope": REVIEW_SCOPE,
        "review_boundary": REVIEW_BOUNDARY,
        "execution_authority": EXECUTION_AUTHORITY,
        "findings": [
            {
                "topic": "same-descriptor table consumption",
                "verdict": "PASS",
                "basis": "B/C/D and v2 table semantics close before case metrics; the metric adapter consumes the held read-only D descriptor, checks its identity and digest, and the orchestrator re-closes B/C/D, safely reopens the bound path without following links, and confirms it still resolves to the same single-link inode before return.",
            },
            {
                "topic": "frozen metric inputs and v2 semantic preconditions",
                "verdict": "PASS",
                "basis": "The adapter pins the R008 scope, parameter contract, window parser and Womersley oracle; it requires complete frame/ID/position/velocity/density/mass/valid verification and reads only the time, fluid ID, initial z, invariant mass, and selected velocity inputs needed for case metrics.",
            },
            {
                "topic": "metric and qualification boundary",
                "verdict": "PASS",
                "basis": "Fixed-frequency coefficients, exact closed native window, three-cycle shared seams, case-specific Uref gates, and mass-weighted transverse RMS are computed; native integrity, solver timestep audit, 15-case matrix adjudication, full T1, readiness, and credit remain false or absent.",
            },
            {
                "topic": "reused v1 metric helpers",
                "verdict": "PASS",
                "basis": "The exact reused helper source is included in the v2 review binding and must also match the immutable Terra High v1 metric-adapter receipt before use.",
            },
            {
                "topic": "v1 compatibility and execution isolation",
                "verdict": "PASS",
                "basis": "The v1 reader and verifier remain unchanged; the additive v2 adapter does not call the GenCase-bound v1 high-level readers or launch tools/jobs.",
            },
        ],
        "known_limitations": [
            "This implementation evaluates one frozen case's diagnostic metric gates only; no v2 15-case/cross-resolution/time-step matrix adjudicator is implemented.",
            "No solver timestep audit or native-integrity gate is consumed; no production bundle or solver frame was read.",
            "Caller-supplied authorization/review authenticity and loaded-module/runtime identity are not authenticated by this receipt.",
        ],
        "reviewer_validation": {
            "command": "PYTHONPATH=. .venv/bin/pytest -q tests/test_f8_r008_t1_metric_adapter_v2.py tests/test_f8_r008_native_fluid_table_metric_bundle_verifier_v2.py",
            "passed": 14,
            "failed": 0,
            "fixture_scope": "temporary synthetic HDF5/BI4/B/C/D bundle only",
        },
        "parent_validation": {
            "command": "PYTHONPATH=. .venv/bin/pytest -q tests/test_f8_r008_t1_metric_adapter_v2.py tests/test_f8_r008_native_fluid_table_metric_bundle_verifier_v2.py",
            "passed": 14,
            "failed": 0,
            "fixture_scope": "temporary synthetic HDF5/BI4/B/C/D bundle only",
        },
        "evidence": code_evidence + test_evidence + archive_evidence,
    }


def verify_receipt(path: Path = OUTPUT) -> dict[str, Any]:
    receipt = json.loads(Path(path).read_text(encoding="utf-8"))
    if receipt != build_receipt():
        raise ValueError("immutable Terra High R008 v2 metric review no longer matches reviewed code/tests")
    return receipt


def write_receipt(path: Path = OUTPUT) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = LAB / target
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable F8 R008 v2 metric review receipt: {target}")
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
