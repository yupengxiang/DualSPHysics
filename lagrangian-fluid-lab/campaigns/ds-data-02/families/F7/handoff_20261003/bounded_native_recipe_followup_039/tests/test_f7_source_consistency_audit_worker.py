"""Synthetic unit and integration tests for F7 Source-Consistency Audit Worker.

Scope: handoff_20261003/bounded_native_recipe_followup_039
Rules: Clearly synthetic tests allowed; no actual H5/CSV array analysis in owner process.
"""

from __future__ import annotations

import json
import math
import sys
import tempfile
from pathlib import Path

import pytest

# Add worker to import path
MODULE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE_ROOT))

from f7_source_consistency_audit_worker import (
    audit_case_source_consistency,
    parse_xml_definition,
    run_source_consistency_audit,
    sha256_file,
)


@pytest.fixture
def mother_constants() -> dict:
    return {
        "tank_size_m": [1.2, 0.8, 0.6],
        "tank_origin_m": [-0.6, -0.4, 0.0],
        "paddle_size_m": [0.06, 0.48, 0.48],
        "paddle_origin_m": [-0.07, -0.24, 0.05],
        "rotation_axis_p1_m": [-0.04, 0.0, 0.05],
        "rotation_axis_p2_m": [-0.04, 0.0, 1.05],
        "time_window_s": [0.0, 12.0],
        "time_out_s": 0.02,
        "nominal_frames": 601,
        "fluid_fill_target_mass_kg": 320.1984,
        "frozen_kinetic_scale_j": 89.584705923,
    }


def test_synthetic_xml_parsing(tmp_path: Path):
    """Test parse_xml_definition on a clearly synthetic DualSPHysics XML."""
    synthetic_xml = tmp_path / "synthetic_case_Def.xml"
    content = """<?xml version="1.0" encoding="UTF-8"?>
<case>
  <casedef>
    <constantsdef>
      <gravity x="0" y="0" z="-9.81" />
      <rhop0 value="1000" />
      <coefh value="0.91924" />
      <coefsound value="30" />
      <gamma value="7" />
    </constantsdef>
    <geometry>
      <definition dp="0.02">
        <pointref x="0.01" y="0.01" z="0.01" />
        <pointmin x="-0.7" y="-0.5" z="-0.1" />
        <pointmax x="0.7" y="0.5" z="0.7" />
      </definition>
      <commands>
        <mainlist>
          <setmkbound mk="0" />
          <drawbox>
            <point x="-0.6" y="-0.4" z="0.0" />
            <size x="1.2" y="0.8" z="0.6" />
            <layers vdp="0,1,2,3" />
          </drawbox>
          <setmkfluid mk="1" />
          <fillbox x="0.0" y="0.0" z="0.2">
            <modefill>void</modefill>
            <point x="-0.5" y="-0.3" z="0.0" />
            <size x="1.0" y="0.6" z="0.4" />
          </fillbox>
        </mainlist>
      </commands>
    </geometry>
  </casedef>
  <execution>
    <parameters>
      <parameter key="TimeMax" value="12" />
      <parameter key="TimeOut" value="0.02" />
      <parameter key="Boundary" value="1" />
    </parameters>
  </execution>
</case>"""
    synthetic_xml.write_text(content, encoding="utf-8")

    parsed = parse_xml_definition(synthetic_xml)
    assert parsed["dp_m"] == 0.02
    assert parsed["pointref"] == [0.01, 0.01, 0.01]
    assert len(parsed["solid_boxes"]) == 1
    assert parsed["solid_boxes"][0]["layers"] == "0,1,2,3"
    assert parsed["constants"]["gravity_z"] == -9.81
    assert parsed["execution_parameters"]["TimeMax"] == "12"


def test_audit_case_detects_gravitational_gap(tmp_path: Path, mother_constants: dict):
    """Verify that audit_case_source_consistency calculates air gap and potential energy release."""
    gapped_xml = tmp_path / "gapped_case_Def.xml"
    content = """<?xml version="1.0" encoding="UTF-8"?>
<case>
  <casedef>
    <constantsdef>
      <gravity x="0" y="0" z="-9.81" />
      <rhop0 value="1000" />
      <coefh value="0.91924" />
      <coefsound value="30" />
    </constantsdef>
    <geometry>
      <definition dp="0.016">
        <pointref x="0.002" y="0.010" z="0.010" />
      </definition>
      <commands>
        <mainlist>
          <setmkbound mk="0" />
          <drawbox>
            <point x="-0.6" y="-0.4" z="0.0" />
            <size x="1.2" y="0.8" z="0.6" />
            <layers vdp="0,1,2" />
          </drawbox>
          <setmkfluid mk="1" />
          <fillbox x="0.0" y="0.0" z="0.2">
            <modefill>void</modefill>
            <point x="-0.55" y="-0.35" z="0.05" />
            <size x="1.1" y="0.7" z="0.432" />
          </fillbox>
        </mainlist>
      </commands>
    </geometry>
  </casedef>
  <execution>
    <parameters>
      <parameter key="TimeMax" value="12" />
      <parameter key="TimeOut" value="0.02" />
    </parameters>
  </execution>
</case>"""
    gapped_xml.write_text(content, encoding="utf-8")

    result = audit_case_source_consistency("TEST_GAPPED", gapped_xml, mother_constants)
    # boundary_top_z = 0.0 + (3 - 1) * 0.016 = 0.032
    # fluid_z_min = 0.05
    # air_gap = 0.05 - 0.032 = 0.018 m (18 mm)
    expected_gap = 0.05 - 0.032
    assert abs(result["initial_phase_air_gap"]["air_gap_m"] - expected_gap) < 1e-6
    assert result["initial_phase_air_gap"]["unphysical_drop_defect"] is True
    # Ep = 320.1984 * 9.81 * 0.018 ≈ 56.54 J
    assert result["initial_phase_air_gap"]["gravitational_potential_energy_j"] > 50.0
    assert result["pointref_classification"] == "arbitrary_offset"
    assert result["boundary_and_kernel_support"]["truncated_kernel_support"] is True


def test_metadata_absence_is_marked_unassessed(tmp_path: Path, mother_constants: dict):
    """Enforce rule: metadata-only arrays absence must be marked unassessed."""
    xml_p = tmp_path / "dummy_Def.xml"
    xml_p.write_text("""<?xml version="1.0"?>
<case>
  <casedef>
    <geometry><definition dp="0.02"><pointref x="0.01" y="0.01" z="0.01"/></definition>
      <commands><mainlist><setmkbound mk="0"/><drawbox><point x="0" y="0" z="0"/><size x="1" y="1" z="1"/></drawbox></mainlist></commands>
    </geometry>
  </casedef>
  <execution><parameters><parameter key="TimeMax" value="12"/><parameter key="TimeOut" value="0.02"/></parameters></execution>
</case>""")
    res = audit_case_source_consistency("TEST_UNASSESSED", xml_p, mother_constants)
    assert res["numerical_arrays_status"] == "unassessed"
    assert res["h5_csv_data_inspection"] == "unassessed_owner_rule"


def test_prospective_commensurate_recipe_definitions():
    """Verify prospective commensurate XML definitions eliminate the air gap and restore lattice symmetry."""
    defs_dir = MODULE_ROOT / "definitions"
    for tier, dp, pref in [
        ("COARSE", 0.025, 0.0125),
        ("MEDIUM", 0.020, 0.0100),
        ("FINE", 0.016, 0.0080),
        ("DP001", 0.010, 0.0050),
    ]:
        xml_file = defs_dir / f"F7_OBSTACLE_COMMENSURATE_PHYSICAL_SURFACE_002_{tier}_Def.xml"
        assert xml_file.exists(), f"Missing prospective definition: {xml_file}"
        parsed = parse_xml_definition(xml_file)
        assert parsed["dp_m"] == dp
        assert parsed["pointref"] == [pref, pref, pref], f"Pointref not dp/2 centered for {tier}"
        assert parsed["execution_parameters"]["TimeMax"] == "12"
        assert parsed["execution_parameters"]["TimeOut"] == "0.02"

        # Check fluid fill starts at z=0.0
        assert len(parsed["fillboxes"]) >= 1
        assert parsed["fillboxes"][0]["point"][2] == 0.0, f"Fluid z_min must be 0.0 for {tier} to eliminate drop gap"
        assert parsed["fillboxes"][0]["size"][2] == 0.482

        # Check boundary layers = 4 (vdp="0,1,2,3")
        tank_box = next((b for b in parsed["solid_boxes"] if b["mk"] == 0), None)
        assert tank_box is not None
        assert tank_box["layers"] == "0,1,2,3"


def test_legal_fallback_definition():
    """Verify legal fallback stirrer definition is well-formed and preserves 12s window."""
    fallback_xml = MODULE_ROOT / "definitions/F7_PUMP_STIRRER_FALLBACK_001_FINE_Def.xml"
    assert fallback_xml.exists()
    parsed = parse_xml_definition(fallback_xml)
    assert parsed["dp_m"] == 0.016
    assert parsed["execution_parameters"]["TimeMax"] == "12"
    assert parsed["execution_parameters"]["TimeOut"] == "0.02"
    assert parsed["execution_parameters"]["Boundary"] == "1"


def test_audit_report_hash_and_structure():
    """Verify the generated source-consistency audit report structure and defect findings."""
    report_file = MODULE_ROOT / "reports/f7_source_consistency_audit_report.json"
    assert report_file.exists()
    with open(report_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["schema"] == "ds02.f7.source-consistency-audit-report.v1"
    assert data["family_id"] == "F7"
    assert data["prior_negatives_preserved"]["time_macro_does_not_explain_spatial_failure"] is True
    assert data["prior_negatives_preserved"]["spatial_ke_43pct_failure_retained"] is True
    assert len(data["defects_identified"]) == 4
    defect_codes = {d["code"] for d in data["defects_identified"]}
    assert "DEFECT_01_POINTREF_INCONSISTENCY" in defect_codes
    assert "DEFECT_02_PADDLE_ECCENTRICITY_WOBBLE" in defect_codes
    assert "DEFECT_03_GRAVITATIONAL_AIR_GAP_SLAP" in defect_codes
    assert "DEFECT_04_DBC_KERNEL_TRUNCATION" in defect_codes
    assert data["governance_and_counters"]["independent_physical_case_count"] == 0
    assert data["governance_and_counters"]["q_n_status"] == "not_granted"
