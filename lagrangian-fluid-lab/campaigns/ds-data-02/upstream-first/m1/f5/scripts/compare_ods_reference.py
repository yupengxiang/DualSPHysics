#!/usr/bin/env python3
"""Compare official F5 MeasureTool CSV products with the official ODS table.

The script is deliberately dependency-free.  It reads only the two small
MeasureTool CSV products and the REGULAR_BEACH sheet from the immutable ODS;
native particle arrays are never opened.  Actual MeasureTool timestamps are
kept.  The ODS is linearly interpolated only inside its time brackets, and no
phase shift or retiming is performed.

The output is diagnostic calibration evidence.  A provisional F5 gate is
reported for the frozen [2, 30] s window, but the report never labels the
2-D calibration as a 3-D qualification or as experimental acceptance.

Example (after the shared runner and extraction worker finish)::

    compare_ods_reference.py \
      --elevation /nas/.../measuretool/_elevation.csv \
      --velocity /nas/.../measuretool/_velocity.csv \
      --output-dir /nas/.../comparisons/ods-001
"""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import math
import re
import statistics
import sys
import unicodedata
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from xml.etree import ElementTree as ET


TABLE_NS = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
TEXT_NS = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
OFFICE_NS = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
TABLE = "{" + TABLE_NS + "}"
TEXT = "{" + TEXT_NS + "}"
OFFICE = "{" + OFFICE_NS + "}"
MAX_ODS_COLUMNS = 128


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = value.casefold().replace("µ", "u")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def number(value: object) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip().replace("\ufeff", "")
    if not text or text.casefold() in {"nan", "na", "n/a", "null", "none", "-"}:
        return None
    # MeasureTool/ODS files in this campaign use decimal points.  Accept a
    # decimal comma as a useful read-only fallback when a local CSV export has
    # been opened and saved by a locale-sensitive spreadsheet.
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    try:
        result = float(text)
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def deduplicate(pairs: Iterable[Tuple[float, float]]) -> List[Tuple[float, float]]:
    values: Dict[float, List[float]] = {}
    for time, value in pairs:
        if math.isfinite(time) and math.isfinite(value):
            values.setdefault(float(time), []).append(float(value))
    return [(time, statistics.fmean(values[time])) for time in sorted(values)]


def read_csv_rows(path: Path) -> List[List[str]]:
    lines: List[str] = []
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as stream:
        for line in stream:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("//"):
                continue
            lines.append(line)
    if not lines:
        raise ValueError(f"CSV has no data lines: {path}")
    sample = "".join(lines[:20])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        counts = {delimiter: sample.count(delimiter) for delimiter in ",;\t"}
        delimiter = max(counts, key=counts.get)
        dialect = csv.excel
        dialect.delimiter = delimiter
    return [row for row in csv.reader(lines, dialect) if any(cell.strip() for cell in row)]


def find_header(rows: Sequence[Sequence[str]]) -> int:
    for index, row in enumerate(rows):
        names = [normalize(cell) for cell in row]
        if any("time" in name for name in names) and sum(bool(name) for name in names) >= 2:
            return index
    raise ValueError("MeasureTool CSV has no recognizable time/header row")


def column_index(headers: Sequence[str], predicate) -> Optional[int]:
    for index, header in enumerate(headers):
        if predicate(normalize(header)):
            return index
    return None


def numeric_column_score(rows: Sequence[Sequence[str]], index: int) -> int:
    return sum(number(row[index]) is not None for row in rows[:50] if index < len(row))


def time_column(headers: Sequence[str]) -> int:
    index = column_index(headers, lambda name: "time" in name)
    if index is None:
        raise ValueError("MeasureTool CSV header has no time column")
    return index


def x_from_header(name: str) -> Optional[int]:
    """Return a point x-coordinate when a CSV header states one explicitly."""
    compact = normalize(name)
    for x in (5, 6, 7):
        # Covers x=5m, xpos:5, point at x 5, and x 5 in a generated header.
        if re.search(rf"(?:^| )x\s*{x}(?:\s*m)?(?:$| )", compact):
            return x
        if re.search(rf"(?:^| )(?:xpos|at)\s*{x}(?:\s*m)?(?:$| )", compact):
            return x
    return None


def is_elevation_value_header(name: str) -> bool:
    if any(token in name for token in ("time", "point", "probe", "sensor", "id", "coord")):
        return False
    return any(token in name for token in ("eta", "height", "elevation", "surface", "z"))


def is_velocity_value_header(name: str) -> bool:
    if any(token in name for token in ("time", "point", "probe", "sensor", "id", "coord")):
        return False
    return any(token in name for token in ("vel", "velocity", "vx", "vy", "vz", " u", " w"))


def parse_wide_columns(
    rows: Sequence[Sequence[str]], time_index: int, indices: Dict[str, int]
) -> Dict[str, List[Tuple[float, float]]]:
    result: Dict[str, List[Tuple[float, float]]] = {key: [] for key in indices}
    for row in rows:
        if time_index >= len(row):
            continue
        time = number(row[time_index])
        if time is None:
            continue
        for key, value_index in indices.items():
            if value_index < len(row):
                value = number(row[value_index])
                if value is not None:
                    result[key].append((time, value))
    return {key: deduplicate(pairs) for key, pairs in result.items()}


def choose_elevation_columns(
    headers: Sequence[str], body: Sequence[Sequence[str]]
) -> Tuple[Dict[str, int], List[str]]:
    warnings: List[str] = []
    explicit: Dict[int, int] = {}
    for index, header in enumerate(headers):
        if not is_elevation_value_header(normalize(header)):
            continue
        x = x_from_header(header)
        if x is not None:
            explicit[x] = index
        # Some MeasureTool builds label the three elevation columns H1/H2/H3
        # rather than copying the x-coordinate from POINTSLIST.
        match = re.search(r"(?:^| )h([123])(?:$| )", normalize(header))
        if match and int(match.group(1)) in (1, 2, 3):
            explicit.setdefault(4 + int(match.group(1)), index)
    if all(x in explicit for x in (5, 6, 7)):
        return {f"x{x}": explicit[x] for x in (5, 6, 7)}, warnings

    candidates = [
        index
        for index, header in enumerate(headers)
        if is_elevation_value_header(normalize(header))
        and numeric_column_score(body, index) > 0
    ]
    if len(candidates) >= 3:
        warnings.append(
            "elevation_point_mapping=positional_first_three_value_columns; "
            "CSV headers did not expose x=5,6,7 labels"
        )
        return {f"x{x}": candidates[i] for i, x in enumerate((5, 6, 7))}, warnings

    # A few older MeasureTool exports call the scalar simply Z.  Exclude
    # obvious coordinates and use the first three numeric non-time fields only
    # as a final, explicitly recorded fallback.
    fallback = [
        index
        for index, header in enumerate(headers)
        if index != time_column(headers)
        and numeric_column_score(body, index) > 0
        and not any(token in normalize(header) for token in ("time", "id", "point", "probe", "x", "y"))
    ]
    if len(fallback) >= 3:
        warnings.append(
            "elevation_point_mapping=positional_numeric_columns; verify against "
            "the three official POINTSLIST blocks before accepting"
        )
        return {f"x{x}": fallback[i] for i, x in enumerate((5, 6, 7))}, warnings
    raise ValueError(
        "could not identify three elevation columns for x=5,6,7; "
        f"headers={list(headers)!r}"
    )


def component_column(name: str, component: str) -> bool:
    compact = normalize(name).replace(" ", "")
    if component == "x":
        return compact in {"vx", "velx", "velocityx", "u"} or compact.endswith("velx")
    if component == "z":
        return compact in {"vz", "velz", "velocityz", "w"} or compact.endswith("velz")
    return False


def choose_velocity_columns(
    headers: Sequence[str], body: Sequence[Sequence[str]]
) -> Tuple[Dict[str, int], List[str]]:
    warnings: List[str] = []
    selected: Dict[str, int] = {}
    for component in ("x", "z"):
        for index, header in enumerate(headers):
            name = normalize(header)
            if component_column(name, component) and numeric_column_score(body, index) > 0:
                selected.setdefault(f"vel{component}", index)
    if len(selected) == 2:
        return selected, warnings

    candidates = [
        index
        for index, header in enumerate(headers)
        if is_velocity_value_header(normalize(header))
        and numeric_column_score(body, index) > 0
    ]
    if len(candidates) >= 2:
        warnings.append(
            "velocity_component_mapping=positional_first_two_value_columns; "
            "CSV headers did not expose VelX/VelZ labels"
        )
        return {"velx": candidates[0], "velz": candidates[1]}, warnings

    fallback = [
        index
        for index, header in enumerate(headers)
        if numeric_column_score(body, index) > 0
        and not any(token in normalize(header) for token in ("time", "id", "point", "probe", "x", "y"))
    ]
    if len(fallback) >= 2:
        warnings.append(
            "velocity_component_mapping=positional_numeric_columns; verify the "
            "MeasureTool vector-column order before accepting"
        )
        return {"velx": fallback[0], "velz": fallback[1]}, warnings
    raise ValueError(
        "could not identify VelX and VelZ columns; " f"headers={list(headers)!r}"
    )


def read_elevation_csv(path: Path) -> Tuple[Dict[str, List[Tuple[float, float]]], Dict[str, object]]:
    rows = read_csv_rows(path)
    header_row = find_header(rows)
    headers = rows[header_row]
    body = rows[header_row + 1 :]
    time_index = time_column(headers)
    indices, warnings = choose_elevation_columns(headers, body)
    series = parse_wide_columns(body, time_index, indices)
    if any(not series[key] for key in ("x5", "x6", "x7")):
        raise ValueError(f"one or more elevation columns contain no numeric data: {indices}")
    return series, {
        "path": str(path),
        "sha256": sha256_file(path),
        "header_row_zero_based": header_row,
        "headers": list(headers),
        "column_indices_zero_based": indices,
        "warnings": warnings,
        "row_count_after_header": len(body),
    }


def read_velocity_csv(path: Path) -> Tuple[Dict[str, List[Tuple[float, float]]], Dict[str, object]]:
    rows = read_csv_rows(path)
    header_row = find_header(rows)
    headers = rows[header_row]
    body = rows[header_row + 1 :]
    time_index = time_column(headers)
    indices, warnings = choose_velocity_columns(headers, body)
    series = parse_wide_columns(body, time_index, indices)
    if any(not series[key] for key in ("velx", "velz")):
        raise ValueError(f"one or more velocity columns contain no numeric data: {indices}")
    return series, {
        "path": str(path),
        "sha256": sha256_file(path),
        "header_row_zero_based": header_row,
        "headers": list(headers),
        "column_indices_zero_based": indices,
        "warnings": warnings,
        "row_count_after_header": len(body),
    }


def ods_cell_text(cell: ET.Element) -> str:
    text = "".join(cell.itertext()).strip()
    if text:
        return text
    value = cell.get(OFFICE + "value")
    return value or ""


def read_ods_sheet(path: Path, requested_name: str) -> List[List[str]]:
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("content.xml"))
    for sheet in root.findall(".//" + TABLE + "table"):
        if sheet.get(TABLE + "name") != requested_name:
            continue
        rows: List[List[str]] = []
        for row_element in sheet.findall(TABLE + "table-row"):
            row_values: List[str] = []
            row_repeat = int(row_element.get(TABLE + "number-rows-repeated", "1"))
            for cell in row_element.findall(TABLE + "table-cell"):
                value = ods_cell_text(cell)
                repeat = int(cell.get(TABLE + "number-columns-repeated", "1"))
                if len(row_values) >= MAX_ODS_COLUMNS:
                    break
                row_values.extend([value] * min(repeat, MAX_ODS_COLUMNS - len(row_values)))
            # Empty trailing cells are irrelevant, but repeated rows must be
            # retained because some ODS writers use them for blank data rows.
            # This workbook has a 1,046,081-row blank tail and 16,384-column
            # blank cells.  Expanding those declarations would be wasteful and
            # does not change any populated observation; retain one blank row.
            if not any(row_values):
                row_repeat = 1
            else:
                row_repeat = min(row_repeat, 4096)
            for _ in range(row_repeat):
                rows.append(list(row_values))
        return rows
    raise ValueError(f"ODS sheet not found: {requested_name!r} in {path}")


def ods_column(headers: Sequence[str], predicate) -> int:
    for index, header in enumerate(headers):
        if predicate(normalize(header)):
            return index
    raise ValueError(f"ODS REGULAR_BEACH header missing required column: {list(headers)!r}")


def read_ods_reference(path: Path) -> Tuple[Dict[str, List[Tuple[float, float]]], Dict[str, object]]:
    rows = read_ods_sheet(path, "REGULAR_BEACH")
    if len(rows) < 5:
        raise ValueError("REGULAR_BEACH has no data rows")
    header_index = next(
        (
            index
            for index, row in enumerate(rows)
            if sum(normalize(cell) == "time s" for cell in row) >= 3
            and any("eta" in normalize(cell) for cell in row)
            and any("vel" in normalize(cell) for cell in row)
        ),
        None,
    )
    if header_index is None:
        raise ValueError("REGULAR_BEACH has no header row")
    headers = rows[header_index]

    def has(*tokens: str):
        return lambda name: all(token in name for token in tokens)

    columns = {
        "theory_eta": ods_column(headers, has("eta", "2ndstokes", "x 6m")),
        "theory_velx": ods_column(headers, has("velx", "2ndstokes", "x 6m")),
        "theory_velz": ods_column(headers, has("velz", "2ndstokes", "x 6m")),
        "sph_eta_x5": ods_column(headers, has("eta", "sph", "x 5m")),
        "sph_eta_x6": ods_column(headers, has("eta", "sph", "x 6m")),
        "sph_eta_x7": ods_column(headers, has("eta", "sph", "x 7m")),
        "sph_velx": ods_column(headers, has("velx", "sph", "x 6m")),
        "sph_velz": ods_column(headers, has("velz", "sph", "x 6m")),
    }
    theory_time = ods_column(headers, lambda name: name == "time s")
    # There are two Time [s] columns in the sheet.  The second and third are
    # SPH times; keep their actual values, rather than assuming the theory grid.
    time_columns = [index for index, header in enumerate(headers) if normalize(header) == "time s"]
    if len(time_columns) < 3:
        raise ValueError("REGULAR_BEACH must contain theory, elevation, and velocity time columns")
    sph_elevation_time, sph_velocity_time = time_columns[1], time_columns[2]

    series: Dict[str, List[Tuple[float, float]]] = {key: [] for key in columns}
    for row in rows[header_index + 1 :]:
        if len(row) <= max(columns.values()):
            continue
        times = {
            "theory": number(row[theory_time]),
            "sph_elevation": number(row[sph_elevation_time]),
            "sph_velocity": number(row[sph_velocity_time]),
        }
        for key, index in columns.items():
            family = "theory" if key.startswith("theory_") else (
                "sph_elevation" if key.startswith("sph_eta_") else "sph_velocity"
            )
            time = times[family]
            value = number(row[index])
            if time is not None and value is not None:
                series[key].append((time, value))
    series = {key: deduplicate(values) for key, values in series.items()}
    if any(not values for values in series.values()):
        raise ValueError(f"one or more ODS reference columns contain no numeric data: {columns}")
    return series, {
        "path": str(path),
        "sha256": sha256_file(path),
        "sheet": "REGULAR_BEACH",
        "sheet_row_count": len(rows),
        "header_row_zero_based": header_index,
        "pre_header_metadata": [
            [cell for cell in row if cell.strip()]
            for row in rows[:header_index]
            if any(cell.strip() for cell in row)
        ],
        "headers": list(headers),
        "column_indices_zero_based": columns,
        "time_columns_zero_based": {
            "theory": theory_time,
            "sph_elevation": sph_elevation_time,
            "sph_velocity": sph_velocity_time,
        },
    }


def interpolate(series: Sequence[Tuple[float, float]], time: float) -> Optional[float]:
    if not series or time < series[0][0] or time > series[-1][0]:
        return None
    times = [point[0] for point in series]
    right = bisect.bisect_left(times, time)
    if right < len(series) and math.isclose(series[right][0], time, rel_tol=0.0, abs_tol=1e-12):
        return series[right][1]
    if right == 0 or right == len(series):
        return None
    left_time, left_value = series[right - 1]
    right_time, right_value = series[right]
    fraction = (time - left_time) / (right_time - left_time)
    return left_value + fraction * (right_value - left_value)


def comparison_metrics(
    simulation: Sequence[Tuple[float, float]],
    reference: Sequence[Tuple[float, float]],
    start: float,
    end: float,
) -> Dict[str, object]:
    matched: List[Tuple[float, float, float]] = []
    requested_times = [time for time, _ in simulation if start <= time <= end]
    for time, simulated in simulation:
        if start <= time <= end:
            expected = interpolate(reference, time)
            if expected is not None:
                matched.append((time, simulated, expected))
    if not matched:
        return {
            "status": "insufficient_overlap",
            "n": 0,
            "window_s": [start, end],
            "reference_bracket_s": [reference[0][0], reference[-1][0]] if reference else None,
            "excluded_outside_reference_bracket": True,
        }
    outside_bracket = sum(
        time < reference[0][0] or time > reference[-1][0] for time in requested_times
    )
    status = "partial_reference_coverage" if outside_bracket else "computed"
    errors = [simulated - expected for _, simulated, expected in matched]
    squared = [error * error for error in errors]
    sim_peak = max(matched, key=lambda point: abs(point[1]))
    ref_peak = max(matched, key=lambda point: abs(point[2]))
    return {
        "status": status,
        "n": len(matched),
        "window_s": [start, end],
        "reference_bracket_s": [reference[0][0], reference[-1][0]],
        "requested_sample_count": len(requested_times),
        "excluded_outside_reference_bracket": outside_bracket,
        "actual_time_first_s": matched[0][0],
        "actual_time_last_s": matched[-1][0],
        "rmse": math.sqrt(statistics.fmean(squared)),
        "mae": statistics.fmean(abs(error) for error in errors),
        "signed_mean_bias": statistics.fmean(errors),
        "maximum_absolute_error": max(abs(error) for error in errors),
        "peak_simulated_value": sim_peak[1],
        "peak_reference_value_at_simulated_times": ref_peak[2],
        "peak_amplitude_bias": abs(sim_peak[1]) - abs(ref_peak[2]),
        "peak_time_error_s": sim_peak[0] - ref_peak[0],
    }


def maximum_reference_abs(series: Sequence[Tuple[float, float]], start: float, end: float) -> float:
    values = [abs(value) for time, value in series if start <= time <= end]
    return max(values) if values else 0.0


def arrival_diagnostic(series: Sequence[Tuple[float, float]], start: float, end: float) -> Dict[str, object]:
    usable = [(time, value) for time, value in series if start <= time <= end]
    if not usable:
        return {"status": "no_samples", "arrival_time_s": None}
    baseline_values = [value for time, value in usable if time < min(start + 0.5, end)]
    baseline = statistics.median(baseline_values) if baseline_values else usable[0][1]
    scale = max(abs(value - baseline) for _, value in usable)
    threshold = max(1.0e-4, 0.05 * scale)
    arrival = next((time for time, value in usable if abs(value - baseline) >= threshold), None)
    return {
        "status": "computed" if arrival is not None else "no_threshold_crossing",
        "arrival_time_s": arrival,
        "baseline_value": baseline,
        "threshold_absolute": threshold,
        "threshold_rule": "max(1e-4, 0.05 * max_abs_deviation_in_report_window)",
    }


def propagation_report(elevation: Dict[str, List[Tuple[float, float]]], end: float) -> Dict[str, object]:
    arrivals = {
        key: arrival_diagnostic(values, 0.0, end) for key, values in elevation.items()
    }
    times = {key: value["arrival_time_s"] for key, value in arrivals.items()}
    present = {key: time for key, time in times.items() if time is not None}
    ordered = [key for key, _ in sorted(present.items(), key=lambda item: item[1])]
    expected = ["x5", "x6", "x7"]
    if len(ordered) < 3:
        status = "incomplete"
    elif ordered == expected:
        status = "consistent"
    else:
        status = "inconsistent"
    deltas = {}
    for earlier, later in (("x5", "x6"), ("x6", "x7"), ("x5", "x7")):
        if times[earlier] is not None and times[later] is not None:
            deltas[f"{later}_minus_{earlier}_s"] = times[later] - times[earlier]
    return {
        "status": status,
        "expected_arrival_order": expected,
        "observed_arrival_order": ordered,
        "arrival_diagnostics": arrivals,
        "arrival_deltas_s": deltas,
        "interpretation": "diagnostic only; physical propagation delay is retained and is never removed by time shifting",
    }


def write_alignment(
    output: Path,
    comparisons: Sequence[Tuple[str, Sequence[Tuple[float, float]], Sequence[Tuple[float, float]]]],
    start: float,
    end: float,
    startup_end: float,
) -> None:
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["series", "time_s", "simulation", "reference", "error", "window"])
        for label, simulation, reference in comparisons:
            for time, simulated in simulation:
                if not start <= time <= end:
                    continue
                expected = interpolate(reference, time)
                if expected is None:
                    continue
                writer.writerow(
                    [
                        label,
                        f"{time:.12g}",
                        f"{simulated:.12g}",
                        f"{expected:.12g}",
                        f"{simulated - expected:.12g}",
                        "startup" if time < startup_end else "primary",
                    ]
                )


def write_summary(output: Path, report: Dict[str, object]) -> None:
    rows: List[Tuple[str, str, Dict[str, object]]] = []
    for label, windows in report["comparisons"].items():
        for window, metrics in windows.items():
            rows.append((label, window, metrics))
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["series", "window", "status", "n", "rmse", "mae", "bias", "max_abs_error", "peak_time_error_s"])
        for label, window, metrics in rows:
            writer.writerow(
                [
                    label,
                    window,
                    metrics.get("status"),
                    metrics.get("n", 0),
                    metrics.get("rmse"),
                    metrics.get("mae"),
                    metrics.get("signed_mean_bias"),
                    metrics.get("maximum_absolute_error"),
                    metrics.get("peak_time_error_s"),
                ]
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elevation", type=Path, required=True, help="MeasureTool elevation CSV")
    parser.add_argument("--velocity", type=Path, required=True, help="MeasureTool velocity CSV")
    parser.add_argument(
        "--ods",
        type=Path,
        default=None,
        help="official CasePiston_SPHvsTheory.ods (required unless inferred)",
    )
    parser.add_argument("--output-dir", type=Path, required=True, help="new comparison output directory")
    parser.add_argument("--simulation-start", type=float, default=0.0)
    parser.add_argument("--simulation-end", type=float, default=30.0)
    parser.add_argument("--startup-end", type=float, default=2.0)
    parser.add_argument("--primary-start", type=float, default=2.0)
    return parser


def inferred_ods_path() -> Path:
    return Path(__file__).resolve().parents[1] / "input" / "CasePiston_SPHvsTheory.ods"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    ods = (args.ods or inferred_ods_path()).resolve()
    elevation = args.elevation.resolve()
    velocity = args.velocity.resolve()
    output = args.output_dir.resolve()
    for path in (elevation, velocity, ods):
        if not path.is_file():
            parser.error(f"missing input file: {path}")
    if output.exists():
        parser.error(f"output directory already exists; use a new path: {output}")
    if not (args.simulation_start < args.primary_start <= args.simulation_end):
        parser.error("require simulation_start < primary_start <= simulation_end")
    if not (args.simulation_start < args.startup_end <= args.simulation_end):
        parser.error("require simulation_start < startup_end <= simulation_end")

    try:
        elevation_series, elevation_meta = read_elevation_csv(elevation)
        velocity_series, velocity_meta = read_velocity_csv(velocity)
        ods_series, ods_meta = read_ods_reference(ods)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"comparison input error: {error}", file=sys.stderr)
        return 2

    windows = {
        "startup_0_2s": (args.simulation_start, args.startup_end),
        "primary_2_30s": (args.primary_start, args.simulation_end),
        "full_common_0_30s": (args.simulation_start, args.simulation_end),
    }
    comparisons = {
        "eta_x5": (elevation_series["x5"], ods_series["sph_eta_x5"], ods_series["theory_eta"]),
        "eta_x6": (elevation_series["x6"], ods_series["sph_eta_x6"], ods_series["theory_eta"]),
        "eta_x7": (elevation_series["x7"], ods_series["sph_eta_x7"], ods_series["theory_eta"]),
        "velx_x6_z0p4": (velocity_series["velx"], ods_series["sph_velx"], ods_series["theory_velx"]),
        "velz_x6_z0p4": (velocity_series["velz"], ods_series["sph_velz"], ods_series["theory_velz"]),
    }
    metric_report: Dict[str, Dict[str, Dict[str, object]]] = {}
    for label, (_, _, reference) in comparisons.items():
        simulation = comparisons[label][0]
        metric_report[label] = {
            window_name: comparison_metrics(simulation, reference, *window)
            for window_name, window in windows.items()
        }

    primary_surface = metric_report["eta_x6"]["primary_2_30s"]
    primary_velx = metric_report["velx_x6_z0p4"]["primary_2_30s"]
    primary_velz = metric_report["velz_x6_z0p4"]["primary_2_30s"]
    surface_limit = max(0.005, 0.10 * 0.15)
    timing_limit = 0.10 * 2.0
    velocity_limit = max(0.05, 0.10 * max(
        maximum_reference_abs(ods_series["theory_velx"], args.primary_start, args.simulation_end),
        maximum_reference_abs(ods_series["theory_velz"], args.primary_start, args.simulation_end),
    ))

    def gate(metric: Dict[str, object], value_key: str, limit: float) -> Dict[str, object]:
        value = metric.get(value_key)
        timing = metric.get("peak_time_error_s")
        if metric.get("status") == "partial_reference_coverage":
            return {
                "status": "insufficient_reference_coverage",
                "limit": limit,
                "timing_limit_s": timing_limit,
                "matched_samples": metric.get("n", 0),
                "excluded_samples": metric.get("excluded_outside_reference_bracket", 0),
            }
        if metric.get("status") != "computed" or value is None or timing is None:
            return {"status": "insufficient_overlap", "limit": limit, "timing_limit_s": timing_limit}
        return {
            "status": "provisional_pass" if abs(float(value)) <= limit and abs(float(timing)) <= timing_limit else "provisional_fail",
            "value": value,
            "limit": limit,
            "peak_time_error_s": timing,
            "timing_limit_s": timing_limit,
        }

    primary_gate = {
        "eta_x6": gate(primary_surface, "rmse", surface_limit),
        "velx_x6_z0p4": gate(primary_velx, "rmse", velocity_limit),
        "velz_x6_z0p4": gate(primary_velz, "rmse", velocity_limit),
    }
    report: Dict[str, object] = {
        "schema": "ds-data-02.upstream-first.f5-ods-comparison.v1",
        "family_id": "F5",
        "case_id": "UF_F5_PISTON_REG",
        "reference_role": "calibration_2d",
        "upstream_case_id": "CasePistonBeach_REG",
        "inputs": {"elevation": elevation_meta, "velocity": velocity_meta, "ods": ods_meta},
        "controls": {
            "simulation_window_s": [args.simulation_start, args.simulation_end],
            "startup_report_window_s": [args.simulation_start, args.startup_end],
            "primary_comparison_window_s": [args.primary_start, args.simulation_end],
            "ods_theory_window_s": [ods_series["theory_eta"][0][0], ods_series["theory_eta"][-1][0]],
            "actual_common_window_s": [
                max(args.simulation_start, ods_series["theory_eta"][0][0]),
                min(args.simulation_end, ods_series["theory_eta"][-1][0]),
            ],
            "interpolation": "linear inside reference brackets only",
            "phase_shift_or_retiming": False,
        },
        "comparisons": metric_report,
        "propagation_delay": propagation_report(elevation_series, args.simulation_end),
        "provisional_calibration_gate": {
            "surface_rmse_limit_m": surface_limit,
            "velocity_rmse_limit_m_per_s": velocity_limit,
            "timing_limit_s": timing_limit,
            "primary": primary_gate,
            "status": "diagnostic_calibration_only",
            "does_not_establish_3d_qualification": True,
            "does_not_establish_experimental_acceptance": True,
        },
        "flags": [
            "startup_window_reported_separately_and_excluded_from_primary_gate",
            "physical_sensor_propagation_delays_preserved",
            "no_phase_shift_or_retiming",
            "ods_is_official_analytical_reference_not_independent_laboratory_observation",
            "reference_bracket_coverage_is_reported_and_never_extrapolated",
        ],
    }
    output.mkdir(parents=True)
    write_alignment(
        output / "aligned-observations.csv",
        [(label, simulation, reference) for label, (simulation, _, reference) in comparisons.items()],
        args.simulation_start,
        args.simulation_end,
        args.startup_end,
    )
    write_summary(output / "comparison-summary.csv", report)
    with (output / "comparison-report.json").open("w", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(output / "comparison-report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
