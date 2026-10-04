#!/usr/bin/env python3
"""Static fresh067 checks; never launch jobs or decode native/CSV arrays."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BINDING = ROOT / "qualification-binding.json"
AUDIT_CONTRACT = ROOT / "audit-contract.json"
WORKER = ROOT / "workers/audit_f6_endpoint_floatinginfo_state0_v1.py"
REQUESTS = sorted((ROOT / "requests").glob("f6_omega_*_full12_qualification_request.json"))


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), path
    return value


def load_worker():
    spec = importlib.util.spec_from_file_location("f6_fresh067_floatinginfo_worker", WORKER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_package_is_disabled_but_qa090_gate_is_terminal() -> None:
    binding = load_json(BINDING)
    assert binding["schema"] == "ds02.f6.stage1-omega-full12-qualification-binding.v1"
    assert binding["status"] == "source_only_disabled"
    assert binding["launch"] is False
    assert binding["launch_allowed"] is False
    gate = binding["qa090_gate"]
    assert gate["observed_receipt_status"] == "completed"
    assert gate["observed_returncode"] == 0
    assert gate["observed_index_pass"] is True
    assert gate["required_index_status"] == "initial-native-integrity-pass"
    assert len(gate["case_reports"]) == 2
    assert all(row["pass"] is True and row["failed_checks"] == [] for row in gate["case_reports"])
    assert all(Path(row["path"]).is_file() for row in gate["case_reports"])
    assert Path(gate["receipt"]).is_file()
    assert Path(gate["index"]).is_file()


def test_requests_bind_exact_mother_recipe_and_actual_073_inputs() -> None:
    assert len(REQUESTS) == 2
    binding = load_json(BINDING)
    mother_receipt_path = Path(binding["mother_solver"]["receipt"])
    mother_receipt = load_json(mother_receipt_path)
    mother_request_command = mother_receipt["request"]["command"]
    assert mother_request_command == binding["mother_solver"]["request_command"]
    assert mother_receipt["request"]["cwd"] == binding["mother_solver"]["request_cwd"]

    by_case = {row["endpoint_id"]: row for row in binding["endpoints"]}
    for request_path in REQUESTS:
        request = load_json(request_path)
        endpoint_id = request["topphysical_case_id"]
        endpoint = by_case[endpoint_id]
        assert request["schema"] == "ds02.runner-request.v2"
        assert request["kind"] == "qualification"
        assert request["launch"] is False
        assert request["launch_allowed"] is False
        assert request["status"] == "source_only_disabled"
        assert request["case_id"] == endpoint_id
        assert request["physical_case_id"] == endpoint["physical_case_id"]
        assert request["physical_condition_sha256"] == endpoint["physical_condition_sha256"]
        assert request["expected_native_frames"] == 241
        assert request["physical_window_s"] == [0.0, 12.0]
        assert request["command"][0] == mother_request_command[0]
        assert request["command"][-2:] == ["-tmax:12", "-tout:0.05"]
        assert request["mother_request_command"] == mother_request_command
        assert request["runtime_command_template"][1] == "-gpu:0"
        assert request["cwd"] == binding["mother_solver"]["request_cwd"]
        assert not any(
            argument.startswith(("-dbc", "-motion", "-forcing", "-cpu"))
            for argument in request["command"]
        )
        assert request["gencase_prefix"] == endpoint["gencase_prefix"]
        assert request["gencase_receipt"] == endpoint["gencase_receipt"]
        assert request["gencase_receipt_sha256"] == endpoint["gencase_receipt_sha256"]
        receipt = load_json(Path(request["gencase_receipt"]))
        assert receipt["status"] == "completed"
        assert receipt["returncode"] == 0
        assert receipt["total_particles"] == 417505
        assert receipt["fluid_particles"] == 327680
        assert receipt["solver_dimension_from_gencase"] == 3
        assert request["gencase_actual"] == endpoint["gencase_actual"]
        assert len(request["input_files"]) == len(set(request["input_files"]))
        assert set(request["input_files"]) == set(request["input_sha256"])
        assert all(Path(path).is_file() for path in request["input_files"])
        assert all(len(value) == 64 for value in request["input_sha256"].values())
        assert request["qa090_gate"] == binding["qa090_gate"]


def test_owner_case_and_condition_are_root073_values() -> None:
    binding = load_json(BINDING)
    for endpoint in binding["endpoints"]:
        owner = load_json(Path(endpoint["canonical_owner"]))
        assert owner["physical_case_id"] == endpoint["topphysical_case_id"]
        assert owner["physical_condition_sha256"] == endpoint["physical_condition_sha256"]
        assert owner["source_plan_condition_sha256"] == endpoint["source_plan_condition_sha256"]
        assert owner["source_definition"] == endpoint["source_definition"]
        assert owner["expected_frames"] == 241
        assert owner["full_event_window_s"] == [0, 12]


def test_floatinginfo_worker_is_endpoint_derived_and_bounded() -> None:
    source = WORKER.read_text(encoding="utf-8")
    worker = load_worker()
    assert worker.SCHEMA == "ds02.f6.endpoint-floatinginfo-state0-omega-audit-result.v1"
    assert "h5py" not in source.lower()
    assert "numpy" not in source.lower()
    assert "PartVTK" not in source
    assert "DualSPHysics5.4" not in source
    assert "FloatingInfo_linux64" not in source
    assert "0.08" not in source
    assert "0.12" not in source
    assert "bounded_prefix_only" in source
    assert "initial_angular_velocity_rad_s" in source


def test_audit_contract_has_no_qualification_authority() -> None:
    contract = load_json(AUDIT_CONTRACT)
    assert contract["status"] == "source_only_disabled"
    assert contract["launch_allowed"] is False
    assert contract["independent_case_count_increment"] == 0
    assert contract["qualification_recipe"]["expected_native_frames"] == 241
    assert contract["qualification_recipe"]["tmax_s"] == 12.0
    assert contract["qualification_recipe"]["tout_s"] == 0.05


if __name__ == "__main__":
    test_package_is_disabled_but_qa090_gate_is_terminal()
    test_requests_bind_exact_mother_recipe_and_actual_073_inputs()
    test_owner_case_and_condition_are_root073_values()
    test_floatinginfo_worker_is_endpoint_derived_and_bounded()
    test_audit_contract_has_no_qualification_authority()
    print("F6 fresh067 static contract: PASS")
