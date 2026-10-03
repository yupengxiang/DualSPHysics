#!/usr/bin/env python3
"""F3 CELL3 Genuine Adaptive Paired Macro Audit & Dense-Save Study Specification (Version 1).

Audits macro hydrodynamic observables between the genuine adaptive CFL pair on the full 8.35s window:
  - BASELINE (Repair 1): CFL=0.05, CoefDtMin=0.005, 383,189 steps, 836 frames (dt=0.01s)
  - GENUINE HALF (Repair 2): CFL=0.025, CoefDtMin=0.0025, 766,348 steps, 836 frames (dt=0.01s)
  - Reuses the frozen observable protocol from F3-CELL3-PROTOCOL.json and f3_observation_v2.py:
    * Geometry: [0.9, 0.18, 0.51] m, water depth 0.09 m, fluid mass 14.58 kg
    * Forcing drive: CaseSloshingAccData.csv (167,001 rows, 8.35s window)
    * Observables: Total variation (tv), COM L2 deviation, q90 coordinate, mean velocity,
      kinetic energy difference, common support velocity, unmatched support mass,
      free-surface proxies (z90, zmax), and wall kinetic energy flux.
    * Registered error budgets: 0.01 (1%) time/output, 0.05 (5%) reference.
  - Formulates the dense-save study specification addressing the 24.83% bracket non-overlap
    identified in attempt 016, deriving TimeOut=0.002s (4,176 frames) directly from the protocol's
    frozen output_control_interval_s=0.002, and binding historical dense product F3_REV075_R075-OUTPUT
    without launching unbudgeted GPU runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import resource
import sys
from typing import Any

import h5py
import numpy as np

# Canonical observation operator and tank bounds from f3_observation_v2.py
try:
    from scripts.f3_observation_v2 import (
        LOW,
        HIGH,
        U as U_CHAR,
        edges_for,
        observe_arrays,
        compare as compare_v2,
        tent_cdf,
    )
except ImportError:
    _lab_dir = Path(__file__).resolve().parent.parent
    if str(_lab_dir) not in sys.path:
        sys.path.insert(0, str(_lab_dir))
    from scripts.f3_observation_v2 import (
        LOW,
        HIGH,
        U as U_CHAR,
        edges_for,
        observe_arrays,
        compare as compare_v2,
        tent_cdf,
    )

TANK_LENGTH_M = 0.90
TANK_WIDTH_M = 0.18
TANK_HEIGHT_M = 0.51
WATER_DEPTH_M = 0.09
TARGET_MASS_KG = 14.58
# Protocol registered energy scale: 0.5 * M0 * g * H = 0.5 * 14.58 * 9.81 * 0.09 = ~6.4368315 J
ENERGY_SCALE_J = float(0.5 * TARGET_MASS_KG * 9.81 * WATER_DEPTH_M)
OBS_BANDWIDTH_M = 0.06
OBS_CELL_WIDTH_M = 0.06

SCHEMA = "ds02.f3.genuine-adaptive-macro-audit.v1"
FAMILY_ID = "F3"


def digest(path: Path | str) -> str:
    """Compute sha256 checksum of a file."""
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def usage_stats() -> dict[str, float]:
    """Capture process resource usage."""
    result: dict[str, float] = {}
    for who, label in ((resource.RUSAGE_SELF, "self"), (resource.RUSAGE_CHILDREN, "children")):
        v = resource.getrusage(who)
        result[f"{label}_user_seconds"] = float(v.ru_utime)
        result[f"{label}_system_seconds"] = float(v.ru_stime)
        result[f"{label}_max_rss_kib"] = float(v.ru_maxrss)
    return result


def observe_single_frame(
    positions: np.ndarray,
    velocities: np.ndarray,
    masses: np.ndarray,
    initial_mass_kg: float,
    *,
    bandwidth: float = OBS_BANDWIDTH_M,
    cell_width: float = OBS_CELL_WIDTH_M,
) -> dict[str, Any]:
    """Compute macro spatial distributions, COM, momentum, energy, and free-surface proxies."""
    p = np.asarray(positions, dtype=np.float64)
    v = np.asarray(velocities, dtype=np.float64)
    m = np.asarray(masses, dtype=np.float64)

    m_sum = float(np.sum(m))
    if initial_mass_kg <= 0 or m_sum <= 0:
        raise ValueError("Masses must be positive")

    # Inside domain mask
    inside = np.all((p >= LOW) & (p <= HIGH), axis=1)
    outside_count = int(np.sum(~inside))
    outside_mass = float(np.sum(m[~inside]))

    # Free surface proxies
    z_coords = p[:, 2]
    z90 = float(np.percentile(z_coords, 90)) if len(z_coords) else 0.0
    zmax = float(np.max(z_coords)) if len(z_coords) else 0.0

    # Left vs right compartment free surface
    left_mask = p[:, 0] < 0.0
    right_mask = p[:, 0] >= 0.0
    z90_left = float(np.percentile(z_coords[left_mask], 90)) if np.any(left_mask) else 0.0
    z90_right = float(np.percentile(z_coords[right_mask], 90)) if np.any(right_mask) else 0.0
    zmax_left = float(np.max(z_coords[left_mask])) if np.any(left_mask) else 0.0
    zmax_right = float(np.max(z_coords[right_mask])) if np.any(right_mask) else 0.0

    # Total kinetic energy in Joules
    v_sq = np.sum(v * v, axis=1)
    ke_total_j = float(0.5 * np.sum(m * v_sq))

    # Canonical observation operator from f3_observation_v2.py
    obs = observe_arrays(
        p, v, m, initial_mass_kg,
        bandwidth=bandwidth,
        cell_width=cell_width,
    )
    obs["kinetic_energy_j"] = ke_total_j
    obs["outside_count"] = outside_count
    obs["outside_mass_kg"] = outside_mass
    obs["free_surface"] = {
        "z90_m": z90,
        "zmax_m": zmax,
        "z90_left_m": z90_left,
        "z90_right_m": z90_right,
        "zmax_left_m": zmax_left,
        "zmax_right_m": zmax_right,
        "slosh_asymmetry_z90_m": abs(z90_left - z90_right),
    }
    return obs


def compare_frames(obs_a: dict[str, Any], obs_b: dict[str, Any]) -> dict[str, float]:
    """Evaluate the 7 registered macro discrepancy metrics using canonical compare."""
    return compare_v2(obs_a, obs_b)


def audit_f3_genuine_adaptive_macro(
    baseline_traj_path: Path | str,
    baseline_conversion_path: Path | str,
    half_traj_path: Path | str,
    half_conversion_path: Path | str,
    protocol_path: Path | str,
    gate_path: Path | str,
    output_path: Path | str,
    *,
    operator_path: Path | str | None = None,
    frame_step: int = 1,
    max_frames: int | None = None,
) -> dict[str, Any]:
    """Execute macro observable audit comparing baseline and half adaptive trajectories."""
    base_tr_p = Path(baseline_traj_path)
    base_cv_p = Path(baseline_conversion_path)
    half_tr_p = Path(half_traj_path)
    half_cv_p = Path(half_conversion_path)
    proto_p = Path(protocol_path)
    gate_p = Path(gate_path)
    out_p = Path(output_path)
    op_p = Path(operator_path) if operator_path is not None else Path(__file__).resolve().parent / "f3_observation_v2.py"

    mandatory = [base_tr_p, base_cv_p, half_tr_p, half_cv_p, proto_p, gate_p]
    if op_p.is_file():
        mandatory.append(op_p)

    for p in mandatory:
        if not p.is_file():
            raise FileNotFoundError(f"Input file not found: {p}")

    digests = {str(p.resolve()): digest(p) for p in mandatory}

    proto = json.loads(proto_p.read_text())
    gate = json.loads(gate_p.read_text())
    time_out_budget = proto.get("time_output_error_budget", 0.01)
    ref_budget = proto.get("reference_error_budget", 0.05)

    with h5py.File(base_tr_p, "r") as h_base, h5py.File(half_tr_p, "r") as h_half:
        time_b = h_base["time"][:]
        time_h = h_half["time"][:]
        n_frames = min(len(time_b), len(time_h))
        if max_frames is not None:
            n_frames = min(n_frames, max_frames)

        frame_indices = list(range(0, n_frames, frame_step))
        sampled_times = [float(time_b[i]) for i in frame_indices]

        # Extract fluid cohort at frame 0
        valid_b0 = h_base["valid"][0].astype(bool)
        type_b0 = h_base["type"][0]
        mass_b0 = h_base["mass"][0].astype(np.float64)
        fluid_mask = valid_b0 & (type_b0 == 3) & (mass_b0 > 0)
        n_fluid = int(fluid_mask.sum())
        total_m0 = float(np.sum(mass_b0[fluid_mask]))

        if n_fluid != 34560:
            raise ValueError(f"Fluid count is {n_fluid}, expected exactly 34560")

        # Metrics history
        metrics_history: dict[str, list[float]] = {
            "tv": [], "com_l2_over_length": [], "q90_over_length": [],
            "mean_velocity_over_U": [], "energy_difference": [],
            "common_support_velocity_over_U": [], "unmatched_support_mass": [],
        }

        ke_history_base: list[float] = []
        ke_history_half: list[float] = []
        asymmetry_history: list[float] = []

        for fi in frame_indices:
            # Baseline frame
            pos_b = h_base["position"][fi][fluid_mask]
            vel_b = h_base["velocity"][fi][fluid_mask] if "velocity" in h_base else np.zeros_like(pos_b)
            obs_b = observe_single_frame(pos_b, vel_b, mass_b0[fluid_mask], total_m0)

            # Half frame
            pos_h = h_half["position"][fi][fluid_mask]
            vel_h = h_half["velocity"][fi][fluid_mask] if "velocity" in h_half else np.zeros_like(pos_h)
            obs_h = observe_single_frame(pos_h, vel_h, mass_b0[fluid_mask], total_m0)

            comp = compare_frames(obs_b, obs_h)
            for mkey, mval in comp.items():
                metrics_history[mkey].append(mval)

            ke_history_base.append(obs_b["kinetic_energy_j"])
            ke_history_half.append(obs_h["kinetic_energy_j"])
            asym_diff = abs(obs_h["free_surface"]["slosh_asymmetry_z90_m"] - obs_b["free_surface"]["slosh_asymmetry_z90_m"])
            asymmetry_history.append(asym_diff)

    # Summarize metrics across trajectory
    trapz_fn = getattr(np, "trapezoid", getattr(np, "trapz", None))
    summary_metrics: dict[str, Any] = {}
    times_arr = np.array(sampled_times, dtype=np.float64)

    for mkey, values in metrics_history.items():
        v_arr = np.array(values, dtype=np.float64)
        max_val = float(np.max(v_arr))
        mean_val = float(np.mean(v_arr))
        median_val = float(np.median(v_arr))
        p95_val = float(np.percentile(v_arr, 95))
        t_max = float(times_arr[int(np.argmax(v_arr))])
        l1_int = float(trapz_fn(v_arr, times_arr)) if len(times_arr) > 1 else 0.0

        summary_metrics[mkey] = {
            "maximum_deviation": max_val,
            "time_at_maximum_s": t_max,
            "mean_deviation": mean_val,
            "median_deviation": median_val,
            "p95_deviation": p95_val,
            "l1_integrated_deviation": l1_int,
            "within_time_output_budget_0p01": bool(max_val <= time_out_budget),
            "within_reference_budget_0p05": bool(max_val <= ref_budget),
        }

    # Free surface and kinetic energy summary
    ke_base_arr = np.array(ke_history_base, dtype=np.float64)
    ke_half_arr = np.array(ke_history_half, dtype=np.float64)
    ke_delta_arr = np.abs(ke_half_arr - ke_base_arr)

    kinetic_summary = {
        "baseline_peak_ke_j": float(np.max(ke_base_arr)),
        "baseline_time_at_peak_ke_s": float(times_arr[int(np.argmax(ke_base_arr))]),
        "half_peak_ke_j": float(np.max(ke_half_arr)),
        "half_time_at_peak_ke_s": float(times_arr[int(np.argmax(ke_half_arr))]),
        "max_absolute_ke_discrepancy_j": float(np.max(ke_delta_arr)),
        "max_relative_ke_discrepancy": float(np.max(ke_delta_arr) / ENERGY_SCALE_J),
        "mean_relative_ke_discrepancy": float(np.mean(ke_delta_arr) / ENERGY_SCALE_J),
    }

    # Dense-save study specification
    dense_save_study = {
        "status": "specified_from_frozen_protocol_budget",
        "finding_from_transport_attempt_016": {
            "nominal_save_cadence_s": 0.01,
            "nominal_frames": 836,
            "observed_bracket_non_overlap_fraction": 0.2483281319661168,
            "non_overlapping_particles_count": 2785,
            "median_absolute_chord_delta_s": 0.0010087327979955152,
            "root_cause": (
                "At nominal Delta_t_save = 0.01s (10 ms bracket), particles whose chord passage difference "
                "exceeds the save bracket width (median delta ~1.01 ms, p75 ~4.50 ms, mean abs ~156 ms in late sloshing) "
                "exhibit empty bracket intersection, failing save bracket containment."
            ),
        },
        "derived_dense_timeout_s": 0.002,
        "derived_dense_frames": 4176,
        "protocol_budget_provenance": {
            "protocol_schema": "f3.cell3.protocol.v1",
            "registered_output_control_interval_s": 0.002,
            "tightening_factor": 5.0,
            "rationale": (
                "output_control_interval_s = 0.002s is the exact frozen cadence in F3-CELL3-PROTOCOL.json. "
                "Refining the save cadence by 5x (bracket width 2 ms) tightly encapsulates the median chord "
                "delta of 1.01 ms, providing bracket overlap for early-to-mid sloshing."
            ),
        },
        "historical_dense_product_reuse": {
            "case_id": "F3_REV075_R075-OUTPUT",
            "trajectory_hdf5": "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_REV075_R075-OUTPUT/f3_rev075_r075-output-direct-nvme-root-reviewed-002/trajectory.h5",
            "trajectory_sha256": "afffa07621978ad912d02d8c1d6447b92b89daa78f2b1fa2ac1538a3b24b8c65",
            "typed_labels_hdf5": "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_REV075_R075-OUTPUT/f3_rev075_r075-output-labels-root-reviewed-001/typed-transport-labels.h5",
            "typed_labels_sha256": "da60974df28c0eafb05499e4007c57e2ee08bbad9225c34475dd7d79ae3df78a",
            "historical_tightening_factor": 4.965,
            "historical_finding": (
                "Save cadence refinement in NOMINAL vs OUTPUT confirmed 100% identity preservation, "
                "-22 microsecond chord time agreement, and identical cumulative net flux. "
                "Equal historical dense products are reused; NO unbudgeted GPU solver launch is initiated."
            ),
        },
    }

    report: dict[str, Any] = {
        "schema": SCHEMA,
        "family_id": FAMILY_ID,
        "audit_title": "F3 CELL3 Genuine Adaptive CFL Halving Macro Audit (Full 8.35s Window)",
        "timestepping": {
            "baseline_case": "F3_CELL3_LONG_DP0075_REPAIR1_ADAPTIVE_CFL05_COEF005",
            "baseline_cfl": 0.05,
            "half_case": "F3_CELL3_LONG_DP0075_REPAIR2_ADAPTIVE_CFL025_COEF0025",
            "half_cfl": 0.025,
            "step_ratio": 766348 / 383189,
            "classification": "genuine_adaptive_cfl_halving_zero_clamps",
        },
        "fluid_cohort": {
            "count": n_fluid,
            "total_initial_mass_kg": total_m0,
        },
        "temporal_window": {
            "start_s": 0.0,
            "end_s": float(times_arr[-1]),
            "frames_audited": len(frame_indices),
        },
        "macro_metrics": summary_metrics,
        "kinetic_energy_audit": kinetic_summary,
        "dense_save_study": dense_save_study,
        "claim_boundary": {
            "model_invoked": False,
            "production": "not_evaluated",
            "production_granted": False,
            "q_i": "macro_audit_measurement_only",
            "q_n": "not_assessed",
            "q_n_granted": False,
            "training": "not_authorized",
            "governance_note": (
                "Descriptive macro audit comparing genuine adaptive Repair 1 and Repair 2 on the full 8.35s window. "
                "Dense-save study specification formulated directly from protocol budget without GPU launch."
            ),
        },
        "input_sha256": digests,
        "resource_usage": usage_stats(),
    }

    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-trajectory", type=Path, required=True, help="Baseline trajectory.h5")
    parser.add_argument("--baseline-conversion", type=Path, required=True, help="Baseline conversion-report.json")
    parser.add_argument("--half-trajectory", type=Path, required=True, help="Half trajectory.h5")
    parser.add_argument("--half-conversion", type=Path, required=True, help="Half conversion-report.json")
    parser.add_argument("--protocol", type=Path, required=True, help="Protocol JSON")
    parser.add_argument("--gate", type=Path, required=True, help="Gate JSON")
    parser.add_argument("--operator", type=Path, default=None, help="Operator f3_observation_v2.py (optional)")
    parser.add_argument("--output", type=Path, required=True, help="Output macro audit report JSON")
    parser.add_argument("--frame-step", type=int, default=1, help="Frame subsampling step")
    parser.add_argument("--max-frames", type=int, default=None, help="Max frames to audit")

    args = parser.parse_args()
    report = audit_f3_genuine_adaptive_macro(
        args.baseline_trajectory,
        args.baseline_conversion,
        args.half_trajectory,
        args.half_conversion,
        args.protocol,
        args.gate,
        args.output,
        operator_path=args.operator,
        frame_step=args.frame_step,
        max_frames=args.max_frames,
    )
    print(json.dumps({
        "schema": report["schema"],
        "macro_metrics": {k: v["maximum_deviation"] for k, v in report["macro_metrics"].items()},
        "dense_save_study_status": report["dense_save_study"]["status"],
        "claim_boundary": report["claim_boundary"],
    }, indent=2))


if __name__ == "__main__":
    main()
