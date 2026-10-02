from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
CASE = (
    ROOT
    / "campaigns/ds-data-02/families/F1/handoff_20261002"
    / "finite_center_initialization_001"
)


def test_new_mother_declares_cell_center_quadrature_contract() -> None:
    metadata = json.loads(
        (CASE / "F1_DUAL_FINITE_CENTER_DP001_003.metadata.json").read_text()
    )
    contract = metadata["continuous_contract"]
    nx, ny, nz = contract["expected_center_counts_xyz"]

    assert metadata["new_mother_route"]["reason"].startswith("The two bounded repairs")
    assert contract["reservoir_volume_m3"] == 0.616
    assert nx * ny * nz == contract["expected_fluid_count"] == 616000
    assert contract["expected_native_mass_kg"] == 616.0
    assert contract["initial_center_envelope_low_m"] == [2.105, 0.005, 0.005]
    assert contract["initial_center_envelope_high_m"] == [3.215, 0.995, 0.545]


def test_new_mother_lattice_and_wall_envelope_are_explicit() -> None:
    xml_path = CASE / "F1_DUAL_FINITE_CENTER_DP001_003_Def.xml"
    root = ET.parse(xml_path).getroot()
    definition = root.find(".//definition")
    assert definition is not None
    assert definition.attrib["dp"] == "0.01"
    assert definition.find("pointref").attrib == {"x": "0.005", "y": "0.005", "z": "0.005"}

    outer_boxes = root.findall(".//drawbox")
    outer = [box for box in outer_boxes if box.findtext("boxfill") == "all^top"]
    assert len(outer) == 2
    for box in outer:
        point = box.find("point").attrib
        endpoint = box.find("endpoint").attrib
        assert point["y"] == "-0.005"
        assert point["z"] == "-0.005"
        assert endpoint["x"] == "3.23"
        assert endpoint["y"] == "1.005"

    fluid = [
        box
        for box in outer_boxes
        if box.findtext("boxfill") == "solid"
        and box.find("point") is not None
        and box.find("point").attrib.get("x") == "2.105"
    ]
    assert len(fluid) == 1
    assert fluid[0].find("size").attrib == {
        "x": "1.110001",
        "y": "0.990001",
        "z": "0.540001",
    }
