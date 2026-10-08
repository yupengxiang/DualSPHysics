"""Manufactured CSV/timeline counterexamples for removal-time diagnostics."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ds_data02_stage2_native_removal_kinematics_v1.py"
SPEC = importlib.util.spec_from_file_location("removal_kinematics_v1", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot import removal kinematics module")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def fixture_sources(tmp_path: Path):
    xml = tmp_path / "case.xml"
    xml.write_text(
        "<case><particles mkfluidfirst=\"1\">"
        "<fluid count=\"4\" mkcount=\"2\"/>"
        "<fluid mkfluid=\"0\" mk=\"1\" begin=\"10\" count=\"2\"/>"
        "<fluid mkfluid=\"1\" mk=\"2\" begin=\"12\" count=\"2\"/>"
        "</particles><massfluid value=\"0.5\"/></case>", encoding="utf-8"
    )
    runparts = tmp_path / "RunPARTs.csv"
    runparts.write_text(
        "Part;TimeStep [s];NpOut;NpOutPos;NpOutRho;NpOutMov\n"
        "0;0.0;0;0;0;0\n"
        "1;0.1;1;1;0;0\n"
        "2;0.2;1;1;0;0\n", encoding="utf-8"
    )
    runout = tmp_path / "Run.out"
    runout.write_text("MapRealPos(final)=(0,0,0)-(1,1,1)\n", encoding="utf-8")
    csv_path = tmp_path / "PartOut.csv"
    csv_path.write_text(
        "Pos.x [m],Pos.y [m],Pos.z [m],PartOut,Motive,Idp,Vel.x [m/s],Vel.y [m/s],Vel.z [m/s],Rhop [kg/m^3],\n"
        "1.1,0.5,0.5,1,1,10,2,0,0,1000,\n"
        "0.5,-0.1,0.5,2,1,12,0,4,0,1000,\n", encoding="utf-8"
    )
    return xml, runparts, runout, csv_path


def test_velocity_mass_and_face_aggregation_is_per_saved_time(tmp_path: Path):
    xml_path, runparts_path, runout_path, csv_path = fixture_sources(tmp_path)
    xml = MODULE.parse_xml(xml_path, "fixture XML")
    timeline = MODULE.parse_runparts(runparts_path, "fixture RunPARTs")
    bounds = MODULE.parse_map_final(runout_path, "fixture Run.out")
    parsed = MODULE.parse_csv(csv_path, "fixture CSV", timeline, xml, bounds)
    assert parsed["motive_counts"] == {"position": 2}
    assert parsed["rows"][0]["mk_absolute"] == 1
    assert parsed["rows"][1]["mk_absolute"] == 2
    assert parsed["rows"][0]["momentum_kg_m_s"] == [1.0, 0.0, 0.0]
    assert parsed["rows"][0]["kinetic_energy_j"] == 1.0
    assert parsed["rows"][0]["faces"] == ["x_high"]
    assert parsed["rows"][1]["faces"] == ["y_low"]
    groups = MODULE.aggregate_time_mk_face(parsed["rows"])
    assert [(row["part"], row["mk_absolute"], row["face"]) for row in groups] == [(1, 1, "x_high"), (2, 2, "y_low")]
    assert groups[0]["time_s"] != groups[1]["time_s"]
    assert groups[0]["momentum_kg_m_s"] == [1.0, 0.0, 0.0]


@pytest.mark.parametrize("mutation", ["duplicate", "missing_velocity", "outside_timeline", "bad_bounds"])
def test_native_csv_join_counterexamples_are_rejected(tmp_path: Path, mutation: str):
    xml_path, runparts_path, runout_path, csv_path = fixture_sources(tmp_path)
    if mutation == "duplicate":
        csv_path.write_text(csv_path.read_text(encoding="utf-8") + "1.1,0.5,0.5,1,1,10,2,0,0,1000,\n", encoding="utf-8")
    elif mutation == "missing_velocity":
        csv_path.write_text(csv_path.read_text(encoding="utf-8").replace("Vel.z [m/s]", "Vel.z missing"), encoding="utf-8")
    elif mutation == "outside_timeline":
        csv_path.write_text(csv_path.read_text(encoding="utf-8").replace(",2,1,12,", ",9,1,12,"), encoding="utf-8")
    elif mutation == "bad_bounds":
        runout_path.write_text("MapRealPos(final)=(1,0,0)-(0,1,1)\n", encoding="utf-8")
    xml = MODULE.parse_xml(xml_path, "fixture XML")
    timeline = MODULE.parse_runparts(runparts_path, "fixture RunPARTs")
    with pytest.raises(MODULE.RemovalKinematicsError):
        bounds = MODULE.parse_map_final(runout_path, "fixture Run.out")
        MODULE.parse_csv(csv_path, "fixture CSV", timeline, xml, bounds)


def test_face_predicate_keeps_physical_fate_unknown():
    bounds = {"low_m": [0.0, 0.0, 0.0], "high_m": [1.0, 1.0, 1.0]}
    assert MODULE.classify_faces([0.5, 0.5, 0.5], bounds) == ["inside"]
    assert MODULE.classify_faces([-0.001, 0.5, 0.5], bounds) == ["x_low"]
    assert MODULE.classify_faces([1.001, -0.001, 0.5], bounds) == ["x_high", "y_low"]


if __name__ == "__main__":
    raise SystemExit("use pytest")
