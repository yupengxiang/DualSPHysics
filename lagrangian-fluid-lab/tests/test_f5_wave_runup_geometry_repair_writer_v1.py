from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET


LAB = Path(__file__).resolve().parents[1]
SCRIPT = LAB / "scripts/f5_wave_runup_geometry_repair_writer_v1.py"
SPEC = importlib.util.spec_from_file_location("f5_geometry_repair_writer", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_writer_materializes_only_new_identity_and_preserves_parameters(tmp_path, monkeypatch):
    root = LAB / ".test-f5-geometry-repair-writer"
    shutil.rmtree(root, ignore_errors=True)
    monkeypatch.setattr(MODULE, "ROOT", root)
    monkeypatch.setattr(MODULE, "INPUT", root / "input")
    monkeypatch.setattr(MODULE, "ROOT_REVIEW", LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/geometry-repair-audit-v1/root-review-receipt-v1.json")
    monkeypatch.setattr(MODULE, "PROPOSAL", LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/geometry-repair-audit-v1/geometry-repair-proposal-audit-v1.json")
    monkeypatch.setattr(MODULE, "CONTRACT", root / "input/geometry-repair-contract-v1.json")
    monkeypatch.setattr(MODULE, "SOURCE_DEFINITION", LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v2/F5_wave_runup_q0p50_dp0p0075_Def.xml")
    monkeypatch.setattr(MODULE, "WRITER", SCRIPT)
    try:
        # Use the real root review and run the low-level definition writer
        # without invoking any external executable.
        target = root / "input/v3.xml"
        motion = root / "input/motion.dat"
        motion.parent.mkdir(parents=True)
        motion_info = MODULE._motion(MODULE.SOURCE_DIR / "Mov_piston.dat", motion, 1.0)
        definition_info = MODULE._definition(MODULE.SOURCE_DEFINITION, target)
        assert motion_info["row_count"] == 626
        assert definition_info["void_precursors"] == 2
        tree = ET.parse(target)
        commands = list(tree.getroot().findall("./casedef/geometry/commands/mainlist/*"))
        assert sum(node.tag == "setmkvoid" for node in commands) == 2
        assert sum(node.tag == "drawfilestl" and node.get("autofill") == "true" for node in commands) == 2
        assert sum(node.tag == "drawfilestl" and node.get("file") == MODULE.SLOPE_NAME for node in commands) == 2
        assert sum(node.tag == "drawfilestl" and node.get("file") == MODULE.BLOCKS_NAME for node in commands) == 2
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_contract_rejects_scientific_credit():
    assert MODULE.TIME_MAX == 16.0
    assert MODULE.OUTPUT_DT == 0.02
    assert MODULE.CASE_ID.endswith("geomrepair_v3")
