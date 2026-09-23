from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f8_r002_cpu_native_preflight_authorization_v1 as authorization
from scripts import f8_r002_cpu_native_preflight_execute_v1 as executor


ROOT = Path(__file__).resolve().parents[1]


def test_authorization_is_hash_bound_r002_only_and_zero_credit() -> None:
    value = authorization.build_authorization()
    assert value["scope_id"].endswith("R002")
    assert value["qualification_credit"] == 0
    assert value["single_input"]["old_r001_inputs_or_outputs_reused"] is False
    assert value["permissions"]["cpu_gencase"] is True
    assert value["permissions"]["solver"] is False
    assert value["permissions"]["worker"] is False
    assert value["control_dependency_copy"]["required_generated_copy"].endswith("r002_acceleration.csv")


def test_executor_is_single_namespace_and_refuses_substitution(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="registered F8 r002 output namespace"):
        executor.run_once(tmp_path / "wrong-output")
    source = (ROOT / "scripts/f8_r002_cpu_native_preflight_execute_v1.py").read_text(encoding="utf-8")
    assert "DualSPHysics5.4CPU_linux64" not in source
    assert "solver_invoked\": False" in source
    assert "worker_started\": False" in source
    assert "generated_control_copy" in source


def test_authorization_writer_is_immutable(tmp_path: Path) -> None:
    target = tmp_path / "authorization.json"
    authorization.write_authorization(target)
    with pytest.raises(FileExistsError, match="immutable F8 r002 authorization"):
        authorization.write_authorization(target)


def test_retained_r002_attempt_is_zero_credit_and_does_not_decode_after_gencase_failure() -> None:
    receipt_path = ROOT / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r002/cpu-native-preflight-v1/receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["scope_id"].endswith("R002")
    assert receipt["qualification_credit"] == 0
    assert receipt["execution_controls"]["cpu_gencase_invoked"] is True
    assert receipt["execution_controls"]["native_decode_invoked"] is False
    assert receipt["execution_controls"]["solver_invoked"] is False
    assert receipt["r001_is_immutable_closed_history"]["r001_evidence_mutated"] is False
