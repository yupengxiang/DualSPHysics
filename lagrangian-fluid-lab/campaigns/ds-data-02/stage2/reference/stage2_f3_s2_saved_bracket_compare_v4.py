#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Guarded F3 three-grid comparison for legacy and compact full reports.

ROOT150 is a legacy full report whose proof directly names report and
report_sha256. ROOT177/178 proofs instead expose a small summary and
full_report_stat_only record; the latter is the authoritative full-report
path/SHA/stat join. The builder only reads the proof, request, receipt,
summary, and filesystem metadata. This worker reads each large report once
after parent reservation, verifies stable pre/post stat and SHA, and then
uses the consumed saved-endpoint comparison semantics. It never opens native
payloads, interpolates a particle/time field, or treats a neighbouring grid
as truth.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f3-s2.saved-bracket-comparison.v4"
PASS_STATUS = "PASS_F3_SAVED_BRACKET_DIAGNOSTICS_V4"
UNKNOWN_STATUS = "UNKNOWN_F3_SAVED_BRACKET_DIAGNOSTICS_V4"
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
QUERY_TIMES_S = (0.0, 2.0, 4.0, 6.0, 8.0)
TIME_TOLERANCE_S = 1.0e-10

REPORT_CONTRACTS: dict[str, dict[str, set[str]]] = {
    "coarse": {
        "schemas": {"ds02.stage2.f3-s2.full-native-stream-observer.v2", "ds02.stage2.f3-s2.full-native-stream-observer.v3"},
        "statuses": {"PASS_FULL_NATIVE_STREAM_V2", "PASS_F3_FULL_NATIVE_STREAM_STRICT_SOURCE_JOIN"},
    },
    "middle": {
        "schemas": {"ds02.stage2.f3-s2.middle-selected-native-observer.v1", "ds02.stage2.f3-s2.full-native-stream-observer.v3"},
        "statuses": {"PASS_MIDDLE_SELECTED_NATIVE_FIELDS", "PASS_F3_FULL_NATIVE_STREAM_STRICT_SOURCE_JOIN"},
    },
    "fine": {
        "schemas": {
            "ds02.stage2.f3-s2.fine-selected-native-observer.v1",
            "ds02.stage2.f3-s2.fine-selected-native-observer.v2",
            "ds02.stage2.f3-s2.full-native-stream-observer.v3",
        },
        "statuses": {"PASS_FINE_SELECTED_NATIVE_FIELDS", "PASS_FINE_SELECTED_NATIVE_FIELDS_STRICT_SOURCE_JOIN", "PASS_F3_FULL_NATIVE_STREAM_STRICT_SOURCE_JOIN"},
    },
}


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{label} is not finite numeric data")
    return float(value)


def _vector(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{label} is not a 3-vector")
    return [_finite(item, f"{label}[{index}]") for index, item in enumerate(value)]


def _stat_tuple(path: Path) -> tuple[int, int, int, int, int, int]:
    stat = path.stat()
    return (
        int(stat.st_size),
        int(stat.st_mtime_ns),
        int(stat.st_ctime_ns),
        int(stat.st_dev),
        int(stat.st_ino),
        int(stat.st_mode),
    )


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _regular(path: Path, label: str) -> Path:
    raw = path.expanduser()
    if raw.is_symlink() or not raw.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {raw}")
    path = raw.resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} resolved target is not regular: {path}")
    return path


def _read_json_stable(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _regular(path, label)
    before = _stat_tuple(path)
    data = path.read_bytes()
    after = _stat_tuple(path)
    if before != after:
        raise RuntimeError(f"{label} changed while being read: {path}")
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value, {
        "path": str(path),
        "bytes": len(data),
        "sha256": _sha_bytes(data),
        "stat_before": _stat_dict(before),
        "stat_after": _stat_dict(after),
        "stable_read": True,
    }


def _stat_dict(value: tuple[int, int, int, int, int, int]) -> dict[str, int]:
    return {
        "size": value[0],
        "mtime_ns": value[1],
        "ctime_ns": value[2],
        "st_dev": value[3],
        "st_ino": value[4],
        "mode": value[5],
    }


def _file_record(path: Path, label: str, *, read: bool = True) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Return a stable small-file record, optionally parsing JSON."""

    path = _regular(path, label)
    before = _stat_tuple(path)
    data = path.read_bytes()
    after = _stat_tuple(path)
    if before != after:
        raise RuntimeError(f"{label} changed while being read: {path}")
    record = {
        "path": str(path),
        "bytes": len(data),
        "sha256": _sha_bytes(data),
        "stat_before": _stat_dict(before),
        "stat_after": _stat_dict(after),
        "stable_read": True,
    }
    if not read:
        return None, record
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value, record


def _metadata_record(path: Path, label: str) -> dict[str, Any]:
    """Stat a deferred report without opening or hashing its bytes."""

    path = _regular(path, label)
    stat = _stat_tuple(path)
    return {
        "path": str(path),
        "bytes": stat[0],
        "stat": _stat_dict(stat),
        "content_read": False,
    }


def _assert_hash(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower()):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return value.lower()


def _assert_small_file(path: Path, expected_sha: Any, label: str) -> dict[str, Any]:
    _, record = _file_record(path, label)
    expected = _assert_hash(expected_sha, f"{label} SHA")
    if record["sha256"] != expected:
        raise ValueError(f"{label} SHA does not match proof")
    return record


def _proof_binding(proof_path: Path, report_path: Path, report_sha: str, label: str) -> dict[str, Any]:
    """Join proof, request, receipt, summary, and deferred full report."""

    proof, proof_record = _file_record(proof_path, f"{label} proof")
    assert proof is not None
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1":
        raise ValueError(f"{label} proof schema is not the actual root verification schema")
    if "ACTUAL" not in str(proof.get("status", "")):
        raise ValueError(f"{label} proof is not an actual terminal proof")

    request_path = Path(str(proof.get("request", ""))).expanduser().resolve()
    receipt_path = Path(str(proof.get("receipt", ""))).expanduser().resolve()
    if not request_path.is_file() or not receipt_path.is_file():
        raise FileNotFoundError(f"{label} proof request/receipt path is missing")
    request_record = _assert_small_file(request_path, proof.get("request_sha256"), f"{label} proof request")
    receipt_record = _assert_small_file(receipt_path, proof.get("receipt_sha256"), f"{label} proof receipt")

    case_binding = proof.get("case_binding")
    terminal_request_record = None
    if isinstance(case_binding, dict) and isinstance(case_binding.get("request_record"), dict):
        terminal = case_binding["request_record"]
        terminal_path = Path(str(terminal.get("path", ""))).expanduser().resolve()
        terminal_request_record = _assert_small_file(terminal_path, terminal.get("sha256"), f"{label} terminal solver request")
        if case_binding.get("terminal_request_sha256") not in (None, terminal_request_record["sha256"]):
            raise ValueError(f"{label} terminal request SHA differs from case binding")

    report_path = report_path.expanduser().resolve()
    compact_record = proof.get("full_report_stat_only")
    summary_record = None
    if isinstance(compact_record, dict):
        if compact_record.get("stable_read") is not True:
            raise ValueError(f"{label} compact proof full_report_stat_only is not stable")
        if compact_record.get("stat_before") != compact_record.get("stat_after"):
            raise ValueError(f"{label} compact proof full report pre/post stat differs")
        expected_report_path = Path(str(compact_record.get("path", ""))).expanduser().resolve()
        expected_report_sha = _assert_hash(compact_record.get("sha256"), f"{label} compact full report")
        if expected_report_path != report_path:
            raise ValueError(f"{label} compact full report path does not match supplied report")
        summary_path = Path(str(proof.get("summary", ""))).expanduser().resolve()
        summary_record = _assert_small_file(summary_path, proof.get("summary_sha256"), f"{label} compact summary")
        if proof.get("summary_bytes") not in (None, summary_record["bytes"]):
            raise ValueError(f"{label} compact summary byte count differs")
        if compact_record.get("bytes") != os.stat(report_path).st_size:
            raise ValueError(f"{label} compact full report current size differs from proof")
    else:
        expected_report_path = Path(str(proof.get("report", ""))).expanduser().resolve()
        expected_report_sha = _assert_hash(proof.get("report_sha256"), f"{label} legacy full report")
        if expected_report_path != report_path:
            raise ValueError(f"{label} legacy proof report path does not match supplied report")
        if proof.get("report_bytes") not in (None, os.stat(report_path).st_size):
            raise ValueError(f"{label} legacy report byte count differs from proof")

    if report_sha != expected_report_sha:
        raise ValueError(f"{label} full report SHA does not match proof")
    return {
        "proof": proof_record,
        "status": proof.get("status"),
        "proof_schema": proof.get("schema"),
        "request": request_record,
        "receipt": receipt_record,
        "terminal_request": terminal_request_record,
        "summary": summary_record,
        "full_report_stat_only": compact_record,
        "expected_report_sha256": expected_report_sha,
        "case_binding": case_binding,
    }

def _time(observation: dict[str, Any], label: str) -> float:
    if "runparts_time_s" in observation:
        return _finite(observation["runparts_time_s"], f"{label} RunPARTs time")
    if "time" in observation and isinstance(observation["time"], dict):
        if "runparts_s" in observation["time"]:
            return _finite(observation["time"]["runparts_s"], f"{label} RunPARTs time")
        if "decoded_s" in observation["time"]:
            return _finite(observation["time"]["decoded_s"], f"{label} decoded time")
    if "decoded_time_s" in observation:
        return _finite(observation["decoded_time_s"], f"{label} decoded time")
    raise ValueError(f"{label} has no actual saved time")


def _native_mass(observation: dict[str, Any], label: str) -> float:
    header = observation.get("native_header")
    if not isinstance(header, dict):
        raise ValueError(f"{label} has no native header")
    mass = header.get("MassFluid")
    if not isinstance(mass, dict):
        raise ValueError(f"{label} has no native MassFluid object")
    return _finite(mass.get("value"), f"{label} native MassFluid")


def _fluid_observables(observation: dict[str, Any], label: str) -> dict[str, Any]:
    value = observation.get("fluid_observable_using_native_header_mass")
    if not isinstance(value, dict):
        value = observation.get("fluid_observables")
    if not isinstance(value, dict):
        raise ValueError(f"{label} has no native-mass fluid observables")
    centroid = value.get("weighted_centroid_m")
    velocity = value.get("weighted_velocity_m_per_s")
    kinetic = value.get("kinetic_energy_j")
    count = value.get("fluid_count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise ValueError(f"{label} fluid_count is invalid")
    return {
        "weighted_centroid_m": None if centroid is None else _vector(centroid, f"{label} centroid"),
        "weighted_velocity_m_per_s": None if velocity is None else _vector(velocity, f"{label} velocity"),
        "kinetic_energy_j": None if kinetic is None else _finite(kinetic, f"{label} kinetic energy"),
        "fluid_count": count,
        "sample_mass_kg": _finite(value.get("sample_mass_kg"), f"{label} native sample mass"),
        "mass_semantics": str(value.get("mass_semantics", "UNKNOWN")),
    }


def _observation(value: dict[str, Any], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} observation is not an object")
    frame = value.get("frame")
    if not isinstance(frame, int) or isinstance(frame, bool) or frame < 0:
        raise ValueError(f"{label} frame is invalid")
    observables = _fluid_observables(value, label)
    return {
        "frame": frame,
        "time_s": _time(value, label),
        "native_massfluid_kg": _native_mass(value, label),
        "fields": observables,
        "field_digest_sha256": str(value.get("field_digest_sha256", "")),
    }


def _validate_report(path: Path, proof_path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    report, report_record = _file_record(path, f"{label} observer report")
    assert report is not None
    contract = REPORT_CONTRACTS[label]
    if report.get("schema") not in contract["schemas"] or report.get("status") not in contract["statuses"]:
        raise ValueError(f"{label} observer schema/status is not the expected source-bound report")
    if report.get("physical_case_id") not in (None, PHYSICAL_CASE_ID):
        raise ValueError(f"{label} physical case identity mismatch")
    scope = report.get("scope") if isinstance(report.get("scope"), dict) else {}
    if scope.get("typed_conversion") not in (None, "NOT_PERFORMED"):
        raise ValueError(f"{label} report includes an unexpected typed conversion")
    if scope.get("particle_field_interpolation") not in (None, "NOT_PERFORMED"):
        raise ValueError(f"{label} report includes particle interpolation")
    if report.get("schema") == "ds02.stage2.f3-s2.full-native-stream-observer.v3":
        binding = report.get("strict_source_binding")
        if scope.get("full_native_window") is not True or not isinstance(binding, dict):
            raise ValueError(f"{label} full v3 report lacks full-window strict source binding")
        for key in ("terminal_request_sha256", "generated_xml_sha256", "source_snapshot_proof_sha256", "bi4_sha256"):
            if not isinstance(binding.get(key), str) or len(binding[key]) != 64:
                raise ValueError(f"{label} full v3 report lacks {key}")
    observations = report.get("observations")
    if not isinstance(observations, list) or not observations:
        raise ValueError(f"{label} report has no observations")
    parsed = [_observation(item, f"{label} frame {index}") for index, item in enumerate(observations)]
    parsed.sort(key=lambda item: (item["time_s"], item["frame"]))
    frames = [item["frame"] for item in parsed]
    if len(frames) != len(set(frames)):
        raise ValueError(f"{label} report has duplicate observation frame IDs")
    times = [item["time_s"] for item in parsed]
    if any(right <= left for left, right in zip(times, times[1:])):
        raise ValueError(f"{label} observer times are not strictly increasing")
    proof_info = _proof_binding(proof_path, path.expanduser().resolve(), report_record["sha256"], label)
    return {
        "label": label,
        "schema": report["schema"],
        "status": report["status"],
        "report": report_record,
        "proof": proof_info,
        "observations": parsed,
        "frame_ids": frames,
        "first_saved_time_s": times[0],
        "last_saved_time_s": times[-1],
        "native_massfluid_values": sorted(set(item["native_massfluid_kg"] for item in parsed)),
    }, report

def _bracket(run: dict[str, Any], query: float) -> dict[str, Any]:
    observations = run["observations"]
    times = [item["time_s"] for item in observations]
    if query < times[0] or query > times[-1]:
        return {"query_time_s": query, "status": "OUTSIDE_SAVED_WINDOW"}
    right = bisect.bisect_left(times, query)
    if right == 0:
        return {"query_time_s": query, "status": "EXACT_OR_LEFT", "lower_index": 0, "upper_index": 0, "lower_time_s": times[0], "upper_time_s": times[0]}
    if right == len(times):
        right -= 1
    if abs(times[right] - query) <= TIME_TOLERANCE_S:
        return {"query_time_s": query, "status": "EXACT", "lower_index": right, "upper_index": right, "lower_time_s": times[right], "upper_time_s": times[right]}
    left = right - 1
    return {
        "query_time_s": query,
        "status": "BRACKETED",
        "lower_index": left,
        "upper_index": right,
        "lower_time_s": times[left],
        "upper_time_s": times[right],
        "bracket_width_s": times[right] - times[left],
    }


def _endpoint(run: dict[str, Any], bracket: dict[str, Any], side: str) -> dict[str, Any] | None:
    if bracket.get("status") not in {"EXACT", "EXACT_OR_LEFT", "BRACKETED"}:
        return None
    index_key = "lower_index" if side == "lower" else "upper_index"
    return run["observations"][int(bracket[index_key])]


def _difference(left: Any, right: Any) -> dict[str, Any]:
    if isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        delta = [float(a) - float(b) for a, b in zip(left, right)]
        magnitude = math.sqrt(sum(item * item for item in delta))
        scale = max(
            math.sqrt(sum(float(item) * float(item) for item in left)),
            math.sqrt(sum(float(item) * float(item) for item in right)),
        )
    elif isinstance(left, (int, float)) and isinstance(right, (int, float)):
        delta = float(left) - float(right)
        magnitude = abs(delta)
        scale = max(abs(float(left)), abs(float(right)))
    else:
        return {"status": "UNKNOWN_INCOMPATIBLE_FIELD_SHAPE"}
    return {
        "status": "MEASURED",
        "left": left,
        "right": right,
        "absolute_difference": delta,
        "absolute_norm": magnitude,
        "relative_difference_nonzero_scale": magnitude / scale if scale > 0.0 else None,
    }


def _compare_pair(left: dict[str, Any], right: dict[str, Any], query: float) -> dict[str, Any]:
    left_bracket = _bracket(left, query)
    right_bracket = _bracket(right, query)
    endpoints: list[dict[str, Any]] = []
    for side in ("lower", "upper"):
        left_obs = _endpoint(left, left_bracket, side)
        right_obs = _endpoint(right, right_bracket, side)
        if left_obs is None or right_obs is None:
            endpoints.append({"side": side, "status": "UNKNOWN_OUTSIDE_SAVED_WINDOW", "interpolation_performed": False, "truth_credit": False})
            continue
        left_time = left_obs["time_s"]
        right_time = right_obs["time_s"]
        aligned = abs(left_time - right_time) <= TIME_TOLERANCE_S
        metrics: dict[str, Any] = {}
        for key in sorted(set(left_obs["fields"]) & set(right_obs["fields"])):
            if key == "mass_semantics":
                continue
            if left_obs["fields"][key] is None or right_obs["fields"][key] is None:
                metrics[key] = {"status": "UNKNOWN_MISSING_FIELD"}
            else:
                metrics[key] = _difference(left_obs["fields"][key], right_obs["fields"][key])
                metrics[key]["scientific_error_status"] = "MEASURED_ALIGNED_SAVED_TIME" if aligned else "UNKNOWN_TIME_ALIGNMENT"
        endpoints.append({
            "side": side,
            "left_frame": left_obs["frame"],
            "right_frame": right_obs["frame"],
            "left_saved_time_s": left_time,
            "right_saved_time_s": right_time,
            "time_difference_s_right_minus_left": right_time - left_time,
            "time_alignment_status": "ALIGNED_WITHIN_TOLERANCE" if aligned else "NOT_ALIGNED",
            "fields": metrics,
            "interpolation_performed": False,
            "error_bound": "UNKNOWN_NOT_ESTIMATED",
            "truth_credit": False,
        })
    return {
        "left_run": left["label"],
        "right_run": right["label"],
        "query_time_s": query,
        "left_bracket": left_bracket,
        "right_bracket": right_bracket,
        "endpoints": endpoints,
        "comparison_semantics": "actual saved endpoint diagnostics; no particle/time interpolation",
        "spatial_truth": False,
        "integration_error_bound": "UNKNOWN_NOT_ESTIMATED",
    }


def build_report(
    report_paths: dict[str, Path],
    proof_paths: dict[str, Path],
    output: Path,
    queries: list[float] | None = None,
) -> dict[str, Any]:
    queries = list(QUERY_TIMES_S if queries is None else queries)
    if not queries or any(not math.isfinite(float(item)) for item in queries):
        raise ValueError("queries must be finite and nonempty")
    runs: dict[str, dict[str, Any]] = {}
    for label in ("coarse", "middle", "fine"):
        if label not in report_paths or label not in proof_paths:
            raise ValueError(f"missing {label} report/proof binding")
        runs[label], _ = _validate_report(report_paths[label], proof_paths[label], label)
    pairwise: list[dict[str, Any]] = []
    for left_label, right_label in (("coarse", "middle"), ("coarse", "fine"), ("middle", "fine")):
        for query in queries:
            pairwise.append(_compare_pair(runs[left_label], runs[right_label], float(query)))
    result = {
        "schema": SCHEMA,
        "status": PASS_STATUS,
        "family_id": "F3",
        "sentinel_id": "F3-S2",
        "physical_case_id": PHYSICAL_CASE_ID,
        "scope": {
            "runs": ["coarse", "middle", "fine"],
            "queries_s": queries,
            "input_reports_read_after_parent_reservation": True,
            "native_payloads_read_by_consumer": False,
            "hdf5_read": False,
            "typed_conversion": "NOT_PERFORMED",
            "particle_field_interpolation": "NOT_PERFORMED",
            "time_interpolation": "NOT_PERFORMED",
            "adjacent_grid_truth": False,
            "error_bounds": "UNKNOWN_NOT_ESTIMATED",
        },
        "runs": {
            label: {
                "schema": run["schema"],
                "status": run["status"],
                "report": run["report"],
                "proof": run["proof"],
                "frame_count": len(run["observations"]),
                "frame_ids": run["frame_ids"],
                "first_saved_time_s": run["first_saved_time_s"],
                "last_saved_time_s": run["last_saved_time_s"],
                "native_massfluid_values": run["native_massfluid_values"],
            }
            for label, run in runs.items()
        },
        "pairwise_saved_bracket_diagnostics": pairwise,
        "qualification": {
            "QI": "PASS_LIMITED_SAVED_BRACKET_DIAGNOSTICS",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "reason": "actual endpoint fields and time brackets were checked; asynchronous differences are not integration/output error bounds and do not provide neighbouring-grid truth",
        },
    }
    output = output.expanduser().resolve()
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable comparison output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return result


def _self_test_compact_schema() -> None:
    """Exercise the ROOT177/178 compact proof adapter without large input."""

    with tempfile.TemporaryDirectory(prefix="ds02-root172-v4-schema-") as directory:
        root = Path(directory)
        report_path = root / "full-report.json"
        summary_path = root / "summary.json"
        request_path = root / "request.json"
        receipt_path = root / "receipt.json"
        observation = {
            "frame": 0,
            "runparts_time_s": 0.0,
            "native_header": {"MassFluid": {"value": 1.0}},
            "fluid_observable_using_native_header_mass": {
                "weighted_centroid_m": [0.0, 0.0, 0.0],
                "weighted_velocity_m_per_s": [0.0, 0.0, 0.0],
                "kinetic_energy_j": 0.0,
                "fluid_count": 1,
                "sample_mass_kg": 1.0,
                "mass_semantics": "native_header",
            },
        }
        report = {
            "schema": "ds02.stage2.f3-s2.full-native-stream-observer.v3",
            "status": "PASS_F3_FULL_NATIVE_STREAM_STRICT_SOURCE_JOIN",
            "physical_case_id": PHYSICAL_CASE_ID,
            "scope": {"full_native_window": True, "typed_conversion": "NOT_PERFORMED", "particle_field_interpolation": "NOT_PERFORMED"},
            "strict_source_binding": {key: "0" * 64 for key in ("terminal_request_sha256", "generated_xml_sha256", "source_snapshot_proof_sha256", "bi4_sha256")},
            "observations": [observation],
        }
        summary = {"schema": "ds02.stage2.f3-s2.full-native-stream-observer.v5.summary", "status": "COMPACT_FIXTURE"}
        request_path.write_text("{}\n", encoding="utf-8")
        receipt_path.write_text("{}\n", encoding="utf-8")
        summary_path.write_text(json.dumps(summary) + "\n", encoding="utf-8")
        report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")
        _, report_record = _file_record(report_path, "compact fixture report")
        _, summary_record = _file_record(summary_path, "compact fixture summary")
        _, request_record = _file_record(request_path, "compact fixture request")
        _, receipt_record = _file_record(receipt_path, "compact fixture receipt")
        stat = report_record["stat_after"]
        proof = {
            "schema": "ds02.stage2.root-actual-verification.v1",
            "status": "VERIFIED_ACTUAL_COMPACT_FIXTURE",
            "request": str(request_path),
            "request_sha256": request_record["sha256"],
            "receipt": str(receipt_path),
            "receipt_sha256": receipt_record["sha256"],
            "summary": str(summary_path),
            "summary_sha256": summary_record["sha256"],
            "summary_bytes": summary_record["bytes"],
            "full_report_stat_only": {
                "path": str(report_path), "sha256": report_record["sha256"], "bytes": report_record["bytes"],
                "stable_read": True, "stat_before": stat, "stat_after": stat,
            },
        }
        proof_path = root / "proof.json"
        proof_path.write_text(json.dumps(proof) + "\n", encoding="utf-8")
        parsed, _ = _validate_report(report_path, proof_path, "middle")
        if parsed["frame_ids"] != [0] or parsed["native_massfluid_values"] != [1.0]:
            raise AssertionError("compact proof fixture did not parse")


def self_test() -> dict[str, Any]:
    _self_test_compact_schema()
    dummy = {
        "label": "dummy",
        "observations": [
            {"frame": 0, "time_s": 0.0, "native_massfluid_kg": 1.0, "fields": {"weighted_centroid_m": [0.0, 0.0, 0.0], "weighted_velocity_m_per_s": [0.0, 0.0, 0.0], "kinetic_energy_j": 0.0, "fluid_count": 2, "sample_mass_kg": 2.0, "mass_semantics": "native"}},
            {"frame": 1, "time_s": 1.0, "native_massfluid_kg": 1.0, "fields": {"weighted_centroid_m": [1.0, 0.0, 0.0], "weighted_velocity_m_per_s": [1.0, 0.0, 0.0], "kinetic_energy_j": 1.0, "fluid_count": 2, "sample_mass_kg": 2.0, "mass_semantics": "native"}},
        ],
    }
    bracket = _bracket(dummy, 0.5)
    if bracket["status"] != "BRACKETED" or bracket["lower_index"] != 0 or bracket["upper_index"] != 1:
        raise AssertionError("bracket self-test failed")
    if _compare_pair(dummy, dummy, 0.5)["endpoints"][0]["interpolation_performed"] is not False:
        raise AssertionError("comparison self-test interpolated")
    return {
        "status": "PASS",
        "schema": SCHEMA,
        "three_runs": ["coarse", "middle", "fine"],
        "queries_s": list(QUERY_TIMES_S),
        "stable_json_only": True,
        "interpolation": False,
        "truth_credit": False,
        "compact_proof_schema_fixture": True,
        "full_report_read_once_after_guard": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--coarse-report", type=Path)
    parser.add_argument("--coarse-proof", type=Path)
    parser.add_argument("--middle-report", type=Path)
    parser.add_argument("--middle-proof", type=Path)
    parser.add_argument("--fine-report", type=Path)
    parser.add_argument("--fine-proof", type=Path)
    parser.add_argument("--query-times", type=float, nargs="+", default=list(QUERY_TIMES_S))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    required = (args.coarse_report, args.coarse_proof, args.middle_report, args.middle_proof, args.fine_report, args.fine_proof, args.output)
    if any(value is None for value in required):
        parser.error("all three report/proof pairs and --output are required")
    try:
        result = build_report(
            {"coarse": args.coarse_report, "middle": args.middle_report, "fine": args.fine_report},
            {"coarse": args.coarse_proof, "middle": args.middle_proof, "fine": args.fine_proof},
            args.output,
            args.query_times,
        )
    except Exception as exc:
        print(json.dumps({"status": UNKNOWN_STATUS, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": result["status"], "output": str(args.output.expanduser().resolve()), "runs": ["coarse", "middle", "fine"], "interpolation": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
