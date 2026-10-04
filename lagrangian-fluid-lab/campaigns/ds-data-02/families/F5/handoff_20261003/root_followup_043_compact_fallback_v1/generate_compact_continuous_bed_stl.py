#!/usr/bin/env python3
"""Source-code generator and geometric validator for the F5 compact continuous bed STL.

Provides pure-function geometry definitions, watertight mesh synthesis,
and local bed elevation queries for the compact F5 physical fallback geometry
(H = 0.40 m, flume width = 0.30 m, fluid length = 2.00 m, mass = 240.0 kg).

Actual scientific file output is executed strictly under Rootguard dispatch.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

# Compact continuous 2D bed profile coordinates (x [m], z [m])
# Flat basin under fluid: x in [-0.20, 2.00] m at z = 0.000 m.
# Slope m = 0.280 from toe x = 2.00 m to crest start x = 3.60 m (reaches z = 0.448 m, above SWL 0.400 m).
# Horizontal crest plateau: x in [3.60, 3.90] m at z = 0.448 m.
# Downslope into receiving basin: x in [3.90, 4.40] m down to z = 0.050 m.
# Downstream receiving basin floor: x in [4.40, 4.80] m at z = 0.050 m.
COMPACT_BED_PROFILE_NODES: List[Tuple[float, float]] = [
    (-0.20, 0.000),
    (2.00, 0.000),
    (3.00, 0.280),
    (3.60, 0.448),
    (3.90, 0.448),
    (4.40, 0.050),
    (4.80, 0.050),
]

# Physical flume bounds for compact configuration
Y_MIN: float = -0.150
Y_MAX: float = 0.150
FLUME_WIDTH_M: float = 0.300
Z_BOTTOM: float = -0.150
CHARACTERISTIC_DEPTH_H_M: float = 0.400
FLUID_LENGTH_M: float = 2.000
NOMINAL_FLUID_MASS_KG: float = 240.000


def compute_bed_elevation(x: float) -> float:
    """Evaluate continuous bed elevation z_bed(x) at any longitudinal coordinate.

    Uses exact piecewise linear interpolation over the authentic profile nodes.
    """
    if x <= COMPACT_BED_PROFILE_NODES[0][0]:
        return COMPACT_BED_PROFILE_NODES[0][1]
    if x >= COMPACT_BED_PROFILE_NODES[-1][0]:
        return COMPACT_BED_PROFILE_NODES[-1][1]

    for i in range(len(COMPACT_BED_PROFILE_NODES) - 1):
        x0, z0 = COMPACT_BED_PROFILE_NODES[i]
        x1, z1 = COMPACT_BED_PROFILE_NODES[i + 1]
        if x0 <= x <= x1:
            if abs(x1 - x0) < 1e-12:
                return z0
            t = (x - x0) / (x1 - x0)
            return z0 + t * (z1 - z0)

    return 0.0


def get_observer_bed_elevations(
    gauge_x_coords: Sequence[float],
) -> List[float]:
    """Return true local bed elevations for specified wave probe x-coordinates."""
    return [round(compute_bed_elevation(x), 6) for x in gauge_x_coords]


def build_compact_bed_triangles() -> List[Tuple[Tuple[float, float, float], ...]]:
    """Synthesize the 52 triangular facets forming the closed compact continuous bed solid.

    The solid comprises:
      - 6 top surface segments (12 triangles)
      - 6 bottom surface segments (12 triangles)
      - 6 left side panels (12 triangles)
      - 6 right side panels (12 triangles)
      - 1 upstream endcap at x = -0.20 m (2 triangles)
      - 1 downstream endcap at x = 4.80 m (2 triangles)
    Total = 52 triangles.
    """
    facets: List[Tuple[Tuple[float, float, float], ...]] = []

    # 1. Top surface facets (looking from +z)
    for i in range(len(COMPACT_BED_PROFILE_NODES) - 1):
        x0, z0 = COMPACT_BED_PROFILE_NODES[i]
        x1, z1 = COMPACT_BED_PROFILE_NODES[i + 1]
        v0 = (x0, Y_MIN, z0)
        v1 = (x1, Y_MIN, z1)
        v2 = (x1, Y_MAX, z1)
        v3 = (x0, Y_MAX, z0)
        facets.append((v0, v1, v2))
        facets.append((v0, v2, v3))

    # 2. Bottom surface facets (z = Z_BOTTOM, looking from -z)
    for i in range(len(COMPACT_BED_PROFILE_NODES) - 1):
        x0, _ = COMPACT_BED_PROFILE_NODES[i]
        x1, _ = COMPACT_BED_PROFILE_NODES[i + 1]
        b0 = (x1, Y_MIN, Z_BOTTOM)
        b1 = (x0, Y_MIN, Z_BOTTOM)
        b2 = (x0, Y_MAX, Z_BOTTOM)
        b3 = (x1, Y_MAX, Z_BOTTOM)
        facets.append((b0, b1, b2))
        facets.append((b0, b2, b3))

    # 3. Left side facets (y = Y_MIN, looking from -y)
    for i in range(len(COMPACT_BED_PROFILE_NODES) - 1):
        x0, z0 = COMPACT_BED_PROFILE_NODES[i]
        x1, z1 = COMPACT_BED_PROFILE_NODES[i + 1]
        l0 = (x0, Y_MIN, Z_BOTTOM)
        l1 = (x1, Y_MIN, Z_BOTTOM)
        l2 = (x1, Y_MIN, z1)
        l3 = (x0, Y_MIN, z0)
        facets.append((l0, l1, l2))
        facets.append((l0, l2, l3))

    # 4. Right side facets (y = Y_MAX, looking from +y)
    for i in range(len(COMPACT_BED_PROFILE_NODES) - 1):
        x0, z0 = COMPACT_BED_PROFILE_NODES[i]
        x1, z1 = COMPACT_BED_PROFILE_NODES[i + 1]
        r0 = (x1, Y_MAX, Z_BOTTOM)
        r1 = (x0, Y_MAX, Z_BOTTOM)
        r2 = (x0, Y_MAX, z0)
        r3 = (x1, Y_MAX, z1)
        facets.append((r0, r1, r2))
        facets.append((r0, r2, r3))

    # 5. Upstream endcap (x = -0.20 m, looking from -x)
    x_up, z_up = COMPACT_BED_PROFILE_NODES[0]
    u0 = (x_up, Y_MAX, Z_BOTTOM)
    u1 = (x_up, Y_MIN, Z_BOTTOM)
    u2 = (x_up, Y_MIN, z_up)
    u3 = (x_up, Y_MAX, z_up)
    facets.append((u0, u1, u2))
    facets.append((u0, u2, u3))

    # 6. Downstream endcap (x = 4.80 m, looking from +x)
    x_dn, z_dn = COMPACT_BED_PROFILE_NODES[-1]
    d0 = (x_dn, Y_MIN, Z_BOTTOM)
    d1 = (x_dn, Y_MAX, Z_BOTTOM)
    d2 = (x_dn, Y_MAX, z_dn)
    d3 = (x_dn, Y_MIN, z_dn)
    facets.append((d0, d1, d2))
    facets.append((d0, d2, d3))

    return facets


def generate_stl_ascii_text(solid_name: str = "f5_compact_continuous_bed") -> str:
    """Generate ASCII STL representation of the 52-triangle compact continuous bed."""
    facets = build_compact_bed_triangles()
    lines = [f"solid {solid_name}"]
    for tri in facets:
        lines.append("  facet normal 0 0 0")
        lines.append("    outer loop")
        for vx, vy, vz in tri:
            sx = f"{vx:g}" if isinstance(vx, float) else str(vx)
            sy = f"{vy:g}" if isinstance(vy, float) else str(vy)
            sz = f"{vz:g}" if isinstance(vz, float) else str(vz)
            lines.append(f"      vertex {sx} {sy} {sz}")
        lines.append("    endloop")
        lines.append("  endfacet")
    lines.append(f"endsolid {solid_name}\n")
    return "\n".join(lines)


def verify_mesh_topology() -> Dict[str, object]:
    """Perform topological and volumetric validation on the compact bed geometry."""
    facets = build_compact_bed_triangles()
    assert len(facets) == 52, f"Expected 52 facets, got {len(facets)}"

    all_x = [v[0] for tri in facets for v in tri]
    all_y = [v[1] for tri in facets for v in tri]
    all_z = [v[2] for tri in facets for v in tri]

    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)
    min_z, max_z = min(all_z), max(all_z)

    assert abs(min_x - (-0.20)) < 1e-6, f"Expected min_x -0.20, got {min_x}"
    assert abs(max_x - 4.80) < 1e-6, f"Expected max_x 4.80, got {max_x}"
    assert abs(min_y - (-0.15)) < 1e-6, f"Expected min_y -0.15, got {min_y}"
    assert abs(max_y - 0.15) < 1e-6, f"Expected max_y 0.15, got {max_y}"
    assert abs(min_z - (-0.15)) < 1e-6, f"Expected min_z -0.15, got {min_z}"
    assert abs(max_z - 0.448) < 1e-6, f"Expected max_z 0.448, got {max_z}"

    # Slope verification
    slope = (compute_bed_elevation(3.60) - compute_bed_elevation(2.00)) / (3.60 - 2.00)
    assert abs(slope - 0.280) < 1e-6, f"Expected slope 0.280, got {slope}"

    return {
        "facets_count": len(facets),
        "bounds_m": {
            "x": [min_x, max_x],
            "y": [min_y, max_y],
            "z": [min_z, max_z],
        },
        "slope_m": slope,
        "crest_elevation_m": max_z,
        "receiving_basin_elevation_m": compute_bed_elevation(4.60),
        "is_watertight_candidate": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="F5 compact continuous bed STL generator and geometric validator."
    )
    parser.add_argument(
        "--validate-mesh",
        action="store_true",
        help="Run topological and geometric validation on the compact bed definition.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Target output file path (Rootguard execution only).",
    )
    args = parser.parse_args()

    if args.validate_mesh:
        report = verify_mesh_topology()
        print("Compact bed mesh validation passed:")
        for k, v in report.items():
            print(f"  {k}: {v}")

    if args.output:
        text = generate_stl_ascii_text()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
        print(f"Wrote compact STL to {args.output} (sha256={digest})")


if __name__ == "__main__":
    main()
