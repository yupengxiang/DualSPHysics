"""Tests for DS-DATA-02 F5 Surface-First 3DP Gauge Evaluator (v1).

Tests operate entirely on isolated synthetic mock fixtures in tmp_path.
Zero access to actual campaign data / H5 files.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import numpy as np

from scripts.ds_data02_f5_surface_first_3dp_gauge_evaluator_v1 import (
    DEFAULT_H_REF_M,
    DEFAULT_TOL_RELATIVE,
    EXPECTED_GAUGES,
    EXPECTED_ROWS,
    EXPECTED_TMAX_S,
    compare_two_gauges,
    evaluate_mechanism,
    parse_gauge_csv,
    parse_run_out,
    parse_runparts_csv,
    sha256_file,
)


def _create_synthetic_gauge_csv(
    path: Path,
    num_rows: int = EXPECTED_ROWS,
    t_end: float = EXPECTED_TMAX_S,
    base_elevation: float = 0.40,
    amplitude: float = 0.01,
    floor_val: float = -0.02,
    num_dry: int = 0,
) -> None:
    times = np.linspace(0.0, t_end, num_rows)
    swlz = base_elevation + amplitude * np.sin(2 * np.pi * times / 4.0)

    # If dry samples requested, force the first num_dry samples to floor_val
    if num_dry > 0:
        swlz[:num_dry] = floor_val

    lines = ["time [s];swlx [m];swly [m];swlz [m];pos0x [m];pos0y [m];pos0z [m];pos2x [m];pos2y [m];pos2z [m]"]
    for t, z in zip(times, swlz):
        lines.append(f"{t:.6f};2.0;0.0;{z:.6f};2.0;0.0;{floor_val:.2f};2.0;0.0;1.25")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _create_synthetic_runparts_csv(path: Path, num_steps: int = 801, npout_max: int = 0) -> None:
    lines = [
        "Part;TimeStep [s];Steps;DTsMin;PartRuntime [s];NpSave;NpSim;NpNew;NpOut;NctSim;NpAlloc [X];NctAlloc [X];SimRuntime [s];NpbSim;NpfSim;NpNormal;NpOutPos;NpOutRho;NpOutMov;DtMin [s];DtMax [s];MemCPU [MiB];MemGPU [MiB];MemGPU_Cells [MiB];NpAlloc;NctAlloc"
    ]
    for step in range(num_steps):
        t = step * 0.02
        npout = npout_max if step == num_steps - 1 else 0
        lines.append(
            f"{step};{t:.6f};30;0;0.07;95145;95145;0;{npout};532;1.0;4.4;1.0;76329;18816;95145;0;0;0;0.0006;0.0007;8.2;16.8;0.03;95273;2352"
        )
    lines.append("# Comment line at the end")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _create_synthetic_run_out(path: Path, xmin: float = -1.30, dp: float = 0.05) -> None:
    content = f"""
DualSPHysics5 v5.4.355 (08-04-2025)
ProgramFile=".../bin/linux/DualSPHysics5.4_linux64"
MapRealPos(border)=(-1.2315,-0.881495,-0.261495)-(10.8815,0.781495,1.2515)
MapRealPos(final)=({xmin},-0.92,-0.32)-(11,0.87,1.45)
CaseNp=95,145
CaseNbound=76,329
CaseNfixed=73,201
CaseNmoving=3,128
CaseNfluid=18,816
Dp={dp}
"""
    path.write_text(content, encoding="utf-8")


def _create_synthetic_attempt_dir(
    attempt_dir: Path,
    xmin: float,
    dp: float,
    amplitude: float = 0.01,
    dry_toe_crest: bool = True,
) -> None:
    attempt_dir.mkdir(parents=True, exist_ok=True)
    rec = {
        "schema": "ds02.execution-receipt.v1",
        "returncode": 0,
        "status": "completed",
        "elapsed_seconds": 12.34,
        "started_at_utc": "2026-10-03T18:00:00Z",
        "finished_at_utc": "2026-10-03T18:00:12Z",
        "binary_sha256": "0415b10e5e32af8b8b7ad2a703f9043dca67dfcf7626eb98f1c05a50856fde29",
    }
    (attempt_dir / "execution-receipt.json").write_text(json.dumps(rec), encoding="utf-8")

    solver_out = attempt_dir / "solver_output"
    solver_out.mkdir(parents=True, exist_ok=True)

    _create_synthetic_run_out(solver_out / "Run.out", xmin=xmin, dp=dp)
    _create_synthetic_runparts_csv(solver_out / "RunPARTs.csv", num_steps=801, npout_max=0)

    for g in EXPECTED_GAUGES:
        csv_path = solver_out / f"GaugesSWL_{g}.csv"
        num_dry = 50 if (dry_toe_crest and g in ("RunupToe", "Crest")) else 0
        _create_synthetic_gauge_csv(
            csv_path,
            num_rows=EXPECTED_ROWS,
            t_end=EXPECTED_TMAX_S,
            base_elevation=0.40,
            amplitude=amplitude,
            num_dry=num_dry,
        )


def test_parse_gauge_csv_success(tmp_path: Path) -> None:
    csv_file = tmp_path / "GaugesSWL_WG1.csv"
    _create_synthetic_gauge_csv(csv_file, num_rows=800, t_end=15.98, num_dry=10)

    parsed = parse_gauge_csv(csv_file)
    assert parsed["file_name"] == "GaugesSWL_WG1.csv"
    assert parsed["total_rows"] == 800
    assert parsed["time_start_s"] == 0.0
    assert pytest.approx(parsed["time_end_s"], abs=1e-3) == 15.98
    assert parsed["pos0z_floor_m"] == -0.02
    assert parsed["dry_samples"] == 10
    assert pytest.approx(parsed["dry_fraction"], abs=1e-4) == 10 / 800
    assert parsed["is_partially_dry"] is True
    assert len(parsed["times"]) == 800
    assert len(parsed["swlz"]) == 800


def test_parse_gauge_csv_row_count_error(tmp_path: Path) -> None:
    csv_file = tmp_path / "GaugesSWL_WG1.csv"
    _create_synthetic_gauge_csv(csv_file, num_rows=799, t_end=15.98)

    with pytest.raises(ValueError, match="expected exactly 800"):
        parse_gauge_csv(csv_file)


def test_parse_runparts_csv(tmp_path: Path) -> None:
    parts_file = tmp_path / "RunPARTs.csv"
    _create_synthetic_runparts_csv(parts_file, num_steps=801, npout_max=0)

    parsed = parse_runparts_csv(parts_file)
    assert parsed["total_steps"] == 801
    assert parsed["max_npout"] == 0
    assert parsed["npout_loss_events"] == 0
    assert parsed["particle_loss_detected"] is False


def test_parse_run_out(tmp_path: Path) -> None:
    run_out_file = tmp_path / "Run.out"
    _create_synthetic_run_out(run_out_file, xmin=-1.30, dp=0.05)

    parsed = parse_run_out(run_out_file)
    assert "DualSPHysics5 v5.4.355" in parsed["solver_version"]
    assert parsed["case_np"] == 95145
    assert parsed["case_nfluid"] == 18816
    assert pytest.approx(parsed["xmin_final_m"], abs=1e-3) == -1.30


def test_compare_two_gauges_identical(tmp_path: Path) -> None:
    f1 = tmp_path / "G1.csv"
    f2 = tmp_path / "G2.csv"
    _create_synthetic_gauge_csv(f1, num_rows=800, amplitude=0.01)
    _create_synthetic_gauge_csv(f2, num_rows=800, amplitude=0.01)

    p1 = parse_gauge_csv(f1)
    p2 = parse_gauge_csv(f2)

    comp = compare_two_gauges(p1, p2, "WG1", h_ref_m=DEFAULT_H_REF_M, tol_relative=DEFAULT_TOL_RELATIVE)
    assert comp["gauge_name"] == "WG1"
    assert comp["evaluation_samples"] == 800
    assert comp["pass_5pct_overall"] is True
    assert pytest.approx(comp["normalized_eta_rmse_m"], abs=1e-8) == 0.0
    assert pytest.approx(comp["relative_eta_rmse"], abs=1e-8) == 0.0


def test_compare_two_gauges_dry_occupancy_dropout(tmp_path: Path) -> None:
    f1 = tmp_path / "G1_toe.csv"
    f2 = tmp_path / "G2_toe.csv"
    _create_synthetic_gauge_csv(f1, num_rows=800, num_dry=100)
    _create_synthetic_gauge_csv(f2, num_rows=800, num_dry=50)

    p1 = parse_gauge_csv(f1)
    p2 = parse_gauge_csv(f2)

    comp = compare_two_gauges(p1, p2, "RunupToe", h_ref_m=DEFAULT_H_REF_M, tol_relative=DEFAULT_TOL_RELATIVE)
    dry_info = comp["dry_occupancy"]
    assert dry_info["left_dry_samples"] == 100
    assert dry_info["right_dry_samples"] == 50
    # Samples 0..50 are dry in both; samples 50..100 are dry in left but wet in right (dropout=50)
    assert dry_info["both_dry_samples"] == 50
    assert dry_info["resolution_dropout_samples"] == 50
    assert dry_info["both_wet_samples"] == 700


def test_evaluate_mechanism_synthetic_end_to_end(tmp_path: Path) -> None:
    coarse_dir = tmp_path / "coarse_attempt"
    medium_dir = tmp_path / "medium_attempt"
    fine_dir = tmp_path / "fine_attempt"

    _create_synthetic_attempt_dir(coarse_dir, xmin=-1.30, dp=0.05, amplitude=0.015)
    _create_synthetic_attempt_dir(medium_dir, xmin=-1.22, dp=0.025, amplitude=0.012)
    _create_synthetic_attempt_dir(fine_dir, xmin=-1.22, dp=0.010, amplitude=0.010)

    stl_file = tmp_path / "f5_continuous_bed_profile_slope_0p280.stl"
    stl_file.write_text("solid dummy bed stl\nendsolid", encoding="utf-8")

    piston_file = tmp_path / "piston_motion.dat"
    piston_file.write_text("0.0 0.0\n16.0 0.1\n", encoding="utf-8")

    out_dir = tmp_path / "eval_output"

    report = evaluate_mechanism(
        mechanism="runup",
        dp050_dir=coarse_dir,
        dp025_dir=medium_dir,
        dp010_dir=fine_dir,
        bed_stl=stl_file,
        piston_file=piston_file,
        output_dir=out_dir,
        report_name="f5_runup_test_report.json",
    )

    report_file = out_dir / "f5_runup_test_report.json"
    assert report_file.is_file()

    loaded = json.loads(report_file.read_text(encoding="utf-8"))
    assert loaded["schema"] == "ds02.f5.surface-first-3dp-gauge-comparison-report.v1"
    assert loaded["mechanism"] == "runup"
    assert loaded["scientific_status"] == "spatial_candidate_evidence_only"
    assert loaded["qualification_claim"] == "none"
    assert loaded["T1_numerical"] is False
    assert loaded["matrix_credit"] == 0
    assert loaded["time_window"]["extrapolation_to_16s"] is False
    assert loaded["numerical_padding"]["verified"] is True
    assert loaded["historical_negative_preservation"]["probe"] == "WG3"
    assert loaded["historical_negative_preservation"]["negative_finding_preserved"] is True
    assert "coarse_vs_medium" in loaded["pairwise_comparisons"]
    assert "medium_vs_fine" in loaded["pairwise_comparisons"]
    assert "coarse_vs_fine" in loaded["pairwise_comparisons"]
    assert loaded["native_npout_summary"]["zero_loss_verified"] is True
