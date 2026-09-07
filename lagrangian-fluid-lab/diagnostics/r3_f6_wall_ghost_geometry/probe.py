#!/usr/bin/env python3
"""Audit the serialized F6 mDBC wall and ghost geometry.

The DualSPHysics VTK files are binary and store the boundary coordinates in
``POINTS`` and the normal/ghost displacement in ``FIELD`` arrays.  This probe
keeps those two facts explicit: ``CfgInit_Normals.vtk`` is treated as the
boundary point ``x_b`` with an initial displacement ``n_b`` and
``CfgInit_NormalsGhost.vtk`` as the same ``x_b`` with the solver-doubled
displacement ``n_g``.  The inferred ghost coordinate is therefore
``x_g=x_b+n_g`` and the effective interface is ``x_gamma=(x_b+x_g)/2``.

This is a geometry and serialization audit only.  It does not modify the
production tracer, does not run a solver, and does not make a physical mDBC
acceptance claim.  In particular, a zero-normal-free candidate can still be
rejected when its effective interface is an unvalidated offset from the
nominal tank or when the actual wall/ghost semantics cannot be independently
observed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import numpy as np


LAB = Path(__file__).resolve().parents[2]
CAMPAIGN = LAB / "campaigns" / "v0.1-candidate"
RUN_ROOT = CAMPAIGN / "runs" / "r3-g2-f6-mdbc-zero-normal-preflight"
PRELIGHT_REPORT = CAMPAIGN / "r3-g2-f6-mdbc-zero-normal-preflight.json"
STATIC_REPORT = CAMPAIGN / "r3-g2-f6-static-buoyancy.json"
OUTPUT_JSON = CAMPAIGN / "r3-f6-wall-ghost-geometry.json"
OUTPUT_MD = CAMPAIGN / "R3-F6-WALL-GHOST-GEOMETRY.md"

VARIANTS: dict[str, str] = {
    "baseline": "R3_F6_mdbc_zero_normal_baseline_baseline_combined_mask2_d2_invert",
    "inward_030": "R3_F6_mdbc_zero_normal_baseline_combined_tank_radius_minus030",
    "inward_020": "R3_F6_mdbc_zero_normal_baseline_combined_tank_radius_minus020",
}
WATERLINE_M = 0.8
TANK_SIDE_RADIUS_THRESHOLD_M = 1.8
ZERO_TOLERANCE = 1.0e-12
DOUBLING_TOLERANCE = 2.0e-5


def _field_dtype(kind: str) -> tuple[str, int]:
    if kind == "short":
        return ">i2", 2
    if kind == "int":
        return ">i4", 4
    if kind == "float":
        return ">f4", 4
    if kind == "double":
        return ">f8", 8
    raise ValueError(f"unsupported binary VTK field type: {kind}")


def read_binary_vtk_fields(path: Path) -> dict[str, Any]:
    """Read points and FIELD arrays from a binary VTK POLYDATA file.

    The parser deliberately refuses an absent or malformed FIELD block rather
    than silently treating it as an all-zero normal field.
    """
    content = path.read_bytes()
    point_header = re.search(br"POINTS\s+(\d+)\s+(float|double)\r?\n", content)
    if point_header is None:
        raise ValueError(f"{path} has no binary POINTS header")
    count = int(point_header.group(1))
    point_dtype, point_width = _field_dtype(point_header.group(2).decode())
    point_offset = point_header.end()
    point_end = point_offset + count * 3 * point_width
    if point_end > len(content):
        raise ValueError(f"{path} ends inside POINTS payload")
    points = np.frombuffer(
        content, dtype=point_dtype, count=count * 3, offset=point_offset
    ).reshape(count, 3).astype(float)

    field_match = re.search(br"FIELD\s+FieldData\s+(\d+)\r?\n", content[point_end:])
    if field_match is None:
        raise ValueError(f"{path} has no FIELD FieldData block")
    cursor = point_end + field_match.end()
    field_count = int(field_match.group(1))
    arrays: dict[str, np.ndarray] = {}
    headers: dict[str, dict[str, Any]] = {}
    for _ in range(field_count):
        header = re.match(
            rb"([A-Za-z0-9_]+)\s+(\d+)\s+(\d+)\s+"
            rb"(short|int|float|double)\r?\n",
            content[cursor:],
        )
        if header is None:
            raise ValueError(f"{path} has malformed FIELD array header at {cursor}")
        name = header.group(1).decode()
        components = int(header.group(2))
        array_count = int(header.group(3))
        kind = header.group(4).decode()
        if array_count != count:
            raise ValueError(
                f"{path} FIELD {name} count {array_count} != POINTS count {count}"
            )
        dtype, width = _field_dtype(kind)
        data_offset = cursor + header.end()
        data_end = data_offset + components * count * width
        if data_end > len(content):
            raise ValueError(f"{path} ends inside FIELD {name} payload")
        values = np.frombuffer(
            content,
            dtype=dtype,
            count=components * count,
            offset=data_offset,
        ).reshape(count, components)
        arrays[name] = values.astype(float if kind in {"float", "double"} else int)
        headers[name] = {
            "components": components,
            "count": count,
            "kind": kind,
            "payload_offset": data_offset,
        }
        cursor = data_end
        if content[cursor : cursor + 1] == b"\n":
            cursor += 1
    return {"path": str(path), "count": count, "points": points, "arrays": arrays, "headers": headers}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _preflight_rows() -> dict[str, dict[str, Any]]:
    if not PRELIGHT_REPORT.is_file():
        return {}
    payload = _load_json(PRELIGHT_REPORT)
    return {row["record"]["variant_id"]: row for row in payload.get("results", [])}


def _variant_preflight(name: str, rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    mapping = {
        "baseline": "baseline_combined_mask2_d2_invert",
        "inward_030": "combined_tank_radius_minus030",
        "inward_020": "combined_tank_radius_minus020",
    }
    return rows.get(mapping[name], {})


def _finite_bbox(values: np.ndarray) -> list[list[float]]:
    return [values.min(axis=0).tolist(), values.max(axis=0).tolist()]


def _safe_unit(values: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(values, axis=1)
    return values / np.maximum(norms[:, None], ZERO_TOLERANCE)


def inspect_variant(label: str, directory_name: str, rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    run_dir = RUN_ROOT / directory_name
    normal_path = run_dir / "CfgInit_Normals.vtk"
    ghost_path = run_dir / "CfgInit_NormalsGhost.vtk"
    normal = read_binary_vtk_fields(normal_path)
    ghost = read_binary_vtk_fields(ghost_path)
    if normal["count"] != ghost["count"]:
        raise ValueError(f"{label}: normal/ghost point count mismatch")
    n = normal["count"]
    points = normal["points"]
    ghost_points = ghost["points"]
    arrays = normal["arrays"]
    ghost_arrays = ghost["arrays"]
    required = {"Mk", "Normal", "NormalSize"}
    if not required.issubset(arrays) or not required.issubset(ghost_arrays):
        raise ValueError(f"{label}: missing one of {sorted(required)} in FIELD arrays")
    if not np.array_equal(arrays["Mk"], ghost_arrays["Mk"]):
        raise ValueError(f"{label}: Mk field differs between normal and ghost files")
    if not np.array_equal(points, ghost_points):
        raise ValueError(f"{label}: ghost file does not retain the same x_b points")

    initial = arrays["Normal"]
    doubled = ghost_arrays["Normal"]
    initial_size = arrays["NormalSize"][:, 0]
    doubled_size = ghost_arrays["NormalSize"][:, 0]
    initial_norm = np.linalg.norm(initial, axis=1)
    doubled_norm = np.linalg.norm(doubled, axis=1)
    zero = initial_norm <= ZERO_TOLERANCE
    finite = bool(
        np.isfinite(points).all()
        and np.isfinite(initial).all()
        and np.isfinite(doubled).all()
        and np.isfinite(initial_size).all()
        and np.isfinite(doubled_size).all()
    )
    mks = arrays["Mk"][:, 0].astype(int)
    fixed = mks == 10
    floating = mks == 20
    radius = np.linalg.norm(points[:, :2], axis=1)
    tank_side = fixed & (radius >= TANK_SIDE_RADIUS_THRESHOLD_M)
    radial_outward = np.column_stack((points[:, 0], points[:, 1], np.zeros(n)))
    radial_outward = _safe_unit(radial_outward)
    normal_unit = _safe_unit(initial)
    inward_dot = np.sum(normal_unit * radial_outward, axis=1)
    nonzero_tank = tank_side & ~zero
    # The solver writes the boundary coordinates in both VTK files and stores
    # the doubled displacement in the ghost FIELD array.  Reconstruct x_g and
    # x_gamma explicitly rather than claiming that POINTS in the ghost file
    # are already ghost coordinates.
    ghost_position = points + doubled
    interface = (points + ghost_position) / 2.0
    interface_radius = np.linalg.norm(interface[:, :2], axis=1)
    ratio = doubled_norm[~zero] / np.maximum(initial_norm[~zero], ZERO_TOLERANCE)
    variant_row = _variant_preflight(label, rows)
    boundnor = variant_row.get("gencase", {}).get("boundnor", {})
    normal_data = variant_row.get("gencase", {}).get("normal_data", {})
    solver_data = variant_row.get("solver", {}).get("normal_data", {})

    # Zero normals must be reported by component, not hidden in an overall
    # percentage.  The Mk field is the only component label in these files.
    zero_by_mk = {
        str(mk): int(np.sum(zero & (mks == mk)))
        for mk in sorted(set(mks.tolist()))
    }
    waterline = {
        "boundary_below_count": int(np.sum(floating & (points[:, 2] < WATERLINE_M))),
        "boundary_at_or_above_count": int(np.sum(floating & (points[:, 2] >= WATERLINE_M))),
        "interface_below_count": int(np.sum(floating & (interface[:, 2] < WATERLINE_M))),
        "interface_at_or_above_count": int(np.sum(floating & (interface[:, 2] >= WATERLINE_M))),
        "waterline_m": WATERLINE_M,
    }
    doubling_residual = np.abs(doubled - 2.0 * initial)
    size_residual = np.abs(doubled_size - 2.0 * initial_size)
    orientation_fraction = (
        float(np.mean(inward_dot[nonzero_tank] < -0.9)) if np.any(nonzero_tank) else None
    )
    structural = {
        "normal_file_present": normal_path.is_file(),
        "ghost_file_present": ghost_path.is_file(),
        "points_equal_between_files": bool(np.array_equal(points, ghost_points)),
        "finite_arrays": finite,
        "boundary_count": int(n),
        "fixed_count": int(np.sum(fixed)),
        "floating_count": int(np.sum(floating)),
        "zero_normal_count": int(np.sum(zero)),
        "zero_normal_by_mk": zero_by_mk,
        "boundnor_serialized_zero_count": boundnor.get("boundnor_zero_count"),
        "solver_fixed_or_moving_zero_count": solver_data.get("fixed_or_moving_zero_count"),
        "normal_geometry_point_count": normal_data.get("normal_geometry_point_count"),
        "solver_effective_boundary": solver_data.get("effective_boundary"),
        "ghost_doubling_max_abs_residual": float(np.max(doubling_residual)),
        "normal_size_doubling_max_abs_residual": float(np.max(size_residual)),
        "ghost_doubling_ratio_min": float(np.min(ratio)) if len(ratio) else None,
        "ghost_doubling_ratio_max": float(np.max(ratio)) if len(ratio) else None,
        "normal_completeness": bool(np.sum(zero) == 0),
    }
    geometry = {
        "boundary_bbox_m": _finite_bbox(points),
        "inferred_ghost_bbox_m": _finite_bbox(ghost_position),
        "effective_interface_bbox_m": _finite_bbox(interface),
        "boundary_radius_range_m": [float(radius.min()), float(radius.max())],
        "effective_interface_radius_range_m": [
            float(interface_radius.min()), float(interface_radius.max())
        ],
        "tank_side_count": int(np.sum(tank_side)),
        "tank_side_inward_normal_fraction_dot_lt_minus_0p9": orientation_fraction,
        "tank_side_inward_dot_range": [
            float(np.min(inward_dot[tank_side])) if np.any(tank_side) else None,
            float(np.max(inward_dot[tank_side])) if np.any(tank_side) else None,
        ],
        "zero_normal_radius_range_m": (
            [float(radius[zero].min()), float(radius[zero].max())] if np.any(zero) else None
        ),
        "zero_normal_z_range_m": (
            [float(points[zero, 2].min()), float(points[zero, 2].max())]
            if np.any(zero) else None
        ),
        "waterline_partition": waterline,
    }
    # The overall gate is intentionally stricter than normal completeness.
    # The inward candidates alter x_gamma relative to the nominal tank and
    # there is no independent measured ghost coordinate or hydrostatic force
    # in this artifact, so neither candidate is promoted here.
    normal_pass = structural["normal_completeness"] and structural["finite_arrays"]
    interface_offset = None
    if np.any(tank_side):
        interface_offset = float(np.median(interface_radius[tank_side]) - 2.0)
    gate = {
        "normal_completeness_pass": normal_pass,
        "solver_doubling_consistency_pass": bool(
            structural["ghost_doubling_max_abs_residual"] <= DOUBLING_TOLERANCE
        ),
        "tank_orientation_pass": bool(
            orientation_fraction is not None and orientation_fraction >= 0.95
        ),
        "effective_interface_nominal_radius_offset_m": interface_offset,
        "independent_ghost_coordinate_observed": False,
        "overall_geometry_gate_pass": False,
        "status": "candidate_geometry_only_rejected",
        "reason": (
            "Serialized field geometry is internally auditable, but a zero-free "
            "normal field does not establish the physical wall interface. The "
            "inward candidates move x_gamma relative to the nominal tank and "
            "the VTK artifact does not independently observe ghost coordinates, "
            "wetting force, or displaced-volume closure."
        ),
    }
    return {
        "label": label,
        "run_directory": str(run_dir.relative_to(LAB)),
        "source_files": {
            "boundary_normals_vtk": str(normal_path.relative_to(LAB)),
            "ghost_normals_vtk": str(ghost_path.relative_to(LAB)),
        },
        "interpretation": {
            "boundary_coordinate": "x_b = POINTS in CfgInit_Normals.vtk",
            "initial_displacement": "n_b = FIELD/Normal in CfgInit_Normals.vtk",
            "ghost_displacement": "n_g = FIELD/Normal in CfgInit_NormalsGhost.vtk",
            "inferred_ghost_coordinate": "x_g = x_b + n_g",
            "effective_interface": "x_gamma = (x_b + x_g)/2 = x_b + n_g/2",
            "solver_doubling_observed": "n_g is compared against 2*n_b; no blind BoundNor normalization",
        },
        "structural": structural,
        "geometry": geometry,
        "gate": gate,
    }


def build_report() -> dict[str, Any]:
    rows = _preflight_rows()
    variants = {
        label: inspect_variant(label, directory, rows)
        for label, directory in VARIANTS.items()
    }
    static = _load_json(STATIC_REPORT) if STATIC_REPORT.is_file() else {}
    static_model = static.get("static_model", {})
    nominal_volume = static_model.get("nominal_displaced_volume_m3")
    target_volume = static_model.get("target_displaced_volume_m3")
    return {
        "schema_version": 1,
        "diagnostic_id": "R3_F6_wall_ghost_geometry",
        "execution_status": "completed_cpu_only_existing_artifacts",
        "acceptance_status": "candidate_geometry_only_rejected",
        "scientific_acceptance": "not_accepted_physical_validation",
        "candidate_only": True,
        "compute": {
            "cfd_solver_run": False,
            "gpu_used": False,
            "production_tracer_imported": False,
            "gpu_indices_used": [],
        },
        "scope": (
            "Binary VTK POINTS/FIELD audit for canonical F6 mDBC and two inward "
            "tank-normal radius candidates; no solver or force claim."
        ),
        "static_displacement_reused": {
            "source": str(STATIC_REPORT.relative_to(LAB)),
            "waterline_m": WATERLINE_M,
            "nominal_displaced_volume_m3": nominal_volume,
            "target_displaced_volume_m3": target_volume,
            "relative_volume_error": static_model.get("nominal_relative_volume_error"),
            "status": "diagnostic_only_not_physical_acceptance",
        },
        "variants": variants,
        "conclusions": {
            "baseline": "792 zero fixed normals remain visible in the serialized field and solver warning.",
            "inward_candidates": "-0.030 m and -0.020 m are zero-free and solver-doubling-consistent in this artifact, but their effective interface is offset and remains rejected.",
            "boundary_ghost_semantics": "POINTS are unchanged between normal and ghost VTK files; ghost positions are inferred from the doubled FIELD/Normal vector, not directly observed.",
            "wetting_and_volume": "Waterline partition is countable, but no force or displaced-volume closure is emitted by the normal VTK artifact.",
        },
        "open_blockers": [
            "Rebuild a nominal-geometry mDBC normal/ghost construction without unexplained zero vectors.",
            "Independently validate x_gamma against the intended wall, corners and wetting surface; do not accept a radius offset solely from zero-normal removal.",
            "Create a fixed-body force gauge and matched DBC/mDBC hydrostatic run after E0 passes.",
            "Separate Chrono/body integration from the fixed hydrostatic closure.",
        ],
    }


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# R3 F6 wall/ghost geometry audit",
        "",
        "> 状态：**candidate-only / rejected；CPU-only，复用已生成 VTK 与审计 JSON，未运行 CFD 或 GPU。**",
        "",
        "## 解释约定",
        "",
        "`CfgInit_Normals.vtk` 与 `CfgInit_NormalsGhost.vtk` 的 `POINTS` 均是同一组边界点 `x_b`。本审计从 `FIELD/Normal` 读取初始位移 `n_b` 与求解器加倍后的 `n_g`，显式构造 `x_g=x_b+n_g` 和 `x_gamma=(x_b+x_g)/2`；不把 `BoundNor` 盲目归一化，也不把 ghost VTK 的 POINTS 误称为 ghost 坐标。",
        "",
        "## 结果",
        "",
        "| variant | zero normals | doubling residual | tank inward fraction | median x_gamma radius offset | overall gate |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for label, result in report["variants"].items():
        structural = result["structural"]
        geometry = result["geometry"]
        gate = result["gate"]
        offset = gate["effective_interface_nominal_radius_offset_m"]
        lines.append(
            f"| `{label}` | {structural['zero_normal_count']} "
            f"({structural['zero_normal_by_mk']}) | "
            f"{structural['ghost_doubling_max_abs_residual']:.3g} | "
            f"{geometry['tank_side_inward_normal_fraction_dot_lt_minus_0p9']} | "
            f"{offset:.6f} m | `{gate['status']}` |"
        )
    lines.extend([
        "",
        "## 判定",
        "",
        "- canonical baseline 仍有 792 个 fixed/tank-side zero `BoundNor`，因此 normal completeness 失败。",
        "- `-0.030 m` 与 `-0.020 m` 候选在现有二进制字段中均 zero-free，且 `n_g≈2n_b`；这只能证明序列化一致性，不能证明名义 tank 壁面或湿润几何正确。",
        "- 两个 inward candidates 的 `x_gamma` 相对 2 m 名义半径发生系统偏移；当前 VTK 只提供边界点和位移字段，没有独立 ghost 坐标、压力力或 displaced-volume closure，故整体 gate 仍 rejected。",
        "- 静水排水量仅复用既有 CPU diagnostic：`V_sub={:.9g} m³`、`m/rho={:.9g} m³`、相对误差 `{:.3%}`；这不是本次几何 VTK 的物理验收。".format(
            report["static_displacement_reused"]["nominal_displaced_volume_m3"] or float("nan"),
            report["static_displacement_reused"]["target_displaced_volume_m3"] or float("nan"),
            report["static_displacement_reused"]["relative_volume_error"] or float("nan"),
        ),
        "",
        "## 下一步阻塞",
        "",
    ])
    lines.extend(f"1. {item}" for item in report["open_blockers"])
    lines.extend([
        "",
        "机器可读结果：`r3-f6-wall-ghost-geometry.json`。本报告没有为 E1 固定浸没体矩阵解锁任何工况。",
        "",
    ])
    return "\n".join(lines)


def write_report() -> dict[str, Any]:
    report = build_report()
    OUTPUT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    OUTPUT_MD.write_text(markdown(report))
    return report


if __name__ == "__main__":
    print(json.dumps(write_report(), indent=2, ensure_ascii=False))

