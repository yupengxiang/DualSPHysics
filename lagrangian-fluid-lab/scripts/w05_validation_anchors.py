#!/usr/bin/env python3
"""Three-resolution external validation anchors for F1, F3 and F6."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

import h5py
import numpy as np
import pandas as pd

from campaign_runner import execute_attempt, require_idle_allowed_gpu
from trajectory_io import convert_streaming
from w02_semantics import partvtk_csv


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "v0.1-candidate"
OFFICIAL_ROOT = LAB / "vendor" / "official" / "DualSPHysics_v5.4"
EXAMPLES = OFFICIAL_ROOT / "examples"
BIN = OFFICIAL_ROOT / "bin" / "linux"
GENCASE = BIN / "GenCase_linux64"
SOLVER = BIN / "DualSPHysics5.4_linux64"
MEASURE = BIN / "MeasureTool_linux64"
BOUNDARY = BIN / "BoundaryVTK_linux64"
RUN_ROOT = CAMPAIGN / "runs"
CASE_ROOT = CAMPAIGN / "cases" / "w05"
ARTIFACT = CAMPAIGN / "artifacts" / "w05"
DATA = CAMPAIGN / "data" / "w05"
REPORT = CAMPAIGN / "w05-validation-anchors.json"

FAMILIES = {
    "F1": {
        "source": EXAMPLES / "mdbc" / "04_Dambreak", "base": "CaseDamBreak3D",
        "dp": [0.04, 0.03, 0.02], "tmax": 6.0, "tout": 0.02, "flags": ["-mdbc"],
    },
    "F3": {
        "source": EXAMPLES / "mdbc" / "03_Sloshing", "base": "CaseSloshingLR",
        "dp": [0.008, 0.006, 0.004], "tmax": 8.35, "tout": 0.005, "flags": ["-mdbc"],
    },
    "F6": {
        "source": EXAMPLES / "main" / "11_Floating", "base": "CaseFloatingSphereVal2D",
        "dp": [0.10, 0.075, 0.05], "tmax": 6.0, "tout": 0.02, "flags": [],
    },
}


def probes():
    records = []
    gpu_cycle = [4, 5, 6, 7]
    index = 0
    for family, config in FAMILIES.items():
        for level, dp in zip(("coarse", "medium", "fine"), config["dp"]):
            case_id = f"W05_{family}_{level}"
            records.append({**config, "case_id": case_id, "family": family, "level": level,
                            "dp": dp, "gpu": gpu_cycle[index % len(gpu_cycle)]})
            index += 1
    return records


def env():
    value = os.environ.copy()
    value["LD_LIBRARY_PATH"] = f"{BIN}:{value.get('LD_LIBRARY_PATH', '')}"
    return value


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def prepare(records=None):
    CASE_ROOT.mkdir(parents=True, exist_ok=True)
    matrix = []
    records = records or probes()
    for record in records:
        working = ARTIFACT / record["case_id"] / "generated"
        shutil.copytree(record["source"], working, dirs_exist_ok=True)
        prefix = working / record["case_id"]
        proc = subprocess.run([
            str(GENCASE), str(working / f"{record['base']}_Def"), str(prefix),
            f"-dp:{record['dp']}", "-save:all",
        ], cwd=working, env=env(), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        # GenCase can truncate same-directory input time series; restore all authoritative assets.
        for source in record["source"].rglob("*"):
            if source.is_file():
                destination = working / source.relative_to(record["source"])
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
        (working / "gencase.stdout.log").write_text(proc.stdout)
        if proc.returncode or not prefix.with_suffix(".xml").is_file():
            raise RuntimeError(f"GenCase failed: {record['case_id']}")
        if record["family"] == "F3":
            # Coarse discretisations rotate a boundary node just beyond the
            # example's tight +Z numerical-domain limit. This changes only the
            # computational guard box, not physical tank geometry.
            xml_path = prefix.with_suffix(".xml")
            tree = ET.parse(xml_path)
            simdomain = tree.find(".//simulationdomain")
            simdomain.find("posmin").attrib.update({"x": "-0.85", "y": "0", "z": "-0.10"})
            simdomain.find("posmax").attrib.update({"x": "0.85", "y": "0", "z": "0.70"})
            tree.write(xml_path, encoding="utf-8", xml_declaration=True)
        match = re.search(r"Fluid\.\.\.\.:\s*([0-9,]+)", proc.stdout)
        fluid = int(match.group(1).replace(",", "")) if match else None
        matrix.append({key: record[key] for key in ("case_id", "family", "level", "dp", "gpu")}
                      | {"fluid_particles": fluid,
                         "source_definition": str((record["source"] / f"{record['base']}_Def.xml").relative_to(LAB))})
    external = ARTIFACT / "external"
    source_manifest = {
        "SPHERIC_Test2.zip": {
            "url": "https://9449af45-2363-44f6-8b03-03b6b7c2aee5.usrfiles.com/archives/9449af_6ce73873d6d04315853e481c337dbfca.zip",
            "sha256": sha256(external / "SPHERIC_Test2.zip"),
            "use": "F1 experimental pressures P1-P8 and elevations H1-H4",
        },
        "SPHERIC_TestCase14.zip": {
            "url": "https://9449af45-2363-44f6-8b03-03b6b7c2aee5.usrfiles.com/archives/9449af_89e9dae6260449eb9cae8af3a3cbcf2f.zip",
            "sha256": sha256(external / "SPHERIC_TestCase14.zip"),
            "use": "route audit only; Float1/Float2 geometry does not match packaged DualSPH Fekken cylinder example",
        },
        "bundled_test10_pressure": {
            "path": "vendor/official/DualSPHysics_v5.4/examples/mdbc/03_Sloshing/EXP_Pressure_SPHERIC_Benchmark#10.txt",
            "sha256": sha256(EXAMPLES / "mdbc" / "03_Sloshing" / "EXP_Pressure_SPHERIC_Benchmark#10.txt"),
        },
        "bundled_fekken_displacement": {
            "path": "vendor/official/DualSPHysics_v5.4/examples/main/11_Floating/EXP_FloatingSphereVal2D_Displacement_Fekken2004.txt",
            "sha256": sha256(EXAMPLES / "main" / "11_Floating" / "EXP_FloatingSphereVal2D_Displacement_Fekken2004.txt"),
        },
    }
    matrix_path = CASE_ROOT / "resolution-matrix.json"
    if matrix_path.exists() and len(records) != len(probes()):
        previous = json.loads(matrix_path.read_text())
        selected = {item["case_id"] for item in matrix}
        matrix = [item for item in previous if item["case_id"] not in selected] + matrix
        matrix.sort(key=lambda item: item["case_id"])
    matrix_path.write_text(json.dumps(matrix, indent=2) + "\n")
    (CASE_ROOT / "external-sources.json").write_text(json.dumps(source_manifest, indent=2) + "\n")


def allowed_uuids():
    return json.loads((CAMPAIGN / "w00-inventory.json").read_text())["execution_policy"]["allowed_gpu_uuids"]


def run_one(record):
    gpu_record = require_idle_allowed_gpu(record["gpu"], allowed_uuids())
    prefix = ARTIFACT / record["case_id"] / "generated" / record["case_id"]
    command = [str(SOLVER), f"-gpu:{record['gpu']}", *record["flags"], str(prefix), "{output}",
               f"-tmax:{record['tmax']}", f"-tout:{record['tout']}"]
    result = execute_attempt(record["case_id"], command, RUN_ROOT, cwd=prefix.parent, env=env(),
                             evidence_glob="data/Part_*.bi4", required_text="Finished execution (code=0)")
    result["gpu_at_launch"] = gpu_record
    if result["status"] != "completed":
        raise RuntimeError(f"{record['case_id']} failed: {result['attempt_directory']}")
    return result


def run_queue(records):
    return [run_one(record) for record in records]


def run(records=None):
    records = records or probes()
    queues = {gpu: [] for gpu in (4, 5, 6, 7)}
    for record in records:
        queues[record["gpu"]].append(record)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(run_queue, queue) for queue in queues.values()]
        return [result for future in futures for result in future.result()]


def latest(case_id):
    return Path(json.loads((RUN_ROOT / case_id / "latest.json").read_text())["attempt_directory"])


def subprocess_checked(command, log):
    proc = subprocess.run(command, cwd=LAB, env=env(), text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(proc.stdout)
    if proc.returncode:
        raise RuntimeError(f"postprocessor failed, see {log}")


def postprocess_f1(record):
    attempt = latest(record["case_id"])
    out = attempt / "measure"
    out.mkdir(exist_ok=True)
    subprocess_checked([
        str(MEASURE), "-dirdata", str(attempt / "data"),
        "-points", str(record["source"] / "elevation.txt"), "-onlytype:-all,+fluid",
        "-elevation:0.5", "-savecsv", str(out / "elevation"),
    ], out / "elevation.stdout.log")
    subprocess_checked([
        str(MEASURE), "-dirdata", str(attempt / "data"),
        "-points", str(record["source"] / "pressure.txt"), "-onlytype:+all,+fluid",
        "-vars:-all,+press", "-kclimit:0.5", "-savecsv", str(out / "pressure"),
    ], out / "pressure.stdout.log")
    return attempt


def postprocess_f3(record):
    attempt = latest(record["case_id"])
    out = attempt / "measure"
    out.mkdir(exist_ok=True)
    posprefix = out / "sensor_position"
    subprocess_checked([
        str(BOUNDARY), "-motiondata", str(attempt / "data"),
        "-saveposmotion:10:-0.448:0:0.093", str(posprefix),
    ], out / "boundaryvtk.stdout.log")
    positions = sorted(out.glob("sensor_position_mk0010.csv"))
    if not positions:
        raise RuntimeError(f"moving sensor coordinates missing for {record['case_id']}")
    subprocess_checked([
        str(MEASURE), "-dirdata", str(attempt / "data"), "-pointspos", str(positions[0]),
        "-onlytype:-all,+fluid", "-vars:-all,+press,+kcorr", "-kcusedummy:0", "-kclimit:0.5",
        "-savecsv", str(out / "pressure"),
    ], out / "pressure.stdout.log")
    return attempt


def postprocess_f6(record):
    attempt = latest(record["case_id"])
    csvs = partvtk_csv(attempt / "data", attempt / "csv-floating", "-all,+floating")
    output = DATA / f"{record['case_id']}.h5"
    convert_streaming({"id": record["case_id"], "family": "F6", "mechanism": "heave validation", "shifting": 0},
                      csvs, output)
    return attempt


def postprocess(records=None):
    for record in records or probes():
        {"F1": postprocess_f1, "F3": postprocess_f3, "F6": postprocess_f6}[record["family"]](record)


def csv_candidates(directory, prefix):
    return sorted(path for path in directory.glob(f"{prefix}*.csv") if "Resume" not in path.name)


def read_measure_csv(path):
    # MeasureTool files use semicolon or comma according to local tool defaults.
    for separator in (";", ","):
        frame = pd.read_csv(path, sep=separator, comment="#", skiprows=3)
        if len(frame.columns) > 1:
            frame.columns = [str(column).strip() for column in frame.columns]
            return frame
    raise ValueError(f"cannot parse MeasureTool CSV: {path}")


def align_rmse(sim_time, sim_value, exp_time, exp_value, start=0.0, end=None):
    order = np.argsort(exp_time)
    exp_time, exp_value = np.asarray(exp_time)[order], np.asarray(exp_value)[order]
    selected = (sim_time >= max(start, exp_time.min())) & (sim_time <= exp_time.max())
    if end is not None:
        selected &= sim_time <= end
    target = np.interp(sim_time[selected], exp_time, exp_value)
    error = sim_value[selected] - target
    return float(np.sqrt(np.mean(error ** 2))), float(np.mean(np.abs(error))), int(selected.sum())


def find_time_column(frame):
    return next(column for column in frame.columns if "time" in column.lower())


def numeric_columns(frame, exclude=()):
    return [column for column in frame.columns if column not in exclude and np.issubdtype(frame[column].dtype, np.number)]


def f1_metrics(record, experiment):
    attempt = latest(record["case_id"])
    elevation_file = csv_candidates(attempt / "measure", "elevation")[0]
    elevation = read_measure_csv(elevation_file)
    time_column = find_time_column(elevation)
    columns = numeric_columns(elevation, (time_column, "Part"))[:4]
    elevation_metrics = {}
    for index, column in enumerate(columns):
        exp_column = f"H{index + 1} (m)"
        rmse, mae, samples = align_rmse(elevation[time_column].to_numpy(), elevation[column].to_numpy(),
                                        experiment["Time (s)"].to_numpy(), experiment[exp_column].to_numpy(), end=6.0)
        elevation_metrics[f"H{index + 1}"] = {"rmse_m": rmse, "mae_m": mae, "samples": samples}
    pressure = read_measure_csv(attempt / "measure" / "pressure_Press.csv")
    pressure_time = find_time_column(pressure)
    pressure_columns = numeric_columns(pressure, (pressure_time, "Part"))[:8]
    pressure_metrics = {}
    for index, column in enumerate(pressure_columns):
        exp_column = f"P{index + 1} (Pa)"
        rmse, mae, samples = align_rmse(pressure[pressure_time].to_numpy(), pressure[column].to_numpy(),
                                        experiment["Time (s)"].to_numpy(), experiment[exp_column].to_numpy(), end=6.0)
        pressure_metrics[f"P{index + 1}"] = {"rmse_pa": rmse, "mae_pa": mae, "samples": samples}
    return {"surface_elevation": elevation_metrics, "pressure": pressure_metrics}


def f3_metrics(record):
    attempt = latest(record["case_id"])
    pressure_file = attempt / "measure" / "pressure_Press.csv"
    simulated = read_measure_csv(pressure_file)
    time_column = find_time_column(simulated)
    pressure_column = next(column for column in simulated.columns if "press" in column.lower())
    experiment = pd.read_csv(record["source"] / "EXP_Pressure_SPHERIC_Benchmark#10.txt",
                             sep=r"\s+", skiprows=1)
    rmse, mae, samples = align_rmse(simulated[time_column].to_numpy(), simulated[pressure_column].to_numpy(),
                                    experiment["time"].to_numpy(), experiment["Pressure(Pa)"].to_numpy(), end=8.35)
    # Compare the first documented lateral impact, not unrelated later-cycle maxima.
    sim_mask = (simulated[time_column] >= 2.0) & (simulated[time_column] <= 3.0)
    exp_mask = (experiment["time"] >= 2.0) & (experiment["time"] <= 3.0)
    sim_peak_i = simulated.loc[sim_mask, pressure_column].idxmax()
    exp_peak_i = experiment.loc[exp_mask, "Pressure(Pa)"].idxmax()
    return {
        "pressure_rmse_pa": rmse, "pressure_mae_pa": mae, "samples": samples,
        "simulated_peak_pa": float(simulated.loc[sim_peak_i, pressure_column]),
        "experimental_peak_pa": float(experiment.loc[exp_peak_i, "Pressure(Pa)"]),
        "peak_time_error_s": float(abs(simulated.loc[sim_peak_i, time_column] - experiment.loc[exp_peak_i, "time"])),
    }


def f6_metrics(record):
    with h5py.File(DATA / f"{record['case_id']}.h5", "r") as h5:
        time = h5["time"][:]
        z = np.asarray([h5["position"][frame, h5["valid"][frame], 2].mean() for frame in range(len(time))])
    displacement = z - z[0]
    experiment = np.loadtxt(record["source"] / "EXP_FloatingSphereVal2D_Displacement_Fekken2004.txt", skiprows=2)
    exp_time = experiment[:, 0] / math.sqrt(9.81) + 1.0
    rmse, mae, samples = align_rmse(time, displacement, exp_time, experiment[:, 1], start=1.0)
    aligned = (time >= exp_time.min()) & (time <= exp_time.max())
    return {"displacement_rmse_m": rmse, "displacement_mae_m": mae, "samples": samples,
            "maximum_downward_displacement_m": float(-displacement[aligned].min())}


def analyze(run_results=None):
    experiment_path = ARTIFACT / "external" / "test2" / "test_case_2_exp_data.xls"
    experiment = pd.read_excel(experiment_path, sheet_name="Experimental_data")
    results = {"F1": {}, "F3": {}, "F6": {}}
    for record in probes():
        metric = {"F1": lambda: f1_metrics(record, experiment),
                  "F3": lambda: f3_metrics(record), "F6": lambda: f6_metrics(record)}[record["family"]]()
        results[record["family"]][record["level"]] = {"dp_m": record["dp"], **metric}
    if run_results is None:
        run_results = [json.loads((RUN_ROOT / record["case_id"] / "latest.json").read_text())
                       for record in probes()]
    compact = [{
        "case_id": item["case_id"], "attempt_id": item["attempt_id"], "status": item["status"],
        "elapsed_seconds": item["elapsed_seconds"], "frames": len(item["evidence_files"]),
        "failed_attempts_before_success": len(list((RUN_ROOT / item["case_id"] / "attempts").glob("*.failed"))),
        **({"gpu_at_launch": item["gpu_at_launch"]} if "gpu_at_launch" in item else {}),
    } for item in run_results]
    payload = {
        "schema_version": 1,
        "external_validation": results,
        "interpretation_limits": {
            "F1": "SPHERIC Test 02 H1-H4 elevation only in current automated metric; pressure remains available for later impulse-window analysis.",
            "F3": "SPHERIC Test 10 pressure is highly impulsive and experimentally variable; report full-trace and event timing separately.",
            "F6": "Three-resolution executable anchor is the bundled Fekken 2004 2D cylinder release, not SPHERIC Test 14.",
            "test14_route": "Official Test 14 archive and STLs were acquired. A new 3D tank/body definition and initial-offset protocol are required before it can replace the surrogate anchor.",
        },
        "resource_summary": {
            "successful_solver_gpu_seconds": sum(item["elapsed_seconds"] for item in compact),
            "successful_runs": len(compact),
            "failed_attempts": sum(item["failed_attempts_before_success"] for item in compact),
        },
        "run_results": compact,
    }
    REPORT.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "run", "postprocess", "analyze", "all"], nargs="?", default="all")
    parser.add_argument("--cases", nargs="*", help="limit prepare/run/postprocess to case ids")
    args = parser.parse_args()
    known = {record["case_id"]: record for record in probes()}
    unknown = set(args.cases or []) - set(known)
    if unknown:
        parser.error(f"unknown cases: {sorted(unknown)}")
    selected = [known[case_id] for case_id in args.cases] if args.cases else list(known.values())
    run_results = None
    if args.action in {"prepare", "all"}:
        prepare(selected)
    if args.action in {"run", "all"}:
        run_results = run(selected)
    if args.action in {"postprocess", "all"}:
        postprocess(selected)
    if args.action in {"analyze", "all"}:
        analyze(run_results)


if __name__ == "__main__":
    main()
