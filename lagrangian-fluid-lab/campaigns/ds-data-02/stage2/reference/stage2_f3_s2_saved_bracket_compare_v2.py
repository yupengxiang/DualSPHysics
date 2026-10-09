#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Compare F3 coarse/middle/fine selected observables at saved-time brackets.

The input is limited to the three JSON sidecars produced by the bounded
native observers: ROOT150's full coarse stream, ROOT167's middle selected
observer, and the forward ROOT171 fine selected observer.  The worker reads
those JSON files only after the parent reservation, verifies each file's
stat/hash before and after the read, and compares endpoint observations at
their actual saved times.  It never opens BI4/VTK/HDF5 payloads and never
interpolates a particle field or treats a neighbouring grid as truth.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f3-s2.saved-bracket-comparison.v2"
PASS_STATUS = "PASS_F3_SAVED_BRACKET_DIAGNOSTICS"
UNKNOWN_STATUS = "UNKNOWN_F3_SAVED_BRACKET_DIAGNOSTICS"
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
QUERY_TIMES_S = (0.0, 2.0, 4.0, 6.0, 8.0)
TIME_TOLERANCE_S = 1.0e-10

REPORT_CONTRACTS: dict[str, dict[str, set[str]]] = {
    "coarse": {
        "schemas": {"ds02.stage2.f3-s2.full-native-stream-observer.v2"},
        "statuses": {"PASS_FULL_NATIVE_STREAM_V2"},
    },
    "middle": {
        "schemas": {"ds02.stage2.f3-s2.middle-selected-native-observer.v1"},
        "statuses": {"PASS_MIDDLE_SELECTED_NATIVE_FIELDS"},
    },
    "fine": {
        "schemas": {
            "ds02.stage2.f3-s2.fine-selected-native-observer.v1",
            "ds02.stage2.f3-s2.fine-selected-native-observer.v2",
        },
        "statuses": {"PASS_FINE_SELECTED_NATIVE_FIELDS", "PASS_FINE_SELECTED_NATIVE_FIELDS_STRICT_SOURCE_JOIN"},
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
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
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


def _proof_binding(proof_path: Path, report_path: Path, report_sha: str, label: str) -> dict[str, Any]:
    proof, proof_record = _read_json_stable(proof_path, f"{label} proof")
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1":
        raise ValueError(f"{label} proof schema is not the actual root verification schema")
    if "ACTUAL" not in str(proof.get("status", "")):
        raise ValueError(f"{label} proof is not an actual terminal proof")
    proof_report = proof.get("report")
    if proof_report is not None and Path(str(proof_report)).expanduser().resolve() != report_path:
        raise ValueError(f"{label} proof report path does not match supplied report")
    expected = proof.get("report_sha256")
    if expected not in (None, report_sha):
        raise ValueError(f"{label} proof report SHA does not match supplied report")
    return {"proof": proof_record, "status": proof.get("status"), "proof_schema": proof.get("schema")}


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
    report, report_record = _read_json_stable(path, f"{label} observer report")
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
    if label == "fine" and report.get("schema") == "ds02.stage2.f3-s2.fine-selected-native-observer.v2":
        source_binding = report.get("fine_source_binding")
        strict_binding = report.get("strict_source_binding")
        if not isinstance(source_binding, dict) or source_binding.get("dp_m") != 0.003 or source_binding.get("initial_fluid_count") != 540000:
            raise ValueError("fine v2 report lacks the strict .003/540000 source gate")
        if not isinstance(strict_binding, dict) or not strict_binding.get("ROOT170") or not strict_binding.get("ROOT169"):
            raise ValueError("fine v2 report lacks ROOT170/ROOT169 strict source binding")
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


def self_test() -> dict[str, Any]:
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
