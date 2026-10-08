from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_no_model_evaluator_v3.py"
ACTUAL_RESULT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/"
    "F2_S1_NATIVE_RAW_TO_TYPED_COMPARE_LABEL_V4/"
    "f2-s1-native-raw-to-typed-compare-label-v4-primary-001/"
    "comparison-v4/native-v2/v16-reconstructed-label-result-v2.json"
)


def _load():
    spec = importlib.util.spec_from_file_location("evaluator_v3_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_actual_v16_denominator_adapter_is_explicit_and_in_memory_only() -> None:
    if not ACTUAL_RESULT.is_file():
        pytest.skip("source-bound v16 result is unavailable in this checkout")
    module = _load()
    raw = json.loads(ACTUAL_RESULT.read_text(encoding="utf-8"))
    adapted, evidence = module.adapt_v16_result(raw)
    assert raw["initial_mass_denominator"] != adapted["initial_mass_denominator"]
    assert raw["initial_mass_denominator"].get("initial_fluid_mass_kg") is None
    assert adapted["initial_mass_denominator"]["initial_fluid_mass_kg"] == pytest.approx(
        21.114001002861187)
    assert adapted["initial_mass_denominator"]["initially_absent_count"] == 0
    assert evidence["source_result_unchanged"] is True
    assert evidence["in_memory_only"] is True
    assert raw["labels"][0]["status"] in {"observed", "right_censored", "failed_before_observation"}


@pytest.mark.parametrize("mutation", ["bad_string_alias", "bad_initial_missing", "bad_frame_zero"])
def test_actual_v16_adapter_rejects_ambiguous_denominator_mutations(mutation: str) -> None:
    if not ACTUAL_RESULT.is_file():
        pytest.skip("source-bound v16 result is unavailable in this checkout")
    module = _load()
    raw = json.loads(ACTUAL_RESULT.read_text(encoding="utf-8"))
    bad = copy.deepcopy(raw)
    if mutation == "bad_string_alias":
        bad["initial_mass_denominator"]["initial_fluid_mass_kg"] = "21.114001002861187"
    elif mutation == "bad_initial_missing":
        bad["initial_mass_denominator"]["initial_missing_mass_kg"] = 0.003
    else:
        frame = next(item for item in bad["frame_observations"] if item["frame"] == 0)
        frame["initial_missing_mass_bucket_kg"] = 0.001
    with pytest.raises(module.EvaluatorV3BindingError):
        module.adapt_v16_result(bad)


def test_v3_request_schema_is_distinct_from_consumed_v2() -> None:
    module = _load()
    assert module.REQUEST_SCHEMA == "ds02.stage2.f2-no-model-evaluator-request.v3"
    assert module.REPORT_SCHEMA == "ds02.stage2.f2-no-model-evaluator-report.v3"
