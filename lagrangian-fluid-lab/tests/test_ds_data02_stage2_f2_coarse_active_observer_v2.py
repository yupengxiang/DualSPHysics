from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_coarse_active_observer_v2.py"
CONTRACT = ROOT / "campaigns/ds-data-02/stage2/contracts/f2-coarse-observation-contract-v2.json"


def module():
    spec = importlib.util.spec_from_file_location("f2_coarse_active_observer_v2", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def report():
    frames = [{
        "frame": i,
        "actual_native_time_s": i * 0.01,
        "active_fluid": {"position_min_m": [-1.0, -0.5, -0.25], "position_max_m": [2.0, 0.5, 1.25]},
    } for i in range(401)]
    return {
        "schema": "ds02.stage2.f2.coarse-active-stream.v3",
        "status": "COMPLETED_F2_COARSE_ACTIVE_FLUID_STREAM_OBSERVATION",
        "case_key": "F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0088_T4_COARSE_CANARY_ROOT_095",
        "physical_case_id": "F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0088_T4_COARSE_CANARY_ROOT_095",
        "input_stability": {"all_equal": True},
        "read_policy": {"hdf5_opened": False, "solver_started": False},
        "active_fluid_stream": {"frame_count": 401, "initial_fluid_count": 27750, "whole_initial_fluid_mass_kg": 18.910848, "frame_summaries": frames},
        "mass_and_material": {
            "native_excluded_mass_lower_bound_kg": 153 * 0.000681472,
            "native_excluded_mass_fraction_whole_initial": (153 * 0.000681472) / 18.910848,
            "initial_mk_mass_denominators_kg": {"1": 6.303616, "2": 6.303616, "3": 6.303616},
            "native_excluded_count_by_mk": {"1": 49, "2": 69, "3": 35},
        },
        "native_identity_join": {"native_row_count": 153},
        "timing_and_error_separation": {
            "actual_native_time_axis": {"first_time_s": 0.0, "last_time_s": 4.0, "frame_count": 401},
            "saved_output_time_axis": {"first_time_s": 0.0, "last_time_s": 4.0, "interval_min_s": 0.01, "interval_max_s": 0.01, "interval_mean_s": 0.01},
            "declared_solver_endpoint": {"used_as_observation_time": False},
            "integration_error": {"status": "OBSERVED_LAST_STEP_BOUND"},
            "output_sampling_error": {"status": "SAVED_INTERVAL_OBSERVED_CONTINUOUS_ERROR_UNKNOWN"},
        },
    }


def test_v2_observer_exposes_finite_saved_time_metrics_without_qualification(tmp_path: Path):
    loaded = module()
    active = tmp_path / "active.json"
    active.write_text(json.dumps(report()), encoding="utf-8")
    output = tmp_path / "derived.json"
    summary = loaded.audit(active, CONTRACT, output)
    assert summary["native_fraction"] == pytest.approx((153 * 0.000681472) / 18.910848)
    result = json.loads(output.read_text(encoding="utf-8"))
    saved = result["saved_time_observer"]
    assert saved["saved_output_axis_finite_observed"]["frame_count"] == 401
    assert saved["saved_output_axis_finite_observed"]["interval_mean_s"] == pytest.approx(0.01)
    assert saved["declared_endpoint_is_metadata_only"] is True
    assert result["saved_output_observer"]["status"] == "PREREGISTERED_COMPARISON_METADATA_ONLY"
    assert result["claim_boundary"]["QI"] == "UNKNOWN"
