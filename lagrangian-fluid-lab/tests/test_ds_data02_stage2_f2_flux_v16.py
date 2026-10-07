from __future__ import annotations

from pathlib import Path
import sys
import math

import pytest


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import ds_data02_stage2_f2_flux_v16 as v16  # noqa: E402


def _summary(known: float) -> dict:
    return {
        "net_flux_known_endpoint_subtotal_kg": known,
        "net_flux_interval_kg": [0.0, 3.0],
        "net_flux_mass_kg": known,
        "net_flux_unknown_interval_kg": None,
        "gross_flux_mass_kg": 8.0,
        "observed_gross_flux_mass_kg": 8.0,
        "unknown_flux_intervals": [{"bracket_s": [1.0, 1.1]}],
    }


def _motion_semantics() -> dict:
    return {
        "start_angle_deg": 0.0,
        "finish_angle_deg": -105.0,
        "rotation_duration_s": 0.9,
        "static_hold_start_s": 0.5,
        "rotation_stop_s": 1.4,
        "finish_s": 4.0,
        "table_coverage_s": [0.0, 4.0],
    }


def _v15_result() -> dict:
    return {
        "schema": v16.V15_RESULT_SCHEMA,
        "event_summary": _summary(13.57200064463541),
        "motion_completion_semantics": _motion_semantics(),
        "moving_source_motion_binding": {
            "case_name_angle_conflict": "legacy value must not survive the forward view",
        },
        "quality": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "nested": {"case_name_angle_conflict": "also remove recursively"},
    }


def test_total_interval_includes_known_subtotal_and_unknown_endpoint_mass() -> None:
    corrected = v16.correct_event_summary(_summary(1.0), unknown_endpoint_mass_kg=3.0)
    assert corrected["net_flux_known_endpoint_subtotal_kg"] == 1.0
    assert corrected["net_flux_unknown_endpoint_contribution_interval_kg"] == [0.0, 3.0]
    assert corrected["net_flux_total_interval_kg"] == [1.0, 4.0]
    assert corrected["gross_flux_mass_kg"] is None
    assert corrected["gross_flux_status"].startswith("UNKNOWN_")
    for legacy in ("net_flux_interval_kg", "net_flux_mass_kg", "net_flux_unknown_interval_kg"):
        assert legacy not in corrected


def test_real_v15_numbers_preserve_signed_known_endpoint_subtotal() -> None:
    corrected = v16.correct_event_summary(
        _summary(13.57200064463541),
        unknown_endpoint_mass_kg=0.003000000142492354,
    )
    assert corrected["net_flux_total_interval_kg"][0] == 13.57200064463541
    assert math.isclose(
        corrected["net_flux_total_interval_kg"][1],
        13.575000644777903,
        rel_tol=0.0,
        abs_tol=5e-15,
    )
    assert corrected["net_flux_unknown_endpoint_contribution_interval_kg"] == [
        0.0,
        0.003000000142492354,
    ]


def test_negative_known_endpoint_subtotal_is_not_clipped_to_zero() -> None:
    corrected = v16.correct_event_summary(_summary(-1.0), unknown_endpoint_mass_kg=2.0)
    assert corrected["net_flux_total_interval_kg"] == [-1.0, 1.0]


def test_unknown_endpoint_mass_must_be_finite_nonnegative() -> None:
    with pytest.raises(v16.FluxV16BindingError, match="nonnegative"):
        v16.correct_event_summary(_summary(1.0), unknown_endpoint_mass_kg=-1.0)
    with pytest.raises(v16.FluxV16BindingError, match="finite"):
        v16.correct_event_summary(_summary(1.0), unknown_endpoint_mass_kg=float("nan"))


def test_forward_view_removes_historical_motion_conflict_and_keeps_unknown_quality() -> None:
    view = v16.forward_result(_v15_result(), unknown_endpoint_mass_kg=3.0)
    assert view["schema"] == v16.RESULT_SCHEMA
    assert "case_name_angle_conflict" not in view["moving_source_motion_binding"]
    assert "case_name_angle_conflict" not in view["nested"]
    assert view["moving_source_motion_binding"]["rotation_duration_s"] == 0.9
    assert view["moving_source_motion_binding"]["rotation_stop_s"] == 1.4
    assert view["moving_source_motion_binding"]["table_coverage_s"] == [0.0, 4.0]
    assert view["event_summary"]["net_flux_total_interval_kg"][0] == 13.57200064463541
    assert math.isclose(
        view["event_summary"]["net_flux_total_interval_kg"][1],
        16.57200064463541,
        rel_tol=0.0,
        abs_tol=5e-15,
    )
    assert view["quality"] == {
        "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "qualification": "UNKNOWN",
    }


def test_forward_view_rejects_non_v15_result() -> None:
    with pytest.raises(v16.FluxV16BindingError, match="v15 replay result"):
        v16.forward_result({"schema": v16.RESULT_SCHEMA}, unknown_endpoint_mass_kg=0.0)
