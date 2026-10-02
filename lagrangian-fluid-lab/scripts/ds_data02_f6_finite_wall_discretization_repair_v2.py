#!/usr/bin/env python3
"""Register the scoped F6 DP020 finite-wall repair.

The first repair candidate (``finite_wall_discretization_repair_001``) was
written before the DP0125 comparison was made explicit.  Its DP0125 copies
are retained as an unexecuted candidate, but this version is the executable
registration: only the two DP020 source XMLs are changed.  The complete
DP0125 and DP025 Bound.vtk files remain immutable comparison evidence.

No GenCase or solver is launched here.  The generated requests are for the
shared CPU runner and require a fresh actual Bound.vtk five-face audit before
any GPU request can be considered.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
V1_PATH = SCRIPT.with_name("ds_data02_f6_finite_wall_discretization_repair_v1.py")
spec = importlib.util.spec_from_file_location("f6_wall_repair_v1", V1_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot import {V1_PATH}")
v1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v1)

AUDIT_ROOT = v1.AUDIT_ROOT.parent / "finite_wall_discretization_repair_002"
OUTPUT_ROOT = AUDIT_ROOT / "definitions"
REQUEST_ROOT = AUDIT_ROOT / "gencase_requests"


def source_cases_dp020() -> list[dict[str, Any]]:
    return [row for row in v1.source_cases() if row["dp_m"] == 0.02]


def input_paths(case: dict[str, Any], repaired: Path, evidence: Path) -> list[Path]:
    paths = [
        SCRIPT,
        V1_PATH,
        v1.RUNNER_V2,
        v1.GENCASE,
        repaired,
        evidence,
        case["source_xml"],
        case["source_bound"],
        case["failure_error"],
        case["failure_runout"],
        case["failure_runparts"],
    ]
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        path = Path(path).resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        if str(path) not in seen:
            seen.add(str(path))
            result.append(path)
    return result


def request_for(case: dict[str, Any], repaired: Path, evidence: Path, launch_commit: str) -> dict[str, Any]:
    case_id = case["case_id"] + "_FINITE_WALL_REPAIR_002"
    paths = input_paths(case, repaired, evidence)
    return {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": "F6",
        "case_id": case_id,
        "mechanism_id": case["mechanism_id"],
        "resolution_id": case["resolution_id"],
        "attempt_id": case_id + "_GENCASE_001",
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "command": [
            str(v1.GENCASE),
            str(repaired.with_suffix("")),
            "{attempt_root}/" + case_id,
            "-save:all",
        ],
        "cwd": str(AUDIT_ROOT),
        "max_wall_seconds": 1200,
        "cpu_threads": 4,
        "estimated_storage_bytes": 2 * v1.GIB,
        "input_files": [str(path) for path in paths],
        "input_sha256": {str(path): v1.sha256(path) for path in paths},
        "worktree_root": str(v1.WORKTREE_ROOT),
        "launch_commit": launch_commit,
        "generator_version": "ds-data-02.f6.finite-wall-discretization-repair.v2",
        "purpose": "repair only the demonstrated DP020 high-y finite-wall lattice omission; GenCase and initial native Bound.vtk QA",
        "repair_scope": {
            "root_cause": "phase003 DP020 GenCase Bound.vtk omitted the interior high-y fixed face at y=2.4-dp/2; only edge particles remained",
            "repair_class": "finite-wall discretization, second registration version of the first repair class",
            "source_physics_unchanged": True,
            "source_fluid_mass_kg": 5120.0,
            "source_body_mass_kg": 128.0,
            "source_body_center_m": [2.4, 1.2, 1.08],
            "source_body_inertia_diag_kg_m2": [8.53333333333, 8.53333333333, 13.6533333333],
            "old_failure_evidence": str(case["failure_error"]),
            "dp0125_policy": "reference only; its native high-y face is complete and receives no added slab",
        },
        "expected": {
            "solver_dimension": 3,
            "fluid_type": 3,
            "floating_type": 2,
            "expected_fluid_particles": 640000,
            "expected_fixed_particles_before_repair": 85682,
            "expected_floating_particles": 35301,
            "finite_walls": ["bottom", "left", "right", "front", "back"],
            "high_y_full_face_required": True,
            "minimum_transverse_layers": 10,
            "no_mass_rescaling": True,
        },
        "preflight": {
            "status": "pending_shared_runner_gencase_and_actual_bound_vtk",
            "gpu_launch": False,
            "q_n_status": "pending",
            "required_face_qa": {
                "x_low": "full tangential lattice",
                "x_high": "full tangential lattice",
                "y_low": "full tangential lattice",
                "y_high": "full tangential lattice newly restored",
                "z_low": "full tangential lattice",
                "z_high": "open top reference; edge-only is expected",
            },
        },
        "qualification_claim": "none",
        "q_n_status": "pending actual GenCase and five-face native QA",
    }


def build() -> dict[str, Any]:
    launch_commit = v1.git_head()
    AUDIT_ROOT.mkdir(parents=True, exist_ok=True)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    REQUEST_ROOT.mkdir(parents=True, exist_ok=True)
    cases = source_cases_dp020()
    evidence: dict[str, Any] = {
        "schema": "ds-data-02.f6.finite-wall-discretization-evidence.v2",
        "family_id": "F6",
        "scope": "DP020 simple-free-response and wave-no-contact finite-wall QA; DP0125 and DP025 are immutable comparison references",
        "created_at_utc": v1.now(),
        "repair_count": {
            "finite_wall_discretization": 1,
            "domain_only": "not a repair for this root cause",
            "repair_version": 2,
        },
        "root_cause": {
            "classification": "GenCase finite-wall lattice omission",
            "observed": "both DP020 Bound.vtk files contain only 478 fixed points on the high-y edge instead of a full x-z plane; the failed native floating particles reached y≈2.55",
            "not_domain_only": "enlarging simulationdomain cannot create missing fixed particles or a closed +Y physical wall",
        },
        "failed_solver_evidence": {},
        "bound_face_comparison": {},
        "new_repair": {
            "status": "definitions_and_requests_written_pending_shared_runner",
            "physical_geometry_change": False,
            "gpu_launch": False,
            "scope": "DP020 only",
        },
        "source_hashes": {},
    }
    for case in cases:
        key = f"{case['mechanism_id']}_{case['resolution_id']}"
        evidence["failed_solver_evidence"][key] = {
            "error": v1.error_audit(case["failure_error"]),
            "run_out": v1.bind(case["failure_runout"], "failed root-domain solver Run.out"),
            "run_parts": v1.bind(case["failure_runparts"], "failed root-domain RunPARTs.csv"),
        }
        evidence["bound_face_comparison"][key] = v1.bound_audit(case["source_bound"], case["dp_m"])
        evidence["source_hashes"][key] = {
            "source_xml": v1.sha256(case["source_xml"]),
            "source_bound": v1.sha256(case["source_bound"]),
        }

    # These references establish that the omission is resolution/source
    # specific.  They are read and hashed only; no reference XML is changed.
    for name, path in v1.reference_bounds().items():
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(path)
        dp = 0.025 if "dp025" in name else 0.0125
        evidence["bound_face_comparison"][name] = v1.bound_audit(path, dp)
        evidence["source_hashes"][name] = v1.sha256(path)

    evidence_path = AUDIT_ROOT / "finite_wall_discretization_evidence_002.json"
    v1.write_json(evidence_path, evidence)
    requests: list[dict[str, Any]] = []
    for case in cases:
        repaired = OUTPUT_ROOT / f"{case['case_id']}_FINITE_WALL_REPAIR_002_Def.xml"
        repair_info = v1.repair_xml(case["source_xml"], repaired)
        request = request_for(case, repaired, evidence_path, launch_commit)
        request_path = REQUEST_ROOT / f"{case['case_id']}_FINITE_WALL_REPAIR_002_gencase.json"
        v1.write_json(request_path, request)
        requests.append({
            "case_id": case["case_id"],
            "repair_xml": repair_info,
            "request": v1.bind(request_path, "shared v2 GenCase request"),
            "status": "pending_shared_runner",
        })
    manifest = {
        "schema": "ds-data-02.f6.finite-wall-discretization-repair-registration.v2",
        "family_id": "F6",
        "launch_commit": launch_commit,
        "supersedes": {
            "candidate_manifest": str((v1.AUDIT_ROOT / "repair_manifest_001.json").resolve()),
            "policy": "001 is retained as an unexecuted candidate; 002 is the scoped executable registration and does not modify DP0125",
        },
        "evidence": v1.bind(evidence_path, "immutable finite-wall root-cause evidence v2"),
        "requests": requests,
        "status": "pending_cpu_gencase_and_actual_bound_vtk_face_qa",
        "gpu_launch": False,
        "source_physics": "frozen DP020 physical tank/body/fluid/control; explicit one-cell high-y slab only; DP0125/DP025 references unchanged",
        "q_n_status": "pending",
    }
    manifest_path = AUDIT_ROOT / "repair_manifest_002.json"
    v1.write_json(manifest_path, manifest)
    return manifest


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=2, sort_keys=True))
