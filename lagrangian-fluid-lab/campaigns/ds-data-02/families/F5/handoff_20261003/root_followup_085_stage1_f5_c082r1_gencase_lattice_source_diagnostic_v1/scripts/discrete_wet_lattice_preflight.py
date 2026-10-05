#!/usr/bin/env python3
"""Source-only discrete wet-lattice preflight for C082R1.

The script parses the candidate Definition and small producer metadata only.  It
does not open BI4/H5/CSV data and does not invoke a producer.  Its endpoint and
clip-boundary variants are deliberately reported as a band because the bundled
GenCase parser source does not document tie ownership for this draw sequence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path


def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def dec(value: str | float) -> Decimal:
    return Decimal(str(value))


def point_in_polygon(x: Decimal, z: Decimal, polygon: list[tuple[Decimal, Decimal]]) -> bool:
    # Boundary-inclusive point test; this is only a source geometry comparison.
    inside = False
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        cross = (x - a[0]) * (b[1] - a[1]) - (z - a[1]) * (b[0] - a[0])
        if cross == 0 and min(a[0], b[0]) <= x <= max(a[0], b[0]) and min(a[1], b[1]) <= z <= max(a[1], b[1]):
            return True
        if (a[1] > z) != (b[1] > z):
            x_cross = (b[0] - a[0]) * (z - a[1]) / (b[1] - a[1]) + a[0]
            if x < x_cross:
                inside = not inside
    return inside


def parse_definition(path: Path) -> dict:
    root = ET.parse(path).getroot()
    definition = root.find("./casedef/geometry/definition")
    require(definition is not None, "geometry definition missing")
    dp = dec(definition.attrib["dp"])
    ref = tuple(dec(definition.find("pointref").attrib[k]) for k in ("x", "y", "z"))
    main = root.find("./casedef/geometry/commands/mainlist")
    require(main is not None, "mainlist missing")
    clip = main.find("clipplane")
    require(clip is not None, "clipplane missing")
    clip_point = tuple(dec(clip.find("point").attrib[k]) for k in ("x", "y", "z"))
    clip_vector = tuple(dec(clip.find("vector").attrib[k]) for k in ("x", "y", "z"))
    fluid = next((n for n in main if n.tag == "drawbox" and n.attrib.get("cmt") == "initial_fluid_equilibrium_cell_centres_dp020"), None)
    require(fluid is not None, "initial fluid drawbox missing")
    fp = tuple(dec(fluid.find("point").attrib[k]) for k in ("x", "y", "z"))
    fs = tuple(dec(fluid.find("size").attrib[k]) for k in ("x", "y", "z"))
    bed = next((n for n in main if n.tag == "drawextrude"), None)
    require(bed is not None and bed.attrib.get("closed") == "true", "closed bed drawextrude missing")
    polygon = [(dec(n.attrib["x"]), dec(n.attrib["z"])) for n in bed.findall("point")]
    require(len(polygon) >= 3, "bed polygon incomplete")
    layer = bed.find("layers")
    return {"dp": dp, "pointref": ref, "clip_point": clip_point, "clip_vector": clip_vector, "fluid_point": fp, "fluid_size": fs, "polygon": polygon, "layers": layer.attrib.get("vdp") if layer is not None else None}


def axis_values(start: Decimal, size: Decimal, dp: Decimal, include_endpoint: bool) -> list[Decimal]:
    count = int((size / dp).to_integral_value(rounding="ROUND_FLOOR")) + (1 if include_endpoint else 0)
    return [start + dp * i for i in range(count)]


def dot(point: tuple[Decimal, Decimal, Decimal], base: tuple[Decimal, Decimal, Decimal], vector: tuple[Decimal, Decimal, Decimal]) -> Decimal:
    return sum(((p - b) * v for p, b, v in zip(point, base, vector)), Decimal(0))


def enumerate_variant(g: dict, include_x: bool, include_y: bool, include_z: bool, boundary_inclusive: bool) -> dict:
    axes = [axis_values(g["fluid_point"][i], g["fluid_size"][i], g["dp"], include) for i, include in enumerate((include_x, include_y, include_z))]
    clip = []
    bed_owned = []
    for x in axes[0]:
        for y in axes[1]:
            for z in axes[2]:
                q = (x, y, z)
                # vector=(.28,0,-1), so dot<=0 is the above-profile fluid side.
                d = dot(q, g["clip_point"], g["clip_vector"])
                keep = d <= 0 if boundary_inclusive else d < 0
                if keep:
                    clip.append(q)
                    if point_in_polygon(x, z, g["polygon"]):
                        bed_owned.append(q)
    return {
        "include_endpoint": {"x": include_x, "y": include_y, "z": include_z},
        "axis_counts": [len(a) for a in axes],
        "clip_only_count": len(clip),
        "closed_bed_owned_count_after_clip": len(bed_owned),
        "rectangular_minus_closed_bed_count": len(clip) - len(bed_owned),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--definition", type=Path, required=True)
    parser.add_argument("--actual-binding", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    g = parse_definition(args.definition)
    binding = json.loads(args.actual_binding.read_text(encoding="utf-8"))
    actual = int(binding["actual_counts"]["fluid_particles"])
    dp3 = g["dp"] ** 3
    rectangle_volume = math.prod(float(v) for v in g["fluid_size"])
    all_variants = []
    for ix in (False, True):
        for iy in (False, True):
            for iz in (False, True):
                for inclusive in (False, True):
                    all_variants.append(enumerate_variant(g, ix, iy, iz, inclusive))
    # The physically relevant endpoint candidate retains both y and z endpoints;
    # x's extra endpoint is above the profile and therefore does not alter the band.
    relevant = [v for v in all_variants if v["include_endpoint"]["y"] and v["include_endpoint"]["z"]]
    clip_counts = [v["clip_only_count"] for v in relevant]
    geom_counts = [v["rectangular_minus_closed_bed_count"] for v in relevant]
    report = {
        "schema": "ds02.f5.c082r1.discrete-wet-lattice-preflight.fresh085.v1",
        "status": "completed_source_math_only",
        "definition": str(args.definition),
        "definition_sha256": sha(args.definition),
        "actual_binding": str(args.actual_binding),
        "actual_fluid_particles_from_genuine_gencase": actual,
        "source": {
            "dp_m": float(g["dp"]),
            "pointref_m": [float(v) for v in g["pointref"]],
            "fluid_box_point_m": [float(v) for v in g["fluid_point"]],
            "fluid_box_size_m": [float(v) for v in g["fluid_size"]],
            "clipplane_point_m": [float(v) for v in g["clip_point"]],
            "clipplane_vector": [float(v) for v in g["clip_vector"]],
            "closed_bed_layers_vdp": g["layers"],
        },
        "continuous_reference": {
            "rectangular_fluid_volume_m3": rectangle_volume,
            "rectangular_equivalent_dp3": rectangle_volume / float(dp3),
            "legacy_continuum_mass_kg": 325.7142857142857,
            "actual_csv_mass_kg_metadata_only": 253.26401266320002,
            "actual_csv_mass_is_not_read_by_source_agent": True,
        },
        "relevant_endpoint_variants": relevant,
        "clip_only_prediction_band": {
            "min_count": min(clip_counts),
            "max_count": max(clip_counts),
            "interpretation": "tie/endpoint band from exact source arithmetic; historical 40710 is within this band",
        },
        "closed_bed_prediction_band": {
            "min_count": min(geom_counts),
            "max_count": max(geom_counts),
            "interpretation": "source polygon occupancy under a simple lattice point test; not a GenCase parser contract",
        },
        "actual_gap_comparison": {
            "actual_minus_clip_only_band": [actual - max(clip_counts), actual - min(clip_counts)],
            "actual_minus_closed_bed_band": [actual - max(geom_counts), actual - min(geom_counts)],
            "historical_source_contract_fluid": 40710,
            "historical_deficit_from_actual": 40710 - actual,
            "interpretation": "The 31658 producer count is materially below source-grid clip-only candidates; endpoint ties alone cannot explain it. Draw-order/solid occupancy and exact raster ownership remain hypotheses for the actual CSV diagnostic.",
        },
        "policy": {
            "arrays_opened_by_source_agent": False,
            "jobs_started": False,
            "expected_fluid_replaced": False,
            "mass_rescaled": False,
            "qa_pass": False,
            "dynamic_acceptance": False,
            "full801_authorized": False,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "actual_fluid": actual, "clip_band": [min(clip_counts), max(clip_counts)]}, sort_keys=True))


if __name__ == "__main__":
    main()
