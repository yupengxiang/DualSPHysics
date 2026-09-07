from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from scripts.r3_f4_impinging_observations import (
    CENTERLINE_POINTS,
    IMPACT_POINTS,
    RESOLUTIONS,
    _flow_summary,
    _force_summary,
    _measure_summary,
    _pointsdef,
    _runparts_summary,
    _run_tag,
    _write_flow_boxes,
    configure_definition,
)


def _definition(path: Path) -> None:
    path.write_text(
        """<?xml version='1.0'?>
<case>
  <execution><parameters>
    <parameter key='TimeMax' value='0.1'/>
    <parameter key='TimeOut' value='0.0002'/>
  </parameters></execution>
</case>
"""
    )


def test_configure_definition_declares_short_observation_window(tmp_path):
    source = tmp_path / "CaseJet2D_Def.xml"
    target = tmp_path / "configured" / "CaseJet2D_medium_Def.xml"
    _definition(source)

    record = configure_definition(source, target, tmax_s=0.03, tout_s=0.0005)

    assert record["changed_parameters"] == {"TimeMax": "0.03", "TimeOut": "0.0005"}
    text = target.read_text()
    assert '<parameter key="TimeMax" value="0.03"' in text
    assert '<parameter key="TimeOut" value="0.0005"' in text


def test_resolution_ladder_and_point_manifest_are_explicit():
    assert RESOLUTIONS == {"coarse": 0.0015, "medium": 0.001, "fine": 0.00075}
    assert len(IMPACT_POINTS) == 7
    assert len(CENTERLINE_POINTS) == 4
    assert _pointsdef(IMPACT_POINTS[:2]) == "pt=-0.12:0:0.001,pt=-0.08:0:0.001"


def test_run_tag_prevents_short_and_long_output_mixing():
    assert _run_tag("medium", 0.03, 0.0005) == "medium__tmax-0p03__tout-0p0005"
    assert _run_tag("medium", 0.1, 0.0005) != _run_tag("medium", 0.03, 0.0005)


def test_measure_summary_supports_scalar_and_vector_point_files(tmp_path):
    scalar = tmp_path / "p.csv"
    scalar.write_text(
        " ;PosX [m]:;0;0.1\n"
        " ;PosY [m]:;0;0\n"
        " ;PosZ [m]:;0.001;0.001\n"
        "Part;Time [s];Press_0 [Pa];Press_1 [Pa]\n"
        "0;0;0;0\n1;0.5;2;-3\n"
    )
    summary = _measure_summary(scalar, ["a", "b"])
    assert summary["rows"] == 2
    assert summary["issues"] == []
    assert summary["peaks"][1]["peak_signed"] == -3

    vector = tmp_path / "v.csv"
    vector.write_text(
        " ;Pos X/Y/Z [m]:;0;0;0.1\n"
        "Part;Time [s];Vel_0.x [m/s];Vel_0.y [m/s];Vel_0.z [m/s]\n"
        "0;0;0;0;0\n1;0.5;3;4;0\n"
    )
    vector_summary = _measure_summary(vector, ["a"], components=3)
    assert vector_summary["peaks"][0]["peak_speed"] == pytest.approx(5)


def test_force_and_flow_summaries_parse_official_semicolon_tables(tmp_path):
    force = tmp_path / "force.csv"
    force.write_text(
        "Part;Time [s];Np;ForceFluid.x [N/m];ForceFluid.y [N/m];ForceFluid.z [N/m];ForceFluid [N/m]\n"
        "0;0;10;0;0;-1;1\n1;0.5;10;0;0;-3;3\n"
    )
    force_summary = _force_summary(force)
    assert force_summary["rows"] == 2
    assert force_summary["peak_force_abs_n_per_m"] == 3
    assert force_summary["peak_force_z_n_per_m"] == -3

    flow = tmp_path / "flow.csv"
    flow.write_text(
        "Time [s];Nok_inlet;Input_inlet;InFlow_inlet???\n"
        "0;10;0;0\n0.5;8;2;4\n"
    )
    flow_summary = _flow_summary(flow)
    assert flow_summary["rows"] == 2
    assert flow_summary["columns"]["Input_inlet"]["sum"] == 2


def test_flow_boxes_use_particle_spacing_y_thickness(tmp_path):
    path = tmp_path / "boxes.xml"
    manifest = _write_flow_boxes(path, 0.0015)
    assert manifest["two_dimensional_per_depth"] is True
    assert manifest["boxes"]["inlet"]["size"][1] == pytest.approx(0.003)
    assert path.read_text().count("<boxsize ") == 3


def test_runparts_summary_marks_open_boundary_node_lifecycle(tmp_path):
    path = tmp_path / "RunPARTs.csv"
    path.write_text(
        "Part;TimeStep [s];NpSave;NpSim;NpNew;NpOut;NpbSim;NpfSim\n"
        "0;0;10;10;4;0;6;4\n"
        "1;0.5;12;12;4;2;6;6\n"
        "# explanatory footer\n"
    )
    summary = _runparts_summary(path)
    assert summary["rows"] == 2
    assert summary["NpNew_sum"] == 8
    assert summary["NpOut_sum"] == 2
    assert summary["numerical_lifecycle_observed"] is True
