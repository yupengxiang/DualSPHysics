from __future__ import annotations

import json

from scripts.f7_pump_direct_torque_admission_proposal_v2 import OUTPUT, build_proposal


def test_v2_is_fully_bound_but_still_fail_closed() -> None:
    result = build_proposal()
    assert result["status"] == "proposal_pending_root_review_not_authorized"
    assert result["diagnostic_only"] is True
    assert result["qualification_credit"] == 0
    counts = result["requested_permissions_exact_counts"]
    assert counts["gencase"] == 1
    assert counts["native_cpu_solver"] == 1
    assert counts["native_decode"] == 1
    assert counts["compute_forces_cpu"] == 1
    assert counts["gpu"] == 0
    assert counts["queue_mutation"] == 0
    assert counts["registry_mutation"] == 0
    assert counts["T1_denominator_mutation"] == 0
    assert counts["T2_denominator_mutation"] == 0


def test_v2_binds_literal_axis_command_and_numeric_gates() -> None:
    result = build_proposal()
    command = " ".join(result["compute_forces_command"]["argv"])
    assert "-dirdata campaigns/core-v1/cfd/f7-pump-direct-torque-anchor-v1/native/data" in command
    assert "-filexml campaigns/core-v1/cfd/f7-pump-direct-torque-anchor-v1/input/F7_pump_torque_anchor_Def.xml" in command
    assert "-first:0" in command and "-last:300" in command and "-onlymk:2" in command
    assert "-momentaxisin:-0.0176:-0.29:-0.7275:-0.0176:-0.49:-0.7275:pump_axis_in" in command
    assert result["moment_result_contract"]["time_alignment_tolerance_s"] == 1.0e-9
    assert result["numeric_acceptance_gates"]["minimum_abs_torque_Nm"] == 1.0e-8
    assert result["numeric_acceptance_gates"]["energy_relative_residual_tolerance"] == 0.10


def test_committed_v2_proposal_binds_latest_audits_and_has_no_execution() -> None:
    assert OUTPUT.is_file()
    result = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert result["schema"] == "core.f7.pump.direct_torque_admission_proposal.v2"
    assert result["bindings"]["force_gauge_audit"]["sha256"]
    assert result["bindings"]["compute_forces_contract"]["sha256"]
    assert result["compute_forces_command"]["execution_completed"] is False
    assert result["protected_state_mutation"]["native_solver_executed"] == 0
    assert result["protected_state_mutation"]["compute_forces_executed"] == 0
