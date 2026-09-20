from __future__ import annotations

import importlib.util
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
SCRIPT = LAB / "scripts/f5_wave_runup_solver_anchor_postrun_audit_v1.py"
SPEC = importlib.util.spec_from_file_location("f5_anchor_postrun", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_run_out_reconciles_actual_dualsphysics_output_dt(tmp_path):
    run_out = tmp_path / "Run.out"
    run_out.write_text("TimeMax=16\n  Output.....: 0 - 16   dt:0.02\nFinished execution (code=0)\nExcluded particles...............: 0\n")
    result = MODULE.parse_run_out(run_out)
    assert result["timemax_s"] == 16.0
    assert result["output_dt_values_s"] == [0.02]
    assert result["finished_code_zero"] is True
    assert result["excluded_particles"] == 0


def test_gauge_audit_keeps_missing_names_and_rows_visible(tmp_path):
    solver = tmp_path / "solver"
    solver.mkdir()
    (solver / "GaugesSWL_WG1.csv").write_text(
        "time [s];swlx [m];swly [m];swlz [m]\n0;0;0;0\n"
    )
    result = MODULE.gauge_audit(solver)
    assert result["all_expected"] is False
    assert result["records"]["WG1"]["issues"] == ["fewer_than_800_rows", "short_window"]


def test_verifier_declares_zero_credit_in_read_only_metadata():
    source = MODULE.__doc__ or ""
    assert "Read-only" in source
    assert MODULE.EXPECTED_FRAMES == 801
    assert MODULE.EXPECTED_TOUT == 0.02
