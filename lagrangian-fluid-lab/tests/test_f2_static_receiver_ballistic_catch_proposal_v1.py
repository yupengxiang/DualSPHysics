"""Structural regression checks for the F2 receiver proposal.

These checks inspect the frozen proposal and its provenance only.  They do
not create inputs, decode native output, launch a solver, or mutate campaign
state.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.f2_static_receiver_ballistic_catch_proposal_v1 import (
    LAB,
    PROPOSAL,
    sha256,
    validate_proposal,
)


def _load() -> dict:
    return json.loads(PROPOSAL.read_text(encoding="utf-8"))


def test_proposal_validator_accepts_frozen_bindings() -> None:
    result = validate_proposal()
    assert result["status"] == "ok"
    assert result["planned_denominator"] == 15
    assert result["runtime_calls"] == {
        "gencase": False,
        "native_decode": False,
        "solver": False,
        "gpu": False,
        "queue": 0,
    }


def test_route_is_a_fresh_stationary_receiver_mechanism() -> None:
    proposal = _load()
    candidate = proposal["candidate"]
    fresh = proposal["fresh_input_contract"]
    construction = fresh["construction"]

    assert candidate["scope_id"] == "F2_static_receiver_ballistic_catch_x_v1"
    assert candidate["mechanism_class"] == "stationary_receiver_ballistic_slug_capture"
    assert fresh["source_identity_changed"] is True
    assert fresh["source_reuse"] is False
    assert fresh["old_generated_input_reused"] is False
    assert fresh["old_trajectory_reused"] is False
    assert fresh["same_input_retry"] is False
    assert fresh["new_definition_required"] is True
    assert fresh["new_native_output_required"] is True

    receiver = construction["receiver_basin"]
    assert receiver["closed_faces"] == ["bottom", "left", "right", "front", "back"]
    assert receiver["open_faces"] == ["top"]
    assert receiver["separation_from_outer_floor_m"] > 0
    assert receiver["y_center_mapping"] == "y_center_m = -0.12 + 0.24*q"

    source = construction["falling_source"]
    assert source["initial_velocity_m_s"] == [0.0, 0.0, -0.2]
    assert source["source_centerline_fixed_across_q"] is True
    assert source["initial_overlap_with_basin"] is False

    forbidden = "\n".join(fresh["forbidden_sources"])
    assert "f2-submerged-orifice-transfer-scope-v1" in forbidden
    assert "f2-receiver-overflow-weir-scope-v1" in forbidden
    assert "F2_resting_fill_side_wet" in forbidden


def test_frozen_plan_has_15_rows_as_13_plus_2() -> None:
    design = _load()["fixed_scope_design"]
    rows = design["planned_rows"]

    assert design["cell_count"] == 15
    assert design["spatial_cell_count"] == 13
    assert design["temporal_cell_count"] == 2
    assert len(rows) == 15
    assert sum(row["design_cell"] == "spatial" for row in rows) == 9
    assert sum(row["design_cell"] == "held_out" for row in rows) == 4
    assert sum(row["design_cell"] == "internal_time" for row in rows) == 1
    assert sum(row["design_cell"] == "native_output" for row in rows) == 1
    assert [row["index"] for row in rows] == list(range(15))
    assert {row["status"] for row in rows} == {"not_started"}
    assert design["qualification_q_values"] == [0.0, 0.5, 1.0]
    assert design["held_out_q_values"] == [0.25, 0.75]
    assert design["dp_values_m"] == [0.01, 0.0075, 0.005]


def test_credit_and_execution_boundaries_are_zeroed() -> None:
    proposal = _load()
    denominator = proposal["denominator"]
    controls = proposal["execution_controls"]
    review = proposal["root_review_only_contract"]

    assert proposal["qualification_claim"] == "none"
    assert proposal["matrix_credit"] == 0
    assert denominator == {
        "planned": 15,
        "executed": 0,
        "passed": 0,
        "failed": 0,
        "event_censored": 0,
        "unattempted": 15,
        "credit": 0,
        "same_input_retry": False,
        "survivor_renormalization": False,
    }
    assert all(controls[key] is False for key in (
        "gencase_invoked",
        "native_decode_invoked",
        "solver_invoked",
        "gpu_launched",
        "matrix_materialized",
        "matrix_submitted",
    ))
    assert all(controls[key] == 0 for key in (
        "queue_mutation",
        "central_ledger_mutation",
        "central_registry_mutation",
    ))
    assert review["authorization"]["qualification_credit"] == 0
    assert review["authorization"]["queue_mutation"] == 0
    assert review["authorization"]["ledger_mutation"] == 0
    assert review["authorization"]["registry_mutation"] == 0


def test_validator_binding_is_the_current_read_only_script() -> None:
    implementation = _load()["implementation"]
    script = LAB / implementation["path"]
    assert script == Path(__file__).parents[1] / implementation["path"]
    assert implementation["sha256"] == sha256(script)
    assert implementation["bytes"] == script.stat().st_size
