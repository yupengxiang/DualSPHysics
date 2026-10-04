#!/usr/bin/env python3
"""test_f7_obstacle_smooth_motion_worker.py

Unit and mock tests for the F7 smooth C2 driving-control repair worker.
"""

import json
import math
import sys
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest

# Ensure worker module is importable
WORKER_DIR = Path(__file__).resolve().parent.parent
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

from f7_obstacle_smooth_motion_worker import (
    evaluate_trajectory_analytic,
    evaluate_segment_exact_limits,
    audit_transition_regularity,
    generate_motion_dat_content,
    verify_xml_undo_integrity,
    compare_against_root_motion_regularity_report,
    run_smooth_motion_worker,
    sha256_file,
    quintic_s,
    quintic_ds,
    quintic_d2s
)


def test_quintic_polynomial_boundary_properties():
    """Verifies that the quintic polynomial has exact 0 velocity and acceleration at ends."""
    assert quintic_s(0.0) == 0.0
    assert quintic_s(1.0) == 1.0
    assert quintic_ds(0.0) == 0.0
    assert quintic_ds(1.0) == 0.0
    assert quintic_d2s(0.0) == 0.0
    assert quintic_d2s(1.0) == 0.0

    # Symmetric peak velocity at tau = 0.5
    assert quintic_ds(0.5) == 30.0 * (0.5 ** 2) * (0.5 ** 2)  # 1.875
    # Zero acceleration at midpoint
    assert quintic_d2s(0.5) == 0.0


def test_analytic_c2_regularity_and_joins_zero_vel_acc():
    """Verifies C2 continuity across all transitions and zero velocity/acceleration joins."""
    regularity = audit_transition_regularity(amp_deg=45.0)
    assert regularity["all_c2_continuous"] is True
    assert regularity["max_angle_jump_deg"] < 1e-12
    assert regularity["max_velocity_jump_deg_s"] < 1e-12
    assert regularity["max_acceleration_jump_deg_s2"] < 1e-12

    # Check each individual transition
    for t in regularity["transitions"]:
        assert t["c0_continuous"] is True, f"Failed C0 at {t['junction']}"
        assert t["c1_continuous"] is True, f"Failed C1 at {t['junction']}"
        assert t["c2_continuous"] is True, f"Failed C2 at {t['junction']}"
        assert t["joins_zero_vel"] is True, f"Non-zero velocity join at {t['junction']}"
        assert t["joins_zero_acc"] is True, f"Non-zero acceleration join at {t['junction']}"

    # Verify rest tail
    for t_tail in [8.0, 9.0, 10.0, 11.0, 12.0]:
        th, v, a = evaluate_trajectory_analytic(t_tail, amp_deg=45.0)
        assert abs(th) < 1e-12
        assert abs(v) < 1e-12
        assert abs(a) < 1e-12


def test_motion_file_format_and_reader_semantics():
    """Verifies motion file format compliance with official JMotionDataRotAxis reader."""
    motion_content = generate_motion_dat_content(amp_deg=45.0, t_max=12.0, dt=0.001)
    lines = [l.strip() for l in motion_content.splitlines() if l.strip()]

    # Header remarks
    comment_lines = [l for l in lines if l.startswith("#")]
    assert len(comment_lines) >= 5

    data_lines = [l for l in lines if not l.startswith("#")]
    assert len(data_lines) == 12001

    # Check columns and parsing
    for i, line in enumerate(data_lines[::500]):  # check every 500 lines
        tokens = line.split()
        assert len(tokens) == 2
        t = float(tokens[0])
        ang = float(tokens[1])
        assert -45.0000001 <= ang <= 45.0000001
        assert 0.0 <= t <= 12.0000001

    # First row is 0, 0
    t0, a0 = map(float, data_lines[0].split())
    assert t0 == 0.0 and abs(a0) < 1e-12

    # Last row is 12, 0
    t_end, a_end = map(float, data_lines[-1].split())
    assert t_end == 12.0 and abs(a_end) < 1e-12


def test_xml_safe_element_handling():
    """Verifies XML parsing safely checks 'elem is not None' without walrus boolean bug."""
    xml_fine = WORKER_DIR / "definitions/F7_OBSTACLE_SMOOTH_C2_BASE_FINE_Def.xml"
    assert xml_fine.exists()

    tree = ET.parse(xml_fine)
    root = tree.getroot()

    constants = root.find("casedef/constantsdef")
    assert constants is not None

    # In Python ElementTree, elements without children can evaluate to False in boolean context.
    # We test that explicit 'is not None' correctly extracts values.
    c_elem = constants.find("coefh")
    assert c_elem is not None
    assert float(c_elem.get("value", "0")) == 0.91924

    cs_elem = constants.find("coefsound")
    assert cs_elem is not None
    assert float(cs_elem.get("value", "0")) == 30.0

    gr_elem = constants.find("gravity")
    assert gr_elem is not None
    assert float(gr_elem.get("z", "0")) == -9.81


def test_xml_whole_undo_integrity():
    """Verifies that the new definitions are an exact whole undo outside declared driving fields."""
    cases = [
        ("COARSE", "F7_OBSTACLE_SMOOTH_C2_BASE_COARSE_Def.xml", "F7_OBSTACLE_REFERENCE_BASE_COARSE_Def.xml"),
        ("MEDIUM", "F7_OBSTACLE_SMOOTH_C2_BASE_MEDIUM_Def.xml", "F7_OBSTACLE_REFERENCE_BASE_MEDIUM_Def.xml"),
        ("FINE", "F7_OBSTACLE_SMOOTH_C2_BASE_FINE_Def.xml", "F7_OBSTACLE_REFERENCE_BASE_FINE_Def.xml"),
    ]
    ref_dir = Path("/home/jade/.codex/worktrees/ds-data-02-f7/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F7/reference/definitions")

    for res, new_name, ref_name in cases:
        new_xml = WORKER_DIR / "definitions" / new_name
        ref_xml = ref_dir / ref_name
        assert new_xml.exists()
        assert ref_xml.exists()

        audit = verify_xml_undo_integrity(ref_xml, new_xml)
        assert audit["constants_identical"] is True, f"Constants mismatch for {res}"
        assert audit["geometry_identical"] is True, f"Geometry mismatch for {res}"
        assert audit["execution_identical"] is True, f"Execution mismatch for {res}"
        assert audit["motion_replaced_with_mvrotfile"] is True, f"Motion not mvrotfile for {res}"
        assert audit["motion_file_target"] == "motion_obstacle_smooth_c2.dat"
        assert audit["whole_undo_outside_driving_fields"] is True


def test_manifest_and_sha_integrity():
    """Verifies case manifests schema and SHA256 integrity."""
    manifest_dir = WORKER_DIR / "case_manifests"
    manifests = list(manifest_dir.glob("*.json"))
    assert len(manifests) == 3

    for m_path in manifests:
        with open(m_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["schema"] == "ds02.f7.case-manifest.v1"
        assert data["physical_parent_id"] == "F7_OBSTACLE_SMOOTH_C2_BASE"
        assert data["mechanism"] == "moving_obstacle_exchange"
        assert data["governance"]["q_n_status"] == "not_granted"
        assert data["governance"]["production_approval"] == "none"

        # Verify XML exists and SHA matches
        xml_path = Path(data["definition_xml"])
        assert xml_path.exists()
        assert sha256_file(xml_path) == data["definition_sha256"]

        # Verify motion file exists and SHA matches
        mot_path = Path(data["motion_file"])
        assert mot_path.exists()
        assert sha256_file(mot_path) == data["motion_file_sha256"]
