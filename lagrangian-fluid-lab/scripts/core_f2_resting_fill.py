#!/usr/bin/env python3
"""Prepare and audit the independent F2 resting-fill static-hold canary.

The candidate changes the initial fluid placement only.  It keeps the cup,
receiver, tray, native particle count/mass rule, gravity and solver recipe
from the retained F2 source.  The first candidate continuous plane at
z=0.665 m was treated as a hypothesis; GenCase's actual native lattice places
the first fluid centre at z=0.660 m for this source point, and that decoded
position is the contract checked by this revision.  This module prepares a
qualification-only canary; it never starts the GPU worker itself.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import subprocess
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
from scripts.finite_wall_audit import outside_closed_face_masks, segment_crossing_events


SCHEMA = "core.f2.resting_fill_static_hold.v1"
JOB_SCHEMA = "core.cfd.job.v1"
REVISION_ID = "F2_resting_fill_static_hold_v2"
SCOPE_ID = "F2_resting_fill_static_hold_x_v1"
CASE_ID = "CORE_F2_resting_fill_static_hold_z0p660_q0p50000000_dp0p007500000000_canary"
SOURCE_RELATIVE = "campaigns/l2-multifamily/c1-canary/cases/L2_C1_F2_rotation_center_nominal_Def.xml"
MOTION_NAME = "CORE_F2_resting_fill_static_hold_zero_motion.dat"
DP_M = 0.0075
TIME_MAX_S = 0.60
DRIVE_START_S = 0.50
OUTPUT_INTERVAL_S = 0.02
TARGET_FIRST_FLUID_CENTER_Z_M = 0.660
TARGET_SOURCE_DRAW_POINT_Z_M = 0.66125
GRAVITY_M_S2 = -9.81
WALL_TOLERANCE_M = 1e-8
SETTLE_SPEED_P95_M_S = 0.10
SETTLE_KE_FRACTION = 0.05
SETTLE_HOLD_S = 0.20
MASS_CHANGE_RELATIVE_MAX = 1e-8

CUP = {"low": [0.0, -0.15, 0.65], "size": [0.425, 0.30, 0.45], "mkbound": 0}
RECEIVER = {"low": [0.45, -0.30, 0.0], "size": [1.10, 0.60, 0.45], "mkbound": 1}
TRAY = {"low": [-0.60, -0.55, -0.20], "size": [2.60, 1.10, 0.10], "mkbound": 2}
FLUID_BOXES = (
    {"low": [0.05, -0.11, 0.66], "size": [0.325, 0.22, 0.11], "mkfluid": 0},
    {"low": [0.05, -0.11, 0.77], "size": [0.325, 0.22, 0.11], "mkfluid": 1},
    {"low": [0.05, -0.11, 0.88], "size": [0.325, 0.22, 0.11], "mkfluid": 2},
)


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    partial.replace(path)


def _nearest_native_box(box: dict, dp: float) -> dict:
    low = np.asarray(box["low"], dtype=float)
    size = np.asarray(box["size"], dtype=float)
    counts = np.maximum(1, np.rint(size / float(dp)).astype(int))
    first = np.ceil(low / float(dp) - 0.5 - 1e-10).astype(int)
    first_center = (first + 0.5) * float(dp)
    draw_size = (counts - 1) * float(dp)
    continuous_mass = float(np.prod(size) * 1000.0)
    discrete_mass = float(np.prod(counts) * float(dp) ** 3 * 1000.0)
    return {
        "continuous_low_m": low.tolist(),
        "continuous_size_m": size.tolist(),
        "first_center_m": first_center.tolist(),
        "draw_size_m": draw_size.tolist(),
        "counts": counts.tolist(),
        "particle_count": int(np.prod(counts)),
        "continuous_mass_kg": continuous_mass,
        "discrete_mass_kg": discrete_mass,
        "mkfluid": int(box["mkfluid"]),
        "native_cell_centre_sampling": True,
    }


def _sampling() -> list[dict]:
    samples = [_nearest_native_box(box, DP_M) for box in FLUID_BOXES]
    # GenCase's source point is one half-dp below the first saved/native
    # fluid centre for this recipe.  The explicit z point is the candidate
    # contract; the preflight verifies the actual decoded native coordinate.
    for index, sample in enumerate(samples):
        source_z = TARGET_SOURCE_DRAW_POINT_Z_M + index * 0.1125
        sample["source_draw_point_m"] = [
            float(sample["first_center_m"][0]),
            float(sample["first_center_m"][1]),
            float(source_z),
        ]
        sample["source_draw_size_m"] = [float(value) for value in sample["draw_size_m"]]
        sample["expected_native_first_center_z_m"] = TARGET_FIRST_FLUID_CENTER_Z_M + index * 0.1125
    return samples


def _set_parameter(root: ET.Element, key: str, value: float | int | str) -> None:
    parameters = root.find(".//execution/parameters")
    if parameters is None:
        raise ValueError("source definition has no execution parameters")
    node = parameters.find(f"parameter[@key='{key}']")
    if node is None:
        node = ET.SubElement(parameters, "parameter", {"key": key})
    node.set("value", str(value))


def _write_zero_motion(path: Path) -> None:
    times = np.arange(0.0, TIME_MAX_S + OUTPUT_INTERVAL_S / 2.0, OUTPUT_INTERVAL_S)
    path.write_text("#Time;Degrees\n" + "\n".join(f"{time:.6f};0.000000000" for time in times) + "\n")


def _rewrite_definition(source: Path, target: Path, motion_name: str, samples: list[dict]) -> dict:
    tree = ET.parse(source)
    root = tree.getroot()
    _set_parameter(root, "SavePosDouble", 2)
    _set_parameter(root, "Boundary", 1)
    _set_parameter(root, "SlipMode", 1)
    _set_parameter(root, "TimeMax", TIME_MAX_S)
    _set_parameter(root, "TimeOut", OUTPUT_INTERVAL_S)
    _set_parameter(root, "PartsOutMax", 1)
    definition = root.find(".//geometry/definition")
    if definition is None:
        raise ValueError("source definition has no geometry definition")
    definition.set("dp", f"{DP_M:.17g}")
    commands = root.find(".//geometry/commands/mainlist")
    if commands is None:
        raise ValueError("source definition has no geometry command list")
    active_mk = None
    fluid_index = 0
    for node in list(commands):
        if node.tag == "setmkfluid":
            active_mk = int(node.get("mk"))
        elif node.tag == "drawbox" and active_mk is not None:
            if fluid_index >= len(samples):
                raise ValueError("source fluid-box count differs from candidate")
            point = node.find("point")
            size = node.find("size")
            sample = samples[fluid_index]
            if point is None or size is None:
                raise ValueError("fluid drawbox is incomplete")
            for axis, value in zip("xyz", sample["source_draw_point_m"]):
                point.set(axis, f"{value:.17g}")
            for axis, value in zip("xyz", sample["source_draw_size_m"]):
                size.set(axis, f"{value:.17g}")
            fluid_index += 1
    if fluid_index != len(samples):
        raise ValueError("source fluid-box count differs from candidate")
    motion = root.find(".//mvrotfile")
    if motion is None:
        raise ValueError("source definition has no moving rotation file")
    motion.set("duration", f"{TIME_MAX_S:.17g}")
    motion_file = motion.find("file")
    if motion_file is None:
        raise ValueError("source rotation has no file node")
    motion_file.set("name", motion_name)
    for begin in root.findall(".//begin"):
        begin.set("finish", f"{TIME_MAX_S:.17g}")
    ET.indent(tree, space="    ")
    target.parent.mkdir(parents=True, exist_ok=True)
    tree.write(target, encoding="utf-8", xml_declaration=True)
    return {
        "source_definition": str(source.resolve()),
        "source_definition_sha256": core_cfd.digest(source),
        "definition": str(target.resolve()),
        "definition_sha256": core_cfd.digest(target),
        "motion_file_name": motion_name,
        "changed_fields": [
            "initial fluid drawbox z points: explicit candidate source-plane contract",
            "execution.parameters.TimeMax=0.60",
            "execution.parameters.TimeOut=0.02",
            "prescribed rotation file: all angles zero",
        ],
        "unchanged_fields": [
            "cup/receiver/tray finite continuum geometry",
            "gravity, density, EOS, viscosity and DBC recipe",
            "native rho*dp^3 mass policy",
        ],
        "qualification_claim": "none",
    }


def _cup_spec() -> dict:
    low = np.asarray(CUP["low"], dtype=float)
    high = low + np.asarray(CUP["size"], dtype=float)
    return {
        "container_interior": {
            "xmin": float(low[0]), "xmax": float(high[0]),
            "ymin": float(low[1]), "ymax": float(high[1]),
            "zmin": float(low[2]), "zmax": float(high[2]),
        },
        "closed_faces": ["bottom", "left", "right", "front", "back"],
        "open_faces": ["top"],
        "obstacles": [],
    }


def _generated_groups(generated_xml: Path) -> tuple[list[dict], list[dict]]:
    root = ET.parse(generated_xml).getroot()
    fixed = []
    fluid = []
    for node in root.findall(".//particles/*"):
        if node.tag not in {"fixed", "moving", "fluid"}:
            continue
        entry = {key: int(value) if key in {"begin", "count", "mk", "mkbound", "mkfluid"} else value
                 for key, value in node.attrib.items()}
        (fluid if node.tag == "fluid" else fixed).append(entry)
    return fixed, fluid


def _select_group(ids: np.ndarray, begin: int, count: int) -> np.ndarray:
    return (ids >= int(begin)) & (ids < int(begin) + int(count))


def _geometry_preflight(
    lab: Path,
    output: Path,
    generated_xml: Path,
    prefix: Path,
    samples: list[dict],
) -> dict:
    generated_fixed, generated_fluid = _generated_groups(generated_xml)
    expected_counts = [int(sample["particle_count"]) for sample in samples]
    actual_counts = [int(item["count"]) for item in generated_fluid]
    generated_count_pass = actual_counts == expected_counts and len(generated_fluid) == len(samples)
    decoder = lab / "campaigns/l1-resume/artifacts/bi4_dump"
    with tempfile.TemporaryDirectory(prefix="f2-resting-fill-preflight-") as folder:
        ids, positions, velocities, density, metadata, info, arrays = core_cfd.native_frame(
            prefix.with_suffix(".bi4"), Path(folder) / "native", decoder
        )
        fluid_count = int(metadata.get("CaseNfluid", 0))
        fixed_count = int(metadata.get("CaseNfixed", 0))
        fluid_mask = np.zeros(len(ids), dtype=bool)
        for group in generated_fluid:
            fluid_mask |= _select_group(ids, group["begin"], group["count"])
        fluid_positions = positions[fluid_mask]
        fluid_velocities = velocities[fluid_mask]
        fluid_density = density[fluid_mask]
        moving = next((item for item in generated_fixed if item.get("mkbound") == 0), None)
        if moving is None:
            raise ValueError("generated moving cup group is missing")
        cup_mask = _select_group(ids, moving["begin"], moving["count"])
        cup_boundary = positions[cup_mask]
        cup_low = np.asarray(CUP["low"], dtype=float)
        cup_high = cup_low + np.asarray(CUP["size"], dtype=float)
        inside_physical = np.all((fluid_positions >= cup_low) & (fluid_positions <= cup_high), axis=1)
        face_clearance = np.min(
            np.concatenate((fluid_positions - cup_low, cup_high - fluid_positions), axis=1), axis=1
        )
        nearest_boundary_distance = cKDTree(cup_boundary).query(fluid_positions, k=1)[0] if len(cup_boundary) else np.full(len(fluid_positions), np.nan)
        actual_low = np.min(fluid_positions, axis=0)
        actual_high = np.max(fluid_positions, axis=0)
        zero_velocity = bool(np.max(np.abs(fluid_velocities), initial=0.0) <= 1e-12)
        finite_unique = bool(
            len(np.unique(ids)) == len(ids)
            and np.isfinite(positions).all()
            and np.isfinite(velocities).all()
            and np.isfinite(density).all()
        )
        checks = {
            "generated_fluid_counts": generated_count_pass,
            "native_fluid_count": fluid_count == sum(expected_counts) == int(fluid_positions.shape[0]),
            "native_ids_unique_finite": finite_unique,
            "native_initial_zero_velocity": zero_velocity,
            "fluid_inside_physical_cup": bool(inside_physical.all()),
            "target_first_fluid_center_z": bool(np.isclose(actual_low[2], TARGET_FIRST_FLUID_CENTER_Z_M, atol=1e-10)),
            "native_boundary_present": bool(len(cup_boundary) == int(moving["count"])),
            "positive_fluid_to_boundary_center_distance": bool(np.min(nearest_boundary_distance, initial=np.inf) > 0.0),
        }
        report = {
            "schema": "core.f2.resting_fill.static_preflight.v1",
            "revision_id": REVISION_ID,
            "scope_id": SCOPE_ID,
            "case_id": CASE_ID,
            "qualification_claim": "none; CPU GenCase/native geometry preflight only",
            "generated_definition": str(generated_xml.resolve()),
            "generated_definition_sha256": core_cfd.digest(generated_xml),
            "native_source": {
                "decoder": str(decoder.resolve()),
                "decoder_sha256": core_cfd.digest(decoder),
                "total_particles": int(len(ids)),
                "fixed_particles": fixed_count,
                "fluid_particles": fluid_count,
                "native_fluid_mass_kg": float(metadata.get("MassFluid", 0.0)) * fluid_count,
            },
            "continuum_cup_bounds_m": {"low": cup_low.tolist(), "high": cup_high.tolist()},
            "candidate_initial_fluid": {
                "target_first_center_z_m": TARGET_FIRST_FLUID_CENTER_Z_M,
                "actual_native_position_bounds_m": {"low": actual_low.tolist(), "high": actual_high.tolist()},
                "minimum_physical_face_clearance_m": float(np.min(face_clearance)),
                "minimum_native_cup_boundary_center_distance_m": float(np.min(nearest_boundary_distance)),
                "maximum_initial_speed_m_s": float(np.linalg.norm(fluid_velocities, axis=1).max(initial=0.0)),
                "particle_count": int(len(fluid_positions)),
            },
            "generated_particle_groups": {"fixed": generated_fixed, "fluid": generated_fluid},
            "checks": checks,
            "preflight_pass": bool(all(checks.values())),
            "no_overlap_definition": "all fluid centers lie inside the physical cup bounds and have positive center distance from generated moving-cup boundary particles; no mass or geometry rescaling",
        }
    return report


def _config(samples: list[dict], preflight_path: Path) -> dict:
    return {
        "schema": "core.cfd.v1",
        "family": "F2",
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "case_id": CASE_ID,
        "recipe_id": "F2_resting_fill_static_hold_dbc_native_v1",
        "recipe": "native_dbc",
        "stage": "repair_canary",
        "split": "qualification_only",
        "qualification_only": True,
        "parameter": {"name": "initial_condition_variant", "value": "resting_fill_z0p660", "range": ["resting_fill_z0p660"]},
        "dp_m": DP_M,
        "cfl": 0.2,
        "time_max_s": TIME_MAX_S,
        "output_interval_s": OUTPUT_INTERVAL_S,
        "source_definition": SOURCE_RELATIVE,
        "physical_case_id": "F2_resting_fill_static_cup_geometry_v1",
        "lineage_group_id": "F2_resting_fill_static_hold_v1",
        "paired_background_id": "F2_resting_fill_static_hold_only_no_pair",
        "view_id": "world_fluid_particle_v1",
        "control_semantics": "cup fixed at zero angle; static hold covers the original 0.50 s drive-start time",
        "source_label_semantics": "initial Mk is a numerical source partition; not material truth",
        "cup": copy.deepcopy(CUP),
        "receiver": copy.deepcopy(RECEIVER),
        "tray": copy.deepcopy(TRAY),
        "fluid_boxes": [copy.deepcopy(item) for item in FLUID_BOXES],
        "wall_bounds": {"xmin": -0.70, "xmax": 2.20, "ymin": -0.65, "ymax": 0.80, "zmin": -0.40, "zmax": 1.80},
        "runtime_domain": {"posmin": [-0.70, -0.65, -0.40], "posmax": [2.20, 0.80, 1.80]},
        "initial_condition": {
            "variant": "resting_fill_z0p660",
            "continuum_wall_geometry_changed": False,
            "fluid_initial_condition_changed": True,
            "target_first_native_fluid_center_z_m": TARGET_FIRST_FLUID_CENTER_Z_M,
            "source_draw_first_fluid_point_z_m": TARGET_SOURCE_DRAW_POINT_Z_M,
            "cup_floor_z_m": 0.65,
            "target_physical_floor_clearance_m": 0.010,
            "highest_generated_cup_bottom_boundary_layer_z_m": 0.6525,
            "initial_velocity_m_s": [0.0, 0.0, 0.0],
            "mass_rescaling": False,
            "predecessor_bottom_gap_m": 0.05500000000000005,
            "predecessor_pre_motion_escape_fraction_max": 0.04006058986010871,
            "preflight_artifact": str(preflight_path.resolve()),
        },
        "static_hold": {
            "drive_start_s": DRIVE_START_S,
            "requested_horizon_s": TIME_MAX_S,
            "settled_speed_p95_m_s": SETTLE_SPEED_P95_M_S,
            "settled_kinetic_over_initial_potential": SETTLE_KE_FRACTION,
            "settled_hold_s": SETTLE_HOLD_S,
            "cup_retention_gate": 1.0,
            "event_window_complete_requires_settled": True,
        },
        "qualification_inheritance": "none; independent initial-condition scope",
        "qualification_claim": "none; resting-fill static-hold canary only",
        "qualified": False,
    }


def prepare_canary(lab: Path, output: Path) -> dict:
    lab, output = Path(lab).resolve(), Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"resting-fill preparation output must be fresh: {output}")
    output.mkdir(parents=True, exist_ok=True)
    samples = _sampling()
    source = lab / SOURCE_RELATIVE
    definition = output / f"{CASE_ID}_Def.xml"
    definition_audit = _rewrite_definition(source, definition, MOTION_NAME, samples)
    motion = output / MOTION_NAME
    _write_zero_motion(motion)
    binaries = lab / "vendor/official/DualSPHysics_v5.4/bin/linux"
    prefix = output / "generated" / CASE_ID
    prefix.parent.mkdir(parents=True, exist_ok=True)
    command = [str(binaries / "GenCase_linux64"), str(definition.with_suffix("")), str(prefix), "-save:all"]
    with (output / "gencase.log").open("w") as log:
        process = subprocess.run(command, cwd=output, env=core_cfd.environment(lab), stdout=log, stderr=subprocess.STDOUT)
    if process.returncode:
        raise RuntimeError(f"GenCase failed; inspect {output / 'gencase.log'}")
    generated_xml = prefix.with_suffix(".xml")
    preflight = _geometry_preflight(lab, output, generated_xml, prefix, samples)
    _write_json(output / "static-preflight.json", preflight)
    sampling_payload = {
        "fluid_boxes": samples,
        "expected_fluid_particles": int(sum(item["particle_count"] for item in samples)),
        "continuous_mass_kg": float(sum(item["continuous_mass_kg"] for item in samples)),
        "sampled_mass_kg": float(sum(item["discrete_mass_kg"] for item in samples)),
        "mass_policy": "native rho*dp^3, no mass rescaling",
    }
    mass = core_cfd.mass_quality(sampling_payload)
    preflight["mass_preflight"] = mass
    preflight["preflight_pass"] = bool(preflight["preflight_pass"] and mass["mass_gate_pass"])
    _write_json(output / "static-preflight.json", preflight)
    solver = binaries / "DualSPHysics5.4_linux64"
    decoder = lab / "campaigns/l1-resume/artifacts/bi4_dump"
    config = _config(samples, output / "static-preflight.json")
    config["definition_audit"] = definition_audit
    config["sampling_rule"] = "explicit source draw point for target native first center; native rho*dp^3, no rescaling"
    inputs = {str(path.resolve()): core_cfd.digest(path) for path in output.rglob("*") if path.is_file()}
    prepared = {
        "schema": "core.cfd.v1",
        "created_at": _stamp(),
        "config": config,
        "sampling": sampling_payload,
        "mass_preflight": mass,
        "native_initial": preflight["native_source"],
        "static_preflight": preflight,
        "preflight_pass": bool(preflight["preflight_pass"]),
        "generated_prefix": str(prefix.resolve()),
        "source_template": str(source.resolve()),
        "source_template_sha256": core_cfd.digest(source),
        "definition_audit": definition_audit,
        "generated_particle_counts": [int(item["count"]) for item in preflight["generated_particle_groups"]["fluid"]],
        "resolved_runtime_domain": config["runtime_domain"],
        "inputs": inputs,
        "solver_binary": str(solver.resolve()),
        "solver_sha256": core_cfd.digest(solver),
        "decoder": str(decoder.resolve()),
        "decoder_sha256": core_cfd.digest(decoder),
        "solver_arguments": [],
        "qualification_only": True,
        "qualification_claim": "none; independent resting-fill static-hold canary only",
    }
    _write_json(output / "prepared.json", prepared)
    return prepared


def _p95(values: np.ndarray) -> float:
    return float(np.percentile(values, 95)) if len(values) else 0.0


def _settled_time(times: np.ndarray, speed_p95: np.ndarray, ke_fraction: np.ndarray) -> float | None:
    """Return a settling start only when the gate remains good to the window end.

    A short quiet interval followed by renewed motion is diagnostic evidence of
    transient low speed, not a settled state.  Requiring the qualifying run to
    reach the final saved frame prevents that false claim while preserving the
    registered continuous-hold duration.
    """
    good = (speed_p95 <= SETTLE_SPEED_P95_M_S) & (ke_fraction <= SETTLE_KE_FRACTION)
    for start in np.flatnonzero(good):
        end = start
        while end + 1 < len(good) and good[end + 1]:
            end += 1
        if end == len(good) - 1 and times[end] - times[start] >= SETTLE_HOLD_S - 1e-9:
            return float(times[start])
    return None


def _expected_native_fluid_axis(prepared: dict) -> np.ndarray:
    """Build the immutable fluid identity axis declared by the prepared case."""
    groups = prepared.get("static_preflight", {}).get("generated_particle_groups", {}).get("fluid", ())
    blocks = [
        np.arange(int(group["begin"]), int(group["begin"]) + int(group["count"]), dtype=np.uint64)
        for group in groups
    ]
    return np.concatenate(blocks) if blocks else np.empty(0, dtype=np.uint64)


def _top_opening_endpoint_mask(
    points: np.ndarray, cup_low: np.ndarray, cup_high: np.ndarray, tolerance: float
) -> np.ndarray:
    """Classify finite endpoints beyond the open cup mouth within its rim."""
    points = np.asarray(points, dtype=float)
    finite = np.isfinite(points).all(axis=1)
    horizontal = np.all(
        (points[:, :2] >= cup_low[:2] - tolerance)
        & (points[:, :2] <= cup_high[:2] + tolerance), axis=1
    )
    return finite & horizontal & (points[:, 2] > cup_high[2] + tolerance)


def _top_opening_crossing_events(
    p0: np.ndarray, p1: np.ndarray, cup_low: np.ndarray, cup_high: np.ndarray, tolerance: float
) -> list[dict]:
    """Locate saved-frame crossings of the open cup mouth for diagnostics."""
    first = np.asarray(p0, dtype=float)
    second = np.asarray(p1, dtype=float)
    delta = second - first
    finite = np.isfinite(first).all(axis=1) & np.isfinite(second).all(axis=1)
    z0, z1, top = first[:, 2], second[:, 2], float(cup_high[2])
    upward = (z0 <= top + tolerance) & (z1 > top + tolerance)
    downward = (z0 > top + tolerance) & (z1 <= top + tolerance)
    moving = np.abs(delta[:, 2]) > 1e-15
    active = finite & moving & (upward | downward)
    fraction = np.full(len(first), np.nan, dtype=float)
    fraction[active] = (top - z0[active]) / delta[active, 2]
    crossing = first + fraction[:, None] * delta
    horizontal = np.all(
        (crossing[:, :2] >= cup_low[:2] - 1e-12)
        & (crossing[:, :2] <= cup_high[:2] + 1e-12), axis=1
    )
    active &= np.isfinite(fraction) & (fraction >= 0.0) & (fraction <= 1.0) & horizontal
    return [
        {
            "point_index": int(index),
            "kind": "open_top",
            "fraction": float(fraction[index]),
            "crossing_position_m": crossing[index].tolist(),
        }
        for index in np.flatnonzero(active)
    ]


def observe_static_hold(prepared_path: Path, hdf5_path: Path) -> dict:
    prepared = json.loads(Path(prepared_path).read_text())
    config = prepared["config"]
    cup_low = np.asarray(config["cup"]["low"], dtype=float)
    cup_high = cup_low + np.asarray(config["cup"]["size"], dtype=float)
    cup_spec = _cup_spec()
    expected_axis = _expected_native_fluid_axis(prepared)
    with h5py.File(hdf5_path, "r") as handle:
        times = np.asarray(handle["time"][:], dtype=float)
        ids = np.asarray(handle["particle_id"][:])
        positions = np.asarray(handle["position"][:], dtype=float)
        velocities = np.asarray(handle["velocity"][:], dtype=float)
        density = np.asarray(handle["density"][:], dtype=float)
        pressure = np.asarray(handle["pressure"][:], dtype=float)
        masses = np.asarray(handle["mass"][:], dtype=float)
        valid = np.asarray(handle["valid"][:], dtype=bool)
        if times.ndim != 1 or len(times) == 0:
            raise ValueError("static-hold trajectory has no saved time frames")
        if (
            positions.shape[:2] != valid.shape
            or positions.shape[:2] != velocities.shape[:2]
            or positions.shape[:2] != density.shape
            or positions.shape[:2] != pressure.shape
            or positions.shape[:2] != masses.shape
        ):
            raise ValueError("static-hold trajectory datasets have inconsistent frame/particle axes")
        time_axis_valid = bool(
            np.isfinite(times).all() and len(times) >= 2 and np.all(np.diff(times) > 0.0)
        )
        initial_valid = valid[0].copy()
        initial_ids = ids[initial_valid]
        initial_mass_values = masses[0].astype(float)
        initial_mass = float(initial_mass_values[initial_valid].sum(dtype=np.float64))
        initial_position = positions[0]
        initial_potential = float((initial_mass_values[initial_valid] * 9.81 * np.maximum(initial_position[initial_valid, 2] - cup_low[2], 0.0)).sum(dtype=np.float64))
        retention = []
        outside_mass_fraction = []
        speed_p95 = []
        ke_fraction = []
        com = []
        missing_counts = []
        nonfinite_counts = []
        mass_deltas = []
        active_mass_values = []
        mass_sum_deltas = []
        outside_top_mass_fraction = []
        outside_side_bottom_mass_fraction = []
        endpoint_frames = 0
        endpoint_by_face = {face: 0 for face in ("bottom", "left", "right", "front", "back")}
        chord_events = 0
        first_chord = None
        open_top_endpoint_frames = 0
        open_top_chord_events = 0
        first_open_top_chord = None
        previous = None
        for frame_index, time_s in enumerate(times):
            active = valid[frame_index].copy()
            finite = (
                np.isfinite(positions[frame_index]).all(axis=1)
                & np.isfinite(velocities[frame_index]).all(axis=1)
                & np.isfinite(masses[frame_index])
                & np.isfinite(density[frame_index])
                & np.isfinite(pressure[frame_index])
            )
            nonfinite_counts.append(int(np.sum(active & ~finite)))
            active &= finite
            missing_counts.append(int(np.sum(initial_valid & ~valid[frame_index])))
            tracked = initial_valid & valid[frame_index] & finite
            delta = np.abs(masses[frame_index, tracked].astype(float) - initial_mass_values[tracked])
            mass_deltas.append(float(np.max(delta, initial=0.0)))
            selected = positions[frame_index, active]
            selected_mass = masses[frame_index, active].astype(float)
            inside = np.all((selected >= cup_low) & (selected <= cup_high), axis=1)
            cup_mass = float(selected_mass[inside].sum(dtype=np.float64))
            active_mass = float(selected_mass.sum(dtype=np.float64))
            active_mass_values.append(active_mass)
            mass_sum_deltas.append(abs(active_mass - initial_mass))
            retention.append(cup_mass / max(initial_mass, 1e-30))
            outside_mass_fraction.append(float(selected_mass[~inside].sum(dtype=np.float64)) / max(initial_mass, 1e-30))
            # Any finite fluid centre above the cup rim is outside the cup's
            # open catchment, including points that have also moved beyond a
            # horizontal rim edge.  The separate endpoint/chord diagnostic
            # still restricts to the finite mouth rectangle.
            selected_top = selected[:, 2] > cup_high[2] + WALL_TOLERANCE_M
            outside_top_mass_fraction.append(float(selected_mass[selected_top].sum(dtype=np.float64)) / max(initial_mass, 1e-30))
            outside_side_bottom_mass_fraction.append(
                float(selected_mass[~inside & ~selected_top].sum(dtype=np.float64)) / max(initial_mass, 1e-30)
            )
            speeds = np.linalg.norm(velocities[frame_index, active], axis=1)
            speed_p95.append(_p95(speeds))
            kinetic = float((0.5 * selected_mass * np.sum(velocities[frame_index, active] ** 2, axis=1)).sum(dtype=np.float64))
            ke_fraction.append(kinetic / max(initial_potential, 1e-30))
            com.append(
                ((selected_mass[:, None] * selected).sum(axis=0) / max(active_mass, 1e-30)).tolist()
                if len(selected) else [None, None, None]
            )
            endpoint = outside_closed_face_masks(positions[frame_index], cup_spec, WALL_TOLERANCE_M)
            endpoint = {face: mask & valid[frame_index] for face, mask in endpoint.items()}
            for face, mask in endpoint.items():
                count = int(mask.sum())
                endpoint_by_face[face] += count
                endpoint_frames += count
            if previous is not None:
                common = previous["valid"] & valid[frame_index] & previous["finite"] & finite
                if common.any():
                    events = segment_crossing_events(
                        previous["positions"][common], positions[frame_index, common], cup_spec, WALL_TOLERANCE_M
                    )
                    chord_events += len(events)
                    if events and first_chord is None:
                        first_chord = {"frame_index": frame_index, "time_s": float(time_s), "events": events[:10]}
                    open_events = _top_opening_crossing_events(
                        previous["positions"][common], positions[frame_index, common], cup_low, cup_high,
                        WALL_TOLERANCE_M,
                    )
                    open_top_chord_events += len(open_events)
                    if open_events and first_open_top_chord is None:
                        first_open_top_chord = {
                            "frame_index": frame_index,
                            "time_s": float(time_s),
                            "events": open_events[:10],
                        }
            open_endpoint = _top_opening_endpoint_mask(
                positions[frame_index], cup_low, cup_high, WALL_TOLERANCE_M
            ) & valid[frame_index]
            open_top_endpoint_frames += int(open_endpoint.sum())
            previous = {
                "valid": valid[frame_index].copy(),
                "finite": finite.copy(),
                "positions": positions[frame_index].copy(),
            }
    retention = np.asarray(retention, dtype=float)
    outside_mass_fraction = np.asarray(outside_mass_fraction, dtype=float)
    speed_p95 = np.asarray(speed_p95, dtype=float)
    ke_fraction = np.asarray(ke_fraction, dtype=float)
    horizon = bool(len(times) >= 2 and times[-1] >= TIME_MAX_S - 1e-6)
    pre_motion_horizon = bool(len(times) >= 2 and times[-1] >= DRIVE_START_S - 1e-6)
    settled = _settled_time(times, speed_p95, ke_fraction)
    no_missing = int(max(missing_counts, default=0)) == 0
    no_nonfinite = int(sum(nonfinite_counts)) == 0
    mass_limit = MASS_CHANGE_RELATIVE_MAX * max(initial_mass, 1e-30)
    no_mass_change = bool(max(mass_deltas, default=0.0) <= mass_limit and max(mass_sum_deltas, default=0.0) <= mass_limit)
    no_closed_endpoint = endpoint_frames == 0
    no_chord = chord_events == 0
    no_open_escape = bool(np.max(outside_mass_fraction, initial=0.0) <= 1e-12)
    native_axis_exact = bool(
        ids.ndim == 1
        and len(ids) == len(expected_axis)
        and np.isfinite(ids).all()
        and len(np.unique(ids)) == len(ids)
        and np.array_equal(ids.astype(np.uint64, copy=False), expected_axis)
    )
    unexpected_active_count = int(np.max(np.sum(valid & ~initial_valid[None, :], axis=1), initial=0))
    pre_motion = times <= DRIVE_START_S + 1e-9
    pre_motion_max_outside = float(np.max(outside_mass_fraction[pre_motion], initial=0.0))
    pre_motion_max_speed = float(np.max(speed_p95[pre_motion], initial=0.0))
    pre_motion_max_ke = float(np.max(ke_fraction[pre_motion], initial=0.0))
    hard_checks = {
        "time_axis_valid": time_axis_valid,
        "initial_native_ids_present": native_axis_exact and bool(len(initial_ids) == len(expected_axis)),
        "no_unexpected_native_ids": unexpected_active_count == 0,
        "no_missing_native_ids": no_missing,
        "no_nonfinite_active_values": no_nonfinite,
        "native_mass_unchanged": no_mass_change,
        "no_cup_closed_wall_endpoint_penetrations": no_closed_endpoint,
        "no_cup_saved_chord_crossings": no_chord,
        "no_open_cup_escape": no_open_escape,
        "no_open_top_saved_chord_crossings": open_top_chord_events == 0,
        "pre_motion_window_reached": pre_motion_horizon,
        "requested_static_hold_horizon_reached": horizon,
    }
    return {
        "schema": "core.f2.resting_fill_static_hold.observations.v1",
        "revision_id": REVISION_ID,
        "case_id": config["case_id"],
        "family": "F2",
        "native_axis_particle_count": int(len(ids)),
        "expected_native_axis_particle_count": int(len(expected_axis)),
        "native_axis_exact": native_axis_exact,
        "unexpected_active_id_count_max": unexpected_active_count,
        "no_unexpected_native_ids": unexpected_active_count == 0,
        "time_s": times.tolist(),
        "cup_retention_mass_fraction": retention.tolist(),
        "outside_cup_mass_fraction": outside_mass_fraction.tolist(),
        "speed_p95_m_s": speed_p95.tolist(),
        "kinetic_energy_over_initial_potential": ke_fraction.tolist(),
        "center_of_mass_m": com,
        "initial_native_mass_kg": initial_mass,
        "initial_potential_energy_J": initial_potential,
        "minimum_cup_retention_mass_fraction": float(np.min(retention)) if len(retention) else None,
        "maximum_outside_cup_mass_fraction": float(np.max(outside_mass_fraction, initial=0.0)),
        "outside_top_mass_fraction": [float(value) for value in outside_top_mass_fraction],
        "outside_side_bottom_mass_fraction": [float(value) for value in outside_side_bottom_mass_fraction],
        "pre_motion_maximum_outside_cup_mass_fraction": pre_motion_max_outside,
        "pre_motion_maximum_speed_p95_m_s": pre_motion_max_speed,
        "pre_motion_maximum_kinetic_over_initial_potential": pre_motion_max_ke,
        "maximum_speed_p95_m_s": float(np.max(speed_p95, initial=0.0)),
        "maximum_kinetic_over_initial_potential": float(np.max(ke_fraction, initial=0.0)),
        "native_missing_count_max": int(max(missing_counts, default=0)),
        "nonfinite_active_value_count": int(sum(nonfinite_counts)),
        "mass_delta_max_kg": float(max(mass_deltas, default=0.0)),
        "active_mass_kg": [float(value) for value in active_mass_values],
        "active_mass_fraction": [float(value / max(initial_mass, 1e-30)) for value in active_mass_values],
        "mass_sum_delta_max_kg": float(max(mass_sum_deltas, default=0.0)),
        "cup_closed_wall_endpoint_particle_frames": int(endpoint_frames),
        "cup_closed_wall_endpoint_by_face": endpoint_by_face,
        "cup_saved_chord_crossings": int(chord_events),
        "first_cup_saved_chord_crossing": first_chord,
        "cup_open_top_endpoint_particle_frames": int(open_top_endpoint_frames),
        "cup_open_top_saved_chord_crossings": int(open_top_chord_events),
        "first_cup_open_top_saved_chord_crossing": first_open_top_chord,
        "requested_horizon_reached": horizon,
        "pre_motion_window_reached": pre_motion_horizon,
        "settled_time_s": settled,
        "static_settled": settled is not None,
        "settled_definition": {
            "speed_p95_m_s_max": SETTLE_SPEED_P95_M_S,
            "kinetic_over_initial_potential_max": SETTLE_KE_FRACTION,
            "continuous_hold_s": SETTLE_HOLD_S,
        },
        "hard_checks": hard_checks,
        "hard_integrity_pass": bool(all(hard_checks.values())),
        "static_hold_gate_pass": bool(all(hard_checks.values()) and horizon and settled is not None),
        "event_window_complete": bool(all(hard_checks.values()) and horizon and settled is not None),
        "qualification_claim": "none; independent static-hold canary observation",
        "qualified": False,
    }


def run(prepared_path: Path, lab: Path, output: Path) -> dict:
    prepared_path, lab, output = Path(prepared_path).resolve(), Path(lab).resolve(), Path(output).resolve()
    prepared = json.loads(prepared_path.read_text())
    if not prepared.get("preflight_pass") or not prepared.get("qualification_only"):
        raise ValueError("resting-fill canary preflight/qualification_only gate did not pass")
    result = core_cfd.run(prepared_path, lab, output)
    observations = observe_static_hold(prepared_path, output / "trajectory.h5")
    audit = {
        "schema": "core.f2.resting_fill_static_hold.audit.v1",
        "revision_id": REVISION_ID,
        "case_id": prepared["config"]["case_id"],
        "family": "F2",
        "prepared_sha256": core_cfd.digest(prepared_path),
        "trajectory_sha256": core_cfd.digest(output / "trajectory.h5"),
        "static_hold_observation": observations,
        "hard_checks": observations["hard_checks"],
        "hard_integrity_pass": observations["hard_integrity_pass"],
        "requested_horizon_reached": observations["requested_horizon_reached"],
        "pre_motion_window_reached": observations["pre_motion_window_reached"],
        "static_settled": observations["static_settled"],
        "event_window_complete": observations["event_window_complete"],
        "qualified": False,
        "qualification_claim": "none; independent resting-fill static-hold canary audit",
    }
    _write_json(output / "observations.json", observations)
    _write_json(output / "audit.json", audit)
    result.update(audit)
    result["observations"] = observations
    result["qualified"] = False
    result["qualification_claim"] = "none; independent resting-fill static-hold canary only"
    _write_json(output / "result.json", result)
    return result


def make_job(prepared_path: Path, lab: Path, output: Path) -> dict:
    prepared_path, lab, output = Path(prepared_path).resolve(), Path(lab).resolve(), Path(output).resolve()
    prepared = json.loads(prepared_path.read_text())
    if not prepared.get("preflight_pass") or not prepared.get("qualification_only"):
        raise ValueError("resting-fill canary is not ready or qualification_only=true is missing")
    solver = Path(prepared["solver_binary"]).resolve()
    decoder = Path(prepared["decoder"]).resolve()
    script = (lab / "scripts/core_f2_resting_fill.py").resolve()
    spec = {
        "schema": JOB_SCHEMA,
        "job_id": "f2-resting-fill-static-hold-canary-v2-001",
        "logical_id": "f2-resting-fill-static-hold-canary-v2-001",
        "attempt_role": "independent_initial_condition_static_hold",
        "category": "f2_resting_fill_static_hold_canary",
        "host": "h200",
        "source_lab": str(lab),
        "cwd": str(lab),
        "argv": [str(lab / ".venv/bin/python"), str(script), "--lab-root", str(lab), "run",
                 "--prepared", str(prepared_path), "--output", "{attempt_dir}/product"],
        "required_outputs": ["product/result.json", "product/trajectory.h5", "product/audit.json", "product/observations.json"],
        "resources": {"cpu_cores": 2, "ram_mib": 16384, "gpu_peak_mib": 4096, "io_weight": 0.25},
        "timeout_seconds": 1800,
        "depends_on": [],
        "qualification_claim": "none",
        "qualification_only": True,
        "qualification_status": "candidate-only; independent initial-condition static hold; no moving-cup/range qualification",
        "input_files": [
            {"path": str(prepared_path), "sha256": core_cfd.digest(prepared_path)},
            {"path": str(solver), "sha256": core_cfd.digest(solver)},
            {"path": str(decoder), "sha256": core_cfd.digest(decoder)},
            {"path": str(script), "sha256": core_cfd.digest(script)},
        ],
        "prepared_case_id": prepared["config"]["case_id"],
        "registered_window_s": TIME_MAX_S,
        "pre_motion_window_s": DRIVE_START_S,
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "family": "F2",
        "physical_geometry_changed": False,
        "initial_condition_changed": True,
        "mass_rescaling": False,
        "worker_contract": "core_runtime worker; scheduler supplies one CUDA UUID and solver uses -gpu:0; output is attempt_dir/product",
        "launch_recommendation": "root review/queue only after CPU preflight; subagent does not launch",
    }
    _write_json(output, spec)
    return spec


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare-canary")
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("make-job")
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("run")
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare-canary":
        result = prepare_canary(args.lab_root, args.output)
    elif args.command == "make-job":
        result = make_job(args.prepared, args.lab_root, args.output)
    else:
        result = run(args.prepared, args.lab_root, args.output)
    print(json.dumps({key: result[key] for key in (
        "preflight_pass", "static_preflight", "qualification_only", "hard_integrity_pass",
        "static_settled", "event_window_complete", "qualification_claim", "job_id",
    ) if key in result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
