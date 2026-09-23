from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f8_r004_cpu_native_preflight_authorization_v1 as authorization
from scripts import f8_r004_cpu_native_preflight_execute_v1 as executor
from scripts import f8_r004_cpu_native_preflight_runner_v1 as runner

ROOT = Path(__file__).resolve().parents[1]


def test_authorization_is_hash_bound_to_v2_materialization_and_zero_credit() -> None:
    value = authorization.build_authorization()
    assert value["scope_id"].endswith("R004")
    assert value["qualification_credit"] == 0
    assert value["single_input"]["r001_r002_r003_input_or_output_reused"] is False
    assert value["control_dependency_copy"]["definition_relative_reference"] == "F8_OPC_q0p500_r004_acceleration.csv"
    assert value["permissions"]["cpu_gencase"] is True
    assert value["permissions"]["solver"] is False
    assert value["permissions"]["worker"] is False


def test_runner_is_r004_only_and_builds_colocated_preflight_plan() -> None:
    value = authorization.build_authorization()
    with pytest.raises(ValueError, match="registered F8 r004 output namespace"):
        runner.build_execution_plan(ROOT / "wrong-output")
    assert value["output_namespace"]["path"].endswith("r004/cpu-native-preflight-v1")


def test_executor_refuses_namespace_substitution_and_forbids_solver() -> None:
    with pytest.raises(ValueError, match="registered F8 r004 output namespace"):
        executor.run_once(ROOT / "wrong-output")
    source = (ROOT / "scripts/f8_r004_cpu_native_preflight_execute_v1.py").read_text(encoding="utf-8")
    assert "DualSPHysics5.4CPU_linux64" not in source
    assert '"solver_invoked": False' in source
    assert '"worker_started": False' in source
    assert "generated_colocated_control_copy" in source


def test_authorization_writer_is_immutable(tmp_path: Path) -> None:
    target = tmp_path / "authorization.json"
    authorization.write_authorization(target)
    with pytest.raises(FileExistsError, match="immutable F8 r004 authorization"):
        authorization.write_authorization(target)


def test_r004_preflight_receipt_is_zero_credit_when_present() -> None:
    path = ROOT / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r004/cpu-native-preflight-v1/receipt.json"
    if not path.is_file():
        pytest.skip("preflight has not been executed yet")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    assert receipt["scope_id"].endswith("R004")
    assert receipt["qualification_credit"] == 0
    assert receipt["input_constantsdef"]["checks"]["hswl_explicit_auto_zero"] is True
    assert receipt["execution_controls"]["solver_invoked"] is False
    assert receipt["execution_controls"]["gpu_invoked"] is False
    assert receipt["execution_controls"]["worker_started"] is False
