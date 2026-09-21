"""Contract checks for the F6 v4 cell canary worker and recovered center run."""

from __future__ import annotations

import json
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
CANARY = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-solver-canary-v4-20260921"
CENTER = CANARY / "cell-04/attempt-001/execution-receipt.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_recovered_center_canary_has_scientific_hard_gates_but_no_credit() -> None:
    value = load(CENTER)
    assert value["schema"] == "core.f6.observation_axis.protected_solver_canary_receipt.v1"
    assert value["status"] == "solver_completed_sidecar_pass_pending_scientific_review"
    assert value["cell_id"] == "F6_OBS_V10_Q0P50_DP0P020_SPATIAL"
    assert value["revision_id"] == "F6_observation_axis_13plus2_v4"
    assert value["qualification_only"] is True
    assert value["qualification_claim"] == "none"
    assert value["qualification_credit"] == 0
    assert value["T1"] is False
    assert value["recovery"]["solver_invoked_once"] is True
    assert value["recovery"]["solver_not_reinvoked"] is True
    assert all(value["hard_gates"].values())
    controls = value["execution_controls"]
    assert controls["solver_invoked"] is True
    assert controls["gpu_started"] is False
    assert controls["queue_mutation"] == 0
    assert controls["registry_mutation"] == 0
    assert controls["ledger_mutation"] == 0
    assert controls["matrix_submission"] is False


def test_center_canary_time_contract_and_sidecar_are_native() -> None:
    value = load(CENTER)
    assert value["frames"]["count"] == 301
    axis = value["time_axis_contract"]
    assert axis["native_time_axis"] == "solver_reported_actual_TimeStep"
    assert axis["requested_output_interval_s"] == 0.005
    assert axis["max_gap_s"] == 0.0055
    assert axis["observation_window_s"] == [1.0, 1.5]
    assert axis["equilibrium_status"] == "not_claimed"
    assert value["sidecar_checks"]["observation_hold_no_equilibrium_claim"] is True
