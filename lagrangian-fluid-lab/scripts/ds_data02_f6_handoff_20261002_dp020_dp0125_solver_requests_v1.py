#!/usr/bin/env python3
"""Register root-only solver requests for the passed finer F6 preflight.

This module consumes the immutable phase-aligned GenCase/PartVTK receipts and
the additive rigid-contract audit.  It emits four source-hash-bound
qualification requests for root review.  It never launches a solver or GPU.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
from typing import Any


SCRIPT = Path(__file__).resolve()
RIGID_AUDIT = SCRIPT.with_name("ds_data02_f6_handoff_20261002_dp020_dp0125_partvtk_rigid_audit_v3.py")
PHASE_GENERATOR = SCRIPT.with_name("ds_data02_f6_handoff_20261002_dp020_dp0125_v3.py")
SPEC = importlib.util.spec_from_file_location("f6_dp020_dp0125_rigid_audit_for_solver_requests", RIGID_AUDIT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load rigid audit sidecar: {RIGID_AUDIT}")
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)
MODULE = BASE.MODULE

ROOT = MODULE.FAMILY_ROOT
AUDIT_PATH = ROOT / "strict_partvtk_rigid_audit_003.json"
MANIFEST_PATH = ROOT / "manifest.json"
PARTVTK_MANIFEST_PATH = ROOT / "partvtk_request_manifest_002.json"
REQUEST_ROOT = ROOT / "qualification_requests_002"
REQUEST_MANIFEST = REQUEST_ROOT / "qualification_request_manifest_002.json"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")


def _git_commit() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=MODULE.REPO_ROOT, check=True, capture_output=True, text=True).stdout.strip()


def _existing(paths: list[Path]) -> list[Path]:
    values: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        path = path.resolve()
        if not path.is_file():
            continue
        value = str(path)
        if value not in seen:
            values.append(path)
            seen.add(value)
    return values


def _request_for_case(case: dict[str, Any], audit_row: dict[str, Any], partvtk_row: dict[str, Any]) -> dict[str, Any]:
    cid = str(case["case_id"])
    mechanism = str(case["mechanism_id"])
    resolution = str(case["resolution_id"])
    gen_attempt = str(case["request"]["attempt_id"])
    gen_root = MODULE._attempt_root(cid, gen_attempt)
    prefix = gen_root / cid
    gen_receipt = gen_root / "execution-receipt.json"
    partvtk_attempt = str(partvtk_row["request"]["attempt_id"])
    partvtk_root = MODULE._attempt_root(cid, partvtk_attempt)
    partvtk_receipt = partvtk_root / "execution-receipt.json"
    partvtk_csv = Path(partvtk_row["output_csv"])
    partvtk_stats = Path(partvtk_row["output_stats"])
    actual_native = [prefix.with_suffix(ext) for ext in (".bi4", ".xml")]
    actual_native.extend(prefix.with_name(prefix.name + suffix) for suffix in ("_All.vtk", "_Bound.vtk", "_Fluid.vtk", "_MkCells.vtk", "__Dp.vtk"))
    source_files = [
        SCRIPT,
        RIGID_AUDIT,
        PHASE_GENERATOR,
        MODULE.RUNTIME_V2,
        MODULE.SOLVER,
        MODULE.GENCASE,
        MODULE.PARTVTK,
        MODULE.FLOATING_INFO,
        MODULE.COMPUTE_FORCES,
        Path(case["definition"]["path"]),
        Path(case["control"]["path"]),
        Path(case["native"]["path"]),
        Path(case["normal"]["path"]),
        gen_receipt,
        partvtk_receipt,
        partvtk_csv,
        partvtk_stats,
        AUDIT_PATH,
        PARTVTK_MANIFEST_PATH,
        ROOT.parent / "scope.json",
        *actual_native,
    ]
    inputs = _existing(source_files)
    missing_required = [path for path in source_files if not path.is_file()]
    if missing_required:
        raise FileNotFoundError(f"solver request inputs missing for {cid}: {missing_required}")
    input_hashes = {str(path): MODULE.sha256(path) for path in inputs}
    total = int(audit_row["gencase"]["total_particles"])
    fluid = int(audit_row["gencase"]["fluid_particles"])
    counts = dict(audit_row["actual_type_counts"])
    xml_contract = audit_row["generated_xml_rigid_contract"]
    attempt = f"{cid}_SOLVER_QUAL_FINE_001"
    request = {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": "F6",
        "case_id": cid,
        "attempt_id": attempt,
        "kind": "qualification",
        "command": [str(MODULE.SOLVER.resolve()), str(prefix.resolve()), "{attempt_root}/solver_output", "-tmax:12", "-tout:0.05"],
        "cwd": str(gen_root.resolve()),
        "max_wall_seconds": 1800,
        "cpu_threads": 4,
        "estimated_peak_gpu_mib": 8192,
        "estimated_storage_bytes": 8 * 1024**3,
        "worktree_root": str(MODULE.REPO_ROOT.resolve()),
        "input_files": [str(path) for path in inputs],
        "input_sha256": input_hashes,
        "generator_version": "ds_data02_f6_handoff_20261002.rigid_contract_003.dp020_dp0125.solver_requests.v1",
        "request_registration_commit": _git_commit(),
        "mechanism_id": mechanism,
        "resolution_id": resolution,
        "gencase_receipt": str(gen_receipt.resolve()),
        "gencase_receipt_sha256": MODULE.sha256(gen_receipt),
        "partvtk_receipt": str(partvtk_receipt.resolve()),
        "partvtk_receipt_sha256": MODULE.sha256(partvtk_receipt),
        "gencase_actual_particles": {"total": total, "fluid": fluid, "fixed": counts["fixed"], "moving": counts["moving"], "floating": counts["floating"]},
        "generated_native_rigid_contract": xml_contract,
        "cost_estimate": {
            "basis": "actual phase-aligned GenCase particle count and DP025 historical full-window output",
            "estimated_total_particles": total,
            "estimated_fluid_particles": fluid,
            "estimated_peak_gpu_mib": 8192,
            "estimated_native_output_bytes": 8 * 1024**3,
            "historical_reference": "F6 RIGID003 DP025 complete 12 s solver outputs; this finer request remains root review pending",
        },
        "complete_event_window_s": [0.0, 12.0],
        "output_interval_s": 0.05,
        "solver_dimension_required": 3,
        "finite_wall_contract": ["bottom", "left", "right", "front", "back"],
        "postprocessing_plan": {
            "floating_info": [str(MODULE.FLOATING_INFO.resolve()), "-dirdata", "{attempt_root}/solver_output/data", "-onlymk:50", "-savedata", "{attempt_root}/solver_output/floatinginfo/FloatingMotion"],
            "compute_forces": [str(MODULE.COMPUTE_FORCES.resolve()), "-dirdata", "{attempt_root}/solver_output/data", "-onlymk:50", "-savecsv", "{attempt_root}/solver_output/forces/FloatingForce"],
            "required_fields": ["pose", "orientation", "linear_velocity", "angular_velocity", "mass", "inertia", "force", "torque"],
            "torque_origin": "native FloatingInfo fluidForceAng is current COM at force accumulation step; ComputeForces origin/phase must remain separately labeled",
        },
        "qualification_claim": "none_until_root_solver_and_native_postprocessing",
        "q_n_status": "pending",
        "solver_launch_authority": "root only through shared ds_data02_runtime_v2.py; F6 owner did not launch GPU",
    }
    return request


def make_requests() -> dict[str, Any]:
    audit = MODULE.read_json(AUDIT_PATH)
    if audit.get("status") != "all_four_generated_rigid_contracts_pass":
        raise RuntimeError(f"rigid preflight is not fully passing: {audit.get('status')}")
    manifest = MODULE.read_json(MANIFEST_PATH)
    partvtk = MODULE.read_json(PARTVTK_MANIFEST_PATH)
    audit_by_case = {str(row["case_id"]): row for row in audit["cases"]}
    partvtk_by_case = {str(row["case_id"]): row for row in partvtk["requests"]}
    REQUEST_ROOT.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for case in manifest["cases"]:
        cid = str(case["case_id"])
        request = _request_for_case(case, audit_by_case[cid], partvtk_by_case[cid])
        path = REQUEST_ROOT / f"{cid}.json"
        MODULE.write_json(path, request)
        rows.append({"case_id": cid, "path": str(path.resolve()), "sha256": MODULE.sha256(path), "attempt_id": request["attempt_id"], "gpu_launch": False})
    result = {
        "schema": "ds-data-02.f6.rigid_contract_003.dp020-dp0125.solver_requests.v1",
        "family_id": "F6",
        "status": "root_dispatch_pending",
        "created_at": MODULE.now(),
        "source_rigid_audit": str(AUDIT_PATH.resolve()),
        "source_rigid_audit_sha256": MODULE.sha256(AUDIT_PATH),
        "source_partvtk_manifest": str(PARTVTK_MANIFEST_PATH.resolve()),
        "source_partvtk_manifest_sha256": MODULE.sha256(PARTVTK_MANIFEST_PATH),
        "request_registration_commit": _git_commit(),
        "requests": rows,
        "gpu_launch": False,
        "qualification_claim": "none",
        "q_n_status": "pending_root_solver_dispatch_and_full_native_postprocessing",
    }
    MODULE.write_json(REQUEST_MANIFEST, result)
    return result


def main() -> int:
    print(json.dumps(make_requests(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
