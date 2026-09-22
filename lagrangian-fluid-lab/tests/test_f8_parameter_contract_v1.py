from __future__ import annotations

import json

from scripts.f8_parameter_contract_v1 import OUTPUT, build_contract


def test_f8_contract_freezes_body_force_semantics_and_bounds() -> None:
    contract = build_contract()
    assert contract["status"] == "pre_admission_static_contract_frozen"
    assert contract["admission_granted"] is False
    assert contract["forcing_semantics"]["globalgravity"] == 0
    assert contract["parameterization"]["alpha_range"] == [2.0, 8.0]
    assert contract["numerical_limits"]["excluded_fluid_particles"] == 0
    assert contract["error_gates"]["profile_phase_absolute_max_rad"] == 0.15


def test_f8_contract_is_non_executing() -> None:
    controls = build_contract()["execution_controls"]
    assert controls["definition_written"] is False
    assert controls["gencase_invoked"] is False
    assert controls["solver_invoked"] is False
    assert controls["registry_mutation"] == 0
    assert controls["denominator_mutation"] == 0


def test_committed_contract_has_bound_inputs() -> None:
    assert OUTPUT.is_file()
    contract = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert contract["status"] == "pre_admission_static_contract_frozen"
    assert len(contract["evidence"]) == 2
    assert all(item["sha256"] for item in contract["evidence"])
