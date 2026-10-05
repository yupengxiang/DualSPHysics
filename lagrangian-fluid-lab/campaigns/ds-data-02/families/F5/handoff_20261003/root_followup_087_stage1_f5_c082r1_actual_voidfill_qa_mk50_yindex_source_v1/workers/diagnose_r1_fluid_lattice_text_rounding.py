#!/usr/bin/env python3
"""Read-only Root worker for per-fluid lattice, CSV text, and source-y-index diagnostics.

The source package keeps this request disabled.  Once Root enables it, the
worker reads only the already-produced official CSV and a small binding JSON.
It reports per-fluid source-grid residuals, binary32 representability, a
decimal-text formatting bound, clip-only cohort gaps, native fixed/moving
occupancy, and a lattice-key contact-distance envelope.  It never shifts,
resamples, fills, or edits a particle coordinate and never authorizes a
solver or a new physical case.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import struct
from collections import Counter
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path


FIELDS = [
    "Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "Zone", "Idp", "Type", "Mk",
    "Mass [kg]", "Vel.x [m/s]", "Vel.y [m/s]", "Vel.z [m/s]", "Rhop [kg/m^3]", "Press [Pa]",
]
AXES = ("x", "y", "z")
AXIS_INDEX = {name: index for index, name in enumerate(AXES)}
DP = 0.02
DP_DEC = Decimal("0.02")
POINTREF = (0.01, 0.0, 0.01)
POINTREF_DEC = tuple(Decimal(value) for value in ("0.01", "0.0", "0.01"))
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


def f32_ulp(value: float) -> float:
    cast = f32(value)
    if not math.isfinite(cast):
        return math.nan
    bits = struct.unpack("<I", struct.pack("<f", cast))[0]
    if cast >= 0.0:
        next_bits = bits + 1
    elif bits > 0:
        next_bits = bits - 1
    else:
        next_bits = 1
    return abs(struct.unpack("<f", struct.pack("<I", next_bits))[0] - cast)


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
    finite = [value for value in values if math.isfinite(value)]
    absolute = [abs(value) for value in finite]
    return {
        "count": len(values),
        "finite_count": len(finite),
        "min": min(finite) if finite else None,
        "max": max(finite) if finite else None,
        "mean": statistics.fmean(finite) if finite else None,
        "p01": percentile(finite, 0.01),
        "p50": percentile(finite, 0.50),
        "p95": percentile(finite, 0.95),
        "p99": percentile(finite, 0.99),
        "max_abs": max(absolute) if absolute else None,
        "p99_abs": percentile(absolute, 0.99),
    }


def categorical_key(value: float) -> str:
    if not math.isfinite(value):
        return "nonfinite"
    if not value.is_integer():
        return "nonintegral"
    return str(int(value))


def find_header(path: Path) -> tuple[int, str, list[str]]:
    with path.open("r", encoding="utf-8", errors="replace", newline="") as stream:
        for line_number, raw in enumerate(stream):
            if "Pos.x [m]" not in raw or "Idp" not in raw or "Type" not in raw:
                continue
            delimiter = max((",", ";", "\t"), key=lambda candidate: raw.count(candidate))
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
            tokens = [row[indices[field]].strip() for field in FIELDS]
            try:
                values = [float(token) for token in tokens]
            except ValueError as exc:
                raise ValueError(f"non-numeric CSV row at line {line_number + 1}") from exc
            rows.append({"line": line_number + 1, "tokens": tokens, "values": values})
    return rows, delimiter, header_line


def decimal_token(token: str) -> Decimal | None:
    try:
        value = Decimal(token)
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def decimal_text_half_step(token: str) -> Decimal | None:
    """Half of the last printed decimal place under round-to-nearest formatting."""
    raw = token.strip().lower()
    if not raw or raw in {"nan", "+nan", "-nan", "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"}:
        return None
    mantissa, separator, exponent_text = raw.partition("e")
    try:
        exponent = int(exponent_text) if separator else 0
    except ValueError:
        return None
    unsigned = mantissa.lstrip("+-")
    fraction_digits = len(unsigned.split(".", 1)[1]) if "." in unsigned else 0
    place_exponent = exponent - fraction_digits
    return Decimal("0.5") * (Decimal(10) ** place_exponent)


def nearest_index(value: float, origin: float) -> int:
    scaled = (value - origin) / DP
    return math.floor(scaled + 0.5) if scaled >= 0 else math.ceil(scaled - 0.5)


def nearest_key(values: list[float]) -> tuple[int, int, int] | None:
    if not all(math.isfinite(values[index]) for index in range(3)):
        return None
    return tuple(nearest_index(values[index], POINTREF[index]) for index in range(3))


def nearest_decimal_index(value: Decimal, origin: Decimal) -> int:
    scaled = (value - origin) / DP_DEC
    return int(scaled.to_integral_value(rounding=ROUND_HALF_UP))


def profile_z(x: float) -> float:
    if x <= PROFILE[0][0]:
        return PROFILE[0][1]
    if x >= PROFILE[-1][0]:
        return PROFILE[-1][1]
    for (x0, z0), (x1, z1) in zip(PROFILE, PROFILE[1:]):
        if x <= x1:
            return z0 + (z1 - z0) * ((x - x0) / (x1 - x0))
    return PROFILE[-1][1]


def expected_clip_keys(boundary_inclusive: bool) -> set[tuple[int, int, int]]:
    result: set[tuple[int, int, int]] = set()
    slope = Decimal("0.28")
    x_intercept = Decimal("2.0")
    for ix in range(172):
        x = POINTREF_DEC[0] + ix * DP_DEC
        # POINTREF.y is 0.0 while the source fluid box starts at y=-0.14.
        # The producer lattice keys therefore run from -7 through +7.
        # Using 0..14 here would relabel every y cohort and create false gaps.
        for iy in range(-7, 8):
            for iz in range(20):
                z = POINTREF_DEC[2] + iz * DP_DEC
                plane = slope * (x - x_intercept)
                keep = z >= plane if boundary_inclusive else z > plane
                if keep:
                    result.add((ix, iy, iz))
    return result


def source_grid_residual(token: str, parsed: float, axis: int) -> dict:
    exact = decimal_token(token)
    if exact is None or not math.isfinite(parsed):
        return {
            "finite": False,
            "raw_residual_cells": None,
            "exact_decimal_residual_cells": None,
            "float32_residual_cells": None,
            "float32_exact_binary64": False,
            "text_parse_error_m": None,
            "text_rounding_half_step_bound_m": decimal_text_half_step(token),
        }
    decimal_index = nearest_decimal_index(exact, POINTREF_DEC[axis])
    decimal_grid = POINTREF_DEC[axis] + decimal_index * DP_DEC
    exact_residual_cells = float((exact - decimal_grid) / DP_DEC)
    float_index = nearest_index(parsed, POINTREF[axis])
    float_grid = POINTREF[axis] + float_index * DP
    cast = f32(parsed)
    cast_index = nearest_index(cast, POINTREF[axis])
    cast_grid = POINTREF[axis] + cast_index * DP
    parsed_decimal = Decimal.from_float(parsed)
    cast_decimal = Decimal.from_float(cast)
    return {
        "finite": True,
        "raw_residual_cells": (parsed - float_grid) / DP,
        "exact_decimal_residual_cells": exact_residual_cells,
        "float32_residual_cells": (cast - cast_grid) / DP,
        "float32_exact_binary64": cast == parsed,
        "float32_value_m": cast,
        "float32_ulp_m": f32_ulp(parsed),
        "text_parse_error_m": float(abs(parsed_decimal - exact)),
        "float32_error_to_text_m": float(abs(cast_decimal - exact)),
        "text_rounding_half_step_bound_m": float(decimal_text_half_step(token)) if decimal_text_half_step(token) is not None else None,
        "source_grid_index": float_index,
        "source_grid_m": float_grid,
    }


def per_fluid_lattice(rows: list[dict]) -> dict:
    fluid = [item for item in rows if categorical_key(item["values"][5]) == "3"]
    by_axis: dict[str, dict[str, list[float]]] = {
        axis: {name: [] for name in ("raw_residual_cells", "exact_decimal_residual_cells", "float32_residual_cells", "text_parse_error_m", "float32_error_to_text_m", "text_rounding_half_step_bound_m", "float32_ulp_m")}
        for axis in AXES
    }
    exact_float32 = Counter()
    nonfinite = Counter()
    worst_residual: list[dict] = []
    worst_text: list[dict] = []
    for item in fluid:
        values = item["values"]
        tokens = item["tokens"]
        for axis, name in enumerate(AXES):
            result = source_grid_residual(tokens[axis], values[axis], axis)
            if not result["finite"]:
                nonfinite[name] += 1
                continue
            for field in by_axis[name]:
                value = result[field]
                if value is not None and math.isfinite(value):
                    by_axis[name][field].append(float(value))
            exact_float32[name] += int(result["float32_exact_binary64"])
            base = {"csv_line": item["line"], "idp": int(values[4]) if math.isfinite(values[4]) and values[4].is_integer() else None, "axis": name, "token": tokens[axis]}
            worst_residual.append({**base, **result})
            worst_text.append({**base, **result})
    for entries, key in ((worst_residual, "raw_residual_cells"), (worst_text, "float32_error_to_text_m")):
        entries.sort(key=lambda entry: abs(entry[key]) if entry.get(key) is not None else -1.0, reverse=True)
    axis_report = {}
    for name in AXES:
        axis_report[name] = {
            "fluid_rows": len(fluid),
            "nonfinite_coordinate_count": nonfinite[name],
            "statistics": {field: summary(values) for field, values in by_axis[name].items()},
            "float32_exact_binary64_count": exact_float32[name],
            "float32_not_exact_binary64_count": len(fluid) - nonfinite[name] - exact_float32[name],
            "raw_within_1e-6_cells_count": sum(abs(value) <= 1e-6 for value in by_axis[name]["raw_residual_cells"]),
            "exact_decimal_within_1e-6_cells_count": sum(abs(value) <= 1e-6 for value in by_axis[name]["exact_decimal_residual_cells"]),
        }
    return {
        "fluid_rows": len(fluid),
        "per_axis": axis_report,
        "worst_residual_examples": worst_residual[:12],
        "worst_float32_text_error_examples": worst_text[:12],
        "text_rounding_bound_assumption": "half of the last printed decimal place, assuming the producer formatted each coordinate by round-to-nearest decimal text",
    }


def rows_by_native_category(rows: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    fluid = [item for item in rows if categorical_key(item["values"][5]) == "3"]
    fixed = [item for item in rows if categorical_key(item["values"][5]) == "0"]
    moving = [item for item in rows if categorical_key(item["values"][5]) == "1"]
    return fluid, fixed, moving


def pair_counts(keys: set[tuple[int, int, int]], index: int) -> dict[str, int]:
    counts = Counter(str(key[index]) for key in keys)
    return dict(sorted(counts.items(), key=lambda pair: int(pair[0])))


def cohort_comparison(fluid_keys: set[tuple[int, int, int]], fixed_keys: set[tuple[int, int, int]], moving_keys: set[tuple[int, int, int]]) -> dict:
    native_keys = fixed_keys | moving_keys
    output = {}
    for label, expected in (("strict", expected_clip_keys(False)), ("inclusive", expected_clip_keys(True))):
        missing = expected - fluid_keys
        output[label] = {
            "expected_clip_only_count": len(expected),
            "observed_fluid_unique_key_count": len(fluid_keys),
            "missing_expected_key_count": len(missing),
            "missing_by_x": pair_counts(missing, 0),
            "missing_by_y": pair_counts(missing, 1),
            "missing_expected_keys_occupied_by_fixed": len(missing & fixed_keys),
            "missing_expected_keys_occupied_by_moving": len(missing & moving_keys),
            "missing_expected_keys_empty_of_native_fixed_moving": len(missing - native_keys),
            "observed_fluid_keys_outside_expected": len(fluid_keys - expected),
            "observed_fluid_keys_overlapping_fixed": len(fluid_keys & fixed_keys),
            "observed_fluid_keys_overlapping_moving": len(fluid_keys & moving_keys),
        }
    return {
        "source_y_origin_m": POINTREF[1],
        "source_fluid_y_min_m": FLUID_MIN[1],
        "source_fluid_y_max_m": FLUID_MAX[1],
        "source_fluid_y_nearest_index_range": [-7, 7],
        "fluid_keys_by_nearest_x": pair_counts(fluid_keys, 0),
        "fluid_keys_by_nearest_y": pair_counts(fluid_keys, 1),
        "fluid_keys_by_nearest_z": pair_counts(fluid_keys, 2),
        "strict_vs_native_occupancy": output["strict"],
        "inclusive_vs_native_occupancy": output["inclusive"],
        "interpretation": "missing keys are partitioned by observed native fixed/moving occupancy versus empty keys; no missing key is filled or reassigned",
    }


def nearest_lattice_distance(key: tuple[int, int, int], native: set[tuple[int, int, int]], max_radius: int = 8) -> float | None:
    if not native:
        return None
    for radius in range(max_radius + 1):
        best_squared = None
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                for dz in range(-radius, radius + 1):
                    if max(abs(dx), abs(dy), abs(dz)) != radius:
                        continue
                    candidate = (key[0] + dx, key[1] + dy, key[2] + dz)
                    if candidate in native:
                        squared = dx * dx + dy * dy + dz * dz
                        best_squared = squared if best_squared is None else min(best_squared, squared)
        if best_squared is not None:
            return math.sqrt(best_squared)
    return None


def contact_envelope(fluid_keys: set[tuple[int, int, int]], native_keys: set[tuple[int, int, int]]) -> dict:
    distances = [nearest_lattice_distance(key, native_keys) for key in fluid_keys]
    finite = [value for value in distances if value is not None]
    distance_stats = summary(finite)
    distance_stat_fields = ("min", "max", "mean", "p01", "p50", "p95", "p99", "max_abs", "p99_abs")
    return {
        "fluid_unique_keys": len(fluid_keys),
        "native_unique_keys": len(native_keys),
        "unresolved_beyond_8_lattice_cells": sum(value is None for value in distances),
        "zero_cell_contact_count": sum(value == 0.0 for value in finite),
        "within_1dp_count": sum(value <= 1.0 for value in finite),
        "within_2dp_count": sum(value <= 2.0 for value in finite),
        "distance_envelope_lattice_cells": distance_stats,
        "distance_envelope_m": {key: distance_stats[key] * DP for key in distance_stat_fields},
        "interpretation": "distance is between nearest source-lattice keys, not a substitute for a continuous contact solver or a bed containment proof",
    }


def native_occupancy_and_contact(rows: list[dict]) -> dict:
    fluid, fixed, moving = rows_by_native_category(rows)
    fluid_keys = {key for item in fluid if (key := nearest_key(item["values"])) is not None}
    fixed_keys = {key for item in fixed if (key := nearest_key(item["values"])) is not None}
    moving_keys = {key for item in moving if (key := nearest_key(item["values"])) is not None}
    return {
        "row_counts": {"fluid_type3": len(fluid), "fixed_type0": len(fixed), "moving_type1": len(moving)},
        "unique_nearest_keys": {"fluid": len(fluid_keys), "fixed": len(fixed_keys), "moving": len(moving_keys)},
        "expected_clip_cohort_vs_native_occupancy": cohort_comparison(fluid_keys, fixed_keys, moving_keys),
        "native_type0_mk50_support": bed_marker_support(rows),
        "contact_distance_envelope": {
            "to_fixed": contact_envelope(fluid_keys, fixed_keys),
            "to_moving": contact_envelope(fluid_keys, moving_keys),
            "to_fixed_or_moving": contact_envelope(fluid_keys, fixed_keys | moving_keys),
        },
        "physical_interpretation_boundary": {
            "native_nonfluid_occupancy_is_reported_as_observation": True,
            "empty_missing_cohort_is_not_filled": True,
            "clipping_vs_particle_subtraction_is_not_decided_by_boolean_gate": True,
            "no_expected_fluid_count_substitution": True,
        },
    }


def bed_marker_support(rows: list[dict]) -> dict:
    markers = [item for item in rows if categorical_key(item["values"][5]) == "0" and categorical_key(item["values"][6]) == "50"]
    by_segment = []
    for lo, hi in SEGMENTS:
        selected = [item for item in markers if lo <= item["values"][0] <= hi and abs(item["values"][1]) <= 0.01]
        bands = {
            str(band): sum(abs(item["values"][2] - profile_z(item["values"][0])) <= band * DP for item in selected)
            for band in (0.5, 1.0, 2.0)
        }
        by_segment.append({"x_bounds_m": [lo, hi], "central_y_rows": len(selected), "central_profile_band_counts": bands})
    return {
        "native_type0_mk50_rows": len(markers),
        "central_profile_support_by_six_x_segments": by_segment,
        "source_mkbound": 40,
        "native_bed_mk": 50,
        "interpretation": "marker support is an evidence table for the full wet footprint; it does not certify a contained or dynamically stable bed",
    }


def geometry_summary(rows: list[dict]) -> dict:
    fluid, fixed, moving = rows_by_native_category(rows)
    below = 0
    outside = 0
    clearances = []
    for item in fluid:
        x, y, z = item["values"][:3]
        if not all(math.isfinite(value) for value in (x, y, z)):
            continue
        clearance = z - profile_z(x)
        clearances.append(clearance)
        below += int(clearance < 0.0)
        outside += int(any(item["values"][axis] < FLUID_MIN[axis] or item["values"][axis] > FLUID_MAX[axis] for axis in range(3)))
    return {
        "fluid_rows": len(fluid),
        "fixed_rows": len(fixed),
        "moving_rows": len(moving),
        "fluid_below_profile_count": below,
        "fluid_outside_source_box_count": outside,
        "fluid_clearance_m": summary(clearances),
        "source_box_m": {"min": list(FLUID_MIN), "max": list(FLUID_MAX)},
    }


def run_check() -> None:
    assert len(expected_clip_keys(False)) == 40695
    assert len(expected_clip_keys(True)) == 40740
    assert {key[1] for key in expected_clip_keys(False)} == set(range(-7, 8))
    assert decimal_text_half_step("0.010000") == Decimal("0.0000005")
    assert decimal_text_half_step("1.0e-2") == Decimal("0.0005")
    exact = source_grid_residual("0.010000", 0.01, 0)
    assert exact["float32_exact_binary64"] is False
    assert abs(exact["exact_decimal_residual_cells"]) == 0.0
    print("source-only per-fluid lattice/text diagnostic synthetic checks passed")


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
    require(binding.get("schema") == "ds02.f5.c082r1.fluid-lattice-text-rounding-binding.fresh087.v1", "binding schema mismatch")
    require(binding.get("attempt_id"), "binding attempt_id missing")
    csv_path = args.csv.resolve()
    require(csv_path.is_file(), f"CSV missing: {csv_path}")
    expected_csv = Path(binding["actual_root256"]["official_csv"]).resolve()
    require(csv_path == expected_csv, "CSV path is not the Root256 producer path")
    csv_digest = sha(csv_path)
    require(csv_digest == binding["actual_root256"]["official_csv_sha256"], "CSV SHA mismatch against Root256 binding")
    rows, delimiter, header_line = read_rows(csv_path)
    counts = binding["actual_gencase"]["actual_counts"]
    require(len(rows) == int(counts["total_particles"]), f"CSV row count {len(rows)} != actual total {counts['total_particles']}")
    actual_fluid = sum(categorical_key(item["values"][5]) == "3" for item in rows)
    require(actual_fluid == int(counts["fluid_particles"]), f"CSV fluid count {actual_fluid} != actual producer {counts['fluid_particles']}")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "schema": "ds02.f5.c082r1.fluid-lattice-text-rounding-diagnostic.fresh087.v1",
        "status": "completed_readonly_per_fluid_diagnostic",
        "case_id": binding["case_id"],
        "attempt_id": binding["attempt_id"],
        "csv": {"path": str(csv_path), "sha256": csv_digest, "delimiter": delimiter, "header_line_zero_based": header_line, "rows": len(rows)},
        "producer_binding": binding["actual_gencase"],
        "root256_prior_diagnostic": binding["actual_root256"],
        "per_fluid_lattice_and_text_rounding": per_fluid_lattice(rows),
        "native_occupancy_and_contact": native_occupancy_and_contact(rows),
        "geometry": geometry_summary(rows),
        "cohort_index_provenance": {
            "pointref_y_m": POINTREF[1],
            "fluid_box_y_bounds_m": [FLUID_MIN[1], FLUID_MAX[1]],
            "nearest_index_formula": "round_half_up((Pos.y - pointref_y)/dp)",
            "correct_nearest_y_index_range": [-7, 7],
            "fresh086_expected_0_to_14_was_a_labeling_error": True,
            "root264_report_is_preserved_and_not_reinterpreted": True,
        },
        "mass_metadata": {"actual_csv_mass_kg": binding["actual_root256"]["actual_csv_mass_kg"], "continuum_mass_kg_legacy": 325.7142857142857, "mass_rescaled": False},
        "interpretation": {
            "float32_and_text_bounds_are_explanatory_diagnostics_only": True,
            "clip_only_cohort_is_not_an_expected_producer_count": True,
            "native_fixed_moving_occupancy_is_not_a_bed_containment_proof": True,
            "no_gap_filling_or_coordinate_shift": True,
            "no_qa_pass_claim": True,
            "no_dynamic_acceptance": True,
            "no_full16_or_full801_authorization": True,
        },
        "arrays_opened_by_source_agent": False,
    }
    report_path = output / "r1-fluid-lattice-text-rounding-occupancy-diagnostic.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "rows": len(rows), "fluid_rows": actual_fluid, "csv_sha256": csv_digest}, sort_keys=True))


if __name__ == "__main__":
    main()
