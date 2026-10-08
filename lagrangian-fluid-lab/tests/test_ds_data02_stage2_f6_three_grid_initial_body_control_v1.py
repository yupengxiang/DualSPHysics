"""Tests for the bounded F6 three-grid source/receipt audit."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f6_three_grid_initial_body_control_v1.py"
REQUEST = (
    ROOT
    / "campaigns/ds-data-02/stage2/requests/"
    / "f6-s1-s2-three-grid-initial-body-control-v1-root-forward-083-001/"
    / "f6-s1-s2-three-grid-initial-body-control-v1-request.json"
)
MANIFEST = (
    ROOT
    / "campaigns/ds-data-02/stage2/requests/"
    / "f6-s1-s2-three-grid-initial-body-control-v1-root-forward-083-001/"
    / "f6-s1-s2-three-grid-initial-body-control-v1-manifest.json"
)


def module():
    spec = importlib.util.spec_from_file_location("f6_three_grid_initial_body_control_v1", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_request_is_small_xml_json_only_and_keeps_mass_semantics_separate():
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert request["hdf5_read"] is False
    assert request["bi4_read"] is False
    assert request["vtk_read"] is False
    assert request["gencase_launch"] is False
    assert request["solver_launch"] is False
    assert len(manifest["rows"]) == 6
    assert all(not any(ext in item.lower() for ext in (".h5", ".bi4", ".obi4", ".vtk"))
               for item in request["input_files"])
    assert request["source_binding"]["physical_body_mass_kg"] == 128.0
    assert request["source_binding"]["original_grid_sample_mass_kg"] == 256.0
    assert request["source_binding"]["physical_body_mass_kg"] != request["source_binding"]["original_grid_sample_mass_kg"]


def test_actual_six_row_source_receipt_audit(tmp_path):
    report = module().audit(MANIFEST, tmp_path / "report.json")
    assert report["status"] == "completed_source_xml_receipt_audit"
    assert len(report["rows"]) == 6
    assert report["comparability"]["source_xml_geometry_and_control_excluding_dp_and_omega"] == "PASS"
    assert report["comparability"]["native_identity"] == "UNKNOWN_EXCEPT_REUSED_ORIGINAL_FRAME0_SCOPE"
    for row in report["rows"]:
        assert row["physical_body_mass_kg"] == pytest.approx(128.0)
        assert row["counts"]["floating"] > 0
        assert row["sample_floating_mass_kg"] > 0


def test_manufactured_generated_xml_does_not_alias_sample_mass_to_body_mass(tmp_path):
    xml = """<?xml version='1.0'?>
    <case>
      <casedef>
        <constantsdef><gravity x='0' y='0' z='-9.81'/><cflnumber value='0.2'/></constantsdef>
        <geometry><definition dp='0.025'/></geometry>
        <floatings><floating mkbound='50'><massbody value='128'/><center x='2.4' y='1.2' z='1.08'/>
          <inertia x='8.53333333333' y='8.53333333333' z='13.6533333333'/>
          <angularvelini x='0.076' y='0.114' z='0.057'/></floating></floatings>
        <initials><angularvelini x='0.076' y='0.114' z='0.057'/></initials>
      </casedef>
      <particles><fixed count='2'/><floating count='4'/><fluid count='3'/></particles>
      <constants><masspart value='0.015625'/><massfluid value='0.015625'/></constants>
    </case>"""
    path = tmp_path / "generated.xml"
    path.write_text(xml, encoding="utf-8")
    parsed = module().parse_generated(path, "manufactured")
    assert parsed["counts"] == {"fixed": 2, "floating": 4, "fluid": 3}
    assert parsed["sample_floating_mass_kg"] == pytest.approx(0.0625)
    assert parsed["contract"]["body_mass_kg"] == pytest.approx(128.0)
    assert parsed["sample_floating_mass_kg"] != parsed["contract"]["body_mass_kg"]
