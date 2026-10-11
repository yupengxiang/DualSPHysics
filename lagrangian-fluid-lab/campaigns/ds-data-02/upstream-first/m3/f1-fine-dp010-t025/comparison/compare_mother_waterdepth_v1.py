#!/usr/bin/env python3
"""Compare a fine F1 depth derivative with the accepted fine mother.

This worker deliberately reuses the strict CSV reader from M1's
``compare_spheric_reference_v2.py``.  It therefore binds every H/P column by
its exact MeasureTool header and declared point coordinates, rejects positional
fallbacks, and preserves the actual time samples.  The child is evaluated at
its native MeasureTool times; the mother is linearly interpolated only inside
the two native time brackets.  No phase shift, retiming, extrapolation,
experimental credit, or acceptance threshold is introduced here.

The worker is an audit/comparison task.  It reads completed receipts,
manifests, and the two small MeasureTool CSVs for each case.  It never reads
native solver frames and never launches a solver, GenCase, or postprocessor.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from xml.etree import ElementTree as ET


LABELS: Tuple[str, ...] = tuple([f"H{i}" for i in range(1, 5)] + [f"P{i}" for i in range(1, 9)])
HEIGHT_LABELS = LABELS[:4]
PRESSURE_LABELS = LABELS[4:]
TIME_TOLERANCE_S = 1.0e-6


class ComparisonError(RuntimeError):
    """Raised when the frozen comparison contract is not satisfied."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_binding(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise ComparisonError(f"missing required file: {path}")
    return {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": sha256(path)}


def read_json(path: Path, role: str) -> Dict[str, Any]:
    if not path.is_file():
        raise ComparisonError(f"missing {role}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ComparisonError(f"cannot read {role}: {path}: {error}") from error
    if not isinstance(value, dict):
        raise ComparisonError(f"{role} must contain a JSON object: {path}")
    return value


def load_m1_parser(path: Path) -> Any:
    """Load the existing strict M1 parser without copying or modifying it."""
    if not path.is_file():
        raise ComparisonError(f"missing M1 parser: {path}")
    spec = importlib.util.spec_from_file_location("m1_compare_spheric_reference_v2", path)
    if spec is None or spec.loader is None:
        raise ComparisonError(f"cannot import M1 parser: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_receipt(path: Path, role: str, case_id: str, attempt_id: str) -> Dict[str, Any]:
    receipt = read_json(path, role)
    request = receipt.get("request")
    if not isinstance(request, dict):
        raise ComparisonError(f"{role} has no request object: {path}")
    if request.get("case_id") != case_id:
        raise ComparisonError(
            f"{role} case mismatch: expected {case_id}, got {request.get('case_id')!r}: {path}"
        )
    if request.get("attempt_id") != attempt_id:
        raise ComparisonError(
            f"{role} attempt mismatch: expected {attempt_id}, got {request.get('attempt_id')!r}: {path}"
        )
    if receipt.get("status") != "completed":
        raise ComparisonError(f"{role} is not completed (status={receipt.get('status')!r}): {path}")
    returncode = receipt.get("returncode", receipt.get("exit_code"))
    if returncode not in (None, 0):
        raise ComparisonError(f"{role} did not complete successfully (returncode={returncode!r}): {path}")
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "case_id": case_id,
        "attempt_id": attempt_id,
        "status": receipt.get("status"),
        "returncode": returncode,
    }


def validate_postprocess_manifest(
    path: Path,
    role: str,
    case_id: str,
    elevation_path: Path,
    pressure_path: Path,
) -> Dict[str, Any]:
    manifest = read_json(path, role)
    if manifest.get("case_id") != case_id:
        raise ComparisonError(
            f"{role} case mismatch: expected {case_id}, got {manifest.get('case_id')!r}: {path}"
        )
    primary = [str(value) for value in manifest.get("primary_observation_files", [])]
    auxiliary = [str(value) for value in manifest.get("auxiliary_observation_files", [])]
    if str(elevation_path.resolve()) not in [str(Path(value).resolve()) for value in primary]:
        raise ComparisonError(f"{role} does not bind the supplied elevation CSV: {path}")
    if str(pressure_path.resolve()) not in [str(Path(value).resolve()) for value in auxiliary]:
        raise ComparisonError(f"{role} does not bind the supplied pressure CSV: {path}")
    window = manifest.get("time_policy", {}).get("simulation_window_s")
    if window != [0.0, 6.0]:
        raise ComparisonError(f"{role} must declare the full [0, 6] s window, got {window!r}: {path}")
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "case_id": case_id,
        "schema": manifest.get("schema"),
        "simulation_window_s": window,
    }


def validate_mother_acceptance(path: Path, case_id: str) -> Dict[str, Any]:
    decision = read_json(path, "mother acceptance decision")
    if decision.get("case_id") != case_id:
        raise ComparisonError(
            f"mother acceptance case mismatch: expected {case_id}, got {decision.get('case_id')!r}"
        )
    if decision.get("status") != "accepted_for_scoped_internal_numerical_transport_diagnostics":
        raise ComparisonError(f"mother acceptance status is not scoped acceptance: {path}")
    if decision.get("frames") != 601:
        raise ComparisonError(f"mother acceptance is not bound to all 601 native frames: {path}")
    if decision.get("fatal_findings"):
        raise ComparisonError(f"mother acceptance contains fatal findings: {path}")
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "status": decision.get("status"),
        "frames": decision.get("frames"),
        "identity": decision.get("identity"),
        "scope": decision.get("scope"),
        "excluded_claims": decision.get("excluded_claims"),
    }


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parameter_value(root: ET.Element, key: str) -> Optional[str]:
    for element in root.iter():
        if local_name(element.tag) == "parameter" and element.attrib.get("key") == key:
            return element.attrib.get("value")
    return None


def definition_binding(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise ComparisonError(f"missing definition: {path}")
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as error:
        raise ComparisonError(f"cannot parse definition {path}: {error}") from error
    size = None
    for element in root.iter():
        if local_name(element.tag) == "size" and all(axis in element.attrib for axis in ("x", "y", "z")):
            size = element
            break
    if size is None:
        raise ComparisonError(f"definition has no fillbox size: {path}")
    geometry_definition = next(
        (element for element in root.iter() if local_name(element.tag) == "definition" and "dp" in element.attrib),
        None,
    )
    if geometry_definition is None:
        raise ComparisonError(f"definition has no geometry dp: {path}")
    time_max = parameter_value(root, "TimeMax")
    time_out = parameter_value(root, "TimeOut")
    if time_max is None or time_out is None:
        raise ComparisonError(f"definition is missing TimeMax/TimeOut: {path}")
    try:
        values = {
            "dp_m": float(geometry_definition.attrib["dp"]),
            "fill_height_m": float(size.attrib["z"]),
            "time_max_s": float(time_max),
            "time_out_s": float(time_out),
        }
    except ValueError as error:
        raise ComparisonError(f"definition has nonnumeric controls: {path}") from error
    values.update(file_binding(path))
    return values


def require_close(actual: float, expected: float, label: str) -> None:
    if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=1.0e-9):
        raise ComparisonError(f"{label}: expected {expected}, got {actual}")


def validate_series(series: Mapping[str, Sequence[Tuple[float, float]]], labels: Iterable[str], role: str) -> None:
    for label in labels:
        values = list(series.get(label, []))
        if not values:
            raise ComparisonError(f"{role} has no numeric samples for {label}")
        times = [point[0] for point in values]
        if any(not math.isfinite(time) or not math.isfinite(value) for time, value in values):
            raise ComparisonError(f"{role} has a nonfinite sample for {label}")
        if any(later <= earlier for earlier, later in zip(times, times[1:])):
            raise ComparisonError(f"{role} time samples are not strictly increasing for {label}")


def require_full_common_coverage(
    mother: Sequence[Tuple[float, float]],
    child: Sequence[Tuple[float, float]],
    start: float,
    end: float,
    label: str,
) -> Dict[str, Any]:
    mother_first, mother_last = mother[0][0], mother[-1][0]
    child_first, child_last = child[0][0], child[-1][0]
    common_start = max(start, mother_first, child_first)
    common_end = min(end, mother_last, child_last)
    if common_start > start + TIME_TOLERANCE_S or common_end < end - TIME_TOLERANCE_S:
        raise ComparisonError(
            f"{label} does not have full common [{start}, {end}] s coverage: "
            f"mother=[{mother_first}, {mother_last}], child=[{child_first}, {child_last}]"
        )
    return {
        "requested_window_s": [start, end],
        "mother_native_bracket_s": [mother_first, mother_last],
        "child_native_bracket_s": [child_first, child_last],
        "common_bracket_s": [common_start, common_end],
        "full_common_0_6": True,
    }


def write_alignment_with_mother(
    path: Path,
    labels: Sequence[str],
    mother_series: Mapping[str, Sequence[Tuple[float, float]]],
    child_series: Mapping[str, Sequence[Tuple[float, float]]],
    parser: Any,
    start: float,
    end: float,
) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "series",
                "quantity",
                "units",
                "child_native_time_s",
                "child_value",
                "mother_interpolated_at_child_time",
                "child_minus_mother",
                "interpolation",
            ]
        )
        for label in labels:
            quantity = "elevation" if label.startswith("H") else "pressure"
            units = "m" if quantity == "elevation" else "Pa"
            for time, child_value in child_series[label]:
                if time < start or time > end:
                    continue
                mother_value = parser.interpolate(mother_series[label], time)
                if mother_value is None:
                    raise ComparisonError(f"mother interpolation fell outside the bracket for {label} at {time}")
                writer.writerow(
                    [
                        label,
                        quantity,
                        units,
                        f"{time:.12g}",
                        f"{child_value:.12g}",
                        f"{mother_value:.12g}",
                        f"{child_value - mother_value:.12g}",
                        "linear_mother_at_child_native_times",
                    ]
                )


def write_summary(path: Path, metrics: Mapping[str, Mapping[str, Any]]) -> None:
    fields = [
        "series",
        "quantity",
        "units",
        "status",
        "matched_samples",
        "child_native_samples",
        "mother_native_samples",
        "rmse",
        "mae",
        "signed_mean_bias",
        "maximum_absolute_error",
        "peak_amplitude_bias",
        "peak_time_error_s",
        "integrated_signed_error",
        "integrated_absolute_error",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for label in metrics:
            row = {"series": label, **metrics[label]}
            writer.writerow(row)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mother-elevation", type=Path, required=True)
    parser.add_argument("--mother-pressure", type=Path, required=True)
    parser.add_argument("--child-elevation", type=Path, required=True)
    parser.add_argument("--child-pressure", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--m1-parser", type=Path, required=True)
    parser.add_argument("--m1-parser-sha256", required=True)
    parser.add_argument("--mother-acceptance", type=Path, required=True)
    parser.add_argument("--mother-acceptance-sha256", required=True)
    parser.add_argument("--mother-definition", type=Path, required=True)
    parser.add_argument("--child-definition", type=Path, required=True)
    parser.add_argument("--child-case-manifest", type=Path, required=True)
    parser.add_argument("--mother-solver-receipt", type=Path, required=True)
    parser.add_argument("--mother-postprocess-receipt", type=Path, required=True)
    parser.add_argument("--mother-postprocess-manifest", type=Path, required=True)
    parser.add_argument("--child-solver-receipt", type=Path, required=True)
    parser.add_argument("--child-postprocess-receipt", type=Path, required=True)
    parser.add_argument("--child-postprocess-manifest", type=Path, required=True)
    parser.add_argument("--mother-case-id", default="UF_F1_MDBC_DAMBREAK3D")
    parser.add_argument("--child-case-id", required=True)
    parser.add_argument("--mother-depth-m", type=float, default=0.55)
    parser.add_argument("--child-depth-m", type=float, required=True)
    parser.add_argument("--mother-dp-m", type=float, default=0.01)
    parser.add_argument("--child-dp-m", type=float, default=0.01)
    parser.add_argument("--mother-time-out-s", type=float, default=0.01)
    parser.add_argument("--child-time-out-s", type=float, default=0.025)
    parser.add_argument("--time-max-s", type=float, default=6.0)
    parser.add_argument("--event-start-s", type=float, default=0.0)
    parser.add_argument("--event-end-s", type=float, default=6.0)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.event_start_s < args.event_end_s:
        raise ComparisonError("event-start-s must be smaller than event-end-s")
    if args.output_dir.exists():
        raise ComparisonError(f"output directory already exists; use a new attempt root: {args.output_dir}")
    require_close(args.mother_depth_m, 0.55, "mother depth")
    require_close(args.mother_dp_m, 0.01, "mother dp")
    require_close(args.child_dp_m, 0.01, "child dp")
    require_close(args.mother_time_out_s, 0.01, "mother TimeOut")
    require_close(args.child_time_out_s, 0.025, "child TimeOut")
    require_close(args.time_max_s, 6.0, "TimeMax")

    acceptance = validate_mother_acceptance(args.mother_acceptance.resolve(), args.mother_case_id)
    if acceptance["sha256"] != args.mother_acceptance_sha256:
        raise ComparisonError(
            "mother acceptance decision hash changed: "
            f"expected {args.mother_acceptance_sha256}, got {acceptance['sha256']}"
        )
    mother_definition = definition_binding(args.mother_definition.resolve())
    child_definition = definition_binding(args.child_definition.resolve())
    require_close(mother_definition["fill_height_m"], args.mother_depth_m, "mother definition depth")
    require_close(child_definition["fill_height_m"], args.child_depth_m, "child definition depth")
    require_close(mother_definition["dp_m"], args.mother_dp_m, "mother definition dp")
    require_close(child_definition["dp_m"], args.child_dp_m, "child definition dp")
    require_close(mother_definition["time_max_s"], args.time_max_s, "mother definition TimeMax")
    require_close(child_definition["time_max_s"], args.time_max_s, "child definition TimeMax")
    require_close(mother_definition["time_out_s"], args.mother_time_out_s, "mother definition TimeOut")
    require_close(child_definition["time_out_s"], args.child_time_out_s, "child definition TimeOut")

    case_manifest = read_json(args.child_case_manifest.resolve(), "child case manifest")
    if case_manifest.get("case_id") != args.child_case_id:
        raise ComparisonError("child case manifest case_id does not match --child-case-id")
    manifest_depth = case_manifest.get("physical_axis", {}).get("candidate_value_m")
    if manifest_depth is not None:
        require_close(float(manifest_depth), args.child_depth_m, "child case manifest depth")
    manifest_timeout = case_manifest.get("numerical_output_recipe", {}).get("candidate_time_out_s")
    if manifest_timeout is not None:
        require_close(float(manifest_timeout), args.child_time_out_s, "child case manifest TimeOut")

    mother_solver_receipt = validate_receipt(
        args.mother_solver_receipt.resolve(), "mother solver receipt", args.mother_case_id, "solver-001"
    )
    mother_postprocess_receipt = validate_receipt(
        args.mother_postprocess_receipt.resolve(),
        "mother postprocess receipt",
        args.mother_case_id,
        "postprocess-001",
    )
    child_solver_receipt = validate_receipt(
        args.child_solver_receipt.resolve(), "child solver receipt", args.child_case_id, "solver-001"
    )
    child_postprocess_receipt = validate_receipt(
        args.child_postprocess_receipt.resolve(),
        "child postprocess receipt",
        args.child_case_id,
        "postprocess-001",
    )
    mother_postprocess_manifest = validate_postprocess_manifest(
        args.mother_postprocess_manifest.resolve(),
        "mother postprocess manifest",
        args.mother_case_id,
        args.mother_elevation.resolve(),
        args.mother_pressure.resolve(),
    )
    child_postprocess_manifest = validate_postprocess_manifest(
        args.child_postprocess_manifest.resolve(),
        "child postprocess manifest",
        args.child_case_id,
        args.child_elevation.resolve(),
        args.child_pressure.resolve(),
    )

    parser_path = args.m1_parser.resolve()
    parser_binding = file_binding(parser_path)
    if parser_binding["sha256"] != args.m1_parser_sha256:
        raise ComparisonError(
            f"M1 parser hash changed: expected {args.m1_parser_sha256}, got {parser_binding['sha256']}"
        )
    m1 = load_m1_parser(parser_path)
    mapping_path = args.mapping.resolve()
    mapping = read_json(mapping_path, "H/P coordinate mapping")
    height_points, pressure_points = m1.expected_mapping(mapping)
    mother_elevation, mother_elevation_meta = m1.read_measurement_csv(
        args.mother_elevation.resolve(), height_points, "elevation"
    )
    child_elevation, child_elevation_meta = m1.read_measurement_csv(
        args.child_elevation.resolve(), height_points, "elevation"
    )
    mother_pressure, mother_pressure_meta = m1.read_measurement_csv(
        args.mother_pressure.resolve(), pressure_points, "pressure"
    )
    child_pressure, child_pressure_meta = m1.read_measurement_csv(
        args.child_pressure.resolve(), pressure_points, "pressure"
    )
    mother_series = {**mother_elevation, **mother_pressure}
    child_series = {**child_elevation, **child_pressure}
    validate_series(mother_series, LABELS, "mother")
    validate_series(child_series, LABELS, "child")

    coverage: Dict[str, Dict[str, Any]] = {}
    metrics: Dict[str, Dict[str, Any]] = {}
    for label in LABELS:
        coverage[label] = require_full_common_coverage(
            mother_series[label], child_series[label], args.event_start_s, args.event_end_s, label
        )
        result = m1.comparison_metrics(
            child_series[label], mother_series[label], args.event_start_s, args.event_end_s
        )
        if result.get("status") != "computed" or result.get("excluded_outside_reference_bracket") != 0:
            raise ComparisonError(f"{label} did not produce full common coverage metrics: {result}")
        result.update(
            {
                "quantity": "elevation" if label.startswith("H") else "pressure",
                "units": "m" if label.startswith("H") else "Pa",
                "child_native_samples": len(child_series[label]),
                "mother_native_samples": len(mother_series[label]),
            }
        )
        metrics[label] = result

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True)
    alignment_path = output_dir / "mother-vs-waterdepth-aligned-observations.csv"
    summary_path = output_dir / "mother-vs-waterdepth-comparison-summary.csv"
    report_path = output_dir / "mother-vs-waterdepth-comparison-report.json"
    write_alignment_with_mother(
        alignment_path,
        LABELS,
        mother_series,
        child_series,
        m1,
        args.event_start_s,
        args.event_end_s,
    )
    write_summary(summary_path, metrics)

    source_bindings = {
        "m1_strict_csv_parser": parser_binding,
        "mapping": file_binding(mapping_path),
        "mother_acceptance": acceptance,
        "mother_definition": mother_definition,
        "child_definition": child_definition,
        "child_case_manifest": file_binding(args.child_case_manifest.resolve()),
        "mother_solver_receipt": mother_solver_receipt,
        "mother_postprocess_receipt": mother_postprocess_receipt,
        "mother_postprocess_manifest": mother_postprocess_manifest,
        "child_solver_receipt": child_solver_receipt,
        "child_postprocess_receipt": child_postprocess_receipt,
        "child_postprocess_manifest": child_postprocess_manifest,
        "mother_elevation_csv": file_binding(args.mother_elevation.resolve()),
        "mother_pressure_csv": file_binding(args.mother_pressure.resolve()),
        "child_elevation_csv": file_binding(args.child_elevation.resolve()),
        "child_pressure_csv": file_binding(args.child_pressure.resolve()),
    }
    report: Dict[str, Any] = {
        "schema": "ds-data-02.upstream-first.m3.f1-fine-dp010-t025.mother-waterdepth-comparison.v1",
        "status": "completed_diagnostic_numerical_comparison",
        "family_id": "F1",
        "mother": {
            "case_id": args.mother_case_id,
            "initial_fill_height_m": args.mother_depth_m,
            "dp_m": args.mother_dp_m,
            "time_max_s": args.time_max_s,
            "time_out_s": args.mother_time_out_s,
        },
        "child": {
            "case_id": args.child_case_id,
            "initial_fill_height_m": args.child_depth_m,
            "dp_m": args.child_dp_m,
            "time_max_s": args.time_max_s,
            "time_out_s": args.child_time_out_s,
        },
        "physical_difference": {
            "axis": "initial_fill_height_m",
            "mother_value_m": args.mother_depth_m,
            "child_value_m": args.child_depth_m,
            "child_minus_mother_m": args.child_depth_m - args.mother_depth_m,
            "role": "physical water-depth condition difference; this is the M3 comparison axis",
            "experimental_credit": False,
        },
        "sampling_difference": {
            "path": "execution/parameters/parameter[@key='TimeOut']/@value",
            "mother_time_out_s": args.mother_time_out_s,
            "child_time_out_s": args.child_time_out_s,
            "child_minus_mother_s": args.child_time_out_s - args.mother_time_out_s,
            "role": "separate numerical/output sampling difference; not physical-axis credit or equivalence proof",
            "equivalence_claim": False,
        },
        "scope": {
            "event_window_s": [args.event_start_s, args.event_end_s],
            "coverage_requirement": "all H1-H4/P1-P8 with full 0..6 s common native coverage",
            "primary_observations": list(HEIGHT_LABELS),
            "auxiliary_observations": list(PRESSURE_LABELS),
            "units": {"H": "m", "P": "Pa"},
        },
        "comparison_rule": {
            "direction": "child values at child native MeasureTool times versus linearly interpolated mother values",
            "interpolation": "linear inside mother native bracket only",
            "sample_grid": "child native times; mother and child time columns preserved",
            "phase_shift": False,
            "retiming": False,
            "extrapolation": False,
            "common_coverage_required": True,
        },
        "inputs": source_bindings,
        "coverage_checks": {
            "all_labels": list(LABELS),
            "all_h1_h4_present": True,
            "all_p1_p8_present": True,
            "all_full_common_0_6": all(item["full_common_0_6"] for item in coverage.values()),
            "by_label": coverage,
            "mother_measuretool_time_brackets": {
                **{label: mother_elevation_meta["time_bracket_s"] for label in HEIGHT_LABELS},
                **{label: mother_pressure_meta["time_bracket_s"] for label in PRESSURE_LABELS},
            },
            "child_measuretool_time_brackets": {
                **{label: child_elevation_meta["time_bracket_s"] for label in HEIGHT_LABELS},
                **{label: child_pressure_meta["time_bracket_s"] for label in PRESSURE_LABELS},
            },
        },
        "metrics": metrics,
        "outputs": {
            "aligned_observations": file_binding(alignment_path),
            "summary_csv": file_binding(summary_path),
        },
        "acceptance": {
            "status": "diagnostic_only_no_acceptance_threshold",
            "experimental_credit": False,
            "experimental_reference_used": False,
            "source_experimental_tolerance_used": False,
            "numerical_convergence_claim": False,
            "q_e_claim": False,
            "q_n_claim": False,
            "child_acceptance": "not established by this comparison",
            "threshold_policy": "metrics are reported for internal numerical transport diagnostics; no pass/fail threshold is applied",
        },
        "flags": [
            "mother_all601_native_scan_and_scoped_acceptance_bound",
            "exact_measuretool_headers_and_declared_coordinates_reused_from_m1_v2",
            "all_h1_h4_and_p1_p8_required",
            "full_0_6_common_coverage_required",
            "physical_depth_difference_labelled_separately_from_time_sampling",
            "time_out_difference_is_not_physical_credit",
            "no_experimental_credit",
            "no_retiming_or_phase_shift",
            "no_extrapolation",
            "no_acceptance_threshold",
            "no_raw_native_frame_reads",
        ],
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(report_path)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ComparisonError as error:
        print(f"comparison contract error: {error}", file=sys.stderr)
        raise SystemExit(2)
