from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_coarse_pure_observer_v1.py"
CONTRACT = ROOT / "campaigns/ds-data-02/stage2/contracts/f2-coarse-observation-contract-v2.json"


def module():
    spec = importlib.util.spec_from_file_location("f2_coarse_pure_observer_v1", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def report(*, include_integration_fields: bool = True):
    frames = [{
        "frame": i,
        "actual_native_time_s": i * 0.01,
        "active_fluid": {
            "position_min_m": [-1.0, -0.5, -0.25],
            "position_max_m": [2.0, 0.5, 1.25],
            "mass_weighted_velocity_m_s": [0.1, -0.2, 0.3],
        },
    } for i in range(401)]
    integration_error = {"status": "OBSERVED_LAST_STEP_BOUND"}
    if include_integration_fields:
        integration_error["fields"] = [91713, 1.0e-5, 5.369918250689863e-5]
    return {
        "schema": "ds02.stage2.f2.coarse-active-stream.v3",
        "status": "COMPLETED_F2_COARSE_ACTIVE_FLUID_STREAM_OBSERVATION",
        "case_key": "F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0088_T4_COARSE_CANARY_ROOT_095",
        "physical_case_id": "F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0088_T4_COARSE_CANARY_ROOT_095",
        "input_stability": {"all_equal": True},
        "read_policy": {"hdf5_opened": False, "solver_started": False},
        "active_fluid_stream": {
            "frame_count": 401,
            "initial_fluid_count": 27750,
            "whole_initial_fluid_mass_kg": 18.910848,
            "frame_summaries": frames,
        },
        "mass_and_material": {
            "native_excluded_mass_lower_bound_kg": 153 * 0.000681472,
            "native_excluded_mass_fraction_whole_initial": (153 * 0.000681472) / 18.910848,
            "initial_mk_mass_denominators_kg": {"1": 6.303616, "2": 6.303616, "3": 6.303616},
            "native_excluded_count_by_mk": {"1": 49, "2": 69, "3": 35},
        },
        "native_identity_join": {"native_row_count": 153},
        "timing_and_error_separation": {
            "actual_native_time_axis": {"first_time_s": 0.0, "last_time_s": 4.0, "frame_count": 401},
            "saved_output_time_axis": {
                "first_time_s": 0.0,
                "last_time_s": 4.0,
                "interval_min_s": 0.01,
                "interval_max_s": 0.01,
                "interval_mean_s": 0.01,
                "frame_count": 401,
            },
            "declared_solver_endpoint": {"used_as_observation_time": False},
            "integration_error": integration_error,
            "output_sampling_error": {"status": "SAVED_INTERVAL_OBSERVED_CONTINUOUS_ERROR_UNKNOWN"},
        },
    }


def test_pure_observer_keeps_dt_as_statistic_and_unknowns_explicit(tmp_path: Path):
    loaded = module()
    active = tmp_path / "active.json"
    active.write_text(json.dumps(report()), encoding="utf-8")
    output = tmp_path / "derived.json"

    summary = loaded.audit(active, CONTRACT, output)
    expected_fraction = (153 * 0.000681472) / 18.910848
    assert summary["native_fraction"] == pytest.approx(expected_fraction)
    result = json.loads(output.read_text(encoding="utf-8"))
    pure = result["pure_time_output_observer"]
    dt = pure["integrator_last_dt_statistic"]
    assert dt["value_s"] == pytest.approx(5.369918250689863e-5)
    assert dt["is_integration_error_upper_bound"] is False
    assert "not an integrator error estimate" in dt["meaning"]
    assert pure["continuous_event_time"] == "UNKNOWN"
    velocity = pure["velocity_ke_observation"]
    assert velocity["mass_weighted_velocity_saved_frame_count"] == 401
    assert velocity["kinetic_energy_sum_m_v2_available"] is False
    assert velocity["nonzero_velocity_ke_reference_denominator"] == "UNKNOWN_NOT_MEASURED"
    assert pure["half_cfl_comparison"]["status"] == "NOT_MEASURED"
    assert result["whole_initial_mass_observer"]["unknown_mass_screen_result_only"] is False
    assert result["claim_boundary"]["dynamics"] == "UNKNOWN"


def test_pure_observer_does_not_invent_last_dt_when_missing(tmp_path: Path):
    loaded = module()
    active = tmp_path / "active.json"
    active.write_text(json.dumps(report(include_integration_fields=False)), encoding="utf-8")
    output = tmp_path / "derived.json"

    loaded.audit(active, CONTRACT, output)
    result = json.loads(output.read_text(encoding="utf-8"))
    dt = result["pure_time_output_observer"]["integrator_last_dt_statistic"]
    assert dt["value_s"] is None
    assert dt["status"] == "UNKNOWN_UNMEASURED"
    assert dt["is_integration_error_upper_bound"] is False

