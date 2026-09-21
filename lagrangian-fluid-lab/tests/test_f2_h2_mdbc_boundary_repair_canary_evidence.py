from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "campaigns/core-v1/cfd/f2-h2-mdbc-boundary-repair-v2-canary-evidence-20260920.json"


def test_h2_canary_is_positive_diagnostic_but_not_t1() -> None:
    value = json.loads(ARTIFACT.read_text())
    assert value["schema"] == "core.f2.h2_mdbc_boundary_repair.canary_evidence.v1"
    status = value["scientific_status"]
    assert status["execution_status"] == "succeeded"
    assert status["hard_integrity_pass"] is True
    assert status["requested_horizon_reached"] is True
    assert status["static_hold_gate_pass"] is True
    assert status["event_window_complete"] is False
    assert status["T1_numerical"] is False
    assert status["registry_mutation"] == 0
    diagnostics = value["diagnostics"]
    assert diagnostics["endpoint_violation_particle_frames"] == 0
    assert diagnostics["saved_chord_crossing_count"] == 0
    assert diagnostics["minimum_cup_retention_mass_fraction"] >= 0.95
    assert value["decision"]["qualification_scope_ready"] is False
    assert value["decision"]["T1_registration_authorized"] is False


def test_h2_canary_requires_a_new_matrix_review() -> None:
    decision = json.loads(ARTIFACT.read_text())["decision"]
    assert decision["expand_to_15_cell_matrix"] is False
    assert "new root review" in decision["next_step"]
