#!/usr/bin/env python3
"""Archive Terra High's read-only v2 review and freeze semantics for implementation.

The reviewer verdict is transcribed from the independent subagent response in
this task. This receipt authorizes only static implementation work, not runtime.
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

from scripts import f8_r008_t1_metric_semantics_proposal_v2 as proposal

ROOT = proposal.ROOT
SCRIPT = Path(__file__).resolve().relative_to(LAB)
TEST = Path("tests/test_f8_r008_t1_metric_semantics_review_v2.py")
RECEIPT = ROOT / "t1-metric-semantics-review-v2/receipt.json"
OUTPUT = LAB / RECEIPT
SCHEMA = "core.cfd.f8.r008_t1_metric_semantics_review.v2"


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def binding(path: Path, role: str) -> dict[str, Any]:
    absolute = (LAB / path).resolve()
    return {
        "path": absolute.relative_to(LAB).as_posix(),
        "role": role,
        "bytes": absolute.stat().st_size,
        "sha256": sha256(absolute),
    }


def build_receipt() -> dict[str, Any]:
    reviewed = proposal.verify_proposal(LAB / proposal.OUTPUT)
    evidence_paths = [
        (proposal.ROOT / "t1-metric-semantics-proposal-v2/receipt.json", "reviewed immutable F8 R008 metric proposal v2"),
        (proposal.NATIVE_SCHEMA, "reviewed F8 native fluid-frame table schema"),
        (Path("scripts/f8_observation_parser_v1.py"), "fixed-frequency harmonic fit inspected by reviewer"),
        (Path("scripts/f8_observation_window_parser_v2.py"), "native closed-window selector inspected by reviewer"),
        (Path("scripts/core_cfd.py"), "generic converter behavior inspected by reviewer"),
        (SCRIPT, "parent-authored independent-review archive and static adoption decision"),
        (TEST, "review archive contract tests"),
    ]
    return {
        "schema": SCHEMA,
        "record_id": "f8-r008-t1-metric-semantics-review-v2",
        "scope_id": reviewed["scope_id"],
        "status": "independent_review_passed_static_semantics_frozen",
        "reviewer": {
            "model": "gpt-5.6-terra",
            "reasoning_effort": "high",
            "agent_id": "01a0d0f3-a5bc-7640-a4fe-545cdcee80a3",
            "verdict": "PASS",
            "review_mode": "read_only_static_design_review",
            "review_archive_note": "This receipt is a parent-authored transcription of the independent reviewer response; it is not represented as a reviewer-authored artifact.",
        },
        "reviewed_proposal": {
            "record_id": reviewed["record_id"],
            "receipt_path": proposal.OUTPUT.relative_to(LAB).as_posix(),
            "receipt_sha256": sha256(LAB / proposal.OUTPUT),
            "verified_bound_evidence_count": 82,
            "all_bound_evidence_hashes_and_sizes_match": True,
        },
        "findings": [
            {
                "finding": "fixed-frequency coefficient convention and cross-grid phasor interpolation",
                "severity": None,
                "verdict": "PASS",
                "basis": "mean + a*sin(omega*t) + b*cos(omega*t), amplitude hypot(a,b), phase atan2(b,a), with interpolation of a/b only; the existing parser's limited output is accurately disclosed",
            },
            {
                "finding": "strict native fluid cohort and frame-value contract",
                "severity": None,
                "verdict": "PASS",
                "basis": "schema requires exact raw ID membership before fluid projection, rejects missing/duplicate/unknown/unclassified IDs, and gates finite positions/velocities plus positive invariant per-ID mass; generic converter disclaimer is accurate",
            },
            {
                "finding": "three-cycle inclusive seam partition",
                "severity": None,
                "verdict": "PASS",
                "basis": "exactly 3N+1 rows partition into inclusive 0..N, N..2N, and 2N..3N slices; each integrates one period independently with shared seam endpoints",
            },
            {
                "finding": "scope, frozen gates, and execution boundary",
                "severity": None,
                "verdict": "PASS",
                "basis": "15 rows, 8 cross-resolution pairs, windows, thresholds, failure denominator, and zero solver/GPU/worker/queue authority are unchanged",
            },
        ],
        "disposition": {
            "additive_semantics_contract": "frozen_for_static_implementation",
            "scope_inputs_or_thresholds_changed": False,
            "solver_or_worker_authorized": False,
            "gpu_or_queue_authorized": False,
            "qualification_credit": 0,
            "next_permitted_work": "implement and statically test the F8 R008 metric adapter and strict native-frame validation; keep all runtime execution behind its separate resource and execution gates",
        },
        "execution_authority": reviewed["execution_authority"],
        "qualification_credit": 0,
        "evidence": [binding(path, role) for path, role in evidence_paths],
    }


def verify_receipt(path: Path = OUTPUT) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if value.get("schema") != SCHEMA or value != build_receipt():
        raise ValueError("F8 R008 Terra High review receipt no longer matches reviewed evidence")
    return value


def write_receipt(path: Path = OUTPUT) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = LAB / target
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable F8 R008 metric review receipt: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(build_receipt(), indent=2, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
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
