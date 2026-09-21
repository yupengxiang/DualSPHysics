#!/usr/bin/env python3
"""Partition the materialized F2 v4 zero-normal failure, read-only.

This audit consumes only the immutable v4 preflight JSON and generated
``Bound.vtk``.  It has no Definition, BI4, GenCase, decoder, solver, GPU,
queue, ledger, registry, or matrix path and grants no qualification credit.
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

from scripts.r4_f6_mdbc_runtime_zero_normal_audit import _all_vtk_arrays, read_binary_vtk  # noqa: E402

BASE = LAB_ROOT / "campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v4"
PREFLIGHT = BASE / "preflight-v4/preflight.json"
CASE_ID = "F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v4"
BOUND = BASE / "preflight-v4" / f"{CASE_ID}_Bound.vtk"
OUTPUT = BASE / "v4-current-failure-partition-audit-v1.json"
ZERO_TOL = 1.0e-12
DP_M = 0.0075
SCHEMA = "core.f2.submerged_orifice_transfer.v4_current_failure_partition.v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    partial.replace(path)


def _layer_counts(values: np.ndarray, positions: np.ndarray, zero: np.ndarray, axis: int) -> dict[str, Any]:
    offsets = np.rint((positions[:, axis] - positions[:, axis].min()) / DP_M).astype(np.int64)
    return {
        "axis": "xyz"[axis],
        "zero_by_offset": {str(int(k)): int(v) for k, v in sorted(Counter(int(x) for x in offsets[zero]).items())},
        "all_by_offset": {str(int(k)): int(v) for k, v in sorted(Counter(int(x) for x in offsets).items())},
    }


def audit(bound_path: Path = BOUND, preflight_path: Path = PREFLIGHT, output: Path = OUTPUT) -> dict[str, Any]:
    bound_path = Path(bound_path).resolve()
    preflight_path = Path(preflight_path).resolve()
    if not bound_path.is_file() or not preflight_path.is_file():
        raise FileNotFoundError("v4 failure evidence is missing")
    preflight = load(preflight_path)
    if preflight.get("schema") != "core.f2.submerged_orifice_transfer.cpu_native_preflight.v4" or preflight.get("case_id") != CASE_ID:
        raise ValueError("wrong v4 preflight identity")
    if preflight.get("preflight_pass") is not False or preflight.get("matrix_credit") != 0:
        raise ValueError("audit input is not a closed negative result")
    vtk = read_binary_vtk(bound_path)
    arrays = _all_vtk_arrays(vtk)
    required = {"Mk", "Normal", "NormalSize"}
    missing = required.difference(arrays)
    if missing:
        raise ValueError(f"Bound.vtk missing fields: {sorted(missing)}")
    points = np.asarray(vtk["points"], dtype=float)
    mk = np.asarray(arrays["Mk"])
    normals = np.asarray(arrays["Normal"], dtype=float)
    normal_size = np.asarray(arrays["NormalSize"], dtype=float)
    if len(points) != int(preflight["generated_counts"]["boundary_particles"]):
        raise ValueError("Bound.vtk count disagrees with preflight")
    if normals.shape != (len(points), 3) or normal_size.shape != (len(points),):
        raise ValueError("Bound.vtk field shape mismatch")
    if not (np.isfinite(points).all() and np.isfinite(normals).all() and np.isfinite(normal_size).all()):
        raise ValueError("Bound.vtk fields are non-finite")
    norms = np.linalg.norm(normals, axis=1)
    zero = norms <= ZERO_TOL
    if int(zero.sum()) != int(preflight["native_initial"]["zero_boundnor_count"]):
        raise ValueError("zero-normal count disagrees with preflight")
    partitions: list[dict[str, Any]] = []
    for value in sorted(np.unique(mk)):
        selected = mk == value
        part_points = points[selected]
        part_zero = zero[selected]
        part_norms = norms[selected]
        partitions.append({
            "mk": int(value),
            "particle_count": int(selected.sum()),
            "zero_boundnor_count": int(part_zero.sum()),
            "zero_normal_size_count": int((normal_size[selected] <= ZERO_TOL).sum()),
            "zero_fraction": float(part_zero.mean()) if len(part_zero) else 0.0,
            "normal_norm_min_m": float(part_norms.min()) if len(part_norms) else None,
            "normal_norm_max_m": float(part_norms.max()) if len(part_norms) else None,
            "zero_bbox_m": {
                "min": part_points[part_zero].min(axis=0).tolist() if part_zero.any() else None,
                "max": part_points[part_zero].max(axis=0).tolist() if part_zero.any() else None,
            },
            "layers": [_layer_counts(part_points, part_points, part_zero, axis) for axis in range(3)],
        })
    result = {
        "schema": SCHEMA,
        "audit_id": "F2_SUBMERGED_ORIFICE_V4_CURRENT_FAILURE_PARTITION_AUDIT_V1",
        "case_id": CASE_ID,
        "status": "read_only_v4_failure_partition_closed",
        "execution_controls": {
            "preflight_json_read": True,
            "bound_vtk_read": True,
            "definition_read": False,
            "bi4_read": False,
            "gencase_invoked": False,
            "native_decoder_invoked": False,
            "solver_invoked": False,
            "gpu_invoked": False,
            "job_created": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "matrix_submission": False,
        },
        "thresholds": {"dp_m": DP_M, "zero_normal_norm_le_m": ZERO_TOL, "mass_relative_error_max": 0.025},
        "source": {"preflight": ref(preflight_path, "v4 failed preflight"), "bound_vtk": ref(bound_path, "v4 generated Bound.vtk")},
        "global": {
            "boundary_particles": int(len(points)),
            "zero_boundnor_count": int(zero.sum()),
            "zero_normal_size_count": int((normal_size <= ZERO_TOL).sum()),
            "arrays_finite": True,
            "mk_values": [int(x) for x in sorted(np.unique(mk))],
        },
        "mk_partitions": partitions,
        "qualification_claim": "none",
        "matrix_credit": 0,
        "interpretation": {
            "purpose": "identify the next falsifiable geometry/normal hypothesis without rerunning v4",
            "hard_gate_preserved": True,
            "same_input_retry": False,
            "no_route_authorization": True,
        },
    }
    write_json(output, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bound", type=Path, default=BOUND)
    parser.add_argument("--preflight", type=Path, default=PREFLIGHT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    print(json.dumps(audit(args.bound, args.preflight, args.output), indent=2, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
