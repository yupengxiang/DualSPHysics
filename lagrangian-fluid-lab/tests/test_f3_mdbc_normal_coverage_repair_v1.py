"""Contract checks for the additive F3 mDBC normal-coverage repair inputs."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import xml.etree.ElementTree as ET


LAB = Path(__file__).resolve().parents[1]
FAMILY = LAB / "campaigns/ds-data-02/families/F3"
PARENTS = FAMILY / "parent_inputs"
EVIDENCE = PARENTS / "normal_coverage_repair_evidence.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _normal_contract(path: Path) -> tuple[float, bool]:
    node = ET.parse(path).getroot().find("./casedef/normals/norgeometry")
    assert node is not None
    distance = node.find("distanceh")
    assert distance is not None
    shapes = node.find("svshapes")
    return float(distance.get("v", "nan")), shapes is not None and shapes.get("v") == "true"


def _load_generator():
    path = LAB / "scripts/ds_data02_f3.py"
    spec = importlib.util.spec_from_file_location("ds_data02_f3_repair_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repair_changes_only_normal_association_contract() -> None:
    pairs = [
        (
            PARENTS / "dual_axis_phase/F3_DualAxisPhase_Def.xml",
            PARENTS / "dual_axis_phase_normal_repair01/F3_DualAxisPhase_Def.xml",
            PARENTS / "dual_axis_phase/F3_DualAxisPhase_Control.csv",
            PARENTS / "dual_axis_phase_normal_repair01/F3_DualAxisPhase_Control.csv",
        ),
        (
            PARENTS / "eccentric_baffle_exchange/F3_EccentricBaffle_Def.xml",
            PARENTS / "eccentric_baffle_exchange_normal_repair01/F3_EccentricBaffle_Def.xml",
            PARENTS / "eccentric_baffle_exchange/F3_EccentricBaffle_Motion.txt",
            PARENTS / "eccentric_baffle_exchange_normal_repair01/F3_EccentricBaffle_Motion.txt",
        ),
    ]
    for parent_def, repair_def, parent_control, repair_control in pairs:
        assert _normal_contract(parent_def) == (2.0, False)
        assert _normal_contract(repair_def) == (3.0, True)
        assert parent_control.read_bytes() == repair_control.read_bytes()
        assert _sha256(parent_control) == _sha256(repair_control)


def test_repair_evidence_binds_actual_solver_output_paths_and_keeps_qn_pending() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert evidence["root_cause_class"] == "mdbc_normal_association_coverage"
    assert evidence["repair_budget"]["used_repairs"] == 1
    assert evidence["repair_budget"]["remaining_repairs"] == 1
    assert evidence["status"].endswith("solver_qi_pending_qn_pending")
    for row in evidence["parents"]:
        run_out = Path(row["native_evidence"]["run_out"]["path"])
        assert "/solver_output/Run.out" in str(run_out)
        assert run_out.is_file()
        assert _sha256(run_out) == row["native_evidence"]["run_out"]["sha256"]
        parent_drive = row.get("parent_control", row.get("parent_motion"))
        repair_drive = row.get("repair_control", row.get("repair_motion"))
        assert parent_drive["sha256"] == repair_drive["sha256"]
        assert row["diagnostic"]["initial_fluid_solid_intersection_count"] == 0


def test_generator_materialises_repair_inputs_without_changing_parent_bytes(tmp_path: Path) -> None:
    generator = _load_generator()
    manifest = generator._write_parent_inputs(tmp_path)
    assert len(manifest["parents"]) == 2
    assert len(manifest["repairs"]) == 3
    assert len(manifest["fallbacks"]) == 1
    for parent in manifest["parents"]:
        repairs = [
            repair for repair in manifest["repairs"]
            if repair["parent_case_id"] == parent["case_id"]
        ]
        assert repairs
        for repair in repairs:
            assert repair["parent_definition_sha256"] == parent["definition"]["sha256"]
            assert repair["control"]["sha256"] == parent["control"]["sha256"]
            repair_def = Path(repair["definition"]["path"])
            assert _normal_contract(repair_def) == (3.0, True)
    fallback = manifest["fallbacks"][0]
    fallback_def = Path(fallback["definition"]["path"])
    fallback_root = ET.parse(fallback_def).getroot()
    control_node = fallback_root.find("./execution/special/accinputs/accinput/acctimesfile")
    assert control_node is not None and control_node.get("value") == "F3_DualAxisPhase_Control.csv"
    parameters = {
        node.get("key"): node.get("value")
        for node in fallback_root.findall("./execution/parameters/parameter")
    }
    assert parameters["TimeMax"] == "10.0"
    assert parameters["TimeOut"] == "0.0025"
