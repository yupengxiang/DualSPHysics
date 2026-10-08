from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_typed_only_evaluator_parent_v3_current_bound.py"
SHIM = ROOT / "scripts/ds_data02_stage2_f2_typed_only_evaluator_child_shim_v1.py"
BASE_REQUEST = ROOT / "campaigns/ds-data-02/stage2/evaluator/v2/f2-s1-typed-evaluator-parent-v2-current-root-061-001.json"
CURRENT_BINDING = ROOT / "campaigns/ds-data-02/stage2/evaluator/v2/f2-s1-current-catalog-binding-v1-001.json"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")


def _load(path: Path):
    spec = importlib.util.spec_from_file_location("typed_parent_v3_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V3 = _load(SCRIPT)


def test_plain_typed_request_product_does_not_require_request_envelope() -> None:
    typed = {"result": {"path": "/tmp/result.json", "sha256": "a" * 64},
             "proof": {"status": "UNKNOWN"}}
    product = V3._typed_product(typed, completed=False)
    assert product["request_path"] == "/tmp/result.json"
    assert product["result_sha256"] == "a" * 64
    assert product["content_sha_verified_by_child"] is False


def test_forward_builder_defers_current_content_hash(tmp_path: Path, monkeypatch) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("CURRENT content validation happened before reservation")

    monkeypatch.setattr(V3.CURRENT, "validate_binding", fail_if_called)
    output = tmp_path / "v3-request.json"
    result = V3.build_forward_request(
        base_request=BASE_REQUEST, current_binding=CURRENT_BINDING, output=output,
        parent_attempt_id="typed-v3-deferred-current-test",
        supervisor_output_root=Path("/var/tmp/ds02-stage2") / "typed-v3-deferred-current-test",
        home_receipt=tmp_path / "parent-receipt.json", max_wall_seconds=30.0,
        allow_missing_parent=True)
    value = json.loads(output.read_text(encoding="utf-8"))
    assert result["hdf5_or_bi4_read"] is False
    assert value["execution"]["current_source_validation_phase"] == "AFTER_PARENT_RESERVATION"
    assert value["execution"]["pre_reservation_scientific_content_hash"] is False
    assert value["current_catalog_binding"]["historical_result_current_catalog_sha256"] == "aabfb1e55e47df73276d2bfc053839bd2bce5792330a82a95ad561a6dcde2972"
    roles = {item["role"]: item for item in value["static_bindings"]}
    assert roles["current_catalog_source"]["content_hash_phase"] == "AFTER_PARENT_RESERVATION"
    assert value["sha256"] == V3.canonical_sha(value)


def test_cpu_delta_uses_cgroup_evidence_without_double_counting() -> None:
    start = {"process_seconds": 0.5, "children_seconds": 0.2,
             "cgroup_usage_seconds": 10.0, "cgroup_cpu_stat_path": "/cg/cpu.stat"}
    end = {"process_seconds": 0.9, "children_seconds": 0.3,
           "cgroup_usage_seconds": 18.765324, "cgroup_cpu_stat_path": "/cg/cpu.stat"}
    value = V3._cpu_delta(start, end)
    assert value["process_rusage_delta_seconds"] == pytest.approx(0.4)
    assert value["children_rusage_delta_seconds"] == pytest.approx(0.1)
    assert value["cgroup_usage_delta_seconds"] == pytest.approx(8.765324)
    assert value["charge_cpu_seconds"] == pytest.approx(8.765324)


def test_real_strace_child_shim_preserves_direct_parent_contract(tmp_path: Path) -> None:
    evaluator = tmp_path / "tiny-evaluator.py"
    evaluator.write_text(
        "import argparse, json, os\n"
        "p=argparse.ArgumentParser(); p.add_argument('run'); p.add_argument('--request'); "
        "p.add_argument('--output'); p.add_argument('--parent-pid', type=int); "
        "p.add_argument('--max-wall-seconds'); a=p.parse_args()\n"
        "assert os.getppid() == a.parent_pid\n"
        "json.dump({'status':'PASS_DEVELOPMENT_TYPED_ONLY_OPERATOR_TRIAL_V1'}, open(a.output,'w'))\n",
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
    assert json.loads(output.read_text(encoding="utf-8"))["status"].startswith("PASS_")
    traces = list(tmp_path.glob("tiny-trace*"))
    assert traces and all(path.stat().st_size >= 0 for path in traces)
