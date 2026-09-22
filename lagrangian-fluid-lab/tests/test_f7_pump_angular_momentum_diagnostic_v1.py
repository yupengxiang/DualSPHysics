from __future__ import annotations

import json
from pathlib import Path

from scripts.f7_pump_angular_momentum_diagnostic_v1 import build_diagnostic


ROOT = Path(__file__).resolve().parents[1]
TRAJECTORY = ROOT / "campaigns/core-v1/evidence/f7-pump-runtime-canary-dp0020-t0p55/trajectory.h5"
CONTROL = ROOT / "campaigns/core-v1/evidence/f7-pump-runtime-canary-dp0020-t0p55/control-sidecar.h5"
OUTPUT = ROOT / "campaigns/core-v1/evidence/f7-pump-runtime-canary-dp0020-t0p55/angular-momentum-diagnostic-v1.json"


def test_diagnostic_is_observational_and_keeps_torque_gate_closed() -> None:
    result = build_diagnostic(TRAJECTORY, CONTROL)
    assert result["schema"] == "core.f7.pump.angular_momentum_diagnostic.v1"
    assert result["status"] == "diagnostic_only_torque_unresolved"
    assert result["qualification_credit"] == 0
    assert result["gates"]["nonzero_motion_observed"] is True
    assert result["gates"]["finite_difference_response_observed"] is True
    assert result["gates"]["direct_torque_dataset_present"] is False
    assert result["gates"]["pump_independence_gate"] is False
    assert result["protected_state_mutation"]["registry"] == 0
    assert result["protected_state_mutation"]["denominator"] == 0


def test_committed_diagnostic_binds_the_two_canary_sources() -> None:
    assert OUTPUT.is_file()
    value = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert value["inputs"]["trajectory"]["sha256"]
    assert value["inputs"]["control_sidecar"]["sha256"]
    assert value["physical_torque_claim"] is False
    assert value["qualification_credit"] == 0
