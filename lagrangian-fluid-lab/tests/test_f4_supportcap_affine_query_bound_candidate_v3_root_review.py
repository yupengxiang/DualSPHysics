"""Independent static regression for the Terra High F4 v3 root review.

This test is deliberately receipt-only.  It does not import a native reader,
start a solver, allocate a device, enqueue work, or mutate project state.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


LAB_ROOT = Path(__file__).resolve().parents[1]
RECEIPT_PATH = LAB_ROOT / (
    "campaigns/core-v1/material/candidates/"
    "f4-supportcap-affine-query-bound-v3/terra-high-root-review-v4.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_terra_high_review_is_hash_closed_and_denies_canary() -> None:
    receipt = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))

    assert receipt["reviewer"]["model"] == "gpt-5.6-terra"
    assert receipt["reviewer"]["reasoning_effort"] == "high"
    assert receipt["review_method"]["runtime_execution"] is False
    assert receipt["decision"] == (
        "STATIC_REVISION_ACCEPTED_FOR_FUTURE_ROOT_REVIEW__NO_CPU_AUTHORIZATION"
    )
    assert receipt["authorized_one_cpu_only"] is False
    assert receipt["qualification_claim"] == "none"
    assert receipt["credit"] == 0
    assert receipt["T1_numerical"] is False
    assert receipt["T2_macro"] is False
    assert receipt["T2_path"] is False

    for binding in receipt["hash_bindings"].values():
        path = LAB_ROOT / binding["path"]
        assert path.is_file(), binding["path"]
        assert _sha256(path) == binding["sha256"], binding["path"]

    assert len(receipt["resolved_prior_blockers"]) == 3
    assert receipt["remaining_boundary"]["one_cpu_canary"] == "not authorized"


def test_candidate_has_a_versioned_runtime_variant_without_execution_authority() -> None:
    candidate_id = "f4_supportcap_affine_query_bound_v3"
    core_material = (LAB_ROOT / "scripts/core_material.py").read_text(encoding="utf-8")
    candidate = (LAB_ROOT / "scripts/f4_supportcap_affine_query_bound_candidate_v3.py").read_text(
        encoding="utf-8"
    )

    assert candidate_id in candidate
    assert candidate_id in core_material
    assert '"native_started": False' in candidate
    assert '"solver_started": False' in candidate
    assert '"gpu_started": False' in candidate
