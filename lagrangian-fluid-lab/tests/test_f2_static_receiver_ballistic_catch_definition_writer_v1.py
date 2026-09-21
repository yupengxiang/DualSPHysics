from __future__ import annotations

import json
from pathlib import Path

from scripts import f2_static_receiver_ballistic_catch_definition_writer_v1 as writer


def test_writer_materializes_literal_definition_and_static_contract(tmp_path: Path):
    definition = tmp_path / "input" / f"{writer.CASE_ID}_Def.xml"
    contract = tmp_path / "input" / "contract.json"
    result = writer.write_definition(definition)
    assert result["case_id"] == writer.CASE_ID
    inspected = writer.inspect_definition(definition)
    assert inspected["source_particle_count"] == 32 * 24 * 24
    written = writer.write_contract(definition, contract)
    payload = json.loads(contract.read_text())
    assert written["definition_sha256"] == inspected["sha256"]
    assert payload["definition_sha256"] == inspected["sha256"]
    assert payload["source_reuse"] is False
    assert payload["qualification_claim"] == "none; fresh input only"


def test_writer_rejects_existing_definition(tmp_path: Path):
    definition = tmp_path / f"{writer.CASE_ID}_Def.xml"
    definition.write_text("sentinel")
    try:
        writer.write_definition(definition)
    except FileExistsError:
        pass
    else:
        raise AssertionError("writer accepted a reused Definition path")


def test_definition_uses_static_receiver_and_no_old_path(tmp_path: Path):
    definition = tmp_path / f"{writer.CASE_ID}_Def.xml"
    writer.write_definition(definition)
    text = definition.read_text()
    assert "F2_airborne_slug" not in text
    assert "submerged" not in text.lower()
    assert "moving" not in text.lower()
    assert 'key="Boundary" value="1"' in text
