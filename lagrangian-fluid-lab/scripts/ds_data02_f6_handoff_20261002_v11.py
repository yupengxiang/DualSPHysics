#!/usr/bin/env python3
"""Additive RIGID003 audit and root-only qualification request builder.

GenCase preserves an explicit floating-body center and diagonal inertia in the
generated XML, but serializes those values at fixed decimal precision.  The
first RIGID003 audit intentionally used an exact comparison with the analytic
Python values and therefore recorded a negative result even though all six
generated XML files agreed.  This wrapper keeps that negative artifact and
records the two contracts separately:

* the analytic physical inertia used by the frozen mother, and
* the fixed-precision values actually emitted by GenCase.

It never regenerates or edits the consumed GenCase/PartVTK outputs.  It only
reads their receipts/CSV/XML files and writes a new audit sidecar plus new
root-dispatchable solver requests.  It does not launch a solver.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path


SCRIPT = Path(__file__).resolve()
V10 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v10.py")
SPEC = importlib.util.spec_from_file_location("f6_handoff_20261002_v10_for_audit002", V10)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load PartVTK-003 wrapper: {V10}")
MODULE_V10 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE_V10)
MODULE = MODULE_V10.MODULE

# v10's MODULE already points at the additive partvtk_003 directory.  Keep
# that path and the v10 source immutable for receipt lineage.
MODULE.SCRIPT = SCRIPT
MODULE.VERSION = "ds_data02_f6_handoff_20261002.rigid_contract_003.partvtk_003.audit_002.v1"

RIGID_CENTER = [2.4, 1.2, 1.08]
RIGID_MASSBODY = 128.0
RIGID_INERTIA_ANALYTIC = [
    8.533333333333335,
    8.533333333333335,
    13.653333333333336,
]
# GenCase's generated native XML uses six significant decimal digits for the
# explicit floating inertia.  This is an output serialization contract, not a
# resolution-dependent body parameter.
RIGID_INERTIA_SERIALIZED = [8.53333, 8.53333, 13.6533]
SERIALIZATION_TOLERANCE = 5.0e-5
AUDIT_PATH = MODULE.FAMILY_ROOT / "strict_rigid_contract_audit_002.json"
BASE_AUDIT_PATH = MODULE.FAMILY_ROOT / "strict_partvtk_audit.json"
FAILED_AUDIT_PATH = MODULE.FAMILY_ROOT / "strict_rigid_contract_audit_001_failed.json"

V9 = V10.with_name("ds_data02_f6_handoff_20261002_v9.py")
V8 = V10.with_name("ds_data02_f6_handoff_20261002_v8.py")
V7 = V10.with_name("ds_data02_f6_handoff_20261002_v7.py")
V6 = V10.with_name("ds_data02_f6_handoff_20261002_v6.py")
V5 = V10.with_name("ds_data02_f6_handoff_20261002_v5.py")
V4 = V10.with_name("ds_data02_f6_handoff_20261002_v4.py")
V3 = V10.with_name("ds_data02_f6_handoff_20261002_v3.py")
V2 = V10.with_name("ds_data02_f6_handoff_20261002_v2.py")
V1 = V10.with_name("ds_data02_f6_handoff_20261002.py")


def _generated_contract(xml_path: Path) -> dict[str, object]:
    """Read the actual native floating block emitted by GenCase."""

    root = ET.parse(xml_path).getroot()
    floating = next((node for node in root.iter("floating") if node.attrib.get("mk") == "60"), None)
    if floating is None:
        raise ValueError(f"generated floating mk=60 not found: {xml_path}")
    massbody = floating.find("massbody")
    center = floating.find("center")
    inertia = floating.find("inertia")
    if massbody is None or center is None or inertia is None:
        raise ValueError(f"generated floating contract incomplete: {xml_path}")
    actual_mass = float(massbody.attrib["value"])
    actual_center = [float(center.attrib[axis]) for axis in ("x", "y", "z")]
    actual_inertia = [float(inertia.attrib[axis]) for axis in ("x", "y", "z")]
    return {
        "massbody_kg": actual_mass,
        "center_m": actual_center,
        "inertia_diag_kg_m2": actual_inertia,
        "analytic_inertia_diag_kg_m2": RIGID_INERTIA_ANALYTIC,
        "serialized_inertia_diag_kg_m2": RIGID_INERTIA_SERIALIZED,
        "serialization_tolerance_kg_m2": SERIALIZATION_TOLERANCE,
        "source_xml": str(xml_path.resolve()),
        "source_xml_sha256": MODULE.sha256(xml_path),
        "exact_massbody": abs(actual_mass - RIGID_MASSBODY) <= 1.0e-12,
        "exact_center": all(abs(a - b) <= 1.0e-12 for a, b in zip(actual_center, RIGID_CENTER)),
        "generated_inertia_matches_serialized_contract": all(
            abs(a - b) <= 1.0e-12
            for a, b in zip(actual_inertia, RIGID_INERTIA_SERIALIZED)
        ),
        "generated_inertia_within_analytic_serialization_precision": all(
            abs(a - b) <= SERIALIZATION_TOLERANCE
            for a, b in zip(actual_inertia, RIGID_INERTIA_ANALYTIC)
        ),
        "explicit_contract_present": True,
    }


def _base_audit() -> dict[str, object]:
    """Read, but never rewrite, the completed PartVTK-003 base audit."""

    if not BASE_AUDIT_PATH.is_file():
        raise FileNotFoundError(BASE_AUDIT_PATH)
    base = MODULE.read_json(BASE_AUDIT_PATH)
    if base.get("status") != "all_three_dp_preflight_pass":
        raise RuntimeError(f"PartVTK-003 base preflight is not passing: {base.get('status')}")
    if len(base.get("cases", [])) != 6:
        raise RuntimeError("PartVTK-003 base audit must contain six cases")
    return base


def audit() -> dict[str, object]:
    """Join immutable PartVTK rows with all six actual generated XML contracts."""

    base = _base_audit()
    manifest = MODULE.read_json(MODULE.FAMILY_ROOT / "manifest.json")
    by_case = {str(case["case_id"]): case for case in manifest["cases"]}
    rows: list[dict[str, object]] = []
    for source_row in base["cases"]:
        row = copy.deepcopy(source_row)
        cid = str(row["case_id"])
        case = by_case[cid]
        gen_attempt = str(case["request"]["attempt_id"])
        xml = MODULE._attempt_root(cid, gen_attempt) / f"{cid}.xml"
        generated = _generated_contract(xml)
        checks = dict(row.get("checks", {}))
        checks.update(
            {
                "generated_xml_exists": xml.is_file(),
                "generated_native_massbody_exact": bool(generated["exact_massbody"]),
                "generated_native_center_exact": bool(generated["exact_center"]),
                "generated_native_inertia_matches_fixed_precision": bool(
                    generated["generated_inertia_matches_serialized_contract"]
                ),
                "generated_native_inertia_within_analytic_precision": bool(
                    generated["generated_inertia_within_analytic_serialization_precision"]
                ),
            }
        )
        row["generated_xml_rigid_contract"] = generated
        row["checks"] = checks
        row["preflight_pass"] = all(bool(value) for value in checks.values())
        rows.append(row)

    result = {
        "schema": "ds-data-02.f6.rigid_contract_003.audit_002.v1",
        "family_id": "F6",
        "created_at": MODULE.now(),
        "status": "all_six_generated_native_rigid_contract_pass"
        if all(row["preflight_pass"] for row in rows)
        else "generated_native_rigid_contract_failed",
        "source_base_audit": {
            "path": str(BASE_AUDIT_PATH.resolve()),
            "sha256": MODULE.sha256(BASE_AUDIT_PATH),
            "status": base.get("status"),
        },
        "preserved_negative_evidence": {
            "path": str(FAILED_AUDIT_PATH.resolve()),
            "sha256": MODULE.sha256(FAILED_AUDIT_PATH) if FAILED_AUDIT_PATH.is_file() else None,
            "reason": "audit_001 compared fixed-precision GenCase XML inertia to unrounded analytic Python values",
        },
        "continuous_geometry": {
            "fluid_volume_m3": 5.12,
            "strict_fluid_mass_kg": 5120.0,
            "body_center_m": RIGID_CENTER,
            "body_massbody_kg": RIGID_MASSBODY,
            "body_inertia_diag_kg_m2": RIGID_INERTIA_ANALYTIC,
        },
        "native_generated_contract": {
            "floatingtype": 2,
            "center_m": RIGID_CENTER,
            "massbody_kg": RIGID_MASSBODY,
            "analytic_inertia_diag_kg_m2": RIGID_INERTIA_ANALYTIC,
            "serialized_inertia_diag_kg_m2": RIGID_INERTIA_SERIALIZED,
            "serialization_tolerance_kg_m2": SERIALIZATION_TOLERANCE,
            "same_across_all_six_generated_xml": True,
            "particle_type2_mass_is_separate": True,
        },
        "supersedes": "strict_rigid_contract_audit_001_failed.json only for the precision criterion; the failed bytes remain preserved",
        "cases": rows,
        "gpu_launch": False,
        "q_i_status": "generated_xml_and_typed_initial_state_preflight_only",
        "q_n_status": "pending_root_solver_and_native_postprocessing",
    }
    MODULE.write_json(AUDIT_PATH, result)
    return result


def _request_input_paths(case: dict[str, object], cid: str, gen_root: Path, prefix: Path, gen_receipt: Path, partvtk_receipt: Path, partvtk_csv: Path, audit_path: Path) -> list[Path]:
    paths = [
        SCRIPT,
        V10,
        V9,
        V8,
        V7,
        V6,
        V5,
        V4,
        V3,
        V2,
        V1,
        MODULE.RUNTIME_V2,
        Path(case["definition"]["path"]),
        Path(case["control"]["path"]),
        Path(case["native"]["path"]),
        Path(case["normal"]["path"]),
        Path(case["official_template"]["path"]),
        MODULE.GENCASE,
        MODULE.PARTVTK,
        MODULE.SOLVER,
        MODULE.FLOATING_INFO,
        MODULE.COMPUTE_FORCES,
        gen_receipt,
        partvtk_receipt,
        partvtk_csv,
        audit_path,
        prefix.with_suffix(".xml"),
        prefix.with_suffix(".bi4"),
        prefix.with_name(prefix.name + "_All.vtk"),
        prefix.with_name(prefix.name + "_Fluid.vtk"),
    ]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError("solver request input missing: " + ", ".join(missing))
    return paths


def make_solver_requests() -> dict[str, object]:
    """Prepare all six root-only solver requests, including both medium cases."""

    audit_result = MODULE.read_json(AUDIT_PATH)
    if audit_result.get("status") != "all_six_generated_native_rigid_contract_pass":
        raise RuntimeError("audit_002 is not fully passing; do not prepare solver requests")
    manifest = MODULE.read_json(MODULE.FAMILY_ROOT / "manifest.json")
    audit_by_case = {str(row["case_id"]): row for row in audit_result["cases"]}
    request_root = MODULE.FAMILY_ROOT / "qualification_requests_002"
    rows: list[dict[str, object]] = []
    for case in manifest["cases"]:
        cid = str(case["case_id"])
        gen_attempt = str(case["request"]["attempt_id"])
        gen_root = MODULE._attempt_root(cid, gen_attempt)
        prefix = gen_root / cid
        gen_receipt = gen_root / "execution-receipt.json"
        partvtk_attempt = f"{cid}_PARTVTK_003"
        partvtk_root = MODULE._attempt_root(cid, partvtk_attempt)
        partvtk_receipt = partvtk_root / "execution-receipt.json"
        partvtk_csv = partvtk_root / f"{cid}_initial_all.csv"
        input_paths = _request_input_paths(
            case, cid, gen_root, prefix, gen_receipt, partvtk_receipt, partvtk_csv, AUDIT_PATH
        )
        row = audit_by_case[cid]
        total = int(row["gencase"]["total_particles"] or 0)
        fluid = int(row["gencase"]["fluid_particles"] or 0)
        gpu_seconds = max(120, min(600, int(total / 1500 + 90)))
        attempt = f"{cid}_SOLVER_QUAL_003"
        request = {
            "schema": "ds-data-02.runner.request.v1",
            "family_id": "F6",
            "case_id": cid,
            "attempt_id": attempt,
            "kind": "qualification",
            "command": [
                str(MODULE.SOLVER.resolve()),
                str(prefix.resolve()),
                "{attempt_root}/solver_output",
                "-tmax:12",
                "-tout:0.05",
            ],
            # The completed GenCase directory contains the XML/BI4 prefix;
            # this cwd is required for the solver's relative native lookups.
            "cwd": str(gen_root.resolve()),
            "max_wall_seconds": 600,
            "cpu_threads": 4,
            "estimated_peak_gpu_mib": 4096,
            "estimated_storage_bytes": 2147483648,
            "worktree_root": str(MODULE.REPO_ROOT.resolve()),
            "input_files": [str(path.resolve()) for path in input_paths],
            "generator_version": MODULE.VERSION,
            "mechanism_id": case["mechanism_id"],
            "resolution_id": case["resolution_id"],
            "launch_commit_required": "root records dispatch commit; F6 owner does not launch GPU",
            "gencase_receipt": str(gen_receipt.resolve()),
            "gencase_receipt_sha256": MODULE.sha256(gen_receipt),
            "partvtk_receipt": str(partvtk_receipt.resolve()),
            "partvtk_receipt_sha256": MODULE.sha256(partvtk_receipt),
            "audit_002": str(AUDIT_PATH.resolve()),
            "audit_002_sha256": MODULE.sha256(AUDIT_PATH),
            "gencase_actual_particles": {
                "total": total,
                "fluid": fluid,
                "fixed": row["actual_type_counts"]["fixed"],
                "moving": row["actual_type_counts"]["moving"],
                "floating": row["actual_type_counts"]["floating"],
            },
            "generated_native_rigid_contract": row["generated_xml_rigid_contract"],
            "cost_estimate": {
                "basis": "actual RIGID003 GenCase/PartVTK count",
                "estimated_gpu_seconds": gpu_seconds,
                "estimated_total_particles": total,
                "estimated_fluid_particles": fluid,
                "estimated_native_bytes": 536870912,
            },
            "complete_event_window_s": [0.0, 12.0],
            "output_interval_s": 0.05,
            "solver_dimension_required": 3,
            "runtime_prefix_contract": {
                "prefix_directory": str(gen_root.resolve()),
                "xml": str(prefix.with_suffix(".xml").resolve()),
                "bi4": str(prefix.with_suffix(".bi4").resolve()),
                "xml_external_references": [],
                "all_xml_references_resolve_from_prefix": True,
                "source_control_native_normal_are_hash_bound_inputs": True,
            },
            "qualification_claim": "none_until_complete_window_and_native_rigid_audit",
            "q_n_status": "pending",
            "postprocessing_plan": {
                "floating_info": [
                    str(MODULE.FLOATING_INFO.resolve()),
                    "-dirdata",
                    "{attempt_root}/solver_output/data",
                    "-onlymk:50",
                    "-savedata",
                    "{attempt_root}/solver_output/floatinginfo/FloatingMotion",
                ],
                "compute_forces": [
                    str(MODULE.COMPUTE_FORCES.resolve()),
                    "-dirdata",
                    "{attempt_root}/solver_output/data",
                    "-onlymk:50",
                    "-savecsv",
                    "{attempt_root}/solver_output/forces/FloatingForce",
                ],
                "required_fields": [
                    "pose",
                    "orientation",
                    "linear_velocity",
                    "angular_velocity",
                    "massbody",
                    "inertia",
                    "force",
                    "torque",
                ],
                "postprocessors_pending_shared_cpu_execution": True,
            },
            "solver_launch_authority": "root only through shared ds_data02_runtime_v2.py; F6 owner did not launch GPU",
        }
        path = request_root / f"{cid}.json"
        MODULE.write_json(path, request)
        rows.append({"case_id": cid, "path": str(path.resolve()), "sha256": MODULE.sha256(path), "attempt_id": attempt})
    result = {
        "schema": "ds-data-02.f6.rigid_contract_003.solver_requests_002.v1",
        "status": "root_dispatch_pending",
        "created_at": MODULE.now(),
        "source_audit": {"path": str(AUDIT_PATH.resolve()), "sha256": MODULE.sha256(AUDIT_PATH)},
        "requests": rows,
        "gpu_launch": False,
        "q_n_status": "pending",
    }
    MODULE.write_json(MODULE.FAMILY_ROOT / "qualification_request_manifest_002.json", result)
    return result


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["audit", "make-solver-requests"])
    args = parser.parse_args()
    result = audit() if args.action == "audit" else make_solver_requests()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
