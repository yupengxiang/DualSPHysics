#!/usr/bin/env python3
"""Read-only native boundary and numerical-domain evidence for F1.

This audit consumes the immutable GenCase Bound.vtk and initial BI4.  It uses
upstream ``bi4_dump`` only to materialise a fresh temporary decode namespace;
it never edits the source BI4/VTK/XML and never launches a solver.  Counts are
reported at the declared physical planes, with tangential coordinate spans and
actual grid steps.  Solver/Q-N/production status remains unassessed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from typing import Any, Iterable

import numpy as np

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(LAB))

from scripts.ds_data02_f1_finite_center_audit import read_binary_vtk_points


SCHEMA = "ds02.f1.finite-center.native-boundary-coverage.v1"
PLANE_TOLERANCE_VTK_M = 2.0e-6
PLANE_TOLERANCE_NATIVE_M = 2.0e-8
ROUND_DIGITS = 8


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _number(pattern: str, text: str, label: str, cast=float):
    match = re.search(pattern, text)
    if match is None:
        raise ValueError(f"{label} not found")
    return cast(match.group(1).replace(",", ""))


def _decode_bi4(bi4: Path, decoder: Path, output_prefix: Path) -> tuple[dict[str, str], dict[str, str], Path]:
    """Decode one initial BI4 to a fresh prefix and return metadata/particle info."""

    if output_prefix.exists():
        raise FileExistsError(f"refusing to reuse decode prefix: {output_prefix}")
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(decoder), str(bi4), str(output_prefix)], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    native_xml = output_prefix.with_suffix(".xml")
    if not native_xml.is_file():
        raise ValueError(f"bi4_dump did not produce XML: {native_xml}")
    root = ET.parse(native_xml).getroot()
    parent = root.find("./item")
    if parent is None:
        raise ValueError("decoded BI4 has no JPartDataBi4 item")
    metadata = {str(e.get("name")): str(e.get("v")) for e in parent if e.get("name") and e.tag != "item"}
    child = root.find(".//item/item")
    if child is None or not child.get("name"):
        raise ValueError("decoded BI4 has no particle item")
    particle_info = {str(e.get("name")): str(e.get("v")) for e in child if e.get("name") and e.get("v") is not None}
    return metadata, particle_info, output_prefix / str(child.get("name"))


def _read_native_arrays(particle_dir: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    ids_path = particle_dir / "Idp.bin"
    pos_path = particle_dir / "Posd.bin"
    if not pos_path.exists():
        pos_path = particle_dir / "Pos.bin"
    if not ids_path.exists() or not pos_path.exists():
        raise ValueError(f"decoded BI4 arrays missing under {particle_dir}")
    ids = np.fromfile(ids_path, dtype=np.uint32)
    positions = np.fromfile(pos_path, dtype=np.float64 if pos_path.name == "Posd.bin" else np.float32)
    if positions.size != ids.size * 3:
        raise ValueError("decoded position and identity lengths differ")
    normals_path = particle_dir / "BoundNor.bin"
    normals = None
    if normals_path.exists():
        normals = np.fromfile(normals_path, dtype=np.float32)
        if normals.size != int(ids.size * 3):
            # Some native outputs contain normals only for fixed particles.
            normals = normals.reshape(-1, 3)
        else:
            normals = normals.reshape(-1, 3)
    return ids, positions.reshape(-1, 3).astype(np.float64, copy=False), normals


def _rounded_unique(values: np.ndarray) -> np.ndarray:
    if not len(values):
        return np.empty(0, dtype=np.float64)
    return np.unique(np.round(np.asarray(values, dtype=np.float64), ROUND_DIGITS))


def _steps(values: np.ndarray) -> dict[str, float | None]:
    unique = _rounded_unique(values)
    if len(unique) < 2:
        return {"min_m": None, "max_m": None}
    delta = np.diff(unique)
    delta = delta[delta > 1.0e-12]
    if not len(delta):
        return {"min_m": None, "max_m": None}
    return {"min_m": float(delta.min()), "max_m": float(delta.max())}


def _plane_summary(points: np.ndarray, *, axis: int, target: float, tolerance: float,
                   tangent_axes: tuple[int, int], name: str,
                   expected_tangent_low: tuple[float, float] | None = None,
                   expected_tangent_high: tuple[float, float] | None = None) -> dict[str, Any]:
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("points must have shape (N, 3)")
    mask = np.isfinite(points).all(axis=1) & (np.abs(points[:, axis] - target) <= tolerance)
    selected = points[mask]
    tangent_a = _rounded_unique(selected[:, tangent_axes[0]]) if len(selected) else np.empty(0)
    tangent_b = _rounded_unique(selected[:, tangent_axes[1]]) if len(selected) else np.empty(0)
    actual_low = [float(selected[:, col].min()) for col in tangent_axes] if len(selected) else [None, None]
    actual_high = [float(selected[:, col].max()) for col in tangent_axes] if len(selected) else [None, None]
    coverage = None
    if expected_tangent_low is not None and expected_tangent_high is not None:
        coverage = {
            "expected_low_m": list(expected_tangent_low),
            "expected_high_m": list(expected_tangent_high),
            "min_reaches_or_below_low": bool(len(selected) and all(actual_low[i] <= expected_tangent_low[i] + tolerance for i in range(2))),
            "max_reaches_or_above_high": bool(len(selected) and all(actual_high[i] >= expected_tangent_high[i] - tolerance for i in range(2))),
        }
        coverage["finite_rectangle_coverage"] = bool(
            coverage["min_reaches_or_below_low"] and coverage["max_reaches_or_above_high"]
        )
    return {
        "name": name,
        "axis": ["x", "y", "z"][axis],
        "target_m": target,
        "tolerance_m": tolerance,
        "point_count": int(len(selected)),
        "coordinate_min_m": actual_low,
        "coordinate_max_m": actual_high,
        "tangent_axes": ["x", "y", "z"][tangent_axes[0]] + "," + ["x", "y", "z"][tangent_axes[1]],
        "tangent_unique_counts": {"first": int(len(tangent_a)), "second": int(len(tangent_b))},
        "tangent_steps_m": {"first": _steps(selected[:, tangent_axes[0]]) if len(selected) else {"min_m": None, "max_m": None},
                             "second": _steps(selected[:, tangent_axes[1]]) if len(selected) else {"min_m": None, "max_m": None}},
        "finite_rectangle_coverage": coverage,
    }


def _plane_specs() -> list[dict[str, Any]]:
    # All five outer closed faces are emitted by the actual `all^top` source;
    # the open top z=1.0 face is intentionally absent from this list.
    return [
        {"name": "outer_x_low", "axis": 0, "target": 0.0, "tangent": (1, 2), "low": (-0.005, -0.005), "high": (1.005, 1.0)},
        {"name": "outer_x_high", "axis": 0, "target": 3.23, "tangent": (1, 2), "low": (-0.005, -0.005), "high": (1.005, 1.0)},
        {"name": "outer_y_low", "axis": 1, "target": -0.005, "tangent": (0, 2), "low": (0.0, -0.005), "high": (3.23, 1.0)},
        {"name": "outer_y_high", "axis": 1, "target": 1.005, "tangent": (0, 2), "low": (0.0, -0.005), "high": (3.23, 1.0)},
        {"name": "outer_z_low", "axis": 2, "target": -0.005, "tangent": (0, 1), "low": (0.0, -0.005), "high": (3.23, 1.005)},
        {"name": "separator_x_low", "axis": 0, "target": 1.25, "tangent": (1, 2), "low": (0.34, 0.0), "high": (0.4, 0.7)},
        {"name": "separator_x_high", "axis": 0, "target": 2.05, "tangent": (1, 2), "low": (0.34, 0.0), "high": (0.4, 0.7)},
        {"name": "separator_y_low", "axis": 1, "target": 0.34, "tangent": (0, 2), "low": (1.25, 0.0), "high": (2.05, 0.7)},
        {"name": "separator_y_high", "axis": 1, "target": 0.4, "tangent": (0, 2), "low": (1.25, 0.0), "high": (2.05, 0.7)},
    ]


def _summarize_planes(points: np.ndarray, tolerance: float, *, include_coverage: bool = True) -> dict[str, Any]:
    rows = []
    for spec in _plane_specs():
        rows.append(_plane_summary(
            points, axis=spec["axis"], target=spec["target"], tolerance=tolerance,
            tangent_axes=spec["tangent"], name=spec["name"],
            expected_tangent_low=spec["low"] if include_coverage else None,
            expected_tangent_high=spec["high"] if include_coverage else None,
        ))
    by_name = {row["name"]: row for row in rows}
    return {
        "planes": rows,
        "outer_five_point_counts": {name: by_name[name]["point_count"] for name in (
            "outer_x_low", "outer_x_high", "outer_y_low", "outer_y_high", "outer_z_low")},
        "outer_five_nonempty": all(by_name[name]["point_count"] > 0 for name in (
            "outer_x_low", "outer_x_high", "outer_y_low", "outer_y_high", "outer_z_low")),
    }


def _native_domain(metadata: dict[str, str], positions: np.ndarray, fixed_count: int, h: float) -> dict[str, Any]:
    def vector(name: str) -> list[float] | None:
        raw = metadata.get(name)
        if raw is None:
            return None
        try:
            values = [float(x) for x in raw.split(",")]
        except ValueError:
            return None
        return values if len(values) == 3 else None
    fixed = positions[:fixed_count]
    particle_low = positions.min(axis=0)
    particle_high = positions.max(axis=0)
    case_low = vector("CasePosMin")
    case_high = vector("CasePosMax")
    map_low = vector("MapPosMin")
    map_high = vector("MapPosMax")
    # If the decoder only exposes one domain pair, preserve the missing pair
    # explicitly rather than deriving it from a default percentage.
    margins = None
    if map_low is not None and map_high is not None and case_low is not None and case_high is not None:
        margins = {
            "low_m": [float(case_low[i] - map_low[i]) for i in range(3)],
            "high_m": [float(map_high[i] - case_high[i]) for i in range(3)],
            "low_over_h": [float((case_low[i] - map_low[i]) / h) for i in range(3)],
            "high_over_h": [float((map_high[i] - case_high[i]) / h) for i in range(3)],
        }
    return {
        "decoded_case_pos_min_m": case_low,
        "decoded_case_pos_max_m": case_high,
        "decoded_map_pos_min_m": map_low,
        "decoded_map_pos_max_m": map_high,
        "particle_bounds_m": [particle_low.tolist(), particle_high.tolist()],
        "fixed_particle_bounds_m": [fixed.min(axis=0).tolist(), fixed.max(axis=0).tolist()] if len(fixed) else None,
        "kernel_h_m": h,
        "domain_margin_relative_to_h": margins,
        "kernel_padding_check": {
            "status": "pass" if margins is not None and all(v >= 1.0 for v in margins["low_over_h"] + margins["high_over_h"]) else "not_proven",
            "criterion": "each decoded simulation-map margin from CasePosMin/Max is at least one h; no default-domain inference is used",
            "margin_available": margins is not None,
        },
    }


def audit(*, gencase_root: Path, decoder: Path, output: Path) -> dict[str, Any]:
    gencase_root = gencase_root.resolve()
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    generated_xml = next(gencase_root.glob("*.xml"))
    generated_bi4 = next(gencase_root.glob("*.bi4"))
    generated_out = next(gencase_root.glob("*.out"))
    bound_vtk = next(gencase_root.glob("*_Bound.vtk"))
    fluid_vtk = next(gencase_root.glob("*_Fluid.vtk"))
    hdp_vtk = next(gencase_root.glob("*_hdp_Actual.vtk"))
    text = generated_out.read_text(errors="replace")
    bound_vtk_points = read_binary_vtk_points(bound_vtk)
    fluid_vtk_points = read_binary_vtk_points(fluid_vtk)
    hdp_vtk_points = read_binary_vtk_points(hdp_vtk)
    generated_root = ET.parse(generated_xml).getroot()
    particles = generated_root.find(".//particles")
    if particles is None:
        raise ValueError("generated XML has no particles")
    total_xml = int(particles.get("np", "-1"))
    boundary_xml = int(particles.get("nb", "-1"))
    fluid_xml = sum(int(node.get("count", "0")) for node in particles.findall("fluid"))
    data2d = int(_number(r"<data2d value=\"([01])\"", generated_xml.read_text(errors="replace"), "data2d", int))
    h = float(generated_root.find(".//constants/dp").get("value")) * 2.0
    with tempfile.TemporaryDirectory(prefix="f1-boundary-decode-") as temp:
        decoded_prefix = Path(temp) / "native"
        metadata, particle_info, particle_dir = _decode_bi4(generated_bi4, decoder, decoded_prefix)
        ids, native_positions, normals = _read_native_arrays(particle_dir)
        fixed_count = int(float(metadata.get("CaseNfixed", boundary_xml)))
        fluid_count = int(float(metadata.get("CaseNfluid", fluid_xml)))
        native_plane = _summarize_planes(native_positions[:fixed_count], PLANE_TOLERANCE_NATIVE_M)
        domain = _native_domain(metadata, native_positions, fixed_count, h)
        native = {
            "decoder_sha256": sha256(decoder),
            "decoded_xml_metadata": metadata,
            "particle_info": particle_info,
            "decoded_particle_directory": particle_dir.name,
            "id_count": int(len(ids)),
            "ids_unique": bool(len(np.unique(ids)) == len(ids)),
            "ids_min_max": [int(ids.min()), int(ids.max())] if len(ids) else None,
            "fixed_count": fixed_count,
            "fluid_count": fluid_count,
            "mass_fluid_kg": float(metadata.get("MassFluid", "nan")),
            "fixed_normals_count": int(len(normals)) if normals is not None else 0,
            "fixed_normals_finite": bool(normals is not None and np.isfinite(normals).all()),
            "boundary_plane_summary": native_plane,
            "domain": domain,
        }
    generated_plane = _summarize_planes(bound_vtk_points, PLANE_TOLERANCE_VTK_M)
    report = {
        "schema": SCHEMA,
        "case_id": generated_xml.stem,
        "physical_case_id": "F1_DUAL_FINITE_CENTER_QUADRATURE",
        "claim_boundary": "Initial native boundary coverage and decoded simulation-domain padding only; no solver, Q-N, or production qualification.",
        "source_hashes": {
            "generated_xml": sha256(generated_xml),
            "generated_bi4": sha256(generated_bi4),
            "generated_out": sha256(generated_out),
            "bound_vtk": sha256(bound_vtk),
            "fluid_vtk": sha256(fluid_vtk),
            "hdp_vtk": sha256(hdp_vtk),
            "decoder": sha256(decoder),
        },
        "generated_gencase": {
            "data2d": data2d,
            "total_particles_xml": total_xml,
            "boundary_particles_xml": boundary_xml,
            "fluid_particles_xml": fluid_xml,
            "fluid_vtk_points": int(len(fluid_vtk_points)),
            "bound_vtk_points": int(len(bound_vtk_points)),
            "hdp_vtk_points": int(len(hdp_vtk_points)),
            "bound_bounds_m": [bound_vtk_points.min(axis=0).tolist(), bound_vtk_points.max(axis=0).tolist()],
            "fluid_bounds_m": [fluid_vtk_points.min(axis=0).tolist(), fluid_vtk_points.max(axis=0).tolist()],
            "boundary_plane_summary": generated_plane,
        },
        "native_bi4": native,
        "checks": {
            "actual_3d": data2d == 0,
            "gencase_counts_match_native_metadata": total_xml == int(native["decoded_xml_metadata"].get("CaseNp", total_xml)) and boundary_xml == native["fixed_count"] and fluid_xml == native["fluid_count"],
            "native_identity_axis_unique": native["ids_unique"],
            "all_outer_five_generated_planes_nonempty": generated_plane["outer_five_nonempty"],
            "all_outer_five_native_planes_nonempty": native["boundary_plane_summary"]["outer_five_nonempty"],
            "native_domain_kernel_padding_proven": native["domain"]["kernel_padding_check"]["status"] == "pass",
        },
        "limitations": [
            "Plane counts classify the exact declared physical planes in generated Bound.vtk and the fixed prefix of decoded BI4; layered boundary particles away from each plane are retained in bounds but not counted as on-plane.",
            "The open top face is intentionally excluded from the five closed-face gate.",
            "This does not prove solver-time wall penetration, event coverage, Q-N, or production status.",
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
    args = parser.parse_args()
    report = audit(gencase_root=args.gencase_root, decoder=args.decoder, output=args.output)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if all(report["checks"].values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
