from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_no_model_calibration_contract_v1.py"
SPEC = importlib.util.spec_from_file_location("no_model_calibration_contract_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


CURRENT = ROOT / "campaigns/ds-data-02/stage2/CURRENT336.json"
PROFILE = ROOT / "campaigns/ds-data-02/stage2/replay/v15/f2-s1-observer-profile-v15-001.json"
REQUEST = ROOT / "campaigns/ds-data-02/stage2/evaluator/v1/f2-s1-no-model-evaluator-request-v1-001.json"
REPORT = ROOT / "campaigns/ds-data-02/stage2/evaluator/v1/f2-s1-no-model-evaluator-report-v1-001.json"
LABEL_SOURCE = ROOT / "campaigns/ds-data-02/stage2/review-source/QUALITY_LABEL_SPLIT_ZH.md"


def test_contract_binds_calibrated_profile_and_expected_operator_failures(tmp_path: Path) -> None:
    output = tmp_path / "contract.json"
    result = MODULE.bind_contract(CURRENT, PROFILE, REQUEST, REPORT, LABEL_SOURCE, output)
    contract = json.loads(output.read_text())
    assert result["status"] == "MANUFACTURED_OPERATOR_CALIBRATION_BOUND"
    assert contract["current_binding"]["case_count"] == 336
    assert contract["profile"]["frozen_before_reference"] is True
    assert contract["evaluator_report"]["counterexamples"] == ["status_mismatch", "time_mismatch"]
    assert contract["label_interface"]["first_passage_states"] == [
        "observed", "right_censored", "failed_before_observation",
        "initially_inside", "ambiguous_multiple_crossing",
    ]
    assert contract["qualification"] == MODULE.UNKNOWN


def test_contract_rejects_profile_bound_to_other_current(tmp_path: Path) -> None:
    profile = json.loads(PROFILE.read_text())
    profile["current_binding_sha256"] = "0" * 64
    profile["sha256"] = MODULE.canonical_sha(profile)
    profile_path = tmp_path / "wrong-profile.json"
    profile_path.write_text(json.dumps(profile, sort_keys=True))
    with pytest.raises(MODULE.CalibrationBindingError, match="CURRENT SHA"):
        MODULE.bind_contract(CURRENT, profile_path, REQUEST, REPORT, LABEL_SOURCE, tmp_path / "out.json")


def test_contract_rejects_missing_operator_counterexample(tmp_path: Path) -> None:
    report = json.loads(REPORT.read_text())
    report["cases"]["time_mismatch"]["status"] = "PASS"
    report_path = tmp_path / "bad-report.json"
    report_path.write_text(json.dumps(report, sort_keys=True))
    with pytest.raises(MODULE.CalibrationBindingError, match="counterexamples"):
        MODULE.bind_contract(CURRENT, PROFILE, REQUEST, report_path, LABEL_SOURCE, tmp_path / "out.json")
