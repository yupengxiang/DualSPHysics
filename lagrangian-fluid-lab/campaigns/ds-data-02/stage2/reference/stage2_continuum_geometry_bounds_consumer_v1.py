#!/usr/bin/env python3
"""Independently consume the declared-box geometry bounds report.

This consumer does not revisit XML, BI4, or HDF5.  It verifies the report's
finite interval relationships and makes the evidence boundary explicit:
axis-aligned union/void arithmetic is analytically identifiable from the
declared primitives, while GenCase cell-centre crop, boundary ownership, and
effective particle mass remain UNKNOWN.  It is a compact review sidecar for
the 14-sentinel report, not a scientific qualification pass.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.continuum-geometry-bounds-consumer.v1"
REPORT_SCHEMA = "ds02.stage2.continuum-geometry-bounds.v1"
DEFAULT_REPORT = Path(__file__).with_name("stage2_continuum_geometry_bounds_v1.json")
DEFAULT_OUTPUT = Path(__file__).with_name("stage2_continuum_geometry_bounds_consumer_v1.json")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256(path)}


def finite(value: Any, label: str) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{label} is not finite")
    return float(value)


def check_interval(value: dict[str, Any], label: str) -> tuple[float, float]:
    lower = finite(value.get("lower_m3"), f"{label}.lower_m3")
    upper = finite(value.get("upper_m3"), f"{label}.upper_m3")
    if lower < -1e-15 or upper < -1e-15 or lower > upper + 1e-12:
        raise ValueError(f"invalid declared interval {label}: {lower}, {upper}")
    # Coordinate-partition and primitive sums can differ by a few ulps when
    # boxes share a decimal face.  Keep the report's declared values intact,
    # but present the review interval in ordered form within that tolerance.
    return min(lower, upper), max(lower, upper)


def consume(report_path: Path, output_path: Path) -> dict[str, Any]:
    report_path = report_path.expanduser().resolve()
    output_path = output_path.expanduser().resolve()
    if output_path.exists():
        raise FileExistsError(f"refuse to overwrite immutable consumer report: {output_path}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(report, dict) or report.get("schema") != REPORT_SCHEMA:
        raise ValueError("geometry bounds input has wrong schema")
    sources = report.get("sources")
    if not isinstance(sources, list) or len(sources) != 14:
        raise ValueError("geometry bounds input must contain exactly 14 sources")
    summaries: list[dict[str, Any]] = []
    positive_overlap = 0
    positive_void = 0
    phase_unknown = 0
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("source entry is not an object")
        sentinel = source.get("sentinel_id")
        geometry = source.get("total_declared_box_geometry")
        semantics = source.get("semantic_status")
        per_mk = source.get("per_mk")
        if not isinstance(sentinel, str) or not isinstance(geometry, dict) or not isinstance(semantics, dict) or not isinstance(per_mk, list):
            raise ValueError(f"incomplete source entry: {sentinel}")
        bounds = geometry.get("declared_volume_bounds_before_particle_crop_m3")
        lower, upper = check_interval(bounds, f"{sentinel}.total")
        primitive = finite(geometry.get("primitive_sum_volume_m3"), f"{sentinel}.primitive_sum_volume_m3")
        union = finite(geometry.get("axis_aligned_union_volume_m3"), f"{sentinel}.axis_aligned_union_volume_m3")
        void_union = finite(geometry.get("void_subtracted_union_volume_m3"), f"{sentinel}.void_subtracted_union_volume_m3")
        overlap = finite(geometry.get("cross_mk_overlap_excess_volume_m3"), f"{sentinel}.cross_mk_overlap_excess_volume_m3")
        if primitive + 1e-12 < union or void_union > union + 1e-12 or overlap < -1e-12:
            raise ValueError(f"inconsistent declared volume relationships: {sentinel}")
        if overlap > 1e-12:
            positive_overlap += 1
        mk_summaries: list[dict[str, Any]] = []
        for item in per_mk:
            if not isinstance(item, dict):
                raise ValueError(f"invalid per_mk entry: {sentinel}")
            mk_bounds = item.get("declared_volume_bounds_before_particle_crop_m3")
            mk_lower, mk_upper = check_interval(mk_bounds, f"{sentinel}.per_mk")
            mk_overlap = finite(item.get("overlap_excess_volume_m3"), f"{sentinel}.per_mk.overlap_excess_volume_m3")
            if mk_overlap < -1e-12:
                raise ValueError(f"negative per-MK overlap: {sentinel}")
            intersections = item.get("void_intersections")
            if not isinstance(intersections, list):
                raise ValueError(f"missing void intersections: {sentinel}")
            void_positive = any(finite(value.get("intersection_volume_m3"), "void intersection") > 1e-12 for value in intersections)
            if void_positive:
                positive_void += 1
            phase_values = [box.get("lattice_phase", {}).get("status") for box in item.get("drawboxes", []) if isinstance(box, dict)]
            phase_unknown += sum(1 for status in phase_values if status != "ANALYTIC_DECLARED_LATTICE_PHASE_ONLY")
            mk_summaries.append({"mkfluid_relative": item.get("mkfluid_relative"),
                                 "volume_interval_m3": [mk_lower, mk_upper],
                                 "overlap_excess_m3": mk_overlap,
                                 "void_intersection_positive": void_positive,
                                 "lattice_phase_status": phase_values})
        summaries.append({
            "sentinel_id": sentinel,
            "family_id": source.get("family_id"),
            "physical_case_id": source.get("physical_case_id"),
            "declared_volume_interval_m3": [lower, upper],
            "declared_mass_interval_kg": geometry.get("declared_mass_bounds_before_particle_crop_kg"),
            "primitive_union_basis": "EXACT_FOR_DECLARED_AXIS_ALIGNED_BOXES",
            "void_subtraction_basis": "EXACT_FOR_DECLARED_AXIS_ALIGNED_BOXES",
            "overlap_status": "POSITIVE_DECLARED_OVERLAP" if overlap > 1e-12 else "NO_POSITIVE_DECLARED_OVERLAP_WITHIN_TOLERANCE",
            "effective_particle_mass": "UNKNOWN",
            "cell_centre_crop": semantics.get("cell_centre_crop_or_fill"),
            "boundary_ownership": semantics.get("boundary_ownership_at_shared_faces"),
            "per_mk": mk_summaries,
        })
    output = {
        "schema": SCHEMA,
        "status": "PASS_INDEPENDENT_DECLARED_BOUNDS_CONSUMED_EFFECTIVE_PARTICLES_UNKNOWN",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_report": record(report_path),
        "independent_consumer_scope": {
            "source_count": len(summaries),
            "bi4_read": False,
            "hdf5_read": False,
            "solver_launch": False,
            "reparsed_source_xml": False,
            "checks": ["finite lower<=upper", "primitive sum>=union", "void-subtracted union<=union", "nonnegative overlap"],
        },
        "identifiable_basis": {
            "axis_aligned_union": "coordinate partition of declared drawbox faces",
            "setmkvoid_intersection": "coordinate partition of declared fluid/void faces",
            "lattice_phase": "point minus pointref divided by declared dp; reports declared phase only",
        },
        "unknown_boundary": {
            "GenCase_cell_centre_crop": "UNKNOWN",
            "shared_face_ownership": "UNKNOWN",
            "effective_particle_sample_mass": "UNKNOWN",
            "continuum_scientific_qualification": "UNKNOWN",
        },
        "aggregate_counts": {"positive_cross_mk_overlap_sources": positive_overlap,
                              "positive_void_intersection_mk_groups": positive_void,
                              "unresolved_phase_entries": phase_unknown},
        "sources": summaries,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    atomic = output_path.with_name(output_path.name + f".{os.getpid()}.tmp")
    try:
        atomic.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        with atomic.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(atomic, output_path)
    finally:
        atomic.unlink(missing_ok=True)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = consume(args.report, args.output)
    print(json.dumps({"status": output["status"], "output": str(args.output.resolve()),
                      "sources": output["independent_consumer_scope"]["source_count"],
                      "bi4_read": False, "hdf5_read": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
