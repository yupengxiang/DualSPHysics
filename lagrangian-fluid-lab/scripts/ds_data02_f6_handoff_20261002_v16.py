#!/usr/bin/env python3
"""F6 RIGID003 DOMAIN_XY_REPAIR_02 audit and post-processing request builder.

This module is additive.  It reads the six completed GenCase attempts for the
second numerical lattice-endpoint repair, audits every native fixed-wall face,
the type-3/mass ledger, and the serialized native rigid-body contract, then
prepares (without launching) four root-only coarse/fine solver requests.

It also records the two completed DOMAIN_X_REPAIR_01 medium solver runs and
prepares deferred native HDF5, FloatingInfo, ComputeForces, and label requests.
The medium solver bytes, old requests, and old receipts are never rewritten.
No GPU, solver, or conversion is started by this module.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
V15 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v15.py")
V14 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v14.py")
V13 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v13.py")
V12 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v12.py")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M15 = _load("f6_domain_xy_repair_02_v15_for_audit", V15)
M14 = _load("f6_domain_x_repair_01_v14_for_medium_audit", V14)
M12 = _load("f6_domain_diagnosis_v12_for_native_audit", V12)
MODULE = M15.MODULE

FAMILY_ROOT = M15.MODULE.FAMILY_ROOT
RAW_ROOT = M15.MODULE.RAW_FAMILY_ROOT
RUNTIME_V2 = M15.MODULE.RUNTIME_V2
GENCASE = M15.MODULE.GENCASE
SOLVER = M15.MODULE.SOLVER
OFFICIAL_BIN = SOLVER.parent
FLOATING_INFO = OFFICIAL_BIN / "FloatingInfo_linux64"
COMPUTE_FORCES = OFFICIAL_BIN / "ComputeForces_linux64"
OFFICIAL_TEMPLATE = OFFICIAL_BIN / "DsphConfig.xml"
DIAGNOSIS = M15.DIAGNOSIS_SIDECAR

INTEGRATION_LAB = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
INTEGRATION_PYTHON = INTEGRATION_LAB / ".venv/bin/python"
CONVERTER = INTEGRATION_LAB / "scripts/ds_data02_f6_stage8_convert.py"
LABELS = INTEGRATION_LAB / "scripts/ds_data02_native_labels.py"
NATIVE_LABELS = INTEGRATION_LAB / "scripts/ds_data02_native_labels.py"
SIMPLE_LABEL_CONFIG = INTEGRATION_LAB / "campaigns/ds-data-02/families/F6/labels/simple_free_response_event_config.json"
WAVE_LABEL_CONFIG = INTEGRATION_LAB / "campaigns/ds-data-02/families/F6/labels/wave_no_contact_event_config.json"

AUDIT_PATH = FAMILY_ROOT / "all_dp_preflight_001.json"
REQUEST_ROOT = FAMILY_ROOT / "qualification_requests_001"
POST_ROOT = FAMILY_ROOT / "postprocessing_001"
MEDIUM_AUDIT_PATH = POST_ROOT / "medium_solver_terminal_audit_001.json"
POST_REQUEST_ROOT = POST_ROOT / "execution_requests"
MECHANISMS = ("simple_free_response", "wave_no_contact")
RESOLUTIONS = ("coarse", "medium", "fine")
GPU_RESOLUTIONS = ("coarse", "fine")
EXPECTED_CENTER = [2.4, 1.2, 1.08]
EXPECTED_INERTIA_SERIALIZED = [8.53333, 8.53333, 13.6533]
EXPECTED_INERTIA_ANALYTIC = [8.533333333333335, 8.533333333333335, 13.653333333333336]
EXPECTED_MASSBODY = 128.0
EXPECTED_FLUID_MASS = 5120.000000000001
EXPECTED_TANK_POSMIN = [0.0, 0.0, 0.0]
EXPECTED_TANK_POSMAX = [4.8, 2.4, 2.4]


def sha256(path: Path) -> str:
    return MODULE.sha256(Path(path))


def write_json(path: Path, value: Any) -> None:
    MODULE.write_json(Path(path), value)


def read_json(path: Path) -> dict[str, Any]:
    return MODULE.read_json(Path(path))


def _manifest() -> dict[str, Any]:
    return read_json(FAMILY_ROOT / "manifest.json")


def _case(manifest: dict[str, Any], mechanism: str, resolution: str) -> dict[str, Any]:
    for row in manifest["cases"]:
        if row["mechanism_id"] == mechanism and row["resolution_id"] == resolution:
            return row
    raise KeyError((mechanism, resolution))


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


def _xml_contract(xml_path: Path) -> dict[str, Any]:
    root = ET.parse(xml_path).getroot()
    particles = root.find("./execution/particles")
    constants = root.find("./execution/constants")
    simdomain = root.find("./execution/parameters/simulationdomain")
    data2d = constants.find("data2d") if constants is not None else None
    summary = particles.find("_summary") if particles is not None else None
    floating = particles.find("floating") if particles is not None else None
    if particles is None or constants is None or summary is None or floating is None:
        raise ValueError(f"generated XML lacks native contract blocks: {xml_path}")

    def count(tag: str) -> int:
        node = summary.find(tag)
        return int(node.get("count", "0")) if node is not None else 0

    def scalar(tag: str, name: str = "value") -> float:
        node = constants.find(tag)
        if node is None or node.get(name) is None:
            raise ValueError(f"missing {tag}.{name} in {xml_path}")
        return float(node.get(name))

    massbody = float(floating.find("massbody").get("value"))
    masspart = float(floating.find("masspart").get("value"))
    center_node = floating.find("center")
    inertia_node = floating.find("inertia")
    center = [float(center_node.get(axis)) for axis in "xyz"]
    inertia = [float(inertia_node.get(axis)) for axis in "xyz"]
    positions = summary.find("positions")
    posmin = [float(positions.find("posmin").get(axis)) for axis in "xyz"]
    posmax = [float(positions.find("posmax").get(axis)) for axis in "xyz"]
    return {
        "path": str(xml_path.resolve()),
        "sha256": sha256(xml_path),
        "particle_np": int(particles.get("np")),
        "particle_nb": int(particles.get("nb")),
        "particle_nbf": int(particles.get("nbf")),
        "type_counts": {
            "fixed": count("fixed"),
            "moving": count("moving"),
            "floating": count("floating"),
            "fluid": count("fluid"),
        },
        "positions_bounds_m": {"posmin": posmin, "posmax": posmax},
        "fluid_mass_per_particle_kg": scalar("massfluid"),
        "bound_mass_per_particle_kg": scalar("massbound"),
        "native_initial_mass_ledger": {
            "fluid_type3_count": count("fluid"),
            "fluid_mass_per_particle_kg": scalar("massfluid"),
            "fluid_mass_kg": count("fluid") * scalar("massfluid"),
            "floating_type2_count": count("floating"),
            "floating_masspart_kg": masspart,
            "floating_type2_massbound_sum_kg": count("floating") * masspart,
            "floating_massbody_aggregate_kg": massbody,
            "aggregate_massbody_is_distinct_from_type2_particle_sum": True,
        },
        "floating_contract": {
            "massbody_kg": massbody,
            "masspart_kg": masspart,
            "center_m": center,
            "inertia_diag_kg_m2": inertia,
        },
        "solver_dimension": 2 if data2d is not None and data2d.get("value", "true").lower() == "true" else 3,
        "simulationdomain_source": {
            "posmin": dict(simdomain.find("posmin").attrib) if simdomain is not None else None,
            "posmax": dict(simdomain.find("posmax").attrib) if simdomain is not None else None,
        },
    }


def _audit_gencase(case: dict[str, Any]) -> dict[str, Any]:
    paths = _generated_paths(case)
    required = [paths[key] for key in ("receipt", "xml", "bi4", "out", "all_vtk", "bound_vtk", "fluid_vtk", "mkcells_vtk", "dp_vtk")]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("DOMAIN_XY_REPAIR_02 GenCase output missing: " + ", ".join(missing))
    receipt = read_json(paths["receipt"])
    contract = _xml_contract(paths["xml"])
    bound = M12._decode_bound_vtk(paths["bound_vtk"], dp=float(case["dp_m"]))
    expected_fluid = int(case["expected_fluid_particles"])
    expected_moving = 0 if case["mechanism_id"] == "simple_free_response" else 1
    mass = contract["native_initial_mass_ledger"]
    checks = {
        "gencase_completed": receipt.get("status") == "completed" and receipt.get("returncode") == 0,
        "actual_3d": receipt.get("solver_dimension_from_gencase") == 3 and contract["solver_dimension"] == 3,
        "positive_fluid_type3": contract["type_counts"]["fluid"] == expected_fluid and receipt.get("fluid_particles") == expected_fluid,
        "positive_floating_type2": contract["type_counts"]["floating"] > 0 and bound["type_counts"].get("floating", 0) == contract["type_counts"]["floating"],
        "moving_paddle_present_or_absent": (contract["type_counts"]["moving"] > 0) == bool(expected_moving),
        "finite_wall_faces_complete": bound["fixed_face_coverage"]["all_declared_faces_nonzero"],
        "all_physical_wall_endpoints_represented": bound["fixed_points_bounds_m"] == [
            [0.0, 4.800000190734863],
            [0.0, 2.4000000953674316],
            [0.0, 2.4000000953674316],
        ],
        "continuous_tank_extent_unchanged": all(abs(a - b) <= 1.0e-6 for a, b in zip(contract["positions_bounds_m"]["posmin"], EXPECTED_TANK_POSMIN))
        and all(abs(a - b) <= 1.0e-6 for a, b in zip(contract["positions_bounds_m"]["posmax"], EXPECTED_TANK_POSMAX)),
        "strict_fluid_mass_exact": abs(mass["fluid_mass_kg"] - float(case["expected_fluid_mass_kg"])) <= 1.0e-9,
        "aggregate_massbody_exact": abs(contract["floating_contract"]["massbody_kg"] - EXPECTED_MASSBODY) <= 1.0e-12,
        "aggregate_center_exact": all(abs(a - b) <= 1.0e-12 for a, b in zip(contract["floating_contract"]["center_m"], EXPECTED_CENTER)),
        "aggregate_inertia_serialized_exact": all(abs(a - b) <= 1.0e-12 for a, b in zip(contract["floating_contract"]["inertia_diag_kg_m2"], EXPECTED_INERTIA_SERIALIZED)),
        "type2_mass_is_separate": mass["aggregate_massbody_is_distinct_from_type2_particle_sum"] and abs(mass["floating_massbody_aggregate_kg"] - mass["floating_type2_massbound_sum_kg"]) > 1.0e-6,
        "source_hashes_recorded": bool(receipt.get("input_hashes_after_run")),
    }
    return {
        "case_id": case["case_id"],
        "mechanism_id": case["mechanism_id"],
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
        "generated_native_contract": contract,
        "native_boundary_vtk": bound,
        "expected": {
            "fluid_particles": expected_fluid,
            "fluid_mass_kg": float(case["expected_fluid_mass_kg"]),
            "finite_wall_faces": ["bottom", "left", "right", "front", "back"],
            "aggregate_massbody_kg": EXPECTED_MASSBODY,
            "aggregate_center_m": EXPECTED_CENTER,
            "aggregate_inertia_diag_kg_m2": EXPECTED_INERTIA_ANALYTIC,
            "particle_type2_mass_is_not_aggregate_mass": True,
        },
        "checks": checks,
        "preflight_pass": all(checks.values()),
        "repair_scope": {
            "repair_id": "F6_HANDOFF_20261002_RIGID003_DOMAIN_XY_REPAIR_02",
            "prior_repair_id": "F6_HANDOFF_20261002_RIGID003_DOMAIN_X_REPAIR_01",
            "same_root_cause_repair_count": 2,
            "root_cause": "coarse pointmax.y=2.48 rasterized through y=2.32, leaving the declared physical y=2.4 wall endpoint absent",
            "change": "coarse numerical pointmax.y=2.56; continuous tank/fluid/body/paddle and explicit rigid contract unchanged",
            "no_density_threshold_or_domain_opening": True,
        },
        "qualification_claim": "none; native GenCase preflight only",
    }


def audit_all_dp() -> dict[str, Any]:
    manifest = _manifest()
    rows = [_audit_gencase(_case(manifest, mechanism, resolution)) for mechanism in MECHANISMS for resolution in RESOLUTIONS]
    result = {
        "schema": "ds-data-02.f6.rigid003_domain_xy_repair_02.all_dp_preflight_001.v1",
        "family_id": "F6",
        "created_at": MODULE.now(),
        "repair_id": "F6_HANDOFF_20261002_RIGID003_DOMAIN_XY_REPAIR_02",
        "status": "all_six_native_preflight_pass" if all(row["preflight_pass"] for row in rows) else "native_preflight_failed",
        "cases": rows,
        "physical_geometry_contract": manifest.get("physical_geometry_contract"),
        "source_lineage": {
            "generator": str(SCRIPT.resolve()),
            "generator_sha256": sha256(SCRIPT),
            "v15_sha256": sha256(V15),
            "v14_sha256": sha256(V14),
            "v13_sha256": sha256(V13),
            "v12_sha256": sha256(V12),
            "diagnosis_sidecar": str(DIAGNOSIS.resolve()),
            "diagnosis_sidecar_sha256": sha256(DIAGNOSIS),
            "runtime_v2": str(RUNTIME_V2.resolve()),
            "runtime_v2_sha256": sha256(RUNTIME_V2),
        },
        "gpu_launch": False,
        "q_i_status": "native_gencase_boundary_mass_rigid_preflight_only",
        "q_n_status": "pending_root_gpu_and_native_postprocessing",
        "production_claim": "none",
    }
    write_json(AUDIT_PATH, result)
    return result


def _solver_input_paths(case: dict[str, Any], audit_row: dict[str, Any]) -> list[Path]:
    paths = _generated_paths(case)
    receipt = read_json(paths["receipt"])
    values: list[Path] = [SCRIPT, V15, V14, V13, V12, RUNTIME_V2, SOLVER, GENCASE, OFFICIAL_TEMPLATE, DIAGNOSIS, AUDIT_PATH]
    values.extend(Path(value) for value in receipt.get("request", {}).get("input_files", []))
    values.extend(paths[key] for key in ("receipt", "xml", "bi4", "out", "all_vtk", "bound_vtk", "fluid_vtk", "mkcells_vtk", "dp_vtk"))
    unique: list[Path] = []
    seen: set[str] = set()
    for value in values:
        resolved = str(value.resolve())
        if resolved not in seen:
            seen.add(resolved)
            unique.append(Path(resolved))
    missing = [str(value) for value in unique if not value.is_file()]
    if missing:
        raise FileNotFoundError("solver request input missing: " + ", ".join(missing))
    return unique


def make_solver_requests() -> dict[str, Any]:
    audit = read_json(AUDIT_PATH)
    if audit.get("status") != "all_six_native_preflight_pass":
        raise RuntimeError("all six DOMAIN_XY_REPAIR_02 native preflights must pass before GPU requests")
    manifest = _manifest()
    rows = []
    for mechanism in MECHANISMS:
        for resolution in GPU_RESOLUTIONS:
            case = _case(manifest, mechanism, resolution)
            audit_row = next(row for row in audit["cases"] if row["case_id"] == case["case_id"])
            paths = _generated_paths(case)
            inputs = _solver_input_paths(case, audit_row)
            cid = str(case["case_id"])
            request_path = REQUEST_ROOT / f"{cid}.json"
            request = {
                "schema": "ds-data-02.runner.request.v1",
                "family_id": "F6",
                "case_id": cid,
                "attempt_id": f"{cid}_SOLVER_QUAL_001",
                "kind": "qualification",
                "command": [str(SOLVER.resolve()), str(paths["prefix"].resolve()), "{attempt_root}/solver_output", "-tmax:12", "-tout:0.05"],
                "cwd": str(paths["root"].resolve()),
                "max_wall_seconds": 600,
                "cpu_threads": 4,
                "estimated_peak_gpu_mib": 4096,
                "estimated_storage_bytes": 2147483648,
                "input_files": [str(path.resolve()) for path in inputs],
                "input_hashes_at_request": {str(path.resolve()): sha256(path) for path in inputs},
                "worktree_root": str(MODULE.REPO_ROOT.resolve()),
                "generator_version": M15.MODULE.VERSION,
                "mechanism_id": mechanism,
                "resolution_id": resolution,
                "repair_id": "F6_HANDOFF_20261002_RIGID003_DOMAIN_XY_REPAIR_02",
                "launch_authority": "root only through shared ds_data02_runtime_v2.py; F6 owner does not launch GPU",
                "gencase_receipt": str(paths["receipt"].resolve()),
                "gencase_receipt_sha256": sha256(paths["receipt"]),
                "preflight": str(AUDIT_PATH.resolve()),
                "preflight_sha256": sha256(AUDIT_PATH),
                "gencase_actual_particles": {
                    "total": audit_row["gencase"]["total_particles"],
                    "fluid": audit_row["gencase"]["fluid_particles"],
                    "fixed": audit_row["generated_native_contract"]["type_counts"]["fixed"],
                    "moving": audit_row["generated_native_contract"]["type_counts"]["moving"],
                    "floating": audit_row["generated_native_contract"]["type_counts"]["floating"],
                },
                "strict_initial_mass_contract": audit_row["generated_native_contract"]["native_initial_mass_ledger"],
                "generated_native_rigid_contract": audit_row["generated_native_contract"]["floating_contract"],
                "native_boundary_contract": {
                    "fixed_face_coverage": audit_row["native_boundary_vtk"]["fixed_face_coverage"],
                    "fixed_points_bounds_m": audit_row["native_boundary_vtk"]["fixed_points_bounds_m"],
                    "continuous_tank_extent_m": [EXPECTED_TANK_POSMIN, EXPECTED_TANK_POSMAX],
                },
                "runtime_prefix_contract": {
                    "prefix_directory": str(paths["root"].resolve()),
                    "xml": str(paths["xml"].resolve()),
                    "bi4": str(paths["bi4"].resolve()),
                    "xml_external_references": [],
                    "all_xml_references_resolve_from_prefix": True,
                    "control_native_normal_hash_bound": True,
                },
                "complete_event_window_s": [0.0, 12.0],
                "output_interval_s": 0.05,
                "solver_dimension_required": 3,
                "cost_estimate": {
                    "basis": "actual DOMAIN_XY_REPAIR_02 GenCase receipt",
                    "estimated_total_particles": audit_row["gencase"]["total_particles"],
                    "estimated_fluid_particles": audit_row["gencase"]["fluid_particles"],
                    "estimated_gpu_seconds": max(120, min(600, int(int(audit_row["gencase"]["total_particles"]) / 1500 + 90))),
                    "estimated_native_bytes": 536870912,
                },
                "postprocessing_pending": [
                    "full native BI4-to-HDF5 trajectory with fixed typed identity axis",
                    "FloatingInfo full pose/orientation/quaternion/linear-angular velocity",
                    "ComputeForces force/torque",
                    "native label materialization and finite-event audit",
                ],
                "qualification_claim": "none; request pending root dispatch and terminal native review",
            }
            write_json(request_path, request)
            rows.append({"path": str(request_path.resolve()), "sha256": sha256(request_path), "case_id": cid, "attempt_id": request["attempt_id"]})
    result = {
        "schema": "ds-data-02.f6.rigid003_domain_xy_repair_02.qualification_requests_001.v1",
        "status": "root_dispatch_pending",
        "created_at": MODULE.now(),
        "requests": rows,
        "gpu_launch": False,
        "q_n_status": "pending",
    }
    write_json(REQUEST_ROOT / "request_manifest.json", result)
    return result


def _numeric_runparts(runparts: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with runparts.open(newline="", encoding="utf-8", errors="replace") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            try:
                float(row.get("TimeStep [s]", ""))
            except (TypeError, ValueError):
                continue
            rows.append(row)
    return rows


def _float_value(row: dict[str, str], key: str) -> float:
    return float(row[key].replace(",", ""))


def _tree_manifest(data_root: Path) -> dict[str, Any]:
    files = []
    for path in sorted(p for p in data_root.rglob("*") if p.is_file()):
        files.append({"path": path.relative_to(data_root).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)})
    digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    frames = sorted(int(match.group(1)) for entry in files if (match := re.match(r"^Part_(\d{4,})\.bi4$", Path(entry["path"]).name)) and Path(entry["path"]).parent == Path("."))
    return {"schema": "ds-data-02.f6.native-data-tree-manifest.v1", "root": str(data_root.resolve()), "file_count": len(files), "files": files, "tree_sha256": digest, "frame_indices": frames}


def _old_medium_case(mechanism: str) -> dict[str, Any]:
    manifest = read_json(M14.FAMILY_ROOT / "manifest.json")
    return next(row for row in manifest["cases"] if row["mechanism_id"] == mechanism and row["resolution_id"] == "medium")


def _old_medium_paths(case: dict[str, Any]) -> dict[str, Path]:
    paths = M14._generated_paths(case)
    # The solver attempt is a sibling of the immutable GenCase attempt inside
    # the case directory.  It is not a direct child of the family root.
    case_root = RAW_ROOT / str(case["case_id"])
    solver_root = case_root / f"{case['case_id']}_SOLVER_QUAL_001"
    return {
        "gencase_root": paths["root"],
        "gencase_prefix": paths["prefix"],
        "gencase_receipt": paths["receipt"],
        "xml": paths["xml"],
        "solver_root": solver_root,
        "solver_receipt": solver_root / "execution-receipt.json",
        "solver_output": solver_root / "solver_output",
        "data": solver_root / "solver_output/data",
        "runout": solver_root / "solver_output/Run.out",
        "runparts": solver_root / "solver_output/RunPARTs.csv",
    }


def _audit_medium_case(mechanism: str) -> dict[str, Any]:
    case = _old_medium_case(mechanism)
    paths = _old_medium_paths(case)
    required = [paths[key] for key in ("gencase_receipt", "xml", "solver_receipt", "runout", "runparts")]
    required.extend([paths["data"] / name for name in ("Part_0000.bi4", "Part_0240.bi4", "Part_Head.ibi4", "PartFloatInfo.ibi4", "PartMotionRef.ibi4")])
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("medium postprocessing source missing: " + ", ".join(missing))
    solver_receipt = read_json(paths["solver_receipt"])
    gencase_receipt = read_json(paths["gencase_receipt"])
    rows = _numeric_runparts(paths["runparts"])
    if not rows:
        raise ValueError(f"no numeric RunPARTs rows: {paths['runparts']}")
    cumulative = {key: int(sum(_float_value(row, key) for row in rows)) for key in ("NpOut", "NpOutPos", "NpOutRho", "NpOutMov")}
    frame_paths = sorted(paths["data"].glob("Part_*.bi4"), key=lambda path: int(re.search(r"(\d+)", path.stem).group(1)))
    frame_indices = [int(re.search(r"(\d+)", path.stem).group(1)) for path in frame_paths]
    xml = _xml_contract(paths["xml"])
    raw_manifest_path = POST_ROOT / "raw_tree_manifests" / f"{mechanism}_medium.json"
    write_json(raw_manifest_path, _tree_manifest(paths["data"]))
    runout = paths["runout"].read_text(encoding="utf-8", errors="replace")
    map_lines = [line for line in runout.splitlines() if line.startswith("MapRealPos(")]
    final = rows[-1]
    checks = {
        "solver_completed_code0": solver_receipt.get("status") == "completed" and solver_receipt.get("returncode") == 0,
        "complete_12s_window": 12.0 <= _float_value(final, "TimeStep [s]") <= 12.01,
        "native_frame_count_241": len(frame_paths) == 241 and frame_indices == list(range(241)),
        "fixed_output_save_interval_0p05": len(rows) == 241,
        "all_exclusion_categories_accounted": cumulative["NpOut"] == cumulative["NpOutPos"] + cumulative["NpOutRho"] + cumulative["NpOutMov"],
        "initial_native_mass_contract": abs(xml["native_initial_mass_ledger"]["fluid_mass_kg"] - EXPECTED_FLUID_MASS) <= 1.0e-9,
        "rigid_contract_exact": abs(xml["floating_contract"]["massbody_kg"] - EXPECTED_MASSBODY) <= 1.0e-12
        and xml["floating_contract"]["center_m"] == EXPECTED_CENTER
        and all(abs(a - b) <= 1.0e-12 for a, b in zip(xml["floating_contract"]["inertia_diag_kg_m2"], EXPECTED_INERTIA_SERIALIZED)),
    }
    return {
        "case_id": case["case_id"],
        "mechanism_id": mechanism,
        "resolution_id": "medium",
        "solver_receipt": {"path": str(paths["solver_receipt"].resolve()), "sha256": sha256(paths["solver_receipt"]), "status": solver_receipt.get("status"), "returncode": solver_receipt.get("returncode"), "elapsed_seconds": solver_receipt.get("elapsed_seconds")},
        "gencase_receipt": {"path": str(paths["gencase_receipt"].resolve()), "sha256": sha256(paths["gencase_receipt"]), "status": gencase_receipt.get("status"), "total_particles": gencase_receipt.get("total_particles"), "fluid_particles": gencase_receipt.get("fluid_particles")},
        "runparts": {
            "path": str(paths["runparts"].resolve()),
            "sha256": sha256(paths["runparts"]),
            "numeric_rows": len(rows),
            "first_time_s": _float_value(rows[0], "TimeStep [s]"),
            "final_time_s": _float_value(final, "TimeStep [s]"),
            "final_np_save": int(_float_value(final, "NpSave")),
            "final_np_sim": int(_float_value(final, "NpSim")),
            "final_npb_sim": int(_float_value(final, "NpbSim")),
            "final_npf_sim": int(_float_value(final, "NpfSim")),
            "cumulative_exclusions": cumulative,
            "max_exclusions_per_frame": {key: int(max(_float_value(row, key) for row in rows)) for key in ("NpOut", "NpOutPos", "NpOutRho", "NpOutMov")},
        },
        "native_frames": {"data_root": str(paths["data"].resolve()), "frame_count": len(frame_paths), "frame_indices": frame_indices, "first_frame": str(frame_paths[0].resolve()), "last_frame": str(frame_paths[-1].resolve()), "tree_manifest": str(raw_manifest_path.resolve()), "tree_manifest_sha256": sha256(raw_manifest_path)},
        "runout": {"path": str(paths["runout"].resolve()), "sha256": sha256(paths["runout"]), "map_real_pos_lines": map_lines},
        "native_generated_contract": xml,
        "rigid_state_sources": {name: {"path": str((paths["data"] / name).resolve()), "sha256": sha256(paths["data"] / name), "bytes": (paths["data"] / name).stat().st_size} for name in ("PartFloatInfo.ibi4", "PartMotionRef.ibi4")},
        "checks": checks,
        "postprocessing_ready": all(checks.values()),
        "simple_exclusion_note": "one fluid position exclusion at approximately 0.450005 s; retain as negative evidence" if mechanism == "simple_free_response" and cumulative["NpOut"] else None,
        "q_n_status": "pending FloatingInfo/ComputeForces/native HDF5/labels and scientific review",
    }


def audit_medium_solver() -> dict[str, Any]:
    rows = [_audit_medium_case(mechanism) for mechanism in MECHANISMS]
    result = {
        "schema": "ds-data-02.f6.rigid003.domain_x_repair_01.medium_solver_terminal_audit_001.v1",
        "family_id": "F6",
        "created_at": MODULE.now(),
        "source_scope": "completed DOMAIN_X_REPAIR_01 medium solver outputs; old raw bytes immutable",
        "cases": rows,
        "status": "both_solver_terminal_reviewed",
        "qualification_claim": "none; terminal solver review only",
        "q_n_status": "pending native postprocessing and scientific acceptance",
    }
    write_json(MEDIUM_AUDIT_PATH, result)
    return result


def _post_common_inputs(row: dict[str, Any]) -> list[Path]:
    mechanism = row["mechanism_id"]
    case = _old_medium_case(mechanism)
    paths = _old_medium_paths(case)
    values = [SCRIPT, V15, V14, V13, V12, RUNTIME_V2, CONVERTER, LABELS, OFFICIAL_TEMPLATE, FLOATING_INFO, COMPUTE_FORCES, DIAGNOSIS, MEDIUM_AUDIT_PATH, Path(row["native_frames"]["tree_manifest"]), paths["gencase_receipt"], paths["xml"], paths["solver_receipt"], paths["runout"], paths["runparts"], paths["data"] / "Part_Head.ibi4", paths["data"] / "PartFloatInfo.ibi4", paths["data"] / "PartMotionRef.ibi4", paths["data"] / "PartOut_000.obi4", paths["data"] / "Part_0000.bi4", paths["data"] / "Part_0240.bi4", paths["gencase_prefix"].with_suffix(".bi4"), paths["gencase_prefix"].with_name(paths["gencase_prefix"].name + "_All.vtk"), paths["gencase_prefix"].with_name(paths["gencase_prefix"].name + "_Fluid.vtk")]
    unique = []
    seen = set()
    for value in values:
        path = Path(value).resolve()
        if str(path) not in seen:
            seen.add(str(path))
            unique.append(path)
    missing = [str(path) for path in unique if not path.is_file()]
    if missing:
        raise FileNotFoundError("postprocessing input missing: " + ", ".join(missing))
    return unique


def _cpu_request(base: dict[str, Any], path: Path) -> None:
    write_json(path, base)


def prepare_postprocessing_requests() -> dict[str, Any]:
    audit = read_json(MEDIUM_AUDIT_PATH)
    rows = audit.get("cases", [])
    if len(rows) != 2 or not all(row.get("postprocessing_ready") for row in rows):
        raise RuntimeError("both medium solver terminal audits must be ready before preparing postprocessing")
    POST_REQUEST_ROOT.mkdir(parents=True, exist_ok=True)
    requests = []
    for row in rows:
        mechanism = row["mechanism_id"]
        case = _old_medium_case(mechanism)
        paths = _old_medium_paths(case)
        cid = str(case["case_id"])
        inputs = _post_common_inputs(row)
        common = {
            "schema": "ds-data-02.runner.request.v1",
            "family_id": "F6",
            "case_id": cid,
            "mechanism_id": mechanism,
            "resolution_id": "medium",
            "source_solver_attempt": str(paths["solver_receipt"].resolve()),
            "source_solver_receipt_sha256": sha256(paths["solver_receipt"]),
            "source_raw_tree_manifest": row["native_frames"]["tree_manifest"],
            "source_raw_tree_manifest_sha256": row["native_frames"]["tree_manifest_sha256"],
            "input_hashes_at_request": {str(path): sha256(path) for path in inputs},
            "input_files": [str(path) for path in inputs],
            "worktree_root": str(MODULE.REPO_ROOT.resolve()),
            "cwd": str(INTEGRATION_LAB.resolve()),
            "source_hash_binding": "wrapper verifies the complete Part_*.bi4 data-tree manifest before and after the task; selected source files and all source provenance are hashed by runner",
            "q_n_status": "pending",
        }
        floating_attempt = f"{cid}_FLOATINGINFO_001"
        floating_request = {
            **common,
            "attempt_id": floating_attempt,
            "kind": "cpu",
            "cpu_task_kind": "audit",
            "cpu_threads": 2,
            "max_wall_seconds": 600,
            "estimated_storage_bytes": 268435456,
            "command": [str(INTEGRATION_PYTHON.resolve()), str(SCRIPT.resolve()), "run-floating-info", "--data-dir", str(paths["data"].resolve()), "--manifest", str(Path(row["native_frames"]["tree_manifest"]).resolve()), "--output-prefix", "{attempt_root}/floatinginfo/FloatingMotion"],
            "purpose": "official FloatingInfo full rigid pose/orientation/linear-angular velocity source audit; no solver/GPU",
            "required_state_fields": ["pose", "orientation", "quaternion", "linear_velocity", "angular_velocity"],
        }
        floating_path = POST_REQUEST_ROOT / f"{cid}_floatinginfo.json"
        _cpu_request(floating_request, floating_path)
        requests.append({"path": str(floating_path.resolve()), "sha256": sha256(floating_path), "kind": "floatinginfo", "case_id": cid})

        force_attempt = f"{cid}_COMPUTEFORCES_001"
        force_request = {
            **common,
            "attempt_id": force_attempt,
            "kind": "cpu",
            "cpu_task_kind": "audit",
            "cpu_threads": 2,
            "max_wall_seconds": 600,
            "estimated_storage_bytes": 268435456,
            "command": [str(INTEGRATION_PYTHON.resolve()), str(SCRIPT.resolve()), "run-compute-forces", "--data-dir", str(paths["data"].resolve()), "--manifest", str(Path(row["native_frames"]["tree_manifest"]).resolve()), "--generated-xml", str(paths["xml"].resolve()), "--output-prefix", "{attempt_root}/forces/FloatingForce"],
            "purpose": "official ComputeForces full floating-body force/torque audit; no solver/GPU",
            "required_state_fields": ["force", "torque", "massbody", "inertia"],
        }
        force_path = POST_REQUEST_ROOT / f"{cid}_computeforces.json"
        _cpu_request(force_request, force_path)
        requests.append({"path": str(force_path.resolve()), "sha256": sha256(force_path), "kind": "computeforces", "case_id": cid})

        conversion_attempt = f"{cid}_NATIVE_H5_001"
        conversion_request = {
            **common,
            "attempt_id": conversion_attempt,
            "kind": "cpu",
            "cpu_task_kind": "conversion",
            "cpu_threads": 4,
            "max_wall_seconds": 1800,
            "estimated_storage_bytes": 2147483648,
            "command": [str(INTEGRATION_PYTHON.resolve()), str(SCRIPT.resolve()), "run-native-conversion", "--case-id", cid, "--data-dir", str(paths["data"].resolve()), "--generated-xml", str(paths["xml"].resolve()), "--manifest", str(Path(row["native_frames"]["tree_manifest"]).resolve()), "--output", "{attempt_root}/trajectory.h5", "--report", "{attempt_root}/conversion-report.json"],
            "purpose": "full native BI4 to HDF5 conversion with fixed typed identity axis and complete rigid-body state; no solver/GPU",
            "required_outputs": ["trajectory.h5", "conversion-report.json"],
            "required_rigid_state_fields": ["pose", "orientation", "quaternion", "linear_velocity", "angular_velocity", "massbody", "inertia", "force", "torque"],
            "conversion_concurrency_note": "submit only when shared conversion slots permit; this request is prepared, not launched",
        }
        conversion_path = POST_REQUEST_ROOT / f"{cid}_native_h5.json"
        _cpu_request(conversion_request, conversion_path)
        requests.append({"path": str(conversion_path.resolve()), "sha256": sha256(conversion_path), "kind": "native_h5", "case_id": cid})

        conversion_output = RAW_ROOT / cid / conversion_attempt / "trajectory.h5"
        label_inputs = inputs + [CONVERTER, NATIVE_LABELS, SIMPLE_LABEL_CONFIG if mechanism == "simple_free_response" else WAVE_LABEL_CONFIG]
        label_inputs.append(conversion_output)
        label_attempt = f"{cid}_LABELS_001"
        label_request = {
            **common,
            "attempt_id": label_attempt,
            "kind": "cpu",
            "cpu_task_kind": "labels",
            "cpu_threads": 2,
            "max_wall_seconds": 900,
            "estimated_storage_bytes": 536870912,
            "command": [str(INTEGRATION_PYTHON.resolve()), str(SCRIPT.resolve()), "run-labels", "--source", str(conversion_output.resolve()), "--config", str((SIMPLE_LABEL_CONFIG if mechanism == "simple_free_response" else WAVE_LABEL_CONFIG).resolve()), "--output", "{attempt_root}/native-labels.h5"],
            "purpose": "native fixed-frame event labels after the new HDF5 exists; no solver/GPU",
            "input_files": [str(path.resolve()) for path in label_inputs],
            "input_hashes_at_request": {str(path.resolve()): (sha256(path) if path.is_file() else "deferred_until_native_h5_receipt") for path in label_inputs},
            "source_trajectory": str(conversion_output.resolve()),
            "source_trajectory_sha256": "deferred_until_native_h5_receipt",
            "deferred_until_attempt": conversion_attempt,
            "required_label_semantics": ["fluid_type3_only", "fixed_identity", "finite_saved_frame_chord_events", "mass_ledger", "no_model"],
        }
        label_path = POST_REQUEST_ROOT / f"{cid}_labels.json"
        _cpu_request(label_request, label_path)
        requests.append({"path": str(label_path.resolve()), "sha256": sha256(label_path), "kind": "labels", "case_id": cid, "deferred": True})

    result = {
        "schema": "ds-data-02.f6.rigid003.domain_x_repair_01.medium_postprocessing_requests_001.v1",
        "created_at": MODULE.now(),
        "status": "prepared_pending_shared_cpu_slots",
        "requests": requests,
        "gpu_launch": False,
        "conversion_launch": False,
        "q_n_status": "pending FloatingInfo/ComputeForces/native HDF5/labels and independent review",
        "production_claim": "none",
    }
    write_json(POST_ROOT / "request_manifest.json", result)
    return result


def _verify_tree(manifest_path: Path, data_dir: Path) -> None:
    expected = read_json(manifest_path)
    actual = _tree_manifest(data_dir)
    if actual["tree_sha256"] != expected["tree_sha256"] or actual["files"] != expected["files"]:
        raise RuntimeError(f"native source tree changed since audit: {data_dir}")


def _run_official_with_manifest(binary: Path, data_dir: Path, manifest: Path, output_prefix: Path, extra: list[str]) -> int:
    _verify_tree(manifest, data_dir)
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    # FloatingInfo and ComputeForces take the output path as the argument to
    # -savedata/-savecsv.  Keep the wrapper explicit so a path is never
    # silently interpreted as an unrelated positional option.
    command = [str(binary), "-dirdata", str(data_dir)]
    command.extend(str(output_prefix) if arg == "{output}" else arg for arg in extra)
    result = subprocess.run(command, cwd=output_prefix.parent, check=False)
    if result.returncode != 0:
        return result.returncode
    _verify_tree(manifest, data_dir)
    return 0


def _run_native_conversion(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir).resolve()
    manifest = Path(args.manifest).resolve()
    _verify_tree(manifest, data_dir)
    command = [str(INTEGRATION_PYTHON.resolve()), str(CONVERTER.resolve()), "--direct-run", "--case-id", args.case_id, "--data-dir", str(data_dir), "--generated-xml", str(Path(args.generated_xml).resolve()), "--output", str(Path(args.output).resolve()), "--report", str(Path(args.report).resolve())]
    result = subprocess.run(command, cwd=INTEGRATION_LAB, check=False)
    if result.returncode != 0:
        return result.returncode
    _verify_tree(manifest, data_dir)
    return 0


def _run_labels(args: argparse.Namespace) -> int:
    import importlib.util as util

    source = Path(args.source).resolve()
    output = Path(args.output).resolve()
    config = read_json(Path(args.config).resolve())
    spec = util.spec_from_file_location("f6_native_labels_for_handoff", NATIVE_LABELS)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load native label materializer")
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.materialize(source, output, config)
    receipt = {"schema": "ds02.f6.handoff.labels-receipt.v1", "source": str(source), "source_sha256": module.digest(source), "output": str(output), "output_sha256": result["sha256"], "status": "completed"}
    write_json(output.with_name("labels-receipt.json"), receipt)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["audit-all-dp", "make-solver-requests", "audit-medium-solver", "prepare-postprocessing", "run-floating-info", "run-compute-forces", "run-native-conversion", "run-labels"])
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output-prefix", type=Path)
    parser.add_argument("--case-id")
    parser.add_argument("--generated-xml", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    if args.action == "audit-all-dp":
        result = audit_all_dp()
    elif args.action == "make-solver-requests":
        result = make_solver_requests()
    elif args.action == "audit-medium-solver":
        result = audit_medium_solver()
    elif args.action == "prepare-postprocessing":
        result = prepare_postprocessing_requests()
    elif args.action == "run-floating-info":
        if not args.data_dir or not args.manifest or not args.output_prefix:
            parser.error("run-floating-info requires --data-dir, --manifest, and --output-prefix")
        return _run_official_with_manifest(FLOATING_INFO, args.data_dir.resolve(), args.manifest.resolve(), args.output_prefix.resolve(), ["-onlymk:60", "-savedata", "{output}", "-savemotion:1", "-csvsep:0"])
    elif args.action == "run-compute-forces":
        if not args.data_dir or not args.manifest or not args.output_prefix or not args.generated_xml:
            parser.error("run-compute-forces requires --data-dir, --manifest, --generated-xml, and --output-prefix")
        return _run_official_with_manifest(COMPUTE_FORCES, args.data_dir.resolve(), args.manifest.resolve(), args.output_prefix.resolve(), ["-filexml", str(args.generated_xml.resolve()), "-onlymk:60", "-viscoauto", "-gravity:0:0:-9.81", "-momentin_xyz:2.4:1.2:1.08", "-momentex_xyz:2.4:1.2:1.08", "-savecsv", "{output}", "-threads:2", "-csvsep:0"])
    elif args.action == "run-native-conversion":
        for name in ("case_id", "data_dir", "manifest", "generated_xml", "output", "report"):
            if getattr(args, name) is None:
                parser.error(f"run-native-conversion requires --{name.replace('_', '-')}")
        return _run_native_conversion(args)
    else:
        for name in ("source", "config", "output"):
            if getattr(args, name) is None:
                parser.error(f"run-labels requires --{name}")
        return _run_labels(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
