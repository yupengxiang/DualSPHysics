"""Synthetic unit tests for F7 RunPARTs timestep telemetry audit script v2."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

# Ensure scripts directory is on sys.path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from ds_data02_f7_runparts_timestep_audit_v2 import (
    SCHEMA,
    audit_timestep_comparison_v2,
    parse_run_out,
    parse_run_parts_csv,
    parse_xml_controls,
    validate_execution_receipt,
)


MOCK_BASELINE_XML = """<?xml version="1.0" encoding="UTF-8" ?>
<case>
    <execution>
        <parameters>
            <parameter key="StepAlgorithm" value="2" />
            <parameter key="Visco" value="0.05" />
            <parameter key="CoefDtMin" value="0.05" />
            <parameter key="DtIni" value="0" />
            <parameter key="DtMin" value="0" />
            <parameter key="DtFixed" value="0" />
            <parameter key="TimeMax" value="12" />
            <parameter key="TimeOut" value="0.002" />
        </parameters>
        <constants>
            <cflnumber value="0.2" />
        </constants>
    </execution>
</case>
"""

MOCK_VARIANT_XML = """<?xml version="1.0" encoding="UTF-8" ?>
<case>
    <execution>
        <parameters>
            <parameter key="StepAlgorithm" value="2" />
            <parameter key="Visco" value="0.05" />
            <parameter key="CoefDtMin" value="0.05" />
            <parameter key="DtIni" value="1.1053689792589941e-05" />
            <parameter key="DtMin" value="1.1053689792589941e-05" />
            <parameter key="DtFixed" value="1.1053689792589941e-05" />
            <parameter key="TimeMax" value="12" />
            <parameter key="TimeOut" value="0.002" />
        </parameters>
        <constants>
            <cflnumber value="0.2" />
        </constants>
    </execution>
</case>
"""

MOCK_RECEIPT_COMPLETED = {
    "status": "completed",
    "returncode": 0,
    "pid": 12345,
    "elapsed_seconds": 120.5,
    "cpu_core_seconds": 240.0,
    "gpu_seconds": 119.0,
}

MOCK_RECEIPT_FAILED = {
    "status": "failed",
    "returncode": 1,
}

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
Steps of simulation..............: 200
PART files.......................: 6
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
Steps of simulation..............: 900
PART files.......................: 6
Finished execution (code=0).
"""


def generate_mock_runparts_csv(
    path: Path,
    num_parts: int,
    base_step_count: int,
    dt_lo: float,
    dt_hi: float,
    dts_min_count: int = 0,
    np_out_per_interval: int = 1,
    time_end_s: float = 12.0,
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
    dt_part = time_end_s / num_parts
    for p in range(1, num_parts + 1):
        t = p * dt_part
        s = base_step_count
        dm = dts_min_count if p == 1 else 0
        nout = np_out_per_interval
        lines.append(
            f"{p};{t:.6f};{s};{dm};0.100000;424,277;424,277;0;{nout};14,800;1.0;89.0;{p*0.1:.6f};105,561;318,716;424,277;0;0;0;{dt_lo:.8e};{dt_hi:.8e};36.0;94.0;20.0;424,405;1,318,668\n"
        )
    path.write_text("".join(lines), encoding="utf-8")


def test_receipt_validation(tmp_path: Path):
    ok_receipt = tmp_path / "ok_receipt.json"
    ok_receipt.write_text(json.dumps(MOCK_RECEIPT_COMPLETED), encoding="utf-8")
    res = validate_execution_receipt(ok_receipt)
    assert res["status"] == "completed"
    assert res["returncode"] == 0

    bad_receipt = tmp_path / "bad_receipt.json"
    bad_receipt.write_text(json.dumps(MOCK_RECEIPT_FAILED), encoding="utf-8")
    with pytest.raises(ValueError, match="Execution receipt validation failed"):
        validate_execution_receipt(bad_receipt)


def test_xml_controls_parsing(tmp_path: Path):
    b_xml = tmp_path / "base.xml"
    b_xml.write_text(MOCK_BASELINE_XML, encoding="utf-8")
    parsed_b = parse_xml_controls(b_xml)
    assert parsed_b["step_algorithm_name"] == "Symplectic"
    assert parsed_b["evaluations_per_step"] == 2
    assert parsed_b["mode"] == "adaptive"
    assert parsed_b["cfl_number"] == 0.2

    v_xml = tmp_path / "variant.xml"
    v_xml.write_text(MOCK_VARIANT_XML, encoding="utf-8")
    parsed_v = parse_xml_controls(v_xml)
    assert parsed_v["step_algorithm_name"] == "Symplectic"
    assert parsed_v["evaluations_per_step"] == 2
    assert parsed_v["mode"] == "fixed"
    assert parsed_v["dt_fixed"] == pytest.approx(1.105368979e-5)


def test_runparts_validation_and_denominator(tmp_path: Path):
    parts_csv = tmp_path / "RunPARTs.csv"
    generate_mock_runparts_csv(
        parts_csv,
        num_parts=5,
        base_step_count=40,
        dt_lo=5.0e-5,
        dt_hi=5.2e-5,
        dts_min_count=10,
        np_out_per_interval=3,
        time_end_s=12.0,
    )
    # Expected total rows: 6 (0..5)
    parsed = parse_run_parts_csv(
        parts_csv,
        evaluations_per_step=2,
        expected_part_count=6,
        expected_time_max_s=12.0,
    )
    assert parsed["sum_steps"] == 200  # 5 * 40
    # Symplectic denominator: 2 * 200 = 400 evaluations
    assert parsed["total_dt_evaluations"] == 400
    assert parsed["sum_dts_min_clamps"] == 10
    assert parsed["floor_clamp_incidence_fraction"] == pytest.approx(10 / 400)
    assert parsed["denominator_formula"] == "2 * sum(Steps)"

    # NpOut interval sum: 5 intervals * 3 = 15
    assert parsed["total_np_out_interval_sum"] == 15
    assert parsed["last_row_np_out"] == 3

    # Per-save interval mean dt percentiles
    assert "per_save_interval_mean_dt_percentiles" in parsed
    assert "p50_dt_s" in parsed["per_save_interval_mean_dt_percentiles"]


def test_malformed_parts_csv_fails(tmp_path: Path):
    # Non-contiguous part indices
    bad_parts_csv = tmp_path / "bad_parts.csv"
    bad_parts_csv.write_text(
        "Part;TimeStep [s];Steps;DTsMin;NpOut;DtMin [s];DtMax [s]\n"
        "0;0;0;0;0;0;0\n"
        "2;0.002;40;0;0;5e-5;5e-5\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        parse_run_parts_csv(bad_parts_csv, expected_part_count=2)

    # Malformed non-numeric row
    non_numeric_csv = tmp_path / "non_numeric.csv"
    non_numeric_csv.write_text(
        "Part;TimeStep [s];Steps;DTsMin;NpOut;DtMin [s];DtMax [s]\n"
        "0;0;0;0;0;0;0\n"
        "1;INVALID_FLOAT;40;0;0;5e-5;5e-5\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Malformed numeric Part row"):
        parse_run_parts_csv(non_numeric_csv, expected_part_count=2)


def test_audit_comparison_v2_full(tmp_path: Path):
    b_receipt = tmp_path / "b_receipt.json"
    b_receipt.write_text(json.dumps(MOCK_RECEIPT_COMPLETED), encoding="utf-8")
    v_receipt = tmp_path / "v_receipt.json"
    v_receipt.write_text(json.dumps(MOCK_RECEIPT_COMPLETED), encoding="utf-8")

    b_xml = tmp_path / "b.xml"
    b_xml.write_text(MOCK_BASELINE_XML, encoding="utf-8")
    v_xml = tmp_path / "v.xml"
    v_xml.write_text(MOCK_VARIANT_XML, encoding="utf-8")

    b_out = tmp_path / "b_Run.out"
    b_out.write_text(MOCK_BASELINE_RUN_OUT, encoding="utf-8")
    v_out = tmp_path / "v_Run.out"
    v_out.write_text(MOCK_VARIANT_RUN_OUT, encoding="utf-8")

    b_parts = tmp_path / "b_RunPARTs.csv"
    generate_mock_runparts_csv(b_parts, num_parts=5, base_step_count=40, dt_lo=5.0e-5, dt_hi=5.2e-5)

    v_parts = tmp_path / "v_RunPARTs.csv"
    generate_mock_runparts_csv(v_parts, num_parts=5, base_step_count=180, dt_lo=1.1e-5, dt_hi=1.1e-5)

    audit = audit_timestep_comparison_v2(
        baseline_parts_path=b_parts,
        baseline_out_path=b_out,
        baseline_xml_path=b_xml,
        baseline_receipt_path=b_receipt,
        variant_parts_path=v_parts,
        variant_out_path=v_out,
        variant_xml_path=v_xml,
        variant_receipt_path=v_receipt,
        expected_part_count=6,
        expected_time_max_s=12.0,
    )

    assert audit["schema"] == SCHEMA
    assert audit["floor_status"]["baseline_clamps_observed"] == 0
    assert audit["floor_status"]["variant_clamps_observed"] == 0
    assert audit["comparison_metrics"]["step_count_ratio"] == pytest.approx(900 / 200)  # 4.5x
    assert audit["comparison_metrics"]["nominal_expected_step_ratio"] == 2.0
    assert "errata" in audit["methodological_analysis"]
    assert "audit_limitations" in audit["methodological_analysis"]


def test_cli_execution_v2(tmp_path: Path):
    b_receipt = tmp_path / "b_receipt.json"
    b_receipt.write_text(json.dumps(MOCK_RECEIPT_COMPLETED), encoding="utf-8")
    v_receipt = tmp_path / "v_receipt.json"
    v_receipt.write_text(json.dumps(MOCK_RECEIPT_COMPLETED), encoding="utf-8")

    b_xml = tmp_path / "b.xml"
    b_xml.write_text(MOCK_BASELINE_XML, encoding="utf-8")
    v_xml = tmp_path / "v.xml"
    v_xml.write_text(MOCK_VARIANT_XML, encoding="utf-8")

    b_out = tmp_path / "b_Run.out"
    b_out.write_text(MOCK_BASELINE_RUN_OUT, encoding="utf-8")
    v_out = tmp_path / "v_Run.out"
    v_out.write_text(MOCK_VARIANT_RUN_OUT, encoding="utf-8")

    # For CLI execution without custom expected_part_count, generate 6000 parts
    # To keep synthetic fixture fast, generate 6000 small lines
    b_parts = tmp_path / "b_RunPARTs.csv"
    # To match b_out steps_of_simulation = 200, let's update b_out steps to match 6000 parts with 1 step/part
    b_out_6001 = tmp_path / "b_Run_6001.out"
    b_out_6001.write_text(MOCK_BASELINE_RUN_OUT.replace("Steps of simulation..............: 200", "Steps of simulation..............: 6,000"), encoding="utf-8")
    generate_mock_runparts_csv(b_parts, num_parts=6000, base_step_count=1, dt_lo=5e-5, dt_hi=5e-5)

    v_parts = tmp_path / "v_RunPARTs.csv"
    v_out_6001 = tmp_path / "v_Run_6001.out"
    v_out_6001.write_text(MOCK_VARIANT_RUN_OUT.replace("Steps of simulation..............: 900", "Steps of simulation..............: 12,000"), encoding="utf-8")
    generate_mock_runparts_csv(v_parts, num_parts=6000, base_step_count=2, dt_lo=1.1e-5, dt_hi=1.1e-5)

    out_json = tmp_path / "audit_report_v2.json"
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "ds_data02_f7_runparts_timestep_audit_v2.py"

    cmd = [
        sys.executable,
        str(script_path),
        "--baseline-parts", str(b_parts),
        "--baseline-out", str(b_out_6001),
        "--baseline-xml", str(b_xml),
        "--baseline-receipt", str(b_receipt),
        "--variant-parts", str(v_parts),
        "--variant-out", str(v_out_6001),
        "--variant-xml", str(v_xml),
        "--variant-receipt", str(v_receipt),
        "--output", str(out_json),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    assert res.returncode == 0
    assert out_json.exists()

    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data["schema"] == SCHEMA
