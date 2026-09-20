import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


LAB = Path(__file__).resolve().parents[1]
CONTRACT = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v1/fresh-definition-contract-v1.json"
WRITER = LAB / "scripts/f5_wave_runup_definition_writer_v1.py"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load():
    return json.loads(CONTRACT.read_text())


def test_f5_definition_contract_is_fresh_and_solver_closed():
    value = load()
    assert value["schema"] == "core.f5.third_t1.definition_materialization.v1"
    assert value["status"] == "definition_written_preflight_pending"
    assert value["qualification_claim"] == "none"
    assert value["candidate"] == {"family": "F5", "scope_id": "F5_prescribed_wave_runup_x_v1", "q": 0.5, "piston_scale": 1.0, "dp_m": 0.0075}
    auth = value["authorization"]
    assert auth["gencase_authorized"] is False
    assert auth["native_decode_authorized"] is False
    assert auth["solver_authorized"] is False
    assert auth["gpu_authorized"] is False
    assert auth["queue_mutation"] == auth["ledger_mutation"] == auth["registry_mutation"] == 0
    controls = value["execution_controls"]
    assert controls["definition_written"] is True
    assert controls["motion_written"] is True
    assert controls["gencase_invoked"] is False
    assert controls["solver_invoked"] is False
    assert controls["qualification_credit"] == 0


def test_f5_definition_has_expected_literal_inputs_and_gauges():
    value = load()
    definition = LAB / value["fresh_identity"]["definition"]["output"]["path"]
    motion = LAB / value["fresh_identity"]["motion"]["output"]["path"]
    assert definition.is_file() and motion.is_file()
    root = ET.parse(definition).getroot()
    assert root.find("./casedef/geometry/definition").get("dp") == "0.0075"
    assert root.find("./casedef/motion/objreal/mvpredef/file").get("name") == motion.name
    params = {node.get("key"): node.get("value") for node in root.findall("./execution/parameters/parameter")}
    assert params["TimeMax"] == "16"
    assert params["TimeOut"] == "0.02"
    gauges = {node.get("name") for node in root.findall("./execution/special/gauges/swl")}
    assert {"WG1", "WG2", "WG3", "WG4"} <= gauges
    rows = [line.split() for line in motion.read_text().splitlines() if line.strip()]
    assert rows[0][0] == "0.0000000000"
    assert float(rows[-1][0]) >= 15.0
    assert all(len(row) == 2 for row in rows)


def test_f5_definition_writer_hash_bindings_are_current():
    value = load()
    implementation = value["implementation"]
    assert implementation["path"] == "scripts/f5_wave_runup_definition_writer_v1.py"
    assert implementation["sha256"] == sha256(WRITER)
    assert CONTRACT.stat().st_size > 0
