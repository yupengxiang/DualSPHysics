from __future__ import annotations

import json
import xml.etree.ElementTree as ET

from scripts.f9_definition_contract_v1 import DEFINITION, OUTPUT, build_contract


def test_f9_definition_contract_is_static_only() -> None:
    contract = build_contract()
    assert contract["status"] == "static_definition_materialized_no_runtime_authorization"
    assert contract["admission_granted"] is False
    assert contract["geometry_contract"]["top_boundary_particles"] is False
    assert contract["execution_parameters_contract"]["XYPeriodic_parameter"] == "forbidden"
    assert contract["anchor_geometry"]["geometric_forward_translation_m"][2] < 0.0
    assert contract["anchor_geometry"]["runtime_periodic_x_vector_m"][0] < 0.0
    assert contract["anchor_geometry"]["runtime_periodic_x_vector_m"][2] > 0.0


def test_f9_definition_contract_freezes_nusselt_boundary_semantics() -> None:
    contract = build_contract()
    assert contract["execution_parameters_contract"]["Boundary"] == 2
    assert contract["execution_parameters_contract"]["SlipMode"] == 2
    assert contract["execution_parameters_contract"]["ViscoTreatment"] == 3
    assert contract["execution_parameters_contract"]["NoPenetration"] == 1
    assert contract["constantsdef_contract"]["gravity_is_only_driving_input"] is True
    assert contract["execution_parameters_contract"]["DtFixed_s"] == 0.00001
    assert contract["execution_parameters_contract"]["expected_output_rows"] == 501
    assert contract["runtime_authorization"]["definition_candidate_materialized"] is True
    assert contract["runtime_authorization"]["definition_write_authorization"] is False
    assert contract["runtime_authorization"]["solver"] is False


def test_committed_f9_definition_contract_is_hash_bound() -> None:
    assert OUTPUT.is_file()
    contract = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert contract["status"] == "static_definition_materialized_no_runtime_authorization"
    assert len(contract["evidence"]) == 4
    assert all(item["sha256"] for item in contract["evidence"])


def test_static_definition_has_only_bottom_boundary_and_individual_periodic_offsets() -> None:
    root = ET.parse(DEFINITION).getroot()
    params = {node.attrib["key"]: node.attrib["value"] for node in root.findall(".//parameter")}
    assert root.find(".//constantsdef/gravity").attrib == {
        "x": "0", "y": "0", "z": "-9.81",
        "comment": "Global vertical gravity", "units_comment": "m/s^2",
    }
    assert params["XPeriodicIncZ"] == "0.025225016464"
    assert params["YPeriodicIncZ"] == "0"
    assert "XYPeriodic" not in params
    assert len(root.findall(".//setmkbound")) == 1
    assert len(root.findall(".//setmkfluid")) == 1
    assert len(root.findall(".//drawextrude")) == 2
    bottom_points = root.findall(".//drawextrude")[0].findall("./point")[2:4]
    fluid_bottom_points = root.findall(".//drawextrude")[1].findall("./point")[0:2]
    assert sorted((p.attrib["x"], p.attrib["z"]) for p in bottom_points) == sorted((p.attrib["x"], p.attrib["z"]) for p in fluid_bottom_points)
    assert not any(root.findall(f".//{tag}") for tag in ("inout", "wavepaddles", "floatings", "accinputs"))
