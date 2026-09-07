#!/usr/bin/env python3
"""Materialize and probe the W08 F6 ``twin_free`` topology holdout.

This is deliberately a small, independent execution unit.  It records only
GenCase and a micro-horizon solver initialization; no normalized release HDF5
or physical acceptance is produced.  All solver launches are guarded by the
W00 UUID allowlist and the physical index is fixed to GPU 7 by default.
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
import xml.etree.ElementTree as ET
from typing import Any

try:
    from scripts.campaign_runner import execute_attempt, require_idle_allowed_gpu
except ModuleNotFoundError:  # direct ``python scripts/...`` execution
    from campaign_runner import execute_attempt, require_idle_allowed_gpu


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "v0.1-candidate"
BIN = LAB / "vendor" / "official" / "DualSPHysics_v5.4" / "bin" / "linux"
GENCASE = BIN / "GenCase_linux64"
SOLVER = BIN / "DualSPHysics5.4_linux64"
DEFINITION = (
    CAMPAIGN / "cases" / "w08" / "topology" / "F6_twin_free"
    / "W08_F6_topology_twin_free_Def.xml"
)
INVENTORY = CAMPAIGN / "w00-inventory.json"
ARTIFACT_ROOT = CAMPAIGN / "artifacts" / "w08-f6-twin-free"
RUN_ROOT = CAMPAIGN / "runs"
CASE_ID = "W08_F6_topology_twin_free_00"
MANIFEST = CAMPAIGN / "cases" / "w08" / "f6-twin-free-topology-probe.json"
GPU = 7


def rel(path: Path | str | None) -> str | None:
    if path is None:
        return None
    candidate = Path(path)
    try:
        return str(candidate.resolve().relative_to(LAB))
    except ValueError:
        return str(candidate)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def binary_record(path: Path) -> dict[str, Any]:
    return {"path": rel(path), "bytes": path.stat().st_size, "sha256": sha256(path)}


def environment() -> dict[str, str]:
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = f"{BIN}:{env.get('LD_LIBRARY_PATH', '')}"
    return env


def inventory() -> dict[str, Any]:
    return json.loads(INVENTORY.read_text())


def base_record() -> dict[str, Any]:
    physics = {
        "body_configuration": "twin_free",
        "body_density_ratio": [0.70, 0.70],
        "entry_froude": 0.0,
        "body_aspect_ratio": 1.125,
        "initial_pitch_deg": 0.0,
        "topology_variant": "two_staggered_free_boxes",
    }
    signature = hashlib.sha256(
        json.dumps({"family": "F6", "physics": physics}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]
    return {
        "schema_version": 1,
        "case_id": CASE_ID,
        "card_id": "W08_F6_topology_twin_free_00",
        "family": "F6",
        "study_id": "W08_F6_topology_holdout",
        "paired_background_id": "background_F6_topology_holdout_twin_free_v1",
        "physical_case_id": f"physical_W08_F6_topology_twin_free_{signature}",
        "lineage_group_id": f"lineage_W08_F6_topology_twin_free_{signature}",
        "execution_unit_id": f"sim_W08_F6_topology_twin_free_{signature}",
        "split": "topology_extrapolation",
        "physics": physics,
        "normalized_intervention": {"body_configuration": "twin_free"},
        "simulation_signature": signature,
        "definition": rel(DEFINITION),
        "source_template_definition": "cases/F6/F6_twin_floaters/F6_twin_floaters_Def.xml",
        "source_template_sha256": sha256(LAB / "cases/F6/F6_twin_floaters/F6_twin_floaters_Def.xml"),
        "particle_spacing_m": 0.04,
        "time_max_s": 0.02,
        "time_out_s": 0.01,
        "gpu_requested_physical_index": GPU,
        "release_status": "candidate",
        "formal_production_authorized": False,
        "physical_acceptance": "rejected_pending_resolution_and_external_reference",
        "reference_acceptance": "rejected_no_external_anchor",
        "canonical_stage_eligibility": {
            "g3_canonical_counted": False,
            "reason": (
                "micro-horizon initialization probe intentionally omits PartVTK/HDF5 "
                "normalization and is not a canonical release materialization"
            ),
        },
        "provenance": {
            "definition_is_new_file": True,
            "reuses_registry_case": False,
            "registry_case_id_not_reused": "F6_twin_floaters",
            "upstream_source_modified": False,
            "geometry_change": (
                "two 0.18 x 0.14 x 0.16 m boxes at (0.26,0.08,0.27) and "
                "(0.78,0.20,0.27) m, both marked as free bodies"
            ),
            "binary_source": "W00 allowlisted official DualSPHysics 5.4 package",
        },
        "stages": {},
        "acceptance": {
            "status": "candidate",
            "physical": "rejected",
            "reference": "rejected",
            "reason": "micro-horizon topology probe only; no resolution study or external reference",
        },
    }


def read_manifest() -> dict[str, Any]:
    if MANIFEST.is_file():
        payload = json.loads(MANIFEST.read_text())
        policy = inventory()["execution_policy"]
        payload.setdefault("allowlisted_physical_gpu_indices", [4, 5, 6, 7])
        payload.setdefault("forbidden_physical_gpu_indices", [0, 1, 2, 3])
        payload.setdefault("allowlisted_gpu_uuids", list(policy["allowed_gpu_uuids"]))
        payload.setdefault("inventory_captured_at_utc", inventory().get("captured_at_utc"))
        payload.setdefault("single_heavy_job_per_gpu", bool(policy["single_heavy_job_per_gpu"]))
        payload.setdefault("recheck_before_each_batch", bool(policy["recheck_before_each_batch"]))
        return payload
    policy = inventory()["execution_policy"]
    return {
        "schema_version": 1,
        "scope": "W08 F6 twin_free topology_extrapolation; independent candidate-only probe",
        "formal_release": False,
        "split": "topology_extrapolation",
        "inventory": rel(INVENTORY),
        "allowlisted_physical_gpu_indices": [4, 5, 6, 7],
        "forbidden_physical_gpu_indices": [0, 1, 2, 3],
        "allowlisted_gpu_uuids": list(policy["allowed_gpu_uuids"]),
        "inventory_captured_at_utc": inventory().get("captured_at_utc"),
        "single_heavy_job_per_gpu": bool(policy["single_heavy_job_per_gpu"]),
        "recheck_before_each_batch": bool(policy["recheck_before_each_batch"]),
        "binary_provenance": {
            "GenCase_linux64": binary_record(GENCASE),
            "DualSPHysics5.4_linux64": binary_record(SOLVER),
        },
        "materializations": [],
    }


def write_manifest(payload: dict[str, Any]) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    temporary = MANIFEST.with_suffix(MANIFEST.suffix + ".partial")
    temporary.write_text(json.dumps(payload, indent=2) + "\n")
    os.replace(temporary, MANIFEST)


def current_record() -> dict[str, Any]:
    payload = read_manifest()
    for item in payload.get("materializations", []):
        if item.get("case_id") == CASE_ID:
            return item
    return base_record()


def update_record(record: dict[str, Any]) -> None:
    payload = read_manifest()
    records = [item for item in payload.get("materializations", []) if item.get("case_id") != CASE_ID]
    records.append(record)
    payload["materializations"] = records
    payload["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    write_manifest(payload)


def prepare() -> dict[str, Any]:
    record = base_record()
    if not DEFINITION.is_file():
        raise FileNotFoundError(DEFINITION)
    generated_dir = ARTIFACT_ROOT / CASE_ID / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    prefix = generated_dir / CASE_ID
    command = [str(GENCASE), str(DEFINITION.with_suffix("")), str(prefix), "-save:all"]
    process = subprocess.run(
        command,
        cwd=DEFINITION.parent,
        env=environment(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    log = generated_dir / "gencase.stdout.log"
    log.write_text(process.stdout)
    generated_xml = prefix.with_suffix(".xml")
    generated_vtk = prefix.with_name(prefix.name + "_MkCells.vtk")
    floating_match = re.search(r"Floating\.:\s*([0-9,]+)", process.stdout)
    fluid_match = re.search(r"Fluid\.{4,}:\s*([0-9,]+)", process.stdout)
    total_match = re.search(r"Total particles:\s*([0-9,]+)", process.stdout)
    record["definition_sha256"] = sha256(DEFINITION)
    record["materialization_status"] = (
        "gencase_completed" if process.returncode == 0 and generated_xml.is_file() else "gencase_failed"
    )
    record["stages"]["gencase"] = {
        "definition": rel(DEFINITION),
        "definition_sha256": sha256(DEFINITION),
        "generated_case_xml": rel(generated_xml) if generated_xml.is_file() else None,
        "generated_case_xml_sha256": sha256(generated_xml) if generated_xml.is_file() else None,
        "generated_boundary_vtk": rel(generated_vtk) if generated_vtk.is_file() else None,
        "generated_boundary_vtk_sha256": sha256(generated_vtk) if generated_vtk.is_file() else None,
        "gencase_command": command,
        "gencase_returncode": process.returncode,
        "floating_particles": int(floating_match.group(1).replace(",", "")) if floating_match else None,
        "fluid_particles": int(fluid_match.group(1).replace(",", "")) if fluid_match else None,
        "total_particles": int(total_match.group(1).replace(",", "")) if total_match else None,
        "log": rel(log),
        "log_sha256": sha256(log),
    }
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
    if not generated.with_suffix(".xml").is_file():
        raise FileNotFoundError(generated.with_suffix(".xml"))
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
    attempt = Path(result["attempt_directory"])
    process_stdout = attempt / "process.stdout.log"
    run_out = attempt / "Run.out"
    combined = "\n".join(
        path.read_text(errors="replace") for path in (process_stdout, run_out) if path.is_file()
    )
    chrono_error_patterns = [
        r"chrono.{0,80}(error|fail|unable|cannot|not found)",
        r"(error|fail|unable|cannot|not found).{0,80}chrono",
    ]
    chrono_errors = [line for line in combined.splitlines() if any(re.search(pattern, line, re.I) for pattern in chrono_error_patterns)]
    record["materialization_status"] = "solver_completed" if result["status"] == "completed" else "solver_failed"
    record["execution_status"] = "completed" if result["status"] == "completed" else "failed"
    record["stages"]["solver_initialization"] = {
        "status": result["status"],
        "attempt_id": result["attempt_id"],
        "attempt_directory": rel(attempt),
        "elapsed_seconds": result["elapsed_seconds"],
        "returncode": result["returncode"],
        "evidence_files": result["evidence_files"],
        "gpu_at_launch": gpu_at_launch,
        "solver_command": result["command"],
        "required_text_found": result["required_text_found"],
        "process_stdout": rel(process_stdout),
        "process_stdout_sha256": sha256(process_stdout) if process_stdout.is_file() else None,
        "run_out": rel(run_out),
        "run_out_sha256": sha256(run_out) if run_out.is_file() else None,
        "chrono_error_lines": chrono_errors,
        "chrono_status": "error_detected" if chrono_errors else "no_error_detected_in_probe_logs",
    }
    update_record(record)
    return record


def audit() -> dict[str, Any]:
    record = current_record()
    generated_xml = ARTIFACT_ROOT / CASE_ID / "generated" / f"{CASE_ID}.xml"
    structural: dict[str, Any] = {
        "generated_xml_parse": False,
        "floating_body_count": 0,
        "floating_mkbound": [],
        "floating_particles": None,
        "fluid_particles": None,
        "structural_pass": False,
    }
    if generated_xml.is_file():
        root = ET.parse(generated_xml).getroot()
        floating_nodes = root.findall("./casedef/floatings/floating")
        generated_nodes = root.findall("./execution/particles/floating")
        structural.update({
            "generated_xml_parse": True,
            "floating_body_count": len(floating_nodes),
            "floating_mkbound": [node.attrib.get("mkbound") for node in floating_nodes],
            "generated_particle_floating_blocks": len(generated_nodes),
            "floating_particles": sum(int(node.attrib.get("count", "0")) for node in generated_nodes),
            "fluid_particles": sum(
                int(node.attrib.get("count", "0"))
                for node in root.findall("./execution/particles/fluid")
            ),
        })
        structural["structural_pass"] = (
            structural["floating_body_count"] == 2
            and structural["generated_particle_floating_blocks"] == 2
            and structural["floating_particles"] > 0
            and structural["fluid_particles"] > 0
        )
    record["stages"]["structural_audit"] = structural
    record["materialization_status"] = "candidate_structural_pass" if structural["structural_pass"] else "candidate_structural_failed"
    record["execution_status"] = "completed" if structural["structural_pass"] else "failed"
    record["acceptance"] = {
        "status": "candidate",
        "physical": "rejected",
        "reference": "rejected",
        "reason": (
            "two-body free-rigid-body structure and micro-horizon initialization are recorded; "
            "no resolution envelope, coupled-body learning contract, or external reference"
        ),
    }
    update_record(record)
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "run", "audit", "all"), default="all", nargs="?")
    args = parser.parse_args()
    if args.action == "prepare":
        prepare()
    elif args.action == "run":
        run_solver()
    elif args.action == "audit":
        audit()
    else:
        prepare()
        run_solver()
        audit()
    print(json.dumps(current_record(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
