#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Compare the four guarded F4 missing-field reports at their saved times.

This consumer reads only the small JSON reports produced by the guarded
selected-frame workers and their legacy nine-frame JSON observers.  It never
opens a BI4/VTK/HDF5 payload and never interpolates a field.  Differences are
therefore labelled asynchronous saved-time diagnostics; they are not an
integration/output error estimate, a spatial truth reference, or a QN/QE
qualification.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f4-s1.saved-output-empirical-comparison.v1"
REPORT_SCHEMA = "ds02.stage2.f4-s1.missing-native-observer.v1"
OLD_OBSERVER_SCHEMA = "ds02.stage2.f4-physical-observer.v1"
EXPECTED_LABELS = {"coarse_same_cfl", "dp0_half_cfl", "dp0_same_cfl", "fine_same_cfl"}
PAIR_AXES = {
    ("coarse_same_cfl", "dp0_same_cfl"): ["spatial_resolution", "asynchronous_saved_time"],
    ("dp0_half_cfl", "dp0_same_cfl"): ["CFL_or_integrator_setting", "asynchronous_saved_time"],
    ("fine_same_cfl", "dp0_same_cfl"): ["spatial_resolution", "asynchronous_saved_time"],
    ("coarse_same_cfl", "fine_same_cfl"): ["spatial_resolution", "asynchronous_saved_time"],
    ("dp0_half_cfl", "fine_same_cfl"): ["CFL_or_integrator_setting", "spatial_resolution", "asynchronous_saved_time"],
}


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    return path


def stat_tuple(path: Path) -> tuple[int, int, int, int, int, int]:
    st = path.stat()
    return (int(st.st_size), int(st.st_mtime_ns), int(st.st_ctime_ns), int(st.st_dev), int(st.st_ino), int(st.st_mode))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json_stable(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = regular(path, label)
    before = stat_tuple(path)
    data = path.read_bytes()
    after = stat_tuple(path)
    if before != after:
        raise RuntimeError(f"{label} changed while being read: {path}")
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value, {
        "path": str(path),
        "bytes": len(data),
        "sha256": sha256_bytes(data),
        "stat_before": {"size": before[0], "mtime_ns": before[1], "ctime_ns": before[2], "st_dev": before[3], "st_ino": before[4], "mode": before[5]},
        "stat_after": {"size": after[0], "mtime_ns": after[1], "ctime_ns": after[2], "st_dev": after[3], "st_ino": after[4], "mode": after[5]},
    }


def finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{label} is not finite numeric data")
    return float(value)


def finite_vector(value: Any, label: str, length: int = 3) -> list[float]:
    if not isinstance(value, list) or len(value) != length:
        raise ValueError(f"{label} must be a {length}-vector")
    return [finite_number(item, f"{label}[{index}]") for index, item in enumerate(value)]


def parse_binding(item: str, label: str) -> tuple[str, Path]:
    if "=" not in item:
        raise ValueError(f"{label} must be LABEL=PATH")
    name, raw_path = item.split("=", 1)
    name = name.strip()
    if not name or not raw_path.strip():
        raise ValueError(f"{label} must have nonempty LABEL and PATH")
    return name, Path(raw_path)


def report_field(obs: dict[str, Any], label: str) -> dict[str, Any]:
    time = obs.get("time") if isinstance(obs.get("time"), dict) else {}
    fluid = obs.get("fluid_observables") if isinstance(obs.get("fluid_observables"), dict) else {}
    native = obs.get("native_header") if isinstance(obs.get("native_header"), dict) else {}
    mass_obj = native.get("MassFluid") if isinstance(native.get("MassFluid"), dict) else {}
    return {
        "frame": int(obs["frame"]),
        "time_s": finite_number(time.get("decoded_s"), f"{label} frame time"),
        "runparts_time_s": finite_number(time.get("runparts_s"), f"{label} RunPARTs time"),
        "massfluid_kg": finite_number(mass_obj.get("value"), f"{label} frame MassFluid"),
        "fluid_count": int(fluid["fluid_count"]),
        "weighted_centroid_m": finite_vector(fluid["weighted_centroid_m"], f"{label} centroid"),
        "weighted_velocity_m_per_s": finite_vector(fluid["weighted_velocity_m_per_s"], f"{label} velocity"),
        "kinetic_energy_j": finite_number(fluid["kinetic_energy_j"], f"{label} KE"),
        "field_digest_sha256": str(obs.get("field_digest_sha256", "")),
    }


def validate_old_observer(path: Path, expected_frames: set[int], label: str) -> dict[str, Any]:
    observer, file_record = read_json_stable(path, label)
    if observer.get("schema") != OLD_OBSERVER_SCHEMA:
        raise ValueError(f"{label} is not the legacy nine-frame observer schema")
    observations = observer.get("observations")
    if not isinstance(observations, list) or not observations:
        raise ValueError(f"{label} has no legacy observations")
    old_frames = {int(item["frame"]) for item in observations if isinstance(item, dict) and "frame" in item}
    if len(old_frames) != len(observations):
        raise ValueError(f"{label} has duplicate/malformed legacy frame IDs")
    overlap = sorted(old_frames & expected_frames)
    if overlap:
        raise ValueError(f"{label} overlaps missing-frame set: {overlap}")
    return {
        "path": file_record["path"],
        "sha256": file_record["sha256"],
        "bytes": file_record["bytes"],
        "schema": observer["schema"],
        "frame_ids": sorted(old_frames),
        "frame_count": len(old_frames),
        "mass_semantics": observer.get("mass_semantics", "UNKNOWN_LEGACY_MASS_SEMANTICS"),
        "used_in_field_comparison": False,
        "semantic_boundary": "legacy XML/typed-range weighted observer retained as provenance only; never combined with native MassFluid fields",
    }


def validate_run(label: str, proof_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    proof, proof_file = read_json_stable(proof_path, f"{label} verification proof")
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1":
        raise ValueError(f"{label} proof schema mismatch")
    if not str(proof.get("status", "")).startswith("VERIFIED_ACTUAL_F4_24_"):
        raise ValueError(f"{label} proof is not a verified F4 24-frame report")
    if proof.get("run_label") != label or int(proof.get("selected_frame_count", -1)) != 24:
        raise ValueError(f"{label} proof run label/frame count mismatch")
    if proof.get("H5_BI4_read_by_root") is not False or proof.get("root_array_content_read") is not False:
        raise ValueError(f"{label} proof scope is wider than the selected JSON field audit")
    report_path = regular(Path(str(proof.get("report", ""))), f"{label} native report")
    report, report_file = read_json_stable(report_path, f"{label} native report")
    if report_file["sha256"] != str(proof.get("report_sha256")):
        raise ValueError(f"{label} report SHA does not match its actual proof")
    if report.get("schema") != REPORT_SCHEMA or report.get("status") != "PASS_MISSING_SELECTED_NATIVE_FIELDS":
        raise ValueError(f"{label} report status/schema mismatch")
    if report.get("family_id") != "F4" or report.get("sentinel_id") != "F4-S1":
        raise ValueError(f"{label} report physical family mismatch")
    if report.get("run_label") != label:
        raise ValueError(f"{label} report label mismatch")
    scope = report.get("scope") if isinstance(report.get("scope"), dict) else {}
    if scope.get("particle_field_interpolation") != "NOT_PERFORMED" or scope.get("typed_conversion") != "NOT_PERFORMED":
        raise ValueError(f"{label} report has an unexpected interpolation/conversion scope")
    native_summary = report.get("native_header_summary") if isinstance(report.get("native_header_summary"), dict) else {}
    if native_summary.get("mass_source") != "official BI4 decoder metadata, never XML fallback":
        raise ValueError(f"{label} does not bind native MassFluid metadata")
    if native_summary.get("massfluid_exact_across_selected_frames") is not True:
        raise ValueError(f"{label} native MassFluid is not stable across selected frames")
    observations = report.get("observations")
    if not isinstance(observations, list) or len(observations) != 24:
        raise ValueError(f"{label} report does not contain exactly 24 observations")
    fields = [report_field(obs, label) for obs in observations]
    frame_ids = {item["frame"] for item in fields}
    proof_frames = {int(item) for item in proof.get("selected_native_frame_ids", [])}
    if frame_ids != proof_frames or len(frame_ids) != 24:
        raise ValueError(f"{label} report/proof frame IDs differ")
    expected_mass = finite_number(native_summary.get("massfluid_kg"), f"{label} summary MassFluid")
    if any(item["massfluid_kg"] != expected_mass for item in fields):
        raise ValueError(f"{label} per-frame native MassFluid differs from summary")
    existing = report.get("source", {}).get("existing_observer") if isinstance(report.get("source"), dict) else None
    if not isinstance(existing, dict) or not existing.get("path"):
        raise ValueError(f"{label} report has no legacy observer provenance")
    old = validate_old_observer(Path(str(existing["path"])), frame_ids, f"{label} legacy observer")
    run = {
        "label": label,
        "physical_case_id": report.get("physical_case_id"),
        "report": report_file,
        "proof": proof_file,
        "report_sha256": report_file["sha256"],
        "proof_sha256": proof_file["sha256"],
        "frame_ids": sorted(frame_ids),
        "frame_count": len(fields),
        "native_massfluid_kg": expected_mass,
        "native_massfluid_semantics": native_summary.get("mass_semantics"),
        "observations": {str(item["frame"]): item for item in fields},
        "legacy_observer": old,
        "last_saved_time_s": finite_number(report.get("time_window", {}).get("last_saved_time_s"), f"{label} final time"),
    }
    return run, report, old


def subtract(a: list[float], b: list[float]) -> list[float]:
    return [x - y for x, y in zip(a, b)]


def norm(vector: list[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))


def compare_pair(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    common = sorted(set(left["frame_ids"]) & set(right["frame_ids"]))
    records: list[dict[str, Any]] = []
    max_abs = {"time_delta_s": 0.0, "centroid_delta_m_norm": 0.0, "velocity_delta_m_per_s_norm": 0.0, "kinetic_energy_delta_j": 0.0}
    for frame in common:
        a = left["observations"][str(frame)]
        b = right["observations"][str(frame)]
        dt = b["time_s"] - a["time_s"]
        dc = subtract(b["weighted_centroid_m"], a["weighted_centroid_m"])
        dv = subtract(b["weighted_velocity_m_per_s"], a["weighted_velocity_m_per_s"])
        dke = b["kinetic_energy_j"] - a["kinetic_energy_j"]
        entry = {
            "frame_id": frame,
            "left_time_s": a["time_s"],
            "right_time_s": b["time_s"],
            "delta_t_s_right_minus_left": dt,
            "time_alignment": "EXACT_SAVED_TIME" if dt == 0.0 else "ASYNCHRONOUS_SAVED_TIME",
            "fields": {
                "weighted_centroid_delta_m_right_minus_left": dc,
                "weighted_velocity_delta_m_per_s_right_minus_left": dv,
                "kinetic_energy_delta_j_right_minus_left": dke,
            },
            "interpolation_performed": False,
            "error_bound": "UNKNOWN_NOT_ESTIMATED",
            "truth_credit": False,
        }
        records.append(entry)
        max_abs["time_delta_s"] = max(max_abs["time_delta_s"], abs(dt))
        max_abs["centroid_delta_m_norm"] = max(max_abs["centroid_delta_m_norm"], norm(dc))
        max_abs["velocity_delta_m_per_s_norm"] = max(max_abs["velocity_delta_m_per_s_norm"], norm(dv))
        max_abs["kinetic_energy_delta_j"] = max(max_abs["kinetic_energy_delta_j"], abs(dke))
    axes = PAIR_AXES.get((left["label"], right["label"]), ["cross_run_async_saved_time_diagnostic"])
    return {
        "left_run": left["label"],
        "right_run": right["label"],
        "comparison_axes": axes,
        "common_frame_count": len(common),
        "records": records,
        "max_absolute_observed_differences": max_abs,
        "interpretation": "descriptive differences at each run's actual saved times; not interpolated and not an integration/output error bound",
        "scientific_truth_credit": False,
    }


def build_report(proofs: list[str], output: Path) -> dict[str, Any]:
    bindings = [parse_binding(item, "--proof") for item in proofs]
    labels = [label for label, _ in bindings]
    if set(labels) != EXPECTED_LABELS or len(labels) != len(EXPECTED_LABELS):
        raise ValueError(f"proof labels must be exactly {sorted(EXPECTED_LABELS)}")
    runs: list[dict[str, Any]] = []
    raw_reports: dict[str, dict[str, Any]] = {}
    old_observers: dict[str, dict[str, Any]] = {}
    for label, path in bindings:
        run, report, old = validate_run(label, path)
        runs.append(run)
        raw_reports[label] = report
        old_observers[label] = old
    physical_ids = {run["physical_case_id"] for run in runs}
    if len(physical_ids) != 1:
        raise ValueError("F4 reports do not share one physical case identity")
    pair_results = [compare_pair(left, right) for left, right in itertools.combinations(sorted(runs, key=lambda item: item["label"]), 2)]
    return {
        "schema": SCHEMA,
        "status": "PASS_REPORT_ONLY_ASYNCHRONOUS_SAVED_TIME_DIAGNOSTICS",
        "family_id": "F4",
        "sentinel_id": "F4-S1",
        "physical_case_id": next(iter(physical_ids)),
        "scope": {
            "input_reports": 4,
            "selected_frames_per_report": 24,
            "native_payloads_read_by_consumer": False,
            "hdf5_read": False,
            "typed_conversion": "NOT_PERFORMED",
            "particle_field_interpolation": "NOT_PERFORMED",
            "time_interpolation": "NOT_PERFORMED",
            "old9_observers_redecoded": False,
            "old9_observer_values_merged": False,
            "native_massfluid_semantics_preserved_per_run": True,
            "observed_differences_are_not_error_bounds": True,
        },
        "runs": [
            {key: value for key, value in run.items() if key != "observations"}
            | {"observation_frame_ids": run["frame_ids"]}
            for run in sorted(runs, key=lambda item: item["label"])
        ],
        "native_massfluid_by_run_kg": {run["label"]: run["native_massfluid_kg"] for run in runs},
        "legacy_old9_semantic_boundary": {
            "observers": old_observers,
            "used_for_comparison": False,
            "reason": "old nine-frame observers use the legacy XML/typed-range weighted field contract; their mass/KE values are not mixed with the new native-header MassFluid reports",
        },
        "pairwise_saved_time_diagnostics": pair_results,
        "qualification": {
            "QI": "PASS_LIMITED_REPORT_COMPARISON_ONLY",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "reason": "selected native fields and actual timestamps were validated in source reports; no interpolation, integration/output error calibration, spatial truth, or characteristic-event anchor was established",
        },
    }


def write_once(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable comparison output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def self_test() -> dict[str, Any]:
    if SCHEMA != "ds02.stage2.f4-s1.saved-output-empirical-comparison.v1":
        raise AssertionError("comparison schema changed")
    # This test only exercises the explicit no-interpolation contract.  Actual
    # reports are consumed through the guarded parent request.
    result = compare_pair(
        {"label": "dp0_same_cfl", "frame_ids": [1], "observations": {"1": {"time_s": 1.0, "weighted_centroid_m": [0.0, 0.0, 0.0], "weighted_velocity_m_per_s": [0.0, 0.0, 0.0], "kinetic_energy_j": 1.0}}},
        {"label": "dp0_half_cfl", "frame_ids": [1], "observations": {"1": {"time_s": 1.25, "weighted_centroid_m": [1.0, 2.0, 3.0], "weighted_velocity_m_per_s": [0.5, 0.0, -0.5], "kinetic_energy_j": 2.0}}},
    )
    if result["records"][0]["time_alignment"] != "ASYNCHRONOUS_SAVED_TIME" or result["records"][0]["interpolation_performed"]:
        raise AssertionError("asynchronous comparison contract failed")
    return {"status": "PASS", "schema": SCHEMA, "native_payload_read": False, "interpolation": False, "truth_credit": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--compare", action="store_true")
    parser.add_argument("--proof", action="append", default=[], help="LABEL=path to one guarded F4 verification proof; repeat four times")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    if args.output is None or len(args.proof) != 4:
        parser.error("--compare requires four --proof LABEL=PATH arguments and --output")
    try:
        result = build_report(args.proof, args.output)
        write_once(args.output, result)
    except BaseException as exc:
        print(json.dumps({"status": "FAILED_F4_SAVED_OUTPUT_EMPIRICAL_COMPARISON", "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=False), flush=True)
        return 1
    print(json.dumps({"status": result["status"], "output": str(args.output.expanduser().resolve()), "native_payload_read": False, "interpolation": False}, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
