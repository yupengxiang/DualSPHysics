import copy
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_portable_no_model_evaluator_v1.py"


def _module():
    spec = importlib.util.spec_from_file_location("portable_evaluator_v1_test_module", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _nested_result(module):
    return {
        "schema": module.PORTABLE_RESULT_SCHEMA,
        "trajectory_read": True,
        "runner_status": "COMPLETE_PROVISIONAL_H5_READ",
        "original_path_fallback": "FORBIDDEN",
        "model_invoked": False,
        "typed_replay_scope": {"raw_to_label_complete": False},
    }


def _report(module, result):
    value = {
        "schema": module.ORCHESTRATION_SCHEMA,
        "status": "COMPLETE_RAW_REPLAY_DEVELOPMENT_UNKNOWN",
        "request": {"path": "/tmp/v7-request.json", "sha256": "a" * 64},
        "private_subprocess": {"fresh_interpreter": True, "forbidden_module_files": []},
        "stages": {"raw_to_typed_loader": {"result": result}},
        "original_path_fallback": "FORBIDDEN",
        "os_open_audit_required": True,
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    value["sha256"] = module.canonical_sha(value)
    return value


def test_completed_report_extracts_the_nested_v15_result_without_path_fallback():
    module = _module()
    result = _nested_result(module)
    report = _report(module, result)
    assert module.extract_portable_result(report) == result
    checked = module.validate_orchestration_report(report)
    assert checked["private_interpreter"] is True
    assert checked["forbidden_module_files"] == []
    assert checked["nested_result_canonical_sha256"] == module.canonical_value_sha(result)


def test_pending_or_promoted_orchestration_is_rejected():
    module = _module()
    result = _nested_result(module)
    report = _report(module, result)
    report["status"] = "READY_FOR_PARENT_IO_SLOT"
    report["sha256"] = module.canonical_sha(report)
    try:
        module.validate_orchestration_report(report)
    except module.PortableEvaluatorBindingError as error:
        assert "completed" in str(error)
    else:
        raise AssertionError("pending portable result must not become evaluator input")


def test_typed_result_requires_explicit_non_raw_scope_and_no_model():
    module = _module()
    frozen = {"case_identity": {"family_id": "F2"}, "observer_profile": {"sha256": "0" * 64}}
    result = _nested_result(module)
    # The deep source/profile checks are intentionally not reached by this
    # guard: an explicitly raw-complete result belongs to the native proof
    # evaluator and must not be accepted as portable typed-only evidence.
    result["typed_replay_scope"]["raw_to_label_complete"] = True
    try:
        module.validate_portable_result(result, frozen)
    except module.PortableEvaluatorBindingError as error:
        assert "typed-replay-only" in str(error)
    else:
        raise AssertionError("raw-complete result must be rejected by portable evaluator")


def test_report_self_hash_is_sensitive_to_nested_result_change():
    module = _module()
    result = _nested_result(module)
    report = _report(module, result)
    changed = copy.deepcopy(report)
    changed["stages"]["raw_to_typed_loader"]["result"]["runner_status"] = "FAILED"
    assert module.canonical_sha(changed) != report["sha256"]
