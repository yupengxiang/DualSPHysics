"""Generalized F1 ECC thick-boundary initial-state audit for two fine grids.

This additive v3 module keeps the physical ECC source and the accepted coarse
002 boundary-side semantics immutable while parameterizing only the numerical
grid.  It supports exactly DP005 and DP003333333333333333.  Each invocation
materializes a new case prefix, runs only official GenCase and PartVTK through
the shared CPU runner, and audits the resulting double BI4 without loading a
trajectory.  It does not start a solver, GPU, conversion, or Q-N workflow.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
import resource
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np

import ds_data02_f1_eccentric_thick_boundary as base


SCHEMA = "ds02.f1.eccentric-thick-boundary.v3"
VARIANT_ID = "003-generalized-grid"
SCOPE = base._LAB / "campaigns/ds-data-02/families/F1/handoff_20261003/eccentric_thick_boundary_fallback_003"
DEFAULT_TEMPLATE = base.DEFAULT_TEMPLATE
TRAJECTORY_FRAMES = 1601
TRAJECTORY_BYTES_PER_PARTICLE_FRAME = 64


@dataclass(frozen=True)
class Resolution:
    token: str
    dp: float
    counts_xyz: tuple[int, int, int]

    @property
    def fluid_particles(self) -> int:
        return math.prod(self.counts_xyz)

    @property
    def fluid_mass_kg(self) -> float:
        return base.EXPECTED_MASS

    @property
    def case_id(self) -> str:
        return f"F1_ECC_THICK_BOUNDARY_DBC_V3_{self.token}"

    @property
    def trajectory_bytes_estimate(self) -> int:
        # This is an uncompressed upper planning bound for all typed particles;
        # gzip HDF5 size is deliberately not guessed as a qualification fact.
        fixed = _support_count_estimate(self.dp)
        return (fixed + self.fluid_particles) * TRAJECTORY_FRAMES * TRAJECTORY_BYTES_PER_PARTICLE_FRAME


def _resolution(token: str) -> Resolution:
    rows = {
        "DP005": Resolution("DP005", 0.005, (80, 134, 60)),
        "DP003333333333333333": Resolution("DP003333333333333333", 0.003333333333333333, (120, 201, 90)),
    }
    try:
        spec = rows[token]
    except KeyError as error:
        raise ValueError(f"unsupported F1 ECC v3 resolution: {token}") from error
    for length, count in zip(base.FLUID_SIZE, spec.counts_xyz):
        if not math.isclose(length, count * spec.dp, rel_tol=0, abs_tol=2e-12):
            raise ValueError(f"{token} does not exactly tile frozen fluid extent {length}")
    return spec


def _all_resolutions() -> tuple[Resolution, ...]:
    return (_resolution("DP005"), _resolution("DP003333333333333333"))


def _internal_obstacle_slabs(dp: float) -> dict[str, dict[str, list[float]]]:
    lo = np.asarray(base.OBSTACLE_LOW, dtype=float)
    hi = lo + np.asarray(base.OBSTACLE_SIZE, dtype=float)
    half = 0.5 * dp
    thickness = 2.0 * dp
    tangent_low = lo + half
    tangent_high = hi - half
    return {
        "x_low": {"point": [lo[0] + half, tangent_low[1], tangent_low[2]], "size": [thickness, tangent_high[1] - tangent_low[1], tangent_high[2] - tangent_low[2]]},
        "x_high": {"point": [hi[0] - 2.5 * dp, tangent_low[1], tangent_low[2]], "size": [thickness, tangent_high[1] - tangent_low[1], tangent_high[2] - tangent_low[2]]},
        "y_low": {"point": [tangent_low[0], lo[1] + half, tangent_low[2]], "size": [tangent_high[0] - tangent_low[0], thickness, tangent_high[2] - tangent_low[2]]},
        "y_high": {"point": [tangent_low[0], hi[1] - 2.5 * dp, tangent_low[2]], "size": [tangent_high[0] - tangent_low[0], thickness, tangent_high[2] - tangent_low[2]]},
        "z_high": {"point": [tangent_low[0], tangent_low[1], hi[2] - 2.5 * dp], "size": [tangent_high[0] - tangent_low[0], tangent_high[1] - tangent_low[1], thickness]},
    }


def _grid_points(point: list[float], size: list[float], dp: float) -> np.ndarray:
    axes = []
    for low, span in zip(point, size):
        count = int(round(span / dp))
        axes.append(np.linspace(low, low + span, count + 1, dtype=float))
    xx, yy, zz = np.meshgrid(*axes, indexing="ij")
    return np.column_stack((xx.ravel(), yy.ravel(), zz.ravel()))


def _support_count_estimate(dp: float) -> int:
    rows = [_grid_points(slab["point"], slab["size"], dp) for slab in base._slab_geometry(dp).values()]
    rows.extend(_grid_points(slab["point"], slab["size"], dp) for slab in _internal_obstacle_slabs(dp).values())
    # GenCase coalesces points on the common lattice.  Rounding only affects
    # this planning estimate; the actual audit uses decoded Idp/Posd bytes.
    return int(len(np.unique(np.round(np.vstack(rows), 10), axis=0)))


def _replace_geometry(root: ET.Element, spec: Resolution) -> None:
    definition = root.find("./casedef/geometry/definition")
    commands = root.find("./casedef/geometry/commands")
    if definition is None or commands is None:
        raise ValueError("candidate geometry nodes missing")
    dp = spec.dp
    definition.set("dp", base._q(dp))
    definition.set("units_comment", "metres (m)")
    pointref = definition.find("pointref")
    if pointref is None:
        pointref = ET.Element("pointref")
        definition.insert(0, pointref)
    pointref.attrib.update({"x": base._q(dp / 2), "y": base._q(dp / 2), "z": base._q(dp / 2)})
    pointmin = definition.find("pointmin")
    pointmax = definition.find("pointmax")
    if pointmin is None or pointmax is None:
        raise ValueError("ECC source point bounds missing")
    pointmin.attrib.update({"x": base._q(-2.5 * dp), "y": base._q(-2.5 * dp), "z": base._q(-2.5 * dp)})
    pointmax.attrib.update({"x": "2", "y": "1", "z": "1"})
    mainlist = commands.find("mainlist")
    if mainlist is None:
        raise ValueError("ECC source mainlist missing")
    for child in list(mainlist):
        mainlist.remove(child)
    base._element(mainlist, "setshapemode", text="dp | actual | bound")
    base._element(mainlist, "setdrawmode", {"mode": "full"})
    base._element(mainlist, "setmkbound", {"mk": "0"})
    for name, slab in base._slab_geometry(dp).items():
        base._drawbox(mainlist, f"v3 thick outer support {name}; external solid layers only", "solid", slab["point"], slab["size"])
    base._element(mainlist, "setmkvoid")
    base._drawbox(mainlist, "frozen ECC obstacle physical solid; continuous geometry unchanged", "solid", base.OBSTACLE_LOW, base.OBSTACLE_SIZE)
    base._element(mainlist, "setmkbound", {"mk": "1"})
    for name, slab in _internal_obstacle_slabs(dp).items():
        base._drawbox(mainlist, f"v3 thick obstacle support {name}; internal solid layers only", "solid", slab["point"], slab["size"])
    base._element(mainlist, "setmkfluid", {"mk": "0"})
    base._drawbox(mainlist, "v3 exact ECC fluid cell centres; one native particle per dp^3 cell", "solid", [dp / 2] * 3, [base.FLUID_SIZE[i] - dp for i in range(3)])


def _native_support_bounds(dp: float) -> tuple[np.ndarray, np.ndarray]:
    tank_hi = np.asarray(base.TANK_LOW) + np.asarray(base.TANK_SIZE)
    return np.asarray(base.TANK_LOW, dtype=float) - 2.5 * dp, tank_hi + 2.5 * dp


def materialize_case(spec: Resolution, template: Path, output_root: Path) -> dict[str, Any]:
    source = base.inspect_source(template.resolve())
    root = ET.parse(template).getroot()
    _replace_geometry(root, spec)
    base._set_parameter(root, "SavePosDouble", "1")
    base._set_parameter(root, "Boundary", "1")
    output_root = output_root.resolve()
    case_dir = output_root / "definitions" / spec.case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    definition = case_dir / f"{spec.case_id}_Def.xml"
    ET.ElementTree(root).write(definition, encoding="utf-8", xml_declaration=True)
    support_low, support_high = _native_support_bounds(spec.dp)
    metadata = {
        "schema": SCHEMA,
        "family_id": base.FAMILY_ID,
        "mechanism_id": base.MECHANISM_ID,
        "case_id": spec.case_id,
        "variant_id": VARIANT_ID,
        "resolution_token": spec.token,
        "physical_case_id": "F1_ECCENTRIC_THICK_BOUNDARY_DBC",
        "status": "static_recipe_pending_bounded_cpu_gencase",
        "qualification_claim": "none",
        "q_n_status": "not_assessed",
        "production_claim": "none",
        "claim_boundary": "Independent v3 initial-state audit only; no solver/GPU/Q-N/production claim.",
        "source_binding": source,
        "physical_binding": {
            "physical_hash": source["physical_hash"],
            "payload": source["physical_payload"],
            "continuous_fluid_mass_kg": spec.fluid_mass_kg,
            "mass_normalization": "forbidden",
            "boundary_method": "DBC",
            "normals": False,
            "coarse_precedent": "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/F1_ECC_THICK_BOUNDARY_DBC_DP010/f1-ecc-thick-boundary-internal-dp010-preflight-002/native-audit.json",
        },
        "numeric_binding": {
            "dp_m": spec.dp,
            "pointref_m": [spec.dp / 2] * 3,
            "pointmin_m": [-2.5 * spec.dp] * 3,
            "pointmax_m": [2.0, 1.0, 1.0],
            "outer_support_side": "outside tank continuous faces",
            "outer_support_layers": 3,
            "outer_support_slabs": base._slab_geometry(spec.dp),
            "obstacle_support_side": "inside obstacle continuous solid",
            "obstacle_support_layers": 3,
            "obstacle_support_slabs": _internal_obstacle_slabs(spec.dp),
            "obstacle_continuous_low_m": list(base.OBSTACLE_LOW),
            "obstacle_continuous_high_m": [base.OBSTACLE_LOW[i] + base.OBSTACLE_SIZE[i] for i in range(3)],
            "fluid_primitive": "boxfill=solid; point=low+0.5dp; size=extent-dp",
            "uses_vdp": False,
            "save_pos_double": True,
            "boundary_parameter": 1,
            "native_expected_support_bounds_m": [support_low.tolist(), support_high.tolist()],
            "trajectory_frames_planned": TRAJECTORY_FRAMES,
            "trajectory_storage_estimate": {
                "bytes_per_particle_frame_guard": TRAJECTORY_BYTES_PER_PARTICLE_FRAME,
                "total_particles_planning_estimate": spec.fluid_particles + _support_count_estimate(spec.dp),
                "uncompressed_upper_bound_bytes": spec.trajectory_bytes_estimate,
                "uncompressed_upper_bound_gib": spec.trajectory_bytes_estimate / 1024**3,
                "meaning": "Planning estimate for all typed particles and 1601 frames; HDF5 compression is measured later, not assumed for qualification.",
            },
        },
        "expected_initial": {
            "counts_xyz": list(spec.counts_xyz),
            "fluid_particles": spec.fluid_particles,
            "fluid_mass_kg": spec.fluid_mass_kg,
            "fluid_center_low_m": [spec.dp / 2] * 3,
            "fluid_center_high_m": [base.FLUID_SIZE[i] - spec.dp / 2 for i in range(3)],
        },
        "hard_gates": [
            "official child receipt returncode=0, Data2D=0, actual total/fluid counts",
            "double BI4 contains Posd.bin and unique contiguous Idp.bin",
            "generated fixed/fluid XML ranges partition Idp exactly",
            f"native fluid count/mass remain {spec.fluid_particles}/{spec.fluid_mass_kg} kg without rescale",
            "actual fixed/fluid bounds lie within generated native padded domain",
            "outer typed fixed positions cover all five faces from outside",
            "obstacle typed fixed positions cover all five faces from inside the continuous solid",
            "every actual obstacle support point lies inside the declared obstacle body",
            "PartVTK initial total equals BI4 total",
        ],
        "preserved_coarse_precedent": {
            "report": "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/F1_ECC_THICK_BOUNDARY_DBC_DP010/f1-ecc-thick-boundary-internal-dp010-preflight-002/native-audit.json",
            "commit": "635511abe1caefe93f30cffdbfa5e17c78b18b0e",
            "interpretation": "Coarse 002 initial contract passed; it does not grant medium/fine or temporal qualification.",
        },
        "definition_path": str(definition.resolve()),
        "definition_sha256": base.sha256(definition),
    }
    metadata_path = case_dir / f"{spec.case_id}.metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False, default=base._json_default) + "\n", encoding="utf-8")
    return {
        "case_id": spec.case_id,
        "variant_id": VARIANT_ID,
        "resolution_token": spec.token,
        "dp_m": spec.dp,
        "counts_xyz": list(spec.counts_xyz),
        "definition": str(definition.resolve()),
        "metadata": str(metadata_path.resolve()),
        "definition_sha256": base.sha256(definition),
        "metadata_sha256": base.sha256(metadata_path),
        "physical_hash": source["physical_hash"],
        "expected_fluid_particles": spec.fluid_particles,
        "expected_fluid_mass_kg": spec.fluid_mass_kg,
        "support_count_estimate": _support_count_estimate(spec.dp),
        "trajectory_bytes_estimate": spec.trajectory_bytes_estimate,
    }


def _internal_face_report(fixed: np.ndarray, dp: float) -> dict[str, Any]:
    lo = np.asarray(base.OBSTACLE_LOW, dtype=float)
    hi = lo + np.asarray(base.OBSTACLE_SIZE, dtype=float)
    specs = [
        ("x_low", 0, lo[0], (lo[1], lo[2]), (hi[1], hi[2])),
        ("x_high", 0, hi[0], (lo[1], lo[2]), (hi[1], hi[2])),
        ("y_low", 1, lo[1], (lo[0], lo[2]), (hi[0], hi[2])),
        ("y_high", 1, hi[1], (lo[0], lo[2]), (hi[0], hi[2])),
        ("z_high", 2, hi[2], (lo[0], lo[1]), (hi[0], hi[1])),
    ]
    result: dict[str, Any] = {}
    for name, axis, plane, tangent_low, tangent_high in specs:
        tangents = [idx for idx in range(3) if idx != axis]
        values = [base._axis_samples(tangent_low[i], tangent_high[i], dp) for i in range(2)]
        aa, bb = np.meshgrid(values[0], values[1], indexing="ij")
        query = np.zeros((aa.size, 3), dtype=float)
        query[:, axis] = plane
        query[:, tangents[0]] = aa.ravel()
        query[:, tangents[1]] = bb.ravel()
        near_all = fixed[np.abs(fixed[:, axis] - plane) <= dp / 2 + 2e-6]
        interior = np.ones(len(near_all), dtype=bool)
        for tangent, low, high in zip(tangents, tangent_low, tangent_high):
            interior &= near_all[:, tangent] >= low + 0.75 * dp - 2e-6
            interior &= near_all[:, tangent] <= high - 0.75 * dp + 2e-6
        near_interior = near_all[interior]
        inward = near_interior[:, axis] > plane + 1e-7 if name.endswith("_low") else near_interior[:, axis] < plane - 1e-7
        fraction = float(np.mean(inward)) if len(inward) else 0.0
        distances = base.cKDTree(near_all).query(query, workers=1)[0] if len(near_all) else np.full(len(query), np.inf)
        radius = math.sqrt(3.0) * dp / 2 + 2e-6
        result[name] = {
            "plane_m": float(plane),
            "near_plane_fixed_points": int(len(near_all)),
            "interior_orientation_points": int(len(near_interior)),
            "inward_orientation_fraction": fraction,
            "surface_samples": int(len(query)),
            "maximum_distance_m": float(distances.max()) if len(distances) else None,
            "uncovered_samples": int(np.count_nonzero(distances > radius)),
            "expected_support_side": "inside_obstacle",
            "covered": bool(len(query) and np.all(distances <= radius) and fraction >= 0.90),
        }
    result["all_obstacle_five_covered"] = all(row["covered"] for row in result.values())
    return result


def _obstacle_points_inside(points: np.ndarray, tolerance: float = 2e-7) -> bool:
    lo = np.asarray(base.OBSTACLE_LOW, dtype=float) - tolerance
    hi = np.asarray(base.OBSTACLE_LOW, dtype=float) + np.asarray(base.OBSTACLE_SIZE, dtype=float) + tolerance
    return bool(len(points) and np.all(points >= lo) and np.all(points <= hi))


def _summary_domain(root: ET.Element) -> tuple[np.ndarray, np.ndarray] | None:
    positions = root.find("./execution/particles/_summary/positions")
    if positions is None:
        return None
    low = np.asarray([float(positions.find("posmin").attrib[axis]) for axis in ("x", "y", "z")])
    high = np.asarray([float(positions.find("posmax").attrib[axis]) for axis in ("x", "y", "z")])
    return low, high


def audit_native(spec: Resolution, case: dict[str, Any], case_root: Path, bi4_dump: Path) -> dict[str, Any]:
    metadata = json.loads(Path(case["metadata"]).read_text(encoding="utf-8"))
    prefix = case_root / spec.case_id
    out_path = prefix.with_suffix(".out")
    xml_path = prefix.with_suffix(".xml")
    bi4_path = prefix.with_suffix(".bi4")
    fluid_vtk = prefix.parent / f"{prefix.name}_Fluid.vtk"
    bound_vtk = prefix.parent / f"{prefix.name}_Bound.vtk"
    partvtk_vtk = case_root / "PartVTK_initial.vtk"
    out_text = out_path.read_text(encoding="utf-8", errors="replace")
    xml_root = ET.parse(xml_path).getroot()
    ranges = base._parse_particle_ranges(xml_path)
    ids, positions, decoder = base._decode_double_bi4(bi4_path, bi4_dump)
    fixed, fluid, typed = base._typed_positions(ids, positions, ranges)
    fluid_vtk_points = base._read_binary_vtk_points(fluid_vtk)
    bound_vtk_points = base._read_binary_vtk_points(bound_vtk)
    partvtk_points = base._read_binary_vtk_points(partvtk_vtk)
    fluid_low = np.asarray([spec.dp / 2] * 3)
    fluid_high = np.asarray([base.FLUID_SIZE[i] - spec.dp / 2 for i in range(3)])
    fluid_finite = bool(np.isfinite(fluid).all())
    fluid_unique = len(np.unique(fluid, axis=0)) == len(fluid)
    fluid_inside = bool(np.all(fluid >= fluid_low - 2e-6) and np.all(fluid <= fluid_high + 2e-6))
    bi4_fluid_sorted = fluid[np.lexsort((fluid[:, 2], fluid[:, 1], fluid[:, 0]))]
    vtk_fluid_sorted = fluid_vtk_points[np.lexsort((fluid_vtk_points[:, 2], fluid_vtk_points[:, 1], fluid_vtk_points[:, 0]))]
    vtk_equal = len(bi4_fluid_sorted) == len(vtk_fluid_sorted) and bool(np.max(np.abs(bi4_fluid_sorted - vtk_fluid_sorted)) <= max(2e-7, spec.dp * 2e-5))
    exact_no_overlap = not bool(base.cKDTree(fluid).query(fixed, workers=1)[0].min() <= 1e-10) if len(fixed) and len(fluid) else True
    coverage_external = base.finite_face_report(fixed, spec.dp)
    coverage_obstacle = _internal_face_report(fixed, spec.dp)
    obstacle_hi = np.asarray(base.OBSTACLE_LOW) + np.asarray(base.OBSTACLE_SIZE)
    obstacle_points = fixed[
        np.all(fixed >= np.asarray(base.OBSTACLE_LOW) - 2e-7, axis=1)
        & np.all(fixed <= obstacle_hi + 2e-7, axis=1)
    ]
    data2d = base._summary_number(out_text, r"Data2D=\[([01])\]")
    gencase_fluid = base._summary_number(out_text, r"Fluid\.+:\s*([0-9,]+)")
    gencase_total = base._summary_number(out_text, r"Total particles:\s*([0-9,]+)")
    massfluid = ranges["massfluid_kg"]
    initial_mass = len(fluid) * float(massfluid) if massfluid is not None else None
    summary_domain = _summary_domain(xml_root)
    pointmin = xml_root.find("./casedef/geometry/definition/pointmin")
    pointmax = xml_root.find("./casedef/geometry/definition/pointmax")
    expected_native_low, expected_native_high = _native_support_bounds(spec.dp)
    actual_low = np.minimum(fixed.min(axis=0), fluid.min(axis=0)) if len(fixed) and len(fluid) else np.full(3, np.inf)
    actual_high = np.maximum(fixed.max(axis=0), fluid.max(axis=0)) if len(fixed) and len(fluid) else np.full(3, -np.inf)
    summary_contains = bool(summary_domain is not None and np.all(actual_low >= summary_domain[0] - 2e-8) and np.all(actual_high <= summary_domain[1] + 2e-8))
    expected_matches_summary = bool(summary_domain is not None and np.allclose(summary_domain[0], expected_native_low, atol=2e-8, rtol=0) and np.allclose(summary_domain[1], expected_native_high, atol=2e-8, rtol=0))
    point_domain_contains = bool(pointmin is not None and pointmax is not None and np.all(expected_native_low >= np.asarray([float(pointmin.attrib[a]) for a in ('x','y','z')]) - 2e-8) and np.all(expected_native_high <= np.asarray([float(pointmax.attrib[a]) for a in ('x','y','z')]) + 2e-8))
    checks = {
        "official_3d": data2d == 0 and ranges["data2d"] == "false",
        "official_summary_counts": gencase_fluid == spec.fluid_particles and gencase_total == len(ids),
        "double_bi4_positions": bool(decoder["posd"]),
        "idp_unique_contiguous": np.array_equal(ids, np.arange(len(ids), dtype=np.uint32)),
        "generated_ranges_partition_ids": typed["fixed_count"] + typed["fluid_count"] == len(ids),
        "exact_fluid_count": len(fluid) == spec.fluid_particles and len(fluid_vtk_points) == spec.fluid_particles,
        "native_mass_kg": massfluid is not None and math.isclose(float(initial_mass), spec.fluid_mass_kg, rel_tol=0, abs_tol=2e-8),
        "fluid_finite_unique": fluid_finite and fluid_unique,
        "fluid_inside_cell_center_envelope": fluid_inside,
        "bi4_fluid_matches_official_fluid_vtk": vtk_equal,
        "fluid_fixed_positions_disjoint": exact_no_overlap,
        "native_summary_domain_contains_actual_bounds": summary_contains,
        "native_summary_domain_matches_expected_padding": expected_matches_summary,
        "declared_point_domain_contains_expected_padding": point_domain_contains,
        "outer_five_face_coverage_from_typed_fixed": coverage_external["all_outer_five_covered"],
        "obstacle_five_face_coverage_from_typed_fixed": coverage_obstacle["all_obstacle_five_covered"],
        "obstacle_support_points_inside_continuous_solid": _obstacle_points_inside(obstacle_points),
        "official_partvtk_total_points": len(partvtk_points) == len(ids),
        "dbc_without_normals": xml_root.find("./casedef/normals") is None,
    }
    child_path = case_root / "gencase-child-receipt.json"
    child = json.loads(child_path.read_text(encoding="utf-8")) if child_path.exists() else {}
    child.update({"variant_id": VARIANT_ID, "resolution_token": spec.token, "obstacle_support_side": "inside_obstacle", "final_audit_status": "pass_initial_native_contract" if all(checks.values()) else "failed_initial_native_contract"})
    child_path.write_text(json.dumps(child, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    child_sha = base.sha256(child_path)
    report = {
        "schema": SCHEMA + ".native-audit",
        "case_id": spec.case_id,
        "variant_id": VARIANT_ID,
        "resolution_token": spec.token,
        "status": "pass_initial_native_contract" if all(checks.values()) else "failed_initial_native_contract",
        "q_n_status": "not_assessed",
        "production_claim": "none",
        "claim_boundary": "Initial GenCase/PartVTK/BI4 only; no solver/GPU/temporal/Q-N/production claim.",
        "actual": {
            "dimension": 3 if checks["official_3d"] else None,
            "total_particles": len(ids), "fluid_particles": len(fluid), "fixed_particles": len(fixed),
            "gencase_fluid_summary": gencase_fluid, "gencase_total_summary": gencase_total,
            "massfluid_kg": massfluid, "initial_fluid_mass_kg": initial_mass,
            "fluid_bounds_m": [fluid.min(axis=0).tolist(), fluid.max(axis=0).tolist()] if len(fluid) else None,
            "fixed_bounds_m": [fixed.min(axis=0).tolist(), fixed.max(axis=0).tolist()] if len(fixed) else None,
            "generated_native_summary_bounds_m": [summary_domain[0].tolist(), summary_domain[1].tolist()] if summary_domain else None,
            "expected_native_support_bounds_m": [expected_native_low.tolist(), expected_native_high.tolist()],
            "partvtk_initial_points": len(partvtk_points), "obstacle_support_fixed_points": int(len(obstacle_points)),
        },
        "typed_identity": typed,
        "coverage_from_actual_double_bi4_fixed_positions": {
            "outer": coverage_external["outer"], "obstacle_inside_v3": coverage_obstacle,
            "all_outer_five_covered": coverage_external["all_outer_five_covered"],
            "all_obstacle_five_covered": coverage_obstacle["all_obstacle_five_covered"],
        },
        "checks": checks,
        "child_gencase_receipt": str(child_path.resolve()),
        "child_gencase_receipt_sha256": child_sha,
        "v1_external_obstacle_check": {
            "coverage": coverage_external["obstacle"],
            "check": coverage_external["all_obstacle_five_covered"],
            "status": "retained_negative_evidence",
            "meaning": "The old external-obstacle interpretation is preserved as negative evidence; v3 requires inside-solid support.",
        },
        "source_hashes": {
            "out": base.sha256(out_path), "generated_xml": base.sha256(xml_path), "bi4": base.sha256(bi4_path),
            "fluid_vtk": base.sha256(fluid_vtk), "bound_vtk": base.sha256(bound_vtk), "partvtk_vtk": base.sha256(partvtk_vtk),
            "metadata": base.sha256(Path(case["metadata"])), "child_gencase_receipt": child_sha,
        },
        "limitations": [
            "Initial GenCase/PartVTK/BI4 geometry only; no solver, temporal lifecycle, transport, Q-N, or production decision.",
            "Open ECC top remains a free surface; no birth or exit ledger is inferred.",
            "Trajectory storage estimate is planning-only until a separate conversion measures actual HDF5 output.",
        ],
    }
    return report


def _usage() -> dict[str, Any]:
    def pack(row: resource.struct_rusage) -> dict[str, Any]:
        return {"user_seconds": row.ru_utime, "system_seconds": row.ru_stime, "max_rss_kib": row.ru_maxrss, "in_block": row.ru_inblock, "out_block": row.ru_oublock}
    return {"self": pack(resource.getrusage(resource.RUSAGE_SELF)), "children": pack(resource.getrusage(resource.RUSAGE_CHILDREN))}


def run_gencase(manifest_path: Path, attempt_root: Path, output_path: Path, gencase: Path, partvtk: Path, bi4_dump: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    case = manifest["case"]
    spec = _resolution(manifest["resolution_token"])
    attempt_root.mkdir(parents=True, exist_ok=True)
    case_root = attempt_root / spec.case_id
    case_root.mkdir(parents=True, exist_ok=True)
    prefix = case_root / spec.case_id
    started = time.monotonic()
    before = _usage()
    gencase_log = case_root / "GenCase.stdout.log"
    command = [str(gencase), str(Path(case["definition"]).with_suffix("")), str(prefix), "-save:all", "-threads:4"]
    with gencase_log.open("wb") as stream:
        gencase_result = subprocess.run(command, cwd=gencase.parent, stdout=stream, stderr=subprocess.STDOUT, check=False)
    if gencase_result.returncode != 0:
        raise RuntimeError(f"official GenCase failed with {gencase_result.returncode}; see {gencase_log}")
    out_path = prefix.with_suffix(".out")
    xml_path = prefix.with_suffix(".xml")
    ranges = base._parse_particle_ranges(xml_path)
    out_text = out_path.read_text(encoding="utf-8", errors="replace")
    child = {
        "schema": SCHEMA + ".gencase-child-receipt",
        "case_id": spec.case_id, "resolution_token": spec.token, "status": "completed", "returncode": 0,
        "solver_dimension_from_gencase": 3 if base._summary_number(out_text, r"Data2D=\[([01])\]") == 0 else 2,
        "dimension": 3 if base._summary_number(out_text, r"Data2D=\[([01])\]") == 0 else 2,
        "total_particles": base._summary_number(out_text, r"Total particles:\s*([0-9,]+)"),
        "fluid_particles": base._summary_number(out_text, r"Fluid\.+:\s*([0-9,]+)"),
        "fixed_particles": ranges["fixed_count"], "gencase_out": str(out_path.resolve()),
        "gencase_out_sha256": base.sha256(out_path), "generated_xml_sha256": base.sha256(xml_path),
        "native_bi4": str(prefix.with_suffix(".bi4").resolve()), "native_bi4_sha256": base.sha256(prefix.with_suffix(".bi4")),
        "resource_note": "Official child receipt; no scientific status is inferred from parent stdout regex.",
    }
    child_path = case_root / "gencase-child-receipt.json"
    child_path.write_text(json.dumps(child, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    partvtk_path = case_root / "PartVTK_initial.vtk"
    partvtk_log = case_root / "PartVTK.stdout.log"
    partvtk_command = [str(partvtk), "-filedata", str(prefix.with_suffix(".bi4")), "-filexml", str(prefix.with_suffix(".xml")), "-savevtk", str(partvtk_path), "-threads:4"]
    with partvtk_log.open("wb") as stream:
        partvtk_result = subprocess.run(partvtk_command, cwd=partvtk.parent, stdout=stream, stderr=subprocess.STDOUT, check=False)
    if partvtk_result.returncode != 0:
        raise RuntimeError(f"official PartVTK failed with {partvtk_result.returncode}; see {partvtk_log}")
    report = audit_native(spec, case, case_root, bi4_dump)
    report.update({
        "manifest": str(manifest_path.resolve()), "manifest_sha256": base.sha256(manifest_path),
        "attempt_root": str(attempt_root.resolve()), "official_gencase": str(gencase.resolve()),
        "official_partvtk": str(partvtk.resolve()), "elapsed_seconds": time.monotonic() - started,
        "resource_usage": {"before": before, "after": _usage()},
        "child_processes_include_official_gencase_and_partvtk": True, "source_bytes_mutated": False,
    })
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=base._json_default) + "\n", encoding="utf-8")
    return report


def design(output_root: Path, token: str, template: Path = DEFAULT_TEMPLATE) -> dict[str, Any]:
    spec = _resolution(token)
    output_root = output_root.resolve()
    case = materialize_case(spec, template.resolve(), output_root)
    manifest = {
        "schema": SCHEMA + ".manifest", "family_id": base.FAMILY_ID, "mechanism_id": base.MECHANISM_ID,
        "physical_case_id": "F1_ECCENTRIC_THICK_BOUNDARY_DBC", "variant_id": VARIANT_ID,
        "resolution_token": spec.token, "dp_m": spec.dp, "counts_xyz": list(spec.counts_xyz),
        "claim_boundary": "static v3 candidate; root-approved bounded CPU initial audit only; no solver/GPU/Q-N claim",
        "case": case,
        "recipe": {
            "fluid_particles": spec.fluid_particles, "fluid_mass_kg": spec.fluid_mass_kg,
            "outer_support_side": "outside_tank", "obstacle_support_side": "inside_obstacle",
            "support_layers": 3, "uses_vdp": False,
            "trajectory_frames_planned": TRAJECTORY_FRAMES,
            "trajectory_storage_estimate_bytes": spec.trajectory_bytes_estimate,
            "trajectory_storage_estimate_gib": spec.trajectory_bytes_estimate / 1024**3,
            "trajectory_storage_estimate_basis": "64 bytes per particle-frame planning guard; actual HDF5 compression measured separately",
        },
        "preserved_coarse_002": "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/F1_ECC_THICK_BOUNDARY_DBC_DP010/f1-ecc-thick-boundary-internal-dp010-preflight-002/native-audit.json",
        "no_execution_performed_at_design": True, "q_n_status": "not_assessed",
    }
    path = output_root / f"eccentric-thick-boundary-v3-{spec.token}.manifest.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=base._json_default) + "\n", encoding="utf-8")
    manifest["manifest_path"] = str(path.resolve())
    manifest["manifest_sha256"] = base.sha256(path)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=base._json_default) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_design = sub.add_parser("design")
    p_design.add_argument("--resolution", choices=[spec.token for spec in _all_resolutions()], required=True)
    p_design.add_argument("--output-root", type=Path, default=SCOPE)
    p_design.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    p_run = sub.add_parser("run-gencase")
    p_run.add_argument("--manifest", type=Path, required=True)
    p_run.add_argument("--attempt-root", type=Path, required=True)
    p_run.add_argument("--output", type=Path, required=True)
    p_run.add_argument("--gencase", type=Path, required=True)
    p_run.add_argument("--partvtk", type=Path, required=True)
    p_run.add_argument("--bi4-dump", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "design":
        result = design(args.output_root, args.resolution, args.template)
    else:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        spec = _resolution(manifest["resolution_token"])
        result = run_gencase(args.manifest, args.attempt_root, args.output, args.gencase, args.partvtk, args.bi4_dump)
        result["resolution_token"] = spec.token
    print(json.dumps(result, indent=2, ensure_ascii=False, default=base._json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
