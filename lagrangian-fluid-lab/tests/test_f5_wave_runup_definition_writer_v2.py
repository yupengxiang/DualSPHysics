import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


LAB = Path(__file__).resolve().parents[1]
CONTRACT = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v2/fresh-definition-contract-v2.json"
WRITER = LAB / "scripts/f5_wave_runup_definition_writer_v2.py"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load():
    return json.loads(CONTRACT.read_text())


def test_f5_v2_repair_is_new_and_solver_closed():
    value = load()
    assert value["schema"] == "core.f5.third_t1.definition_materialization.v2"
    assert value["status"] == "definition_written_preflight_pending"
    assert value["qualification_claim"] == "none"
    assert value["candidate"]["revision_id"] == "F5_piston_amplitude_runup_v2"
    repair = value["repair_lineage"]
    assert repair["failure_class"] == "definition_relative_asset_not_adjacent"
    assert repair["prior_output_reused"] is False
    assert repair["prior_generated_xml_reused"] is False
    assert repair["prior_bi4_reused"] is False
    assert repair["prior_trajectory_reused"] is False
    assert value["authorization"]["gencase_authorized"] is False
    assert value["execution_controls"]["qualification_credit"] == 0


def test_f5_v2_places_all_definition_relative_assets_adjacent():
    value = load()
    root = LAB / value["fresh_identity"]["output_directory"]
    definition = root / Path(value["fresh_identity"]["definition"]["output"]["path"]).name
    assert definition.is_file()
    xml = ET.parse(definition).getroot()
    motion_name = xml.find("./casedef/motion/objreal/mvpredef/file").get("name")
    assert motion_name and (root / motion_name).is_file()
    assert (root / "Slope.stl").is_file()
    assert (root / "Blocks_3D_scaled.stl").is_file()
    assert set(value["fresh_identity"]["required_relative_assets"]) <= {path.name for path in root.iterdir() if path.is_file()}


def test_f5_v2_writer_hash_is_current():
    value = load()
    implementation = value["implementation"]
    assert implementation["path"] == "scripts/f5_wave_runup_definition_writer_v2.py"
    assert implementation["sha256"] == sha256(WRITER)
