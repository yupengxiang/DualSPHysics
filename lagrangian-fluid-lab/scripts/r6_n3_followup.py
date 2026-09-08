#!/usr/bin/env python3
"""R6 N3 bounded follow-up for the plain dam-break route.

N3 is intentionally small.  It performs at most two new fine-grid solver
calls, both at the registered CFL repair value, and keeps the R6-N2 evidence
immutable.  The same module also produces compact P0 timing rows and an
identity-level P1 forensic report from the native ``PartOut``/``RunPARTs``
records.  It does not authorize T1 development, G4, or a formal release.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Sequence
import xml.etree.ElementTree as ET

import h5py
import numpy as np

try:
    from scripts import r6_n2_campaign as r6
    from scripts.boundary_sidecars import read_binary_vtk_polydata, write_sidecar
    from scripts.campaign_runner import execute_attempt, query_gpus, require_idle_allowed_gpu
    from scripts.r5_f1_solver_gate import WALL_SPECS
    from scripts.trajectory_io import convert_streaming
    from scripts.w02_semantics import partvtk_csv
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import r6_n2_campaign as r6
    from boundary_sidecars import read_binary_vtk_polydata, write_sidecar
    from campaign_runner import execute_attempt, query_gpus, require_idle_allowed_gpu
    from r5_f1_solver_gate import WALL_SPECS
    from trajectory_io import convert_streaming
    from w02_semantics import partvtk_csv


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "v0.1-candidate"
BIN = LAB / "vendor" / "official" / "DualSPHysics_v5.4" / "bin" / "linux"
GENCASE = BIN / "GenCase_linux64"
SOLVER = BIN / "DualSPHysics5.4_linux64"
PARTVTKOUT = BIN / "PartVTKOut_linux64"
SOURCE_DEFINITION = LAB / "cases" / "F1" / "F1_dam_break_plain" / "F1_dam_break_plain_Def.xml"

CASE_ROOT = CAMPAIGN / "cases" / "r6-n3-endpoint-cfl"
ARTIFACT_ROOT = CAMPAIGN / "artifacts" / "r6-n3-endpoint-cfl"
RUN_ROOT = CAMPAIGN / "runs" / "r6-n3-endpoint-cfl"
DATA_ROOT = CAMPAIGN / "data" / "r6-n3-endpoint-cfl"
SIDECAR_ROOT = CAMPAIGN / "sidecars" / "r6-n3-endpoint-cfl"

REPORT = CAMPAIGN / "r6-n3-endpoint-closure.json"
P0_REPORT = CAMPAIGN / "r6-n3-phase-profile.json"
P1_REPORT = CAMPAIGN / "r6-n3-endpoint-forensics.json"

GPU_IDS = (4, 5)
PROTECTED_GPU_IDS = (0, 1, 2, 3)
CFL_NUMBER = 0.1
TIME_MAX_S = 1.5
TIME_OUT_S = 0.001
DOMAIN_TOP_M = 0.6
HEIGHTS_M = {"h09": 0.414, "h11": 0.506}
DP_M = 0.014
SCHEMA_VERSION = "r6-n3-endpoint-cfl-v1"


def relpath(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(LAB.resolve()))
    except ValueError:
        return str(Path(path).resolve())


def lab_path(value: str | Path) -> Path:
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
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=True) + "\n")
    os.replace(temporary, path)


def _environment(*, cpu: bool = False) -> dict[str, str]:
    value = os.environ.copy()
    value["LD_LIBRARY_PATH"] = f"{BIN}:{value.get('LD_LIBRARY_PATH', '')}"
    value["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    if cpu:
        value["CUDA_VISIBLE_DEVICES"] = ""
        value["NVIDIA_VISIBLE_DEVICES"] = "void"
    return value


def _allowed_uuids() -> list[str]:
    return list(json.loads((CAMPAIGN / "w00-inventory.json").read_text())["execution_policy"]["allowed_gpu_uuids"])


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
    for index, height_label in enumerate(("h09", "h11")):
        case_id = f"R6_N3_F1_plain_dam_break_{height_label}_fine_cfl010"
        result.append({
            "id": case_id,
            "case_id": case_id,
            "family": "F1",
            "background_id": "plain_dam_break",
            "mechanism": "collapse-runup-return",
            "height_label": height_label,
            "height_m": HEIGHTS_M[height_label],
            "continuous_initial_fluid_z_bounds_m": list(r6.SOURCE_Z_BOUNDS_BY_HEIGHT[height_label]),
            "resolution": "fine",
            "dp_m": DP_M,
            "cfl_number": CFL_NUMBER,
            "time_max_s": TIME_MAX_S,
            "time_out_s": TIME_OUT_S,
            "source_definition": str(SOURCE_DEFINITION),
            "gpu": GPU_IDS[index],
            "registered_absorbing_exit_faces": [],
            "wall_spec": WALL_SPECS["plain_dam_break"],
        })
    return result


def record_hash(record: dict[str, Any]) -> str:
    stable = {key: value for key, value in record.items() if key not in {"candidate_definition", "generated_prefix"}}
    stable["source_definition_sha256"] = sha256(SOURCE_DEFINITION)
    return hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _load_report() -> dict[str, Any]:
    if REPORT.is_file():
        try:
            return json.loads(REPORT.read_text())
        except json.JSONDecodeError:
            pass
    return {
        "schema_version": SCHEMA_VERSION,
        "round": "R6-N3",
        "execution_status": "not_started",
        "formal_release": False,
        "development_authorized": False,
        "protected_gpu_indices": list(PROTECTED_GPU_IDS),
        "allowed_gpu_indices": list(GPU_IDS),
        "resource_budget": {
            "new_solver_cases_authorized": 2,
            "new_solver_cases_used": 0,
            "initial_gpu_hours": 8.0,
            "hard_upper_gpu_hours": 24.0,
        },
    }


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
    _fluid_drawbox(root).find("./size").set("z", str(record["height_m"]))
    cfl = root.find(".//constantsdef/cflnumber")
    if cfl is None:
        raise ValueError("plain source has no constantsdef/cflnumber")
    cfl.set("value", str(record["cfl_number"]))
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
    started = time.perf_counter()
    process = subprocess.run(
        [str(GENCASE), str(candidate.with_suffix("")), str(prefix), "-save:all"],
        cwd=generated_dir, env=_environment(cpu=True), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )
    elapsed = time.perf_counter() - started
    stdout_path = generated_dir / "gencase.stdout.log"
    stdout_path.write_text(process.stdout)
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
            "elapsed_seconds": elapsed,
            "stdout": relpath(stdout_path),
        },
    }


def prepare() -> list[dict[str, Any]]:
    prepared = [prepare_one(record) for record in records()]
    report = _load_report()
    report.update({
        "schema_version": SCHEMA_VERSION,
        "round": "R6-N3",
        "preparation_status": "completed",
        "prepared_cases": prepared,
        "execution_status": "prepared_only",
        "resource_budget": {**report.get("resource_budget", {}), "new_solver_cases_authorized": 2},
    })
    atomic_json(REPORT, report)
    return prepared


def _latest_attempt(record: dict[str, Any]) -> Path | None:
    latest = RUN_ROOT / record["case_id"] / "latest.json"
    if not latest.is_file():
        return None
    try:
        attempt = Path(json.loads(latest.read_text())["attempt_directory"])
    except (KeyError, json.JSONDecodeError):
        return None
    return attempt if attempt.is_dir() else None


def run_one(record: dict[str, Any], *, rerun: bool = False) -> dict[str, Any]:
    latest = RUN_ROOT / record["case_id"] / "latest.json"
    expected_hash = record_hash(record)
    if latest.is_file() and not rerun:
        payload = json.loads(latest.read_text())
        if payload.get("status") == "completed" and payload.get("record_hash") == expected_hash:
            return {**payload, "execution_status": "reused_completed"}
    gpu = int(record["gpu"])
    gpu_record = require_idle_allowed_gpu(gpu, _allowed_uuids())
    prefix = lab_path(record["generated_prefix"])
    result = execute_attempt(
        record["case_id"], [str(SOLVER), f"-gpu:{gpu}", str(prefix), "{output}"], RUN_ROOT,
        cwd=prefix.parent, env=_environment(), evidence_glob="data/Part_*.bi4",
        required_text="Finished execution (code=0)",
    )
    payload = {
        **result,
        "record_hash": expected_hash,
        "execution_status": "completed" if result.get("status") == "completed" else "solver_failed",
        "gpu_at_launch": gpu_record,
        "protected_gpu_indices": list(PROTECTED_GPU_IDS),
        "gpu_index_requested": gpu,
        "input_generated_xml_sha256": sha256(prefix.with_suffix(".xml")),
        "input_generated_bi4_sha256": sha256(prefix.with_suffix(".bi4")),
    }
    atomic_json(RUN_ROOT / record["case_id"] / "latest.json", payload)
    return payload


def run_solver(prepared: Sequence[dict[str, Any]], *, rerun: bool = False) -> list[dict[str, Any]]:
    prepared = list(prepared)
    if len(prepared) > 2:
        raise ValueError("N3 authorizes at most two new solver cases")
    with ThreadPoolExecutor(max_workers=len(prepared) or 1) as pool:
        results = list(pool.map(lambda item: run_one(item, rerun=rerun), prepared))
    report = _load_report()
    executed = sum(item.get("execution_status") == "completed" for item in results)
    report.update({
        "solver_runs": results,
        "execution_status": "completed" if all(
            item.get("execution_status") in {"completed", "reused_completed"} for item in results
        ) else "partial_with_findings",
        "resource_snapshot_after_solver": query_gpus(),
        "resource_budget": {
            **report.get("resource_budget", {}),
            "new_solver_cases_used": max(int(report.get("resource_budget", {}).get("new_solver_cases_used", 0)), executed),
        },
    })
    atomic_json(REPORT, report)
    return results


def normalize_one(record: dict[str, Any]) -> dict[str, Any]:
    attempt = _latest_attempt(record)
    if attempt is None:
        return {"case_id": record["case_id"], "normalization_status": "blocked_missing_attempt"}
    output = DATA_ROOT / f"{record['case_id']}.h5"
    csv_dir = attempt / "csv"
    started = time.perf_counter()
    try:
        complete = False
        if output.is_file():
            with h5py.File(output, "r") as h5:
                complete = bool(h5.attrs.get("conversion_complete", True))
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
            h5.attrs["r6_n3_cfl_number"] = float(record["cfl_number"])
            h5.attrs["r6_n3_record_hash"] = record_hash(record)
            h5.attrs["source_definition_sha256"] = sha256(SOURCE_DEFINITION)
        prefix = lab_path(record["generated_prefix"])
        vtk = prefix.with_name(prefix.name + "_MkCells.vtk")
        parsed = read_binary_vtk_polydata(vtk)
        sidecar = SIDECAR_ROOT / f"{record['case_id']}.h5"
        sidecar_summary = write_sidecar(
            sidecar, record["case_id"], output, parsed,
            source_vtk_label=relpath(vtk), source_hdf5_label=relpath(output),
        )
        return {
            "case_id": record["case_id"],
            "normalization_status": "completed",
            "elapsed_seconds": time.perf_counter() - started,
            "hdf5": relpath(output),
            "hdf5_sha256": sha256(output),
            "sidecar": relpath(sidecar),
            "sidecar_sha256": sha256(sidecar),
            "sidecar_audit": sidecar_summary,
        }
    except Exception as error:
        return {
            "case_id": record["case_id"],
            "normalization_status": "failed",
            "elapsed_seconds": time.perf_counter() - started,
            "error": repr(error),
        }


def normalize(prepared: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    results = [normalize_one(record) for record in prepared]
    report = _load_report()
    report["normalization"] = results
    report["normalization_status"] = "completed" if all(
        item.get("normalization_status") == "completed" for item in results
    ) else "partial_with_findings"
    atomic_json(REPORT, report)
    return results


def _case_h5(record: dict[str, Any]) -> Path:
    if record["case_id"].startswith("R6_N3_"):
        return DATA_ROOT / f"{record['case_id']}.h5"
    return r6.DATA_ROOT / f"{record['case_id']}.h5"


def audit_new(prepared: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    audits = []
    for record in prepared:
        h5_path = _case_h5(record)
        attempt = _latest_attempt(record)
        started = time.perf_counter()
        if not h5_path.is_file() or attempt is None:
            audits.append({
                "case_id": record["case_id"],
                "r6_full_time_audit_status": "missing_input",
                "r6_hard_failures": ["normalized_hdf5_or_attempt_missing"],
                "audit_elapsed_seconds": time.perf_counter() - started,
            })
            continue
        try:
            result = r6.full_time_audit(record, h5_path, attempt)
            result["audit_elapsed_seconds"] = time.perf_counter() - started
            audits.append(result)
        except Exception as error:
            audits.append({
                "case_id": record["case_id"],
                "r6_full_time_audit_status": "audit_exception",
                "r6_hard_failures": [repr(error)],
                "audit_elapsed_seconds": time.perf_counter() - started,
            })
    report = _load_report()
    report.update({
        "audits": audits,
        "audit_status": "completed" if all(
            item.get("r6_full_time_audit_status") in {"pass", "failed_or_unknown"} for item in audits
        ) else "partial_with_findings",
    })
    atomic_json(REPORT, report)
    return audits


def _normalise_csv_row(row: dict[str, Any]) -> dict[str, Any]:
    return {str(key).strip().rstrip(","): value for key, value in row.items() if key is not None}


def _runparts_rows(attempt: Path | None) -> dict[int, dict[str, Any]]:
    if attempt is None or not (attempt / "RunPARTs.csv").is_file():
        return {}
    lines = (attempt / "RunPARTs.csv").read_text(errors="replace").splitlines()
    header_index = next((index for index, line in enumerate(lines) if line.startswith("Part;")), None)
    if header_index is None:
        return {}
    rows = {}
    for raw in csv.DictReader(lines[header_index:], delimiter=";"):
        row = _normalise_csv_row(raw)
        try:
            rows[int(str(row.get("Part", "")).strip())] = row
        except ValueError:
            continue
    return rows


def _float(value: Any) -> float | None:
    try:
        result = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return result if np.isfinite(result) else None


def _parse_domain(xml_path: Path) -> dict[str, list[float]] | None:
    if not xml_path.is_file():
        return None
    root = ET.parse(xml_path).getroot()
    # GenCase leaves the requested ``simulationdomain`` expressions in the
    # execution section and writes the resolved particle envelope in
    # ``particles/_summary/positions``.  The latter is the actual numerical
    # domain relevant to the identity-forensics decision.
    positions = root.find(".//particles/_summary/positions")
    if positions is not None:
        posmin, posmax = positions.find("./posmin"), positions.find("./posmax")
    else:
        domain = root.find(".//simulationdomain")
        if domain is None:
            return None
        posmin, posmax = domain.find("./posmin"), domain.find("./posmax")
    if posmin is None or posmax is None:
        return None
    try:
        return {
            "min_m": [float(posmin.attrib[key]) for key in ("x", "y", "z")],
            "max_m": [float(posmax.attrib[key]) for key in ("x", "y", "z")],
        }
    except (KeyError, ValueError):
        return None


def _inside_domain(point: Sequence[float], domain: dict[str, list[float]] | None) -> bool | None:
    if domain is None:
        return None
    point = np.asarray(point, dtype=float)
    return bool(np.all(point >= np.asarray(domain["min_m"])) and np.all(point <= np.asarray(domain["max_m"])))


def _forensic_case(record: dict[str, Any]) -> dict[str, Any]:
    h5_path = _case_h5(record)
    attempt = _latest_attempt(record) if record["case_id"].startswith("R6_N3_") else r6._latest_attempt(record)
    generated = lab_path(record.get("generated_prefix", "")) if record.get("generated_prefix") else None
    domain = _parse_domain(generated.with_suffix(".xml")) if generated else None
    evidence = r6._partout_exclusion_evidence(attempt)
    part_rows = _runparts_rows(attempt)
    hashes = {
        "hdf5_sha256": sha256(h5_path) if h5_path.is_file() else None,
        "runparts_sha256": sha256(attempt / "RunPARTs.csv") if attempt and (attempt / "RunPARTs.csv").is_file() else None,
        "run_out_sha256": sha256(attempt / "Run.out") if attempt and (attempt / "Run.out").is_file() else None,
        "partout_000_obi4_sha256": sha256(attempt / "data" / "PartOut_000.obi4") if attempt and (attempt / "data" / "PartOut_000.obi4").is_file() else None,
    }
    base = {
        "case_id": record["case_id"],
        "height_label": record.get("height_label"),
        "resolution": record.get("resolution"),
        "hdf5": relpath(h5_path),
        "attempt": relpath(attempt) if attempt else None,
        "actual_simulation_domain": domain,
        "physical_wall_spec": record.get("wall_spec", WALL_SPECS["plain_dam_break"]),
        "top_is_absorbing": False,
        "raw_input_hashes": hashes,
        "partout_status": evidence.get("status"),
        "partout_reason_counts": evidence.get("reason_counts", {}),
        "missing_identity_count": 0,
        "missing_identities": [],
    }
    if not h5_path.is_file():
        base["status"] = "missing_hdf5"
        return base
    with h5py.File(h5_path, "r") as h5:
        time_axis = np.asarray(h5["time"][:], dtype=np.float64)
        valid = np.asarray(h5["valid"][:], dtype=bool)
        initial = valid[0]
        final = valid[-1]
        missing_indices = np.flatnonzero(initial & ~final)
        particle_ids = np.asarray(
            h5["particle_id"][:] if "particle_id" in h5 else np.arange(len(initial)), dtype=np.int64
        )
        base.update({
            "initial_particles": int(initial.sum()),
            "final_particles": int(final.sum()),
            "missing_identity_count": int(len(missing_indices)),
            "time_start_s": float(time_axis[0]),
            "time_end_s": float(time_axis[-1]),
        })
        last_frames: dict[int, list[int]] = {}
        last_by_index: dict[int, int] = {}
        for index in missing_indices:
            history = np.flatnonzero(valid[:, index])
            if not len(history):
                continue
            frame = int(history[-1])
            last_by_index[int(index)] = frame
            last_frames.setdefault(frame, []).append(int(index))
        states: dict[int, tuple[np.ndarray, np.ndarray, float | None]] = {}
        for frame, indices in last_frames.items():
            positions = np.asarray(h5["position"][frame, indices], dtype=float)
            velocities = np.asarray(h5["velocity"][frame, indices], dtype=float)
            density = np.asarray(h5["density"][frame, indices], dtype=float)
            for offset, index in enumerate(indices):
                states[index] = (positions[offset], velocities[offset], _float(density[offset]))
        rows = []
        for index in missing_indices:
            index = int(index)
            particle_id = int(particle_ids[index])
            last_frame = last_by_index.get(index)
            state = states.get(index)
            event = evidence.get("by_particle_id", {}).get(str(particle_id))
            event_part = int(event["part_out"]) if event else None
            part_row = part_rows.get(event_part, {}) if event_part is not None else {}
            event_time = _float(part_row.get("TimeStep [s]"))
            row = {
                "particle_index": index,
                "particle_id": particle_id,
                "last_valid_frame": last_frame,
                "last_valid_time_s": float(time_axis[last_frame]) if last_frame is not None else None,
                "first_missing_frame": last_frame + 1 if last_frame is not None and last_frame + 1 < len(time_axis) else None,
                "first_missing_time_s": float(time_axis[last_frame + 1]) if last_frame is not None and last_frame + 1 < len(time_axis) else None,
                "failure_window_s": (
                    [float(time_axis[last_frame]), float(time_axis[last_frame + 1])]
                    if last_frame is not None and last_frame + 1 < len(time_axis) else None
                ),
                "last_valid_position_m": state[0].tolist() if state else None,
                "last_valid_velocity_m_s": state[1].tolist() if state else None,
                "last_valid_density_kg_m3": state[2] if state else None,
                "part_out": event_part,
                "native_event_time_s": event_time,
                "native_reason": event.get("native_reason") if event else None,
                "native_reason_counters": event.get("native_reason_counters", []) if event else [],
                "native_event_position_m": event.get("position_m") if event else None,
                "native_event_density_kg_m3": event.get("density_kg_m3") if event else None,
                "native_motive": event.get("motive") if event else None,
                "inside_actual_simulation_domain": _inside_domain(event["position_m"], domain) if event else None,
                "classification": (
                    "solver_density_exclusion" if event and event.get("native_reason") == "density"
                    else "solver_position_exclusion" if event and event.get("native_reason") == "position"
                    else "solver_movement_exclusion" if event and event.get("native_reason") == "movement"
                    else "unresolved_missing_identity"
                ),
            }
            rows.append(row)
        base["missing_identities"] = rows
    base["status"] = "no_missing_final_identities" if not base["missing_identities"] else (
        "solver_exclusions_only" if all(
            row["classification"] in {"solver_density_exclusion", "solver_position_exclusion", "solver_movement_exclusion"}
            for row in base["missing_identities"]
        ) else "unresolved_missing_identity"
    )
    return base


def _forensic_records() -> list[dict[str, Any]]:
    current = {item["case_id"]: item for item in r6.records()}
    try:
        previous = r6.load_report()
        for item in previous.get("prepared_cases", []):
            current[item["case_id"]] = item
    except (OSError, json.JSONDecodeError, KeyError):
        pass
    if REPORT.is_file():
        try:
            for item in json.loads(REPORT.read_text()).get("prepared_cases", []):
                current[item["case_id"]] = item
        except json.JSONDecodeError:
            pass
    return [*current.values()]


def build_forensics() -> dict[str, Any]:
    started = time.perf_counter()
    cases = [_forensic_case(record) for record in _forensic_records()]
    payload = {
        "schema_version": "r6-n3-p1-forensics-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "execution_status": "completed",
        "top_absorption_policy": "top is open geometrically but is not an absorbing outlet without registered native solver evidence",
        "cases": cases,
        "elapsed_seconds": time.perf_counter() - started,
    }
    atomic_json(P1_REPORT, payload)
    return payload


def _run_csv_summary(attempt: Path | None) -> dict[str, Any]:
    if attempt is None or not (attempt / "Run.csv").is_file():
        return {}
    lines = (attempt / "Run.csv").read_text(errors="replace").splitlines()
    if len(lines) < 2:
        return {}
    header = lines[0].lstrip("#")
    row = next(csv.DictReader([header, lines[1]], delimiter=";"), {})
    row = _normalise_csv_row(row)
    fields = (
        "Np", "TSimul", "TSeg", "TTotal", "Steps", "PhysicalTime", "PartFiles", "PartsOut",
        "MaxParticles", "MaxCells", "Nbound", "Nfixed", "Dp", "H", "PartsOutRho", "PartsOutVel",
        "VA-Init", "NL-Limits", "NL-PreSort", "NL-RadixSort", "NL-CellBegin", "NL-SortData",
        "NL-OutCheck", "CF-PreForces", "CF-PreMDBC", "CF-Forces", "SU-Shifting", "SU-ComputeStep",
        "SU-Floating", "SU-Motion", "SU-ResizeNp", "SU-DownData", "SU-SavePart", "SU-Chrono",
        "SU-Moorings", "SU-InOut", "SU-Gauges", "SU-FlexStruc",
    )
    return {field: _float(row.get(field)) for field in fields if row.get(field) not in (None, "")}


def _mass_summary(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"status": "missing_hdf5"}
    with h5py.File(path, "r") as h5:
        initial_valid = np.asarray(h5["valid"][0], dtype=bool)
        final_valid = np.asarray(h5["valid"][-1], dtype=bool)
        mass = np.asarray(h5["mass"], dtype=np.float64)
        initial = float(np.nansum(mass[0, initial_valid]))
        final = float(np.nansum(mass[-1, final_valid]))
        return {
            "initial_mass_kg": initial,
            "final_mass_kg": final,
            "mass_loss_kg": initial - final,
            "initial_particles": int(initial_valid.sum()),
            "final_particles": int(final_valid.sum()),
            "loss_count": int((initial_valid & ~final_valid).sum()),
        }


def _profile_case(record: dict[str, Any], audits: dict[str, dict[str, Any]], forensic: dict[str, dict[str, Any]], prepared: dict[str, dict[str, Any]], normalization: dict[str, dict[str, Any]]) -> dict[str, Any]:
    case_id = record["case_id"]
    is_new = case_id.startswith("R6_N3_")
    attempt = _latest_attempt(record) if is_new else r6._latest_attempt(record)
    latest = RUN_ROOT / case_id / "latest.json" if is_new else r6.RUN_ROOT / case_id / "latest.json"
    latest_payload = json.loads(latest.read_text()) if latest.is_file() else {}
    audit = audits.get(case_id, {})
    native = forensic.get(case_id, {})
    pair = None
    if is_new:
        old_id = f"R6_F1_plain_dam_break_{record['height_label']}_fine"
        old_audit = audits.get(old_id)
        if old_audit:
            pair = r6._pair_comparison(old_audit, audit)
    reasons = native.get("partout_reason_counts", {})
    return {
        "case_id": case_id,
        "height_label": record.get("height_label"),
        "resolution": record.get("resolution"),
        "device_index": latest_payload.get("gpu_index_requested", record.get("gpu")),
        "gpu_uuid": (latest_payload.get("gpu_at_launch") or {}).get("uuid"),
        "attempt_id": latest_payload.get("attempt_id"),
        "attempt_sha256": sha256(attempt / "attempt.json") if attempt and (attempt / "attempt.json").is_file() else None,
        "input_record_hash": latest_payload.get("record_hash") or record.get("r6_n3_record_hash"),
        "mass": _mass_summary(_case_h5(record)),
        "loss_reasons": reasons,
        "t1_metrics": {
            "status": "diagnostic_only_pair_to_previous_same_height_fine" if pair else "not_available",
            "max_distribution_tv": (pair or {}).get("maxima", {}).get("distribution_tv"),
            "max_com_l2_m": (pair or {}).get("maxima", {}).get("com_l2_m"),
            "max_front_q90_abs_delta_m": (pair or {}).get("maxima", {}).get("front_q90_abs_delta_m"),
            "extrema_time_grid_count": (pair or {}).get("time_grid_count"),
            "pair_status": (pair or {}).get("status"),
            "qualification": "not_qualified_by_two_case_repair_probe",
        },
        "t2_qualification": "candidate_t2_numerical_reference_only_separate_h10_material_task",
        "phase_seconds": {
            "gencase": (prepared.get(case_id) or {}).get("gencase", {}).get("elapsed_seconds"),
            "solver_wall": latest_payload.get("elapsed_seconds"),
            "normalize": (normalization.get(case_id) or {}).get("elapsed_seconds"),
            "audit": audit.get("audit_elapsed_seconds"),
            "unknown_phase_policy": "null means not captured in the prior R6 run, not zero",
        },
        "run_csv": _run_csv_summary(attempt),
        "status": audit.get("r6_full_time_audit_status", "not_audited"),
    }


def build_profile() -> dict[str, Any]:
    current_report = r6.load_report()
    current_audits = {item["case_id"]: item for item in current_report.get("audits", []) if item.get("case_id")}
    new_report = _load_report()
    new_audits = {item["case_id"]: item for item in new_report.get("audits", []) if item.get("case_id")}
    audits = {**current_audits, **new_audits}
    forensic_payload = json.loads(P1_REPORT.read_text()) if P1_REPORT.is_file() else build_forensics()
    forensic = {item["case_id"]: item for item in forensic_payload.get("cases", [])}
    prepared = {item["case_id"]: item for item in new_report.get("prepared_cases", [])}
    normalization = {item["case_id"]: item for item in new_report.get("normalization", [])}
    all_records = [*r6.records(), *records()]
    rows = [_profile_case(record, audits, forensic, prepared, normalization) for record in all_records]
    bridge_path = CAMPAIGN / "r6-n3-bridge-h10.json"
    bridge_report = {}
    if bridge_path.is_file():
        try:
            bridge_report = json.loads(bridge_path.read_text())
        except json.JSONDecodeError:
            bridge_report = {}
    # The bridge is a separate bounded phase, but its three rows belong in
    # the single compact P0 table so every new solver case has one auditable
    # device/hash/mass/phase record.
    rows.extend(bridge_report.get("profile_rows", []))
    payload = {
        "schema_version": "r6-n3-p0-profile-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "execution_status": "completed",
        "row_contract": "one compact row per case; null phase is explicitly uncaptured rather than zero",
        "source_reports": {
            "r6_n2": relpath(r6.REPORT),
            "r6_n3": relpath(REPORT),
            "r6_n3_bridge": relpath(bridge_path),
            "p1_forensics": relpath(P1_REPORT),
        },
        "rows": rows,
        "bytes": None,
    }
    atomic_json(P0_REPORT, payload)
    payload["bytes"] = P0_REPORT.stat().st_size
    atomic_json(P0_REPORT, payload)
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run", "normalize", "audit", "forensics", "profile"), nargs="?", default="profile")
    parser.add_argument("--rerun", action="store_true")
    args = parser.parse_args(argv)
    if args.action == "prepare":
        prepare()
    elif args.action == "run":
        prepared = _load_report().get("prepared_cases") or prepare()
        run_solver(prepared, rerun=args.rerun)
    elif args.action == "normalize":
        prepared = _load_report().get("prepared_cases") or prepare()
        normalize(prepared)
    elif args.action == "audit":
        prepared = _load_report().get("prepared_cases") or prepare()
        audit_new(prepared)
    elif args.action == "forensics":
        build_forensics()
    elif args.action == "profile":
        build_forensics()
        build_profile()
    report = _load_report()
    print(json.dumps({
        "execution_status": report.get("execution_status"),
        "preparation_status": report.get("preparation_status"),
        "normalization_status": report.get("normalization_status"),
        "audit_status": report.get("audit_status"),
        "formal_release": False,
        "development_authorized": False,
        "p0_report": relpath(P0_REPORT) if P0_REPORT.is_file() else None,
        "p1_report": relpath(P1_REPORT) if P1_REPORT.is_file() else None,
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
