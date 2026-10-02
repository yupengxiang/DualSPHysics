#!/usr/bin/env python3
"""Read-only F1 boundary-layer coverage evidence.

The initial exact-plane audit is intentionally retained as an immutable
source of evidence.  DualSPHysics mDBC layers can be offset from the declared
continuum wall, so this additive audit reports the nearest decoded fixed
particle layers and their finite tangential coverage.  A layer-band result is
diagnostic evidence only; it does not turn an absent exact plane into a
qualification pass and it does not infer simulation-domain padding.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts.ds_data02_f1_boundary_coverage import (
    _decode_bi4,
    _plane_specs,
    _read_native_arrays,
    _summarize_planes,
    read_binary_vtk_points,
    sha256,
)


SCHEMA = "ds02.f1.finite-center.native-boundary-layer-coverage.v1"
ROUND_DIGITS = 8


def _layer_rows(points: np.ndarray, spec: dict[str, Any], *, width_m: float) -> dict[str, Any]:
    """Return nearest coordinate layers and union coverage for one face.

    The width is measured from the declared physical plane.  All coordinate
    layers in that band are retained separately, so the report cannot hide a
    missing exact plane behind a single aggregate count.
    """

    axis = int(spec["axis"])
    tangent = tuple(spec["tangent"])
    finite = np.isfinite(points).all(axis=1)
    coords = points[:, axis]
    finite_coords = coords[finite]
    target = float(spec["target"])
    if not len(finite_coords):
        unique = np.empty(0, dtype=float)
    else:
        unique = np.unique(np.round(finite_coords, ROUND_DIGITS))
        unique = unique[np.abs(unique - target) <= width_m + 1.0e-10]
    unique = sorted((float(value) for value in unique), key=lambda value: (abs(value - target), value))

    layers: list[dict[str, Any]] = []
    union = np.zeros(len(points), dtype=bool)
    for coordinate in unique:
        mask = finite & np.isclose(coords, coordinate, atol=5.0e-8, rtol=0.0)
        union |= mask
        selected = points[mask]
        tangent_values = [np.unique(np.round(selected[:, col], ROUND_DIGITS)) for col in tangent]
        layers.append({
            "coordinate_m": coordinate,
            "offset_from_declared_plane_m": coordinate - target,
            "point_count": int(len(selected)),
            "tangent_axes": "xyz"[tangent[0]] + "," + "xyz"[tangent[1]],
            "tangent_unique_counts": {
                "first": int(len(tangent_values[0])),
                "second": int(len(tangent_values[1])),
            },
            "tangent_min_m": [float(selected[:, col].min()) for col in tangent] if len(selected) else [None, None],
            "tangent_max_m": [float(selected[:, col].max()) for col in tangent] if len(selected) else [None, None],
        })

    selected = points[union]
    tangent_values = [np.unique(np.round(selected[:, col], ROUND_DIGITS)) for col in tangent]
    tangent_min = [float(selected[:, col].min()) for col in tangent] if len(selected) else [None, None]
    tangent_max = [float(selected[:, col].max()) for col in tangent] if len(selected) else [None, None]
    expected_low = tuple(float(value) for value in spec["low"])
    expected_high = tuple(float(value) for value in spec["high"])
    finite_rectangle = bool(
        len(selected)
        and all(tangent_min[i] <= expected_low[i] + width_m for i in range(2))
        and all(tangent_max[i] >= expected_high[i] - width_m for i in range(2))
    )
    return {
        "name": spec["name"],
        "axis": "xyz"[axis],
        "declared_plane_m": target,
        "band_width_m": width_m,
        "exact_plane_point_count_within_band_tolerance": int(
            sum(row["point_count"] for row in layers if abs(row["offset_from_declared_plane_m"]) <= 5.0e-8)
        ),
        "nearest_layer": layers[0] if layers else None,
        "layers_in_band": layers,
        "band_union_point_count": int(len(selected)),
        "band_union_tangent_unique_counts": {
            "first": int(len(tangent_values[0])),
            "second": int(len(tangent_values[1])),
        },
        "band_union_tangent_min_m": tangent_min,
        "band_union_tangent_max_m": tangent_max,
        "band_union_finite_rectangle_coverage": finite_rectangle,
        "interpretation": "diagnostic layer-band evidence; exact-plane and solver wall checks remain separate",
    }


def _layer_summary(points: np.ndarray, *, h_m: float, band_multiple: float) -> dict[str, Any]:
    width = float(h_m * band_multiple)
    rows = [_layer_rows(points, spec, width_m=width) for spec in _plane_specs()]
    by_name = {row["name"]: row for row in rows}
    outer = ["outer_x_low", "outer_x_high", "outer_y_low", "outer_y_high", "outer_z_low"]
    return {
        "band_multiple_of_h": float(band_multiple),
        "band_width_m": width,
        "planes": rows,
        "outer_five_band_union_nonempty": all(by_name[name]["band_union_point_count"] > 0 for name in outer),
        "outer_five_band_union_rectangle_coverage": all(
            by_name[name]["band_union_finite_rectangle_coverage"] for name in outer
        ),
    }


def audit(*, gencase_root: Path, decoder: Path, output: Path, band_multiple: float = 2.0) -> dict[str, Any]:
    gencase_root = gencase_root.resolve()
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    generated_xml = next(gencase_root.glob("*.xml"))
    generated_bi4 = next(gencase_root.glob("*.bi4"))
    bound_vtk = next(gencase_root.glob("*_Bound.vtk"))
    generated_out = next(gencase_root.glob("*.out"))
    points = read_binary_vtk_points(bound_vtk)
    exact_vtk = _summarize_planes(points, 2.0e-6)
    text = generated_xml.read_text(errors="replace")
    del text
    import xml.etree.ElementTree as ET
    root = ET.parse(generated_xml).getroot()
    dp = float(root.find(".//constants/dp").get("value"))
    particles = root.find(".//particles")
    expected_total = int(particles.get("np", "-1"))
    expected_fixed = int(particles.get("nb", "-1"))
    with __import__("tempfile").TemporaryDirectory(prefix="f1-boundary-layer-decode-") as temp:
        metadata, particle_info, particle_dir = _decode_bi4(generated_bi4, decoder, Path(temp) / "native")
        ids, native_positions, normals = _read_native_arrays(particle_dir)
        fixed_count = int(float(metadata.get("CaseNfixed", expected_fixed)))
        native_fixed = native_positions[:fixed_count]
        native_layer = _layer_summary(native_fixed, h_m=dp * 2.0, band_multiple=band_multiple)
        native_exact = _summarize_planes(native_fixed, 2.0e-8)
        native_metadata = metadata
        native_particle_info = particle_info
        native_ids_unique = bool(len(np.unique(ids)) == len(ids))
        native_normals_finite = bool(normals is not None and np.isfinite(normals).all())
    report = {
        "schema": SCHEMA,
        "case_id": generated_xml.stem,
        "physical_case_id": "F1_DUAL_FINITE_CENTER_QUADRATURE",
        "claim_boundary": "Decoded mDBC layer-band evidence only; no solver, Q-N, or production qualification.",
        "source_hashes": {
            "generated_xml": sha256(generated_xml),
            "generated_bi4": sha256(generated_bi4),
            "generated_out": sha256(generated_out),
            "bound_vtk": sha256(bound_vtk),
            "decoder": sha256(decoder),
        },
        "generated": {
            "point_count": int(len(points)),
            "point_bounds_m": [points.min(axis=0).tolist(), points.max(axis=0).tolist()],
            "expected_total_particles": expected_total,
            "expected_fixed_particles": expected_fixed,
            "exact_plane_summary": exact_vtk,
            "layer_band_summary": _layer_summary(points, h_m=dp * 2.0, band_multiple=band_multiple),
        },
        "native_bi4": {
            "decoded_xml_metadata": native_metadata,
            "particle_info": native_particle_info,
            "id_count": int(len(ids)),
            "ids_unique": native_ids_unique,
            "fixed_count": fixed_count,
            "fixed_bounds_m": [native_fixed.min(axis=0).tolist(), native_fixed.max(axis=0).tolist()],
            "fixed_normals_finite": native_normals_finite,
            "exact_plane_summary": native_exact,
            "layer_band_summary": native_layer,
        },
        "checks": {
            "counts_match_native": expected_total == int(float(native_metadata.get("CaseNp", expected_total))) and expected_fixed == fixed_count,
            "native_identity_axis_unique": native_ids_unique,
            "native_normals_finite": native_normals_finite,
            "exact_outer_five_generated_nonempty": exact_vtk["outer_five_nonempty"],
            "exact_outer_five_native_nonempty": native_exact["outer_five_nonempty"],
            "layer_band_outer_five_nonempty": native_layer["outer_five_band_union_nonempty"],
            "layer_band_outer_five_rectangle_coverage": native_layer["outer_five_band_union_rectangle_coverage"],
            "decoded_domain_padding_proven": False,
        },
        "domain_padding": {
            "status": "not_proven",
            "reason": "This additive audit does not infer CasePos/MapPos or default simulation-domain margins from XML or particle extrema.",
            "decoded_case_pos_min": native_metadata.get("CasePosMin"),
            "decoded_case_pos_max": native_metadata.get("CasePosMax"),
            "decoded_map_pos_min": native_metadata.get("MapPosMin"),
            "decoded_map_pos_max": native_metadata.get("MapPosMax"),
        },
        "limitations": [
            "Layer-band coverage records offsets and tangent spans; it cannot convert an absent exact physical plane into a plane point.",
            "The open top is excluded from the five-face list; separator rows are reported separately from outer rows.",
            "No solver-time wall penetration, numerical-domain legality, Q-N, or production status is assessed.",
        ],
        "q_n_status": "not_assessed",
        "production_status": "not_accepted",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gencase-root", type=Path, required=True)
    parser.add_argument("--decoder", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--band-multiple", type=float, default=2.0)
    args = parser.parse_args()
    report = audit(gencase_root=args.gencase_root, decoder=args.decoder, output=args.output, band_multiple=args.band_multiple)
    print(json.dumps({"schema": report["schema"], "checks": report["checks"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
