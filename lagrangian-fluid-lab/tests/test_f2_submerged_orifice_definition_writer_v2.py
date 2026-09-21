from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET

from scripts.f2_submerged_orifice_definition_writer_v2 import (
    CASE_ID,
    DEFAULT_BASE,
    DEFAULT_CONTRACT,
    DEFAULT_DEFINITION,
    DEFAULT_PROPOSAL,
    FAILED_ANCHOR_DIR,
    inspect_definition,
    verify_contract,
    write_definition,
)


LAB = Path(__file__).resolve().parents[1]


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_fresh_definition_is_literal_v2_normal_contract():
    inspection = inspect_definition(DEFAULT_DEFINITION)
    assert inspection["case_id"] == CASE_ID
    assert inspection["normal_list"] == {
        "outer_boxfill": "all^top",
        "gate_boxfill": "bottom | top | left | right | front | back",
        "outer_layers_vdp": "0",
        "gate_layers_vdp": "0",
    }
    assert inspection["mainlist"] == {
        "runlist_first": True,
        "outer_layers_vdp": "0,1,2",
        "setmkvoid_gate_precursor": True,
        "gate_layers_vdp": "0,-1,-2",
        "source_is_unlayered": True,
    }
    assert inspection["normal_block"] == {"active": True, "distanceh": 3.0, "svshapes": True}
    assert inspection["runtime_invoked"] is False


def test_fresh_definition_contract_is_hash_bound_and_runtime_closed():
    contract = verify_contract(DEFAULT_CONTRACT, DEFAULT_PROPOSAL, DEFAULT_DEFINITION)
    assert contract["status"] == "fresh_definition_static_contract_not_runtime_authorized"
    assert contract["decision"] == "fresh_definition_writer_reviewable_cpu_native_still_closed"
    assert contract["case_id"] == CASE_ID
    assert contract["fresh_definition"]["old_anchor_definition_reused"] is False
    assert contract["fresh_definition"]["old_anchor_bi4_reused"] is False
    assert contract["preflight"]["status"] == "not_run"
    assert contract["preflight"]["fresh_generated_xml_present"] is False
    assert contract["preflight"]["fresh_native_bi4_present"] is False
    assert contract["failure_denominator"]["planned_rows"] == 15
    assert contract["failure_denominator"]["qualification_numerator"] == 0
    auth = contract["authorization"]
    assert all(auth[key] is False for key in (
        "cpu_gencase", "native_decode", "solver_launch", "gpu_launch",
        "job_spec_creation", "matrix_submission",
    ))
    assert auth["queue_mutation"] == 0
    assert auth["ledger_mutation"] == 0
    assert auth["registry_mutation"] == 0
    assert ".bi4" not in json.dumps(contract)


def test_writer_emits_new_identity_without_reading_old_definition(tmp_path: Path):
    target = tmp_path / f"{CASE_ID}_Def.xml"
    record = write_definition(target)
    assert record["case_id"] == CASE_ID
    assert target.is_file()
    assert target.resolve() != (FAILED_ANCHOR_DIR / "F2_ORIFICE_q0p50_dp0075_spatial_Def.xml").resolve()
    root = ET.parse(target).getroot()
    assert root.find("./casedef/geometry/commands/list[@name='GeometryForNormals']") is not None
    assert root.find("./casedef/geometry/commands/mainlist/setmkvoid") is not None
    assert "anchor-q0p5-dp0p0075" not in target.read_text(encoding="utf-8")
