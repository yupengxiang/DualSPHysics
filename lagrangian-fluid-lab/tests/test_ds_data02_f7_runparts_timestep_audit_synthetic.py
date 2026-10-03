"""Synthetic unit tests for F7 RunPARTs timestep telemetry audit script."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from ds_data02_f7_runparts_timestep_audit_v1 import (
    SCHEMA,
    audit_timestep_comparison,
    parse_run_out,
    parse_run_parts_csv,
)


MOCK_BASELINE_RUN_OUT = """
CaseName="F7_BASELINE_MOCK"
RunName="F7_BASELINE_MOCK"
StepAlgorithm="Symplectic"
CFLnumber=0.2
DtIni=0.0002584041981971494
DtMin=0.0000129202101023836
TimeMax=12
TimePart=0.002
Particles of simulation (initial): 424,277
DTs adjusted to DtMin............: 0
Excluded particles...............: 410
Total Runtime....................: 1757.302368 sec.
Simulation Runtime...............: 1756.950928 sec.
Steps of simulation..............: 236,891
PART files.......................: 6001
Finished execution (code=0).
"""

MOCK_VARIANT_RUN_OUT = """
CaseName="F7_VARIANT_MOCK"
RunName="F7_VARIANT_MOCK"
StepAlgorithm="Symplectic"
CFLnumber=0.2
DtIni=1.105368979258994e-05
DtMin=1.105368979258994e-05
FixedDt=1.105368979258994e-05
TimeMax=12
TimePart=0.002
Particles of simulation (initial): 424,277
DTs adjusted to DtMin............: 0
Excluded particles...............: 423
Total Runtime....................: 5365.655762 sec.
Simulation Runtime...............: 5365.341309 sec.
Steps of simulation..............: 1,085,611
PART files.......................: 6001
Finished execution (code=0).
"""


def generate_mock_runparts_csv(
    path: Path,
    num_parts: int,
    base_step_count: int,
    dt_lo: float,
    dt_hi: float,
    dts_min_count: int = 0,
) -> None:
    """Generate mock semicolon-separated RunPARTs.csv with header."""
    header = (
        "Part;TimeStep [s];Steps;DTsMin;PartRuntime [s];NpSave;NpSim;NpNew;NpOut;NctSim;"
        "NpAlloc [X];NctAlloc [X];SimRuntime [s];NpbSim;NpfSim;NpNormal;NpOutPos;NpOutRho;"
        "NpOutMov;DtMin [s];DtMax [s];MemCPU [MiB];MemGPU [MiB];MemGPU_Cells [MiB];NpAlloc;NctAlloc\n"
    )
    lines = [header]
    # Part 0
    lines.append(
        "0;0;0;0;0.000000;424,277;424,277;0;0;14,800;1.000302;89.099189;0.000000;105,561;318,716;424,277;0;0;0;0;0;36.470919;73.930901;20.121315;424,405;1,318,668\n"
    )
    time_accum = 0.0
    dt_part = 0.002
    for p in range(1, num_parts + 1):
        time_accum += dt_part
        s = base_step_count + (p % 3)
        dm = dts_min_count if p == 1 else 0
        lines.append(
            f"{p};{time_accum:.6f};{s};{dm};0.100000;424,277;424,277;0;0;14,800;1.0;89.0;{p*0.1:.6f};105,561;318,716;424,277;0;0;0;{dt_lo:.8e};{dt_hi:.8e};36.0;94.0;20.0;424,405;1,318,668\n"
        )
    path.write_text("".join(lines), encoding="utf-8")


def test_parse_run_out(tmp_path: Path):
    b_out = tmp_path / "baseline_Run.out"
    b_out.write_text(MOCK_BASELINE_RUN_OUT, encoding="utf-8")
    parsed_b = parse_run_out(b_out)

    assert parsed_b["case_name"] == "F7_BASELINE_MOCK"
    assert parsed_b["mode"] == "adaptive"
    assert parsed_b["cfl_number"] == 0.2
    assert parsed_b["dt_min_floor"] == pytest.approx(1.292021e-5)
    assert parsed_b["fixed_dt"] is None
    assert parsed_b["dts_adjusted_to_dtmin"] == 0
    assert parsed_b["steps_of_simulation"] == 236891
    assert parsed_b["return_code"] == 0

    v_out = tmp_path / "variant_Run.out"
    v_out.write_text(MOCK_VARIANT_RUN_OUT, encoding="utf-8")
    parsed_v = parse_run_out(v_out)

    assert parsed_v["case_name"] == "F7_VARIANT_MOCK"
    assert parsed_v["mode"] == "fixed"
    assert parsed_v["fixed_dt"] == pytest.approx(1.105368979e-5)
    assert parsed_v["dts_adjusted_to_dtmin"] == 0
    assert parsed_v["steps_of_simulation"] == 1085611


def test_parse_run_parts_csv(tmp_path: Path):
    parts_csv = tmp_path / "RunPARTs.csv"
    generate_mock_runparts_csv(
        parts_csv,
        num_parts=10,
        base_step_count=38,
        dt_lo=5.0e-5,
        dt_hi=5.2e-5,
        dts_min_count=0,
    )
    parsed = parse_run_parts_csv(parts_csv)

    assert parsed["total_part_rows"] == 11  # 0 to 10
    assert parsed["floor_clamp_zero"] is True
    assert parsed["floor_clamp_incidence_fraction"] == 0.0
    assert parsed["is_constant_fixed_dt"] is False
    assert parsed["global_min_dt_s"] == pytest.approx(5.0e-5)
    assert parsed["global_max_dt_s"] == pytest.approx(5.2e-5)
    assert "p50_dt_s" in parsed["interval_mean_dt_percentiles"]


def test_audit_timestep_comparison(tmp_path: Path):
    b_out = tmp_path / "b_Run.out"
    b_out.write_text(MOCK_BASELINE_RUN_OUT, encoding="utf-8")
    b_parts = tmp_path / "b_RunPARTs.csv"
    # To match steps_of_simulation = 236891 across 6000 parts, ~39.48 steps/part
    # Let's test with smaller synthetic numbers and verify step matching logic
    generate_mock_runparts_csv(b_parts, num_parts=5, base_step_count=40, dt_lo=5.0e-5, dt_hi=5.2e-5)

    v_out = tmp_path / "v_Run.out"
    v_out.write_text(MOCK_VARIANT_RUN_OUT, encoding="utf-8")
    v_parts = tmp_path / "v_RunPARTs.csv"
    generate_mock_runparts_csv(v_parts, num_parts=5, base_step_count=180, dt_lo=1.1e-5, dt_hi=1.1e-5)

    audit = audit_timestep_comparison(
        baseline_parts_path=b_parts,
        baseline_out_path=b_out,
        variant_parts_path=v_parts,
        variant_out_path=v_out,
    )

    assert audit["schema"] == SCHEMA
    assert audit["findings"]["floor_clamping_eliminated"] is True
    assert audit["findings"]["baseline_mode"] == "adaptive"
    assert audit["findings"]["variant_mode"] == "fixed"
    # 180 / 40 ~ 4.5
    assert audit["comparison_metrics"]["step_count_ratio"] > 4.0
    assert audit["comparison_metrics"]["nominal_expected_step_ratio"] == 2.0


def test_cli_execution(tmp_path: Path):
    b_out = tmp_path / "b_Run.out"
    b_out.write_text(MOCK_BASELINE_RUN_OUT, encoding="utf-8")
    b_parts = tmp_path / "b_RunPARTs.csv"
    generate_mock_runparts_csv(b_parts, num_parts=5, base_step_count=40, dt_lo=5.0e-5, dt_hi=5.2e-5)

    v_out = tmp_path / "v_Run.out"
    v_out.write_text(MOCK_VARIANT_RUN_OUT, encoding="utf-8")
    v_parts = tmp_path / "v_RunPARTs.csv"
    generate_mock_runparts_csv(v_parts, num_parts=5, base_step_count=180, dt_lo=1.1e-5, dt_hi=1.1e-5)

    out_json = tmp_path / "audit_report.json"

    script_path = Path(__file__).resolve().parent.parent / "scripts" / "ds_data02_f7_runparts_timestep_audit_v1.py"
    cmd = [
        sys.executable,
        str(script_path),
        "--baseline-parts", str(b_parts),
        "--baseline-out", str(b_out),
        "--variant-parts", str(v_parts),
        "--variant-out", str(v_out),
        "--output", str(out_json),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    assert res.returncode == 0
    assert out_json.exists()

    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data["schema"] == SCHEMA
