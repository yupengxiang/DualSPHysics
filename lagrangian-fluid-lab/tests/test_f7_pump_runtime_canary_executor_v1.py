from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from scripts.f7_pump_runtime_canary_executor_v1 import (
    _derived_definition,
    _fluid_axis,
)
from scripts.f7_pump_geometry_adapter_v1 import DEFAULT_DEFINITION


def test_derived_definition_changes_only_bounded_runtime_window(tmp_path):
    target = tmp_path / "CasePump_Def.xml"
    _derived_definition(DEFAULT_DEFINITION, target, time_max_s=0.6, time_out_s=0.02, dp_m=0.01)
    parameters = {
        node.get("key"): node.get("value")
        for node in ET.parse(target).getroot().findall("./execution/parameters/parameter")
    }
    assert float(parameters["TimeMax"]) == pytest.approx(0.6)
    assert float(parameters["TimeOut"]) == pytest.approx(0.02)
    assert ET.parse(target).getroot().find("./casedef/geometry/definition").get("dp") == "0.01"


def test_fluid_axis_rejects_missing_or_overlapping_ranges(tmp_path):
    missing = tmp_path / "missing.xml"
    missing.write_text("<root />")
    with pytest.raises(ValueError, match="no fluid blocks"):
        _fluid_axis(missing)
    overlapping = tmp_path / "overlap.xml"
    overlapping.write_text(
        "<root><particles><fluid begin='0' count='2'/>"
        "<fluid begin='1' count='2'/></particles></root>"
    )
    with pytest.raises(ValueError, match="overlap"):
        _fluid_axis(overlapping)
