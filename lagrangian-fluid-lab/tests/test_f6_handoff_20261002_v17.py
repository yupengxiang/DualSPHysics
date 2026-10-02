from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ds_data02_f6_handoff_20261002_v17.py"
SPEC = importlib.util.spec_from_file_location("ds_data02_f6_handoff_20261002_v17", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
F6 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(F6)


def test_torque_contract_preserves_raw_frame_and_forbids_unreframed_com_label() -> None:
    contract = F6.read_json(F6.TORQUE_CONTRACT)
    assert contract["raw_compute_forces"]["reference_coordinates_m"] == [2.4, 1.2, 1.08]
    assert contract["raw_compute_forces"]["raw_torque_claim"].startswith("raw official")
    assert contract["current_com_reframe"]["current_com_label_allowed_only_after_reframe"] is True
    assert "cross(r_COM(t) - r_reference(t), F_matching(t))" in contract["current_com_reframe"]["world_frame_formula"]
    assert contract["current_com_reframe"]["raw_output_preserved"] is True
    assert contract["join_contract"]["frame_count"] == 241


def test_torque_contract_binds_both_frozen_audit_requests() -> None:
    contract = F6.read_json(F6.TORQUE_CONTRACT)
    force = [row for row in contract["source_requests"] if "COMPUTEFORCES" in row["attempt_id"]]
    floating = [row for row in contract["source_requests"] if "FLOATINGINFO" in row["attempt_id"]]
    assert {row["mechanism_id"] for row in force} == {"simple_free_response", "wave_no_contact"}
    assert {row["mechanism_id"] for row in floating} == {"simple_free_response", "wave_no_contact"}
    assert contract["gpu_launch"] is False
