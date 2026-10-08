import copy
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_no_model_evaluator_v2.py"
FROZEN = ROOT / "campaigns/ds-data-02/stage2/replay/v15/f2-s1-replay-request-v15-001.json"


def _module():
    spec = importlib.util.spec_from_file_location("no_model_v2_test_module", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _fixture(module):
    frozen = json.loads(FROZEN.read_text())
    profile = frozen["observer_profile"]
    source = {
        "current_catalog_sha256": profile["current_binding_sha256"],
        "trajectory_h5_producer_sha256": profile["trajectory_producer_sha256"],
        "source_files": profile["source_file_sha256"],
    }
    frames = []
    for frame, time in zip(profile["query_frame_indices"], profile["query_times_s"]):
        frames.append({
            "frame": frame,
            "time_s": time,
            "mass_weighted_com_m": [0.1, 0.2, 0.3],
            "mass_weighted_mean_velocity_m_s": [0.0, 0.0, 0.0],
            "mass_weighted_kinetic_energy_J": 0.0,
            "mass_quantile_front_m": {str(q): 0.1 for q in profile["mass_quantiles"]},
            "mass_distribution_kg": [0.0, 0.0, profile["mass_denominator_kg"], 0.0],
            "position_frame": "body",
            "velocity_frame": "world_inertial",
        })
    result = {
        "schema": module.RESULT_SCHEMA,
        "case_identity": frozen["case_identity"],
        "source_binding": source,
        "observer_profile": {"sha256": profile["sha256"]},
        "initial_mass_denominator": {
            "denominator_kg": profile["mass_denominator_kg"],
        },
        "frame_observations": frames,
        "labels": [{"status": "observed", "event_time_s": 1.0}],
    }
    return result, profile


def test_macro_operator_self_test_and_scientific_counterexamples():
    module = _module()
    result, profile = _fixture(module)
    passed = module.score_macro_prediction(
        result, module.macro_prediction_from_result(result, profile), profile)
    assert passed["status"] == "PASS"
    assert passed["checks"]["velocity"] is True
    assert passed["checks"]["kinetic_energy"] is True
    assert passed["checks"]["mass_front"] is True
    assert passed["checks"]["mass_distribution"] is True

    wrong_velocity = module.score_macro_prediction(
        result, module.macro_prediction_from_result(result, profile, mutation="wrong_velocity"), profile)
    assert wrong_velocity["status"] == "FAIL"
    assert wrong_velocity["checks"]["velocity"] is False

    wrong_time = module.score_macro_prediction(
        result, module.macro_prediction_from_result(result, profile, mutation="wrong_time"), profile)
    assert wrong_time["status"] == "FAIL"
    assert wrong_time["checks"]["event_time"] is False

    wrong_budget = module.score_macro_prediction(
        result, module.macro_prediction_from_result(result, profile, mutation="wrong_budget"), profile)
    assert wrong_budget["status"] == "FAIL"
    assert wrong_budget["checks"]["time_integration_budget"] is False


def test_shape_and_source_are_binding_errors():
    module = _module()
    result, profile = _fixture(module)
    for mutation in ("wrong_shape", "wrong_source"):
        prediction = module.macro_prediction_from_result(result, profile, mutation=mutation)
        try:
            module.score_macro_prediction(result, prediction, profile)
        except module.EvaluatorV2BindingError:
            pass
        else:
            raise AssertionError(f"{mutation} must be a binding error")


def test_request_hash_excludes_only_self_hash():
    module = _module()
    value = {"schema": module.REQUEST_SCHEMA, "status": "DEVELOPMENT", "sha256": "stale"}
    assert module.canonical_sha(value) == module.canonical_sha({**value, "sha256": "different"})
