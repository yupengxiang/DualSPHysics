#!/usr/bin/env python3
"""test_f7_obstacle_smooth_motion_worker.py

Unit and synthetic fixture tests for the F7 smooth C2 prospective worker (Round 042).

Enforces:
1. Pure synthetic target fixture testing of I/O math and reader semantics.
2. No generation of actual production motion files under test.
3. Explicit rejection of owner-041 zero-discontinuity guarantee for piecewise linear reader DfGetNewAng.
4. Independent whole-XML undo verification (ET.tostring(restored) == ET.tostring(ref)).
5. Overwrite-safety via mode 'x' and IEEE 754 precision roundtrip with '%.17g'.
"""

import json
import math
import sys
import tempfile
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest

WORKER_DIR = Path(__file__).resolve().parent.parent
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

from f7_obstacle_smooth_motion_worker import (
    quintic_s,
    quintic_ds,
    quintic_d2s,
    evaluate_trajectory_analytic,
    evaluate_segment_exact_limits,
    audit_transition_regularity,
    describe_sampled_motion_io,
    generate_motion_dat_content,
    write_motion_file_exclusive,
    generate_smooth_c2_definition_xml,
    verify_xml_declared_subtree_undo,
    sha256_file,
    sha256_bytes
)


# -----------------------------------------------------------------------------
# Test 1: Analytic Quintic Polynomial Formulation
# -----------------------------------------------------------------------------

def test_quintic_polynomial_boundary_derivatives():
    """Verifies that base quintic polynomial s(tau) satisfies zero derivative endpoints."""
    assert quintic_s(0.0) == 0.0
    assert quintic_s(1.0) == 1.0
    assert quintic_ds(0.0) == 0.0
    assert quintic_ds(1.0) == 0.0
    assert quintic_d2s(0.0) == 0.0
    assert quintic_d2s(1.0) == 0.0

    # Symmetric midpoint properties at tau = 0.5
    assert quintic_s(0.5) == 0.5
    assert quintic_ds(0.5) == 30.0 * (0.5 ** 2) * (0.5 ** 2)  # 1.875
    assert quintic_d2s(0.5) == 0.0


def test_analytic_c2_continuity_and_rest_tail():
    """Verifies analytic one-sided limits match at all segment transitions and rest tail."""
    audit = audit_transition_regularity(amp_deg=45.0)
    assert audit["all_c2_continuous"] is True
    assert audit["max_angle_jump_deg"] < 1e-12
    assert audit["max_velocity_jump_deg_s"] < 1e-12
    assert audit["max_acceleration_jump_deg_s2"] < 1e-12

    for t in audit["transitions"]:
        assert t["c0_continuous"] is True, f"Failed C0 at {t['junction']}"
        assert t["c1_continuous"] is True, f"Failed C1 at {t['junction']}"
        assert t["c2_continuous"] is True, f"Failed C2 at {t['junction']}"
        assert t["joins_zero_vel"] is True, f"Non-zero velocity join at {t['junction']}"
        assert t["joins_zero_acc"] is True, f"Non-zero acceleration join at {t['junction']}"

    # Verify rest tail across [8.0, 12.0] s
    for t_tail in [8.0, 9.0, 10.0, 11.0, 12.0]:
        th, v, a = evaluate_trajectory_analytic(t_tail, amp_deg=45.0)
        assert abs(th) < 1e-12
        assert abs(v) < 1e-12
        assert abs(a) < 1e-12


# -----------------------------------------------------------------------------
# Test 2: Discrete Sampled I/O Descriptor & Rejection of 041 Guarantee
# -----------------------------------------------------------------------------

def test_sampled_motion_io_math_synthetic_fixture():
    """Verifies discrete sampled motion I/O math on synthetic short fixture.

    Proves that DfGetNewAng piecewise linear interpolation produces:
    - Finite knot slope jumps (delta v_i > 0)
    - Non-zero start-interval slope (jump from stationary rest)
    - Rejection of 041 claim of exact zero native discontinuities.
    """
    # Test on synthetic 1.0 s fixture with dt = 0.01 s
    synth_desc = describe_sampled_motion_io(amp_deg=45.0, t_max=1.0, dt=0.01)

    assert synth_desc["knot_count"] == 101
    assert synth_desc["sampling_dt_s"] == 0.01

    # First interval slope must be strictly positive since theta(0.01) > 0
    assert synth_desc["first_interval_slope_deg_s"] > 0.0
    assert synth_desc["initial_start_slope_jump_deg_s"] > 0.0

    # Max knot slope jump must be strictly positive, proving velocity discontinuities
    assert synth_desc["max_knot_slope_jump_deg_s"] > 0.0

    # Theoretical linear chord error bound must match (1/8) * dt^2 * peak_acc
    expected_bound = 0.125 * (0.01 ** 2) * synth_desc["peak_analytic_acceleration_deg_s2"]
    assert abs(synth_desc["theoretical_max_interp_error_deg"] - expected_bound) < 1e-14

    # Empirical chord error must be bounded by theoretical bound
    assert synth_desc["empirical_max_chord_error_deg"] <= synth_desc["theoretical_max_interp_error_deg"] + 1e-10

    # Source pins check
    pins = synth_desc["reader_physical_source_pins"]
    assert pins["solver_reader_function"] == "JMotionMovActive::DfGetNewAng(double t)"
    assert pins["solver_reader_source_file"] == "src/source/JMotionObj.cpp"
    assert pins["solver_reader_lines"] == "214-226"


def test_cadence_sensitivity_scaling_dt001_vs_dt0005():
    """Verifies scaling of slope jumps and linear interpolation error between dt=0.001s and dt=0.0005s."""
    desc_001 = describe_sampled_motion_io(amp_deg=45.0, t_max=12.0, dt=0.001)
    desc_0005 = describe_sampled_motion_io(amp_deg=45.0, t_max=12.0, dt=0.0005)

    assert desc_001["knot_count"] == 12001
    assert desc_0005["knot_count"] == 24001

    # Slope jump scales as O(dt) -> halving dt approximately halves max slope jump
    ratio_jump = desc_001["max_knot_slope_jump_deg_s"] / desc_0005["max_knot_slope_jump_deg_s"]
    assert 1.95 <= ratio_jump <= 2.05

    # Linear interpolation error scales as O(dt^2) -> halving dt quarters theoretical error
    ratio_err = desc_001["theoretical_max_interp_error_deg"] / desc_0005["theoretical_max_interp_error_deg"]
    assert abs(ratio_err - 4.0) < 1e-6


# -----------------------------------------------------------------------------
# Test 3: IEEE 754 Full Roundtrip Precision (.17g) and Format Compliance
# -----------------------------------------------------------------------------

def test_float_17g_exact_roundtrip():
    """Verifies that %.17g formatting guarantees exact floating point roundtrip."""
    test_values = [
        0.0, 1.0, -1.0, 45.0, -45.0, 0.001, 0.0005,
        1.2345678901234567, -42.797543233281914,
        math.pi, math.e, 150.0 * math.sqrt(3.0)
    ]
    for val in test_values:
        formatted = f"{val:.17g}"
        roundtrip_val = float(formatted)
        assert val == roundtrip_val, f"Precision loss for {val}: got {roundtrip_val}"


def test_motion_dat_synthetic_content_format():
    """Verifies motion dat generation adheres to official 2-column format without disk write."""
    content = generate_motion_dat_content(amp_deg=45.0, t_max=1.0, dt=0.1)
    lines = [l.strip() for l in content.splitlines() if l.strip()]

    # Comments header
    comments = [l for l in lines if l.startswith("#")]
    assert len(comments) >= 5

    # Data rows
    data = [l for l in lines if not l.startswith("#")]
    assert len(data) == 11  # 0.0, 0.1, ..., 1.0

    t0, a0 = map(float, data[0].split())
    assert t0 == 0.0 and abs(a0) < 1e-12

    t_end, a_end = map(float, data[-1].split())
    assert abs(t_end - 1.0) < 1e-12 and abs(a_end - 45.0) < 1e-12


# -----------------------------------------------------------------------------
# Test 4: Exclusive Output Mode 'x' (Overwrite Safety)
# -----------------------------------------------------------------------------

def test_exclusive_output_mode_x_prevents_overwrite():
    """Verifies that write_motion_file_exclusive raises FileExistsError on existing target."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir) / "motion_test.dat"

        # First write succeeds
        sha1 = write_motion_file_exclusive(tmp_path, "sample content\n")
        assert tmp_path.exists()
        assert sha256_file(tmp_path) == sha1

        # Second write to the exact same file MUST fail with FileExistsError
        with pytest.raises(FileExistsError):
            write_motion_file_exclusive(tmp_path, "overwriting content\n")


# -----------------------------------------------------------------------------
# Test 5: XML Declared Subtree Replacement & Whole-XML Undo Verification
# -----------------------------------------------------------------------------

def test_xml_whole_tree_undo_identity():
    """Verifies that restoring declared motion subtree restores 100% whole XML identity."""
    cases = ["COARSE", "MEDIUM", "FINE"]
    ref_dir = Path("/home/jade/.codex/worktrees/ds-data-02-f7/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F7/reference/definitions")
    defs_dir = WORKER_DIR / "definitions"

    for res in cases:
        ref_xml = ref_dir / f"F7_OBSTACLE_REFERENCE_BASE_{res}_Def.xml"
        new_xml = defs_dir / f"F7_OBSTACLE_SMOOTH_C2_BASE_{res}_Def.xml"

        assert ref_xml.exists(), f"Reference XML missing: {ref_xml}"
        assert new_xml.exists(), f"Definition XML missing: {new_xml}"

        audit = verify_xml_declared_subtree_undo(ref_xml, new_xml)
        assert audit["whole_tree_identical_upon_undo"] is True, f"Whole-tree undo failed for {res}"
        assert audit["constants_identical"] is True, f"Constants changed for {res}"
        assert audit["mkconfig_identical"] is True, f"mkconfig changed for {res}"
        assert audit["geometry_identical"] is True, f"geometry changed for {res}"
        assert audit["execution_identical"] is True, f"execution changed for {res}"
        assert audit["no_silent_geometry_kernel_repair"] is True
        assert audit["declared_motion_subtree_isolated"] is True


# -----------------------------------------------------------------------------
# Test 6: Case Manifests & Governance Integrity
# -----------------------------------------------------------------------------

def test_case_manifests_integrity():
    """Verifies case manifests schema, references, and zero-increment governance."""
    manifest_dir = WORKER_DIR / "case_manifests"
    manifests = list(manifest_dir.glob("*.json"))
    assert len(manifests) == 3, f"Expected 3 manifests, found {len(manifests)}"

    for m_path in manifests:
        with open(m_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["schema"] == "ds02.f7.case-manifest.v1"
        assert data["physical_parent_id"] == "F7_OBSTACLE_SMOOTH_C2_BASE"
        assert data["mechanism"] == "moving_obstacle_exchange"
        assert data["governance"]["q_n_status"] == "not_granted"
        assert data["governance"]["production_approval"] == "none"
        assert data["governance"]["independent_case_count_increment"] == 0

        # XML definition exists and matches SHA
        xml_path = Path(data["definition_xml"])
        assert xml_path.exists()
        assert sha256_file(xml_path) == data["definition_sha256"]

        # Control cadence options
        opts = data["control_cadence_options"]
        assert "selected_target_dt001" in opts
        assert "independent_control_dt0005" in opts
        assert opts["selected_target_dt001"]["rows"] == 12001
        assert opts["independent_control_dt0005"]["rows"] == 24001
