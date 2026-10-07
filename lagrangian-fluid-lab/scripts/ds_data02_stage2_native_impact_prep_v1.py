#!/usr/bin/env python3
"""Prepare bounded observation/qualification impact evidence from native joins.

This is a forward-only JSON audit.  It consumes the completed coverage index
and native sidecars, computes only the typed mass that became unobserved after
each first gap, and records the first-gap window and native motive.  It does
not read H5, infer physical spill, bound dynamics, or grant QN/QE.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any


class ImpactPrepError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def require_file(path: str | Path, label: str) -> Path:
    value = Path(path)
    if not value.is_file():
        raise ImpactPrepError(f"{label} is missing: {value}")
    return value


def read_json(path: str | Path, label: str) -> tuple[Path, dict[str, Any]]:
    value = require_file(path, label)
    try:
        result = json.loads(value.read_text())
    except Exception as exc:
        raise ImpactPrepError(f"{label} is invalid JSON: {value}: {exc}") from exc
    if not isinstance(result, dict):
        raise ImpactPrepError(f"{label} is not an object: {value}")
    return value, result


def ref(path: Path, *, declared_sha: str | None = None, label: str) -> dict[str, Any]:
    path = require_file(path, label)
    actual = sha256(path)
    if declared_sha is not None and actual != declared_sha:
        raise ImpactPrepError(f"{label} hash differs from declared binding: {path}")
    return {"path": str(path), "sha256": actual, "bytes": path.stat().st_size}


def sidecar_evidence(row: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    evidence = row.get("cause", {}).get("evidence")
    if not isinstance(evidence, dict) or not evidence.get("path"):
        raise ImpactPrepError(f"coverage row has no native evidence: {row.get('physical_case_id')}")
    path = require_file(evidence["path"], "native sidecar")
    actual = sha256(path)
    if actual != evidence.get("sha256"):
        raise ImpactPrepError(f"coverage/native sidecar hash differs: {path}")
    sidecar = json.loads(path.read_text())
    if sidecar.get("physical_case_id") != row.get("physical_case_id"):
        raise ImpactPrepError(f"native sidecar physical identity differs: {path}")
    if sidecar.get("status") != "CAUSES_RECONCILED":
        raise ImpactPrepError(f"native sidecar is not reconciled: {path}")
    return path, sidecar


def missing_records(sidecar: dict[str, Any]) -> list[dict[str, Any]]:
    records = sidecar.get("excluded_particles")
    if isinstance(records, list):
        return records
    records = sidecar.get("missing_fluid_ids")
    if isinstance(records, list):
        return records
    return []


def first_gap_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    frames = [int(item["first_missing_frame"]) for item in records
              if item.get("first_missing_frame") is not None]
    brackets = [item.get("first_missing_bracket_s") for item in records
                if isinstance(item.get("first_missing_bracket_s"), list)
                and len(item["first_missing_bracket_s"]) == 2]
    lows = [float(pair[0]) for pair in brackets]
    highs = [float(pair[1]) for pair in brackets]
    return {
        "records_with_first_gap": len(frames),
        "first_missing_frame_min": min(frames) if frames else None,
        "first_missing_frame_max": max(frames) if frames else None,
        "first_missing_time_window_s": [min(lows), max(highs)] if lows and highs else None,
    }


def motive_counts(sidecar: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in records:
        motive = item.get("native_motive")
        if motive is not None:
            result[str(motive)] = result.get(str(motive), 0) + 1
    if result:
        return result
    raw = sidecar.get("native_motive_counts", {})
    return {str(key): int(value) for key, value in raw.items()}


def typed_mass(sidecar: dict[str, Any], records: list[dict[str, Any]]) -> tuple[int, float]:
    typed = sidecar.get("typed_identity", {})
    if typed:
        count = int(typed.get("missing_fluid_count", len(records)))
        mass = float(typed.get("missing_fluid_initial_mass_kg", 0.0))
        return count, mass
    count = int(sidecar.get("typed_unique_missing", len(records)))
    mass = float(sidecar.get("joined_initial_mass_kg", 0.0))
    return count, mass


def write_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    except Exception:
        try:
            os.unlink(temp)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coverage", required=True, type=Path)
    parser.add_argument("--join-manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    coverage_path, coverage = read_json(args.coverage.resolve(), "coverage index")
    manifest_path, manifest = read_json(args.join_manifest.resolve(), "native join manifest")
    if coverage.get("schema") != "ds02.stage2.omission-coverage-index.v2":
        raise ImpactPrepError("coverage index must be v2")
    if manifest.get("schema") != "ds02.stage2.native-join-manifest.v1":
        raise ImpactPrepError("native join manifest schema mismatch")
    if manifest.get("scope", {}).get("total_cases") != 65:
        raise ImpactPrepError("native join manifest does not cover 65 new cases")
    rows = coverage.get("rows", [])
    if len(rows) != 118:
        raise ImpactPrepError(f"coverage has {len(rows)} rows, expected 118")
    prepared: list[dict[str, Any]] = []
    aggregate: dict[str, dict[str, float | int]] = {}
    for row in rows:
        sidecar_path, sidecar = sidecar_evidence(row)
        records = missing_records(sidecar)
        count, mass = typed_mass(sidecar, records)
        fluid = row.get("current_scan", {}).get("fluid", {})
        denominator = float(fluid.get("typed_initial_mass_kg", 0.0))
        if denominator <= 0 or not math.isfinite(denominator):
            raise ImpactPrepError(f"invalid typed mass denominator: {row.get('physical_case_id')}")
        if mass < 0 or not math.isfinite(mass):
            raise ImpactPrepError(f"invalid missing mass: {sidecar_path}")
        fraction = mass / denominator
        family = str(row["family_id"])
        family_total = aggregate.setdefault(family, {"cases": 0, "missing_ids": 0, "missing_mass_kg": 0.0, "denominator_mass_kg_sum": 0.0})
        family_total["cases"] += 1
        family_total["missing_ids"] += count
        family_total["missing_mass_kg"] += mass
        family_total["denominator_mass_kg_sum"] += denominator
        prepared.append({
            "family_id": family,
            "physical_case_id": row["physical_case_id"],
            "historical_118_membership": True,
            "native_sidecar": ref(sidecar_path, declared_sha=row["cause"]["evidence"].get("sha256"), label="native sidecar"),
            "native_cause": row["cause"].get("history_cause"),
            "native_motive_counts": motive_counts(sidecar, records),
            "missing_fluid_count": count,
            "missing_fluid_initial_mass_kg": mass,
            "typed_initial_mass_denominator_kg": denominator,
            "unobserved_typed_mass_fraction_lower_bound": fraction,
            "mass_interpretation": "lower bound on typed source mass no longer observed after the first gap; does not prove physical loss or bound dynamics",
            "first_gap": first_gap_summary(records),
            "source_mk_status": "DEFERRED_STATIC_H5_PER_MK_AUDIT",
            "observation_impact_status": "UNKNOWN",
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "QN": "NOT_ASSESSED",
            "QE": "NOT_ASSESSED",
        })
    result = {
        "schema": "ds02.stage2.native-impact-preparation.v1",
        "purpose": "Evidence-only impact preparation for all 118 exact CURRENT native omission joins.",
        "source_coverage": ref(coverage_path, label="coverage index"),
        "source_join_manifest": ref(manifest_path, label="native join manifest"),
        "scope": {"historical_118_rows": len(prepared), "families": sorted(aggregate), "h5_opened": False, "frames_read": False},
        "aggregate": aggregate,
        "interpretation": {
            "mass_denominator": "typed_initial_mass_kg from each completed current scientific scan; H5 per-MK refinement is deferred",
            "f6_rigid_observation_separation": "F6 fluid typed mass is not XML rigid-body mass 128 kg or floating typed sample mass 256 kg",
            "observables_remaining_unknown": ["fluid free-surface/pressure/impact timing", "rigid COM/orientation/angular velocity", "coupled impulse/force/energy response"],
            "minimal_paired_experiment": "same wetted wall and physical boundary; one native-gate/discrete-support/domain-margin factor at a time; compare rigid and fluid observables with the same initial condition",
            "qualification": "no full-qualification, QN, QE, or dynamics credit",
        },
        "rows": sorted(prepared, key=lambda item: (item["family_id"], item["physical_case_id"])),
    }
    write_atomic(args.output.resolve(), result)
    print(json.dumps({"status": "completed", "output": str(args.output.resolve()), "scope": result["scope"], "aggregate": aggregate}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ImpactPrepError as exc:
        raise SystemExit(f"ImpactPrepError: {exc}")
