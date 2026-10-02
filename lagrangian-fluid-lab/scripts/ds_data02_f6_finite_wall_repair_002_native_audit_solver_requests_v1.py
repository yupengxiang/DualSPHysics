#!/usr/bin/env python3
"""Audit the executed F6 DP020 wall repair and register root-only solver jobs.

This module consumes only the two fresh ``repair_002`` GenCase attempts.  It
uses the shared finite-face sampler for physical interior, edge, and corner
coverage, checks the generated native XML/BI4 counts and mass contract, and
stages a co-located solver prefix whose only XML change is the explicitly
reviewed numerical simulation domain.  It never launches a solver or GPU.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
LAB_ROOT = SCRIPT.parents[1]
INTEGRATION_LAB = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
FACE_HELPER = INTEGRATION_LAB / "scripts/ds_data02_finite_faces_v1.py"
RUNTIME_V2 = INTEGRATION_LAB / "scripts/ds_data02_runtime_v2.py"
OFFICIAL_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4")
SOLVER = OFFICIAL_ROOT / "bin/linux/DualSPHysics5.4_linux64"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F6")
FAMILY_ROOT = LAB_ROOT / "campaigns/ds-data-02/families/F6"
REPAIR_ROOT = FAMILY_ROOT / "handoff_20261002/rigid_contract_003/dp020_dp0125_cpu_003/finite_wall_discretization_repair_002"
AUDIT_PATH = REPAIR_ROOT / "native_audit_001.json"
STAGE_MANIFEST_PATH = REPAIR_ROOT / "solver_domain_stage_001.json"
REQUEST_ROOT = REPAIR_ROOT / "solver_requests_001"
REQUEST_MANIFEST_PATH = REQUEST_ROOT / "request_manifest.json"
STAGE_ROOT = DATA_ROOT / "F6_HANDOFF_20261002_RIGID003_DP020_FINITE_WALL_REPAIR_002_DOMAIN_STAGE_001"
DOMAIN_LOW = [-0.25, -0.15, -0.15]
DOMAIN_HIGH = [5.10, 2.55, 3.05]
TANK_LOW = [0.0, 0.0, 0.0]
TANK_HIGH = [4.8, 2.4, 2.4]
DP = 0.02
EXPECTED_CENTER = [2.4, 1.2, 1.08]
EXPECTED_INERTIA = [8.53333333333, 8.53333333333, 13.6533333333]
EXPECTED_BODY_MASS = 128.0
EXPECTED_FLUID_MASS = 5120.0
EXPECTED_FLUID_COUNT = 640000
EXPECTED_FLOATING_COUNT = 35301
EXPECTED_FIXED_COUNT = 114004

_spec = importlib.util.spec_from_file_location("f6_finite_faces_v1", FACE_HELPER)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"cannot load finite-face helper: {FACE_HELPER}")
FACES = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(FACES)


CASES = [
    {
        "mechanism_id": "simple_free_response",
        "label": "SIMPLE_FREE_RESPONSE",
        "case_id": "F6_HANDOFF_20261002_SIMPLE_FREE_RESPONSE_RIGID003_EPSFREE002_PHASE003_DP020_FINITE_WALL_REPAIR_002",
        "expected_moving": 0,
    },
    {
        "mechanism_id": "wave_no_contact",
        "label": "WAVE_NO_CONTACT",
        "case_id": "F6_HANDOFF_20261002_WAVE_NO_CONTACT_RIGID003_EPSFREE002_PHASE003_DP020_FINITE_WALL_REPAIR_002",
        "expected_moving": 77408,
    },
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path = Path(path).resolve()
    if path.exists():
        raise FileExistsError(f"refusing to overwrite F6 native evidence: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def binding(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def git_head() -> str:
    return subprocess.run(["git", "-C", str(LAB_ROOT.parent), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()


def case_paths(case: dict[str, Any]) -> dict[str, Path]:
    case_id = case["case_id"]
    root = DATA_ROOT / case_id / f"{case_id}_GENCASE_001"
    prefix = root / case_id
    receipt = root / "execution-receipt.json"
    return {
        "root": root,
        "prefix": prefix,
        "receipt": receipt,
        "xml": prefix.with_suffix(".xml"),
        "bi4": prefix.with_suffix(".bi4"),
        "all_vtk": prefix.with_name(prefix.name + "_All.vtk"),
        "bound_vtk": prefix.with_name(prefix.name + "_Bound.vtk"),
        "fluid_vtk": prefix.with_name(prefix.name + "_Fluid.vtk"),
        "mkcells_vtk": prefix.with_name(prefix.name + "_MkCells.vtk"),
        "dp_vtk": prefix.with_name(prefix.name + "__Dp.vtk"),
    }


def stage_paths(case: dict[str, Any]) -> dict[str, Path]:
    root = STAGE_ROOT / case["case_id"]
    prefix = root / case["case_id"]
    return {
        "root": root,
        "prefix": prefix,
        "xml": prefix.with_suffix(".xml"),
        "bi4": prefix.with_suffix(".bi4"),
        "all_vtk": prefix.with_name(prefix.name + "_All.vtk"),
        "bound_vtk": prefix.with_name(prefix.name + "_Bound.vtk"),
        "fluid_vtk": prefix.with_name(prefix.name + "_Fluid.vtk"),
        "mkcells_vtk": prefix.with_name(prefix.name + "_MkCells.vtk"),
        "dp_vtk": prefix.with_name(prefix.name + "__Dp.vtk"),
    }


def _prefix_from_request(case: dict[str, Any]) -> Path:
    request_path = REPAIR_ROOT / "gencase_requests" / f"{case['case_id']}_gencase.json"
    request = read_json(request_path)
    receipt = case_paths(case)["receipt"]
    if request.get("attempt_id") != receipt.parent.name:
        raise ValueError(f"GenCase request/receipt attempt mismatch for {case['case_id']}")
    return request_path


def stage_case(case: dict[str, Any]) -> dict[str, Any]:
    source = case_paths(case)
    target = stage_paths(case)
    required = [source[key] for key in ("xml", "bi4", "all_vtk", "bound_vtk", "fluid_vtk", "mkcells_vtk", "dp_vtk")]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("completed GenCase native files missing: " + ", ".join(missing))
    if target["root"].exists():
        raise FileExistsError(f"refusing to overwrite domain stage: {target['root']}")
    target["root"].mkdir(parents=True, exist_ok=False)
    copied: list[dict[str, Any]] = []
    for key in ("bi4", "all_vtk", "bound_vtk", "fluid_vtk", "mkcells_vtk", "dp_vtk"):
        shutil.copy2(source[key], target[key])
        copied.append({"name": key, "source": binding(source[key], "immutable repair_002 native output"), "staged": binding(target[key], "co-located solver native input")})
    source_xml = source["xml"].read_text(encoding="utf-8")
    old_min = '<posmin x="default" y="default" z="default" comment="e.g.: x=0.5, y=default-1, z=default-10%" />'
    old_max = '<posmax x="default" y="default" z="default + 20%" />'
    new_min = '<posmin x="-0.25" y="-0.15" z="-0.15" comment="root-reviewed swept-domain margin; physical geometry unchanged" />'
    new_max = '<posmax x="5.1" y="2.55" z="3.05" comment="root-reviewed swept-domain margin; physical geometry unchanged" />'
    if source_xml.count(old_min) != 1 or source_xml.count(old_max) != 1:
        raise ValueError(f"unexpected simulationdomain in {source['xml']}")
    staged_xml = source_xml.replace(old_min, new_min).replace(old_max, new_max)
    target["xml"].write_text(staged_xml, encoding="utf-8")
    copied.append({
        "name": "xml",
        "source": binding(source["xml"], "immutable repair_002 generated native XML"),
        "staged": binding(target["xml"], "co-located XML with domain-only numeric change"),
        "change": {
            "only": "execution.parameters.simulationdomain.posmin/posmax numeric values and their comments",
            "source_default": {"posmin": ["default", "default", "default"], "posmax": ["default", "default", "default + 20%"]},
            "staged_numeric": {"posmin": DOMAIN_LOW, "posmax": DOMAIN_HIGH},
        },
    })
    return {"case_id": case["case_id"], "source_root": str(source["root"].resolve()), "stage_root": str(target["root"].resolve()), "files": copied}


def vtk_point_count(path: Path) -> int:
    header = re.search(rb"POINTS\s+(\d+)\s+float\n", Path(path).read_bytes())
    if header is None:
        raise ValueError(f"VTK POINTS header missing: {path}")
    return int(header.group(1))


def generated_xml_contract(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    definition = next((node for node in root.iter("definition") if "dp" in node.attrib), None)
    floating = next((node for node in root.iter("floating") if node.attrib.get("mk") == "60" and node.find("center") is not None), None)
    fluid = next((node for node in root.iter("fluid") if node.attrib.get("mkfluid") == "0"), None)
    constants = next(iter(root.iter("constants")), None)
    if definition is None or floating is None or fluid is None or constants is None:
        raise ValueError(f"generated XML contract incomplete: {path}")
    massbody = floating.find("massbody")
    center = floating.find("center")
    inertia = floating.find("inertia")
    masspart = floating.find("masspart")
    massfluid = constants.find("massfluid")
    if None in (massbody, center, inertia, masspart, massfluid):
        raise ValueError(f"generated XML mass/rigid fields incomplete: {path}")
    actual_center = [float(center.attrib[axis]) for axis in ("x", "y", "z")]
    actual_inertia = [float(inertia.attrib[axis]) for axis in ("x", "y", "z")]
    fluid_count = int(fluid.attrib["count"])
    fluid_particle_mass = float(massfluid.attrib["value"])
    return {
        "xml": binding(path, "actual generated native XML"),
        "dp_m": float(definition.attrib["dp"]),
        "fluid_count": fluid_count,
        "fluid_particle_mass_kg": fluid_particle_mass,
        "fluid_mass_kg": fluid_count * fluid_particle_mass,
        "floating_count": int(floating.attrib["count"]),
        "aggregate_massbody_kg": float(massbody.attrib["value"]),
        "type2_particle_mass_kg": int(floating.attrib["count"]) * float(masspart.attrib["value"]),
        "type2_particle_mass_policy": "separate MassBound/particle sum; never substitutes for aggregate massbody",
        "aggregate_center_m": actual_center,
        "aggregate_inertia_diag_kg_m2": actual_inertia,
        "inertia_positive": all(value > 0.0 for value in actual_inertia),
        "body_contract_match": (
            abs(float(massbody.attrib["value"]) - EXPECTED_BODY_MASS) <= 1e-12
            and all(abs(actual_center[i] - EXPECTED_CENTER[i]) <= 1e-12 for i in range(3))
            and all(abs(actual_inertia[i] - EXPECTED_INERTIA[i]) <= 5e-5 for i in range(3))
        ),
        "fluid_contract_match": abs(fluid_count * fluid_particle_mass - EXPECTED_FLUID_MASS) <= 1e-12,
        "data2d": next((node.attrib.get("value") for node in root.iter("data2d")), None),
    }


def domain_stage_contract(source: Path, staged: Path) -> dict[str, Any]:
    source_text = source.read_text(encoding="utf-8")
    staged_text = staged.read_text(encoding="utf-8")
    old_min = '<posmin x="default" y="default" z="default" comment="e.g.: x=0.5, y=default-1, z=default-10%" />'
    old_max = '<posmax x="default" y="default" z="default + 20%" />'
    new_min = '<posmin x="-0.25" y="-0.15" z="-0.15" comment="root-reviewed swept-domain margin; physical geometry unchanged" />'
    new_max = '<posmax x="5.1" y="2.55" z="3.05" comment="root-reviewed swept-domain margin; physical geometry unchanged" />'
    expected = source_text.replace(old_min, new_min).replace(old_max, new_max)
    return {
        "source": binding(source, "immutable generated XML"),
        "staged": binding(staged, "domain-only solver XML"),
        "only_domain_values_changed": expected == staged_text,
        "domain_low_m": DOMAIN_LOW,
        "domain_high_m": DOMAIN_HIGH,
    }


def native_case_audit(case: dict[str, Any], stage: dict[str, Any]) -> dict[str, Any]:
    source = case_paths(case)
    staged = stage_paths(case)
    receipt = read_json(source["receipt"])
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise RuntimeError(f"GenCase receipt is not successful: {source['receipt']}")
    contract = generated_xml_contract(source["xml"])
    points, types = FACES.bound_vtk_points(source["bound_vtk"])
    type_counts = {str(kind): int((types == kind).sum()) for kind in sorted(set(types.tolist()))}
    all_faces = FACES.open_tank_coverage(points, low_m=TANK_LOW, high_m=TANK_HIGH, dp_m=DP)
    fixed_points = points[types == 0]
    fixed_faces = FACES.open_tank_coverage(fixed_points, low_m=TANK_LOW, high_m=TANK_HIGH, dp_m=DP)
    expected_types = {"0": EXPECTED_FIXED_COUNT, "1": case["expected_moving"], "2": EXPECTED_FLOATING_COUNT}
    type_counts_match = all(type_counts.get(key, 0) == value for key, value in expected_types.items())
    total = int(receipt["total_particles"])
    fluid = int(receipt["fluid_particles"])
    checks = {
        "receipt_completed": receipt.get("status") == "completed" and receipt.get("returncode") == 0,
        "actual_3d": receipt.get("solver_dimension_from_gencase") == 3,
        "fluid_count_receipt_640000": fluid == EXPECTED_FLUID_COUNT,
        "fluid_count_xml_640000": contract["fluid_count"] == EXPECTED_FLUID_COUNT,
        "fluid_vtk_count_640000": vtk_point_count(source["fluid_vtk"]) == EXPECTED_FLUID_COUNT,
        "all_vtk_count_matches_receipt": vtk_point_count(source["all_vtk"]) == total,
        "bound_count_matches_total_minus_fluid": len(points) == total - fluid,
        "typed_counts_match": type_counts_match,
        "positive_fluid_type3": fluid > 0,
        "positive_floating_type2": type_counts.get("2", 0) > 0,
        "moving_contract": type_counts.get("1", 0) == case["expected_moving"],
        "fluid_mass_5120kg": contract["fluid_contract_match"],
        "body_128kg_center_inertia": contract["body_contract_match"],
        "positive_inertia": contract["inertia_positive"],
        "data3d": contract["data2d"] == "false",
        "all_five_physical_faces_covered": all_faces["all_five_finite_faces_covered"],
        "fixed_five_physical_faces_covered": fixed_faces["all_five_finite_faces_covered"],
        "domain_stage_only_change": domain_stage_contract(source["xml"], staged["xml"])["only_domain_values_changed"],
    }
    return {
        "case_id": case["case_id"],
        "mechanism_id": case["mechanism_id"],
        "gencase_receipt": binding(source["receipt"], "repair_002 GenCase receipt"),
        "native_outputs": {key: binding(source[key], "repair_002 native output") for key in ("xml", "bi4", "all_vtk", "bound_vtk", "fluid_vtk", "mkcells_vtk", "dp_vtk")},
        "stage": stage,
        "stage_domain": domain_stage_contract(source["xml"], staged["xml"]),
        "receipt_actual": {key: receipt.get(key) for key in ("total_particles", "fluid_particles", "solver_dimension_from_gencase", "bytes", "elapsed_seconds", "cpu_core_seconds")},
        "native_xml_contract": contract,
        "native_boundary": {
            "point_count": int(len(points)),
            "type_counts": type_counts,
            "point_bounds_m": [[float(points[:, axis].min()), float(points[:, axis].max())] for axis in range(3)],
            "all_boundary_face_coverage": all_faces,
            "fixed_boundary_face_coverage": fixed_faces,
        },
        "checks": checks,
        "preflight_pass": all(checks.values()),
        "qualification_claim": "none",
        "q_i_status": "actual GenCase native contract and finite-face preflight only",
        "q_n_status": "pending root solver dispatch and complete-window native trajectory review",
    }


def stage_and_audit() -> dict[str, Any]:
    if AUDIT_PATH.exists() or STAGE_MANIFEST_PATH.exists():
        raise FileExistsError("repair_002 native audit/stage already exists; preserve immutable bytes")
    stages = [stage_case(case) for case in CASES]
    stage_manifest = {
        "schema": "ds-data-02.f6.rigid003.dp020.finite-wall-repair-002.domain-stage.v1",
        "family_id": "F6",
        "created_at_utc": now(),
        "stage_root": str(STAGE_ROOT.resolve()),
        "domain_low_m": DOMAIN_LOW,
        "domain_high_m": DOMAIN_HIGH,
        "physical_geometry_unchanged": True,
        "source_native_files_byte_identical_except_generated_xml": True,
        "cases": stages,
        "gpu_launch": False,
        "q_n_status": "pending",
    }
    write_json(STAGE_MANIFEST_PATH, stage_manifest)
    audits = [native_case_audit(case, stage) for case, stage in zip(CASES, stages)]
    if not all(row["preflight_pass"] for row in audits):
        raise RuntimeError("new repair_002 native QA did not pass; solver requests withheld")
    result = {
        "schema": "ds-data-02.f6.rigid003.dp020.finite-wall-repair-002.native-audit.v1",
        "family_id": "F6",
        "created_at_utc": now(),
        "status": "both_repair_002_native_preflight_pass",
        "stage_manifest": binding(STAGE_MANIFEST_PATH, "domain-only co-located staging manifest"),
        "finite_face_helper": binding(FACE_HELPER, "root-reviewed physical finite-face sampler"),
        "cases": audits,
        "physical_contract": {
            "continuous_tank_low_m": TANK_LOW,
            "continuous_tank_high_m": TANK_HIGH,
            "fluid_particles": EXPECTED_FLUID_COUNT,
            "fluid_mass_kg": EXPECTED_FLUID_MASS,
            "body_massbody_kg": EXPECTED_BODY_MASS,
            "body_center_m": EXPECTED_CENTER,
            "body_inertia_diag_kg_m2": EXPECTED_INERTIA,
            "floatingtype": 2,
        },
        "gpu_launch": False,
        "qualification_claim": "none",
        "q_i_status": "native GenCase and finite-face QA pass",
        "q_n_status": "pending root-owned complete 0-12 s solver and native postprocessing",
    }
    write_json(AUDIT_PATH, result)
    return result


def solver_input_files(case: dict[str, Any], audit: dict[str, Any]) -> list[Path]:
    source = case_paths(case)
    staged = stage_paths(case)
    gencase_request = REPAIR_ROOT / "gencase_requests" / f"{case['case_id']}_gencase.json"
    gencase_evidence = REPAIR_ROOT / "finite_wall_discretization_evidence_002.json"
    repair_manifest = REPAIR_ROOT / "repair_manifest_002.json"
    candidates = [
        SCRIPT,
        FACE_HELPER,
        RUNTIME_V2,
        SOLVER,
        gencase_request,
        gencase_evidence,
        repair_manifest,
        STAGE_MANIFEST_PATH,
        AUDIT_PATH,
        source["receipt"],
        source["xml"],
        source["bi4"],
        source["all_vtk"],
        source["bound_vtk"],
        source["fluid_vtk"],
        source["mkcells_vtk"],
        source["dp_vtk"],
        staged["xml"],
        staged["bi4"],
        staged["all_vtk"],
        staged["bound_vtk"],
        staged["fluid_vtk"],
        staged["mkcells_vtk"],
        staged["dp_vtk"],
    ]
    result: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        path = Path(path).resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        if str(path) not in seen:
            result.append(path)
            seen.add(str(path))
    return result


def solver_request(case: dict[str, Any], audit_row: dict[str, Any], registration_commit: str) -> dict[str, Any]:
    staged = stage_paths(case)
    total = int(audit_row["receipt_actual"]["total_particles"])
    fluid = int(audit_row["receipt_actual"]["fluid_particles"])
    raw_frame_bytes = total * 241 * 64
    safety = 512 * 1024**2
    margin = 0.35
    calculated = int(raw_frame_bytes * (1.0 + margin) + safety)
    requested_storage = 16 * 1024**3 if case["mechanism_id"] == "simple_free_response" else 18 * 1024**3
    wall = 2400 if case["mechanism_id"] == "simple_free_response" else 3000
    inputs = solver_input_files(case, audit_row)
    cid = case["case_id"]
    request_id = f"{cid}_SOLVER_QUAL_DOMAIN_STAGE_001"
    return {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": "F6",
        "case_id": cid,
        "attempt_id": request_id,
        "kind": "qualification",
        "command": [str(SOLVER.resolve()), str(staged["prefix"].resolve()), "{attempt_root}/solver_output", "-tmax:12", "-tout:0.05"],
        "cwd": str(staged["root"].resolve()),
        "max_wall_seconds": wall,
        "cpu_threads": 4,
        "estimated_peak_gpu_mib": 8192,
        "estimated_storage_bytes": requested_storage,
        "input_files": [str(path) for path in inputs],
        "input_sha256": {str(path): sha256(path) for path in inputs},
        "worktree_root": str(LAB_ROOT.parent.resolve()),
        "generator_version": "ds-data-02.f6.rigid003.dp020.finite-wall-repair-002.solver-requests.v1",
        "request_registration_commit": registration_commit,
        "mechanism_id": case["mechanism_id"],
        "resolution_id": "dp020",
        "repair_id": "F6_HANDOFF_20261002_RIGID003_FINITE_WALL_REPAIR_002_DOMAIN_STAGE_001",
        "launch_authority": "root only through shared ds_data02_runtime_v2.py; F6 owner did not launch GPU",
        "gencase_receipt": str(case_paths(case)["receipt"].resolve()),
        "gencase_receipt_sha256": sha256(case_paths(case)["receipt"]),
        "native_audit": str(AUDIT_PATH.resolve()),
        "native_audit_sha256": sha256(AUDIT_PATH),
        "gencase_actual_particles": {
            "total": total,
            "fluid": fluid,
            "fixed": int(audit_row["native_boundary"]["type_counts"].get("0", 0)),
            "moving": int(audit_row["native_boundary"]["type_counts"].get("1", 0)),
            "floating": int(audit_row["native_boundary"]["type_counts"].get("2", 0)),
        },
        "native_initial_mass_contract": audit_row["native_xml_contract"],
        "native_boundary_contract": {
            "all_five_physical_faces_covered": audit_row["checks"]["all_five_physical_faces_covered"],
            "fixed_five_physical_faces_covered": audit_row["checks"]["fixed_five_physical_faces_covered"],
            "coverage_sampler": str(FACE_HELPER.resolve()),
        },
        "runtime_prefix_contract": {
            "prefix_directory": str(staged["root"].resolve()),
            "xml": str(staged["xml"].resolve()),
            "bi4": str(staged["bi4"].resolve()),
            "xml_external_references": [],
            "all_xml_references_resolve_from_prefix": True,
            "co_located_native_auxiliary_files": True,
            "source_native_files_byte_identical_except_domain_xml": True,
            "simulationdomain_low_m": DOMAIN_LOW,
            "simulationdomain_high_m": DOMAIN_HIGH,
        },
        "complete_event_window_s": [0.0, 12.0],
        "output_interval_s": 0.05,
        "solver_dimension_required": 3,
        "cost_estimate": {
            "basis": "actual repair_002 GenCase particle count and completed DP025 reference timing",
            "estimated_total_particles": total,
            "estimated_fluid_particles": fluid,
            "raw_particle_frame_bytes": raw_frame_bytes,
            "storage_margin_fraction": margin,
            "storage_safety_bytes": safety,
            "calculated_minimum_storage_bytes": calculated,
            "requested_storage_bytes": requested_storage,
            "estimated_gpu_seconds": wall,
        },
        "postprocessing_pending": [
            "FloatingInfo full pose/orientation/quaternion/linear-angular velocity",
            "ComputeForces force/torque with origin and force-phase semantics preserved",
            "native labels and full exclusion classification",
            "strict [0,12] spatial/event comparison",
        ],
        "qualification_claim": "none; request pending root dispatch and terminal native review",
        "q_n_status": "pending",
    }


def make_solver_requests(audit: dict[str, Any]) -> dict[str, Any]:
    if audit.get("status") != "both_repair_002_native_preflight_pass":
        raise RuntimeError(f"native audit did not pass: {audit.get('status')}")
    REQUEST_ROOT.mkdir(parents=True, exist_ok=True)
    registration_commit = git_head()
    rows: list[dict[str, Any]] = []
    for case, row in zip(CASES, audit["cases"]):
        request = solver_request(case, row, registration_commit)
        path = REQUEST_ROOT / f"{case['case_id']}.json"
        write_json(path, request)
        rows.append({"case_id": case["case_id"], "path": str(path.resolve()), "sha256": sha256(path), "attempt_id": request["attempt_id"], "gpu_launch": False})
    result = {
        "schema": "ds-data-02.f6.rigid003.dp020.finite-wall-repair-002.solver-request-manifest.v1",
        "family_id": "F6",
        "created_at_utc": now(),
        "status": "root_dispatch_pending",
        "requests": rows,
        "gpu_launch": False,
        "q_n_status": "pending root dispatch, 12 s native trajectory, postprocessing and event review",
    }
    write_json(REQUEST_MANIFEST_PATH, result)
    return result


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["audit-and-requests"])
    args = parser.parse_args()
    if args.action == "audit-and-requests":
        audit = stage_and_audit()
        result = make_solver_requests(audit)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
