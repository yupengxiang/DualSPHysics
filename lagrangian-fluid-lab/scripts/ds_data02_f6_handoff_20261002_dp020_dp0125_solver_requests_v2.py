#!/usr/bin/env python3
"""Register additive storage/time-corrected F6 solver requests.

The four ``qualification_requests_002`` files are consumed historical
requests and remain byte-for-byte untouched.  This version uses the actual
phase003 particle counts, the explicit ``Np * 241 * 64`` native-output
budget requested by the campaign owner, and measured DP025 12-second solver
times to produce review-only requests.  It does not launch a solver.
"""

from __future__ import annotations

import importlib.util
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
LAB_ROOT = SCRIPT.parents[1]
FAMILY_ROOT = LAB_ROOT / "campaigns/ds-data-02/families/F6/handoff_20261002"
ROOT = FAMILY_ROOT / "rigid_contract_003/dp020_dp0125_cpu_003"
CURRENT_MANIFEST = ROOT / "manifest.json"
CURRENT_REQUEST_MANIFEST = ROOT / "partvtk_002/qualification_requests_002/qualification_request_manifest_002.json"
CURRENT_AUDIT = ROOT / "partvtk_002/strict_partvtk_rigid_audit_003.json"
DOMAIN_AUDIT = ROOT / "equivalence_domain_audit_001.json"
REQUEST_ROOT = ROOT / "qualification_requests_003"
REQUEST_MANIFEST = REQUEST_ROOT / "qualification_request_manifest_003.json"
INTEGRATION_LAB = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
RUNTIME_V2 = INTEGRATION_LAB / "scripts/ds_data02_runtime_v2.py"
OFFICIAL_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4")
SOLVER = OFFICIAL_ROOT / "bin/linux/DualSPHysics5.4_linux64"
GENCASE = OFFICIAL_ROOT / "bin/linux/GenCase_linux64"
PARTVTK = OFFICIAL_ROOT / "bin/linux/PartVTK_linux64"
FLOATING_INFO = OFFICIAL_ROOT / "bin/linux/FloatingInfo_linux64"
COMPUTE_FORCES = OFFICIAL_ROOT / "bin/linux/ComputeForces_linux64"
DP025_SIMPLE_RECEIPT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F6/"
    "F6_HANDOFF_20261002_SIMPLE_FREE_RESPONSE_COMMENSURATE_RIGID003_DP025/"
    "F6_HANDOFF_20261002_SIMPLE_FREE_RESPONSE_COMMENSURATE_RIGID003_DP025_SOLVER_QUAL_DP025_001/execution-receipt.json"
)
DP025_WAVE_RECEIPT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F6/"
    "F6_HANDOFF_20261002_WAVE_NO_CONTACT_COMMENSURATE_RIGID003_DP025/"
    "F6_HANDOFF_20261002_WAVE_NO_CONTACT_COMMENSURATE_RIGID003_DP025_SOLVER_QUAL_DP025_DOMAIN_X_REPAIR_001/execution-receipt.json"
)
AUDIT_SCRIPT = SCRIPT.with_name("ds_data02_f6_handoff_20261002_dp020_dp0125_equivalence_domain_audit_v1.py")
GENERATOR = SCRIPT.with_name("ds_data02_f6_handoff_20261002_dp020_dp0125_v3.py")

SPEC = importlib.util.spec_from_file_location("f6_finer_domain_audit", AUDIT_SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import audit sidecar: {AUDIT_SCRIPT}")
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def sha256(path: Path) -> str:
    return AUDIT.sha256(path)


def read_json(path: Path) -> dict[str, Any]:
    return AUDIT.read_json(path)


def write_json(path: Path, value: dict[str, Any]) -> None:
    AUDIT.write_json(path, value)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def git_commit() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=LAB_ROOT, check=True, capture_output=True, text=True).stdout.strip()


def existing(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        if str(path) not in seen:
            result.append(path)
            seen.add(str(path))
    return result


def _old_request_for_case(case_id: str) -> dict[str, Any]:
    old_manifest = read_json(CURRENT_REQUEST_MANIFEST)
    for row in old_manifest["requests"]:
        if row["case_id"] == case_id:
            return read_json(Path(row["path"]))
    raise KeyError(case_id)


def _reference_timing(mechanism: str) -> tuple[Path, float]:
    return (DP025_SIMPLE_RECEIPT, 479.0921823529061) if mechanism == "simple_free_response" else (DP025_WAVE_RECEIPT, 586.6077744141221)


def _storage_and_wall(total_particles: int, mechanism: str, resolution: str) -> dict[str, Any]:
    raw = total_particles * 241 * 64
    margin = 0.35
    safety_bytes = 512 * 1024 * 1024
    estimate = math.ceil(raw * (1.0 + margin) + safety_bytes)
    requested = 16 * 1024**3 if resolution == "dp020" and mechanism == "simple_free_response" else 18 * 1024**3 if resolution == "dp020" else 64 * 1024**3 if mechanism == "simple_free_response" else 72 * 1024**3
    reference_receipt, reference_seconds = _reference_timing(mechanism)
    reference_total = 327680
    scaled_seconds = reference_seconds * total_particles / reference_total
    wall = 2400 if resolution == "dp020" and mechanism == "simple_free_response" else 3000 if resolution == "dp020" else 7200 if mechanism == "simple_free_response" else 9600
    return {
        "formula": "total_particles * 241 frames * 64 bytes + 35% margin + 512 MiB safety",
        "raw_particle_frame_bytes": raw,
        "margin_fraction": margin,
        "safety_bytes": safety_bytes,
        "calculated_minimum_bytes": estimate,
        "requested_storage_bytes": requested,
        "requested_storage_gib": requested / 1024**3,
        "reference_receipt": str(reference_receipt.resolve()),
        "reference_receipt_sha256": sha256(reference_receipt),
        "reference_solver_seconds": reference_seconds,
        "reference_particle_count": reference_total,
        "linear_particle_scaled_seconds": scaled_seconds,
        "requested_max_wall_seconds": wall,
        "wall_margin_over_linear_scaling": wall / scaled_seconds,
    }


def request_for_case(case: dict[str, Any], audit_row: dict[str, Any]) -> dict[str, Any]:
    cid = str(case["case_id"])
    old = _old_request_for_case(cid)
    old_inputs = [Path(value) for value in old["input_files"]]
    xml = Path(audit_row["generated_xml_rigid_contract"]["xml"])
    prefix = xml.with_suffix("")
    generated = [prefix.with_suffix(".xml"), prefix.with_suffix(".bi4")] + [prefix.with_name(prefix.name + suffix) for suffix in ("_All.vtk", "_Bound.vtk", "_Fluid.vtk", "_MkCells.vtk", "__Dp.vtk")]
    gen_receipt = Path(audit_row["gencase"]["receipt"])
    partvtk_receipt = Path(audit_row["partvtk"]["receipt"])
    partvtk_csv = Path(audit_row["partvtk"]["csv"])
    source_files = old_inputs + [
        SCRIPT, AUDIT_SCRIPT, DOMAIN_AUDIT, GENERATOR, RUNTIME_V2,
        SOLVER, GENCASE, PARTVTK, FLOATING_INFO, COMPUTE_FORCES,
        CURRENT_MANIFEST, CURRENT_AUDIT, CURRENT_REQUEST_MANIFEST,
        gen_receipt, partvtk_receipt, partvtk_csv,
        DP025_SIMPLE_RECEIPT, DP025_WAVE_RECEIPT, *generated,
    ]
    inputs = existing(source_files)
    total_particles = int(audit_row["gencase"]["total_particles"])
    fluid_particles = int(audit_row["gencase"]["fluid_particles"])
    estimate = _storage_and_wall(total_particles, case["mechanism_id"], case["resolution_id"])
    attempt = f"{cid}_SOLVER_QUAL_FINE_STORAGE_DOMAIN_001"
    input_hashes = {str(path): sha256(path) for path in inputs}
    return {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": "F6",
        "case_id": cid,
        "attempt_id": attempt,
        "kind": "qualification",
        "command": [str(SOLVER.resolve()), str(prefix.resolve()), "{attempt_root}/solver_output", "-tmax:12", "-tout:0.05"],
        "cwd": str(prefix.parent.resolve()),
        "max_wall_seconds": estimate["requested_max_wall_seconds"],
        "cpu_threads": 4,
        "estimated_peak_gpu_mib": 8192 if case["resolution_id"] == "dp020" else 16384,
        "estimated_storage_bytes": estimate["requested_storage_bytes"],
        "worktree_root": str(LAB_ROOT.resolve()),
        "input_files": [str(path) for path in inputs],
        "input_sha256": input_hashes,
        "generator_version": "ds_data02_f6_handoff_20261002.rigid_contract_003.dp020_dp0125.solver_requests.v2",
        "request_registration_commit": git_commit(),
        "mechanism_id": case["mechanism_id"],
        "resolution_id": case["resolution_id"],
        "gencase_receipt": str(gen_receipt.resolve()),
        "gencase_receipt_sha256": sha256(gen_receipt),
        "partvtk_receipt": str(partvtk_receipt.resolve()),
        "partvtk_receipt_sha256": sha256(partvtk_receipt),
        "gencase_actual_particles": {"total": total_particles, "fluid": fluid_particles, **{key: int(audit_row["actual_type_counts"][key]) for key in ("fixed", "moving", "floating")}},
        "generated_native_rigid_contract": audit_row["generated_xml_rigid_contract"],
        "cost_estimate": {
            **estimate,
            "estimated_total_particles": total_particles,
            "estimated_fluid_particles": fluid_particles,
            "old_request_storage_bytes": old["estimated_storage_bytes"],
            "old_request_max_wall_seconds": old["max_wall_seconds"],
            "historical_reference": "completed RIGID003 DP025 12 s native solver receipts; linear particle scaling is a bound review aid, not a performance guarantee",
        },
        "complete_event_window_s": [0.0, 12.0],
        "output_interval_s": 0.05,
        "solver_dimension_required": 3,
        "finite_wall_contract": ["bottom", "left", "right", "front", "back"],
        "simulationdomain_gate": {
            "status": "pending_root_domain_review",
            "reason": "phase003 generated XML uses default domain; this request cannot claim swept coverage until MapRealPos or a root-owned domain-only staged copy is bound",
            "equivalence_domain_audit": str(DOMAIN_AUDIT.resolve()),
            "equivalence_domain_audit_sha256": sha256(DOMAIN_AUDIT),
            "wave_domain_repair_reference_x_m": [-0.2, 5.0] if case["mechanism_id"] == "wave_no_contact" else None,
        },
        "postprocessing_plan": {
            "floating_info": [str(FLOATING_INFO.resolve()), "-dirdata", "{attempt_root}/solver_output/data", "-onlymk:50", "-savedata", "{attempt_root}/solver_output/floatinginfo/FloatingMotion"],
            "compute_forces": [str(COMPUTE_FORCES.resolve()), "-dirdata", "{attempt_root}/solver_output/data", "-onlymk:50", "-savecsv", "{attempt_root}/solver_output/forces/FloatingForce"],
            "required_fields": ["pose", "orientation", "linear_velocity", "angular_velocity", "mass", "inertia", "force", "torque"],
            "torque_origin": "native FloatingInfo fluidForceAng is current COM at the force accumulation step; ComputeForces origin/phase stays separate",
        },
        "qualification_claim": "none_until_root_domain_review_solver_and_native_postprocessing",
        "q_n_status": "pending",
        "solver_launch_authority": "root only through shared ds_data02_runtime_v2.py; F6 owner did not launch GPU",
    }


def make_requests() -> dict[str, Any]:
    audit = read_json(CURRENT_AUDIT)
    domain = read_json(DOMAIN_AUDIT)
    if audit.get("status") != "all_four_generated_rigid_contracts_pass":
        raise RuntimeError(f"rigid audit is not passing: {audit.get('status')}")
    if domain.get("status") != "continuous_contract_pass_domain_pending":
        raise RuntimeError(f"unexpected domain audit status: {domain.get('status')}")
    manifest = read_json(CURRENT_MANIFEST)
    rows: list[dict[str, Any]] = []
    REQUEST_ROOT.mkdir(parents=True, exist_ok=True)
    by_case = {row["case_id"]: row for row in audit["cases"]}
    for case in manifest["cases"]:
        request = request_for_case(case, by_case[case["case_id"]])
        path = REQUEST_ROOT / f"{case['case_id']}.json"
        write_json(path, request)
        rows.append({"case_id": case["case_id"], "path": str(path.resolve()), "sha256": sha256(path), "attempt_id": request["attempt_id"], "gpu_launch": False})
    result = {
        "schema": "ds-data-02.f6.rigid_contract_003.dp020-dp0125.solver_requests.v2",
        "family_id": "F6",
        "status": "root_dispatch_pending_storage_and_domain_review",
        "created_at": now(),
        "source_rigid_audit": str(CURRENT_AUDIT.resolve()),
        "source_rigid_audit_sha256": sha256(CURRENT_AUDIT),
        "source_domain_audit": str(DOMAIN_AUDIT.resolve()),
        "source_domain_audit_sha256": sha256(DOMAIN_AUDIT),
        "source_prior_request_manifest": str(CURRENT_REQUEST_MANIFEST.resolve()),
        "source_prior_request_manifest_sha256": sha256(CURRENT_REQUEST_MANIFEST),
        "request_registration_commit": git_commit(),
        "requests": rows,
        "gpu_launch": False,
        "qualification_claim": "none",
        "q_n_status": "pending_root_domain_review_solver_dispatch_and_full_native_postprocessing",
        "old_requests_immutable": True,
    }
    write_json(REQUEST_MANIFEST, result)
    return result


if __name__ == "__main__":
    print(json.dumps(make_requests(), ensure_ascii=False, indent=2, sort_keys=True))
