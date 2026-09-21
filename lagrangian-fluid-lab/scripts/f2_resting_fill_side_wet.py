#!/usr/bin/env python3
"""Prepare an independent F2 side-wetted resting-fill candidate.

The retained resting-fill failure has a fluid footprint 4.25--5.25 cm from
the physical cup faces.  This candidate keeps the cup continuum geometry and
native mass rule, expands the continuous liquid footprint to the cup walls,
and lowers the liquid column to preserve the original continuum volume.  It
is a new physical initial-condition scope; it does not inherit any F2 result
and this module never launches a GPU worker during preparation.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

import numpy as np
from scipy.spatial import cKDTree

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from scripts import core_cfd
from scripts import core_f2_resting_fill as base_observer


SCHEMA = "core.f2.resting_fill_side_wet.v1"
JOB_SCHEMA = "core.cfd.job.v1"
REVISION_ID = "F2_resting_fill_side_wet_v1"
SCOPE_ID = "F2_resting_fill_side_wet_x_v1"
CASE_ID = "CORE_F2_resting_fill_side_wet_q0p50000000_dp0p007500000000_canary"
SOURCE_RELATIVE = "campaigns/l2-multifamily/c1-canary/cases/L2_C1_F2_rotation_center_nominal_Def.xml"
MOTION_NAME = "CORE_F2_resting_fill_side_wet_zero_motion.dat"
DP_M = 0.0075
TIME_MAX_S = 0.60
DRIVE_START_S = 0.50
OUTPUT_INTERVAL_S = 0.02
TARGET_FIRST_CENTER = [0.010, -0.130, 0.660]
SOURCE_DRAW_POINT = [0.01125, -0.13125, 0.66125]
SOURCE_DRAW_SIZE = [0.405, 0.2625, 0.2025]
NATIVE_COUNTS = [55, 36, 28]
CONTINUUM_BOX = {
    "low": [0.010, -0.130, 0.660],
    "size": [0.405, 0.270, 0.2157750342935528],
    "mkfluid": 0,
}
CUP = {"low": [0.0, -0.15, 0.65], "size": [0.425, 0.30, 0.45], "mkbound": 0}
RECEIVER = {"low": [0.45, -0.30, 0.0], "size": [1.10, 0.60, 0.45], "mkbound": 1}
TRAY = {"low": [-0.60, -0.55, -0.20], "size": [2.60, 1.10, 0.10], "mkbound": 2}


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    partial.replace(path)


def _zero_motion(path: Path) -> None:
    times = np.arange(0.0, TIME_MAX_S + OUTPUT_INTERVAL_S / 2.0, OUTPUT_INTERVAL_S)
    path.write_text("#Time;Degrees\n" + "\n".join(f"{t:.6f};0.000000000" for t in times) + "\n")


def _set_parameter(root: ET.Element, key: str, value: float | int | str) -> None:
    parameters = root.find(".//execution/parameters")
    if parameters is None:
        raise ValueError("source definition has no execution parameters")
    node = parameters.find(f"parameter[@key='{key}']")
    if node is None:
        node = ET.SubElement(parameters, "parameter", {"key": key})
    node.set("value", str(value))


def _rewrite_definition(source: Path, target: Path, motion_name: str) -> dict:
    tree = ET.parse(source)
    root = tree.getroot()
    for key, value in {
        "SavePosDouble": 2,
        "Boundary": 1,
        "SlipMode": 1,
        "TimeMax": TIME_MAX_S,
        "TimeOut": OUTPUT_INTERVAL_S,
        "PartsOutMax": 1,
    }.items():
        _set_parameter(root, key, value)
    definition = root.find(".//geometry/definition")
    if definition is None:
        raise ValueError("source definition has no geometry definition")
    definition.set("dp", f"{DP_M:.17g}")
    commands = root.find(".//geometry/commands/mainlist")
    if commands is None:
        raise ValueError("source definition has no mainlist")
    nodes = list(commands)
    kept = []
    index = 0
    while index < len(nodes):
        node = nodes[index]
        if node.tag == "setmkfluid":
            index += 1
            if index >= len(nodes) or nodes[index].tag != "drawbox":
                raise ValueError("fluid source command is not setmkfluid followed by drawbox")
            index += 1
            continue
        kept.append(node)
        index += 1
    commands[:] = kept
    ET.SubElement(commands, "setmkfluid", {"mk": "0"})
    drawbox = ET.SubElement(commands, "drawbox")
    ET.SubElement(drawbox, "boxfill").text = "solid"
    ET.SubElement(drawbox, "point", {axis: f"{value:.17g}" for axis, value in zip("xyz", SOURCE_DRAW_POINT)})
    ET.SubElement(drawbox, "size", {axis: f"{value:.17g}" for axis, value in zip("xyz", SOURCE_DRAW_SIZE)})
    motion = root.find(".//mvrotfile")
    if motion is None:
        raise ValueError("source definition has no rotation motion")
    motion.set("duration", f"{TIME_MAX_S:.17g}")
    motion_file = motion.find("file")
    if motion_file is None:
        raise ValueError("source rotation has no file")
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
            "one full-footprint fluid drawbox replacing three inset fluid boxes",
            "continuous liquid height selected to preserve prior 0.023595 m3 volume",
            "execution.parameters.TimeMax=0.60",
            "execution.parameters.TimeOut=0.02",
            "prescribed rotation file: all angles zero",
        ],
        "unchanged_fields": [
            "cup/receiver/tray finite continuum geometry",
            "gravity, density, EOS, viscosity and DBC recipe",
            "native rho*dp^3 mass policy and no mass rescaling",
        ],
        "qualification_claim": "none",
    }


def _groups(path: Path) -> tuple[list[dict], list[dict]]:
    root = ET.parse(path).getroot()
    fixed, fluid = [], []
    for node in root.findall(".//particles/*"):
        if node.tag not in {"fixed", "moving", "fluid"}:
            continue
        item = {}
        for key, value in node.attrib.items():
            item[key] = int(value) if key in {"begin", "count", "mk", "mkbound", "mkfluid"} else value
        (fluid if node.tag == "fluid" else fixed).append(item)
    return fixed, fluid


def _select(ids: np.ndarray, begin: int, count: int) -> np.ndarray:
    return (ids >= begin) & (ids < begin + count)


def _preflight(lab: Path, generated_xml: Path, prefix: Path) -> dict:
    fixed, fluid = _groups(generated_xml)
    expected_count = int(np.prod(NATIVE_COUNTS))
    generated_counts = [int(item["count"]) for item in fluid]
    decoder = lab / "campaigns/l1-resume/artifacts/bi4_dump"
    with tempfile.TemporaryDirectory(prefix="f2-side-wet-preflight-") as temp:
        ids, positions, velocities, density, metadata, info, arrays = core_cfd.native_frame(
            prefix.with_suffix(".bi4"), Path(temp) / "native", decoder
        )
        fluid_mask = np.zeros(len(ids), dtype=bool)
        for item in fluid:
            fluid_mask |= _select(ids, int(item["begin"]), int(item["count"]))
        moving = next(item for item in fixed if item.get("mkbound") == 0)
        cup_mask = _select(ids, int(moving["begin"]), int(moving["count"]))
        fluid_positions = positions[fluid_mask]
        cup_positions = positions[cup_mask]
        cup_low = np.asarray(CUP["low"], dtype=float)
        cup_high = cup_low + np.asarray(CUP["size"], dtype=float)
        inside = np.all((fluid_positions >= cup_low) & (fluid_positions <= cup_high), axis=1)
        face_clearance = np.min(np.concatenate((fluid_positions - cup_low, cup_high - fluid_positions), axis=1), axis=1)
        nearest = cKDTree(cup_positions).query(fluid_positions, k=1)[0]
        generated_pass = generated_counts == [expected_count] and len(fluid) == 1
        checks = {
            "generated_fluid_count": generated_pass,
            "native_fluid_count": int(metadata["CaseNfluid"]) == expected_count == int(fluid_positions.shape[0]),
            "native_ids_unique_finite": bool(len(np.unique(ids)) == len(ids) and np.isfinite(positions).all() and np.isfinite(velocities).all() and np.isfinite(density).all()),
            "native_initial_zero_velocity": bool(np.max(np.abs(velocities[fluid_mask]), initial=0.0) <= 1e-12),
            "fluid_inside_physical_cup": bool(inside.all()),
            "target_native_position_bounds": bool(
                np.allclose(fluid_positions.min(axis=0), TARGET_FIRST_CENTER, atol=1e-10)
                and np.allclose(fluid_positions.max(axis=0), [0.415, 0.1325, 0.8625], atol=1e-10)
            ),
            "native_boundary_present": int(cup_positions.shape[0]) == int(moving["count"]),
            "positive_fluid_to_boundary_center_distance": bool(np.min(nearest, initial=np.inf) > 0.0),
            "side_wall_within_native_smoothing_support": bool(
                float(np.min(nearest)) <= float(metadata["H"]) and
                float(fluid_positions[:, 0].min() - cup_low[0]) <= 2 * DP_M and
                float(cup_high[0] - fluid_positions[:, 0].max()) <= 2 * DP_M and
                float(fluid_positions[:, 1].min() - cup_low[1]) <= 3 * DP_M and
                float(cup_high[1] - fluid_positions[:, 1].max()) <= 3 * DP_M
            ),
        }
        return {
            "schema": "core.f2.resting_fill_side_wet.static_preflight.v1",
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
                "fixed_particles": int(metadata["CaseNfixed"]),
                "fluid_particles": int(metadata["CaseNfluid"]),
                "native_fluid_mass_kg": float(metadata["MassFluid"]) * int(metadata["CaseNfluid"]),
                "dp_m": float(metadata["Dp"]),
                "smoothing_length_m": float(metadata["H"]),
            },
            "continuum_cup_bounds_m": {"low": cup_low.tolist(), "high": cup_high.tolist()},
            "continuum_fluid_box": copy.deepcopy(CONTINUUM_BOX),
            "native_fluid_position_bounds_m": {"low": fluid_positions.min(axis=0).tolist(), "high": fluid_positions.max(axis=0).tolist()},
            "native_cup_boundary_position_bounds_m": {"low": cup_positions.min(axis=0).tolist(), "high": cup_positions.max(axis=0).tolist()},
            "physical_face_clearance_m": {
                "bottom": float(fluid_positions[:, 2].min() - cup_low[2]),
                "left": float(fluid_positions[:, 0].min() - cup_low[0]),
                "right": float(cup_high[0] - fluid_positions[:, 0].max()),
                "front": float(fluid_positions[:, 1].min() - cup_low[1]),
                "back": float(cup_high[1] - fluid_positions[:, 1].max()),
                "top": float(cup_high[2] - fluid_positions[:, 2].max()),
            },
            "minimum_native_cup_boundary_center_distance_m": float(np.min(nearest)),
            "maximum_initial_speed_m_s": float(np.linalg.norm(velocities[fluid_mask], axis=1).max(initial=0.0)),
            "particle_count": int(fluid_positions.shape[0]),
            "generated_particle_groups": {"fixed": fixed, "fluid": fluid},
            "checks": checks,
            "preflight_pass": bool(all(checks.values())),
            "no_overlap_definition": "all fluid centers are inside the fixed continuum cup bounds, have positive distance from generated cup particles, and the side faces are within the declared native support candidate; no mass or geometry rescaling",
        }


def _config(preflight_path: Path) -> dict:
    return {
        "schema": "core.cfd.v1",
        "family": "F2",
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "case_id": CASE_ID,
        "recipe_id": "F2_resting_fill_side_wet_dbc_native_v1",
        "recipe": "native_dbc",
        "stage": "repair_canary",
        "split": "qualification_only",
        "qualification_only": True,
        "parameter": {"name": "initial_condition_variant", "value": "side_wet_fixed_volume", "range": ["side_wet_fixed_volume"]},
        "dp_m": DP_M,
        "cfl": 0.2,
        "time_max_s": TIME_MAX_S,
        "output_interval_s": OUTPUT_INTERVAL_S,
        "source_definition": SOURCE_RELATIVE,
        "physical_case_id": "F2_resting_fill_side_wet_fixed_volume_geometry_v1",
        "lineage_group_id": SCOPE_ID,
        "paired_background_id": "F2_resting_fill_side_wet_no_pair",
        "view_id": "world_fluid_particle_v1",
        "control_semantics": "cup fixed at zero angle; static hold covers the original 0.50 s drive-start time",
        "source_label_semantics": "single initial Mk is a numerical source partition; not material truth",
        "cup": copy.deepcopy(CUP),
        "receiver": copy.deepcopy(RECEIVER),
        "tray": copy.deepcopy(TRAY),
        "fluid_boxes": [copy.deepcopy(CONTINUUM_BOX)],
        "wall_bounds": {"xmin": -0.70, "xmax": 2.20, "ymin": -0.65, "ymax": 0.80, "zmin": -0.40, "zmax": 1.80},
        "runtime_domain": {"posmin": [-0.70, -0.65, -0.40], "posmax": [2.20, 0.80, 1.80]},
        "initial_condition": {
            "variant": "side_wet_fixed_volume",
            "continuum_wall_geometry_changed": False,
            "fluid_initial_condition_changed": True,
            "side_wetted_candidate": True,
            "continuous_volume_m3": float(np.prod(CONTINUUM_BOX["size"])),
            "predecessor_continuous_volume_m3": 0.023595,
            "target_first_native_fluid_center_m": TARGET_FIRST_CENTER,
            "native_particle_count_not_inherited": True,
            "mass_rescaling": False,
            "predecessor_side_clearances_m": {"left": 0.055, "right": 0.055, "front": 0.0425, "back": 0.0475},
            "predecessor_open_top_escape_fraction_max": 0.024396328967299295,
            "predecessor_pre_motion_escape_fraction_max": 0.04006058986010871,
            "preflight_artifact": str(preflight_path.resolve()),
        },
        "static_hold": {
            "drive_start_s": DRIVE_START_S,
            "requested_horizon_s": TIME_MAX_S,
            "settled_speed_p95_m_s_max": 0.10,
            "settled_kinetic_over_initial_potential_max": 0.05,
            "settled_hold_s": 0.20,
            "cup_retention_gate": 1.0,
            "event_window_complete_requires_settled": True,
        },
        "qualification_inheritance": "none; independent side-wetted initial-condition scope",
        "qualification_claim": "none; independent side-wetted static-hold canary only",
        "qualified": False,
    }


def prepare_canary(lab: Path, output: Path) -> dict:
    lab, output = Path(lab).resolve(), Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"side-wet output must be fresh: {output}")
    output.mkdir(parents=True, exist_ok=True)
    source = lab / SOURCE_RELATIVE
    definition = output / f"{CASE_ID}_Def.xml"
    definition_audit = _rewrite_definition(source, definition, MOTION_NAME)
    motion = output / MOTION_NAME
    _zero_motion(motion)
    binaries = lab / "vendor/official/DualSPHysics_v5.4/bin/linux"
    prefix = output / "generated" / CASE_ID
    prefix.parent.mkdir(parents=True, exist_ok=True)
    command = [str(binaries / "GenCase_linux64"), str(definition.with_suffix("")), str(prefix), "-save:all"]
    with (output / "gencase.log").open("w") as log:
        process = subprocess.run(command, cwd=output, env=core_cfd.environment(lab), stdout=log, stderr=subprocess.STDOUT)
    if process.returncode:
        raise RuntimeError(f"GenCase failed; inspect {output / 'gencase.log'}")
    generated_xml = prefix.with_suffix(".xml")
    preflight = _preflight(lab, generated_xml, prefix)
    sampling = {
        "fluid_boxes": [{
            "continuous_low_m": list(CONTINUUM_BOX["low"]),
            "continuous_size_m": list(CONTINUUM_BOX["size"]),
            "first_center_m": list(TARGET_FIRST_CENTER),
            "draw_size_m": list(SOURCE_DRAW_SIZE),
            "counts": list(NATIVE_COUNTS),
            "particle_count": int(np.prod(NATIVE_COUNTS)),
            "continuous_mass_kg": float(np.prod(CONTINUUM_BOX["size"]) * 1000.0),
            "discrete_mass_kg": float(np.prod(NATIVE_COUNTS) * DP_M ** 3 * 1000.0),
            "mkfluid": 0,
            "native_cell_centre_sampling": True,
            "source_draw_point_m": list(SOURCE_DRAW_POINT),
            "source_draw_size_m": list(SOURCE_DRAW_SIZE),
        }],
        "expected_fluid_particles": int(np.prod(NATIVE_COUNTS)),
        "continuous_mass_kg": float(np.prod(CONTINUUM_BOX["size"]) * 1000.0),
        "sampled_mass_kg": float(np.prod(NATIVE_COUNTS) * DP_M ** 3 * 1000.0),
        "mass_policy": "native rho*dp^3, no mass rescaling",
    }
    mass = core_cfd.mass_quality(sampling)
    preflight["mass_preflight"] = mass
    preflight["preflight_pass"] = bool(preflight["preflight_pass"] and mass["mass_gate_pass"])
    _write_json(output / "static-preflight.json", preflight)
    config = _config(output / "static-preflight.json")
    config["definition_audit"] = definition_audit
    config["sampling_rule"] = "full side-wetted native cell-centre footprint, fixed continuum volume, native rho*dp^3, no rescaling"
    solver = binaries / "DualSPHysics5.4_linux64"
    decoder = lab / "campaigns/l1-resume/artifacts/bi4_dump"
    inputs = {str(path.resolve()): core_cfd.digest(path) for path in output.rglob("*") if path.is_file()}
    prepared = {
        "schema": "core.cfd.v1",
        "created_at": _stamp(),
        "config": config,
        "sampling": sampling,
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
        "qualification_claim": "none; independent side-wetted resting-fill static-hold canary only",
    }
    _write_json(output / "prepared.json", prepared)
    return prepared


def run(prepared_path: Path, lab: Path, output: Path) -> dict:
    prepared = json.loads(Path(prepared_path).read_text())
    if not prepared.get("preflight_pass") or not prepared.get("qualification_only"):
        raise ValueError("side-wet preflight/qualification_only gate did not pass")
    result = core_cfd.run(Path(prepared_path), Path(lab), Path(output))
    observations = base_observer.observe_static_hold(Path(prepared_path), Path(output) / "trajectory.h5")
    observations["revision_id"] = REVISION_ID
    observations["case_id"] = prepared["config"]["case_id"]
    audit = {
        "schema": "core.f2.resting_fill_side_wet.audit.v1",
        "revision_id": REVISION_ID,
        "case_id": prepared["config"]["case_id"],
        "family": "F2",
        "prepared_sha256": core_cfd.digest(Path(prepared_path)),
        "trajectory_sha256": core_cfd.digest(Path(output) / "trajectory.h5"),
        "static_hold_observation": observations,
        "hard_checks": observations["hard_checks"],
        "hard_integrity_pass": observations["hard_integrity_pass"],
        "requested_horizon_reached": observations["requested_horizon_reached"],
        "pre_motion_window_reached": observations["pre_motion_window_reached"],
        "static_settled": observations["static_settled"],
        "event_window_complete": observations["event_window_complete"],
        "qualified": False,
        "qualification_claim": "none; independent side-wetted static-hold canary audit",
    }
    _write_json(Path(output) / "observations.json", observations)
    _write_json(Path(output) / "audit.json", audit)
    result.update(audit)
    result["observations"] = observations
    result["qualified"] = False
    result["qualification_claim"] = "none; independent side-wetted static-hold canary only"
    _write_json(Path(output) / "result.json", result)
    return result


def make_job(prepared_path: Path, lab: Path, output: Path) -> dict:
    prepared_path, lab, output = Path(prepared_path).resolve(), Path(lab).resolve(), Path(output).resolve()
    prepared = json.loads(prepared_path.read_text())
    if not prepared.get("preflight_pass") or not prepared.get("qualification_only"):
        raise ValueError("side-wet preflight/qualification_only gate did not pass")
    solver = Path(prepared["solver_binary"]).resolve()
    decoder = Path(prepared["decoder"]).resolve()
    script = (lab / "scripts/f2_resting_fill_side_wet.py").resolve()
    observer_script = (lab / "scripts/core_f2_resting_fill.py").resolve()
    spec = {
        "schema": JOB_SCHEMA,
        "job_id": "f2-resting-fill-side-wet-canary-v1-001",
        "logical_id": "f2-resting-fill-side-wet-canary-v1-001",
        "attempt_role": "independent_side_wetted_initial_condition_static_hold",
        "category": "f2_resting_fill_side_wet_canary",
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
        "qualification_status": "candidate-only; independent side-wetted initial condition; no moving-cup/range qualification",
        "input_files": [
            {"path": str(prepared_path), "sha256": core_cfd.digest(prepared_path)},
            {"path": str(solver), "sha256": core_cfd.digest(solver)},
            {"path": str(decoder), "sha256": core_cfd.digest(decoder)},
            {"path": str(script), "sha256": core_cfd.digest(script)},
            {"path": str(observer_script), "sha256": core_cfd.digest(observer_script)},
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
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare-canary")
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("make-job")
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("run")
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
