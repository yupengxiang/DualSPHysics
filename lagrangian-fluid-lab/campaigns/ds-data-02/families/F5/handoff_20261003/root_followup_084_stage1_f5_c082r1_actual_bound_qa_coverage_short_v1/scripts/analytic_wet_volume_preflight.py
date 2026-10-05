#!/usr/bin/env python3
"""Source-only fluid wet-volume/count preflight for C082R1.

This reads only the candidate XML and actual small metadata binding.  It
enumerates source lattice conventions and clips the analytic bed polygon with
stdlib arithmetic.  It never opens BI4/H5/CSV arrays and never launches a
producer.  The result is a comparison aid, not a count contract or acceptance
criterion because GenCase raster ownership/draw ordering is still authoritative.
"""
from __future__ import annotations
import argparse, hashlib, json, math
import xml.etree.ElementTree as ET
from pathlib import Path


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def inside_polygon(x: float, z: float, polygon: list[tuple[float, float]]) -> bool:
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        cross = (x - a[0]) * (b[1] - a[1]) - (z - a[1]) * (b[0] - a[0])
        if abs(cross) <= 1.0e-10 and min(a[0], b[0]) - 1.0e-10 <= x <= max(a[0], b[0]) + 1.0e-10 and min(a[1], b[1]) - 1.0e-10 <= z <= max(a[1], b[1]) + 1.0e-10:
            return True
    inside = False
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        if (a[1] > z) != (b[1] > z):
            x_cross = (b[0] - a[0]) * (z - a[1]) / (b[1] - a[1]) + a[0]
            if x < x_cross:
                inside = not inside
    return inside


def clip_polygon(poly: list[tuple[float, float]], axis: int, bound: float, keep_ge: bool) -> list[tuple[float, float]]:
    def value(point: tuple[float, float]) -> float:
        return point[axis] - bound
    def is_inside(point: tuple[float, float]) -> bool:
        return value(point) >= -1.0e-12 if keep_ge else value(point) <= 1.0e-12
    out: list[tuple[float, float]] = []
    for a, b in zip(poly, poly[1:] + poly[:1]):
        ia, ib = is_inside(a), is_inside(b)
        if ia:
            out.append(a)
        if ia != ib:
            va, vb = value(a), value(b)
            t = va / (va - vb)
            out.append((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
    return out


def polygon_area(poly: list[tuple[float, float]]) -> float:
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(poly, poly[1:] + poly[:1]))) / 2.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--definition", type=Path, required=True)
    ap.add_argument("--actual-binding", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    root = ET.parse(args.definition).getroot()
    definition = root.find("./casedef/geometry/definition")
    require(definition is not None, "geometry definition missing")
    dp = float(definition.attrib["dp"])
    pointref_node = definition.find("pointref")
    require(pointref_node is not None, "pointref missing")
    pointref = tuple(float(pointref_node.attrib[k]) for k in ("x", "y", "z"))
    main = root.find("./casedef/geometry/commands/mainlist")
    require(main is not None, "geometry command list missing")
    clip = main.find("clipplane")
    require(clip is not None, "clipplane missing")
    clip_point_node, clip_vector_node = clip.find("point"), clip.find("vector")
    require(clip_point_node is not None and clip_vector_node is not None, "clipplane point/vector missing")
    clip_point = tuple(float(clip_point_node.attrib[k]) for k in ("x", "y", "z"))
    clip_vector = tuple(float(clip_vector_node.attrib[k]) for k in ("x", "y", "z"))
    fluid_node = next((n for n in main if n.tag == "drawbox" and n.attrib.get("cmt") == "initial_fluid_equilibrium_cell_centres_dp020"), None)
    require(fluid_node is not None, "initial fluid drawbox missing")
    fluid_point_node, fluid_size_node = fluid_node.find("point"), fluid_node.find("size")
    require(fluid_point_node is not None and fluid_size_node is not None, "fluid point/size missing")
    fluid_point = tuple(float(fluid_point_node.attrib[k]) for k in ("x", "y", "z"))
    fluid_size = tuple(float(fluid_size_node.attrib[k]) for k in ("x", "y", "z"))
    bed_node = next((n for n in main if n.tag == "drawextrude"), None)
    require(bed_node is not None, "analytic drawextrude missing")
    polygon = [(float(n.attrib["x"]), float(n.attrib["z"])) for n in bed_node.findall("point")]
    require(len(polygon) >= 3, "analytic bed polygon incomplete")
    actual = json.loads(args.actual_binding.read_text(encoding="utf-8"))
    actual_count = int(actual["actual_counts"]["fluid_particles"])
    nominal_volume = math.prod(fluid_size)
    cell_volume = dp ** 3
    nominal_equivalent = nominal_volume / cell_volume

    # GenCase's endpoint ownership is implementation-defined; enumerate both
    # endpoint conventions while holding the exact source point/size fixed.
    variants = []
    for include_x in (False, True):
        for include_y in (False, True):
            for include_z in (False, True):
                counts = [math.floor(size / dp + 1.0e-9) + (1 if include else 0) for size, include in zip(fluid_size, (include_x, include_y, include_z))]
                lattice = []
                for i in range(counts[0]):
                    x = fluid_point[0] + i * dp
                    for j in range(counts[1]):
                        y = fluid_point[1] + j * dp
                        for k in range(counts[2]):
                            z = fluid_point[2] + k * dp
                            dot = sum((coord - base) * direction for coord, base, direction in zip((x, y, z), clip_point, clip_vector))
                            lattice.append((x, y, z, dot))
                by_side = {}
                for side_name, sign in (("dot_leq_zero", -1.0), ("dot_geq_zero", 1.0)):
                    clipped = [q for q in lattice if sign * q[3] >= -1.0e-10]
                    minus_bed = [q for q in clipped if not inside_polygon(q[0], q[2], polygon)]
                    by_side[side_name] = {"clip_count": len(clipped), "rectangular_clip_minus_analytic_bed_count": len(minus_bed), "analytic_bed_owned_count": len(clipped) - len(minus_bed)}
                variants.append({"include_endpoint": {"x": include_x, "y": include_y, "z": include_z}, "axis_counts": {"x": counts[0], "y": counts[1], "z": counts[2]}, "sides": by_side})

    clipped_bed = list(polygon)
    for axis, bound, ge in ((0, fluid_point[0], True), (0, fluid_point[0] + fluid_size[0], False), (1, fluid_point[2], True), (1, fluid_point[2] + fluid_size[2], False)):
        clipped_bed = clip_polygon(clipped_bed, axis, bound, ge)
    overlap_area_xz = polygon_area(clipped_bed) if clipped_bed else 0.0
    overlap_volume = overlap_area_xz * fluid_size[1]
    continuous_wet_volume = nominal_volume - overlap_volume
    report = {
        "schema": "ds02.f5.c082r1.analytic-wet-volume-preflight.v1",
        "status": "completed_source_math_only",
        "source_definition": str(args.definition),
        "source_definition_sha256": sha(args.definition),
        "actual_binding": str(args.actual_binding),
        "actual_fluid_particles_from_genuine_gencase": actual_count,
        "source_parameters": {"dp_m": dp, "pointref_m": list(pointref), "fluid_point_m": list(fluid_point), "fluid_size_m": list(fluid_size), "clipplane_point_m": list(clip_point), "clipplane_vector": list(clip_vector), "closed_bed_polygon_xz_m": [list(p) for p in polygon]},
        "continuous_volume": {"rectangular_fluid_volume_m3": nominal_volume, "analytic_bed_overlap_with_fluid_rectangle_m3": overlap_volume, "prospective_rectangular_minus_analytic_bed_wet_volume_m3": continuous_wet_volume, "cell_volume_m3": cell_volume, "rectangular_equivalent_lattice_count": nominal_equivalent, "prospective_wet_equivalent_lattice_count": continuous_wet_volume / cell_volume},
        "discrete_endpoint_variants": variants,
        "actual_comparison": {"actual_minus_continuous_wet_equivalent_count": actual_count - continuous_wet_volume / cell_volume, "actual_minus_nominal_rectangular_equivalent_count": actual_count - nominal_equivalent, "interpretation": "The producer's 31658 is measured metadata. This source-only geometric preflight cannot assign GenCase raster ownership, layer shell ownership, or draw-order semantics; no expected count is substituted and no pass is inferred."},
        "policy": {"arrays_opened_by_source_agent": False, "jobs_started": False, "mass_rescaled": False, "dynamic_acceptance": False, "full801_authorized": False}
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "actual_fluid": actual_count, "continuous_wet_equivalent": report["continuous_volume"]["prospective_wet_equivalent_lattice_count"]}, sort_keys=True))

if __name__ == "__main__":
    main()
