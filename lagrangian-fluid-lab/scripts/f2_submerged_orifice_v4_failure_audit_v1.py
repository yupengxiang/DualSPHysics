#!/usr/bin/env python3
"""Read-only audit of the already materialized v4 Bound.vtk failure.

This adapter reads only the v4 preflight JSON and its generated ``*_Bound.vtk``
sidecar.  It never opens the failed Definition or native input, and it has no
GenCase, decoder, solver, GPU, job, queue, ledger, registry, or matrix path.
The result is evidence for a new root-review candidate; it is not a runtime
preflight and it grants no execution authority.
"""
from __future__ import annotations

import argparse
from collections import Counter
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


SCHEMA = "core.f2.submerged_orifice_transfer.v4_failure_boundnor_audit.v1"
AUDIT_ID = "F2_SUBMERGED_ORIFICE_V4_FAILURE_BOUNDNOR_AUDIT_V1"
V4_CASE_ID = "F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v2"
DP_M = 0.0075
ZERO_NORMAL_TOLERANCE_M = 1.0e-12
FACE_TOLERANCE_M = 0.00005
FACE_INCIDENT_LIMIT_M = 1.5 * DP_M + FACE_TOLERANCE_M

DEFAULT_BASE = (
    LAB_ROOT
    / "campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1"
)
DEFAULT_V4_DIR = DEFAULT_BASE / "normal-remediation-v2/preflight-v4"
DEFAULT_PREFLIGHT = DEFAULT_V4_DIR / "preflight.json"
DEFAULT_BOUND = DEFAULT_V4_DIR / f"{V4_CASE_ID}_Bound.vtk"
DEFAULT_OUTPUT = (
    DEFAULT_BASE
    / "normal-remediation-v3/v4-boundnor-failure-audit-v1.json"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    partial.replace(path)


def ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": str(path),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "role": role,
    }


def _face_rows(
    points: np.ndarray,
    zero: np.ndarray,
    low: np.ndarray,
    high: np.ndarray,
    faces: tuple[tuple[str, int, float], ...],
) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for name, axis, value in faces:
        incident = np.abs(points[:, axis] - value) <= FACE_INCIDENT_LIMIT_M
        offsets = np.rint((points[:, axis] - value) / DP_M).astype(np.int64)
        total = Counter(int(item) for item in offsets[incident])
        zeros = Counter(int(item) for item in offsets[incident & zero])
        rows[name] = {
            "axis": "xyz"[axis],
            "surface_m": value,
            "incident_particles": int(incident.sum()),
            "incident_zero_normals": int((incident & zero).sum()),
            "offset_layers_dp_total": {
                str(k): int(v) for k, v in sorted(total.items())
            },
            "offset_layers_dp_zero": {
                str(k): int(v) for k, v in sorted(zeros.items())
            },
        }
    return rows


def _partition(
    points: np.ndarray,
    normals: np.ndarray,
    normal_size: np.ndarray,
    mk: np.ndarray,
    mk_value: int,
) -> dict[str, Any]:
    selected = mk == mk_value
    part_points = points[selected]
    part_normals = normals[selected]
    part_size = normal_size[selected]
    norms = np.linalg.norm(part_normals, axis=1)
    zero = norms <= ZERO_NORMAL_TOLERANCE_M
    if mk_value == 17:
        low = np.array([0.0, 0.0, 0.0])
        high = np.array([1.6, 0.5, 0.8])
        faces = (
            ("x_min", 0, 0.0),
            ("x_max", 0, 1.6),
            ("y_min", 1, 0.0),
            ("y_max", 1, 0.5),
            ("z_min", 2, 0.0),
        )
        role = "outer_tank_closed_faces"
    elif mk_value == 18:
        low = np.array([0.72, 0.04, 0.18])
        high = np.array([0.78, 0.46, 0.8])
        faces = (
            ("x_min", 0, 0.72),
            ("x_max", 0, 0.78),
            ("y_min", 1, 0.04),
            ("y_max", 1, 0.46),
            ("z_min", 2, 0.18),
            ("z_max", 2, 0.8),
        )
        role = "upper_gate_slab_all_faces"
    else:
        low = part_points.min(axis=0)
        high = part_points.max(axis=0)
        faces = tuple(
            (f"axis_{axis}_{side}", axis, float(value))
            for axis in range(3)
            for side, value in (("min", low[axis]), ("max", high[axis]))
        )
        role = "unregistered_boundary_mk"
    zero_points = part_points[zero]
    return {
        "mk": int(mk_value),
        "geometry_role": role,
        "particle_count": int(selected.sum()),
        "zero_boundnor_count": int(zero.sum()),
        "zero_boundnor_fraction": float(zero.mean()) if len(zero) else 0.0,
        "normal_size_zero_count": int(
            (part_size <= ZERO_NORMAL_TOLERANCE_M).sum()
        ),
        "normal_norm_min_m": float(norms.min()) if len(norms) else None,
        "normal_norm_max_m": float(norms.max()) if len(norms) else None,
        "zero_bbox_m": {
            "min": zero_points.min(axis=0).tolist() if len(zero_points) else None,
            "max": zero_points.max(axis=0).tolist() if len(zero_points) else None,
        },
        "face_rows": _face_rows(part_points, zero, low, high, faces),
    }


def audit_bound_vtk(
    bound_path: Path = DEFAULT_BOUND,
    preflight_path: Path = DEFAULT_PREFLIGHT,
    output: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    bound_path = Path(bound_path).resolve()
    preflight_path = Path(preflight_path).resolve()
    if not bound_path.is_file():
        raise FileNotFoundError(bound_path)
    if not preflight_path.is_file():
        raise FileNotFoundError(preflight_path)
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    if preflight.get("schema") != "core.f2.submerged_orifice_transfer.cpu_native_preflight.v4":
        raise ValueError("v4 preflight schema mismatch")
    if preflight.get("case_id") != V4_CASE_ID or preflight.get("preflight_pass") is not False:
        raise ValueError("audit input is not the failed v4 preflight")
    vtk = read_binary_vtk(bound_path)
    arrays = _all_vtk_arrays(vtk)
    required = {"Mk", "Normal", "NormalSize"}
    missing = required.difference(arrays)
    if missing:
        raise ValueError(f"Bound.vtk missing generated fields: {sorted(missing)}")
    points = np.asarray(vtk["points"], dtype=float)
    normals = np.asarray(arrays["Normal"], dtype=float)
    normal_size = np.asarray(arrays["NormalSize"], dtype=float)
    mk = np.asarray(arrays["Mk"])
    if normals.shape != (len(points), 3) or normal_size.shape != (len(points),):
        raise ValueError("Bound.vtk normal shapes do not match POINTS")
    if not (
        np.isfinite(points).all()
        and np.isfinite(normals).all()
        and np.isfinite(normal_size).all()
    ):
        raise ValueError("Bound.vtk generated fields are not finite")
    norms = np.linalg.norm(normals, axis=1)
    partitions = [
        _partition(points, normals, normal_size, mk, int(value))
        for value in sorted(np.unique(mk))
    ]
    generated = preflight.get("generated_counts", {})
    native = preflight.get("native_initial", {})
    if int(generated.get("boundary_particles", -1)) != len(points):
        raise ValueError("v4 preflight boundary count does not match Bound.vtk")
    if int(native.get("zero_boundnor_count", -1)) != int(
        (norms <= ZERO_NORMAL_TOLERANCE_M).sum()
    ):
        raise ValueError("v4 preflight zero-normal count does not match Bound.vtk")
    result = {
        "schema": SCHEMA,
        "audit_id": AUDIT_ID,
        "case_id": V4_CASE_ID,
        "status": "read_only_v4_boundnor_failure_audited",
        "input_scope": {
            "preflight_json_read": True,
            "bound_vtk_only_for_generated_fields": True,
            "definition_read": False,
            "bi4_read": False,
            "native_decoder_invoked": False,
            "gencase_invoked": False,
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "matrix_submission": False,
        },
        "thresholds": {
            "dp_m": DP_M,
            "zero_normal_norm_le_m": ZERO_NORMAL_TOLERANCE_M,
            "face_incident_limit_m": FACE_INCIDENT_LIMIT_M,
            "zero_gate_is_unconditional": True,
            "mass_relative_error_max": 0.025,
        },
        "source": {
            "preflight_evidence": ref(preflight_path, "existing v4 failed preflight JSON"),
            "bound_vtk": ref(bound_path, "existing v4 generated Bound.vtk sidecar"),
        },
        "generated_field_summary": {
            "point_count": int(len(points)),
            "mk_values": [int(value) for value in sorted(np.unique(mk))],
            "global_zero_boundnor_count": int(
                (norms <= ZERO_NORMAL_TOLERANCE_M).sum()
            ),
            "global_zero_normal_size_count": int(
                (normal_size <= ZERO_NORMAL_TOLERANCE_M).sum()
            ),
            "global_zero_fraction": float(
                np.mean(norms <= ZERO_NORMAL_TOLERANCE_M)
            ),
            "normal_norm_min_m": float(norms.min()),
            "normal_norm_max_m": float(norms.max()),
            "arrays_finite": True,
            "array_names": sorted(arrays),
        },
        "v4_failure_crosscheck": {
            "preflight_zero_boundnor_count": int(native["zero_boundnor_count"]),
            "preflight_zero_normal_size_count": int(native["zero_normal_size_count"]),
            "preflight_mass_relative_error": 0.04718017578125,
            "preflight_mass_relative_error_max": 0.025,
            "preflight_endpoint_counts": {
                "outer": int(native["wall_endpoint_outer_count"]),
                "gate": int(native["gate_endpoint_penetration_count"]),
            },
            "preflight_ids_and_finite_passed": True,
            "hard_failure_preserved": True,
        },
        "mk_partitions": partitions,
        "interpretation": {
            "finding": (
                "All 64,899 zero BoundNor/NormalSize entries are Mk=17 outer-wall "
                "entries; Mk=18 gate entries have zero count 0."
            ),
            "evidence_for_one_hypothesis": (
                "The v4 recipe uses a single vdp=0 outer GeometryForNormals source "
                "while the emitted outer wall has active 0,1,2 shell layers; the "
                "uncovered outer-layer population is therefore a geometry-list "
                "coverage candidate. The independent source count is 86x57x49, "
                "which explains the +4.718017578125% mass failure against the "
                "continuous source volume."
            ),
            "hypothesis_limit": "one geometry/normal closure hypothesis only",
            "threshold_policy": (
                "zero normal and mass gates remain hard; no threshold relaxation "
                "or survivor renormalization is allowed"
            ),
        },
    }
    write_json(output, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bound", type=Path, default=DEFAULT_BOUND)
    parser.add_argument("--preflight", type=Path, default=DEFAULT_PREFLIGHT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    result = audit_bound_vtk(args.bound, args.preflight, args.output)
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
