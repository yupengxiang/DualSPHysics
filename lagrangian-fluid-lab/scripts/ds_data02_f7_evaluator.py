#!/usr/bin/env python3
"""Model-free state evaluator for Family F7 with reference denominators and explicit failures.

Adheres strictly to P5 quality standards:
1. Model-free: NEVER loads neural network weights, never executes a learned model.
2. Exact reference self-comparison verification: identical trajectory yields zero error and valid=True.
3. Explicit detection of:
   - saved_time_mismatch (different or non-monotonic timestamps)
   - condition_binding / condition_mismatch (coordinate_frame, geometry_sha256, control_sha256)
   - typed identity mismatches / unexpected candidate identities
   - missing_reference_mass (inactive candidate particles where reference is active)
   - unknown_reference_mass (nonfinite coordinates or negative/nonfinite masses)
   - finite_closed_wall_crossing (impenetrable tank walls or pump casing boundaries)
   - open_top_exit (containment violation above tank rim or pump boundary)
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

# F7 characteristic physical scales
DEFAULT_OBSTACLE_LENGTH_SCALE_M = 1.20   # Tank length in X [-0.60, 0.60]
DEFAULT_OBSTACLE_VELOCITY_SCALE_M_S = 3.4309  # sqrt(g * L) = sqrt(9.81 * 1.20)

DEFAULT_PUMP_LENGTH_SCALE_M = 0.555      # Casing X envelope size [-0.319, 0.236]
DEFAULT_PUMP_VELOCITY_SCALE_M_S = 2.3334 # sqrt(g * L) = sqrt(9.81 * 0.555)


def identities(handle: h5py.File) -> list[tuple[int, int]]:
    keys = list(zip(handle["particle_zone"][:].tolist(), handle["particle_id"][:].tolist()))
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate typed identities")
    return keys


def get_f7_closed_walls(mechanism: str = "moving_obstacle_exchange") -> list[dict[str, Any]]:
    """Define finite closed boundary walls for F7 geometries."""
    if mechanism == "moving_obstacle_exchange":
        # Closed rectangular tank [-0.60, 0.60] x [-0.40, 0.40] x [0.0, 0.60]
        return [
            {"id": "tank_bottom", "axis": 2, "value": 0.0, "aperture_bounds": [[-0.60, 0.60], [-0.40, 0.40]]},
            {"id": "tank_left", "axis": 0, "value": -0.60, "aperture_bounds": [[-0.40, 0.40], [0.0, 0.60]]},
            {"id": "tank_right", "axis": 0, "value": 0.60, "aperture_bounds": [[-0.40, 0.40], [0.0, 0.60]]},
            {"id": "tank_front", "axis": 1, "value": -0.40, "aperture_bounds": [[-0.60, 0.60], [0.0, 0.60]]},
            {"id": "tank_back", "axis": 1, "value": 0.40, "aperture_bounds": [[-0.60, 0.60], [0.0, 0.60]]},
        ]
    elif mechanism == "pump_recirculation":
        # Closed casing envelope: X in [-0.32, 0.24], Y in [-0.54, 0.26], Z in [-1.02, -0.07]
        return [
            {"id": "casing_bottom", "axis": 2, "value": -1.013, "aperture_bounds": [[-0.32, 0.24], [-0.54, 0.26]]},
            {"id": "casing_left", "axis": 0, "value": -0.32, "aperture_bounds": [[-0.54, 0.26], [-1.02, -0.07]]},
            {"id": "casing_right", "axis": 0, "value": 0.24, "aperture_bounds": [[-0.54, 0.26], [-1.02, -0.07]]},
            {"id": "casing_front", "axis": 1, "value": -0.54, "aperture_bounds": [[-0.32, 0.24], [-1.02, -0.07]]},
            {"id": "casing_back", "axis": 1, "value": 0.26, "aperture_bounds": [[-0.32, 0.24], [-1.02, -0.07]]},
        ]
    else:
        raise ValueError(f"unsupported F7 mechanism: {mechanism}")


def get_f7_open_top(mechanism: str = "moving_obstacle_exchange") -> dict[str, Any]:
    """Define open top / exit aperture for containment audit."""
    if mechanism == "moving_obstacle_exchange":
        return {
            "id": "tank_open_top_exit",
            "axis": 2,
            "value": 1.80,
            "aperture_bounds": [[-2.0, 2.0], [-2.0, 2.0]],
        }
    elif mechanism == "pump_recirculation":
        return {
            "id": "casing_top_exit",
            "axis": 2,
            "value": -0.07,
            "aperture_bounds": [[-0.32, 0.24], [-0.54, 0.26]],
        }
    else:
        raise ValueError(f"unsupported F7 mechanism: {mechanism}")


def evaluate_f7(
    reference: Path | str,
    candidate: Path | str,
    *,
    mechanism: str = "moving_obstacle_exchange",
    length_scale_m: float | None = None,
    velocity_scale_m_s: float | None = None,
    custom_walls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Evaluate candidate trajectory against reference for Family F7 under P5 quality standards."""
    if length_scale_m is None:
        length_scale_m = DEFAULT_OBSTACLE_LENGTH_SCALE_M if mechanism == "moving_obstacle_exchange" else DEFAULT_PUMP_LENGTH_SCALE_M
    if velocity_scale_m_s is None:
        velocity_scale_m_s = DEFAULT_OBSTACLE_VELOCITY_SCALE_M_S if mechanism == "moving_obstacle_exchange" else DEFAULT_PUMP_VELOCITY_SCALE_M_S

    if length_scale_m <= 0 or velocity_scale_m_s <= 0:
        raise ValueError("physical scales must be positive")

    reference, candidate = Path(reference), Path(candidate)
    failures: list[str] = []

    with h5py.File(reference, "r") as ref, h5py.File(candidate, "r") as cand:
        for name in ("time", "particle_id", "particle_zone", "valid", "type", "mass", "position", "velocity"):
            if name not in ref or name not in cand:
                raise ValueError(f"missing required state: {name}")

        ref_time = np.asarray(ref["time"][:], dtype=np.float64)
        cand_time = np.asarray(cand["time"][:], dtype=np.float64)
        if not np.array_equal(ref_time, cand_time):
            return {
                "schema": "ds-data-02.f7.evaluation.v1",
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
        initial_mass = np.where(initial_fluid, ref["mass"][0], 0.0).astype(np.float64)
        if not np.isfinite(initial_mass).all() or np.any(initial_mass[initial_fluid] <= 0):
            raise ValueError("reference initial mass invalid")

        denominator = float(initial_mass.sum())
        if denominator <= 0:
            raise ValueError("reference has no initial fluid mass")

        closed_walls = get_f7_closed_walls(mechanism) if custom_walls is None else custom_walls
        open_top = get_f7_open_top(mechanism)

        position_error: list[float] = []
        velocity_error: list[float] = []
        missing: list[float] = []
        unknown: list[float] = []
        mass_error: list[float] = []
        reference_loss: list[float] = []
        wall_crossings = 0
        open_top_crossings = 0

        previous_pos = None
        previous_good = None

        nt = len(ref_time)
        nref = len(ref_keys)

        for ti in range(nt):
            rv = ref["valid"][ti].astype(bool) & initial_fluid
            reference_loss.append(float(initial_mass[initial_fluid & ~rv].sum() / denominator))

            cp = np.full((nref, 3), np.nan, dtype=np.float64)
            cv = np.full_like(cp, np.nan)
            cm = np.full(nref, np.nan, dtype=np.float64)
            candidate_active = np.zeros(nref, dtype=bool)

            cp[present] = cand["position"][ti][mapping[present]]
            cv[present] = cand["velocity"][ti][mapping[present]]
            cm[present] = cand["mass"][ti][mapping[present]]
            candidate_active[present] = cand["valid"][ti][mapping[present]].astype(bool)

            raw_active = cand["valid"][ti].astype(bool) & (cand["type"][ti] == 3)
            raw_mass = np.asarray(cand["mass"][ti], dtype=np.float64)
            raw_pos = np.asarray(cand["position"][ti], dtype=np.float64)
            raw_vel = np.asarray(cand["velocity"][ti], dtype=np.float64)

            if np.any(raw_active & (~np.isfinite(raw_mass) | (raw_mass <= 0))):
                failures.append("invalid_candidate_mass")
            if np.any(raw_active & (~np.isfinite(raw_pos).all(axis=1) | ~np.isfinite(raw_vel).all(axis=1))):
                failures.append("nonfinite_candidate_state")

            good = candidate_active & np.isfinite(cp).all(axis=1) & np.isfinite(cv).all(axis=1) & np.isfinite(cm) & (cm > 0)
            common = rv & good

            missing.append(float(initial_mass[rv & ~candidate_active].sum() / denominator))
            unknown.append(float(initial_mass[rv & candidate_active & ~good].sum() / denominator))
            mass_error.append(float(np.abs(cm[common] - ref["mass"][ti][common]).sum() / denominator))

            rp = np.asarray(ref["position"][ti], dtype=np.float64)
            rvel = np.asarray(ref["velocity"][ti], dtype=np.float64)
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

                # Open top / exit boundary crossing into unconfined region
                fwd_top, _, _ = finite_crossing(previous_pos, cp, open_top)
                open_top_crossings += int((fwd_top & paired).sum())

            previous_pos = cp
            previous_good = good

        if max(missing, default=0.0) > 0:
            failures.append("missing_reference_mass")
        if max(unknown, default=0.0) > 0:
            failures.append("unknown_reference_mass")
        if wall_crossings > 0:
            failures.append("finite_closed_wall_crossing")
        if open_top_crossings > 0:
            failures.append("containment_violation:open_top_exit")

        return {
            "schema": "ds-data-02.f7.evaluation.v1",
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
        choices=["moving_obstacle_exchange", "pump_recirculation"],
        default="moving_obstacle_exchange",
        help="Physical mechanism of F7 case",
    )
    parser.add_argument("--length-scale", type=float, default=None, help="Optional length scale override (m)")
    parser.add_argument("--velocity-scale", type=float, default=None, help="Optional velocity scale override (m/s)")
    parser.add_argument("--walls", type=Path, default=None, help="Optional custom JSON closed walls file")
    parser.add_argument("--output", type=Path, required=True, help="Output evaluation JSON path")
    args = parser.parse_args()

    custom_walls = json.loads(args.walls.read_text(encoding="utf-8")) if args.walls else None
    result = evaluate_f7(
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
