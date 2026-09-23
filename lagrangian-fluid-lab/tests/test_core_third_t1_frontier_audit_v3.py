from __future__ import annotations

import json

from scripts.core_third_t1_frontier_audit_v3 import OUTPUT, build_audit


def test_user_selected_f8_is_a_candidate_not_a_qualified_third_family():
    value = build_audit()

    assert value["schema"] == "core.third_t1.frontier_audit.v3"
    assert value["status"] == "user_selected_candidate_pending_one_shot_preflight_and_t1_qualification"
    assert value["current_t1_families"] == ["F3", "F4"]
    assert value["third_family_established"] is False
    assert value["qualification_credit"] == 0
    assert value["decision_source"]["denominator_eligible_before_t1_qualification"] is False
    assert "Accept the fully filled, body-force-driven oscillatory channel" in value["decision_source"]["user_statement"]

    f8 = value["route_decisions"]["F8"]
    assert f8["route_selected_by_user"] is True
    assert f8["scope_id"] == "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008"
    assert f8["cpu_native_preflight_authorized"] is True
    assert f8["cpu_native_preflight_status"] == "authorized_for_exactly_one_r008_cpu_native_preflight"
    assert f8["solver_t1_execution_authorized"] is False
    assert f8["t1_qualification"] is False
    assert f8["qualification_credit"] == 0
    assert "F3 worker absence" in f8["live_gate"]

    controls = value["execution_controls"]
    assert controls["gencase_invoked"] is False
    assert controls["native_decode_invoked"] is False
    assert controls["solver_invoked"] is False
    assert controls["worker_started"] is False
    assert controls["registry_mutation"] == 0
    assert controls["denominator_mutation"] == 0
    assert controls["qualification_credit"] == 0


def test_frontier_v3_is_hash_bound_and_committed_output_matches_builder():
    assert OUTPUT.is_file()
    generated = json.loads(OUTPUT.read_text(encoding="utf-8"))
    rebuilt = build_audit()
    assert generated["schema"] == "core.third_t1.frontier_audit.v3"
    assert generated["route_decisions"]["F8"] == rebuilt["route_decisions"]["F8"]
    assert generated["evidence"][-1]["role"] == "v3 frontier audit writer"
    assert generated["evidence"][-1]["sha256"]
    assert generated["evidence"][-1]["bytes"] > 0

    expected_roles = {
        "user-accepted F8 mechanism-family ruling; no T1/denominator eligibility",
        "fresh R008 frozen T1 scope design",
        "independent R008 T1 design review",
        "R008 independent static review; CPU/native preflight only",
        "R008 conditional resource-admission decision",
        "R008 v3 request-only CPU/native preflight request",
        "R008 exact one-shot CPU/native preflight authorization",
        "latest bound status: preflight deferred by live resource gates; no runtime namespace or consumed lock",
    }
    observed_roles = {row["role"] for row in generated["evidence"]}
    assert expected_roles <= observed_roles
