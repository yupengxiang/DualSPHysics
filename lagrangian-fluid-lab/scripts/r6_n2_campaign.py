#!/usr/bin/env python3
"""R6 N2 bounded F1 plain-dam-break qualification campaign.

This is the executable follow-up to the R5 reviewer handoff.  It keeps the
old nine-cell evidence immutable, adds only the two registered height
endpoints (three resolutions each), and makes the T1 decision from the full
saved time axis rather than from the historical 1.0 s snapshot.

The campaign also materialises finite wall sidecars for the plain control and
can run the bounded plain-control material evaluator.  It never changes the
DualSPHysics vendor tree and never treats T1 as external physical truth.
"""

from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Iterable, Sequence
import xml.etree.ElementTree as ET

import h5py
import numpy as np

try:
    from scripts import r5_f1_solver_gate as r5_gate
    from scripts.boundary_sidecars import audit_sidecar, read_binary_vtk_polydata, write_sidecar
    from scripts.campaign_runner import execute_attempt, query_gpus, require_idle_allowed_gpu
    from scripts.r5_f1_material_task import run_bounded as run_material_bounded
    from scripts.trajectory_io import convert_streaming
    from scripts.w02_semantics import partvtk_csv
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import r5_f1_solver_gate as r5_gate
    from boundary_sidecars import audit_sidecar, read_binary_vtk_polydata, write_sidecar
    from campaign_runner import execute_attempt, query_gpus, require_idle_allowed_gpu
    from r5_f1_material_task import run_bounded as run_material_bounded
    from trajectory_io import convert_streaming
    from w02_semantics import partvtk_csv


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "v0.1-candidate"
BIN = LAB / "vendor" / "official" / "DualSPHysics_v5.4" / "bin" / "linux"
GENCASE = BIN / "GenCase_linux64"
SOLVER = BIN / "DualSPHysics5.4_linux64"
PARTVTKOUT = BIN / "PartVTKOut_linux64"
SOURCE_DEFINITION = LAB / "cases" / "F1" / "F1_dam_break_plain" / "F1_dam_break_plain_Def.xml"
CASE_ROOT = CAMPAIGN / "cases" / "r6-n2-height"
ARTIFACT_ROOT = CAMPAIGN / "artifacts" / "r6-n2-height"
RUN_ROOT = CAMPAIGN / "runs" / "r6-n2-height"
DATA_ROOT = CAMPAIGN / "data" / "r6-n2-height"
SIDECAR_ROOT = CAMPAIGN / "sidecars" / "r6-n2-height"
REPORT = CAMPAIGN / "r6-n2-n2-campaign.json"
HANDOFF = CAMPAIGN / "R6-N2-LATEST-HANDOFF.md"
MATERIAL_REPORT = CAMPAIGN / "r6-f1-material-task.json"

GPU_IDS = (4, 5, 6, 7)
PROTECTED_GPU_IDS = (0, 1, 2, 3)
TIME_MAX_S = 1.5
TIME_OUT_S = 0.001
DOMAIN_TOP_M = 0.6
HEIGHTS_M = {"h09": 0.414, "h10": 0.460, "h11": 0.506}
RESOLUTIONS_M = {"coarse": 0.035, "medium": 0.024, "fine": 0.014}
LEVEL_ORDER = {"coarse": 0, "medium": 1, "fine": 2}
SOURCE_Z_BOUNDS_BY_HEIGHT = {
    label: (0.04, height + 0.04) for label, height in HEIGHTS_M.items()
}
# The nominal h10 geometry is [0.04, 0.50] m, but the generated fluid
# centres occupy a resolution-dependent support envelope ([0.034, 0.510] m
# in the reused R5 products).  Material labels therefore use this one common
# declared envelope across resolutions rather than per-run extrema.
MATERIAL_SOURCE_Z_BOUNDS_M = (0.03, 0.52)
SCHEMA_VERSION = "r6-n2-f1-plain-v1"


def relpath(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(LAB.resolve()))
    except ValueError:
        return str(Path(path).resolve())


def lab_path(value: str | Path) -> Path:
    """Resolve a campaign-relative path without depending on the shell cwd."""
    path = Path(value)
    return path if path.is_absolute() else LAB / path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    os.replace(temporary, path)


def environment(*, cpu: bool = False) -> dict[str, str]:
    value = os.environ.copy()
    value["LD_LIBRARY_PATH"] = f"{BIN}:{value.get('LD_LIBRARY_PATH', '')}"
    value["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    if cpu:
        value["CUDA_VISIBLE_DEVICES"] = ""
        value["NVIDIA_VISIBLE_DEVICES"] = "void"
    return value


def allowed_uuids() -> list[str]:
    inventory = json.loads((CAMPAIGN / "w00-inventory.json").read_text())
    return list(inventory["execution_policy"]["allowed_gpu_uuids"])


def _set_parameter(root: ET.Element, key: str, value: Any) -> None:
    parent = root.find(".//execution/parameters")
    if parent is None:
        raise ValueError("source definition has no execution/parameters")
    node = parent.find(f"./parameter[@key='{key}']")
    if node is None:
        node = ET.SubElement(parent, "parameter", key=key)
    node.set("value", str(value))


def _fluid_drawbox(root: ET.Element) -> ET.Element:
    commands = root.find(".//geometry/commands/mainlist")
    if commands is None:
        raise ValueError("source definition has no geometry mainlist")
    fluid_seen = False
    for node in commands:
        if node.tag == "setmkfluid":
            fluid_seen = True
        elif fluid_seen and node.tag == "drawbox":
            if (node.findtext("./boxfill") or "").strip() == "solid":
                return node
    raise ValueError("could not locate the initial fluid drawbox")


def records() -> list[dict[str, Any]]:
    result = []
    for height_label in ("h09", "h11"):
        for level, dp in RESOLUTIONS_M.items():
            case_id = f"R6_F1_plain_dam_break_{height_label}_{level}"
            result.append({
                "case_id": case_id,
                "family": "F1",
                "background_id": "plain_dam_break",
                "mechanism": "collapse-runup-return",
                "height_label": height_label,
                "height_m": HEIGHTS_M[height_label],
                "continuous_initial_fluid_z_bounds_m": list(SOURCE_Z_BOUNDS_BY_HEIGHT[height_label]),
                "resolution": level,
                "dp_m": dp,
                "time_max_s": TIME_MAX_S,
                "time_out_s": TIME_OUT_S,
                "source_definition": str(SOURCE_DEFINITION),
                "gpu": GPU_IDS[len(result) % len(GPU_IDS)],
                "wall_spec": r5_gate.WALL_SPECS["plain_dam_break"],
            })
    return result


def base_records() -> list[dict[str, Any]]:
    result = []
    for level, dp in RESOLUTIONS_M.items():
        case_id = f"R4_F1_plain_dam_break_{level}"
        result.append({
            "case_id": case_id,
            "family": "F1",
            "background_id": "plain_dam_break",
            "mechanism": "collapse-runup-return",
            "height_label": "h10",
            "height_m": HEIGHTS_M["h10"],
            "continuous_initial_fluid_z_bounds_m": list(SOURCE_Z_BOUNDS_BY_HEIGHT["h10"]),
            "resolution": level,
            "dp_m": dp,
            "time_max_s": TIME_MAX_S,
            "time_out_s": TIME_OUT_S,
            "source_definition": str(SOURCE_DEFINITION),
            "gpu": GPU_IDS[0],
            "wall_spec": r5_gate.WALL_SPECS["plain_dam_break"],
            "hdf5": str(r5_gate.DATA_ROOT / f"{case_id}.h5"),
            "attempt_root": str(r5_gate.RUN_ROOT / case_id),
            "generated_prefix": str(
                CAMPAIGN / "artifacts" / "r4-f1-core-preflight" / case_id / "generated" / case_id
            ),
        })
    return result


def record_hash(record: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def prepare_one(record: dict[str, Any]) -> dict[str, Any]:
    case_id = record["case_id"]
    case_dir = CASE_ROOT / case_id
    generated_dir = ARTIFACT_ROOT / case_id / "generated"
    case_dir.mkdir(parents=True, exist_ok=True)
    generated_dir.mkdir(parents=True, exist_ok=True)
    candidate = case_dir / f"{case_id}_Def.xml"
    tree = ET.parse(SOURCE_DEFINITION)
    root = tree.getroot()
    definition = root.find(".//geometry/definition")
    if definition is None:
        raise ValueError("plain source has no geometry definition")
    definition.set("dp", str(record["dp_m"]))
    fluid = _fluid_drawbox(root)
    fluid.find("./size").set("z", str(record["height_m"]))
    _set_parameter(root, "SavePosDouble", 2)
    _set_parameter(root, "StepAlgorithm", 1)
    _set_parameter(root, "VerletSteps", 40)
    _set_parameter(root, "Boundary", 1)
    _set_parameter(root, "Shifting", 0)
    _set_parameter(root, "TimeMax", TIME_MAX_S)
    _set_parameter(root, "TimeOut", TIME_OUT_S)
    ET.indent(tree, space="    ")
    tree.write(candidate, encoding="utf-8", xml_declaration=True)
    prefix = generated_dir / case_id
    command = [str(GENCASE), str(candidate.with_suffix("")), str(prefix), "-save:all"]
    process = subprocess.run(
        command, cwd=generated_dir, env=environment(cpu=True), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )
    (generated_dir / "gencase.stdout.log").write_text(process.stdout)
    if process.returncode != 0 or not prefix.with_suffix(".xml").is_file() or not prefix.with_suffix(".bi4").is_file():
        raise RuntimeError(f"GenCase failed for {case_id}: {process.stdout[-1500:]}")
    fluid_match = re.search(r"Fluid\.{3,}:\s*([0-9,]+)", process.stdout)
    return {
        **record,
        "candidate_definition": relpath(candidate),
        "candidate_definition_sha256": sha256(candidate),
        "generated_prefix": relpath(prefix),
        "generated_xml_sha256": sha256(prefix.with_suffix(".xml")),
        "gencase": {
            "returncode": process.returncode,
            "fluid_particles": int(fluid_match.group(1).replace(",", "")) if fluid_match else None,
            "stdout": relpath(generated_dir / "gencase.stdout.log"),
        },
    }


def prepare(selected: Sequence[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    selected = list(selected or records())
    prepared = [prepare_one(record) for record in selected]
    report = load_report()
    report["preparation_status"] = "completed"
    report["prepared_cases"] = prepared
    report["execution_status"] = "prepared_only"
    atomic_json(REPORT, report)
    return prepared


def _latest_attempt(record: dict[str, Any]) -> Path | None:
    latest = RUN_ROOT / record["case_id"] / "latest.json"
    if not latest.is_file():
        return None
    try:
        path = Path(json.loads(latest.read_text())["attempt_directory"])
    except (KeyError, json.JSONDecodeError):
        return None
    return path if path.is_dir() else None


def run_one(record: dict[str, Any], gpu: int, *, rerun: bool = False) -> dict[str, Any]:
    prefix = lab_path(record["generated_prefix"])
    latest = RUN_ROOT / record["case_id"] / "latest.json"
    if latest.is_file() and not rerun:
        payload = json.loads(latest.read_text())
        if payload.get("status") == "completed" and payload.get("record_hash") == record_hash(record):
            return {**payload, "execution_status": "reused_completed"}
    gpu_record = require_idle_allowed_gpu(gpu, allowed_uuids())
    result = execute_attempt(
        record["case_id"],
        [str(SOLVER), f"-gpu:{gpu}", str(prefix), "{output}"],
        RUN_ROOT,
        cwd=prefix.parent,
        env=environment(),
        evidence_glob="data/Part_*.bi4",
        required_text="Finished execution (code=0)",
    )
    payload = {
        **result,
        "record_hash": record_hash(record),
        "execution_status": "completed" if result.get("status") == "completed" else "solver_failed",
        "gpu_at_launch": gpu_record,
        "protected_gpu_indices": list(PROTECTED_GPU_IDS),
        "gpu_index_requested": gpu,
    }
    atomic_json(RUN_ROOT / record["case_id"] / "latest.json", payload)
    return payload


def run_solver(prepared: Sequence[dict[str, Any]], *, rerun: bool = False) -> list[dict[str, Any]]:
    prepared = list(prepared)
    if not prepared:
        raise ValueError("no prepared height cases")
    # The first medium case remains the bounded chain smoke; other cells are
    # independent and may use the four explicitly allowed GPUs concurrently.
    first = next((item for item in prepared if item["resolution"] == "medium"), prepared[0])
    results = [run_one(first, first["gpu"], rerun=rerun)]
    remaining = [item for item in prepared if item["case_id"] != first["case_id"]]
    for start in range(0, len(remaining), len(GPU_IDS)):
        batch = remaining[start:start + len(GPU_IDS)]
        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
            futures = [pool.submit(run_one, item, item["gpu"], rerun=rerun) for item in batch]
            results.extend(future.result() for future in futures)
    report = load_report()
    report["solver_runs"] = results
    report["execution_status"] = "completed" if all(
        item.get("execution_status") in {"completed", "reused_completed"} for item in results
    ) else "partial_with_findings"
    report["resource_snapshot_after_solver"] = query_gpus()
    atomic_json(REPORT, report)
    return results


def normalize_one(record: dict[str, Any]) -> dict[str, Any]:
    attempt = _latest_attempt(record)
    if attempt is None:
        return {"case_id": record["case_id"], "normalization_status": "blocked_missing_attempt"}
    output = DATA_ROOT / f"{record['case_id']}.h5"
    csv_dir = attempt / "csv"
    complete = False
    if output.is_file():
        with h5py.File(output, "r") as h5:
            complete = bool(h5.attrs.get("conversion_complete", True))
    try:
        if not complete:
            csv_paths = partvtk_csv(attempt / "data", csv_dir, "-all,+fluid")
            convert_streaming(
                {"id": record["case_id"], "family": "F1", "mechanism": record["mechanism"], "shifting": 0},
                csv_paths, output,
            )
        with h5py.File(output, "r+") as h5:
            h5.attrs["continuous_initial_fluid_z_bounds_m"] = np.asarray(
                record["continuous_initial_fluid_z_bounds_m"], dtype=np.float64
            )
            h5.attrs["r6_height_m"] = float(record["height_m"])
            h5.attrs["r6_record_hash"] = record_hash(record)
            h5.attrs["source_definition_sha256"] = sha256(SOURCE_DEFINITION)
        vtk = lab_path(record["generated_prefix"]).with_name(lab_path(record["generated_prefix"]).name + "_MkCells.vtk")
        parsed = read_binary_vtk_polydata(vtk)
        sidecar = SIDECAR_ROOT / f"{record['case_id']}.h5"
        sidecar_summary = write_sidecar(
            sidecar, record["case_id"], output, parsed,
            source_vtk_label=relpath(vtk), source_hdf5_label=relpath(output),
        )
        return {
            "case_id": record["case_id"],
            "normalization_status": "completed",
            "hdf5": relpath(output),
            "hdf5_sha256": sha256(output),
            "sidecar": relpath(sidecar),
            "sidecar_sha256": sha256(sidecar),
            "sidecar_audit": sidecar_summary,
        }
    except Exception as error:
        return {"case_id": record["case_id"], "normalization_status": "failed", "error": repr(error)}


def normalize(prepared: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    results = [normalize_one(record) for record in prepared]
    report = load_report()
    report["normalization"] = results
    report["normalization_status"] = "completed" if all(
        item.get("normalization_status") == "completed" for item in results
    ) else "partial_with_findings"
    atomic_json(REPORT, report)
    return results


def _weighted_quantile(values: np.ndarray, weights: np.ndarray, fraction: float) -> float | None:
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    finite = np.isfinite(values) & np.isfinite(weights) & (weights > 0.0)
    if not finite.any():
        return None
    order = np.argsort(values[finite])
    sorted_values = values[finite][order]
    sorted_weights = weights[finite][order]
    cumulative = np.cumsum(sorted_weights)
    target = float(fraction) * float(cumulative[-1])
    return float(sorted_values[min(int(np.searchsorted(cumulative, target, side="left")), len(sorted_values) - 1)])


def _frame_metrics(h5: h5py.File, frame: int, initial_mass: float) -> dict[str, Any]:
    valid = np.asarray(h5["valid"][frame], dtype=bool)
    position = np.asarray(h5["position"][frame], dtype=np.float64)
    velocity = np.asarray(h5["velocity"][frame], dtype=np.float64)
    mass = np.asarray(h5["mass"][frame], dtype=np.float64)
    rows = np.flatnonzero(valid)
    if not len(rows):
        return {"valid_particles": 0, "mass_kg": 0.0, "distribution": None}
    weights = mass[rows]
    points = position[rows]
    speeds2 = np.sum(velocity[rows] * velocity[rows], axis=1)
    background = "plain_dam_break"
    return {
        "valid_particles": int(len(rows)),
        "mass_kg": float(np.sum(weights, dtype=np.float64)),
        "mass_fraction": float(np.sum(weights, dtype=np.float64) / max(initial_mass, 1e-30)),
        "com_m": [
            float(np.average(points[:, axis], weights=np.maximum(weights, 1e-30)))
            for axis in range(3)
        ],
        "front_quantiles_m": {
            "q50": _weighted_quantile(points[:, 0], weights, 0.50),
            "q90": _weighted_quantile(points[:, 0], weights, 0.90),
            "q99": _weighted_quantile(points[:, 0], weights, 0.99),
        },
        "kinetic_energy_proxy_j": float(0.5 * np.sum(weights * speeds2, dtype=np.float64)),
        "max_speed_m_s": float(np.sqrt(np.max(speeds2))),
        "distribution": _closed_distribution(
            r5_gate._distribution(points, weights, background, initial_mass)
        ),
    }


def _closed_distribution(distribution: dict[str, float]) -> dict[str, float]:
    """Add the explicit mass-loss/unclassified bin required by TV metrics.

    The legacy R5 helper reports only the mass currently assigned to spatial
    regions, divided by initial mass.  That is useful as a physical mass
    series, but it is not a probability distribution after a particle exits
    the open top.  R6 keeps that distinction visible by adding the residual
    as a named category instead of silently renormalising it away.
    """
    result = {str(key): float(value) for key, value in distribution.items()}
    # Make this helper idempotent: fixed-time records already carry the
    # explicit residual bin, while pair-comparison fixtures may not.
    result.pop("unclassified_or_lost", None)
    assigned = float(sum(result.values()))
    if assigned > 1.0 + 1e-6:
        raise ValueError(f"mass distribution exceeds initial mass by {assigned - 1.0:.6g}")
    if assigned > 1.0:
        # The tiny excess seen in some discrete mass sums is roundoff, not a
        # physical source.  Close it without erasing a meaningful loss bin.
        result = {key: value / assigned for key, value in result.items()}
        assigned = 1.0
    result["unclassified_or_lost"] = max(0.0, 1.0 - assigned)
    return result


def _normalise_csv_row(row: dict[str, Any]) -> dict[str, Any]:
    return {str(key).strip().rstrip(","): value for key, value in row.items() if key is not None}


def _runparts_exclusion_reasons(attempt: Path | None) -> dict[int, list[str]]:
    """Map solver PART numbers to the native exclusion counters.

    ``PartOut`` stores per-particle records, while ``RunPARTs.csv`` stores the
    native reason counters.  Joining both keeps the identity-level evidence
    auditable without guessing from a last position alone.
    """
    if attempt is None:
        return {}
    path = attempt / "RunPARTs.csv"
    if not path.is_file():
        return {}
    lines = path.read_text(errors="replace").splitlines()
    header_index = next((index for index, line in enumerate(lines) if line.startswith("Part;")), None)
    if header_index is None:
        return {}
    reader = csv.DictReader(lines[header_index:], delimiter=";")
    result: dict[int, list[str]] = {}
    for raw in reader:
        row = _normalise_csv_row(raw)
        try:
            part = int(str(row.get("Part", "")).strip())
        except ValueError:
            continue
        reasons = []
        for column, reason in (("NpOutPos", "position"), ("NpOutRho", "density"), ("NpOutMov", "movement")):
            try:
                count = int(str(row.get(column, "0")).replace(",", "").strip())
            except ValueError:
                count = 0
            if count:
                reasons.append(reason)
        result[part] = reasons
    return result


def _partout_exclusion_evidence(attempt: Path | None) -> dict[str, Any]:
    """Decode native ``PartOut`` rows and join their native reason counters."""
    empty = {"status": "unavailable", "rows": [], "by_particle_id": {}, "reason_counts": {}}
    if attempt is None or not PARTVTKOUT.is_file():
        return empty
    data_dir = attempt / "data"
    if not data_dir.is_dir() or not any(data_dir.glob("PartOut_*.obi4")):
        return {**empty, "status": "no_partout_files"}
    part_reasons = _runparts_exclusion_reasons(attempt)
    with tempfile.TemporaryDirectory(prefix="r6-partout-") as temporary:
        output = Path(temporary) / "excluded.csv"
        resume = Path(temporary) / "resume.csv"
        process = subprocess.run(
            [str(PARTVTKOUT), "-dirdata", str(data_dir), "-savecsv", str(output),
             "-saveresume", str(resume), "-createdirs:1", "-csvsep:1"],
            cwd=attempt, env=environment(cpu=True), text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        if process.returncode != 0 or not output.is_file():
            return {**empty, "status": "partvtkout_failed", "returncode": process.returncode}
        with output.open(newline="", errors="replace") as stream:
            reader = csv.DictReader(stream, skipinitialspace=True)
            rows = []
            by_particle_id: dict[str, dict[str, Any]] = {}
            reason_counts: dict[str, int] = {}
            for raw in reader:
                row = _normalise_csv_row(raw)
                if not row.get("Idp"):
                    continue
                try:
                    particle_id = int(str(row["Idp"]).strip())
                    part = int(str(row.get("PartOut", "-1")).strip())
                except ValueError:
                    continue
                native_reasons = part_reasons.get(part, [])
                reason = native_reasons[0] if len(native_reasons) == 1 else (
                    "multiple" if native_reasons else "unknown"
                )
                evidence = {
                    "particle_id": particle_id,
                    "part_out": part,
                    "motive": int(str(row.get("Motive", "-1")).strip() or -1),
                    "position_m": [float(row.get(key, "nan")) for key in ("Pos.x [m]", "Pos.y [m]", "Pos.z [m]")],
                    "velocity_m_s": [float(row.get(key, "nan")) for key in ("Vel.x [m/s]", "Vel.y [m/s]", "Vel.z [m/s]")],
                    "density_kg_m3": float(row.get("Rhop [kg/m^3]", "nan")),
                    "native_reason": reason,
                    "native_reason_counters": native_reasons,
                }
                rows.append(evidence)
                by_particle_id[str(particle_id)] = evidence
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
    return {
        "status": "available",
        "rows": rows,
        "by_particle_id": by_particle_id,
        "reason_counts": reason_counts,
    }


def _classify_missing_identities(
    h5: h5py.File,
    record: dict[str, Any],
    exclusion_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify final identity disappearance without treating the open top as a wall.

    A missing final row is not, by itself, solver loss: particles may legally
    leave through the declared top opening.  The last valid state and the
    one-step forward position are used to distinguish that case from a row
    that disappears while still inside the closed part of the domain.
    """
    time = np.asarray(h5["time"][:], dtype=np.float64)
    initial_valid = np.asarray(h5["valid"][0], dtype=bool)
    final_valid = np.asarray(h5["valid"][-1], dtype=bool)
    positions = np.asarray(h5["position"][:], dtype=np.float64)
    velocities = np.asarray(h5["velocity"][:], dtype=np.float64)
    missing = initial_valid & ~final_valid
    particle_ids = np.asarray(
        h5["particle_id"][:] if "particle_id" in h5 else np.arange(len(initial_valid)),
        dtype=np.int64,
    )
    categories = {
        "legal_open_top_exit_candidate": 0,
        "top_crossing_without_registered_absorber": 0,
        "solver_density_exclusion": 0,
        "solver_position_exclusion": 0,
        "solver_movement_exclusion": 0,
        "solver_exclusion_unknown": 0,
        "conversion_or_export_missing": 0,
        "closed_wall_or_domain_candidate": 0,
        "inside_domain_unknown": 0,
        "no_last_valid_position": 0,
    }
    by_particle_id = (exclusion_evidence or {}).get("by_particle_id", {})
    registered_absorber = set(record.get("registered_absorbing_exit_faces", ()))
    examples: list[dict[str, Any]] = []
    tolerance = 0.51 * float(record["dp_m"])
    for particle_index in np.flatnonzero(missing):
        history = np.flatnonzero(np.asarray(h5["valid"][:, particle_index], dtype=bool))
        if not len(history):
            categories["no_last_valid_position"] += 1
            continue
        last = int(history[-1])
        point = positions[last, particle_index]
        velocity = velocities[last, particle_index]
        next_dt = float(time[last + 1] - time[last]) if last + 1 < len(time) else 0.0
        predicted_z = float(point[2] + velocity[2] * next_dt)
        open_top = bool(
            point[2] >= DOMAIN_TOP_M - tolerance
            or (velocity[2] > 0.0 and predicted_z >= DOMAIN_TOP_M - tolerance)
        )
        closed_domain = bool(
            point[0] < -tolerance
            or point[0] > 1.2 + tolerance
            or point[1] < -tolerance
            or point[1] > 0.4 + tolerance
            or point[2] < -tolerance
        )
        evidence = by_particle_id.get(str(int(particle_ids[particle_index])))
        if evidence is not None:
            reason = str(evidence.get("native_reason", "unknown"))
            if reason == "density":
                category = "solver_density_exclusion"
            elif reason == "position":
                if "top" in registered_absorber and float(evidence["position_m"][2]) >= DOMAIN_TOP_M - tolerance:
                    category = "legal_open_top_exit_candidate"
                else:
                    category = "solver_position_exclusion"
            elif reason == "movement":
                category = "solver_movement_exclusion"
            else:
                category = "solver_exclusion_unknown"
        elif open_top:
            # A top opening in the physical-wall specification is not an
            # absorbing outlet.  Without a registered outlet and a native
            # per-identity event, this remains unresolved.
            category = "top_crossing_without_registered_absorber"
        elif closed_domain:
            category = "closed_wall_or_domain_candidate"
        else:
            category = "conversion_or_export_missing" if (exclusion_evidence or {}).get("status") == "available" else "inside_domain_unknown"
        categories[category] += 1
        if len(examples) < 8:
            examples.append({
                "particle_index": int(particle_index),
                "last_valid_frame": last,
                "last_valid_time_s": float(time[last]),
                "last_valid_position_m": point.tolist(),
                "last_valid_velocity_m_s": velocity.tolist(),
                "one_step_predicted_z_m": predicted_z,
                "solver_exclusion": evidence,
                "category": category,
            })
    missing_count = int(missing.sum())
    if not missing_count:
        status = "no_missing_final_identities"
    elif any(categories[key] for key in (
        "top_crossing_without_registered_absorber", "solver_exclusion_unknown",
        "conversion_or_export_missing", "inside_domain_unknown", "no_last_valid_position",
    )):
        status = "unresolved_missing_identities"
    elif categories["legal_open_top_exit_candidate"] == missing_count:
        status = "legal_open_top_exit_only"
    elif sum(categories[key] for key in (
        "solver_density_exclusion", "solver_position_exclusion", "solver_movement_exclusion",
    )) == missing_count:
        status = "solver_exclusions_only"
    else:
        status = "classified_with_closed_domain_candidates"
    return {
        "missing_count": missing_count,
        "categories": categories,
        "status": status,
        "examples": examples,
        "registered_absorbing_exit_faces": sorted(registered_absorber),
        "exclusion_evidence_status": (exclusion_evidence or {}).get("status", "unavailable"),
        "exclusion_evidence_reason_counts": (exclusion_evidence or {}).get("reason_counts", {}),
        "domain_top_m": DOMAIN_TOP_M,
        "open_face_policy": "top_is_open; it is not an absorbing outlet without registered solver evidence",
    }


def full_time_audit(record: dict[str, Any], h5_path: Path, attempt: Path | None) -> dict[str, Any]:
    base = r5_gate.audit_hdf5(record | {"id": record["case_id"]}, h5_path, attempt)
    requested_times = np.linspace(0.0, TIME_MAX_S, 21)
    with h5py.File(h5_path, "r") as h5:
        time = np.asarray(h5["time"][:], dtype=np.float64)
        initial_valid = np.asarray(h5["valid"][0], dtype=bool)
        initial_mass = float(np.asarray(h5["mass"][0], dtype=np.float64)[initial_valid].sum(dtype=np.float64))
        metrics: list[dict[str, Any]] = []
        for requested in requested_times:
            frame = int(np.argmin(np.abs(time - requested)))
            metrics.append({
                "requested_time_s": float(requested),
                "actual_time_s": float(time[frame]),
                "frame": frame,
                **_frame_metrics(h5, frame, initial_mass),
            })
        exclusion_evidence = _partout_exclusion_evidence(attempt)
        missing_identity_classification = _classify_missing_identities(h5, record, exclusion_evidence)
    hard_failures: list[str] = []
    if not time.size or time[0] > 1e-6 or time[-1] < TIME_MAX_S - 5.0e-4:
        hard_failures.append("saved_time_axis_does_not_cover_0_to_1.5s")
    if base.get("finite_bad_value_rows", 0):
        hard_failures.append("nonfinite_values_for_valid_rows")
    if base.get("identities_reappeared_after_gap", 0):
        hard_failures.append("identity_reappeared_after_gap")
    if base.get("identities_introduced_after_initial", 0):
        hard_failures.append("identity_introduced_after_initial")
    penetration = base.get("penetration", {})
    if penetration.get("frames_with_penetration", 0):
        hard_failures.append("finite_wall_or_obstacle_penetration")
    if base.get("excluded_particles_from_solver_log") is None:
        hard_failures.append("excluded_particle_evidence_unknown")
    missing_unknown = "initial_identities_missing_at_final_requires_solver_loss_or_exit_classification"
    if base.get("unknowns"):
        for item in base["unknowns"]:
            if str(item) == missing_unknown and missing_identity_classification["status"] == "legal_open_top_exit_only":
                continue
            hard_failures.append(str(item))
    if missing_identity_classification["status"] not in {"no_missing_final_identities", "legal_open_top_exit_only"}:
        hard_failures.append("initial_identities_missing_with_unresolved_cause")
    if base.get("issues"):
        hard_failures.extend(str(item) for item in base["issues"])
    base.update({
        "r6_full_time_audit_status": "pass" if not hard_failures else "failed_or_unknown",
        "r6_hard_failures": sorted(set(hard_failures)),
        "fixed_time_grid_count": len(metrics),
        "fixed_time_grid": metrics,
        "continuous_initial_fluid_z_bounds_m": record["continuous_initial_fluid_z_bounds_m"],
        "height_m": record["height_m"],
        "height_label": record["height_label"],
        "resolution": record["resolution"],
        "missing_identity_classification": missing_identity_classification,
        "solver_exclusion_evidence": exclusion_evidence,
    })
    return base


def _base_audit_records() -> list[dict[str, Any]]:
    return base_records()


def _audit_records(prepared: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for record in [*_base_audit_records(), *prepared]:
        if "hdf5" in record:
            h5_path = Path(record["hdf5"])
        else:
            h5_path = DATA_ROOT / f"{record['case_id']}.h5"
        attempt = Path(record["attempt_root"]) if "attempt_root" in record else _latest_attempt(record)
        if "hdf5" in record:
            attempt_path = r5_gate.latest_attempt({"id": record["case_id"]})
        elif attempt is not None and attempt.is_dir() and (attempt / "attempt.json").is_file():
            attempt_path = attempt
        else:
            attempt_path = _latest_attempt(record)
        if not h5_path.is_file():
            result.append({
                "case_id": record["case_id"], "height_label": record["height_label"],
                "resolution": record["resolution"], "audit_status": "unknown",
                "r6_full_time_audit_status": "missing_hdf5", "r6_hard_failures": ["normalized_hdf5_missing"],
            })
            continue
        try:
            result.append(full_time_audit(record, h5_path, attempt_path))
        except Exception as error:
            result.append({
                "case_id": record["case_id"], "height_label": record["height_label"],
                "resolution": record["resolution"], "audit_status": "unknown",
                "r6_full_time_audit_status": "audit_exception", "r6_hard_failures": [repr(error)],
            })
    return result


def _metric_by_requested(audit: dict[str, Any]) -> dict[float, dict[str, Any]]:
    return {round(float(item["requested_time_s"]), 6): item for item in audit.get("fixed_time_grid", [])}


def _pair_comparison(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    a, b = _metric_by_requested(left), _metric_by_requested(right)
    rows = []
    for requested in sorted(set(a) & set(b)):
        first, second = a[requested], b[requested]
        if first.get("distribution") is None or second.get("distribution") is None:
            continue
        first_distribution = _closed_distribution(first["distribution"])
        second_distribution = _closed_distribution(second["distribution"])
        com = float(np.linalg.norm(np.asarray(first["com_m"]) - np.asarray(second["com_m"])))
        q90 = abs(float(first["front_quantiles_m"]["q90"]) - float(second["front_quantiles_m"]["q90"]))
        energy_left = float(first["kinetic_energy_proxy_j"])
        energy_right = float(second["kinetic_energy_proxy_j"])
        energy_delta = abs(energy_left - energy_right) / max(abs(energy_left), abs(energy_right), 1e-12)
        rows.append({
            "requested_time_s": requested,
            "distribution_tv": float(r5_gate.mass_fraction_tv(first_distribution, second_distribution)),
            "com_l2_m": com,
            "front_q90_abs_delta_m": q90,
            "kinetic_energy_relative_delta": energy_delta,
        })
    thresholds = {
        "distribution_tv": 0.05,
        "com_l2_m": 0.06,
        "front_q90_abs_delta_m": 0.06,
    }
    maxima = {
        "distribution_tv": max((row["distribution_tv"] for row in rows), default=None),
        "com_l2_m": max((row["com_l2_m"] for row in rows), default=None),
        "front_q90_abs_delta_m": max((row["front_q90_abs_delta_m"] for row in rows), default=None),
        "kinetic_energy_relative_delta": max((row["kinetic_energy_relative_delta"] for row in rows), default=None),
    }
    pass_status = bool(rows) and all(
        maxima[key] is not None and maxima[key] <= value
        for key, value in thresholds.items()
    )
    return {
        "time_grid_count": len(rows),
        "thresholds": thresholds,
        "maxima": maxima,
        "status": "pass_diagnostic" if pass_status else "fail_diagnostic",
        "series": rows,
    }


def _height_decisions(audits: Sequence[dict[str, Any]]) -> dict[str, Any]:
    by_height: dict[str, list[dict[str, Any]]] = {}
    for item in audits:
        by_height.setdefault(str(item.get("height_label", "unknown")), []).append(item)
    decisions: dict[str, Any] = {}
    qualified: list[str] = []
    for height_label, items in sorted(by_height.items()):
        by_level = {item.get("resolution"): item for item in items}
        comparisons = {}
        for left, right, label in (("coarse", "medium", "coarse_to_medium"), ("medium", "fine", "medium_to_fine")):
            if left in by_level and right in by_level:
                comparisons[label] = _pair_comparison(by_level[left], by_level[right])
            else:
                comparisons[label] = {"status": "unknown", "reason": "resolution_missing"}
        case_ok = len(by_level) == 3 and all(
            item.get("r6_full_time_audit_status") == "pass" for item in by_level.values()
        )
        comparison_ok = all(item.get("status") == "pass_diagnostic" for item in comparisons.values())
        status = "qualified_t1_height_candidate" if case_ok and comparison_ok else "blocked_t1_height_candidate"
        if status == "qualified_t1_height_candidate":
            qualified.append(height_label)
        decisions[height_label] = {
            "height_m": HEIGHTS_M.get(height_label),
            "continuous_initial_fluid_z_bounds_m": list(SOURCE_Z_BOUNDS_BY_HEIGHT.get(height_label, ())),
            "resolution_status": {level: by_level.get(level, {}).get("r6_full_time_audit_status", "missing") for level in RESOLUTIONS_M},
            "comparisons": comparisons,
            "status": status,
        }
    return {"by_height": decisions, "qualified_height_labels": qualified}


def audit_and_decide(prepared: Sequence[dict[str, Any]]) -> dict[str, Any]:
    audits = _audit_records(prepared)
    heights = _height_decisions(audits)
    qualified = heights["qualified_height_labels"]
    qualified_values = sorted(HEIGHTS_M[label] for label in qualified if label in HEIGHTS_M)
    recipe_status = "qualified" if len(qualified_values) >= 2 else "candidate_only_or_blocked"
    report = load_report()
    report.update({
        "schema_version": SCHEMA_VERSION,
        "round": "R6-N2",
        "scope": "plain dam-break full-time audit plus registered 0.9H0/1.1H0 endpoints",
        "audits": audits,
        "height_decisions": heights["by_height"],
        "qualified_t1_height_labels": qualified,
        "qualified_t1_height_range_m": [qualified_values[0], qualified_values[-1]] if qualified_values else None,
        "t1_recipe": {
            "status": recipe_status,
            "claim": "numerical SPH reference recipe only; not external continuous-fluid truth",
            "full_time_grid": "21 fixed requested physical times from 0 to 1.5 s",
            "resolution_pair_thresholds": {"distribution_tv": 0.05, "com_l2_m": 0.06, "front_q90_abs_delta_m": 0.06},
        },
        "t2_reference": {"status": "pending_plain_control_material_run"},
        "external_validation": {"status": "not_run", "formal_acceptance": False},
        "development_authorized": bool(recipe_status == "qualified"),
        "development_tranche": {
            "status": "not_started",
            "authorization": bool(recipe_status == "qualified"),
            "reason": "requires at least two qualified height endpoints; no cases generated in this audit",
            "planned_max_cases": 24,
            "first_batch_max_cases": 8,
        },
        "g4_training": {
            "status": "deferred_t1_not_authorized",
            "routes": ["ParticleMLP", "LocalInteraction"],
            "seeds": [17, 29, 43],
            "gpu_used": False,
            "reason": "do not train or rank models before a bounded development recipe is authorized",
        },
        "formal_release": False,
        "execution_status": "completed_with_findings" if len(qualified) < 3 else "completed",
        "acceptance_status": "candidate_t1_recipe" if qualified else "no_t1_recipe",
        "validation_scope": [
            "full saved time axis",
            "fixed 21-time physical grid",
            "mass-weighted center of mass",
            "front q50/q90/q99",
            "kinetic-energy proxy trend",
            "finite lifecycle and finite wall diagnostics",
        ],
        "open_blockers": [
            "T1 remains numerical-reference evidence, not external physical validation",
            "plain-control material T2 requires first-passage/final-destination evaluation",
            "center/twin missing identities remain a separate forensic branch",
            "formal v0.1 and hidden test release remain unauthorized",
        ],
    })
    atomic_json(REPORT, report)
    write_handoff(report)
    return report


def forensic_missing_identities() -> dict[str, Any]:
    result = {}
    for background in ("center_obstacle", "twin_obstacle_split_remerge"):
        rows = []
        for level in RESOLUTIONS_M:
            case_id = f"R4_F1_{background}_{level}"
            h5_path = r5_gate.DATA_ROOT / f"{case_id}.h5"
            if not h5_path.is_file():
                rows.append({"resolution": level, "status": "missing_hdf5"})
                continue
            with h5py.File(h5_path, "r") as h5:
                initial = np.asarray(h5["valid"][0], dtype=bool)
                final = np.asarray(h5["valid"][-1], dtype=bool)
                missing = initial & ~final
                categories = {"open_top_exit_candidate": 0, "closed_wall_or_domain": 0, "inside_domain_unknown": 0, "no_last_valid_position": 0}
                last_positions = []
                for index in np.flatnonzero(missing):
                    valid_history = np.flatnonzero(np.asarray(h5["valid"][:, index], dtype=bool))
                    if not len(valid_history):
                        categories["no_last_valid_position"] += 1
                        continue
                    point = np.asarray(h5["position"][int(valid_history[-1]), index], dtype=float)
                    last_positions.append(point.tolist())
                    if point[2] > 0.6 + 0.51 * RESOLUTIONS_M[level]:
                        categories["open_top_exit_candidate"] += 1
                    elif (
                        point[0] < 0.0 or point[0] > 1.2 or point[1] < 0.0 or point[1] > 0.4 or point[2] < 0.0
                    ):
                        categories["closed_wall_or_domain"] += 1
                    else:
                        categories["inside_domain_unknown"] += 1
                rows.append({
                    "resolution": level,
                    "initial_fluid_missing_at_final": int(missing.sum()),
                    "categories": categories,
                    "status": "classified_with_unknowns" if categories["inside_domain_unknown"] else "classified",
                })
        result[background] = rows
    return result


def ensure_base_sidecars() -> dict[str, Any]:
    outputs = {}
    for record in base_records():
        h5_path = Path(record["hdf5"])
        vtk = Path(record["generated_prefix"]).with_name(Path(record["generated_prefix"]).name + "_MkCells.vtk")
        sidecar = SIDECAR_ROOT / f"{record['case_id']}.h5"
        if not h5_path.is_file() or not vtk.is_file():
            outputs[record["resolution"]] = {"status": "missing_input", "hdf5": relpath(h5_path), "vtk": relpath(vtk)}
            continue
        if not sidecar.is_file():
            parsed = read_binary_vtk_polydata(vtk)
            write_sidecar(sidecar, record["case_id"], h5_path, parsed,
                          source_vtk_label=relpath(vtk), source_hdf5_label=relpath(h5_path))
        outputs[record["resolution"]] = {"status": "ready", "sidecar": relpath(sidecar), "sidecar_sha256": sha256(sidecar)}
    return outputs


def _material_semantics_summary(configurations: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for group in configurations:
        report_path = Path(group["report"])
        detailed = json.loads(report_path.read_text())
        for item in detailed["configurations"]:
            passage_mass_fractions = item.get("first_passage_status_mass_fractions")
            if passage_mass_fractions is None:
                # Older completed bundles predate the summary-only mass
                # fields.  Recover the same semantics from their immutable
                # HDF5 arrays instead of rerunning a six-group CPU campaign.
                bundle = Path(item["trajectory_bundle"])
                if not bundle.is_absolute():
                    bundle = LAB / bundle
                with h5py.File(bundle, "r") as h5:
                    statuses = np.asarray(h5["destination/first_passage_status"][:], dtype=str)
                    weights = np.asarray(h5["mass_weight"][:], dtype=np.float64)
                    denominator = float(weights.sum(dtype=np.float64))
                passage_mass_fractions = {
                    status: float(weights[statuses == status].sum(dtype=np.float64) / max(denominator, 1e-30))
                    for status in sorted(set(statuses))
                }
            rows.append({
                "resolution": group["resolution"],
                "config_id": item["config_id"],
                "seed_count": item["seed_count"],
                "substeps": item["substeps"],
                "first_passage_status_counts": item.get("first_passage_status_counts", {}),
                "first_passage_status_mass_fractions": passage_mass_fractions,
                "terminal_category_counts": item.get("terminal_category_counts", {}),
                "terminal_category_mass_fractions": item.get("mass_accounting", {}).get("fractions_of_initial_mass", {}),
                "support_diagnostics": item.get("support_diagnostics", {}),
                "checks": item.get("checks", {}),
            })
    return rows


def _material_pair_comparisons(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Report seed/substep stability without turning T2 into an acceptance gate."""
    comparisons = []
    for left_index, left in enumerate(rows):
        for right in rows[left_index + 1:]:
            if left["resolution"] != right["resolution"]:
                continue
            same_seed = left["seed_count"] == right["seed_count"]
            same_substeps = left["substeps"] == right["substeps"]
            if same_seed == same_substeps:
                continue
            categories = sorted(set(left["terminal_category_mass_fractions"]) | set(right["terminal_category_mass_fractions"]))
            terminal_tv = 0.5 * sum(
                abs(
                    float(left["terminal_category_mass_fractions"].get(category, 0.0))
                    - float(right["terminal_category_mass_fractions"].get(category, 0.0))
                )
                for category in categories
            )
            passage_labels = sorted(set(left["first_passage_status_mass_fractions"]) | set(right["first_passage_status_mass_fractions"]))
            passage_l1 = sum(
                abs(
                    float(left["first_passage_status_mass_fractions"].get(label, 0.0))
                    - float(right["first_passage_status_mass_fractions"].get(label, 0.0))
                )
                for label in passage_labels
            )
            comparisons.append({
                "resolution": left["resolution"],
                "left": {"config_id": left["config_id"], "seed_count": left["seed_count"], "substeps": left["substeps"]},
                "right": {"config_id": right["config_id"], "seed_count": right["seed_count"], "substeps": right["substeps"]},
                "comparison_axis": "seed_count" if same_substeps else "substeps",
                "terminal_category_tv": float(terminal_tv),
                "first_passage_status_mass_l1": float(passage_l1),
                "status": "reported_not_acceptance_gate",
            })
    return comparisons


def run_plain_material() -> dict[str, Any]:
    sidecars = ensure_base_sidecars()
    material_root = CAMPAIGN / "artifacts" / "r6-f1-material-task"
    configurations = []
    for level, seed_counts in (("medium", (256, 512)), ("fine", (512,))):
        sidecar = SIDECAR_ROOT / f"R4_F1_plain_dam_break_{level}.h5"
        hdf5 = r5_gate.DATA_ROOT / f"R4_F1_plain_dam_break_{level}.h5"
        if not sidecar.is_file() or not hdf5.is_file():
            configurations.append({"resolution": level, "status": "blocked_missing_sidecar_or_hdf5"})
            continue
        output_dir = material_root / level
        detailed_report_path = output_dir / "r5-f1-material-task.json"
        reused = False
        if detailed_report_path.is_file():
            try:
                report = json.loads(detailed_report_path.read_text())
                reused = report.get("execution_status") == "completed" and len(report.get("configurations", [])) == len(seed_counts) * 2
            except json.JSONDecodeError:
                report = None
        if not reused:
            report = run_material_bounded(
                hdf5, sidecar,
                case_id=f"R4_F1_plain_dam_break_{level}",
                spec_path=CAMPAIGN / "r6-f1-material-task" / "transport_spec.plain.v1.json",
                output_dir=output_dir,
                seed_counts=seed_counts,
                substeps=(2, 4),
                source_z_bounds_m=MATERIAL_SOURCE_Z_BOUNDS_M,
            )
        configurations.append({
            "resolution": level,
            "status": report["execution_status"],
            "report": relpath(output_dir / "r5-f1-material-task.json"),
            "checks": report["checks"],
            "configuration_count": len(report["configurations"]),
            "mass_accounting": report["mass_accounting"],
            "reused_existing_trajectory_bundles": reused,
        })
    semantics = _material_semantics_summary(configurations)
    report = {
        "schema_version": "r6-f1-material-task-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "execution_status": "completed" if all(item["status"] == "completed" for item in configurations) else "completed_with_findings",
        "acceptance_status": "candidate_t2_numerical_reference_only",
        "formal_material_target_admitted": False,
        "case_family": "F1",
        "case_variant": "plain_control",
        "execution_environment": {
            "solver_rerun": False,
            "gpu_used": False,
            "cuda_used": False,
            "neighbour_backend": "optional CPU Torch exact top-k for empty visibility set; NumPy fallback",
            "finite_wall_collision_path": "unchanged full sidecar swept-wall check",
        },
        "source_layers": {
            "semantic_role": "initial-depth measurement stratum, not material identity",
            "continuous_bounds_m": list(MATERIAL_SOURCE_Z_BOUNDS_M),
            "nominal_geometry_bounds_m": [0.04, 0.50],
            "support_envelope_reason": "one common envelope contains all reused R5 discrete initial centres",
            "cross_resolution_policy": "same declared continuous bounds for coarse/medium/fine",
        },
        "sidecars": sidecars,
        "configurations": configurations,
        "semantics_by_configuration": semantics,
        "cross_configuration_comparisons": _material_pair_comparisons(semantics),
        "open_blockers": [
            "T2 numerical transport reference completed; external/reference anchors are still absent",
            "first passage and final destination are reported separately and are not interchangeable",
            "support-gate failures and tracer_unknown mass remain reported rather than silently discarded",
            "formal v0.1 and development release remain controlled by T1/reference gates",
        ],
    }
    atomic_json(MATERIAL_REPORT, report)
    return report


def load_report() -> dict[str, Any]:
    if REPORT.is_file():
        try:
            return json.loads(REPORT.read_text())
        except json.JSONDecodeError:
            pass
    return {
        "schema_version": SCHEMA_VERSION,
        "round": "R6-N2",
        "execution_status": "not_started",
        "acceptance_status": "pending",
        "formal_release": False,
        "protected_gpu_indices": list(PROTECTED_GPU_IDS),
        "allowed_gpu_indices": list(GPU_IDS),
        "resource_budget": {"initial_gpu_hours": 8.0, "hard_upper_gpu_hours": 24.0},
    }


def write_handoff(report: dict[str, Any]) -> None:
    height_rows = []
    for label, item in report.get("height_decisions", {}).items():
        height_rows.append(
            f"| `{label}` | `{item.get('height_m')}` | `{item.get('status')}` | "
            f"`{item.get('comparisons', {}).get('coarse_to_medium', {}).get('maxima', {}).get('distribution_tv')}` | "
            f"`{item.get('comparisons', {}).get('medium_to_fine', {}).get('maxima', {}).get('distribution_tv')}` |"
        )
    text = f"""# R6 N2 latest handoff

Date: {datetime.now(timezone.utc).date().isoformat()}
Scope: full-time `plain_dam_break` re-audit, registered `0.9H0`/`1.1H0` endpoint runs, and plain-control material semantics.

## Decision

`formal_v0.1 = NO_GO` remains invariant.  The T1 result is a numerical SPH
reference-recipe decision only; it is not an external continuous-fluid truth
claim.  Development authorization is limited to the explicit recipe recorded
in `r6-n2-n2-campaign.json` and is false unless the machine-readable gate says
otherwise.

| height label | height (m) | decision | coarse-medium max TV | medium-fine max TV |
|---|---:|---|---:|---:|
{chr(10).join(height_rows) if height_rows else '| none | | | | |'}

Qualified height labels: `{report.get('qualified_t1_height_labels', [])}`
Qualified range: `{report.get('qualified_t1_height_range_m')}`
T1 recipe status: `{report.get('t1_recipe', {}).get('status')}`
Development authorized: `{report.get('development_authorized')}`
Development tranche: `{report.get('development_tranche', {}).get('status')}`

## T2 material reference

Status: `{report.get('t2_reference', {}).get('status', 'pending')}`; acceptance:
`{report.get('t2_reference', {}).get('acceptance_status', 'not_run')}`; formal
material admission: `false`.

The plain-control run uses one continuous source support envelope
`{list(MATERIAL_SOURCE_Z_BOUNDS_M)} m` across medium/fine, with nominal geometry
range `[0.04, 0.50] m` retained separately.  First passage and final category
are separate fields; failure after an earlier arrival is not relabelled as a
negative first-passage result.  The material configuration count is
`{report.get('t2_reference', {}).get('configuration_count', 0)}` and all
cross-configuration comparisons remain diagnostic, not acceptance gates.
The plain-control neighbour query used an optional CPU-only exact top-k
accelerator; no CUDA/GPU was used, and the full finite-wall collision check
remained active.

## G4 and external scope

G4 training status: `{report.get('g4_training', {}).get('status', 'not_run')}`;
no G4 model ranking or development tranche was launched from this round.
External/reference validation: `{report.get('external_validation', {}).get('status')}`.

## Semantics and scope

- The audit uses 21 fixed requested physical times over 0--1.5 s and records
  the actual nearest saved frame.
- It compares mass distribution, mass-weighted centre of mass, front q50/q90/q99,
  and a kinetic-energy proxy across the complete time window.
- The initial fluid source layers use declared continuous z bounds, not per-run
  discrete particle extrema.  The latter are retained only as diagnostics.
- The material task separates first passage from final destination.  A tracer
  that reaches the target and later fails has an observed first passage but an
  unknown final category.
- F6 received no new solver call.  Center/twin forensic evidence is bounded and
  does not block the plain control.

## Machine artefacts

- T1 report: `r6-n2-n2-campaign.json`
- Material report: `r6-f1-material-task.json`
- This handoff: `R6-N2-LATEST-HANDOFF.md`

Open blockers: {json.dumps(report.get('open_blockers', []), ensure_ascii=False)}
"""
    HANDOFF.write_text(text)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run", "normalize", "audit", "material", "forensics", "all"), nargs="?", default="all")
    parser.add_argument("--rerun", action="store_true")
    args = parser.parse_args(argv)
    if args.action in {"prepare", "all"}:
        prepared = prepare()
    elif args.action in {"run", "normalize", "audit"}:
        # Reuse the immutable preparation manifest for post-processing.  A
        # later audit must not silently regenerate candidate XML/GenCase
        # products and change the evidence it is supposed to inspect.
        prepared = load_report().get("prepared_cases") or prepare()
    else:
        prepared = load_report().get("prepared_cases", records())
    if args.action in {"run", "all"}:
        run_solver(prepared, rerun=args.rerun)
    if args.action in {"normalize", "audit", "all"}:
        normalize(prepared)
    if args.action in {"audit", "all"}:
        report = audit_and_decide(prepared)
        report["forensics"] = forensic_missing_identities()
        atomic_json(REPORT, report)
        write_handoff(report)
    if args.action == "forensics":
        report = load_report()
        report["forensics"] = forensic_missing_identities()
        atomic_json(REPORT, report)
    if args.action in {"material", "all"}:
        material = run_plain_material()
        report = load_report()
        report.setdefault("development_tranche", {
            "status": "not_started",
            "authorization": bool(report.get("development_authorized", False)),
            "reason": "requires at least two qualified height endpoints; no cases generated in this audit",
            "planned_max_cases": 24,
            "first_batch_max_cases": 8,
        })
        report.setdefault("g4_training", {
            "status": "deferred_t1_not_authorized",
            "routes": ["ParticleMLP", "LocalInteraction"],
            "seeds": [17, 29, 43],
            "gpu_used": False,
            "reason": "do not train or rank models before a bounded development recipe is authorized",
        })
        report["t2_reference"] = {
            "status": material["execution_status"],
            "report": relpath(MATERIAL_REPORT),
            "acceptance_status": material["acceptance_status"],
            "configuration_count": sum(item.get("configuration_count", 0) for item in material["configurations"]),
            "semantics_by_configuration": material.get("semantics_by_configuration", []),
            "cross_configuration_comparisons": material.get("cross_configuration_comparisons", []),
            "formal_acceptance": False,
        }
        report["open_blockers"] = [
            "T1 remains a numerical-reference candidate at one height only; development authorization is false",
            "T2 plain-control material reference completed, but external/reference anchors are absent",
            "material support-gate failures and tracer_unknown mass remain candidate-only findings",
            "center/twin missing identities remain a separate forensic branch",
            "formal v0.1 and hidden test release remain unauthorized",
        ]
        atomic_json(REPORT, report)
        write_handoff(report)
    report = load_report()
    print(json.dumps({
        "execution_status": report.get("execution_status"),
        "normalization_status": report.get("normalization_status"),
        "acceptance_status": report.get("acceptance_status"),
        "qualified_t1_height_labels": report.get("qualified_t1_height_labels", []),
        "qualified_t1_height_range_m": report.get("qualified_t1_height_range_m"),
        "development_authorized": report.get("development_authorized", False),
        "formal_release": report.get("formal_release", False),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
