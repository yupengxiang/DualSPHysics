from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.f2_h2_mdbc_static_range_repair_contract_v1 import LAB, OUTPUT, REPORT, verify


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _contract() -> dict:
    return json.loads(OUTPUT.read_text(encoding="utf-8"))


def test_contract_is_hash_bound_to_v4_failure_and_v5_evidence() -> None:
    value = verify(OUTPUT)
    assert value["schema"] == "core.f2.h2_mdbc.static_range.repair_preflight_contract.v1"
    assert len(value["hash_bindings"]) == 9
    for item in value["hash_bindings"].values():
        path = LAB / item["path"]
        assert path.is_file(), item["path"]
        assert path.stat().st_size == item["bytes"]
        assert _sha256(path) == item["sha256"]


def test_retains_v4_cell11_failure_and_fixed_gate() -> None:
    value = _contract()
    retained = value["retained_failure"]
    assert retained["matrix_cell_count"] == 15
    assert retained["failed_cell_count"] == 1
    assert retained["failed_index"] == 11
    assert retained["failing_third_layer_error"] == 0.02806106870228997
    assert retained["source_gate"] == 0.025
    assert retained["total_gate"] == 0.03
    assert retained["mass_rescaling"] is False
    assert retained["same_input_retry"] is False
    assert retained["failure_remains_in_denominator"] is True


def test_selects_one_evidence_backed_hypothesis_and_v5_passes_cpu_native() -> None:
    value = _contract()
    proposal = value["proposal"]
    assert proposal["status"] == "hash_bound_candidate_proposal_with_historical_cpu_native_closure"
    assert proposal["new_input_identity"] is True
    assert proposal["old_v4_input_reused"] is False
    assert proposal["full_scope_materialized"] is True
    assert proposal["runtime_authorized"] is False
    assert proposal["qualification_credit"] == 0
    assert value["hypothesis_policy"]["maximum_hypothesis_classes"] == 2
    assert value["hypothesis_policy"]["selected_hypothesis_classes"] == 1
    hypothesis = value["repair_hypotheses"]
    assert len(hypothesis) == 1
    assert hypothesis[0]["hypothesis_id"] == "H2_v5_top_layer_lateral_lattice_balance"
    assert hypothesis[0]["independent_input_identity"] is True
    assert hypothesis[0]["old_third_layer_error"] > 0.025
    assert hypothesis[0]["predicted_third_layer_error"] < 0.025
    assert hypothesis[0]["observed_third_layer_error"] == 0.004152671755724757
    assert hypothesis[0]["observed_total_error"] < 0.03
    preflight = value["cpu_native_preflight_contract"]
    assert preflight["full_scope_rows"] == 15
    assert preflight["full_scope_preflight_passed"] == 15
    assert preflight["full_scope_failed"] == 0
    assert preflight["full_scope_unattempted"] == 0
    assert preflight["cell_11"]["preflight_pass"] is True
    assert preflight["cell_11"]["mass_rescaling"] is False
    assert preflight["qualification_credit"] == 0
    assert preflight["solver_product_present"] is False


def test_denominator_controls_and_core_gate_remain_closed() -> None:
    value = _contract()
    denominator = value["failure_denominator"]
    assert denominator["planned"] == 15
    assert denominator["qualification_numerator"] == 0
    assert denominator["parent_v4_failure_retained"] is True
    assert denominator["failed_rows_dropped"] is False
    assert denominator["survivor_renormalization"] is False
    assert denominator["threshold_relaxation"] is False
    assert denominator["same_input_retry"] is False
    controls = value["execution_controls"]
    assert controls["this_contract_runs_gencase"] is False
    assert controls["this_contract_runs_decoder"] is False
    assert controls["solver_invoked"] is False
    assert controls["gpu_invoked"] is False
    assert controls["queue_mutation"] == 0
    assert controls["ledger_mutation"] == 0
    assert controls["registry_mutation"] == 0
    assert controls["qualification_credit"] == 0
    gate = value["core_gate_effect"]
    assert gate["current_registered_t1_families"] == ["F3", "F4"]
    assert gate["third_t1_family_established"] is False
    assert gate["core_gate_changed"] is False
    assert "没有重跑同一输入" in REPORT.read_text(encoding="utf-8")
