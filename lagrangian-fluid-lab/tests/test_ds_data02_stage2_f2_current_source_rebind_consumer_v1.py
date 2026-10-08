from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_current_source_rebind_consumer_v1.py"
TYPED_REQUEST = ROOT / "campaigns/ds-data-02/stage2/evaluator/v2/f2-s1-typed-evaluator-v2-current-root-061-001.json"
REBIND = ROOT / "campaigns/ds-data-02/stage2/evaluator/v3/f2-s1-current-source-rebind-v1-001.json"


def _load():
    spec = importlib.util.spec_from_file_location("current_source_rebind_consumer_v1_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


consumer = _load()


def test_current_bound_typed_request_requires_rebind_sidecar(tmp_path: Path):
    output = tmp_path / "consumer.json"
    value = consumer.validate_request(typed_request=TYPED_REQUEST,
                                      rebind_sidecar=REBIND, output=output)
    assert value["status"] == "PASS_JSON_ONLY_REBIND_CONSUMER_BOUND"
    assert value["actual_current_catalog_sha256"] == consumer.ACTUAL_CURRENT_SHA256
    assert value["historical_overlay_sha256"] == consumer.HISTORICAL_OVERLAY_SHA256
    assert value["hdf5_bi4_raw_read"] is False
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["credit_boundary"]["label_array_values"] == "NOT_REOPENED"
    assert report["sha256"] == consumer.canonical_sha(report)


def test_typed_request_with_unrelated_result_is_rejected(tmp_path: Path):
    request = json.loads(TYPED_REQUEST.read_text(encoding="utf-8"))
    request["result"]["sha256"] = "0" * 64
    request_path = tmp_path / "wrong.json"
    request_path.write_text(json.dumps(request, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(consumer.ConsumerRebindError, match="result SHA differs"):
        consumer.validate_request(typed_request=request_path, rebind_sidecar=REBIND,
                                  output=tmp_path / "bad-output.json")
