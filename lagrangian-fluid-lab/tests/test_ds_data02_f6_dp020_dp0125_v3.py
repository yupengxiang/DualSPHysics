from __future__ import annotations

import importlib.util
from pathlib import Path
import xml.etree.ElementTree as ET


SCRIPT = Path(__file__).parents[1] / "scripts/ds_data02_f6_handoff_20261002_dp020_dp0125_v3.py"
SPEC = importlib.util.spec_from_file_location("ds_data02_f6_dp020_dp0125_v3", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_phase_scope_has_unique_case_lineage_and_finer_dps() -> None:
    assert MODULE.MODULE.DP_LADDER == (("dp020", 0.020), ("dp0125", 0.0125))
    assert MODULE.SCOPE_ROOT.name == "dp020_dp0125_cpu_003"
    assert all("PHASE003" in value["case_prefix"] for value in MODULE.MODULE.MECHANISMS.values())


def test_phase_aligned_definition_uses_half_dp_pointref_and_fixed_rigid_contract() -> None:
    xml = MODULE._definition_xml_phase_aligned("simple_free_response", "dp0125", 0.0125)
    root = ET.fromstring(xml)
    definition = root.find("./casedef/geometry/definition")
    floating = root.find("./casedef/floatings/floating")
    fluid = root.find('.//drawbox[@cmt="Frozen continuous fluid cell-centre population"]')

    assert definition is not None and floating is not None and fluid is not None
    assert definition.find("pointref").attrib == {"x": "0.00625", "y": "0.00625", "z": "0.00625"}
    assert float(fluid.find("size").get("x")) == 3.9875
    assert floating.find("center").attrib["z"] == "1.08"
    assert floating.find("inertia").attrib["z"] == "13.6533333333"


def test_prior_failures_remain_available() -> None:
    assert MODULE.V2_FAILURE.is_file()
    assert MODULE.V1_FAILURE.is_file()
    assert MODULE.DP025_FAILURE.is_file()
