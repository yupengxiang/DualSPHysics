from __future__ import annotations

import hashlib
import json

from scripts.f4_ess32_root_review_v1 import LAB, OUTPUT, REPORT, verify


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _review() -> dict:
    return json.loads(OUTPUT.read_text(encoding="utf-8"))


def test_review_hash_binds_existing_contracts_and_code() -> None:
    value = verify(OUTPUT)
    bindings = value["hash_bindings"]
    assert len(bindings) == 9
    for item in bindings.values():
        path = LAB / item["path"]
        assert path.is_file(), item["path"]
        assert path.stat().st_size == item["bytes"]
        assert _sha(path) == item["sha256"]


def test_full_native_window_and_output_prefix_are_closed() -> None:
    value = _review()
    window = value["source_window_review"]
    assert window["source_exists"] is True
    assert window["hdf5_opened_by_this_review"] is False
    assert window["hdf5_rehashed_by_this_review"] is False
    assert window["frame_count"] == 1086
    assert window["particle_count"] == 217485
    assert window["time_end_s"] == 4.340002980805959
    assert window["native_rows_exact"] is True
    assert window["no_stride_or_synthetic_cadence"] is True
    closure = value["contract_hash_review"]
    assert closure["output_stem_is_absent"] is True
    assert all(item["exists"] is False for item in closure["planned_artifacts_absent"].values())
    assert closure["old_implementation_sha256_matches_contract"] is True


def test_zero_survivor_blocks_authorization_without_relaxing_gates() -> None:
    value = _review()
    decision = value["review_decision"]
    assert value["status"] == "proposal_only_blocked_by_zero_counterfactual_survivor"
    assert decision["candidate_id"] == "f4_ess32_v2"
    assert decision["authorized_one_cpu_only"] is False
    assert value["candidate_quality_contract"]["counterfactual_cohort_survivors"] == 0
    gates = value["fixed_zero_credit_rules"]
    assert gates["unknown_fraction_limit"] == 0.01
    assert gates["unknown_or_right_censored_is_unknown"] is True
    assert gates["no_partial_credit"] is True
    assert gates["cdf_changed"] is False
    assert gates["event_gate_changed"] is False
    assert gates["qualification_credit"] == "none"


def test_no_runtime_or_core_mutation_and_report_boundary() -> None:
    value = _review()
    constraints = value["execution_constraints"]
    assert constraints["read_only_json_review"] is True
    assert constraints["sidecar_started"] is False
    assert constraints["old_cfd_rerun"] is False
    assert constraints["solver_started"] is False
    assert constraints["gpu_started"] is False
    assert constraints["queue_mutation"] == 0
    assert constraints["matrix_mutation"] == 0
    assert constraints["registry_mutation"] == 0
    assert constraints["ledger_mutation"] == 0
    assert constraints["qualification_credit"] == 0
    assert constraints["core_gate_changed"] is False
    report = REPORT.read_text(encoding="utf-8")
    assert "proposal_only_blocked_by_zero_counterfactual_survivor" in report
    assert "authorized_one_cpu_only=false" in report
    assert "禁止 CFD/solver/GPU/queue/ledger/registry/matrix" in report
