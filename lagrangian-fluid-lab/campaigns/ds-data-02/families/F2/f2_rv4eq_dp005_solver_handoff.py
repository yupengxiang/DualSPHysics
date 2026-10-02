#!/usr/bin/env python3
"""Prepare root-owned RV4-equivalent F2 DP005 solver requests.

The two requests produced here are additive qualification inputs for the new
``F2_RV4EQ_DP005`` scope.  They use the already completed DP005 GenCase
outputs, copied into a fresh data-root ``native_inputs`` directory so the
solver prefix is a real colocated XML/BI4/motion triplet.  This module never
launches GenCase, DualSPHysics, a conversion, or a GPU job.

The build also records an independent initial native boundary and prescribed
moving-cup swept-cloud audit.  The audit expands both the actual PartVTK
initial cloud and the continuous swept moving-node bounding box by the
generated kernel support radius before comparing them with the runtime
simulationdomain.  It is a domain preflight, not a physical-spill claim.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
from typing import Any, Iterable, Mapping
import xml.etree.ElementTree as ET


FAMILY_ROOT = Path(__file__).resolve().parent
WORKTREE_ROOT = FAMILY_ROOT.parents[4]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
INTEGRATION_LAB = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
RUNTIME_V2 = INTEGRATION_LAB / "scripts/ds_data02_runtime_v2.py"
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")
MANIFEST = FAMILY_ROOT / "rv4_equivalent_dp005/manifest.json"
INITIAL_AUDIT_MANIFEST = DATA_ROOT / "families/F2/F2_RV4EQ_DP005_INITIAL_AUDIT/audit-f2-rv4eq-dp005-initial-20261002-001/reports/rv4-equivalent-dp005-initial-audit-manifest.json"
CORRECTION_MANIFEST = DATA_ROOT / "families/F2/F2_RV4EQ_DP005_INITIAL_CORRECTION/audit-f2-rv4eq-dp005-initial-correction-20261002-001/correction/rv4-equivalent-dp005-initial-correction-manifest.json"
NATIVE_INPUT_ROOT = DATA_ROOT / "families/F2/F2_RV4EQ_DP005_NATIVE_INPUTS_20261002"
HANDOFF_ROOT = FAMILY_ROOT / "rv4_equivalent_dp005/solver_handoff"
EXTERNAL_HANDOFF_ROOT = DATA_ROOT / "families/F2/F2_RV4EQ_DP005_SOLVER_HANDOFF_20261002"
SCOPE_ID = "F2_SCOPE_RV4_EQUIVALENT_DP005_PRECHECK_20261002"
SCHEMA = "ds-data-02.f2.rv4-equivalent-dp005.solver-handoff.v1"
FRAMES = 401
MACRO_SAVE_S = 0.01
PLANNING_MULTIPLIER = 1.40
DP = 0.005
HDP = 1.3
KERNEL_SUPPORT_RADIUS = 2.0 * HDP * DP
SOLVER_THREADS = 4
SOLVER_WALL_SECONDS = 1800
GPU_MIB = 16384


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def require(path: Path, label: str) -> Path:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    return path


def require_dir(path: Path, label: str) -> Path:
    path = Path(path).resolve()
    if not path.is_dir():
        raise FileNotFoundError(f"{label} missing: {path}")
    return path


def input_binding(paths: Iterable[Path]) -> dict[str, str]:
    unique: dict[str, str] = {}
    for path in paths:
        path = require(Path(path), "request input")
        unique[str(path)] = sha256(path)
    return dict(sorted(unique.items()))


def copy_immutable(source: Path, destination: Path, label: str) -> Path:
    source = require(source, label)
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if sha256(destination) != sha256(source):
            raise RuntimeError(f"refusing to replace non-identical staged {label}: {destination}")
    else:
        shutil.copyfile(source, destination)
    if sha256(destination) != sha256(source):
        raise RuntimeError(f"staged {label} hash mismatch: {destination}")
    return destination


def load_json(path: Path, label: str) -> dict[str, Any]:
    return json.loads(require(path, label).read_text(encoding="utf-8"))


def xml_parameters(path: Path) -> dict[str, str]:
    root = ET.parse(path).getroot()
    return {
        str(node.attrib.get("key")): str(node.attrib.get("value"))
        for node in root.findall(".//execution/parameters/parameter")
        if node.attrib.get("key")
    }


def _attrs(node: ET.Element | None, keys: Iterable[str]) -> dict[str, str] | None:
    if node is None:
        return None
    return {key: node.attrib.get(key, "") for key in keys}


def bound_boxes(xml_path: Path) -> list[dict[str, Any]]:
    root = ET.parse(xml_path).getroot()
    mainlist = root.find(".//casedef/geometry/commands/mainlist")
    if mainlist is None:
        raise ValueError(f"geometry mainlist missing: {xml_path}")
    active_mk: int | None = None
    boxes: list[dict[str, Any]] = []
    for node in mainlist:
        if node.tag == "setmkbound":
            active_mk = int(node.attrib["mk"])
        elif node.tag == "setmkfluid":
            active_mk = None
        elif node.tag == "drawbox" and active_mk is not None:
            point = node.find("point")
            size = node.find("size")
            if point is None or size is None:
                raise ValueError(f"bound box missing point/size: {xml_path}")
            boxes.append({
                "mk": active_mk,
                "boxfill": node.findtext("boxfill", default="").strip(),
                "low_m": [float(point.attrib[axis]) for axis in "xyz"],
                "size_m": [float(size.attrib[axis]) for axis in "xyz"],
            })
    if len(boxes) != 3:
        raise ValueError(f"expected three finite bound boxes, got {len(boxes)}: {xml_path}")
    return boxes


def projection(xml_path: Path, motion_path: Path) -> dict[str, Any]:
    root = ET.parse(xml_path).getroot()
    constants = root.find(".//casedef/constantsdef")
    motion = root.find("./casedef/motion/objreal")
    domain = root.find(".//execution/parameters/simulationdomain")
    definition = root.find(".//casedef/geometry/definition")
    if constants is None or motion is None or domain is None or definition is None:
        raise ValueError(f"incomplete physical/control XML: {xml_path}")
    begin = motion.find("begin")
    mvrot = motion.find("mvrotfile")
    axis1 = mvrot.find("axisp1") if mvrot is not None else None
    axis2 = mvrot.find("axisp2") if mvrot is not None else None
    parameters = sorted(
        (node.attrib.get("key", ""), node.attrib.get("value", ""))
        for node in root.findall(".//execution/parameters/parameter")
    )
    posmin = domain.find("posmin")
    posmax = domain.find("posmax")
    motion_file = motion.find("file")
    return {
        "bound_boxes": bound_boxes(xml_path),
        "constantsdef": [(node.tag, tuple(sorted(node.attrib.items()))) for node in constants],
        "motion": {
            "begin": _attrs(begin, ("mov", "start", "finish")),
            "mvrotfile": _attrs(mvrot, ("id", "duration", "anglesunits")),
            "axis1": _attrs(axis1, ("x", "y", "z")),
            "axis2": _attrs(axis2, ("x", "y", "z")),
            "motion_file_name": motion_file.attrib.get("name", "") if motion_file is not None else "",
            "file_sha256": sha256(motion_path),
        },
        "execution_parameters": parameters,
        "simulationdomain": {
            "posmin": _attrs(posmin, ("x", "y", "z")),
            "posmax": _attrs(posmax, ("x", "y", "z")),
        },
        "definition": {
            "dp": definition.attrib.get("dp", ""),
            "pointmin": _attrs(definition.find("pointmin"), ("x", "y", "z")),
            "pointmax": _attrs(definition.find("pointmax"), ("x", "y", "z")),
        },
    }


def compare_projection(rv4_xml: Path, rv4_motion: Path, candidate_xml: Path, candidate_motion: Path) -> dict[str, Any]:
    """Compare projections without mixing motion path metadata into the hash."""
    rv4 = projection(rv4_xml, rv4_motion)
    candidate = projection(candidate_xml, candidate_motion)
    compared = ("bound_boxes", "constantsdef", "execution_parameters", "simulationdomain")
    differences = {
        key: {"rv4": rv4[key], "candidate": candidate[key]}
        for key in compared
        if rv4[key] != candidate[key]
    }
    if "execution_parameters" in differences:
        rv4_parameters = dict(rv4["execution_parameters"])
        candidate_parameters = dict(candidate["execution_parameters"])
        parameter_differences = {
            key: {"rv4": rv4_parameters.get(key), "candidate": candidate_parameters.get(key)}
            for key in set(rv4_parameters) | set(candidate_parameters)
            if rv4_parameters.get(key) != candidate_parameters.get(key)
        }
        if set(parameter_differences) == {"TimeOut"}:
            differences.pop("execution_parameters")
    rv4_motion_projection = dict(rv4["motion"])
    candidate_motion_projection = dict(candidate["motion"])
    rv4_motion_projection.pop("motion_file_name", None)
    candidate_motion_projection.pop("motion_file_name", None)
    if rv4_motion_projection != candidate_motion_projection:
        differences["motion"] = {"rv4": rv4_motion_projection, "candidate": candidate_motion_projection}
    physical_value = {key: rv4[key] for key in compared}
    physical_value["motion"] = rv4_motion_projection
    return {
        "compared_keys": [*compared, "motion"],
        "differences": differences,
        "allowed_numerical_changes": {
            "definition_dp": {"rv4": rv4["definition"]["dp"], "candidate": candidate["definition"]["dp"]},
            "definition_pointmin": {"rv4": rv4["definition"]["pointmin"], "candidate": candidate["definition"]["pointmin"]},
            "definition_pointmax": {"rv4": rv4["definition"]["pointmax"], "candidate": candidate["definition"]["pointmax"]},
            "solver_save_interval": {"rv4": dict(rv4["execution_parameters"]).get("TimeOut"), "candidate": dict(candidate["execution_parameters"]).get("TimeOut")},
            "explicit_fluid_source_blocks": True,
        },
        "physical_solids_controls_window_equal": not differences,
        "rv4_projection_sha256": canonical_hash(physical_value),
        "rv4_xml_sha256": sha256(rv4_xml),
        "candidate_xml_sha256": sha256(candidate_xml),
        "rv4_motion_sha256": sha256(rv4_motion),
        "candidate_motion_sha256": sha256(candidate_motion),
    }


def parse_motion_angles(motion_path: Path) -> dict[str, Any]:
    rows: list[tuple[float, float]] = []
    for line in motion_path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "//")) or stripped.lower().startswith("time;"):
            continue
        fields = stripped.replace(";", " ").split()
        if len(fields) < 2:
            continue
        try:
            rows.append((float(fields[0]), float(fields[1])))
        except ValueError:
            continue
    if not rows:
        raise ValueError(f"motion file has no numeric samples: {motion_path}")
    return {
        "row_count": len(rows),
        "time_start_s": min(row[0] for row in rows),
        "time_end_s": max(row[0] for row in rows),
        "angle_min_deg": min(row[1] for row in rows),
        "angle_max_deg": max(row[1] for row in rows),
        "samples_sha256": sha256(motion_path),
    }


def domain_from_xml(xml_path: Path) -> tuple[list[float], list[float], dict[str, str]]:
    root = ET.parse(xml_path).getroot()
    domain = root.find(".//execution/parameters/simulationdomain")
    definition = root.find(".//casedef/geometry/definition")
    hdp = root.find(".//casedef/constantsdef/hdp")
    if domain is None or definition is None or hdp is None:
        raise ValueError(f"domain/constants missing: {xml_path}")
    low_node = domain.find("posmin")
    high_node = domain.find("posmax")
    if low_node is None or high_node is None:
        raise ValueError(f"domain bounds missing: {xml_path}")
    low = [float(low_node.attrib[axis]) for axis in "xyz"]
    high = [float(high_node.attrib[axis]) for axis in "xyz"]
    return low, high, {"dp_m": definition.attrib.get("dp", ""), "hdp": hdp.attrib.get("value", "")}


def empty_bounds() -> dict[str, list[float]]:
    return {"min_m": [math.inf, math.inf, math.inf], "max_m": [-math.inf, -math.inf, -math.inf]}


def add_bounds(target: dict[str, list[float]], point_low: Iterable[float], point_high: Iterable[float]) -> None:
    for index, value in enumerate(point_low):
        target["min_m"][index] = min(target["min_m"][index], float(value))
    for index, value in enumerate(point_high):
        target["max_m"][index] = max(target["max_m"][index], float(value))


def parse_raw_initial_csv(csv_path: Path) -> dict[str, Any]:
    """Extract actual native Type 0/1/3 cloud bounds without rewriting CSV."""
    csv_path = require(csv_path, "raw initial PartVTK CSV")
    with csv_path.open(newline="", encoding="utf-8", errors="replace") as stream:
        next(stream)
        next(stream)
        next(stream)
        reader = csv.DictReader(stream, skipinitialspace=True)
        required = {"Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "Type", "Mk"}
        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError(f"raw CSV fields missing {required - set(reader.fieldnames or [])}: {csv_path}")
        by_type: dict[str, dict[str, Any]] = {}
        by_type_mk: dict[str, int] = {}
        row_count = 0
        union = empty_bounds()
        for row in reader:
            if not row or not row.get("Type"):
                continue
            kind = str(int(float(row["Type"])))
            point = [float(row[f"Pos.{axis} [m]"]) for axis in "xyz"]
            current = by_type.setdefault(kind, {"count": 0, "bounds": empty_bounds()})
            current["count"] += 1
            add_bounds(current["bounds"], point, point)
            add_bounds(union, point, point)
            row_count += 1
            if kind == "1":
                mk = int(float(row["Mk"]))
                by_type_mk[str(mk)] = by_type_mk.get(str(mk), 0) + 1
        return {
            "csv": {"path": str(csv_path), "sha256": sha256(csv_path), "bytes": csv_path.stat().st_size},
            "row_count": row_count,
            "by_type": by_type,
            "moving_type1_mk_counts": by_type_mk,
            "union_bounds": union,
        }


def rotate_y(point: tuple[float, float, float], angle_rad: float, axis_z: float) -> tuple[float, float, float]:
    x, y, z = point
    c = math.cos(angle_rad)
    s = math.sin(angle_rad)
    dz = z - axis_z
    return (c * x + s * dz, y, -s * x + c * dz + axis_z)


def swept_moving_bounds(initial_bounds: Mapping[str, Any], angles_deg: Iterable[float], axis_z: float) -> dict[str, Any]:
    low = initial_bounds["min_m"]
    high = initial_bounds["max_m"]
    angle_values = [float(value) for value in angles_deg]
    if not angle_values:
        raise ValueError("moving sweep has no angles")
    lo = math.radians(min(angle_values))
    hi = math.radians(max(angle_values))
    corners = [(x, y, z) for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])]
    # Evaluate prescribed samples and the exact stationary-angle candidates
    # for each corner.  The resulting box contains every point in the raw
    # moving-node initial bounding box over the full prescribed angle range.
    candidates = [lo, hi, *[math.radians(value) for value in angle_values]]
    for x, _y, z in corners:
        dx = x
        dz = z - axis_z
        candidates.extend([math.atan2(dz, dx), math.atan2(dz, dx) + math.pi])
        candidates.extend([math.atan2(-dx, dz), math.atan2(-dx, dz) + math.pi])
    candidates = [value for value in candidates if lo <= value <= hi]
    result = empty_bounds()
    for angle in candidates:
        for corner in corners:
            point = rotate_y(corner, angle, axis_z)
            add_bounds(result, point, point)
    return {
        "bounds": result,
        "angle_min_deg": math.degrees(lo),
        "angle_max_deg": math.degrees(hi),
        "candidate_angle_count": len(candidates),
        "method": "actual Type=1 initial raw bounding-box corners over all motion samples plus exact stationary-angle candidates",
        "axis_origin_m": [0.0, 0.0, axis_z],
        "axis_unit": [0.0, 1.0, 0.0],
    }


def domain_audit(*, case_id: str, generated_xml: Path, generated_motion: Path, raw_csv: Path, audit_report: Path, output_path: Path) -> dict[str, Any]:
    domain_low, domain_high, numerical = domain_from_xml(generated_xml)
    raw = parse_raw_initial_csv(raw_csv)
    motion = parse_motion_angles(generated_motion)
    moving = raw["by_type"].get("1")
    if moving is None:
        raise ValueError(f"no native Type=1 moving nodes in {raw_csv}")
    swept = swept_moving_bounds(moving["bounds"], [motion["angle_min_deg"], motion["angle_max_deg"]], 0.65)
    # Re-read all explicit samples for the provenance count; the extrema
    # calculation above includes interval stationary points, so endpoints
    # alone are enough for the exact interval range.
    angles: list[float] = []
    for line in generated_motion.read_text(encoding="utf-8", errors="replace").splitlines():
        fields = line.strip().replace(";", " ").split()
        if len(fields) >= 2:
            try:
                angles.append(float(fields[1]))
            except ValueError:
                pass
    union = empty_bounds()
    add_bounds(union, raw["union_bounds"]["min_m"], raw["union_bounds"]["max_m"])
    add_bounds(union, swept["bounds"]["min_m"], swept["bounds"]["max_m"])
    padded = {
        "min_m": [value - KERNEL_SUPPORT_RADIUS for value in union["min_m"]],
        "max_m": [value + KERNEL_SUPPORT_RADIUS for value in union["max_m"]],
    }
    low_margin = [padded["min_m"][index] - domain_low[index] for index in range(3)]
    high_margin = [domain_high[index] - padded["max_m"][index] for index in range(3)]
    pass_bounds = all(value >= 0.0 for value in [*low_margin, *high_margin])
    result = {
        "schema": f"{SCHEMA}.native-domain-audit.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "case_id": case_id,
        "scope_id": SCOPE_ID,
        "generated_xml": {"path": str(generated_xml), "sha256": sha256(generated_xml)},
        "generated_motion": {"path": str(generated_motion), "sha256": sha256(generated_motion)},
        "initial_audit_report": {"path": str(audit_report), "sha256": sha256(audit_report)},
        "raw_native_initial": raw,
        "motion_curve": {**motion, "actual_sample_count": len(angles), "angle_samples_min_deg": min(angles), "angle_samples_max_deg": max(angles)},
        "simulationdomain": {"low_m": domain_low, "high_m": domain_high},
        "kernel_padding": {"dp_m": float(numerical["dp_m"]), "hdp": float(numerical["hdp"]), "h_m": float(numerical["hdp"]) * float(numerical["dp_m"]), "support_radius_m": KERNEL_SUPPORT_RADIUS, "basis": "cubic-spline support radius 2h with generated hdp*dp"},
        "moving_type1_swept_bounds": swept,
        "union_bounds_before_kernel_padding": union,
        "union_bounds_after_kernel_padding": padded,
        "domain_margins_after_kernel_padding_m": {"low": low_margin, "high": high_margin},
        "checks": {
            "actual_native_rows_present": raw["row_count"] > 0,
            "actual_type0_fixed_boundary_present": int(raw["by_type"].get("0", {}).get("count", 0)) > 0,
            "actual_type1_moving_boundary_present": int(raw["by_type"].get("1", {}).get("count", 0)) > 0,
            "motion_covers_0_to_4_s": abs(float(motion["time_start_s"])) <= 1e-12 and abs(float(motion["time_end_s"]) - 4.0) <= 1e-12,
            "padded_raw_and_moving_sweep_inside_domain": pass_bounds,
        },
        "interpretation": "initial native fixed/moving cloud and prescribed moving-cup solid sweep are inside the padded numerical domain; this does not classify fluid spill or native exclusions",
        "qualification_claim": "none",
        "production_claim": "none",
    }
    result["all_domain_checks_pass"] = all(result["checks"].values())
    write_json(output_path, result)
    return result


def stage_case(record: Mapping[str, Any], audit_case: Mapping[str, Any]) -> dict[str, Any]:
    case_id = str(record["case_id"])
    generated = audit_case["gencase"]
    source_xml = require(Path(str(generated["xml"]["path"])), f"{case_id} generated XML")
    source_bi4 = require(Path(str(generated["bi4"]["path"])), f"{case_id} generated BI4")
    source_motion = require(Path(str(generated["motion"]["path"])), f"{case_id} generated motion")
    metadata = load_json(Path(str(record["metadata"]["path"])), f"{case_id} metadata")
    stage_dir = NATIVE_INPUT_ROOT / case_id
    stage_dir.mkdir(parents=True, exist_ok=True)
    staged_xml = copy_immutable(source_xml, stage_dir / f"{case_id}.xml", f"{case_id} XML")
    staged_bi4 = copy_immutable(source_bi4, stage_dir / f"{case_id}.bi4", f"{case_id} BI4")
    staged_motion = copy_immutable(source_motion, stage_dir / f"{case_id}_motion.dat", f"{case_id} motion")
    prefix = staged_xml.with_suffix("")
    if not all(Path(str(prefix) + suffix).is_file() for suffix in (".xml", ".bi4", "_motion.dat")):
        raise RuntimeError(f"staged solver prefix is incomplete: {prefix}")
    provenance = {
        "schema": f"{SCHEMA}.native-input-provenance.v1",
        "case_id": case_id,
        "source_gencase_output": {
            "xml": {"path": str(source_xml), "sha256": sha256(source_xml)},
            "bi4": {"path": str(source_bi4), "sha256": sha256(source_bi4)},
            "motion": {"path": str(source_motion), "sha256": sha256(source_motion)},
            "receipt": audit_case["gencase"]["receipt"],
        },
        "staged_native_input": {
            "xml": {"path": str(staged_xml), "sha256": sha256(staged_xml)},
            "bi4": {"path": str(staged_bi4), "sha256": sha256(staged_bi4)},
            "motion": {"path": str(staged_motion), "sha256": sha256(staged_motion)},
            "prefix": str(prefix),
        },
        "copy_is_byte_identical": all(sha256(a) == sha256(b) for a, b in ((source_xml, staged_xml), (source_bi4, staged_bi4), (source_motion, staged_motion))),
        "physical_condition_hash": metadata["rv4_binding"]["physical_condition_hash"],
        "qualification_claim": "none",
        "production_claim": "none",
    }
    provenance_path = stage_dir / "native-input-provenance.json"
    if provenance_path.exists():
        existing = load_json(provenance_path, "existing native provenance")
        if canonical(existing) != canonical(provenance):
            raise RuntimeError(f"existing native provenance differs: {provenance_path}")
    else:
        write_json(provenance_path, provenance)
    return {"directory": stage_dir, "prefix": prefix, "xml": staged_xml, "bi4": staged_bi4, "motion": staged_motion, "provenance": provenance_path, "source_xml": source_xml, "source_bi4": source_bi4, "source_motion": source_motion}


def stage_macro_case(source: Mapping[str, Path], case_id: str) -> dict[str, Path]:
    """Create a solver-only .01 s XML copy beside the same native BI4 bytes."""
    directory = NATIVE_INPUT_ROOT / f"{case_id}_BASELINE_SAVE001"
    directory.mkdir(parents=True, exist_ok=True)
    prefix = directory / f"{case_id}_BASELINE_SAVE001"
    macro_xml = prefix.with_suffix(".xml")
    macro_bi4 = prefix.with_suffix(".bi4")
    macro_motion = directory / f"{prefix.name}_motion.dat"
    source_text = Path(source["xml"]).read_text(encoding="utf-8")
    rewritten, count = __import__("re").subn(
        r'(<parameter\s+key="TimeOut"\s+value=")[^"]+("\s*/>)',
        rf"\g<1>{MACRO_SAVE_S:.17g}\g<2>",
        source_text,
        count=1,
    )
    if count != 1:
        raise ValueError(f"candidate XML lacks one TimeOut parameter: {source['xml']}")
    old_motion_name = Path(source["motion"]).name
    new_motion_name = macro_motion.name
    if old_motion_name not in rewritten:
        raise ValueError(f"candidate XML lacks its copied motion filename: {source['xml']}")
    rewritten = rewritten.replace(old_motion_name, new_motion_name)
    if macro_xml.exists():
        if macro_xml.read_text(encoding="utf-8") != rewritten:
            raise RuntimeError(f"refusing to replace non-identical macro XML: {macro_xml}")
    else:
        macro_xml.write_text(rewritten, encoding="utf-8")
    copy_immutable(Path(source["bi4"]), macro_bi4, "macro BI4")
    copy_immutable(Path(source["motion"]), macro_motion, "macro motion")
    provenance = {
        "schema": f"{SCHEMA}.macro-native-input-provenance.v1",
        "case_id": case_id,
        "source_gencase_xml": {"path": str(Path(source["xml"]).resolve()), "sha256": sha256(Path(source["xml"]))},
        "solver_xml": {"path": str(macro_xml.resolve()), "sha256": sha256(macro_xml), "time_out_s": MACRO_SAVE_S},
        "source_bi4": {"path": str(Path(source["bi4"]).resolve()), "sha256": sha256(Path(source["bi4"]))},
        "solver_bi4": {"path": str(macro_bi4.resolve()), "sha256": sha256(macro_bi4)},
        "source_motion": {"path": str(Path(source["motion"]).resolve()), "sha256": sha256(Path(source["motion"]))},
        "solver_motion": {"path": str(macro_motion.resolve()), "sha256": sha256(macro_motion)},
        "bi4_bytes_unchanged": sha256(Path(source["bi4"])) == sha256(macro_bi4),
        "motion_bytes_unchanged": sha256(Path(source["motion"])) == sha256(macro_motion),
        "only_solver_numeric_change": "TimeOut .001 -> .01; physical geometry/control/motion/window unchanged",
        "qualification_claim": "none",
        "production_claim": "none",
    }
    provenance_path = directory / "solver-input-provenance.json"
    if provenance_path.exists():
        if canonical(load_json(provenance_path, "existing macro provenance")) != canonical(provenance):
            raise RuntimeError(f"existing macro provenance differs: {provenance_path}")
    else:
        write_json(provenance_path, provenance)
    return {"directory": directory, "prefix": prefix, "xml": macro_xml, "bi4": macro_bi4, "motion": macro_motion, "provenance": provenance_path, "candidate_xml": Path(source["xml"]), "candidate_bi4": Path(source["bi4"]), "candidate_motion": Path(source["motion"]), "candidate_provenance": Path(source["provenance"])}


def quality_thresholds(background: str) -> dict[str, Any]:
    contract = load_json(FAMILY_ROOT / "quality_contract.json", "quality contract")
    qn = contract["background_contracts"][background.lower() + ("_catch" if background == "CENTER" else "_spill")]["q_n"]
    return {
        "continuous_initial_mass_kg": 24.576,
        "native_mass_relative_budget_fraction": 1e-12,
        "event_time_absolute_budget_s": qn["event_time_absolute_budget_s"],
        "save_half_width_budget_s": qn["event_time_absolute_budget_s"] * qn["save_fraction_of_total_error_budget_max"],
        "macro_relative_error_threshold": qn["macro_relative_error_threshold"],
        "unknown_mass_remains_in_initial_denominator": True,
        "timing_qualification": False,
        "timing_qualification_reason": "TimeOut=.01 macro view; frozen event budget requires an independently reviewed finer-save view",
    }


def common_inputs(*, record: Mapping[str, Any], audit_case: Mapping[str, Any], audit_report_path: Path, staged: Mapping[str, Path], domain_report: Path) -> list[Path]:
    metadata_path = require(Path(str(record["metadata"]["path"])), "DP005 metadata")
    definition_path = require(Path(str(record["definition"]["path"])), "DP005 definition")
    motion_path = require(Path(str(record["motion"]["path"])), "DP005 source motion")
    audit_report = require(audit_report_path, "initial audit report")
    generated_receipt = require(Path(str(audit_case["gencase"]["receipt"]["path"])), "GenCase receipt")
    return [
        Path(__file__), RUNTIME_V2, SOLVER,
        FAMILY_ROOT / "quality_contract.json", FAMILY_ROOT / "event_definitions.json", FAMILY_ROOT / "integration_save_plan.json",
        FAMILY_ROOT / "case_registry.jsonl", FAMILY_ROOT / "definitions/reference_matrix.json", FAMILY_ROOT.parents[1] / "GOAL_ZH.md",
        MANIFEST, INITIAL_AUDIT_MANIFEST, CORRECTION_MANIFEST,
        metadata_path, definition_path, motion_path, audit_report, generated_receipt,
        staged["xml"], staged["bi4"], staged["motion"], staged["provenance"],
        staged["candidate_xml"], staged["candidate_bi4"], staged["candidate_motion"], staged["candidate_provenance"], domain_report,
        # The exact RV4 generated XML/motion are the canonical physical source
        # used in the projection comparison and are kept as immutable inputs.
        staged["rv4_xml"], staged["rv4_motion"],
    ]


def make_request(*, record: Mapping[str, Any], audit_case: Mapping[str, Any], audit_report_path: Path, staged: Mapping[str, Path], domain_report: Path, request_path: Path) -> dict[str, Any]:
    case_id = str(record["case_id"])
    background = str(record["background"])
    generated_receipt_path = require(Path(str(audit_case["gencase"]["receipt"]["path"])), "GenCase receipt")
    receipt = load_json(generated_receipt_path, "GenCase receipt")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError(f"GenCase is not completed: {generated_receipt_path}")
    if int(receipt.get("solver_dimension_from_gencase", 0)) != 3 or int(receipt.get("fluid_particles", 0)) != 196608:
        raise ValueError(f"actual GenCase 3-D/fluid population mismatch: {case_id}")
    total_particles = int(receipt["total_particles"])
    raw_lower_bound = FRAMES * total_particles * 64
    storage_estimate = math.ceil(raw_lower_bound * PLANNING_MULTIPLIER)
    params = xml_parameters(staged["xml"])
    if params.get("TimeMax") != "4" or params.get("TimeOut") != "0.01":
        raise ValueError(f"RV4EQ macro request requires TimeMax=4/TimeOut=.01, got {params}")
    rv4_xml = staged["rv4_xml"]
    rv4_motion = staged["rv4_motion"]
    projection_report = compare_projection(rv4_xml, rv4_motion, staged["xml"], staged["motion"])
    if not projection_report["physical_solids_controls_window_equal"]:
        raise ValueError(f"RV4 physical projection differs for {case_id}: {projection_report['differences']}")
    metadata = load_json(Path(str(record["metadata"]["path"])), "DP005 metadata")
    physical_hash = str(metadata["rv4_binding"]["physical_condition_hash"])
    new_case_id = f"{case_id}_BASELINE_SAVE001"
    attempt_id = f"qualification-{case_id.lower()}-baseline-save001-native-fullstate-v1"
    inputs = common_inputs(record=record, audit_case=audit_case, audit_report_path=audit_report_path, staged=staged, domain_report=domain_report)
    request = {
        "schema": "ds-data-02.runner.request.v1",
        "kind": "qualification",
        "family_id": "F2",
        "case_id": new_case_id,
        "attempt_id": attempt_id,
        "command": [str(SOLVER.resolve()), str(staged["prefix"]), "{attempt_root}/solver_output"],
        "cwd": str(staged["directory"]),
        "worktree_root": str(WORKTREE_ROOT.resolve()),
        "raw_output_root": str((DATA_ROOT / "families/F2" / new_case_id).resolve()),
        "cpu_threads": SOLVER_THREADS,
        "max_wall_seconds": SOLVER_WALL_SECONDS,
        "estimated_peak_gpu_mib": GPU_MIB,
        "estimated_storage_bytes": storage_estimate,
        "storage_estimate_basis": {
            "frames": FRAMES,
            "actual_total_particles": total_particles,
            "bytes_per_particle_frame_lower_bound": 64,
            "lower_bound_bytes": raw_lower_bound,
            "planning_margin_fraction": PLANNING_MULTIPLIER - 1.0,
            "planning_multiplier": PLANNING_MULTIPLIER,
            "planning_margin_bytes": storage_estimate - raw_lower_bound,
            "formula": "ceil(actual_total_particles * 401 * 64 * 1.40)",
            "root_cost_review_required": True,
        },
        "event_window_s": 4.0,
        "physical_case_id": str(metadata["physical_case_id"]),
        "physical_condition_hash": physical_hash,
        "physical_geometry_control_hash": physical_hash,
        "numerical_recipe_hash": str(metadata["numerical_recipe_hash"]),
        "recipe_id": "F2_RV4_EQUIVALENT_DP005_BASELINE_SAVE001",
        "scope_id": SCOPE_ID,
        "mechanism_id": str(metadata["mechanism_id"]),
        "resolution": "dp005",
        "registry_role": "new_RV4_equivalent_finer_reference_outside_original_48_registry",
        "new_independent_physical_case_count": 0,
        "gencase_receipt": str(generated_receipt_path),
        "gencase_receipt_sha256": sha256(generated_receipt_path),
        "gencase_input_prefix": str(staged["prefix"]),
        "gencase_artifacts": {
            "generated_xml": {"path": str(staged["candidate_xml"]), "sha256": sha256(staged["candidate_xml"])},
            "solver_xml": {"path": str(staged["xml"]), "sha256": sha256(staged["xml"])},
            "copied_bi4": {"path": str(staged["bi4"]), "sha256": sha256(staged["bi4"])},
            "copied_motion": {"path": str(staged["motion"]), "sha256": sha256(staged["motion"])},
            "native_input_provenance": {"path": str(staged["provenance"]), "sha256": sha256(staged["provenance"])},
            "solver_input_provenance": {"path": str(staged["provenance"]), "sha256": sha256(staged["provenance"])},
            "consumed_gencase_receipt": {"path": str(generated_receipt_path), "sha256": sha256(generated_receipt_path)},
        },
        "source_binding": {
            "rv4_source_xml": {"path": str(rv4_xml), "sha256": sha256(rv4_xml)},
            "rv4_source_motion": {"path": str(rv4_motion), "sha256": sha256(rv4_motion)},
            "gencase_generated_xml": {"path": str(staged["candidate_xml"]), "sha256": sha256(staged["candidate_xml"])},
            "solver_xml": {"path": str(staged["xml"]), "sha256": sha256(staged["xml"])},
            "candidate_generated_bi4": {"path": str(staged["bi4"]), "sha256": sha256(staged["bi4"])},
            "candidate_motion": {"path": str(staged["motion"]), "sha256": sha256(staged["motion"])},
            "physical_projection": projection_report,
            "physical_condition_hash": physical_hash,
            "motion_control_full_window": parse_motion_angles(staged["motion"]),
        },
        "numerical_recipe_fields": {
            "dp_m": DP,
            "TimeMax": params.get("TimeMax"),
            "TimeOut": params.get("TimeOut"),
            "DtFixed": params.get("DtFixed"),
            "DtIni": params.get("DtIni"),
            "DtMin": params.get("DtMin"),
            "frames_expected": FRAMES,
            "simulationdomain": domain_from_xml(staged["xml"])[0:2],
        },
        "domain_audit": {"path": str(domain_report), "sha256": sha256(domain_report), "status": "pass"},
        "quality_thresholds": quality_thresholds(background),
        "thresholds_apply_before_results": True,
        "input_files": [str(path.resolve()) for path in inputs],
        "input_sha256": input_binding(inputs),
        "gpu_launch": {"family_owner_launch": False, "requested_by": "primary_process"},
        "qualification_launch_authority": "shared_ds_data_02_runner_only_primary_process",
        "status": "ready_for_root_gpu_review_only",
        "qualification_claim": "none; request is an input handoff and does not grant Q-I/Q-N",
        "production_claim": "none",
        "request_note": "Full 4 s macro save=.01 view with 401 expected frames. The solver XML is an additive numeric copy of the completed .001 GenCase XML; BI4 and motion bytes are copied unchanged. Primary process may schedule through the shared runner after review. Native unknowns and physical fate remain separate; this request cannot self-grant Q-N or production eligibility.",
    }
    write_json(request_path, request)
    return request


def build() -> dict[str, Any]:
    manifest = load_json(MANIFEST, "RV4EQ manifest")
    audit_manifest = load_json(INITIAL_AUDIT_MANIFEST, "RV4EQ initial audit manifest")
    audit_by_case = {row["case_id"]: row for row in audit_manifest["cases"]}
    if not audit_manifest.get("all_initial_checks_pass"):
        raise ValueError("initial RV4EQ audit manifest is not all-pass")
    HANDOFF_ROOT.mkdir(parents=True, exist_ok=True)
    EXTERNAL_HANDOFF_ROOT.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for record in manifest["cases"]:
        case_id = str(record["case_id"])
        audit_case = load_json(Path(str(audit_by_case[case_id]["report"])), f"{case_id} audit report")
        source_staged = stage_case(record, audit_case)
        background = str(record["background"])
        rv4_case = "F2H10V2_CENTER_V1_MEDIUM_RV4D1_BASELINE_SAVE001" if background == "CENTER" else "F2H10V2_OFFSET_V1_MEDIUM_RV4D1_BASELINE_SAVE001"
        rv4_dir = INTEGRATION_LAB / "campaigns/ds-data-02/families/F2/handoff_20261002/root_rv4_launch_001/staged_inputs" / rv4_case
        rv4_xml = require(rv4_dir / f"{rv4_case}.xml", f"{background} RV4 source XML")
        rv4_motion = require(rv4_dir / ("F2H10V2_CENTER_V1_MEDIUM_motion.dat" if background == "CENTER" else "F2H10V2_OFFSET_V1_MEDIUM_motion.dat"), f"{background} RV4 source motion")
        macro_case = stage_macro_case(source_staged, case_id)
        staged = {**macro_case, "rv4_xml": rv4_xml, "rv4_motion": rv4_motion}
        generated_xml = Path(staged["xml"])
        raw_csv = Path(audit_case["native_initial_population"]["csv"]["path"])
        domain_report = EXTERNAL_HANDOFF_ROOT / case_id / "native-domain-audit.json"
        domain_result = domain_audit(case_id=case_id, generated_xml=generated_xml, generated_motion=Path(staged["motion"]), raw_csv=raw_csv, audit_report=Path(audit_by_case[case_id]["report"]), output_path=domain_report)
        if not domain_result["all_domain_checks_pass"]:
            raise ValueError(f"native/domain audit failed for {case_id}")
        request_path = HANDOFF_ROOT / "requests" / f"{case_id}_BASELINE_SAVE001_request.json"
        request = make_request(record=record, audit_case=audit_case, audit_report_path=Path(audit_by_case[case_id]["report"]), staged=staged, domain_report=domain_report, request_path=request_path)
        records.append({
            "background": background,
            "source_case_id": case_id,
            "case_id": request["case_id"],
            "attempt_id": request["attempt_id"],
            "request": {"path": str(request_path.resolve()), "sha256": sha256(request_path)},
            "native_inputs": {"directory": str(staged["directory"]), "prefix": str(staged["prefix"]), "xml_sha256": sha256(staged["xml"]), "bi4_sha256": sha256(staged["bi4"]), "motion_sha256": sha256(staged["motion"])},
            "domain_audit": {"path": str(domain_report), "sha256": sha256(domain_report), "all_domain_checks_pass": domain_result["all_domain_checks_pass"]},
            "physical_projection": request["source_binding"]["physical_projection"],
            "actual_total_particles": request["storage_estimate_basis"]["actual_total_particles"],
            "estimated_storage_bytes": request["estimated_storage_bytes"],
        })
    handoff = {
        "schema": f"{SCHEMA}.manifest",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope_id": SCOPE_ID,
        "source_manifest": {"path": str(MANIFEST), "sha256": sha256(MANIFEST)},
        "source_initial_audit_manifest": {"path": str(INITIAL_AUDIT_MANIFEST), "sha256": sha256(INITIAL_AUDIT_MANIFEST)},
        "source_correction_manifest": {"path": str(CORRECTION_MANIFEST), "sha256": sha256(CORRECTION_MANIFEST)},
        "requests": records,
        "frames_expected": FRAMES,
        "save_interval_s": 0.01,
        "physical_case_count": 2,
        "new_independent_physical_case_count": 0,
        "qualification_claim": "none; root review and actual solver evidence remain required",
        "production_claim": "none",
        "gpu_launch": False,
        "next_gate": "root reviews source bindings, native/domain audit, storage estimates, then schedules through shared runner",
    }
    output = HANDOFF_ROOT / "solver_handoff_manifest.json"
    write_json(output, handoff)
    return {"manifest": str(output), "manifest_sha256": sha256(output), "requests": records}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build", nargs="?", default="build")
    args = parser.parse_args()
    if args.build != "build":
        parser.error("the only command is build")
    print(json.dumps(build(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
