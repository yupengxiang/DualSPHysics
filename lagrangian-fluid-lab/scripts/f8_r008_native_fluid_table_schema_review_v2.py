#!/usr/bin/env python3
"""Archive Terra High's read-only review of the R008 native-table v2 verifier."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

LAB = Path(__file__).resolve().parents[1]
ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/native-fluid-table-schema-v2")
OUTPUT = LAB / ROOT / "design-review-v2/receipt.json"
SCHEMA_PATH = ROOT / "schema.json"
PROPOSAL_PATH = ROOT / "proposal.json"
V1_SCHEMA_PATH = Path(
    "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/"
    "t1-metric-semantics-proposal-v2/native-fluid-table-schema-v1.json"
)
SCRIPT_PATH = Path("scripts/f8_r008_native_fluid_table_v2.py")
SCHEMA_TEST_PATH = Path("tests/test_f8_r008_native_fluid_table_schema_v2.py")
IMPLEMENTATION_TEST_PATH = Path("tests/test_f8_r008_native_fluid_table_v2.py")
ARCHIVE_SCRIPT_PATH = Path(__file__).resolve().relative_to(LAB)
ARCHIVE_TEST_PATH = Path("tests/test_f8_r008_native_fluid_table_schema_review_v2.py")
SCHEMA_ID = "core.cfd.f8.r008_native_fluid_table_schema_implementation_review.v2"
V1_SCHEMA_SHA256 = "2258f903146ee1e0a2b09b616864b770d928270818128826b327aeb625e7a8a8"
REVIEWER = {
    "model": "gpt-5.6-terra",
    "reasoning_effort": "high",
    "agent_id": "01a0d297-70b1-79b3-b4ba-40c479490929",
    "verdict": "PASS",
    "review_mode": "read_only_static_implementation_review",
    "reviewer_ran_tests": False,
    "execution_or_evidence_mutation": False,
}
REVIEW_BOUNDARY = {
    "production_bundle_read": False,
    "gencase_invoked": False,
    "native_decoder_invoked": False,
    "solver_or_worker_invoked": False,
    "gpu_or_queue_invoked": False,
    "registry_or_ledger_mutated": False,
    "qualification_credit": 0,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _binding(path: Path, role: str) -> dict[str, Any]:
    absolute = LAB / path
    payload = absolute.read_bytes()
    return {
        "path": path.as_posix(),
        "role": role,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def build_receipt() -> dict[str, Any]:
    schema = json.loads((LAB / SCHEMA_PATH).read_text(encoding="utf-8"))
    proposal = json.loads((LAB / PROPOSAL_PATH).read_text(encoding="utf-8"))
    v1_hash = _sha256(LAB / V1_SCHEMA_PATH)
    if v1_hash != V1_SCHEMA_SHA256:
        raise ValueError("reviewed native fluid-table v1 schema changed")
    if (schema.get("schema") != "core.cfd.f8.r008_native_fluid_frame_table.v2"
            or schema.get("status") != "static_design_review_passed_implementation_only"
            or proposal.get("status") != "static_design_review_passed_implementation_only"
            or proposal.get("design_review_receipt_path") != OUTPUT.relative_to(LAB).as_posix()
            or proposal.get("predecessor", {}).get("sha256") != v1_hash
            or proposal.get("predecessor", {}).get("preserved_unchanged") is not True):
        raise ValueError("v2 schema/proposal status or predecessor binding changed")

    evidence = [
        _binding(SCHEMA_PATH, "reviewed additive v2 HDF5 table contract"),
        _binding(PROPOSAL_PATH, "reviewed proposal and unchanged scientific/execution gates"),
        _binding(V1_SCHEMA_PATH, "unchanged historical v1 schema"),
        _binding(SCRIPT_PATH, "reviewed standalone bounded native-table semantic verifier"),
        _binding(SCHEMA_TEST_PATH, "v2 contract and v1-preservation tests"),
        _binding(IMPLEMENTATION_TEST_PATH, "synthetic BI4/HDF5 semantic and adversarial regression tests"),
        _binding(ARCHIVE_SCRIPT_PATH, "parent-authored immutable review archive builder"),
        _binding(ARCHIVE_TEST_PATH, "review archive integrity tests"),
    ]
    return {
        "schema": SCHEMA_ID,
        "record_id": "f8-r008-native-fluid-table-schema-implementation-review-v2",
        "status": "static_implementation_review_passed_no_execution_or_t1_credit",
        "reviewer": REVIEWER,
        "reviewed_scope": {
            "table_schema": schema["schema"],
            "standalone_semantic_verifier": True,
            "verified_B_C_D_bundle_orchestration": False,
            "solver_or_T1_adjudication": False,
        },
        "findings": [
            {
                "topic": "fixed root attributes",
                "verdict": "PASS",
                "detail": "The verifier rebuilds the full canonical root-attribute mapping, so caller-supplied expectations cannot override fixed schema/version/semantics/status fields.",
            },
            {
                "topic": "HDF5 root-link closure",
                "verdict": "PASS",
                "detail": "Exactly seven direct links are required; all seven registered names must resolve to unique hard-linked datasets. This proves exact closure without allocating unknown attacker-sized names.",
            },
            {
                "topic": "boolean enum values",
                "verdict": "PASS",
                "detail": "The enum type is checked and the raw uint8 representation is read without bool coercion; conversion_complete and every valid cell must equal one exactly.",
            },
            {
                "topic": "source projection and rounding",
                "verdict": "PASS",
                "detail": "Synthetic regression covers both Posd float64 and Pos float32 promotion, plus roundTiesToEven midpoint cases for MassFluid conversion.",
            },
            {
                "topic": "bounded attributes and datasets",
                "verdict": "PASS",
                "detail": "The contract and implementation agree on fixed-length bounded UTF-8 attributes, complete dimensions, one LZF chunk per time row, HDF5 storage classes, and the 45-byte per-cell logical-size formula.",
            },
        ],
        "known_boundary": "Callers must first verify B/C/D provenance and supply hash-bound source frames and expected provenance attributes; this receipt does not certify that orchestration or any production bundle.",
        "parent_validation": {
            "command": "./.venv/bin/python -m pytest -q tests/test_f8_r008_native_fluid_table_schema_v2.py tests/test_f8_r008_native_fluid_table_v2.py",
            "passed": 32,
            "failed": 0,
            "reviewer_ran_tests": False,
            "fixture_scope": "temporary synthetic BI4/HDF5 only",
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
        "evidence": evidence,
    }


def verify_receipt(path: Path = OUTPUT) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if value != build_receipt():
        raise ValueError("native fluid-table schema review receipt no longer matches reviewed evidence")
    return value


def write_receipt(path: Path = OUTPUT) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = LAB / target
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable native fluid-table review: {target}")
    payload = json.dumps(build_receipt(), indent=2, sort_keys=True, allow_nan=False) + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        target,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o644,
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
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
