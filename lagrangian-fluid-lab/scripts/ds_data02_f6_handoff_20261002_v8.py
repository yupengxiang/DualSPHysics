#!/usr/bin/env python3
"""Rigid-state preflight and root-only qualification requests for F6.

This wrapper consumes the immutable PartVTK-002 outputs.  It records the
nonzero type-2 point-cloud inertia while keeping its MassBound particle sum
separate from the native aggregate massbody/inertia contract.  It also emits
solver requests without relying on a nonexistent PartVTK-001 receipt.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path


SCRIPT = Path(__file__).resolve()
V7 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v7.py")
SPEC = importlib.util.spec_from_file_location("f6_handoff_20261002_v7", V7)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load audit wrapper: {V7}")
MODULE_V7 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE_V7)
MODULE = MODULE_V7.MODULE
MODULE.SCRIPT = SCRIPT
MODULE.VERSION = "ds_data02_f6_handoff_20261002.commensurate_mother.solver_qual.v1"
V6 = V7.with_name("ds_data02_f6_handoff_20261002_v6.py")
V5 = V7.with_name("ds_data02_f6_handoff_20261002_v5.py")


def _typed_points(csv_path: Path) -> dict[int, list[tuple[float, float, float]]]:
    rows = list(csv.reader(csv_path.read_text(encoding="utf-8", errors="replace").splitlines()))
    hi = next(i for i, row in enumerate(rows) if row and any("type" in cell.lower() for cell in row))
    header = [cell.strip().lower() for cell in rows[hi]]
    type_col = next(i for i, cell in enumerate(header) if "type" == cell or cell.startswith("type"))
    x_col = next(i for i, cell in enumerate(header) if "pos.x" in cell)
    y_col = next(i for i, cell in enumerate(header) if "pos.y" in cell)
    z_col = next(i for i, cell in enumerate(header) if "pos.z" in cell)
    result: dict[int, list[tuple[float, float, float]]] = {0: [], 1: [], 2: [], 3: []}
    for row in rows[hi + 1:]:
        if len(row) <= max(type_col, x_col, y_col, z_col):
            continue
        try:
            kind = int(row[type_col].strip())
            point = (float(row[x_col]), float(row[y_col]), float(row[z_col]))
        except (ValueError, TypeError):
            continue
        if kind in result:
            result[kind].append(point)
    return result


def _inertia(points: list[tuple[float, float, float]], particle_mass: float) -> tuple[list[float], list[list[float]]]:
    if not points:
        raise ValueError("type-2 point cloud is empty")
    center = [sum(point[axis] for point in points) / len(points) for axis in range(3)]
    tensor = [[0.0, 0.0, 0.0] for _ in range(3)]
    for point in points:
        x, y, z = (point[axis] - center[axis] for axis in range(3))
        tensor[0][0] += particle_mass * (y * y + z * z)
        tensor[1][1] += particle_mass * (x * x + z * z)
        tensor[2][2] += particle_mass * (x * x + y * y)
        tensor[0][1] -= particle_mass * x * y
        tensor[1][0] = tensor[0][1]
        tensor[0][2] -= particle_mass * x * z
        tensor[2][0] = tensor[0][2]
        tensor[1][2] -= particle_mass * y * z
        tensor[2][1] = tensor[1][2]
    return center, tensor


def _bounds(points: list[tuple[float, float, float]]) -> list[list[float]] | None:
    if not points:
        return None
    return [[min(point[axis] for point in points), max(point[axis] for point in points)] for axis in range(3)]


def make_rigid_preflight() -> dict[str, object]:
    audit_path = MODULE.FAMILY_ROOT / "strict_partvtk_audit.json"
    audit = MODULE.read_json(audit_path)
    manifest = MODULE.read_json(MODULE.FAMILY_ROOT / "manifest.json")
    manifest_by_case = {row["case_id"]: row for row in manifest["cases"]}
    records: list[dict[str, object]] = []
    for row in audit["cases"]:
        cid = str(row["case_id"])
        csv_path = Path(row["partvtk"]["csv"])
        native_path = Path(manifest_by_case[cid]["native"]["path"])
        definition_path = Path(manifest_by_case[cid]["definition"]["path"])
        native = MODULE.read_json(native_path)
        points = _typed_points(csv_path)
        particle_mass = float(MODULE_V7._stats_particle_mass(csv_path)[0])
        type2_center, type2_inertia = _inertia(points[2], particle_mass)
        body_draw = next(
            node for node in ET.parse(definition_path).getroot().iter("drawbox")
            if "Native floatingtype=2 body" in node.attrib.get("cmt", "")
        )
        body_point = [float(body_draw.find("point").attrib[axis]) for axis in ("x", "y", "z")]
        body_size = [float(body_draw.find("size").attrib[axis]) for axis in ("x", "y", "z")]
        fluid_bounds = _bounds(points[3])
        body_bounds = [[body_point[axis], body_point[axis] + body_size[axis]] for axis in range(3)]
        fluid_top = float(native["fluid_ledger"]["continuous_box_low_m"][2]) + float(native["fluid_ledger"]["continuous_box_size_m"][2])
        body_bottom = body_point[2]
        records.append({
            "case_id": cid,
            "mechanism_id": row["mechanism_id"],
            "resolution_id": row["resolution_id"],
            "dp_m": row["dp_m"],
            "source": {
                "partvtk_csv": str(csv_path.resolve()),
                "partvtk_csv_sha256": MODULE.sha256(csv_path),
                "native_json": str(native_path.resolve()),
                "native_json_sha256": MODULE.sha256(native_path),
                "definition_xml": str(definition_path.resolve()),
                "definition_xml_sha256": MODULE.sha256(definition_path),
            },
            "native_aggregate_contract": {
                "floatingtype": native["rigid_body"]["floatingtype"],
                "massbody_kg": native["rigid_body"]["massbody_kg"],
                "source_inertia_kg_m2": native["rigid_body"]["source_inertia_kg_m2"],
                "initial_pose_center_m": native["rigid_body"]["initial_pose"]["center_m"],
                "state_fields_pending_solver": native["rigid_body"]["required_state_fields"],
            },
            "type2_massbound_particle_audit": {
                "count": len(points[2]),
                "particle_mass_kg_from_partvtk_stats": particle_mass,
                "particle_mass_sum_kg": len(points[2]) * particle_mass,
                "point_bounds_m": _bounds(points[2]),
                "point_centroid_m": type2_center,
                "point_cloud_inertia_kg_m2": type2_inertia,
                "nonzero_inertia": all(abs(type2_inertia[i][i]) > 1.0e-12 for i in range(3)),
                "is_not_native_aggregate_mass": True,
            },
            "initial_geometry_audit": {
                "body_point_m": body_point,
                "body_size_m": body_size,
                "body_bounds_m": body_bounds,
                "fluid_type3_bounds_m": fluid_bounds,
                "continuous_fluid_top_m": fluid_top,
                "body_bottom_m": body_bottom,
                "body_fluid_gap_m": body_bottom - fluid_top,
                "strict_initial_submerged_body_volume_m3": 0.0,
                "no_type3_body_overlap_by_z": body_bottom > fluid_top,
                "finite_3d_type3": row["checks"]["actual_3d"] and row["checks"]["positive_fluid_type3"],
            },
            "moving_paddle_particles": row["actual_type_counts"]["moving"],
            "preflight_status": "typed_initial_state_pass_pending_solver_native_state",
        })
    result = {
        "schema": "ds-data-02.f6.rigid-state-preflight.v1",
        "family_id": "F6",
        "created_at": MODULE.now(),
        "audit_source": str(audit_path.resolve()),
        "audit_source_sha256": MODULE.sha256(audit_path),
        "status": "all_six_typed_initial_rigid_preflight_pass",
        "continuous_mass_contract_kg": 5120.0,
        "aggregate_massbody_contract_kg": 128.0,
        "warning": "MassBound type-2 particle sums are diagnostic only; native aggregate mass/inertia and full pose/velocity/force/torque remain solver/FloatingInfo/ComputeForces evidence.",
        "records": records,
        "q_i_status": "preflight_only",
        "q_n_status": "pending_root_solver_and_native_postprocessing",
    }
    MODULE.write_json(MODULE.FAMILY_ROOT / "rigid_state_preflight.json", result)
    MODULE.write_json(MODULE.FAMILY_ROOT / "native_semantics_addendum_001.json", {
        "schema": "ds-data-02.f6.native-semantics-addendum.v1",
        "family_id": "F6",
        "source_native_bytes_preserved": True,
        "correction": "commensurate mother body bottom is z=0.88 m while continuous fluid top is z=0.84 m; the prior native JSON prose saying the faces equal was inherited text and is superseded by this additive sidecar.",
        "native_aggregate_massbody_kg": 128.0,
        "native_analytic_inertia_kg_m2": [[8.533333333333335, 0.0, 0.0], [0.0, 8.533333333333335, 0.0], [0.0, 0.0, 13.653333333333336]],
        "records": [{"case_id": item["case_id"], "body_fluid_gap_m": item["initial_geometry_audit"]["body_fluid_gap_m"], "type2_particle_mass_sum_kg": item["type2_massbound_particle_audit"]["particle_mass_sum_kg"]} for item in records],
    })
    return result


def _solver_request(case, audit_row):
    cid = str(case["case_id"])
    gen_attempt = str(case["request"]["attempt_id"])
    gen_root = MODULE._attempt_root(cid, gen_attempt)
    prefix = gen_root / cid
    gencase_receipt = gen_root / "execution-receipt.json"
    partvtk_attempt = f"{cid}_PARTVTK_002"
    partvtk_root = MODULE._attempt_root(cid, partvtk_attempt)
    partvtk_receipt = partvtk_root / "execution-receipt.json"
    partvtk_csv = partvtk_root / f"{cid}_initial_all.csv"
    generated = [prefix.with_suffix(ext) for ext in (".xml", ".bi4")] + [prefix.with_name(prefix.name + suffix) for suffix in ("_All.vtk", "_Fluid.vtk")]
    input_paths = [MODULE.SCRIPT, V7, V6, V5, MODULE.RUNTIME_V2, Path(case["definition"]["path"]), Path(case["control"]["path"]), Path(case["native"]["path"]), Path(case["normal"]["path"]), Path(case["official_template"]["path"]), MODULE.GENCASE, MODULE.PARTVTK, MODULE.SOLVER, MODULE.FLOATING_INFO, MODULE.COMPUTE_FORCES, gencase_receipt, partvtk_receipt, partvtk_csv, MODULE.FAMILY_ROOT / "rigid_state_preflight.json", MODULE.FAMILY_ROOT / "native_semantics_addendum_001.json", *generated]
    input_paths = [path for path in input_paths if path.is_file()]
    estimated_total = int(audit_row["gencase"]["total_particles"] or 0)
    estimated_fluid = int(audit_row["gencase"]["fluid_particles"] or 0)
    gpu_seconds = max(120, min(600, int(estimated_total / 1500 + 90)))
    attempt = f"{cid}_SOLVER_QUAL_001"
    return {
        "schema": "ds-data-02.runner.request.v1", "family_id": "F6", "case_id": cid, "attempt_id": attempt,
        "kind": "qualification", "command": [str(MODULE.SOLVER.resolve()), str(prefix.resolve()), "{attempt_root}/solver_output", "-tmax:12", "-tout:0.05"],
        "cwd": str(gen_root.resolve()), "max_wall_seconds": 600, "cpu_threads": 4, "estimated_peak_gpu_mib": 4096,
        "estimated_storage_bytes": 2147483648, "worktree_root": str(MODULE.REPO_ROOT.resolve()), "input_files": [str(path.resolve()) for path in input_paths],
        "generator_version": MODULE.VERSION, "mechanism_id": case["mechanism_id"], "resolution_id": case["resolution_id"],
        "launch_commit_required": "root records actual dispatch commit; F6 owner does not launch GPU",
        "gencase_receipt": str(gencase_receipt.resolve()), "gencase_receipt_sha256": MODULE.sha256(gencase_receipt),
        "partvtk_receipt": str(partvtk_receipt.resolve()), "partvtk_receipt_sha256": MODULE.sha256(partvtk_receipt),
        "gencase_actual_particles": {"total": estimated_total, "fluid": estimated_fluid, "fixed": audit_row["actual_type_counts"]["fixed"], "moving": audit_row["actual_type_counts"]["moving"], "floating": audit_row["actual_type_counts"]["floating"]},
        "cost_estimate": {"basis": "actual commensurate GenCase/PartVTK count", "estimated_gpu_seconds": gpu_seconds, "estimated_total_particles": estimated_total, "estimated_fluid_particles": estimated_fluid, "estimated_native_bytes": 536870912},
        "complete_event_window_s": list(MODULE.WINDOW), "output_interval_s": MODULE.OUTPUT_DT, "solver_dimension_required": 3,
        "qualification_claim": "none_until_complete_window_and_native_rigid_audit", "q_n_status": "pending",
        "postprocessing_plan": {"floating_info": [str(MODULE.FLOATING_INFO.resolve()), "-dirdata", "{attempt_root}/solver_output/data", "-onlymk:50", "-savedata", "{attempt_root}/solver_output/floatinginfo/FloatingMotion"], "compute_forces": [str(MODULE.COMPUTE_FORCES.resolve()), "-dirdata", "{attempt_root}/solver_output/data", "-onlymk:50", "-savecsv", "{attempt_root}/solver_output/forces/FloatingForce"], "required_fields": ["pose", "orientation", "linear_velocity", "angular_velocity", "mass", "inertia", "force", "torque"], "postprocessors_pending_shared_cpu_execution": True},
        "solver_launch_authority": "root only through shared ds_data02_runtime_v2.py; F6 owner did not launch GPU",
    }


MODULE._solver_request = _solver_request


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["rigid-preflight", "make-solver-requests"])
    args = parser.parse_args()
    result = make_rigid_preflight() if args.action == "rigid-preflight" else MODULE.make_solver_requests()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
