#!/usr/bin/env python3
"""Read-only partition audit of the existing submerged-orifice Bound.vtk.

This diagnostic consumes only the generated ``*_Bound.vtk`` sidecar already
recorded by the failed anchor.  It does not open the anchor Definition or BI4,
does not invoke the native decoder or GenCase, and never changes the anchor.
The VTK ``Normal``/``NormalSize`` fields are treated as the generated normal
sidecar for a spatial partition by ``Mk`` and incident geometry face.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.r4_f6_mdbc_runtime_zero_normal_audit import (  # noqa: E402
    _all_vtk_arrays,
    read_binary_vtk,
)


SCHEMA = "core.f2.submerged_orifice_transfer.boundnor_partition_audit.v1"
AUDIT_ID = "F2_SUBMERGED_ORIFICE_BOUNDNOR_PARTITION_AUDIT_V1"
CASE_ID = "F2_ORIFICE_q0p50_dp0075_spatial"
DP_M = 0.0075
ZERO_TOLERANCE_M = 1.0e-12
NEAR_ZERO_TOLERANCE_M = 1.0e-8
FACE_TOLERANCE_M = 0.00005
FACE_INCIDENT_LIMIT_M = 1.5 * DP_M + FACE_TOLERANCE_M

DEFAULT_BOUND = (
    LAB_ROOT
    / "campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1"
    / "anchor-q0p5-dp0p0075/generated"
    / f"{CASE_ID}_Bound.vtk"
)
DEFAULT_OUTPUT = (
    LAB_ROOT
    / "campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1"
    / "normal-remediation-v2/generated-boundnor-partition-audit-v1.json"
)


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    partial.replace(path)


def _face_masks(points: np.ndarray, low: np.ndarray, high: np.ndarray,
                faces: tuple[tuple[str, int, float], ...]) -> dict[str, np.ndarray]:
    masks: dict[str, np.ndarray] = {}
    for name, axis, value in faces:
        masks[name] = np.abs(points[:, axis] - value) <= FACE_INCIDENT_LIMIT_M
    return masks


def _face_partition(points: np.ndarray, zero: np.ndarray, low: np.ndarray,
                    high: np.ndarray,
                    faces: tuple[tuple[str, int, float], ...]) -> dict[str, Any]:
    masks = _face_masks(points, low, high, faces)
    incident_count = np.zeros(len(points), dtype=np.int8)
    for mask in masks.values():
        incident_count += mask.astype(np.int8)
    face_rows: dict[str, Any] = {}
    for name, axis, value in faces:
        mask = masks[name]
        offsets = np.rint((points[:, axis] - value) / DP_M).astype(np.int64)
        total_offsets = Counter(int(v) for v in offsets[mask])
        zero_offsets = Counter(int(v) for v in offsets[mask & zero])
        face_rows[name] = {
            "axis": "xyz"[axis],
            "surface_m": value,
            "incident_particles": int(mask.sum()),
            "incident_zero_normals": int((mask & zero).sum()),
            "incident_nonzero_normals": int((mask & ~zero).sum()),
            "offset_layers_dp_total": {str(k): int(v) for k, v in sorted(total_offsets.items())},
            "offset_layers_dp_zero": {str(k): int(v) for k, v in sorted(zero_offsets.items())},
        }
    exclusive = {
        str(count): {
            "particles": int((incident_count == count).sum()),
            "zero_normals": int(((incident_count == count) & zero).sum()),
        }
        for count in range(0, int(incident_count.max(initial=0)) + 1)
    }
    return {
        "face_rows_are_incident_and_can_overlap": True,
        "face_incidence_exclusive_partition": exclusive,
        "faces": face_rows,
    }


def _mk_partition(points: np.ndarray, normals: np.ndarray, normal_size: np.ndarray,
                  mk: np.ndarray, mk_value: int) -> dict[str, Any]:
    selected = mk == mk_value
    p = points[selected]
    n = normals[selected]
    size = normal_size[selected]
    norms = np.linalg.norm(n, axis=1)
    zero = norms <= ZERO_TOLERANCE_M
    near_zero = norms <= NEAR_ZERO_TOLERANCE_M
    if mk_value == 17:
        low = np.array([0.0, 0.0, 0.0])
        high = np.array([1.6, 0.5, 0.8])
        faces = (("x_min", 0, 0.0), ("x_max", 0, 1.6),
                 ("y_min", 1, 0.0), ("y_max", 1, 0.5), ("z_min", 2, 0.0))
        geometry_role = "outer_tank_closed_faces"
    elif mk_value == 18:
        low = np.array([0.72, 0.04, 0.18])
        high = np.array([0.78, 0.46, 0.8])
        faces = (("x_min", 0, 0.72), ("x_max", 0, 0.78),
                 ("y_min", 1, 0.04), ("y_max", 1, 0.46),
                 ("z_min", 2, 0.18), ("z_max", 2, 0.8))
        geometry_role = "upper_gate_slab_all_faces"
    else:
        low = p.min(axis=0)
        high = p.max(axis=0)
        faces = tuple((f"axis_{axis}_{side}", axis, float(value))
                      for axis in range(3)
                      for side, value in (("min", low[axis]), ("max", high[axis])))
        geometry_role = "unregistered_mk"
    zero_points = p[zero]
    return {
        "mk": int(mk_value),
        "geometry_role": geometry_role,
        "particle_count": int(selected.sum()),
        "zero_normal_count": int(zero.sum()),
        "zero_normal_fraction": float(zero.mean()) if len(zero) else 0.0,
        "near_zero_normal_count": int(near_zero.sum()),
        "exact_vector_zero_count": int(np.all(n == 0.0, axis=1).sum()),
        "normal_size_zero_count": int((size <= ZERO_TOLERANCE_M).sum()),
        "normal_norm_min_m": float(norms.min()) if len(norms) else None,
        "normal_norm_max_m": float(norms.max()) if len(norms) else None,
        "zero_bbox_m": {
            "min": zero_points.min(axis=0).tolist() if len(zero_points) else None,
            "max": zero_points.max(axis=0).tolist() if len(zero_points) else None,
        },
        "face_partition": _face_partition(p, zero, low, high, faces),
    }


def audit_bound_vtk(bound_path: Path = DEFAULT_BOUND,
                    output: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    bound_path = Path(bound_path).resolve()
    if not bound_path.is_file():
        raise FileNotFoundError(bound_path)
    vtk = read_binary_vtk(bound_path)
    arrays = _all_vtk_arrays(vtk)
    required = {"Mk", "Normal", "NormalSize"}
    missing = required.difference(arrays)
    if missing:
        raise ValueError(f"Bound.vtk missing required generated fields: {sorted(missing)}")
    points = np.asarray(vtk["points"], dtype=float)
    normals = np.asarray(arrays["Normal"], dtype=float)
    normal_size = np.asarray(arrays["NormalSize"], dtype=float)
    mk = np.asarray(arrays["Mk"])
    if normals.shape != (len(points), 3) or normal_size.shape != (len(points),):
        raise ValueError("generated normal field shapes do not match Bound.vtk POINTS")
    if not (np.isfinite(points).all() and np.isfinite(normals).all() and np.isfinite(normal_size).all()):
        raise ValueError("generated Bound.vtk fields are not finite")
    norm = np.linalg.norm(normals, axis=1)
    partitions = [_mk_partition(points, normals, normal_size, mk, int(value))
                  for value in sorted(np.unique(mk))]
    result = {
        "schema": SCHEMA,
        "audit_id": AUDIT_ID,
        "case_id": CASE_ID,
        "status": "read_only_generated_boundnor_partitioned",
        "input_scope": {
            "bound_vtk_only": True,
            "definition_read": False,
            "bi4_read": False,
            "native_decoder_invoked": False,
            "gencase_invoked": False,
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
        },
        "thresholds": {
            "dp_m": DP_M,
            "zero_normal_norm_le_m": ZERO_TOLERANCE_M,
            "near_zero_normal_norm_le_m": NEAR_ZERO_TOLERANCE_M,
            "face_incident_limit_m": FACE_INCIDENT_LIMIT_M,
            "face_rows_are_incident": True,
        },
        "source": {
            "path": str(bound_path),
            "sha256": sha256(bound_path),
            "bytes": bound_path.stat().st_size,
            "role": "existing failed-anchor generated Bound.vtk Normal/NormalSize sidecar",
        },
        "generated_field_summary": {
            "point_count": int(len(points)),
            "mk_values": [int(value) for value in sorted(np.unique(mk))],
            "global_zero_normal_count": int((norm <= ZERO_TOLERANCE_M).sum()),
            "global_near_zero_normal_count": int((norm <= NEAR_ZERO_TOLERANCE_M).sum()),
            "global_exact_vector_zero_count": int(np.all(normals == 0.0, axis=1).sum()),
            "global_zero_fraction": float(np.mean(norm <= ZERO_TOLERANCE_M)),
            "array_names": sorted(arrays),
        },
        "mk_partitions": partitions,
        "interpretation": {
            "finding": "zero vectors are concentrated in the inner boundary layers for both registered Mk roles; the gate also has zero vectors across its slab edge/inner-layer partition",
            "remediation_basis": "new v2 must put GeometryForNormals at vdp=0 and orient the internal gate shell on the solid side with a void precursor and layers 0,-1,-2",
            "threshold_policy": "zero vectors remain hard failure; no threshold relaxation, survivor renormalization, or same-input retry",
        },
    }
    write_json(output, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bound", type=Path, default=DEFAULT_BOUND)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    result = audit_bound_vtk(args.bound, args.output)
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
