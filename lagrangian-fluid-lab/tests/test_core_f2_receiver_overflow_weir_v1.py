import json
from pathlib import Path

import numpy as np
import pytest

from scripts.core_f2_receiver_overflow_weir_v1 import (
    evaluate_event,
    crest_crossing_mass_fraction,
    receiver_contact_mass_fraction,
    verify_candidate_bundle,
)


LAB = Path(__file__).resolve().parents[1]
BASE = LAB / "campaigns/core-v1/cfd/f2-receiver-overflow-weir-scope-v1"


def test_adapter_closes_hash_bound_zero_credit_contract():
    evidence = verify_candidate_bundle(BASE)
    assert evidence["schema"] == "core.f2.receiver_overflow_weir.adapter_contract.v1"
    assert evidence["status"] == "adapter_contract_only_root_review_required"
    assert evidence["candidate"]["matrix_rows"] == 15
    assert evidence["candidate"]["matrix_credit"] == 0
    assert evidence["native_anchor"]["zero_normals"] == 0
    assert evidence["execution_controls"]["solver_invoked"] is False
    assert evidence["execution_controls"]["queue_mutation"] == 0
    assert evidence["root_review"]["submit_allowed"] is False


def test_adapter_contract_root_review_does_not_authorize_runtime():
    review = json.loads((BASE / "root-review-adapter-contract-v1.json").read_text())
    assert review["decision"] == "approved_for_adapter_contract_only"
    assert review["qualification_claim"] == "none"
    assert review["matrix_credit"] == 0
    assert review["authorized_anchor"] is False
    assert review["authorized_runtime_preparation"] is False
    assert review["authorization"]["solver_launch"] is False
    assert review["authorization"]["gpu_launch"] is False
    assert review["authorization"]["queue_mutation"] == 0
    assert review["authorization"]["ledger_mutation"] == 0
    assert review["authorization"]["registry_mutation"] == 0
    assert review["findings"]["pure_observer_contract_reviewed"] is True
    assert review["findings"]["physical_trajectory_observed"] is False


def test_event_observer_detects_crossing_and_sustained_contact_without_future_state():
    masses = np.ones(2)
    previous = np.array([[0.70, 0.10, 0.30], [0.70, 0.20, 0.30]])
    current = np.array([[0.80, 0.10, 0.27], [0.80, 0.20, 0.27]])
    crossing = crest_crossing_mass_fraction(previous, current, masses, 0.26)
    assert crossing["crossed_particle_count"] == 2
    assert crossing["mass_fraction"] == pytest.approx(1.0)
    contact = receiver_contact_mass_fraction(current, masses)
    assert contact["contact_particle_count"] == 2
    assert contact["mass_fraction"] == pytest.approx(1.0)

    frames = np.stack([previous, current, current, current])
    event = evaluate_event(frames, [0.0, 0.10, 0.21, 0.31], masses, 0.26)
    assert event["crest_crossing"]["frame_index"] == 1
    assert event["receiver_contact"]["frame_index"] == 1
    assert event["max_sustained_receiver_contact_s"] == pytest.approx(0.21)
    assert event["event_complete"] is True


def test_adapter_rejects_changed_fixed_row(tmp_path):
    source = BASE / "fixed-matrix-v1.json"
    changed = tmp_path / source.name
    payload = json.loads(source.read_text())
    payload["rows"][0]["status"] = "passed"
    changed.write_text(json.dumps(payload))
    # The bundle verifier uses the fixed path and its hash binding.  Tampering
    # the bound file itself must be rejected before any observer can run.
    original = source.read_text()
    try:
        source.write_text(changed.read_text())
        with pytest.raises(ValueError, match="fixed matrix contains an executed row"):
            verify_candidate_bundle(BASE)
    finally:
        source.write_text(original)
