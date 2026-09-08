#!/usr/bin/env python3
"""Three-case h10 bridge for the R6-N3 CFL recipe.

The endpoint probe showed that CFL 0.1 removes the fine-grid density
exclusions.  This bounded bridge applies exactly that one-factor change to
the h10 coarse/medium/fine triplet so the repaired fine result is not silently
mixed with the old-CFL resolution products.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
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
    from scripts import r6_n3_followup as n3
    from scripts.boundary_sidecars import read_binary_vtk_polydata, write_sidecar
    from scripts.campaign_runner import execute_attempt, query_gpus, require_idle_allowed_gpu
    from scripts.r5_f1_solver_gate import WALL_SPECS
    from scripts.trajectory_io import convert_streaming
    from scripts.w02_semantics import partvtk_csv
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import r6_n2_campaign as r6
    import r6_n3_followup as n3
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
CASE_ROOT = CAMPAIGN / "cases" / "r6-n3-bridge-h10"
ARTIFACT_ROOT = CAMPAIGN / "artifacts" / "r6-n3-bridge-h10"
RUN_ROOT = CAMPAIGN / "runs" / "r6-n3-bridge-h10"
DATA_ROOT = CAMPAIGN / "data" / "r6-n3-bridge-h10"
SIDECAR_ROOT = CAMPAIGN / "sidecars" / "r6-n3-bridge-h10"
REPORT = CAMPAIGN / "r6-n3-bridge-h10.json"
GPU_IDS = (4, 5, 6)
PROTECTED_GPU_IDS = (0, 1, 2, 3)
LEVELS = ("coarse", "medium", "fine")
DP_M = r6.RESOLUTIONS_M
CFL_NUMBER = 0.1
HEIGHT_M = r6.HEIGHTS_M["h10"]


def relpath(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(LAB.resolve()))
    except ValueError:
        return str(Path(path).resolve())


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


def records() -> list[dict[str, Any]]:
    result = []
    for index, level in enumerate(LEVELS):
        case_id = f"R6_N3_F1_plain_dam_break_h10_{level}_cfl010"
        result.append({
            "id": case_id,
            "case_id": case_id,
            "family": "F1",
            "background_id": "plain_dam_break",
            "mechanism": "collapse-runup-return",
            "height_label": "h10",
            "height_m": HEIGHT_M,
            "continuous_initial_fluid_z_bounds_m": list(r6.SOURCE_Z_BOUNDS_BY_HEIGHT["h10"]),
            "resolution": level,
            "dp_m": DP_M[level],
            "cfl_number": CFL_NUMBER,
            "time_max_s": r6.TIME_MAX_S,
            "time_out_s": r6.TIME_OUT_S,
            "source_definition": str(n3.SOURCE_DEFINITION),
            "gpu": GPU_IDS[index],
            "registered_absorbing_exit_faces": [],
            "wall_spec": WALL_SPECS["plain_dam_break"],
        })
    return result


def record_hash(record: dict[str, Any]) -> str:
    stable = {key: value for key, value in record.items() if key not in {"candidate_definition", "generated_prefix"}}
    stable["source_definition_sha256"] = sha256(n3.SOURCE_DEFINITION)
    return hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_report() -> dict[str, Any]:
    if REPORT.is_file():
        try:
            return json.loads(REPORT.read_text())
        except json.JSONDecodeError:
            pass
    return {
        "schema_version": "r6-n3-bridge-h10-v1",
        "round": "R6-N3",
        "execution_status": "not_started",
        "formal_release": False,
        "development_authorized": False,
        "protected_gpu_indices": list(PROTECTED_GPU_IDS),
        "allowed_gpu_indices": list(GPU_IDS),
        "bridge_case_limit": 3,
    }


def prepare_one(record: dict[str, Any]) -> dict[str, Any]:
    case_id = record["case_id"]
    case_dir = CASE_ROOT / case_id
    generated_dir = ARTIFACT_ROOT / case_id / "generated"
    case_dir.mkdir(parents=True, exist_ok=True)
    generated_dir.mkdir(parents=True, exist_ok=True)
    candidate = case_dir / f"{case_id}_Def.xml"
    tree = ET.parse(n3.SOURCE_DEFINITION)
    root = tree.getroot()
    definition = root.find(".//geometry/definition")
    if definition is None:
        raise ValueError("plain source has no geometry definition")
    definition.set("dp", str(record["dp_m"]))
    n3._fluid_drawbox(root).find("./size").set("z", str(record["height_m"]))
    cfl = root.find(".//constantsdef/cflnumber")
    if cfl is None:
        raise ValueError("plain source has no cflnumber")
    cfl.set("value", str(record["cfl_number"]))
    for key, value in (("SavePosDouble", 2), ("StepAlgorithm", 1), ("VerletSteps", 40),
                       ("Boundary", 1), ("Shifting", 0), ("TimeMax", r6.TIME_MAX_S),
                       ("TimeOut", r6.TIME_OUT_S)):
        n3._set_parameter(root, key, value)
    ET.indent(tree, space="    ")
    tree.write(candidate, encoding="utf-8", xml_declaration=True)
    prefix = generated_dir / case_id
    started = time.perf_counter()
    process = subprocess.run(
        [str(GENCASE), str(candidate.with_suffix("")), str(prefix), "-save:all"],
        cwd=generated_dir, env=n3._environment(cpu=True), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )
    elapsed = time.perf_counter() - started
    stdout_path = generated_dir / "gencase.stdout.log"
    stdout_path.write_text(process.stdout)
    if process.returncode != 0 or not prefix.with_suffix(".xml").is_file() or not prefix.with_suffix(".bi4").is_file():
        raise RuntimeError(f"GenCase failed for {case_id}: {process.stdout[-1500:]}")
    match = re.search(r"Fluid\.{3,}:\s*([0-9,]+)", process.stdout)
    return {
        **record,
        "candidate_definition": relpath(candidate),
        "candidate_definition_sha256": sha256(candidate),
        "generated_prefix": relpath(prefix),
        "generated_xml_sha256": sha256(prefix.with_suffix(".xml")),
        "gencase": {
            "returncode": process.returncode,
            "fluid_particles": int(match.group(1).replace(",", "")) if match else None,
            "elapsed_seconds": elapsed,
            "stdout": relpath(stdout_path),
        },
    }


def prepare() -> list[dict[str, Any]]:
    prepared = [prepare_one(item) for item in records()]
    report = load_report()
    report.update({"prepared_cases": prepared, "preparation_status": "completed", "execution_status": "prepared_only"})
    atomic_json(REPORT, report)
    return prepared


def latest_attempt(record: dict[str, Any]) -> Path | None:
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
    gpu_record = require_idle_allowed_gpu(gpu, n3._allowed_uuids())
    prefix = Path(record["generated_prefix"])
    prefix = prefix if prefix.is_absolute() else LAB / prefix
    result = execute_attempt(
        record["case_id"], [str(SOLVER), f"-gpu:{gpu}", str(prefix), "{output}"], RUN_ROOT,
        cwd=prefix.parent, env=n3._environment(), evidence_glob="data/Part_*.bi4",
        required_text="Finished execution (code=0)",
    )
    payload = {
        **result,
        "record_hash": expected_hash,
        "execution_status": "completed" if result.get("status") == "completed" else "solver_failed",
        "gpu_at_launch": gpu_record,
        "gpu_index_requested": gpu,
        "protected_gpu_indices": list(PROTECTED_GPU_IDS),
        "input_generated_xml_sha256": sha256(prefix.with_suffix(".xml")),
        "input_generated_bi4_sha256": sha256(prefix.with_suffix(".bi4")),
    }
    atomic_json(RUN_ROOT / record["case_id"] / "latest.json", payload)
    return payload


def run_solver(prepared: Sequence[dict[str, Any]], *, rerun: bool = False) -> list[dict[str, Any]]:
    prepared = list(prepared)
    if len(prepared) > 3:
        raise ValueError("h10 bridge is limited to three cases")
    with ThreadPoolExecutor(max_workers=len(prepared) or 1) as pool:
        results = list(pool.map(lambda item: run_one(item, rerun=rerun), prepared))
    report = load_report()
    report.update({
        "solver_runs": results,
        "execution_status": "completed" if all(item.get("execution_status") in {"completed", "reused_completed"} for item in results) else "partial_with_findings",
        "resource_snapshot_after_solver": query_gpus(),
    })
    atomic_json(REPORT, report)
    return results


def normalize_one(record: dict[str, Any]) -> dict[str, Any]:
    attempt = latest_attempt(record)
    if attempt is None:
        return {"case_id": record["case_id"], "normalization_status": "blocked_missing_attempt"}
    output = DATA_ROOT / f"{record['case_id']}.h5"
    started = time.perf_counter()
    try:
        complete = False
        if output.is_file():
            with h5py.File(output, "r") as h5:
                complete = bool(h5.attrs.get("conversion_complete", True))
        if not complete:
            csv_paths = partvtk_csv(attempt / "data", attempt / "csv", "-all,+fluid")
            convert_streaming(
                {"id": record["case_id"], "family": "F1", "mechanism": record["mechanism"], "shifting": 0},
                csv_paths, output,
            )
        with h5py.File(output, "r+") as h5:
            h5.attrs["continuous_initial_fluid_z_bounds_m"] = np.asarray(record["continuous_initial_fluid_z_bounds_m"], dtype=np.float64)
            h5.attrs["r6_n3_cfl_number"] = float(record["cfl_number"])
            h5.attrs["r6_n3_record_hash"] = record_hash(record)
            h5.attrs["source_definition_sha256"] = sha256(n3.SOURCE_DEFINITION)
        prefix = Path(record["generated_prefix"])
        prefix = prefix if prefix.is_absolute() else LAB / prefix
        vtk = prefix.with_name(prefix.name + "_MkCells.vtk")
        sidecar = SIDECAR_ROOT / f"{record['case_id']}.h5"
        summary = write_sidecar(sidecar, record["case_id"], output, read_binary_vtk_polydata(vtk),
                                source_vtk_label=relpath(vtk), source_hdf5_label=relpath(output))
        return {
            "case_id": record["case_id"],
            "normalization_status": "completed",
            "elapsed_seconds": time.perf_counter() - started,
            "hdf5": relpath(output),
            "hdf5_sha256": sha256(output),
            "sidecar": relpath(sidecar),
            "sidecar_sha256": sha256(sidecar),
            "sidecar_audit": summary,
        }
    except Exception as error:
        return {"case_id": record["case_id"], "normalization_status": "failed", "elapsed_seconds": time.perf_counter() - started, "error": repr(error)}


def normalize(prepared: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    results = [normalize_one(item) for item in prepared]
    report = load_report()
    report["normalization"] = results
    report["normalization_status"] = "completed" if all(item.get("normalization_status") == "completed" for item in results) else "partial_with_findings"
    atomic_json(REPORT, report)
    return results


def audit(prepared: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for record in prepared:
        path = DATA_ROOT / f"{record['case_id']}.h5"
        attempt = latest_attempt(record)
        started = time.perf_counter()
        if not path.is_file() or attempt is None:
            results.append({"case_id": record["case_id"], "r6_full_time_audit_status": "missing_input", "r6_hard_failures": ["normalized_hdf5_or_attempt_missing"]})
            continue
        try:
            item = r6.full_time_audit(record, path, attempt)
            item["audit_elapsed_seconds"] = time.perf_counter() - started
            results.append(item)
        except Exception as error:
            results.append({"case_id": record["case_id"], "r6_full_time_audit_status": "audit_exception", "r6_hard_failures": [repr(error)]})
    by_level = {item.get("resolution"): item for item in results}
    comparisons = {
        "coarse_to_medium": r6._pair_comparison(by_level["coarse"], by_level["medium"]) if "coarse" in by_level and "medium" in by_level else {"status": "unknown"},
        "medium_to_fine": r6._pair_comparison(by_level["medium"], by_level["fine"]) if "medium" in by_level and "fine" in by_level else {"status": "unknown"},
    }
    report = load_report()
    report.update({
        "audits": results,
        "comparisons": comparisons,
        "audit_status": "completed" if all(item.get("r6_full_time_audit_status") == "pass" for item in results) else "completed_with_findings",
    })
    atomic_json(REPORT, report)
    return results


def profile() -> dict[str, Any]:
    report = load_report()
    prepared = {item["case_id"]: item for item in report.get("prepared_cases", [])}
    audits = {item["case_id"]: item for item in report.get("audits", [])}
    rows = []
    for record in records():
        attempt = latest_attempt(record)
        latest = RUN_ROOT / record["case_id"] / "latest.json"
        latest_payload = json.loads(latest.read_text()) if latest.is_file() else {}
        audit_item = audits.get(record["case_id"], {})
        mass = n3._mass_summary(DATA_ROOT / f"{record['case_id']}.h5")
        rows.append({
            "case_id": record["case_id"],
            "height_label": "h10",
            "resolution": record["resolution"],
            "device_index": latest_payload.get("gpu_index_requested", record["gpu"]),
            "gpu_uuid": (latest_payload.get("gpu_at_launch") or {}).get("uuid"),
            "attempt_id": latest_payload.get("attempt_id"),
            "attempt_sha256": sha256(attempt / "attempt.json") if attempt and (attempt / "attempt.json").is_file() else None,
            "record_hash": latest_payload.get("record_hash"),
            "mass": mass,
            "loss_reasons": audit_item.get("solver_exclusion_evidence", {}).get("reason_counts", {}),
            "t1_qualification": "diagnostic_h10_same_cfl_triplet_only_not_formal_release",
            "t2_qualification": "candidate_t2_numerical_reference_only_separate_h10_material_task",
            "phase_seconds": {
                "gencase": prepared.get(record["case_id"], {}).get("gencase", {}).get("elapsed_seconds"),
                "solver_wall": latest_payload.get("elapsed_seconds"),
                "normalize": next((item.get("elapsed_seconds") for item in report.get("normalization", []) if item.get("case_id") == record["case_id"]), None),
                "audit": audit_item.get("audit_elapsed_seconds"),
            },
            "status": audit_item.get("r6_full_time_audit_status", "not_audited"),
        })
    report["profile_rows"] = rows
    atomic_json(REPORT, report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run", "normalize", "audit", "profile", "all"), default="profile", nargs="?")
    parser.add_argument("--rerun", action="store_true")
    args = parser.parse_args(argv)
    if args.action in {"prepare", "all"}:
        prepared = prepare()
    else:
        prepared = load_report().get("prepared_cases") or prepare()
    if args.action in {"run", "all"}:
        run_solver(prepared, rerun=args.rerun)
    if args.action in {"normalize", "audit", "all"}:
        normalize(prepared)
    if args.action in {"audit", "all"}:
        audit(prepared)
    if args.action == "profile":
        profile()
    report = load_report()
    print(json.dumps({
        "execution_status": report.get("execution_status"),
        "preparation_status": report.get("preparation_status"),
        "normalization_status": report.get("normalization_status"),
        "audit_status": report.get("audit_status"),
        "comparisons": {key: value.get("status") for key, value in report.get("comparisons", {}).items()},
        "formal_release": False,
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
