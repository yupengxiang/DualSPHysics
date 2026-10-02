#!/usr/bin/env python3
"""Prepare the F5 DP=.05/.0125 native 16 s solver requests.

The four inputs in this scope are already completed GenCase/PartVTK products.
This module makes a new, co-located execution stage for each product and
changes only the numerical ``simulationdomain`` to the domain used by the
successful DP=.025 domain-repair-011 reference.  It never runs GenCase,
PartVTK, DualSPHysics, a GPU, or a converter.  The resulting requests are
for root/shared-runner review only; they do not grant Q-I, Q-N, or production
status.

The staged control file, STL, and BI4 are byte-identical copies.  The staged
XML is byte-identical to the actual generated XML after its one
``simulationdomain`` element is normalized.  Thus the wider domain is an
execution envelope and cannot silently change the physical mother, fluid
mass, finite geometry, or prescribed control.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from typing import Any, Iterable, Mapping


SCRIPT = Path(__file__).resolve()
LAB_ROOT = SCRIPT.parents[1]
WORKTREE_ROOT = SCRIPT.parents[2]
FAMILY_ROOT = LAB_ROOT / "campaigns/ds-data-02/families/F5"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5")
RAW_OUTPUT_ROOT = DATA_ROOT / "case/attempt"
RUNNER_V2 = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
)
SOLVER = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
)
OLD_PRODUCER = LAB_ROOT / "scripts/ds_data02_f5_commensurate_dp_reference_010.py"
SOURCE_BED = FAMILY_ROOT / "definitions/assets/f5_continuous_bed_profile_slope_0p280.stl"
QUALITY_CONTRACT = FAMILY_ROOT / "quality_contract.json"
EVENT_DEFINITIONS = FAMILY_ROOT / "event_definitions.json"
SAVE_PLAN = FAMILY_ROOT / "integration_save_plan.json"
FAMILY_CARD = FAMILY_ROOT / "family_card.json"
REFERENCE_MATRIX = FAMILY_ROOT / "definitions/reference_matrix.json"
HISTORY_REUSE = FAMILY_ROOT / "history_reuse_inventory.json"
FAMILY_HANDOFF = FAMILY_ROOT / "FAMILY_HANDOFF.md"
COMMENSURATE_SCOPE = FAMILY_ROOT / (
    "initialization_repairs/F5_CONTINUOUS_CELL_CENTRE_COMMENSURATE_DP005_DP00125_010"
)
V7_SCOPE = FAMILY_ROOT / "initialization_repairs/F5_CONTINUOUS_CELL_CENTRE_PHASE_EXACT_DP025_007"
REPAIR_ROOT = FAMILY_ROOT / (
    "initialization_repairs/"
    "F5_CONTINUOUS_CELL_CENTRE_COMMENSURATE_DP005_DP00125_NATIVE_REFERENCE_011"
)

SCOPE = "F5_CONTINUOUS_CELL_CENTRE_COMMENSURATE_DP005_DP00125_NATIVE_REFERENCE_011"
STAGE_SCOPE = "F5_FOUR_DP_NATIVE_REFERENCE_011"
EVENT_WINDOW_S = 16.0
SAVE_INTERVAL_S = 0.02
EXPECTED_FRAMES = 801
RHO0 = 1000.0
CONTINUUM_MASS_KG = 2352.0
CONTINUUM_LOW = (-0.90, -0.70, 0.02)
CONTINUUM_SIZE = (4.20, 1.40, 0.40)

# These are the actual domain-repair-011 values from both successful DP=.025
# references.  They cover the finite native layers and the prescribed piston
# sweep with the same physical geometry/control as the DP=.025 mother.
DOMAIN_MIN = (-1.22, -0.92, -0.32)
DOMAIN_MAX = (11.0, 0.87, 1.45)

CASE_SPECS: dict[str, dict[str, Any]] = {
    "runup_dp005": {
        "mechanism_id": "runup_return",
        "resolution_id": "dp005",
        "dp_m": 0.05,
        "case_id": "F5_REF_RUNUP_NOMINAL_DP005_CELL_CENTRE_010",
        "source_definition": "F5_REF_RUNUP_NOMINAL_MEDIUM.xml",
        "source_metadata": "F5_REF_RUNUP_NOMINAL_MEDIUM.metadata.json",
        "motion": "piston_f91973457a049db5_regular_piston.dat",
        "generated_dir": "F5_REF_RUNUP_NOMINAL_DP005_CELL_CENTRE_010/gencase-f5-runup_return-dp005-cellcentre-commensurate-010",
        "gencase_receipt_dir": "F5_REF_RUNUP_NOMINAL_DP005_CELL_CENTRE_010/gencase-f5-runup_return-dp005-cellcentre-commensurate-010",
        "partvtk_dir": "F5_REF_RUNUP_NOMINAL_DP005_CELL_CENTRE_010/audit-f5-runup_return-dp005-cellcentre-010",
        "domain_reference_dir": "F5_REF_RUNUP_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007_NATIVE_REFERENCE_009",
        "domain_reference_case": "F5_REF_RUNUP_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007",
        "union_coverage_dir": "F5_REF_RUNUP_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007_NATIVE_REFERENCE_009/root-native-union-solid-coverage-003",
        "total_particles": 94790,
        "fluid_particles": 18816,
        "cpu_threads": 2,
        "max_wall_seconds": 1800,
        "estimated_peak_gpu_mib": 8192,
        "estimated_gpu_seconds": 1800,
    },
    "weir_dp005": {
        "mechanism_id": "weir_pair",
        "resolution_id": "dp005",
        "dp_m": 0.05,
        "case_id": "F5_REF_WEIR_NOMINAL_DP005_CELL_CENTRE_010",
        "source_definition": "F5_REF_WEIR_NOMINAL_MEDIUM.xml",
        "source_metadata": "F5_REF_WEIR_NOMINAL_MEDIUM.metadata.json",
        "motion": "piston_4c73cd98b7230035_regular_piston.dat",
        "generated_dir": "F5_REF_WEIR_NOMINAL_DP005_CELL_CENTRE_010/gencase-f5-weir_pair-dp005-cellcentre-commensurate-010",
        "gencase_receipt_dir": "F5_REF_WEIR_NOMINAL_DP005_CELL_CENTRE_010/gencase-f5-weir_pair-dp005-cellcentre-commensurate-010",
        "partvtk_dir": "F5_REF_WEIR_NOMINAL_DP005_CELL_CENTRE_010/audit-f5-weir_pair-dp005-cellcentre-010",
        "domain_reference_dir": "F5_REF_WEIR_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007_NATIVE_REFERENCE_009",
        "domain_reference_case": "F5_REF_WEIR_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007",
        "union_coverage_dir": "F5_REF_WEIR_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007_NATIVE_REFERENCE_009/root-native-union-solid-coverage-003",
        "total_particles": 96558,
        "fluid_particles": 18816,
        "cpu_threads": 2,
        "max_wall_seconds": 1800,
        "estimated_peak_gpu_mib": 8192,
        "estimated_gpu_seconds": 1800,
    },
    "runup_dp00125": {
        "mechanism_id": "runup_return",
        "resolution_id": "dp00125",
        "dp_m": 0.0125,
        "case_id": "F5_REF_RUNUP_NOMINAL_DP00125_CELL_CENTRE_010",
        "source_definition": "F5_REF_RUNUP_NOMINAL_MEDIUM.xml",
        "source_metadata": "F5_REF_RUNUP_NOMINAL_MEDIUM.metadata.json",
        "motion": "piston_f91973457a049db5_regular_piston.dat",
        "generated_dir": "F5_REF_RUNUP_NOMINAL_DP00125_CELL_CENTRE_010/gencase-f5-runup_return-dp00125-cellcentre-commensurate-010",
        "gencase_receipt_dir": "F5_REF_RUNUP_NOMINAL_DP00125_CELL_CENTRE_010/gencase-f5-runup_return-dp00125-cellcentre-commensurate-010",
        "partvtk_dir": "F5_REF_RUNUP_NOMINAL_DP00125_CELL_CENTRE_010/audit-f5-runup_return-dp00125-cellcentre-010",
        "domain_reference_dir": "F5_REF_RUNUP_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007_NATIVE_REFERENCE_009",
        "domain_reference_case": "F5_REF_RUNUP_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007",
        "union_coverage_dir": "F5_REF_RUNUP_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007_NATIVE_REFERENCE_009/root-native-union-solid-coverage-003",
        "total_particles": 4040985,
        "fluid_particles": 1204224,
        "cpu_threads": 4,
        "max_wall_seconds": 14400,
        "estimated_peak_gpu_mib": 32768,
        "estimated_gpu_seconds": 7360,
    },
    "weir_dp00125": {
        "mechanism_id": "weir_pair",
        "resolution_id": "dp00125",
        "dp_m": 0.0125,
        "case_id": "F5_REF_WEIR_NOMINAL_DP00125_CELL_CENTRE_010",
        "source_definition": "F5_REF_WEIR_NOMINAL_MEDIUM.xml",
        "source_metadata": "F5_REF_WEIR_NOMINAL_MEDIUM.metadata.json",
        "motion": "piston_4c73cd98b7230035_regular_piston.dat",
        "generated_dir": "F5_REF_WEIR_NOMINAL_DP00125_CELL_CENTRE_010/gencase-f5-weir_pair-dp00125-cellcentre-commensurate-010",
        "gencase_receipt_dir": "F5_REF_WEIR_NOMINAL_DP00125_CELL_CENTRE_010/gencase-f5-weir_pair-dp00125-cellcentre-commensurate-010",
        "partvtk_dir": "F5_REF_WEIR_NOMINAL_DP00125_CELL_CENTRE_010/audit-f5-weir_pair-dp00125-cellcentre-010",
        "domain_reference_dir": "F5_REF_WEIR_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007_NATIVE_REFERENCE_009",
        "domain_reference_case": "F5_REF_WEIR_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007",
        "union_coverage_dir": "F5_REF_WEIR_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007_NATIVE_REFERENCE_009/root-native-union-solid-coverage-003",
        "total_particles": 4070667,
        "fluid_particles": 1204224,
        "cpu_threads": 4,
        "max_wall_seconds": 14400,
        "estimated_peak_gpu_mib": 32768,
        "estimated_gpu_seconds": 7360,
    },
}

SIM_DOMAIN_RE = re.compile(r"<simulationdomain\b[^>]*>.*?</simulationdomain>", re.DOTALL)
POSITION_TAG_RE = {
    "posmin": re.compile(r"<posmin\b[^>]*/>"),
    "posmax": re.compile(r"<posmax\b[^>]*/>"),
}
FLOAT_RE = re.compile(r"[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?")


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
    if path.exists():
        raise FileExistsError(f"refusing to overwrite additive F5 artifact: {path}")
    partial = path.with_name(path.name + f".{os.getpid()}.partial")
    partial.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    partial.replace(path)


def git_head() -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(WORKTREE_ROOT), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN_GIT_COMMIT"


def q(value: float) -> str:
    return f"{float(value):.12f}".rstrip("0").rstrip(".") or "0"


def _path(*parts: str) -> Path:
    return DATA_ROOT.joinpath(*parts)


def case_paths(key: str, spec: Mapping[str, Any]) -> dict[str, Path]:
    generated_dir = _path(str(spec["generated_dir"]))
    partvtk_dir = _path(str(spec["partvtk_dir"]))
    case_id = str(spec["case_id"])
    return {
        "generated_dir": generated_dir,
        "generated_xml": generated_dir / f"{case_id}.xml",
        "generated_bi4": generated_dir / f"{case_id}.bi4",
        "gencase_receipt": generated_dir / "execution-receipt.json",
        "partvtk_dir": partvtk_dir,
        "partvtk_receipt": partvtk_dir / "execution-receipt.json",
        "partvtk_report": partvtk_dir / "partvtk-audit-010.json",
        "partvtk_csv": partvtk_dir / "partvtk-initial-010.csv",
        "stage_dir": _path(STAGE_SCOPE, f"{case_id}/native_inputs_domain_repair_011"),
        "domain_reference_dir": _path(
            str(spec["domain_reference_dir"]), "native_inputs_domain_repair_011"
        ),
        "domain_reference_xml": _path(
            str(spec["domain_reference_dir"]),
            "native_inputs_domain_repair_011",
            f"{spec['domain_reference_case']}.xml",
        ),
        "domain_reference_receipt": _path(
            str(spec["domain_reference_dir"]),
            f"qualification-f5-{spec['mechanism_id']}-phase-exact-007-native-reference-009-domain-repair-011",
            "execution-receipt.json",
        ),
        "union_coverage": _path(
            str(spec["union_coverage_dir"]), "native-solid-coverage.json"
        ),
    }


def source_paths(spec: Mapping[str, Any]) -> dict[str, Path]:
    return {
        "definition": FAMILY_ROOT / "definitions" / str(spec["source_definition"]),
        "metadata": FAMILY_ROOT / "definitions" / str(spec["source_metadata"]),
        "motion": FAMILY_ROOT / "definitions" / str(spec["motion"]),
        "bed": SOURCE_BED,
    }


def _source_reference_files() -> list[Path]:
    return [
        SCRIPT,
        OLD_PRODUCER,
        RUNNER_V2,
        SOLVER,
        QUALITY_CONTRACT,
        EVENT_DEFINITIONS,
        SAVE_PLAN,
        FAMILY_CARD,
        REFERENCE_MATRIX,
        HISTORY_REUSE,
        FAMILY_HANDOFF,
        SOURCE_BED,
        V7_SCOPE / "actual_preflight_evidence_007.json",
        V7_SCOPE / "native_reference_009/native_reference_preflight_009.json",
    ]


def _unique(paths: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for value in paths:
        path = Path(value).resolve()
        if str(path) not in seen:
            seen.add(str(path))
            result.append(path)
    return result


def copy_exact(source: Path, target: Path) -> None:
    source = Path(source).resolve()
    target = Path(target).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if not target.is_file() or sha256(source) != sha256(target):
            raise FileExistsError(f"existing stage differs; refusing overwrite: {target}")
        return
    shutil.copy2(source, target)


def replace_domain(xml_text: str) -> str:
    matches = list(SIM_DOMAIN_RE.finditer(xml_text))
    if len(matches) != 1:
        raise ValueError(f"expected one simulationdomain, found {len(matches)}")
    section = matches[0].group(0)
    for tag, values in (("posmin", DOMAIN_MIN), ("posmax", DOMAIN_MAX)):
        tag_matches = list(POSITION_TAG_RE[tag].finditer(section))
        if len(tag_matches) != 1:
            raise ValueError(f"expected one {tag} tag, found {len(tag_matches)}")
        original = tag_matches[0].group(0)
        replaced = original
        for axis, value in zip("xyz", values):
            replaced, count = re.subn(
                rf'\b{axis}="[^"]*"', f'{axis}="{q(value)}"', replaced, count=1
            )
            if count != 1:
                raise ValueError(f"{tag} lacks {axis} attribute")
        section = section.replace(original, replaced, 1)
    return xml_text[: matches[0].start()] + section + xml_text[matches[0].end() :]


def canonical_without_domain(xml_text: str) -> str:
    matches = list(SIM_DOMAIN_RE.finditer(xml_text))
    if len(matches) != 1:
        raise ValueError(f"expected one simulationdomain, found {len(matches)}")
    return xml_text[: matches[0].start()] + "<simulationdomain data='DOMAIN_REDACTED'/ >" + xml_text[matches[0].end() :]


def _domain_from_xml(xml_path: Path) -> tuple[tuple[float, ...], tuple[float, ...]]:
    root = ET.parse(xml_path).getroot()
    node = root.find(".//simulationdomain")
    if node is None:
        raise ValueError(f"missing simulationdomain: {xml_path}")
    lo = node.find("posmin")
    hi = node.find("posmax")
    if lo is None or hi is None:
        raise ValueError(f"incomplete simulationdomain: {xml_path}")
    return (
        tuple(float(lo.attrib[axis]) for axis in "xyz"),
        tuple(float(hi.attrib[axis]) for axis in "xyz"),
    )


def _motion_stats(path: Path) -> dict[str, Any]:
    rows: list[tuple[float, float]] = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            fields = text.split()
            if len(fields) < 2:
                raise ValueError(f"invalid motion row: {path}: {text}")
            rows.append((float(fields[0]), float(fields[1])))
    if not rows:
        raise ValueError(f"motion has no rows: {path}")
    times = [row[0] for row in rows]
    displacement = [row[1] for row in rows]
    return {
        "row_count": len(rows),
        "time_start_s": times[0],
        "time_end_s": times[-1],
        "displacement_min_m": min(displacement),
        "displacement_max_m": max(displacement),
        "full_window": math.isclose(times[0], 0.0, abs_tol=1.0e-12)
        and math.isclose(times[-1], EVENT_WINDOW_S, abs_tol=1.0e-12),
    }


def _stl_bounds(path: Path) -> tuple[list[float], list[float]]:
    values: list[tuple[float, float, float]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        fields = line.split()
        if len(fields) == 4 and fields[0].lower() == "vertex":
            values.append(tuple(float(value) for value in fields[1:4]))
    if not values:
        raise ValueError(f"ASCII STL has no vertices: {path}")
    return [min(row[i] for row in values) for i in range(3)], [max(row[i] for row in values) for i in range(3)]


def _drawbox_extents(xml_path: Path) -> list[dict[str, Any]]:
    root = ET.parse(xml_path).getroot()
    extents: list[dict[str, Any]] = []
    for box in root.findall(".//drawbox"):
        point = box.find("point")
        size = box.find("size")
        if point is None or size is None:
            continue
        lo = [float(point.attrib[axis]) for axis in "xyz"]
        hi = [lo[i] + float(size.attrib[axis]) for i, axis in enumerate("xyz")]
        extents.append({"comment": box.attrib.get("cmt", ""), "min_m": lo, "max_m": hi})
    if not extents:
        raise ValueError(f"generated XML contains no drawbox geometry: {xml_path}")
    return extents


def _domain_geometry_audit(xml_path: Path, motion_path: Path, bed_path: Path) -> dict[str, Any]:
    lo, hi = _domain_from_xml(xml_path)
    drawboxes = _drawbox_extents(xml_path)
    motion = _motion_stats(motion_path)
    # The generated piston drawbox is the only prescribed x-moving finite
    # object in these mothers.  The static extent is expanded by the actual
    # control displacement, retaining the source y/z extents.
    piston = next((entry for entry in drawboxes if entry["comment"] == "prescribed_piston"), None)
    if piston is None:
        raise ValueError("prescribed_piston drawbox missing")
    piston_min = list(piston["min_m"])
    piston_max = list(piston["max_m"])
    swept = {
        "min_m": [piston_min[0] + motion["displacement_min_m"], piston_min[1], piston_min[2]],
        "max_m": [piston_max[0] + motion["displacement_max_m"], piston_max[1], piston_max[2]],
    }
    stl_min, stl_max = _stl_bounds(bed_path)
    extents = [*drawboxes, {"comment": "finite_bed_stl", "min_m": stl_min, "max_m": stl_max}, {"comment": "piston_sweep", **swept}]
    inside = all(
        lo[axis] <= extent["min_m"][axis] and extent["max_m"][axis] <= hi[axis]
        for extent in extents
        for axis in range(3)
    )
    return {
        "domain_min_m": list(lo),
        "domain_max_m": list(hi),
        "drawbox_count": len(drawboxes),
        "drawbox_extents_m": drawboxes,
        "bed_stl_bounds_m": {"min": stl_min, "max": stl_max},
        "piston_swept_bounds_m": swept,
        "motion": motion,
        "all_declared_geometry_and_motion_inside_domain": inside,
        "domain_matches_repair_011": all(
            math.isclose(lo[i], DOMAIN_MIN[i], abs_tol=1.0e-12)
            and math.isclose(hi[i], DOMAIN_MAX[i], abs_tol=1.0e-12)
            for i in range(3)
        ),
    }


def _partvtk_support_audit(key: str, spec: Mapping[str, Any], report_path: Path) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    checks = report.get("checks", {})
    observed = report.get("observed", {})
    marker_checks = report.get("finite_geometry_markers", {})
    required_markers = [
        "tank_floor",
        "finite_sidewall_left",
        "finite_sidewall_right",
        "prescribed_piston",
        "finite_bed_stl",
    ]
    if spec["mechanism_id"] == "weir_pair":
        required_markers += ["weir_left_side_segment", "weir_right_side_segment"]
    required_mks = ["1", "20", "40", "50"] + (["60"] if spec["mechanism_id"] == "weir_pair" else [])
    mk_counts = {str(k): int(v) for k, v in observed.get("mk_counts", {}).items()}
    type_counts = {str(k): int(v) for k, v in observed.get("type_counts", {}).items()}
    return {
        "report": bind(report_path, "actual official PartVTK initial audit"),
        "report_all_checks_pass": bool(report.get("all_actual_checks_pass")),
        "required_marker_names": required_markers,
        "required_marker_names_present": all(bool(marker_checks.get(name)) for name in required_markers),
        "required_native_mk_counts": {mk: mk_counts.get(mk, 0) for mk in required_mks},
        "required_native_mk_positive": all(mk_counts.get(mk, 0) > 0 for mk in required_mks),
        "typed_counts": type_counts,
        "actual_3d_and_fluid_fixed_moving": type_counts.get("3", 0) == int(spec["fluid_particles"])
        and type_counts.get("0", 0) > 0
        and type_counts.get("1", 0) > 0,
        "support_scope": "PartVTK initial marker/mk/type evidence; root must retain the DP025 union-face/STL witness and review DP-specific native support before launch",
        "root_union_face_witness_required": True,
    }


def _receipt_contract(key: str, spec: Mapping[str, Any], paths: Mapping[str, Path]) -> dict[str, Any]:
    receipt = json.loads(paths["gencase_receipt"].read_text(encoding="utf-8"))
    if receipt.get("status") != "completed" or int(receipt.get("returncode", 1)) != 0:
        raise ValueError(f"completed GenCase receipt required: {paths['gencase_receipt']}")
    if int(receipt.get("total_particles", 0)) != int(spec["total_particles"]):
        raise ValueError(f"total particle mismatch in {key}: {receipt.get('total_particles')}")
    if int(receipt.get("fluid_particles", 0)) != int(spec["fluid_particles"]):
        raise ValueError(f"fluid particle mismatch in {key}: {receipt.get('fluid_particles')}")
    if int(receipt.get("solver_dimension_from_gencase", 0)) != 3:
        raise ValueError(f"GenCase is not 3-D in {key}")
    if not paths["generated_xml"].is_file() or not paths["generated_bi4"].is_file():
        raise FileNotFoundError(f"generated native prefix incomplete for {key}")
    partvtk = json.loads(paths["partvtk_report"].read_text(encoding="utf-8"))
    if not partvtk.get("all_actual_checks_pass"):
        raise ValueError(f"PartVTK audit is not fully passing for {key}")
    if int(partvtk["observed"]["fluid_count"]) != int(spec["fluid_particles"]):
        raise ValueError(f"PartVTK fluid count mismatch in {key}")
    if not math.isclose(float(partvtk["observed"]["fluid_mass_kg"]), CONTINUUM_MASS_KG, abs_tol=1.0e-5):
        raise ValueError(f"PartVTK mass mismatch in {key}")
    return {"receipt": receipt, "partvtk": partvtk}


def _stage_case(key: str, spec: Mapping[str, Any], paths: Mapping[str, Path]) -> dict[str, Any]:
    source = source_paths(spec)
    paths["stage_dir"].mkdir(parents=True, exist_ok=True)
    stage_xml = paths["stage_dir"] / f"{spec['case_id']}.xml"
    stage_bi4 = paths["stage_dir"] / f"{spec['case_id']}.bi4"
    stage_motion = paths["stage_dir"] / str(spec["motion"])
    stage_bed = paths["stage_dir"] / "assets" / SOURCE_BED.name
    original_text = paths["generated_xml"].read_text(encoding="utf-8")
    staged_text = replace_domain(original_text)
    ET.fromstring(staged_text)
    if stage_xml.exists():
        if stage_xml.read_text(encoding="utf-8") != staged_text:
            raise FileExistsError(f"existing staged XML differs: {stage_xml}")
    else:
        stage_xml.write_text(staged_text, encoding="utf-8")
    copy_exact(paths["generated_bi4"], stage_bi4)
    copy_exact(source["motion"], stage_motion)
    copy_exact(source["bed"], stage_bed)
    original_domain = _domain_from_xml(paths["generated_xml"])
    staged_domain = _domain_from_xml(stage_xml)
    if canonical_without_domain(original_text) != canonical_without_domain(staged_text):
        raise AssertionError(f"staged XML changed more than simulationdomain: {key}")
    if staged_domain != (DOMAIN_MIN, DOMAIN_MAX):
        raise AssertionError(f"staged domain mismatch: {key}: {staged_domain}")
    if sha256(paths["generated_bi4"]) != sha256(stage_bi4):
        raise AssertionError(f"staged BI4 mismatch: {key}")
    if sha256(source["motion"]) != sha256(stage_motion) or sha256(source["bed"]) != sha256(stage_bed):
        raise AssertionError(f"staged external input mismatch: {key}")
    return {
        "stage_dir": paths["stage_dir"],
        "stage_xml": stage_xml,
        "stage_bi4": stage_bi4,
        "stage_motion": stage_motion,
        "stage_bed": stage_bed,
        "source_domain": {"min_m": list(original_domain[0]), "max_m": list(original_domain[1])},
        "stage_domain": {"min_m": list(staged_domain[0]), "max_m": list(staged_domain[1])},
        "canonical_only_simulationdomain_change": True,
        "bi4_byte_identical": True,
        "motion_byte_identical": True,
        "bed_byte_identical": True,
    }


def _estimated_storage(total_particles: int) -> dict[str, int]:
    base = int(total_particles) * EXPECTED_FRAMES * 64
    margin = 2 * 1024**3
    rounded = ((base + margin + 1024**3 - 1) // 1024**3) * 1024**3
    return {
        "actual_total_particles": int(total_particles),
        "bytes_per_particle_frame": 64,
        "expected_native_frames": EXPECTED_FRAMES,
        "base_bytes": base,
        "margin_bytes": margin,
        "rounded_storage_bytes": rounded,
    }


def _input_paths(key: str, spec: Mapping[str, Any], paths: Mapping[str, Path], stage: Mapping[str, Any]) -> list[Path]:
    source = source_paths(spec)
    domain_dir = paths["domain_reference_dir"]
    domain_receipt = paths["domain_reference_receipt"]
    return _unique(
        [
            *_source_reference_files(),
            source["definition"],
            source["metadata"],
            source["motion"],
            source["bed"],
            COMMENSURATE_SCOPE / key / "commensurate-dp-metadata-010.json",
            COMMENSURATE_SCOPE / key / "commensurate-dp-static-preflight-010.json",
            COMMENSURATE_SCOPE / key / "gencase-request-010.json",
            COMMENSURATE_SCOPE / key / "partvtk-audit-request-010.json",
            paths["gencase_receipt"],
            paths["generated_xml"],
            paths["generated_bi4"],
            paths["partvtk_receipt"],
            paths["partvtk_report"],
            paths["partvtk_csv"],
            V7_SCOPE / "native_reference_009" / f"{str(spec['mechanism_id'])}/solver-request-009.json",
            V7_SCOPE / "native_reference_009/native_reference_preflight_009.json",
            domain_dir / paths["domain_reference_xml"].name,
            domain_receipt,
            paths["union_coverage"],
            stage["stage_xml"],
            stage["stage_bi4"],
            stage["stage_motion"],
            stage["stage_bed"],
        ]
    )


def _request(key: str, spec: Mapping[str, Any], paths: Mapping[str, Path], stage: Mapping[str, Any], evidence: Mapping[str, Any]) -> dict[str, Any]:
    input_paths = _input_paths(key, spec, paths, stage)
    for path in input_paths:
        if not path.is_file():
            raise FileNotFoundError(f"request input missing for {key}: {path}")
    input_prefix = stage["stage_dir"] / str(spec["case_id"])
    storage = _estimated_storage(int(spec["total_particles"]))
    source = source_paths(spec)
    stage_xml = stage["stage_xml"]
    generated_xml_text = paths["generated_xml"].read_text(encoding="utf-8")
    staged_xml_text = stage_xml.read_text(encoding="utf-8")
    request = {
        "schema": "ds-data-02.runner.request.v2",
        "kind": "qualification",
        "family_id": "F5",
        "mechanism_id": spec["mechanism_id"],
        "resolution_id": spec["resolution_id"],
        "case_id": spec["case_id"],
        "attempt_id": f"qualification-f5-{spec['mechanism_id']}-{spec['resolution_id']}-native-reference-011",
        "command": [str(SOLVER), str(input_prefix), "{attempt_root}/solver_output", "-tmax:16", "-tout:0.02"],
        "input_prefix": str(input_prefix),
        "gencase_receipt": str(paths["gencase_receipt"]),
        "gencase_receipt_sha256": sha256(paths["gencase_receipt"]),
        "cwd": str(stage["stage_dir"]),
        "max_wall_seconds": int(spec["max_wall_seconds"]),
        "cpu_threads": int(spec["cpu_threads"]),
        "estimated_peak_gpu_mib": int(spec["estimated_peak_gpu_mib"]),
        "estimated_gpu_seconds": int(spec["estimated_gpu_seconds"]),
        "cost_estimate": {
            "reference": "F5 DP=.025 domain-repair-011 successful full 16 s native solver ~460 GPU s",
            "scaling_basis": "DP=.05 coarse request is a bounded macro reference; DP=.0125 fine uses approximately 8x native particles and 2x measured timestep cost",
            "root_cost_review_required": True,
        },
        "estimated_storage_basis": storage,
        "estimated_storage_bytes": storage["rounded_storage_bytes"],
        "expected_native_frames": EXPECTED_FRAMES,
        "event_window_s": EVENT_WINDOW_S,
        "save_interval_s": SAVE_INTERVAL_S,
        "time_out_s": SAVE_INTERVAL_S,
        "raw_output_root": str(RAW_OUTPUT_ROOT),
        "worktree_root": str(WORKTREE_ROOT),
        "launch_commit": git_head(),
        "runner_v2": bind(RUNNER_V2, "shared CPU/GPU request runner v2"),
        "solver_binary": bind(SOLVER, "official DualSPHysics solver"),
        "input_files": [str(path) for path in input_paths],
        "input_sha256": {str(path): sha256(path) for path in input_paths},
        "source_bindings": {
            "physical_mother_definition": bind(source["definition"], "immutable physical mother definition"),
            "physical_mother_metadata": bind(source["metadata"], "immutable physical mother metadata"),
            "control": bind(source["motion"], "immutable prescribed 16 s control"),
            "finite_bed_stl": bind(source["bed"], "immutable finite bed STL"),
            "actual_gencase_receipt": bind(paths["gencase_receipt"], "actual completed GenCase receipt"),
            "actual_generated_xml": bind(paths["generated_xml"], "actual generated XML"),
            "actual_generated_bi4": bind(paths["generated_bi4"], "actual generated BI4"),
            "actual_partvtk_receipt": bind(paths["partvtk_receipt"], "actual PartVTK receipt"),
            "actual_partvtk_audit": bind(paths["partvtk_report"], "actual PartVTK audit"),
            "dp025_domain_reference_xml": bind(paths["domain_reference_xml"], "successful DP=.025 domain-repair-011 XML"),
            "dp025_domain_reference_receipt": bind(paths["domain_reference_receipt"], "successful DP=.025 domain-repair-011 solver receipt"),
            "dp025_union_finite_support_witness": bind(paths["union_coverage"], "root DP=.025 union finite-face/STL witness"),
            "staged_xml": bind(stage_xml, "new co-located execution XML; domain-only change"),
            "staged_bi4": bind(stage["stage_bi4"], "new co-located BI4 byte-identical to actual GenCase"),
            "staged_motion": bind(stage["stage_motion"], "new co-located control byte-identical to source"),
            "staged_bed": bind(stage["stage_bed"], "new co-located bed STL byte-identical to source"),
        },
        "native_artifacts": {
            "actual_native": {
                "total_particles": int(spec["total_particles"]),
                "fluid_particles": int(spec["fluid_particles"]),
                "fluid_mass_kg": CONTINUUM_MASS_KG,
                "solver_dimension": 3,
            },
            "source_gencase": {
                "xml": bind(paths["generated_xml"], "immutable actual GenCase XML"),
                "bi4": bind(paths["generated_bi4"], "immutable actual GenCase BI4"),
            },
            "staged": {
                "xml": bind(stage_xml, "co-located execution XML"),
                "bi4": bind(stage["stage_bi4"], "co-located execution BI4"),
                "motion": bind(stage["stage_motion"], "co-located execution control"),
                "bed": bind(stage["stage_bed"], "co-located execution bed"),
            },
        },
        "physical_contract": {
            "continuous_fluid_low_m": list(CONTINUUM_LOW),
            "continuous_fluid_size_m": list(CONTINUUM_SIZE),
            "continuous_fluid_volume_m3": math.prod(CONTINUUM_SIZE),
            "density_kg_m3": RHO0,
            "fluid_mass_kg": CONTINUUM_MASS_KG,
            "mass_denominator_unchanged": True,
            "finite_geometry_and_stl_unchanged": True,
            "control_phase_and_bytes_unchanged": True,
            "execution_domain_only_change": True,
            "physical_mother_resolution_change": True,
        },
        "domain_repair_contract": {
            "basis": "successful DP=.025 domain-repair-011; same finite geometry/control and swept piston envelope",
            "posmin_m": list(DOMAIN_MIN),
            "posmax_m": list(DOMAIN_MAX),
            "staged_xml_domain_exact": stage["stage_domain"],
            "source_generated_xml_domain": stage["source_domain"],
            "stage_diff_canonical_only_simulationdomain": stage["canonical_only_simulationdomain_change"],
            "generated_bi4_unchanged": stage["bi4_byte_identical"],
            "motion_unchanged": stage["motion_byte_identical"],
            "bed_unchanged": stage["bed_byte_identical"],
            "geometry_and_control_inside_domain": evidence["domain_geometry"],
            "root_domain_review_required": True,
        },
        "physical_face_audit": evidence["face_audit"],
        "control_audit": evidence["control_audit"],
        "actual_native_preflight": evidence["actual_native_preflight"],
        "family_observables": [
            "WG1", "WG2", "WG3", "WG4", "runup_peak", "toe_first_arrival",
            "crest_first_passage", "notch_first_passage", "return_crossing",
            "terminal_destination", "initial_mass", "boundary_identity_audit",
        ],
        "family_owner_gpu_launch_forbidden": True,
        "qualification_launch_authority": "root primary through shared DS-DATA-02 runner only",
        "qualification_scope": "complete native 0-16 s macro reference at new DP; Q-I/Q-N and production remain pending",
        "q_n_status": "pending root native finite-face review and solver execution",
        "qualification_claim": "none",
        "production_claim": "none",
        "request_note": "Fresh co-located execution stage. Do not modify consumed GenCase/PartVTK assets. Root must review cost, domain, finite-face support and source hashes before any GPU launch.",
    }
    return request


def prepare() -> dict[str, Any]:
    REPAIR_ROOT.mkdir(parents=True, exist_ok=True)
    cases: dict[str, Any] = {}
    for key, spec in CASE_SPECS.items():
        paths = case_paths(key, spec)
        contract = _receipt_contract(key, spec, paths)
        stage = _stage_case(key, spec, paths)
        source = source_paths(spec)
        domain_geometry = _domain_geometry_audit(stage["stage_xml"], stage["stage_motion"], stage["stage_bed"])
        face_audit = _partvtk_support_audit(key, spec, paths["partvtk_report"])
        domain_reference_domain = _domain_from_xml(paths["domain_reference_xml"])
        if domain_reference_domain != (DOMAIN_MIN, DOMAIN_MAX):
            raise AssertionError(f"DP025 reference domain mismatch for {key}: {domain_reference_domain}")
        domain_reference_xml = paths["domain_reference_xml"].read_text(encoding="utf-8")
        root_union = json.loads(paths["union_coverage"].read_text(encoding="utf-8"))
        if not root_union.get("pass") or not all(root_union.get("checks", {}).values()):
            raise ValueError(f"DP025 root union support witness is not passing: {paths['union_coverage']}")
        motion_stats = _motion_stats(stage["stage_motion"])
        control_audit = {
            "motion_file": bind(stage["stage_motion"], "staged 16 s piston control"),
            "source_motion": bind(source["motion"], "source 16 s piston control"),
            "byte_identical": sha256(source["motion"]) == sha256(stage["stage_motion"]),
            "row_count": motion_stats["row_count"],
            "time_start_s": motion_stats["time_start_s"],
            "time_end_s": motion_stats["time_end_s"],
            "displacement_min_m": motion_stats["displacement_min_m"],
            "displacement_max_m": motion_stats["displacement_max_m"],
            "full_window": motion_stats["full_window"],
            "xml_motion_duration_s": 16.0,
            "control_phase_pass": motion_stats["full_window"] and motion_stats["row_count"] == 641,
        }
        # Keep assignment above readable in JSON while avoiding a false
        # assertion that a control file alone proves solver interpolation.
        control_audit["control_phase_pass"] = bool(
            control_audit["byte_identical"]
            and control_audit["full_window"]
            and control_audit["row_count"] == 641
        )
        actual_checks = {
            "gencase_completed": contract["receipt"].get("status") == "completed" and int(contract["receipt"].get("returncode", 1)) == 0,
            "positive_fluid": int(contract["receipt"].get("fluid_particles", 0)) > 0,
            "actual_3d": int(contract["receipt"].get("solver_dimension_from_gencase", 0)) == 3,
            "expected_total_particles": int(contract["receipt"].get("total_particles", 0)) == int(spec["total_particles"]),
            "expected_fluid_particles": int(contract["receipt"].get("fluid_particles", 0)) == int(spec["fluid_particles"]),
            "partvtk_exact_fluid_mass": math.isclose(float(contract["partvtk"]["observed"]["fluid_mass_kg"]), CONTINUUM_MASS_KG, abs_tol=1.0e-5),
            "partvtk_all_checks_pass": bool(contract["partvtk"].get("all_actual_checks_pass")),
            "domain_reference_matches": domain_reference_domain == (DOMAIN_MIN, DOMAIN_MAX),
            "domain_geometry_inside": domain_geometry["all_declared_geometry_and_motion_inside_domain"],
            "motion_control_pass": control_audit["control_phase_pass"],
            "finite_marker_and_native_mk_support": face_audit["required_marker_names_present"] and face_audit["required_native_mk_positive"],
        }
        evidence = {
            "schema": "ds-data-02.f5.native-solver-preflight-011.v1",
            "family_id": "F5",
            "scope": SCOPE,
            "case_key": key,
            "case_id": spec["case_id"],
            "mechanism_id": spec["mechanism_id"],
            "resolution_id": spec["resolution_id"],
            "created_at_utc": utc_now(),
            "producer_script": bind(SCRIPT, "committed native solver request producer"),
            "actual_gencase_receipt": bind(paths["gencase_receipt"], "actual completed GenCase receipt"),
            "actual_partvtk_audit": bind(paths["partvtk_report"], "actual completed PartVTK audit"),
            "domain_reference": {
                "xml": bind(paths["domain_reference_xml"], "successful DP=.025 domain-repair-011 XML"),
                "solver_receipt": bind(paths["domain_reference_receipt"], "successful DP=.025 domain-repair-011 receipt"),
                "root_union_support_witness": bind(paths["union_coverage"], "successful DP=.025 union finite-face/STL witness"),
                "domain_min_m": list(DOMAIN_MIN),
                "domain_max_m": list(DOMAIN_MAX),
                "canonical_execution_domain_only": True,
            },
            "stage": {
                "directory": str(stage["stage_dir"]),
                "xml": bind(stage["stage_xml"], "co-located execution XML"),
                "bi4": bind(stage["stage_bi4"], "co-located execution BI4"),
                "motion": bind(stage["stage_motion"], "co-located execution motion"),
                "bed": bind(stage["stage_bed"], "co-located execution bed STL"),
                "source_xml_canonical_without_domain_equal": stage["canonical_only_simulationdomain_change"],
                "bi4_byte_identical": stage["bi4_byte_identical"],
                "motion_byte_identical": stage["motion_byte_identical"],
                "bed_byte_identical": stage["bed_byte_identical"],
            },
            "actual_native": {
                "total_particles": int(spec["total_particles"]),
                "fluid_particles": int(spec["fluid_particles"]),
                "fluid_mass_kg": CONTINUUM_MASS_KG,
                "solver_dimension": 3,
                "source_receipt_fields": {
                    key: contract["receipt"].get(key)
                    for key in ("status", "returncode", "total_particles", "fluid_particles", "solver_dimension_from_gencase", "output_root")
                },
            },
            "domain_geometry": domain_geometry,
            "control_audit": control_audit,
            "native_support_audit": face_audit,
            "checks": actual_checks,
            "all_static_and_actual_preflight_checks_pass": all(actual_checks.values()),
            "root_native_dp_specific_union_face_review_required": True,
            "q_n_status": "pending root review and solver execution",
            "qualification_claim": "none",
            "production_claim": "none",
        }
        evidence_path = REPAIR_ROOT / key / "native-solver-preflight-011.json"
        if not evidence_path.exists():
            write_json(evidence_path, evidence)
        request = _request(key, spec, paths, stage, {
            "domain_geometry": domain_geometry,
            "face_audit": face_audit,
            "control_audit": control_audit,
            "actual_native_preflight": evidence,
        })
        request_path = REPAIR_ROOT / key / "solver-request-011.json"
        if not request_path.exists():
            write_json(request_path, request)
        cases[key] = {
            "case_id": spec["case_id"],
            "request": str(request_path),
            "request_sha256": sha256(request_path),
            "preflight": str(evidence_path),
            "preflight_sha256": sha256(evidence_path),
            "stage_dir": str(stage["stage_dir"]),
            "input_prefix": str(stage["stage_dir"] / str(spec["case_id"])),
            "total_particles": int(spec["total_particles"]),
            "fluid_particles": int(spec["fluid_particles"]),
            "estimated_storage_bytes": request["estimated_storage_bytes"],
            "max_wall_seconds": spec["max_wall_seconds"],
            "all_static_and_actual_preflight_checks_pass": evidence["all_static_and_actual_preflight_checks_pass"],
        }
    manifest = {
        "schema": "ds-data-02.f5.native-solver-request-manifest-011.v1",
        "family_id": "F5",
        "scope": SCOPE,
        "stage_scope": STAGE_SCOPE,
        "created_at_utc": utc_now(),
        "producer_script": bind(SCRIPT, "committed native solver request producer"),
        "launch_commit": git_head(),
        "solver_launch_forbidden": True,
        "root_only_launch": True,
        "event_window_s": EVENT_WINDOW_S,
        "save_interval_s": SAVE_INTERVAL_S,
        "expected_native_frames": EXPECTED_FRAMES,
        "same_repaired_domain_as_dp025": {"posmin_m": list(DOMAIN_MIN), "posmax_m": list(DOMAIN_MAX)},
        "physical_mass_contract_kg": CONTINUUM_MASS_KG,
        "cases": cases,
        "q_n_status": "pending root native review and solver execution",
        "qualification_claim": "none",
        "production_claim": "none",
    }
    manifest_path = REPAIR_ROOT / "solver-request-manifest-011.json"
    if not manifest_path.exists():
        write_json(manifest_path, manifest)
    return {"manifest": str(manifest_path), "manifest_sha256": sha256(manifest_path), "cases": cases, "launch_commit": git_head()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare"])
    args = parser.parse_args()
    result = prepare()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
