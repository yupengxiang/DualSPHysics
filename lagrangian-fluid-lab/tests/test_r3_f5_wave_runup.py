from __future__ import annotations

from pathlib import Path

import pytest

from scripts.r3_f5_wave_runup import (
    EXTERNAL_GAUGES,
    RESOLUTIONS,
    _excluded_particles,
    _read_gauge,
    _restore_input_assets,
    compare_resolution_matrix,
    _run_tag,
    configure_definition,
)


def _definition(path: Path) -> None:
    path.write_text(
        """<?xml version='1.0'?>
<case>
  <execution>
    <special><gauges>
      <default>
        <_computedt value='0.001'/>
        <_computetime start='0.1' end='0.2'/>
        <_outputdt value='0'/>
        <_outputtime start='0' end='10'/>
      </default>
    </gauges></special>
    <parameters>
      <parameter key='TimeMax' value='20'/>
      <parameter key='TimeOut' value='0.02'/>
    </parameters>
  </execution>
</case>
"""
    )


def test_configure_definition_activates_cadence_and_external_gauges(tmp_path):
    source = tmp_path / "Case_Def.xml"
    target = tmp_path / "configured" / "Case_External_Def.xml"
    _definition(source)

    record = configure_definition(source, target, gauge_cadence_s=0.02, tmax_s=16.0)

    assert record["active_gauge_option_names"] == [
        "computedt", "computetime", "outputdt", "outputtime"
    ]
    assert len(record["external_gauges"]) == len(EXTERNAL_GAUGES)
    text = target.read_text()
    assert "<_computedt" not in text
    assert '<computedt value="0.02"' in text
    assert '<computetime start="0" end="16"' in text
    assert '<parameter key="TimeMax" value="16"' in text
    assert '<swl name="WG1">' in text
    assert '<point0 x="3.1" y="0.18" z="0"' in text
    assert '<point2 x="3.1" y="0.18" z="0.6"' in text


def test_candidate_resolution_ladder_excludes_known_legacy_stress_case():
    assert RESOLUTIONS == {"coarse": 0.03, "medium": 0.025, "fine": 0.02}
    assert 0.04 not in RESOLUTIONS.values()


def test_run_tag_separates_parameterizations_to_prevent_stale_frame_mixing():
    assert _run_tag("medium", 4.0, 0.02) == "medium__tmax-4__tout-0p02"
    assert _run_tag("medium", 16.0, 0.02) != _run_tag("medium", 4.0, 0.02)


def test_excluded_particle_parser_handles_solver_dot_leader():
    assert _excluded_particles("Excluded particles...............: 1") == 1
    assert _excluded_particles("Excluded particles...............: 21,695") == 21695


def test_resolution_comparison_reports_offset_corrected_sensitivity(tmp_path):
    runs = []
    for label, dp, offset in (("coarse", 0.03, 0.20), ("medium", 0.025, 0.25)):
        directory = tmp_path / label
        directory.mkdir()
        (directory / "GaugesSWL_WG1.csv").write_text(
            "time [s];swlx [m];swly [m];swlz [m]\n"
            f"0;3.1;0.18;{offset}\n"
            f"1;3.1;0.18;{offset + 0.01}\n"
            f"2;3.1;0.18;{offset + 0.02}\n"
        )
        runs.append({"label": label, "dp_m": dp, "status": "completed", "output_dir": str(directory)})

    report = compare_resolution_matrix(runs)

    gauge = report["pairs"][0]["gauges"]["WG1"]
    assert gauge["status"] == "computed"
    assert gauge["initial_offset_m"] == pytest.approx(-0.05)
    assert gauge["raw_swl_rmse_m"] == pytest.approx(0.05)
    assert gauge["normalized_eta_rmse_m"] == pytest.approx(0.0)
    assert report["acceptance_threshold_declared"] is False


def test_restore_input_assets_recovers_same_directory_gencase_inputs(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "generated"
    source.mkdir()
    destination.mkdir()
    (source / "Mov_piston.dat").write_text("0 0\n0.1 0.02\n")
    (source / "Slope.stl").write_text("solid slope\nendsolid slope\n")
    (destination / "Mov_piston.dat").write_bytes(b"")
    (destination / "Slope.stl").write_bytes(b"")

    _restore_input_assets(source, destination)

    assert (destination / "Mov_piston.dat").read_text() == "0 0\n0.1 0.02\n"
    assert (destination / "Slope.stl").read_text() == "solid slope\nendsolid slope\n"


def test_read_gauge_requires_two_finite_strictly_increasing_rows(tmp_path):
    path = tmp_path / "GaugesSWL_WG1.csv"
    path.write_text(
        "time;x;y;z;x2;y2;z2;x3;y3;z3\n"
        "0.0;3.1;0.18;0.24;3.1;0.18;0;3.1;0.18;0.6\n"
        "0.02;3.1;0.18;0.25;3.1;0.18;0;3.1;0.18;0.6\n"
    )
    report = _read_gauge(path)
    assert report["rows"] == 2
    assert report["dt_median_s"] == 0.02
    assert report["swl_dynamic"] is True
    assert report["issues"] == []
