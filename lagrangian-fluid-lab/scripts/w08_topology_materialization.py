#!/usr/bin/env python3
"""Materialize one explicitly declared W08 topology holdout.

The continuous W08 design remains a 204-card, design-only matrix.  This
module owns the separate topology namespace so an executed holdout cannot be
mistaken for a registry probe or a second split assignment of one of the old
``F1_twin_obstacle`` cases.  All generated/run/data directories are ignored
campaign artefacts; this manifest is the tracked provenance index for them.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any

import h5py

try:
    from scripts.campaign_runner import execute_attempt, require_idle_allowed_gpu
    from scripts.r3_g3_coverage_audit import audit_h5
    from scripts.trajectory_io import audit_hdf5, convert_streaming
    from scripts.w02_semantics import partvtk_csv
    from scripts.w08_generalization_design import topology_holdout_cards
except ModuleNotFoundError:  # direct ``python scripts/...`` execution
    from campaign_runner import execute_attempt, require_idle_allowed_gpu
    from r3_g3_coverage_audit import audit_h5
    from trajectory_io import audit_hdf5, convert_streaming
    from w02_semantics import partvtk_csv
    from w08_generalization_design import topology_holdout_cards


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "v0.1-candidate"
BIN = LAB / "vendor" / "official" / "DualSPHysics_v5.4" / "bin" / "linux"
GENCASE = BIN / "GenCase_linux64"
SOLVER = BIN / "DualSPHysics5.4_linux64"
PARTVTK = BIN / "PartVTK_linux64"
INVENTORY = CAMPAIGN / "w00-inventory.json"
DEFINITION = (
    CAMPAIGN / "cases" / "w08" / "topology" / "F1_twin_obstacle"
    / "W08_F1_topology_twin_obstacle_Def.xml"
)
ARTIFACT_ROOT = CAMPAIGN / "artifacts" / "w08-topology"
RUN_ROOT = CAMPAIGN / "runs"
DATA_ROOT = CAMPAIGN / "data" / "w08-topology"
MANIFEST = CAMPAIGN / "cases" / "w08" / "topology-holdout-materializations.json"
CASE = topology_holdout_cards()[0]
CASE_ID = CASE["materialization_case_id"]
GPU = 4


def rel(path: Path | str | None) -> str | None:
    if path is None:
        return None
    path = Path(path)
    try:
        return str(path.resolve().relative_to(LAB))
    except ValueError:
        return str(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def environment() -> dict[str, str]:
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = f"{BIN}:{env.get('LD_LIBRARY_PATH', '')}"
    return env


def inventory() -> dict[str, Any]:
    return json.loads(INVENTORY.read_text())


def binary_record(path: Path) -> dict[str, Any]:
    return {"path": rel(path), "bytes": path.stat().st_size, "sha256": sha256(path)}


def base_record() -> dict[str, Any]:
    if not DEFINITION.is_file():
        raise FileNotFoundError(DEFINITION)
    return {
        **CASE,
        "case_id": CASE_ID,
        "mechanism": "multi-path-split-remerge",
        "source_template_definition": "cases/F1/F1_twin_obstacle/F1_twin_obstacle_Def.xml",
        "source_template_sha256": sha256(LAB / "cases/F1/F1_twin_obstacle/F1_twin_obstacle_Def.xml"),
        "definition": rel(DEFINITION),
        "definition_sha256": sha256(DEFINITION),
        "particle_spacing_m": 0.04,
        "time_max_s": 0.80,
        "time_out_s": 0.05,
        "gpu_requested_physical_index": GPU,
        "formal_production_authorized": False,
        "release_status": "candidate",
        "physical_acceptance": "rejected_pending_resolution_and_external_reference",
        "reference_acceptance": "rejected_no_external_anchor",
        "provenance": {
            "definition_is_new_file": True,
            "reuses_registry_case": False,
            "registry_case_id_not_reused": "F1_twin_obstacle",
            "geometry_change": (
                "two obstacle boxes moved to x=0.58/0.84 m, y=0.04/0.26 m and "
                "changed to 0.09 x 0.10 x 0.30 m"
            ),
            "upstream_source_modified": False,
            "binary_source": "W00 allowlisted official DualSPHysics 5.4.355 package",
        },
    }


def read_manifest() -> dict[str, Any]:
    if MANIFEST.is_file():
        return json.loads(MANIFEST.read_text())
    return {
        "schema_version": 1,
        "scope": "W08 topology-extrapolation materializations; candidate-only evidence",
        "formal_release": False,
        "split": "topology_extrapolation",
        "inventory": rel(INVENTORY),
        "binary_provenance": {
            "GenCase_linux64": binary_record(GENCASE),
            "DualSPHysics5.4_linux64": binary_record(SOLVER),
            "PartVTK_linux64": binary_record(PARTVTK),
        },
        "materializations": [],
    }


def write_manifest(payload: dict[str, Any]) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    temporary = MANIFEST.with_suffix(MANIFEST.suffix + ".partial")
    temporary.write_text(json.dumps(payload, indent=2) + "\n")
    os.replace(temporary, MANIFEST)


def update_record(record: dict[str, Any]) -> None:
    payload = read_manifest()
    records = [item for item in payload.get("materializations", []) if item.get("case_id") != CASE_ID]
    records.append(record)
    payload["materializations"] = records
    payload["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    write_manifest(payload)


def current_record() -> dict[str, Any]:
    payload = read_manifest()
    for item in payload.get("materializations", []):
        if item.get("case_id") == CASE_ID:
            return item
    return base_record()


def prepare() -> dict[str, Any]:
    record = base_record()
    generated_dir = ARTIFACT_ROOT / CASE_ID / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    prefix = generated_dir / CASE_ID
    command = [str(GENCASE), str(DEFINITION.with_suffix("")), str(prefix), "-save:all"]
    process = subprocess.run(
        command, cwd=DEFINITION.parent, env=environment(), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    log = generated_dir / "gencase.stdout.log"
    log.write_text(process.stdout)
    fluid_match = re.search(r"Fluid\.\.\.\.:\s*([0-9,]+)", process.stdout)
    total_match = re.search(r"Total particles:\s*([0-9,]+)", process.stdout)
    generated_xml = prefix.with_suffix(".xml")
    generated_vtk = prefix.with_name(prefix.name + "_MkCells.vtk")
    record.update({
        "materialization_status": "gencase_completed" if process.returncode == 0 and generated_xml.is_file() else "gencase_failed",
        "stages": {
            "declared": {
                "w08_card_id": CASE["card_id"],
                "split": CASE["split"],
                "physical_case_id": CASE["physical_case_id"],
                "lineage_group_id": CASE["lineage_group_id"],
                "execution_unit_id": CASE["execution_unit_id"],
            },
            "executable": {
                "definition": rel(DEFINITION),
                "definition_sha256": sha256(DEFINITION),
                "generated_case_xml": rel(generated_xml) if generated_xml.is_file() else None,
                "generated_case_xml_sha256": sha256(generated_xml) if generated_xml.is_file() else None,
                "generated_boundary_vtk": rel(generated_vtk) if generated_vtk.is_file() else None,
                "generated_boundary_vtk_sha256": sha256(generated_vtk) if generated_vtk.is_file() else None,
                "gencase_command": [rel(value) if index > 0 and index < 3 else value for index, value in enumerate(command)],
                "gencase_returncode": process.returncode,
                "fluid_particles": int(fluid_match.group(1).replace(",", "")) if fluid_match else None,
                "total_particles": int(total_match.group(1).replace(",", "")) if total_match else None,
                "log": rel(log),
                "log_sha256": sha256(log),
            },
        },
    })
    update_record(record)
    if record["materialization_status"] != "gencase_completed":
        raise RuntimeError(f"GenCase failed for {CASE_ID}; see {log}")
    return record


def latest_attempt() -> Path:
    payload = json.loads((RUN_ROOT / CASE_ID / "latest.json").read_text())
    return Path(payload["attempt_directory"])


def run_solver() -> dict[str, Any]:
    record = current_record()
    generated = ARTIFACT_ROOT / CASE_ID / "generated" / CASE_ID
    gpu_at_launch = require_idle_allowed_gpu(
        GPU, inventory()["execution_policy"]["allowed_gpu_uuids"]
    )
    result = execute_attempt(
        CASE_ID,
        [str(SOLVER), f"-gpu:{GPU}", str(generated), "{output}"],
        RUN_ROOT,
        cwd=generated.parent,
        env=environment(),
        evidence_glob="data/Part_*.bi4",
        required_text="Finished execution (code=0)",
    )
    result["gpu_at_launch"] = gpu_at_launch
    result["solver_binary"] = binary_record(SOLVER)
    record["materialization_status"] = "solver_completed" if result["status"] == "completed" else "solver_failed"
    record["execution_status"] = "completed" if result["status"] == "completed" else "failed"
    record["stages"]["run"] = {
        "status": result["status"],
        "attempt_id": result["attempt_id"],
        "attempt_directory": rel(result["attempt_directory"]),
        "elapsed_seconds": result["elapsed_seconds"],
        "returncode": result["returncode"],
        "evidence_files": result["evidence_files"],
        "gpu_at_launch": gpu_at_launch,
        "solver_command": result["command"],
        "process_stdout": rel(Path(result["attempt_directory"]) / "process.stdout.log"),
        "process_stdout_sha256": sha256(Path(result["attempt_directory"]) / "process.stdout.log"),
        "run_out": rel(Path(result["attempt_directory"]) / "Run.out"),
        "run_out_sha256": sha256(Path(result["attempt_directory"]) / "Run.out")
        if (Path(result["attempt_directory"]) / "Run.out").is_file() else None,
    }
    update_record(record)
    if result["status"] != "completed":
        raise RuntimeError(f"solver failed for {CASE_ID}: {result['attempt_directory']}")
    return record


def normalize() -> dict[str, Any]:
    record = current_record()
    attempt = latest_attempt()
    csv_dir = attempt / "csv"
    csvs = partvtk_csv(attempt / "data", csv_dir, "-all,+fluid")
    output = DATA_ROOT / f"{CASE_ID}.h5"
    normalized_record = {
        "id": CASE_ID,
        "family": "F1",
        "mechanism": "multi-path-split-remerge",
        "shifting": 0,
    }
    convert_streaming(normalized_record, csvs, output)
    # The normalizer stores the scientific fields; add the split/lineage
    # contract metadata after the byte-stream conversion, never by mutating
    # solver output or pretending it is a formal release file.
    with h5py.File(output, "r+") as h5:
        h5.attrs.update({
            "physical_case_id": CASE["physical_case_id"],
            "lineage_group_id": CASE["lineage_group_id"],
            "execution_unit_id": CASE["execution_unit_id"],
            "split": CASE["split"],
            "world_frame": "inertial laboratory frame",
            "time_units": "s",
            "length_units": "m",
            "mass_units": "kg",
            "release_status": "candidate",
            "physical_acceptance": "rejected_pending_resolution_and_external_reference",
            "reference_acceptance": "rejected_no_external_anchor",
            "formal_production_authorized": False,
        })
    partvtk_log = csv_dir / "partvtk.stdout.log"
    record["materialization_status"] = "normalized"
    record["stages"]["normalized_hdf5"] = {
        "hdf5": rel(output),
        "hdf5_bytes": output.stat().st_size,
        "hdf5_sha256": sha256(output),
        "frames": len(csvs),
        "partvtk_binary": binary_record(PARTVTK),
        "partvtk_command_log": rel(partvtk_log),
        "partvtk_command_log_sha256": sha256(partvtk_log) if partvtk_log.is_file() else None,
        "csv_frame_count": len(csvs),
    }
    update_record(record)
    return record


def audit() -> dict[str, Any]:
    record = current_record()
    output = DATA_ROOT / f"{CASE_ID}.h5"
    attempt = latest_attempt()
    run_stage = record.get("stages", {}).get("run", {})
    process_stdout = attempt / "process.stdout.log"
    run_out = attempt / "Run.out"
    run_stage.update({
        "process_stdout": rel(process_stdout),
        "process_stdout_sha256": sha256(process_stdout) if process_stdout.is_file() else None,
        "run_out": rel(run_out),
        "run_out_sha256": sha256(run_out) if run_out.is_file() else None,
    })
    trajectory = audit_hdf5(
        {"id": CASE_ID, "family": "F1", "mechanism": "multi-path-split-remerge"},
        output, RUN_ROOT, LAB,
    )
    if run_out.is_file():
        match = re.search(r"Excluded particles\.+:\s*([0-9,]+)", run_out.read_text(errors="replace"))
        if match:
            trajectory["excluded_particles"] = int(match.group(1).replace(",", ""))
    structural = audit_h5(output)
    physical_acceptance = "rejected_pending_resolution_and_external_reference"
    record["materialization_status"] = "candidate_structural_pass" if structural["structural_pass"] else "candidate_structural_failed"
    record["execution_status"] = "completed" if structural["structural_pass"] else "failed"
    record["stages"]["structural_audit"] = {
        "trajectory_io_audit": trajectory,
        "g3_audit": structural,
        "structural_pass": bool(structural["structural_pass"]),
        "physical_acceptance": physical_acceptance,
        "reference_acceptance": "rejected_no_external_anchor",
        "formal_production_authorized": False,
    }
    record["acceptance"] = {
        "status": "candidate",
        "physical": "rejected",
        "reference": "rejected",
        "reason": (
            "topology geometry is executable and structurally valid, but one coarse "
            "resolution run has no external reference and is not a formal dataset"
        ),
    }
    update_record(record)
    return record


def all_stages() -> dict[str, Any]:
    record = prepare()
    record = run_solver()
    record = normalize()
    return audit()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "run", "normalize", "audit", "all"), default="all", nargs="?")
    args = parser.parse_args()
    if args.action == "prepare":
        prepare()
    elif args.action == "run":
        run_solver()
    elif args.action == "normalize":
        normalize()
    elif args.action == "audit":
        audit()
    else:
        all_stages()
    print(json.dumps(current_record(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
