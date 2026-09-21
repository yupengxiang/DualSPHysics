"""Regression tests for the read-only F1/F2 third-T1 closure receipt."""

from __future__ import annotations

import hashlib
import json

from scripts import f1_f2_third_t1_route_closed_v2 as audit


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_receipts_are_hash_bound_and_current() -> None:
    card = audit.verify()
    assert card["schema"] == "core.third_t1.f1_f2_route_closed.candidate_card.v2"
    assert card["status"] == "route_closed_no_new_hypothesis"
    receipt = _load(audit.RECEIPT_OUTPUT)
    assert receipt["candidate_card"]["path"] == str(
        audit.CARD_OUTPUT.relative_to(audit.LAB)
    )
    assert receipt["candidate_card"]["bytes"] == audit.CARD_OUTPUT.stat().st_size
    assert receipt["candidate_card"]["sha256"] == _sha256(audit.CARD_OUTPUT)
    for item in card["evidence"].values():
        path = audit.LAB / item["path"]
        assert path.is_file()
        assert path.stat().st_size == item["bytes"]
        assert _sha256(path) == item["sha256"]


def test_every_reviewed_route_is_closed_and_zero_credit() -> None:
    card = _load(audit.CARD_OUTPUT)
    routes = {item["route_id"]: item for item in card["route_findings"]}
    assert len(routes) == 8
    assert routes["F1_H1_H2_H3_H4"]["status"] == (
        "closed_hard_negative_repair_lineage"
    )
    assert routes["F1_suspended_obstacle_gap_G1"]["hard_integrity_pass"] is False
    assert routes["F1_suspended_obstacle_gap_G1"]["event_window_complete"] is True
    assert routes["F2_dynamic_DBC_duration"]["event_window_complete"] is False
    assert routes["F2_receiver_overflow_weir"]["executed"] == 1
    assert routes["F2_receiver_overflow_weir"]["failed"] == 1
    assert routes["F2_receiver_ballistic_v1_v2"]["v2_outer_endpoint_particles"] == 3840
    assert routes["F2_distributed_slot_v1_v2"]["v2_zero_boundnor"] == 76095
    assert routes["F2_submerged_orifice_normal_remediation_v2_v3_v4"][
        "zero_boundnor"
    ] == {"v2": 64899, "v3": 83443, "v4": 29484}
    assert all(item["matrix_credit"] == 0 for item in routes.values())
    assert all(item["same_input_retry"] is False for item in routes.values())


def test_core_gate_and_authorization_remain_closed() -> None:
    card = _load(audit.CARD_OUTPUT)
    gate = card["core_gate"]
    assert gate["current_registered_t1_families"] == ["F3", "F4"]
    assert gate["third_t1_family_established"] is False
    assert gate["qualification_credit_added"] == 0
    assert gate["registry_mutation"] == 0
    assert gate["ledger_mutation"] == 0
    assert gate["T1_denominator_mutation"] == 0
    assert gate["T2_denominator_mutation"] == 0

    controls = card["execution_controls"]
    assert controls["definition_writer_invoked"] is False
    assert controls["cpu_gencase_invoked"] is False
    assert controls["native_decoder_invoked"] is False
    assert controls["solver_invoked"] is False
    assert controls["gpu_launched"] is False
    assert controls["queue_mutation"] == 0
    assert controls["qualification_credit"] == 0

    receipt = _load(audit.RECEIPT_OUTPUT)
    assert receipt["root_review"]["root_review_only"] is True
    assert receipt["root_review"]["authorized_now"] is False
    assert receipt["root_review"]["new_definition_authorized"] is False
    assert receipt["route_decision"]["new_physical_definition_found"] is False


def test_closure_implementation_has_no_runtime_entry_point() -> None:
    source = audit.LAB.joinpath(
        "scripts/f1_f2_third_t1_route_closed_v2.py"
    ).read_text(encoding="utf-8")
    assert "subprocess" not in source
    assert "Popen(" not in source
    assert "solver_binary" not in source
    assert "queue_mutation" in source
    assert "new_physical_definition_found" in source
