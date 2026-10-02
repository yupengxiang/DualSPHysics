from __future__ import annotations

import importlib.util
from pathlib import Path
import xml.etree.ElementTree as ET


SCRIPT = Path(__file__).parents[1] / "scripts/ds_data02_f6_handoff_20261002_dp020_dp0125_v2.py"
SPEC = importlib.util.spec_from_file_location("ds_data02_f6_dp020_dp0125_v2", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_epsilon_free_scope_keeps_only_the_two_finer_dps() -> None:
    assert MODULE.MODULE.DP_LADDER == (("dp020", 0.020), ("dp0125", 0.0125))
    assert MODULE.SCOPE_ROOT.name == "dp020_dp0125_cpu_002"


def test_epsilon_free_fluid_span_is_exact_and_rigid_contract_is_explicit() -> None:
    xml = MODULE._definition_xml_without_epsilon("simple_free_response", "dp0125", 0.0125)
    root = ET.fromstring(xml)
    fluid = root.find('.//drawbox[@cmt="Frozen continuous fluid cell-centre population"]')
    floating = root.find("./casedef/floatings/floating")

    assert fluid is not None and floating is not None
    assert float(fluid.find("size").get("x")) == 3.9875
    assert float(fluid.find("size").get("y")) == 1.5875
    assert float(fluid.find("size").get("z")) == 0.7875
    assert floating.find("center").attrib["z"] == "1.08"
    assert floating.find("inertia").attrib["x"] == "8.53333333333"


def test_prior_mass_failure_and_dp025_negative_evidence_remain_bound() -> None:
    assert MODULE.V1_FAILURE.is_file()
    assert MODULE.DP025_FAILURE.is_file()
    assert MODULE.DP025_SPATIAL.is_file()
