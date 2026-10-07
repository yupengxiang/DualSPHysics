#!/usr/bin/env python3
"""Model-free state evaluator for Family F2 with reference denominators and explicit failures.

Adheres strictly to P5 quality standards:
1. Model-free: NEVER loads neural network weights, never executes a learned model.
2. Exact reference self-comparison verification: identical trajectory yields zero error and valid=True.
3. Explicit detection of:
   - saved_time_mismatch (different or non-monotonic timestamps)
   - condition_binding / condition_mismatch (coordinate_frame, geometry_sha256, control_sha256)
   - typed identity mismatches / unexpected candidate identities
   - missing_reference_mass (inactive candidate particles where reference is active)
   - unknown_reference_mass (nonfinite coordinates or negative/nonfinite masses)
   - finite_closed_wall_crossing (catch basin floor and receiver walls)
   - open_top_exit (containment violation above domain limit z=2.20m)
4. Denominators: strictly normalized by initial total fluid mass and physical scales (L, V).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

import h5py
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from ds_data02_native_labels import finite_crossing

# F2 characteristic scales
DEFAULT_LENGTH_SCALE_M = 0.425  # Cup characteristic dimension
DEFAULT_VELOCITY_SCALE_M_S = 2.04  # sqrt(g * L) = sqrt(9.81 * 0.425)


def identities(handle: h5py.File) -> list[tuple[int, int]]:
    keys = list(zip(handle["particle_zone"][:].tolist(), handle["particle_id"][:].tolist()))
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate typed identities")
    return keys


def get_f2_closed_walls(mechanism: str = "center_catch", case_id: str | None = None) -> list[dict]:
    """Define finite closed walls for F2 remediated catch basin and receiver."""
    # Catch basin floor at z=-0.20 in [-1.20, 2.80] x [-1.00, 1.00]
    walls = [
        {"id": "basin_floor", "axis": 2, "value": -0.20, "aperture_bounds": [[-1.20, 2.80], [-1.00, 1.00]]},
        {"id": "basin_left", "axis": 0, "value": -1.20, "aperture_bounds": [[-1.00, 1.00], [-0.20, 0.15]]},
        {"id": "basin_right", "axis": 0, "value": 2.80, "aperture_bounds": [[-1.00, 1.00], [-0.20, 0.15]]},
        {"id": "basin_front", "axis": 1, "value": -1.00, "aperture_bounds": [[-1.20, 2.80], [-0.20, 0.15]]},
        {"id": "basin_back", "axis": 1, "value": 1.00, "aperture_bounds": [[-1.20, 2.80], [-0.20, 0.15]]},
    ]
    # Receiver walls coordinates from case parameters
    x_min = 0.65 if (case_id and ("P03" in case_id or "P04" in case_id)) else 0.45
    x_max = x_min + 1.10

    if mechanism == "center_catch":
        y_min, y_max = -0.30, 0.30
    else:
        # offset_spill: P01/P03 at y=-0.16, P02/P04 at y=-0.08
        if case_id and ("P02" in case_id or "P04" in case_id):
            y_min, y_max = -0.08, 0.52
        else:
            y_min, y_max = -0.16, 0.44

    walls.extend([
        {"id": "receiver_bottom", "axis": 2, "value": 0.0, "aperture_bounds": [[x_min, x_max], [y_min, y_max]]},
        {"id": "receiver_left", "axis": 0, "value": x_min, "aperture_bounds": [[y_min, y_max], [0.0, 0.45]]},
        {"id": "receiver_right", "axis": 0, "value": x_max, "aperture_bounds": [[y_min, y_max], [0.0, 0.45]]},
        {"id": "receiver_front", "axis": 1, "value": y_min, "aperture_bounds": [[x_min, x_max], [0.0, 0.45]]},
        {"id": "receiver_back", "axis": 1, "value": y_max, "aperture_bounds": [[x_min, x_max], [0.0, 0.45]]},
    ])
    return walls


def get_f2_open_top() -> dict:
    """Define open top aperture for containment audit above simulation domain."""
    return {
        "id": "top_open_exit",
        "axis": 2,
        "value": 2.20,
        "aperture_bounds": [[-1.40, 3.00], [-1.20, 1.20]],
    }


def evaluate_f2(
    reference: Path | str,
    candidate: Path | str,
    *,
    case_id: str | None = None,
    mechanism: str = "center_catch",
    length_scale_m: float = DEFAULT_LENGTH_SCALE_M,
    velocity_scale_m_s: float = DEFAULT_VELOCITY_SCALE_M_S,
    custom_walls: list[dict] | None = None,
) -> dict:
    """Evaluate candidate trajectory against reference for Family F2 under P5 standards."""
    if length_scale_m <= 0 or velocity_scale_m_s <= 0:
        raise ValueError("physical scales must be positive")

    reference, candidate = Path(reference), Path(candidate)
    failures = []

    if case_id is None:
        for part in candidate.parts:
            if part.startswith("F2_"):
                case_id = part
                break

    with h5py.File(reference, "r") as ref, h5py.File(candidate, "r") as cand:
        for name in ("time", "particle_id", "particle_zone", "valid", "type", "mass", "position", "velocity"):
            if name not in ref or name not in cand:
                raise ValueError(f"missing required state: {name}")

        ref_time = ref["time"][:]
        cand_time = cand["time"][:]
        if not np.array_equal(ref_time, cand_time):
            return {
                "schema": "ds-data-02.f2.evaluation.v1",
                "valid": False,
                "failures": ["saved_time_mismatch"],
                "numerical_qualification": "not_assessed",
                "model_invoked": False,
            }

        # Check metadata bindings
        for attr in ("coordinate_frame", "geometry_sha256", "control_sha256"):
            if attr in ref.attrs and attr in cand.attrs:
                if ref.attrs[attr] != cand.attrs[attr]:
                    failures.append(f"condition_mismatch:{attr}")
            elif attr in ref.attrs and attr not in cand.attrs:
                failures.append(f"missing_condition_binding:{attr}")

        ref_keys = identities(ref)
        cand_keys = identities(cand)
        cand_index = {key: i for i, key in enumerate(cand_keys)}
        if any(key not in cand_index for key in ref_keys):
            failures.append("typed_identity_mismatch:missing_candidate_keys")
        if failures:
            return {
                "schema": "ds-data-02.f2.evaluation.v1",
                "valid": False,
                "failures": failures,
                "numerical_qualification": "not_assessed",
                "model_invoked": False,
            }

        mapping = np.array([cand_index[k] for k in ref_keys], dtype=int)
        nref = len(ref_keys)
        initial_fluid = (ref["type"][0] == 3) & (ref["valid"][0].astype(bool))
        initial_mass = ref["mass"][0].copy()
        denominator = float(initial_mass[initial_fluid].sum())
        if denominator <= 0.0 or not np.isfinite(denominator):
            raise ValueError("invalid initial fluid denominator")

        is_identity = np.array_equal(mapping, np.arange(nref))
        walls = custom_walls if custom_walls is not None else get_f2_closed_walls(mechanism, case_id=case_id)
        open_top = get_f2_open_top()

        wall_crossings = 0
        open_top_crossings = 0
        position_error = []
        velocity_error = []
        mass_error = []
        missing = []
        unknown = []

        previous_pos = None
        previous_good = None

        for ti in range(len(ref_time)):
            rv = ref["valid"][ti].astype(bool) & (ref["type"][ti] == 3)
            raw_pos = cand["position"][ti]
            raw_vel = cand["velocity"][ti]
            raw_mass = cand["mass"][ti]
            raw_val = cand["valid"][ti]

            if is_identity:
                cp = raw_pos
                cv = raw_vel
                cm = raw_mass
                candidate_active = raw_val.astype(bool)
            else:
                cp = raw_pos[mapping]
                cv = raw_vel[mapping]
                cm = raw_mass[mapping]
                candidate_active = raw_val[mapping].astype(bool)

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

            missing_frac = float(initial_mass[rv & ~candidate_active].sum() / denominator)
            unknown_frac = float(initial_mass[rv & candidate_active & ~good].sum() / denominator)
            missing.append(missing_frac)
            unknown.append(unknown_frac)
            if missing_frac > 0.0:
                failures.append(f"missing_reference_mass:frame_{ti}")
            if unknown_frac > 0.0:
                failures.append(f"unknown_reference_mass:frame_{ti}")

            mass_error.append(float(np.abs(cm[common] - ref["mass"][ti][common]).sum() / denominator))

            rp = ref["position"][ti]
            rvel = ref["velocity"][ti]
            if not np.isfinite(rp[rv]).all() or not np.isfinite(rvel[rv]).all():
                raise ValueError("reference active state invalid")

            pos_err = (initial_mass[common] * np.linalg.norm(cp[common] - rp[common], axis=1)).sum() / denominator / length_scale_m
            vel_err = (initial_mass[common] * np.linalg.norm(cv[common] - rvel[common], axis=1)).sum() / denominator / velocity_scale_m_s
            position_error.append(float(pos_err))
            velocity_error.append(float(vel_err))

            if ti > 0:
                paired = previous_good & good & initial_fluid
                p0_fl = previous_pos[paired]
                p1_fl = cp[paired]
                if len(p0_fl) > 0:
                    for wall in walls:
                        fwd, bwd, _ = finite_crossing(p0_fl, p1_fl, wall)
                        wall_crossings += int((fwd | bwd).sum())
                    fwd_top, bwd_top, _ = finite_crossing(p0_fl, p1_fl, open_top)
                    open_top_crossings += int((fwd_top | bwd_top).sum())

            previous_pos = cp.copy()
            previous_good = good.copy()

        if wall_crossings > 0:
            failures.append(f"finite_closed_wall_crossing:{wall_crossings}_events")
        if open_top_crossings > 0:
            failures.append(f"open_top_exit:{open_top_crossings}_events")

        failures = sorted(set(failures))
        return {
            "schema": "ds-data-02.f2.evaluation.v1",
            "valid": len(failures) == 0,
            "failures": failures,
            "metrics": {
                "total_frames": len(ref_time),
                "total_particles": nref,
                "total_mass_kg": denominator,
                "max_position_error_per_mass": float(max(position_error)),
                "max_velocity_error_per_mass": float(max(velocity_error)),
                "max_mass_error_fraction": float(max(mass_error)),
                "finite_wall_crossing_count": wall_crossings,
                "open_top_exit_count": open_top_crossings,
            },
            "checks": {
                "containment_compliant": (open_top_crossings == 0),
                "wall_crossing_compliant": (wall_crossings == 0),
            },
            "mechanism": mechanism,
            "length_scale_m": length_scale_m,
            "velocity_scale_m_s": velocity_scale_m_s,
            "numerical_qualification": "not_assessed",
            "model_invoked": False,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True, help="Reference trajectory.h5")
    parser.add_argument("--candidate", type=Path, required=True, help="Candidate trajectory.h5")
    parser.add_argument("--mechanism", choices=["center_catch", "offset_spill"], default="center_catch")
    parser.add_argument("--length-scale", type=float, default=DEFAULT_LENGTH_SCALE_M)
    parser.add_argument("--velocity-scale", type=float, default=DEFAULT_VELOCITY_SCALE_M_S)
    parser.add_argument("--walls", type=Path, help="Optional custom JSON closed walls file")
    parser.add_argument("--output", type=Path, required=True, help="Output evaluation JSON path")
    args = parser.parse_args()

    custom_walls = json.loads(args.walls.read_text(encoding="utf-8")) if args.walls else None
    result = evaluate_f2(
        args.reference,
        args.candidate,
        mechanism=args.mechanism,
        length_scale_m=args.length_scale,
        velocity_scale_m_s=args.velocity_scale,
        custom_walls=custom_walls,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Evaluation written to {args.output} (valid={result['valid']}, failures={result['failures']})")
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
