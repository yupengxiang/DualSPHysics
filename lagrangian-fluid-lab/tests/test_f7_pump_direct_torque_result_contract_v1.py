from __future__ import annotations

import pytest

from scripts.f7_pump_compute_forces_result_contract_v1 import (
    RAW_HEADER_MAP,
    validate_headers,
    validate_rows,
)
from scripts.f7_pump_energy_consistency_contract_v1 import validate_energy_rows


def test_compute_forces_contract_freezes_headers_and_semantics() -> None:
    result = validate_headers(RAW_HEADER_MAP.values())
    assert result["schema"] == "core.f7.pump.compute_forces.result_parser.v1"
    assert result["moment_unit_mapping"].startswith("official")


def test_compute_forces_contract_rejects_missing_or_unaligned_rows() -> None:
    rows = [{"time_s": 0.0, "force_fluid_x_N": 0.0, "force_fluid_y_N": 0.0,
             "force_fluid_z_N": 0.0, "moment_pump_axis_in_Nm": 0.0,
             "moment_pump_axis_ex_Nm": 0.0}]
    with pytest.raises(ValueError, match="not aligned"):
        validate_rows(rows, expected_times=[0.02])


def test_energy_contract_is_numeric_and_fail_closed() -> None:
    rows = [{"time_s": 0.0, "tau_axis_Nm": 1.0, "omega_rad_s": 1.0,
             "delta_energy_fluid_J": 1.0, "dissipation_J": 0.0, "gravity_work_J": 0.0}]
    result = validate_energy_rows(rows, expected_times=[0.0])
    assert result["accepted"] is True
    assert result["relative_tolerance"] == 0.10
