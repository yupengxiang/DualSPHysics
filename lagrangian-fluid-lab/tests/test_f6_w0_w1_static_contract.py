import json
from pathlib import Path

from scripts.f6_w0_w1_static_contract import (
    BODY_ID,
    DEFAULT_ROOT,
    EVENT_SCHEMA,
    PREFLIGHT_SCHEMA,
    PROPOSAL_SCHEMA,
    SIDECAR_SCHEMA,
    create,
    static_gate,
)


ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    return json.loads((DEFAULT_ROOT / name).read_text(encoding="utf-8"))


def test_f6_w0_w1_static_receipt_passes_without_runtime_authorization():
    receipt = _load("preflight.json")
    assert receipt["schema"] == PREFLIGHT_SCHEMA
    assert receipt["status"] == "cpu_static_gate_pass"
    assert receipt["gate_passed"] is True
    assert receipt["qualification_claim"] == "none"
    assert receipt["qualification_credit"] == 0
    assert receipt["event_window_complete"] is False
    controls = receipt["execution_controls"]
    assert controls["gencase_invoked"] is False
    assert controls["solver_invoked"] is False
    assert controls["gpu_invoked"] is False
    assert controls["queue_mutation"] == 0
    assert controls["registry_mutation"] == 0
    assert controls["ledger_mutation"] == 0
    assert controls["matrix_submission"] is False


def test_f6_w0_w1_contract_is_zero_force_and_new_identity():
    contract = _load("definition-contract.json")
    proposal = _load("proposal.json")
    sidecar = _load("body-state-sidecar-schema.json")
    event = _load("event-window-contract.json")
    assert contract["schema"] == "core.f6.w0_w1.static_definition_contract.v1"
    assert contract["forcing_mode"] == "zero_gravity_zero_force_units_inertia_anchor"
    assert contract["physical_f6_qualification"] is False
    assert proposal["schema"] == PROPOSAL_SCHEMA
    assert proposal["qualification_claim"] == "none"
    assert proposal["qualification_credit"] == 0
    assert proposal["execution_controls"]["gencase_invoked"] is False
    assert proposal["execution_controls"]["solver_invoked"] is False
    assert proposal["execution_controls"]["gpu_invoked"] is False
    assert proposal["execution_controls"]["matrix_submission"] is False
    assert sidecar["schema"] == SIDECAR_SCHEMA
    assert sidecar["body_id"] == BODY_ID
    assert sidecar["forcing_mode"] == "zero_gravity_zero_force_units_inertia_anchor"
    assert sidecar["physical_f6_qualification"] is False
    assert event["schema"] == EVENT_SCHEMA
    assert event["forcing_mode"] == "zero_gravity_zero_force_units_inertia_anchor"
    assert event["physical_f6_qualification"] is False
    assert event["window"]["expected_frame_count"] == 151
    assert event["window"]["output_interval_s"] == 0.01
    definition_text = (DEFAULT_ROOT / "CORE_F6_W0_W1_single_body_no_contact_anchor_20260921_Def.xml").read_text(encoding="utf-8")
    assert 'z="0.0"' in definition_text
    assert all(token not in definition_text for token in ("F6_floating_box", "F6_heavy_box_entry", "F6_twin_floaters", ".bi4", ".h5"))


def test_static_gate_retains_failure_evidence_for_bad_clearance(tmp_path):
    receipt = create(tmp_path)
    assert receipt["gate_passed"] is True
    contract_path = tmp_path / "definition-contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["initial_clearance"]["minimum_all_declared_clearance_m"] = 0.0
    failed = static_gate(
        tmp_path,
        contract,
        tmp_path / f"{contract['case_id']}_Def.xml",
        tmp_path / "body-state-sidecar-schema.json",
        tmp_path / "event-window-contract.json",
    )
    assert failed["status"] == "cpu_static_gate_failed"
    assert failed["gate_passed"] is False
    assert failed["checks"]["clearance_margin"]["passed"] is False
    assert failed["execution_controls"]["solver_invoked"] is False
