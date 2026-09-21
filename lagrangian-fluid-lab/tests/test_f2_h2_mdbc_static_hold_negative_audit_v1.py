from __future__ import annotations

import hashlib
import json

from scripts.f2_h2_mdbc_static_hold_negative_audit_v1 import LAB, OUTPUT, REPORT, verify


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _contract() -> dict:
    return json.loads(OUTPUT.read_text(encoding="utf-8"))


def test_contract_hash_binds_all_small_sidecars_and_preserves_trajectory_receipts() -> None:
    value = verify(OUTPUT)
    bindings = value["hash_bindings"]
    assert len(bindings) >= 70
    assert sum(name.endswith("_observer") for name in bindings) == 8
    assert sum(name.endswith("_worker_audit") for name in bindings) == 8
    assert sum(name.endswith("_cpu_native_preflight") for name in bindings) == 8
    for item in bindings.values():
        path = LAB / item["path"]
        assert path.is_file(), item["path"]
        assert path.stat().st_size == item["bytes"]
        assert _sha256(path) == item["sha256"]
    trajectories = value["batch8_audit"]["trajectory_bindings"]
    assert len(trajectories) == 8
    assert all(
        item["hash_source"]
        == "existing observer sidecar; HDF5 not reopened or rehashed"
        for item in trajectories
    )


def test_batch8_negative_metrics_and_fixed_denominator_are_retained() -> None:
    value = _contract()
    summary = value["batch8_audit"]["common_failure_summary"]
    assert summary["rows"] == 8
    assert summary["static_speed_gate_false"] == 8
    assert summary["static_kinetic_gate_false"] == 8
    assert summary["no_open_cup_escape_false"] == 8
    assert summary["cup_retention_gate_true"] == 8
    assert summary["maximum_speed_p95_m_s"]["min"] > 1.5
    assert summary["maximum_kinetic_over_initial_potential"]["min"] > 0.30
    assert summary["maximum_outside_cup_mass_fraction"]["min"] > 0.019
    denominator = value["failure_denominator"]
    assert denominator["planned"] == 15
    assert denominator["attempted"] == 8
    assert denominator["scientific_failed"] == 8
    assert denominator["unattempted"] == 7
    assert denominator["failed_rows_dropped"] is False
    assert denominator["survivor_renormalization"] is False
    assert denominator["unknown_or_not_assessed_credit"] == 0


def test_input_closure_hypotheses_and_route_are_proposal_only() -> None:
    value = _contract()
    closure = value["cpu_native_input_closure"]
    assert len(closure["rows"]) == 8
    assert closure["all_native_initial_zero_velocity"] is True
    assert closure["all_zero_boundary_normals"] is True
    assert closure["all_mass_rescaling_false"] is True
    assert closure["trajectory_or_solver_checked"] is False
    assert value["hypothesis_policy"]["maximum_hypothesis_classes"] == 2
    assert value["hypothesis_policy"]["selected_hypothesis_classes"] == 2
    hypotheses = value["hypotheses"]
    assert len(hypotheses) == 2
    assert hypotheses[0]["authorization_now"] is False
    assert hypotheses[1]["authorization_now"] is False
    assert value["next_independent_route"]["proposal_only"] is True
    assert value["next_independent_route"]["authorized_now"] is False
    assert value["next_independent_route"]["matrix_credit"] == 0


def test_no_runtime_or_core_gate_mutation_and_report_is_explicit() -> None:
    value = _contract()
    controls = value["execution_controls"]
    assert controls["this_audit_reads_json_sidecars_only"] is True
    assert controls["trajectory_reopened"] is False
    assert controls["trajectory_rehashed"] is False
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
    report = REPORT.read_text(encoding="utf-8")
    assert "8/8 已执行行都是科学失败" in report
    assert "禁止重跑 batch8 同输入" in report
    assert "不改变 Core gate" in report
