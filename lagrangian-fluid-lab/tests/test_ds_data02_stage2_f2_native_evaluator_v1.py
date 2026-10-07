from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import ds_data02_stage2_f2_native_evaluator_v1 as evaluator  # noqa: E402


V4_REQUEST = (Path(__file__).resolve().parents[1] /
              "campaigns/ds-data-02/stage2/native-reconstruction/v4/"
              "f2-s1-native-raw-to-typed-reference-compare-request-v4-002.json")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v4_request_source_only_gate_passes_without_h5_read() -> None:
    request, bound = evaluator._validate_v4_request(V4_REQUEST)
    assert request["qualification"] == evaluator.UNKNOWN_QUALIFICATION
    assert bound["base"]["schema"] == "ds02.stage2.f2-native-raw-to-typed-to-label-request.v2"
    assert bound["v15_path"].name == "ds_data02_stage2_f2_replay_v15.py"


def test_noncomplete_v4_comparison_is_rejected_before_label_or_h5_access(tmp_path: Path) -> None:
    report = tmp_path / "failed-v4-report.json"
    payload = {
        "schema": evaluator.V4_REPORT_SCHEMA,
        "status": "REFERENCE_COMPARISON_FAILED_DEVELOPMENT",
        "request": {"path": str(V4_REQUEST.resolve()), "sha256": _sha(V4_REQUEST)},
        "typed_reference_comparison": {"passed": False},
    }
    report.write_text(json.dumps(payload) + "\n")
    with pytest.raises(evaluator.NativeEvaluatorBindingError, match="not complete"):
        evaluator.validate_completed_replay(V4_REQUEST, report)


def test_v15_loader_binds_sibling_v14_module() -> None:
    path = (Path(__file__).resolve().parents[1] /
            "scripts/ds_data02_stage2_f2_replay_v15.py")
    module = evaluator._load_v15(path, evaluator.sha256_file(path))
    assert Path(module.v14.__file__).resolve().parent == path.parent.resolve()
