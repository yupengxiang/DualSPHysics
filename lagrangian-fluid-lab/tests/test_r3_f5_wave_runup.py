from __future__ import annotations

from pathlib import Path

from scripts.r3_f5_wave_runup import (
    EXTERNAL_GAUGES,
    _read_gauge,
    _restore_input_assets,
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

