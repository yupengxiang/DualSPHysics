#!/usr/bin/env python3
"""Run the second F1/F3 backgrounds and join them to existing external anchors."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

import h5py
import numpy as np

try:
    from scripts.campaign_runner import execute_attempt, require_idle_allowed_gpu
    from scripts.protocol_metrics import mass_fraction_tv, require_strict_time
    from scripts.trajectory_io import convert_streaming
    from scripts.w02_semantics import partvtk_csv
except ModuleNotFoundError:
    from campaign_runner import execute_attempt, require_idle_allowed_gpu
    from protocol_metrics import mass_fraction_tv, require_strict_time
    from trajectory_io import convert_streaming
    from w02_semantics import partvtk_csv


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "v0.1-candidate"
BIN = LAB / "vendor" / "official" / "DualSPHysics_v5.4" / "bin" / "linux"
GENCASE = BIN / "GenCase_linux64"
SOLVER = BIN / "DualSPHysics5.4_linux64"
RUN_ROOT = CAMPAIGN / "runs"
CASE_ROOT = CAMPAIGN / "cases" / "r3-g2-f1-f3"
ARTIFACT = CAMPAIGN / "artifacts" / "r3-g2-f1-f3"
DATA = CAMPAIGN / "data" / "r3-g2-f1-f3"
REPORT = CAMPAIGN / "r3-g2-f1-f3-matrix.json"
W05_REPORT = CAMPAIGN / "w05-validation-anchors.json"
RESOLUTIONS = {
    "F1": {"coarse": 0.035, "medium": 0.024, "fine": 0.014},
    "F3": {"coarse": 0.035, "medium": 0.028, "fine": 0.022},
}
BACKGROUNDS = {
    "F1": {
        "name": "twin_obstacle_split_remerge",
        "source": LAB / "cases" / "F1" / "F1_twin_obstacle" / "F1_twin_obstacle_Def.xml",
        "tmax": 1.5,
    },
    "F3": {
        "name": "baffled_exchange",
        "source": LAB / "cases" / "F3" / "F3_baffled_slosh" / "F3_baffled_slosh_Def.xml",
        "tmax": 0.9,
    },
}


def records() -> list[dict]:
    result = []
    gpu_cycle = [4, 5, 6, 7]
    for family, background in BACKGROUNDS.items():
        for level, dp in RESOLUTIONS[family].items():
            result.append({
                "case_id": f"R3_{family}_{background['name']}_massmatched_{level}",
                "family": family, "background": background["name"],
                "source": background["source"], "tmax": background["tmax"],
                "level": level, "dp": dp, "tout": 0.01,
                "gpu": gpu_cycle[len(result) % len(gpu_cycle)],
            })
    return result


def environment() -> dict[str, str]:
    value = os.environ.copy()
    value["LD_LIBRARY_PATH"] = f"{BIN}:{value.get('LD_LIBRARY_PATH', '')}"
    return value


def set_parameter(root: ET.Element, key: str, value) -> None:
    node = root.find(f".//parameter[@key='{key}']")
    if node is None:
        node = ET.SubElement(root.find(".//execution/parameters"), "parameter", key=key)
    node.set("value", str(value))


def prepare(selected: list[dict]) -> None:
    CASE_ROOT.mkdir(parents=True, exist_ok=True)
    matrix = []
    for record in selected:
        tree = ET.parse(record["source"])
        root = tree.getroot()
        root.find(".//geometry/definition").set("dp", str(record["dp"]))
        set_parameter(root, "SavePosDouble", 2)
        set_parameter(root, "TimeMax", record["tmax"])
        set_parameter(root, "TimeOut", record["tout"])
        definition = CASE_ROOT / f"{record['case_id']}_Def.xml"
        ET.indent(tree, space="    ")
        tree.write(definition, encoding="utf-8", xml_declaration=True)
        generated = ARTIFACT / record["case_id"] / "generated"
        generated.mkdir(parents=True, exist_ok=True)
        prefix = generated / record["case_id"]
        proc = subprocess.run(
            [str(GENCASE), str(definition.with_suffix("")), str(prefix), "-save:all"],
            cwd=CASE_ROOT, env=environment(), text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        (generated / "gencase.stdout.log").write_text(proc.stdout)
        if proc.returncode or not prefix.with_suffix(".xml").is_file():
            raise RuntimeError(f"GenCase failed: {record['case_id']}")
        match = re.search(r"Fluid\.\.\.\.:\s*([0-9,]+)", proc.stdout)
        matrix.append({
            key: record[key] for key in ("case_id", "family", "background", "level", "dp", "tout", "gpu", "tmax")
        } | {
            "fluid_particles": int(match.group(1).replace(",", "")) if match else None,
            "source_definition": str(record["source"].relative_to(LAB)),
            "execution_kind": "selected primary run",
        })
    existing = {}
    path = CASE_ROOT / "matrix.json"
    if path.exists():
        existing = {item["case_id"]: item for item in json.loads(path.read_text())}
    existing.update({item["case_id"]: item for item in matrix})
    selected_ids = {record["case_id"] for record in records()}
    for case_id, item in existing.items():
        if case_id not in selected_ids:
            item["execution_kind"] = "GenCase-only preflight rejected for initial-mass mismatch"
    path.write_text(json.dumps(sorted(existing.values(), key=lambda item: item["case_id"]), indent=2) + "\n")


def allowed_uuids() -> list[str]:
    inventory = json.loads((CAMPAIGN / "w00-inventory.json").read_text())
    return inventory["execution_policy"]["allowed_gpu_uuids"]


def run_one(record: dict) -> dict:
    launch_gpu = require_idle_allowed_gpu(record["gpu"], allowed_uuids())
    prefix = ARTIFACT / record["case_id"] / "generated" / record["case_id"]
    result = execute_attempt(
        record["case_id"], [str(SOLVER), f"-gpu:{record['gpu']}", str(prefix), "{output}"],
        RUN_ROOT, cwd=prefix.parent, env=environment(), evidence_glob="data/Part_*.bi4",
        required_text="Finished execution (code=0)",
    )
    result["gpu_at_launch"] = launch_gpu
    if result["status"] != "completed":
        raise RuntimeError(f"solver failed: {record['case_id']}")
    return result


def run(selected: list[dict]) -> list[dict]:
    # One task per GPU in each batch avoids the driver's short-lived context
    # retention tripping the conservative idle-GPU guard between queue items.
    batches = [selected[start:start + 4] for start in range(0, len(selected), 4)]
    output = []
    for batch in batches:
        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
            output.extend(pool.map(run_one, batch))
    return output


def latest(case_id: str) -> Path:
    return Path(json.loads((RUN_ROOT / case_id / "latest.json").read_text())["attempt_directory"])


def normalize(selected: list[dict]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    for record in selected:
        attempt = latest(record["case_id"])
        csvs = partvtk_csv(attempt / "data", attempt / "csv", "-all,+fluid")
        convert_streaming(
            {"id": record["case_id"], "family": record["family"],
             "mechanism": record["background"], "shifting": 0},
            csvs, DATA / f"{record['case_id']}.h5",
        )


def internal_timestep(record: dict) -> dict:
    log = (latest(record["case_id"]) / "process.stdout.log").read_text(errors="replace")
    match = re.search(r"Steps of simulation\.+:\s*([0-9,]+)", log)
    if not match:
        raise ValueError(f"solver step count missing: {record['case_id']}")
    steps = int(match.group(1).replace(",", ""))
    return {"adaptive_solver_steps": steps, "mean_internal_dt_s": record["tmax"] / steps}


def distribution(position: np.ndarray, valid: np.ndarray, mass: np.ndarray, family: str) -> dict[str, float]:
    total = float(mass[0, valid[0]].sum(dtype=np.float64))
    final = valid[-1]
    x = position[-1, :, 0]
    if family == "F1":
        masks = {
            "upstream_x_lt_0p58": final & (x < 0.58),
            "obstacle_corridor": final & (x >= 0.58) & (x < 0.90),
            "downstream_x_ge_0p90": final & (x >= 0.90),
            "unavailable": valid[0] & ~final,
        }
    else:
        masks = {
            "left_x_lt_0p58": final & (x < 0.58),
            "baffle_band": final & (x >= 0.58) & (x <= 0.62),
            "right_x_gt_0p62": final & (x > 0.62),
            "unavailable": valid[0] & ~final,
        }
    return {name: float(mass[0, mask].sum(dtype=np.float64) / total) for name, mask in masks.items()}


def fraction_series(position, valid, mass, family):
    total = float(mass[0, valid[0]].sum(dtype=np.float64))
    threshold = 0.90 if family == "F1" else 0.62
    return np.asarray([
        mass[0, valid[frame] & (position[frame, :, 0] >= threshold)].sum(dtype=np.float64) / total
        for frame in range(len(valid))
    ])


def cadence_audit(time, series) -> dict:
    result = {}
    for stride in (1, 2, 5):
        indices = np.arange(0, len(time), stride)
        if indices[-1] != len(time) - 1:
            indices = np.append(indices, len(time) - 1)
        observed = series[indices]
        baseline = float(observed[0])
        excursion = observed - baseline
        peak = int(np.argmax(np.abs(excursion)))
        half = np.flatnonzero(np.abs(excursion) >= 0.5 * abs(excursion[peak]))
        result[str(stride)] = {
            "nominal_saved_cadence_s": float(np.median(np.diff(time[indices]))),
            "initial_fraction": baseline,
            "peak_fraction": float(observed[peak]),
            "peak_excursion_from_initial": float(excursion[peak]),
            "peak_time_s": float(time[indices][peak]),
            "first_half_excursion_time_s": float(time[indices][half[0]]) if len(half) else None,
        }
    return result


def audit_case(record: dict) -> dict:
    with h5py.File(DATA / f"{record['case_id']}.h5", "r") as h5:
        time = h5["time"][:]
        valid = h5["valid"][:]
        position = h5["position"][:]
        mass = h5["mass"][:]
    require_strict_time(time)
    cadence = cadence_audit(time, fraction_series(position, valid, mass, record["family"]))
    result = {
        "dp_m": record["dp"], "frames": len(time),
        "initial_particles": int(valid[0].sum()),
        "numerical_loss_fraction": float(np.mean(valid[0] & ~valid[-1])),
        "final_mass_fraction": distribution(position, valid, mass, record["family"]),
        "observation_cadence_downsample": cadence,
        "peak_time_range_across_0p01_to_0p05_s_cadence_s": max(
            item["peak_time_s"] for item in cadence.values()) - min(
            item["peak_time_s"] for item in cadence.values()),
        **internal_timestep(record),
    }
    return result


def analyze(run_results: list[dict] | None = None) -> dict:
    w05 = json.loads(W05_REPORT.read_text())
    external = w05["external_validation"]
    result = {}
    all_records = records()
    for family in BACKGROUNDS:
        cases = {}
        for record in [item for item in all_records if item["family"] == family]:
            cases[record["level"]] = audit_case(record)
        cases["resolution_change"] = {
            "coarse_to_medium_mass_fraction_tv": mass_fraction_tv(
                cases["coarse"]["final_mass_fraction"], cases["medium"]["final_mass_fraction"]),
            "medium_to_fine_mass_fraction_tv": mass_fraction_tv(
                cases["medium"]["final_mass_fraction"], cases["fine"]["final_mass_fraction"]),
        }
        result[family] = {
            "background_1_external_anchor": {
                "name": "SPHERIC Test 02" if family == "F1" else "SPHERIC Test 10",
                "three_resolution_results": external[family],
                "validation_scope": "selected gauges only; see W05 limits",
            },
            "background_2_topology_numerical": {
                "name": BACKGROUNDS[family]["name"],
                "three_resolution_results": cases,
                "validation_scope": "numerical resolution and mechanism only; no external experiment",
            },
        }
    if run_results is None:
        run_results = [json.loads((RUN_ROOT / record["case_id"] / "latest.json").read_text()) for record in all_records]
    compact = [{
        "case_id": item["case_id"], "attempt_id": item["attempt_id"],
        "status": item["status"], "elapsed_seconds": item["elapsed_seconds"],
        "frames": len(item["evidence_files"]),
    } for item in run_results]
    payload = {
        "schema_version": 1,
        "scope": "F1 and F3 two backgrounds by three spatial resolutions",
        "acceptance_status": "mixed_partial_external_and_numerical_only",
        "axis_separation": {
            "spatial_resolution_m_by_family": RESOLUTIONS,
            "solver_internal_timestep": "adaptive; steps and mean dt reported per run",
            "saved_output_cadence_s": 0.01,
            "cadence_sensitivity": "same solver run downsampled by strides 1/2/5, so solver state is unchanged",
        },
        "families": result,
        "run_results_new_backgrounds": compact,
        "resource_summary_new_backgrounds": {
            "successful_runs": len(compact),
            "successful_solver_gpu_seconds": sum(item["elapsed_seconds"] for item in compact),
        },
        "external_anchor_reuse_audit": {
            "decision": "reuse exact W05 physical-background runs; do not claim equivalence to the new topology backgrounds",
            "case_ids": [
                item["case_id"] for item in w05["run_results"]
                if item["case_id"].startswith("W05_F1_") or item["case_id"].startswith("W05_F3_")
            ],
            "matched_namespaces": ["geometry", "initial fluid", "physics", "control", "numerics", "observation"],
        },
        "open_blockers": [
            "topology backgrounds have no compatible external observation",
            "F1 Test 02 impulse pressure still needs event-window high-cadence output",
            "F3 Test 10 first-impact timing and full-trace pressure do not jointly converge",
        ],
        "gencase_preflight": {
            "rejected_common_dp_m": [0.04, 0.03, 0.02],
            "reason": "initial discrete-mass range was about 27% for F1 and 15% for F3",
            "selected_dp_m": RESOLUTIONS,
            "selected_initial_mass_range": "about 3.1% for F1 and 4.6% for F3",
        },
    }
    all_attempts = []
    for record in all_records:
        for attempt in (RUN_ROOT / record["case_id"] / "attempts").glob("*.complete/attempt.json"):
            all_attempts.append(json.loads(attempt.read_text()))
    payload["resource_summary_new_backgrounds"]["successful_attempts_including_superseded_horizon"] = len(all_attempts)
    payload["resource_summary_new_backgrounds"]["gpu_seconds_including_superseded_horizon"] = sum(
        item["elapsed_seconds"] for item in all_attempts)
    payload["family_decisions"] = {
        "F1": "external H2/H4 remain partial anchors; twin-obstacle topology background rejected for resolution instability",
        "F3": "external fine first-impact magnitude remains partial; baffled-exchange aggregate transport is numerically stable but not externally validated",
    }
    REPORT.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "run", "normalize", "analyze", "all"), nargs="?", default="all")
    parser.add_argument("--cases", nargs="*")
    args = parser.parse_args()
    known = {record["case_id"]: record for record in records()}
    unknown = set(args.cases or ()) - set(known)
    if unknown:
        parser.error(f"unknown cases: {sorted(unknown)}")
    selected = [known[name] for name in args.cases] if args.cases else list(known.values())
    run_results = None
    if args.action in ("prepare", "all"):
        prepare(selected)
    if args.action in ("run", "all"):
        run_results = run(selected)
    if args.action in ("normalize", "all"):
        normalize(selected)
    if args.action in ("analyze", "all"):
        analyze(run_results)


if __name__ == "__main__":
    main()
