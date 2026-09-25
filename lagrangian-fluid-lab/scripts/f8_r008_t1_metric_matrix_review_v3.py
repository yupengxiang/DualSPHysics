#!/usr/bin/env python3
"""Parent-authored immutable archive of the Terra High RunPARTs matrix v4 review."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts import f8_r008_t1_metric_matrix_adapter_v2 as matrix_core
from scripts import f8_r008_t1_metric_matrix_adapter_v4 as matrix_v4
from scripts import f8_r008_t1_metric_adapter_v1 as metric_v1
from scripts import f8_r008_native_fluid_table_metric_bundle_verifier_v2 as metric_bundle
from scripts import f8_r008_native_fluid_table_metric_review_v2 as metric_review_v2
from scripts import f8_r008_native_fluid_table_schema_review_v2 as table_review


ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/native-fluid-table-schema-v2")
OUTPUT = LAB / ROOT / "metric-matrix-review-v3/receipt.json"
ARCHIVE_TEST_PATH = "tests/test_f8_r008_t1_metric_matrix_review_v3.py"
SCHEMA = "core.cfd.f8.r008_t1_metric_matrix_implementation_review.v3"
RECORD_ID = "f8-r008-t1-metric-matrix-implementation-review-v3"
REVIEWER = {
    "model": "gpt-5.6-terra",
    "reasoning_effort": "high",
    "agent_id": "01a0d8af-779c-7422-8fd4-b9f9e2295473",
    "verdict": "PASS",
    "review_mode": "read_only_static_implementation_review_with_findings_closed_by_followup",
    "reviewer_ran_tests": False,
    "execution_or_evidence_mutation": False,
    "cryptographic_model_identity_attestation": False,
    "archive_note": "Parent-authored source-hash archive; not represented as reviewer-authored content.",
}
REVIEW_HISTORY = [
    {
        "verdict": "REVISE",
        "summary": "Initial v2/v4 review found that the diagnostic policy was described as a frozen execution fact, signed floating zero was accepted under canonical wording, and cross-column native semantics were not checked.",
    },
    {
        "verdict": "REVISE",
        "summary": "Narrow follow-up confirmed those fixes and requested consistent policy wording and field-check names.",
    },
    {
        "verdict": "PASS",
        "summary": "Final Terra High follow-up confirmed all findings closed with no remaining P3.",
    },
]
REVIEW_BOUNDARY = {
    "production_runparts_read": False,
    "production_bundle_or_frame_read": False,
    "gencase_invoked": False,
    "native_decoder_invoked": False,
    "solver_or_worker_invoked": False,
    "gpu_or_queue_invoked": False,
    "registry_or_ledger_mutated": False,
    "execution_source_identity_verified": False,
    "runtime_configuration_verified": False,
    "normal_completion_verified": False,
    "cross_field_native_semantics_verified": False,
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
    if relative_path.startswith("repo:"):
        path = LAB.parent / relative_path.removeprefix("repo:")
    else:
        path = LAB / relative_path
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ValueError(f"review evidence must be a single-link regular file: {relative_path}")
        digest = hashlib.sha256()
        size = 0
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            size += len(block)
            digest.update(block)
        after = os.fstat(descriptor)
        named = os.stat(path, follow_symlinks=False)
        identity = lambda value: (
            value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
            value.st_ctime_ns, value.st_nlink,
        )
        if identity(before) != identity(after) or identity(after) != identity(named) or size != before.st_size:
            raise ValueError(f"review evidence changed while hashed: {relative_path}")
        return {"path": relative_path, "bytes": size, "sha256": digest.hexdigest()}
    finally:
        os.close(descriptor)


def build_receipt() -> dict[str, Any]:
    matrix_core._load_frozen_contract()
    for review_module in (matrix_core.metric_v1_review, matrix_core.metric_review_v2, matrix_core.table_review):
        review_module.verify_receipt()
    for module in (metric_v1, metric_bundle, metric_review_v2, table_review):
        if hasattr(module, "verify_receipt"):
            module.verify_receipt()

    code_paths = (
        "scripts/f8_r008_t1_metric_matrix_adapter_v2.py",
        "scripts/f8_r008_t1_metric_matrix_adapter_v4.py",
        "scripts/f8_r008_runparts_timestep_diagnostic_v1.py",
        "scripts/f8_r008_runparts_timestep_diagnostic_v2.py",
        "scripts/f8_r008_native_fluid_table_metric_bundle_verifier_v2.py",
        "scripts/f8_r008_t1_metric_adapter_v2.py",
        "scripts/f8_r008_t1_metric_adapter_v1.py",
        "scripts/f8_r008_native_fluid_table_v2.py",
    )
    test_paths = (
        "tests/test_f8_r008_runparts_timestep_diagnostic_v1.py",
        "tests/test_f8_r008_runparts_timestep_diagnostic_v2.py",
        "tests/test_f8_r008_t1_metric_matrix_adapter_v2.py",
        "tests/test_f8_r008_t1_metric_adapter_v1.py",
        ARCHIVE_TEST_PATH,
    )
    review_modules = (matrix_core.metric_v1_review, matrix_core.metric_review_v2, matrix_core.table_review)
    receipt_paths = tuple(module.OUTPUT.relative_to(LAB).as_posix() for module in review_modules)
    frozen_paths = (
        metric_v1.FROZEN_SCOPE_RECEIPT.relative_to(LAB).as_posix(),
        metric_v1.FROZEN_PARAMETER_CONTRACT.relative_to(LAB).as_posix(),
        metric_v1.FROZEN_DEFINITION_PACK.relative_to(LAB).as_posix(),
        metric_v1.FROZEN_METRIC_PROPOSAL.relative_to(LAB).as_posix(),
        "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/t1-metric-semantics-proposal-v2/native-fluid-table-schema-v1.json",
        "repo:src/source/JSph.cpp",
    )
    evidence = [_file_binding(path) for path in (*code_paths, *test_paths, *receipt_paths, *frozen_paths)]
    evidence.append(_file_binding(Path(__file__).resolve().relative_to(LAB).as_posix()))
    if len({item["path"] for item in evidence}) != len(evidence):
        raise ValueError("matrix v3 review evidence inventory contains duplicate paths")

    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "status": "static_implementation_review_passed_no_execution_or_t1_credit",
        "reviewer": REVIEWER,
        "review_history": REVIEW_HISTORY,
        "reviewed_scope": {
            "frozen_case_denominator": 15,
            "cross_resolution_comparisons": 8,
            "source_content_recomputed_from_runparts": True,
            "diagnostic_input_policy": matrix_v4.runparts.INPUT_SCOPE,
            "all_26_fields_type_and_range_checked": True,
            "cross_field_native_semantics_verified": False,
            "execution_attempt_identity_verified": False,
            "runtime_configuration_verified": False,
            "normal_completion_verified": False,
            "native_integrity_or_final_T1_adjudication": False,
        },
        "findings": [
            {
                "topic": "bounded RunPARTs diagnostic input",
                "verdict": "PASS",
                "detail": "The selected fresh single-segment Part 0/time 0 policy is explicit, all 26 column values receive type/range checks, and restart/append data outside the policy fails closed. This does not prove an invocation followed the policy.",
            },
            {
                "topic": "15-case matrix and comparisons",
                "verdict": "PASS",
                "detail": "The shared core retains the exact frozen 15-case denominator, eight registered cross-resolution comparisons, and separate timestep/cadence gates; the RunPARTs diagnostic is recomputed from bounded source bytes.",
            },
            {
                "topic": "execution and qualification boundary",
                "verdict": "PASS",
                "detail": "Attempt/source identity, runtime configuration, cross-column runtime semantics, normal completion, timestep adjudication, readiness, and T1 remain unverified or false; aggregate pass is unreachable through this diagnostic path and credit remains zero.",
            },
        ],
        "known_limitations": [
            "The parser's fresh-segment input policy is not evidence that any actual solver invocation followed it; command, restart arguments, configuration, and attempt identity require an independent execution evidence chain.",
            "RunPARTs PART DtMax is a recorded interval diagnostic, not proof of the effective per-step maximum, full horizon, or normal solver termination; early stops and algorithm-specific recording semantics remain unresolved.",
            "All 26 fields are individually type/range checked, but cross-column count, allocation, or runtime accounting relationships are not verified.",
            "Timestep comparison, native-integrity adjudication, full T1, and qualification credit remain disabled; all tests use synthetic data.",
        ],
        "reviewer_validation": {
            "command": None,
            "passed": 0,
            "failed": 0,
            "fixture_scope": "reviewer did not run tests; parent validation recorded separately",
        },
        "parent_validation": {
            "command": "./.venv/bin/pytest -q tests/test_f8_r008_runparts_timestep_diagnostic_v1.py tests/test_f8_r008_runparts_timestep_diagnostic_v2.py tests/test_f8_r008_t1_metric_matrix_adapter_v2.py tests/test_f8_r008_t1_metric_adapter_v1.py",
            "passed": 145,
            "failed": 0,
            "fixture_scope": "synthetic CSV/results and temporary files only",
        },
        "review_boundary": REVIEW_BOUNDARY,
        "execution_authority": EXECUTION_AUTHORITY,
        "evidence": evidence,
    }


def verify_receipt(path: Path = OUTPUT) -> dict[str, Any]:
    receipt = json.loads(Path(path).read_text(encoding="utf-8"))
    if receipt != build_receipt():
        raise ValueError("immutable Terra High R008 v3 matrix review no longer matches reviewed evidence")
    return receipt


def write_receipt(path: Path = OUTPUT) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = LAB / target
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable F8 R008 v3 matrix review: {target}")
    payload = json.dumps(build_receipt(), indent=2, sort_keys=True, allow_nan=False) + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0), 0o644)
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
    parser.add_argument("--write", action="store_true", help="write the immutable Terra High receipt once")
    arguments = parser.parse_args()
    if arguments.write:
        print(write_receipt().relative_to(LAB))
    else:
        print(json.dumps(build_receipt(), indent=2, sort_keys=True))
