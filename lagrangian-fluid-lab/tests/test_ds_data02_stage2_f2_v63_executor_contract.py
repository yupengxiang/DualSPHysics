from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_stage2_f2_portable_executor_v63.py"
spec = importlib.util.spec_from_file_location("v63_executor_contract", SCRIPT)
assert spec is not None and spec.loader is not None
V63 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V63)
WORKER = Path(__file__).parents[1] / "scripts" / "ds_data02_stage2_f2_native_raw_to_typed_label_v63.py"
worker_spec = importlib.util.spec_from_file_location("v63_worker_contract", WORKER)
assert worker_spec is not None and worker_spec.loader is not None
W63 = importlib.util.module_from_spec(worker_spec)
worker_spec.loader.exec_module(W63)


def test_failed_child_unknown_vs_parent_raw_hash() -> None:
    unknown = V63._execution_contract(parent_hash_before=None,
                                      child={"returncode": 2}, child_result=None)
    assert unknown["parent_hash_raw_opened"] is False
    assert unknown["child_raw_opened"] == "UNKNOWN"
    assert unknown["raw_opened"] == "UNKNOWN"
    assert unknown["hdf5_opened"] == "UNKNOWN"

    parent_known = V63._execution_contract(parent_hash_before={"tree_sha256": "bound"},
                                           child={"returncode": 2}, child_result=None)
    assert parent_known["parent_hash_raw_opened"] is True
    assert parent_known["child_raw_opened"] == "UNKNOWN"
    assert parent_known["raw_opened"] is True
    assert parent_known["hdf5_opened"] == "UNKNOWN"


def test_success_boundary_keeps_child_flags() -> None:
    value = V63._execution_contract(
        parent_hash_before={"tree_sha256": "bound"},
        child={"returncode": 0},
        child_result={"status": "COMPLETED", "raw_opened": True,
                      "hdf5_opened": True, "converter_invoked": True,
                      "label_operator_invoked": False, "model_invoked": False,
                      "cfd_invoked": False},
    )
    assert value["child_success"] is True
    assert value["raw_opened"] is True
    assert value["hdf5_opened"] is True
    assert value["execution_boundary"]["converter_invoked"] is True


def test_worker_summary_joins_report_typed_metadata(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    typed = output / "typed.h5"
    typed.write_bytes(b"small-test-output")
    typed_sha = hashlib.sha256(typed.read_bytes()).hexdigest()
    report = output / "raw-to-typed-to-label-report-v2.json"
    report.write_text(json.dumps({"typed_output": {
        "path": str(typed), "sha256": typed_sha, "bytes": typed.stat().st_size,
    }}) + "\n", encoding="utf-8")
    result = {
        "status": "COMPLETED",
        "raw_to_typed": {"raw_evidence": {"before_tree_sha256": "a", "after_tree_sha256": "a", "file_count": 1}},
        "typed_output": {"path": str(typed), "sha256": typed_sha},
        "execution_boundary": {"raw_opened": True, "hdf5_opened": True,
                                "converter_invoked": True, "label_operator_invoked": True,
                                "model_invoked": False, "cfd_invoked": False},
    }
    summary = W63._worker_summary(result, output)
    assert summary["typed_output_report_contract"]["sha256"] == typed_sha
    assert summary["typed_output_report_contract"]["bytes"] == typed.stat().st_size
    assert summary["typed_output_report_sha256"] == hashlib.sha256(report.read_bytes()).hexdigest()

    report.write_text(json.dumps({"typed_output": {
        "path": str(typed), "sha256": "0" * 64, "bytes": typed.stat().st_size,
    }}) + "\n", encoding="utf-8")
    with pytest.raises(W63.V63WorkerError, match="typed-output report contract"):
        W63._worker_summary(result, output)
