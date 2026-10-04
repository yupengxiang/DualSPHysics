#!/usr/bin/env python3
"""Static source-package checks; never invoke PartVTK or read native arrays."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUEST = ROOT / "requests/f6_omega_initial_native_qa_request.json"
BINDING = ROOT / "qa-binding.json"
WORKER = ROOT / "workers/run_f6_initial_native_qa_v1.py"


def load_worker():
    spec = importlib.util.spec_from_file_location("f6_initial_native_qa_worker", WORKER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_request_is_disabled_and_hash_bound() -> None:
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    assert request["schema"] == "ds02.runner-request.v2"
    assert request["cpu_task_kind"] == "audit"
    assert request["launch"] is False
    assert request["launch_allowed"] is False
    assert request["status"] == "source_only_disabled"
    assert request["command"][request["command"].index("--output-root") + 1] == "{attempt_root}/initial-native-qa"
    assert len(request["input_files"]) == len(set(request["input_files"]))
    assert set(request["input_files"]) <= set(request["input_sha256"])
    assert all(len(value) == 64 for value in request["input_sha256"].values())


def test_binding_preserves_two_endpoint_contract() -> None:
    binding = json.loads(BINDING.read_text(encoding="utf-8"))
    assert binding["status"] == "source_only_disabled"
    assert binding["launch_allowed"] is False
    assert binding["independent_case_count_increment"] == 0
    assert [row["endpoint_id"] for row in binding["endpoints"]] == [
        "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S025_DP025",
        "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S200_DP025",
    ]
    assert binding["physical_contract"]["native_support_mass_kg"] == 256.0
    assert binding["physical_contract"]["physical_mass_kg"] == 128.0
    assert binding["physical_contract"]["masspart_kg"] == 0.015625


def test_generated_xml_contract_only() -> None:
    # XML is configuration evidence. This deliberately does not open BI4,
    # H5, CSV, or any native particle array.
    worker = load_worker()
    binding = json.loads(BINDING.read_text(encoding="utf-8"))
    for endpoint in binding["endpoints"]:
        info = worker.xml_contract(
            Path(endpoint["source_definition"]),
            Path(endpoint["generated_xml"]),
            endpoint,
        )
        assert info["all_xml_checks_passed"] is True


def test_worker_is_source_only() -> None:
    source = WORKER.read_text(encoding="utf-8")
    assert "PartVTK_linux64" in source
    assert "FloatingInfo" not in source or "required_followup" in source
    assert "GenCase_linux64" not in source
    assert "h5py" not in source.lower()
    assert "FloatingInfo_linux64" not in source


if __name__ == "__main__":
    test_request_is_disabled_and_hash_bound()
    test_binding_preserves_two_endpoint_contract()
    test_generated_xml_contract_only()
    test_worker_is_source_only()
    print("F6 fresh064 source contract: PASS")
