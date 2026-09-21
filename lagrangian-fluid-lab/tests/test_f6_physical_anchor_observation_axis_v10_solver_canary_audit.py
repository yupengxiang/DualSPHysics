"""Checks for the live v4 canary aggregate audit."""

from __future__ import annotations

import json
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
AUDIT = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-solver-canary-v4-20260921/canary-audit.json"


def load() -> dict:
    return json.loads(AUDIT.read_text(encoding="utf-8"))


def test_audit_keeps_eight_cell_denominator_and_zero_credit_while_attempts_run() -> None:
    value = load()
    assert value["selected_count"] == 8
    assert value["audited_count"] >= 1
    assert value["scientific_pass_count"] >= 1
    assert value["qualification_claim"] == "none"
    assert value["qualification_credit"] == 0
    assert value["T1"] is False
    center = next(row for row in value["rows"] if row["index"] == 4)
    assert center["cell_id"] == "F6_OBS_V10_Q0P50_DP0P020_SPATIAL"
    assert center["scientific_pass"] is True
    assert center["hard_gate_pass"] is True
    assert center["recovered"] is True


def test_audit_retains_scientific_hard_failure_and_gate_names() -> None:
    value = load()
    failed = next(row for row in value["rows"] if row["index"] == 8)
    assert failed["status"] == "solver_completed_hard_failure"
    assert failed["scientific_pass"] is False
    assert failed["failure_category"] == "scientific_hard_gate_failure"
    assert failed["hard_gate_failures"] == [
        "excluded_particles_zero",
        "native_identity_fixed",
        "fluid_group_count_fixed",
    ]
    assert value["hard_gate_failure_counts"]["excluded_particles_zero"] == 1
