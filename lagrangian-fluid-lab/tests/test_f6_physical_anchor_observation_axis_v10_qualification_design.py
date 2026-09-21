"""Contract checks for the proposal-only F6 v10 qualification design."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
DESIGN_DIR = LAB / (
    "campaigns/core-v1/cfd/"
    "f6-fluid-rigid-body-physical-anchor-observation-axis-v10-"
    "qualification-design-20260921"
)
DESIGN = DESIGN_DIR / "design.json"
MATRIX = DESIGN_DIR / "matrix.json"
CARD = DESIGN_DIR / "candidate-card.json"
SOURCE = LAB / (
    "campaigns/core-v1/cfd/"
    "f6-fluid-rigid-body-physical-anchor-observation-axis-v10-root-review-20260921"
)
PREFLIGHT = LAB / (
    "campaigns/core-v1/cfd/"
    "f6-fluid-rigid-body-physical-anchor-observation-axis-v10-cpu-native-preflight-20260921"
    "/preflight.json"
)
CANARY = LAB / (
    "campaigns/core-v1/cfd/"
    "f6-fluid-rigid-body-physical-anchor-observation-axis-v10-solver-canary-20260921"
    "/attempt-001/execution-receipt.json"
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_design_is_proposal_only_and_has_exact_13_plus_2_cells() -> None:
    value = load(DESIGN)
    assert value["status"] == "root_review_only_not_submitted"
    assert value["matrix_cell_count"] == 15
    assert value["spatial_cell_count"] == 13
    assert value["time_output_comparison_count"] == 2
    assert value["qualification_only"] is True
    assert value["qualification_claim"] == "none"
    assert value["qualification_credit"] == 0
    assert value["T1"] is False
    assert value["scope_id"] == "F6_fluid_rigid_body_physical_anchor_aligned_sampling_v3"
    assert value["revision_id"] == "F6_observation_axis_13plus2_v4"
    assert value["parameter"]["name"] == "body_release_com_z_m"
    assert value["parameter"]["range_m"] == [0.49, 0.61]
    assert value["parameter"]["anchor_q"] == [0.0, 0.5, 1.0]
    assert value["parameter"]["held_out_q"] == [0.25, 0.75]
    assert value["cells"][0]["geometry"]["fluid_low_m"] == [0.175, 0.05, 0.04]
    assert value["cells"][0]["geometry"]["fluid_size_m"] == [1.14, 0.465, 0.24]


def test_cells_have_unique_identity_and_fixed_qualification_signature() -> None:
    value = load(DESIGN)
    cells = value["cells"]
    assert len({cell["cell_id"] for cell in cells}) == 15
    assert len({cell["case_id"] for cell in cells}) == 15
    assert len({cell["definition_id"] for cell in cells}) == 15

    spatial = [cell for cell in cells if cell["design_cell"] in {"spatial", "spatial_held_out"}]
    comparisons = [cell for cell in cells if cell["design_cell"] in {"internal_time", "native_output"}]
    assert len(spatial) == 13
    assert len(comparisons) == 2
    assert {(cell["parameter"]["q"], cell["resolution"]["dp_m"]) for cell in spatial} == {
        (q, dp)
        for q in (0.0, 0.5, 1.0)
        for dp in (0.025, 0.020, 0.015)
    } | {
        (q, dp)
        for q in (0.25, 0.75)
        for dp in (0.020, 0.015)
    }
    assert {(cell["design_cell"], cell["parameter"]["q"], cell["resolution"]["dp_m"]) for cell in comparisons} == {
        ("internal_time", 0.5, 0.020),
        ("native_output", 0.5, 0.020),
    }
    for cell in cells:
        assert cell["qualification_only"] is True
        assert cell["split"] == "qualification_only"
        assert cell["qualification_claim"] == "none"
        assert cell["qualification_credit"] == 0
        assert cell["T1"] is False
        assert cell["execution_policy"]["queue_submission"] is False
        assert cell["execution_policy"]["registry_mutation"] is False
        assert cell["execution_policy"]["ledger_mutation"] is False
        assert cell["execution_policy"]["matrix_credit"] == 0
        assert cell["fresh_input_contract"]["fresh_definition_required"] is True
        assert cell["fresh_input_contract"]["fresh_generated_xml_required"] is True
        assert cell["fresh_input_contract"]["fresh_generated_bi4_required"] is True
        assert cell["fresh_input_contract"]["old_v10_canary_used_as_input"] is False


def test_event_prediction_is_independent_and_monotone_in_release_height() -> None:
    value = load(DESIGN)
    cells = [cell for cell in value["cells"] if cell["design_cell"] == "spatial"]
    by_q = {}
    for cell in cells:
        by_q.setdefault(cell["parameter"]["q"], cell["event_contract"]["predicted_contact_time_s"])
    assert list(by_q) == [0.0, 0.5, 1.0]
    assert by_q[0.0] < by_q[0.5] < by_q[1.0]
    for cell in value["cells"]:
        event = cell["event_contract"]
        assert event["analytic_only"] is True
        assert event["event_window_complete_required"] is True
        assert event["observation_window_s"] == [1.0, 1.5]
        assert cell["time_contract"]["native_time_axis"] == "solver_reported_actual_TimeStep"
        assert cell["time_contract"]["equilibrium_status"] == "not_claimed"
        expected = 601 if cell["design_cell"] == "native_output" else 301
        assert cell["time_contract"]["expected_frame_count"] == expected
        assert event["expected_frame_count"] == expected


def test_design_binds_current_nonqualifying_v10_context_by_hash() -> None:
    value = load(DESIGN)
    bindings = value["source_bindings"]
    expected = {
        "fresh_v10_definition_contract": SOURCE / "definition-contract.json",
        "fresh_v10_preflight": PREFLIGHT,
        "fresh_v10_solver_canary": CANARY,
    }
    for name, path in expected.items():
        assert bindings[name]["sha256"] == sha256(path)
        assert bindings[name]["hash_only"] is True
    assert load(PREFLIGHT)["T1"] is False
    assert load(CANARY)["T1"] is False


def test_matrix_and_candidate_card_cannot_claim_submission() -> None:
    matrix = load(MATRIX)
    card = load(CARD)
    assert matrix["submitted"] is False
    assert matrix["qualification_credit"] == 0
    assert matrix["design_ref"]["sha256"] == sha256(DESIGN)
    assert card["status"] == "root_review_only_not_submitted"
    assert card["qualification_claim"] == "none"
    assert card["T1"] is False
    controls = card["execution_controls"]
    assert controls["definition_written"] is False
    assert controls["gencase_invoked"] is False
    assert controls["solver_invoked"] is False
    assert controls["gpu_invoked"] is False
    assert controls["queue_mutation"] == 0
    assert controls["registry_mutation"] == 0
    assert controls["ledger_mutation"] == 0
    assert controls["matrix_submission"] is False
