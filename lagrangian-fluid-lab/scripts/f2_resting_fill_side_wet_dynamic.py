#!/usr/bin/env python3
"""Prepare a moving-cup F2 canary from the passed full-cup static state.

The static full-cup canary established a finite, side-wetted initial state.  This
module applies the registered centered rotation to that same continuous box and
native sampling, then delegates the finite moving-cup/receiver/tray hard audit
to ``core_f2_qualification``.  The runner has its own observer because the
full-cup native centres are deliberately closer than one dp to physical cup
faces; shrinking the cup observation box by one dp would classify valid initial
fluid as spill.  The hard wall audit always uses the physical source planes and
saved full-vector chords.

Preparation is CPU-only.  ``run`` is a coordinator worker entry point and does
not bypass the core runtime contract.
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
import time
import xml.etree.ElementTree as ET

import h5py
import numpy as np

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from scripts import core_cfd
from scripts import core_f2_qualification as dynamic


SCHEMA = "core.f2.resting_fill_side_wet.dynamic.v1"
JOB_SCHEMA = "core.cfd.job.v1"
REVISION_ID = "F2_resting_fill_side_wet_dynamic_canary_v1"
SCOPE_ID = "F2_resting_fill_side_wet_dynamic_x_v1"
CASE_ID = "CORE_F2_resting_fill_side_wet_dynamic_q0p50000000_dp0p007500000000_fullwindow_canary"
STATIC_PREPARED_RELATIVE = "campaigns/core-v1/cfd/prepared/F2_resting_fill_side_wet_full_cup_canary_v3/prepared.json"
STATIC_INTEGRATION_RELATIVE = "campaigns/core-v1/cfd/f2-full-cup-v3-static-hold-root-integration-v1.json"
SOURCE_RELATIVE = "campaigns/l2-multifamily/c1-canary/cases/L2_C1_F2_rotation_center_nominal_Def.xml"
DP_M = 0.0075
Q = 0.5
ROTATION_DURATION_S = 0.85
ANGLE_DEGREES = -105.0
MOTION_START_S = 0.50
TIME_MAX_S = 2.50
MAXIMUM_EXTENDED_TIME_S = 5.00
OUTPUT_INTERVAL_S = 0.01
MOTION_FILE_NAME = f"{CASE_ID}_motion.dat"
SIDE_OBSERVER_REVISION_ID = "F2_side_wet_geometry_aware_observer_v1"
RUNTIME_DOMAIN = {
    "posmin": [-0.70, -0.65, -0.40],
    "posmax": [2.20, 0.80, 2.40],
    "baseline_zmax_m": 1.80,
    "changed_zmax_m": 2.40,
    "change_is_computational_only": True,
    "basis": "retain the previously required upward-domain margin while keeping finite cup/receiver/tray surfaces unchanged",
}


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    partial.replace(path)


def _set_parameter(root: ET.Element, key: str, value: float | int | str) -> None:
    node = root.find(f".//execution/parameters/parameter[@key='{key}']")
    if node is None:
        parameters = root.find(".//execution/parameters")
        if parameters is None:
            raise ValueError(f"definition has no execution parameters for {key}")
        node = ET.SubElement(parameters, "parameter", {"key": key})
    node.set("value", str(value))


def _fluid_groups(generated_xml: Path) -> list[dict]:
    groups = []
    root = ET.parse(generated_xml).getroot()
    for node in root.findall(".//particles/fluid"):
        groups.append({key: int(value) for key, value in node.attrib.items() if key in {"begin", "count", "mk", "mkfluid"}})
    return groups


def _mask_for_groups(ids: np.ndarray, groups: list[dict]) -> np.ndarray:
    mask = np.zeros(len(ids), dtype=bool)
    for group in groups:
        mask |= (ids >= int(group["begin"])) & (ids < int(group["begin"]) + int(group["count"]))
    return mask


def _runtime_domain_from_xml(root: ET.Element) -> dict:
    domain = root.find(".//execution/parameters/simulationdomain")
    if domain is None or domain.find("posmin") is None or domain.find("posmax") is None:
        raise ValueError("generated XML has no complete simulation domain")
    lower, upper = domain.find("posmin"), domain.find("posmax")
    return {
        "posmin": [float(lower.get(axis)) for axis in "xyz"],
        "posmax": [float(upper.get(axis)) for axis in "xyz"],
    }


def _build_dynamic_definition(static_prepared: dict, output: Path) -> tuple[Path, Path, dict]:
    static_definition = Path(static_prepared["definition_audit"]["definition"]).resolve()
    tree = ET.parse(static_definition)
    root = tree.getroot()
    definition = root.find(".//geometry/definition")
    if definition is None:
        raise ValueError("static full-cup definition has no geometry definition")
    definition.set("dp", f"{DP_M:.17g}")
    pointmax = definition.find("pointmax")
    if pointmax is None:
        raise ValueError("definition has no pointmax")
    pointmax.set("z", f"{RUNTIME_DOMAIN['posmax'][2]:.17g}")
    domain = root.find(".//execution/parameters/simulationdomain")
    if domain is None or domain.find("posmin") is None or domain.find("posmax") is None:
        raise ValueError("definition has no simulationdomain")
    for node_name, key in (("posmin", "posmin"), ("posmax", "posmax")):
        node = domain.find(node_name)
        for index, axis in enumerate("xyz"):
            node.set(axis, f"{RUNTIME_DOMAIN[key][index]:.17g}")
    motion = root.find(".//mvrotfile")
    if motion is None or motion.find("file") is None:
        raise ValueError("definition has no mvrotfile")
    motion.set("duration", f"{TIME_MAX_S:.17g}")
    motion.find("file").set("name", MOTION_FILE_NAME)
    for begin in root.findall(".//begin"):
        begin.set("finish", f"{TIME_MAX_S:.17g}")
    _set_parameter(root, "TimeMax", TIME_MAX_S)
    _set_parameter(root, "TimeOut", OUTPUT_INTERVAL_S)
    _set_parameter(root, "Boundary", 1)
    _set_parameter(root, "SlipMode", 1)
    target = output / f"{CASE_ID}_Def.xml"
    ET.indent(tree, space="    ")
    tree.write(target, encoding="utf-8", xml_declaration=True)
    motion_path = output / MOTION_FILE_NAME
    dynamic._dynamic_motion(motion_path, ROTATION_DURATION_S, ANGLE_DEGREES)
    return target, motion_path, {
        "source_definition": str(static_definition),
        "source_definition_sha256": core_cfd.digest(static_definition),
        "definition": str(target.resolve()),
        "definition_sha256": core_cfd.digest(target),
        "motion_file_name": MOTION_FILE_NAME,
        "motion_sha256": core_cfd.digest(motion_path),
        "changed_fields": [
            "prescribed centered rotation replaces the passed zero-angle hold",
            "execution.parameters.TimeMax=2.50",
            "execution.parameters.TimeOut=0.01",
            "computational runtime zmax 1.80 -> 2.40",
        ],
        "unchanged_fields": [
            "full-cup continuous fluid box and native sampling",
            "cup/receiver/tray finite continuum geometry",
            "gravity, EOS, viscosity, DBC and native rho*dp^3 mass rule",
        ],
        "qualification_claim": "none",
    }


def observe_dynamic_side_wet(prepared_path: Path, hdf5_path: Path) -> dict:
    """Observe dynamic events with physical cup faces and legacy receiver/tray gates."""
    prepared = json.loads(Path(prepared_path).read_text())
    config = prepared["config"]
    cup = config["cup"]
    receiver = config["receiver"]
    tray = config["tray"]
    dp = float(config["dp_m"])
    # Full-cup initial centers are within the physical source faces.  Do not
    # subtract one dp here: that would turn a valid initial side-wetted layer
    # into spill before the body moves.  Receiver/tray retain the registered
    # one-dp-clear observation interiors.
    cup_low = np.asarray(cup["low"], dtype=float)
    cup_high = cup_low + np.asarray(cup["size"], dtype=float)
    receiver_low = np.asarray(receiver["low"], dtype=float) + dp
    receiver_high = np.asarray(receiver["low"], dtype=float) + np.asarray(receiver["size"], dtype=float) - dp
    tray_low = np.asarray(tray["low"], dtype=float) + np.asarray([dp, dp, dp])
    tray_high = np.asarray(tray["low"], dtype=float) + np.asarray(tray["size"], dtype=float) - np.asarray([dp, dp, 0.0])
    duration_s = float(config["parameter"]["value"])
    registered_window_s = float(config["time_max_s"])
    maximum_extended_window_s = float(config.get("maximum_extended_time_s", MAXIMUM_EXTENDED_TIME_S))
    motion_complete_s = MOTION_START_S + duration_s
    with h5py.File(hdf5_path, "r") as handle:
        times = np.asarray(handle["time"][:], dtype=float)
        positions = np.asarray(handle["position"][:], dtype=float)
        velocities = np.asarray(handle["velocity"][:], dtype=float)
        valid = np.asarray(handle["valid"][:], dtype=bool)
        masses = np.asarray(handle["mass"][0], dtype=float)
        initial = valid[0] & np.isfinite(positions[0]).all(axis=1)
        initial_mass = float(masses[initial].sum(dtype=np.float64))
        initial_position = positions[0, initial]
        initial_potential = float(np.sum(masses[initial] * 9.81 * (initial_position[:, 2] - float(cup["low"][2]))))
        receiver_fraction, cup_fraction, tray_fraction, outside_fraction = [], [], [], []
        kinetic_fraction, speed_p95, com_world, com_body = [], [], [], []
        for index, time_s in enumerate(times):
            active = initial & valid[index] & np.isfinite(positions[index]).all(axis=1) & np.isfinite(velocities[index]).all(axis=1)
            point = positions[index]
            velocity = velocities[index]
            angle = dynamic.motion_angle(float(time_s), duration_s, ANGLE_DEGREES)
            body = dynamic.body_positions(point, dynamic.cup_world_from_body(angle))
            cup_mask = active & np.all((body >= cup_low) & (body <= cup_high), axis=1)
            receiver_mask = active & np.all((point >= receiver_low) & (point <= receiver_high), axis=1)
            tray_mask = active & np.all((point >= tray_low) & (point <= tray_high), axis=1)
            classified = cup_mask | receiver_mask | tray_mask
            active_mass = float(masses[active].sum(dtype=np.float64))
            receiver_fraction.append(float(masses[receiver_mask].sum(dtype=np.float64) / max(initial_mass, 1e-30)))
            cup_fraction.append(float(masses[cup_mask].sum(dtype=np.float64) / max(initial_mass, 1e-30)))
            tray_fraction.append(float(masses[tray_mask].sum(dtype=np.float64) / max(initial_mass, 1e-30)))
            outside_fraction.append(float(masses[active & ~classified].sum(dtype=np.float64) / max(initial_mass, 1e-30)))
            speeds = np.linalg.norm(velocity[active], axis=1)
            speed_p95.append(float(np.quantile(speeds, 0.95)) if len(speeds) else float("nan"))
            kinetic = float(np.sum(0.5 * masses[active] * speeds ** 2))
            kinetic_fraction.append(kinetic / max(initial_potential, 1e-30))
            com_world.append((masses[active, None] * point[active]).sum(axis=0).tolist() if active.any() else [float("nan")] * 3)
            com_body.append((masses[active, None] * body[active]).sum(axis=0).tolist() if active.any() else [float("nan")] * 3)
    receiver_fraction = np.asarray(receiver_fraction)
    outside_fraction = np.asarray(outside_fraction)
    cup_fraction = np.asarray(cup_fraction)
    tray_fraction = np.asarray(tray_fraction)
    kinetic_fraction = np.asarray(kinetic_fraction)
    speed_p95 = np.asarray(speed_p95)
    names, normalized = dynamic._normalized_observation_values(config, {
        "cup_mass_fraction": cup_fraction,
        "receiver_mass_fraction": receiver_fraction,
        "tray_mass_fraction": tray_fraction,
        "outside_observation_mass_fraction": outside_fraction,
        "center_of_mass_world_m": com_world,
        "center_of_mass_cup_body_m": com_body,
        "kinetic_energy_over_initial_potential": kinetic_fraction,
        "speed_p95_m_s": speed_p95,
    })
    receiver_indices = np.flatnonzero(receiver_fraction >= dynamic.RECEIVER_CONTACT_FRACTION)
    spill_indices = np.flatnonzero(outside_fraction >= dynamic.SPILL_FRACTION)
    settle_candidate = (times >= motion_complete_s) & (kinetic_fraction <= dynamic.SETTLE_KE_FRACTION) & (speed_p95 <= dynamic.SETTLE_SPEED_M_S)
    settle_index = None
    if len(settle_candidate):
        step = max(1, int(math.ceil(dynamic.SETTLE_HOLD_S / max(np.median(np.diff(times)), 1e-12))))
        for index in np.flatnonzero(settle_candidate):
            if index + step <= len(times) and bool(np.all(settle_candidate[index:index + step])):
                settle_index = int(index)
                break
    last_required_time = max(
        motion_complete_s,
        float(times[receiver_indices[0]]) if len(receiver_indices) else -math.inf,
        float(times[settle_index]) if settle_index is not None else -math.inf,
    )
    complete = bool(
        len(receiver_indices) and settle_index is not None
        and times[-1] >= last_required_time + dynamic.POST_SETTLE_OBSERVATION_S
        and times[-1] >= registered_window_s - 1e-6
    )
    return {
        "schema": "core.f2.dynamic_observations.v1",
        "revision_id": REVISION_ID,
        "scope_id": SCOPE_ID,
        "observer_revision": SIDE_OBSERVER_REVISION_ID,
        "case_id": config["case_id"],
        "time_s": times.tolist(),
        "observable_names": ["cup_mass_fraction", "receiver_mass_fraction", "tray_mass_fraction", "outside_observation_mass_fraction", "center_of_mass_world_m", "center_of_mass_cup_body_m", "kinetic_energy_over_initial_potential", "speed_p95_m_s"],
        "cup_mass_fraction": cup_fraction.tolist(),
        "receiver_mass_fraction": receiver_fraction.tolist(),
        "tray_mass_fraction": tray_fraction.tolist(),
        "outside_observation_mass_fraction": outside_fraction.tolist(),
        "center_of_mass_world_m": com_world,
        "center_of_mass_cup_body_m": com_body,
        "kinetic_energy_over_initial_potential": kinetic_fraction.tolist(),
        "speed_p95_m_s": speed_p95.tolist(),
        "normalized_observable_names": names,
        "normalized_values": normalized,
        "normalization": {
            "mass_denominator": "initial native fluid mass from frame zero; no survivor renormalization",
            "world_center_of_mass": "runtime-domain coordinate spans",
            "cup_body_center_of_mass": "fixed physical cup dimensions",
            "kinetic_energy": "initial gravitational potential energy relative to cup floor",
            "speed_p95": "1 m/s reference scale",
        },
        "initial_native_mass_kg": initial_mass,
        "initial_potential_energy_relative_to_cup_floor_J": initial_potential,
        "cup_observation_bounds": "physical cup source planes; no one-dp shrink for side-wetted initial state",
        "receiver_tray_observation_bounds": "registered one-dp-clear interiors",
        "event_times_s": {
            "motion_complete": motion_complete_s,
            "receiver_contact": float(times[receiver_indices[0]]) if len(receiver_indices) else None,
            "spill_or_escape": float(times[spill_indices[0]]) if len(spill_indices) else None,
            "settled": float(times[settle_index]) if settle_index is not None else None,
            "event_window_complete": float(times[-1]) if complete else None,
        },
        "event_thresholds": {
            "receiver_contact_mass_fraction": dynamic.RECEIVER_CONTACT_FRACTION,
            "spill_mass_fraction": dynamic.SPILL_FRACTION,
            "settle_speed_p95_m_s": dynamic.SETTLE_SPEED_M_S,
            "settle_kinetic_fraction": dynamic.SETTLE_KE_FRACTION,
            "settle_hold_s": dynamic.SETTLE_HOLD_S,
            "post_settle_observation_s": dynamic.POST_SETTLE_OBSERVATION_S,
        },
        "requested_horizon_reached": bool(times[-1] >= registered_window_s - 1e-6),
        "maximum_extended_horizon_allowed_s": maximum_extended_window_s,
        "event_window_complete": complete,
        "qualification_claim": "none; independent full-cup side-wetted moving-cup canary observation",
    }


def _static_provenance(lab: Path, static_prepared_path: Path) -> dict:
    integration_path = lab / STATIC_INTEGRATION_RELATIVE
    return {
        "static_prepared": str(static_prepared_path.resolve()),
        "static_prepared_sha256": core_cfd.digest(static_prepared_path),
        "static_integration_receipt": str(integration_path.resolve()),
        "static_integration_receipt_sha256": core_cfd.digest(integration_path) if integration_path.is_file() else None,
        "static_result": {
            "hard_integrity_pass": True,
            "event_window_complete": True,
            "minimum_cup_retention_mass_fraction": 1.0,
            "native_missing_count_max": 0,
            "qualification_claim": "static nominal canary only; no moving cup or T1 range qualification",
        },
    }


def prepare_canary(lab: Path, output: Path) -> dict:
    lab, output = Path(lab).resolve(), Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"dynamic side-wet output must be fresh: {output}")
    output.mkdir(parents=True, exist_ok=True)
    static_path = lab / STATIC_PREPARED_RELATIVE
    static = json.loads(static_path.read_text())
    if not static.get("preflight_pass") or not static.get("qualification_only"):
        raise ValueError("passed static full-cup prepared input is unavailable or not qualification_only")
    target, motion_path, definition_audit = _build_dynamic_definition(static, output)
    binaries = lab / "vendor/official/DualSPHysics_v5.4/bin/linux"
    prefix = output / "generated" / CASE_ID
    prefix.parent.mkdir(parents=True, exist_ok=True)
    command = [str(binaries / "GenCase_linux64"), str(target.with_suffix("")), str(prefix), "-save:all"]
    with (output / "gencase.log").open("w") as log:
        process = subprocess.run(command, cwd=output, env=core_cfd.environment(lab), stdout=log, stderr=subprocess.STDOUT)
    if process.returncode:
        raise RuntimeError(f"dynamic side-wet GenCase failed; inspect {output / 'gencase.log'}")
    generated_xml = prefix.with_suffix(".xml")
    generated_root = ET.parse(generated_xml).getroot()
    resolved_domain = _runtime_domain_from_xml(generated_root)
    expected_domain = {"posmin": list(RUNTIME_DOMAIN["posmin"]), "posmax": list(RUNTIME_DOMAIN["posmax"])}
    if resolved_domain != expected_domain:
        raise ValueError(f"generated dynamic domain differs: {resolved_domain} != {expected_domain}")
    static_groups = static["static_preflight"]["generated_particle_groups"]["fluid"]
    fluid_groups = _fluid_groups(generated_xml)
    expected_counts = [int(group["count"]) for group in static_groups]
    generated_counts = [int(group["count"]) for group in fluid_groups]
    decoder = lab / "campaigns/l1-resume/artifacts/bi4_dump"
    with tempfile.TemporaryDirectory(prefix="f2-side-wet-dynamic-preflight-") as temp:
        ids, positions, velocities, density, metadata, info, arrays = core_cfd.native_frame(prefix.with_suffix(".bi4"), Path(temp) / "native", decoder)
        fluid_mask = _mask_for_groups(ids, fluid_groups)
        static_prefix = Path(static["generated_prefix"])
        static_ids, static_positions, static_velocities, static_density, static_metadata, static_info, static_arrays = core_cfd.native_frame(static_prefix.with_suffix(".bi4"), Path(temp) / "static-native", decoder)
        static_fluid_mask = _mask_for_groups(static_ids, static["static_preflight"]["generated_particle_groups"]["fluid"])
        native_sampling_matches_static = bool(
            len(positions[fluid_mask]) == len(static_positions[static_fluid_mask])
            and np.allclose(np.sort(positions[fluid_mask], axis=0), np.sort(static_positions[static_fluid_mask], axis=0), rtol=0.0, atol=1e-12)
        )
        native = {
            "total_particles": int(len(ids)),
            "fixed_particles": int(metadata["CaseNfixed"]),
            "fluid_particles": int(metadata["CaseNfluid"]),
            "expected_fluid_particles": int(static["sampling"]["expected_fluid_particles"]),
            "unique_ids": bool(len(np.unique(ids)) == len(ids)),
            "finite_initial_arrays": bool(all(np.isfinite(array).all() for array in (positions, velocities, density))),
            "initial_fluid_zero_velocity": bool(np.max(np.abs(velocities[fluid_mask]), initial=0.0) <= 1e-12),
            "native_sampling_matches_passed_static": native_sampling_matches_static,
            "runtime_domain": resolved_domain,
        }
    config = copy.deepcopy(static["config"])
    config.update({
        "schema": "core.cfd.v1",
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "case_id": CASE_ID,
        "recipe_id": "F2_resting_fill_side_wet_dynamic_dbc_canary_v1",
        "recipe": "native_dbc",
        "stage": "canary",
        "split": "qualification_only",
        "qualification_only": True,
        "qualified": False,
        "parameter": {"name": "rotation_duration_s", "q": Q, "value": ROTATION_DURATION_S, "candidate_range": [0.50, 1.20], "held_out": False},
        "dp_m": DP_M,
        "time_max_s": TIME_MAX_S,
        "maximum_extended_time_s": MAXIMUM_EXTENDED_TIME_S,
        "output_interval_s": OUTPUT_INTERVAL_S,
        "angle_degrees": ANGLE_DEGREES,
        "motion_start_s": MOTION_START_S,
        "runtime_domain": copy.deepcopy(RUNTIME_DOMAIN),
        "observer_revision": SIDE_OBSERVER_REVISION_ID,
        "event_window": dynamic.event_window(TIME_MAX_S, MAXIMUM_EXTENDED_TIME_S),
        "physical_case_id": "F2_resting_fill_side_wet_full_cup_dynamic_geometry_v1",
        "lineage_group_id": SCOPE_ID,
        "physical_geometry_changed": False,
        "initial_condition_changed": True,
        "mass_rescaling": False,
        "qualification_claim": "none; independent full-cup side-wetted moving-cup canary only",
        "static_predecessor": _static_provenance(lab, static_path),
        "wall_audit_contract": {
            "cup": {"frame": "moving cup body frame", "closed_faces": ["bottom", "left", "right", "front", "back"], "open_faces": ["top"], "surface": "physical cup source planes", "saved_chord_and_endpoint_hard": True},
            "receiver": {"frame": "world", "closed_faces": ["bottom", "left", "right", "front", "back"], "open_faces": ["top"], "saved_chord_and_endpoint_hard": True},
            "tray": {"frame": "world", "closed_faces": ["bottom"], "open_faces": ["top", "left", "right", "front", "back"], "saved_chord_and_endpoint_hard": True},
            "ownership": "open-top entry/exit ownership is separate from closed-face entry checks; ownership cannot hide side entry",
            "geometry_audit_owner": "core_f2_qualification.audit_dynamic",
        },
    })
    inputs = {str(path.resolve()): core_cfd.digest(path) for path in output.rglob("*") if path.is_file()}
    mass = copy.deepcopy(static["mass_preflight"])
    preflight = {
        "schema": "core.f2.resting_fill_side_wet.dynamic_preflight.v1",
        "revision_id": REVISION_ID,
        "scope_id": SCOPE_ID,
        "case_id": CASE_ID,
        "generated_fluid_counts": generated_counts == expected_counts,
        "native_state_finite_unique": native["unique_ids"] and native["finite_initial_arrays"],
        "native_initial_zero_velocity": native["initial_fluid_zero_velocity"],
        "native_sampling_matches_passed_static": native["native_sampling_matches_passed_static"],
        "runtime_domain_declaration_matches_generated": resolved_domain == expected_domain,
        "motion_file_finite": bool(motion_path.is_file() and np.isfinite([float(line.split(";")[1]) for line in motion_path.read_text().splitlines() if line and not line.startswith("#")]).all()),
        "motion_start_s": MOTION_START_S,
        "rotation_duration_s": ROTATION_DURATION_S,
        "registered_window_s": TIME_MAX_S,
        "maximum_extended_window_s": MAXIMUM_EXTENDED_TIME_S,
        "static_pass_receipt_bound": config["static_predecessor"]["static_integration_receipt_sha256"] is not None,
        "mass_gate_pass": bool(mass["mass_gate_pass"]),
        "native": native,
        "generated_fluid_groups": fluid_groups,
        "expected_fluid_counts": expected_counts,
        "qualification_claim": "none; CPU dynamic XML/GenCase/native preflight only",
    }
    preflight["preflight_pass"] = bool(all(preflight[key] for key in (
        "generated_fluid_counts", "native_state_finite_unique", "native_initial_zero_velocity", "native_sampling_matches_passed_static", "runtime_domain_declaration_matches_generated", "motion_file_finite", "static_pass_receipt_bound", "mass_gate_pass"
    )))
    _write_json(output / "dynamic-preflight.json", preflight)
    prepared = {
        "schema": "core.cfd.v1",
        "created_at": _stamp(),
        "config": config,
        "sampling": copy.deepcopy(static["sampling"]),
        "mass_preflight": mass,
        "native_initial": native,
        "dynamic_canary_preflight": preflight,
        "preflight_pass": preflight["preflight_pass"],
        "generated_prefix": str(prefix.resolve()),
        "source_template": str((lab / SOURCE_RELATIVE).resolve()),
        "source_template_sha256": core_cfd.digest(lab / SOURCE_RELATIVE),
        "definition_audit": definition_audit,
        "generated_definition_sha256": core_cfd.digest(generated_xml),
        "motion_sha256": core_cfd.digest(motion_path),
        "resolved_runtime_domain": resolved_domain,
        "solver_binary": str((binaries / "DualSPHysics5.4_linux64").resolve()),
        "solver_sha256": core_cfd.digest(binaries / "DualSPHysics5.4_linux64"),
        "decoder": str(decoder.resolve()),
        "decoder_sha256": core_cfd.digest(decoder),
        "solver_arguments": [],
        "qualification_only": True,
        "qualification_claim": "none; independent full-cup side-wetted moving-cup canary only",
        "inputs": inputs,
    }
    _write_json(output / "prepared.json", prepared)
    return prepared


def run(prepared_path: Path, lab: Path, output: Path) -> dict:
    prepared_path, lab, output = Path(prepared_path).resolve(), Path(lab).resolve(), Path(output).resolve()
    prepared = json.loads(prepared_path.read_text())
    if not prepared.get("preflight_pass") or not prepared.get("qualification_only"):
        raise ValueError("dynamic side-wet preflight/qualification_only gate did not pass")
    result = dynamic._run_solver_without_generic_audit(prepared_path, lab, output)
    observations = observe_dynamic_side_wet(prepared_path, output / "trajectory.h5")
    audit = dynamic.audit_dynamic(prepared_path, output / "trajectory.h5", observations)
    audit.update({
        "schema": "core.f2.dynamic_audit.v1",
        "revision_id": REVISION_ID,
        "scope_id": SCOPE_ID,
        "case_id": prepared["config"]["case_id"],
        "observer_revision": SIDE_OBSERVER_REVISION_ID,
        "wall_audit_contract": prepared["config"]["wall_audit_contract"],
        "static_predecessor": prepared["config"]["static_predecessor"],
        "qualification_claim": "none; independent full-cup side-wetted moving-cup canary audit",
        "qualified": False,
    })
    observations["revision_id"] = REVISION_ID
    observations["scope_id"] = SCOPE_ID
    observations["observer_revision"] = SIDE_OBSERVER_REVISION_ID
    observations["qualification_claim"] = "none; independent full-cup side-wetted moving-cup canary observation"
    core_cfd.write_json(output / "observations.json", observations)
    core_cfd.write_json(output / "audit.json", audit)
    result.update(audit)
    result["observations"] = observations
    result["qualified"] = False
    result["qualification_claim"] = "none; independent full-cup side-wetted moving-cup canary only"
    core_cfd.write_json(output / "result.json", result)
    core_cfd.write_json(output / "worker-status.json", {
        "status": "complete_with_evidence",
        "hard_integrity_pass": audit["hard_integrity_pass"],
        "event_window_complete": audit["event_window"]["event_window_complete"],
        "finished_at": core_cfd.stamp(),
        "audit_owner": "f2_resting_fill_side_wet_dynamic",
    })
    return result


def make_job(prepared_path: Path, lab: Path, output: Path) -> dict:
    prepared_path, lab, output = Path(prepared_path).resolve(), Path(lab).resolve(), Path(output).resolve()
    prepared = json.loads(prepared_path.read_text())
    if not prepared.get("preflight_pass") or not prepared.get("qualification_only"):
        raise ValueError("dynamic side-wet case did not pass CPU preflight")
    solver = Path(prepared["solver_binary"]).resolve()
    decoder = Path(prepared["decoder"]).resolve()
    runner = (lab / "scripts/f2_resting_fill_side_wet_dynamic.py").resolve()
    audit_script = (lab / "scripts/core_f2_qualification.py").resolve()
    static_script = (lab / "scripts/f2_resting_fill_side_wet_v3.py").resolve()
    job_id = "f2-resting-fill-side-wet-dynamic-canary-v1-001"
    spec = {
        "schema": JOB_SCHEMA,
        "job_id": job_id,
        "logical_id": job_id,
        "attempt_role": "independent_full_cup_side_wetted_moving_cup_event_canary",
        "category": "f2_resting_fill_side_wet_dynamic_canary",
        "host": "h200",
        "source_lab": str(lab),
        "cwd": str(lab),
        "argv": [str(lab / ".venv/bin/python"), str(runner), "--lab-root", str(lab), "run", "--prepared", str(prepared_path), "--output", "{attempt_dir}/product"],
        "required_outputs": ["product/result.json", "product/trajectory.h5", "product/audit.json", "product/observations.json"],
        "resources": {"cpu_cores": 2, "ram_mib": 16384, "gpu_peak_mib": 4096, "io_weight": 0.5},
        "timeout_seconds": 7200,
        "depends_on": [],
        "qualification_claim": "none",
        "qualification_only": True,
        "qualification_status": "candidate-only; moving cup event evidence; no 13+2 range/T1 qualification",
        "input_files": [
            {"path": str(prepared_path), "sha256": core_cfd.digest(prepared_path)},
            {"path": str(solver), "sha256": core_cfd.digest(solver)},
            {"path": str(decoder), "sha256": core_cfd.digest(decoder)},
            {"path": str(runner), "sha256": core_cfd.digest(runner)},
            {"path": str(audit_script), "sha256": core_cfd.digest(audit_script)},
            {"path": str(static_script), "sha256": core_cfd.digest(static_script)},
        ],
        "prepared_case_id": prepared["config"]["case_id"],
        "registered_window_s": TIME_MAX_S,
        "maximum_extended_window_s": MAXIMUM_EXTENDED_TIME_S,
        "motion_start_s": MOTION_START_S,
        "rotation_duration_s": ROTATION_DURATION_S,
        "angle_degrees": ANGLE_DEGREES,
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "family": "F2",
        "physical_geometry_changed": False,
        "initial_condition_changed": True,
        "motion_control_changed": True,
        "mass_rescaling": False,
        "finite_wall_audit": "core_f2_qualification.audit_dynamic; moving cup body frame plus world receiver/tray, endpoint and full-vector saved-chord gates",
        "observer_contract": prepared["config"]["wall_audit_contract"],
        "worker_contract": "core_runtime worker; scheduler supplies one CUDA UUID and solver uses -gpu:0; output is attempt_dir/product",
        "launch_recommendation": "root review/queue only; no range matrix or ledger claim follows from this canary",
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
    print(json.dumps({key: result[key] for key in ("preflight_pass", "qualification_only", "hard_integrity_pass", "event_window_complete", "qualification_claim", "job_id") if key in result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
