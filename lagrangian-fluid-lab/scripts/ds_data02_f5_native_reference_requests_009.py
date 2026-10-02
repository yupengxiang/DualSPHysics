#!/usr/bin/env python3
"""Stage and register F5 v7 native 16 s macro reference requests.

The v7 GenCase products are already complete and immutable.  This producer
copies the actual XML/BI4/control/bed bytes into a fresh external native-input
directory because the generated XML uses relative control and STL paths.  It
audits those relative paths, finite face extents, STL triangle coverage,
motion coverage, native typed counts, and the repaired integer-grid evidence,
then writes solver requests for the shared runner.  It never starts a solver.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET
from typing import Any


SCRIPT = Path(__file__).resolve()
LAB_ROOT = SCRIPT.parents[1]
WORKTREE_ROOT = SCRIPT.parents[2]
FAMILY_ROOT = LAB_ROOT / "campaigns/ds-data-02/families/F5"
V7_ROOT = FAMILY_ROOT / "initialization_repairs/F5_CONTINUOUS_CELL_CENTRE_PHASE_EXACT_DP025_007"
SCOPE = "F5_NATIVE_REFERENCE_PHASE_EXACT_DP025_007_009"
STAGE_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5")
RAW_OUTPUT_ROOT = STAGE_ROOT / "case/attempt"
RUNNER_V2 = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py")
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")
QUALITY = FAMILY_ROOT / "quality_contract.json"
EVENTS = FAMILY_ROOT / "event_definitions.json"
SAVE_PLAN = FAMILY_ROOT / "integration_save_plan.json"
BED = FAMILY_ROOT / "definitions/assets/f5_continuous_bed_profile_slope_0p280.stl"
ACTUAL_EVIDENCE = V7_ROOT / "actual_preflight_evidence_007.json"
V7_PRODUCER = LAB_ROOT / "scripts/ds_data02_f5_cell_centre_phase_exact_007.py"
V8_AUDITOR = LAB_ROOT / "scripts/ds_data02_f5_cell_centre_index_audit_008.py"
COORD_TOL = 2.0e-7
EVENT_WINDOW_S = 16.0
SAVE_INTERVAL_S = 0.02
EXPECTED_FRAMES = int(round(EVENT_WINDOW_S / SAVE_INTERVAL_S)) + 1
BYTES_PER_PARTICLE_FRAME = 64
STORAGE_MARGIN_BYTES = 2 * 1024**3
GPU_MEMORY_MIB = 8192
MAX_WALL_SECONDS = 5400

DOMAIN_MIN = (-1.15, -0.84, -0.30)
DOMAIN_MAX = (11.00, 0.84, 1.45)

CASE_SPECS: dict[str, dict[str, Any]] = {
    "runup_return": {
        "case_id": "F5_REF_RUNUP_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007",
        "solver_case_id": "F5_REF_RUNUP_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007_NATIVE_REFERENCE_009",
        "source_xml": FAMILY_ROOT / "definitions/F5_REF_RUNUP_NOMINAL_MEDIUM.xml",
        "source_metadata": FAMILY_ROOT / "definitions/F5_REF_RUNUP_NOMINAL_MEDIUM.metadata.json",
        "motion_name": "piston_f91973457a049db5_regular_piston.dat",
        "gencase_prefix_dir": STAGE_ROOT / "F5_REF_RUNUP_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007/gencase-f5-runup_return-cellcentre-phase-exact-dp025-007",
        "audit_dir": STAGE_ROOT / "F5_REF_RUNUP_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007/audit-f5-runup_return-phase-index-v7-008",
        "strict_audit_dir": STAGE_ROOT / "F5_REF_RUNUP_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007/audit-f5-runup_return-cellcentre-phase-exact-dp025-007",
        "mechanism_id": "runup_return",
        "extra_drawboxes": (),
    },
    "weir_pair": {
        "case_id": "F5_REF_WEIR_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007",
        "solver_case_id": "F5_REF_WEIR_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007_NATIVE_REFERENCE_009",
        "source_xml": FAMILY_ROOT / "definitions/F5_REF_WEIR_NOMINAL_MEDIUM.xml",
        "source_metadata": FAMILY_ROOT / "definitions/F5_REF_WEIR_NOMINAL_MEDIUM.metadata.json",
        "motion_name": "piston_4c73cd98b7230035_regular_piston.dat",
        "gencase_prefix_dir": STAGE_ROOT / "F5_REF_WEIR_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007/gencase-f5-weir_pair-cellcentre-phase-exact-dp025-007",
        "audit_dir": STAGE_ROOT / "F5_REF_WEIR_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007/audit-f5-weir_pair-phase-index-v7-008",
        "strict_audit_dir": STAGE_ROOT / "F5_REF_WEIR_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007/audit-f5-weir_pair-cellcentre-phase-exact-dp025-007",
        "mechanism_id": "weir_pair",
        "extra_drawboxes": ("weir_left_side_segment", "weir_right_side_segment"),
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bind(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def write_json(path: Path, value: Any) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    partial.replace(path)


def git_commit() -> str:
    return subprocess.run(
        ["git", "-C", str(WORKTREE_ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def copy_exact(source: Path, target: Path) -> None:
    source = Path(source).resolve()
    target = Path(target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if sha256(source) != sha256(target) or target.stat().st_size != source.stat().st_size:
            raise RuntimeError(f"refusing to overwrite staged bytes: {target}")
        return
    shutil.copy2(source, target)
    if sha256(source) != sha256(target):
        raise RuntimeError(f"copy hash mismatch: {source} -> {target}")


def parse_float_attrs(node: ET.Element, names: tuple[str, ...]) -> tuple[float, ...]:
    return tuple(float(node.attrib[name]) for name in names)


def drawbox_audit(xml_path: Path, mechanism: str) -> dict[str, Any]:
    root = ET.parse(xml_path).getroot()
    expected: dict[str, tuple[tuple[float, ...], tuple[float, ...]]] = {
        "tank_floor": ((-1.10, -0.80, -0.25), (11.90, 1.60, 0.25)),
        "finite_sidewall_left": ((-1.10, -0.80, -0.25), (11.90, 0.08, 1.45)),
        "finite_sidewall_right": ((-1.10, 0.72, -0.25), (11.90, 0.08, 1.45)),
        "prescribed_piston": ((-1.08, -0.72, 0.0), (0.08, 1.44, 1.02)),
        "weir_left_side_segment": ((4.96, -0.70, 0.3648), (0.24, 0.95, 0.11)),
        "weir_right_side_segment": ((4.96, 0.50, 0.3648), (0.24, 0.20, 0.11)),
    }
    required = ["tank_floor", "finite_sidewall_left", "finite_sidewall_right", "prescribed_piston"]
    required.extend(CASE_SPECS[mechanism]["extra_drawboxes"])
    actual: dict[str, Any] = {}
    for node in root.findall(".//drawbox"):
        cmt = node.attrib.get("cmt")
        if cmt not in expected:
            continue
        point = node.find("point")
        size = node.find("size")
        if point is None or size is None:
            raise ValueError(f"drawbox lacks point/size: {cmt}")
        actual[cmt] = {
            "point_m": list(parse_float_attrs(point, ("x", "y", "z"))),
            "size_m": list(parse_float_attrs(size, ("x", "y", "z"))),
            "layers": (node.find("layers").attrib.get("vdp") if node.find("layers") is not None else None),
            "has_layers": node.find("layers") is not None,
        }
    comparisons: dict[str, bool] = {}
    for name in required:
        if name not in actual:
            comparisons[name] = False
            continue
        point, size = expected[name]
        comparisons[name] = all(abs(actual[name]["point_m"][i] - point[i]) <= 1e-9 for i in range(3)) and all(
            abs(actual[name]["size_m"][i] - size[i]) <= 1e-9 for i in range(3)
        ) and actual[name]["has_layers"]
    stl_nodes = root.findall(".//drawfilestl")
    stl_names = [node.attrib.get("file") for node in stl_nodes]
    return {
        "required_drawboxes": required,
        "drawboxes": actual,
        "drawbox_extent_checks": comparisons,
        "all_required_drawbox_extents_exact": all(comparisons.values()),
        "stl_references": stl_names,
        "finite_bed_reference_present": "assets/f5_continuous_bed_profile_slope_0p280.stl" in stl_names,
    }


def stl_audit(path: Path) -> dict[str, Any]:
    vertices: list[tuple[float, float, float]] = []
    for line in Path(path).read_text(encoding="utf-8", errors="strict").splitlines():
        fields = line.strip().split()
        if len(fields) == 4 and fields[0].lower() == "vertex":
            vertices.append(tuple(float(value) for value in fields[1:]))
    if len(vertices) == 0 or len(vertices) % 3 != 0:
        raise ValueError(f"unexpected ASCII STL vertex count: {path}")
    area = 0.0
    for index in range(0, len(vertices), 3):
        p0, p1, p2 = vertices[index : index + 3]
        u = [p1[i] - p0[i] for i in range(3)]
        v = [p2[i] - p0[i] for i in range(3)]
        cross = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        area += 0.5 * math.sqrt(sum(value * value for value in cross))
    return {
        "format": "ASCII STL",
        "triangle_count": len(vertices) // 3,
        "vertex_count": len(vertices),
        "bbox_min_m": [min(value[i] for value in vertices) for i in range(3)],
        "bbox_max_m": [max(value[i] for value in vertices) for i in range(3)],
        "surface_area_m2": area,
    }


def motion_audit(path: Path, xml_path: Path) -> dict[str, Any]:
    rows = [tuple(map(float, line.split())) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise ValueError(path)
    root = ET.parse(xml_path).getroot()
    files = [node.attrib.get("name") for node in root.findall(".//motion//file")]
    begins = [node for node in root.findall(".//motion//begin") if node.attrib.get("mov") == "1"]
    durations = [float(node.attrib["duration"]) for node in root.findall(".//motion//mvpredef")]
    finishes = [float(node.attrib["finish"]) for node in begins]
    return {
        "row_count": len(rows),
        "time_start_s": rows[0][0],
        "time_end_s": rows[-1][0],
        "displacement_min_m": min(row[1] for row in rows),
        "displacement_max_m": max(row[1] for row in rows),
        "xml_motion_files": files,
        "xml_motion_begin_finish_s": [[float(node.attrib["start"]), float(node.attrib["finish"])] for node in begins],
        "xml_motion_durations_s": durations,
        "full_window": rows[0][0] == 0.0 and rows[-1][0] == EVENT_WINDOW_S and all(abs(value - EVENT_WINDOW_S) <= 1e-9 for value in durations + finishes),
    }


def domain_audit(xml_path: Path, stl: dict[str, Any], fluid_bounds: dict[str, Any], motion: dict[str, Any]) -> dict[str, Any]:
    root = ET.parse(xml_path).getroot()
    minimum = root.find(".//simulationdomain/posmin")
    maximum = root.find(".//simulationdomain/posmax")
    if minimum is None or maximum is None:
        raise ValueError(f"simulationdomain missing: {xml_path}")
    actual_min = parse_float_attrs(minimum, ("x", "y", "z"))
    actual_max = parse_float_attrs(maximum, ("x", "y", "z"))
    swept_piston = [-1.08 + motion["displacement_min_m"], -1.08 + 0.08 + motion["displacement_max_m"]]
    required_min = [min(stl["bbox_min_m"][i], fluid_bounds["min"][i], DOMAIN_MIN[i]) for i in range(3)]
    required_max = [max(stl["bbox_max_m"][i], fluid_bounds["max"][i], DOMAIN_MAX[i]) for i in range(3)]
    required_min[0] = min(required_min[0], swept_piston[0])
    required_max[0] = max(required_max[0], swept_piston[1])
    # DOMAIN_MIN/MAX are the registered actual execution envelope; this check
    # records that the XML contains the frozen envelope exactly and covers the
    # finite wall, STL and piston sweep.
    covers_geometry = all(actual_min[i] <= stl["bbox_min_m"][i] + 1e-9 and actual_max[i] >= stl["bbox_max_m"][i] - 1e-9 for i in range(3))
    covers_fluid = all(actual_min[i] <= fluid_bounds["min"][i] + 1e-9 and actual_max[i] >= fluid_bounds["max"][i] - 1e-9 for i in range(3))
    covers_piston = actual_min[0] <= swept_piston[0] + 1e-9 and actual_max[0] >= swept_piston[1] - 1e-9
    return {
        "xml_posmin_m": list(actual_min),
        "xml_posmax_m": list(actual_max),
        "registered_execution_domain_min_m": list(DOMAIN_MIN),
        "registered_execution_domain_max_m": list(DOMAIN_MAX),
        "domain_exact_registered_envelope": all(abs(actual_min[i] - DOMAIN_MIN[i]) <= 1e-9 and abs(actual_max[i] - DOMAIN_MAX[i]) <= 1e-9 for i in range(3)),
        "covers_finite_bed_bbox": covers_geometry,
        "covers_initial_fluid_bbox": covers_fluid,
        "piston_swept_x_m": swept_piston,
        "covers_piston_sweep": covers_piston,
        "full_physical_domain_coverage": covers_geometry and covers_fluid and covers_piston,
    }


def particle_audit(xml_path: Path, indexed_report: Path) -> dict[str, Any]:
    root = ET.parse(xml_path).getroot()
    particles = root.find(".//particles")
    constants = root.find(".//constants")
    if particles is None or constants is None:
        raise ValueError(xml_path)
    data2d = constants.find("data2d")
    report = json.loads(Path(indexed_report).read_text(encoding="utf-8"))
    observed = report["observed"]
    return {
        "solver_dimension_3d": data2d is not None and data2d.attrib.get("value", "true").lower() == "false",
        "generated_np": int(particles.attrib["np"]),
        "generated_fixed_count": int(particles.attrib["nbf"]),
        "generated_moving_count": int(particles.findall("moving")[0].attrib["count"]),
        "generated_fluid_count": int(particles.findall("fluid")[0].attrib["count"]),
        "actual_partvtk_type_counts": observed["type_counts"],
        "actual_partvtk_mk_counts": observed["mk_counts"],
        "fluid_mass_kg": observed["fluid_mass_kg"],
        "positive_typed_fixed_moving_fluid": all(observed["type_counts"].get(str(value), 0) > 0 for value in (0, 1, 3)),
        "native_3d_and_expected_fluid": data2d is not None and data2d.attrib.get("value", "true").lower() == "false" and observed["fluid_count"] == 150528,
    }


def estimate_storage_bytes(total_particles: int) -> int:
    base = total_particles * EXPECTED_FRAMES * BYTES_PER_PARTICLE_FRAME
    raw = base + STORAGE_MARGIN_BYTES
    return int(math.ceil(raw / (1024**3)) * 1024**3)


def stage_and_audit(mechanism: str, spec: dict[str, Any]) -> dict[str, Any]:
    prefix_dir = Path(spec["gencase_prefix_dir"])
    case_id = spec["case_id"]
    generated_xml = prefix_dir / f"{case_id}.xml"
    generated_bi4 = prefix_dir / f"{case_id}.bi4"
    gencase_receipt = prefix_dir / "execution-receipt.json"
    indexed_report_path = Path(spec["audit_dir"]) / "initialization-index-audit-008.json"
    motion_source = FAMILY_ROOT / "definitions" / spec["motion_name"]
    for path in (generated_xml, generated_bi4, gencase_receipt, indexed_report_path, motion_source, BED):
        if not Path(path).is_file():
            raise FileNotFoundError(path)
    receipt = json.loads(gencase_receipt.read_text(encoding="utf-8"))
    indexed_report = json.loads(indexed_report_path.read_text(encoding="utf-8"))
    stage_dir = STAGE_ROOT / f"{spec['solver_case_id']}/native_inputs"
    stage_prefix = stage_dir / case_id
    staged_xml = stage_prefix.with_suffix(".xml")
    staged_bi4 = stage_prefix.with_suffix(".bi4")
    staged_motion = stage_dir / spec["motion_name"]
    staged_bed = stage_dir / "assets" / BED.name
    copy_exact(generated_xml, staged_xml)
    copy_exact(generated_bi4, staged_bi4)
    copy_exact(motion_source, staged_motion)
    copy_exact(BED, staged_bed)
    drawboxes = drawbox_audit(staged_xml, mechanism)
    stl = stl_audit(staged_bed)
    motion = motion_audit(staged_motion, staged_xml)
    fluid_bounds = indexed_report["observed"]["fluid_bounds_m"]
    domain = domain_audit(staged_xml, stl, fluid_bounds, motion)
    particles = particle_audit(staged_xml, indexed_report_path)
    finite_face_checks = {
        "drawbox_extents_and_layers": drawboxes["all_required_drawbox_extents_exact"],
        "finite_bed_stl_reference": drawboxes["finite_bed_reference_present"],
        "finite_bed_triangle_count_positive": stl["triangle_count"] > 0,
        "finite_bed_bbox_nonzero": all(stl["bbox_max_m"][i] > stl["bbox_min_m"][i] for i in range(3)),
        "fixed_moving_fluid_type_counts": particles["positive_typed_fixed_moving_fluid"],
        "full_window_motion": motion["full_window"],
        "domain_covers_bed_fluid_piston": domain["full_physical_domain_coverage"],
    }
    all_audit_checks = all(finite_face_checks.values()) and particles["native_3d_and_expected_fluid"] and indexed_report["all_static_and_actual_checks"]
    return {
        "mechanism_id": mechanism,
        "case_id": case_id,
        "solver_case_id": spec["solver_case_id"],
        "gencase_receipt": bind(gencase_receipt, "immutable v7 actual GenCase receipt"),
        "generated_xml": bind(generated_xml, "immutable v7 actual GenCase XML"),
        "generated_bi4": bind(generated_bi4, "immutable v7 actual GenCase BI4"),
        "indexed_partvtk_report": bind(indexed_report_path, "immutable v8 indexed PartVTK report"),
        "source_motion": bind(motion_source, "immutable source motion"),
        "staged_xml": bind(staged_xml, "new co-located native solver XML"),
        "staged_bi4": bind(staged_bi4, "new co-located native solver BI4"),
        "staged_motion": bind(staged_motion, "new co-located native solver motion"),
        "staged_bed": bind(staged_bed, "new co-located native solver finite bed"),
        "gencase_counts": {key: receipt.get(key) for key in ("status", "returncode", "solver_dimension_from_gencase", "fluid_particles", "total_particles")},
        "indexed_partvtk": indexed_report["observed"],
        "drawbox_audit": drawboxes,
        "stl_audit": stl,
        "motion_audit": motion,
        "domain_audit": domain,
        "particle_audit": particles,
        "finite_face_checks": finite_face_checks,
        "all_native_preflight_checks": all_audit_checks,
        "stage_dir": str(stage_dir),
        "stage_prefix": str(stage_prefix),
    }


def make_request(mechanism: str, spec: dict[str, Any], evidence_path: Path, audit: dict[str, Any]) -> dict[str, Any]:
    solver_case_id = spec["solver_case_id"]
    stage_dir = Path(audit["stage_dir"])
    stage_prefix = Path(audit["stage_prefix"])
    gencase_receipt = Path(audit["gencase_receipt"]["path"])
    generated_xml = Path(audit["generated_xml"]["path"])
    generated_bi4 = Path(audit["generated_bi4"]["path"])
    input_paths = [
        SCRIPT, RUNNER_V2, SOLVER, V7_PRODUCER, V8_AUDITOR,
        QUALITY, EVENTS, SAVE_PLAN, BED, ACTUAL_EVIDENCE, evidence_path,
        spec["source_xml"], spec["source_metadata"], FAMILY_ROOT / "definitions" / spec["motion_name"],
        V7_ROOT / mechanism / "gencase-request-007.json",
        V7_ROOT / mechanism / "initialization-repair-preflight-007.json",
        V7_ROOT / mechanism / "initialization-repair-metadata-007.json",
        V7_ROOT / "previous_repair_failure_ledger_007.json",
        gencase_receipt, generated_xml, generated_bi4,
        Path(audit["indexed_partvtk_report"]["path"]),
        Path(audit["staged_xml"]["path"]), Path(audit["staged_bi4"]["path"]),
        Path(audit["staged_motion"]["path"]), Path(audit["staged_bed"]["path"]),
    ]
    input_paths = [Path(path).resolve() for path in input_paths]
    missing = [path for path in input_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(missing[0])
    total_particles = int(audit["gencase_counts"]["total_particles"])
    storage = estimate_storage_bytes(total_particles)
    attempt_id = f"qualification-f5-{mechanism}-phase-exact-007-native-reference-009"
    request_dir = V7_ROOT / "native_reference_009" / mechanism
    request_dir.mkdir(parents=True, exist_ok=True)
    output = {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": "F5",
        "case_id": solver_case_id,
        "source_case_id": spec["case_id"],
        "mechanism_id": mechanism,
        "attempt_id": attempt_id,
        "kind": "qualification",
        "command": [str(SOLVER), str(stage_prefix), "{attempt_root}/solver_output", "-tmax:16", "-tout:0.02"],
        "input_prefix": str(stage_prefix),
        "cwd": str(stage_dir),
        "worktree_root": str(WORKTREE_ROOT),
        "launch_commit": git_commit(),
        "max_wall_seconds": MAX_WALL_SECONDS,
        "cpu_threads": 4,
        "estimated_peak_gpu_mib": GPU_MEMORY_MIB,
        "estimated_storage_bytes": storage,
        "estimated_storage_basis": {
            "actual_total_particles": total_particles,
            "expected_native_frames": EXPECTED_FRAMES,
            "bytes_per_particle_frame": BYTES_PER_PARTICLE_FRAME,
            "base_bytes": total_particles * EXPECTED_FRAMES * BYTES_PER_PARTICLE_FRAME,
            "margin_bytes": STORAGE_MARGIN_BYTES,
            "rounded_storage_bytes": storage,
        },
        "event_window_s": EVENT_WINDOW_S,
        "save_interval_s": SAVE_INTERVAL_S,
        "time_out_s": SAVE_INTERVAL_S,
        "input_files": [str(path) for path in input_paths],
        "input_sha256": {str(path): sha256(path) for path in input_paths},
        "gencase_receipt": gencase_receipt.as_posix(),
        "gencase_receipt_sha256": sha256(gencase_receipt),
        "native_artifacts": {
            "staged_xml": bind(Path(audit["staged_xml"]["path"]), "co-located staged XML"),
            "staged_bi4": bind(Path(audit["staged_bi4"]["path"]), "co-located staged BI4"),
            "staged_motion": bind(Path(audit["staged_motion"]["path"]), "co-located staged motion"),
            "staged_bed": bind(Path(audit["staged_bed"]["path"]), "co-located staged bed STL"),
            "generated_xml_original": bind(generated_xml, "immutable actual GenCase XML"),
            "generated_bi4_original": bind(generated_bi4, "immutable actual GenCase BI4"),
        },
        "source_bindings": {
            "source_definition": bind(spec["source_xml"], "immutable physical source definition"),
            "source_metadata": bind(spec["source_metadata"], "immutable source metadata"),
            "source_motion": bind(FAMILY_ROOT / "definitions" / spec["motion_name"], "immutable source motion"),
            "source_bed": bind(BED, "immutable finite bed STL"),
            "quality_contract": bind(QUALITY, "frozen quality contract"),
            "event_definitions": bind(EVENTS, "frozen event definitions"),
            "integration_save_plan": bind(SAVE_PLAN, "frozen integration/save plan"),
        },
        "actual_native": {
            "total_particles": total_particles,
            "fluid_particles": int(audit["gencase_counts"]["fluid_particles"]),
            "solver_dimension": int(audit["gencase_counts"]["solver_dimension_from_gencase"]),
            "fluid_mass_kg": audit["indexed_partvtk"]["fluid_mass_kg"],
            "typed_counts": audit["particle_audit"]["actual_partvtk_type_counts"],
            "mk_counts": audit["particle_audit"]["actual_partvtk_mk_counts"],
        },
        "physical_face_audit": {
            "evidence_path": str(evidence_path.resolve()),
            "evidence_sha256": sha256(evidence_path),
            "all_native_preflight_checks": audit["all_native_preflight_checks"],
            "finite_face_checks": audit["finite_face_checks"],
            "domain": audit["domain_audit"],
            "motion": audit["motion_audit"],
        },
        "qualification_scope": "complete native 0-16 s macro reference only; same v7 recipe and finite geometry/control; Q-I/Q-N and production remain pending",
        "observables": ["WG1", "WG2", "WG3", "WG4", "runup_peak", "toe_first_arrival", "crest_first_passage", "notch_first_passage", "return_crossing", "terminal_destination", "initial_mass", "boundary_identity_audit"],
        "qualification_launch_authority": "shared_ds_data_02_runner_only_primary_process",
        "family_owner_gpu_launch_forbidden": True,
        "qualification_claim": "none",
        "production_claim": "none",
        "q_n_status": "pending root native review and solver execution",
        "raw_output_root": str(RAW_OUTPUT_ROOT),
        "recipe_id": "F5_CONTINUOUS_CELL_CENTRE_PHASE_EXACT_DP025_007",
        "request_note": "Input prefix is a new co-located stage; no files are added to or modified in consumed GenCase directories. Root/shared runner owns any solver launch.",
    }
    path = request_dir / "solver-request-009.json"
    write_json(path, output)
    output["path"] = str(path)
    output["sha256"] = sha256(path)
    return output


def main() -> None:
    if not ACTUAL_EVIDENCE.is_file():
        raise FileNotFoundError(ACTUAL_EVIDENCE)
    audits = {mechanism: stage_and_audit(mechanism, spec) for mechanism, spec in CASE_SPECS.items()}
    if not all(audit["all_native_preflight_checks"] for audit in audits.values()):
        raise RuntimeError("physical/native preflight failed; refusing to register solver requests")
    evidence_path = V7_ROOT / "native_reference_009" / "native_reference_preflight_009.json"
    evidence = {
        "schema": "ds-data-02.f5.native-reference-preflight.v1",
        "family_id": "F5",
        "scope": SCOPE,
        "created_at_utc": utc_now(),
        "status": "actual_staged_native_inputs_and_physical_face_audit_pass_pending_solver",
        "producer_script": bind(SCRIPT, "committed request/staging producer"),
        "producer_git_commit": git_commit(),
        "v7_actual_preflight": bind(ACTUAL_EVIDENCE, "immutable v7 indexed native preflight"),
        "registered_contract": {
            "continuous_box_low_m": [-0.9, -0.7, 0.02],
            "continuous_box_size_m": [4.2, 1.4, 0.4],
            "continuous_mass_kg": 2352.0,
            "dp_m": 0.025,
            "event_window_s": EVENT_WINDOW_S,
            "save_interval_s": SAVE_INTERVAL_S,
            "expected_frames": EXPECTED_FRAMES,
        },
        "cases": audits,
        "qualification_claim": "none",
        "production_claim": "none",
        "q_n_status": "pending root review and solver execution",
    }
    write_json(evidence_path, evidence)
    requests = {
        mechanism: make_request(mechanism, CASE_SPECS[mechanism], evidence_path, audits[mechanism])
        for mechanism in CASE_SPECS
    }
    # The evidence is intentionally written before requests, so requests bind
    # its stable hash without a circular report/request dependency.
    result = {"scope": SCOPE, "evidence": str(evidence_path), "cases": audits, "requests": requests, "git_commit": git_commit()}
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
