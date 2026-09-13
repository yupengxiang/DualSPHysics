#!/usr/bin/env python3
"""Prepare and execute the first L2 F1/F2 canaries.

The canaries are deliberately small in count but use the nominal L2 reference
spacing.  F1 is a resolved obstacle release and F2 is a real rotating-cup
candidate rebound from the read-only W06 evidence, with its definition
rebound at the L2 nominal spacing.  Nothing in this script promotes a canary
to family qualification or material truth.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import subprocess
import time
import xml.etree.ElementTree as ET

import h5py
import numpy as np

try:
    from scripts.campaign_runner import execute_attempt, require_idle_allowed_gpu
    from scripts.l2_campaign import (
        CAMPAIGN,
        LAB,
        atomic_json,
        inspect_hdf5,
        read_json,
        repo_relative,
        require_adopted,
        sha256_file,
        update_stage,
        update_usage,
        utc_now,
    )
    from scripts.trajectory_io import convert_streaming
    from scripts.w02_semantics import partvtk_csv
except ModuleNotFoundError:  # direct invocation from scripts/
    from campaign_runner import execute_attempt, require_idle_allowed_gpu
    from l2_campaign import (
        CAMPAIGN,
        LAB,
        atomic_json,
        inspect_hdf5,
        read_json,
        repo_relative,
        require_adopted,
        sha256_file,
        update_stage,
        update_usage,
        utc_now,
    )
    from trajectory_io import convert_streaming
    from w02_semantics import partvtk_csv


BIN = LAB / "vendor" / "official" / "DualSPHysics_v5.4" / "bin" / "linux"
GENCASE = BIN / "GenCase_linux64"
SOLVER = BIN / "DualSPHysics5.4_linux64"
PARTVTK = BIN / "PartVTK_linux64"
INVENTORY = LAB / "campaigns" / "v0.1-candidate" / "w00-inventory.json"
C1_ROOT = CAMPAIGN / "c1-canary"
CASE_ROOT = C1_ROOT / "cases"
ARTIFACT_ROOT = C1_ROOT / "artifacts"
RUN_ROOT = CAMPAIGN / "runs"
DATA_ROOT = C1_ROOT / "data"
REPORT_PATH = CAMPAIGN / "reports" / "c1-canary.json"
NOMINAL_DP = 0.0075


def environment() -> dict[str, str]:
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = f"{BIN}:{env.get('LD_LIBRARY_PATH', '')}"
    return env


def sha256(path: Path) -> str:
    return sha256_file(path)[0]


def directory_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def child_cpu_seconds() -> float:
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return float(usage.ru_utime + usage.ru_stime)


def inventory_allowlist() -> list[str]:
    payload = read_json(INVENTORY)
    return list(payload["execution_policy"]["allowed_gpu_uuids"])


def set_parameter(root: ET.Element, key: str, value: str | int | float) -> None:
    node = root.find(f".//parameter[@key='{key}']")
    if node is None:
        parameters = root.find(".//execution/parameters")
        if parameters is None:
            raise ValueError(f"missing execution parameters for {key}")
        node = ET.SubElement(parameters, "parameter", key=key)
    node.set("value", str(value))


def set_spacing(root: ET.Element, spacing: float) -> None:
    nodes = root.findall(".//geometry/definition")
    if not nodes:
        raise ValueError("case definition has no geometry definition")
    for node in nodes:
        node.set("dp", f"{spacing:.16g}")


def write_rotation_control(path: Path, *, duration: float = 1.2, final_angle: float = -105.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = ["#Time;Degrees"]
    for current in np.linspace(0.0, 2.5, 251):
        if current <= 0.5:
            angle = 0.0
        elif current >= 0.5 + duration:
            angle = final_angle
        else:
            phase = (current - 0.5) / duration
            angle = final_angle * 0.5 * (1.0 - math.cos(math.pi * phase))
        rows.append(f"{current:.6f};{angle:.9f}")
    path.write_text("\n".join(rows) + "\n")


def configs() -> list[dict]:
    return [
        {
            "case_id": "L2_C1_F1_obstacle_nominal",
            "family": "F1",
            "mechanism": "resolved-obstacle-collapse-split-return",
            "source_definition": LAB / "cases/F1/F1_center_obstacle/F1_center_obstacle_Def.xml",
            "recipe_id": "L2_F1_C1_obstacle_dbc_native_v1_dp0p0075",
            "physical_case_id": "physical_L2_F1_obstacle_center_nominal_v1",
            "lineage_group_id": "lineage_L2_F1_obstacle_center_nominal_v1",
            "paired_background_id": "paired_L2_F1_obstacle_v1",
            "view_id": "world_fluid_particle_v1",
            "resolution_m": NOMINAL_DP,
            "time_max_s": 0.6,
            "time_out_s": 0.02,
            "gpu": 4,
            "wall_bounds": {"xmin": 0.0, "xmax": 1.2, "ymin": 0.0, "ymax": 0.4, "zmin": 0.0},
            "control_semantics": "none; gravity and initial release are fixed inputs",
        },
        {
            "case_id": "L2_C1_F2_rotation_center_nominal",
            "family": "F2",
            "mechanism": "real-rotating-cup-centered-catch",
            "source_definition": LAB / "campaigns/v0.1-candidate/cases/w06/W06_standard_slow_center_Def.xml",
            "source_motion": LAB / "campaigns/v0.1-candidate/cases/w06/W06_standard_slow_center_motion.dat",
            "recipe_id": "L2_F2_C1_rotation_cup_dbc_v1_dp0p0075",
            "physical_case_id": "physical_L2_F2_rotation_cup_center_nominal_v1",
            "lineage_group_id": "lineage_L2_F2_rotation_cup_center_nominal_v1",
            "paired_background_id": "paired_L2_F2_rotation_cup_v1",
            "view_id": "world_fluid_particle_v1",
            "resolution_m": NOMINAL_DP,
            "time_max_s": 2.5,
            "time_out_s": 0.02,
            "gpu": 5,
            "wall_bounds": {"xmin": -0.6, "xmax": 2.0, "ymin": -0.55, "ymax": 0.55, "zmin": -0.25},
            "control_semantics": "known prescribed cup rotation; no future fluid state",
        },
    ]


def prepare_case(config: dict) -> dict:
    case_id = config["case_id"]
    definition = CASE_ROOT / f"{case_id}_Def.xml"
    definition.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.parse(config["source_definition"])
    root = tree.getroot()
    set_spacing(root, config["resolution_m"])
    set_parameter(root, "SavePosDouble", 2)
    set_parameter(root, "TimeMax", config["time_max_s"])
    set_parameter(root, "TimeOut", config["time_out_s"])
    if config["family"] == "F2":
        motion_name = f"{case_id}_motion.dat"
        for node in root.findall(".//mvrotfile/file"):
            node.set("name", motion_name)
        motion_path = definition.parent / motion_name
        write_rotation_control(motion_path)
        config["motion_path"] = motion_path
    ET.indent(tree, space="    ")
    tree.write(definition, encoding="utf-8", xml_declaration=True)
    generated_dir = ARTIFACT_ROOT / case_id / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    prefix = generated_dir / case_id
    process = subprocess.run(
        [str(GENCASE), str(definition.with_suffix("")), str(prefix), "-save:all"],
        cwd=definition.parent, env=environment(), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    (generated_dir / "gencase.stdout.log").write_text(process.stdout)
    if process.returncode != 0 or not prefix.with_suffix(".xml").is_file():
        raise RuntimeError(f"GenCase failed for {case_id}: {process.stdout[-1200:]}")
    config["definition"] = definition
    config["generated_prefix"] = prefix
    config["generated_xml"] = prefix.with_suffix(".xml")
    config["prepare_returncode"] = process.returncode
    config["source_definition_sha256"] = sha256(config["source_definition"])
    config["definition_sha256"] = sha256(definition)
    config["generated_xml_sha256"] = sha256(config["generated_xml"])
    config["generated_particle_summary"] = {
        "bytes": prefix.with_suffix(".xml").stat().st_size,
        "directory_bytes": directory_bytes(generated_dir),
    }
    return config


def run_case(config: dict, allowed_uuids: list[str]) -> dict:
    gpu_record = require_idle_allowed_gpu(config["gpu"], allowed_uuids)
    prefix = config["generated_prefix"]
    result = execute_attempt(
        config["case_id"],
        [str(SOLVER), f"-gpu:{config['gpu']}", str(prefix), "{output}"],
        RUN_ROOT,
        cwd=LAB,
        env=environment(),
        evidence_glob="data/Part_*.bi4",
        required_text="Finished execution (code=0)",
        timeout_seconds=3600,
        resource_category="qualification",
    )
    result["gpu_at_launch"] = gpu_record
    result["input_definition_sha256"] = config["definition_sha256"]
    result["recipe_id"] = config["recipe_id"]
    result["solver_binary_sha256"] = sha256(SOLVER)
    return result


def parse_motion(path: Path) -> tuple[np.ndarray, np.ndarray]:
    values = []
    for raw in path.read_text().splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        time_value, angle = raw.split(";")
        values.append((float(time_value), float(angle)))
    array = np.asarray(values, dtype=np.float64)
    return array[:, 0], array[:, 1]


def add_semantics(hdf5_path: Path, config: dict, attempt: dict) -> dict:
    with h5py.File(hdf5_path, "r+") as handle:
        handle.attrs["l2_recipe_id"] = config["recipe_id"]
        handle.attrs["physical_case_id"] = config["physical_case_id"]
        handle.attrs["lineage_group_id"] = config["lineage_group_id"]
        handle.attrs["paired_background_id"] = config["paired_background_id"]
        handle.attrs["attempt_id"] = attempt["attempt_id"]
        handle.attrs["view_id"] = config["view_id"]
        handle.attrs["data_qualification_status"] = "canary_structural_only"
        handle.attrs["T2_macro_status"] = "not_assessed"
        handle.attrs["T2_path_status"] = "not_assessed"
        handle.attrs["source_label_semantics"] = "initial Mk is a numerical source partition; not material truth"
        handle.attrs["control_semantics"] = config["control_semantics"]
        if "source_label_initial_mk" in handle:
            del handle["source_label_initial_mk"]
        handle.create_dataset("source_label_initial_mk", data=np.asarray(handle["mk"][0], dtype=np.int16))
        if config["family"] == "F2":
            motion_time, motion_angle = parse_motion(config["motion_path"])
            trajectory_time = np.asarray(handle["time"][:], dtype=np.float64)
            group = handle.require_group("control")
            if "time_s" in group:
                del group["time_s"]
            if "cup_angle_degrees" in group:
                del group["cup_angle_degrees"]
            group.create_dataset("time_s", data=trajectory_time)
            group.create_dataset("cup_angle_degrees", data=np.interp(trajectory_time, motion_time, motion_angle))
            handle.attrs["control_file_sha256"] = sha256(config["motion_path"])
    # Every L2 canary must declare the control information that is available
    # to a future model.  F1/F4/F5 use fixed initial conditions and gravity;
    # F2 uses a replayable motion file.  The previous F1/F2-specific test
    # incorrectly rejected the explicit control declaration on C3 anchors.
    return {
        "source_semantics_present": True,
        "control_semantics_present": bool(config.get("control_semantics"))
        and (config["family"] != "F2" or config.get("motion_path", Path()).is_file()),
    }


def audit_case(config: dict, attempt: dict) -> dict:
    attempt_dir = Path(attempt["attempt_directory"])
    csv_dir = attempt_dir / "csv"
    csv_paths = partvtk_csv(attempt_dir / "data", csv_dir, "-all,+fluid")
    output = DATA_ROOT / f"{config['case_id']}.h5"
    record = {
        "id": config["case_id"],
        "family": config["family"],
        "mechanism": config["mechanism"],
        "shifting": 0,
    }
    convert_streaming(record, csv_paths, output)
    semantic = add_semantics(output, config, attempt)
    independent = inspect_hdf5(output, full_scan=True, wall_bounds=config["wall_bounds"])
    with h5py.File(output, "r") as handle:
        initial_valid = np.asarray(handle["valid"][0], dtype=bool)
        final_valid = np.asarray(handle["valid"][-1], dtype=bool)
        mass = np.asarray(handle["mass"][0], dtype=np.float64)
        initial_mass = float(np.nansum(mass[initial_valid]))
        final_mass = float(np.nansum(mass[final_valid]))
        source_labels = np.asarray(handle["source_label_initial_mk"][:], dtype=np.int16)
        source_counts = {str(int(value)): int(np.sum(initial_valid & (source_labels == value)))
                         for value in np.unique(source_labels[initial_valid])}
        control = handle.get("control")
        control_check = {"required": config["family"] == "F2", "present": True}
        if config["family"] == "F2":
            angles = np.asarray(control["cup_angle_degrees"][:], dtype=np.float64) if control is not None else np.array([])
            times = np.asarray(handle["time"][:], dtype=np.float64)
            static = angles.size > 0 and bool(np.all(np.abs(angles[times <= 0.5 + 1e-9]) <= 1e-8))
            control_check.update({
                "static_hold_before_rotation": static,
                "final_angle_degrees": float(angles[-1]) if angles.size else None,
                "replayable_from_declared_file": bool(handle.attrs.get("control_file_sha256")),
            })
        else:
            control_check["present"] = True
    hard_integrity = bool(
        attempt["status"] == "completed"
        and independent.get("structural_pass")
        and all(independent.get("finite", {}).values())
        and independent.get("wall_violation_count") == 0
        and semantic["source_semantics_present"]
        and semantic["control_semantics_present"]
        and control_check.get("static_hold_before_rotation", True)
        and control_check.get("replayable_from_declared_file", True)
    )
    return {
        "case_id": config["case_id"],
        "family": config["family"],
        "recipe_id": config["recipe_id"],
        "physical_case_id": config["physical_case_id"],
        "lineage_group_id": config["lineage_group_id"],
        "paired_background_id": config["paired_background_id"],
        "attempt_id": attempt["attempt_id"],
        "attempt_directory": str(attempt_dir),
        "hdf5": str(output),
        "hdf5_sha256": sha256(output),
        "frame_count": independent.get("frame_count"),
        "particle_count": independent.get("particle_count"),
        "time_end_s": independent.get("time_end_s"),
        "source_counts_initial": source_counts,
        "initial_mass_kg": initial_mass,
        "final_mass_kg": final_mass,
        "final_mass_fraction": final_mass / initial_mass if initial_mass else None,
        "missing_initial_identities_at_final": int(np.sum(initial_valid & ~final_valid)),
        "independent_audit": independent,
        "semantic_audit": semantic,
        "control_audit": control_check,
        "canary_hard_integrity_pass": hard_integrity,
        "qualification_claim": "none; canary structural evidence only",
        "T2_macro": "not_assessed",
        "T2_path": "not_assessed",
    }


def run_all(selected_gpus: list[int], family_filter: set[str] | None = None, *, append: bool = False) -> dict:
    state = require_adopted()
    if state["stages"]["C0"]["status"] not in {"complete", "complete_with_findings"}:
        raise RuntimeError("C1 requires C0 to be complete")
    if not append and state["stages"]["C1"]["status"] not in {"ready", "pending"}:
        raise RuntimeError("C1 already has a terminal status; refusing an untracked rerun")
    if append and state["stages"]["C1"]["status"] != "complete":
        raise RuntimeError("an appended C1 canary requires the original C1 record to be complete")
    if not GENCASE.is_file() or not SOLVER.is_file() or not PARTVTK.is_file():
        raise FileNotFoundError("official GenCase, solver, and PartVTK binaries are required")
    selected = [config for config in configs() if family_filter is None or config["family"] in family_filter]
    if not selected:
        raise ValueError("C1 family filter selected no cases")
    if len(selected_gpus) < len(selected):
        raise ValueError(f"C1 needs {len(selected)} allowlisted physical GPU indices for the selected canaries")
    prior = read_json(REPORT_PATH) if append and REPORT_PATH.is_file() else {}
    prior_families = {item.get("family") for item in prior.get("audits", [])}
    selected_families = {config["family"] for config in selected}
    if prior_families & selected_families:
        raise RuntimeError(f"refusing duplicate family canary append: {sorted(prior_families & selected_families)}")
    before_bytes = sum(directory_bytes(path) for path in (C1_ROOT, ARTIFACT_ROOT, DATA_ROOT))
    allowed = inventory_allowlist()
    started_wall = time.perf_counter()
    child_before = child_cpu_seconds()
    prepared = []
    for config in selected:
        config["gpu"] = selected_gpus[len(prepared)]
        prepared.append(prepare_case(config))
    attempts = []
    audits = []
    stop_reason = None
    # Sequential launch avoids hiding a common input error behind two heavy
    # concurrent jobs.  The second canary is admitted only after the first
    # has produced a completed solver attempt.
    for config in prepared:
        attempt = run_case(config, allowed)
        attempts.append({
            "case_id": config["case_id"],
            "family": config["family"],
            "attempt": attempt,
            "input": {
                "source_definition": repo_relative(config["source_definition"]),
                "source_definition_sha256": config["source_definition_sha256"],
                "definition": repo_relative(config["definition"]),
                "definition_sha256": config["definition_sha256"],
                "generated_xml": repo_relative(config["generated_xml"]),
                "generated_xml_sha256": config["generated_xml_sha256"],
                "resolution_m": config["resolution_m"],
            },
        })
        if attempt["status"] != "completed":
            stop_reason = "first canary did not complete; cohort stopped before the next heavy solver attempt"
            break
        audits.append(audit_case(config, attempt))
        if not audits[-1]["canary_hard_integrity_pass"]:
            stop_reason = "canary completed but failed a hard structural/source gate; cohort stopped"
            break
    child_after = child_cpu_seconds()
    used_bytes = sum(directory_bytes(path) for path in (C1_ROOT, ARTIFACT_ROOT, DATA_ROOT))
    run_wall = sum(item["attempt"].get("elapsed_seconds", 0.0) for item in attempts)
    all_prepared = list(prior.get("prepared_cases", [])) + [
        {
            "case_id": config["case_id"],
            "family": config["family"],
            "recipe_id": config["recipe_id"],
            "resolution_m": config["resolution_m"],
            "definition": repo_relative(config["definition"]),
            "definition_sha256": config["definition_sha256"],
            "source_definition": repo_relative(config["source_definition"]),
            "source_definition_sha256": config["source_definition_sha256"],
            "generated_xml": repo_relative(config["generated_xml"]),
            "generated_xml_sha256": config["generated_xml_sha256"],
        }
        for config in prepared
    ]
    all_attempts = list(prior.get("attempts", [])) + attempts
    all_audits = list(prior.get("audits", [])) + audits
    all_pass = {item["family"] for item in all_audits if item["canary_hard_integrity_pass"]} >= {"F1", "F2"}
    stop_reasons = [value for value in (prior.get("stop_reason"), stop_reason) if value]
    report = {
        "schema": "l2.c1.f1_f2_canary.v1",
        "stage": "C1",
        "created_at_utc": utc_now(),
        "baseline_commit": state["baseline_commit"],
        "status": "complete" if all_pass else "complete_with_findings",
        "decision": "canary_integrity_passed; family qualification not yet claimed" if all_pass else "bounded_canary_finding; no family qualification",
        "stop_reason": "; ".join(stop_reasons) if stop_reasons else None,
        "canary_contract": {
            "reference_resolution_m": NOMINAL_DP,
            "attempt_unit": "one solver attempt per family, qualification ledger category",
            "common_error_policy": "stop after the first common input/semantics failure; preserve attempt",
            "legacy_data_policy": "W06 and low-cost F1 assets are read-only templates; their historical status is unchanged",
        },
        "prepared_cases": all_prepared,
        "attempts": all_attempts,
        "audits": all_audits,
        "acceptance": {
            "f1_canary_pass": any(item["family"] == "F1" and item["canary_hard_integrity_pass"] for item in all_audits),
            "f2_canary_pass": any(item["family"] == "F2" and item["canary_hard_integrity_pass"] for item in all_audits),
            "nominal_spacing_used": all(item["resolution_m"] == NOMINAL_DP for item in all_prepared),
            "source_material_axes_separate": all(item.get("T2_macro") == "not_assessed" and item.get("T2_path") == "not_assessed" for item in all_audits),
            "no_family_qualification_claim": True,
        },
        "resource_observation": {
            "wall_seconds_controller": time.perf_counter() - started_wall,
            "solver_wall_seconds_sum": run_wall,
            "child_cpu_seconds": max(0.0, child_after - child_before),
            "gpu_hours": run_wall / 3600.0,
            "cpu_core_hours_actual": max(0.0, child_after - child_before) / 3600.0,
            "cpu_core_hours_conservative": run_wall / 3600.0,
            "qualification_solver_attempts": len(attempts),
            "new_storage_bytes": max(0, used_bytes - before_bytes),
        },
        "execution_environment": {
            "solver": repo_relative(SOLVER),
            "solver_sha256": sha256(SOLVER),
            "gencase": repo_relative(GENCASE),
            "gencase_sha256": sha256(GENCASE),
            "partvtk": repo_relative(PARTVTK),
            "partvtk_sha256": sha256(PARTVTK),
            "allowlist_source": repo_relative(INVENTORY),
            "gpu_indices": selected_gpus,
        },
    }
    if prior:
        previous_resource = prior.get("resource_observation", {})
        cumulative = {}
        for key in ("gpu_hours", "cpu_core_hours_actual", "cpu_core_hours_conservative", "qualification_solver_attempts", "new_storage_bytes"):
            cumulative[key] = previous_resource.get(key, 0) + report["resource_observation"].get(key, 0)
        report["resource_observation"]["cumulative"] = cumulative
        report["execution_environment"]["previous_report"] = str(REPORT_PATH)
    atomic_json(REPORT_PATH, report)
    # Include the report itself in the new-storage accounting.
    report["resource_observation"]["new_storage_bytes"] += REPORT_PATH.stat().st_size
    atomic_json(REPORT_PATH, report)
    update_usage(
        gpu_hours=report["resource_observation"]["gpu_hours"],
        cpu_core_hours_actual=report["resource_observation"]["cpu_core_hours_actual"],
        cpu_core_hours_conservative=report["resource_observation"]["cpu_core_hours_conservative"],
        qualification_solver_attempts=report["resource_observation"]["qualification_solver_attempts"],
        new_storage_bytes=report["resource_observation"]["new_storage_bytes"],
    )
    update_stage("C1", "complete", facts={
        "report": "reports/c1-canary.json",
        "decision": report["decision"],
        "attempt_count": len(attempts),
        "canary_pass_count": sum(item["canary_hard_integrity_pass"] for item in audits),
    })
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpus", default="4,5", help="allowlisted physical GPU indices, in selected-family order")
    parser.add_argument("--families", default="F1,F2", help="comma-separated selected families")
    parser.add_argument("--append", action="store_true", help="append an independent family canary to the existing C1 report")
    args = parser.parse_args()
    gpus = [int(value.strip()) for value in args.gpus.split(",") if value.strip()]
    families = {value.strip() for value in args.families.split(",") if value.strip()}
    report = run_all(gpus, families, append=args.append)
    print(json.dumps({
        "status": report["status"],
        "decision": report["decision"],
        "attempts": len(report["attempts"]),
        "audits": [(item["case_id"], item["canary_hard_integrity_pass"]) for item in report["audits"]],
        "report": str(REPORT_PATH),
    }, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
