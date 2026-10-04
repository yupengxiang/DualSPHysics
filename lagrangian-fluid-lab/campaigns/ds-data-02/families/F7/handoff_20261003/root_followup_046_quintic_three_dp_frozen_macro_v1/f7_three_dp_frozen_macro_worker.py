#!/usr/bin/env python3
"""f7_three_dp_frozen_macro_worker.py

DS-DATA-02 Family F7: Full 12s Binding-Driven Three-DP / All-Pairs Frozen Macro
and Moving Paddle Actual Pose Worker.

Scope:
    lagrangian-fluid-lab/campaigns/ds-data-02/families/F7/handoff_20261003/root_followup_046_quintic_three_dp_frozen_macro_v1

Governance & Physical Mother Boundary:
    1. Lineage Group: F7_OBSTACLE_REFERENCE_BASE_AND_QUINTIC_SHARED_GEOMETRY_NO_LEAK
    2. Physical Condition SHA256: 512cb217f29e716346c249339545ed2599e7cb1aeb8e81fe7f1c0cf7f341c34c
    3. Three Discretizations (ExplicitWet Geometry):
       - Coarse:  dp = 0.020 m (40,700 fluid, 1,984 moving Type 1, 27,495 fixed Type 0)
       - Medium:  dp = 0.016 m (78,732 fluid, 3,798 moving Type 1, 42,612 fixed Type 0)
       - Fine:    dp = 0.010 m (318,716 fluid, 4,899 moving Type 1, 100,662 fixed Type 0)
    4. Refinement Ratios:
       - Coarse / Medium = 0.020 / 0.016 = 1.25
       - Medium / Fine   = 0.016 / 0.010 = 1.60
       - Coarse / Fine   = 0.020 / 0.010 = 2.00
       Explicit rejection: Refinement ratio is NOT constant (1.25 != 1.60).
       Explicit rejection: No particle UID match across resolutions.
    5. Motion Forcing:
       - Analytic Target: Piecewise quintic polynomial (C2 smooth, two 45 deg cycles in 0..8s, neutral rest in 8..12s).
       - Actual Solver Implementation: Official DualSPHysics reader (JMotionMovActive::DfGetNewAng,
         src/source/JMotionObj.cpp:214-226) performs PIECEWISE LINEAR interpolation with finite knot slope jumps;
         no native C2 claim.
    6. Moving Type 1 Marker Pose Path:
       - Evaluated from actual native positions of Type 1 markers around pivot [-0.04, 0.0, 0.05] m.
       - Validated against analytic quintic target and piecewise linear forcing.
    7. Frozen Macro Observables & Normalizers:
       - Operators: active_mass_kg, com_x_m, com_y_m, com_z_m, kinetic_energy_j
       - Mass Normalizer: Continuous initial mass 320.1984 kg
       - COM Normalizers: Initial envelope widths [1.1, 0.7, 0.432] m
       - KE Normalizer: Fine reference peak kinetic energy over 0..12s
       - Macro Relative Budget: 0.05 (5%)
       - Old spatial KE negative evidence (~43% discrepancy) is preserved; KE 5% failure gate is strictly kept.
    8. Particle Exclusions:
       - Lifecycle: FINITE_INITIAL_NUMERICAL_COHORT_WITH_EXCLUSIONS
       - Policy: native_unknown_exclusions_retained (unknown physical fates; no closed-cohort assumption).
    9. Explicit Gaps & Status:
       - Q-N Status: not_granted
       - Production Approval: none
       - Residence-specific registered budget is None (gap returned explicitly).
       - Independent time/save and motion cadence/protocol sensitivity still required.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

import numpy as np

# Mandatory 13 fields for typed DualSPHysics HDF5 trajectory
MANDATORY_13_FIELDS = (
    "time",
    "valid",
    "initial_type",
    "particle_id",
    "particle_zone",
    "initial_mk",
    "initial_mass",
    "mass",
    "position",
    "velocity",
    "density",
    "pressure",
    "type",
)

# Standard 5 macro operators
OPERATORS = [
    "active_mass_kg",
    "com_x_m",
    "com_y_m",
    "com_z_m",
    "kinetic_energy_j",
]

# Physical condition hash pinned across all quintic explicit-wet variants
PHYSICAL_CONDITION_SHA256 = (
    "512cb217f29e716346c249339545ed2599e7cb1aeb8e81fe7f1c0cf7f341c34c"
)

# Paddle rotation axis
PADDLE_AXIS_POINT = (-0.04, 0.0, 0.05)
PADDLE_AXIS_DIRECTION = (0.0, 0.0, 1.0)


def sha256_file(path: Path | str) -> str:
    """Computes SHA256 hex digest of a file in chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


# -----------------------------------------------------------------------------
# Analytic Quintic Trajectory Formulation (Two 45° cycles + 4s neutral rest)
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


def evaluate_trajectory_analytic(t: float, amp_deg: float = 45.0) -> tuple[float, float, float]:
    """Evaluates analytic angle (deg), angular velocity (deg/s), and angular acceleration (deg/s^2) at time t.

    Window: 0..8s active (two full symmetric cycles), 8..12s neutral rest tail at 0 deg.
    """
    scale = amp_deg / 45.0

    if t <= 0.0 or t >= 12.0 or t >= 8.0:
        return 0.0, 0.0, 0.0

    if t < 1.0:
        tau = t / 1.0
        theta = scale * 45.0 * quintic_s(tau)
        vel = scale * 45.0 * quintic_ds(tau) / 1.0
        acc = scale * 45.0 * quintic_d2s(tau) / 1.0
        return theta, vel, acc
    elif t < 3.0:
        tau = (t - 1.0) / 2.0
        theta = scale * (45.0 - 90.0 * quintic_s(tau))
        vel = scale * (-90.0 * quintic_ds(tau) / 2.0)
        acc = scale * (-90.0 * quintic_d2s(tau) / 4.0)
        return theta, vel, acc
    elif t < 5.0:
        tau = (t - 3.0) / 2.0
        theta = scale * (-45.0 + 90.0 * quintic_s(tau))
        vel = scale * (90.0 * quintic_ds(tau) / 2.0)
        acc = scale * (90.0 * quintic_d2s(tau) / 4.0)
        return theta, vel, acc
    elif t < 7.0:
        tau = (t - 5.0) / 2.0
        theta = scale * (45.0 - 90.0 * quintic_s(tau))
        vel = scale * (-90.0 * quintic_ds(tau) / 2.0)
        acc = scale * (-90.0 * quintic_d2s(tau) / 4.0)
        return theta, vel, acc
    else:  # 7.0 <= t < 8.0
        tau = (t - 7.0) / 1.0
        theta = scale * (-45.0 + 45.0 * quintic_s(tau))
        vel = scale * (45.0 * quintic_ds(tau) / 1.0)
        acc = scale * (45.0 * quintic_d2s(tau) / 1.0)
        return theta, vel, acc


def evaluate_piecewise_linear_motion(
    times: np.ndarray,
    angles: np.ndarray,
    t: float,
) -> float:
    """Simulates DualSPHysics official motion reader JMotionMovActive::DfGetNewAng (piecewise linear)."""
    if t <= times[0]:
        return float(angles[0])
    if t >= times[-1]:
        return float(angles[-1])
    idx = int(np.searchsorted(times, t))
    t0, t1 = times[idx - 1], times[idx]
    a0, a1 = angles[idx - 1], angles[idx]
    if t1 == t0:
        return float(a0)
    tfactor = (t - t0) / (t1 - t0)
    return float(a0 + tfactor * (a1 - a0))


# -----------------------------------------------------------------------------
# Moving Paddle Type 1 Marker Pose Path Extractor
# -----------------------------------------------------------------------------

def extract_moving_paddle_pose(
    positions_t: np.ndarray,
    positions_0: np.ndarray,
    axis_origin: tuple[float, float] = (-0.04, 0.0),
) -> dict[str, float]:
    """Extracts actual moving paddle pose from Type 1 marker positions in the xy-plane.

    Rigid 2D rotation around axis_origin:
        Delta x_i(t) = x_i(t) - x_axis
        Delta y_i(t) = y_i(t) - y_axis
    Least-squares angle:
        theta = atan2(sum (Delta y_t * Delta x_0 - Delta x_t * Delta y_0),
                      sum (Delta x_t * Delta x_0 + Delta y_t * Delta y_0))
    """
    x_ax, y_ax = axis_origin
    dx0 = positions_0[:, 0] - x_ax
    dy0 = positions_0[:, 1] - y_ax
    dxt = positions_t[:, 0] - x_ax
    dyt = positions_t[:, 1] - y_ax

    dot_sum = float(np.sum(dxt * dx0 + dyt * dy0))
    cross_sum = float(np.sum(dyt * dx0 - dxt * dy0))
    angle_rad = math.atan2(cross_sum, dot_sum)
    angle_deg = math.degrees(angle_rad)

    # Centroid
    centroid = [float(np.mean(positions_t[:, i])) for i in range(3)]

    # Rigid reconstruction RMS
    cos_th = math.cos(angle_rad)
    sin_th = math.sin(angle_rad)
    pred_x = x_ax + cos_th * dx0 - sin_th * dy0
    pred_y = y_ax + sin_th * dx0 + cos_th * dy0
    res_x = positions_t[:, 0] - pred_x
    res_y = positions_t[:, 1] - pred_y
    rigid_rms_m = float(math.sqrt(np.mean(res_x ** 2 + res_y ** 2)))

    return {
        "angle_deg": angle_deg,
        "centroid_x_m": centroid[0],
        "centroid_y_m": centroid[1],
        "centroid_z_m": centroid[2],
        "rigid_rms_m": rigid_rms_m,
    }


# -----------------------------------------------------------------------------
# Macro Series Extraction from Typed Trajectory (HDF5)
# -----------------------------------------------------------------------------

def compute_frame_macro(
    masses: np.ndarray,
    positions: np.ndarray,
    velocities: np.ndarray,
    valid_flags: np.ndarray,
    fluid_mask: np.ndarray,
) -> tuple[list[float], int, float]:
    """Computes active mass, COM xyz, and kinetic energy for a single frame.

    Returns:
        ([active_mass, com_x, com_y, com_z, kinetic_energy], excluded_count, excluded_mass)
    """
    active_mask = fluid_mask & valid_flags
    if not np.any(active_mask):
        raise ValueError("No active fluid particles in frame")

    m = masses[active_mask]
    p = positions[active_mask]
    v = velocities[active_mask]

    if np.any(~np.isfinite(m) | (m <= 0)):
        raise ValueError("Non-finite or non-positive active fluid masses detected")
    if np.any(~np.isfinite(p)) or np.any(~np.isfinite(v)):
        raise ValueError("Non-finite active fluid positions or velocities detected")

    total_mass = float(np.sum(m))
    weighted_p = np.sum(m[:, None] * p, axis=0)
    com = (weighted_p / total_mass).tolist()
    kinetic_energy = float(0.5 * np.sum(m * np.sum(v * v, axis=1)))

    # Track excluded fluid particles
    excluded_mask = fluid_mask & (~valid_flags)
    excluded_count = int(np.sum(excluded_mask))
    excluded_mass = float(np.sum(masses[excluded_mask])) if excluded_count > 0 else 0.0

    return [total_mass, *com, kinetic_energy], excluded_count, excluded_mass


def extract_macros_from_typed_h5(
    h5_path: Path | str,
    particle_chunk: int = 65536,
) -> dict[str, Any]:
    """Extracts macro series, moving Type 1 pose path, and native exclusion accounting from typed HDF5."""
    import h5py

    path = Path(h5_path)
    file_sha = sha256_file(path)

    with h5py.File(path, "r") as h:
        # Check mandatory fields
        for field in MANDATORY_13_FIELDS:
            if field not in h:
                raise ValueError(f"Typed HDF5 missing mandatory field: {field}")

        times = np.asarray(h["time"][:], dtype=float)
        if len(times) < 2 or times[0] != 0.0 or times[-1] < 12.0:
            raise ValueError(f"Trajectory does not cover full 0..12s window: {times[0]} to {times[-1]}")
        if not np.all(np.diff(times) > 0):
            raise ValueError("Timeline is not strictly increasing")

        initial_types = np.asarray(h["initial_type"][:], dtype=int)
        initial_masses = np.asarray(h["initial_mass"][:], dtype=float)

        fluid_mask = initial_types == 3
        type1_mask = initial_types == 1
        type0_mask = initial_types == 0

        # Positive initial weights for all fluid particles
        fluid_initial_masses = initial_masses[fluid_mask]
        if np.any(~np.isfinite(fluid_initial_masses) | (fluid_initial_masses <= 0)):
            raise ValueError("Fluid particles must have strictly positive initial masses")

        initial_fluid_mass_sum = float(np.sum(fluid_initial_masses))
        type1_count = int(np.sum(type1_mask))
        fluid_count = int(np.sum(fluid_mask))
        type0_count = int(np.sum(type0_mask))
        total_count = len(initial_types)

        # Get initial positions of Type 1 markers for pose tracking
        initial_pos_type1 = np.asarray(h["position"][0, type1_mask], dtype=float)

        num_frames = len(times)
        macro_values: list[list[float]] = []
        pose_records: list[dict[str, float]] = []
        exclusions_per_frame: list[dict[str, Any]] = []

        for frame in range(num_frames):
            valid = np.asarray(h["valid"][frame, :], dtype=bool)
            mass = np.asarray(h["mass"][frame, :], dtype=float)
            pos = np.asarray(h["position"][frame, :], dtype=float)
            vel = np.asarray(h["velocity"][frame, :], dtype=float)

            # Macro extraction
            frame_vals, excl_cnt, excl_m = compute_frame_macro(
                mass, pos, vel, valid, fluid_mask
            )
            macro_values.append(frame_vals)
            exclusions_per_frame.append({
                "frame": frame,
                "time_s": float(times[frame]),
                "excluded_count": excl_cnt,
                "excluded_mass_kg": excl_m,
            })

            # Type 1 moving marker pose extraction
            pos_t1 = pos[type1_mask & valid]
            if len(pos_t1) == len(initial_pos_type1):
                pose = extract_moving_paddle_pose(pos_t1, initial_pos_type1, axis_origin=PADDLE_AXIS_POINT[:2])
                pose["time_s"] = float(times[frame])
                pose_records.append(pose)
            else:
                pose_records.append({
                    "time_s": float(times[frame]),
                    "angle_deg": float("nan"),
                    "centroid_x_m": float("nan"),
                    "centroid_y_m": float("nan"),
                    "centroid_z_m": float("nan"),
                    "rigid_rms_m": float("nan"),
                    "warning": "Type 1 marker count changed during simulation",
                })

        physical_cond = str(h.attrs.get("physical_condition_sha256", ""))

    return {
        "source": str(path),
        "source_sha256": file_sha,
        "physical_condition_sha256": physical_cond,
        "particle_counts": {
            "total": total_count,
            "fluid": fluid_count,
            "type1_moving": type1_count,
            "type0_fixed": type0_count,
        },
        "initial_fluid_mass_sum_kg": initial_fluid_mass_sum,
        "time_s": times.tolist(),
        "operators": list(OPERATORS),
        "values": macro_values,
        "moving_paddle_poses": pose_records,
        "exclusions": exclusions_per_frame,
    }


# -----------------------------------------------------------------------------
# Comparison and Normalization Engine
# -----------------------------------------------------------------------------

def interpolate_series_to_grid(
    times: np.ndarray,
    values: np.ndarray,
    grid: np.ndarray,
) -> np.ndarray:
    """Interpolates macro series onto the uniform evaluation grid."""
    if times[0] > grid[0] or times[-1] < grid[-1]:
        raise ValueError(
            f"Series window [{times[0]}, {times[-1]}] does not cover grid [{grid[0]}, {grid[-1]}]"
        )
    return np.column_stack([
        np.interp(grid, times, values[:, i]) for i in range(values.shape[1])
    ])


def compare_two_macro_series(
    baseline_curve: np.ndarray,
    candidate_curve: np.ndarray,
    grid: np.ndarray,
    scales: np.ndarray,
    budget_rel: float = 0.05,
) -> dict[str, Any]:
    """Compares candidate macro curve against baseline curve on uniform grid."""
    delta = candidate_curve - baseline_curve
    errors = np.abs(delta) / scales

    metrics: dict[str, Any] = {}
    for i, name in enumerate(OPERATORS):
        max_err = float(np.max(errors[:, i]))
        rms_err = float(np.sqrt(np.mean(errors[:, i] ** 2)))
        max_abs = float(np.max(np.abs(delta[:, i])))
        metrics[name] = {
            "scale": float(scales[i]),
            "max_scaled_error": max_err,
            "rms_scaled_error": rms_err,
            "max_absolute_difference": max_abs,
            "budget_pass": bool(max_err <= budget_rel),
        }

    # Time-mean kinetic energy error
    dt_integral = float(abs(np.trapezoid(delta[:, 4], grid))) if hasattr(np, "trapezoid") else float(abs(np.trapz(delta[:, 4], grid)))
    ke_time_mean_err = dt_integral / 12.0 / scales[4]
    metrics["kinetic_time_mean"] = {
        "scale": float(scales[4]),
        "scaled_error": float(ke_time_mean_err),
        "budget_pass": bool(ke_time_mean_err <= budget_rel),
    }

    # Peak kinetic energy error
    cand_peak = float(np.max(candidate_curve[:, 4]))
    base_peak = float(np.max(baseline_curve[:, 4]))
    ke_peak_err = abs(cand_peak - base_peak) / scales[4]
    metrics["kinetic_peak"] = {
        "scale": float(scales[4]),
        "scaled_error": float(ke_peak_err),
        "candidate_peak_j": cand_peak,
        "baseline_peak_j": base_peak,
        "budget_pass": bool(ke_peak_err <= budget_rel),
    }

    # Overall budget pass for this pair
    all_pass = all(m["budget_pass"] for m in metrics.values())

    return {
        "metrics": metrics,
        "macro_budget_pass": bool(all_pass),
    }


def compare_paddle_poses_to_analytic(
    poses: list[dict[str, float]],
    motion_dat_rows: list[list[float]] | None = None,
) -> dict[str, Any]:
    """Compares actual Type 1 marker pose path against analytic quintic and piecewise linear forcing."""
    times = [p["time_s"] for p in poses]
    actual_angles = [p["angle_deg"] for p in poses]

    analytic_angles = [evaluate_trajectory_analytic(t)[0] for t in times]
    errors_analytic = [abs(a - b) for a, b in zip(actual_angles, analytic_angles) if not math.isnan(a)]

    max_err_analytic = float(max(errors_analytic)) if errors_analytic else float("nan")
    rms_err_analytic = float(math.sqrt(np.mean(np.array(errors_analytic) ** 2))) if errors_analytic else float("nan")

    # Check neutral rest tail (t >= 8.0s)
    rest_errors = [
        abs(a) for t, a in zip(times, actual_angles) if t >= 8.0 and not math.isnan(a)
    ]
    max_rest_dev = float(max(rest_errors)) if rest_errors else float("nan")

    pwl_metrics: dict[str, Any] = {}
    if motion_dat_rows is not None and len(motion_dat_rows) > 1:
        dat_t = np.array([r[0] for r in motion_dat_rows])
        dat_a = np.array([r[1] for r in motion_dat_rows])
        pwl_angles = [evaluate_piecewise_linear_motion(dat_t, dat_a, t) for t in times]
        errors_pwl = [abs(a - b) for a, b in zip(actual_angles, pwl_angles) if not math.isnan(a)]
        pwl_metrics = {
            "max_abs_pwl_error_deg": float(max(errors_pwl)) if errors_pwl else float("nan"),
            "rms_pwl_error_deg": float(math.sqrt(np.mean(np.array(errors_pwl) ** 2))) if errors_pwl else float("nan"),
        }

    return {
        "max_abs_analytic_error_deg": max_err_analytic,
        "rms_analytic_error_deg": rms_err_analytic,
        "max_neutral_rest_tail_deviation_deg": max_rest_dev,
        "rest_tail_held": bool(max_rest_dev < 0.1) if not math.isnan(max_rest_dev) else False,
        **pwl_metrics,
    }


# -----------------------------------------------------------------------------
# Main Worker Orchestration
# -----------------------------------------------------------------------------

def run_three_dp_worker(
    binding_path: Path,
    output_path: Path,
    pre_extracted_data: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Executes the three-DP all-pairs frozen macro and moving pose worker.

    Args:
        binding_path: Path to input binding.json
        output_path: Path to output review JSON
        pre_extracted_data: Optional pre-extracted macro series dictionary for testing/simulation.
    """
    if output_path.exists():
        raise FileExistsError(f"Output file already exists: {output_path}")

    binding_sha = sha256_file(binding_path)
    with open(binding_path, "r") as f:
        binding = json.load(f)

    # Validate normalizers and budgets
    normalizers_path = Path(binding["normalizers"])
    normalizers_sha = sha256_file(normalizers_path)
    with open(normalizers_path, "r") as f:
        normalizers = json.load(f)

    budget_path = Path(binding["budget"])
    budget_sha = sha256_file(budget_path)
    with open(budget_path, "r") as f:
        budget = json.load(f)

    # Uniform evaluation grid: 0..12s, dt = 0.02s, 601 points
    grid = np.linspace(0.0, 12.0, 601)

    # Load motion .dat if available
    motion_dat_rows: list[list[float]] | None = None
    if "motion_dat" in binding and Path(binding["motion_dat"]).is_file():
        motion_dat_text = Path(binding["motion_dat"]).read_text()
        motion_dat_rows = [
            list(map(float, line.split()))
            for line in motion_dat_text.splitlines()
            if line.strip() and not line.startswith("#")
        ]

    # Resolutions: coarse, medium, fine
    roles = ["coarse", "medium", "fine"]
    loaded_data: dict[str, Any] = {}
    sampled_curves: dict[str, np.ndarray] = {}

    for role in roles:
        if role not in binding["cases"]:
            raise KeyError(f"Binding missing case for resolution: {role}")
        case_info = binding["cases"][role]

        if pre_extracted_data is not None and role in pre_extracted_data:
            data = pre_extracted_data[role]
        else:
            # Source-only check: verify typed H5 exists before extracting
            traj_h5 = Path(case_info["trajectory_h5"])
            if not traj_h5.is_file():
                raise FileNotFoundError(
                    f"Typed trajectory H5 not found for {role}: {traj_h5}. "
                    "Compute must be executed by Root guarded runner before audit."
                )
            data = extract_macros_from_typed_h5(traj_h5)

        # Check physical mother identity
        phys_hash = data.get("physical_condition_sha256", "")
        if phys_hash and phys_hash != PHYSICAL_CONDITION_SHA256:
            raise ValueError(
                f"Physical condition SHA256 mismatch for {role}: {phys_hash} vs {PHYSICAL_CONDITION_SHA256}"
            )

        times = np.asarray(data["time_s"], dtype=float)
        values = np.asarray(data["values"], dtype=float)
        curve = interpolate_series_to_grid(times, values, grid)

        loaded_data[role] = data
        sampled_curves[role] = curve

    # Establish KE normalization scale from Fine reference or original scale reference
    if "original_scale_reference" in binding and Path(binding["original_scale_reference"]).is_file():
        ref_data = json.loads(Path(binding["original_scale_reference"]).read_text())
        ref_times = np.asarray(ref_data["time_s"], dtype=float)
        ref_values = np.asarray(ref_data["values"], dtype=float)
        ref_curve = interpolate_series_to_grid(ref_times, ref_values, grid)
        ke_scale = float(np.max(ref_curve[:, 4]))
    else:
        # Fallback to fine resolution peak kinetic energy
        ke_scale = float(np.max(sampled_curves["fine"][:, 4]))

    scales = np.array([
        normalizers["continuous_initial_mass_kg"],
        *normalizers["com_axis_scales_m"],
        ke_scale,
    ])
    if not np.isfinite(scales).all() or np.any(scales <= 0):
        raise ValueError(f"Invalid reference normalization scales: {scales}")

    macro_budget_rel = float(normalizers.get("macro_relative_budget", 0.05))

    # All-pairs comparisons across three DPs
    # Pair 1: coarse vs medium
    # Pair 2: medium vs fine
    # Pair 3: coarse vs fine
    pairs = [
        ("coarse_vs_medium", "coarse", "medium"),
        ("medium_vs_fine", "medium", "fine"),
        ("coarse_vs_fine", "coarse", "fine"),
    ]
    pairwise_results: dict[str, Any] = {}
    all_pairs_budget_pass = True

    for pair_name, base_role, cand_role in pairs:
        pair_comp = compare_two_macro_series(
            sampled_curves[base_role],
            sampled_curves[cand_role],
            grid,
            scales,
            budget_rel=macro_budget_rel,
        )
        pairwise_results[pair_name] = {
            "baseline_role": base_role,
            "candidate_role": cand_role,
            "baseline_case_id": binding["cases"][base_role]["case_id"],
            "candidate_case_id": binding["cases"][cand_role]["case_id"],
            **pair_comp,
        }
        if not pair_comp["macro_budget_pass"]:
            all_pairs_budget_pass = False

    # Moving paddle Type 1 pose path evaluations
    pose_results: dict[str, Any] = {}
    for role in roles:
        if "moving_paddle_poses" in loaded_data[role]:
            pose_results[role] = compare_paddle_poses_to_analytic(
                loaded_data[role]["moving_paddle_poses"],
                motion_dat_rows=motion_dat_rows,
            )
        else:
            pose_results[role] = {
                "status": "poses_not_available_in_source",
            }

    # Summary of particle exclusions
    exclusions_summary: dict[str, Any] = {}
    for role in roles:
        excl_list = loaded_data[role].get("exclusions", [])
        total_excl = max([e.get("excluded_count", 0) for e in excl_list]) if excl_list else 0
        total_excl_mass = max([e.get("excluded_mass_kg", 0.0) for e in excl_list]) if excl_list else 0.0
        exclusions_summary[role] = {
            "max_excluded_particles": total_excl,
            "max_excluded_mass_kg": total_excl_mass,
            "native_exclusions_retained_as_unknown": True,
        }

    result = {
        "schema": "ds02.f7.three-dp-frozen-macro-review.v1",
        "binding_path": str(binding_path),
        "binding_sha256": binding_sha,
        "physical_condition_sha256": PHYSICAL_CONDITION_SHA256,
        "window_s": [0.0, 12.0],
        "grid_step_s": 0.02,
        "grid_points": len(grid),
        "normalizers": {
            **normalizers,
            "kinetic_energy_scale_j": ke_scale,
            "normalizers_sha256": normalizers_sha,
        },
        "budget": {
            **budget,
            "budget_sha256": budget_sha,
        },
        "refinement_boundary": {
            "dp_values_m": {"coarse": 0.02, "medium": 0.016, "fine": 0.01},
            "refinement_ratios": {
                "coarse_to_medium": 1.25,
                "medium_to_fine": 1.60,
                "coarse_to_fine": 2.00,
            },
            "constant_refinement_ratio_claim": False,
            "constant_refinement_ratio_rationale": "Refinement ratio varies (1.25 != 1.60); no uniform grid ratio claim.",
            "uid_match_across_dp": False,
            "uid_match_rationale": "Independent GenCase node distributions; particle UIDs do not map across resolutions.",
        },
        "motion_forcing": {
            "analytic_target": "Two 45 deg quintic cycles active 0..8s, neutral rest tail 8..12s",
            "solver_reader": "DualSPHysics JMotionMovActive::DfGetNewAng",
            "solver_interpolation": "Piecewise linear with finite knot slope jumps; NOT native C2",
            "native_c2_claim": False,
        },
        "moving_paddle_pose_analysis": pose_results,
        "pairwise_macro_comparisons": pairwise_results,
        "overall_macro_budget_pass": all_pairs_budget_pass,
        "exclusions_accounting": {
            "lifecycle_mode": "FINITE_INITIAL_NUMERICAL_COHORT_WITH_EXCLUSIONS",
            "policy": "native_unknown_exclusions_retained",
            "closed_cohort_assumed": False,
            "by_resolution": exclusions_summary,
        },
        "governance_and_explicit_gaps": {
            "q_n_status": "not_granted",
            "production_approval": "none",
            "residence_specific_registered_budget": None,
            "residence_gap_declaration": "Residence budget not registered; unnormalised seconds and kg*s reported with no qualification claim.",
            "three_dp_macros_qualification_boundary": "ThreeDP macros alone do not grant whole Q-N; independent time/save and motion cadence/protocol sensitivity still required.",
            "historical_spatial_ke_negative_evidence": "Historical ~43% spatial KE discrepancy from previous kinematics is retained; 5% budget failure gate preserved.",
            "actual_numbers_pending": "Full qualification requires complete typed trajectories executed under Root guarded compute.",
        },
    }

    with output_path.open("x") as f:
        json.dump(result, f, indent=2)
        f.write("\n")

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, required=True, help="Path to input binding.json")
    parser.add_argument("--output", type=Path, required=True, help="Path to output review JSON")
    args = parser.parse_args()

    result = run_three_dp_worker(args.binding, args.output)
    print(json.dumps({
        "output": str(args.output),
        "overall_macro_budget_pass": result["overall_macro_budget_pass"],
        "q_n_status": result["governance_and_explicit_gaps"]["q_n_status"],
        "production_approval": result["governance_and_explicit_gaps"]["production_approval"],
    }))


if __name__ == "__main__":
    main()
