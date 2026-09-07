#!/usr/bin/env python3
"""Materialize the independent W08 F2 ``spout`` topology holdout.

The continuous W08 matrix and the existing F1 topology manifest are left
untouched.  This module owns one F2 candidate namespace and records every
stage needed to reproduce the short GenCase -> solver -> PartVTK -> HDF5
structural-evidence path.  The case is deliberately candidate-only: no
external reference, resolution study, or material-tracer claim is implied.
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
except ModuleNotFoundError:  # direct ``python scripts/...`` execution
    from campaign_runner import execute_attempt, require_idle_allowed_gpu
    from r3_g3_coverage_audit import audit_h5
    from trajectory_io import audit_hdf5, convert_streaming
    from w02_semantics import partvtk_csv


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "v0.1-candidate"
BIN = LAB / "vendor" / "official" / "DualSPHysics_v5.4" / "bin" / "linux"
GENCASE = BIN / "GenCase_linux64"
SOLVER = BIN / "DualSPHysics5.4_linux64"
PARTVTK = BIN / "PartVTK_linux64"
INVENTORY = CAMPAIGN / "w00-inventory.json"
SOURCE_TEMPLATE = LAB / "cases" / "F2" / "F2_airborne_slug_centered" / "F2_airborne_slug_centered_Def.xml"
DEFINITION = (
    CAMPAIGN / "cases" / "w08" / "topology" / "F2_spout"
    / "W08_F2_topology_spout_Def.xml"
)
ARTIFACT_ROOT = CAMPAIGN / "artifacts" / "w08-f2-spout"
RUN_ROOT = CAMPAIGN / "runs"
DATA_ROOT = CAMPAIGN / "data" / "w08-f2-spout"
MANIFEST = CAMPAIGN / "cases" / "w08" / "f2-spout-topology-materialization.json"

# Physical index, not CUDA_VISIBLE_DEVICES' remapped local ordinal.  The
# inventory allowlist maps this index to an approved GPU-5 UUID.  Never alter
# this to a physical index in [0, 3].
GPU = 5
FORBIDDEN_GPUS = tuple(range(4))
CASE_ID = "W08_F2_topology_spout_00"


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


def physics() -> dict[str, Any]:
    return {
        "fill_fraction": 0.525,
        "rotation_duration_s": 1.0,
        "final_angle_deg": 115.0,
        "receiver_offset_over_mouth": 0.0,
        "receiver_distance_over_mouth": 1.4,
        "mouth_topology": "spout",
        "geometry_variant": "stepped_converging_spout_y0p10_to_y0p06",
    }


def signature() -> str:
    payload = json.dumps({"family": "F2", "physics": physics()}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def declared_card() -> dict[str, Any]:
    sig = signature()
    return {
        "card_id": "W08_F2_topology_spout_00",
        "family": "F2",
        "study_id": "W08_F2_topology_holdout",
        "paired_background_id": "background_F2_topology_holdout_spout_v1",
        "physical_case_id": f"physical_W08_F2_topology_spout_{sig}",
        "lineage_group_id": f"lineage_W08_F2_topology_spout_{sig}",
        "split": "topology_extrapolation",
        "physics": physics(),
        "normalized_intervention": {"mouth_topology": "spout"},
        "simulation_signature": sig,
        "execution_unit_id": f"sim_W08_F2_topology_spout_{sig}",
        "execution_status": "planned_not_run",
        "formal_production_authorized": False,
        "materialization_case_id": CASE_ID,
        "definition": rel(DEFINITION),
        "provenance_status": "declared_independent_geometry",
    }


def allowlist_snapshot() -> dict[str, Any]:
    policy = inventory()["execution_policy"]
    host_by_index = {item["physical_index"]: item for item in inventory()["host"]["gpus"]}
    if GPU in FORBIDDEN_GPUS:
        raise RuntimeError(f"refusing forbidden physical GPU {GPU}")
    requested = host_by_index.get(GPU)
    if requested is None:
        raise RuntimeError(f"physical GPU {GPU} is not present in inventory")
    if requested["uuid"] not in set(policy["allowed_gpu_uuids"]):
        raise RuntimeError(f"physical GPU {GPU} UUID is absent from inventory allowlist")
    allowlisted_indices = sorted(
        item["physical_index"] for item in inventory()["host"]["gpus"]
        if item["uuid"] in set(policy["allowed_gpu_uuids"])
    )
    if any(index in FORBIDDEN_GPUS for index in allowlisted_indices):
        raise RuntimeError(f"inventory allowlist unexpectedly includes forbidden index: {allowlisted_indices}")
    return {
        "requested_physical_index": GPU,
        "requested_uuid": requested["uuid"],
        "requested_uuid_in_allowlist": True,
        "allowlisted_physical_indices": allowlisted_indices,
        "forbidden_physical_indices": list(FORBIDDEN_GPUS),
        "allowlist_source": rel(INVENTORY),
        "single_heavy_job_per_gpu": bool(policy["single_heavy_job_per_gpu"]),
        "recheck_before_run": bool(policy["recheck_before_each_batch"]),
    }


def base_record() -> dict[str, Any]:
    if not DEFINITION.is_file():
        raise FileNotFoundError(DEFINITION)
    if not SOURCE_TEMPLATE.is_file():
        raise FileNotFoundError(SOURCE_TEMPLATE)
    card = declared_card()
    return {
        **card,
        "case_id": CASE_ID,
        "mechanism": "stepped-converging-spout-transfer-catch-spill-proxy",
        "source_template_definition": rel(SOURCE_TEMPLATE),
        "source_template_sha256": sha256(SOURCE_TEMPLATE),
        "definition_sha256": sha256(DEFINITION),
        "particle_spacing_m": 0.04,
        "time_max_s": 0.65,
        "time_out_s": 0.05,
        "gpu_requested_physical_index": GPU,
        "formal_production_authorized": False,
        "release_status": "candidate",
        "physical_acceptance": "rejected_pending_resolution_and_external_reference",
        "reference_acceptance": "rejected_no_external_anchor",
        "provenance": {
            "definition_is_new_file": True,
            "reuses_registry_case": False,
            "registry_case_id_not_reused": "F2_airborne_slug_centered",
            "geometry_change": (
                "replaces the straight F2 downstream transverse receiver wall with "
                "four connected stepped side-rail sections converging from a 0.20 m "
                "entrance to a 0.06 m outlet throat"
            ),
            "upstream_source_modified": False,
            "binary_source": "W00 allowlisted official DualSPHysics 5.4.355 package",
            "physics_scope_note": (
                "F2 remains the repository's airborne-slug transfer/catch/spill proxy; "
                "this topology holdout is not a real rotating cup or an external validation case"
            ),
        },
        "gpu_policy": allowlist_snapshot(),
    }


def read_manifest() -> dict[str, Any]:
    if MANIFEST.is_file():
        return json.loads(MANIFEST.read_text())
    return {
        "schema_version": 1,
        "scope": "independent W08 F2 spout topology-extrapolation materialization; candidate-only evidence",
        "formal_release": False,
        "split": "topology_extrapolation",
        "design_reference": "campaigns/v0.1-candidate/cases/w08/controlled-generalization-design.json",
        "inventory": rel(INVENTORY),
        "gpu_policy": allowlist_snapshot(),
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
                "w08_card_id": CASE_ID,
                "split": record["split"],
                "physical_case_id": record["physical_case_id"],
                "lineage_group_id": record["lineage_group_id"],
                "execution_unit_id": record["execution_unit_id"],
            },
            "executable": {
                "definition": rel(DEFINITION),
                "definition_sha256": sha256(DEFINITION),
                "generated_case_xml": rel(generated_xml) if generated_xml.is_file() else None,
                "generated_case_xml_sha256": sha256(generated_xml) if generated_xml.is_file() else None,
                "generated_boundary_vtk": rel(generated_vtk) if generated_vtk.is_file() else None,
                "generated_boundary_vtk_sha256": sha256(generated_vtk) if generated_vtk.is_file() else None,
                "gencase_command": command,
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
    policy = allowlist_snapshot()
    # This performs the live UUID, memory, and utilization recheck.  The
    # command below uses the same physical index and never a remapped ordinal.
    gpu_at_launch = require_idle_allowed_gpu(
        GPU, inventory()["execution_policy"]["allowed_gpu_uuids"]
    )
    if gpu_at_launch["index"] in FORBIDDEN_GPUS or gpu_at_launch["uuid"] != policy["requested_uuid"]:
        raise RuntimeError(f"live GPU selection violated the physical GPU-5 policy: {gpu_at_launch}")
    result = execute_attempt(
        CASE_ID,
        [str(SOLVER), f"-gpu:{GPU}", str(generated), "{output}"],
        RUN_ROOT,
        cwd=generated.parent,
        env=environment(),
        evidence_glob="data/Part_*.bi4",
        required_text="Finished execution (code=0)",
    )
    record["materialization_status"] = "solver_completed" if result["status"] == "completed" else "solver_failed"
    record["execution_status"] = "completed" if result["status"] == "completed" else "failed"
    attempt = Path(result["attempt_directory"])
    record["stages"]["run"] = {
        "status": result["status"],
        "attempt_id": result["attempt_id"],
        "attempt_directory": rel(attempt),
        "elapsed_seconds": result["elapsed_seconds"],
        "returncode": result["returncode"],
        "evidence_files": result["evidence_files"],
        "gpu_at_launch": gpu_at_launch,
        "gpu_policy_recheck": policy,
        "solver_command": result["command"],
        "process_stdout": rel(attempt / "process.stdout.log"),
        "process_stdout_sha256": sha256(attempt / "process.stdout.log"),
        "run_out": rel(attempt / "Run.out") if (attempt / "Run.out").is_file() else None,
        "run_out_sha256": sha256(attempt / "Run.out") if (attempt / "Run.out").is_file() else None,
    }
    update_record(record)
    if result["status"] != "completed":
        raise RuntimeError(f"solver failed for {CASE_ID}: {attempt}")
    return record


def normalize() -> dict[str, Any]:
    record = current_record()
    attempt = latest_attempt()
    csv_dir = attempt / "csv"
    csvs = partvtk_csv(attempt / "data", csv_dir, "-all,+fluid")
    output = DATA_ROOT / f"{CASE_ID}.h5"
    normalized_record = {
        "id": CASE_ID,
        "family": "F2",
        "mechanism": "stepped-converging-spout-transfer-catch-spill-proxy",
        "shifting": 0,
    }
    convert_streaming(normalized_record, csvs, output)
    # Scientific fields come from the immutable solver/PartVTK stream.  Only
    # explicit lineage and candidate-status attributes are added here.
    with h5py.File(output, "r+") as h5:
        h5.attrs.update({
            "physical_case_id": record["physical_case_id"],
            "lineage_group_id": record["lineage_group_id"],
            "execution_unit_id": record["execution_unit_id"],
            "split": record["split"],
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
        {"id": CASE_ID, "family": "F2", "mechanism": "stepped-converging-spout-transfer-catch-spill-proxy"},
        output, RUN_ROOT, LAB,
    )
    if run_out.is_file():
        match = re.search(r"Excluded particles\.\.\.:\s*([0-9,]+)", run_out.read_text(errors="replace"))
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
            "F2 spout geometry is executable and structurally audited, but this is "
            "one coarse proxy run with no external reference or resolution study"
        ),
    }
    update_record(record)
    return record


def all_stages() -> dict[str, Any]:
    prepare()
    run_solver()
    normalize()
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
