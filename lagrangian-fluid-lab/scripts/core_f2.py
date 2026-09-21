#!/usr/bin/env python3
"""CPU preparation and bounded worker contract for the F2 static cup hold.

This is a minimal substitute canary for the F2 rotating-cup family.  It keeps
the finite cup, receiver and tray geometry from the registered F2 source, but
freezes the prescribed cup angle at zero.  The static hold checks native mass,
finite identities, cup retention and the full requested horizon.  It is
evidence for a later moving-cup design, never an F2 qualification receipt.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import h5py
import numpy as np

SOURCE_ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(SOURCE_ROOT))

from scripts.core_cfd import (digest, environment, mass_quality, native_frame,
                               run as native_run, write_json)


SCHEMA = "core.f2.static_hold.v1"
JOB_SCHEMA = "core.cfd.job.v1"
REVISION_ID = "F2_H0_static_cup_hold_v1"
CASE_ID = "CORE_F2_H0_static_cup_hold_q0p50000000_dp0p007500000000_canary"
SOURCE_RELATIVE = "campaigns/l2-multifamily/c1-canary/cases/L2_C1_F2_rotation_center_nominal_Def.xml"
MOTION_NAME = "CORE_F2_H0_static_cup_hold_motion.dat"
DP_M = 0.0075
TIME_MAX_S = 0.60
OUTPUT_INTERVAL_S = 0.02
RETENTION_MIN = 0.95

CUP = {"low": [0.0, -0.15, 0.65], "size": [0.425, 0.30, 0.45], "mkbound": 0}
RECEIVER = {"low": [0.45, -0.30, 0.0], "size": [1.10, 0.60, 0.45], "mkbound": 1}
TRAY = {"low": [-0.60, -0.55, -0.20], "size": [2.60, 1.10, 0.10], "mkbound": 2}
FLUID_BOXES = (
    {"low": [0.05, -0.11, 0.70], "size": [0.325, 0.22, 0.11], "mkfluid": 0},
    {"low": [0.05, -0.11, 0.81], "size": [0.325, 0.22, 0.11], "mkfluid": 1},
    {"low": [0.05, -0.11, 0.92], "size": [0.325, 0.22, 0.11], "mkfluid": 2},
)


def _nearest_native_box(box: dict, dp: float) -> dict:
    """Materialize the nearest in-box centre lattice without mass scaling."""
    low = [float(value) for value in box["low"]]
    size = [float(value) for value in box["size"]]
    counts = [max(1, int(round(value / dp))) for value in size]
    first = [math.ceil(value / dp - .5 - 1e-10) for value in low]
    first_center = [(index + .5) * dp for index in first]
    draw_size = [(count - 1) * dp for count in counts]
    continuous = float(math.prod(size) * 1000.0)
    discrete = float(math.prod(counts) * dp**3 * 1000.0)
    return {
        "continuous_low_m": low,
        "continuous_size_m": size,
        "first_center_m": first_center,
        "draw_size_m": draw_size,
        "counts": counts,
        "particle_count": int(math.prod(counts)),
        "continuous_mass_kg": continuous,
        "discrete_mass_kg": discrete,
        "mkfluid": int(box["mkfluid"]),
        "native_cell_centre_sampling": True,
    }


def _static_motion(path: Path) -> None:
    rows = ["#Time;Degrees"]
    for time_s in np.arange(0.0, TIME_MAX_S + 0.005, 0.01):
        rows.append(f"{time_s:.6f};0.000000000")
    path.write_text("\n".join(rows) + "\n")


def _set_parameter(root: ET.Element, key: str, value: str | float | int) -> None:
    node = root.find(f".//execution/parameters/parameter[@key='{key}']")
    if node is None:
        parameters = root.find(".//execution/parameters")
        if parameters is None:
            raise ValueError(f"F2 source has no execution parameters for {key}")
        node = ET.SubElement(parameters, "parameter", {"key": key})
    node.set("value", str(value))


def _rewrite_definition(source: Path, target: Path, motion_name: str, sampling: list[dict]) -> dict:
    tree = ET.parse(source)
    root = tree.getroot()
    _set_parameter(root, "TimeMax", TIME_MAX_S)
    _set_parameter(root, "TimeOut", OUTPUT_INTERVAL_S)
    definition = root.find(".//geometry/definition")
    if definition is None:
        raise ValueError("F2 source has no geometry definition")
    definition.set("dp", f"{DP_M:.17g}")
    commands = root.find(".//geometry/commands/mainlist")
    if commands is None:
        raise ValueError("F2 source has no geometry mainlist")
    fluid_index = 0
    active_mk = None
    for node in list(commands):
        if node.tag == "setmkfluid":
            active_mk = int(node.get("mk"))
        elif node.tag == "drawbox" and active_mk is not None:
            if fluid_index >= len(sampling):
                raise ValueError("F2 source contains more fluid boxes than registered")
            point = node.find("point")
            size = node.find("size")
            if point is None or size is None:
                raise ValueError("F2 fluid drawbox is incomplete")
            sample = sampling[fluid_index]
            for index, axis in enumerate("xyz"):
                point.set(axis, f"{sample['first_center_m'][index]:.17g}")
                size.set(axis, f"{sample['draw_size_m'][index]:.17g}")
            fluid_index += 1
    if fluid_index != len(sampling):
        raise ValueError("F2 source fluid box count changed")
    motion = root.find(".//mvrotfile")
    if motion is None:
        raise ValueError("F2 source has no prescribed rotation")
    motion.set("duration", f"{TIME_MAX_S:.17g}")
    for node in root.findall(".//begin"):
        node.set("finish", f"{TIME_MAX_S:.17g}")
    file_node = motion.find("file")
    if file_node is None:
        raise ValueError("F2 source rotation has no motion file")
    file_node.set("name", motion_name)
    ET.indent(tree, space="    ")
    target.parent.mkdir(parents=True, exist_ok=True)
    tree.write(target, encoding="utf-8", xml_declaration=True)
    return {
        "source_definition": str(source.resolve()),
        "source_definition_sha256": digest(source),
        "definition": str(target.resolve()),
        "definition_sha256": digest(target),
        "motion_file_name": motion_name,
        "changed_fields": [
            "geometry.definition.dp=0.0075",
            "fluid drawboxes: registered nearest cell-centre sampling",
            "motion angle: fixed zero",
            "execution.parameters.TimeMax=0.60",
            "execution.parameters.TimeOut=0.02",
        ],
        "unchanged_fields": [
            "cup/receiver/tray finite geometry",
            "gravity and fluid material constants",
            "Boundary/SlipMode/solver recipe",
            "native rho*dp^3 particle mass policy",
        ],
        "qualification_claim": "none",
    }


def static_config() -> dict:
    return {
        "schema": "core.cfd.v1",
        "family": "F2",
        "scope_id": "F2_static_cup_hold_canary_v1",
        "revision_id": REVISION_ID,
        "case_id": CASE_ID,
        "recipe_id": "F2_static_cup_hold_dbc_native_v1",
        "recipe": "native_dbc",
        "stage": "canary",
        "parameter": {"name": "cup_angle_degrees", "value": 0.0, "range": [0.0, 0.0]},
        "dp_m": DP_M,
        "cfl": 0.2,
        "time_max_s": TIME_MAX_S,
        "output_interval_s": OUTPUT_INTERVAL_S,
        "source_definition": SOURCE_RELATIVE,
        "physical_case_id": "F2_static_cup_hold_geometry_v1",
        "lineage_group_id": "F2_static_cup_hold_v1",
        "paired_background_id": "F2_static_hold_only_no_pair",
        "view_id": "world_fluid_particle_v1",
        "control_semantics": "prescribed zero cup angle; gravity and initial fluid are fixed inputs",
        "source_label_semantics": "initial Mk is a numerical source partition; not material truth",
        "cup": copy.deepcopy(CUP),
        "receiver": copy.deepcopy(RECEIVER),
        "tray": copy.deepcopy(TRAY),
        "fluid_boxes": [copy.deepcopy(item) for item in FLUID_BOXES],
        "wall_bounds": {"xmin": -0.60, "xmax": 2.00, "ymin": -0.55, "ymax": 0.55,
                        "zmin": -0.20, "zmax": 1.10},
        "qualification_claim": "none",
        "qualified": False,
        "hold_gate": {
            "cup_retention_mass_fraction_min": RETENTION_MIN,
            "meaning": "fixed initial native mass fraction remaining in finite cup interior at every saved frame",
            "full_window_required": True,
        },
    }


def prepare_static_hold(lab: Path, output: Path) -> dict:
    lab, output = Path(lab).resolve(), Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("F2 static hold preparation output must be fresh")
    output.mkdir(parents=True, exist_ok=True)
    config = static_config()
    source = lab / config["source_definition"]
    sampling = [_nearest_native_box(box, DP_M) for box in FLUID_BOXES]
    config["sampling_rule"] = "nearest in-box cell-centre lattice per fluid layer; native rho*dp^3, no mass rescaling"
    target = output / f"{CASE_ID}_Def.xml"
    definition_audit = _rewrite_definition(source, target, MOTION_NAME, sampling)
    motion = output / MOTION_NAME
    _static_motion(motion)
    binaries = lab / "vendor/official/DualSPHysics_v5.4/bin/linux"
    prefix = output / "generated" / CASE_ID
    prefix.parent.mkdir(parents=True, exist_ok=True)
    command = [str(binaries / "GenCase_linux64"), str(target.with_suffix("")), str(prefix), "-save:all"]
    with (output / "gencase.log").open("w") as log:
        process = subprocess.run(command, cwd=output, env=environment(lab), stdout=log, stderr=subprocess.STDOUT)
    if process.returncode:
        raise RuntimeError("F2 static hold GenCase failed; inspect " + str(output / "gencase.log"))
    generated_xml = prefix.with_suffix(".xml")
    generated = ET.parse(generated_xml).getroot()
    blocks = generated.findall(".//particles/fluid")
    generated_counts = [int(block.get("count")) for block in blocks]
    expected_counts = [int(item["particle_count"]) for item in sampling]
    count_gate = generated_counts == expected_counts and len(blocks) == len(expected_counts)
    sampling_payload = {
        "fluid_boxes": sampling,
        "expected_fluid_particles": int(sum(expected_counts)),
        "continuous_mass_kg": float(sum(item["continuous_mass_kg"] for item in sampling)),
        "sampled_mass_kg": float(sum(item["discrete_mass_kg"] for item in sampling)),
        "mass_policy": "native rho*dp^3, no mass rescaling",
    }
    mass = mass_quality(sampling_payload)
    decoder = lab / "campaigns/l1-resume/artifacts/bi4_dump"
    with __import__("tempfile").TemporaryDirectory(prefix="core-f2-static-") as folder:
        ids, pos, vel, rho, meta, info, arrays = native_frame(prefix.with_suffix(".bi4"), Path(folder) / "native", decoder)
        native = {
            "total_particles": int(len(ids)),
            "fluid_particles": int(meta.get("CaseNfluid", 0)),
            "expected_fluid_particles": int(sampling_payload["expected_fluid_particles"]),
            "unique_ids": bool(len(np.unique(ids)) == len(ids)),
            "finite_initial_arrays": bool(all(np.isfinite(array).all() for array in (pos, vel, rho))),
            "native_initial_mass_kg": float(meta.get("MassFluid", 0.0)) * int(meta.get("CaseNfluid", 0)),
        }
    checks = {
        "generated_fluid_counts": count_gate,
        "native_fluid_count": native["fluid_particles"] == native["expected_fluid_particles"],
        "native_state_finite_unique": native["unique_ids"] and native["finite_initial_arrays"],
        "motion_file_zero_and_finite": bool(motion.is_file() and all(
            float(line.split(";")[1]) == 0.0 for line in motion.read_text().splitlines()
            if line and not line.startswith("#")
        )),
        "mass_gate": bool(mass["mass_gate_pass"]),
    }
    inputs = {str(path.resolve()): digest(path) for path in output.rglob("*") if path.is_file()}
    prepared = {
        "schema": "core.cfd.v1",
        "created_at": "2026-09-19T00:00:00+00:00",
        "config": config,
        "sampling": sampling_payload,
        "mass_preflight": mass,
        "native_initial": native,
        "static_hold_preflight": checks,
        "preflight_pass": bool(all(checks.values())),
        "generated_prefix": str(prefix.resolve()),
        "source_template": str(source.resolve()),
        "source_template_sha256": digest(source),
        "definition_audit": definition_audit,
        "generated_particle_counts": generated_counts,
        "resolved_runtime_domain": {"zmax": 1.8},
        "inputs": inputs,
        "solver_binary": str(binaries / "DualSPHysics5.4_linux64"),
        "solver_sha256": digest(binaries / "DualSPHysics5.4_linux64"),
        "decoder": str(decoder),
        "decoder_sha256": digest(decoder),
        "solver_arguments": [],
        "qualification_claim": "none; static F2 hold canary only",
    }
    write_json(output / "prepared.json", prepared)
    return prepared


def observe_static_hold(prepared_path: Path, hdf5_path: Path) -> dict:
    prepared = json.loads(Path(prepared_path).read_text())
    config = prepared["config"]
    cup = config["cup"]
    low = np.asarray(cup["low"], dtype=float)
    high = low + np.asarray(cup["size"], dtype=float)
    with h5py.File(hdf5_path, "r") as handle:
        times = np.asarray(handle["time"][:], dtype=float)
        initial_valid = handle["valid"][0].astype(bool)
        initial_mass_values = np.asarray(handle["mass"][0], dtype=float)
        initial_mass = float(initial_mass_values[initial_valid].sum(dtype=np.float64))
        retention, centers, speeds = [], [], []
        for index in range(len(times)):
            valid = handle["valid"][index].astype(bool)
            position = np.asarray(handle["position"][index], dtype=float)
            velocity = np.asarray(handle["velocity"][index], dtype=float)
            mass = np.asarray(handle["mass"][index], dtype=float)
            active = valid & np.isfinite(position).all(axis=1) & np.isfinite(velocity).all(axis=1) & np.isfinite(mass)
            cup_mask = active & np.all((position >= low) & (position <= high), axis=1)
            active_mass = float(mass[active].sum(dtype=np.float64))
            cup_mass = float(mass[cup_mask].sum(dtype=np.float64))
            center = (mass[active, None] * position[active]).sum(axis=0) / max(active_mass, 1e-30)
            retention.append(cup_mass / max(initial_mass, 1e-30))
            centers.append(center.tolist())
            speeds.append(float(np.linalg.norm(velocity[active], axis=1).max(initial=0.0)))
    retention = np.asarray(retention, dtype=float)
    horizon = bool(len(times) >= 2 and times[-1] >= config["time_max_s"] - 1e-6)
    minimum_retention = float(np.min(retention)) if len(retention) else 0.0
    report = {
        "schema": SCHEMA,
        "revision_id": REVISION_ID,
        "case_id": config["case_id"],
        "observable_names": ["cup_retention_mass_fraction", "center_of_mass_m", "max_speed_m_s"],
        "time_s": times.tolist(),
        "cup_retention_mass_fraction": retention.tolist(),
        "center_of_mass_m": centers,
        "max_speed_m_s": speeds,
        "initial_native_mass_kg": initial_mass,
        "minimum_cup_retention_mass_fraction": minimum_retention,
        "requested_horizon_reached": horizon,
        "static_hold_gate_pass": bool(horizon and minimum_retention >= RETENTION_MIN),
        "qualification_claim": "none; static F2 hold canary observation",
    }
    return report


def run(prepared_path: Path, lab: Path, output: Path) -> dict:
    prepared_path, lab, output = Path(prepared_path).resolve(), Path(lab).resolve(), Path(output).resolve()
    if not json.loads(prepared_path.read_text()).get("preflight_pass"):
        raise ValueError("F2 static hold preflight did not pass")
    result = native_run(prepared_path, lab, output)
    observations = observe_static_hold(prepared_path, output / "trajectory.h5")
    audit_path = output / "audit.json"
    audit = json.loads(audit_path.read_text()) if audit_path.is_file() else dict(result)
    audit.update({
        "family": "F2",
        "static_hold_gate_pass": observations["static_hold_gate_pass"],
        "minimum_cup_retention_mass_fraction": observations["minimum_cup_retention_mass_fraction"],
        "qualification_claim": "none; static F2 hold canary only",
        "qualified": False,
    })
    audit["hard_integrity_pass"] = bool(audit.get("hard_integrity_pass") and observations["static_hold_gate_pass"])
    write_json(output / "observations.json", observations)
    write_json(output / "audit.json", audit)
    result.update(audit)
    result["observations"] = observations
    write_json(output / "result.json", result)
    return result


def make_job(prepared_path: Path, lab: Path, output: Path) -> dict:
    prepared_path, lab, output = Path(prepared_path).resolve(), Path(lab).resolve(), Path(output).resolve()
    prepared = json.loads(prepared_path.read_text())
    if not prepared.get("preflight_pass"):
        raise ValueError("F2 static hold prepared case did not pass CPU preflight")
    solver = Path(prepared["solver_binary"]).resolve()
    spec = {
        "schema": JOB_SCHEMA,
        "job_id": "f2-h0-static-hold-canary-001",
        "logical_id": "f2-h0-static-hold-canary-001",
        "attempt_role": "initial_state_substitute",
        "category": "static_hold_canary",
        "host": "ada",
        "source_lab": str(lab),
        "cwd": str(lab),
        "argv": [str(lab / ".venv/bin/python"), str(lab / "scripts/core_f2.py"),
                 "--lab-root", str(lab), "run", "--prepared", str(prepared_path),
                 "--output", "{attempt_dir}/product"],
        "required_outputs": ["product/result.json", "product/trajectory.h5", "product/audit.json", "product/observations.json"],
        "resources": {"cpu_cores": 2, "ram_mib": 16384, "gpu_peak_mib": 4096, "io_weight": .25},
        "timeout_seconds": 1800,
        "depends_on": [],
        "qualification_claim": "none",
        "input_files": [{"path": str(prepared_path), "sha256": digest(prepared_path)},
                        {"path": str(solver), "sha256": digest(solver)}],
        "prepared_case_id": prepared["config"]["case_id"],
        "registered_window_s": prepared["config"]["time_max_s"],
        "worker_contract": "core_runtime worker; scheduler supplies one CUDA UUID and solver uses -gpu:0",
        "qualification_status": "static hold substitute; moving-cup F2 scope remains unqualified",
    }
    write_json(output, spec)
    return spec


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, default=SOURCE_ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare-static-hold")
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("make-job")
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("run")
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare-static-hold":
        result = prepare_static_hold(args.lab_root, args.output)
    elif args.command == "make-job":
        result = make_job(args.prepared, args.lab_root, args.output)
    else:
        result = run(args.prepared, args.lab_root, args.output)
    print(json.dumps({key: result[key] for key in (
        "preflight_pass", "static_hold_preflight", "static_hold_gate_pass", "qualification_claim",
    ) if key in result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
