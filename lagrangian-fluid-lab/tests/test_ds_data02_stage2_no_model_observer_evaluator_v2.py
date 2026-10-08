from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_no_model_observer_evaluator_v2.py"
SPEC = importlib.util.spec_from_file_location("no_model_observer_v2_test_module", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source(path: Path) -> dict[str, object]:
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": _sha(path)}


def _fixture(tmp_path: Path) -> tuple[object, dict, dict, dict]:
    source = tmp_path / "source-bound.txt"
    source.write_text("frozen source binding\n")
    source_binding = {
        "config": _source(source),
        "current_catalog": _source(source),
        "trajectory_h5": _source(source),
    }
    config = {
        "profile_id": "manufactured-observer-v2",
        "query_times_s": [0.0, 1.0],
        "observers": list(MODULE.DEFAULT_OBSERVERS),
        "physical_scales": {
            "position_m": 1.0,
            "velocity_m_s": 1.0,
            "kinetic_energy_j": 1.0,
            "feature_time_s": 1.0,
            "mass_kg": 6.0,
        },
        "tolerances": {
            "position_relative": 0.02,
            "velocity_relative": 0.02,
            "kinetic_energy_relative": 0.02,
            "mass_fraction_absolute": 0.03,
        },
        "budget_fraction_of_total_error": {
            "integration_time": 0.25,
            "output_sampling": 0.25,
        },
        "mass_distribution_bins_m": [0.5, 1.0],
        "mass_quantile": 0.5,
        "source_binding": source_binding,
    }
    config_path = tmp_path / "observer-config.json"
    config_path.write_text(json.dumps(config, indent=2, sort_keys=True))
    profile_path = tmp_path / "profile.json"
    profile = MODULE.build_profile(config_path, profile_path)

    trajectory = {
        "schema": MODULE.TRAJECTORY_SCHEMA,
        "query_times_s": [0.0, 1.0],
        "identity": [[0, 10], [0, 11], [0, 12]],
        "initial_mass_kg": [1.0, 2.0, 3.0],
        "positions_m": [
            [[0.0, 0.0, 0.0], [0.5, 0.0, 0.0], [1.0, 0.0, 0.0]],
            [[0.5, 0.0, 0.0], [1.0, 0.0, 0.0], [1.5, 0.0, 0.0]],
        ],
        "velocities_m_s": [
            [[1.0, 0.0, 0.0], [2.0, 0.0, 0.0], [3.0, 0.0, 0.0]],
            [[2.0, 0.0, 0.0], None, [99.0, 0.0, 0.0]],
        ],
        # The last particle at t=1 remains finite in the arrays, but is
        # inactive.  It must not enter COM, mass fractions, speed, or KE.
        "valid": [[True, True, True], [True, True, False]],
        "position_frame": "world",
        "velocity_frame": "world_inertial",
        "source_binding": copy.deepcopy(source_binding),
    }
    observed = MODULE.compute_observers(trajectory, profile)
    prediction = {
        "schema": MODULE.PREDICTION_SCHEMA,
        "profile_sha256": profile["sha256"],
        "query_times_s": [0.0, 1.0],
        "identity": observed["meta"]["identity"],
        "observers": {name: observed[name] for name in profile["observers"]},
        "budget_fraction_of_total_error": {
            "integration_time": 0.25,
            "output_sampling": 0.25,
        },
    }
    return profile, trajectory, prediction, observed


def test_operator_com_velocity_ke_quantile_distribution_and_invalid_mask(tmp_path: Path) -> None:
    profile, trajectory, _prediction, observed = _fixture(tmp_path)

    assert observed["meta"]["initial_mass_denominator_kg"] == 6.0
    assert observed["mass_weighted_com_m"] == [[2.0 / 3.0, 0.0, 0.0], [5.0 / 6.0, 0.0, 0.0]]
    assert observed["mean_velocity_m_s"] == [[14.0 / 6.0, 0.0, 0.0], [2.0, 0.0, 0.0]]
    assert observed["kinetic_energy_j"] == [18.0, 2.0]
    assert observed["mass_quantile_front_m"] == [0.5, 1.0]
    assert observed["mass_distribution_fraction"] == [
        [1.0 / 6.0, 2.0 / 6.0, 3.0 / 6.0],
        [0.0, 1.0 / 6.0, 2.0 / 6.0],
    ]
    assert observed["observed_mass_fraction"] == [1.0, 3.0 / 6.0]
    # Only the active particle with null velocity contributes missing speed;
    # the inactive finite 99 m/s row is excluded before velocity accounting.
    assert observed["velocity_missing_mass_fraction"] == [0.0, 2.0 / 6.0]
    assert profile["qualification"] == MODULE.UNKNOWN
    assert trajectory["velocity_frame"] == "world_inertial"


def test_score_is_source_identity_time_shape_and_budget_bound(tmp_path: Path) -> None:
    profile, trajectory, prediction, observed = _fixture(tmp_path)
    report = MODULE.score_prediction(profile, trajectory, prediction, verify_sources=True)
    assert report["status"] == "PASS"
    assert report["binding_status"] == "PASS_SOURCE_PROFILE_IDENTITY_TIME_BOUND"
    assert report["budget"]["runtime_seconds_or_output_bytes_used"] is False
    assert report["budget"]["source_content_verified"] is True
    assert report["metric_scores"]["kinetic_energy_j"]["status"] == "PASS"

    wrong_shape = copy.deepcopy(prediction)
    wrong_shape["observers"]["kinetic_energy_j"] = [observed["kinetic_energy_j"][0]]
    with pytest.raises(MODULE.ObserverBindingError, match="first dimension"):
        MODULE.score_prediction(profile, trajectory, wrong_shape)

    wrong_time = copy.deepcopy(prediction)
    wrong_time["query_times_s"] = [0.0, 2.0]
    with pytest.raises(MODULE.ObserverBindingError, match="query times"):
        MODULE.score_prediction(profile, trajectory, wrong_time)

    infinite = copy.deepcopy(prediction)
    infinite["observers"]["kinetic_energy_j"][0] = float("inf")
    with pytest.raises(MODULE.ObserverBindingError, match="finite"):
        MODULE.score_prediction(profile, trajectory, infinite)

    wide = copy.deepcopy(prediction)
    wide["tolerances"] = {"kinetic_energy_relative": 1000.0}
    with pytest.raises(MODULE.ObserverBindingError, match="override"):
        MODULE.score_prediction(profile, trajectory, wide)

    wrong_source = copy.deepcopy(trajectory)
    wrong_source["source_binding"]["current_catalog"]["sha256"] = "0" * 64
    with pytest.raises(MODULE.ObserverBindingError, match="source SHA"):
        MODULE.score_prediction(profile, wrong_source, prediction)

    same_size_wrong_content = copy.deepcopy(trajectory)
    original_source = Path(trajectory["source_binding"]["current_catalog"]["path"])
    replacement = tmp_path / "same-size-wrong-content.txt"
    replacement.write_bytes(b"X" * original_source.stat().st_size)
    same_size_wrong_content["source_binding"]["current_catalog"]["path"] = str(replacement)
    same_size_wrong_content["source_binding"]["current_catalog"]["bytes"] = replacement.stat().st_size
    # Keep the profile SHA in the trajectory declaration.  Strict scoring
    # must hash the relocated path and reject this same-size wrong-content case.
    with pytest.raises(MODULE.ObserverBindingError, match="source binding current_catalog SHA differs"):
        MODULE.score_prediction(profile, same_size_wrong_content, prediction)

    missing_prediction = copy.deepcopy(prediction)
    missing_prediction["observers"]["kinetic_energy_j"][0] = None
    missing_report = MODULE.score_prediction(profile, trajectory, missing_prediction)
    assert missing_report["status"] == "FAIL"
    assert missing_report["metric_scores"]["kinetic_energy_j"]["missing_prediction_query_count"] == 1


def test_cli_source_verify_and_no_runtime_budget_substitution(tmp_path: Path) -> None:
    profile, trajectory, prediction, _observed = _fixture(tmp_path)
    profile_path = tmp_path / "profile.json"
    trajectory_path = tmp_path / "trajectory.json"
    prediction_path = tmp_path / "prediction.json"
    observed_path = tmp_path / "observed.json"
    report_path = tmp_path / "report.json"
    profile_path.write_text(json.dumps(profile, indent=2, sort_keys=True))
    trajectory_path.write_text(json.dumps(trajectory, indent=2, sort_keys=True))
    prediction_path.write_text(json.dumps(prediction, indent=2, sort_keys=True))

    assert MODULE.main([
        "observe", "--profile", str(profile_path), "--trajectory", str(trajectory_path),
        "--output", str(observed_path), "--verify-sources",
    ]) == 0
    assert MODULE.main([
        "score", "--profile", str(profile_path), "--trajectory", str(trajectory_path),
        "--prediction", str(prediction_path), "--output", str(report_path), "--verify-sources",
    ]) == 0
    assert json.loads(report_path.read_text())["status"] == "PASS"

    bad_budget = copy.deepcopy(prediction)
    bad_budget["evaluation_seconds"] = 0.01
    bad_budget_path = tmp_path / "bad-budget.json"
    bad_budget_path.write_text(json.dumps(bad_budget))
    with pytest.raises(MODULE.ObserverBindingError, match="runtime seconds"):
        MODULE.score_prediction(profile, trajectory, bad_budget)
