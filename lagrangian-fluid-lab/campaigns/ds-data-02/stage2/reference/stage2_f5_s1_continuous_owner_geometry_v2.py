#!/usr/bin/env python3
"""Independently close the F5-S1 source-derived continuous fluid region.

The old continuous-geometry scope intentionally left the mass UNKNOWN because
it had not yet bound the GenCase clip-side convention.  The bounded official
clip evidence now records ``n dot (x-p) <= 0`` and the source plane
``0.28*(x-2)-z <= 0``.  This worker recomputes the piecewise-linear volume
from the already-recorded small audit JSON and verifies the analytic integral:

    E = [0.01, 3.43] x [-0.14, 0.14] x [0.01, 0.39]
    E intersect {z >= 0.28*(x-2)}
    volume = 0.287736 m^3, mass(rho=1000) = 287.736 kg.

This closes a *source-derived geometric target*.  It does not turn the old
253.264 kg discrete source sample or the 363.888 kg raw envelope into an owner
target, and it does not grant initial-support or scientific Q credit.  The
generated particle support remains a separate guarded GenCase question; the
existing sample is retained as a hard-fail diagnostic against this region.
No production VTK/BI4/HDF5 is opened and no GenCase/solver is launched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any


SCHEMA = "ds02.stage2.f5-s1.continuous-owner-geometry.v2"
AUDIT_SCHEMA = "ds02.stage2.f5-s1.clipplane-volume-audit.v1"
EVIDENCE_SCHEMA = "ds02.stage2.f5-s1.clipplane-official-evidence-audit.v2"
SCOPE_SCHEMA = "ds02.stage2.f5-s1.continuous-geometry-scope.v2"
MAX_JSON_BYTES = 10 * 1024 * 1024
UNKNOWN_Q = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0}


class GeometryFailure(RuntimeError):
    pass


def _abs(path: Path) -> Path:
    return path.expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    s = path.stat()
    return {"device": int(s.st_dev), "inode": int(s.st_ino), "bytes": int(s.st_size),
            "mtime_ns": int(s.st_mtime_ns), "ctime_ns": int(s.st_ctime_ns)}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise GeometryFailure(f"{label} is not a regular non-symlink file: {path}")
    before = _stat(path)
    if before["bytes"] > MAX_JSON_BYTES:
        raise GeometryFailure(f"{label} exceeds 10 MiB cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise GeometryFailure(f"{label} changed during bounded read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GeometryFailure(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise GeometryFailure(f"{label} must be a JSON object")
    return value, {"path": str(path), "sha256": _sha(raw), "stat": after, "bytes": len(raw)}


def _float(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise GeometryFailure(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise GeometryFailure(f"{label} is non-finite")
    return result


def _close(a: float, b: float, tol: float = 1e-12) -> bool:
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def integrate_clipped_box(low: tuple[float, float, float], high: tuple[float, float, float],
                          normal: tuple[float, float, float], point: tuple[float, float, float]) -> tuple[float, dict[str, Any]]:
    """Return the box volume satisfying n dot (x-point) <= 0.

    The source contract is intentionally narrow: a negative z coefficient is
    required so the retained side is represented as z >= a*x+b.  A different
    plane orientation is an input error, never silently complemented.
    """
    nx, ny, nz = normal
    if abs(ny) > 1e-15 or nz >= 0.0 or abs(nz) <= 1e-15:
        raise GeometryFailure("F5 v2 only accepts the recorded xz plane with negative z normal")
    if not (low[0] < high[0] and low[1] < high[1] and low[2] < high[2]):
        raise GeometryFailure("box bounds are not strictly ordered")
    a = -nx / nz
    b = (nx * point[0] + nz * point[2]) / nz
    x0, x1 = low[0], high[0]
    z0, z1 = low[2], high[2]
    ywidth = high[1] - low[1]
    cuts = [x0, x1]
    for z in (z0, z1):
        if abs(a) > 1e-15:
            x = (z - b) / a
            if x0 < x < x1:
                cuts.append(x)
    cuts = sorted(set(cuts))
    area = 0.0
    pieces: list[dict[str, Any]] = []
    for xa, xb in zip(cuts, cuts[1:]):
        xm = (xa + xb) / 2.0
        threshold = a * xm + b
        if threshold <= z0:
            integral = (z1 - z0) * (xb - xa)
            classification = "full_z"
        elif threshold >= z1:
            integral = 0.0
            classification = "empty"
        else:
            integral = z1 * (xb - xa) - (a * (xb * xb - xa * xa) / 2.0 + b * (xb - xa))
            classification = "above_plane"
        area += integral
        pieces.append({"x_interval_m": [xa, xb], "classification": classification,
                       "integrated_height_area_m2": integral})
    return area * ywidth, {"plane_a": a, "plane_b": b, "x_breaks_m": cuts, "pieces": pieces}


def _vec(value: Any, label: str) -> tuple[float, float, float]:
    if not isinstance(value, list) or len(value) != 3:
        raise GeometryFailure(f"{label} is not a 3-vector")
    return tuple(_float(item, f"{label}[{i}]") for i, item in enumerate(value))  # type: ignore[return-value]


def audit(audit_path: Path, evidence_path: Path, scope_path: Path | None = None) -> dict[str, Any]:
    audit_value, audit_record = _read_json(audit_path, "F5 clipplane volume audit")
    evidence_value, evidence_record = _read_json(evidence_path, "F5 official clip evidence")
    scope_value, scope_record = (None, None)
    if scope_path is not None:
        scope_value, scope_record = _read_json(scope_path, "F5 continuous geometry scope")
        if scope_value.get("schema") != SCOPE_SCHEMA:
            raise GeometryFailure("continuous geometry scope schema mismatch")
    if audit_value.get("schema") != AUDIT_SCHEMA or evidence_value.get("schema") != EVIDENCE_SCHEMA:
        raise GeometryFailure("F5 source audit/evidence schema mismatch")
    plane_contract = evidence_value.get("clipplane_contract") or {}
    point = _vec(plane_contract.get("point_m"), "clipplane point")
    vector = _vec(plane_contract.get("vector_m"), "clipplane vector")
    if point != (2.0, 0.0, 0.0) or vector != (0.28, 0.0, -1.0):
        raise GeometryFailure("F5 plane differs from the source/evidence contract")
    region = evidence_value.get("continuous_region") or {}
    low = _vec(region.get("envelope_low_m"), "fluid envelope low")
    size = _vec(region.get("envelope_size_m"), "fluid envelope size")
    high = tuple(low[i] + size[i] for i in range(3))
    volume, quadrature = integrate_clipped_box(low, high, vector, point)
    mass = volume * 1000.0
    expected_volume = _float(region.get("volume_m3"), "recorded continuous volume")
    expected_mass = _float(region.get("mass_at_rho0_1000_kg"), "recorded continuous mass")
    if not _close(volume, expected_volume) or not _close(mass, expected_mass):
        raise GeometryFailure("analytic integral disagrees with the bounded official-evidence record")
    audit_region = audit_value.get("continuous_region") or {}
    if not _close(volume, _float(audit_region.get("volume_m3"), "audit volume")):
        raise GeometryFailure("analytic integral disagrees with the bounded volume-audit record")
    mass_gate = audit_value.get("mass_gate") or {}
    sample_mass = _float(mass_gate.get("generated_sample_mass_kg"), "generated sample mass")
    sample_relative = sample_mass / mass - 1.0
    recorded_sample_relative = mass_gate.get("sample_vs_derived_fraction", mass_gate.get("sample_vs_source_derived_continuous_fraction"))
    if not _close(sample_relative, _float(recorded_sample_relative, "sample relative mass")):
        raise GeometryFailure("sample-vs-derived diagnostic was not recomputed consistently")
    if scope_value is not None:
        old_status = (scope_value.get("formal_scientific_domain") or {}).get("continuous_fluid_mass_kg")
        if old_status not in (None, "UNKNOWN"):
            raise GeometryFailure("old scope unexpectedly contains a promoted continuous mass")
    return {
        "schema": SCHEMA,
        "status": "SOURCE_DERIVED_CONTINUOUS_REGION_MASS_CLOSED_SUPPORT_PENDING",
        "identity": {"family_id": "F5", "sentinel_id": "F5-S1",
                      "physical_case_id": "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090",
                      "geometry_family_id": "F5_C082S1_CLOSED_ANALYTIC_PROFILE_EXTRUDED_Y_V1"},
        "source_inputs": {"clip_volume_audit": audit_record, "official_clip_evidence": evidence_record,
                           "prior_scope": scope_record},
        "continuous_region": {
            "box_low_m": list(low), "box_high_m": list(high), "box_size_m": list(size),
            "plane_point_m": list(point), "plane_vector_m": list(vector),
            "retained_half_space": "0.28*(x-2)-z <= 0, equivalently z >= 0.28*(x-2)",
            "volume_m3": volume, "density_kg_m3": 1000.0, "mass_kg": mass,
            "quadrature": quadrature,
            "authority": "frozen source Def + official ClipPoint semantics recorded in bounded evidence",
        },
        "owner_contract": {
            "continuous_region_mass_kg": mass,
            "owner_authority": "SOURCE_DERIVED_GEOMETRIC_REGION_NO_SEPARATE_SCALAR_FILE",
            "raw_envelope_mass_kg": 363.888,
            "old_source_discrete_sample_mass_kg": 253.264,
            "do_not_substitute_raw_or_discrete_mass": True,
            "support_status": "PENDING_GUARDED_REPRESENTATION_SUPPORT",
            "scientific_mass_status": "GEOMETRIC_TARGET_ONLY_UNTIL_NATIVE_SUPPORT_AND_CONTROL_JOIN",
        },
        "existing_sample_diagnostic": {
            "generated_sample_mass_kg": sample_mass,
            "relative_to_source_derived_mass": sample_relative,
            "mass_gate": "HARDFAIL_OVER_TWO_PERCENT",
            "rescale": False,
            "interpretation": "existing discrete representation fails the source-derived region gate; this is not flux or legal-outflow evidence",
        },
        "next_parent": {
            "action": "Use the closed source-derived region as the immutable mass/support gate for a new GenCase-only representation QA; do not run CFD until generated native support reaches the gate.",
            "required_fields": ["generated XML roles/counts", "Fluid/Bound finite support", "overlap and envelope membership", "native frame-0 Idp roles", "native MassFluid/MassBound when present"],
            "solver_launch": False, "gencase_launch": "PARENT_GUARDED_ONLY",
            "resource_class": {"cpu_threads": 1, "memory_bytes": 4 * 1024**3, "max_wall_seconds": 900, "gpu": False},
            "failure_scope": "retain 287.736 kg source-derived target and existing discrete hard-fail; leave QI/QN/QE UNKNOWN",
        },
        "scientific_qualification": dict(UNKNOWN_Q),
        "read_scope": {"bounded_json_only": True, "production_vtk": False, "production_bi4": False,
                        "hdf5": False, "solver_or_gencase_launch": False},
    }


def _write_once(path: Path, value: Any) -> None:
    path = _abs(path)
    if path.exists() or path.is_symlink():
        raise GeometryFailure(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def self_test() -> None:
    # Full, empty, and partial manufactured boxes exercise the same integral
    # used by the source contract; the tests do not create a production file.
    full, _ = integrate_clipped_box((0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (0.0, 0.0, -1.0), (0.0, 0.0, -2.0))
    empty, _ = integrate_clipped_box((0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (0.0, 0.0, -1.0), (0.0, 0.0, 2.0))
    partial, _ = integrate_clipped_box((0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (1.0, 0.0, -1.0), (0.0, 0.0, 0.0))
    assert _close(full, 1.0) and _close(empty, 0.0) and _close(partial, 0.5)
    try:
        integrate_clipped_box((0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (0.0, 0.0, 1.0), (0.0, 0.0, 0.0))
    except GeometryFailure:
        pass
    else:
        raise AssertionError("wrong plane orientation was accepted")
    print("PASS_F5_S1_CONTINUOUS_OWNER_GEOMETRY_V2_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--volume-audit", type=Path)
    parser.add_argument("--official-evidence", type=Path)
    parser.add_argument("--scope", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    if args.volume_audit is None or args.official_evidence is None or args.output is None:
        parser.error("--volume-audit, --official-evidence and --output are required unless --self-test is used")
    try:
        value = audit(args.volume_audit, args.official_evidence, args.scope)
        _write_once(args.output, value)
    except (GeometryFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_F5_S1_CONTINUOUS_OWNER_GEOMETRY_V2: {exc}")
        return 2
    print(json.dumps({"status": value["status"], "output": str(_abs(args.output)), "scientific_credit": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
