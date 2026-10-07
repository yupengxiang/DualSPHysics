#!/usr/bin/env python3
"""Audit selected initial H5 arrays against exact conversion source-MK blocks.

The audit is intentionally static: it opens only ``initial_*`` datasets and
never reads trajectory frames.  It is prepared for a separately scheduled
shared-I/O slot.  Every request must name one or two exact physical case IDs;
the bounded selector prevents accidentally scheduling the historical 118-case
audit as one 900-second job.  It does not infer physical fate, dynamics, QN,
or QE.
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

import h5py
import numpy as np


class StaticAuditError(RuntimeError):
    pass


MAX_CASES_PER_REQUEST = 2


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def require_file(path: str | Path, label: str) -> Path:
    value = Path(path)
    if not value.is_file():
        raise StaticAuditError(f"{label} is missing: {value}")
    return value


def read_json(path: str | Path, label: str) -> tuple[Path, dict[str, Any]]:
    value = require_file(path, label)
    try:
        document = json.loads(value.read_text())
    except Exception as exc:
        raise StaticAuditError(f"{label} is invalid JSON: {value}: {exc}") from exc
    if not isinstance(document, dict):
        raise StaticAuditError(f"{label} is not an object: {value}")
    return value, document


def ref(path: Path, *, declared_sha: str | None = None, label: str) -> dict[str, Any]:
    path = require_file(path, label)
    actual = sha256(path)
    if declared_sha is not None and actual != declared_sha:
        raise StaticAuditError(f"{label} hash differs from declared binding: {path}")
    return {"path": str(path), "sha256": actual, "bytes": path.stat().st_size}


def fluid_blocks(conversion: dict[str, Any]) -> list[dict[str, int]]:
    blocks = conversion.get("typed_identity", {}).get("blocks", [])
    result = []
    for raw in blocks:
        if raw.get("tag") == "fluid" and int(raw.get("type", -1)) == 3:
            result.append({
                "begin": int(raw["begin"]),
                "count": int(raw["count"]),
                "mk": int(raw["mk"]),
                "mkfluid": int(raw.get("mkfluid", -1)),
                "type": int(raw["type"]),
            })
    if not result:
        raise StaticAuditError("conversion report has no type=3 fluid blocks")
    return result


def all_blocks(conversion: dict[str, Any]) -> list[dict[str, int]]:
    blocks = conversion.get("typed_identity", {}).get("blocks", [])
    result = []
    for raw in blocks:
        result.append({
            "begin": int(raw["begin"]),
            "count": int(raw["count"]),
            "mk": int(raw["mk"]),
            "mkfluid": int(raw.get("mkfluid", -1)) if raw.get("mkfluid") is not None else -1,
            "type": int(raw["type"]),
        })
    if not result:
        raise StaticAuditError("conversion report has no typed blocks")
    return result


def audit_case(row: dict[str, Any]) -> dict[str, Any]:
    physical_id = str(row["physical_case_id"])
    trajectory = row["current_identity"]["trajectory"]
    h5_path = require_file(trajectory["path"], f"trajectory for {physical_id}")
    conversion_info = row["current_identity"]["conversion_report"]
    conversion_path, conversion = read_json(conversion_info["path"], "conversion report")
    if conversion.get("conversion_status") != "completed":
        raise StaticAuditError(f"conversion is not completed: {conversion_path}")
    blocks = fluid_blocks(conversion)
    typed_blocks = all_blocks(conversion)
    total_particles = sum(int(block["count"]) for block in typed_blocks)
    expected_min = float(conversion["typed_identity"]["initial_mass_min_kg"])
    expected_max = float(conversion["typed_identity"]["initial_mass_max_kg"])
    expected_mass = conversion.get("hash_scopes", {}).get("numerical_parameters", {}).get("decoder_header_constants", {}).get("MassFluid")
    # Header constants may be serialized as a short decimal (for example
    # 0.001) while the H5 initial_mass dataset stores float32.  Compare at
    # the native float32 value instead of treating the decimal spelling as an
    # exact binary64 value.
    expected_mass32 = None if expected_mass is None else float(np.float32(expected_mass))

    with h5py.File(h5_path, "r") as h5:
        required = ("particle_id", "particle_zone", "initial_type", "initial_mk", "initial_mass")
        missing = [name for name in required if name not in h5]
        if missing:
            raise StaticAuditError(f"{physical_id} H5 missing static datasets: {missing}")
        ids = np.asarray(h5["particle_id"][:])
        zones = np.asarray(h5["particle_zone"][:])
        types = np.asarray(h5["initial_type"][:])
        mks = np.asarray(h5["initial_mk"][:])
        masses = np.asarray(h5["initial_mass"][:])
        lengths = {len(ids), len(zones), len(types), len(mks), len(masses)}
        if len(lengths) != 1:
            raise StaticAuditError(f"{physical_id} static axis lengths differ: {lengths}")
        if len(ids) != total_particles:
            raise StaticAuditError(f"{physical_id} particle count differs: H5={len(ids)} conversion={total_particles}")
        if len(np.unique(ids)) != len(ids):
            raise StaticAuditError(f"{physical_id} particle_id axis is not unique")
        if not np.isfinite(masses).all() or np.any(masses <= 0):
            raise StaticAuditError(f"{physical_id} initial_mass contains nonpositive/nonfinite values")
        expected_type = np.full(total_particles, -1, dtype=np.int8)
        expected_mk = np.full(total_particles, -1, dtype=np.int16)
        block_rows = []
        for block in typed_blocks:
            begin, end = block["begin"], block["begin"] + block["count"]
            if begin < 0 or end > total_particles:
                raise StaticAuditError(f"{physical_id} conversion block exceeds H5 axis: {block}")
            expected_type[begin:end] = block["type"]
            expected_mk[begin:end] = block["mk"]
            block_rows.append({**block, "h5_count": int(np.sum((types == block["type"]) & (mks == block["mk"])) )})
        if not np.array_equal(types, expected_type):
            raise StaticAuditError(f"{physical_id} initial_type differs from conversion source blocks")
        if not np.array_equal(mks, expected_mk):
            raise StaticAuditError(f"{physical_id} initial_mk differs from conversion source blocks")
        fluid = types == 3
        expected_fluid_count = sum(int(block["count"]) for block in blocks)
        if int(np.sum(fluid)) != expected_fluid_count:
            # This catches a type block mismatch before the per-MK table is emitted.
            raise StaticAuditError(f"{physical_id} fluid type axis count is inconsistent")
        mass_values = masses[fluid].astype(np.float64)
        if mass_values.size == 0:
            raise StaticAuditError(f"{physical_id} has no fluid particles")
        if not math.isclose(float(np.min(mass_values)), expected_min, rel_tol=0.0, abs_tol=1e-12):
            raise StaticAuditError(f"{physical_id} H5 fluid mass minimum differs from conversion")
        if not math.isclose(float(np.max(mass_values)), expected_max, rel_tol=0.0, abs_tol=1e-12):
            raise StaticAuditError(f"{physical_id} H5 fluid mass maximum differs from conversion")
        if expected_mass32 is not None and not np.array_equal(
                masses[fluid].astype(np.float32),
                np.full(mass_values.shape, np.float32(expected_mass32), dtype=np.float32)):
            raise StaticAuditError(f"{physical_id} H5 fluid mass differs from decoder MassFluid")
        per_mk = []
        for mk in sorted(set(int(value) for value in mks[fluid])):
            mask = fluid & (mks == mk)
            values = masses[mask].astype(np.float64)
            per_mk.append({
                "mk": mk,
                "count": int(mask.sum()),
                "mass_sum_kg": float(values.sum(dtype=np.float64)),
                "mass_min_kg": float(values.min()),
                "mass_max_kg": float(values.max()),
                "mass_unique_values": sorted(set(float(value) for value in values)),
            })
        attrs = {
            "schema": h5.attrs.get("schema"),
            "conversion_complete": h5.attrs.get("conversion_complete"),
            "identity_key": h5.attrs.get("identity_key"),
            "mass_semantics": h5.attrs.get("mass_semantics"),
        }
    return {
        "family_id": row["family_id"],
        "physical_case_id": physical_id,
        "status": "STATIC_PER_MK_MASS_RECONCILED",
        "trajectory": {
            "path": str(h5_path),
            "declared_sha256": trajectory.get("producer_declared_sha256"),
            "declared_bytes": trajectory.get("bytes"),
            "h5_opened": True,
            "frame_datasets_read": False,
            "datasets_read": ["particle_id", "particle_zone", "initial_type", "initial_mk", "initial_mass"],
        },
        "conversion_report": ref(conversion_path, declared_sha=conversion_info.get("sha256"), label="conversion report"),
        "h5_static_attributes": attrs,
        "particle_count": int(len(ids)),
        "fluid_particle_count": int(fluid.sum()),
        "fluid_mass_kg": float(mass_values.sum(dtype=np.float64)),
        "conversion_fluid_blocks": blocks,
        "h5_typed_blocks": block_rows,
        "per_mk": per_mk,
        "physical_fate": "UNKNOWN",
        "dynamical_impact": "UNKNOWN",
        "QN": "NOT_ASSESSED",
        "QE": "NOT_ASSESSED",
    }


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
    parser.add_argument("--case-id", action="append", required=True,
                        help="exact physical_case_id; repeat at most twice")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    requested_ids = [str(value) for value in args.case_id]
    if not requested_ids or len(requested_ids) > MAX_CASES_PER_REQUEST:
        raise StaticAuditError(
            f"bounded request requires 1..{MAX_CASES_PER_REQUEST} --case-id values")
    if len(set(requested_ids)) != len(requested_ids):
        raise StaticAuditError("duplicate --case-id values are not allowed")
    coverage_path, coverage = read_json(args.coverage.resolve(), "coverage index")
    if coverage.get("schema") not in {
            "ds02.stage2.omission-coverage-index.v2",
            "ds02.stage2.omission-coverage-index.v3"}:
        raise StaticAuditError("coverage index must be v2 or forward v3")
    rows = coverage.get("rows", [])
    if len(rows) != 118:
        raise StaticAuditError(f"coverage index has {len(rows)} rows, expected 118")
    by_id = {}
    for row in rows:
        physical_id = str(row.get("physical_case_id", ""))
        if not physical_id or physical_id in by_id:
            raise StaticAuditError(f"coverage has duplicate or missing physical_case_id: {physical_id}")
        by_id[physical_id] = row
    missing = sorted(set(requested_ids) - set(by_id))
    if missing:
        raise StaticAuditError(f"requested case IDs are absent from coverage: {missing}")
    result_rows = [audit_case(by_id[physical_id]) for physical_id in requested_ids]
    counts = {}
    for row in result_rows:
        counts[row["family_id"]] = counts.get(row["family_id"], 0) + 1
    result = {
        "schema": "ds02.stage2.static-per-mk-h5-audit.v2",
        "purpose": "Bounded static initial H5 per-source-MK mass cross-check for exact selected CURRENT cases.",
        "input_coverage": {"path": str(coverage_path), "sha256": sha256(coverage_path), "bytes": coverage_path.stat().st_size, "schema": coverage.get("schema")},
        "scope": {
            "total_cases": len(result_rows),
            "case_counts": counts,
            "selected_case_ids": requested_ids,
            "historical_118_cases_queued": True,
            "unselected_historical_case_count": 118 - len(result_rows),
            "frames_read": False,
            "bounded_selector_max_cases": MAX_CASES_PER_REQUEST,
        },
        "interpretation": {
            "mass_denominator": "actual H5 initial_mass grouped by initial_mk and initial_type=3; conversion block count and MassFluid are cross-checks",
            "f6_body_mass_separation": "F6 XML rigid-body mass 128 kg and floating typed sample mass 256 kg are not fluid denominator values",
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "qualification": "none",
        },
        "rows": result_rows,
    }
    write_atomic(args.output.resolve(), result)
    print(json.dumps({"status": "completed", "output": str(args.output.resolve()), "scope": result["scope"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except StaticAuditError as exc:
        raise SystemExit(f"StaticAuditError: {exc}")
