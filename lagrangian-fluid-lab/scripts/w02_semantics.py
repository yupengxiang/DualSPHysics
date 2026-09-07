#!/usr/bin/env python3
"""Run and analyse W02 particle-identity and reference-frame probes."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

import h5py
import numpy as np
import pandas as pd

try:
    from scripts.campaign_runner import execute_attempt, require_idle_allowed_gpu
    from scripts.trajectory_io import convert_streaming
except ModuleNotFoundError:
    from campaign_runner import execute_attempt, require_idle_allowed_gpu
    from trajectory_io import convert_streaming


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "v0.1-candidate"
BIN = LAB / "vendor" / "official" / "DualSPHysics_v5.4" / "bin" / "linux"
GENCASE = BIN / "GenCase_linux64"
SOLVER = BIN / "DualSPHysics5.4_linux64"
PARTVTK = BIN / "PartVTK_linux64"
BASE_DEF = LAB / "cases" / "F3" / "F3_impulse_slosh" / "F3_impulse_slosh_Def.xml"
RUN_ROOT = CAMPAIGN / "runs"
CASE_ROOT = CAMPAIGN / "cases" / "w02"
ARTIFACT_ROOT = CAMPAIGN / "artifacts" / "w02"
DATA_ROOT = CAMPAIGN / "data" / "w02"
REPORT = CAMPAIGN / "w02-semantics.json"

PROBES = {
    "W02_shift_off": {"shifting": 0, "gpu": 4},
    "W02_shift_full": {"shifting": 3, "gpu": 5},
}


def environment():
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = f"{BIN}:{env.get('LD_LIBRARY_PATH', '')}"
    return env


def set_parameter(root, key, value):
    node = root.find(f".//parameter[@key='{key}']")
    if node is None:
        parameters = root.find(".//execution/parameters")
        node = ET.SubElement(parameters, "parameter", key=key)
    node.set("value", str(value))


def prepare():
    CASE_ROOT.mkdir(parents=True, exist_ok=True)
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    for case_id, config in PROBES.items():
        tree = ET.parse(BASE_DEF)
        root = tree.getroot()
        set_parameter(root, "SavePosDouble", 2)
        set_parameter(root, "Shifting", config["shifting"])
        set_parameter(root, "ShiftCoef", -2)
        set_parameter(root, "ShiftTFS", 2.75)
        set_parameter(root, "TimeMax", 0.25)
        set_parameter(root, "TimeOut", 0.0025)
        definition = CASE_ROOT / f"{case_id}_Def.xml"
        ET.indent(tree, space="    ")
        tree.write(definition, encoding="utf-8", xml_declaration=True)
        generated_dir = ARTIFACT_ROOT / case_id / "generated"
        generated_dir.mkdir(parents=True, exist_ok=True)
        prefix = generated_dir / case_id
        proc = subprocess.run(
            [str(GENCASE), str(definition.with_suffix("")), str(prefix), "-save:all"],
            cwd=definition.parent, env=environment(), text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        (generated_dir / "gencase.stdout.log").write_text(proc.stdout)
        if proc.returncode or not prefix.with_suffix(".xml").is_file():
            raise RuntimeError(f"GenCase failed for {case_id}")


def allowed_uuids():
    inventory = json.loads((CAMPAIGN / "w00-inventory.json").read_text())
    return inventory["execution_policy"]["allowed_gpu_uuids"]


def run_one(case_id, config):
    gpu = config["gpu"]
    gpu_record = require_idle_allowed_gpu(gpu, allowed_uuids())
    prefix = ARTIFACT_ROOT / case_id / "generated" / case_id
    result = execute_attempt(
        case_id,
        [str(SOLVER), f"-gpu:{gpu}", str(prefix), "{output}"],
        RUN_ROOT,
        cwd=LAB,
        env=environment(),
        evidence_glob="data/Part_*.bi4",
        required_text="Finished execution (code=0)",
    )
    result["gpu_at_launch"] = gpu_record
    if result["status"] != "completed":
        raise RuntimeError(f"solver failed for {case_id}: {result['attempt_directory']}")
    return result


def run():
    # Two deliberately small controlled probes are safe to run concurrently.
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run_one, case_id, config) for case_id, config in PROBES.items()]
        return [future.result() for future in futures]


def partvtk_csv(data_dir, output_dir, onlytype="-all,+fluid"):
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    prefix = output_dir / "Particles"
    proc = subprocess.run([
        str(PARTVTK), "-dirdata", str(data_dir), "-savecsv", str(prefix),
        f"-onlytype:{onlytype}",
        "-vars:-all,+idp,+vel,+rhop,+press,+type,+mk,+mass,+zone", "-csvsep:1",
    ], cwd=LAB, env=environment(), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (output_dir / "partvtk.stdout.log").write_text(proc.stdout)
    frames = sorted(output_dir.glob("Particles_[0-9][0-9][0-9][0-9].csv"))
    if proc.returncode or not frames:
        raise RuntimeError(f"PartVTK failed for {data_dir}: {proc.stdout[-1000:]}")
    return frames


def latest_attempt(case_id):
    payload = json.loads((RUN_ROOT / case_id / "latest.json").read_text())
    return Path(payload["attempt_directory"])


def record(case_id, shifting):
    return {"id": case_id, "family": "W02", "mechanism": "velocity-position semantics",
            "shifting": shifting}


def displacement_velocity_audit(h5_path, dp=0.04):
    absolute = []
    normalized_dp = []
    speed = []
    intervals = 0
    samples = 0
    with h5py.File(h5_path, "r") as h5:
        times = h5["time"][:]
        for index, dt in enumerate(np.diff(times)):
            common = h5["valid"][index] & h5["valid"][index + 1]
            if not common.any():
                continue
            displacement = h5["position"][index + 1, common] - h5["position"][index, common]
            midpoint_displacement = 0.5 * (
                h5["velocity"][index, common] + h5["velocity"][index + 1, common]
            ) * dt
            residual = np.linalg.norm(displacement - midpoint_displacement, axis=1)
            absolute.append(residual)
            normalized_dp.append(residual / dp)
            speed.append(np.linalg.norm(0.5 * (
                h5["velocity"][index, common] + h5["velocity"][index + 1, common]), axis=1))
            intervals += 1
            samples += int(common.sum())
        retained = int((h5["valid"][0] & h5["valid"][-1]).sum())
        initial = int(h5["valid"][0].sum())
    absolute = np.concatenate(absolute)
    normalized_dp = np.concatenate(normalized_dp)
    speed = np.concatenate(speed)
    return {
        "intervals": intervals,
        "particle_interval_samples": samples,
        "identity_retention": retained / max(initial, 1),
        "midpoint_displacement_residual_m": {
            "median": float(np.median(absolute)), "p95": float(np.quantile(absolute, 0.95)),
            "max": float(np.max(absolute)),
        },
        "midpoint_displacement_residual_over_dp": {
            "median": float(np.median(normalized_dp)), "p95": float(np.quantile(normalized_dp, 0.95)),
            "max": float(np.max(normalized_dp)),
        },
        "midpoint_speed_m_per_s": {"median": float(np.median(speed)), "p95": float(np.quantile(speed, 0.95))},
    }


def read_csv_frame(path):
    frame = pd.read_csv(path, skiprows=3)
    frame.columns = [str(column).strip() for column in frame.columns]
    return frame.loc[:, ~frame.columns.str.startswith("Unnamed")]


def boundary_motion_audit():
    results = {}
    sources = {
        "motion_formulation": (LAB / "runs-official" / "O3_sloshing_motion" / "data", "-all,+moving"),
        "accelerated_frame_formulation": (LAB / "runs-official" / "O3_sloshing_acc" / "data", "-all,+fixed"),
    }
    for name, (source, particle_type) in sources.items():
        frames = partvtk_csv(source, ARTIFACT_ROOT / "reference-frame" / name, particle_type)
        first = read_csv_frame(frames[0]).sort_values(["Zone", "Idp"])
        last = read_csv_frame(frames[-1]).sort_values(["Zone", "Idp"])
        common = first.merge(last, on=["Zone", "Idp"], suffixes=("_0", "_1"))
        delta = np.column_stack([
            common[f"Pos.{axis} [m]_1"] - common[f"Pos.{axis} [m]_0"] for axis in "xyz"
        ])
        results[name] = {
            "particle_type_query": particle_type,
            "frames": len(frames), "common_boundary_particles": len(common),
            "boundary_displacement_median_m": float(np.median(np.linalg.norm(delta, axis=1))),
            "boundary_displacement_max_m": float(np.max(np.linalg.norm(delta, axis=1))),
            "observed_coordinate_interpretation": (
                "world/inertial coordinates: moving tank boundary coordinates change"
                if name == "motion_formulation" else
                "tank-attached coordinates: fixed boundaries remain fixed while AccInput supplies non-inertial forcing"
            ),
        }
    return results


def analyze(run_results=None):
    cases = {}
    for case_id, config in PROBES.items():
        attempt = latest_attempt(case_id)
        csvs = partvtk_csv(attempt / "data", attempt / "csv")
        out = DATA_ROOT / f"{case_id}.h5"
        convert_streaming(record(case_id, config["shifting"]), csvs, out)
        cases[case_id] = displacement_velocity_audit(out)
        cases[case_id]["shifting"] = config["shifting"]
        cases[case_id]["attempt_directory"] = str(attempt.relative_to(LAB))
    off = cases["W02_shift_off"]["midpoint_displacement_residual_over_dp"]["median"]
    full = cases["W02_shift_full"]["midpoint_displacement_residual_over_dp"]["median"]
    inventory = json.loads((CAMPAIGN / "case-registry.json").read_text())
    dimensionality = {}
    for item in inventory["cases"]:
        dimensionality[item.get("dimension", "unknown")] = dimensionality.get(item.get("dimension", "unknown"), 0) + 1
    compact_runs = None
    if run_results is not None:
        compact_runs = [{
            "case_id": item["case_id"], "attempt_id": item["attempt_id"],
            "status": item["status"], "elapsed_seconds": item["elapsed_seconds"],
            "frames": len(item["evidence_files"]), "gpu_at_launch": item["gpu_at_launch"],
        } for item in run_results]
    payload = {
        "schema_version": 1,
        "scope": "empirical W02 audit; not a formal benchmark result",
        "binary_under_test": "DualSPHysics 5.4.355 / GenCase 5.4.354.01",
        "controlled_shift_probes": cases,
        "shift_residual_median_ratio_full_over_off": full / max(off, 1e-30),
        "reference_frame_probes": boundary_motion_audit(),
        "first_round_case_dimensionality": dimensionality,
        "claims": {
            "idp": "Stable in these fixed-resolution probes; it identifies numerical SPH particles, not independently verified material parcels.",
            "position_velocity": "With shifting disabled, exported velocity approximately transports exported position over a short output interval. With shifting enabled, position includes additional numerical shifting displacement, so Vel alone is not the full trajectory derivative.",
            "reference_frames": "Motion and AccInput formulations expose different coordinate conventions and must carry explicit world/body transform metadata.",
            "scope_limit": "No claim is made here for variable-resolution split/merge identity; its (Zone,Idp) key remains numerical-node identity only.",
        },
        "run_results": compact_runs,
    }
    REPORT.write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "run", "analyze", "all"], default="all", nargs="?")
    args = parser.parse_args()
    results = None
    if args.action in {"prepare", "all"}:
        prepare()
    if args.action in {"run", "all"}:
        results = run()
    if args.action in {"analyze", "all"}:
        payload = analyze(results)
        print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
