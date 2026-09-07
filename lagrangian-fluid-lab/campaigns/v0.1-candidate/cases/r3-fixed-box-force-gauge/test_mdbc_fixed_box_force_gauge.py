"""Contract and evidence tests for the isolated mDBC fixed-box calibrations."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import xml.etree.ElementTree as ET


CASE_ROOT = Path(__file__).resolve().parent
DEFINITIONS = (
    CASE_ROOT / "fixed_box_mdbc_canonical_Def.xml",
    CASE_ROOT / "fixed_box_mdbc_fine_Def.xml",
)
REPORT = CASE_ROOT / "mdbc-fixed-box-force-gauge-report.json"


def _drawboxes(container: ET.Element) -> list[tuple[str | None, ET.Element]]:
    result: list[tuple[str | None, ET.Element]] = []
    mkbound: str | None = None
    for child in list(container):
        if child.tag == "setmkbound":
            mkbound = child.attrib.get("mk")
        elif child.tag in {"setmkfluid", "setmkvoid"}:
            mkbound = None
        elif child.tag == "drawbox":
            result.append((mkbound, child))
    return result


def _layers(box: ET.Element) -> list[float]:
    node = box.find("./layers")
    assert node is not None
    return [float(value) for value in node.attrib["vdp"].split(",")]


def test_mdbc_definitions_are_true_fixed_body_cases():
    for definition in DEFINITIONS:
        root = ET.parse(definition).getroot()
        assert root.find(".//floatings") is None
        assert root.findall(".//floating") == []
        assert root.find(".//parameter[@key='Boundary']").attrib["value"] == "2"
        force = root.find(".//force[@name='BoxForce']/target")
        assert force is not None and force.attrib["mkbound"] == "1"
        body = [
            box for mkbound, box in _drawboxes(root.find(".//mainlist"))
            if mkbound == "1"
        ]
        assert len(body) == 1


def test_half_dp_normal_surface_and_solid_side_layers_are_explicit():
    for definition in DEFINITIONS:
        root = ET.parse(definition).getroot()
        commands = root.find(".//geometry/commands")
        normal_list = commands.find("./list[@name='GeometryForNormals']")
        mainlist = commands.find("./mainlist")
        assert normal_list is not None and mainlist is not None
        normal_body = [
            box for mkbound, box in _drawboxes(normal_list) if mkbound == "1"
        ]
        actual_body = [
            box for mkbound, box in _drawboxes(mainlist) if mkbound == "1"
        ]
        assert len(normal_body) == len(actual_body) == 1
        assert _layers(normal_body[0]) == [0.5]
        assert _layers(actual_body[0]) == [0.0, -1.0, -2.0]
        assert -0.5 not in _layers(actual_body[0])


def test_physical_void_is_a_fully_submerged_0p2_cube_with_gap():
    root = ET.parse(DEFINITIONS[0]).getroot()
    mainlist = root.find(".//mainlist")
    assert mainlist is not None
    children = list(mainlist)
    void_index = next(i for i, child in enumerate(children) if child.tag == "setmkvoid")
    body_index = next(
        i for i, child in enumerate(children)
        if child.tag == "setmkbound" and child.attrib.get("mk") == "1"
    )
    assert body_index > void_index
    void_box = children[void_index + 1]
    point = void_box.find("./point")
    size = void_box.find("./size")
    assert point is not None and size is not None
    assert [float(point.attrib[k]) for k in ("x", "y", "z")] == [0.5, 0.3, 0.2]
    assert [float(size.attrib[k]) for k in ("x", "y", "z")] == [0.2, 0.2, 0.2]
    assert float(point.attrib["z"]) > 0.0
    assert float(point.attrib["z"]) + float(size.attrib["z"]) < 0.60


def test_report_keeps_mapping_normals_force_and_failed_gates_explicitly():
    if not REPORT.exists():
        return
    report = json.loads(REPORT.read_text())
    assert report["bounded_calibration_count"] == 2
    assert report["overall_acceptance_status"] == "candidate_not_accepted"
    assert report["owner_authorization"]["busy_jobs_interrupted"] is False
    rows = {case["run_label"]: case for case in report["cases"]}
    assert set(rows) == {"canonical-2", "fine-3"}
    for case in rows.values():
        assert case["fixed_body_mapping_gate"]["source_mkbound_maps_to_one_fixed_row"]
        assert case["fixed_body_mapping_gate"]["no_moving_or_floating_rows"]
        assert case["solver_log"]["gauge_config_target_found"]
        assert case["normal_ghost_audit"]["normal_zero_count"] > 0
        assert case["screen"]["stable_window_gate"] is False
        trace = CASE_ROOT / case["force_gauge"]["signed_csv"]
        assert trace.exists()
        with trace.open(newline="") as stream:
            csv_rows = list(csv.reader(stream, delimiter=";"))
        assert csv_rows[0] == [
            "time [s]", "force [N]", "forcex [N]", "forcey [N]", "forcez [N]"
        ]
        assert len(csv_rows) > 100
