#!/usr/bin/env python3
"""Compare official F1 MeasureTool CSVs with mapped SPHERIC Test 02 data.

The worker reads only the small MeasureTool products and the primary SPHERIC
workbook.  It preserves H/P labels and the explicit x-reflection recorded in
``spheric-test2-metadata.json``.  Reference values are interpolated only at
native simulation times inside their source bracket; no phase shift,
retiming, extrapolation, or source-derived acceptance tolerance is applied.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import math
import re
import shutil
import statistics
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from xml.etree import ElementTree as ET


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def number(value: object) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip().replace("\ufeff", "")
    if not text or text.casefold() in {"nan", "na", "n/a", "null", "none", "-"}:
        return None
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    try:
        result = float(text)
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.casefold())).strip()


def read_delimited_rows(path: Path) -> List[List[str]]:
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as stream:
        lines = [line for line in stream if line.strip() and not line.lstrip().startswith(("#", "//"))]
    if not lines:
        raise ValueError(f"reference file has no rows: {path}")
    sample = "".join(lines[:20])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        delimiter = max(",;\t", key=sample.count)
        dialect = csv.excel
        dialect.delimiter = delimiter
    return [row for row in csv.reader(lines, dialect) if any(cell.strip() for cell in row)]


def expected_mapping(metadata: Dict[str, object]) -> Tuple[Dict[str, Tuple[float, float, float]], Dict[str, Tuple[float, float, float]]]:
    coordinate = metadata["coordinate_mapping"]
    heights = {
        item["label"]: tuple(float(value) for value in item["official"])
        for item in coordinate["height_probes"]
    }
    pressure = {
        item["label"]: tuple(float(value) for value in item["official"])
        for item in coordinate["pressure_probes"]
    }
    return heights, pressure


def coordinate_rows(rows: Sequence[Sequence[str]]) -> Dict[str, Sequence[str]]:
    result: Dict[str, Sequence[str]] = {}
    for row in rows:
        for cell in row:
            name = normalize(cell)
            if name.startswith("posx"):
                result["x"] = row
            elif name.startswith("posy"):
                result["y"] = row
            elif name.startswith("posz"):
                result["z"] = row
    return result


def measurement_columns(
    rows: Sequence[Sequence[str]],
    header_index: int,
    expected: Dict[str, Tuple[float, float, float]],
) -> Tuple[Dict[str, int], List[str], Dict[str, List[Optional[float]]]]:
    coords = coordinate_rows(rows[:header_index])
    warnings: List[str] = []
    columns: Dict[int, Tuple[float, float, float]] = {}
    if all(axis in coords for axis in ("x", "y", "z")):
        max_len = max(len(coords[axis]) for axis in ("x", "y", "z"))
        for index in range(max_len):
            values = tuple(number(coords[axis][index]) if index < len(coords[axis]) else None for axis in ("x", "y", "z"))
            if all(value is not None for value in values):
                columns[index] = tuple(float(value) for value in values)  # type: ignore[arg-type]
    selected: Dict[str, int] = {}
    used: set[int] = set()
    for label, target in expected.items():
        candidates = sorted(
            (
                math.sqrt(sum((coordinate[axis] - target[axis]) ** 2 for axis in range(3))),
                index,
            )
            for index, coordinate in columns.items()
            if index not in used
        )
        if candidates and candidates[0][0] <= 1.0e-4:
            selected[label] = candidates[0][1]
            used.add(candidates[0][1])
    if len(selected) != len(expected):
        # This remains explicit in metadata so a missing POINTSLIST position
        # cannot be mistaken for a coordinate-verified comparison.
        value_candidates = [
            index
            for index in range(len(rows[header_index]))
            if index != next((i for i, cell in enumerate(rows[header_index]) if "time" in normalize(cell)), -1)
        ]
        selected = {label: value_candidates[index] for index, label in enumerate(expected) if index < len(value_candidates)}
        warnings.append("point_mapping=positional_fallback; coordinate metadata did not identify every expected point")
    return selected, warnings, {
        str(index): [value for value in coordinate] for index, coordinate in columns.items()
    }


def read_measurement_csv(
    path: Path, expected: Dict[str, Tuple[float, float, float]], quantity: str,
) -> Tuple[Dict[str, List[Tuple[float, float]]], Dict[str, object]]:
    rows = read_delimited_rows(path)
    header_index = next(
        (
            index
            for index, row in enumerate(rows)
            if row and normalize(row[0]) == "part" and any("time" in normalize(cell) for cell in row)
        ),
        None,
    )
    if header_index is None:
        raise ValueError(f"MeasureTool CSV has no Part/Time header: {path}")
    headers = rows[header_index]
    time_index = next(index for index, cell in enumerate(headers) if "time" in normalize(cell))
    columns, warnings, coordinates = measurement_columns(rows, header_index, expected)
    if set(columns) != set(expected):
        raise ValueError(f"could not map all {quantity} points in {path}: {columns}")
    series: Dict[str, List[Tuple[float, float]]] = {label: [] for label in expected}
    missing: Dict[str, int] = {label: 0 for label in expected}
    times: List[float] = []
    for row in rows[header_index + 1 :]:
        if time_index >= len(row):
            continue
        time = number(row[time_index])
        if time is None:
            continue
        times.append(time)
        for label, index in columns.items():
            value = number(row[index]) if index < len(row) else None
            if value is None:
                missing[label] += 1
            else:
                series[label].append((time, value))
    monotonic = all(later > earlier for earlier, later in zip(times, times[1:]))
    if not monotonic:
        warnings.append("time_column_not_strictly_increasing")
    if any(not values for values in series.values()):
        raise ValueError(f"one or more {quantity} points have no numeric samples: {missing}")
    metadata = {
        "path": str(path),
        "sha256": sha256(path),
        "quantity": quantity,
        "header_row_zero_based": header_index,
        "headers": headers,
        "time_column_zero_based": time_index,
        "column_indices_zero_based": columns,
        "column_coordinates_m": coordinates,
        "warnings": warnings,
        "row_count_after_header": len(rows) - header_index - 1,
        "missing_value_count_by_label": missing,
        "time_bracket_s": [times[0], times[-1]] if times else None,
        "strictly_increasing_time": monotonic,
    }
    return series, metadata


def column_number(reference: str) -> int:
    result = 0
    for character in re.match(r"([A-Z]+)", reference.upper()).group(1):  # type: ignore[union-attr]
        result = result * 26 + ord(character) - ord("A") + 1
    return result - 1


def xlsx_value(cell: ET.Element, shared: Sequence[str], ns: Dict[str, str]) -> str:
    kind = cell.attrib.get("t")
    value = cell.find("m:v", ns)
    if kind == "s" and value is not None:
        return shared[int(value.text)]
    if kind == "inlineStr":
        return "".join(text.text or "" for text in cell.findall(".//m:t", ns))
    return value.text if value is not None and value.text is not None else ""


def parse_xlsx_experimental_data(path: Path) -> Tuple[List[List[str]], Dict[str, object]]:
    main_ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    ns = {"m": main_ns}
    with zipfile.ZipFile(path) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_targets = {
            relation.attrib["Id"]: relation.attrib["Target"]
            for relation in relationships
        }
        relation_id = None
        for sheet in workbook.findall("m:sheets/m:sheet", ns):
            if sheet.attrib.get("name") == "Experimental_data":
                relation_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
                break
        if relation_id is None:
            raise ValueError("Experimental_data sheet is missing from converted workbook")
        target = rel_targets[relation_id]
        sheet_path = "xl/" + target.lstrip("/")
        shared: List[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(text.text or "" for text in si.findall(".//m:t", ns)) for si in shared_root.findall("m:si", ns)]
        sheet_root = ET.fromstring(archive.read(sheet_path))
        rows: List[List[str]] = []
        for row_element in sheet_root.findall(".//m:sheetData/m:row", ns):
            row: List[str] = []
            for cell in row_element.findall("m:c", ns):
                index = column_number(cell.attrib["r"])
                while len(row) <= index:
                    row.append("")
                row[index] = xlsx_value(cell, shared, ns)
            rows.append(row)
    return rows, {
        "converted_sheet": "Experimental_data",
        "converted_dimensions": [len(rows), max((len(row) for row in rows), default=0)],
    }


def read_spheric_reference(path: Path) -> Tuple[Dict[str, List[Tuple[float, float]]], Dict[str, object]]:
    converter: Dict[str, object] = {"input_format": path.suffix.casefold().lstrip(".")}
    if path.suffix.casefold() == ".xlsx":
        rows, converted = parse_xlsx_experimental_data(path)
        converter.update(converted)
    elif path.suffix.casefold() == ".csv":
        rows = read_delimited_rows(path)
        converter["converted_sheet"] = "CSV input"
    else:
        libreoffice = shutil.which("libreoffice")
        if libreoffice is None:
            raise RuntimeError("libreoffice is required to read the primary .xls workbook")
        with tempfile.TemporaryDirectory(prefix="spheric-xls-") as temporary:
            completed = subprocess.run(
                [libreoffice, "--headless", "--convert-to", "xlsx", "--outdir", temporary, str(path)],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            converted_path = Path(temporary) / (path.stem + ".xlsx")
            if not converted_path.is_file():
                raise RuntimeError(f"LibreOffice did not produce {converted_path}: {completed.stdout} {completed.stderr}")
            rows, converted = parse_xlsx_experimental_data(converted_path)
            converter.update(converted)
            converter["converter"] = libreoffice
    if not rows:
        raise ValueError("SPHERIC reference has no rows")
    headers = rows[0]
    columns: Dict[str, int] = {}
    for index, header in enumerate(headers):
        name = normalize(header)
        if name == "time s":
            columns["time"] = index
        for label in [f"P{i}" for i in range(1, 9)] + [f"H{i}" for i in range(1, 5)]:
            if name.startswith(normalize(label)):
                columns[label] = index
    required = ["time"] + [f"P{i}" for i in range(1, 9)] + [f"H{i}" for i in range(1, 5)]
    missing = [label for label in required if label not in columns]
    if missing:
        raise ValueError(f"SPHERIC reference missing columns {missing}: {headers}")
    series: Dict[str, List[Tuple[float, float]]] = {label: [] for label in required[1:]}
    missing_counts = {label: 0 for label in required[1:]}
    times: List[float] = []
    for row in rows[1:]:
        time = number(row[columns["time"]]) if columns["time"] < len(row) else None
        if time is None:
            continue
        times.append(time)
        for label in required[1:]:
            value = number(row[columns[label]]) if columns[label] < len(row) else None
            if value is None:
                missing_counts[label] += 1
            else:
                series[label].append((time, value))
    monotonic = all(later > earlier for earlier, later in zip(times, times[1:]))
    if not monotonic:
        raise ValueError("SPHERIC reference time column is not strictly increasing")
    if any(not values for values in series.values()):
        raise ValueError(f"SPHERIC reference has empty channels: {missing_counts}")
    converter.update(
        {
            "source_path": str(path),
            "source_sha256": sha256(path),
            "headers": headers,
            "columns_zero_based": columns,
            "row_count_after_header": len(rows) - 1,
            "missing_value_count_by_label": missing_counts,
            "time_bracket_s": [times[0], times[-1]],
            "strictly_increasing_time": monotonic,
        }
    )
    return series, converter


def interpolate(reference: Sequence[Tuple[float, float]], time: float) -> Optional[float]:
    if not reference or time < reference[0][0] or time > reference[-1][0]:
        return None
    index = bisect.bisect_left([point[0] for point in reference], time)
    if index < len(reference) and reference[index][0] == time:
        return reference[index][1]
    if index == 0 or index == len(reference):
        return None
    before, after = reference[index - 1], reference[index]
    fraction = (time - before[0]) / (after[0] - before[0])
    return before[1] + fraction * (after[1] - before[1])


def trapezoid(values: Sequence[Tuple[float, float]]) -> float:
    return sum((later_time - earlier_time) * (earlier_value + later_value) / 2.0 for (earlier_time, earlier_value), (later_time, later_value) in zip(values, values[1:]))


def comparison_metrics(
    simulation: Sequence[Tuple[float, float]], reference: Sequence[Tuple[float, float]], start: float, end: float,
) -> Dict[str, object]:
    requested = [(time, value) for time, value in simulation if start <= time <= end]
    matched: List[Tuple[float, float, float]] = []
    for time, value in requested:
        expected = interpolate(reference, time)
        if expected is not None:
            matched.append((time, value, expected))
    outside = len(requested) - len(matched)
    if not matched:
        return {
            "status": "insufficient_overlap",
            "window_s": [start, end],
            "reference_bracket_s": [reference[0][0], reference[-1][0]] if reference else None,
            "requested_sample_count": len(requested),
            "matched_samples": 0,
            "excluded_outside_reference_bracket": outside,
        }
    errors = [value - expected for _, value, expected in matched]
    sim_peak = max(matched, key=lambda point: abs(point[1]))
    ref_peak = max(matched, key=lambda point: abs(point[2]))
    error_curve = [(time, value - expected) for time, value, expected in matched]
    return {
        "status": "partial_reference_coverage" if outside else "computed",
        "window_s": [start, end],
        "reference_bracket_s": [reference[0][0], reference[-1][0]],
        "requested_sample_count": len(requested),
        "matched_samples": len(matched),
        "excluded_outside_reference_bracket": outside,
        "actual_time_first_s": matched[0][0],
        "actual_time_last_s": matched[-1][0],
        "rmse": math.sqrt(statistics.fmean(error * error for error in errors)),
        "mae": statistics.fmean(abs(error) for error in errors),
        "signed_mean_bias": statistics.fmean(errors),
        "maximum_absolute_error": max(abs(error) for error in errors),
        "peak_simulated_value": sim_peak[1],
        "peak_reference_value_at_simulated_times": ref_peak[2],
        "peak_amplitude_bias": abs(sim_peak[1]) - abs(ref_peak[2]),
        "peak_time_error_s": sim_peak[0] - ref_peak[0],
        "integrated_signed_error": trapezoid(error_curve),
        "integrated_absolute_error": trapezoid([(time, abs(error)) for time, error in error_curve]),
    }


def write_alignment(path: Path, comparisons: Dict[str, Tuple[Sequence[Tuple[float, float]], Sequence[Tuple[float, float]]]], start: float, end: float) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["series", "time_s", "simulation", "reference", "error", "window"])
        for label, (simulation, reference) in comparisons.items():
            for time, value in simulation:
                if not start <= time <= end:
                    continue
                expected = interpolate(reference, time)
                if expected is None:
                    continue
                writer.writerow([label, f"{time:.12g}", f"{value:.12g}", f"{expected:.12g}", f"{value - expected:.12g}", "full"])


def write_summary(path: Path, comparisons: Dict[str, Dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["series", "status", "matched_samples", "excluded", "rmse", "mae", "maximum_absolute_error", "peak_time_error_s", "integrated_absolute_error"])
        for label, metrics in comparisons.items():
            writer.writerow([
                label,
                metrics.get("status"),
                metrics.get("matched_samples"),
                metrics.get("excluded_outside_reference_bracket"),
                metrics.get("rmse"),
                metrics.get("mae"),
                metrics.get("maximum_absolute_error"),
                metrics.get("peak_time_error_s"),
                metrics.get("integrated_absolute_error"),
            ])


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elevation", type=Path, required=True, help="F1 MeasureTool elevation CSV")
    parser.add_argument("--pressure", type=Path, required=True, help="F1 MeasureTool pressure CSV")
    parser.add_argument("--source", type=Path, default=None, help="SPHERIC test_case_2_exp_data.xls/csv")
    parser.add_argument("--mapping", type=Path, default=None, help="SPHERIC mapping metadata JSON")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--simulation-start", type=float, default=0.0)
    parser.add_argument("--simulation-end", type=float, default=6.0)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    source = (args.source or root / "reference/source/test_case_2_exp_data.xls").resolve()
    mapping_path = (args.mapping or root / "reference/spheric-test2-metadata.json").resolve()
    for path in (args.elevation, args.pressure, source, mapping_path):
        if not path.is_file():
            parser.error(f"missing input: {path}")
    if args.output_dir.exists():
        parser.error(f"output directory already exists; use a new path: {args.output_dir}")
    if not args.simulation_start < args.simulation_end:
        parser.error("require simulation-start < simulation-end")
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    height_points, pressure_points = expected_mapping(mapping)
    elevation, elevation_meta = read_measurement_csv(args.elevation.resolve(), height_points, "elevation")
    pressure, pressure_meta = read_measurement_csv(args.pressure.resolve(), pressure_points, "pressure")
    reference, reference_meta = read_spheric_reference(source)
    windows = {"simulation_0_6s": (args.simulation_start, args.simulation_end)}
    comparisons: Dict[str, Tuple[Sequence[Tuple[float, float]], Sequence[Tuple[float, float]]]] = {}
    for label in [f"H{i}" for i in range(1, 5)]:
        comparisons[label] = (elevation[label], reference[label])
    for label in [f"P{i}" for i in range(1, 9)]:
        comparisons[label] = (pressure[label], reference[label])
    metric_report = {
        label: comparison_metrics(simulation, ref, *windows["simulation_0_6s"])
        for label, (simulation, ref) in comparisons.items()
    }
    pressure_impact = {
        label: {
            "window_s": [args.simulation_start, args.simulation_end],
            "peak_simulated_pa": metric_report[label].get("peak_simulated_value"),
            "peak_reference_pa": metric_report[label].get("peak_reference_value_at_simulated_times"),
            "peak_amplitude_bias_pa": metric_report[label].get("peak_amplitude_bias"),
            "peak_absolute_amplitude_error_pa": abs(metric_report[label]["peak_amplitude_bias"])
            if metric_report[label].get("peak_amplitude_bias") is not None
            else None,
            "peak_time_error_s": metric_report[label].get("peak_time_error_s"),
            "integrated_signed_error_pa_s": metric_report[label].get("integrated_signed_error"),
            "integrated_absolute_error_pa_s": metric_report[label].get("integrated_absolute_error"),
            "impact_window_definition": "full official 0..6 s run; SPHERIC release does not define a narrower impact interval",
        }
        for label in [f"P{i}" for i in range(1, 9)]
    }
    source_files = {
        "source_page": mapping.get("source_page"),
        "source_archive": mapping.get("source_archive"),
        "source_archive_sha256": mapping.get("archive_sha256"),
        "workbook_path": str(source),
        "workbook_sha256": sha256(source),
        "metadata_path": str(mapping_path),
        "metadata_sha256": sha256(mapping_path),
    }
    report: Dict[str, object] = {
        "schema": "ds-data-02.upstream-first.f1-spheric-comparison.v1",
        "family_id": "F1",
        "case_id": "UF_F1_MDBC_DAMBREAK3D",
        "reference_role": "diagnostic_experimental_reference",
        "upstream_case_id": "CaseDamBreak3D",
        "inputs": {"elevation": elevation_meta, "pressure": pressure_meta, "spheric_reference": reference_meta, "source_files": source_files},
        "controls": {
            "simulation_window_s": [args.simulation_start, args.simulation_end],
            "interpolation": "linear inside SPHERIC source bracket only",
            "phase_shift_or_retiming": False,
            "pressure_impact_window_s": [args.simulation_start, args.simulation_end],
            "coordinate_mapping": mapping["coordinate_mapping"],
            "sensor_labels_preserved": True,
        },
        "comparisons": metric_report,
        "pressure_impact_metrics": pressure_impact,
        "coverage_checks": {
            "simulation_time_bracket_by_channel": {
                **{label: elevation_meta["time_bracket_s"] for label in elevation},
                **{label: pressure_meta["time_bracket_s"] for label in pressure},
            },
            "reference_time_bracket_s": reference_meta["time_bracket_s"],
            "source_monotonic_time": reference_meta["strictly_increasing_time"],
            "all_elevation_labels_present": all(elevation.values()),
            "all_pressure_labels_present": all(pressure.values()),
            "missing_value_count_by_label": {
                **elevation_meta["missing_value_count_by_label"],
                **pressure_meta["missing_value_count_by_label"],
                **reference_meta["missing_value_count_by_label"],
            },
            "excluded_outside_reference_bracket_by_label": {
                label: metric_report[label]["excluded_outside_reference_bracket"] for label in metric_report
            },
        },
        "uncertainty": mapping["uncertainty"],
        "acceptance": {
            "status": "diagnostic_only_no_source_derived_tolerance",
            "source_tolerance_declared": False,
            "does_not_establish_product_acceptance": True,
        },
        "flags": [
            "sensor_labels_preserved_under_explicit_x_reflection",
            "H4_is_reservoir_history_and_was_not_sorted_by_raw_x",
            "actual_measuretool_times_preserved",
            "no_extrapolation_or_phase_shift",
            "pressure_metrics_include_full_run_integral_because_source_defines_no_narrower_impact_interval",
            "no_source_uncertainty_or_acceptance_threshold_invented",
        ],
    }
    args.output_dir.mkdir(parents=True)
    write_alignment(args.output_dir / "spheric-aligned-observations.csv", comparisons, args.simulation_start, args.simulation_end)
    write_summary(args.output_dir / "spheric-comparison-summary.csv", metric_report)
    (args.output_dir / "spheric-comparison-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(args.output_dir / "spheric-comparison-report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
