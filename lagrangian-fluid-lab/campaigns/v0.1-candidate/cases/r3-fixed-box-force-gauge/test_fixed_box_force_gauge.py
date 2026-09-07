"""Contract tests for the isolated fixed-body force-gauge case."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import xml.etree.ElementTree as ET


CASE_ROOT = Path(__file__).resolve().parent
DEFINITIONS = (
    CASE_ROOT / "fixed_box_dbc_gravity_Def.xml",
    CASE_ROOT / "fixed_box_dbc_zero_pressure_Def.xml",
)


def _parameter(root: ET.Element, key: str) -> str:
    node = root.find(f".//execution/parameters/parameter[@key='{key}']")
    assert node is not None, key
    return node.attrib["value"]


def _body_box(root: ET.Element) -> tuple[ET.Element, ET.Element]:
    mainlist = root.find(".//geometry/commands/mainlist")
    assert mainlist is not None
    children = list(mainlist)
    for index, node in enumerate(children):
        if node.tag == "setmkbound" and node.attrib.get("mk") == "1":
            box = children[index + 1]
            assert box.tag == "drawbox"
            point = box.find("point")
            size = box.find("size")
            assert point is not None and size is not None
            return point, size
    raise AssertionError("mkbound=1 body box not found")


def test_each_definition_is_a_true_fixed_body_control():
    for definition in DEFINITIONS:
        root = ET.parse(definition).getroot()
        assert root.find(".//floatings") is None
        assert root.findall(".//floating") == []
        point, size = _body_box(root)
        assert [float(point.attrib[key]) for key in ("x", "y", "z")] == [0.5, 0.3, 0.2]
        assert [float(size.attrib[key]) for key in ("x", "y", "z")] == [0.2, 0.2, 0.2]
        force = root.find(".//force[@name='BoxForce']")
        assert force is not None
        target = force.find("target")
        assert target is not None and target.attrib["mkbound"] == "1"


def test_geometry_has_full_immersion_and_floor_clearance():
    root = ET.parse(DEFINITIONS[0]).getroot()
    point, size = _body_box(root)
    bottom = float(point.attrib["z"])
    top = bottom + float(size.attrib["z"])
    assert bottom > 0.0
    assert top < 0.60
    assert bottom - 0.0 >= 0.20


def test_zero_pressure_control_reinitialises_state():
    root = ET.parse(DEFINITIONS[1]).getroot()
    constants = root.find(".//constantsdef")
    assert constants is not None
    gravity = constants.find("gravity")
    rhopgradient = constants.find("rhopgradient")
    assert gravity is not None
    assert [gravity.attrib[key] for key in ("x", "y", "z")] == ["0", "0", "0"]
    assert rhopgradient is not None and rhopgradient.attrib["value"] == "1"
    assert _parameter(root, "DensityDT") == "0"
    boundary = root.find(".//parameter[@key='Boundary']")
    assert boundary is None or boundary.attrib.get("value") == "1"


def test_generated_mapping_and_runtime_report_if_materialised():
    generated = CASE_ROOT / "generated" / "fixed_box_dbc_gravity" / "fixed_box_dbc_gravity.xml"
    report_path = CASE_ROOT / "fixed-box-force-gauge-report.json"
    if not generated.exists() or not report_path.exists():
        return
    particles = ET.parse(generated).getroot().find(".//execution/particles")
    assert particles is not None
    body = [node for node in particles.findall("fixed") if node.attrib.get("mkbound") == "1"]
    assert len(body) == 1
    assert body[0].attrib["mk"] == "18"
    assert int(body[0].attrib["count"]) == 729
    report = json.loads(report_path.read_text())
    assert report["overall_acceptance_status"] == "candidate_not_accepted"
    for case in report["cases"]:
        assert case["fixed_body_mapping_gate"]["source_mkbound_maps_to_fixed"]
        assert case["solver_log"]["gauge_config_target_found"]
        trace = CASE_ROOT / case["force_gauge"]["signed_csv"]
        assert trace.exists()
        with trace.open(newline="") as stream:
            rows = list(csv.reader(stream, delimiter=";"))
        assert rows[0] == ["time [s]", "force [N]", "forcex [N]", "forcey [N]", "forcez [N]"]
        assert len(rows) > 100
