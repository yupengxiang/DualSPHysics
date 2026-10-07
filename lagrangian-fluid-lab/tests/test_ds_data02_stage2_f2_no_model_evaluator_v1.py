import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_no_model_evaluator_v1.py"


def _module():
    spec = importlib.util.spec_from_file_location("no_model_v1_test_module", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_actual_typed_result_operator_trial_and_counterexamples(tmp_path):
    module = _module()
    result = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_S1_PORTABLE_TYPED_ONLY_FULL401_REPLAY_V26/f2-s1-portable-typed-only-full401-v26-primary-001/f2-s1-typed-only-full401-result-v26.json")
    request = ROOT / "campaigns/ds-data-02/stage2/replay/v15/f2-s1-replay-request-v15-001.json"
    trial_request_path = ROOT / "campaigns/ds-data-02/stage2/evaluator/v1/f2-s1-no-model-evaluator-request-v1-001.json"
    trial_request = module.load_json(trial_request_path)
    assert result.is_file()
    report = module.run_trial(trial_request, output=tmp_path / "report.json")
    assert report["status"] == "PASS_OPERATOR_TRIAL_WITH_EXPECTED_COUNTEREXAMPLES"
    assert report["cases"]["pass"]["status"] == "PASS"
    assert report["cases"]["status_mismatch"]["status"] == "FAIL"
    assert report["cases"]["time_mismatch"]["status"] == "FAIL"
    assert report["model_invoked"] is False
    assert report["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    assert report["source_profile_binding"]["v15_stat_validation"]["trajectory_content_read"] is False
    assert request.is_file()


def test_wrong_result_source_is_binding_error():
    module = _module()
    result_path = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_S1_PORTABLE_TYPED_ONLY_FULL401_REPLAY_V26/f2-s1-portable-typed-only-full401-v26-primary-001/f2-s1-typed-only-full401-result-v26.json")
    request_path = ROOT / "campaigns/ds-data-02/stage2/replay/v15/f2-s1-replay-request-v15-001.json"
    result = module.load_json(result_path)
    request = module.load_json(request_path)
    result["source_binding"] = dict(result["source_binding"])
    result["source_binding"]["current_catalog_sha256"] = "0" * 64
    try:
        module.validate_stat_source_profile(result, request, request["observer_profile"])
    except module.EvaluatorBindingError as error:
        assert "source binding differs" in str(error)
    else:
        raise AssertionError("wrong source identity must be a binding error")

