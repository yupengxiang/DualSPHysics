from __future__ import annotations

import json
import math
from pathlib import Path
from xml.etree import ElementTree

import pytest

from scripts import f8_input_materialization_v1 as writer


ROOT = Path(__file__).resolve().parents[1]


def test_inputs_are_exclusively_created_from_the_registered_targets() -> None:
    with pytest.raises(ValueError):
        writer.write_materialization(Path("/tmp/unregistered.xml"), Path("/tmp/unregistered.csv"), Path("/tmp/unregistered.json"))
    with pytest.raises(FileExistsError):
        writer.write_materialization()


def test_committed_input_materialization_is_hash_closed_and_zero_credit() -> None:
    receipt = json.loads((ROOT / writer.RECEIPT_TARGET).read_text(encoding="utf-8"))
    assert receipt["status"] == "one_time_inputs_materialized_static_only"
    assert receipt["qualification_claim"] == "none"
    assert receipt["qualification_credit"] == 0
    assert receipt["authorization"]["consumed"] is True
    assert receipt["authorization"]["overwrite_or_reuse_allowed"] is False
    assert receipt["execution_controls"]["gencase_invoked"] is False
    assert receipt["execution_controls"]["definition_written"] is True
    for item in receipt["bindings"]:
        path = ROOT / item["path"]
        assert path.is_file()
        assert path.stat().st_size == item["bytes"]
        assert writer.sha256(path) == item["sha256"]


def test_generated_input_has_registered_geometry_and_control_semantics() -> None:
    values = writer.parameters(writer.load_json(writer.CONTRACT))
    root = ElementTree.parse(ROOT / writer.DEFINITION_TARGET).getroot()
    assert root.find(".//gravity").attrib == {"x": "0", "y": "0", "z": "0", "comment": "Global gravity disabled; forcing is accinput linear X acceleration.", "units_comment": "m/s^2"}
    assert [node.attrib["mk"] for node in root.findall(".//setmkfluid")] == ["0"]
    assert [node.attrib["mk"] for node in root.findall(".//setmkbound")] == ["0"]
    assert root.find(".//drawbox/boxfill").text == "top|bottom"
    parameters = {node.attrib["key"]: node.attrib["value"] for node in root.findall(".//parameter")}
    assert parameters["Boundary"] == "2"
    assert parameters["XYPeriodic"] == "0"
    assert math.isclose(float(parameters["TimeMax"]), float(values["t_end"]), rel_tol=0, abs_tol=1e-14)
    accinput = root.find(".//accinput")
    assert accinput is not None and accinput.attrib == {"mkfluid": "0"}
    assert accinput.find("globalgravity").attrib["value"] == "0"
    assert accinput.find("acctimesfile").attrib["value"] == "acceleration/F8_OPC_q0p500_acceleration.csv"
