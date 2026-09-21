"""Targeted checks for the read-only F2 pour/catch route audit."""

from __future__ import annotations

import json

from scripts import f2_pour_catch_route_audit_v1 as audit


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_route_and_evidence_bindings_are_current() -> None:
    route = audit.verify()
    assert route["schema"] == "core.f2.pour_catch.route_decision.v1"
    assert route["status"] == "root_review_only_conditional_route"
    assert route["core_gate"]["qualification_credit_added"] == 0
    assert route["core_gate"]["registry_mutation"] == 0
    assert route["core_gate"]["ledger_mutation"] == 0
    assert route["core_gate"]["T1_denominator_mutation"] == 0
    assert route["core_gate"]["T2_denominator_mutation"] == 0

    candidate = _load(audit.CANDIDATE_OUTPUT)
    gap = _load(audit.GAP_OUTPUT)
    candidate_binding = gap["hash_bindings"]["candidate"]
    assert candidate_binding["path"] == str(audit.CANDIDATE_OUTPUT.relative_to(audit.LAB))
    assert candidate_binding["bytes"] == audit.CANDIDATE_OUTPUT.stat().st_size
    assert candidate_binding["sha256"] == audit.sha256(audit.CANDIDATE_OUTPUT)

    assert route["candidate_card"]["sha256"] == audit.sha256(audit.CANDIDATE_OUTPUT)
    assert route["root_review_gap_audit"]["sha256"] == audit.sha256(audit.GAP_OUTPUT)
    assert candidate["candidate_id"] == gap["candidate_id"]


def test_closed_routes_and_v1_negative_denominators_are_retained() -> None:
    route = _load(audit.ROUTE_OUTPUT)
    submerged = route["route_comparison"]["closed_submerged_slot"]
    dynamic = route["route_comparison"]["closed_dynamic_dbc"]
    weir = route["route_comparison"]["closed_receiver_weir"]

    assert submerged["status"] == "closed_negative"
    assert submerged["zero_boundnor"] == 76095
    assert submerged["zero_normalsize"] == 76095
    assert submerged["same_input_retry"] is False
    assert submerged["credit"] == 0

    assert dynamic["status"] == "closed_event_censored"
    assert dynamic["hard_integrity_pass"] is True
    assert dynamic["event_window_complete"] is False
    assert dynamic["same_input_retry"] is False
    assert dynamic["credit"] == 0

    assert weir == {
        "status": "closed_terminal_anchor_negative",
        "planned": 15,
        "executed": 1,
        "failed": 1,
        "event_censored": 1,
        "unattempted": 14,
        "credit": 0,
        "same_input_retry": False,
    }

    candidate = _load(audit.CANDIDATE_OUTPUT)
    negative = candidate["retained_v1_negative"]
    assert negative["anchor_case_id"] == (
        "CORE_F2_STATIC_RECEIVER_BALLISTIC_CATCH_q0p50000000_dp0p007500000000_anchor"
    )
    assert negative["loader_attempt_returncode"] == 127
    assert negative["repair_attempt_frames"] == 301
    assert negative["repair_attempt_excluded_particles"] == 64
    assert negative["repair_attempt_excluded_particles_density"] == 44
    assert negative["hard_integrity_pass"] is False
    assert negative["matrix_credit"] == 0
    assert negative["same_input_retry"] is False
    assert negative["reuse_allowed"] is False


def test_selected_v2_is_fresh_distinct_and_zero_credit() -> None:
    candidate = _load(audit.CANDIDATE_OUTPUT)
    contract = candidate["fresh_input_contract"]
    hypothesis = candidate["hypothesis"]
    topology = candidate["topology"]
    plan = candidate["planned_matrix"]

    assert candidate["scope_id"] == "F2_receiver_ballistic_catch_release_speed_v2_x_v1"
    assert candidate["revision_id"] == "F2_receiver_ballistic_catch_release_speed_v2"
    assert candidate["candidate_id"] == "F2_receiver_ballistic_catch_release_speed010_v2"
    assert candidate["mechanism_class"] == "stationary_receiver_ballistic_slug_capture"
    assert candidate["qualification_claim"] == "none"
    assert candidate["T1_numerical"] is False
    assert candidate["matrix_credit"] == 0
    assert hypothesis["v1_value"] == -0.20
    assert hypothesis["v2_value"] == -0.10
    assert hypothesis["falsifiable"] is True
    assert topology["aperture_or_crest"] is False
    assert topology["moving_cup"] is False
    assert topology["submerged_slot"] is False
    assert topology["distinct_from_closed_route"] is True

    for key in (
        "new_scope_id",
        "new_revision_id",
        "new_case_id",
        "new_literal_definition_required",
        "new_native_output_required",
    ):
        assert contract[key] is True
    for key in (
        "source_reuse",
        "qualification_inheritance",
        "v1_definition_reused",
        "v1_generated_xml_reused",
        "v1_generated_bi4_reused",
        "v1_trajectory_reused",
        "v1_output_stem_reused",
        "same_input_retry",
    ):
        assert contract[key] is False

    assert plan["proposed_rows"] == 15
    assert len(plan["rows"]) == 15
    assert plan["executed"] == 0
    assert plan["passed"] == 0
    assert plan["failed"] == 0
    assert plan["event_censored"] == 0
    assert plan["unattempted"] == 15
    assert plan["credit"] == 0
    assert plan["parent_scope_denominator_unchanged"] is True
    assert plan["survivor_renormalization"] is False


def test_root_review_gaps_keep_definition_and_preflight_blocked() -> None:
    gap = _load(audit.GAP_OUTPUT)
    assert gap["status"] == "blocked_before_new_definition"
    assert gap["decision"] == "hold_new_definition_until_root_gaps_are_closed"
    assert gap["worth_new_definition"] is True
    assert gap["worth_preflight_now"] is False
    assert {item["status"] for item in gap["gaps"]} >= {"blocking"}
    assert gap["authorization"]["definition_writer"] is False
    assert gap["authorization"]["cpu_gencase"] is False
    assert gap["authorization"]["native_decode"] is False
    assert gap["authorization"]["solver"] is False
    assert gap["authorization"]["gpu"] is False
    assert gap["authorization"]["queue_mutation"] == 0
    assert gap["authorization"]["ledger_mutation"] == 0
    assert gap["authorization"]["registry_mutation"] == 0
    assert gap["authorization"]["T1_denominator_mutation"] == 0
    assert gap["authorization"]["T2_denominator_mutation"] == 0
    assert gap["authorization"]["qualification_credit"] == 0


def test_route_implementation_has_no_execution_entry_point() -> None:
    source = audit.LAB.joinpath("scripts/f2_pour_catch_route_audit_v1.py").read_text(
        encoding="utf-8"
    )
    assert "subprocess" not in source
    assert "subprocess.run" not in source
    assert "Popen(" not in source
    assert "solver_binary" not in source
    assert "queue_mutation" in source
