#!/usr/bin/env python3
"""Execute and audit the reviewer-approved F1 nine-cell solver gate.

The R4 preflight already created the nine GenCase products.  This module is
the missing dynamics layer: it launches the actual solver into immutable
attempt directories, converts BI4 output through PartVTK/HDF5, performs a
bounded-memory trajectory audit, and makes a per-background T1 diagnostic
decision.  It never makes a production or external-reference claim.

The first run is intentionally the plain-dam-break medium cell.  That cell
is a chain smoke test; its physical result is not used as a prerequisite for
the other eight independent cells.  GPU 0--3 are never eligible here.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable

import h5py
import numpy as np

try:
    from scripts.campaign_runner import execute_attempt, require_idle_allowed_gpu, query_gpus
    from scripts.protocol_metrics import mass_fraction_tv
    from scripts.r4_f1_core_preflight import (
        ARTIFACT_ROOT as PREFLIGHT_ARTIFACT_ROOT,
        CASE_ROOT as PREFLIGHT_CASE_ROOT,
        PROTOCOL as PREFLIGHT_PROTOCOL,
        case_records as preflight_case_records,
    )
    from scripts.trajectory_io import convert_streaming
    from scripts.w02_semantics import partvtk_csv
except ModuleNotFoundError:
    from campaign_runner import execute_attempt, require_idle_allowed_gpu, query_gpus
    from protocol_metrics import mass_fraction_tv
    from r4_f1_core_preflight import (
        ARTIFACT_ROOT as PREFLIGHT_ARTIFACT_ROOT,
        CASE_ROOT as PREFLIGHT_CASE_ROOT,
        PROTOCOL as PREFLIGHT_PROTOCOL,
        case_records as preflight_case_records,
    )
    from trajectory_io import convert_streaming
    from w02_semantics import partvtk_csv


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "v0.1-candidate"
BIN = LAB / "vendor" / "official" / "DualSPHysics_v5.4" / "bin" / "linux"
SOLVER = BIN / "DualSPHysics5.4_linux64"
RUN_ROOT = CAMPAIGN / "runs" / "r5-f1-solver-gate"
DATA_ROOT = CAMPAIGN / "data" / "r5-f1-solver-gate"
CSV_ROOT = CAMPAIGN / "artifacts" / "r5-f1-solver-gate" / "csv"
REPORT = CAMPAIGN / "r5-f1-solver-gate.json"
GPU_IDS = (4, 5, 6, 7)
SMOKE_CASE_ID = "R4_F1_plain_dam_break_medium"
SCHEMA_VERSION = "r5-f1-solver-gate-v1"

PROTOCOL = {
    "time_max_s": float(PREFLIGHT_PROTOCOL["time_max_s"]),
    "time_out_s": float(PREFLIGHT_PROTOCOL["time_out_s"]),
    "step_algorithm": int(PREFLIGHT_PROTOCOL["step_algorithm"]),
    "integrator": str(PREFLIGHT_PROTOCOL["integrator"]),
    "verlet_steps": int(PREFLIGHT_PROTOCOL["verlet_steps"]),
    "boundary_formulation": str(PREFLIGHT_PROTOCOL["boundary_formulation"]),
    "boundary_parameter": int(PREFLIGHT_PROTOCOL["boundary_parameter"]),
    "save_pos_double": int(PREFLIGHT_PROTOCOL["save_pos_double"]),
    "shifting": int(PREFLIGHT_PROTOCOL["shifting"]),
    "output_cadence_s": float(PREFLIGHT_PROTOCOL["time_out_s"]),
}

# This is a physical-wall specification for the three closed F1 backgrounds,
# not the solver's broad simulation-domain AABB.  The open top is deliberate.
# The obstacle boxes are reconstructed from the case definitions and are used
# only for a penetration diagnostic; they are not an external validation.
WALL_SPECS: dict[str, dict[str, Any]] = {
    "plain_dam_break": {
        "container_interior": {"xmin": 0.0, "xmax": 1.2, "ymin": 0.0, "ymax": 0.4, "zmin": 0.0},
        "obstacles": [],
        "open_faces": ["top"],
    },
    "center_obstacle": {
        "container_interior": {"xmin": 0.0, "xmax": 1.2, "ymin": 0.0, "ymax": 0.4, "zmin": 0.0},
        "obstacles": [{"id": "center_obstacle", "xmin": 0.68, "xmax": 0.80, "ymin": 0.15, "ymax": 0.25, "zmin": 0.0, "zmax": 0.34}],
        "open_faces": ["top"],
    },
    "twin_obstacle_split_remerge": {
        "container_interior": {"xmin": 0.0, "xmax": 1.2, "ymin": 0.0, "ymax": 0.4, "zmin": 0.0},
        "obstacles": [
            {"id": "twin_obstacle_lower", "xmin": 0.62, "xmax": 0.72, "ymin": 0.06, "ymax": 0.16, "zmin": 0.0, "zmax": 0.30},
            {"id": "twin_obstacle_upper", "xmin": 0.78, "xmax": 0.88, "ymin": 0.24, "ymax": 0.34, "zmin": 0.0, "zmax": 0.30},
        ],
        "open_faces": ["top"],
    },
}


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    os.replace(temporary, path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fingerprint(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"path": str(path.relative_to(LAB)) if path.is_relative_to(LAB) else str(path), "exists": path.is_file()}
    if path.is_file():
        result.update({"bytes": path.stat().st_size, "sha256": sha256(path)})
    else:
        result.update({"bytes": None, "sha256": None})
    return result


def environment() -> dict[str, str]:
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = f"{BIN}:{env.get('LD_LIBRARY_PATH', '')}"
    env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    return env


def allowed_uuids() -> list[str]:
    inventory = json.loads((CAMPAIGN / "w00-inventory.json").read_text())
    return list(inventory["execution_policy"]["allowed_gpu_uuids"])


def records() -> list[dict[str, Any]]:
    result = []
    for record in preflight_case_records():
        case_id = record["case_id"]
        candidate = PREFLIGHT_CASE_ROOT / f"{case_id}_Def.xml"
        generated = PREFLIGHT_ARTIFACT_ROOT / case_id / "generated" / case_id
        result.append({
            "id": case_id,
            "case_id": case_id,
            "family": "F1",
            "background_id": record["background_id"],
            "mechanism": record["mechanism"],
            "resolution": record["level"],
            "dp_m": float(record["dp_m"]),
            "source_definition": str(record["source_definition"]),
            "candidate_definition": str(candidate),
            "generated_prefix": str(generated),
            "protocol": PROTOCOL,
            "wall_spec": WALL_SPECS[record["background_id"]],
        })
    return result


def record_hash(record: dict[str, Any]) -> str:
    stable = {
        key: value for key, value in record.items()
        if key not in {"candidate_definition", "generated_prefix", "wall_spec"}
    }
    stable["candidate_definition_sha256"] = sha256(Path(record["candidate_definition"])) if Path(record["candidate_definition"]).is_file() else None
    stable["generated_xml_sha256"] = sha256(Path(record["generated_prefix"]).with_suffix(".xml")) if Path(record["generated_prefix"]).with_suffix(".xml").is_file() else None
    stable["wall_spec"] = record["wall_spec"]
    return hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def input_fingerprint(record: dict[str, Any]) -> dict[str, Any]:
    generated = Path(record["generated_prefix"])
    paths = [Path(record["source_definition"]), Path(record["candidate_definition"])]
    paths.extend(generated.with_suffix(suffix) for suffix in (".xml", ".bi4", ".out"))
    return {
        "record_hash": record_hash(record),
        "files": [fingerprint(path) for path in paths],
    }


def verify_inputs(record: dict[str, Any]) -> list[str]:
    required = [Path(record["candidate_definition"]), Path(record["generated_prefix"]).with_suffix(".xml"), Path(record["generated_prefix"]).with_suffix(".bi4")]
    return [str(path) for path in required if not path.is_file()]


def latest_attempt(record: dict[str, Any]) -> Path | None:
    path = RUN_ROOT / record["id"] / "latest.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text())
        attempt = Path(payload["attempt_directory"])
        return attempt if attempt.is_dir() else None
    except (KeyError, json.JSONDecodeError):
        return None


def completed_attempt_count(case_id: str) -> int:
    """Count completed solver attempts without confusing reuse with execution."""
    attempts = RUN_ROOT / case_id / "attempts"
    if not attempts.is_dir():
        return 0
    return sum(path.is_dir() for path in attempts.glob("*.complete"))


def run_one(record: dict[str, Any], gpu_index: int, *, rerun: bool = False) -> dict[str, Any]:
    missing_inputs = verify_inputs(record)
    base = {
        "case_id": record["id"],
        "background_id": record["background_id"],
        "resolution": record["resolution"],
        "gpu_index_requested": gpu_index,
        "input_fingerprint": input_fingerprint(record),
    }
    if missing_inputs:
        return {**base, "execution_status": "blocked_missing_input", "acceptance_status": "pending", "missing_inputs": missing_inputs}
    previous_path = RUN_ROOT / record["id"] / "latest.json"
    if previous_path.is_file() and not rerun:
        try:
            previous = json.loads(previous_path.read_text())
            if previous.get("execution_status") == "completed" and previous.get("input_fingerprint", {}).get("record_hash") == base["input_fingerprint"]["record_hash"]:
                return {**previous, "execution_status": "reused_completed", "reuse_reason": "same input record hash; pass --rerun to make a new attempt"}
        except json.JSONDecodeError:
            pass
    try:
        gpu_record = require_idle_allowed_gpu(gpu_index, allowed_uuids())
        prefix = Path(record["generated_prefix"])
        result = execute_attempt(
            record["id"],
            [str(SOLVER), f"-gpu:{gpu_index}", str(prefix), "{output}"],
            RUN_ROOT,
            cwd=LAB,
            env=environment(),
            evidence_glob="data/Part_*.bi4",
            required_text="Finished execution (code=0)",
        )
        payload = {
            **base,
            **result,
            "execution_status": "completed" if result.get("status") == "completed" else "solver_failed",
            "acceptance_status": "pending_solver_audit",
            "gpu_at_launch": gpu_record,
            "solver": str(SOLVER.relative_to(LAB)),
            "environment": {"CUDA_DEVICE_ORDER": "PCI_BUS_ID", "CUDA_VISIBLE_DEVICES": str(gpu_index)},
            "protected_gpu_indices": [0, 1, 2, 3],
        }
        # execute_attempt writes latest.json before this extra metadata exists.
        atomic_json(RUN_ROOT / record["id"] / "latest.json", payload)
        return payload
    except Exception as error:  # Keep independent cells running and preserve the blocker.
        return {**base, "execution_status": "blocked_or_failed", "acceptance_status": "pending", "error": repr(error), "gpu_index_requested": gpu_index}


def load_report() -> dict[str, Any]:
    if REPORT.is_file():
        try:
            return json.loads(REPORT.read_text())
        except json.JSONDecodeError:
            pass
    return {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": "R5_F1_SOLVER_GATE",
        "scope": "F1 three backgrounds by three resolutions; actual solver gate",
        "execution_status": "not_started",
        "acceptance_status": "pending_solver_and_reference_gate",
        "validation_scope": [],
        "protocol": PROTOCOL,
        "resource_plan": {
            "allowed_gpu_indices": list(GPU_IDS),
            "protected_gpu_indices": [0, 1, 2, 3],
            "max_concurrent_heavy_jobs": 4,
            "initial_budget_gpu_hours": 8.0,
            "hard_upper_budget_gpu_hours": 24.0,
        },
        "cases": [],
        "open_blockers": [],
    }


def merge_cases(report: dict[str, Any], updates: Iterable[dict[str, Any]]) -> None:
    by_id = {item["case_id"]: item for item in report.get("cases", []) if "case_id" in item}
    by_id.update({item["case_id"]: item for item in updates})
    report["cases"] = [by_id[item["id"]] for item in records() if item["id"] in by_id]


def run_stage(selected: list[dict[str, Any]], gpu_indices: list[int], *, rerun: bool = False) -> dict[str, Any]:
    report = load_report()
    report["execution_status"] = "running"
    report["validation_scope"] = ["actual DualSPHysics solver", "raw BI4 output", "GPU UUID and attempt provenance"]
    atomic_json(REPORT, report)

    known = {item["id"]: item for item in selected}
    smoke = known.get(SMOKE_CASE_ID)
    ordered = ([smoke] if smoke is not None else []) + [item for item in selected if item["id"] != SMOKE_CASE_ID]
    results: list[dict[str, Any]] = []
    if ordered:
        first = run_one(ordered[0], gpu_indices[0], rerun=rerun)
        results.append(first)
        report["last_completed_stage"] = "smoke_cell" if first["case_id"] == SMOKE_CASE_ID else "solver_first_cell"
        merge_cases(report, results)
        atomic_json(REPORT, report)
        print(json.dumps({"stage": report["last_completed_stage"], "case_id": first["case_id"], "execution_status": first["execution_status"]}, ensure_ascii=False), flush=True)
    remaining = ordered[1:]
    for start in range(0, len(remaining), len(gpu_indices)):
        batch = remaining[start:start + len(gpu_indices)]
        assignments = [(item, gpu_indices[index]) for index, item in enumerate(batch)]
        with ThreadPoolExecutor(max_workers=len(assignments)) as pool:
            futures = [pool.submit(run_one, item, gpu, rerun=rerun) for item, gpu in assignments]
            batch_results = [future.result() for future in futures]
        results.extend(batch_results)
        merge_cases(report, batch_results)
        report["last_completed_stage"] = f"solver_batch_{start // len(gpu_indices) + 1}"
        atomic_json(REPORT, report)
        print(json.dumps({"stage": report["last_completed_stage"], "cases": [{"case_id": item["case_id"], "execution_status": item["execution_status"]} for item in batch_results]}, ensure_ascii=False), flush=True)
    selected_ids = {item["id"] for item in selected}
    tracked = [item for item in report["cases"] if item.get("case_id") in selected_ids]
    complete = sum(item.get("execution_status") in {"completed", "reused_completed"} for item in tracked)
    report["execution_status"] = "completed" if complete == len(selected_ids) else "partial_with_findings"
    all_ids = {item["id"] for item in records()}
    report["actual_solver_runs"] = sum(completed_attempt_count(case_id) for case_id in all_ids)
    report["reused_solver_runs"] = sum(item.get("execution_status") == "reused_completed" for item in results)
    report["solver_runs_this_invocation"] = sum(item.get("execution_status") == "completed" for item in results)
    all_case_by_id = {item.get("case_id"): item for item in report["cases"]}
    successful_cases = sum(all_case_by_id.get(case_id, {}).get("status") == "completed" for case_id in all_ids)
    report["missing_or_failed_solver_runs"] = max(0, len(all_ids) - successful_cases)
    report["resource_snapshot_after_run"] = query_gpus()
    atomic_json(REPORT, report)
    return report


def normalize_stage(selected: list[dict[str, Any]]) -> dict[str, Any]:
    report = load_report()
    updates = []
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    CSV_ROOT.mkdir(parents=True, exist_ok=True)
    for record in selected:
        existing = next((item for item in report.get("cases", []) if item.get("case_id") == record["id"]), {})
        attempt = latest_attempt(record)
        update = {**existing, "case_id": record["id"], "normalization_status": "unknown", "acceptance_status": "pending_normalization"}
        csv_dir = attempt / "csv" if attempt is not None else None
        if attempt is None or existing.get("execution_status") not in {"completed", "reused_completed"}:
            update["normalization_status"] = "unknown_missing_solver_attempt"
            updates.append(update)
            continue
        output = DATA_ROOT / f"{record['id']}.h5"
        try:
            complete = False
            if output.is_file():
                with h5py.File(output, "r") as h5:
                    complete = bool(h5.attrs.get("conversion_complete", True))
            if not complete:
                csv_paths = partvtk_csv(attempt / "data", csv_dir, "-all,+fluid")
                convert_streaming(
                    {"id": record["id"], "family": "F1", "mechanism": record["mechanism"], "shifting": 0},
                    csv_paths,
                    output,
                )
            with h5py.File(output, "r+") as h5:
                h5.attrs["r5_record_hash"] = record_hash(record)
                h5.attrs["candidate_definition_sha256"] = sha256(Path(record["candidate_definition"]))
                h5.attrs["generated_input_sha256"] = sha256(Path(record["generated_prefix"]).with_suffix(".xml"))
                h5.attrs["source_definition_sha256"] = sha256(Path(record["source_definition"]))
                h5.attrs["acceptance_status"] = "pending_solver_audit"
            update.update({
                "normalization_status": "completed",
                "hdf5": fingerprint(output),
                "csv_directory": str(csv_dir.relative_to(LAB)),
                "acceptance_status": "pending_trajectory_audit",
            })
        except Exception as error:
            update.update({"normalization_status": "failed", "error": repr(error), "acceptance_status": "blocked_normalization"})
        updates.append(update)
        print(json.dumps({"stage": "normalize", "case_id": record["id"], "normalization_status": update["normalization_status"]}, ensure_ascii=False), flush=True)
    merge_cases(report, updates)
    report["normalization_status"] = "completed" if all(item.get("normalization_status") == "completed" for item in report["cases"] if item["case_id"] in {r["id"] for r in selected}) else "partial_with_findings"
    atomic_json(REPORT, report)
    return report


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _run_excluded_particles(attempt: Path | None) -> int | None:
    if attempt is None:
        return None
    texts = []
    for path in [attempt / "process.stdout.log", *attempt.glob("*.out")]:
        if path.is_file():
            texts.append(path.read_text(errors="replace"))
    match = re.search(r"Excluded particles\.+:\s*([0-9,]+)", "\n".join(texts), re.IGNORECASE)
    return int(match.group(1).replace(",", "")) if match else None


def _box_penetration(points: np.ndarray, box: dict[str, float]) -> tuple[np.ndarray, np.ndarray]:
    inside = (
        (points[:, 0] > box["xmin"]) & (points[:, 0] < box["xmax"]) &
        (points[:, 1] > box["ymin"]) & (points[:, 1] < box["ymax"]) &
        (points[:, 2] > box["zmin"]) & (points[:, 2] < box["zmax"])
    )
    if not inside.any():
        return inside, np.zeros(len(points), dtype=np.float64)
    selected = points[inside]
    penetration = np.minimum.reduce([
        selected[:, 0] - box["xmin"], box["xmax"] - selected[:, 0],
        selected[:, 1] - box["ymin"], box["ymax"] - selected[:, 1],
        selected[:, 2] - box["zmin"], box["zmax"] - selected[:, 2],
    ])
    values = np.zeros(len(points), dtype=np.float64)
    values[inside] = penetration
    return inside, values


def _wall_penetration(points: np.ndarray, mass: np.ndarray, spec: dict[str, Any], tolerance: float) -> dict[str, Any]:
    bounds = spec["container_interior"]
    outside = (
        (points[:, 0] < bounds["xmin"] - tolerance) | (points[:, 0] > bounds["xmax"] + tolerance) |
        (points[:, 1] < bounds["ymin"] - tolerance) | (points[:, 1] > bounds["ymax"] + tolerance) |
        (points[:, 2] < bounds["zmin"] - tolerance)
    )
    obstacle_counts = {}
    obstacle_mass = {}
    max_depth = 0.0
    inside_any = np.zeros(len(points), dtype=bool)
    for obstacle in spec["obstacles"]:
        inside, penetration = _box_penetration(points, obstacle)
        inside_any |= inside
        obstacle_counts[obstacle["id"]] = int(inside.sum())
        obstacle_mass[obstacle["id"]] = float(mass[inside].sum(dtype=np.float64))
        if len(penetration):
            max_depth = max(max_depth, float(penetration.max(initial=0.0)))
    return {
        "outside_closed_container_count": int(outside.sum()),
        "outside_closed_container_mass_kg": float(mass[outside].sum(dtype=np.float64)),
        "obstacle_penetration_count": int(inside_any.sum()),
        "obstacle_penetration_mass_kg": float(mass[inside_any].sum(dtype=np.float64)),
        "obstacle_penetration_max_depth_m": max_depth,
        "obstacle_counts_by_id": obstacle_counts,
        "obstacle_mass_by_id_kg": obstacle_mass,
        "open_faces": list(spec["open_faces"]),
    }


def _distribution(points: np.ndarray, mass: np.ndarray, background_id: str, total_initial_mass: float) -> dict[str, float]:
    x, y = points[:, 0], points[:, 1]
    if background_id == "plain_dam_break":
        masks = {
            "upstream_x_lt_0p58": x < 0.58,
            "downstream_low_y_lt_0p2": (x >= 0.58) & (y < 0.2),
            "downstream_high_y_ge_0p2": (x >= 0.58) & (y >= 0.2),
        }
    else:
        masks = {
            "upstream_x_lt_0p58": x < 0.58,
            "downstream_low_y_lt_0p2": (x >= 0.90) & (y < 0.2),
            "downstream_high_y_ge_0p2": (x >= 0.90) & (y >= 0.2),
        }
    assigned = np.zeros(len(points), dtype=bool)
    result = {}
    for name, mask in masks.items():
        result[name] = float(mass[mask].sum(dtype=np.float64) / max(total_initial_mass, 1e-30))
        assigned |= mask
    result["intermediate_or_corridor"] = float(mass[~assigned].sum(dtype=np.float64) / max(total_initial_mass, 1e-30))
    return result


def audit_hdf5(record: dict[str, Any], h5_path: Path, attempt: Path | None) -> dict[str, Any]:
    issues: list[str] = []
    unknowns: list[str] = []
    with h5py.File(h5_path, "r") as h5:
        required = {"time", "particle_id", "particle_zone", "valid", "position", "velocity", "density", "mass", "pressure", "type", "mk"}
        missing = sorted(required - set(h5.keys()))
        if missing:
            return {"case_id": record["id"], "audit_status": "unknown", "unknowns": [f"missing datasets: {missing}"]}
        time = np.asarray(h5["time"][:], dtype=np.float64)
        ids = np.asarray(h5["particle_id"][:], dtype=np.int64)
        zones = np.asarray(h5["particle_zone"][:], dtype=np.int16)
        valid_shape = h5["valid"].shape
        if len(time) < 2 or not np.all(np.diff(time) > 0):
            issues.append("time_not_strictly_increasing_or_too_short")
        if valid_shape != (len(time), len(ids)):
            issues.append("valid_shape_mismatch")
        if len(np.unique(np.column_stack((zones, ids)), axis=0)) != len(ids):
            issues.append("identity_key_duplicate")

        initial_valid = np.asarray(h5["valid"][0], dtype=bool)
        final_valid = np.asarray(h5["valid"][-1], dtype=bool)
        initial_positions = np.asarray(h5["position"][0], dtype=np.float64)
        initial_mass_values = np.asarray(h5["mass"][0], dtype=np.float64)
        initial_fluid_mass = float(initial_mass_values[initial_valid].sum(dtype=np.float64))
        ever_seen = np.zeros(len(ids), dtype=bool)
        missing_since_seen = np.zeros(len(ids), dtype=bool)
        reappeared = np.zeros(len(ids), dtype=bool)
        introduced_after_initial = np.zeros(len(ids), dtype=bool)
        finite_bad_rows = 0
        finite_bad_first_frame: int | None = None
        density_min = math.inf
        density_max = -math.inf
        mass_series: list[float] = []
        distributions: dict[str, dict[str, float]] = {}
        penetration_frames = []
        center_series = []
        max_speed = 0.0

        for frame_index, time_value in enumerate(time):
            current_valid = np.asarray(h5["valid"][frame_index], dtype=bool)
            positions = np.asarray(h5["position"][frame_index], dtype=np.float64)
            velocities = np.asarray(h5["velocity"][frame_index], dtype=np.float64)
            density = np.asarray(h5["density"][frame_index], dtype=np.float64)
            masses = np.asarray(h5["mass"][frame_index], dtype=np.float64)
            pressure = np.asarray(h5["pressure"][frame_index], dtype=np.float64)
            current_rows = np.flatnonzero(current_valid)
            finite = np.isfinite(positions[current_rows]).all(axis=1)
            finite &= np.isfinite(velocities[current_rows]).all(axis=1)
            finite &= np.isfinite(density[current_rows]) & np.isfinite(masses[current_rows]) & np.isfinite(pressure[current_rows])
            bad_count = int((~finite).sum())
            if bad_count:
                finite_bad_rows += bad_count
                finite_bad_first_frame = frame_index if finite_bad_first_frame is None else finite_bad_first_frame
            if current_rows.size:
                density_min = min(density_min, float(np.nanmin(density[current_rows])))
                density_max = max(density_max, float(np.nanmax(density[current_rows])))
                speed = np.linalg.norm(velocities[current_rows], axis=1)
                max_speed = max(max_speed, float(np.nanmax(speed)))
                frame_mass = float(np.nansum(masses[current_rows], dtype=np.float64))
                mass_series.append(frame_mass)
                distributions[f"{float(time_value):.6f}"] = _distribution(positions[current_rows], masses[current_rows], record["background_id"], initial_fluid_mass)
                center_series.append({
                    "time_s": float(time_value),
                    "mass_kg": frame_mass,
                    "com_x_m": float(np.average(positions[current_rows, 0], weights=np.maximum(masses[current_rows], 1e-30))),
                    "com_y_m": float(np.average(positions[current_rows, 1], weights=np.maximum(masses[current_rows], 1e-30))),
                    "com_z_m": float(np.average(positions[current_rows, 2], weights=np.maximum(masses[current_rows], 1e-30))),
                })
                tolerance = 0.51 * record["dp_m"]
                penetration = _wall_penetration(positions[current_rows], masses[current_rows], record["wall_spec"], tolerance)
                if penetration["outside_closed_container_count"] or penetration["obstacle_penetration_count"]:
                    penetration_frames.append({"frame": frame_index, "time_s": float(time_value), **penetration})
            else:
                mass_series.append(0.0)

            reappeared |= current_valid & missing_since_seen
            introduced_after_initial |= current_valid & ~initial_valid
            missing_since_seen |= ever_seen & ~current_valid
            ever_seen |= current_valid

        if len(time) and np.any(initial_valid & ~final_valid):
            unknowns.append("initial_identities_missing_at_final_requires_solver_loss_or_exit_classification")
        excluded = _run_excluded_particles(attempt)
        if excluded is None:
            unknowns.append("excluded_particle_evidence_unknown")
        if finite_bad_rows:
            issues.append("nonfinite_values_for_valid_rows")
        if not math.isfinite(density_min) or not math.isfinite(density_max):
            unknowns.append("density_range_unknown")
        elif density_min < 650.0 or density_max > 1350.0:
            issues.append("density_outside_broad_sanity_range")

        common = initial_valid & final_valid
        final_positions = np.asarray(h5["position"][-1], dtype=np.float64)
        displacement = np.linalg.norm(final_positions[common] - initial_positions[common], axis=1) if common.any() else np.asarray([], dtype=np.float64)
        final_mass = float(np.asarray(h5["mass"][-1], dtype=np.float64)[final_valid].sum(dtype=np.float64))
        sampled_distribution = {}
        for requested in (0.5, 1.0, 1.5):
            index = int(np.argmin(np.abs(time - requested)))
            key = f"{float(time[index]):.6f}"
            if key in distributions:
                sampled_distribution[f"requested_{requested:.3f}s"] = {"actual_time_s": float(time[index]), **distributions[key]}
            else:
                unknowns.append(f"distribution_missing_near_{requested:.3f}s")
        penetration_summary = {
            "frames_with_penetration": len(penetration_frames),
            "first_penetration": penetration_frames[0] if penetration_frames else None,
            "max_obstacle_penetration_depth_m": max((item.get("obstacle_penetration_max_depth_m", 0.0) for item in penetration_frames), default=0.0),
            "max_outside_closed_container_mass_kg": max((item.get("outside_closed_container_mass_kg", 0.0) for item in penetration_frames), default=0.0),
            "max_obstacle_penetration_mass_kg": max((item.get("obstacle_penetration_mass_kg", 0.0) for item in penetration_frames), default=0.0),
        }
        final_mass_fraction = final_mass / max(initial_fluid_mass, 1e-30)
        quality_status = "pass_diagnostic" if not issues and not unknowns else ("quality_failed" if issues else "unknown")
        return {
            "case_id": record["id"],
            "background_id": record["background_id"],
            "resolution": record["resolution"],
            "dp_m": record["dp_m"],
            "audit_status": quality_status,
            "acceptance_status": "diagnostic_only_pending_reference_gate",
            "validation_scope": ["full saved time axis", "valid lifecycle", "finite state", "initial-mass denominator", "closed-wall/obstacle penetration diagnostic", "T1 mass distributions"],
            "frames": len(time),
            "time_start_s": float(time[0]) if len(time) else None,
            "time_end_s": float(time[-1]) if len(time) else None,
            "output_cadence_median_s": float(np.median(np.diff(time))) if len(time) > 1 else None,
            "particle_axis_count": len(ids),
            "initial_valid_particles": int(initial_valid.sum()),
            "final_valid_particles": int(final_valid.sum()),
            "identity_retention_first_to_last": float(common.sum() / max(1, initial_valid.sum())),
            "identities_introduced_after_initial": int(introduced_after_initial.sum()),
            "initial_identities_missing_at_final": int((initial_valid & ~final_valid).sum()),
            "identities_reappeared_after_gap": int(reappeared.sum()),
            "initial_fluid_mass_kg": initial_fluid_mass,
            "final_valid_mass_kg": final_mass,
            "final_valid_mass_fraction_of_initial": final_mass_fraction,
            "minimum_frame_mass_kg": float(min(mass_series)) if mass_series else None,
            "maximum_frame_mass_kg": float(max(mass_series)) if mass_series else None,
            "excluded_particles_from_solver_log": excluded,
            "finite_bad_value_rows": finite_bad_rows,
            "finite_bad_first_frame": finite_bad_first_frame,
            "density_min_kg_m3": density_min if math.isfinite(density_min) else None,
            "density_max_kg_m3": density_max if math.isfinite(density_max) else None,
            "max_speed_m_s": max_speed,
            "mean_displacement_m": float(displacement.mean()) if len(displacement) else None,
            "max_displacement_m": float(displacement.max()) if len(displacement) else None,
            "mass_distribution_samples": sampled_distribution,
            "mass_distribution_series": distributions,
            "center_of_mass_series": center_series,
            "penetration": penetration_summary,
            "issues": issues,
            "unknowns": unknowns,
            "wall_spec": record["wall_spec"],
            "hdf5": str(h5_path.relative_to(LAB)) if h5_path.is_relative_to(LAB) else str(h5_path),
            "hdf5_sha256": sha256(h5_path),
        }


def audit_stage(selected: list[dict[str, Any]]) -> dict[str, Any]:
    report = load_report()
    updates = []
    for record in selected:
        existing = next((item for item in report.get("cases", []) if item.get("case_id") == record["id"]), {})
        h5_path = DATA_ROOT / f"{record['id']}.h5"
        attempt = latest_attempt(record)
        if not h5_path.is_file():
            update = {**existing, "case_id": record["id"], "audit_status": "unknown", "unknowns": ["normalized HDF5 missing"], "acceptance_status": "pending"}
        else:
            try:
                update = {**existing, **audit_hdf5(record, h5_path, attempt)}
            except Exception as error:
                update = {**existing, "case_id": record["id"], "audit_status": "unknown", "unknowns": [repr(error)], "acceptance_status": "blocked_audit"}
        updates.append(update)
        print(json.dumps({"stage": "audit", "case_id": record["id"], "audit_status": update.get("audit_status")}, ensure_ascii=False), flush=True)
    merge_cases(report, updates)
    report["audit_status"] = "completed" if all(item.get("audit_status") in {"pass_diagnostic", "quality_failed", "unknown"} for item in report["cases"] if item["case_id"] in {r["id"] for r in selected}) else "partial"
    atomic_json(REPORT, report)
    return report


def _distribution_at(audit: dict[str, Any], requested_time: float = 1.0) -> dict[str, float] | None:
    samples = audit.get("mass_distribution_samples", {})
    entry = samples.get(f"requested_{requested_time:.3f}s")
    if not entry:
        return None
    return {key: float(value) for key, value in entry.items() if key != "actual_time_s"}


def decide_stage(selected: list[dict[str, Any]]) -> dict[str, Any]:
    report = load_report()
    by_background: dict[str, list[dict[str, Any]]] = {}
    for item in report.get("cases", []):
        if item.get("case_id") in {r["id"] for r in selected}:
            by_background.setdefault(item.get("background_id", "unknown"), []).append(item)
    decisions = {}
    qualified = []
    blockers = []
    for background, items in sorted(by_background.items()):
        items = sorted(items, key=lambda item: {"coarse": 0, "medium": 1, "fine": 2}.get(item.get("resolution"), 99))
        statuses = {item.get("resolution"): item.get("audit_status") for item in items}
        distributions = {item.get("resolution"): _distribution_at(item) for item in items}
        comparisons = {}
        for left, right, label in (("coarse", "medium", "coarse_to_medium"), ("medium", "fine", "medium_to_fine")):
            if distributions.get(left) is None or distributions.get(right) is None:
                comparisons[label] = {"tv": None, "status": "unknown"}
            else:
                tv = mass_fraction_tv(distributions[left], distributions[right])
                comparisons[label] = {"tv": float(tv), "threshold": 0.05, "status": "pass" if tv <= 0.05 else "fail"}
        ready = len(items) == 3 and all(item.get("audit_status") == "pass_diagnostic" for item in items) and all(item["status"] == "pass" for item in comparisons.values())
        if ready:
            decision = "candidate_t1_only_pending_external_reference"
            qualified.append(background)
        else:
            decision = "blocked_or_rejected_candidate_t1"
            blockers.append({"background_id": background, "resolution_status": statuses, "comparisons": comparisons})
        decisions[background] = {
            "decision": decision,
            "resolution_status": statuses,
            "mass_distribution_comparisons": comparisons,
            "physical_acceptance": False,
            "external_reference_acceptance": False,
            "t2_material_acceptance": False,
        }
    all_cases = [item for group in by_background.values() for item in group]
    report["decision_status"] = "completed"
    report["acceptance_status"] = "candidate_t1_only_for_qualified_backgrounds" if qualified else "no_background_t1_qualified"
    report["family_decisions"] = decisions
    report["qualified_t1_backgrounds"] = qualified
    report["development_tranche_authorized"] = False
    # ``run`` deliberately changes a reused record's status to
    # ``reused_completed``.  Count the durable attempt directories here so a
    # later audit/decision pass cannot report zero actual solver executions.
    report["actual_solver_runs"] = sum(
        completed_attempt_count(record["id"]) for record in records()
        if record["id"] in {item.get("case_id") for item in all_cases}
    )
    report["completed_hdf5_and_frame_audit"] = sum(item.get("audit_status") in {"pass_diagnostic", "quality_failed", "unknown"} for item in all_cases)
    report["open_blockers"] = [
        "T1 decision is diagnostic and not an external/reference physical acceptance",
        "T2 material destination and tracer evaluator are not part of this solver gate",
        "F1 source-layer material task must consume a new single-obstacle medium/fine artifact",
        "no development tranche is authorized by this decision",
    ] + blockers
    atomic_json(REPORT, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "normalize", "audit", "decide", "all"), nargs="?", default="all")
    parser.add_argument("--cases", nargs="*", help="exact case IDs; default is all nine")
    parser.add_argument("--gpus", default=",".join(str(item) for item in GPU_IDS), help="physical GPU IDs, default 4,5,6,7")
    parser.add_argument("--rerun", action="store_true", help="make a fresh attempt even if the same input hash already completed")
    args = parser.parse_args(argv)
    all_records = records()
    known = {record["id"]: record for record in all_records}
    selected_ids = args.cases or list(known)
    unknown = sorted(set(selected_ids) - set(known))
    if unknown:
        parser.error(f"unknown case IDs: {unknown}")
    selected = [known[item] for item in selected_ids]
    gpu_indices = [int(item) for item in args.gpus.split(",") if item.strip()]
    if not gpu_indices or any(item not in GPU_IDS for item in gpu_indices):
        parser.error(f"GPU IDs must be a nonempty subset of {GPU_IDS}")
    report = load_report()
    if args.action in {"run", "all"}:
        report = run_stage(selected, gpu_indices, rerun=args.rerun)
    if args.action in {"normalize", "all"}:
        report = normalize_stage(selected)
    if args.action in {"audit", "all"}:
        report = audit_stage(selected)
    if args.action in {"decide", "all"}:
        report = decide_stage(selected)
    print(json.dumps({
        "execution_status": report.get("execution_status"),
        "acceptance_status": report.get("acceptance_status"),
        "actual_solver_runs": report.get("actual_solver_runs", 0),
        "completed_hdf5_and_frame_audit": report.get("completed_hdf5_and_frame_audit", 0),
        "qualified_t1_backgrounds": report.get("qualified_t1_backgrounds", []),
        "development_tranche_authorized": report.get("development_tranche_authorized", False),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
