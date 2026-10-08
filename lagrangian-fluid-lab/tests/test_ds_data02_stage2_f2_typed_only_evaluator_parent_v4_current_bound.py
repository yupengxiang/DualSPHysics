from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
PARENT_SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_typed_only_evaluator_parent_v4_current_bound.py"
EVALUATOR_SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_typed_only_evaluator_v3_current_bound.py"
SHIM = ROOT / "scripts/ds_data02_stage2_f2_typed_only_evaluator_child_shim_v1.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
BASE_REQUEST = ROOT / "campaigns/ds-data-02/stage2/evaluator/v2/f2-s1-typed-evaluator-parent-v2-current-root-061-001.json"
CURRENT_BINDING = ROOT / "campaigns/ds-data-02/stage2/evaluator/v2/f2-s1-current-catalog-binding-v1-001.json"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PARENT = _load(PARENT_SCRIPT, "typed_parent_v4_current_bound_test")
EVALUATOR = _load(EVALUATOR_SCRIPT, "typed_evaluator_v3_current_bound_test")


def test_dual_score_requires_historical_result_hash_and_keeps_real_current_separate(monkeypatch) -> None:
    actual = "d" * 64
    historical = "a" * 64
    result = {"source_binding": {"current_catalog_sha256": historical,
                                  "source_files": {"current_catalog": historical}}}
    frozen = {"current_binding": {"sha256": actual},
              "source_files": [{"role": "current_catalog", "sha256": actual}]}
    seen = {}

    def score(value, shadow):
        seen["sha"] = shadow["current_binding"]["sha256"]
        seen["source"] = shadow["source_files"][0]["sha256"]
        return {"status": "PASS"}

    monkeypatch.setattr(EVALUATOR.V2.V1, "_score_typed_result", score)
    score_value, reconciliation = EVALUATOR._dual_source_score(
        result, frozen, {"current_catalog_sha256": actual,
                         "historical_result_current_catalog_sha256": historical})
    assert seen == {"sha": historical, "source": historical}
    assert frozen["current_binding"]["sha256"] == actual
    assert reconciliation["actual_current_catalog_sha256"] == actual
    assert reconciliation["exact_current_source_claim"] == "NOT_GRANTED_TO_HISTORICAL_RESULT_VIEW"
    assert score_value["current_source_reconciliation"] == reconciliation


def test_dual_score_rejects_result_claiming_actual_current(monkeypatch) -> None:
    with pytest.raises(EVALUATOR.TypedEvaluatorV2CurrentError, match="historical relocated view"):
        EVALUATOR._dual_source_score(
            {"source_binding": {"current_catalog_sha256": "d" * 64,
                                 "source_files": {"current_catalog": "d" * 64}}},
            {"current_binding": {"sha256": "d" * 64},
             "source_files": [{"role": "current_catalog", "sha256": "d" * 64}]},
            {"current_catalog_sha256": "d" * 64,
             "historical_result_current_catalog_sha256": "a" * 64})


def test_bootstrap_cpu_delta_includes_import_and_finalization() -> None:
    start = {"process_seconds": 1.0, "children_seconds": 0.0,
             "cgroup_usage_seconds": 4.0, "cgroup_cpu_stat_path": "/cg/cpu.stat",
             "capture_phase": "FIRST_SCRIPT_LINE_BEFORE_EVALUATOR_CLOSURE_IMPORT"}
    end = {"process_seconds": 2.1, "children_seconds": 0.2,
           "cgroup_usage_seconds": 12.0, "cgroup_cpu_stat_path": "/cg/cpu.stat"}
    value = PARENT._cpu_delta(start, end)
    assert value["charge_cpu_seconds"] == pytest.approx(8.0)
    assert value["cgroup_usage_delta_seconds"] == pytest.approx(8.0)
    assert value["selection"] == "max_process_children_cgroup"


def test_report_product_separates_typed_request_and_result_paths() -> None:
    value = PARENT._typed_product(
        {"result": {"path": "/external/result.json", "sha256": "b" * 64}},
        completed=False, typed_request_path="/input/typed-request.json")
    assert value["request_path"] == "/input/typed-request.json"
    assert value["result_path"] == "/external/result.json"


def test_real_child_shim_rejects_wrong_status_at_parent_boundary(tmp_path: Path) -> None:
    evaluator = tmp_path / "tiny-evaluator.py"
    evaluator.write_text(
        "import argparse, json, os\n"
        "p=argparse.ArgumentParser(); p.add_argument('run'); p.add_argument('--request'); "
        "p.add_argument('--output'); p.add_argument('--parent-pid', type=int); "
        "p.add_argument('--max-wall-seconds'); a=p.parse_args()\n"
        "assert os.getppid() == a.parent_pid\n"
        "json.dump({'status':'FAIL_WRONG_SOURCE'}, open(a.output,'w'))\n",
        encoding="utf-8")
    request = tmp_path / "tiny-request.json"
    request.write_text("{}\n", encoding="utf-8")
    output = tmp_path / "tiny-result.json"
    trace = tmp_path / "tiny-trace"
    command = ["/usr/bin/strace", "-ff", "-e", "trace=%file,%process", "-s", "4096",
               "-o", str(trace), "--", str(PYTHON), "-B", "-I", str(SHIM), "run",
               "--evaluator", str(evaluator), "--request", str(request),
               "--output", str(output), "--python", str(PYTHON),
               "--max-wall-seconds", "10"]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "FAIL_WRONG_SOURCE"
    traces = list(tmp_path.glob("tiny-trace*"))
    assert traces
    # The parent V4 exact-status gate must reject this child result; a child
    # returning zero is not scientific/evaluator success.
    assert json.loads(output.read_text(encoding="utf-8"))["status"] != PARENT.CHILD_PASS_STATUS


def test_forward_builder_registers_v3_child_and_dual_binding(tmp_path: Path) -> None:
    output = tmp_path / "v4-request.json"
    result = PARENT.build_forward_request(
        base_request=BASE_REQUEST, current_binding=CURRENT_BINDING, output=output,
        parent_attempt_id="typed-v4-deferred-current-test",
        supervisor_output_root=Path("/var/tmp/ds02-stage2") / "typed-v4-deferred-current-test",
        home_receipt=tmp_path / "parent-receipt.json", max_wall_seconds=30.0,
        allow_missing_parent=True)
    value = json.loads(output.read_text(encoding="utf-8"))
    roles = {item["role"]: item for item in value["static_bindings"]}
    assert "typed_only_evaluator_v3_current_bound" in roles
    assert value["v4_current_forward"]["dual_current_binding"]["historical_hash_is_runtime_result_provenance_only"] is True
    assert value["current_catalog_binding"]["current_catalog_sha256"] == "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
    assert value["current_catalog_binding"]["historical_result_current_catalog_sha256"] == "aabfb1e55e47df73276d2bfc053839bd2bce5792330a82a95ad561a6dcde2972"
    assert result["hdf5_or_bi4_read"] is False


def test_builder_can_require_existing_parent_attempt(tmp_path: Path) -> None:
    output = tmp_path / "v4-existing-parent.json"
    PARENT.build_forward_request(
        base_request=BASE_REQUEST, current_binding=CURRENT_BINDING, output=output,
        parent_attempt_id="typed-v4-existing-parent-test",
        supervisor_output_root=Path("/var/tmp/ds02-stage2") / "typed-v4-existing-parent-test",
        home_receipt=tmp_path / "parent-receipt.json", max_wall_seconds=30.0,
        allow_missing_parent=False)
    value = json.loads(output.read_text(encoding="utf-8"))
    assert value["parent_resource_binding"]["allow_missing_parent"] is False
