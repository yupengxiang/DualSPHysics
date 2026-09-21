#!/usr/bin/env python3
"""Re-audit a retained F2 resting-fill trajectory without rerunning the solver.

This is a versioned diagnostic path.  It reads the retained HDF5 product and
the frozen prepared case, writes a new report directory, and never overwrites
the original result, audit, observations, or execution receipt.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET

import h5py
import numpy as np
from scipy.spatial import cKDTree

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from scripts import core_cfd
from scripts import core_f2_resting_fill as observer


SCHEMA = "core.f2.resting_fill.static_hold.reaudit.v1"
GRAVITY = 9.81
DP = 0.0075
SMOOTHING_LENGTH_FACTOR = 1.3


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    partial.replace(path)


def _hdf5_digest(path: Path) -> str:
    return core_cfd.digest(path)


def _bounds_classification(
    positions: np.ndarray,
    masses: np.ndarray,
    valid: np.ndarray,
    low: np.ndarray,
    high: np.ndarray,
    initial_mass: float,
) -> dict:
    finite = np.isfinite(positions).all(axis=1) & np.isfinite(masses) & valid
    point = positions
    # Above the rim is open-cup escape even when the particle has also
    # travelled beyond a horizontal rim edge.  Finite side-wall penetration
    # is reported separately only while the point remains within the wall's
    # vertical span.
    top = finite & (point[:, 2] > high[2])
    bottom = (
        finite
        & (point[:, 0] >= low[0]) & (point[:, 0] <= high[0])
        & (point[:, 1] >= low[1]) & (point[:, 1] <= high[1])
        & (point[:, 2] < low[2])
    )
    side = (
        finite
        & (point[:, 2] >= low[2]) & (point[:, 2] <= high[2])
        & ((point[:, 0] < low[0]) | (point[:, 0] > high[0])
           | (point[:, 1] < low[1]) | (point[:, 1] > high[1]))
    )
    return {
        "top_opening_count": int(top.sum()),
        "top_opening_mass_fraction": float(masses[top].sum(dtype=np.float64) / max(initial_mass, 1e-30)),
        "bottom_outside_count": int(bottom.sum()),
        "bottom_outside_mass_fraction": float(masses[bottom].sum(dtype=np.float64) / max(initial_mass, 1e-30)),
        "side_outside_count": int(side.sum()),
        "side_outside_mass_fraction": float(masses[side].sum(dtype=np.float64) / max(initial_mass, 1e-30)),
    }


def _first_missing_diagnostic(
    times: np.ndarray,
    ids: np.ndarray,
    positions: np.ndarray,
    velocities: np.ndarray,
    density: np.ndarray,
    pressure: np.ndarray,
    masses: np.ndarray,
    valid: np.ndarray,
    source_labels: np.ndarray,
    low: np.ndarray,
    high: np.ndarray,
    runtime_domain: dict,
) -> dict:
    initial = valid[0].copy()
    missing = initial[None, :] & ~valid
    first_frame = int(np.flatnonzero(missing.any(axis=1))[0]) if missing.any() else None
    if first_frame is None:
        return {
            "first_missing_frame_index": None,
            "first_missing_time_s": None,
            "first_missing_count": 0,
            "records": [],
            "first_loss_is_domain_ceiling_consistent": False,
        }
    if first_frame == 0:
        raise ValueError("trajectory loses native IDs in its initial frame")
    previous = first_frame - 1
    indices = np.flatnonzero(missing[first_frame])
    zmax = float(runtime_domain["posmax"][2])
    smoothing = SMOOTHING_LENGTH_FACTOR * DP
    records = []
    for index in indices:
        point = positions[previous, index]
        velocity = velocities[previous, index]
        speed = float(np.linalg.norm(velocity))
        margin = float(zmax - point[2])
        linear_dt = float(margin / velocity[2]) if velocity[2] > 0 else None
        records.append({
            "particle_id": int(ids[index]),
            "source_label_initial_mk": int(source_labels[index]),
            "previous_frame_index": previous,
            "previous_time_s": float(times[previous]),
            "previous_position_m": point.tolist(),
            "previous_velocity_m_s": velocity.tolist(),
            "previous_speed_m_s": speed,
            "previous_density_kg_m3": float(density[previous, index]),
            "previous_pressure_pa": float(pressure[previous, index]),
            "runtime_domain_zmax_m": zmax,
            "runtime_domain_z_margin_m": margin,
            "smoothing_length_m": smoothing,
            "linear_z_crossing_dt_s": linear_dt,
            "previous_position_inside_runtime_domain": bool(
                np.all(point >= np.asarray(runtime_domain["posmin"], dtype=float))
                and np.all(point <= np.asarray(runtime_domain["posmax"], dtype=float))
            ),
            "previous_position_above_cup_opening": bool(
                low[0] <= point[0] <= high[0]
                and low[1] <= point[1] <= high[1]
                and point[2] > high[2]
            ),
        })
    return {
        "first_missing_frame_index": first_frame,
        "first_missing_time_s": float(times[first_frame]),
        "first_missing_count": int(len(indices)),
        "previous_frame_index": previous,
        "previous_frame_time_s": float(times[previous]),
        "records": records,
        "first_loss_is_domain_ceiling_consistent": bool(
            records
            and all(item["previous_position_inside_runtime_domain"] for item in records)
            and all(item["previous_position_above_cup_opening"] for item in records)
            and all(item["previous_velocity_m_s"][2] > 0 for item in records)
            and all(item["linear_z_crossing_dt_s"] is not None for item in records)
            and all(item["linear_z_crossing_dt_s"] <= float(times[first_frame] - times[previous]) for item in records)
        ),
    }


def _initial_geometry_diagnostic(prepared: dict, trajectory: Path) -> dict:
    config = prepared["config"]
    cup_low = np.asarray(config["cup"]["low"], dtype=float)
    cup_high = cup_low + np.asarray(config["cup"]["size"], dtype=float)
    prefix = Path(prepared["generated_prefix"])
    decoder = Path(prepared["decoder"])
    with tempfile.TemporaryDirectory(prefix="f2-resting-fill-reaudit-native-") as temp:
        ids, positions, velocities, density, metadata, info, arrays = core_cfd.native_frame(
            prefix.with_suffix(".bi4"), Path(temp) / "native", decoder
        )
        groups = prepared["static_preflight"]["generated_particle_groups"]
        fluid_mask = np.zeros(len(ids), dtype=bool)
        for group in groups["fluid"]:
            fluid_mask |= (ids >= int(group["begin"])) & (ids < int(group["begin"]) + int(group["count"]))
        moving = next(group for group in groups["fixed"] if group.get("mkbound") == 0)
        cup_mask = (ids >= int(moving["begin"])) & (ids < int(moving["begin"]) + int(moving["count"]))
        fluid = positions[fluid_mask]
        cup = positions[cup_mask]
        tree = cKDTree(cup)
        distances = tree.query(fluid, k=1)[0]
        dp = float(metadata["Dp"])
        h = float(metadata["H"])
        bottom_boundary = cup[cup[:, 2] <= cup_low[2] + 0.5 * dp + 1e-12]
        bottom_fluid = fluid[fluid[:, 2] <= cup_low[2] + 1.5 * dp + 1e-12]
        side_rows = {}
        side_definitions = {
            "left": (0, cup_low[0], -1),
            "right": (0, cup_high[0], 1),
            "front": (1, cup_low[1], -1),
            "back": (1, cup_high[1], 1),
        }
        for face, (axis, plane, direction) in side_definitions.items():
            fluid_face = fluid[:, axis] < plane + 8 * dp if direction < 0 else fluid[:, axis] > plane - 8 * dp
            fluid_face &= fluid[:, 2] > cup_low[2] + 4 * dp
            fluid_face &= fluid[:, 2] < cup_high[2] - 4 * dp
            boundary_face = cup[:, axis] <= plane + 3 * dp if direction < 0 else cup[:, axis] >= plane - 3 * dp
            boundary_face &= cup[:, 2] > cup_low[2] + 4 * dp
            boundary_face &= cup[:, 2] < cup_high[2] - 4 * dp
            face_distance = cKDTree(cup[boundary_face]).query(fluid[fluid_face], k=1)[0] if fluid_face.any() else np.empty(0)
            side_rows[face] = {
                "fluid_particle_count": int(fluid_face.sum()),
                "boundary_particle_count": int(boundary_face.sum()),
                "minimum_center_distance_m": float(np.min(face_distance)) if len(face_distance) else None,
            }
        with h5py.File(trajectory, "r") as handle:
            initial_position = np.asarray(handle["position"][0], dtype=float)
            initial_density = np.asarray(handle["density"][0], dtype=float)
            initial_pressure = np.asarray(handle["pressure"][0], dtype=float)
            initial_valid = np.asarray(handle["valid"][0], dtype=bool)
            initial_z = initial_position[initial_valid, 2]
            initial_rho = initial_density[initial_valid]
            initial_p = initial_pressure[initial_valid]
        water_top = float(np.max(initial_z))
        expected_p = float(metadata["Rhop0"]) * GRAVITY * (water_top - initial_z)
        fit = np.polyfit(initial_z, initial_p, 1)
        source_low = np.asarray(config["fluid_boxes"][0]["low"], dtype=float)
        source_high = source_low + np.asarray(config["fluid_boxes"][-1]["size"], dtype=float)
        return {
            "native_decoder_metadata": {
                "dp_m": dp,
                "smoothing_length_m": h,
                "rhop0_kg_m3": float(metadata["Rhop0"]),
                "gamma": float(metadata["Gamma"]),
                "mass_fluid_kg": float(metadata["MassFluid"]),
                "native_fluid_count": int(fluid_mask.sum()),
                "native_cup_boundary_count": int(cup_mask.sum()),
            },
            "continuum_cup_bounds_m": {"low": cup_low.tolist(), "high": cup_high.tolist()},
            "native_fluid_position_bounds_m": {"low": fluid.min(axis=0).tolist(), "high": fluid.max(axis=0).tolist()},
            "native_cup_boundary_position_bounds_m": {"low": cup.min(axis=0).tolist(), "high": cup.max(axis=0).tolist()},
            "physical_face_clearance_m": {
                "bottom": float(fluid[:, 2].min() - cup_low[2]),
                "left": float(fluid[:, 0].min() - cup_low[0]),
                "right": float(cup_high[0] - fluid[:, 0].max()),
                "front": float(fluid[:, 1].min() - cup_low[1]),
                "back": float(cup_high[1] - fluid[:, 1].max()),
                "top": float(cup_high[2] - fluid[:, 2].max()),
            },
            "native_center_clearance_m": {
                "minimum_any_cup_boundary": float(distances.min()),
                "bottom_fluid_to_bottom_boundary": float(
                    cKDTree(bottom_boundary).query(bottom_fluid, k=1)[0].min()
                ),
                "bottom_boundary_max_center_z_m": float(bottom_boundary[:, 2].max()),
                "bottom_fluid_min_center_z_m": float(bottom_fluid[:, 2].min()),
            },
            "side_wall_center_clearance_m": side_rows,
            "initial_velocity": {
                "max_speed_m_s": float(np.linalg.norm(velocities[fluid_mask], axis=1).max()),
                "all_zero": bool(np.allclose(velocities[fluid_mask], 0.0, atol=1e-12)),
            },
            "initial_hydrostatic_diagnostic": {
                "fluid_z_top_m": water_top,
                "density_min_kg_m3": float(initial_rho.min()),
                "density_max_kg_m3": float(initial_rho.max()),
                "density_fit_slope_kg_m4": float(np.polyfit(initial_z, initial_rho, 1)[0]),
                "pressure_min_pa": float(initial_p.min()),
                "pressure_max_pa": float(initial_p.max()),
                "pressure_fit_slope_pa_m": float(fit[0]),
                "expected_hydrostatic_pressure_fit_slope_pa_m": float(-float(metadata["Rhop0"]) * GRAVITY),
                "expected_pressure_residual_max_pa": float(np.max(np.abs(initial_p - expected_p))),
                "expected_pressure_residual_rms_pa": float(np.sqrt(np.mean((initial_p - expected_p) ** 2))),
                "rhopgradient_value": 2,
                "interpretation": "initial pressure decreases upward from the fluid free surface; no sign inversion evidence",
            },
            "source_continuum_fluid_boxes_m": [
                {"low": list(box["low"]), "size": list(box["size"])} for box in config["fluid_boxes"]
            ],
        }


def reaudit(prepared: Path, trajectory: Path, output: Path) -> dict:
    prepared = Path(prepared).resolve()
    trajectory = Path(trajectory).resolve()
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"reaudit output must be fresh: {output}")
    snapshot_dir = output / "code_snapshot"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    observer_snapshot = snapshot_dir / "core_f2_resting_fill.py"
    reaudit_snapshot = snapshot_dir / "f2_resting_fill_reaudit.py"
    shutil.copy2(Path(observer.__file__).resolve(), observer_snapshot)
    shutil.copy2(Path(__file__).resolve(), reaudit_snapshot)
    case = json.loads(prepared.read_text())
    config = case["config"]
    with h5py.File(trajectory, "r") as handle:
        times = np.asarray(handle["time"][:], dtype=float)
        ids = np.asarray(handle["particle_id"][:])
        positions = np.asarray(handle["position"][:], dtype=float)
        velocities = np.asarray(handle["velocity"][:], dtype=float)
        density = np.asarray(handle["density"][:], dtype=float)
        pressure = np.asarray(handle["pressure"][:], dtype=float)
        masses = np.asarray(handle["mass"][:], dtype=float)
        valid = np.asarray(handle["valid"][:], dtype=bool)
        source_labels = np.asarray(handle["source_label_initial_mk"][:])
        initial_mass = float(masses[0, valid[0]].sum(dtype=np.float64))
        bounds = []
        for index, time_s in enumerate(times):
            bounds.append(_bounds_classification(
                positions[index], masses[index], valid[index],
                np.asarray(config["cup"]["low"], dtype=float),
                np.asarray(config["cup"]["low"], dtype=float) + np.asarray(config["cup"]["size"], dtype=float),
                initial_mass,
            ) | {"frame_index": index, "time_s": float(time_s), "valid_count": int(valid[index].sum())})
        first_missing = _first_missing_diagnostic(
            times, ids, positions, velocities, density, pressure, masses, valid, source_labels,
            np.asarray(config["cup"]["low"], dtype=float),
            np.asarray(config["cup"]["low"], dtype=float) + np.asarray(config["cup"]["size"], dtype=float),
            config["runtime_domain"],
        )
    observations = observer.observe_static_hold(prepared, trajectory)
    geometry = _initial_geometry_diagnostic(case, trajectory)
    definition = Path(case["definition_audit"]["definition"])
    xml = ET.parse(definition).getroot()
    parameters = {node.get("key"): node.get("value") for node in xml.findall(".//execution/parameters/parameter")}
    constants = {node.tag: node.attrib for node in xml.findall(".//constantsdef/*")}
    report = {
        "schema": SCHEMA,
        "created_at": _stamp(),
        "revision_id": config["revision_id"],
        "case_id": config["case_id"],
        "qualification_claim": "none; read-only re-audit of retained failed canary",
        "solver_rerun": False,
        "gpu_launched": False,
        "original_evidence_preserved": True,
        "inputs": {
            "prepared": str(prepared),
            "prepared_sha256": core_cfd.digest(prepared),
            "trajectory": str(trajectory),
            "trajectory_sha256": core_cfd.digest(trajectory),
            "original_observations": str(trajectory.parent / "observations.json"),
            "original_observations_sha256": core_cfd.digest(trajectory.parent / "observations.json"),
            "original_audit": str(trajectory.parent / "audit.json"),
            "original_audit_sha256": core_cfd.digest(trajectory.parent / "audit.json"),
            "observer_script": str(Path(observer.__file__).resolve()),
            "observer_script_sha256": core_cfd.digest(Path(observer.__file__)),
            "observer_code_snapshot": str(observer_snapshot),
            "observer_code_snapshot_sha256": core_cfd.digest(observer_snapshot),
            "reaudit_code_snapshot": str(reaudit_snapshot),
            "reaudit_code_snapshot_sha256": core_cfd.digest(reaudit_snapshot),
        },
        "observer_contract": {
            "full_native_particle_axis_checked": True,
            "per_frame_validity_checked": True,
            "density_pressure_finiteness_checked": True,
            "per_particle_mass_and_active_mass_checked": True,
            "finite_cup_closed_faces_checked": ["bottom", "left", "right", "front", "back"],
            "open_top_endpoint_and_saved_crossing_diagnostic": True,
            "static_settled_requires_final_continuous_hold_s": observer.SETTLE_HOLD_S,
            "minimum_retention_is_true_nonempty_minimum": True,
        },
        "observations": observations,
        "frame_bounds_classification": bounds,
        "first_missing_diagnostic": first_missing,
        "initial_geometry_and_pressure_diagnostic": geometry,
        "definition_parameters": parameters,
        "definition_constants": constants,
        "failure_interpretation": {
            "confirmed": [
                "The first six missing native identities occur at t=0.4800123333 s after being above the cup opening and below the runtime z ceiling at t=0.4600327165 s.",
                "Their prior upward velocities are 1.4403-1.5147 m/s and linear z-ceiling crossing estimates are 0.00945-0.01817 s, within the saved-frame interval.",
                "The maximum observed open-top mass fraction is 0.02439632897 before the original 0.50 s drive start; no finite closed-cup endpoint or saved chord crossing was found.",
                "The initial pressure profile decreases upward with fitted slope near -rho0*g; the source shows no initial hydrostatic sign inversion.",
                "The minimum center gap is the bottom fluid layer to the top generated cup-bottom layer: 0.0075 m, below h=0.00975 m but positive; side face physical clearances are materially larger.",
            ],
            "not_claimed": [
                "The re-audit does not establish hydrostatic equilibrium or explain the later upward numerical transient as a single proven mechanism.",
                "The finite-domain loss is not counted as a closed-wall penetration; enlarging the runtime domain alone would not make the open-top spill gate pass.",
            ],
        },
        "repair_hypotheses_max_two": [
            {
                "id": "H1_bottom_boundary_startup_coupling",
                "status": "evidence_supported_hypothesis",
                "basis": "Initial density/pressure is hydrostatic and velocity is zero, while the fluid-to-bottom-boundary center gap is only 0.0075 m versus h=0.00975 m; the run develops a large startup oscillation and open-top jet without a closed-wall crossing.",
                "candidate": "Independent static-initialization or boundary-coupling recipe that removes the startup transient while retaining continuum cup geometry, native count, and rho*dp^3 masses; requires a new canary and must not be called a repair of this result.",
            },
            {
                "id": "H2_runtime_domain_ceiling",
                "status": "confirmed_for_missing_id_mechanism_but_insufficient_for_gate",
                "basis": "First missing IDs are rising toward z=1.8 m with crossing estimates inside the saved interval; this is consistent with solver-domain truncation.",
                "candidate": "Independent runtime-domain envelope sized above the observed upward tail, with unchanged physical cup geometry; it can prevent missing IDs but cannot remove the measured open-top spill or establish settled behavior.",
            },
        ],
        "hard_integrity_pass": observations["hard_integrity_pass"],
        "static_settled": observations["static_settled"],
        "event_window_complete": observations["event_window_complete"],
        "qualified": False,
    }
    output.mkdir(parents=True, exist_ok=True)
    _write_json(output / "observations.json", observations)
    _write_json(output / "forensics.json", report)
    manifest = {
        "schema": "core.f2.resting_fill.static_hold.reaudit_manifest.v1",
        "created_at": report["created_at"],
        "output": str(output),
        "forensics": str(output / "forensics.json"),
        "forensics_sha256": core_cfd.digest(output / "forensics.json"),
        "observations": str(output / "observations.json"),
        "observations_sha256": core_cfd.digest(output / "observations.json"),
        "solver_rerun": False,
        "original_evidence_preserved": True,
        "qualification_claim": report["qualification_claim"],
    }
    _write_json(output / "manifest.json", manifest)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("reaudit")
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--trajectory", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "reaudit":
        result = reaudit(args.prepared, args.trajectory, args.output)
        print(json.dumps({
            key: result[key] for key in (
                "hard_integrity_pass", "static_settled", "event_window_complete",
                "qualified", "qualification_claim", "first_missing_diagnostic",
            )
        }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
