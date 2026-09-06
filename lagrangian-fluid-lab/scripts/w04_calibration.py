#!/usr/bin/env python3
"""Run and analyse the W04 fundamental calibration suite."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
from pathlib import Path
import shutil
import subprocess

import h5py
import numpy as np

from campaign_runner import execute_attempt, require_idle_allowed_gpu
from trajectory_io import convert_streaming
from w02_semantics import partvtk_csv


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "v0.1-candidate"
BIN = LAB / "vendor" / "official" / "DualSPHysics_v5.4" / "bin" / "linux"
GENCASE = BIN / "GenCase_linux64"
SOLVER = BIN / "DualSPHysics5.4_linux64"
RUN_ROOT = CAMPAIGN / "runs"
CASE_ROOT = CAMPAIGN / "cases" / "w04"
ARTIFACT = CAMPAIGN / "artifacts" / "w04"
DATA = CAMPAIGN / "data" / "w04"
REPORT = CAMPAIGN / "w04-calibration.json"

OFFICIAL = LAB / "vendor" / "official" / "DualSPHysics_v5.4" / "examples"
POISEUILLE_DEF = OFFICIAL / "mdbc" / "02_Poiseuille" / "CasePoiseuilleLR_Def.xml"
EXP_SPHERE = OFFICIAL / "main" / "11_Floating" / "EXP_FloatingSphereVal2D_Displacement_Fekken2004.txt"

PROBES = {
    "W04_poiseuille": {
        "gpu": 4, "prefix": ARTIFACT / "W04_poiseuille" / "generated" / "W04_poiseuille",
        "flags": ["-mdbc"], "tmax": 5.0, "tout": 0.02,
    },
    "W04_small_slosh": {
        "gpu": 5, "prefix": LAB / "cases" / "official" / "O3_sloshing_motion" / "generated" / "O3_sloshing_motion",
        "flags": [], "tmax": 8.35, "tout": 0.02,
    },
    "W04_floating_sphere": {
        "gpu": 6, "prefix": LAB / "cases" / "official" / "O6_floating_sphere" / "generated" / "O6_floating_sphere",
        "flags": [], "tmax": 6.0, "tout": 0.02,
    },
}


def env():
    value = os.environ.copy()
    value["LD_LIBRARY_PATH"] = f"{BIN}:{value.get('LD_LIBRARY_PATH', '')}"
    return value


def prepare():
    CASE_ROOT.mkdir(parents=True, exist_ok=True)
    target_def = CASE_ROOT / "W04_poiseuille_Def.xml"
    shutil.copy2(POISEUILLE_DEF, target_def)
    prefix = PROBES["W04_poiseuille"]["prefix"]
    prefix.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run([str(GENCASE), str(target_def.with_suffix("")), str(prefix), "-save:all"],
                          cwd=CASE_ROOT, env=env(), text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (prefix.parent / "gencase.stdout.log").write_text(proc.stdout)
    if proc.returncode or not prefix.with_suffix(".xml").is_file():
        raise RuntimeError("W04 Poiseuille GenCase failed")
    provenance = {
        "W04_poiseuille": str(POISEUILLE_DEF.relative_to(LAB)),
        "W04_small_slosh": "cases/official/O3_sloshing_motion/generated/O3_sloshing_motion (dp=0.01)",
        "W04_floating_sphere": "cases/official/O6_floating_sphere/generated/O6_floating_sphere (dp=0.1)",
    }
    (CASE_ROOT / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")


def allowed_uuids():
    return json.loads((CAMPAIGN / "w00-inventory.json").read_text())["execution_policy"]["allowed_gpu_uuids"]


def run_one(case_id, config):
    gpu_record = require_idle_allowed_gpu(config["gpu"], allowed_uuids())
    command = [str(SOLVER), f"-gpu:{config['gpu']}", *config["flags"],
               str(config["prefix"]), "{output}", f"-tmax:{config['tmax']}", f"-tout:{config['tout']}"]
    result = execute_attempt(case_id, command, RUN_ROOT, cwd=config["prefix"].parent,
                             env=env(), evidence_glob="data/Part_*.bi4",
                             required_text="Finished execution (code=0)")
    result["gpu_at_launch"] = gpu_record
    if result["status"] != "completed":
        raise RuntimeError(f"{case_id} failed: {result['attempt_directory']}")
    return result


def run():
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(run_one, case_id, config) for case_id, config in PROBES.items()]
        return [future.result() for future in futures]


def latest(case_id):
    return Path(json.loads((RUN_ROOT / case_id / "latest.json").read_text())["attempt_directory"])


def normalize_outputs():
    DATA.mkdir(parents=True, exist_ok=True)
    for case_id in PROBES:
        attempt = latest(case_id)
        csvs = partvtk_csv(attempt / "data", attempt / "csv", "-all,+fluid,+floating")
        convert_streaming({"id": case_id, "family": "W04", "mechanism": "calibration", "shifting": 0},
                          csvs, DATA / f"{case_id}.h5")


def static_hydrostatic():
    path = CAMPAIGN / "data" / "C0_static_tank.h5"
    with h5py.File(path, "r") as h5:
        fluid0 = h5["valid"][0] & (h5["type"][0] == 3)
        fluid1 = h5["valid"][-1] & (h5["type"][-1] == 3)
        common = fluid0 & fluid1
        mass = h5["mass"][0, common]
        com0 = np.average(h5["position"][0, common], axis=0, weights=mass)
        com1 = np.average(h5["position"][-1, common], axis=0, weights=mass)
        speed = np.linalg.norm(h5["velocity"][-1, common], axis=1)
        z = h5["position"][-1, common, 2]
        pressure = h5["pressure"][-1, common]
        slope, intercept = np.polyfit(z, pressure, 1)
    expected = -1000 * 9.81
    return {
        "duration_s": 0.2, "fluid_particles": int(common.sum()),
        "center_of_mass_drift_over_dp": float(np.linalg.norm(com1 - com0) / 0.04),
        "final_speed_m_per_s": {"median": float(np.median(speed)), "p95": float(np.quantile(speed, 0.95))},
        "pressure_depth_slope_pa_per_m": float(slope),
        "expected_hydrostatic_slope_pa_per_m": expected,
        "relative_slope_error": float(abs(slope - expected) / abs(expected)),
        "pressure_fit_intercept_pa": float(intercept),
    }


def ballistic_translation():
    path = CAMPAIGN / "data" / "F2_airborne_slug_centered.h5"
    with h5py.File(path, "r") as h5:
        times = h5["time"][:]
        mask = h5["valid"][0] & (h5["type"][0] == 3)
        mass = h5["mass"][0, mask]
        com = np.asarray([np.average(h5["position"][i, mask], axis=0, weights=mass) for i in range(len(times))])
        v0 = np.average(h5["velocity"][0, mask], axis=0, weights=mass)
        zmin = np.asarray([h5["position"][i, mask, 2].min() for i in range(len(times))])
    # Stop before the block approaches the receiving floor: this is a manufactured free-flight check.
    selected = (times <= 0.2) & (zmin > 0.12)
    dt = times[selected] - times[0]
    expected = com[0] + dt[:, None] * v0
    expected[:, 2] -= 0.5 * 9.81 * dt ** 2
    error = np.linalg.norm(com[selected] - expected, axis=1)
    return {
        "comparison_frames": int(selected.sum()), "comparison_end_s": float(times[selected][-1]),
        "initial_com_velocity_m_per_s": v0.tolist(),
        "com_ballistic_error_over_dp": {"max": float(error.max() / 0.04), "final": float(error[-1] / 0.04)},
        "scope": "pre-impact center-of-mass motion only",
    }


def poiseuille():
    with h5py.File(DATA / "W04_poiseuille.h5", "r") as h5:
        mask = h5["valid"][-1] & (h5["type"][-1] == 3)
        z = h5["position"][-1, mask, 2]
        vx = h5["velocity"][-1, mask, 0]
    half_height, acceleration, viscosity = 0.5, 0.8, 0.1
    analytical = acceleration * (half_height ** 2 - z ** 2) / (2 * viscosity)
    error = vx - analytical
    return {
        "fluid_samples": int(mask.sum()), "analytical_half_height_m": half_height,
        "kinematic_viscosity_m2_per_s": viscosity, "body_acceleration_m_per_s2": acceleration,
        "analytical_centerline_speed_m_per_s": acceleration * half_height ** 2 / (2 * viscosity),
        "velocity_rmse_m_per_s": float(np.sqrt(np.mean(error ** 2))),
        "velocity_mae_m_per_s": float(np.mean(np.abs(error))),
        "simulated_max_speed_m_per_s": float(vx.max()),
    }


def dominant_period(time, signal, discard_before=1.0):
    selected = time >= discard_before
    t = time[selected]
    y = signal[selected] - np.mean(signal[selected])
    dt = float(np.median(np.diff(t)))
    spectrum = np.abs(np.fft.rfft(y * np.hanning(len(y))))
    frequency = np.fft.rfftfreq(len(y), dt)
    index = 1 + int(np.argmax(spectrum[1:]))
    return float(1 / frequency[index]), float(frequency[index])


def sloshing():
    with h5py.File(DATA / "W04_small_slosh.h5", "r") as h5:
        time = h5["time"][:]
        com_x = []
        for frame in range(len(time)):
            mask = h5["valid"][frame] & (h5["type"][frame] == 3)
            com_x.append(float(np.average(h5["position"][frame, mask, 0], weights=h5["mass"][frame, mask])))
    period, frequency = dominant_period(time, np.asarray(com_x))
    motion = np.loadtxt(OFFICIAL / "main" / "05_SloshingTank" / "CaseSloshingMotionData.dat", comments="#")
    peaks = np.flatnonzero((motion[1:-1, 1] > motion[:-2, 1]) & (motion[1:-1, 1] >= motion[2:, 1])) + 1
    forcing_period = float(np.median(np.diff(motion[peaks, 0])))
    width, depth = 0.9, 0.093
    wavenumber = math.pi / width
    linear_period = 2 * math.pi / math.sqrt(9.81 * wavenumber * math.tanh(wavenumber * depth))
    return {
        "frames": len(time), "duration_s": float(time[-1]),
        "fluid_com_dominant_period_s": period, "fluid_com_dominant_frequency_hz": frequency,
        "prescribed_tank_period_s": forcing_period,
        "relative_forcing_frequency_error": abs(period - forcing_period) / forcing_period,
        "linear_fundamental_period_s": linear_period,
        "note": "frequency-lock check under a prescribed approximately four-degree rotation; not a free-decay validation",
    }


def floating_sphere():
    with h5py.File(DATA / "W04_floating_sphere.h5", "r") as h5:
        time = h5["time"][:]
        z = []
        for frame in range(len(time)):
            mask = h5["valid"][frame] & (h5["type"][frame] == 2)
            z.append(float(h5["position"][frame, mask, 2].mean()))
    z = np.asarray(z)
    displacement = z - z[0]
    experiment = np.loadtxt(EXP_SPHERE, comments=("G.", "T("))
    exp_time = experiment[:, 0] / math.sqrt(9.81) + 1.0  # release occurs after FtPause=1 s
    selected = (time >= exp_time.min()) & (time <= min(exp_time.max(), time.max()))
    expected = np.interp(time[selected], exp_time, experiment[:, 1])
    error = displacement[selected] - expected
    return {
        "frames": len(time), "floating_particle_count": int(mask.sum()),
        "release_time_s": 1.0, "maximum_downward_displacement_m": float(-displacement.min()),
        "fekken_displacement_rmse_m": float(np.sqrt(np.mean(error ** 2))),
        "fekken_displacement_mae_m": float(np.mean(np.abs(error))),
        "note": "coarse dp=0.1 calibration; external curve is an anchor, not a passed production resolution",
    }


def analyze(run_results=None):
    normalize_outputs()
    compact = None if run_results is None else [{
        "case_id": item["case_id"], "attempt_id": item["attempt_id"], "status": item["status"],
        "elapsed_seconds": item["elapsed_seconds"], "frames": len(item["evidence_files"]),
        "gpu_at_launch": item["gpu_at_launch"],
    } for item in run_results]
    payload = {
        "schema_version": 1, "scope": "fundamental calibration, not formal validation",
        "static_hydrostatic": static_hydrostatic(),
        "ballistic_translation": ballistic_translation(),
        "viscous_poiseuille": poiseuille(),
        "prescribed_small_sloshing": sloshing(),
        "floating_buoyancy": floating_sphere(),
        "run_results": compact,
    }
    REPORT.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "run", "analyze", "all"], nargs="?", default="all")
    args = parser.parse_args()
    results = None
    if args.action in {"prepare", "all"}:
        prepare()
    if args.action in {"run", "all"}:
        results = run()
    if args.action in {"analyze", "all"}:
        analyze(results)


if __name__ == "__main__":
    main()
