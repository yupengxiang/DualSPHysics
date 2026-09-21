from __future__ import annotations

import json
from pathlib import Path

from scripts.f2_distributed_slot_definition_v1 import (
    frame_boxes,
    verify_definition,
    write_definition,
    write_contract,
)


LAB = Path(__file__).resolve().parents[1]
ROOT_REVIEW = LAB / "campaigns/core-v1/cfd/f2-distributed-slot-root-review-v1.json"


def test_frame_has_two_openings_and_a_solid_web():
    boxes = frame_boxes()
    assert [name for name, _, _ in boxes] == ["left_frame", "central_web", "right_frame", "top_frame"]
    assert boxes[1][2][1] > 0
    assert boxes[0][2][1] > 0 and boxes[2][2][1] > 0


def test_fresh_definition_is_literal_and_contract_closed(tmp_path):
    base = tmp_path / "scope"
    definition = base / "definition" / "F2_SLOT_TRANSFER_q0p50000000_dp0p007500000000_anchor_Def.xml"
    write_definition(definition)
    result = verify_definition(definition)
    assert result["status"] == "definition_static_contract_pass"
    contract = write_contract(base)
    assert json.loads((base / "definition/definition-contract-v1.json").read_text())["qualification_claim"] == "none"
    assert contract["execution_controls"]["gencase_invoked"] is False
    assert definition.read_text().startswith("<?xml")


def test_root_review_receipt_is_present_and_zero_credit():
    review = json.loads(ROOT_REVIEW.read_text())
    assert review["status"] == "authorized_one_fresh_definition_and_cpu_native_preflight_only"
    assert review["execution_constraints"]["qualification_credit"] == 0
