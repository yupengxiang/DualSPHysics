from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_no_model_evaluator_v4.py"
V3_REQUEST = ROOT / (
    "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v26/"
    "f2-s1-no-model-evaluator-v3-actual-request-002.json"
)
RAW_REPORT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/"
    "F2_S1_NATIVE_RAW_TO_TYPED_COMPARE_LABEL_V4/"
    "f2-s1-native-raw-to-typed-compare-label-v4-primary-001/comparison-v4/native-v2/"
    "raw-to-typed-to-label-report-v2.json"
)
PROOF = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab") / (
    "campaigns/ds-data-02/stage2/checkpoints/"
    "F2_NATIVE_RAW_TO_TYPED_LABEL_INDEPENDENT_VERIFICATION_001.json"
)


def _load():
    spec = importlib.util.spec_from_file_location("ds02_evaluator_v4_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v4_accepts_actual_raw_to_typed_to_label_report_and_strict_proof() -> None:
    v4 = _load()
    raw = json.loads(RAW_REPORT.read_text())
    proof = json.loads(PROOF.read_text())
    result = {"reconstruction_binding": {
        "raw_tree_sha256": proof["raw_tree_evidence"]["expected_raw_tree_sha256"]
    }}
    checked = v4._validate_actual_raw_report(
        result, proof["labels"]["v16_sha256"], proof, PROOF, raw, v4.file_sha256(RAW_REPORT))
    assert checked["raw_report_schema"] == "ds02.stage2.f2-native-raw-to-typed-to-label-report.v2"
    assert checked["full401_exact"] is True
    assert checked["typed_reconstruction_sha256"] == proof["reconstructed_H5"]["sha256"]


def test_v4_request_is_additive_and_canonical(tmp_path: Path) -> None:
    v4 = _load()
    output = tmp_path / "evaluator-v4.json"
    request = v4.build_request(V3_REQUEST, output)
    assert request["schema"] == "ds02.stage2.f2-no-model-evaluator-request.v4"
    assert request["sha256"] == v4.canonical_sha(request)
    assert request["adapter"]["requires_complete_raw_to_typed_and_typed_to_label"] is True
    assert any(item.get("role") == "evaluator_v4" for item in request["input_files"])
    assert request["raw_to_label_report"]["path"] == str(RAW_REPORT)


def test_v4_rejects_missing_actual_stage(tmp_path: Path) -> None:
    v4 = _load()
    raw = json.loads(RAW_REPORT.read_text())
    raw["typed_to_label"] = None
    proof = json.loads(PROOF.read_text())
    result = {"reconstruction_binding": {
        "raw_tree_sha256": proof["raw_tree_evidence"]["expected_raw_tree_sha256"]
    }}
    with pytest.raises(v4.v3.v2.EvaluatorV2BindingError, match="stage bindings"):
        v4._validate_actual_raw_report(
            result, proof["labels"]["v16_sha256"], proof, PROOF, raw, "0" * 64)
