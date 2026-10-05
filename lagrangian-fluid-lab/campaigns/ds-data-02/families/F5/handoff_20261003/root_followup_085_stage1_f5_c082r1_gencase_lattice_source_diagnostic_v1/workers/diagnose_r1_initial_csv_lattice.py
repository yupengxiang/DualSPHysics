#!/usr/bin/env python3
"""Root-owned read-only diagnostic for the R1 official initial CSV.

This worker is disabled in the source package.  When Root enables it, the
worker reads the already-produced PartVTK CSV and computes location residuals,
float32 round-trip/ULP diagnostics, fluid lattice occupancy gaps, and Type0/Mk50
bed support.  It never edits the CSV, shifts/resamples coordinates, substitutes
an expected fluid count, or authorizes a solver.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import struct
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path


FIELDS = [
    "Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "Zone", "Idp", "Type", "Mk",
    "Mass [kg]", "Vel.x [m/s]", "Vel.y [m/s]", "Vel.z [m/s]", "Rhop [kg/m^3]", "Press [Pa]",
]
DP = 0.02
POINTREF = (0.01, 0.0, 0.01)
PROFILE = [(-0.2, 0.0), (2.0, 0.0), (3.0, 0.28), (3.6, 0.448), (3.9, 0.448), (4.4, 0.05), (4.8, 0.05)]
FLUID_MIN = (0.01, -0.14, 0.01)
FLUID_MAX = (3.43, 0.14, 0.39)
SEGMENTS = [(-0.2, 2.0), (2.0, 3.0), (3.0, 3.6), (3.6, 3.9), (3.9, 4.4), (4.4, 4.8)]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def f32_bits(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


def f32_ulp(value: float) -> float:
    value = f32(value)
    if not math.isfinite(value):
        return math.nan
    bits = f32_bits(value)
    if bits == 0x7F800000 or bits == 0xFF800000:
        return math.nan
    if value >= 0.0:
        next_bits = bits + 1
    elif bits > 0:
        next_bits = bits - 1
    else:
        next_bits = 1
    return abs(struct.unpack("<f", struct.pack("<I", next_bits))[0] - value)


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lo = math.floor(position)
    hi = math.ceil(position)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo)


def summary(values: list[float]) -> dict:
    finite = [v for v in values if math.isfinite(v)]
    absolute = [abs(v) for v in finite]
    return {
        "count": len(values),
        "finite_count": len(finite),
        "min": min(finite) if finite else None,
        "max": max(finite) if finite else None,
        "mean": statistics.fmean(finite) if finite else None,
        "p50": percentile(finite, 0.50),
        "p90": percentile(finite, 0.90),
        "p95": percentile(finite, 0.95),
        "p99": percentile(finite, 0.99),
        "p999": percentile(finite, 0.999),
        "max_abs": max(absolute) if absolute else None,
        "p99_abs": percentile(absolute, 0.99),
    }


def profile_z(x: float) -> float:
    if x <= PROFILE[0][0]:
        return PROFILE[0][1]
    if x >= PROFILE[-1][0]:
        return PROFILE[-1][1]
    for (x0, z0), (x1, z1) in zip(PROFILE, PROFILE[1:]):
        if x <= x1:
            return z0 + (z1 - z0) * ((x - x0) / (x1 - x0))
    return PROFILE[-1][1]


def nearest_index(value: float, origin: float) -> int:
    scaled = (value - origin) / DP
    # Source coordinates are expected near nonnegative lattice indices.  This
    # explicit half-up rule avoids Python's banker-rounding ambiguity in the
    # diagnostic key; the raw residual remains reported independently.
    return math.floor(scaled + 0.5) if scaled >= 0 else math.ceil(scaled - 0.5)


def nearest_grid(value: float, origin: float) -> tuple[int, float, float]:
    index = nearest_index(value, origin)
    nearest = origin + index * DP
    residual_m = value - nearest
    return index, nearest, residual_m / DP


def find_header(path: Path) -> tuple[int, str, list[str]]:
    with path.open("r", encoding="utf-8", errors="replace", newline="") as stream:
        for line_number, raw in enumerate(stream):
            if "Pos.x [m]" not in raw or "Idp" not in raw or "Type" not in raw:
                continue
            choices = [",", ";", "\t"]
            delimiter = max(choices, key=lambda candidate: raw.count(candidate))
            header = [field.strip() for field in next(csv.reader([raw], delimiter=delimiter))]
            if all(field in header for field in FIELDS):
                return line_number, delimiter, header
    raise ValueError("official CSV header missing or unsupported")


def read_rows(path: Path) -> tuple[list[dict], str, int]:
    header_line, delimiter, header = find_header(path)
    indices = {field: header.index(field) for field in FIELDS}
    rows: list[dict] = []
    with path.open("r", encoding="utf-8", errors="replace", newline="") as stream:
        reader = csv.reader(stream, delimiter=delimiter)
        for line_number, row in enumerate(reader):
            if line_number <= header_line or not row or all(not cell.strip() for cell in row):
                continue
            if len(row) <= max(indices.values()):
                continue
            try:
                values = [float(row[indices[field]].strip()) for field in FIELDS]
            except ValueError as exc:
                raise ValueError(f"non-numeric CSV row at line {line_number + 1}") from exc
            rows.append({"line": line_number + 1, "values": values})
    return rows, delimiter, header_line


def categorical_key(value: float) -> str:
    if not math.isfinite(value):
        return "nonfinite"
    if not value.is_integer():
        return "nonintegral"
    return str(int(value))


def field_quality(rows: list[dict]) -> dict:
    nonfinite_by_field = {field: 0 for field in FIELDS}
    nonpositive_mass = 0
    nonpositive_density = 0
    nonintegral_categorical = {field: 0 for field in ("Zone", "Idp", "Type", "Mk")}
    zero_velocity = 0
    for item in rows:
        values = item["values"]
        for index, field in enumerate(FIELDS):
            if not math.isfinite(values[index]):
                nonfinite_by_field[field] += 1
        if not math.isfinite(values[7]) or values[7] <= 0:
            nonpositive_mass += 1
        if not math.isfinite(values[11]) or values[11] <= 0:
            nonpositive_density += 1
        for index, field in ((3, "Zone"), (4, "Idp"), (5, "Type"), (6, "Mk")):
            if math.isfinite(values[index]) and not values[index].is_integer():
                nonintegral_categorical[field] += 1
        if all(math.isfinite(values[index]) and values[index] == 0.0 for index in (8, 9, 10)):
            zero_velocity += 1
    uid_values = [int(item["values"][4]) for item in rows if math.isfinite(item["values"][4]) and item["values"][4].is_integer()]
    unique_uids = set(uid_values)
    missing_between = None
    if uid_values:
        lower, upper = min(unique_uids), max(unique_uids)
        missing_between = (upper - lower + 1) - len(unique_uids)
    return {
        "nonfinite_by_field": nonfinite_by_field,
        "nonpositive_mass_count": nonpositive_mass,
        "nonpositive_density_count": nonpositive_density,
        "nonintegral_categorical_by_field": nonintegral_categorical,
        "zero_velocity_rows": zero_velocity,
        "uid": {
            "finite_integer_rows": len(uid_values),
            "unique_rows": len(unique_uids),
            "duplicate_rows": len(uid_values) - len(unique_uids),
            "min": min(unique_uids) if unique_uids else None,
            "max": max(unique_uids) if unique_uids else None,
            "missing_between_min_max": missing_between,
        },
    }


def type_counts(rows: list[dict]) -> dict:
    result: Counter[str] = Counter()
    mk_counts: Counter[str] = Counter()
    for item in rows:
        values = item["values"]
        result[categorical_key(values[5])] += 1
        mk_counts[categorical_key(values[6])] += 1
    return {"by_type": dict(sorted(result.items())), "by_mk": dict(sorted(mk_counts.items()))}


def axis_residuals(rows: list[dict]) -> tuple[dict, list[dict], dict]:
    by_axis: dict[str, list[float]] = {"x": [], "y": [], "z": []}
    f32_by_axis: dict[str, list[float]] = {"x": [], "y": [], "z": []}
    raw_to_f32: dict[str, list[float]] = {"x": [], "y": [], "z": []}
    ulps: dict[str, list[float]] = {"x": [], "y": [], "z": []}
    nonfinite_by_axis: Counter[str] = Counter()
    worst: list[dict] = []
    names = ("x", "y", "z")
    for item_index, item in enumerate(rows):
        values = item["values"]
        for axis, name in enumerate(names):
            raw = values[axis]
            if not math.isfinite(raw):
                nonfinite_by_axis[name] += 1
                continue
            origin = POINTREF[axis]
            index, nearest, residual = nearest_grid(raw, origin)
            cast = f32(raw)
            _, cast_nearest, cast_residual = nearest_grid(cast, origin)
            by_axis[name].append(residual)
            f32_by_axis[name].append(cast_residual)
            raw_to_f32[name].append(abs(raw - cast))
            ulp = f32_ulp(raw)
            if math.isfinite(ulp):
                ulps[name].append(ulp)
            worst.append({
                "row_index": item_index,
                "csv_line": item["line"],
                "idp": int(values[4]) if math.isfinite(values[4]) else None,
                "axis": name,
                "raw_m": raw,
                "nearest_source_grid_m": cast_nearest,
                "raw_residual_m": raw - nearest,
                "raw_residual_cells": residual,
                "float32_value_m": cast,
                "float32_residual_m": cast - cast_nearest,
                "float32_residual_cells": cast_residual,
                "float32_ulp_m": ulp,
                "raw_to_float32_abs_m": abs(raw - cast),
                "raw_within_1e-6_cells": abs(residual) <= 1e-6,
            })
    worst.sort(key=lambda entry: abs(entry["raw_residual_cells"]), reverse=True)
    report = {}
    for axis in names:
        report[axis] = {
            "input_rows": len(rows),
            "nonfinite_count": nonfinite_by_axis[axis],
            "raw_residual_cells": summary(by_axis[axis]),
            "float32_cast_residual_cells": summary(f32_by_axis[axis]),
            "raw_to_float32_abs_m": summary(raw_to_f32[axis]),
            "float32_ulp_m": summary(ulps[axis]),
            "threshold_counts_raw_cells": {str(t): sum(abs(v) <= t for v in by_axis[axis]) for t in (1e-6, 1e-5, 1e-4, 1e-3)},
            "threshold_counts_float32_cells": {str(t): sum(abs(v) <= t for v in f32_by_axis[axis]) for t in (1e-6, 1e-5, 1e-4, 1e-3)},
        }
    return report, worst[:12], {"raw": by_axis, "float32": f32_by_axis}


def expected_clip_keys(boundary_inclusive: bool) -> set[tuple[int, int, int]]:
    result: set[tuple[int, int, int]] = set()
    dp = Decimal("0.02")
    origin_x = Decimal("0.01")
    origin_z = Decimal("0.01")
    slope = Decimal("0.28")
    x_intercept = Decimal("2.0")
    for ix in range(172):
        x = origin_x + ix * dp
        for iy in range(15):
            for iz in range(20):
                z = origin_z + iz * dp
                plane = slope * (x - x_intercept)
                keep = z >= plane if boundary_inclusive else z > plane
                if keep:
                    result.add((ix, iy, iz))
    return result


def occupancy(rows: list[dict]) -> dict:
    fluid: list[tuple[int, int, int, dict]] = []
    for item in rows:
        values = item["values"]
        if not math.isfinite(values[5]) or not values[5].is_integer() or int(values[5]) != 3:
            continue
        ix = nearest_index(values[0], POINTREF[0])
        iy = nearest_index(values[1], POINTREF[1])
        iz = nearest_index(values[2], POINTREF[2])
        fluid.append((ix, iy, iz, item))
    observed = {(ix, iy, iz) for ix, iy, iz, _ in fluid}
    by_x: Counter[str] = Counter(str(ix) for ix, _, _, _ in fluid)
    by_y: Counter[str] = Counter(str(iy) for _, iy, _, _ in fluid)
    by_z: Counter[str] = Counter(str(iz) for _, _, iz, _ in fluid)
    strict = expected_clip_keys(False)
    inclusive = expected_clip_keys(True)
    missing_xy_strict = Counter((ix, iy) for ix, iy, iz in strict - observed)
    missing_xy_inclusive = Counter((ix, iy) for ix, iy, iz in inclusive - observed)
    return {
        "observed_fluid_count": len(fluid),
        "unique_nearest_grid_keys": len(observed),
        "duplicate_nearest_grid_keys": len(fluid) - len(observed),
        "counts_by_nearest_x_index": dict(sorted(by_x.items(), key=lambda pair: int(pair[0]))),
        "counts_by_nearest_y_index": dict(sorted(by_y.items(), key=lambda pair: int(pair[0]))),
        "counts_by_nearest_z_index": dict(sorted(by_z.items(), key=lambda pair: int(pair[0]))),
        "clip_only_expected_strict_count": len(strict),
        "clip_only_expected_inclusive_count": len(inclusive),
        "missing_from_strict_clip_only": len(strict - observed),
        "missing_from_inclusive_clip_only": len(inclusive - observed),
        "observed_outside_inclusive_clip_only": len(observed - inclusive),
        "missing_by_x_strict": {str(ix): len({key for key in strict if key[0] == ix} - observed) for ix in sorted({key[0] for key in strict})},
        "missing_by_x_inclusive": {str(ix): len({key for key in inclusive if key[0] == ix} - observed) for ix in sorted({key[0] for key in inclusive})},
        "missing_by_y_strict": {str(iy): len({key for key in strict if key[1] == iy} - observed) for iy in sorted({key[1] for key in strict})},
        "missing_by_y_inclusive": {str(iy): len({key for key in inclusive if key[1] == iy} - observed) for iy in sorted({key[1] for key in inclusive})},
        "missing_by_xy_strict_nonzero": {f"{ix},{iy}": count for (ix, iy), count in sorted(missing_xy_strict.items()) if count},
        "missing_by_xy_inclusive_nonzero": {f"{ix},{iy}": count for (ix, iy), count in sorted(missing_xy_inclusive.items()) if count},
        "interpretation": "nearest keys are diagnostic coordinates; no source coordinate is shifted or rewritten",
    }


def support(rows: list[dict]) -> dict:
    marker = [item for item in rows if categorical_key(item["values"][5]) == "0" and categorical_key(item["values"][6]) == "50"]
    by_segment = []
    for lo, hi in SEGMENTS:
        selected = [item for item in marker if lo <= item["values"][0] <= hi and abs(item["values"][1]) <= 0.01]
        bands = {}
        for band in (0.5, 1.0, 2.0):
            bands[str(band)] = sum(abs(item["values"][2] - profile_z(item["values"][0])) <= band * DP for item in selected)
        by_segment.append({"x_bounds_m": [lo, hi], "central_y_marker_rows": len(selected), "central_profile_band_counts": bands})
    return {
        "native_type0_mk50_rows": len(marker),
        "native_type0_mk50_central_profile_support_by_segment": by_segment,
        "source_mkbound": 40,
        "native_bed_mk": 50,
        "native_bed_type": 0,
        "interpretation": "marker/profile counts are diagnostic evidence only; no contained-bed or dynamic claim",
    }


def geometry(rows: list[dict]) -> dict:
    fluid = [item["values"] for item in rows if categorical_key(item["values"][5]) == "3"]
    below = []
    outside = []
    clearances = []
    for values in fluid:
        x, y, z = values[:3]
        surface = profile_z(x)
        clearances.append(z - surface)
        if z < surface:
            below.append(values)
        if any(values[axis] < FLUID_MIN[axis] or values[axis] > FLUID_MAX[axis] for axis in range(3)):
            outside.append(values)
    return {
        "fluid_rows": len(fluid),
        "below_profile_count_exact": len(below),
        "outside_source_box_count": len(outside),
        "fluid_clearance_above_profile_m": {
            "min": min(clearances) if clearances else None,
            "p01": percentile(clearances, 0.01),
            "p50": percentile(clearances, 0.50),
            "max": max(clearances) if clearances else None,
        },
        "source_box_m": {"min": list(FLUID_MIN), "max": list(FLUID_MAX)},
    }


def run_check() -> None:
    assert f32(0.01) == f32(f32(0.01))
    assert len(expected_clip_keys(False)) == 40695
    assert len(expected_clip_keys(True)) == 40740
    print("source-only CSV lattice diagnostic synthetic checks passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding", type=Path)
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        run_check()
        return
    require(args.binding is not None and args.csv is not None and args.output_dir is not None, "binding, csv and output-dir are required")
    binding = json.loads(args.binding.read_text(encoding="utf-8"))
    require(binding.get("schema") == "ds02.f5.c082r1.initial-csv-lattice-diagnostic-binding.fresh085.v1", "binding schema mismatch")
    csv_path = args.csv.resolve()
    require(csv_path.is_file(), f"CSV missing: {csv_path}")
    expected_csv = Path(binding["actual_root246"]["official_csv"]).resolve()
    require(csv_path == expected_csv, "CSV path is not the bound Root246 producer path")
    csv_digest = sha(csv_path)
    expected_digest = binding["actual_root246"].get("official_csv_sha256")
    require(expected_digest is None or csv_digest == expected_digest, "CSV SHA mismatch against Root-bound producer hash")
    rows, delimiter, header_line = read_rows(csv_path)
    counts = binding["actual_gencase"]["actual_counts"]
    require(len(rows) == int(counts["total_particles"]), f"CSV row count {len(rows)} != actual total {counts['total_particles']}")
    residual_report, worst, residual_values = axis_residuals(rows)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "schema": "ds02.f5.c082r1.initial-csv-lattice-diagnostic.fresh085.v1",
        "status": "completed_readonly_csv_diagnostic",
        "case_id": binding["case_id"],
        "attempt_id": binding["attempt_id"],
        "csv": {"path": str(csv_path), "sha256": csv_digest, "delimiter": delimiter, "header_line_zero_based": header_line, "rows": len(rows)},
        "producer_binding": binding["actual_gencase"],
        "field_quality": field_quality(rows),
        "type_and_mk_counts": type_counts(rows),
        "axis_lattice": {"dp_m": DP, "pointref_m": list(POINTREF), "residuals": residual_report, "worst_finite_samples": worst, "source_coordinate_transform": "nearest grid key is reported only; raw coordinates are never modified"},
        "occupancy": occupancy(rows),
        "geometry": geometry(rows),
        "native_type0_mk50_support": support(rows),
        "mass_metadata": {"actual_csv_mass_kg_from_root246": 253.26401266320002, "continuum_mass_kg_legacy": 325.7142857142857, "mass_rescaled": False, "source_agent_read_csv": False},
        "interpretation": {
            "lattice_failure_is_preserved": True,
            "float32_ulp_is_explanatory_diagnostic_only": True,
            "xy_wet_cohort_gap_is_not_filled": True,
            "no_threshold_widening": True,
            "no_coordinate_shift_or_resampling": True,
            "no_qa_pass_claim": True,
            "no_dynamic_acceptance": True,
            "no_full16_or_full801_authorization": True,
        },
        "arrays_opened_by_source_agent": False,
    }
    (output / "r1-initial-csv-lattice-diagnostic.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "rows": len(rows), "csv_sha256": csv_digest, "max_abs_residual_cells": {axis: residual_report[axis]["raw_residual_cells"]["max_abs"] for axis in ("x", "y", "z")}}, sort_keys=True))


if __name__ == "__main__":
    main()
