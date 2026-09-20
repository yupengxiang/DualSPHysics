from __future__ import annotations

import importlib.util
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
SCRIPT = LAB / "scripts/f5_wave_runup_solver_anchor_cadence_parser_v1.py"
SPEC = importlib.util.spec_from_file_location("f5_anchor_cadence_parser", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_parse_real_dualsphysics_timemax_and_output_dt_records(tmp_path):
    run_out = tmp_path / "Run.out"
    run_out.write_text(
        "TimeMax=16\n"
        "  Output.....: 0 - 16   dt:0.02\n"
        "  Output.....: 0 - 16   dt:0.02\n"
        "Finished execution (code=0)\n",
        encoding="utf-8",
    )

    result = MODULE.parse_run_out(run_out)

    assert result["timemax_s"] == 16.0
    assert result["output_dt_values_s"] == [0.02]
    assert result["output_record_count"] == 2
    assert MODULE.cadence_gate(result, expected_tmax_s=16.0, expected_dt_s=0.02)


def test_parse_accepts_spacing_and_scientific_notation_in_native_record(tmp_path):
    run_out = tmp_path / "Run.out"
    run_out.write_text(
        "TimeMax = 1.6e1\n"
        "Output........: 0 - 16   dt : 2e-2\n",
        encoding="utf-8",
    )

    result = MODULE.parse_run_out(run_out)

    assert result["timemax_s"] == 16.0
    assert result["output_dt_values_s"] == [0.02]


def test_timeout_token_alone_does_not_fake_a_native_cadence(tmp_path):
    run_out = tmp_path / "Run.out"
    run_out.write_text("TimeMax=16\nTimeOut=0.02\n", encoding="utf-8")

    result = MODULE.parse_run_out(run_out)

    assert result["output_dt_values_s"] == []
    assert result["cadence_s"] is None
    assert not MODULE.cadence_gate(result, expected_tmax_s=16.0, expected_dt_s=0.02)
