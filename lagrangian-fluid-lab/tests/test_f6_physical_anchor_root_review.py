import json
import xml.etree.ElementTree as ET
from pathlib import Path

from scripts.f6_physical_anchor_root_review import (
    BODY_ID,
    EVENT_SCHEMA,
    GRAVITY,
    PREFLIGHT_SCHEMA,
    PROPOSAL_SCHEMA,
    SIDECAR_SCHEMA,
    build_contract,
    build_event_contract,
    build_sidecar,
    body_model,
    create,
    fluid_model,
    static_preflight,
    tank_model,
)


LAB = Path(__file__).resolve().parents[1]
ROOT = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-root-review-v1-20260921"


def read_json(name: str) -> dict:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_physical_anchor_cpu_receipt_is_fail_closed_and_unqualified():
    receipt = read_json("preflight.json")

    assert receipt["schema"] == PREFLIGHT_SCHEMA
    assert receipt["status"] == "cpu_physical_anchor_preflight_pass"
    assert receipt["gate_passed"] is True
    assert receipt["event_window_auditable"] is True
    assert receipt["event_window_complete"] is False
    assert receipt["event_window_status"] == "auditable_prediction_pending_runtime_event_window"
    assert receipt["recommendation"] == "worth_one_protected_solver_canary_conditionally"
    assert receipt["solver_canary_authorized_in_this_receipt"] is False
    assert receipt["qualification_claim"] == "none"
    assert receipt["qualification_credit"] == 0
    controls = receipt["execution_controls"]
    assert controls["gencase_invoked"] is False
    assert controls["solver_invoked"] is False
    assert controls["gpu_invoked"] is False
    assert controls["queue_mutation"] == 0
    assert controls["registry_mutation"] == 0
    assert controls["ledger_mutation"] == 0
    assert controls["matrix_submission"] is False


def test_definition_contract_proposal_and_event_are_hash_bound():
    proposal = read_json("proposal.json")
    contract = read_json("definition-contract.json")
    sidecar = read_json("body-state-force-torque-sidecar-schema.json")
    event = read_json("event-window-contract.json")
    definition = ROOT / "CORE_F6_physical_anchor_single_body_gravity_20260921_Def.xml"
    xml_root = ET.parse(definition).getroot()

    assert proposal["schema"] == PROPOSAL_SCHEMA
    assert proposal["qualification_claim"] == "none"
    assert proposal["qualification_credit"] == 0
    assert proposal["T1"] is False
    decision = proposal["root_review_decision"]
    assert decision["cpu_preflight_pass"] is True
    assert decision["event_window_is_analytically_auditable"] is True
    assert decision["worth_one_protected_solver_canary_conditionally"] is True
    assert decision["solver_canary_authorized_now"] is False

    assert contract["gravity_m_s2"] == list(GRAVITY)
    assert contract["physical_f6_qualification"] is False
    assert contract["fresh_input"]["old_assets_reused"] is False
    assert contract["fresh_input"]["old_xml_copied"] is False
    assert contract["fresh_input"]["old_bi4_reused"] is False
    assert contract["fresh_input"]["old_hdf5_reused"] is False
    assert contract["body"]["body_id"] == BODY_ID
    assert contract["body"]["mass_kg"] == 2.9952
    assert contract["body"]["inertia_about_com_kg_m2"][0][0] > 0.0

    gravity = xml_root.find("./casedef/constantsdef/gravity")
    assert gravity is not None
    assert [float(gravity.get(axis)) for axis in ("x", "y", "z")] == list(GRAVITY)
    assert xml_root.find("./casedef/geometry/definition").get("dp") == "0.02"
    xml_text = definition.read_text(encoding="utf-8")
    for legacy_token in ("F6_floating_box", "F6_heavy_box_entry", "F6_twin_floaters", ".bi4", ".h5"):
        assert legacy_token not in xml_text

    assert event["schema"] == EVENT_SCHEMA
    assert event["window"] == {
        "start_s": 0.0,
        "end_s": 1.5,
        "output_interval_s": 0.005,
        "expected_frame_count": 301,
        "settle_hold_start_s": 1.0,
        "settle_hold_end_s": 1.5,
    }
    assert event["predicted_events"]["contact_prediction_window_s"][0] > 0.0
    assert event["predicted_events"]["contact_prediction_window_s"][1] < 1.0
    assert event["uncensored_required"] is True
    assert sidecar["schema"] == SIDECAR_SCHEMA
    names = {field["name"] for field in sidecar["required_fields"]}
    assert {"body_position_m", "fluid_force_N", "fluid_torque_Nm", "boundary_contact_count", "open_face_mass_flux_kg_s", "valid"} <= names


def test_tampered_prediction_leaves_failed_preflight_without_authorization(tmp_path):
    receipt = create(tmp_path / "f6-physical-anchor")
    assert receipt["gate_passed"] is True
    root = tmp_path / "f6-physical-anchor"
    contract = json.loads((root / "definition-contract.json").read_text(encoding="utf-8"))
    contract["predicted_events"]["predicted_contact_time_s"] = -1.0
    contract["predicted_events"]["contact_prediction_window_s"] = [-1.02, -0.98]
    failed = static_preflight(
        root,
        contract,
        root / "CORE_F6_physical_anchor_single_body_gravity_20260921_Def.xml",
        root / "body-state-force-torque-sidecar-schema.json",
        root / "event-window-contract.json",
    )
    assert failed["status"] == "cpu_physical_anchor_preflight_failed"
    assert failed["gate_passed"] is False
    assert failed["recommendation"] == "do_not_authorize_solver_canary"
    assert failed["solver_canary_authorized_in_this_receipt"] is False
    assert failed["qualification_claim"] == "none"
    assert failed["qualification_credit"] == 0


def test_corrupted_gravity_or_legacy_token_fails_cpu_gate(tmp_path):
    root = tmp_path / "f6-physical-anchor"
    create(root)
    contract = json.loads((root / "definition-contract.json").read_text(encoding="utf-8"))
    definition = root / "CORE_F6_physical_anchor_single_body_gravity_20260921_Def.xml"
    sidecar = root / "body-state-force-torque-sidecar-schema.json"
    event = root / "event-window-contract.json"
    original = definition.read_text(encoding="utf-8")

    bad_gravity = root / "bad-gravity.xml"
    bad_gravity.write_text(original.replace('z="-9.81"', 'z="-9.80"', 1), encoding="utf-8")
    failed_gravity = static_preflight(root, contract, bad_gravity, sidecar, event)
    assert failed_gravity["gate_passed"] is False
    assert failed_gravity["checks"]["gravity_binding"]["passed"] is False
    assert failed_gravity["recommendation"] == "do_not_authorize_solver_canary"

    legacy_token_definition = root / "legacy-token.xml"
    legacy_token_definition.write_text(original.replace("<case>", "<case><!-- F6_floating_box -->", 1), encoding="utf-8")
    failed_legacy = static_preflight(root, contract, legacy_token_definition, sidecar, event)
    assert failed_legacy["gate_passed"] is False
    assert failed_legacy["checks"]["fresh_xml_no_legacy_input"]["passed"] is False
    assert failed_legacy["solver_canary_authorized_in_this_receipt"] is False
