#!/usr/bin/env python3
"""Audit the repaired medium GenCase outputs and prepare root GPU requests.

This is a read-only CPU-side gate after ``RIGID003_DOMAIN_X_REPAIR_01``
GenCase.  It checks the actual generated XML summary, binary native boundary
VTK, and shared-runner receipts.  It then writes two root-only qualification
requests with the completed GenCase directory as ``cwd`` so XML/native files
resolve exactly where the solver will read them.  It never launches a solver,
converts BI4, or claims Q-I/Q-N.
"""

from __future__ import annotations

import importlib.util
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
V13 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v13.py")
V12 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v12.py")
SPEC13 = importlib.util.spec_from_file_location("f6_domain_x_repair_01_v13_for_audit", V13)
if SPEC13 is None or SPEC13.loader is None:
    raise RuntimeError(f"cannot load domain repair generator: {V13}")
MODULE_V13 = importlib.util.module_from_spec(SPEC13)
SPEC13.loader.exec_module(MODULE_V13)
MODULE = MODULE_V13.MODULE
SPEC12 = importlib.util.spec_from_file_location("f6_domain_diagnosis_v12_for_audit", V12)
if SPEC12 is None or SPEC12.loader is None:
    raise RuntimeError(f"cannot load native audit decoder: {V12}")
MODULE_V12 = importlib.util.module_from_spec(SPEC12)
SPEC12.loader.exec_module(MODULE_V12)

FAMILY_ROOT = MODULE_V13.MODULE.FAMILY_ROOT
RAW_ROOT = MODULE_V13.MODULE.RAW_FAMILY_ROOT
RUNTIME_V2 = MODULE_V13.MODULE.RUNTIME_V2
SOLVER = MODULE_V13.MODULE.SOLVER
GENCASE = MODULE_V13.MODULE.GENCASE
DIAGNOSIS = MODULE_V13.DIAGNOSIS_SIDECAR
AUDIT_PATH = FAMILY_ROOT / "medium_preflight_001.json"
REQUEST_ROOT = FAMILY_ROOT / "qualification_requests_001"
MECHANISMS = ("simple_free_response", "wave_no_contact")
EXPECTED_MASSBODY = 128.0
EXPECTED_CENTER = [2.4, 1.2, 1.08]
EXPECTED_INERTIA = [8.53333, 8.53333, 13.6533]


def sha256(path: Path) -> str:
    return MODULE.sha256(path)


def write_json(path: Path, value: Any) -> None:
    MODULE.write_json(path, value)


def read_json(path: Path) -> dict[str, Any]:
    return MODULE.read_json(path)


def _medium_case(manifest: dict[str, Any], mechanism: str) -> dict[str, Any]:
    for case in manifest["cases"]:
        if case["mechanism_id"] == mechanism and case["resolution_id"] == "medium":
            return case
    raise KeyError(mechanism)


def _generated_paths(case: dict[str, Any]) -> dict[str, Path]:
    cid = str(case["case_id"])
    attempt = str(case["request"]["attempt_id"])
    root = MODULE._attempt_root(cid, attempt)
    prefix = root / cid
    return {
        "root": root,
        "prefix": prefix,
        "receipt": root / "execution-receipt.json",
        "xml": prefix.with_suffix(".xml"),
        "bi4": prefix.with_suffix(".bi4"),
        "out": prefix.with_suffix(".out"),
        "all_vtk": prefix.with_name(prefix.name + "_All.vtk"),
        "bound_vtk": prefix.with_name(prefix.name + "_Bound.vtk"),
        "fluid_vtk": prefix.with_name(prefix.name + "_Fluid.vtk"),
        "mkcells_vtk": prefix.with_name(prefix.name + "_MkCells.vtk"),
        "dp_vtk": prefix.with_name(prefix.name + "__Dp.vtk"),
    }


def _xml_summary(xml_path: Path) -> dict[str, Any]:
    root = ET.parse(xml_path).getroot()
    particles = root.find("./execution/particles")
    summary = particles.find("_summary") if particles is not None else None
    floating = particles.find("floating") if particles is not None else None
    simdomain = root.find("./execution/parameters/simulationdomain")
    data2d = root.find("./execution/constants/data2d")
    if particles is None or summary is None or floating is None:
        raise ValueError(f"generated XML summary/float block missing: {xml_path}")

    def count(name: str) -> int:
        node = summary.find(name)
        return int(node.attrib.get("count", "0")) if node is not None else 0

    massbody = floating.find("massbody")
    center = floating.find("center")
    inertia = floating.find("inertia")
    contract = {
        "massbody_kg": float(massbody.attrib["value"]) if massbody is not None else None,
        "center_m": [float(center.attrib[axis]) for axis in "xyz"] if center is not None else None,
        "inertia_diag_kg_m2": [float(inertia.attrib[axis]) for axis in "xyz"] if inertia is not None else None,
    }
    return {
        "path": str(xml_path.resolve()),
        "sha256": sha256(xml_path),
        "particle_np": int(particles.attrib.get("np", "0")),
        "particle_nb": int(particles.attrib.get("nb", "0")),
        "particle_nbf": int(particles.attrib.get("nbf", "0")),
        "type_counts": {"fixed": count("fixed"), "moving": count("moving"), "floating": count("floating"), "fluid": count("fluid")},
        "floating_contract": contract,
        "solver_dimension": 2 if data2d is not None and data2d.attrib.get("value", "true").lower() == "true" else 3,
        "simulationdomain_source": {
            "posmin": dict(simdomain.find("posmin").attrib) if simdomain is not None and simdomain.find("posmin") is not None else None,
            "posmax": dict(simdomain.find("posmax").attrib) if simdomain is not None and simdomain.find("posmax") is not None else None,
        },
    }


def _audit_case(case: dict[str, Any]) -> dict[str, Any]:
    paths = _generated_paths(case)
    required = [paths[key] for key in ("receipt", "xml", "bi4", "all_vtk", "bound_vtk", "fluid_vtk", "mkcells_vtk", "dp_vtk")]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("repaired GenCase output missing: " + ", ".join(missing))
    receipt = read_json(paths["receipt"])
    xml = _xml_summary(paths["xml"])
    bound = MODULE_V12._decode_bound_vtk(paths["bound_vtk"], dp=float(case["dp_m"]))
    expected_fluid = int(case["expected_fluid_particles"])
    mechanism = str(case["mechanism_id"])
    checks = {
        "gencase_completed": receipt.get("status") == "completed" and receipt.get("returncode") == 0,
        "actual_3d": receipt.get("solver_dimension_from_gencase") == 3 and xml["solver_dimension"] == 3,
        "positive_fluid_type3": xml["type_counts"]["fluid"] > 0 and xml["type_counts"]["fluid"] == expected_fluid and receipt.get("fluid_particles") == expected_fluid,
        "positive_floating_type2": xml["type_counts"]["floating"] > 0 and bound["type_counts"].get("floating", 0) == xml["type_counts"]["floating"],
        "moving_paddle_present_when_required": (xml["type_counts"]["moving"] > 0) if mechanism == "wave_no_contact" else xml["type_counts"]["moving"] == 0,
        "finite_wall_faces_complete": bound["fixed_face_coverage"]["all_declared_faces_nonzero"],
        "xmax_wall_endpoint_present": bound["fixed_face_coverage"]["counts"]["x_max"] > 0 and bound["fixed_points_bounds_m"][0][1] >= 4.8 - 1.0e-5,
        "explicit_x_domain_bounds": xml["simulationdomain_source"]["posmin"].get("x") == "-0.2" and xml["simulationdomain_source"]["posmax"].get("x") == "5.0",
        "aggregate_massbody_exact": abs(float(xml["floating_contract"]["massbody_kg"]) - EXPECTED_MASSBODY) <= 1.0e-12,
        "aggregate_center_exact": all(abs(a - b) <= 1.0e-12 for a, b in zip(xml["floating_contract"]["center_m"], EXPECTED_CENTER)),
        "aggregate_inertia_serialized_exact": all(abs(a - b) <= 1.0e-12 for a, b in zip(xml["floating_contract"]["inertia_diag_kg_m2"], EXPECTED_INERTIA)),
        "source_hashes_recorded": bool(receipt.get("input_hashes_after_run")),
    }
    return {
        "case_id": case["case_id"],
        "mechanism_id": mechanism,
        "resolution_id": case["resolution_id"],
        "dp_m": case["dp_m"],
        "gencase": {
            "receipt": str(paths["receipt"].resolve()),
            "receipt_sha256": sha256(paths["receipt"]),
            "status": receipt.get("status"),
            "returncode": receipt.get("returncode"),
            "total_particles": receipt.get("total_particles"),
            "fluid_particles": receipt.get("fluid_particles"),
            "solver_dimension_from_gencase": receipt.get("solver_dimension_from_gencase"),
            "input_hashes_after_run": receipt.get("input_hashes_after_run"),
        },
        "generated_native_contract": xml,
        "native_boundary_vtk": bound,
        "expected": {
            "fluid_particles": expected_fluid,
            "fluid_mass_kg": float(case["strict_continuous_fluid_mass_kg"]),
            "aggregate_massbody_kg": EXPECTED_MASSBODY,
            "aggregate_center_m": EXPECTED_CENTER,
            "aggregate_inertia_diag_kg_m2": EXPECTED_INERTIA,
            "particle_type2_mass_is_not_aggregate_mass": True,
        },
        "checks": checks,
        "preflight_pass": all(checks.values()),
        "qualification_claim": "none; native GenCase preflight only",
    }


def audit_medium() -> dict[str, Any]:
    manifest = read_json(FAMILY_ROOT / "manifest.json")
    diagnosis = read_json(DIAGNOSIS)
    rows = [_audit_case(_medium_case(manifest, mechanism)) for mechanism in MECHANISMS]
    result = {
        "schema": "ds-data-02.f6.rigid003_domain_x_repair_01.medium_preflight_001.v1",
        "family_id": "F6",
        "created_at": MODULE.now(),
        "status": "both_medium_gencase_preflight_pass" if all(row["preflight_pass"] for row in rows) else "medium_gencase_preflight_failed",
        "repair_id": "F6_HANDOFF_20261002_RIGID003_DOMAIN_X_REPAIR_01",
        "diagnosis_source": {"path": str(DIAGNOSIS.resolve()), "sha256": sha256(DIAGNOSIS), "qualification_claim": diagnosis.get("qualification_claim")},
        "continuous_geometry": manifest.get("physical_geometry_contract"),
        "cases": rows,
        "gpu_launch": False,
        "q_i_status": "native_gencase_and_boundary_preflight_only",
        "q_n_status": "pending_root_solver_and_native_postprocessing",
    }
    write_json(AUDIT_PATH, result)
    return result


def _solver_inputs(case: dict[str, Any], preflight: dict[str, Any]) -> list[Path]:
    paths = _generated_paths(case)
    values = [
        SCRIPT,
        V13,
        V12,
        RUNTIME_V2,
        SOLVER,
        GENCASE,
        DIAGNOSIS,
        AUDIT_PATH,
        Path(case["definition"]["path"]),
        Path(case["control"]["path"]),
        Path(case["native"]["path"]),
        Path(case["normal"]["path"]),
        Path(case["official_template"]["path"]),
        paths["receipt"],
        paths["xml"],
        paths["bi4"],
        paths["out"],
        paths["all_vtk"],
        paths["bound_vtk"],
        paths["fluid_vtk"],
        paths["mkcells_vtk"],
        paths["dp_vtk"],
    ]
    missing = [str(path) for path in values if not path.is_file()]
    if missing:
        raise FileNotFoundError("solver request input missing: " + ", ".join(missing))
    return values


def make_solver_requests() -> dict[str, Any]:
    preflight = read_json(AUDIT_PATH)
    if preflight.get("status") != "both_medium_gencase_preflight_pass":
        raise RuntimeError("medium native preflight is not passing; no GPU request may be prepared")
    manifest = read_json(FAMILY_ROOT / "manifest.json")
    by_mechanism = {row["mechanism_id"]: row for row in preflight["cases"]}
    rows = []
    for mechanism in MECHANISMS:
        case = _medium_case(manifest, mechanism)
        audit_row = by_mechanism[mechanism]
        input_paths = _solver_inputs(case, preflight)
        cid = str(case["case_id"])
        gen_root = _generated_paths(case)["root"]
        prefix = _generated_paths(case)["prefix"]
        attempt = f"{cid}_SOLVER_QUAL_001"
        input_hashes = {str(path.resolve()): sha256(path) for path in input_paths}
        total = int(audit_row["gencase"]["total_particles"] or 0)
        fluid = int(audit_row["gencase"]["fluid_particles"] or 0)
        request = {
            "schema": "ds-data-02.runner.request.v1",
            "family_id": "F6",
            "case_id": cid,
            "attempt_id": attempt,
            "kind": "qualification",
            "command": [str(SOLVER.resolve()), str(prefix.resolve()), "{attempt_root}/solver_output", "-tmax:12", "-tout:0.05"],
            "cwd": str(gen_root.resolve()),
            "max_wall_seconds": 600,
            "cpu_threads": 4,
            "estimated_peak_gpu_mib": 4096,
            "estimated_storage_bytes": 2147483648,
            "input_files": [str(path.resolve()) for path in input_paths],
            "input_hashes_at_request": input_hashes,
            "worktree_root": str(MODULE.REPO_ROOT.resolve()),
            "generator_version": MODULE_V13.MODULE.VERSION,
            "mechanism_id": mechanism,
            "resolution_id": "medium",
            "repair_id": "F6_HANDOFF_20261002_RIGID003_DOMAIN_X_REPAIR_01",
            "launch_authority": "root only; F6 owner does not launch GPU",
            "gencase_receipt": str(_generated_paths(case)["receipt"].resolve()),
            "gencase_receipt_sha256": sha256(_generated_paths(case)["receipt"]),
            "medium_preflight": str(AUDIT_PATH.resolve()),
            "medium_preflight_sha256": sha256(AUDIT_PATH),
            "diagnosis_sidecar": str(DIAGNOSIS.resolve()),
            "diagnosis_sidecar_sha256": sha256(DIAGNOSIS),
            "gencase_actual_particles": {
                "total": total,
                "fluid": fluid,
                "fixed": audit_row["generated_native_contract"]["type_counts"]["fixed"],
                "moving": audit_row["generated_native_contract"]["type_counts"]["moving"],
                "floating": audit_row["generated_native_contract"]["type_counts"]["floating"],
            },
            "generated_native_rigid_contract": audit_row["generated_native_contract"]["floating_contract"],
            "native_boundary_contract": {
                "fixed_face_coverage": audit_row["native_boundary_vtk"]["fixed_face_coverage"],
                "fixed_points_bounds_m": audit_row["native_boundary_vtk"]["fixed_points_bounds_m"],
            },
            "runtime_prefix_contract": {
                "prefix_directory": str(gen_root.resolve()),
                "xml": str(prefix.with_suffix(".xml").resolve()),
                "bi4": str(prefix.with_suffix(".bi4").resolve()),
                "xml_external_references": [],
                "all_xml_references_resolve_from_prefix": True,
            },
            "complete_event_window_s": [0.0, 12.0],
            "output_interval_s": 0.05,
            "solver_dimension_required": 3,
            "cost_estimate": {
                "basis": "actual repaired medium GenCase receipt",
                "estimated_total_particles": total,
                "estimated_fluid_particles": fluid,
                "estimated_gpu_seconds": max(120, min(600, int(total / 1500 + 90))),
                "estimated_native_bytes": 536870912,
            },
            "postprocessing_pending": ["native all typed H5", "FloatingInfo full pose/velocity/angular velocity", "ComputeForces force/torque", "PartVTK contact/exclusion audit when conversion slot is available"],
            "qualification_claim": "none; request pending root dispatch and terminal native review",
        }
        path = REQUEST_ROOT / f"{cid}.json"
        write_json(path, request)
        rows.append({"mechanism_id": mechanism, "case_id": cid, "path": str(path.resolve()), "sha256": sha256(path), "attempt_id": attempt})
    result = {
        "schema": "ds-data-02.f6.rigid003_domain_x_repair_01.qualification_requests_001.v1",
        "status": "root_dispatch_pending",
        "created_at": MODULE.now(),
        "requests": rows,
        "gpu_launch": False,
        "q_n_status": "pending",
    }
    write_json(REQUEST_ROOT / "request_manifest.json", result)
    return result


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["audit-medium", "make-solver-requests"])
    args = parser.parse_args()
    result = audit_medium() if args.action == "audit-medium" else make_solver_requests()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
