#!/usr/bin/env python3
"""Supplement F5 ODS diagnostics with the official WavePaddle analytical CSV.

The ODS comparison is consumed and immutable.  This separately named worker
uses ``WavePaddle_mkb0010.csv`` produced by the official solver as a second,
analytical reference.  It does not fill, alter, or retime the ODS rows.  The
worker reads only the two small MeasureTool CSVs, the small wave CSV, and the
ODS metadata/table; native particle arrays are never opened.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import re
import statistics
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_frozen_comparator():
    path = Path(__file__).with_name("compare_ods_reference.py")
    spec = importlib.util.spec_from_file_location("frozen_f5_ods_comparator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen comparator: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return path, module


def parse_float(text: str) -> Optional[float]:
    text = text.strip().replace("\ufeff", "")
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.casefold())).strip()


def metadata_value(lines: Sequence[str], pattern: str) -> Optional[float]:
    expression = re.compile(pattern, re.IGNORECASE)
    for line in lines:
        match = expression.search(line)
        if match:
            return parse_float(match.group(1))
    return None


def read_wave_csv(path: Path) -> Tuple[Dict[str, List[Tuple[float, float]]], Dict[str, object]]:
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as stream:
        rows = [row for row in csv.reader(stream, delimiter=";") if any(cell.strip() for cell in row)]
    header_index = next(
        (index for index, row in enumerate(rows) if row and normalized(row[0]) == "time s"), None
    )
    if header_index is None:
        raise ValueError(f"WavePaddle CSV has no Time [s] header: {path}")
    headers = rows[header_index]
    names = {normalized(header): index for index, header in enumerate(headers)}
    required = {
        "eta_o2": "elevation o2 m",
        "velx_o2": "velx o2 m s",
        "velz_o2": "velz o2 m s",
    }
    missing = [key for key, name in required.items() if name not in names]
    if missing:
        raise ValueError(f"WavePaddle CSV missing official order-2 columns {missing}: {headers}")
    series: Dict[str, List[Tuple[float, float]]] = {key: [] for key in required}
    for row in rows[header_index + 1 :]:
        if not row:
            continue
        time = parse_float(row[0]) if row else None
        if time is None:
            continue
        for key, name in required.items():
            index = names[name]
            value = parse_float(row[index]) if index < len(row) else None
            if value is None:
                raise ValueError(f"WavePaddle row has missing {key} at t={time}: {row}")
            series[key].append((time, value))
    if not all(series.values()) or any(
        any(later <= earlier for (earlier, _), (later, _) in zip(values, values[1:]))
        for values in series.values()
    ):
        raise ValueError("WavePaddle reference times must be strictly increasing and non-empty")
    preamble = [";".join(row) for row in rows[:header_index]]
    metadata: Dict[str, object] = {
        "path": str(path),
        "sha256": sha256(path),
        "preamble": preamble,
        "header_row_zero_based": header_index,
        "headers": headers,
        "row_count_after_header": len(rows) - header_index - 1,
        "time_bracket_s": [series["eta_o2"][0][0], series["eta_o2"][-1][0]],
        "official_controls": {
            "paddle_start_time_s": metadata_value(preamble, r"Start time:\s*([-+0-9.eE]+)"),
            "paddle_end_time_s": metadata_value(preamble, r"end:\s*([-+0-9.eE]+)"),
            "depth_m": metadata_value(preamble, r"Depth:\s*([-+0-9.eE]+)"),
            "wave_height_m": metadata_value(preamble, r"WaveHeight:\s*([-+0-9.eE]+)"),
            "wave_period_s": metadata_value(preamble, r"WavePeriod:\s*([-+0-9.eE]+)"),
            "initial_ramp_periods": metadata_value(preamble, r"InitialRamp:\s*([-+0-9.eE]+)"),
            "wave_order": next(
                (line.split(":", 1)[1].strip() for line in preamble if line.casefold().startswith("waveorder:")),
                None,
            ),
            "save_motion_time_s": metadata_value(preamble, r"SaveMotion:\s*\[time:\s*([-+0-9.eE]+)"),
            "save_motion_dt_s": metadata_value(preamble, r"SaveMotion:.*?dt:\s*([-+0-9.eE]+)"),
            "save_motion_x_m": metadata_value(preamble, r"SaveMotion:.*?xpos:\s*([-+0-9.eE]+)"),
            "save_motion_z_m": metadata_value(preamble, r"SaveMotion:.*?zpos:\s*([-+0-9.eE]+)"),
        },
    }
    receipt = path.with_name("execution-receipt.json")
    if receipt.is_file():
        metadata["solver_receipt"] = {"path": str(receipt), "sha256": sha256(receipt)}
    return series, metadata


def max_abs_difference(
    left: Sequence[Tuple[float, float]], right: Sequence[Tuple[float, float]],
) -> Dict[str, object]:
    right_by_time = {round(time, 9): value for time, value in right}
    common = [(time, value, right_by_time[round(time, 9)]) for time, value in left if round(time, 9) in right_by_time]
    errors = [value - expected for _, value, expected in common]
    return {
        "n": len(common),
        "time_bracket_s": [common[0][0], common[-1][0]] if common else None,
        "max_absolute_difference": max(map(abs, errors)) if errors else None,
        "rmse": math.sqrt(statistics.fmean(error * error for error in errors)) if errors else None,
        "status": "exact_at_common_native_times" if common and max(map(abs, errors)) <= 1.0e-12 else "not_exact_or_no_overlap",
    }


def count_outside_reference(
    simulation: Sequence[Tuple[float, float]], start: float, end: float, reference: Sequence[Tuple[float, float]]
) -> int:
    first, last = reference[0][0], reference[-1][0]
    return sum(first > time or time > last for time, _ in simulation if start <= time <= end)


def upward_zero_crossings(series: Sequence[Tuple[float, float]], start: float, end: float) -> List[float]:
    """Find upward zero crossings by linear interpolation in absolute time."""
    crossings: List[float] = []
    for (before_time, before_value), (after_time, after_value) in zip(series, series[1:]):
        if after_time < start or before_time > end or before_time == after_time:
            continue
        if before_value <= 0.0 < after_value:
            fraction = -before_value / (after_value - before_value)
            crossing = before_time + fraction * (after_time - before_time)
            if start <= crossing <= end:
                crossings.append(crossing)
    return crossings


def zero_crossing_report(
    simulation: Sequence[Tuple[float, float]], reference: Sequence[Tuple[float, float]], start: float, end: float,
) -> Dict[str, object]:
    simulation_crossings = upward_zero_crossings(simulation, start, end)
    reference_crossings = upward_zero_crossings(reference, start, end)
    matched = min(len(simulation_crossings), len(reference_crossings))
    errors = [simulation_crossings[index] - reference_crossings[index] for index in range(matched)]
    return {
        "window_s": [start, end],
        "matching": "ordered absolute-time pairs; no phase fit or retiming",
        "simulation_upward_zero_crossings_s": simulation_crossings,
        "reference_upward_zero_crossings_s": reference_crossings,
        "paired_errors_s": errors,
        "matched_count": matched,
        "unmatched_simulation_count": len(simulation_crossings) - matched,
        "unmatched_reference_count": len(reference_crossings) - matched,
        "status": "computed" if len(simulation_crossings) == len(reference_crossings) else "unmatched_crossings_reported",
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    frozen_path, frozen = load_frozen_comparator()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wave", type=Path, required=True, help="official WavePaddle_mkb0010.csv")
    parser.add_argument("--elevation", type=Path, required=True, help="MeasureTool elevation CSV")
    parser.add_argument("--velocity", type=Path, required=True, help="MeasureTool velocity CSV")
    parser.add_argument("--ods", type=Path, default=None, help="official ODS for overlap audit")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--simulation-start", type=float, default=0.0)
    parser.add_argument("--simulation-end", type=float, default=30.0)
    parser.add_argument("--startup-end", type=float, default=2.0)
    parser.add_argument("--primary-start", type=float, default=2.0)
    args = parser.parse_args(argv)
    ods = (args.ods or frozen.inferred_ods_path()).resolve()
    for path in (args.wave, args.elevation, args.velocity, ods):
        if not path.is_file():
            parser.error(f"missing input: {path}")
    if args.output_dir.exists():
        parser.error(f"output directory already exists; use a new path: {args.output_dir}")
    if not (args.simulation_start < args.primary_start <= args.simulation_end):
        parser.error("require simulation-start < primary-start <= simulation-end")

    wave, wave_meta = read_wave_csv(args.wave.resolve())
    elevation_raw, elevation_meta = frozen.read_elevation_csv(args.elevation.resolve())
    velocity, velocity_meta = frozen.read_velocity_csv(args.velocity.resolve())
    ods_series, ods_meta = frozen.read_ods_reference(ods)
    elevation_baselines = {key: values[0][1] for key, values in elevation_raw.items() if values}
    elevation = {
        key: [(time, value - elevation_baselines[key]) for time, value in values]
        for key, values in elevation_raw.items()
    }
    elevation_meta["value_transform"] = "eta = MeasureTool Elevation - first native sample per x"
    elevation_meta["still_water_baselines_m"] = elevation_baselines

    windows = {
        "startup_0_2s": (args.simulation_start, args.startup_end),
        "primary_2_30s": (args.primary_start, args.simulation_end),
        "full_common_0_30s": (args.simulation_start, args.simulation_end),
    }
    comparisons = {
        "eta_x6": (elevation["x6"], wave["eta_o2"]),
        "velx_x6_z0p4": (velocity["velx"], wave["velx_o2"]),
        "velz_x6_z0p4": (velocity["velz"], wave["velz_o2"]),
    }
    metric_report = {
        label: {
            window_name: frozen.comparison_metrics(simulation, reference, *window)
            for window_name, window in windows.items()
        }
        for label, (simulation, reference) in comparisons.items()
    }
    zero_crossings = {
        label: zero_crossing_report(simulation, reference, args.primary_start, args.simulation_end)
        for label, (simulation, reference) in comparisons.items()
    }

    ods_overlap = {
        "eta_o2_vs_ods_theory_eta": max_abs_difference(wave["eta_o2"], ods_series["theory_eta"]),
        "velx_o2_vs_ods_theory_velx": max_abs_difference(wave["velx_o2"], ods_series["theory_velx"]),
        "velz_o2_vs_ods_theory_velz": max_abs_difference(wave["velz_o2"], ods_series["theory_velz"]),
    }
    original_ods_coverage = {
        "frozen_ods_comparison_requested_window_s": [args.primary_start, args.simulation_end],
        "ods_populated_time_bracket_s": [ods_series["theory_eta"][0][0], ods_series["theory_eta"][-1][0]],
        "excluded_primary_samples_if_using_ods": count_outside_reference(
            elevation["x6"], args.primary_start, args.simulation_end, ods_series["theory_eta"]
        ),
        "status": "preserved_from_immutable_ods_comparison; supplemental_reference_does_not_fill_or_replace_it",
    }
    report: Dict[str, object] = {
        "schema": "ds-data-02.upstream-first.f5-wave-generator-supplement.v1",
        "family_id": "F5",
        "case_id": "UF_F5_PISTON_REG",
        "reference_role": "calibration_2d_supplemental_analytical_reference",
        "upstream_case_id": "CasePistonBeach_REG",
        "frozen_ods_comparator": {
            "path": str(frozen_path),
            "sha256": sha256(frozen_path),
            "ods_input_sha256": ods_meta["sha256"],
        },
        "inputs": {"wave_generator": wave_meta, "elevation": elevation_meta, "velocity": velocity_meta, "ods": ods_meta},
        "controls": {
            "simulation_window_s": [args.simulation_start, args.simulation_end],
            "startup_report_window_s": [args.simulation_start, args.startup_end],
            "primary_comparison_window_s": [args.primary_start, args.simulation_end],
            "wave_generator_reference_window_s": [wave["eta_o2"][0][0], wave["eta_o2"][-1][0]],
            "interpolation": "linear inside official analytical reference brackets only",
            "phase_shift_or_retiming": False,
        },
        "comparisons": metric_report,
        "upward_zero_crossing_timing": zero_crossings,
        "comparison_reference_sources": {
            "eta_x6": "official WavePaddle_mkb0010.csv Elevation_o2 at x=6m,z=-0.26 control",
            "velx_x6_z0p4": "official WavePaddle_mkb0010.csv Velx_o2 at x=6m,z=-0.26 control",
            "velz_x6_z0p4": "official WavePaddle_mkb0010.csv Velz_o2 at x=6m,z=-0.26 control",
        },
        "ods_overlap_audit": ods_overlap,
        "original_ods_coverage": original_ods_coverage,
        "status": "supplemental_analytical_diagnostic_only",
        "flags": [
            "official_wave_generator_is_analytical_reference_not_independent_experiment",
            "wave_generator_order_2_columns_used_without_phase_shift_or_retiming",
            "immutable_ods_result_and_negative_coverage_preserved",
            "does_not_establish_3d_qualification_or_experimental_acceptance",
            "no_source_uncertainty_or_acceptance_tolerance_invented",
        ],
    }
    args.output_dir.mkdir(parents=True)
    frozen.write_alignment(
        args.output_dir / "wave-generator-aligned-observations.csv",
        [(label, simulation, reference) for label, (simulation, reference) in comparisons.items()],
        args.simulation_start,
        args.simulation_end,
        args.startup_end,
    )
    frozen.write_summary(args.output_dir / "wave-generator-comparison-summary.csv", report)
    (args.output_dir / "wave-generator-supplemental-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(args.output_dir / "wave-generator-supplemental-report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
