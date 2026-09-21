"""Contract tests for the fresh, root-review-only F6 v10 proposal."""

from __future__ import annotations

import json
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
PROPOSAL = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-cadence-revision-v10-20260921/proposal.json"


def load() -> dict:
    return json.loads(PROPOSAL.read_text(encoding="utf-8"))


def test_v10_is_fresh_root_review_only_and_cannot_reuse_v9_input() -> None:
    value = load()
    assert value["schema"] == "core.f6.physical_anchor.cadence_revision_proposal.v1"
    assert value["status"] == "root_review_only_fresh_definition_required"
    assert value["fresh_identity"]["fresh_definition_required"] is True
    assert value["fresh_identity"]["fresh_generated_xml_required"] is True
    assert value["fresh_identity"]["fresh_generated_bi4_required"] is True
    assert value["fresh_identity"]["old_xml_bi4_hdf5_reused_as_input"] is False
    assert value["fresh_identity"]["old_trajectory_reused_as_input"] is False
    assert value["prior_v9"]["same_input_retry"] is False
    assert value["prior_v9"]["resume"] is False
    assert value["qualification_claim"] == "none"
    assert value["qualification_credit"] == 0
    assert value["T1"] is False
    controls = value["execution_controls"]
    assert controls["definition_written"] is False
    assert controls["gencase_invoked"] is False
    assert controls["solver_invoked"] is False
    assert controls["gpu_invoked"] is False
    assert controls["queue_mutation"] == 0
    assert controls["registry_mutation"] == 0
    assert controls["ledger_mutation"] == 0
    assert controls["matrix_submission"] is False


def test_v10_time_axis_and_observation_semantics_are_explicit() -> None:
    value = load()
    axis = value["time_axis_contract"]
    assert axis["requested_output_interval_s"] == 0.005
    assert axis["native_time_axis"] == "solver_reported_actual_TimeStep"
    assert axis["frame_count"] == 301
    assert axis["strictly_increasing"] is True
    assert axis["max_gap_s"] == 0.0055
    assert axis["terminal_coverage"]["mode"] == "bracket_target"
    assert axis["terminal_coverage"]["last_native_time_must_be_at_least_target"] is True
    assert axis["terminal_coverage"]["terminal_overshoot_max_s"] == 0.0005
    hold = value["observation_window_contract"]
    assert hold["name"] == "observation_hold"
    assert hold["requires_equilibrium_claim"] is False
    assert hold["equilibrium_status"] == "not_claimed"
    assert hold["equilibrium_thresholds"] is None
    assert any("observation window" in gate for gate in value["runtime_hard_gates"])
