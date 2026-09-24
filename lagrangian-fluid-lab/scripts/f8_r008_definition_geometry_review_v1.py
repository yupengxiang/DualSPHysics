#!/usr/bin/env python3
"""Archive Terra High's static review of F8 R008 Definition geometry."""
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
from scripts import f8_r008_definition_geometry_audit_v1 as audit


ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008")
OUTPUT = LAB / ROOT / "definition-geometry-audit-v1/receipt.json"
SCHEMA = "core.cfd.f8.r008_definition_geometry_static_review.v1"
RECORD_ID = "f8-r008-definition-geometry-static-review-v1"
REVIEWER = {
    "model": "gpt-5.6-terra",
    "reasoning_effort": "high",
    "agent_id": "01a0d2cf-4c87-73d1-8269-3e54aead560e",
    "verdict": "PASS",
    "review_mode": "read_only_static_implementation_review",
    "reviewer_ran_tests": True,
    "reviewer_test_summary": "11 passed",
    "execution_or_evidence_mutation": False,
}
REVIEW_BOUNDARY = {
    "frozen_static_definition_inputs_read": True,
    "production_bundle_read": False,
    "solver_frame_read": False,
    "gencase_invoked": False,
    "native_decoder_invoked": False,
    "solver_or_worker_invoked": False,
    "gpu_or_queue_invoked": False,
    "registry_or_ledger_mutated": False,
    "qualification_credit": 0,
}
EVIDENCE_PATHS = (
    "scripts/f8_r008_definition_geometry_audit_v1.py",
    "tests/test_f8_r008_definition_geometry_audit_v1.py",
    "scripts/f8_r008_definition_control_pack_v1.py",
    "tests/test_f8_r008_definition_control_pack_v1.py",
    "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/definition-control-pack-v1/receipt.json",
    "scripts/f8_t1_scope_design_v1.py",
    "tests/test_f8_t1_scope_design_v1.py",
    "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/t1-scope-design-v1/receipt.json",
    "scripts/f8_input_materialization_v1.py",
    "scripts/f8_r006_static_design_review_v1.py",
    "tests/test_f8_r006_static_design_review_v1.py",
    "scripts/f8_r007_static_design_review_v1.py",
    "tests/test_f8_r007_static_design_review_v1.py",
    "scripts/f8_r008_per_case_bundle_verifier_v1.py",
    "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/per-case-provenance-implementation-review-v2/receipt.json",
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
        identity = lambda item: (
            item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns, item.st_nlink,
        )
        if identity(before) != identity(after) or identity(after) != identity(named) or size != before.st_size:
            raise ValueError(f"review evidence changed while binding: {relative_path}")
        return {"path": relative_path, "bytes": size, "sha256": digest.hexdigest()}
    finally:
        os.close(fd)


def build_receipt() -> dict[str, Any]:
    geometry = audit.audit_frozen_geometry_pack()
    dp_counts: dict[str, int] = {}
    for case in geometry["case_summaries"]:
        label = f"{case['dp_m']:.4f}"
        dp_counts[label] = dp_counts.get(label, 0) + 1
    if geometry["definition_count"] != 47 or dp_counts != {"0.0060": 5, "0.0075": 39, "0.0090": 3}:
        raise ValueError("frozen geometry audit lost its expected 15+32 case or dp distribution")
    if geometry["native_normal_vectors_verified"] or geometry["native_geometry_generated"]:
        raise ValueError("static geometry audit unexpectedly claims native runtime evidence")
    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "status": "static_definition_geometry_passed_runtime_geometry_unverified",
        "reviewer": REVIEWER,
        "reviewed_scope": {
            "all_47_frozen_definition_geometries": True,
            "frozen_scope_and_xyperiodic_presence_semantics": True,
            "domain_wall_fluid_and_support_formulas": True,
            "generated_particle_counts_or_runtime_boundnor_vectors": False,
            "solver_or_T1_adjudication": False,
        },
        "dp_distribution_m": dp_counts,
        "static_audit": geometry,
        "known_boundary": "The receipt proves hash-bound static XML declarations and recomputed geometry formulas only. It does not prove generated particle counts, hdp mesh coordinates, BoundNor coverage/direction/magnitude, solver behavior, readiness, or T1 qualification.",
        "parent_validation": {
            "command": "./.venv/bin/python -m pytest -q tests/test_f8_r008_definition_geometry_audit_v1.py tests/test_f8_r008_definition_control_pack_v1.py tests/test_f8_r008_per_case_bundle_verifier_v1.py",
            "passed": 71,
            "failed": 0,
            "fixture_scope": "47 frozen static Definition XMLs plus synthetic mutation fixtures; no runtime geometry outputs",
        },
        "review_boundary": REVIEW_BOUNDARY,
        "execution_authority": {
            "gencase": False,
            "native_decoder": False,
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
        raise ValueError("immutable R008 Definition geometry review no longer matches its evidence")
    return value


def write_receipt(path: Path = OUTPUT) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = LAB / target
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable Definition geometry review: {target}")
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
