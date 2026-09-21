from __future__ import annotations

import json
from pathlib import Path


def test_anchor_canary_is_hard_positive_but_event_censored_and_unregistered() -> None:
    root = Path(__file__).resolve().parents[1]
    path = root / "campaigns/core-v1/cfd/f2-dynamic-third-family-dbc-duration-anchor-canary-negative-evidence-v1.json"
    evidence = json.loads(path.read_text())
    result = evidence["scientific_result"]
    credit = evidence["matrix_credit"]
    assert evidence["qualification_claim"] == "none"
    assert evidence["T1_numerical"] is False
    assert result["hard_integrity_pass"] is True
    assert result["requested_horizon_reached"] is True
    assert result["event_window_complete"] is False
    assert result["missing_native_fluid_id_count"] == 0
    assert result["closed_wall_endpoint_count"] == 0
    assert result["saved_chord_crossing_count"] == 0
    assert credit["fixed_denominator"] == 15
    assert credit["credit"] == 0
    assert credit["formal_row_status"] == "not_started"
    assert credit["executed_prepared_case_id"].endswith("_anchor")
    assert credit["formal_matrix_case_id"].endswith("_held_out")
    assert evidence["classification"]["same_input_retry_allowed"] is False
    assert evidence["execution_controls"]["registry_mutation"] == 0

