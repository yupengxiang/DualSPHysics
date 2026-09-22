#!/usr/bin/env python3
"""Write immutable v4 static receipts for the F4 support-cap candidate.

This builder hashes only source text and existing JSON receipts.  It has no
native reader, solver, GPU, queue, registry, or ledger entry point.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.f4_supportcap_affine_query_bound_candidate_v3 import candidate_spec


ROOT = Path("campaigns/core-v1/material/candidates/f4-supportcap-affine-query-bound-v3")
CARD_NAME = "candidate-card-v3.json"
REVIEW_NAME = "terra-high-root-review-v4.json"


def _binding(lab_root: Path, path: str, role: str | None = None) -> dict[str, str]:
    source = lab_root / path
    item = {"path": path, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    if role is not None:
        item["role"] = role
    return item


def build_card(lab_root: Path) -> dict[str, Any]:
    spec = candidate_spec()
    return {
        "schema": "core.material.f4.reconstruction_candidate_card.v4",
        "candidate_id": spec["candidate_id"],
        "revision": "v3-reliability-censoring-hash-closure-20260923",
        "scope_id": "F4_resting_pool_laminar_tallwall120_x_v1",
        "family": "F4",
        "status": "proposal_only_root_review_required",
        "purpose": "versioned static hash closure after reliability-censoring semantics changed",
        "mechanism": {"backend": spec["backend"], "support_cap": spec["mechanisms"][0]["neighbours"],
                      "error_estimator": spec["mechanisms"][1]["error_estimator"],
                      "maximum_support_distance_m": spec["maximum_support_distance_m"]},
        "fixed_gate": {**spec["fixed_gate"], "unknown_fraction_limit": 0.01},
        "qualification_claim": "none", "credit": 0, "T1_numerical": False,
        "T2_macro": False, "T2_path": False, "root_review_only": True,
        "authorized_one_cpu_only": False,
        "execution_policy": {"synthetic_regression_only": True, "native_started": False,
                             "gencase_started": False, "solver_started": False, "gpu_started": False,
                             "queue_mutation": 0, "registry_mutation": 0, "ledger_mutation": 0,
                             "historical_receipts_overwritten": False},
        "input_bindings": {
            "core_material": _binding(lab_root, "scripts/core_material.py", "registered candidate and event implementation"),
            "implementation": _binding(lab_root, "scripts/f4_supportcap_affine_query_bound_candidate_v3.py", "array-only candidate wrapper"),
            "synthetic_tests": _binding(lab_root, "tests/test_f4_supportcap_affine_query_bound_candidate_v3_revision2.py", "static integration and hash-closure regression"),
            "calibration_script": _binding(lab_root, "scripts/f4_material_calibration_v3.py", "held-out synthetic calibration"),
        },
        "historical_receipts_preserved": ["candidate-card-v1.json", "candidate-card-v2.json", "terra-high-root-review-v2.json", "terra-high-root-review-v3.json"],
    }


def build_review(lab_root: Path, card_path: str) -> dict[str, Any]:
    bindings = {
        "candidate_card_v3": _binding(lab_root, card_path),
        "implementation": _binding(lab_root, "scripts/f4_supportcap_affine_query_bound_candidate_v3.py"),
        "core_material": _binding(lab_root, "scripts/core_material.py"),
        "calibration_script": _binding(lab_root, "scripts/f4_material_calibration_v3.py"),
        "calibration_design": _binding(lab_root, "campaigns/core-v1/material/evidence/f4-reconstruction-calibration-v3-20260922-design.json"),
        "calibration_receipt": _binding(lab_root, "campaigns/core-v1/material/evidence/f4-reconstruction-calibration-v3-20260922-result.json"),
        "synthetic_tests": _binding(lab_root, "tests/test_f4_supportcap_affine_query_bound_candidate_v3_revision2.py"),
    }
    return {
        "schema": "core.material.f4.reconstruction_candidate.terra_high_root_review.v4",
        "record_id": "f4-supportcap-affine-query-bound-v3-terra-high-root-review-20260923-v4",
        "reviewer": {"model": "gpt-5.6-terra", "reasoning_effort": "high", "role": "independent Terra High static root reviewer"},
        "review_scope": {"candidate_id": "f4_supportcap_affine_query_bound_v3", "revision": "candidate-card-v3",
                         "scope_id": "F4_resting_pool_laminar_tallwall120_x_v1", "historical_receipts_modified": False},
        "review_method": {"static_only": True, "synthetic_array_validation": True, "runtime_execution": False,
                          "native_started": False, "gencase_started": False, "solver_started": False, "gpu_started": False,
                          "queue_mutation": 0, "registry_mutation": 0, "ledger_mutation": 0,
                          "historical_receipts_overwritten": False},
        "decision": "STATIC_REVISION_ACCEPTED_FOR_FUTURE_ROOT_REVIEW__NO_CPU_AUTHORIZATION",
        "status": "static_review_completed_canary_denied", "authorized_one_cpu_only": False,
        "formal_scientific_admission": False, "qualification_claim": "none", "credit": 0,
        "T1_numerical": False, "T2_macro": False, "T2_path": False,
        "resolved_prior_blockers": ["registered variant remains trace-bound", "current reliability-censoring source hash is closed", "held-out synthetic calibration remains provenance-only"],
        "remaining_boundary": {"one_cpu_canary": "not authorized", "full_source_sidecar": False, "gpu": False,
                               "queue": False, "registry": False, "ledger": False, "T2_remains_false": True,
                               "next_required_review": "separate root authorization before any native CPU canary"},
        "hash_bindings": bindings,
    }


def write_artifacts(lab_root: Path, card: Path, review: Path) -> None:
    if card.exists() or review.exists():
        raise FileExistsError("refusing to overwrite historical candidate receipts")
    value = build_card(lab_root)
    card.parent.mkdir(parents=True, exist_ok=True)
    card.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    review.write_text(json.dumps(build_review(lab_root, str(card.relative_to(lab_root))), indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    lab = Path(__file__).resolve().parents[1]
    parser.add_argument("--lab-root", type=Path, default=lab)
    parser.add_argument("--card", type=Path, default=lab / ROOT / CARD_NAME)
    parser.add_argument("--review", type=Path, default=lab / ROOT / REVIEW_NAME)
    args = parser.parse_args(argv)
    write_artifacts(args.lab_root.resolve(), args.card.resolve(), args.review.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
