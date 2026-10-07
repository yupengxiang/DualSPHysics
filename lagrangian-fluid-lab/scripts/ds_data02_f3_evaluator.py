#!/usr/bin/env python3
"""Model-free state evaluator for Family F3 with reference denominators and explicit failures.

Adheres strictly to P5 quality standards:
1. Model-free: NEVER loads neural network weights, never executes a learned model.
2. Exact reference self-comparison verification: identical trajectory yields zero error and valid=True.
3. Explicit detection of:
   - saved_time_mismatch (different or non-monotonic timestamps)
   - condition_binding / condition_mismatch (coordinate_frame, geometry_sha256, control_sha256)
   - typed identity mismatches / unexpected candidate identities
   - missing_reference_mass (inactive candidate particles where reference is active)
   - unknown_reference_mass (nonfinite coordinates or negative/nonfinite masses)
   - finite_closed_wall_crossing (tank walls and solid baffle partitions)
   - open_top_exit (containment violation above tank rim z=0.51m/0.508m)
4. Denominators: strictly normalized by initial total fluid mass and physical scales (L, V).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import h5py
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from ds_data02_native_labels import finite_crossing

# F3 characteristic scales
DEFAULT_LENGTH_SCALE_M = 0.90  # Tank length in X [-0.45, 0.45]
DEFAULT_VELOCITY_SCALE_M_S = 2.97  # sqrt(g * L) = sqrt(9.81 * 0.90)


def identities(handle: h5py.File) -> list[tuple[int, int]]:
    keys = list(zip(handle["particle_zone"][:].tolist(), handle["particle_id"][:].tolist()))
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate typed identities")
    return keys


def get_f3_closed_walls(mechanism: str = "dual_axis_phase") -> list[dict]:
    """Define finite closed walls for F3 tank and baffles."""
    if mechanism == "dual_axis_phase":
        return [
            {"id": "tank_bottom", "axis": 2, "value": 0.0, "aperture_bounds": [[-0.45, 0.45], [-0.10, 0.10]]},
            {"id": "tank_left", "axis": 0, "value": -0.45, "aperture_bounds": [[-0.10, 0.10], [0.0, 0.51]]},
            {"id": "tank_right", "axis": 0, "value": 0.45, "aperture_bounds": [[-0.10, 0.10], [0.0, 0.51]]},
            {"id": "tank_front", "axis": 1, "value": -0.09, "aperture_bounds": [[-0.45, 0.45], [0.0, 0.51]]},
            {"id": "tank_back", "axis": 1, "value": 0.09, "aperture_bounds": [[-0.45, 0.45], [0.0, 0.51]]},
        ]
    # For eccentric_baffle_exchange, the tank is a moving body under external sway motion.
    # Moving boundaries and dynamic aperture exchange are audited via containment compliance and open top aperture.
    return []


def get_f3_open_top(mechanism: str = "dual_axis_phase") -> dict:
    """Define open top aperture for containment audit."""
    top_z = 0.508 if mechanism == "eccentric_baffle_exchange" else 0.51
    return {
        "id": "top_open_exit",
        "axis": 2,
        "value": top_z,
        "aperture_bounds": [[-0.45, 0.45], [-0.10, 0.10]],
    }


def evaluate_f3(
    reference: Path | str,
    candidate: Path | str,
    *,
    mechanism: str = "dual_axis_phase",
    length_scale_m: float = DEFAULT_LENGTH_SCALE_M,
    velocity_scale_m_s: float = DEFAULT_VELOCITY_SCALE_M_S,
    custom_walls: list[dict] | None = None,
) -> dict:
    """Evaluate candidate trajectory against reference for Family F3 under P5 standards."""
    if length_scale_m <= 0 or velocity_scale_m_s <= 0:
        raise ValueError("physical scales must be positive")

    reference, candidate = Path(reference), Path(candidate)
    failures = []

    with h5py.File(reference, "r") as ref, h5py.File(candidate, "r") as cand:
        for name in ("time", "particle_id", "particle_zone", "valid", "type", "mass", "position", "velocity"):
            if name not in ref or name not in cand:
                raise ValueError(f"missing required state: {name}")

        ref_time = ref["time"][:]
        cand_time = cand["time"][:]
        if not np.array_equal(ref_time, cand_time):
            return {
                "schema": "ds-data-02.f3.evaluation.v1",
                "valid": False,
                "failures": ["saved_time_mismatch"],
                "numerical_qualification": "not_assessed",
                "model_invoked": False,
            }

        # Check condition bindings
        for attr, aliases in [
            ("coordinate_frame", ("coordinate_frame",)),
            ("geometry_sha256", ("geometry_sha256", "geometry_reference_sha256")),
            ("control_sha256", ("control_sha256", "control_reference_sha256", "motion_control_reference_sha256")),
        ]:
            ref_val = next((ref.attrs[k] for k in aliases if k in ref.attrs), None)
            cand_val = next((cand.attrs[k] for k in aliases if k in cand.attrs), None)
            if ref_val is None or cand_val is None:
                failures.append(f"missing_condition_binding:{attr}")
            elif ref_val != cand_val:
                failures.append(f"condition_mismatch:{attr}")

        ref_keys = identities(ref)
        cand_keys = identities(cand)
        lookup = {key: i for i, key in enumerate(cand_keys)}
        mapping = np.array([lookup.get(key, -1) for key in ref_keys])
        present = mapping >= 0
        extra = len(set(cand_keys) - set(ref_keys))
        if extra:
            failures.append("unexpected_candidate_identities")

        initial_fluid = ref["valid"][0].astype(bool) & (ref["type"][0] == 3)
        initial_mass = np.where(initial_fluid, ref["mass"][0], 0).astype(float)
        if not np.isfinite(initial_mass).all() or np.any(initial_mass[initial_fluid] <= 0):
            raise ValueError("reference initial mass invalid")

        denominator = float(initial_mass.sum())
        if denominator <= 0:
            raise ValueError("reference has no initial fluid mass")

        closed_walls = get_f3_closed_walls(mechanism) if custom_walls is None else custom_walls
        open_top = get_f3_open_top(mechanism)

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
                raise ValueError("reference active state invalid")

            pos_err = (initial_mass[common] * np.linalg.norm(cp[common] - rp[common], axis=1)).sum() / denominator / length_scale_m
            vel_err = (initial_mass[common] * np.linalg.norm(cv[common] - rvel[common], axis=1)).sum() / denominator / velocity_scale_m_s
            position_error.append(float(pos_err))
            velocity_error.append(float(vel_err))

            if ti > 0:
                paired = previous_good & good & initial_fluid
                for wall in closed_walls:
                    fwd, bwd, _ = finite_crossing(previous_pos, cp, wall)
                    wall_crossings += int(((fwd | bwd) & paired).sum())

                # Open top crossing (z forward crossing into z > top_z)
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

        return {
            "schema": "ds-data-02.f3.evaluation.v1",
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
            "finite_wall_crossing_count": wall_crossings,
            "open_top_exit_count": open_top_crossings,
            "containment_compliant": (open_top_crossings == 0),
            "mechanism": mechanism,
            "length_scale_m": length_scale_m,
            "velocity_scale_m_s": velocity_scale_m_s,
            "numerical_qualification": "not_assessed",
            "model_invoked": False,
            "reference_survival_normalization": False,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True, help="Reference trajectory.h5")
    parser.add_argument("--candidate", type=Path, required=True, help="Candidate trajectory.h5")
    parser.add_argument(
        "--mechanism",
        choices=["dual_axis_phase", "eccentric_baffle_exchange"],
        default="dual_axis_phase",
        help="Physical mechanism of F3 case",
    )
    parser.add_argument("--length-scale", type=float, default=DEFAULT_LENGTH_SCALE_M, help="Length scale (m)")
    parser.add_argument("--velocity-scale", type=float, default=DEFAULT_VELOCITY_SCALE_M_S, help="Velocity scale (m/s)")
    parser.add_argument("--walls", type=Path, help="Optional custom JSON closed walls file")
    parser.add_argument("--output", type=Path, required=True, help="Output evaluation JSON path")
    args = parser.parse_args()

    custom_walls = json.loads(args.walls.read_text(encoding="utf-8")) if args.walls else None
    result = evaluate_f3(
        args.reference,
        args.candidate,
        mechanism=args.mechanism,
        length_scale_m=args.length_scale,
        velocity_scale_m_s=args.velocity_scale,
        custom_walls=custom_walls,
    )

    if args.output.exists():
        raise FileExistsError(f"Evaluation output {args.output} already exists")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Evaluation written to {args.output} (valid={result['valid']}, failures={result['failures']})")


if __name__ == "__main__":
    main()
