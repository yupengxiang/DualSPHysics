#!/usr/bin/env python3
"""PartVTK-003 and generated-XML rigid-contract audit for RIGID003."""

from __future__ import annotations

import csv
import importlib.util
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path


SCRIPT = Path(__file__).resolve()
V9 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v9.py")
SPEC = importlib.util.spec_from_file_location("f6_handoff_20261002_v9", V9)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load RIGID003 generator: {V9}")
MODULE_V9 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE_V9)
MODULE = MODULE_V9.MODULE
ORIGINAL_ROOT = MODULE.FAMILY_ROOT
MODULE.FAMILY_ROOT = ORIGINAL_ROOT / "partvtk_003"
MODULE.SCRIPT = SCRIPT
MODULE.VERSION = "ds_data02_f6_handoff_20261002.rigid_contract_003.partvtk_003.v1"
V5 = V9.with_name("ds_data02_f6_handoff_20261002_v5.py")
V4 = V9.with_name("ds_data02_f6_handoff_20261002_v4.py")
V3 = V9.with_name("ds_data02_f6_handoff_20261002_v3.py")
V2 = V9.with_name("ds_data02_f6_handoff_20261002_v2.py")
V1 = V9.with_name("ds_data02_f6_handoff_20261002.py")
RIGID_CENTER = [2.4, 1.2, 1.08]
RIGID_INERTIA = [8.533333333333335, 8.533333333333335, 13.653333333333336]


_BASE_INPUT_FILES = MODULE._request_input_files


def _request_input_files_existing(*paths: Path) -> list[str]:
    values = [value for value in _BASE_INPUT_FILES(*paths) if Path(value).is_file()]
    for path in (V9, V5, V4, V3, V2, V1):
        value = str(path.resolve())
        if value not in values:
            values.append(value)
    return values


MODULE._request_input_files = _request_input_files_existing


def make_partvtk_requests() -> dict[str, object]:
    source_manifest = MODULE.read_json(ORIGINAL_ROOT / "manifest.json")
    MODULE.FAMILY_ROOT.mkdir(parents=True, exist_ok=True)
    MODULE.write_json(MODULE.FAMILY_ROOT / "manifest.json", source_manifest)
    rows: list[dict[str, object]] = []
    for case in source_manifest["cases"]:
        cid = str(case["case_id"])
        gen_attempt = str(case["request"]["attempt_id"])
        gen_receipt = MODULE._receipt(cid, gen_attempt)
        if not gen_receipt.is_file():
            raise FileNotFoundError(gen_receipt)
        gen = MODULE.read_json(gen_receipt)
        if gen.get("status") != "completed" or gen.get("returncode") != 0:
            raise RuntimeError(f"GenCase incomplete: {gen_receipt}")
        prefix = MODULE._attempt_root(cid, gen_attempt) / cid
        bi4, xml = prefix.with_suffix(".bi4"), prefix.with_suffix(".xml")
        if not bi4.is_file() or not xml.is_file():
            raise FileNotFoundError(f"generated native pair missing for {cid}")
        attempt = f"{cid}_PARTVTK_003"
        csv_out = f"{{attempt_root}}/{cid}_initial_all.csv"
        stats_out = f"{{attempt_root}}/{cid}_initial_stats.csv"
        inputs = _request_input_files_existing(
            SCRIPT, MODULE.RUNTIME_V2, MODULE.PARTVTK, gen_receipt, bi4, xml,
            prefix.with_name(prefix.name + "_All.vtk"),
            prefix.with_name(prefix.name + "_Fluid.vtk"),
            Path(case["definition"]["path"]), Path(case["control"]["path"]),
            Path(case["native"]["path"]), Path(case["normal"]["path"]),
        )
        request = {
            "schema": "ds-data-02.runner.request.v1", "family_id": "F6", "case_id": cid,
            "attempt_id": attempt, "kind": "cpu", "cpu_task_kind": "audit",
            "command": [str(MODULE.PARTVTK.resolve()), "-filedata", str(bi4.resolve()), "-filexml", str(xml.resolve()), "-savecsv", csv_out, "-savestatscsv", stats_out, "-csvsep:1", "-onlytype:+all", "-vars:+all", "-threads:4"],
            "cwd": str(prefix.parent.resolve()), "max_wall_seconds": 600, "cpu_threads": 4,
            "estimated_storage_bytes": 268435456, "input_files": inputs, "worktree_root": str(MODULE.REPO_ROOT.resolve()),
            "generator_version": MODULE.VERSION, "mechanism_id": case["mechanism_id"], "resolution_id": case["resolution_id"],
            "purpose": "official PartVTK-003 typed initial-state audit plus generated floating center/inertia audit; no solver/GPU",
            "gencase_receipt": str(gen_receipt.resolve()), "gencase_receipt_sha256": MODULE.sha256(gen_receipt),
            "expected": {"fluid_type": 3, "floating_type": 2, "moving_type": 1 if case["mechanism_id"] == "wave_no_contact" else 0, "strict_continuous_fluid_mass_kg": case["strict_continuous_fluid_mass_kg"], "native_massbody_kg": 128.0, "native_center_m": RIGID_CENTER, "native_inertia_kg_m2": RIGID_INERTIA},
        }
        path = MODULE.FAMILY_ROOT / "execution_requests" / f"{cid}_partvtk_003.json"
        MODULE.write_json(path, request)
        rows.append({"case_id": cid, "request": {"path": str(path.resolve()), "sha256": MODULE.sha256(path), "attempt_id": attempt}, "gencase_receipt": str(gen_receipt.resolve()), "output_csv": str((MODULE._attempt_root(cid, attempt) / f"{cid}_initial_all.csv").resolve())})
    result = {"schema": "ds-data-02.f6.rigid_contract_003.partvtk_requests.v1", "created_at": MODULE.now(), "status": "ready_for_shared_runtime_partvtk", "requests": rows}
    MODULE.write_json(MODULE.FAMILY_ROOT / "partvtk_request_manifest.json", result)
    return result


def _load_partvtk_counter():
    path = V9.with_name("ds_data02_f6_handoff_20261002_v7.py")
    spec = importlib.util.spec_from_file_location("f6_handoff_20261002_v7_for_rigid003", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._partvtk_counts


def _generated_contract(xml_path: Path) -> dict[str, object]:
    root = ET.parse(xml_path).getroot()
    floating = next((node for node in root.iter("floating") if node.attrib.get("mk") == "60"), None)
    if floating is None:
        raise ValueError(f"generated floating mk=60 not found: {xml_path}")
    massbody = floating.find("massbody")
    center = floating.find("center")
    inertia = floating.find("inertia")
    if massbody is None or center is None or inertia is None:
        raise ValueError(f"generated floating contract incomplete: {xml_path}")
    actual_center = [float(center.attrib[axis]) for axis in ("x", "y", "z")]
    actual_inertia = [float(inertia.attrib[axis]) for axis in ("x", "y", "z")]
    return {
        "massbody_kg": float(massbody.attrib["value"]),
        "center_m": actual_center,
        "inertia_diag_kg_m2": actual_inertia,
        "source_xml": str(xml_path.resolve()),
        "source_xml_sha256": MODULE.sha256(xml_path),
        "exact_massbody": abs(float(massbody.attrib["value"]) - 128.0) <= 1.0e-12,
        "exact_center": all(abs(a - b) <= 1.0e-12 for a, b in zip(actual_center, RIGID_CENTER)),
        "explicit_inertia_matches_frozen_contract": all(abs(a - b) <= 2.0e-5 for a, b in zip(actual_inertia, RIGID_INERTIA)),
        "explicit_contract_present": True,
    }


def audit() -> dict[str, object]:
    MODULE._partvtk_counts = _load_partvtk_counter()
    base = MODULE.audit()
    manifest = MODULE.read_json(MODULE.FAMILY_ROOT / "manifest.json")
    by_case = {case["case_id"]: case for case in manifest["cases"]}
    rigid_rows: list[dict[str, object]] = []
    for row in base["cases"]:
        case = by_case[row["case_id"]]
        gen_attempt = str(case["request"]["attempt_id"])
        xml = MODULE._attempt_root(row["case_id"], gen_attempt) / f"{row['case_id']}.xml"
        generated = _generated_contract(xml)
        row["generated_xml_rigid_contract"] = generated
        row["checks"]["generated_native_mass_center_inertia_exact"] = all((generated["exact_massbody"], generated["exact_center"], generated["explicit_inertia_matches_frozen_contract"], generated["explicit_contract_present"]))
        row["preflight_pass"] = all(row["checks"].values())
        rigid_rows.append(row)
    result = {
        "schema": "ds-data-02.f6.rigid_contract_003.audit.v1", "family_id": "F6", "created_at": MODULE.now(),
        "status": "all_six_generated_native_rigid_contract_pass" if all(row["preflight_pass"] for row in rigid_rows) else "generated_native_rigid_contract_failed",
        "continuous_geometry": {"fluid_volume_m3": 5.12, "strict_fluid_mass_kg": 5120.0, "body_center_m": RIGID_CENTER, "body_massbody_kg": 128.0, "body_inertia_diag_kg_m2": RIGID_INERTIA},
        "supersedes": "commensurate_mother/partvtk_002 strict audit did not inspect generated XML floating center/inertia",
        "cases": rigid_rows, "gpu_launch": False,
        "q_i_status": "generated_xml_and_typed_initial_state_preflight_only", "q_n_status": "pending_root_solver_and_native_postprocessing",
    }
    MODULE.write_json(MODULE.FAMILY_ROOT / "strict_rigid_contract_audit.json", result)
    return result


def make_solver_requests() -> dict[str, object]:
    audit_result = MODULE.read_json(MODULE.FAMILY_ROOT / "strict_rigid_contract_audit.json")
    if audit_result.get("status") != "all_six_generated_native_rigid_contract_pass":
        raise RuntimeError("generated native rigid contract is not fully passing")
    manifest = MODULE.read_json(MODULE.FAMILY_ROOT / "manifest.json")
    audit_by_case = {row["case_id"]: row for row in audit_result["cases"]}
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
        generated = [prefix.with_suffix(ext) for ext in (".xml", ".bi4")] + [prefix.with_name(prefix.name + suffix) for suffix in ("_All.vtk", "_Fluid.vtk")]
        input_paths = [SCRIPT, V9, V5, V4, V3, V2, V1, MODULE.RUNTIME_V2, Path(case["definition"]["path"]), Path(case["control"]["path"]), Path(case["native"]["path"]), Path(case["normal"]["path"]), Path(case["official_template"]["path"]), MODULE.GENCASE, MODULE.PARTVTK, MODULE.SOLVER, MODULE.FLOATING_INFO, MODULE.COMPUTE_FORCES, gen_receipt, partvtk_receipt, partvtk_csv, MODULE.FAMILY_ROOT / "strict_rigid_contract_audit.json", *generated]
        input_paths = [path for path in input_paths if path.is_file()]
        total = int(audit_by_case[cid]["gencase"]["total_particles"] or 0)
        fluid = int(audit_by_case[cid]["gencase"]["fluid_particles"] or 0)
        gpu_seconds = max(120, min(600, int(total / 1500 + 90)))
        request = {
            "schema": "ds-data-02.runner.request.v1", "family_id": "F6", "case_id": cid, "attempt_id": f"{cid}_SOLVER_QUAL_003", "kind": "qualification",
            "command": [str(MODULE.SOLVER.resolve()), str(prefix.resolve()), "{attempt_root}/solver_output", "-tmax:12", "-tout:0.05"], "cwd": str(gen_root.resolve()), "max_wall_seconds": 600, "cpu_threads": 4,
            "estimated_peak_gpu_mib": 4096, "estimated_storage_bytes": 2147483648, "worktree_root": str(MODULE.REPO_ROOT.resolve()), "input_files": [str(path.resolve()) for path in input_paths],
            "generator_version": MODULE.VERSION, "mechanism_id": case["mechanism_id"], "resolution_id": case["resolution_id"], "launch_commit_required": "root records dispatch commit; F6 owner does not launch GPU",
            "gencase_receipt": str(gen_receipt.resolve()), "gencase_receipt_sha256": MODULE.sha256(gen_receipt), "partvtk_receipt": str(partvtk_receipt.resolve()), "partvtk_receipt_sha256": MODULE.sha256(partvtk_receipt),
            "gencase_actual_particles": {"total": total, "fluid": fluid, "fixed": audit_by_case[cid]["actual_type_counts"]["fixed"], "moving": audit_by_case[cid]["actual_type_counts"]["moving"], "floating": audit_by_case[cid]["actual_type_counts"]["floating"]},
            "generated_native_rigid_contract": audit_by_case[cid]["generated_xml_rigid_contract"], "cost_estimate": {"basis": "actual RIGID003 GenCase/PartVTK count", "estimated_gpu_seconds": gpu_seconds, "estimated_total_particles": total, "estimated_fluid_particles": fluid, "estimated_native_bytes": 536870912},
            "complete_event_window_s": [0.0, 12.0], "output_interval_s": 0.05, "solver_dimension_required": 3, "qualification_claim": "none_until_complete_window_and_native_rigid_audit", "q_n_status": "pending",
            "postprocessing_plan": {"floating_info": [str(MODULE.FLOATING_INFO.resolve()), "-dirdata", "{attempt_root}/solver_output/data", "-onlymk:50", "-savedata", "{attempt_root}/solver_output/floatinginfo/FloatingMotion"], "compute_forces": [str(MODULE.COMPUTE_FORCES.resolve()), "-dirdata", "{attempt_root}/solver_output/data", "-onlymk:50", "-savecsv", "{attempt_root}/solver_output/forces/FloatingForce"], "required_fields": ["pose", "orientation", "linear_velocity", "angular_velocity", "mass", "inertia", "force", "torque"], "postprocessors_pending_shared_cpu_execution": True},
            "solver_launch_authority": "root only through shared ds_data02_runtime_v2.py; F6 owner did not launch GPU",
        }
        path = MODULE.FAMILY_ROOT / "qualification_requests" / f"{cid}.json"
        MODULE.write_json(path, request)
        rows.append({"case_id": cid, "path": str(path.resolve()), "sha256": MODULE.sha256(path), "attempt_id": request["attempt_id"]})
    result = {"schema": "ds-data-02.f6.rigid_contract_003.solver_requests.v1", "status": "root_dispatch_pending", "created_at": MODULE.now(), "requests": rows, "gpu_launch": False, "q_n_status": "pending"}
    MODULE.write_json(MODULE.FAMILY_ROOT / "qualification_request_manifest.json", result)
    return result


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["make-partvtk-requests", "audit", "make-solver-requests"])
    args = parser.parse_args()
    if args.action == "make-partvtk-requests":
        result = make_partvtk_requests()
    elif args.action == "audit":
        result = audit()
    else:
        result = make_solver_requests()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
