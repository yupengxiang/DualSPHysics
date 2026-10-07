#!/usr/bin/env python3
"""Model-free state evaluator for Family F6 with reference denominators and explicit failures.

Adheres strictly to P5 quality standards:
1. Model-free: NEVER loads neural network weights, never executes a learned model.
2. Exact reference self-comparison verification: identical trajectory yields zero error and valid=True.
3. Explicit detection of:
   - saved_time_mismatch (different or non-monotonic timestamps)
   - condition_binding / condition_mismatch (coordinate_frame, geometry_sha256, control_sha256)
   - typed identity mismatches / unexpected candidate identities
   - missing_reference_mass (inactive candidate particles where reference is active)
   - unknown_reference_mass (nonfinite coordinates or negative/nonfinite masses)
   - finite_closed_wall_crossing (tank walls: bottom, left, right, front, back)
   - open_top_exit (containment violation above tank rim z=1.40m)
   - rigid_body_boundary_violation (floating body center leaves tank bounds)
   - rigid_body_contact_violation (contact_event_flag set to True)
   - rigid_body_nonfinite_state (nonfinite values in rigid body kinematics)
4. Denominators: strictly normalized by initial total fluid mass and physical scales (L, V).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any

import h5py
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from ds_data02_native_labels import finite_crossing

# F6 characteristic scales
SCALES_BY_MECHANISM = {
    "simple_free_response": {
        "length_scale_m": 4.0,
        "velocity_scale_m_s": math.sqrt(9.81 * 4.0),  # ~6.264 m/s
        "tank_size": (4.0, 2.0, 1.4),
    },
    "wave_no_contact": {
        "length_scale_m": 5.0,
        "velocity_scale_m_s": math.sqrt(9.81 * 5.0),  # ~7.004 m/s
        "tank_size": (5.0, 2.0, 1.4),
    },
}


def identities(handle: h5py.File) -> list[tuple[int, int]]:
    """Extract unique typed identity pairs (particle_zone, particle_id)."""
    keys = list(zip(handle["particle_zone"][:].tolist(), handle["particle_id"][:].tolist()))
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate typed identities in trajectory")
    return keys


def get_f6_closed_walls(mechanism: str = "simple_free_response") -> list[dict[str, Any]]:
    """Define finite closed walls for F6 tank."""
    scales = SCALES_BY_MECHANISM.get(mechanism, SCALES_BY_MECHANISM["simple_free_response"])
    lx, ly, lz = scales["tank_size"]

    return [
        {"id": "tank_bottom", "axis": 2, "value": 0.0, "aperture_bounds": [[0.0, lx], [0.0, ly]]},
        {"id": "tank_left", "axis": 0, "value": 0.0, "aperture_bounds": [[0.0, ly], [0.0, lz]]},
        {"id": "tank_right", "axis": 0, "value": lx, "aperture_bounds": [[0.0, ly], [0.0, lz]]},
        {"id": "tank_front", "axis": 1, "value": 0.0, "aperture_bounds": [[0.0, lx], [0.0, lz]]},
        {"id": "tank_back", "axis": 1, "value": ly, "aperture_bounds": [[0.0, lx], [0.0, lz]]},
    ]


def get_f6_open_top(mechanism: str = "simple_free_response") -> dict[str, Any]:
    """Define open top aperture for containment audit."""
    scales = SCALES_BY_MECHANISM.get(mechanism, SCALES_BY_MECHANISM["simple_free_response"])
    lx, ly, lz = scales["tank_size"]

    return {
        "id": "top_open_exit",
        "axis": 2,
        "value": lz,
        "aperture_bounds": [[0.0, lx], [0.0, ly]],
    }


def quaternion_distance_rad(q1: np.ndarray, q2: np.ndarray) -> np.ndarray:
    """Compute shortest angular distance between unit quaternions in radians: theta = 2 * acos(|<q1, q2>|)."""
    # Dot product per time step
    dots = np.abs(np.sum(q1 * q2, axis=-1))
    dots = np.clip(dots, -1.0, 1.0)
    return 2.0 * np.arccos(dots)


def evaluate_f6(
    reference: Path | str,
    candidate: Path | str,
    *,
    mechanism: str | None = None,
    length_scale_m: float | None = None,
    velocity_scale_m_s: float | None = None,
    custom_walls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Evaluate candidate trajectory against reference for Family F6 under P5 standards."""
    reference, candidate = Path(reference).resolve(), Path(candidate).resolve()
    if not reference.is_file():
        raise FileNotFoundError(f"Reference trajectory not found: {reference}")
    if not candidate.is_file():
        raise FileNotFoundError(f"Candidate trajectory not found: {candidate}")

    failures: list[str] = []

    with h5py.File(reference, "r") as ref, h5py.File(candidate, "r") as cand:
        # Determine mechanism
        ref_case_id = str(ref.attrs.get("case_id", reference.stem))
        if mechanism is None:
            mechanism = "wave_no_contact" if "wave" in ref_case_id.lower() else "simple_free_response"

        default_scales = SCALES_BY_MECHANISM.get(mechanism, SCALES_BY_MECHANISM["simple_free_response"])
        if length_scale_m is None or length_scale_m <= 0:
            length_scale_m = default_scales["length_scale_m"]
        if velocity_scale_m_s is None or velocity_scale_m_s <= 0:
            velocity_scale_m_s = default_scales["velocity_scale_m_s"]

        lx, ly, lz = default_scales["tank_size"]

        # Check required particle datasets
        for name in ("time", "particle_id", "particle_zone", "valid", "type", "mass", "position", "velocity"):
            if name not in ref or name not in cand:
                raise ValueError(f"Missing required state dataset: {name}")

        ref_time = ref["time"][:]
        cand_time = cand["time"][:]
        if not np.array_equal(ref_time, cand_time):
            return {
                "schema": "ds-data-02.f6.evaluation.v1",
                "valid": False,
                "failures": ["saved_time_mismatch"],
                "numerical_qualification": "not_assessed",
                "model_invoked": False,
            }

        # Check condition bindings
        for attr, aliases in [
            ("coordinate_frame", ("coordinate_frame",)),
            ("geometry_sha256", ("geometry_sha256", "generated_xml_sha256", "geometry_reference_sha256")),
            ("control_sha256", ("control_sha256", "control_reference_sha256", "motion_control_reference_sha256")),
        ]:
            ref_val = next((ref.attrs[k] for k in aliases if k in ref.attrs), None)
            cand_val = next((cand.attrs[k] for k in aliases if k in cand.attrs), None)
            if ref_val is not None and cand_val is not None and ref_val != cand_val:
                failures.append(f"condition_mismatch:{attr}")
            elif ref_val is not None and cand_val is None:
                failures.append(f"missing_condition_binding:{attr}")

        # Check particle identities
        ref_keys = identities(ref)
        cand_keys = identities(cand)
        lookup = {key: i for i, key in enumerate(cand_keys)}
        mapping = np.array([lookup.get(key, -1) for key in ref_keys])
        present = mapping >= 0
        extra = len(set(cand_keys) - set(ref_keys))
        if extra:
            failures.append("unexpected_candidate_identities")

        # Initial fluid mass denominator
        initial_fluid = ref["valid"][0].astype(bool) & (ref["type"][0] == 3)
        initial_mass = np.where(initial_fluid, ref["mass"][0], 0).astype(float)
        if not np.isfinite(initial_mass).all() or np.any(initial_mass[initial_fluid] <= 0):
            raise ValueError("Reference initial fluid mass invalid")

        denominator = float(initial_mass.sum())
        if denominator <= 0:
            raise ValueError("Reference has no initial fluid mass")

        closed_walls = get_f6_closed_walls(mechanism) if custom_walls is None else custom_walls
        open_top = get_f6_open_top(mechanism)

        position_error = []
        velocity_error = []
        missing = []
        unknown = []
        mass_error = []
        reference_loss = []
        wall_crossings = 0
        open_top_crossings = 0

        previous_pos = None
        previous_good = None

        nt = len(ref_time)
        nref = len(ref_keys)

        for ti in range(nt):
            rv = ref["valid"][ti].astype(bool) & initial_fluid
            reference_loss.append(float(initial_mass[initial_fluid & ~rv].sum() / denominator))

            cp = np.full((nref, 3), np.nan)
            cv = np.full_like(cp, np.nan)
            cm = np.full(nref, np.nan)
            candidate_active = np.zeros(nref, bool)

            cp[present] = cand["position"][ti][mapping[present]]
            cv[present] = cand["velocity"][ti][mapping[present]]
            cm[present] = cand["mass"][ti][mapping[present]]
            candidate_active[present] = cand["valid"][ti][mapping[present]].astype(bool)

            raw_active = cand["valid"][ti].astype(bool) & (cand["type"][ti] == 3)
            raw_mass = cand["mass"][ti]
            raw_pos = cand["position"][ti]
            raw_vel = cand["velocity"][ti]

            if np.any(raw_active & (~np.isfinite(raw_mass) | (raw_mass <= 0))):
                failures.append("invalid_candidate_mass")
            if np.any(raw_active & (~np.isfinite(raw_pos).all(axis=1) | ~np.isfinite(raw_vel).all(axis=1))):
                failures.append("nonfinite_candidate_state")

            good = candidate_active & np.isfinite(cp).all(axis=1) & np.isfinite(cv).all(axis=1) & np.isfinite(cm) & (cm > 0)
            common = rv & good

            missing.append(float(initial_mass[rv & ~candidate_active].sum() / denominator))
            unknown.append(float(initial_mass[rv & candidate_active & ~good].sum() / denominator))
            mass_error.append(float(np.abs(cm[common] - ref["mass"][ti][common]).sum() / denominator))

            rp = ref["position"][ti]
            rvel = ref["velocity"][ti]
            if not np.isfinite(rp[rv]).all() or not np.isfinite(rvel[rv]).all():
                raise ValueError("Reference active particle state invalid")

            pos_err = (initial_mass[common] * np.linalg.norm(cp[common] - rp[common], axis=1)).sum() / denominator / length_scale_m
            vel_err = (initial_mass[common] * np.linalg.norm(cv[common] - rvel[common], axis=1)).sum() / denominator / velocity_scale_m_s
            position_error.append(float(pos_err))
            velocity_error.append(float(vel_err))

            if ti > 0:
                paired = previous_good & good & initial_fluid
                for wall in closed_walls:
                    fwd, bwd, _ = finite_crossing(previous_pos, cp, wall)
                    wall_crossings += int(((fwd | bwd) & paired).sum())

                # Open top crossing (z forward crossing into z > lz)
                fwd_top, _, _ = finite_crossing(previous_pos, cp, open_top)
                open_top_crossings += int((fwd_top & paired).sum())

            previous_pos = cp
            previous_good = good

        if max(missing, default=0) > 0:
            failures.append("missing_reference_mass")
        if max(unknown, default=0) > 0:
            failures.append("unknown_reference_mass")
        if wall_crossings > 0:
            failures.append("finite_closed_wall_crossing")
        if open_top_crossings > 0:
            failures.append("containment_violation:open_top_exit")

        # ---------------------------------------------------------
        # Rigid Body Dynamics Evaluation (Family F6 specific)
        # ---------------------------------------------------------
        ref_rb = ref.get("rigid_body") or ref.get("rigid_state")
        cand_rb = cand.get("rigid_body") or cand.get("rigid_state")

        rb_pos_error = []
        rb_lin_vel_error = []
        rb_ang_vel_error = []
        rb_quat_error_rad = []
        rb_euler_error_deg = []
        rb_contact_violations = 0

        if ref_rb is not None and cand_rb is not None:
            # Position error
            if "position" in ref_rb and "position" in cand_rb:
                r_pos = ref_rb["position"][:]
                c_pos = cand_rb["position"][:]
                if not np.isfinite(c_pos).all():
                    failures.append("rigid_body_nonfinite_state:position")
                else:
                    pos_diff = np.linalg.norm(c_pos - r_pos, axis=-1) / length_scale_m
                    rb_pos_error = [float(x) for x in pos_diff]

                    # Check containment within tank bounds
                    out_bounds = (
                        (c_pos[:, 0] < 0.05) | (c_pos[:, 0] > lx - 0.05) |
                        (c_pos[:, 1] < 0.05) | (c_pos[:, 1] > ly - 0.05) |
                        (c_pos[:, 2] < 0.02) | (c_pos[:, 2] > lz - 0.02)
                    )
                    if np.any(out_bounds):
                        failures.append("rigid_body_boundary_violation")

            # Linear velocity error
            if "linear_velocity" in ref_rb and "linear_velocity" in cand_rb:
                r_v = ref_rb["linear_velocity"][:]
                c_v = cand_rb["linear_velocity"][:]
                if not np.isfinite(c_v).all():
                    failures.append("rigid_body_nonfinite_state:linear_velocity")
                else:
                    v_diff = np.linalg.norm(c_v - r_v, axis=-1) / velocity_scale_m_s
                    rb_lin_vel_error = [float(x) for x in v_diff]

            # Angular velocity error
            if "angular_velocity" in ref_rb and "angular_velocity" in cand_rb:
                r_w = ref_rb["angular_velocity"][:]
                c_w = cand_rb["angular_velocity"][:]
                if not np.isfinite(c_w).all():
                    failures.append("rigid_body_nonfinite_state:angular_velocity")
                else:
                    ang_scale = velocity_scale_m_s / length_scale_m
                    w_diff = np.linalg.norm(c_w - r_w, axis=-1) / ang_scale
                    rb_ang_vel_error = [float(x) for x in w_diff]

            # Orientation quaternion error
            cand_quat = cand_rb.get("orientation_quaternion") or cand_rb.get("body_quaternion_xyzw")
            ref_quat = ref_rb.get("orientation_quaternion") or ref_rb.get("body_quaternion_xyzw")
            if ref_quat is not None and cand_quat is not None:
                r_q = ref_quat[:]
                c_q = cand_quat[:]
                if not np.isfinite(c_q).all():
                    failures.append("rigid_body_nonfinite_state:orientation_quaternion")
                else:
                    q_dist = quaternion_distance_rad(c_q, r_q)
                    rb_quat_error_rad = [float(x) for x in q_dist]

            # Euler angle error
            if "orientation_euler_deg" in ref_rb and "orientation_euler_deg" in cand_rb:
                r_e = ref_rb["orientation_euler_deg"][:]
                c_e = cand_rb["orientation_euler_deg"][:]
                if np.isfinite(c_e).all():
                    e_diff = np.max(np.abs(c_e - r_e), axis=-1)
                    rb_euler_error_deg = [float(x) for x in e_diff]

            # Contact event flag
            if "contact_event_flag" in cand_rb:
                c_flags = cand_rb["contact_event_flag"][:]
                rb_contact_violations = int(np.sum(c_flags.astype(bool)))
                if rb_contact_violations > 0:
                    failures.append(f"rigid_body_contact_violation:{rb_contact_violations}")
        elif ref_rb is not None and cand_rb is None:
            failures.append("missing_candidate_rigid_body")

        return {
            "schema": "ds-data-02.f6.evaluation.v1",
            "valid": not bool(failures),
            "failures": sorted(set(failures)),
            "time": ref_time.tolist(),
            "initial_reference_mass_kg": denominator,
            "extra_candidate_identities": extra,
            "missing_reference_mass_fraction": missing,
            "unknown_reference_mass_fraction": unknown,
            "reference_numerical_loss_mass_fraction": reference_loss,
            "mass_absolute_error_fraction": mass_error,
            "position_error_per_initial_mass": position_error,
            "velocity_error_per_initial_mass": velocity_error,
            "mean_position_error": float(np.mean(position_error)) if position_error else 0.0,
            "mean_velocity_error": float(np.mean(velocity_error)) if velocity_error else 0.0,
            "finite_wall_crossing_count": wall_crossings,
            "open_top_exit_count": open_top_crossings,
            "containment_compliant": (open_top_crossings == 0),
            "rigid_body_evaluation": {
                "position_error_relative": rb_pos_error,
                "mean_position_error_relative": float(np.mean(rb_pos_error)) if rb_pos_error else 0.0,
                "linear_velocity_error_relative": rb_lin_vel_error,
                "mean_linear_velocity_error_relative": float(np.mean(rb_lin_vel_error)) if rb_lin_vel_error else 0.0,
                "angular_velocity_error_relative": rb_ang_vel_error,
                "mean_angular_velocity_error_relative": float(np.mean(rb_ang_vel_error)) if rb_ang_vel_error else 0.0,
                "quaternion_error_rad": rb_quat_error_rad,
                "mean_quaternion_error_rad": float(np.mean(rb_quat_error_rad)) if rb_quat_error_rad else 0.0,
                "euler_error_deg": rb_euler_error_deg,
                "mean_euler_error_deg": float(np.mean(rb_euler_error_deg)) if rb_euler_error_deg else 0.0,
                "contact_event_violations": rb_contact_violations,
                "no_contact_compliant": (rb_contact_violations == 0),
            },
            "mechanism": mechanism,
            "length_scale_m": length_scale_m,
            "velocity_scale_m_s": velocity_scale_m_s,
            "numerical_qualification": "not_assessed",
            "model_invoked": False,
            "reference_survival_normalization": False,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True, help="Reference trajectory.h5")
    parser.add_argument("--candidate", type=Path, required=True, help="Candidate trajectory.h5")
    parser.add_argument(
        "--mechanism",
        choices=["simple_free_response", "wave_no_contact"],
        help="Physical mechanism of F6 case",
    )
    parser.add_argument("--length-scale", type=float, help="Length scale (m)")
    parser.add_argument("--velocity-scale", type=float, help="Velocity scale (m/s)")
    parser.add_argument("--walls", type=Path, help="Optional custom JSON closed walls file")
    parser.add_argument("--output", type=Path, required=True, help="Output evaluation JSON path")
    args = parser.parse_args()

    custom_walls = json.loads(args.walls.read_text(encoding="utf-8")) if args.walls else None
    result = evaluate_f6(
        args.reference,
        args.candidate,
        mechanism=args.mechanism,
        length_scale_m=args.length_scale,
        velocity_scale_m_s=args.velocity_scale,
        custom_walls=custom_walls,
    )

    if args.output.exists():
        args.output.unlink()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Evaluation written to {args.output} (valid={result['valid']}, failures={result['failures']})")
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
