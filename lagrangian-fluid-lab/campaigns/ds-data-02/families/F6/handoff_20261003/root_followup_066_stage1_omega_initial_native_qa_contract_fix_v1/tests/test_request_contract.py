#!/usr/bin/env python3
"""Static fresh066 checks; no PartVTK, BI4, H5, CSV, or native arrays."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUEST = ROOT / "requests/f6_omega_initial_native_qa_contract_fix_request.json"
BINDING = ROOT / "qa-binding.json"
WORKER = ROOT / "workers/run_f6_initial_native_qa_v1.py"


def load_worker():
    spec = importlib.util.spec_from_file_location("f6_fresh066_worker", WORKER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_request_is_disabled_and_complete() -> None:
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    assert request["schema"] == "ds02.runner-request.v2"
    assert request["cpu_task_kind"] == "audit"
    assert request["launch"] is False
    assert request["launch_allowed"] is False
    assert request["status"] == "source_only_disabled"
    assert request["qa086_gate"]["observed_status"] == "failed_before_native_array_read"
    assert request["command"][request["command"].index("--output-root") + 1] == "{attempt_root}/initial-native-qa"
    assert len(request["input_files"]) == len(set(request["input_files"]))
    assert set(request["input_files"]) == set(request["input_sha256"])
    assert all(Path(path).is_file() for path in request["input_files"])
    assert all(len(value) == 64 for value in request["input_sha256"].values())


def test_historical_binding_field_matches_worker() -> None:
    binding = json.loads(BINDING.read_text(encoding="utf-8"))
    assert binding["schema"] == "ds02.f6.stage1-omega-initial-native-qa-binding.v2"
    assert binding["scope_id"] == "root_followup_066_stage1_omega_initial_native_qa_contract_fix_v1"
    assert binding["status"] == "source_only_disabled"
    assert binding["launch_allowed"] is False
    assert "historical_evidence_preserved" not in binding
    assert isinstance(binding["historical_evidence"], list)
    assert len(binding["historical_evidence"]) == 2
    assert {item["id"] for item in binding["historical_evidence"]} == {
        "root_angular_native_qa_review_019",
        "root_angular_native_semantic_review_020",
    }
    assert binding["independent_case_count_increment"] == 0


def test_owner_source_bindings_are_explicit() -> None:
    binding = json.loads(BINDING.read_text(encoding="utf-8"))
    plan = json.loads(Path(binding["source_plan"]["path"]).read_text(encoding="utf-8"))
    plan_rows = {row["endpoint_id"]: row for row in plan["endpoints"]}
    for endpoint in binding["endpoints"]:
        row = plan_rows[endpoint["endpoint_id"]]
        owner = json.loads(Path(endpoint["canonical_owner"]).read_text(encoding="utf-8"))
        assert endpoint["source_plan_condition_sha256"] == row["physical_condition_sha256"]
        assert endpoint["source_definition_sha256"] == row["source_definition_sha256"]
        assert owner["physical_condition_sha256"] == endpoint["physical_condition_sha256"]
        assert owner["source_plan_condition_sha256"] == endpoint["source_plan_condition_sha256"]
        assert owner["source_definition"] == endpoint["source_definition"]


def test_generated_xml_contract_only() -> None:
    # XML configuration is safe source evidence. This test does not open the
    # native BI4 files or execute the worker's PartVTK path.
    worker = load_worker()
    binding = json.loads(BINDING.read_text(encoding="utf-8"))
    for endpoint in binding["endpoints"]:
        info = worker.xml_contract(
            Path(endpoint["source_definition"]),
            Path(endpoint["generated_xml"]),
            endpoint,
        )
        assert info["all_xml_checks_passed"] is True


def test_worker_contract_version_and_source_only_boundary() -> None:
    worker = load_worker()
    source = WORKER.read_text(encoding="utf-8")
    assert worker.BINDING_SCHEMA == "ds02.f6.stage1-omega-initial-native-qa-binding.v2"
    assert worker.SCHEMA.endswith("result.v2")
    assert "GenCase_linux64" not in source
    assert "h5py" not in source.lower()
    assert "FloatingInfo_linux64" not in source


if __name__ == "__main__":
    test_request_is_disabled_and_complete()
    test_historical_binding_field_matches_worker()
    test_owner_source_bindings_are_explicit()
    test_generated_xml_contract_only()
    test_worker_contract_version_and_source_only_boundary()
    print("F6 fresh066 contract fix: PASS")
