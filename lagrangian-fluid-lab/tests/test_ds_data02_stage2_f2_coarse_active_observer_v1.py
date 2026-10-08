from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_coarse_active_observer_v1.py"
CONTRACT = ROOT / "campaigns/ds-data-02/stage2/contracts/f2-coarse-observation-contract-v2.json"


def module():
    spec = importlib.util.spec_from_file_location("f2_coarse_active_observer_v1", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def active_report():
    frames = [
        {
            "frame": index,
            "actual_native_time_s": index * 0.01,
            "active_fluid": {
                "position_min_m": [-1.0 - index * 0.001, -0.5, -0.25],
                "position_max_m": [2.0, 0.5 + index * 0.001, 1.25],
            },
        }
        for index in range(401)
    ]
    return {
        "schema": "ds02.stage2.f2.coarse-active-stream.v2",
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
        "timing_and_error_separation": {"actual_native_time_axis": {"first_time_s": 0.0, "last_time_s": 4.0}},
    }


def test_observer_preserves_whole_initial_mass_and_unknown_boundary(tmp_path: Path):
    loaded = module()
    active_path = tmp_path / "active.json"
    active_path.write_text(json.dumps(active_report()), encoding="utf-8")
    output = tmp_path / "observer.json"
    result = loaded.audit(active_path, CONTRACT, output)
    assert result["native_fraction"] == pytest.approx((153 * 0.000681472) / 18.910848)
    derived = json.loads(output.read_text(encoding="utf-8"))
    assert derived["whole_initial_mass_observer"]["denominator_kg"] == pytest.approx(18.910848)
    assert derived["whole_initial_mass_observer"]["unknown_mass_screen_result_only"] is False
    assert derived["whole_initial_mass_observer"]["physical_fate"] == "UNKNOWN"
    assert derived["saved_space_observer"]["union_saved_active_position_bounds_m"]["min_m"][0] == pytest.approx(-1.4)
    assert derived["saved_space_observer"]["union_saved_active_position_bounds_m"]["max_m"][1] == pytest.approx(0.9)
    assert derived["claim_boundary"]["QN"] == "UNKNOWN"


def test_observer_rejects_raw_h5_path_and_wrong_mass(tmp_path: Path):
    loaded = module()
    (tmp_path / "raw.h5").write_bytes(b"forbidden")
    with pytest.raises(loaded.ObserverError, match="forbidden"):
        loaded.require_json(tmp_path / "raw.h5", "active stream report")
    report = active_report()
    report["active_fluid_stream"]["whole_initial_fluid_mass_kg"] = 1.0
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(loaded.ObserverError, match="18.910848"):
        loaded.derive(report, loaded.validate_contract(json.loads(CONTRACT.read_text())), path, CONTRACT)
