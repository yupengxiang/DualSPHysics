from __future__ import annotations

import json
from pathlib import Path

from scripts.f2_submerged_orifice_preflight_v1 import (
    ANCHOR_DP,
    ANCHOR_INDEX,
    ANCHOR_Q,
    CASE_ID,
    ROOT_REVIEW_SCHEMA,
    verify_root_review,
)


LAB = Path(__file__).resolve().parents[1]
BASE = LAB / "campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1"
REVIEW = BASE / "root-review-cpu-preflight-v1.json"
PREFLIGHT = BASE / "anchor-q0p5-dp0p0075/preflight.json"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_root_review_rechecks_one_fresh_anchor_and_keeps_full_matrix():
    review = verify_root_review(REVIEW, BASE)
    assert review["schema"] == ROOT_REVIEW_SCHEMA
    assert review["authorized_matrix_indices"] == [ANCHOR_INDEX]
    assert review["authorized_case_ids"] == [CASE_ID]
    assert review["hash_bindings"]["authorized_row"] == {
        "index": ANCHOR_INDEX,
        "q": ANCHOR_Q,
        "dp_m": ANCHOR_DP,
        "orifice_height_m": 0.18,
        "case_id": CASE_ID,
    }
    assert review["hash_bindings"]["matrix"]["sha256"]
    assert review["hash_bindings"]["failure_denominator"]["sha256"]
    assert review["hash_bindings"]["lineage"]["sha256"]
    assert len(review["prior_failure_bindings"]) == 4
    auth = review["authorization"]
    assert auth["cpu_gencase"] is True
    assert auth["native_decode"] is True
    assert auth["solver_launch"] is False
    assert auth["gpu_launch"] is False
    assert auth["job_spec_creation"] is False
    assert auth["matrix_submission"] is False
    assert auth["queue_mutation"] == 0
    assert auth["ledger_mutation"] == 0
    assert auth["registry_mutation"] == 0


def test_failed_preflight_is_hard_noncredit_evidence_without_runtime_authority():
    preflight = _read(PREFLIGHT)
    assert preflight["status"] == "cpu_native_preflight_failed"
    assert preflight["preflight_pass"] is False
    assert preflight["qualified"] is False
    assert preflight["qualification_claim"] == "none"
    assert preflight["matrix_credit"] == 0
    assert preflight["authorized_matrix_index"] == ANCHOR_INDEX
    assert preflight["case_id"] == CASE_ID
    native = preflight["native_initial"]
    assert native["ids_unique"] is True
    assert native["arrays_finite"] is True
    assert native["fluid_ids_match_generated_xml"] is True
    assert native["wall_endpoint_outer_count"] == 0
    assert native["gate_endpoint_penetration_count"] == 0
    assert native["zero_boundary_normals"] > 0
    assert preflight["mass_contract"]["pass"] is True
    controls = preflight["execution_controls"]
    assert controls["cpu_gencase_invoked"] is True
    assert controls["cpu_native_decode_invoked"] is True
    assert controls["solver_invoked"] is False
    assert controls["gpu_invoked"] is False
    assert controls["queue_mutation"] == 0
    assert controls["ledger_mutation"] == 0
    assert controls["registry_mutation"] == 0
    assert controls["qualification_numerator_credit"] == 0
    assert preflight["solver_product_present"] is False


def test_preflight_artifact_records_native_generator_hard_failure():
    preflight = _read(PREFLIGHT)
    assert preflight["generated_counts"]["total_particles"] == (
        preflight["generated_counts"]["boundary_particles"]
        + preflight["generated_counts"]["fluid_particles"]
    )
    assert preflight["native_initial"]["normal_file_present"] is True
    assert preflight["native_initial"]["normal_count"] == preflight["generated_counts"]["boundary_particles"]
    log = Path(preflight["artifacts"]["gencase_log"]).read_text(encoding="utf-8")
    assert "Final zero normals:" in log
    assert "*** There are boundary particles without normal data." in log
    assert "Finished execution (code=0)." in log
