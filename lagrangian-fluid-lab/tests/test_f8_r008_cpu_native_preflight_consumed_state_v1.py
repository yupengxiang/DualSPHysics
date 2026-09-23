from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f8_r008_cpu_native_preflight_authorization_v1 as authorization
from scripts import f8_r008_cpu_native_preflight_execute_v1 as execute


LAB = Path(__file__).resolve().parents[1]
SCOPE = LAB / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008"


def test_consumed_r008_preflight_is_auditable_but_cannot_be_reauthorized() -> None:
    sealed = execute.load_authorization()
    receipt = json.loads((SCOPE / "cpu-native-preflight-v3/receipt.json").read_text())
    lock = json.loads((SCOPE / "cpu-native-preflight-v3/one-shot-lock.json").read_text())

    assert sealed["qualification_credit"] == 0
    assert receipt["status"] == "cpu_native_preflight_passed_zero_credit"
    assert receipt["execution_controls"]["cpu_gencase_invoked"] is True
    assert receipt["execution_controls"]["native_decode_invoked"] is True
    assert receipt["execution_controls"]["solver_invoked"] is False
    assert receipt["execution_controls"]["worker_started"] is False
    assert lock["same_input_retry"] is False
    assert lock["gencase_invocation_budget"] == 1
    assert lock["native_decode_invocation_budget"] == 1
    assert lock["solver_invocation_budget"] == 0

    with pytest.raises(FileExistsError, match="runtime output namespace must remain unused"):
        authorization.build_authorization()
