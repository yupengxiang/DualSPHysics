#!/usr/bin/env python3
"""Build, run and audit true rotating-cup pouring probes for W06."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
from pathlib import Path
import re
import subprocess

import h5py
import numpy as np

try:
    from scripts.campaign_runner import execute_attempt, require_idle_allowed_gpu
    from scripts.trajectory_io import convert_streaming
    from scripts.w02_semantics import partvtk_csv
except ModuleNotFoundError:
    from campaign_runner import execute_attempt, require_idle_allowed_gpu
    from trajectory_io import convert_streaming
    from w02_semantics import partvtk_csv


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "v0.1-candidate"
BIN = LAB / "vendor" / "official" / "DualSPHysics_v5.4" / "bin" / "linux"
GENCASE = BIN / "GenCase_linux64"
SOLVER = BIN / "DualSPHysics5.4_linux64"
CASE_ROOT = CAMPAIGN / "cases" / "w06"
ARTIFACT = CAMPAIGN / "artifacts" / "w06"
RUN_ROOT = CAMPAIGN / "runs"
DATA = CAMPAIGN / "data" / "w06"
REPORT = CAMPAIGN / "w06-rotating-pour.json"
DP = 0.025
PIVOT = np.array([0.0, 0.0, 0.65])

GEOMETRIES = {"narrow": 0.35, "standard": 0.425, "wide": 0.50}
STATES = {
    "slow_center": {"duration": 1.20, "receiver_x": 0.45, "receiver_y": 0.0, "angle": -105.0},
    "fast_center": {"duration": 0.50, "receiver_x": 0.45, "receiver_y": 0.0, "angle": -105.0},
    "offset_partial": {"duration": 0.85, "receiver_x": 0.45, "receiver_y": 0.22, "angle": -105.0},
    "far_partial": {"duration": 0.85, "receiver_x": 0.90, "receiver_y": 0.0, "angle": -105.0},
}


def records():
    values = []
    gpu_cycle = [4, 5, 6, 7]
    for index, (geometry, width) in enumerate((g, w) for g, w in GEOMETRIES.items() for _ in [0]):
        for state, control in STATES.items():
            case_id = f"W06_{geometry}_{state}"
            values.append({"case_id": case_id, "geometry": geometry, "cup_width": width,
                           "state": state, "gpu": gpu_cycle[len(values) % 4], **control})
    return values


def env():
    value = os.environ.copy()
    value["LD_LIBRARY_PATH"] = f"{BIN}:{value.get('LD_LIBRARY_PATH', '')}"
    return value


def motion_angle(time, duration, angle):
    if time <= 0.5:
        return 0.0
    if time >= 0.5 + duration:
        return angle
    phase = (time - 0.5) / duration
    return angle * 0.5 * (1 - math.cos(math.pi * phase))


def write_motion(path, record):
    lines = ["#Time;Degrees"]
    for time in np.linspace(0, 2.5, 501):
        lines.append(f"{time:.6f};{motion_angle(time, record['duration'], record['angle']):.9f}")
    path.write_text("\n".join(lines) + "\n")


def definition_text(record):
    width = record["cup_width"]
    dp = float(record.get("dp", DP))
    time_out = float(record.get("tout", 0.01))
    boundary_method = int(record.get("boundary_method", 1))
    shape_mode = "actual | bound" if boundary_method == 2 else "dp | bound"
    normal_geometry = f'''<list name="GeometryForNormals">
        <setactive drawpoints="0" drawshapes="1"/><setshapemode>actual | bound</setshapemode>
        <setnormalinvert invert="true"/>
        <setmkbound mk="0"/><drawbox><boxfill>bottom | left | right | front | back</boxfill>
          <point x="0" y="-0.15" z="0.65"/><size x="{width}" y="0.30" z="0.45"/><layers vdp="-0.5"/>
        </drawbox>
        <setmkbound mk="1"/><drawbox><boxfill>bottom | left | right | front | back</boxfill>
          <point x="{record['receiver_x']}" y="{record['receiver_y'] - 0.30}" z="0"/><size x="1.10" y="0.60" z="0.45"/><layers vdp="-0.5"/>
        </drawbox>
        <setmkbound mk="2"/><drawbox><boxfill>bottom</boxfill>
          <point x="-0.60" y="-0.55" z="-0.20"/><size x="2.60" y="1.10" z="0.10"/><layers vdp="-0.5"/>
        </drawbox>
        <shapeout file="hdp"/><resetdraw/>
      </list>''' if boundary_method == 2 else ""
    run_normals = '<runlist name="GeometryForNormals"/>' if boundary_method == 2 else ""
    normals = '''
    <normals active="true"><norgeometry>
      <geometryfile file="[CaseName]_hdp_Actual.vtk"/><distanceh v="2.0"/>
    </norgeometry></normals>''' if boundary_method == 2 else ""
    fluid_x0, fluid_x1 = 0.05, width - 0.05
    layer_height = 0.11
    receiver_x, receiver_y = record["receiver_x"], record["receiver_y"]
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<case>
  <casedef>
    <constantsdef>
      <gravity x="0" y="0" z="-9.81"/><rhop0 value="1000"/><rhopgradient value="2"/>
      <hswl value="0" auto="true"/><gamma value="7"/><speedsystem value="0" auto="true"/>
      <coefsound value="25"/><speedsound value="0" auto="true"/><hdp value="1.3"/><cflnumber value="0.2"/>
    </constantsdef>
    <mkconfig boundcount="220" fluidcount="16"/>
    <geometry>
      <definition dp="{dp}"><pointmin x="-0.80" y="-0.70" z="-0.45"/><pointmax x="2.3" y="0.90" z="1.80"/></definition>
      <commands>{normal_geometry}<mainlist>
        {run_normals}
        <setshapemode>{shape_mode}</setshapemode><setdrawmode mode="full"/>
        <setmkbound mk="0"/><drawbox><boxfill>bottom | left | right | front | back</boxfill>
          <point x="0" y="-0.15" z="0.65"/><size x="{width}" y="0.30" z="0.45"/><layers vdp="0,1,2"/>
        </drawbox>
        <setmkbound mk="1"/><drawbox><boxfill>bottom | left | right | front | back</boxfill>
          <point x="{receiver_x}" y="{receiver_y - 0.30}" z="0"/><size x="1.10" y="0.60" z="0.45"/><layers vdp="0,1,2"/>
        </drawbox>
        <setmkbound mk="2"/><drawbox><boxfill>bottom</boxfill>
          <point x="-0.60" y="-0.55" z="-0.20"/><size x="2.60" y="1.10" z="0.10"/><layers vdp="0,1,2"/>
        </drawbox>
        <setmkfluid mk="0"/><drawbox><boxfill>solid</boxfill><point x="{fluid_x0}" y="-0.11" z="0.70"/><size x="{fluid_x1-fluid_x0}" y="0.22" z="{layer_height}"/></drawbox>
        <setmkfluid mk="1"/><drawbox><boxfill>solid</boxfill><point x="{fluid_x0}" y="-0.11" z="0.81"/><size x="{fluid_x1-fluid_x0}" y="0.22" z="{layer_height}"/></drawbox>
        <setmkfluid mk="2"/><drawbox><boxfill>solid</boxfill><point x="{fluid_x0}" y="-0.11" z="0.92"/><size x="{fluid_x1-fluid_x0}" y="0.22" z="{layer_height}"/></drawbox>
      </mainlist></commands>
    </geometry>{normals}
    <motion><objreal ref="0"><begin mov="1" start="0" finish="2.5"/>
      <mvrotfile id="1" duration="2.5" anglesunits="degrees"><file name="{record['case_id']}_motion.dat"/>
        <axisp1 x="0" y="-1" z="0.65"/><axisp2 x="0" y="1" z="0.65"/>
      </mvrotfile></objreal></motion>
  </casedef>
  <execution><parameters>
    <parameter key="SavePosDouble" value="2"/><parameter key="Boundary" value="{boundary_method}"/><parameter key="SlipMode" value="1"/>
    <parameter key="StepAlgorithm" value="2"/><parameter key="Kernel" value="2"/>
    <parameter key="ViscoTreatment" value="1"/><parameter key="Visco" value="0.03"/><parameter key="ViscoBoundFactor" value="1"/>
    <parameter key="DensityDT" value="3"/><parameter key="DensityDTvalue" value="0.1"/>
    <parameter key="Shifting" value="0"/><parameter key="RigidAlgorithm" value="1"/><parameter key="FtPause" value="0"/>
    <parameter key="CoefDtMin" value="0.05"/><parameter key="DtIni" value="0"/><parameter key="DtMin" value="0"/>
    <parameter key="DtFixed" value="0"/><parameter key="DtAllParticles" value="0"/>
    <parameter key="TimeMax" value="2.5"/><parameter key="TimeOut" value="{time_out}"/><parameter key="PartsOutMax" value="1"/>
    <parameter key="RhopOutMin" value="700"/><parameter key="RhopOutMax" value="1300"/><parameter key="MinFluidStop" value="0"/>
    <simulationdomain><posmin x="-0.70" y="-0.65" z="-0.40"/><posmax x="2.20" y="0.80" z="1.80"/></simulationdomain>
  </parameters></execution>
</case>
'''


def prepare(selected=None):
    selected = selected or records()
    CASE_ROOT.mkdir(parents=True, exist_ok=True)
    matrix = []
    for record in selected:
        definition = CASE_ROOT / f"{record['case_id']}_Def.xml"
        motion = CASE_ROOT / f"{record['case_id']}_motion.dat"
        definition.write_text(definition_text(record))
        write_motion(motion, record)
        generated = ARTIFACT / record["case_id"] / "generated"
        generated.mkdir(parents=True, exist_ok=True)
        prefix = generated / record["case_id"]
        log = subprocess.run([str(GENCASE), str(definition.with_suffix("")), str(prefix), "-save:all"],
                             cwd=CASE_ROOT, env=env(), text=True, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT)
        (generated / "gencase.stdout.log").write_text(log.stdout)
        (generated / motion.name).write_bytes(motion.read_bytes())
        if log.returncode or not prefix.with_suffix(".xml").is_file():
            raise RuntimeError(f"GenCase failed for {record['case_id']}")
        match = re.search(r"Fluid\.\.\.\.:\s*([0-9,]+)", log.stdout)
        matrix.append({key: record[key] for key in ("case_id", "geometry", "cup_width", "state", "duration",
                                                     "receiver_x", "receiver_y", "angle", "gpu")}
                      | {"fluid_particles": int(match.group(1).replace(",", "")) if match else None})
    (CASE_ROOT / "matrix.json").write_text(json.dumps(matrix, indent=2) + "\n")


def allowed_uuids():
    return json.loads((CAMPAIGN / "w00-inventory.json").read_text())["execution_policy"]["allowed_gpu_uuids"]


def run_one(record):
    gpu = require_idle_allowed_gpu(record["gpu"], allowed_uuids())
    prefix = ARTIFACT / record["case_id"] / "generated" / record["case_id"]
    result = execute_attempt(record["case_id"],
                             [str(SOLVER), f"-gpu:{record['gpu']}", str(prefix), "{output}"],
                             RUN_ROOT, cwd=prefix.parent, env=env(), evidence_glob="data/Part_*.bi4",
                             required_text="Finished execution (code=0)")
    result["gpu_at_launch"] = gpu
    if result["status"] != "completed":
        raise RuntimeError(f"{record['case_id']} failed: {result['attempt_directory']}")
    return result


def run(selected=None):
    selected = selected or records()
    queues = {gpu: [] for gpu in (4, 5, 6, 7)}
    for record in selected:
        queues[record["gpu"]].append(record)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(lambda queue: [run_one(item) for item in queue], queue) for queue in queues.values()]
        return [item for future in futures for item in future.result()]


def latest(case_id):
    return Path(json.loads((RUN_ROOT / case_id / "latest.json").read_text())["attempt_directory"])


def rotation_matrix_y(angle_degrees):
    angle = math.radians(angle_degrees)
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def add_control_metadata(h5_path, record):
    with h5py.File(h5_path, "r+") as h5:
        time = h5["time"][:]
        angles = np.asarray([motion_angle(value, record["duration"], record["angle"]) for value in time])
        transforms = np.repeat(np.eye(4)[None], len(time), axis=0)
        for index, angle in enumerate(angles):
            # DualSPHysics' mvrotfile Y-axis sign convention is opposite to
            # the active right-handed matrix used by this analysis code.
            rotation = rotation_matrix_y(-angle)
            transforms[index, :3, :3] = rotation
            transforms[index, :3, 3] = PIVOT - rotation @ PIVOT
        control = h5.require_group("control")
        for name in ("cup_angle_degrees", "cup_world_from_body"):
            if name in control:
                del control[name]
        control.create_dataset("cup_angle_degrees", data=angles)
        control.create_dataset("cup_world_from_body", data=transforms)
        h5.attrs["coordinate_frame"] = "world; cup body transform in /control/cup_world_from_body"


def normalize(selected=None):
    DATA.mkdir(parents=True, exist_ok=True)
    for record in selected or records():
        attempt = latest(record["case_id"])
        csvs = partvtk_csv(attempt / "data", attempt / "csv", "-all,+fluid")
        output = DATA / f"{record['case_id']}.h5"
        convert_streaming({"id": record["case_id"], "family": "F2", "mechanism": "rotating cup pour", "shifting": 0},
                          csvs, output)
        add_control_metadata(output, record)


def body_positions(world, world_from_body):
    inverse = np.linalg.inv(world_from_body)
    homogeneous = np.column_stack((world, np.ones(len(world))))
    return (homogeneous @ inverse.T)[:, :3]


def inside_aabb(points, lower, upper):
    return np.all((points >= np.asarray(lower)) & (points <= np.asarray(upper)), axis=1)


def audit_case(record, path=None):
    path = Path(path) if path is not None else DATA / f"{record['case_id']}.h5"
    with h5py.File(path, "r") as h5:
        time = h5["time"][:]
        initial = h5["valid"][0] & (h5["type"][0] == 3)
        mass = h5["mass"][0]
        source_mk = h5["mk"][0]
        initial_mass = float(np.nansum(mass[initial]))
        first_exit = np.full(len(initial), np.nan)
        capture_transitions = np.zeros(len(initial), dtype=int)
        previous_captured = np.zeros(len(initial), dtype=bool)
        ever_captured = np.zeros(len(initial), dtype=bool)
        transforms = h5["control/cup_world_from_body"][:]
        for frame, current_time in enumerate(time):
            valid = h5["valid"][frame] & initial
            world = h5["position"][frame]
            cup = body_positions(world, transforms[frame])
            retained = valid & inside_aabb(cup, [0.025, -0.145, 0.675],
                                           [record["cup_width"] - 0.025, 0.145, 1.075])
            newly_exited = initial & np.isnan(first_exit) & ~retained
            first_exit[newly_exited] = current_time
            receiver = valid & inside_aabb(world,
                [record["receiver_x"] + 0.025, record["receiver_y"] - 0.275, 0.025],
                [record["receiver_x"] + 1.075, record["receiver_y"] + 0.275, 0.425])
            capture_transitions += (~previous_captured & receiver).astype(int)
            ever_captured |= receiver
            previous_captured = receiver
        final_valid = h5["valid"][-1] & initial
        final_world = h5["position"][-1]
        final_cup = body_positions(final_world, transforms[-1])
        retained = final_valid & inside_aabb(final_cup, [0.025, -0.145, 0.675],
                                             [record["cup_width"] - 0.025, 0.145, 1.075])
        captured = final_valid & inside_aabb(final_world,
            [record["receiver_x"] + 0.025, record["receiver_y"] - 0.275, 0.025],
            [record["receiver_x"] + 1.075, record["receiver_y"] + 0.275, 0.425])
        missing = initial & ~final_valid
        spilled = final_valid & ~retained & ~captured & (final_world[:, 2] < -0.10)
        inflight = final_valid & ~retained & ~captured & ~spilled
        categories = {"captured": captured, "retained": retained,
                      "spilled_to_tray": spilled, "inflight_or_unclassified": inflight,
                      "numerically_missing": missing}
        by_source = {}
        for source in sorted(int(value) for value in np.unique(source_mk[initial])):
            selected = initial & (source_mk == source)
            denominator = float(np.nansum(mass[selected]))
            by_source[str(source)] = {name: float(np.nansum(mass[selected & mask]) / denominator)
                                      for name, mask in categories.items()}
        finite_exit = first_exit[initial & np.isfinite(first_exit)]
        return {
            "particles_initial": int(initial.sum()), "initial_mass_kg": initial_mass,
            "final_mass_fraction": {name: float(np.nansum(mass[mask]) / initial_mass) for name, mask in categories.items()},
            "source_to_destination_fraction": by_source,
            "fraction_ever_captured": float(np.nansum(mass[initial & ever_captured]) / initial_mass),
            "fraction_with_multiple_capture_entries": float(np.nansum(mass[initial & (capture_transitions > 1)]) / initial_mass),
            "median_first_exit_time_s": float(np.median(finite_exit)) if len(finite_exit) else None,
            "mass_closure_error": float(sum(np.nansum(mass[mask]) for mask in categories.values()) - initial_mass),
        }


def analyze(run_results=None):
    results = {record["case_id"]: {key: record[key] for key in
               ("geometry", "cup_width", "state", "duration", "receiver_x", "receiver_y", "angle")}
               | audit_case(record) for record in records()}
    if run_results is None:
        run_results = [json.loads((RUN_ROOT / record["case_id"] / "latest.json").read_text()) for record in records()]
    compact = [{"case_id": item["case_id"], "attempt_id": item["attempt_id"], "status": item["status"],
                "elapsed_seconds": item["elapsed_seconds"], "frames": len(item["evidence_files"])}
               for item in run_results]
    payload = {
        "schema_version": 1, "scope": "12-case mechanism exploration, not formal production",
        "coordinate_semantics": "particle positions are world coordinates; cup transform is stored per frame",
        "cases": results,
        "mechanism_counts": {
            "mostly_captured_ge_0p8": sum(v["final_mass_fraction"]["captured"] >= 0.8 for v in results.values()),
            "partial_capture_0p2_to_0p8": sum(0.2 <= v["final_mass_fraction"]["captured"] < 0.8 for v in results.values()),
            "mostly_missed_lt_0p2": sum(v["final_mass_fraction"]["captured"] < 0.2 for v in results.values()),
        },
        "run_results": compact,
    }
    REPORT.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "run", "normalize", "analyze", "all"], nargs="?", default="all")
    parser.add_argument("--cases", nargs="*", help="limit prepare/run/normalize to selected case ids")
    args = parser.parse_args()
    known = {record["case_id"]: record for record in records()}
    unknown = set(args.cases or []) - set(known)
    if unknown:
        parser.error(f"unknown cases: {sorted(unknown)}")
    selected = [known[case_id] for case_id in args.cases] if args.cases else list(known.values())
    run_results = None
    if args.action in {"prepare", "all"}: prepare(selected)
    if args.action in {"run", "all"}: run_results = run(selected)
    if args.action in {"normalize", "all"}: normalize(selected)
    if args.action in {"analyze", "all"}: analyze(run_results)


if __name__ == "__main__":
    main()
