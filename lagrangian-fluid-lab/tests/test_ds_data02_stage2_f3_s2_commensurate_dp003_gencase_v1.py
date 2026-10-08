from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f3_s2_commensurate_dp003_gencase_v1.py"
REQUEST = (ROOT / "campaigns/ds-data-02/stage2/requests/"
           / "f3-s2-commensurate-dp003-gencase-v1-root-forward-096-001/"
           / "f3-s2-commensurate-dp003-gencase-v1-request.json")
MANIFEST = REQUEST.parent / "f3-s2-commensurate-dp003-gencase-v1-manifest.json"


def module():
    spec = importlib.util.spec_from_file_location("f3_s2_commensurate_dp003_gencase_v1", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def source_xml() -> str:
    return """<?xml version="1.0" encoding="utf-8"?>
<case>
  <casedef>
    <geometry>
      <definition dp="0.006"><pointref x="0.003" y="0.003" z="0.003"/></definition>
      <commands>
        <list name="GeometryForNormals">
          <drawbox><point x="-0.45" y="-0.09" z="0"/><size x="0.9" y="0.18" z="0.51"/></drawbox>
        </list>
        <mainlist>
          <drawbox><boxfill>solid</boxfill><point x="-0.447" y="-0.087" z="0.003"/><size x="0.894" y="0.174" z="0.084"/></drawbox>
          <drawbox><boxfill>all^top</boxfill><point x="-0.453" y="-0.093" z="-0.003"/><size x="0.906" y="0.186" z="0.513"/></drawbox>
        </mainlist>
      </commands>
    </geometry>
  </casedef>
  <execution>
    <special><accinputs><accinput><acctimesfile value="CaseSloshingAccData.csv"/></accinput></accinputs></special>
    <particles><fixed count="111708"/><fluid count="67500"/></particles>
    <constants><massfluid value="0.000216"/></constants>
  </execution>
</case>
"""


def test_candidate_builder_changes_only_declared_resolution_selectors(tmp_path: Path, monkeypatch):
    loaded = module()
    source = tmp_path / "source.xml"
    candidate = tmp_path / "candidate.xml"
    source.write_text(source_xml(), encoding="utf-8")
    monkeypatch.setattr(loaded, "SOURCE_XML_SHA256", loaded.sha256(source))
    provenance = loaded.build_candidate_xml(source, candidate)
    projection = provenance["candidate_projection"]
    assert projection["dp_m"] == pytest.approx(0.003)
    assert projection["pointref_m"] == pytest.approx([0.0015, 0.0015, 0.0015])
    assert projection["fluid_low_m"] == pytest.approx([-0.4485, -0.0885, 0.0015])
    assert projection["fluid_size_m"] == pytest.approx([0.897, 0.177, 0.087])
    assert projection["bound_low_m"] == pytest.approx([-0.4515, -0.0915, -0.0015])
    assert projection["bound_size_m"] == pytest.approx([0.903, 0.183, 0.5115])
    assert projection["normal_low_m"] == pytest.approx([-0.45, -0.09, 0.0])
    assert projection["normal_size_m"] == pytest.approx([0.9, 0.18, 0.51])
    assert projection["control_name"] == "CaseSloshingAccData.csv"


def test_generated_projection_requires_exact_fluid_count_and_mass(tmp_path: Path, monkeypatch):
    loaded = module()
    source = tmp_path / "source.xml"
    candidate = tmp_path / "candidate.xml"
    source.write_text(source_xml(), encoding="utf-8")
    monkeypatch.setattr(loaded, "SOURCE_XML_SHA256", loaded.sha256(source))
    loaded.build_candidate_xml(source, candidate)
    tree = ET.parse(candidate)
    root = tree.getroot()
    particles = next(node for node in root.iter() if loaded.local(node.tag) == "particles")
    fluid = next(node for node in list(particles) if loaded.local(node.tag) == "fluid")
    fixed = next(node for node in list(particles) if loaded.local(node.tag) == "fixed")
    fluid.set("count", "540000")
    fixed.set("count", "1")
    constants = next(node for node in root.iter() if loaded.local(node.tag) == "constants")
    massfluid = next(node for node in list(constants) if loaded.local(node.tag) == "massfluid")
    massfluid.set("value", "0.000027")
    generated = tmp_path / "generated.xml"
    tree.write(generated, encoding="utf-8", xml_declaration=True)
    projection = loaded.generated_projection(generated)
    assert projection["counts"] == {"fixed": 1, "fluid": 540000}
    assert projection["massfluid_kg"] == pytest.approx(0.000027)
    assert projection["counts"]["fluid"] * projection["massfluid_kg"] == pytest.approx(14.58)


def test_targets_make_owner_dimensions_commensurate():
    loaded = module()
    target = loaded.targets()
    assert target["fluid_low_m"] == pytest.approx([-0.4485, -0.0885, 0.0015])
    assert target["fluid_size_m"] == pytest.approx([0.897, 0.177, 0.087])
    assert 300 * 60 * 30 == loaded.EXPECTED_FLUID_COUNT
    assert loaded.EXPECTED_MASSFLUID_KG == pytest.approx(0.000027)
    assert loaded.EXPECTED_SAMPLE_MASS_KG == pytest.approx(14.58)


def test_source_projection_rejects_wrong_dp(tmp_path: Path, monkeypatch):
    loaded = module()
    source = tmp_path / "source.xml"
    source.write_text(source_xml().replace('dp="0.006"', 'dp="0.0048"'), encoding="utf-8")
    monkeypatch.setattr(loaded, "SOURCE_XML_SHA256", loaded.sha256(source))
    with pytest.raises(ValueError, match="source dp"):
        loaded.build_candidate_xml(source, tmp_path / "candidate.xml")


def test_request_scope_constants_are_initial_only():
    loaded = module()
    assert loaded.SOURCE_DP_M == pytest.approx(0.006)
    assert loaded.TARGET_DP_M == pytest.approx(0.003)
    assert loaded.ESTIMATED_TOTAL_COUNT == loaded.ESTIMATED_FIXED_COUNT + loaded.EXPECTED_FLUID_COUNT


def test_guarded_request_binds_commensurate_candidate_without_native_payload():
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert request["gencase_launch"] is True
    assert request["solver_launch"] is False
    assert request["deferred_input_file_count"] == 0
    assert request["candidate_estimate"]["fluid_particles"] == 540000
    assert request["candidate_estimate"]["total_particles_estimate"] == 986832
    assert request["estimated_storage_bytes"] == 256 * 1024 * 1024
    assert request["guard_policy"]["no_source_bi4_read"] is True
    assert manifest["candidate"]["fluid_axis_counts"] == [300, 60, 30]
    assert manifest["candidate"]["historical_dp0048_immutable"] is True
