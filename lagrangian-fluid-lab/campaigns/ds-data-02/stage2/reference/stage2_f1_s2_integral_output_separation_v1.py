#!/usr/bin/env python3
"""Run the bounded F1-S2 integration/output sampling diagnostic.

The worker consumes the two compact JSON reports already produced by the
ROOT362 recovery.  It never opens a Part/BI4 file.  It computes, separately
for each actual saved-time axis, trapezoidal integrals of the native compact
fluid observables and reports the saved-time/bracket structure.  The two
quantities are deliberately kept as observed diagnostics: because the same
and half-CFL rows are asynchronous, their difference does not identify an
integration error, an output error, or a truth value.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f1-s2.integral-output-separation-worker.v1"
MANIFEST_SCHEMA = "ds02.stage2.f1-s2.integral-output-separation-manifest.v1"
READY_STATUS = "PREPARED_ROOT371_F1_S2_INTEGRAL_OUTPUT_DIAGNOSTIC"
COMPLETE_STATUS = "COMPLETE_F1_S2_INTEGRAL_OUTPUT_DIAGNOSTIC_NO_SCIENTIFIC_Q"
MAX_JSON_BYTES = 10 * 1024 * 1024
UNKNOWN = "UNKNOWN"
FIELDS = ("speed_norm_m_per_s", "kinetic_energy_j")


class DiagnosticFailure(RuntimeError):
    pass


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {
        "device": int(value.st_dev),
        "inode": int(value.st_ino),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
    }


def _stat_equal(left: dict[str, int], right: dict[str, int]) -> bool:
    return all(int(left[key]) == int(right[key]) for key in ("device", "inode", "bytes", "mtime_ns", "ctime_ns"))


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _record(path: Path, label: str, *, parse: bool = True) -> tuple[Any, dict[str, Any]]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise DiagnosticFailure(f"{label} is not a regular non-symlink file: {path}")
    before = _stat(path)
    if before["bytes"] > MAX_JSON_BYTES:
        raise DiagnosticFailure(f"{label} exceeds the 10 MiB JSON cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if not _stat_equal(before, after) or len(raw) != before["bytes"]:
        raise DiagnosticFailure(f"{label} changed during bounded read: {path}")
    value: Any = None
    if parse:
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DiagnosticFailure(f"{label} is not bounded JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise DiagnosticFailure(f"{label} is not a JSON object")
    return value, {
        "path": str(path),
        "sha256": _digest(raw),
        "stat": after,
        "bytes": len(raw),
        "scope": "bounded_json_only",
        "payload_read_by_worker": True,
    }


def _record_ref(ref: Any, label: str) -> tuple[Any, dict[str, Any]]:
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
        raise DiagnosticFailure(f"{label} lacks a path record")
    value, actual = _record(Path(ref["path"]), label)
    expected_sha = ref.get("sha256")
    if not isinstance(expected_sha, str) or actual["sha256"] != expected_sha:
        raise DiagnosticFailure(f"{label} SHA does not match the bound record")
    expected_stat = ref.get("stat")
    if isinstance(expected_stat, dict):
        # The compact producers bind the complete five-field stat.  Requiring
        # every field prevents a changed inode or timestamp being hidden by an
        # unchanged content digest.
        if any(key not in expected_stat for key in actual["stat"]):
            raise DiagnosticFailure(f"{label} has an incomplete bound stat")
        for key in actual["stat"]:
            if int(actual["stat"][key]) != int(expected_stat[key]):
                raise DiagnosticFailure(f"{label} {key} changed since binding")
    return value, actual


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise DiagnosticFailure(f"{label} is boolean")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise DiagnosticFailure(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise DiagnosticFailure(f"{label} is not finite")
    return result


def _vector(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise DiagnosticFailure(f"{label} is not a three-vector")
    return [_finite(item, f"{label}[{index}]") for index, item in enumerate(value)]


def _norm(vector: list[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))


def _trapz(times: list[float], values: list[float]) -> float:
    if len(times) != len(values) or len(times) < 2:
        raise DiagnosticFailure("trapezoidal integral requires at least two aligned rows")
    return sum((times[index] - times[index - 1]) * (values[index] + values[index - 1]) / 2.0 for index in range(1, len(times)))


def _compact_observations(report: dict[str, Any], label: str) -> list[dict[str, Any]]:
    if report.get("schema") != "ds02.stage2.f1-s2.root279-native-compact-report.v1":
        raise DiagnosticFailure(f"{label} compact schema mismatch")
    if report.get("status") != "COMPLETE_ROOT279_NATIVE_COMPACT_REPORT":
        raise DiagnosticFailure(f"{label} compact report is not terminal: {report.get('status')}")
    if report.get("world_orientation") != UNKNOWN:
        raise DiagnosticFailure(f"{label} world orientation is not explicitly UNKNOWN")
    qualification = report.get("scientific_qualification")
    if not isinstance(qualification, dict) or any(qualification.get(key) != UNKNOWN for key in ("QI", "QN", "QE")):
        raise DiagnosticFailure(f"{label} compact report has unauthorized scientific qualification")
    identity = report.get("source_identity_digest")
    if not isinstance(identity, str) or len(identity) != 64:
        raise DiagnosticFailure(f"{label} source identity digest is missing")
    attempt = report.get("attempt")
    if not isinstance(attempt, dict) or attempt.get("label") != label:
        raise DiagnosticFailure(f"{label} compact attempt label mismatch")
    ident = attempt.get("identity")
    if not isinstance(ident, dict) or ident.get("sentinel_id") != "F1-S2" or ident.get("family_id") != "F1":
        raise DiagnosticFailure(f"{label} compact producer identity mismatch")
    observations = report.get("observations")
    if not isinstance(observations, list) or len(observations) < 2:
        raise DiagnosticFailure(f"{label} compact report has too few observations")
    rows: list[dict[str, Any]] = []
    previous = None
    for index, item in enumerate(observations):
        if not isinstance(item, dict):
            raise DiagnosticFailure(f"{label} observation {index} is not an object")
        time_s = _finite(item.get("time_s"), f"{label} observation time")
        if previous is not None and time_s <= previous:
            raise DiagnosticFailure(f"{label} saved-time axis is not strictly increasing")
        previous = time_s
        fluid = item.get("fluid")
        if not isinstance(fluid, dict) or item.get("fixed_moving_excluded_from_fluid_observables") is not True:
            raise DiagnosticFailure(f"{label} fluid-only observable contract is not explicit")
        com = _vector(fluid.get("com_m"), f"{label} COM")
        velocity = _vector(fluid.get("velocity_m_per_s"), f"{label} velocity")
        kinetic = _finite(fluid.get("kinetic_energy_j"), f"{label} kinetic energy")
        mass = _finite(fluid.get("mass_kg"), f"{label} native fluid mass")
        if mass < 0.0 or kinetic < 0.0:
            raise DiagnosticFailure(f"{label} contains a negative mass or kinetic energy")
        native_header = item.get("native_header")
        if not isinstance(native_header, dict) or native_header.get("mass_semantics") != "PER_PARTICLE_NATIVE_HEADER_WEIGHT":
            raise DiagnosticFailure(f"{label} native mass semantics are not per-particle")
        rows.append({"time_s": time_s, "com_m": com, "velocity_m_per_s": velocity, "speed_norm_m_per_s": _norm(velocity), "kinetic_energy_j": kinetic, "mass_kg": mass})
    return rows


def _bracket(rows: list[dict[str, Any]], query: float) -> dict[str, Any]:
    exact = [row for row in rows if row["time_s"] == query]
    if exact:
        return {"status": "EXACT_SAVED_TIME", "query_time_s": query, "lower": exact[0], "upper": exact[0], "width_s": 0.0, "interpolation": "NOT_PERFORMED"}
    lower = None
    upper = None
    for row in rows:
        if row["time_s"] < query:
            lower = row
        elif row["time_s"] > query:
            upper = row
            break
    if lower is None or upper is None:
        return {"status": "OUTSIDE_SAVED_WINDOW", "query_time_s": query, "interpolation": "FORBIDDEN"}
    return {"status": "BRACKETED_SAVED_TIME", "query_time_s": query, "lower": lower, "upper": upper, "width_s": upper["time_s"] - lower["time_s"], "interpolation": "NOT_PERFORMED"}


def _endpoint_change(bracket: dict[str, Any], field: str) -> dict[str, Any]:
    if bracket.get("status") != "BRACKETED_SAVED_TIME":
        return {"status": bracket.get("status"), "field": field, "value": None}
    left = bracket["lower"][field]
    right = bracket["upper"][field]
    if field == "com_m":
        delta = [right[index] - left[index] for index in range(3)]
        return {"status": "OBSERVED_ENDPOINT_CHANGE", "field": field, "delta": delta, "norm_m": _norm(delta)}
    return {"status": "OBSERVED_ENDPOINT_CHANGE", "field": field, "delta": right - left}


def _run_summary(label: str, rows: list[dict[str, Any]], queries: list[float]) -> dict[str, Any]:
    times = [row["time_s"] for row in rows]
    gaps = [times[index] - times[index - 1] for index in range(1, len(times))]
    integrals = {field: _trapz(times, [row[field] for row in rows]) for field in FIELDS}
    brackets = [_bracket(rows, query) for query in queries]
    return {
        "label": label,
        "saved_row_count": len(rows),
        "saved_time_window_s": [times[0], times[-1]],
        "saved_time_gaps_s": {"min": min(gaps), "max": max(gaps), "mean": sum(gaps) / len(gaps)},
        "trapezoidal_integrals": integrals,
        "brackets": brackets,
        "endpoint_change_diagnostics": [{"query_time_s": item["query_time_s"], "width_s": item.get("width_s"), "com": _endpoint_change(item, "com_m"), "speed_norm_m_per_s": _endpoint_change(item, "speed_norm_m_per_s"), "kinetic_energy_j": _endpoint_change(item, "kinetic_energy_j")} for item in brackets],
        "interpretation": "actual saved-time integral and endpoint/output diagnostics; no interpolation and no error-bound claim",
    }


def _diff(left: float, right: float) -> dict[str, Any]:
    return {"absolute": abs(right - left), "left": left, "right": right}


def _validate_lineage(manifest: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    proof, _ = _record_ref(manifest.get("root362_proof"), "ROOT362 proof")
    recovery, _ = _record_ref(manifest.get("recovery_report"), "ROOT362 recovery report")
    scalar, _ = _record_ref(manifest.get("scalar_result"), "ROOT362 scalar result")
    if proof.get("status") != "VERIFIED_ACTUAL_ROOT279_METADATA_RECOVERY_COMPACT_SCALAR_CHAIN_NO_NATIVE_REREAD_NO_Q":
        raise DiagnosticFailure("ROOT362 proof status mismatch")
    if proof.get("report_sha256") != manifest["recovery_report"]["sha256"]:
        raise DiagnosticFailure("ROOT362 proof does not bind the recovery report")
    if not (proof.get("actual_native_selected_read_after_reservation") is False and proof.get("native_payload_reopened_by_recovery") is False and proof.get("scientific_Q_credit") == 0 and proof.get("world_orientation") == UNKNOWN):
        raise DiagnosticFailure("ROOT362 proof has an unauthorized read or qualification claim")
    if recovery.get("schema") != "ds02.stage2.f1-s2.root279-native-scalar-recovery-worker.v1" or recovery.get("status") != "COMPLETE_ROOT279_METADATA_RECOVERY_COMPACT_V3_SCALAR_V2_VERIFIER_NO_NATIVE_REREAD":
        raise DiagnosticFailure("ROOT362 recovery report schema/status mismatch")
    if recovery.get("scalar_result", {}).get("sha256") != manifest["scalar_result"]["sha256"]:
        raise DiagnosticFailure("ROOT362 recovery report does not bind the scalar result")
    if scalar.get("schema") != "ds02.stage2.rotation-invariant-native-scalar-observer.v2" or scalar.get("status") != "COMPLETE_ROTATION_INVARIANT_NATIVE_SCALAR_DIAGNOSTIC":
        raise DiagnosticFailure("ROOT362 scalar result schema/status mismatch")
    q = scalar.get("scientific_qualification")
    if not isinstance(q, dict) or q.get("scientific_credit") != 0 or any(q.get(key) != UNKNOWN for key in ("QI", "QN", "QE")):
        raise DiagnosticFailure("ROOT362 scalar result has unauthorized qualification")
    if scalar.get("axis_scope", {}).get("producer_to_world_orientation") != UNKNOWN:
        raise DiagnosticFailure("ROOT362 scalar world orientation is not UNKNOWN")
    return proof, recovery, scalar


def run(manifest_path: Path, output: Path) -> dict[str, Any]:
    manifest, manifest_record = _record(manifest_path, "F1-S2 integral/output manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != READY_STATUS:
        raise DiagnosticFailure("manifest schema/status mismatch")
    queries = manifest.get("registered_query_times_s")
    if not isinstance(queries, list) or queries != sorted(set(queries)) or not queries:
        raise DiagnosticFailure("registered query times must be sorted and unique")
    queries = [_finite(value, "registered query time") for value in queries]
    proof, recovery, scalar = _validate_lineage(manifest)
    calibration, _ = _record_ref(manifest.get("calibration_contract"), "F1-S2 calibration contract")
    calibration_q = calibration.get("scientific_qualification") or calibration.get("interpretation", {}).get("scientific_qualification", {})
    if calibration.get("schema") != "ds02.stage2.f1-s2.common-endpoint-calibration.v1" or calibration_q.get("QN") != UNKNOWN:
        raise DiagnosticFailure("calibration contract schema/qualification mismatch")
    producers = manifest.get("producers")
    if not isinstance(producers, list) or [item.get("label") for item in producers if isinstance(item, dict)] != ["same_cfl", "half_cfl"]:
        raise DiagnosticFailure("manifest must contain same_cfl followed by half_cfl")
    reports: dict[str, dict[str, Any]] = {}
    report_records: dict[str, dict[str, Any]] = {}
    identities: set[str] = set()
    for item in producers:
        label = item.get("label")
        report, record = _record_ref(item.get("report"), f"{label} compact report")
        rows = _compact_observations(report, label)
        reports[label] = {"report": report, "rows": rows}
        report_records[label] = record
        identities.add(str(report["source_identity_digest"]))
    if len(identities) != 1:
        raise DiagnosticFailure("same/half compact reports do not share source identity")
    summaries = {label: _run_summary(label, value["rows"], queries) for label, value in reports.items()}
    same = summaries["same_cfl"]; half = summaries["half_cfl"]
    exact_pairs = []
    same_rows = reports["same_cfl"]["rows"]
    half_rows = reports["half_cfl"]["rows"]
    for left in same_rows:
        for right in half_rows:
            if left["time_s"] == right["time_s"]:
                exact_pairs.append({"time_s": left["time_s"], "same_cfl": left, "half_cfl": right, "field_differences": {field: (left[field] - right[field]) for field in ("speed_norm_m_per_s", "kinetic_energy_j")}})
    result = {
        "schema": SCHEMA,
        "status": COMPLETE_STATUS,
        "manifest": manifest_record,
        "lineage": {"root362_proof": manifest["root362_proof"], "recovery_report": manifest["recovery_report"], "scalar_result": manifest["scalar_result"], "calibration_contract": manifest["calibration_contract"]},
        "producers": {label: {"report": report_records[label], "actual_cfl": calibration["actual_pair_controls"][label]["effective_cfl"], "output_interval_s": calibration["actual_pair_controls"][label]["output_interval_s"] if "output_interval_s" in calibration["actual_pair_controls"][label] else calibration["actual_pair_controls"]["common_output_contract"]["output_interval_s"]} for label in report_records},
        "summaries": summaries,
        "exact_same_time_pairs": exact_pairs,
        "observed_integral_differences": {field: _diff(same["trapezoidal_integrals"][field], half["trapezoidal_integrals"][field]) for field in FIELDS},
        "observed_output_sampling_differences": {"terminal_time_s": _diff(same["saved_time_window_s"][1], half["saved_time_window_s"][1]), "saved_row_count": same["saved_row_count"] - half["saved_row_count"], "mean_gap_s": _diff(same["saved_time_gaps_s"]["mean"], half["saved_time_gaps_s"]["mean"])},
        "interpretation": {"integration_scope": "trapezoidal integral on each actual saved-time axis; observed diagnostic only", "output_scope": "actual saved-time gaps and no-interpolation endpoint brackets", "separation_status": "NOT_IDENTIFIABLE_INTEGRATION_VS_OUTPUT_FROM_ASYNCHRONOUS_PAIR", "bracket_width_is_error": False, "integral_difference_is_integration_error": False, "world_orientation": UNKNOWN, "neighbor_grid_truth": False},
        "registered_scope": {"query_times_s": queries, "frozen_error_budget": calibration.get("frozen_tolerances"), "units": {"position": "m component-space", "velocity": "m/s component-space", "kinetic_energy": "J", "time": "s"}, "zero_reference": "undefined unless a task-specific nonzero scale is registered"},
        "scientific_qualification": {"QI": UNKNOWN, "QN": UNKNOWN, "QE": UNKNOWN, "scientific_credit": 0},
        "read_scope": {"bounded_json_only": True, "native_bi4_read": False, "vtk_read": False, "hdf5_read": False, "solver_launch": False, "gencase_launch": False, "interpolation": False},
    }
    _write_once(output, result)
    return result


def _write_once(path: Path, value: Any) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise DiagnosticFailure(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _fixture_report(label: str, times: list[float]) -> dict[str, Any]:
    rows = []
    for index, time_s in enumerate(times):
        rows.append({"time_s": time_s, "fixed_moving_excluded_from_fluid_observables": True, "fluid": {"com_m": [float(index), 0.0, 0.0], "velocity_m_per_s": [float(index), 0.0, 0.0], "kinetic_energy_j": float(index * index), "mass_kg": 340.0}, "native_header": {"mass_semantics": "PER_PARTICLE_NATIVE_HEADER_WEIGHT"}})
    return {"schema": "ds02.stage2.f1-s2.root279-native-compact-report.v1", "status": "COMPLETE_ROOT279_NATIVE_COMPACT_REPORT", "world_orientation": UNKNOWN, "scientific_qualification": {"QI": UNKNOWN, "QN": UNKNOWN, "QE": UNKNOWN}, "source_identity_digest": "a" * 64, "attempt": {"label": label, "identity": {"family_id": "F1", "sentinel_id": "F1-S2"}}, "observations": rows}


def _self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="f1-s2-integral-output-") as temporary:
        root = Path(temporary)
        files: dict[str, Path] = {}
        same = root / "same.json"; same.write_text(json.dumps(_fixture_report("same_cfl", [0.0, 0.25, 0.5])) + "\n")
        half = root / "half.json"; half.write_text(json.dumps(_fixture_report("half_cfl", [0.0, 0.24, 0.5])) + "\n")
        scalar = root / "scalar.json"; scalar.write_text(json.dumps({"schema": "ds02.stage2.rotation-invariant-native-scalar-observer.v2", "status": "COMPLETE_ROTATION_INVARIANT_NATIVE_SCALAR_DIAGNOSTIC", "scientific_qualification": {"QI": UNKNOWN, "QN": UNKNOWN, "QE": UNKNOWN, "scientific_credit": 0}, "axis_scope": {"producer_to_world_orientation": UNKNOWN}}) + "\n")
        recovery = root / "recovery.json"; recovery.write_text(json.dumps({"schema": "ds02.stage2.f1-s2.root279-native-scalar-recovery-worker.v1", "status": "COMPLETE_ROOT279_METADATA_RECOVERY_COMPACT_V3_SCALAR_V2_VERIFIER_NO_NATIVE_REREAD", "report": "PLACEHOLDER", "scalar_result": {"sha256": _digest(scalar.read_bytes())}}) + "\n")
        proof = root / "proof.json"; proof.write_text(json.dumps({"status": "VERIFIED_ACTUAL_ROOT279_METADATA_RECOVERY_COMPACT_SCALAR_CHAIN_NO_NATIVE_REREAD_NO_Q", "report_sha256": _digest(recovery.read_bytes()), "actual_native_selected_read_after_reservation": False, "native_payload_reopened_by_recovery": False, "scientific_Q_credit": 0, "world_orientation": UNKNOWN}) + "\n")
        calibration = root / "calibration.json"; calibration.write_text(json.dumps({"schema": "ds02.stage2.f1-s2.common-endpoint-calibration.v1", "scientific_qualification": {"QN": UNKNOWN}, "actual_pair_controls": {"same_cfl": {"effective_cfl": 0.2, "output_interval_s": 0.005}, "half_cfl": {"effective_cfl": 0.1, "output_interval_s": 0.005}, "common_output_contract": {"output_interval_s": 0.005}}, "frozen_tolerances": {"time": 0.25}}) + "\n")
        def ref(path: Path) -> dict[str, Any]:
            return {"path": str(path), "sha256": _digest(path.read_bytes()), "stat": _stat(path)}
        manifest = {"schema": MANIFEST_SCHEMA, "status": READY_STATUS, "registered_query_times_s": [0.0, 0.25, 0.5], "root362_proof": ref(proof), "recovery_report": ref(recovery), "scalar_result": ref(scalar), "calibration_contract": ref(calibration), "producers": [{"label": "same_cfl", "report": ref(same)}, {"label": "half_cfl", "report": ref(half)}]}
        manifest_path = root / "manifest.json"; manifest_path.write_text(json.dumps(manifest) + "\n")
        output = root / "result.json"
        result = run(manifest_path, output)
        assert result["status"] == COMPLETE_STATUS
        assert result["scientific_qualification"]["scientific_credit"] == 0
        assert result["interpretation"]["separation_status"].startswith("NOT_IDENTIFIABLE")
        assert result["exact_same_time_pairs"]
        bad = json.loads(manifest_path.read_text()); bad["producers"][0]["report"]["sha256"] = "0" * 64; bad_path = root / "bad.json"; bad_path.write_text(json.dumps(bad) + "\n")
        try:
            run(bad_path, root / "bad-result.json")
        except DiagnosticFailure:
            pass
        else:
            raise AssertionError("tampered compact report was accepted")
    print("PASS_F1_S2_INTEGRAL_OUTPUT_SEPARATION_WORKER_NO_Q")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test(); return 0
        if args.manifest is None or args.output is None:
            parser.error("--run requires --manifest and --output")
        result = run(args.manifest, args.output)
        print(json.dumps({"status": result["status"], "output": str(args.output.expanduser().absolute()), "scientific_credit": 0}, sort_keys=True))
        return 0
    except (DiagnosticFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_F1_S2_INTEGRAL_OUTPUT_SEPARATION: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
