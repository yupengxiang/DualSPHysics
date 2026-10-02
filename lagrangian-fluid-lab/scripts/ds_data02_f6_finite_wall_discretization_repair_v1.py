#!/usr/bin/env python3
"""Record F6's finite-wall diagnosis and register one additive GenCase repair.

The DP=.020 native runs failed because the generated fixed lattice contains
only the edge particles on the high-y tank face.  This producer decodes the
immutable binary Bound.vtk evidence, records the failed solver particles, and
creates fresh XML definitions with one explicit one-cell high-y wall slab.
The continuous tank dimensions, fluid lattice, body, mass/inertia, controls,
and prescribed wave are copied byte-for-byte from each source XML; only the
new repair drawbox is inserted.  It writes CPU GenCase requests for the shared
runner and never launches GenCase or a solver itself.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
import re
import struct
import subprocess
from typing import Any


SCRIPT = Path(__file__).resolve()
LAB_ROOT = SCRIPT.parents[1]
WORKTREE_ROOT = SCRIPT.parents[2]
FAMILY_ROOT = LAB_ROOT / "campaigns/ds-data-02/families/F6"
INTEGRATION_LAB = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
RUNNER_V2 = INTEGRATION_LAB / "scripts/ds_data02_runtime_v2.py"
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F6")
AUDIT_ROOT = FAMILY_ROOT / "handoff_20261002/rigid_contract_003/dp020_dp0125_cpu_003/finite_wall_discretization_repair_001"
OUTPUT_ROOT = AUDIT_ROOT / "definitions"
REQUEST_ROOT = AUDIT_ROOT / "gencase_requests"
GIB = 1024**3


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite F6 repair evidence: {path}")
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def bind(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def git_head() -> str:
    return subprocess.run(["git", "-C", str(WORKTREE_ROOT), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()


def source_cases() -> list[dict[str, Any]]:
    rows = []
    for mechanism, label in (("simple_free_response", "SIMPLE_FREE_RESPONSE"), ("wave_no_contact", "WAVE_NO_CONTACT")):
        for dp_id, dp_text, bound_name in (("DP020", "0.02", "EPSFREE002_PHASE003_DP020"), ("DP0125", "0.0125", "EPSFREE002_PHASE003_DP0125")):
            case = f"F6_HANDOFF_20261002_{label}_RIGID003_EPSFREE002_PHASE003_{dp_id}"
            gen_dir = DATA_ROOT / case / f"{case}_GENCASE_001"
            solver_case = case
            solver_attempt = f"{case}_SOLVER_QUAL_FINE_ROOT_DOMAIN_001"
            if mechanism == "simple_free_response":
                source_xml = gen_dir / f"{case}.xml"
                bound = gen_dir / f"{case}_Bound.vtk"
                error = DATA_ROOT / case / solver_attempt / "solver_output/Error_BoundaryOut.vtk"
                runout = DATA_ROOT / case / solver_attempt / "solver_output/Run.out"
                runparts = DATA_ROOT / case / solver_attempt / "solver_output/RunPARTs.csv"
            else:
                source_xml = gen_dir / f"{case}.xml"
                bound = gen_dir / f"{case}_Bound.vtk"
                error = DATA_ROOT / case / solver_attempt / "solver_output/Error_BoundaryOut.vtk"
                runout = DATA_ROOT / case / solver_attempt / "solver_output/Run.out"
                runparts = DATA_ROOT / case / solver_attempt / "solver_output/RunPARTs.csv"
            rows.append({
                "mechanism_id": mechanism,
                "case_id": case,
                "resolution_id": dp_id.lower(),
                "dp_m": float(dp_text),
                "source_xml": source_xml,
                "source_bound": bound,
                "failure_error": error,
                "failure_runout": runout,
                "failure_runparts": runparts,
                "solver_attempt": solver_attempt,
                "solver_case": solver_case,
            })
    return rows


def reference_bounds() -> dict[str, Path]:
    return {
        "simple_dp025": DATA_ROOT / "F6_HANDOFF_20261002_SIMPLE_FREE_RESPONSE_COMMENSURATE_RIGID003_DP025/F6_HANDOFF_20261002_SIMPLE_FREE_RESPONSE_COMMENSURATE_RIGID003_DP025_GENCASE_001/F6_HANDOFF_20261002_SIMPLE_FREE_RESPONSE_COMMENSURATE_RIGID003_DP025_Bound.vtk",
        "wave_dp025": DATA_ROOT / "F6_HANDOFF_20261002_WAVE_NO_CONTACT_COMMENSURATE_RIGID003_DP025/F6_HANDOFF_20261002_WAVE_NO_CONTACT_COMMENSURATE_RIGID003_DP025_GENCASE_001/F6_HANDOFF_20261002_WAVE_NO_CONTACT_COMMENSURATE_RIGID003_DP025_Bound.vtk",
        "simple_dp0125": DATA_ROOT / "F6_HANDOFF_20261002_SIMPLE_FREE_RESPONSE_RIGID003_EPSFREE002_PHASE003_DP0125/F6_HANDOFF_20261002_SIMPLE_FREE_RESPONSE_RIGID003_EPSFREE002_PHASE003_DP0125_GENCASE_001/F6_HANDOFF_20261002_SIMPLE_FREE_RESPONSE_RIGID003_EPSFREE002_PHASE003_DP0125_Bound.vtk",
        "wave_dp0125": DATA_ROOT / "F6_HANDOFF_20261002_WAVE_NO_CONTACT_RIGID003_EPSFREE002_PHASE003_DP0125/F6_HANDOFF_20261002_WAVE_NO_CONTACT_RIGID003_EPSFREE002_PHASE003_DP0125_GENCASE_001/F6_HANDOFF_20261002_WAVE_NO_CONTACT_RIGID003_EPSFREE002_PHASE003_DP0125_Bound.vtk",
    }


def read_bound_vtk(path: Path) -> tuple[list[tuple[float, float, float]], list[int]]:
    data = Path(path).read_bytes()
    match = re.search(rb"POINTS (\d+) float\n", data)
    if match is None:
        raise ValueError(f"Bound.vtk lacks binary POINTS header: {path}")
    count = int(match.group(1))
    offset = match.end()
    points = [struct.unpack_from(">fff", data, offset + 12 * i) for i in range(count)]
    point_data = data.find(f"POINT_DATA {count}".encode("ascii"), offset + 12 * count)
    if point_data < 0:
        raise ValueError(f"Bound.vtk lacks POINT_DATA header: {path}")
    id_header = re.search(rb"SCALARS Idp ([^\n]+)\nLOOKUP_TABLE default\n", data[point_data:])
    if id_header is None:
        raise ValueError(f"Bound.vtk lacks Idp scalar: {path}")
    id_offset = point_data + id_header.end()
    id_spec = id_header.group(1).decode("ascii")
    id_fmt = ">I" if "unsigned" in id_spec else ">i"
    id_size = 4
    type_header = re.search(rb"Type 1 \d+ ([^\n]+)\n", data[id_offset + count * id_size:])
    if type_header is None:
        raise ValueError(f"Bound.vtk lacks Type scalar: {path}")
    type_offset = id_offset + count * id_size + type_header.end()
    type_spec = type_header.group(1).decode("ascii")
    if "unsigned_char" in type_spec:
        type_values = [data[type_offset + i] for i in range(count)]
    elif "short" in type_spec:
        type_values = [struct.unpack_from(">h", data, type_offset + 2 * i)[0] for i in range(count)]
    else:
        type_values = [struct.unpack_from(">i", data, type_offset + 4 * i)[0] for i in range(count)]
    return points, type_values


def plane_record(points: list[tuple[float, float, float]], fixed: list[tuple[float, float, float]], axis: int, side: str, dp: float) -> dict[str, Any]:
    value = min(point[axis] for point in fixed) if side == "low" else max(point[axis] for point in fixed)
    tolerance = max(dp * 1.0e-4, 1.0e-7)
    selected = [point for point in fixed if abs(point[axis] - value) <= tolerance]
    others = [index for index in range(3) if index != axis]
    return {
        "axis": "xyz"[axis],
        "side": side,
        "coordinate_m": float(value),
        "count": len(selected),
        "tolerance_m": tolerance,
        "tangential_axes": ["xyz"[index] for index in others],
        "tangential_ranges_m": [[float(min(point[index] for point in selected)), float(max(point[index] for point in selected))] for index in others],
        "tangential_unique_counts": [len({round(point[index], 7) for point in selected}) for index in others],
    }


def bound_audit(path: Path, dp: float) -> dict[str, Any]:
    points, types = read_bound_vtk(path)
    fixed = [point for point, kind in zip(points, types) if kind == 0]
    floating = [point for point, kind in zip(points, types) if kind == 2]
    if not fixed or not floating:
        raise ValueError(f"Bound.vtk lacks fixed/floating cohorts: {path}")
    faces = {}
    for axis in range(3):
        for side in ("low", "high"):
            faces[f"{'xyz'[axis]}_{side}"] = plane_record(points, fixed, axis, side, dp)
    return {
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "total_boundary_points": len(points),
        "fixed_points": len(fixed),
        "floating_points": len(floating),
        "all_bounds_m": [[float(min(point[index] for point in points)), float(max(point[index] for point in points))] for index in range(3)],
        "fixed_bounds_m": [[float(min(point[index] for point in fixed)), float(max(point[index] for point in fixed))] for index in range(3)],
        "faces": faces,
    }


def error_audit(path: Path) -> dict[str, Any]:
    data = Path(path).read_bytes()
    match = re.search(rb"POINTS (\d+) float\n", data)
    if match is None:
        raise ValueError(path)
    count = int(match.group(1))
    point = list(struct.unpack_from(">fff", data, match.end()))
    id_header = re.search(rb"SCALARS Idp int\nLOOKUP_TABLE default\n", data)
    if id_header is None:
        raise ValueError(path)
    idp = struct.unpack_from(">i", data, id_header.end())[0]
    values: dict[str, Any] = {"path": str(path.resolve()), "sha256": sha256(path), "point_count": count, "position_m": point, "idp": idp}
    for name, pattern, fmt in (("rho", rb"Rho 1 1 float\n", ">f"), ("type", rb"Type 1 1 short\n", ">h"), ("motive", rb"Motive 1 1 short\n", ">h")):
        header = re.search(pattern, data)
        if header is not None:
            values[name] = struct.unpack_from(fmt, data, header.end())[0]
    velocity_header = re.search(rb"Vel 3 1 float\n", data)
    if velocity_header is not None:
        values["velocity_m_s"] = list(struct.unpack_from(">fff", data, velocity_header.end()))
    return values


def xml_values(text: str) -> tuple[float, float, float, float, float]:
    definition = re.search(r'<definition dp="([^"]+)"[^>]*>.*?<pointref x="([^"]+)" y="([^"]+)" z="([^"]+)"', text, re.S)
    wall = re.search(r'<drawbox cmt="Finite tank walls; physical endpoints frozen">.*?<point x="([^"]+)" y="([^"]+)" z="([^"]+)" />.*?<size x="([^"]+)" y="([^"]+)" z="([^"]+)"', text, re.S)
    if definition is None or wall is None:
        raise ValueError("repair source XML lacks definition or finite wall")
    return float(definition.group(1)), float(wall.group(4)), float(wall.group(5)), float(wall.group(5)), float(wall.group(6))


def repair_xml(source: Path, target: Path) -> dict[str, Any]:
    text = source.read_text(encoding="utf-8")
    dp, width, height, wall_y, wall_z = xml_values(text)
    if abs(wall_y - 2.4) > 1.0e-9 or abs(wall_z - 2.4) > 1.0e-9:
        raise ValueError(f"unexpected physical tank dimensions in {source}")
    if "Finite tank +Y explicit lattice face repair" in text:
        raise ValueError(f"source already contains repair marker: {source}")
    slab_y = wall_y - dp
    slab = f'''                    <!-- Additive repair: explicit high-y finite wall lattice plane; physical wall remains y={wall_y:g}. -->
                    <setdrawmode mode="full" />
                    <setmkbound mk="20" />
                    <drawbox cmt="Finite tank +Y explicit lattice face repair">
                        <boxfill>solid</boxfill>
                        <point x="0" y="{slab_y:.12g}" z="0" />
                        <size x="{width:.12g}" y="{dp:.12g}" z="{wall_z:.12g}" />
                    </drawbox>
'''
    marker = '                    <shapeout file="" reset="true" />'
    if text.count(marker) != 1:
        raise ValueError(f"expected one shapeout insertion point in {source}")
    repaired = text.replace(marker, slab + marker, 1)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(target)
    target.write_text(repaired, encoding="utf-8")
    return {
        "source": bind(source, "immutable phase003 generated XML"),
        "repaired": bind(target, "new explicit high-y wall repair XML"),
        "dp_m": dp,
        "physical_tank_size_m": [width, wall_y, wall_z],
        "repair_slab": {"point_m": [0.0, slab_y, 0.0], "size_m": [width, dp, wall_z], "target_center_plane_m": wall_y - dp / 2.0, "mkbound": 20},
        "byte_scope": "source XML is immutable; repaired XML differs only by the additive explicit slab and its comment",
    }


def request_for(case: dict[str, Any], repaired: Path, audit_path: Path, launch_commit: str) -> dict[str, Any]:
    case_id = case["case_id"] + "_FINITE_WALL_REPAIR_001"
    expected_fluid = 640000 if case["dp_m"] == 0.02 else 2621440
    expected_fixed = 85682 if case["dp_m"] == 0.02 else 292996
    expected_float = 35301 if case["dp_m"] == 0.02 else 139425
    source = [SCRIPT, RUNNER_V2, GENCASE, repaired, audit_path, case["source_xml"], case["source_bound"]]
    # The DP020 solver failure is direct evidence for this repair.  DP0125 was
    # deliberately not launched after the DP020 common-cause failure, so its
    # request carries no fabricated failure receipt.
    source.extend(path for path in (case["failure_error"], case["failure_runout"], case["failure_runparts"]) if path.is_file())
    source = [path.resolve() for path in source]
    inputs = []
    seen = set()
    for path in source:
        if str(path) in seen:
            continue
        if not path.is_file():
            raise FileNotFoundError(path)
        seen.add(str(path)); inputs.append(path)
    return {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": "F6",
        "case_id": case_id,
        "mechanism_id": case["mechanism_id"],
        "resolution_id": case["resolution_id"],
        "attempt_id": case_id + "_GENCASE_001",
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "command": [str(GENCASE), str(repaired.with_suffix("")), "{attempt_root}/" + case_id, "-save:all"],
        "cwd": str(AUDIT_ROOT),
        "max_wall_seconds": 1200,
        "cpu_threads": 4,
        "estimated_storage_bytes": 2 * GIB,
        "input_files": [str(path) for path in inputs],
        "input_sha256": {str(path): sha256(path) for path in inputs},
        "worktree_root": str(WORKTREE_ROOT),
        "launch_commit": launch_commit,
        "generator_version": "ds-data-02.f6.finite-wall-discretization-repair.v1",
        "purpose": "single evidence-backed explicit high-y finite-wall lattice repair; GenCase and initial PartVTK QA only",
        "repair_scope": {
            "root_cause": "phase003 GenCase Bound.vtk omitted the interior high-y fixed face at y=2.4-dp/2; only edge particles remained",
            "repair_class": "finite-wall discretization, first repair in this new class",
            "source_physics_unchanged": True,
            "source_fluid_mass_kg": 5120.0,
            "source_body_mass_kg": 128.0,
            "source_body_center_m": [2.4, 1.2, 1.08],
            "source_body_inertia_diag_kg_m2": [8.53333333333, 8.53333333333, 13.6533333333],
            "old_failure_evidence": str(case["failure_error"]),
        },
        "expected": {
            "solver_dimension": 3,
            "fluid_type": 3,
            "floating_type": 2,
            "expected_fluid_particles": expected_fluid,
            "expected_fixed_particles": expected_fixed,
            "expected_floating_particles": expected_float,
            "finite_walls": ["bottom", "left", "right", "front", "back"],
            "high_y_full_face_required": True,
            "minimum_transverse_layers": 10,
            "no_mass_rescaling": True,
        },
        "preflight": {"status": "pending_shared_runner_gencase_and_actual_bound_vtk", "gpu_launch": False, "q_n_status": "pending"},
        "qualification_claim": "none",
        "q_n_status": "pending actual GenCase and five-face native QA",
    }


def build() -> dict[str, Any]:
    launch_commit = git_head()
    AUDIT_ROOT.mkdir(parents=True, exist_ok=True)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    REQUEST_ROOT.mkdir(parents=True, exist_ok=True)
    cases = source_cases()
    # Validate all source diagnostics before writing the new definitions.
    for case in cases:
        for key in ("source_xml", "source_bound"):
            if not case[key].is_file():
                raise FileNotFoundError(case[key])
    evidence: dict[str, Any] = {
        "schema": "ds-data-02.f6.finite-wall-discretization-evidence.v1",
        "family_id": "F6",
        "scope": "DP020/DP0125 simple-free-response and wave-no-contact initial finite-wall QA",
        "created_at_utc": now(),
        "repair_count": {"finite_wall_discretization": 1, "domain_only": "not a repair for this root cause"},
        "root_cause": {
            "classification": "GenCase finite-wall lattice omission",
            "observed": "DP020 +Y interior face is absent while x faces and y- face are complete; Error_BoundaryOut reports type-2 floating particles at y=2.55",
            "not_domain_only": "enlarging simulationdomain cannot create missing fixed particles or a closed +Y physical wall",
        },
        "failed_solver_evidence": {},
        "bound_face_comparison": {},
        "new_repair": {"status": "definitions_and_requests_written_pending_shared_runner", "physical_geometry_change": False, "gpu_launch": False},
        "source_hashes": {},
    }
    for case in cases:
        key = f"{case['mechanism_id']}_{case['resolution_id']}"
        if case["failure_error"].is_file():
            evidence["failed_solver_evidence"][key] = {
                "error": error_audit(case["failure_error"]),
                "run_out": bind(case["failure_runout"], "failed root-domain solver Run.out"),
                "run_parts": bind(case["failure_runparts"], "failed root-domain RunPARTs.csv"),
            }
        evidence["bound_face_comparison"][key] = bound_audit(case["source_bound"], case["dp_m"])
        evidence["source_hashes"][key] = {"source_xml": sha256(case["source_xml"]), "source_bound": sha256(case["source_bound"])}
    for name, path in reference_bounds().items():
        if not path.is_file():
            raise FileNotFoundError(path)
        dp = 0.025 if "dp025" in name else 0.0125
        evidence["bound_face_comparison"][name] = bound_audit(path, dp)
        evidence["source_hashes"][name] = sha256(path)
    evidence_path = AUDIT_ROOT / "finite_wall_discretization_evidence_001.json"
    write_json(evidence_path, evidence)
    requests = []
    for case in cases:
        repaired = OUTPUT_ROOT / f"{case['case_id']}_FINITE_WALL_REPAIR_001_Def.xml"
        repair_info = repair_xml(case["source_xml"], repaired)
        request = request_for(case, repaired, evidence_path, launch_commit)
        request_path = REQUEST_ROOT / f"{case['case_id']}_FINITE_WALL_REPAIR_001_gencase.json"
        write_json(request_path, request)
        requests.append({"case_id": case["case_id"], "repair_xml": repair_info, "request": bind(request_path, "shared v2 GenCase request"), "status": "pending_shared_runner"})
    manifest = {
        "schema": "ds-data-02.f6.finite-wall-discretization-repair-registration.v1",
        "family_id": "F6",
        "launch_commit": launch_commit,
        "evidence": bind(evidence_path, "immutable finite-wall root-cause evidence"),
        "requests": requests,
        "status": "pending_cpu_gencase_and_actual_bound_vtk_face_qa",
        "gpu_launch": False,
        "source_physics": "frozen DP020/DP0125 physical tank/body/fluid/control; explicit one-cell high-y slab only",
        "q_n_status": "pending",
    }
    manifest_path = AUDIT_ROOT / "repair_manifest_001.json"
    write_json(manifest_path, manifest)
    return manifest


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("audit", nargs="?", default="audit")
    args = parser.parse_args()
    if args.audit != "audit":
        raise SystemExit(f"unsupported command: {args.audit}")
    print(json.dumps(build(), ensure_ascii=False, indent=2, sort_keys=True))
