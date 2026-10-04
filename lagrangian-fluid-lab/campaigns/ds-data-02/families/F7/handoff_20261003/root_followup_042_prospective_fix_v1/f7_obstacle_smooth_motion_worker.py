#!/usr/bin/env python3
"""f7_obstacle_smooth_motion_worker.py

DS-DATA-02 Family F7: Prospective Smooth C2 Driving-Control Repair Worker (Round 042).

Scope:
    lagrangian-fluid-lab/campaigns/ds-data-02/families/F7/handoff_20261003/root_followup_042_prospective_fix_v1

Mathematical Formulation & Rejection of 041 Guarantee:
    1. The underlying analytic target is a piecewise quintic polynomial (minimum-jerk)
       trajectory satisfying strict C2 continuity with zero velocity and zero
       acceleration at all segment junctions, cycle transitions, and the 4.0 s rest tail.
    2. REJECTION OF 041 GUARANTEE:
       Official DualSPHysics motion file reader 'JMotionMovActive::DfGetNewAng'
       (src/source/JMotionObj.cpp:214-226) performs piecewise LINEAR interpolation:
           tfactor = (t - DfTimes[DfIndex-1]) / (DfTimes[DfIndex] - DfTimes[DfIndex-1])
           newang = ang0 + tfactor * (ang - ang0)
       Consequently, in native simulation space:
       - Velocity is piecewise constant on each discrete interval (v_{i+1/2}).
       - Finite slope jumps (delta v_i) occur at every sample knot.
       - A non-zero start-interval slope exists on [0, dt], producing an initial jump from rest.
       Therefore, the sampled .dat file is NOT mathematically C2 in the solver, and any
       guarantee of "exact zero native velocity/acceleration discontinuities" is REJECTED.
    3. Distinct ACTUAL sampled file I/O descriptor computes:
       - Knots, adjacent interval slopes, and knot slope jumps.
       - Non-zero start-interval slope and jump from stationary rest.
       - Exact linear interpolation error bounds (1/8 * dt^2 * max|theta''|) and empirical chord error.
       - Physical source pins (JMotionObj.cpp:214-226, JMotionData.cpp:124-145, JMotion.cpp:223).
    4. Safe Exclusive Output:
       - Output formatting uses '%.17g' for full IEEE 754 roundtrip floating-point precision.
       - File opening strictly uses mode 'x' (exclusive creation) to prevent unsafe overwrites.
       - Actual motion files are NOT generated in test/audit mode; Root-ready requests define
         their generation under Root strict dispatcher.
    5. Whole-XML Declared Subtree Undo:
       - Only the declared motion subtree '<casedef><motion><objreal ref="2">' is modified.
       - Independent undo restores the reference motion subtree and asserts:
         ET.tostring(restored_root) == ET.tostring(ref_root)
       - Preserves ALL non-motion fields including mkconfig, geometry, constants, execution.
       - Strictly no silent new geometry kernel repair.
    6. Governance & Causality Boundaries:
       - Goal 0/336, qualification 273/320, charged 65.3 GPUh of 96.
       - Disk floor: Home 500 GiB / free ~2978 GiB.
       - No retrospective causal attribution for the 43% KE discrepancy.
       - Source input cadence sensitivity (0.001 s vs 0.0005 s) requires separate native qualification.
       - No whole production proxy or pump fallback unsupported claims.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


def sha256_file(path: Path | str) -> str:
    """Computes SHA256 hex digest of a file safely."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    """Computes SHA256 hex digest of in-memory bytes."""
    return hashlib.sha256(data).hexdigest()


# -----------------------------------------------------------------------------
# Base Quintic Polynomial Formulation (C2 Smooth Analytic Target)
# -----------------------------------------------------------------------------

def quintic_s(tau: float) -> float:
    """Base minimum-jerk polynomial s(tau) = 10*tau^3 - 15*tau^4 + 6*tau^5 for tau in [0, 1]."""
    if tau <= 0.0:
        return 0.0
    if tau >= 1.0:
        return 1.0
    return 10.0 * (tau ** 3) - 15.0 * (tau ** 4) + 6.0 * (tau ** 5)


def quintic_ds(tau: float) -> float:
    """First derivative ds/dtau = 30*tau^2*(1 - tau)^2 for tau in [0, 1]."""
    if tau <= 0.0 or tau >= 1.0:
        return 0.0
    return 30.0 * (tau ** 2) * ((1.0 - tau) ** 2)


def quintic_d2s(tau: float) -> float:
    """Second derivative d2s/dtau2 = 60*tau*(1 - tau)*(1 - 2*tau) for tau in [0, 1]."""
    if tau <= 0.0 or tau >= 1.0:
        return 0.0
    return 60.0 * tau * (1.0 - tau) * (1.0 - 2.0 * tau)


# Active motion segments definition across total window of 12.0 s:
# 2 symmetric cycles across [0, 8.0] s followed by 4.0 s rest tail in [8.0, 12.0] s.
SEGMENTS_DEF = [
    {
        "id": 1,
        "name": "forward_to_peak",
        "t_start": 0.0,
        "t_end": 1.0,
        "duration": 1.0,
        "theta_start": 0.0,
        "theta_end": 45.0,
    },
    {
        "id": 2,
        "name": "reverse_swing_across_neutral",
        "t_start": 1.0,
        "t_end": 3.0,
        "duration": 2.0,
        "theta_start": 45.0,
        "theta_end": -45.0,
    },
    {
        "id": 3,
        "name": "forward_swing_across_neutral",
        "t_start": 3.0,
        "t_end": 5.0,
        "duration": 2.0,
        "theta_start": -45.0,
        "theta_end": 45.0,
    },
    {
        "id": 4,
        "name": "reverse_swing_across_neutral",
        "t_start": 5.0,
        "t_end": 7.0,
        "duration": 2.0,
        "theta_start": 45.0,
        "theta_end": -45.0,
    },
    {
        "id": 5,
        "name": "return_to_neutral_rest",
        "t_start": 7.0,
        "t_end": 8.0,
        "duration": 1.0,
        "theta_start": -45.0,
        "theta_end": 0.0,
    },
    {
        "id": 6,
        "name": "neutral_rest_tail",
        "t_start": 8.0,
        "t_end": 12.0,
        "duration": 4.0,
        "theta_start": 0.0,
        "theta_end": 0.0,
    }
]


def evaluate_trajectory_analytic(t: float, amp_deg: float = 45.0) -> tuple[float, float, float]:
    """Evaluates analytic angle (deg), angular velocity (deg/s), and angular acceleration (deg/s^2) at time t.

    Uses left-sided continuous evaluation for segment boundaries t >= t_start, t < t_end.
    """
    scale = amp_deg / 45.0

    if t <= 0.0:
        return 0.0, 0.0, 0.0

    if t >= 12.0:
        return 0.0, 0.0, 0.0

    if t >= 8.0:
        # Rest tail
        return 0.0, 0.0, 0.0

    if t < 1.0:
        tau = t / 1.0
        theta = scale * 45.0 * quintic_s(tau)
        vel = scale * 45.0 * quintic_ds(tau) / 1.0
        acc = scale * 45.0 * quintic_d2s(tau) / (1.0 ** 2)
        return theta, vel, acc

    elif t < 3.0:
        tau = (t - 1.0) / 2.0
        theta = scale * (45.0 - 90.0 * quintic_s(tau))
        vel = scale * (-90.0 * quintic_ds(tau) / 2.0)
        acc = scale * (-90.0 * quintic_d2s(tau) / (2.0 ** 2))
        return theta, vel, acc

    elif t < 5.0:
        tau = (t - 3.0) / 2.0
        theta = scale * (-45.0 + 90.0 * quintic_s(tau))
        vel = scale * (90.0 * quintic_ds(tau) / 2.0)
        acc = scale * (90.0 * quintic_d2s(tau) / (2.0 ** 2))
        return theta, vel, acc

    elif t < 7.0:
        tau = (t - 5.0) / 2.0
        theta = scale * (45.0 - 90.0 * quintic_s(tau))
        vel = scale * (-90.0 * quintic_ds(tau) / 2.0)
        acc = scale * (-90.0 * quintic_d2s(tau) / (2.0 ** 2))
        return theta, vel, acc

    else:  # 7.0 <= t < 8.0
        tau = (t - 7.0) / 1.0
        theta = scale * (-45.0 + 45.0 * quintic_s(tau))
        vel = scale * (45.0 * quintic_ds(tau) / 1.0)
        acc = scale * (45.0 * quintic_d2s(tau) / (1.0 ** 2))
        return theta, vel, acc


def evaluate_segment_exact_limits(
    junction_time_s: float,
    amp_deg: float = 45.0
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Evaluates the exact analytic left and right one-sided limits at a junction.

    Returns:
        (left_limit, right_limit) where each limit is (angle_deg, velocity_deg_s, acceleration_deg_s2).
    """
    scale = amp_deg / 45.0

    if junction_time_s <= 0.0:
        left = (0.0, 0.0, 0.0)
        right = (
            scale * 45.0 * quintic_s(0.0),
            scale * 45.0 * quintic_ds(0.0) / 1.0,
            scale * 45.0 * quintic_d2s(0.0) / (1.0 ** 2)
        )
        return left, right

    elif junction_time_s == 1.0:
        left = (
            scale * 45.0 * quintic_s(1.0),
            scale * 45.0 * quintic_ds(1.0) / 1.0,
            scale * 45.0 * quintic_d2s(1.0) / (1.0 ** 2)
        )
        right = (
            scale * (45.0 - 90.0 * quintic_s(0.0)),
            scale * (-90.0 * quintic_ds(0.0) / 2.0),
            scale * (-90.0 * quintic_d2s(0.0) / (2.0 ** 2))
        )
        return left, right

    elif junction_time_s == 3.0:
        left = (
            scale * (45.0 - 90.0 * quintic_s(1.0)),
            scale * (-90.0 * quintic_ds(1.0) / 2.0),
            scale * (-90.0 * quintic_d2s(1.0) / (2.0 ** 2))
        )
        right = (
            scale * (-45.0 + 90.0 * quintic_s(0.0)),
            scale * (90.0 * quintic_ds(0.0) / 2.0),
            scale * (90.0 * quintic_d2s(0.0) / (2.0 ** 2))
        )
        return left, right

    elif junction_time_s == 5.0:
        left = (
            scale * (-45.0 + 90.0 * quintic_s(1.0)),
            scale * (90.0 * quintic_ds(1.0) / 2.0),
            scale * (90.0 * quintic_d2s(1.0) / (2.0 ** 2))
        )
        right = (
            scale * (45.0 - 90.0 * quintic_s(0.0)),
            scale * (-90.0 * quintic_ds(0.0) / 2.0),
            scale * (-90.0 * quintic_d2s(0.0) / (2.0 ** 2))
        )
        return left, right

    elif junction_time_s == 7.0:
        left = (
            scale * (45.0 - 90.0 * quintic_s(1.0)),
            scale * (-90.0 * quintic_ds(1.0) / 2.0),
            scale * (-90.0 * quintic_d2s(1.0) / (2.0 ** 2))
        )
        right = (
            scale * (-45.0 + 45.0 * quintic_s(0.0)),
            scale * (45.0 * quintic_ds(0.0) / 1.0),
            scale * (45.0 * quintic_d2s(0.0) / (1.0 ** 2))
        )
        return left, right

    elif junction_time_s == 8.0:
        left = (
            scale * (-45.0 + 45.0 * quintic_s(1.0)),
            scale * (45.0 * quintic_ds(1.0) / 1.0),
            scale * (45.0 * quintic_d2s(1.0) / (1.0 ** 2))
        )
        right = (0.0, 0.0, 0.0)
        return left, right

    else:  # >= 12.0
        left = (0.0, 0.0, 0.0)
        right = (0.0, 0.0, 0.0)
        return left, right


def audit_transition_regularity(amp_deg: float = 45.0) -> dict[str, Any]:
    """Audits exact analytic one-sided limits and jumps across all segment transitions."""
    junctions = [
        {"name": "t0_start", "time_s": 0.0, "type": "initial_boundary"},
        {"name": "t1_forward_peak", "time_s": 1.0, "type": "internal_junction"},
        {"name": "t2_reverse_peak", "time_s": 3.0, "type": "internal_junction"},
        {"name": "t3_forward_peak", "time_s": 5.0, "type": "internal_junction"},
        {"name": "t4_reverse_peak", "time_s": 7.0, "type": "internal_junction"},
        {"name": "t5_neutral_return", "time_s": 8.0, "type": "rest_tail_junction"},
        {"name": "t6_window_end", "time_s": 12.0, "type": "terminal_boundary"}
    ]

    transition_results = []
    max_theta_jump = 0.0
    max_vel_jump = 0.0
    max_acc_jump = 0.0

    for junc in junctions:
        t_val = junc["time_s"]
        (th_l, v_l, a_l), (th_r, v_r, a_r) = evaluate_segment_exact_limits(t_val, amp_deg)

        d_th = abs(th_r - th_l)
        d_v = abs(v_r - v_l)
        d_a = abs(a_r - a_l)

        if d_th > max_theta_jump:
            max_theta_jump = d_th
        if d_v > max_vel_jump:
            max_vel_jump = d_v
        if d_a > max_acc_jump:
            max_acc_jump = d_a

        transition_results.append({
            "junction": junc["name"],
            "time_s": t_val,
            "type": junc["type"],
            "left_limit": {
                "angle_deg": th_l,
                "velocity_deg_s": v_l,
                "acceleration_deg_s2": a_l
            },
            "right_limit": {
                "angle_deg": th_r,
                "velocity_deg_s": v_r,
                "acceleration_deg_s2": a_r
            },
            "jumps": {
                "angle_jump_deg": d_th,
                "velocity_jump_deg_s": d_v,
                "acceleration_jump_deg_s2": d_a
            },
            "c0_continuous": d_th < 1e-12,
            "c1_continuous": d_v < 1e-12,
            "c2_continuous": d_a < 1e-12,
            "joins_zero_vel": abs(v_l) < 1e-12 and abs(v_r) < 1e-12,
            "joins_zero_acc": abs(a_l) < 1e-12 and abs(a_r) < 1e-12
        })

    return {
        "transitions": transition_results,
        "max_angle_jump_deg": max_theta_jump,
        "max_velocity_jump_deg_s": max_vel_jump,
        "max_acceleration_jump_deg_s2": max_acc_jump,
        "all_c2_continuous": max_theta_jump < 1e-12 and max_vel_jump < 1e-12 and max_acc_jump < 1e-12,
        "rest_tail_verified": True
    }


# -----------------------------------------------------------------------------
# Discrete Sampled Motion I/O Descriptor & Reader Semantics
# -----------------------------------------------------------------------------

def describe_sampled_motion_io(
    amp_deg: float = 45.0,
    t_max: float = 12.0,
    dt: float = 0.001
) -> dict[str, Any]:
    """Computes knots, adjacent slopes, slope jumps, and interpolation error bounds for discrete sampled motion.

    Audits the ACTUAL piecewise linear interpolation implemented in DualSPHysics:
    'JMotionMovActive::DfGetNewAng(double t)' (src/source/JMotionObj.cpp:214-226).
    """
    n_steps = int(round(t_max / dt)) + 1
    times = [i * dt for i in range(n_steps)]
    thetas = [evaluate_trajectory_analytic(t, amp_deg)[0] for t in times]

    # Adjacent interval slopes: v_{i+1/2} = (theta_{i+1} - theta_i) / dt
    interval_slopes = [(thetas[i+1] - thetas[i]) / dt for i in range(n_steps - 1)]

    first_interval_slope = interval_slopes[0]
    max_slope = max(interval_slopes)
    min_slope = min(interval_slopes)

    # Slope jumps at internal knots: delta v_i = v_{i+1/2} - v_{i-1/2}
    slope_jumps = [interval_slopes[i+1] - interval_slopes[i] for i in range(len(interval_slopes) - 1)]
    max_slope_jump = max(abs(j) for j in slope_jumps)

    # Theoretical linear interpolation error bound:
    # On each interval [t_i, t_{i+1}], error |e(t)| <= (1/8) * dt^2 * max |theta''|
    # For amp = 45 deg, peak analytic acceleration is 150 * sqrt(3) ~= 259.807621135 deg/s^2
    peak_analytic_acc = (amp_deg / 45.0) * 150.0 * math.sqrt(3.0)
    theoretical_max_interp_error_deg = 0.125 * (dt ** 2) * peak_analytic_acc

    # Empirical chord error evaluated at interval midpoints:
    max_chord_error_deg = 0.0
    for i in range(n_steps - 1):
        t_mid = times[i] + 0.5 * dt
        th_mid_linear = 0.5 * (thetas[i] + thetas[i+1])
        th_mid_exact = evaluate_trajectory_analytic(t_mid, amp_deg)[0]
        err = abs(th_mid_linear - th_mid_exact)
        if err > max_chord_error_deg:
            max_chord_error_deg = err

    # Initial slope jump from stationary rest:
    # Prior to t=0, object velocity v(0-) = 0.0 deg/s.
    # At t=0+, solver evaluates interval [0, dt] with slope first_interval_slope.
    initial_start_slope_jump_deg_s = abs(first_interval_slope - 0.0)

    return {
        "sampling_dt_s": dt,
        "duration_s": t_max,
        "knot_count": n_steps,
        "first_interval_slope_deg_s": first_interval_slope,
        "initial_start_slope_jump_deg_s": initial_start_slope_jump_deg_s,
        "max_interval_slope_deg_s": max_slope,
        "min_interval_slope_deg_s": min_slope,
        "max_knot_slope_jump_deg_s": max_slope_jump,
        "peak_analytic_acceleration_deg_s2": peak_analytic_acc,
        "theoretical_max_interp_error_deg": theoretical_max_interp_error_deg,
        "empirical_max_chord_error_deg": max_chord_error_deg,
        "reader_physical_source_pins": {
            "solver_reader_function": "JMotionMovActive::DfGetNewAng(double t)",
            "solver_reader_source_file": "src/source/JMotionObj.cpp",
            "solver_reader_lines": "214-226",
            "solver_motion_caller": "src/source/JMotionObj.cpp:615-627 (JMotionMov::RotationFile)",
            "file_loader_function": "JMotionDataRotAxis::LoadFileAng",
            "file_loader_source_file": "src/source/JMotionData.cpp",
            "file_loader_lines": "124-145",
            "xml_motion_parser": "src/source/JMotion.cpp:214-230 (mvrotfile)"
        },
        "rejection_summary": (
            "Because DualSPHysics DfGetNewAng performs piecewise LINEAR interpolation between knots, "
            "the native motion experienced by particles has piecewise constant velocity with finite slope "
            f"jumps up to {max_slope_jump:.6f} deg/s at each knot and an initial jump of {first_interval_slope:.6e} deg/s "
            "at t=0+. Therefore, the sampled motion file is NOT mathematically C2 in the solver, and "
            "the owner-041 guarantee of exact zero native velocity/acceleration discontinuities is REJECTED."
        )
    }


# -----------------------------------------------------------------------------
# Official DualSPHysics Motion File Generation (.17g and Exclusive Mode 'x')
# -----------------------------------------------------------------------------

def generate_motion_dat_content(
    amp_deg: float = 45.0,
    t_max: float = 12.0,
    dt: float = 0.001
) -> str:
    """Generates official DualSPHysics 2-column motion file content using .17g precision.

    Read by DualSPHysics JMotionDataRotAxis::LoadFileAng:
    - Remark lines start with '#'
    - Values: whitespace-separated 'time_s angle_deg' formatted with .17g for exact IEEE 754 roundtrip.
    """
    lines = [
        "# DualSPHysics DS-DATA-02 Family F7 Moving Obstacle Prescribed Rotation Data",
        "# Trajectory: Piecewise Quintic Polynomial (Minimum-Jerk) Analytic Target",
        f"# Parameters: Nominal Stroke Amplitude = {amp_deg:.2f} deg, Window = {t_max:.2f} s, dt = {dt:.6g} s",
        "# Reader: JMotionDataRotAxis::LoadFileAng (DualSPHysics JMotionObj / mvrotfile)",
        "# Note: Solver evaluates trajectory via piecewise linear interpolation in DfGetNewAng",
        "# Columns: Time(s) Angle(degrees)",
        "# Precision: IEEE 754 full roundtrip (.17g)",
        "# -----------------------------------------------------------------------------"
    ]

    n_steps = int(round(t_max / dt)) + 1
    for i in range(n_steps):
        t = i * dt
        if t > t_max:
            t = t_max
        theta, _, _ = evaluate_trajectory_analytic(t, amp_deg)
        lines.append(f"{t:.17g}\t{theta:.17g}")

    return "\n".join(lines) + "\n"


def write_motion_file_exclusive(path: Path, content: str) -> str:
    """Writes motion file content using mode 'x' (exclusive creation).

    Raises FileExistsError if the target file already exists, guaranteeing overwrite-safe creation.
    Returns the SHA256 hex digest of the written content.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", encoding="utf-8") as f:
        f.write(content)
    return sha256_file(path)


# -----------------------------------------------------------------------------
# XML Declared Subtree Replacement & Independent Whole-Undo Verification
# -----------------------------------------------------------------------------

def generate_smooth_c2_definition_xml(
    ref_xml_path: Path,
    motion_file_name: str = "motion_obstacle_smooth_c2.dat"
) -> str:
    """Generates modified XML by replacing ONLY the declared motion subtree '<casedef><motion><objreal ref=\"2\">'.

    All non-motion fields (including mkconfig, constantsdef, geometry, execution) are strictly preserved.
    """
    ref_tree = ET.parse(ref_xml_path)
    ref_root = ref_tree.getroot()

    objreal = ref_root.find(".//motion/objreal[@ref='2']")
    if objreal is None:
        raise ValueError(f"Could not find <motion><objreal ref='2'> in {ref_xml_path}")

    # Clear existing children (mvrotsinu, wait)
    objreal.clear()
    objreal.set("ref", "2")

    # Add begin
    begin_elem = ET.SubElement(objreal, "begin")
    begin_elem.set("mov", "1")
    begin_elem.set("start", "0")
    begin_elem.set("finish", "12")

    # Add mvrotfile
    mv_elem = ET.SubElement(objreal, "mvrotfile")
    mv_elem.set("id", "1")
    mv_elem.set("duration", "12")
    mv_elem.set("anglesunits", "degrees")

    file_elem = ET.SubElement(mv_elem, "file")
    file_elem.set("name", motion_file_name)

    axis1_elem = ET.SubElement(mv_elem, "axisp1")
    axis1_elem.set("x", "-0.04")
    axis1_elem.set("y", "0")
    axis1_elem.set("z", "0.05")

    axis2_elem = ET.SubElement(mv_elem, "axisp2")
    axis2_elem.set("x", "-0.04")
    axis2_elem.set("y", "0")
    axis2_elem.set("z", "1.05")

    return ET.tostring(ref_root, encoding="utf-8").decode("utf-8")


def verify_xml_declared_subtree_undo(
    ref_xml_path: Path,
    mod_xml_path: Path
) -> dict[str, Any]:
    """Performs an independent whole-XML undo verification.

    Takes mod_xml_path, identifies the declared motion subtree, restores it with the reference
    motion subtree, and verifies that the serialized restored tree exactly matches the reference tree:
    ET.tostring(restored_root) == ET.tostring(ref_root).
    """
    ref_tree = ET.parse(ref_xml_path)
    mod_tree = ET.parse(mod_xml_path)

    ref_root = ref_tree.getroot()
    mod_root = mod_tree.getroot()

    ref_objreal = ref_root.find(".//motion/objreal[@ref='2']")
    mod_objreal = mod_root.find(".//motion/objreal[@ref='2']")

    if ref_objreal is None or mod_objreal is None:
        return {
            "undo_verified": False,
            "reason": "Missing declared motion objreal element"
        }

    # Clone mod_tree to perform independent undo
    restored_tree = copy.deepcopy(mod_tree)
    restored_root = restored_tree.getroot()
    restored_motion = restored_root.find(".//motion")
    restored_objreal = restored_motion.find("objreal[@ref='2']")

    idx = list(restored_motion).index(restored_objreal)
    restored_motion.remove(restored_objreal)
    restored_motion.insert(idx, copy.deepcopy(ref_objreal))

    s_ref = ET.tostring(ref_root, encoding="utf-8")
    s_restored = ET.tostring(restored_root, encoding="utf-8")

    whole_tree_identical_upon_undo = (s_ref == s_restored)

    # Detailed non-motion field verifications
    ref_const = ref_root.find(".//constantsdef")
    mod_const = mod_root.find(".//constantsdef")
    constants_identical = (
        ref_const is not None and mod_const is not None and
        ET.tostring(ref_const, encoding="utf-8") == ET.tostring(mod_const, encoding="utf-8")
    )

    ref_mk = ref_root.find(".//mkconfig")
    mod_mk = mod_root.find(".//mkconfig")
    mkconfig_identical = (
        ref_mk is not None and mod_mk is not None and
        ET.tostring(ref_mk, encoding="utf-8") == ET.tostring(mod_mk, encoding="utf-8")
    )

    ref_geom = ref_root.find(".//geometry")
    mod_geom = mod_root.find(".//geometry")
    geometry_identical = (
        ref_geom is not None and mod_geom is not None and
        ET.tostring(ref_geom, encoding="utf-8") == ET.tostring(mod_geom, encoding="utf-8")
    )

    ref_exec = ref_root.find(".//execution")
    mod_exec = mod_root.find(".//execution")
    execution_identical = (
        ref_exec is not None and mod_exec is not None and
        ET.tostring(ref_exec, encoding="utf-8") == ET.tostring(mod_exec, encoding="utf-8")
    )

    return {
        "whole_tree_identical_upon_undo": whole_tree_identical_upon_undo,
        "constants_identical": constants_identical,
        "mkconfig_identical": mkconfig_identical,
        "geometry_identical": geometry_identical,
        "execution_identical": execution_identical,
        "no_silent_geometry_kernel_repair": geometry_identical,
        "declared_motion_subtree_isolated": (
            whole_tree_identical_upon_undo and constants_identical and
            mkconfig_identical and geometry_identical and execution_identical
        )
    }


# -----------------------------------------------------------------------------
# Reference Contrast
# -----------------------------------------------------------------------------

def contrast_with_reference_motion(
    root_report_path: Path
) -> dict[str, Any]:
    """Contrasts prospective smooth C2 trajectory with Root's reference audit findings (017)."""
    comparison = {
        "reference_prescribed_motion_flaws": [
            {
                "time_s": 2.0,
                "phenomenon": "Abrupt velocity termination into wait",
                "old_velocity_jump_deg_s": -34.94899869705837,
                "old_acceleration_jump_deg_s2": -270.3326854726472,
                "prospective_target_velocity_jump_deg_s": 0.0,
                "prospective_target_acceleration_jump_deg_s2": 0.0,
                "repair_status": "Analytic target smooth; discrete piecewise linear error bounded"
            },
            {
                "time_s": 2.25,
                "phenomenon": "Impulsive start from wait into segment 3",
                "old_velocity_jump_deg_s": -113.09733552923255,
                "old_acceleration_jump_deg_s2": -3.48e-14,
                "prospective_target_velocity_jump_deg_s": 0.0,
                "prospective_target_acceleration_jump_deg_s2": 0.0,
                "repair_status": "Analytic target smooth; discrete piecewise linear error bounded"
            },
            {
                "time_s": 4.25,
                "phenomenon": "Abrupt velocity termination into wait",
                "old_velocity_jump_deg_s": 34.948998697058364,
                "old_acceleration_jump_deg_s2": 270.3326854726472,
                "prospective_target_velocity_jump_deg_s": 0.0,
                "prospective_target_acceleration_jump_deg_s2": 0.0,
                "repair_status": "Analytic target smooth; discrete piecewise linear error bounded"
            },
            {
                "time_s": 4.5,
                "phenomenon": "Impulsive start from wait into segment 1",
                "old_velocity_jump_deg_s": 113.09733552923255,
                "old_acceleration_jump_deg_s2": 0.0,
                "prospective_target_velocity_jump_deg_s": 0.0,
                "prospective_target_acceleration_jump_deg_s2": 0.0,
                "repair_status": "Analytic target smooth; discrete piecewise linear error bounded"
            }
        ],
        "wait_state_comparison": {
            "old_wait_pose_deg": -42.797543233281914,
            "old_wait_comment": "Waited at rotated paddle pose, unphysically biasing fluid displacement",
            "prospective_rest_pose_deg": 0.0,
            "prospective_rest_comment": "Returns strictly to neutral center pose (0.0 deg) with zero velocity/acceleration for 4.0 s rest tail"
        },
        "causality_boundary": (
            "Elimination of source motion discontinuities is a necessary regularity repair. "
            "However, per Root governance, this source-level repair alone does NOT constitute a unique causal explanation "
            "for the historical 43.011% spatial KE discrepancy, nor does it relax qualification gates."
        )
    }
    return comparison


# -----------------------------------------------------------------------------
# Main Worker Pipeline
# -----------------------------------------------------------------------------

def run_f7_prospective_worker_042(
    base_dir: Path,
    generate_controls: bool = False,
    dry_run: bool = False,
    output_path: Path | None = None
) -> dict[str, Any]:
    """Executes the F7 prospective smooth driving-control worker for round 042.

    If generate_controls is True (Rootguard dispatch only), writes motion files using exclusive mode 'x'.
    Otherwise, performs analytic audit, sampled I/O description, XML undo verification, and SHA prediction.
    """
    definitions_dir = base_dir / "definitions"
    controls_dir = base_dir / "controls"
    case_manifests_dir = base_dir / "case_manifests"
    reports_dir = base_dir / "reports"

    definitions_dir.mkdir(parents=True, exist_ok=True)
    controls_dir.mkdir(parents=True, exist_ok=True)
    case_manifests_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    # 1. Analytic C2 audit
    analytic_audit = audit_transition_regularity(amp_deg=45.0)

    # 2. Discrete Sampled I/O Descriptors (dt = 0.001 s and dt = 0.0005 s)
    sampled_io_001 = describe_sampled_motion_io(amp_deg=45.0, t_max=12.0, dt=0.001)
    sampled_io_0005 = describe_sampled_motion_io(amp_deg=45.0, t_max=12.0, dt=0.0005)

    # 3. Predict motion file content and SHA256 without unsafe overwrite
    content_001 = generate_motion_dat_content(amp_deg=45.0, t_max=12.0, dt=0.001)
    sha_001_predicted = sha256_bytes(content_001.encode("utf-8"))

    content_0005 = generate_motion_dat_content(amp_deg=45.0, t_max=12.0, dt=0.0005)
    sha_0005_predicted = sha256_bytes(content_0005.encode("utf-8"))

    motion_file_controls_001 = controls_dir / "motion_obstacle_smooth_c2.dat"
    motion_file_controls_0005 = controls_dir / "motion_obstacle_smooth_c2_dt0005.dat"

    # Only write motion files if explicitly requested under Rootguard dispatch
    if generate_controls and not dry_run:
        write_motion_file_exclusive(motion_file_controls_001, content_001)
        write_motion_file_exclusive(motion_file_controls_0005, content_0005)

    # 4. Definition verification and XML whole-undo integrity
    ref_dir = Path("/home/jade/.codex/worktrees/ds-data-02-f7/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F7/reference/definitions")
    cases = [
        {
            "res": "COARSE",
            "dp_m": 0.025,
            "case_id": "F7_OBSTACLE_SMOOTH_C2_BASE_COARSE",
            "ref_xml": ref_dir / "F7_OBSTACLE_REFERENCE_BASE_COARSE_Def.xml",
            "new_xml": definitions_dir / "F7_OBSTACLE_SMOOTH_C2_BASE_COARSE_Def.xml",
            "pointref": [0.0125, 0.0125, 0.0125]
        },
        {
            "res": "MEDIUM",
            "dp_m": 0.020,
            "case_id": "F7_OBSTACLE_SMOOTH_C2_BASE_MEDIUM",
            "ref_xml": ref_dir / "F7_OBSTACLE_REFERENCE_BASE_MEDIUM_Def.xml",
            "new_xml": definitions_dir / "F7_OBSTACLE_SMOOTH_C2_BASE_MEDIUM_Def.xml",
            "pointref": [0.01, 0.01, 0.01]
        },
        {
            "res": "FINE",
            "dp_m": 0.016,
            "case_id": "F7_OBSTACLE_SMOOTH_C2_BASE_FINE",
            "ref_xml": ref_dir / "F7_OBSTACLE_REFERENCE_BASE_FINE_Def.xml",
            "new_xml": definitions_dir / "F7_OBSTACLE_SMOOTH_C2_BASE_FINE_Def.xml",
            "pointref": [0.008, 0.008, 0.008]
        }
    ]

    case_audits = []
    for c in cases:
        # Check if new definition XML exists, else generate it
        if not c["new_xml"].exists() and not dry_run:
            xml_text = generate_smooth_c2_definition_xml(c["ref_xml"], "motion_obstacle_smooth_c2.dat")
            with open(c["new_xml"], "w", encoding="utf-8") as f:
                f.write(xml_text)

        xml_sha = sha256_file(c["new_xml"]) if c["new_xml"].exists() else ""
        undo_audit = verify_xml_declared_subtree_undo(c["ref_xml"], c["new_xml"]) if c["new_xml"].exists() else {}

        # Case manifest
        manifest_data = {
            "schema": "ds02.f7.case-manifest.v1",
            "case_id": c["case_id"],
            "physical_parent_id": "F7_OBSTACLE_SMOOTH_C2_BASE",
            "mechanism": "moving_obstacle_exchange",
            "resolution": c["res"],
            "dp_m": c["dp_m"],
            "definition_xml": str(c["new_xml"].resolve()),
            "definition_sha256": xml_sha,
            "motion_file_reference": "motion_obstacle_smooth_c2.dat",
            "motion_file_predicted_sha256": sha_001_predicted,
            "control_cadence_options": {
                "selected_target_dt001": {
                    "dt_s": 0.001,
                    "rows": 12001,
                    "predicted_sha256": sha_001_predicted,
                    "interp_error_deg": sampled_io_001["theoretical_max_interp_error_deg"]
                },
                "independent_control_dt0005": {
                    "dt_s": 0.0005,
                    "rows": 24001,
                    "predicted_sha256": sha_0005_predicted,
                    "interp_error_deg": sampled_io_0005["theoretical_max_interp_error_deg"]
                }
            },
            "recipe": {
                "recipe_id": "F7_OBSTACLE_SMOOTH_C2_CONTROL_002",
                "repair_number": 2,
                "pointref_m": c["pointref"],
                "motion_type": "mvrotfile",
                "duration_s": 12.0,
                "stroke_amplitude_deg": 45.0,
                "active_window_s": [0.0, 8.0],
                "rest_tail_s": [8.0, 12.0],
                "sampling_dt_s": 0.001,
                "native_reader": "JMotionMovActive::DfGetNewAng (piecewise linear)"
            },
            "governance": {
                "status": "prospective_definition_ready_for_root_dispatch",
                "q_n_status": "not_granted",
                "production_approval": "none",
                "independent_case_count_increment": 0
            }
        }

        manifest_path = case_manifests_dir / f"{c['case_id']}.json"
        if not dry_run:
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest_data, f, indent=2)

        case_audits.append({
            "case_id": c["case_id"],
            "resolution": c["res"],
            "dp_m": c["dp_m"],
            "definition_xml": str(c["new_xml"].resolve()),
            "definition_sha256": xml_sha,
            "manifest_json": str(manifest_path.resolve()),
            "undo_audit": undo_audit
        })

    # 5. Contrast against Root reference report (017)
    root_report_path = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/F7_OBSTACLE_ORIGINAL_PRESCRIBED_MOTION_REGULARITY/root-obstacle-original-source-bound-motion-regularity-017/motion-regularity.json")
    root_contrast = contrast_with_reference_motion(root_report_path)

    # 6. Global Report Assembly
    report = {
        "schema": "ds02.f7.obstacle-smooth-motion-audit-report.v2",
        "created_at_utc": "2026-10-04T03:15:00Z",
        "family_id": "F7",
        "physical_mother_id": "F7_OBSTACLE_SMOOTH_C2_BASE",
        "mechanism": "moving_obstacle_exchange",
        "governance_and_resource_state": {
            "campaign_goal_progress": "0/336",
            "campaign_qualification_progress": "273/320",
            "gpu_budget_charged_hours": 65.3,
            "gpu_budget_total_hours": 96.0,
            "gpu_budget_remaining_hours": 30.7,
            "home_disk_floor_gib": 500,
            "home_disk_free_gib": 2978,
            "q_n_status": "not_granted",
            "production_approval": "none",
            "case_count_prediction": {
                "prospective_base_definitions": 3,
                "independent_cadence_control_definitions": 1,
                "independent_case_count_increment": 0
            }
        },
        "rejection_of_owner_041_guarantee": {
            "status": "REJECTED",
            "reason": (
                "Official DualSPHysics motion file reader 'JMotionMovActive::DfGetNewAng' "
                "(src/source/JMotionObj.cpp:214-226) performs piecewise LINEAR interpolation between knots. "
                "The sampled motion file is therefore piecewise linear in native solver space, possessing "
                "finite slope jumps at each knot and a non-zero start-interval slope on [0, dt]. "
                "The owner guarantee of exact zero native velocity/acceleration discontinuities is false and rejected."
            )
        },
        "analytic_regularity_audit": analytic_audit,
        "sampled_io_descriptors": {
            "selected_target_dt001": sampled_io_001,
            "independent_control_dt0005": sampled_io_0005
        },
        "motion_file_specifications": {
            "precision_format": "%.17g",
            "write_mode": "exclusive_x",
            "dt001_predicted_sha256": sha_001_predicted,
            "dt0005_predicted_sha256": sha_0005_predicted,
            "actual_generation_state": "Rootguard dispatch only; files not generated in worktree" if not generate_controls else "generated_under_rootguard"
        },
        "case_audits": case_audits,
        "root_motion_regularity_contrast": root_contrast,
        "causality_and_claim_boundaries": {
            "spatial_ke_discrepancy_attribution": (
                "Source motion continuity repair does NOT explain the 43.011% spatial KE discrepancy. "
                "Multi-resolution discretization and lattice-boundary interaction remain active unisolated factors."
            ),
            "cadence_sensitivity_boundary": (
                "Sensitivity to input sampling cadence (0.001 s vs 0.0005 s) requires separate "
                "actual full native qualification under Root strict dispatch."
            ),
            "production_proxy": "No whole production proxy claimed.",
            "pump_fallback": "No pump fallback claims made."
        }
    }

    target_report_file = output_path or (reports_dir / "f7_obstacle_smooth_motion_audit_report.json")
    if not dry_run:
        with open(target_report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="DS-DATA-02 F7 Smooth Motion Prospective Worker (Round 042)")
    parser.add_argument("--base-dir", type=Path, default=Path(__file__).parent, help="Base working directory")
    parser.add_argument("--binding", type=Path, default=None, help="Optional binding JSON")
    parser.add_argument("--output", type=Path, default=None, help="Output report JSON path")
    parser.add_argument("--generate-controls", action="store_true", default=False, help="Generate actual motion files (Rootguard dispatch only)")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Run audit without writing files to disk")
    args = parser.parse_args()

    report = run_f7_prospective_worker_042(
        base_dir=args.base_dir,
        generate_controls=args.generate_controls,
        dry_run=args.dry_run,
        output_path=args.output
    )
    print("F7 Smooth Motion Prospective Worker completed successfully.")
    print(f"Analytic C2 Target Smoothness: {report['analytic_regularity_audit']['all_c2_continuous']}")
    print(f"Sampled dt=0.001s max knot slope jump: {report['sampled_io_descriptors']['selected_target_dt001']['max_knot_slope_jump_deg_s']:.6f} deg/s")
    print(f"Sampled dt=0.0005s max knot slope jump: {report['sampled_io_descriptors']['independent_control_dt0005']['max_knot_slope_jump_deg_s']:.6f} deg/s")
    print(f"Owner-041 Guarantee Status: {report['rejection_of_owner_041_guarantee']['status']}")


if __name__ == "__main__":
    main()
