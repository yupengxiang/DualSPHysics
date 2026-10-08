#!/usr/bin/env python3
"""Compute declared box-union bounds without reading native or typed data.

The existing geometry audit reports the sum of ``solid`` fluid drawboxes but
must leave overlaps, ``setmkvoid`` subtraction, and lattice phase unknown.
This forward report makes the part that is analytically identifiable explicit:
for axis-aligned boxes it computes exact primitive-union and void-subtracted
volumes by coordinate partition, reports cross-MK overlaps, and records the
position of every box relative to ``pointref`` in units of ``dp``.  GenCase
cell-centre selection, boundary ownership, and effective particle mass remain
unknown and are never inferred from these bounds.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any, Iterable


SCHEMA = "ds02.stage2.continuum-geometry-bounds.v1"
DEFAULT_QUALITY = Path(__file__).with_name("stage2_reference_quality_cost_v2.json")
DEFAULT_OUTPUT = Path(__file__).with_name("stage2_continuum_geometry_bounds_v1.json")


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def number(value: str | None, label: str) -> float:
    if value is None:
        raise ValueError(f"missing numeric {label}")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite numeric {label}")
    return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_binding(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256(path)}


def vector(node: ET.Element | None, names: tuple[str, str, str], label: str) -> tuple[float, float, float] | None:
    if node is None or any(name not in node.attrib for name in names):
        return None
    return tuple(number(node.attrib[name], f"{label}.{name}") for name in names)


def bounds(point: tuple[float, float, float], size: tuple[float, float, float]) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    if any(value <= 0.0 for value in size):
        raise ValueError(f"solid drawbox has non-positive size: {point} {size}")
    return tuple((point[index], point[index] + size[index]) for index in range(3))  # type: ignore[return-value]


def volume(box: tuple[tuple[float, float], tuple[float, float], tuple[float, float]]) -> float:
    return math.prod(high - low for low, high in box)


def intersection(a: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
                 b: tuple[tuple[float, float], tuple[float, float], tuple[float, float]]) -> float:
    lengths = [min(a[index][1], b[index][1]) - max(a[index][0], b[index][0]) for index in range(3)]
    return math.prod(length if length > 0.0 else 0.0 for length in lengths)


def contains(box: tuple[tuple[float, float], tuple[float, float], tuple[float, float]], point: tuple[float, float, float]) -> bool:
    return all(low <= value < high for (low, high), value in zip(box, point))


def union_volume(boxes: list[tuple[tuple[float, float], tuple[float, float], tuple[float, float]]]) -> float:
    """Exact union volume for finite axis-aligned boxes via cell partition."""
    if not boxes:
        return 0.0
    coordinates = [sorted({edge for box in boxes for edge in box[axis]}) for axis in range(3)]
    total = 0.0
    for x0, x1 in zip(coordinates[0], coordinates[0][1:]):
        for y0, y1 in zip(coordinates[1], coordinates[1][1:]):
            for z0, z1 in zip(coordinates[2], coordinates[2][1:]):
                if x1 <= x0 or y1 <= y0 or z1 <= z0:
                    continue
                center = ((x0 + x1) / 2.0, (y0 + y1) / 2.0, (z0 + z1) / 2.0)
                if any(contains(box, center) for box in boxes):
                    total += (x1 - x0) * (y1 - y0) * (z1 - z0)
    return total


def void_subtracted_volume(fluid_boxes: list[Any], void_boxes: list[Any]) -> float:
    """Volume of union(fluid) minus union(void), for declared box geometry."""
    if not fluid_boxes:
        return 0.0
    boxes = [*fluid_boxes, *void_boxes]
    coordinates = [sorted({edge for box in boxes for edge in box[axis]}) for axis in range(3)]
    total = 0.0
    for x0, x1 in zip(coordinates[0], coordinates[0][1:]):
        for y0, y1 in zip(coordinates[1], coordinates[1][1:]):
            for z0, z1 in zip(coordinates[2], coordinates[2][1:]):
                if x1 <= x0 or y1 <= y0 or z1 <= z0:
                    continue
                center = ((x0 + x1) / 2.0, (y0 + y1) / 2.0, (z0 + z1) / 2.0)
                if any(contains(box, center) for box in fluid_boxes) and not any(contains(box, center) for box in void_boxes):
                    total += (x1 - x0) * (y1 - y0) * (z1 - z0)
    return total


def box_record(role: str, mkfluid: str | None, point: tuple[float, float, float], size: tuple[float, float, float],
               dp: float | None, pointref: tuple[float, float, float] | None, comment: str | None) -> dict[str, Any]:
    box = bounds(point, size)
    phase: dict[str, Any] = {"status": "UNKNOWN_NO_POINTREF_OR_DP"}
    if dp is not None and pointref is not None and dp > 0.0:
        start = tuple((point[index] - pointref[index]) / dp for index in range(3))
        size_cells = tuple(size[index] / dp for index in range(3))
        fractional = tuple(value - math.floor(value) for value in start)
        phase = {
            "status": "ANALYTIC_DECLARED_LATTICE_PHASE_ONLY",
            "start_index_real": list(start),
            "start_index_floor": [math.floor(value) for value in start],
            "start_fractional_phase": list(fractional),
            "size_in_dp": list(size_cells),
            "size_nearest_integer_residual_in_dp": [value - round(value) for value in size_cells],
            "effective_cell_centre_selection": "UNKNOWN",
        }
    return {
        "role": role,
        "mkfluid_relative": mkfluid,
        "point_m": list(point),
        "size_m": list(size),
        "bounds_m": [[low, high] for low, high in box],
        "declared_volume_m3": volume(box),
        "comment": comment,
        "lattice_phase": phase,
        "_box": box,
    }


def parse_xml(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    root = ET.parse(path).getroot()
    definition = next((node for node in root.iter() if local_name(node.tag) == "definition"), None)
    dp = number(definition.get("dp"), "definition.dp") if definition is not None else None
    pointref_node = next((node for node in definition or [] if local_name(node.tag) == "pointref"), None)
    pointref = vector(pointref_node, ("x", "y", "z"), "definition.pointref")
    rhop_node = next((node for node in root.iter() if local_name(node.tag) == "rhop0"), None)
    rhop0 = number(rhop_node.get("value"), "rhop0") if rhop_node is not None else None

    active_role: str | None = None
    active_mkfluid: str | None = None
    fluids: list[dict[str, Any]] = []
    voids: list[dict[str, Any]] = []
    bounds_declared: list[dict[str, Any]] = []
    for node in root.iter():
        tag = local_name(node.tag)
        if tag == "setmkfluid":
            active_role, active_mkfluid = "fluid", node.get("mk")
            continue
        if tag == "setmkvoid":
            active_role, active_mkfluid = "void", None
            continue
        if tag == "setmkbound":
            active_role, active_mkfluid = "bound", None
            continue
        if tag != "drawbox" or active_role is None:
            continue
        fill = next((child for child in node if local_name(child.tag) == "boxfill"), None)
        if fill is None or (fill.text or "").strip().lower() != "solid":
            continue
        point_node = next((child for child in node if local_name(child.tag) == "point"), None)
        size_node = next((child for child in node if local_name(child.tag) == "size"), None)
        point = vector(point_node, ("x", "y", "z"), "drawbox.point")
        size = vector(size_node, ("x", "y", "z"), "drawbox.size")
        if point is None or size is None:
            raise ValueError(f"solid drawbox lacks point/size in {path}")
        item = box_record(active_role, active_mkfluid, point, size, dp, pointref, node.get("cmt"))
        if active_role == "fluid":
            fluids.append(item)
        elif active_role == "void":
            voids.append(item)
        else:
            bounds_declared.append(item)

    # Private tuples are consumed while constructing the report and removed
    # before JSON serialization.
    fluid_boxes = [item["_box"] for item in fluids]
    void_boxes = [item["_box"] for item in voids]
    by_mk: dict[str, list[dict[str, Any]]] = {}
    for item in fluids:
        by_mk.setdefault(str(item["mkfluid_relative"]), []).append(item)
    per_mk: list[dict[str, Any]] = []
    for mkfluid, items in by_mk.items():
        boxes = [item["_box"] for item in items]
        primitive_sum = math.fsum(item["declared_volume_m3"] for item in items)
        union = union_volume(boxes)
        void_union = void_subtracted_volume(boxes, void_boxes)
        void_intersections = [
            {"fluid_comment": item.get("comment"), "void_comment": void.get("comment"),
             "intersection_volume_m3": intersection(item["_box"], void["_box"])}
            for item in items for void in voids if intersection(item["_box"], void["_box"]) > 0.0
        ]
        entry: dict[str, Any] = {
            "mkfluid_relative": mkfluid,
            "drawbox_count": len(items),
            "drawboxes": [{key: value for key, value in item.items() if key != "_box"} for item in items],
            "primitive_sum_volume_m3": primitive_sum,
            "axis_aligned_union_volume_m3": union,
            "overlap_excess_volume_m3": max(0.0, primitive_sum - union),
            "void_subtracted_union_volume_m3": void_union,
            "void_intersections": void_intersections,
            "declared_volume_bounds_before_particle_crop_m3": {
                "lower_m3": void_union,
                "upper_m3": primitive_sum,
                "interpretation": "conservative declared-box interval; effective GenCase cell-centre crop remains UNKNOWN",
            },
            "declared_mass_bounds_before_particle_crop_kg": ({
                "lower_kg": void_union * rhop0,
                "upper_kg": primitive_sum * rhop0,
                "density_source": "XML rhop0",
            } if rhop0 is not None else {"status": "UNKNOWN_MISSING_RHOP0"}),
        }
        per_mk.append(entry)

    total_primitive = math.fsum(item["declared_volume_m3"] for item in fluids)
    total_union = union_volume(fluid_boxes)
    total_void_union = void_subtracted_volume(fluid_boxes, void_boxes)
    all_mk_overlap = max(0.0, math.fsum(item["axis_aligned_union_volume_m3"] for item in per_mk) - total_union)
    result: dict[str, Any] = {
        "source_xml": file_binding(path),
        "definition": {"dp_m": dp, "pointref_m": list(pointref) if pointref is not None else None},
        "rhop0_kg_m3": rhop0,
        "fluid_drawboxes": [{key: value for key, value in item.items() if key != "_box"} for item in fluids],
        "void_drawboxes": [{key: value for key, value in item.items() if key != "_box"} for item in voids],
        "bound_drawbox_count": len(bounds_declared),
        "per_mk": per_mk,
        "total_declared_box_geometry": {
            "primitive_sum_volume_m3": total_primitive,
            "axis_aligned_union_volume_m3": total_union,
            "cross_mk_overlap_excess_volume_m3": all_mk_overlap,
            "void_subtracted_union_volume_m3": total_void_union,
            "declared_volume_bounds_before_particle_crop_m3": {"lower_m3": total_void_union, "upper_m3": total_primitive},
            "declared_mass_bounds_before_particle_crop_kg": ({
                "lower_kg": total_void_union * rhop0, "upper_kg": total_primitive * rhop0,
                "density_source": "XML rhop0",
            } if rhop0 is not None else {"status": "UNKNOWN_MISSING_RHOP0"}),
        },
        "semantic_status": {
            "axis_aligned_union_math": "PASS_DECLARED_PRIMITIVE_GEOMETRY",
            "setmkvoid_intersection_math": "PASS_DECLARED_PRIMITIVE_GEOMETRY",
            "overlap_effect_on_generated_particles": "UNKNOWN",
            "void_effect_on_generated_particles": "UNKNOWN",
            "cell_centre_crop_or_fill": "UNKNOWN",
            "boundary_ownership_at_shared_faces": "UNKNOWN",
            "effective_particle_sample_mass": "UNKNOWN",
            "continuous_geometry_is_not_particle_sample_truth": True,
        },
    }
    return result


def build_report(quality_path: Path, output_path: Path) -> dict[str, Any]:
    quality_path = quality_path.expanduser().resolve()
    if not quality_path.is_file():
        raise FileNotFoundError(quality_path)
    output_path = output_path.expanduser().resolve()
    if output_path.exists():
        raise FileExistsError(f"refuse to overwrite immutable report: {output_path}")
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    rows = quality.get("sources")
    if not isinstance(rows, list) or len(rows) != 14:
        raise ValueError("quality input must contain exactly 14 source rows")
    sources = []
    for row in rows:
        source = row.get("source_xml") if isinstance(row, dict) else None
        path = source.get("path") if isinstance(source, dict) else None
        if not isinstance(path, str):
            raise ValueError(f"source row lacks source_xml.path: {row!r}")
        parsed = parse_xml(Path(path))
        parsed.update({"sentinel_id": row.get("sentinel_id"), "family_id": row.get("family_id"),
                       "physical_case_id": row.get("physical_case_id"),
                       "reference_particle_sample_mass_kg": source.get("sample_mass_kg")})
        sources.append(parsed)
    report = {
        "schema": SCHEMA,
        "status": "PASS_ANALYTIC_AXIS_ALIGNED_BOUNDS_EFFECTIVE_PARTICLES_UNKNOWN",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "audit_scope": {
            "source_rows": len(sources), "bi4_read": False, "hdf5_read": False, "solver_launch": False,
            "source_geometry_only": True, "union_method": "exact coordinate partition for axis-aligned boxes",
            "particle_centre_semantics": "UNKNOWN", "mass_rescaling": False,
        },
        "quality_input": file_binding(quality_path),
        "sources": sources,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        raise FileExistsError(output_path)
    temporary = output_path.with_name(output_path.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, output_path)
    finally:
        temporary.unlink(missing_ok=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quality", type=Path, default=DEFAULT_QUALITY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = build_report(args.quality, args.output)
    print(json.dumps({"status": report["status"], "output": str(args.output.resolve()),
                      "sources": len(report["sources"]), "bi4_read": False, "hdf5_read": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
