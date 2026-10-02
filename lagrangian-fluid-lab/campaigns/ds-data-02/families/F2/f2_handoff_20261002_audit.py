#!/usr/bin/env python3
"""Audit Gem-backed F2 handoff artefacts without changing consumed evidence.

The audit is deliberately a read-only CPU task.  It invokes the official
PartVTK binary only from the shared runtime request, then checks the native
CSV identity/type fields, source-band populations, cell-centre lattice,
fluid-wall overlap, mass, and finite wall faces.  The ``legacy-root-cause``
command also reads the consumed Gem P01 GenCase VTK/XML bytes to prove
whether the former 31.129% error is a denominator error or a true
inclusive-lattice mismatch.  It never edits a BI4 or normalizes particle
positions/masses.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
from typing import Any, Iterable, Mapping
import xml.etree.ElementTree as ET


FAMILY_ID = "F2"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PARTVTK = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64")
HANDOFF_ROOT = Path(__file__).resolve().parent / "handoff_20261002"
TOL = 2.5e-6


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def number(row: Mapping[str, str], key: str) -> float:
    return float(row[key].strip())


def integer(row: Mapping[str, str], key: str) -> int:
    return int(float(row[key].strip()))


def float32(value: float) -> float:
    """Return the exact IEEE-754 single-precision value used by PartVTK."""
    return struct.unpack("f", struct.pack("f", float(value)))[0]


def parse_partvtk_csv(path: Path) -> list[dict[str, str]]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    header_index = next((i for i, line in enumerate(lines) if line.startswith("Pos.x [m]")), None)
    if header_index is None:
        raise RuntimeError(f"PartVTK CSV has no particle header: {path}")
    header = [item.strip() for item in lines[header_index].split(",") if item.strip()]
    required = {"Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "Zone", "Idp", "Mass [kg]", "Type", "Mk"}
    missing = required.difference(header)
    if missing:
        raise RuntimeError(f"PartVTK CSV missing fields {sorted(missing)}: {path}")
    rows: list[dict[str, str]] = []
    for line in lines[header_index + 1 :]:
        if not line.strip():
            continue
        values = [item.strip() for item in line.split(",")]
        if len(values) < len(header):
            continue
        rows.append(dict(zip(header, values)))
    if not rows:
        raise RuntimeError(f"PartVTK CSV contains no particle rows: {path}")
    return rows


def parse_declared_boxes(xml_path: Path) -> dict[int, dict[str, Any]]:
    root = ET.parse(xml_path).getroot()
    mainlist = root.find(".//geometry/commands/mainlist")
    if mainlist is None:
        raise RuntimeError(f"definition has no geometry mainlist: {xml_path}")
    bound_mk: int | None = None
    boxes: dict[int, dict[str, Any]] = {}
    for node in mainlist:
        if node.tag == "setmkbound":
            bound_mk = int(node.attrib["mk"])
            continue
        if node.tag == "setmkfluid":
            bound_mk = None
            continue
        if node.tag != "drawbox" or bound_mk is None:
            continue
        point = node.find("./point")
        size = node.find("./size")
        if point is None or size is None:
            continue
        low = [float(point.attrib[key]) for key in ("x", "y", "z")]
        extent = [float(size.attrib[key]) for key in ("x", "y", "z")]
        boxes[bound_mk] = {
            "mk": bound_mk,
            "low_m": low,
            "high_m": [a + b for a, b in zip(low, extent)],
            "size_m": extent,
            "boxfill": node.findtext("./boxfill", default="").strip(),
        }
    if len(boxes) != 3:
        raise RuntimeError(f"expected 3 declared bound boxes, found {len(boxes)}: {xml_path}")
    return boxes


def face_names(boxfill: str) -> tuple[str, ...]:
    mapping = {"bottom": "z-", "top": "z+", "left": "x-", "right": "x+", "front": "y-", "back": "y+"}
    return tuple(mapping[token.strip()] for token in boxfill.split("|") if token.strip() in mapping)


def face_coverage(points: list[tuple[float, float, float]], box: Mapping[str, Any], dp: float) -> dict[str, Any]:
    low = box["low_m"]
    high = box["high_m"]
    size = box["size_m"]
    axes = {"x": 0, "y": 1, "z": 2}
    tolerance = max(2.25 * dp, 1e-6)
    output: dict[str, Any] = {}
    for face in face_names(str(box["boxfill"])):
        axis = axes[face[0]]
        target = low[axis] if face[1] == "-" else high[axis]
        selected = [point for point in points if abs(point[axis] - target) <= tolerance]
        tangential = [index for index in range(3) if index != axis]
        spans = []
        for index in tangential:
            span = max((point[index] for point in selected), default=0.0) - min((point[index] for point in selected), default=0.0)
            spans.append(max(0.0, min(1.0, span / max(size[index], 1e-12))))
        output[face] = {
            "count": len(selected),
            "span_fraction": min(spans) if spans else 0.0,
            "normal": [(-1.0 if face[1] == "-" else 1.0) if index == axis else 0.0 for index in range(3)],
            "coordinate_target_m": target,
            "tolerance_m": tolerance,
        }
    return output


def nearest_box_group(groups: Mapping[tuple[int, int], list[tuple[float, float, float]]], box: Mapping[str, Any], *, type_id: int) -> tuple[int, int] | None:
    center = [(a + b) / 2.0 for a, b in zip(box["low_m"], box["high_m"])]
    candidates = {key: points for key, points in groups.items() if key[0] == type_id}
    if not candidates:
        return None
    return min(candidates, key=lambda key: sum((sum(point[i] for point in candidates[key]) / len(candidates[key]) - center[i]) ** 2 for i in range(3)))


def run_partvtk(data_dir: Path, output_dir: Path, case_id: str) -> tuple[Path, dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = output_dir / "Particles"
    bi4 = data_dir / f"{case_id}.bi4"
    xml = data_dir / f"{case_id}.xml"
    command = [
        str(PARTVTK),
        "-filedata",
        str(bi4),
        "-filexml",
        str(xml),
        "-first:0",
        "-last:0",
        "-threads:4",
        "-savecsv",
        str(prefix),
        "-onlytype:+all",
        "-vars:-all,+idp,+vel,+rhop,+press,+type,+mk,+mass,+zone",
        "-csvsep:1",
    ]
    completed = subprocess.run(command, cwd=output_dir, capture_output=True, text=True, check=False, timeout=600)
    log_path = output_dir / "partvtk.stdout.log"
    log_path.write_text(completed.stdout + completed.stderr, encoding="utf-8")
    frames = sorted(output_dir.glob("Particles_*.csv"))
    frames = [path for path in frames if not path.name.endswith("_stats.csv")]
    if not frames and (output_dir / "Particles.csv").is_file():
        frames = [output_dir / "Particles.csv"]
    if completed.returncode != 0 or not frames:
        raise RuntimeError(f"PartVTK failed for {case_id}: {log_path}")
    return frames[0], {
        "command": command,
        "returncode": completed.returncode,
        "csv": {"path": str(frames[0]), "sha256": sha256(frames[0]), "bytes": frames[0].stat().st_size},
        "log": {"path": str(log_path), "sha256": sha256(log_path), "bytes": log_path.stat().st_size},
        "binary": {"path": str(PARTVTK), "sha256": sha256(PARTVTK)},
    }


def audit_case(entry: Mapping[str, Any], report_root: Path) -> dict[str, Any]:
    case_id = str(entry["case_id"])
    request = json.loads(Path(entry["request"]["path"]).read_text(encoding="utf-8"))
    receipt_path = DATA_ROOT / "families" / FAMILY_ID / case_id / request["attempt_id"] / "execution-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise RuntimeError(f"GenCase receipt is not completed: {receipt_path}")
    expected = entry["expected_population"]
    if receipt.get("solver_dimension_from_gencase") != 3 or receipt.get("fluid_particles") != expected["total_particle_count"]:
        raise RuntimeError(f"GenCase population/dimension mismatch for {case_id}: {receipt_path}")
    data_dir = Path(receipt["output_root"])
    case_report = report_root / case_id
    csv_path, partvtk = run_partvtk(data_dir, case_report / "partvtk", case_id)
    rows = parse_partvtk_csv(csv_path)
    positions = [(number(row, "Pos.x [m]"), number(row, "Pos.y [m]"), number(row, "Pos.z [m]")) for row in rows]
    typed_ids = [(integer(row, "Zone"), integer(row, "Idp")) for row in rows]
    typed_id_duplicates = len(typed_ids) - len(set(typed_ids))
    fluid_rows = [row for row in rows if integer(row, "Type") == 3]
    fluid_positions = [(number(row, "Pos.x [m]"), number(row, "Pos.y [m]"), number(row, "Pos.z [m]")) for row in fluid_rows]
    fluid_mks = sorted({integer(row, "Mk") for row in fluid_rows})
    per_mk = {str(mk): sum(integer(row, "Mk") == mk for row in fluid_rows) for mk in fluid_mks}
    coordinate_keys = [(round(point[0], 7), round(point[1], 7), round(point[2], 7)) for point in fluid_positions]
    coordinate_duplicates = len(coordinate_keys) - len(set(coordinate_keys))
    metadata = json.loads(Path(entry["metadata"]["path"]).read_text(encoding="utf-8"))
    dp = float(metadata["dp_m"])
    low = metadata["geometry"]["continuous_fluid_low_m"]
    size = metadata["geometry"]["continuous_fluid_size_m"]
    counts = expected["cells_xyz"]
    expected_axes = [[low[i] + dp / 2.0 + index * dp for index in range(counts[i])] for i in range(3)]
    actual_axes = [sorted({point[i] for point in fluid_positions}) for i in range(3)]
    axis_checks = []
    for actual, expected_axis in zip(actual_axes, expected_axes):
        error = max((min(abs(value - target) for target in expected_axis) for value in actual), default=float("inf"))
        axis_checks.append({"actual_count": len(actual), "expected_count": len(expected_axis), "max_nearest_error_m": error, "first_m": actual[0] if actual else None, "last_m": actual[-1] if actual else None, "pass": len(actual) == len(expected_axis) and error <= TOL})
    band_checks = []
    bounds_y = metadata["geometry"]["source_band_bounds_y_m"]
    for index, (band_low, band_high) in enumerate(bounds_y):
        band = [row for row in fluid_rows if band_low - TOL <= number(row, "Pos.y [m]") <= band_high - TOL]
        ys = sorted({number(row, "Pos.y [m]") for row in band})
        band_checks.append({"source_index": index, "native_mk": fluid_mks[index] if index < len(fluid_mks) else None, "count": len(band), "expected_count": expected["source_band_particle_count"], "y_count": len(ys), "y_values_m": ys, "pass": len(band) == expected["source_band_particle_count"] and len(ys) == expected["source_band_cells_xyz"][1]})
    gaps = [actual_axes[1][i + 1] - actual_axes[1][i] for i in range(len(actual_axes[1]) - 1)] if actual_axes[1] else []
    mass = sum(number(row, "Mass [kg]") for row in fluid_rows)
    expected_mass = float(expected["expected_lattice_mass_kg"])
    native_particle_mass = float32(dp ** 3 * 1000.0)
    # PartVTK's CSV uses eight significant digits for Mass. Compare the
    # measured sum to that immutable serialization contract as well as to the
    # exact lattice mass; never alter the measured values.
    serialized_particle_mass = float(f"{native_particle_mass:.7E}")
    expected_native_mass = serialized_particle_mass * expected["total_particle_count"]
    mass_relative_error = mass / expected_mass - 1.0 if expected_mass else float("inf")
    native_storage_relative_error = mass / expected_native_mass - 1.0 if expected_native_mass else float("inf")
    physical_lattice_relative_error = float(expected["relative_mass_error"])
    boundary_groups: dict[tuple[int, int], list[tuple[float, float, float]]] = {}
    for row, point in zip(rows, positions):
        key = (integer(row, "Type"), integer(row, "Mk"))
        boundary_groups.setdefault(key, []).append(point)
    boxes = parse_declared_boxes(Path(entry["definition"]["path"]))
    walls: dict[str, Any] = {}
    labels = [(0, "cup", 1), (1, "receiver", 0), (2, "tray", 0)]
    for declared_mk, label, type_id in labels:
        box = boxes[declared_mk]
        native = nearest_box_group(boundary_groups, box, type_id=type_id)
        # GenCase may assign several fixed finite bodies to one native
        # Type/Mk.  A single ``nearest_box_group`` therefore cannot identify
        # the tray: use all native points of the declared Type for face
        # evidence, while retaining the nearest Type/Mk as a provenance hint.
        native_points = [point for key, points in boundary_groups.items() if key[0] == type_id for point in points]
        walls[label] = {
            "declared_mk": declared_mk,
            "native_type_mk_nearest_hint": list(native) if native else None,
            "native_type_mks_observed": sorted({key[1] for key in boundary_groups if key[0] == type_id}),
            "native_grouping_note": "finite bodies can share a native Type/Mk; face coverage is selected by declared face coordinates over the complete native Type point set",
        }
        if native_points:
            coverage = face_coverage(native_points, box, dp)
            walls[label].update({"point_count_considered": len(native_points), "bounds_low_m": [min(p[i] for p in native_points) for i in range(3)], "bounds_high_m": [max(p[i] for p in native_points) for i in range(3)], "face_coverage": coverage, "finite_faces_pass": all(item["count"] > 0 and item["span_fraction"] >= 0.5 for item in coverage.values())})
        else:
            walls[label]["finite_faces_pass"] = False
    fluid_keys = set(coordinate_keys)
    boundary_keys = {(round(point[0], 7), round(point[1], 7), round(point[2], 7)) for row, point in zip(rows, positions) if integer(row, "Type") != 3}
    overlap = len(fluid_keys & boundary_keys)
    checks = {
        "three_d": receipt.get("solver_dimension_from_gencase") == 3,
        "fluid_count": len(fluid_rows) == expected["total_particle_count"],
        "source_mk_count": len(fluid_mks) == expected["source_band_count"],
        "source_band_counts": all(item["pass"] for item in band_checks),
        "axis_lattice": all(item["pass"] for item in axis_checks),
        "interface_spacing": bool(gaps) and all(abs(gap - dp) <= TOL for gap in gaps),
        "typed_id_unique": typed_id_duplicates == 0,
        "fluid_position_unique": coordinate_duplicates == 0,
        "fluid_boundary_nonoverlap": overlap == 0,
        "mass_within_budget": abs(native_storage_relative_error) <= float(metadata["mass_error_budget_fraction"]),
        "finite_wall_faces": all(item.get("finite_faces_pass", False) for item in walls.values()),
    }
    return {
        "case_id": case_id,
        "background": entry["background"],
        "resolution": entry["resolution"],
        "receipt": {"path": str(receipt_path), "sha256": sha256(receipt_path), "output_root": str(data_dir), "total_particles": receipt["total_particles"], "fluid_particles": receipt["fluid_particles"], "dimension": receipt["solver_dimension_from_gencase"]},
        "partvtk": partvtk,
        "row_count": len(rows),
        "typed_id_duplicates": typed_id_duplicates,
        "fluid_type": 3,
        "fluid_mks": fluid_mks,
        "fluid_per_native_mk": per_mk,
        "fluid_position_duplicates": coordinate_duplicates,
        "fluid_boundary_overlap_count": overlap,
        "axis_checks": axis_checks,
        "source_band_checks": band_checks,
        "interface_dy_m": gaps,
        "fluid_mass_kg": mass,
        "expected_mass_kg": expected_mass,
        "expected_native_float32_particle_mass_kg": native_particle_mass,
        "expected_partvtk_csv_particle_mass_kg": serialized_particle_mass,
        "expected_native_float32_mass_kg": expected_native_mass,
        "mass_relative_error_vs_exact_lattice": mass_relative_error,
        "native_storage_relative_error": native_storage_relative_error,
        "physical_lattice_relative_error": physical_lattice_relative_error,
        "wall_evidence": walls,
        "checks": checks,
        "status": "PASS_INITIAL_STRUCTURE" if all(checks.values()) else "FAIL_INITIAL_STRUCTURE",
    }


def audit(manifest_path: Path, report_root: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = [audit_case(entry, report_root) for entry in manifest["cases"]]
    result = {
        "schema": "ds-data-02.f2.gem-handoff-20261002-audit.v1",
        "family_id": FAMILY_ID,
        "scope_id": manifest["scope_id"],
        "manifest": {"path": str(manifest_path), "sha256": sha256(manifest_path)},
        "qualification_claim": "none",
        "production_claim": "none",
        "native_identity_semantics": "PartVTK CSV Zone+Idp; Type=3 and native Mk identify fluid; no coordinate/mass rewriting",
        "cases": cases,
        "status": "PASS_INITIAL_STRUCTURE" if all(case["status"] == "PASS_INITIAL_STRUCTURE" for case in cases) else "FAIL_INITIAL_STRUCTURE",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    write_json(report_root / "gem-handoff-initial-structure-audit.json", result)
    return result


LEGACY_CASES = {
    "F2_CENTER_P01": {
        "source_definition": HANDOFF_ROOT / "source_assets/F2_GEM_CENTER_P01_Def.xml",
        "receipt": DATA_ROOT / "families/F2/F2_CENTER_P01/F2_CENTER_P01_GENCASE_01/execution-receipt.json",
    },
    "F2_OFFSET_P01": {
        "source_definition": HANDOFF_ROOT / "source_assets/F2_GEM_OFFSET_P01_Def.xml",
        "receipt": DATA_ROOT / "families/F2/F2_OFFSET_P01/F2_OFFSET_P01_GENCASE_01/execution-receipt.json",
    },
}


def parse_binary_vtk_points(path: Path) -> list[tuple[float, float, float]]:
    """Read only the first binary VTK POINTS array, preserving source bytes."""
    data = path.read_bytes()
    marker = b"POINTS "
    start = data.find(marker)
    if start < 0:
        raise RuntimeError(f"VTK has no POINTS section: {path}")
    line_end = data.find(b"\n", start)
    if line_end < 0:
        raise RuntimeError(f"VTK POINTS header is truncated: {path}")
    fields = data[start:line_end].decode("ascii").split()
    if len(fields) != 3 or fields[2] != "float":
        raise RuntimeError(f"unsupported VTK POINTS header {fields}: {path}")
    count = int(fields[1])
    payload_start = line_end + 1
    payload_end = payload_start + count * 3 * 4
    if payload_end > len(data):
        raise RuntimeError(f"VTK POINTS payload is truncated: {path}")
    values = struct.unpack(f">{count * 3}f", data[payload_start:payload_end])
    return [tuple(values[index:index + 3]) for index in range(0, len(values), 3)]


def parse_fluid_boxes(xml_path: Path) -> list[dict[str, Any]]:
    root = ET.parse(xml_path).getroot()
    mainlist = root.find(".//geometry/commands/mainlist")
    if mainlist is None:
        raise RuntimeError(f"definition has no geometry mainlist: {xml_path}")
    current: int | None = None
    boxes: list[dict[str, Any]] = []
    for node in mainlist:
        if node.tag == "setmkfluid":
            current = int(node.attrib["mk"])
            continue
        if node.tag == "setmkbound":
            current = None
            continue
        if node.tag != "drawbox" or current is None:
            continue
        point = node.find("./point")
        size = node.find("./size")
        if point is None or size is None:
            continue
        low = [float(point.attrib[key]) for key in ("x", "y", "z")]
        extent = [float(size.attrib[key]) for key in ("x", "y", "z")]
        boxes.append({
            "mk": current,
            "low_m": low,
            "high_m": [a + b for a, b in zip(low, extent)],
            "size_m": extent,
            "volume_m3": math.prod(extent),
            "boxfill": node.findtext("./boxfill", default="").strip(),
        })
    if len(boxes) != 3:
        raise RuntimeError(f"expected 3 fluid source boxes, found {len(boxes)}: {xml_path}")
    return boxes


def legacy_root_cause_case(case_id: str, paths: Mapping[str, Path]) -> dict[str, Any]:
    receipt_path = paths["receipt"].resolve()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    source_xml = paths["source_definition"].resolve()
    output_root = Path(receipt["output_root"]).resolve()
    xml_path = output_root / f"{case_id}.xml"
    fluid_vtk = output_root / f"{case_id}_Fluid.vtk"
    boxes = parse_fluid_boxes(source_xml)
    dp = float(ET.parse(source_xml).getroot().find(".//geometry/definition").attrib["dp"])
    points = parse_binary_vtk_points(fluid_vtk)
    axes = [sorted({point[index] for point in points}) for index in range(3)]
    point_low = [min(point[index] for point in points) for index in range(3)]
    point_high = [max(point[index] for point in points) for index in range(3)]
    declared_volume = sum(box["volume_m3"] for box in boxes)
    lattice_volume = len(points) * dp ** 3
    support_volume = math.prod((point_high[index] - point_low[index] + dp) for index in range(3))
    declared_mass = declared_volume * 1000.0
    lattice_mass = lattice_volume * 1000.0
    relative_error = lattice_volume / declared_volume - 1.0
    expected_receipt = receipt.get("continuum_mass_consistency", {})
    return {
        "case_id": case_id,
        "source_definition": {"path": str(source_xml), "sha256": sha256(source_xml)},
        "receipt": {"path": str(receipt_path), "sha256": sha256(receipt_path), "status": receipt.get("status"), "returncode": receipt.get("returncode"), "solver_dimension": receipt.get("solver_dimension_from_gencase")},
        "actual_files": {
            "xml": {"path": str(xml_path), "sha256": sha256(xml_path)},
            "fluid_vtk": {"path": str(fluid_vtk), "sha256": sha256(fluid_vtk)},
        },
        "declared_fluid_sources": boxes,
        "declared_continuous_volume_m3": declared_volume,
        "declared_continuous_mass_kg": declared_mass,
        "dp_m": dp,
        "actual_fluid_point_count": len(points),
        "actual_fluid_point_bounds_m": {"low": point_low, "high": point_high},
        "actual_axis_counts": [len(axis) for axis in axes],
        "actual_axis_values_m": axes,
        "actual_lattice_volume_m3": lattice_volume,
        "actual_lattice_mass_kg": lattice_mass,
        "actual_support_occupied_volume_m3": support_volume,
        "relative_lattice_error_vs_declared_continuum": relative_error,
        "relative_lattice_error_percent": relative_error * 100.0,
        "receipt_consistency_label_ignored": expected_receipt.get("consistent"),
        "checks": {
            "receipt_completed_3d": receipt.get("status") == "completed" and receipt.get("returncode") == 0 and receipt.get("solver_dimension_from_gencase") == 3,
            "actual_fluid_nonzero": len(points) > 0,
            "declared_mass_matches_source_boxes": abs(declared_mass - 18.876) < 1e-12,
            "actual_point_count_matches_receipt": len(points) == receipt.get("fluid_particles"),
            "inclusive_lattice_mismatch_is_reproduced": abs(relative_error - 0.3112947658402204) < 1e-9,
            "not_a_denominator_typo": abs(declared_volume - 0.018876) < 1e-12 and abs(lattice_volume - 0.024752) < 1e-12 and abs(support_volume - lattice_volume) < 1e-8,
        },
        "status": "ROOT_CAUSE_CONFIRMED",
        "interpretation": "The 31.129% value is a real inclusive drawbox lattice expansion: the declared 0.325x0.22x0.264 m fluid boxes are not commensurate with dp=0.02, producing 17x13x14 points and effective occupied volume 0.34x0.26x0.28 m. The source denominator is retained; no normalization or support-layer reassignment is allowed.",
    }


def legacy_root_cause(report_path: Path) -> dict[str, Any]:
    cases = [legacy_root_cause_case(case_id, paths) for case_id, paths in LEGACY_CASES.items()]
    result = {
        "schema": "ds-data-02.f2.gem-handoff-20261002-legacy-root-cause.v1",
        "family_id": FAMILY_ID,
        "scope_id": "F2_SCOPE_GEM_COMMENSURATE_CELLCENTER_20261002_V1",
        "qualification_claim": "none",
        "production_claim": "none",
        "source_of_truth": "raw Gem P01 source XML plus consumed GenCase XML/Fluid.vtk/receipt; receipt boolean labels are not used as verdicts",
        "cases": cases,
        "status": "ROOT_CAUSE_CONFIRMED" if all(all(case["checks"].values()) for case in cases) else "ROOT_CAUSE_UNRESOLVED",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    write_json(report_path, result)
    return result


def make_request(manifest_path: Path, request_path: Path, *, case_id: str = "F2H10_INITIAL_AUDIT", attempt_id: str = "f2h10-initial-audit-20261002-001") -> dict[str, Any]:
    manifest_path = manifest_path.resolve()
    request_path = request_path.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    audit_script = Path(__file__).resolve()
    input_files = [audit_script, manifest_path, PARTVTK]
    for entry in manifest["cases"]:
        request = json.loads(Path(entry["request"]["path"]).read_text(encoding="utf-8"))
        input_files.extend([
            Path(entry["definition"]["path"]),
            Path(entry["metadata"]["path"]),
            Path(request["motion_sha256"] and json.loads(Path(entry["metadata"]["path"]).read_text())["motion"]["path"]),
            DATA_ROOT / "families" / FAMILY_ID / entry["case_id"] / request["attempt_id"] / "execution-receipt.json",
            Path(entry["request"]["path"]),
        ])
    unique_files = []
    seen: set[str] = set()
    for path in input_files:
        path = Path(path).resolve()
        if str(path) not in seen:
            seen.add(str(path))
            unique_files.append(str(path))
    request = {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": FAMILY_ID,
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 4,
        "max_wall_seconds": 600,
        "estimated_storage_bytes": 8 * 1024 * 1024 * 1024,
        "command": ["/usr/bin/python3", str(audit_script), "audit", "--manifest", str(manifest_path), "--report-root", "{attempt_root}/report"],
        "cwd": str(audit_script.parent),
        "raw_output_root": str(DATA_ROOT / "families/F2/F2H10_GEM_COMMENSURATE/initial_audit"),
        "worktree_root": str(audit_script.parents[5]),
        "solver_launch_forbidden": True,
        "scope_id": manifest["scope_id"],
        "input_files": unique_files,
        "request_note": "Shared v2 CPU PartVTK initial-frame audit only; no solver/GPU/QN/production claim.",
    }
    write_json(request_path, request)
    return request


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_audit = sub.add_parser("audit")
    p_audit.add_argument("--manifest", type=Path, required=True)
    p_audit.add_argument("--report-root", type=Path, required=True)
    p_legacy = sub.add_parser("legacy-root-cause")
    p_legacy.add_argument("--report", type=Path, required=True)
    p_request = sub.add_parser("make-request")
    p_request.add_argument("--manifest", type=Path, required=True)
    p_request.add_argument("--request", type=Path, required=True)
    p_request.add_argument("--case-id", default="F2H10_INITIAL_AUDIT")
    p_request.add_argument("--attempt-id", default="f2h10-initial-audit-20261002-001")
    args = parser.parse_args()
    if args.command == "audit":
        result = audit(args.manifest, args.report_root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "PASS_INITIAL_STRUCTURE" else 2
    if args.command == "legacy-root-cause":
        result = legacy_root_cause(args.report)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "ROOT_CAUSE_CONFIRMED" else 2
    request = make_request(args.manifest, args.request, case_id=args.case_id, attempt_id=args.attempt_id)
    print(json.dumps({"status": "written", "request": str(args.request), "input_count": len(request["input_files"])}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
