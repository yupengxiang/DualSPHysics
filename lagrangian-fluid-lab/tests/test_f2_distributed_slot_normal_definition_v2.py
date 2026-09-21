from __future__ import annotations

import json
from pathlib import Path

from scripts.f2_distributed_slot_normal_definition_v2 import write_contract, write_definition


def test_v2_definition_mirrors_main_layers(tmp_path):
    import xml.etree.ElementTree as ET

    path = tmp_path / "v2_Def.xml"
    write_definition(path)
    root = ET.parse(path).getroot()
    layers = [node.find("layers").get("vdp") for node in root.findall("./casedef/geometry/commands/list[@name='GeometryForNormals']/drawbox")]
    assert layers == ["0,-1,-2"] * 5


def test_v2_contract_records_no_native_product(tmp_path, monkeypatch):
    import scripts.f2_distributed_slot_normal_definition_v2 as module

    definition = tmp_path / "v2_Def.xml"
    base = tmp_path / "scope"
    write_definition(definition)
    monkeypatch.setattr(module, "DEFINITION", definition)
    value = write_contract(base)
    assert value["fresh_input"]["native_bi4_present"] is False
    assert value["execution_controls"]["qualification_credit"] == 0
