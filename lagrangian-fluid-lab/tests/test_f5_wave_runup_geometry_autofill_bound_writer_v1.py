from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET


LAB = Path(__file__).resolve().parents[1]
SCRIPT = LAB / "scripts/f5_wave_runup_geometry_autofill_bound_writer_v1.py"
SPEC = importlib.util.spec_from_file_location("f5_autofill_bound_writer", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_v4_contract_is_zero_credit_and_fresh():
    review = MODULE._verify_root_review()
    assert review["matrix_credit"] == 0
    prior = MODULE.load(MODULE.V3_PREFLIGHT)
    assert prior["geometry_repair"]["blocks_endpoint_inside_count"] == 1


def test_v4_definition_writer_uses_two_official_autofill_draws(tmp_path):
    target = LAB / ".test-f5-autofill-bound-v4.xml"
    try:
        info = MODULE._definition(MODULE.SOURCE_DEFINITION, target)
        assert info["autofill_draws"] == 2
        assert info["separate_boundary_redraws"] == 0
        root = ET.parse(target).getroot()
        draws = [node for node in root.findall("./casedef/geometry/commands/mainlist/drawfilestl") if node.get("file") in {MODULE.SLOPE_NAME, MODULE.BLOCKS_NAME}]
        assert len(draws) == 2
        assert all(node.get("autofill") == "true" for node in draws)
    finally:
        target.unlink(missing_ok=True)
