#!/usr/bin/env python3
"""Archive Terra High's read-only PASS review of the static F8 R008 adapter.

This is a parent-authored transcription of the reviewer response, not a
reviewer-authored report. It records static implementation acceptance only.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB))

from scripts import f8_r008_t1_metric_adapter_v1 as adapter


ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008")
SCRIPT = Path(__file__).resolve().relative_to(LAB)
TEST = Path("tests/test_f8_r008_t1_metric_adapter_review_v1.py")
OUTPUT = LAB / ROOT / "t1-metric-adapter-review-v1/receipt.json"
SCHEMA = "core.cfd.f8.r008_t1_metric_adapter_review.v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def binding(path: Path, role: str) -> dict[str, Any]:
    absolute = (LAB / path).resolve()
    payload = absolute.read_bytes()
    return {
        "path": absolute.relative_to(LAB).as_posix(),
        "role": role,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def build_receipt() -> dict[str, Any]:
    adapter._assert_frozen_inputs()
    generation = adapter.verify_gencase_receipt(
        adapter.FROZEN_ANCHOR_PREFLIGHT, adapter.ANCHOR_CASE_ID,
    )
    evidence_paths = [
        (Path("scripts/f8_r008_t1_metric_adapter_v1.py"), "reviewed static F8 R008 metric adapter"),
        (Path("tests/test_f8_r008_t1_metric_adapter_v1.py"), "adapter identity, metric, provenance, and matrix tests"),
        (adapter.FROZEN_METRIC_PROPOSAL.relative_to(LAB), "adopted F8 R008 metric semantics proposal v2"),
        (adapter.FROZEN_METRIC_REVIEW.relative_to(LAB), "Terra High PASS review of metric semantics v2"),
        (adapter.FROZEN_DEFINITION_PACK.relative_to(LAB), "frozen R008 Definition bindings"),
        (adapter.FROZEN_WINDOW_PARSER.relative_to(LAB), "pinned native observation-window parser"),
        (adapter.FROZEN_WOMERSLEY_ORACLE.relative_to(LAB), "pinned Womersley reference oracle"),
        (adapter.FROZEN_ANCHOR_PREFLIGHT.relative_to(LAB), "pinned zero-credit R008 CPU/native anchor receipt"),
        (Path(generation["generated_xml"]["path"]).relative_to(LAB), "verified anchor generated XML"),
        (adapter.FROZEN_GENCASE_METRICS.relative_to(LAB), "pinned scoped GenCase wrapper metrics"),
        (adapter.FROZEN_GENCASE_BINARY.relative_to(LAB), "pinned GenCase executable"),
        (SCRIPT, "parent-authored archive of Terra High adapter review"),
        (TEST, "adapter review archive contract tests"),
    ]
    return {
        "schema": SCHEMA,
        "record_id": "f8-r008-t1-metric-adapter-review-v1",
        "scope_id": adapter.SCOPE_ID,
        "status": "independent_static_review_passed_no_execution",
        "reviewer": {
            "model": "gpt-5.6-terra",
            "reasoning_effort": "high",
            "agent_id": "01a0d12c-53fc-7840-b965-a0982d69c4f0",
            "verdict": "PASS",
            "review_mode": "read_only_static_code_and_sha256_review",
            "reviewer_ran_pytest": True,
            "review_thread_note": "Follow-up review in the same Terra High agent thread as the prior adapter reviews; not represented as a newly spawned second reviewer.",
            "archive_note": "Parent-authored transcription of the reviewer response; not represented as reviewer-authored content.",
        },
        "reviewer_validation": {
            "adapter_tests": {"command": "PYTHONPATH=. .venv/bin/pytest -q tests/test_f8_r008_t1_metric_adapter_v1.py", "passed": 18, "failed": 0},
            "archive_tests": {"command": "PYTHONPATH=. .venv/bin/pytest -q tests/test_f8_r008_t1_metric_adapter_review_v1.py", "passed": 4, "failed": 0},
        },
        "parent_validation": {
            "command": "PYTHONPATH=. .venv/bin/pytest -q tests/test_f8_r008_t1_metric_adapter_v1.py",
            "passed": 18,
            "failed": 0,
        },
        "findings": [
            {
                "topic": "frozen input trust anchors",
                "verdict": "PASS",
                "basis": "scope, parameter contract, Definition pack, metric proposal/review, anchor receipt, wrapper metrics, and GenCase binary are pinned and checked before trusted metric paths",
            },
            {
                "topic": "anchor GenCase provenance",
                "verdict": "PASS",
                "basis": "only the exact anchor receipt is accepted; Definition, XML cohorts/hash, executable, argv, wrapper metrics, zero exit, no timeout, clean process tree, and fixed zero-credit controls are checked",
            },
            {
                "topic": "case table and matrix recomputation",
                "verdict": "PASS",
                "basis": "frozen H/dp, exact 15-row scope, provenance-bound HDF5 reread, case metric recomputation, frozen comparisons, and safety-field equality are enforced",
            },
            {
                "topic": "metric and qualification boundary",
                "verdict": "PASS",
                "basis": "fixed-frequency coefficients, exact 3N+1 cycle seams, mass-weighted RMS, cross-resolution interpolation, false full-T1 decision, zero credit, and no execution authority remain intact",
            },
        ],
        "remaining_limitations": [
            "No reviewed per-case materialization receipt verifier is implemented; all such receipts fail closed.",
            "No complete provenance-verified 15-row solver result matrix exists; adapter PASS is not T1 qualification.",
        ],
        "disposition": {
            "static_adapter_accepted": True,
            "next_permitted_work": "design and independently review a per-case materialization provenance verifier; keep solver, worker, GPU, and queue execution behind separate gates",
            "qualification_credit": 0,
            "solver_or_worker_authorized": False,
            "gpu_or_queue_authorized": False,
        },
        "qualification_credit": 0,
        "execution_authority": {
            "solver": False,
            "gpu": False,
            "worker": False,
            "queue": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
        },
        "evidence": [binding(path, role) for path, role in evidence_paths],
    }


def verify_receipt(path: Path = OUTPUT) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if value.get("schema") != SCHEMA or value != build_receipt():
        raise ValueError("F8 R008 adapter review receipt no longer matches reviewed evidence")
    return value


def write_receipt(path: Path = OUTPUT) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = LAB / target
    payload = json.dumps(build_receipt(), indent=2, sort_keys=True, allow_nan=False) + "\n"
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable F8 R008 adapter review receipt: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
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
    arguments = parser.parse_args()
    if arguments.write:
        print(write_receipt().relative_to(LAB))
    else:
        print(json.dumps(build_receipt(), indent=2, sort_keys=True))
