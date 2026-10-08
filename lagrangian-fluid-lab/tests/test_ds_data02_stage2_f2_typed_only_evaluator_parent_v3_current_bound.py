from __future__ import annotations

import hashlib
import importlib.util
import json
import os
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


def test_tiny_parent_child_order_is_reserve_then_current_validation(tmp_path: Path, monkeypatch) -> None:
    external = tmp_path / "external"
    home = tmp_path / "home"
    output = external / "attempt"
    receipt = home / "receipt.json"
    trace = output / "trace"
    external.mkdir()
    home.mkdir()
    request_path = tmp_path / "request.json"
    request_path.write_text("{}\n", encoding="utf-8")
    calls: list[tuple[str, object]] = []
    bound = {
        "path": request_path, "request": {"typed_request": {"path": str(tmp_path / "typed.json")}},
        "typed": {"result": {"path": str(tmp_path / "typed-result.json"), "sha256": "a" * 64},
                  "proof": {"status": "UNKNOWN"}},
        "ledger": tmp_path / "ledger.json", "limits": {"home_path": str(home)},
        "external": external, "output_root": output, "receipt": receipt,
        "trace_path": trace, "runtime_path": SCRIPT, "max_wall": 10.0,
        "cleanup_grace": 25.0, "external_estimate": 1024, "home_estimate": 1024,
        "parent_attempt_id": "tiny-v3", "reservation_id": "tiny-reservation",
        "charge_id": "tiny-charge", "allow_missing_parent": True,
        "python": PYTHON, "worktree_root": ROOT.parent,
    }
    parent_bound = {"request": bound["request"], "external": external,
                    "output_root": output, "receipt": receipt, "trace_path": trace,
                    "external_estimate": 1024, "home_estimate": 1024,
                    "reservation_id": "tiny-reservation", "charge_id": "tiny-charge",
                    "parent_attempt_id": "tiny-v3", "allow_missing_parent": True,
                    "limits": bound["limits"], "ledger": bound["ledger"]}
    bound["request"]["execution"] = {"max_wall_seconds": 10.0}
    bound["request"]["python_binding"] = {"literal_invocation_path": str(PYTHON)}

    def validate(path, *, verify_static_content=False):
        calls.append(("validate", verify_static_content))
        return bound

    def current_after(value):
        calls.append(("current", None))
        return tmp_path / "binding.json", {
            "current_catalog_sha256": "d" * 64,
            "historical_result_current_catalog_sha256": "a" * 64,
        }

    def reserve(value):
        calls.append(("reserve", None))
        return {"status": "PARENT_RESERVATION_APPLIED"}

    def charge(value, **kwargs):
        calls.append(("charge", kwargs.get("status")))
        return {"status": "PARENT_CHARGE_APPLIED", "charge": kwargs}

    tiny_child = [str(PYTHON), "-c", "import json; print(json.dumps({'status':'PASS_DEVELOPMENT_TYPED_ONLY_OPERATOR_TRIAL_V1'}))"]
    monkeypatch.setattr(V3, "_validate_request", validate)
    monkeypatch.setattr(V3, "_current_after_reservation", current_after)
    monkeypatch.setattr(V3.P1, "_bound_for_parent", lambda value: parent_bound)
    monkeypatch.setattr(V3.P1, "_install", lambda parent_pid, max_wall: {})
    monkeypatch.setattr(V3.P1, "_restore", lambda old: None)
    monkeypatch.setattr(V3, "_child_command", lambda value, parent_pid: tiny_child)
    monkeypatch.setattr(V3.PARENT, "_reserve", reserve)
    monkeypatch.setattr(V3.PARENT, "_charge", charge)
    monkeypatch.setattr(V3.PARENT, "_report_size_fixed_point", lambda report: 0)
    value = V3.run(request_path, io_slot_approved=True, parent_pid=os.getppid())
    assert value["status"] == "COMPLETED_PARENT_TYPED_ONLY_OPERATOR_UNKNOWN"
    assert [name for name, _ in calls[:4]] == ["validate", "reserve", "validate", "current"]
    report = json.loads(receipt.read_text(encoding="utf-8"))
    assert report["typed_only_product"]["request_path"] == str(tmp_path / "typed-result.json")
