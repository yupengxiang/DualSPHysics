#!/usr/bin/env python3
"""Audit the F1 dp=.015 numerical bridge against the official F1 mother.

This worker consumes only the small H1--H4 MeasureTool CSV products and their
receipts/manifests.  It does not open native particle arrays and it never
retimes either run.  The fine-run timestamps are the comparison grid; bridge
values are linearly interpolated only inside the actual bridge bracket.

The numerical bridge contract is deliberately stricter than a CSV comparison:
both solver and extraction lifecycles must be complete, point coordinates must
be verified, and a separate native-integrity evidence record must bind decoded
identity, validity semantics, and explicit excluded-particle records.  In the
absence of that evidence this script reports ``pending_native_integrity`` and
cannot grant bridge eligibility even when all CSV metrics pass.

The native-integrity evidence format expected by this audit is documented in
``integrity_evidence_requirements`` in the JSON report.  The evidence is kept
separate because a MeasureTool CSV alone cannot prove native identity or
excluded-particle semantics.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import importlib.util
import json
import math
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


HEIGHT_LABELS = [f"H{i}" for i in range(1, 5)]
EXPECTED_FAMILY = "F1"
EXPECTED_UPSTREAM_CASE = "CaseDamBreak3D"
EXPECTED_FINE_CASE = "UF_F1_MDBC_DAMBREAK3D"
EXPECTED_BRIDGE_CASE = "UF_F1_MDBC_DP015_BASE"
EXPECTED_MANIFEST_SCHEMA = "ds-data-02.upstream-first.f1-generic-postprocess.v2"
EXPECTED_RECEIPT_SCHEMA = "ds02.execution-receipt.v1"
HEIGHT_TOLERANCE_M = 0.0275
COORDINATE_TOLERANCE_M = 1.0e-4
TIME_EPSILON_S = 1.0e-6


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"JSON document is not an object: {path}")
    return value


def real(path: object) -> Optional[Path]:
    if not isinstance(path, str) or not path:
        return None
    return Path(path).expanduser().resolve()


def path_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def import_measurement_reader() -> Any:
    """Load the already-reviewed F1 MeasureTool parser without running main."""
    parser_path = Path(__file__).with_name("compare_spheric_reference_v2.py")
    spec = importlib.util.spec_from_file_location("f1_spheric_reader", parser_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import measurement parser: {parser_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def expected_contract_values(contract: Dict[str, Any]) -> Tuple[float, float, float]:
    if contract.get("schema") != "upstream-first.numerical-bridge-acceptance.v1":
        raise ValueError("unexpected numerical bridge contract schema")
    if contract.get("status") != "frozen_before_fine_and_bridge_solver_comparisons":
        raise ValueError("numerical bridge contract is not frozen before comparisons")
    window = contract.get("time_window_s")
    if not isinstance(window, list) or len(window) != 2:
        raise ValueError("bridge contract time_window_s must contain two values")
    start, end = float(window[0]), float(window[1])
    gates = contract.get("engineering_gates")
    if not isinstance(gates, dict):
        raise ValueError("bridge contract engineering_gates is missing")
    text = f"{gates.get('height_comparison', '')} {gates.get('height_bias', '')}"
    if "0.0275" not in text:
        raise ValueError("bridge contract does not contain the frozen 0.0275 m height gate")
    return start, end, HEIGHT_TOLERANCE_M


def receipt_binding(receipt: Dict[str, Any], target: Path) -> Dict[str, Any]:
    target_hash = sha256(target)
    matches: List[str] = []
    for key, value in (receipt.get("input_hashes_at_launch") or {}).items():
        if isinstance(key, str) and isinstance(value, str):
            try:
                key_path = Path(key).resolve()
            except OSError:
                continue
            if key_path == target and value == target_hash:
                matches.append(key)
    return {"sha256": target_hash, "matched_input_paths": matches, "bound": bool(matches)}


def validate_execution_receipt(
    path: Path,
    role: str,
    expected_case: Optional[str],
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    result: Dict[str, Any] = {
        "role": role,
        "path": str(path),
        "exists": path.is_file(),
        "sha256": sha256(path) if path.is_file() else None,
        "status": "invalid",
        "reasons": [],
    }
    if not path.is_file():
        result["reasons"].append("receipt_missing")
        return result, None
    try:
        document = load_json(path)
    except Exception as exc:  # pragma: no cover - defensive receipt handling
        result["reasons"].append(f"receipt_parse_error:{exc}")
        return result, None
    result["schema"] = document.get("schema")
    result["status_field"] = document.get("status")
    result["returncode"] = document.get("returncode")
    result["finished_at_utc"] = document.get("finished_at_utc")
    result["started_at_utc"] = document.get("started_at_utc")
    result["output_root"] = document.get("output_root")
    request = document.get("request")
    result["request"] = {
        key: request.get(key)
        for key in ("family_id", "case_id", "attempt_id", "kind", "reference_role", "upstream_case_id")
    } if isinstance(request, dict) else None
    if document.get("schema") != EXPECTED_RECEIPT_SCHEMA:
        result["reasons"].append("unexpected_receipt_schema")
    if document.get("status") != "completed":
        result["reasons"].append(f"status_not_completed:{document.get('status')!r}")
    if document.get("returncode") != 0:
        result["reasons"].append(f"returncode_not_zero:{document.get('returncode')!r}")
    if not document.get("finished_at_utc"):
        result["reasons"].append("finished_at_missing")
    if not isinstance(request, dict):
        result["reasons"].append("request_missing")
    else:
        if request.get("family_id") != EXPECTED_FAMILY:
            result["reasons"].append(f"family_id_mismatch:{request.get('family_id')!r}")
        if expected_case is not None and request.get("case_id") != expected_case:
            result["reasons"].append(f"case_id_mismatch:{request.get('case_id')!r}")
        if request.get("upstream_case_id") not in (None, EXPECTED_UPSTREAM_CASE):
            result["reasons"].append(f"upstream_case_id_mismatch:{request.get('upstream_case_id')!r}")
    output_root = real(document.get("output_root"))
    if output_root is None:
        result["reasons"].append("output_root_missing")
    else:
        result["output_root_resolved"] = str(output_root)
        if not output_root.is_dir():
            result["reasons"].append("output_root_missing_on_filesystem")
        if role == "solver":
            data_root = output_root / "data"
            result["native_data_root"] = str(data_root)
            if not data_root.is_dir():
                result["reasons"].append("native_data_root_missing")
            else:
                part_files = sorted(data_root.glob("Part_*.bi4"))
                result["native_part_file_count"] = len(part_files)
                if not part_files:
                    result["reasons"].append("native_part_files_missing")
    result["status"] = "complete" if not result["reasons"] else "incomplete"
    return result, document


def validate_postprocess_manifest(
    path: Path,
    csv_path: Path,
    solver_receipt_path: Path,
    solver_receipt: Dict[str, Any],
    postprocess_receipt_summary: Dict[str, Any],
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    result: Dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "sha256": sha256(path) if path.is_file() else None,
        "status": "invalid",
        "reasons": [],
    }
    if not path.is_file():
        result["reasons"].append("manifest_missing")
        return result, None
    try:
        manifest = load_json(path)
    except Exception as exc:  # pragma: no cover - defensive manifest handling
        result["reasons"].append(f"manifest_parse_error:{exc}")
        return result, None
    result["schema"] = manifest.get("schema")
    result["family_id"] = manifest.get("family_id")
    result["case_id"] = manifest.get("case_id")
    result["upstream_case_id"] = manifest.get("upstream_case_id")
    result["solver_root"] = manifest.get("solver_root")
    result["output_root"] = manifest.get("output_root")
    if manifest.get("schema") != EXPECTED_MANIFEST_SCHEMA:
        result["reasons"].append("unexpected_postprocess_manifest_schema")
    if manifest.get("family_id") != EXPECTED_FAMILY:
        result["reasons"].append("manifest_family_id_mismatch")
    if manifest.get("upstream_case_id") != EXPECTED_UPSTREAM_CASE:
        result["reasons"].append("manifest_upstream_case_id_mismatch")
    solver_root = real(manifest.get("solver_root"))
    solver_output_root = real(solver_receipt.get("output_root"))
    if solver_root is None or solver_output_root is None or solver_root != solver_output_root:
        result["reasons"].append("manifest_solver_root_not_bound_to_solver_receipt")
    output_root = real(manifest.get("output_root"))
    postprocess_root = real(postprocess_receipt_summary.get("output_root"))
    if output_root is None or postprocess_root is None or not path_within(output_root, postprocess_root):
        result["reasons"].append("manifest_output_root_not_bound_to_postprocess_receipt")
    primary = manifest.get("primary_observation_files")
    if not isinstance(primary, list) or not all(isinstance(value, str) for value in primary):
        result["reasons"].append("primary_observation_files_missing")
    else:
        resolved_primary = [real(value) for value in primary]
        result["primary_observation_files"] = [str(value) if value else None for value in resolved_primary]
        if csv_path.resolve() not in [value for value in resolved_primary if value is not None]:
            result["reasons"].append("supplied_csv_not_listed_as_primary_observation")
    if not csv_path.is_file():
        result["reasons"].append("observation_csv_missing")
    source_hashes = manifest.get("source_hashes")
    solver_hash = sha256(solver_receipt_path) if solver_receipt_path.is_file() else None
    result["source_hashes"] = source_hashes if isinstance(source_hashes, dict) else None
    if not isinstance(source_hashes, dict) or source_hashes.get("solver_receipt_sha256") != solver_hash:
        result["reasons"].append("manifest_solver_receipt_hash_mismatch")
    observation_hashes = manifest.get("observation_hashes")
    result["observation_hashes"] = observation_hashes if isinstance(observation_hashes, dict) else None
    csv_hash = sha256(csv_path) if csv_path.is_file() else None
    if not isinstance(observation_hashes, dict) or observation_hashes.get("elevation_csv_sha256") != csv_hash:
        result["reasons"].append("manifest_elevation_hash_mismatch")
    input_points = manifest.get("input_points")
    result["input_points"] = input_points if isinstance(input_points, dict) else None
    if not isinstance(input_points, dict) or not real(input_points.get("elevation")) or not real(input_points["elevation"]).is_file():
        result["reasons"].append("elevation_point_definition_missing")
    # A completed postprocess receipt must itself bind the solver receipt.  The
    # generic extractor also records this hash in its manifest; both bindings
    # are retained so a CSV copied between attempts cannot pass silently.
    if postprocess_receipt_summary.get("solver_receipt_binding", {}).get("bound") is not True:
        result["reasons"].append("postprocess_receipt_does_not_bind_solver_receipt")
    result["status"] = "complete" if not result["reasons"] else "incomplete"
    return result, manifest


def validate_integrity_evidence(
    path: Optional[Path], solver_receipt_path: Path, solver_receipt: Dict[str, Any], role: str
) -> Dict[str, Any]:
    requirements = {
        "schema": "ds-data-02.upstream-first.f1-native-integrity.v1",
        "status": "verified",
        "solver_root": "must equal the bound solver receipt output_root",
        "source_hashes.solver_receipt_sha256": "must equal the bound solver receipt hash",
        "native_time_record.strictly_increasing": True,
        "native_time_record.window_s": [0.0, 6.0],
        "excluded_particle_records.present": True,
        "excluded_particle_records.path": "explicit record file, including zero-count runs",
        "excluded_particle_records.sha256": "hash of the explicit record file",
        "decoded_identity.status": "verified",
        "decoded_identity.spatial_identity_verified": True,
        "decoded_identity.raw_native_fields_retained": True,
        "decoded_identity.validity_semantics_retained": True,
    }
    result: Dict[str, Any] = {
        "role": role,
        "status": "pending",
        "path": str(path) if path else None,
        "requirements": requirements,
        "reasons": [],
    }
    if path is None:
        result["reasons"].append("native_integrity_evidence_not_supplied")
        return result
    if not path.is_file():
        result["reasons"].append("native_integrity_evidence_missing")
        return result
    result["sha256"] = sha256(path)
    try:
        evidence = load_json(path)
    except Exception as exc:  # pragma: no cover - defensive evidence handling
        result["reasons"].append(f"native_integrity_evidence_parse_error:{exc}")
        return result
    result["evidence"] = evidence
    if evidence.get("schema") != requirements["schema"]:
        result["reasons"].append("unexpected_native_integrity_schema")
    if evidence.get("status") != requirements["status"]:
        result["reasons"].append("native_integrity_status_not_verified")
    bound_root = real(solver_receipt.get("output_root"))
    if real(evidence.get("solver_root")) != bound_root:
        result["reasons"].append("native_integrity_solver_root_mismatch")
    source_hashes = evidence.get("source_hashes")
    solver_hash = sha256(solver_receipt_path) if solver_receipt_path.is_file() else None
    if not isinstance(source_hashes, dict) or not isinstance(solver_hash, str) or source_hashes.get("solver_receipt_sha256") != solver_hash:
        result["reasons"].append("native_integrity_solver_receipt_hash_unbound")
    native_time = evidence.get("native_time_record")
    if not isinstance(native_time, dict) or native_time.get("strictly_increasing") is not True:
        result["reasons"].append("native_time_record_not_verified")
    else:
        bracket = native_time.get("window_s")
        try:
            valid_bracket = (
                isinstance(bracket, list)
                and len(bracket) == 2
                and float(bracket[0]) <= TIME_EPSILON_S
                and float(bracket[1]) >= 6.0 - TIME_EPSILON_S
            )
        except (TypeError, ValueError):
            valid_bracket = False
        if not valid_bracket:
            result["reasons"].append("native_time_record_does_not_cover_0_6s")
    excluded = evidence.get("excluded_particle_records")
    if not isinstance(excluded, dict) or excluded.get("present") is not True:
        result["reasons"].append("explicit_excluded_particle_records_missing")
    else:
        record_path = real(excluded.get("path"))
        if record_path is None or not record_path.is_file():
            result["reasons"].append("explicit_excluded_particle_record_file_missing")
        elif excluded.get("sha256") != sha256(record_path):
            result["reasons"].append("explicit_excluded_particle_record_hash_mismatch")
        else:
            result["excluded_particle_record_sha256"] = sha256(record_path)
    identity = evidence.get("decoded_identity")
    if not isinstance(identity, dict):
        result["reasons"].append("decoded_identity_missing")
    else:
        for field in ("spatial_identity_verified", "raw_native_fields_retained", "validity_semantics_retained"):
            if identity.get(field) is not True:
                result["reasons"].append(f"decoded_identity_{field}_not_verified")
        if identity.get("status") != "verified":
            result["reasons"].append("decoded_identity_status_not_verified")
    result["status"] = "verified" if not result["reasons"] else "pending"
    return result


def parse_observations(
    path: Path,
    expected_points: Dict[str, Tuple[float, float, float]],
    reader: Any,
    role: str,
) -> Tuple[Dict[str, Any], Optional[Dict[str, List[Tuple[float, float]]]], Optional[Dict[str, Any]]]:
    result: Dict[str, Any] = {
        "role": role,
        "path": str(path),
        "exists": path.is_file(),
        "sha256": sha256(path) if path.is_file() else None,
        "status": "invalid",
        "reasons": [],
    }
    if not path.is_file():
        result["reasons"].append("observation_csv_missing")
        return result, None, None
    try:
        series, metadata = reader.read_measurement_csv(path, expected_points, "elevation")
    except Exception as exc:
        result["reasons"].append(f"measurement_csv_parse_error:{exc}")
        return result, None, None
    result["metadata"] = metadata
    result["time_bracket_s"] = metadata.get("time_bracket_s")
    result["strictly_increasing_time"] = metadata.get("strictly_increasing_time")
    result["row_count_after_header"] = metadata.get("row_count_after_header")
    result["missing_value_count_by_label"] = metadata.get("missing_value_count_by_label")
    result["warnings"] = metadata.get("warnings", [])
    if metadata.get("strictly_increasing_time") is not True:
        result["reasons"].append("time_column_not_strictly_increasing")
    if any(int(value or 0) > 0 for value in (metadata.get("missing_value_count_by_label") or {}).values()):
        result["reasons"].append("invalid_or_missing_measurement_values")
    if any("fallback" in str(warning) for warning in metadata.get("warnings", [])):
        result["reasons"].append("coordinate_mapping_fallback_used")
    columns = metadata.get("column_indices_zero_based") or {}
    bindings = metadata.get("point_bindings") or {}
    coordinate_mode = metadata.get("coordinate_binding")
    actual_points: Dict[str, Any] = {}
    for label, expected in expected_points.items():
        index = columns.get(label)
        binding = bindings.get(label) if isinstance(bindings, dict) else None
        actual = binding.get("measured_m") if isinstance(binding, dict) else None
        distance = None
        if isinstance(actual, list) and len(actual) == 3:
            if str(metadata.get("quantity")) == "elevation":
                # MeasureTool's Elevation PosZ is the measured initial
                # surface/reference height for H4.  Verify the requested XY
                # location and retain measured z without treating it as a
                # query-coordinate mismatch.
                distance = math.sqrt(sum((float(actual[i]) - expected[i]) ** 2 for i in (0, 1)))
            else:
                distance = math.sqrt(sum((float(actual[i]) - expected[i]) ** 2 for i in range(3)))
        point_ok = distance is not None and distance <= COORDINATE_TOLERANCE_M
        actual_points[label] = {
            "expected_m": list(expected),
            "actual_m": actual,
            "column_index_zero_based": index,
            "distance_m": distance,
            "measured_z_m": (binding.get("measured_z_m") if isinstance(binding, dict) else None),
            "header": (binding.get("header") if isinstance(binding, dict) else None),
            "coordinate_mode": coordinate_mode,
            "coordinate_verified": point_ok,
        }
        if not point_ok:
            result["reasons"].append(f"coordinate_not_verified:{label}")
    result["actual_points"] = actual_points
    times_by_label = {label: [float(time) for time, _ in values] for label, values in series.items()}
    result["sample_count_by_label"] = {label: len(values) for label, values in series.items()}
    reference_times = times_by_label.get(HEIGHT_LABELS[0], [])
    time_consistent = all(times == reference_times for times in times_by_label.values())
    result["same_valid_time_grid_for_all_points"] = time_consistent
    if not time_consistent:
        result["reasons"].append("point_time_grids_differ")
    result["status"] = "complete" if not result["reasons"] else "incomplete"
    return result, series, metadata


def interpolate(series: Sequence[Tuple[float, float]], time: float) -> Optional[float]:
    if not series or time < series[0][0] or time > series[-1][0]:
        return None
    times = [point[0] for point in series]
    index = bisect.bisect_left(times, time)
    if index < len(series) and series[index][0] == time:
        return series[index][1]
    if index == 0 or index == len(series):
        return None
    before, after = series[index - 1], series[index]
    if after[0] <= before[0]:
        return None
    fraction = (time - before[0]) / (after[0] - before[0])
    return before[1] + fraction * (after[1] - before[1])


def compare_probe(
    fine: Sequence[Tuple[float, float]],
    bridge: Sequence[Tuple[float, float]],
    start: float,
    end: float,
    tolerance: float,
    data_complete: bool,
) -> Tuple[Dict[str, Any], List[Tuple[float, float, float]]]:
    requested = [(time, value) for time, value in fine if start <= time <= end]
    aligned: List[Tuple[float, float, float]] = []
    for time, value in requested:
        bridge_value = interpolate(bridge, time)
        if bridge_value is not None:
            aligned.append((time, value, bridge_value))
    excluded = len(requested) - len(aligned)
    errors = [fine_value - bridge_value for _, fine_value, bridge_value in aligned]
    metrics: Dict[str, Any] = {
        "window_s": [start, end],
        "requested_sample_count": len(requested),
        "matched_samples": len(aligned),
        "excluded_outside_actual_common_bracket": excluded,
        "fine_time_bracket_s": [fine[0][0], fine[-1][0]] if fine else None,
        "bridge_time_bracket_s": [bridge[0][0], bridge[-1][0]] if bridge else None,
        "time_shift_s": 0.0,
        "retiming_or_phase_fit": False,
    }
    if not data_complete or not aligned or excluded:
        metrics["status"] = "not_evaluated_missing_or_incomplete"
        if not data_complete:
            metrics["reason"] = "observation_data_incomplete"
        elif not aligned:
            metrics["reason"] = "no_actual_common_bracketed_samples"
        else:
            metrics["reason"] = "actual_common_bracket_does_not_cover_requested_window"
        return metrics, aligned
    signed_bias = statistics.fmean(errors)
    rmse = math.sqrt(statistics.fmean(error * error for error in errors))
    metrics.update(
        {
            "status": "pass" if rmse <= tolerance and abs(signed_bias) <= tolerance else "fail",
            "rmse_m": rmse,
            "mae_m": statistics.fmean(abs(error) for error in errors),
            "signed_mean_bias_m": signed_bias,
            "absolute_signed_mean_bias_m": abs(signed_bias),
            "maximum_absolute_error_m": max(abs(error) for error in errors),
            "rmse_limit_m": tolerance,
            "absolute_signed_mean_bias_limit_m": tolerance,
            "rmse_gate": rmse <= tolerance,
            "absolute_signed_mean_bias_gate": abs(signed_bias) <= tolerance,
        }
    )
    return metrics, aligned


def write_summary(path: Path, probes: Dict[str, Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "probe",
                "status",
                "requested_sample_count",
                "matched_samples",
                "excluded_outside_actual_common_bracket",
                "rmse_m",
                "mae_m",
                "signed_mean_bias_m",
                "absolute_signed_mean_bias_m",
                "maximum_absolute_error_m",
                "rmse_limit_m",
                "absolute_signed_mean_bias_limit_m",
            ]
        )
        for label in HEIGHT_LABELS:
            metrics = probes[label]
            writer.writerow(
                [
                    label,
                    metrics.get("status"),
                    metrics.get("requested_sample_count"),
                    metrics.get("matched_samples"),
                    metrics.get("excluded_outside_actual_common_bracket"),
                    metrics.get("rmse_m"),
                    metrics.get("mae_m"),
                    metrics.get("signed_mean_bias_m"),
                    metrics.get("absolute_signed_mean_bias_m"),
                    metrics.get("maximum_absolute_error_m"),
                    metrics.get("rmse_limit_m"),
                    metrics.get("absolute_signed_mean_bias_limit_m"),
                ]
            )


def write_alignment(path: Path, aligned: Dict[str, List[Tuple[float, float, float]]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["probe", "time_s", "fine_m", "bridge_m", "error_m", "time_shift_s"])
        for label in HEIGHT_LABELS:
            for time, fine_value, bridge_value in aligned[label]:
                writer.writerow([label, f"{time:.12g}", f"{fine_value:.12g}", f"{bridge_value:.12g}", f"{fine_value - bridge_value:.12g}", "0"])


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fine-elevation", type=Path, required=True)
    parser.add_argument("--bridge-elevation", type=Path, required=True)
    parser.add_argument("--fine-solver-receipt", type=Path, required=True)
    parser.add_argument("--bridge-solver-receipt", type=Path, required=True)
    parser.add_argument("--fine-postprocess-manifest", type=Path, required=True)
    parser.add_argument("--bridge-postprocess-manifest", type=Path, required=True)
    parser.add_argument("--fine-postprocess-receipt", type=Path, required=True)
    parser.add_argument("--bridge-postprocess-receipt", type=Path, required=True)
    parser.add_argument("--fine-integrity-evidence", type=Path, default=None)
    parser.add_argument("--bridge-integrity-evidence", type=Path, default=None)
    parser.add_argument("--acceptance", type=Path, default=Path(__file__).parents[3] / "m3/numerical-bridge-acceptance.json")
    parser.add_argument("--mapping", type=Path, default=Path(__file__).parents[1] / "reference/spheric-test2-metadata.json")
    parser.add_argument("--fine-case-id", default=EXPECTED_FINE_CASE)
    parser.add_argument("--bridge-case-id", default=EXPECTED_BRIDGE_CASE)
    parser.add_argument("--start", type=float, default=None)
    parser.add_argument("--end", type=float, default=None)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    output_dir = args.output_dir.resolve()
    if output_dir.exists():
        parser.error(f"output directory already exists; use a new path: {output_dir}")
    for path in (args.acceptance, args.mapping):
        if not path.is_file():
            parser.error(f"missing contract/mapping input: {path}")

    report: Dict[str, Any] = {
        "schema": "ds-data-02.upstream-first.f1-numerical-bridge-audit.v2",
        "family_id": EXPECTED_FAMILY,
        "reference_role": "numerical_bridge_diagnostic",
        "upstream_case_id": EXPECTED_UPSTREAM_CASE,
        "inputs": {},
        "controls": {
            "comparison": "fine-run actual timestamps; bridge linear interpolation only inside actual bridge bracket",
            "time_shift_s": 0.0,
            "retiming_or_phase_fit": False,
            "invalid_or_missing_values": "reported and excluded from finite diagnostics; any such condition blocks acceptance",
            "measurement_binding": "exact Elevation_<n> [m] headers plus XY; measured PosZ retained",
        },
        "integrity_evidence_requirements": {},
        "probes": {},
        "aligned_observation_count": {},
        "acceptance": {"status": "not_evaluated", "bridge_eligibility_granted": False},
        "flags": [
            "CSV_comparison_does_not_grant_bridge_eligibility",
            "native_excluded_particle_records_are_bound_separately",
            "actual_point_coordinates_and_time_coverage_preserved",
            "elevation_measured_posz_recorded_without_xyz_rejection",
            "exact_elevation_headers_and_xy_binding",
            "no_positional_measurement_fallback",
            "no_retiming_or_phase_shift",
        ],
    }

    try:
        contract = load_json(args.acceptance)
        contract_start, contract_end, tolerance = expected_contract_values(contract)
    except Exception as exc:
        parser.error(f"invalid frozen bridge contract: {exc}")
    start = contract_start if args.start is None else float(args.start)
    end = contract_end if args.end is None else float(args.end)
    window_matches_contract = math.isclose(start, contract_start, abs_tol=TIME_EPSILON_S) and math.isclose(end, contract_end, abs_tol=TIME_EPSILON_S)
    if not start < end:
        parser.error("require start < end")
    report["inputs"]["acceptance_contract"] = {"path": str(args.acceptance.resolve()), "sha256": sha256(args.acceptance), "schema": contract.get("schema"), "status": contract.get("status")}
    report["inputs"]["coordinate_mapping"] = {"path": str(args.mapping.resolve()), "sha256": sha256(args.mapping)}
    report["controls"].update({"window_s": [start, end], "frozen_contract_window_s": [contract_start, contract_end], "window_matches_contract": window_matches_contract, "height_tolerance_m": tolerance, "tolerance_origin": contract.get("tolerance_origin")})

    fine_solver_summary, fine_solver = validate_execution_receipt(args.fine_solver_receipt.resolve(), "solver", args.fine_case_id)
    bridge_solver_summary, bridge_solver = validate_execution_receipt(args.bridge_solver_receipt.resolve(), "solver", args.bridge_case_id)
    report["inputs"]["fine_solver_receipt"] = fine_solver_summary
    report["inputs"]["bridge_solver_receipt"] = bridge_solver_summary

    fine_post_summary, fine_post_receipt = validate_execution_receipt(args.fine_postprocess_receipt.resolve(), "postprocess", args.fine_case_id)
    bridge_post_summary, bridge_post_receipt = validate_execution_receipt(args.bridge_postprocess_receipt.resolve(), "postprocess", args.bridge_case_id)
    if fine_solver is not None:
        fine_post_summary["solver_receipt_binding"] = receipt_binding(fine_post_receipt or {}, args.fine_solver_receipt.resolve())
    else:
        fine_post_summary["solver_receipt_binding"] = {"bound": False, "reason": "solver_receipt_unreadable"}
    if bridge_solver is not None:
        bridge_post_summary["solver_receipt_binding"] = receipt_binding(bridge_post_receipt or {}, args.bridge_solver_receipt.resolve())
    else:
        bridge_post_summary["solver_receipt_binding"] = {"bound": False, "reason": "solver_receipt_unreadable"}
    report["inputs"]["fine_postprocess_receipt"] = fine_post_summary
    report["inputs"]["bridge_postprocess_receipt"] = bridge_post_summary

    fine_manifest_summary, fine_manifest = validate_postprocess_manifest(
        args.fine_postprocess_manifest.resolve(), args.fine_elevation.resolve(), args.fine_solver_receipt.resolve(), fine_solver or {}, fine_post_summary
    )
    bridge_manifest_summary, bridge_manifest = validate_postprocess_manifest(
        args.bridge_postprocess_manifest.resolve(), args.bridge_elevation.resolve(), args.bridge_solver_receipt.resolve(), bridge_solver or {}, bridge_post_summary
    )
    report["inputs"]["fine_postprocess_manifest"] = fine_manifest_summary
    report["inputs"]["bridge_postprocess_manifest"] = bridge_manifest_summary

    fine_integrity = validate_integrity_evidence(args.fine_integrity_evidence.resolve() if args.fine_integrity_evidence else None, args.fine_solver_receipt.resolve(), fine_solver or {}, "fine")
    bridge_integrity = validate_integrity_evidence(args.bridge_integrity_evidence.resolve() if args.bridge_integrity_evidence else None, args.bridge_solver_receipt.resolve(), bridge_solver or {}, "bridge")
    report["inputs"]["fine_native_integrity"] = fine_integrity
    report["inputs"]["bridge_native_integrity"] = bridge_integrity
    report["integrity_evidence_requirements"] = fine_integrity["requirements"]

    try:
        mapping = load_json(args.mapping)
        reader = import_measurement_reader()
        height_points, _ = reader.expected_mapping(mapping)
    except Exception as exc:
        parser.error(f"invalid coordinate mapping/parser: {exc}")
    fine_observation, fine_series, _ = parse_observations(args.fine_elevation.resolve(), height_points, reader, "fine")
    bridge_observation, bridge_series, _ = parse_observations(args.bridge_elevation.resolve(), height_points, reader, "bridge")
    report["inputs"]["fine_observation"] = fine_observation
    report["inputs"]["bridge_observation"] = bridge_observation

    aligned: Dict[str, List[Tuple[float, float, float]]] = {label: [] for label in HEIGHT_LABELS}
    all_probe_data_complete = (
        fine_observation.get("status") == "complete"
        and bridge_observation.get("status") == "complete"
        and fine_series is not None
        and bridge_series is not None
        and window_matches_contract
    )
    for label in HEIGHT_LABELS:
        metrics, values = compare_probe(
            (fine_series or {}).get(label, []),
            (bridge_series or {}).get(label, []),
            start,
            end,
            tolerance,
            all_probe_data_complete,
        )
        report["probes"][label] = metrics
        aligned[label] = values
        report["aligned_observation_count"][label] = len(values)

    output_dir.mkdir(parents=True)
    write_summary(output_dir / "bridge-h1-h4-summary.csv", report["probes"])
    write_alignment(output_dir / "bridge-h1-h4-aligned.csv", aligned)

    lifecycle_complete = all(
        report["inputs"][key].get("status") == "complete"
        for key in (
            "fine_solver_receipt",
            "bridge_solver_receipt",
            "fine_postprocess_receipt",
            "bridge_postprocess_receipt",
            "fine_postprocess_manifest",
            "bridge_postprocess_manifest",
        )
    )
    data_complete = all_probe_data_complete and all(
        report["probes"][label].get("status") in {"pass", "fail"}
        and report["probes"][label].get("excluded_outside_actual_common_bracket") == 0
        and report["aligned_observation_count"][label] > 0
        for label in HEIGHT_LABELS
    )
    metrics_pass = all(report["probes"][label].get("status") == "pass" for label in HEIGHT_LABELS)
    integrity_verified = fine_integrity.get("status") == "verified" and bridge_integrity.get("status") == "verified"
    if not window_matches_contract:
        acceptance_status = "not_evaluated_contract_window_mismatch"
    elif not lifecycle_complete:
        acceptance_status = "not_evaluated_lifecycle_incomplete"
    elif not data_complete:
        acceptance_status = "not_evaluated_data_incomplete"
    elif not metrics_pass:
        acceptance_status = "failed_height_gate"
    elif not integrity_verified:
        acceptance_status = "pending_native_integrity"
    else:
        acceptance_status = "pass"
    report["acceptance"] = {
        "status": acceptance_status,
        "bridge_eligibility_granted": acceptance_status == "pass",
        "lifecycle_complete": lifecycle_complete,
        "observation_data_complete": data_complete,
        "all_height_metrics_pass": metrics_pass,
        "native_integrity_verified": integrity_verified,
        "rule": "No bridge pass when either run/manifest/CSV coverage is incomplete or native identity/excluded-particle evidence is pending.",
    }
    report["output_files"] = {
        "summary_csv": str(output_dir / "bridge-h1-h4-summary.csv"),
        "aligned_csv": str(output_dir / "bridge-h1-h4-aligned.csv"),
    }
    (output_dir / "bridge-h1-h4-audit.json").write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(output_dir / "bridge-h1-h4-audit.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
