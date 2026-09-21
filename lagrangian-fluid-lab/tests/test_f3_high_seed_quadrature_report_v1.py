from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from scripts.f3_high_seed_quadrature_report_v1 import _event_metrics


LAB = Path(__file__).resolve().parents[1]
EVIDENCE = LAB / "campaigns/core-v1/material/evidence/f3-high-seed-quadrature-row29-canary-v1-20260920.json"


def test_event_metrics_keeps_all_seed_denominator_and_censors_missing_events() -> None:
    times = np.asarray([0.0, 0.01, 0.02])
    values = np.asarray([np.nan, 0.015, np.nan, 0.02])
    select = np.asarray([True, True, False, False])
    result = _event_metrics(times, values, select, 0.5, 0.02)
    assert result["event_count"] == 1
    assert result["cdf_at_window_end"] == 0.5
    assert result["event_mass_kg"] == 0.5
    assert result["censored_fraction"] == 0.5
    assert result["cdf_denominator_policy"] == "all geometric seeds carrying this source label"


def test_generated_evidence_is_explicitly_nonqualifying_and_integrity_checked() -> None:
    evidence = json.loads(EVIDENCE.read_text())
    assert evidence["schema"] == "core.material.f3.native_volume_mls.high_seed_quadrature_report.v1"
    assert evidence["qualification_claim"] == "none"
    assert evidence["t2_decision"]["acceptable_closure_path"] is False
    canary = evidence["high_seed_canary"]
    assert canary["seed_count"] == 8192
    assert canary["frame_count"] == 5
    assert canary["time_end_s"] < 0.05
    assert canary["integrity_audit"]["integrity_pass"] is True
    assert canary["integrity_audit"]["checkpoint"]["pass"] is True


def test_generated_evidence_preserves_mass_events_and_existing_failures() -> None:
    evidence = json.loads(EVIDENCE.read_text())
    mass = evidence["high_seed_canary"]["mass_events_coverage"]
    assert abs(sum(mass["mass_by_source_kg"].values()) - mass["total_initial_mass_kg"]) < 1e-12
    assert all(row["first_passage"]["event_count"] == 0 for row in mass["by_source"])
    assert all(row["return"]["event_count"] == 0 for row in mass["by_source"])
    rows = evidence["existing_full_window_rows"]
    assert {row["matrix_row"] for row in rows} == {29, 31}
    assert all(row["unknown_gate_pass"] is False for row in rows)
    assert all(row["cdf_gate_pass"] is False for row in rows)
    assert all(row["event_window_complete"] is True for row in rows)
    assert all(row["reader_integrity_pass"] is True for row in rows)
    assert all("destination_current_mass_kg" in source
               for row in rows for source in row["source_rows"])
    assert evidence["resource_ledger"]["full_window_projection"]["hours"] > 10.0
