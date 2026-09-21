from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.f2_submerged_orifice_scope_v1 import (
    DEFAULT_BASE,
    EXPECTED_ROWS,
    SCOPE_ID,
    verify_bundle,
    write_bundle,
)


LAB = Path(__file__).resolve().parents[1]
BASE = LAB / "campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1"


def test_new_f2_bundle_is_hash_bound_zero_credit_and_unattempted():
    report = verify_bundle(BASE)
    assert report["status"] == "root_review_only_contract_verified"
    assert report["scope_id"] == SCOPE_ID
    assert report["fixed_matrix"]["rows"] == EXPECTED_ROWS
    assert report["fixed_matrix"]["all_not_started"] is True
    assert report["failure_denominator"]["credit"] == 0
    assert report["prior_failure_count"] == 4
    assert report["execution_controls"] == {
        "solver": False,
        "gpu": False,
        "queue": 0,
        "ledger": 0,
        "registry": 0,
    }
    assert report["core_gate_effect"] == {
        "new_t1_family": False,
        "qualification_credit": 0,
        "core_can_finalize_changed": False,
    }


def test_orifice_contract_is_new_underflow_scene_without_old_assets():
    card = json.loads((BASE / "candidate-card-v1.json").read_text())
    contract = json.loads((BASE / "root-review-contract-v1.json").read_text())
    geometry = card["fixed_geometry"]
    assert geometry["submerged_aperture"]["top_mapping"] == "orifice_height_m = 0.10 + 0.16*q"
    assert geometry["upper_gate_slab"]["anchor_low_m"] == [0.72, 0.04, 0.18]
    assert geometry["upper_gate_slab"]["low_z_mapping"] == "z_low_m = orifice_height_m(q)"
    assert card["mechanism"]["class"] == "stationary_reservoir_submerged_orifice_transfer"
    assert card["lineage"]["source_reuse"] is False
    novelty = contract["novelty_review"]
    assert novelty["underflow_aperture_not_crest_overflow"] is True
    assert novelty["stationary_source_no_rotating_cup"] is True
    assert novelty["old_failed_inputs_reused"] is False
    assert novelty["old_failed_trajectory_reused"] is False


def test_contract_rejects_tampered_candidate_hash(tmp_path: Path):
    output = tmp_path / "scope"
    write_bundle(output)
    candidate = output / "candidate-card-v1.json"
    payload = json.loads(candidate.read_text())
    payload["mechanism"]["hypothesis"] += " tampered"
    candidate.write_text(json.dumps(payload, indent=2) + "\n")
    with pytest.raises(ValueError, match="candidate_card hash mismatch"):
        verify_bundle(output)


def test_contract_has_no_runtime_or_job_authority():
    contract = json.loads((BASE / "root-review-contract-v1.json").read_text())
    assert contract["authorized_anchor"] is False
    assert contract["authorized_runtime_preparation"] is False
    assert all(value is False for key, value in contract["authorization"].items() if key in {
        "cpu_gencase", "native_decode", "solver_launch", "gpu_launch", "job_spec_creation", "matrix_submission"
    })
    assert contract["authorization"]["queue_mutation"] == 0
    assert contract["authorization"]["ledger_mutation"] == 0
    assert contract["authorization"]["registry_mutation"] == 0
