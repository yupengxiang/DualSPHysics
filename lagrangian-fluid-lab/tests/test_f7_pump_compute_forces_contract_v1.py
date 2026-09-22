from __future__ import annotations

import json

from scripts.f7_pump_compute_forces_contract_v1 import OUTPUT, build_contract


def test_compute_forces_contract_is_explicitly_unexecuted() -> None:
    result = build_contract()
    assert result["status"] == "root_review_only_pending_native_bi4_and_admission"
    assert result["execution"] == {
        "authorized": False,
        "executed": False,
        "native_bi4_present": False,
        "solver_or_queue_mutation": 0,
    }
    assert "-onlymk:2" in result["command_template"]
    assert result["root_gates"]["energy_consistency"] is True


def test_committed_contract_binds_official_inputs() -> None:
    assert OUTPUT.is_file()
    result = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert result["schema"] == "core.f7.pump.compute_forces_contract.v1"
    assert result["bindings"]["compute_forces_help"]["sha256"]
    assert result["bindings"]["pump_cpu_wrapper"]["sha256"]
