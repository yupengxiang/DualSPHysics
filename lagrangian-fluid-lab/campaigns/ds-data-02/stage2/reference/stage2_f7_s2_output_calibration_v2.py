#!/usr/bin/env python3
"""Evaluate a bounded F7-S2 native output-sampling diagnostic.

The parent guard supplies same-CFL and half-CFL selected-native observer JSON
files.  This worker consumes those JSON files and the two small RunPARTs
summaries only.  It never opens a BI4/Part/HDF5 file, invokes a decoder, or
starts a solver.

The report keeps three quantities separate:

* ``local_output_reconstruction`` uses decoded fields from one run at
  registered neighbouring saved rows.  It reconstructs the middle saved row
  from the outer rows for a 2x output stride, and for a 4x stride when the
  parent selected the required radius-two rows.  This is an empirical local
  output-sampling diagnostic; it is not a pure output truncation bound or a
  physical-solution error.
* ``same_half_native_frame_diagnostic`` compares equal native frame IDs from
  same and half CFL while retaining each run's own saved time.  It mixes
  asynchronous output timing and integration effects and is never used as
  truth for either run.
* ``query_brackets`` reports the actual RunPARTs brackets for the registered
  physical query times.  No field interpolation at a query time is performed.

The frozen F7 contract is copied into the report and the output share is
registered as one quarter of each task tolerance before any field difference
is evaluated.  QI/QN/QE remain UNKNOWN.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable


SCHEMA = "ds02.stage2.f7-s2.output-calibration.v2"
REPORT_SCHEMA = "ds02.stage2.f7-s2.output-calibration-report.v2"
REQUEST_SCHEMA = "ds02.request.v1"
OBSERVER_SCHEMA = "ds02.stage2.native-physical-observer.v2"
CONTRACT_SCHEMA = "ds02.stage2.f7-s2.observer-calibration-contract.v3"
FAMILY = "F7"
SENTINEL = "F7-S2"
PHYSICAL_CASE = "F7_OBSTACLE_QUINTIC_B08_A065"
QUERY_TIMES_S = (0.0, 3.0, 6.0, 9.0, 12.0)
TIME_TOLERANCE_S = 1.0e-10
OBSERVABLE_KEYS = ("centroid_m", "velocity_m_per_s", "kinetic_energy_j")

REPO = Path(__file__).resolve().parents[5]
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
RUNNER = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
CONTRACT = REPO / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
    "stage2_f7_s2_observer_calibration_contract_v3.json"
)
OUTPUT_DIR = REPO / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
    "stage2-f7-s2-output-calibration-v2"
)
REQUEST_PATH = OUTPUT_DIR / "f7_s2_output_calibration_v2.json"
CASE_ID = "F7_S2_OUTPUT_CALIBRATION_V2"
ATTEMPT_ID = "f7-s2-output-calibration-v2-root-001"
OUTPUT_RELATIVE = "{attempt_root}/report/f7_s2_output_calibration_v2.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be an existing regular non-symlink file: {path}")
    return path


def record(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "sha256": sha256(path),
    }


def load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def atomic_json(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refuse to overwrite immutable artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def finite(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} is boolean")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} is not finite")
    return result


def vector3(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{label} must be a length-three list")
    return [finite(item, f"{label}[{index}]") for index, item in enumerate(value)]


def norm(value: list[float]) -> float:
    return math.sqrt(sum(item * item for item in value))


def difference(left: list[float], right: list[float]) -> list[float]:
    return [left[index] - right[index] for index in range(3)]


def parse_runparts(path: Path, label: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    with regular(path, label).open("r", encoding="utf-8", errors="strict", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for raw in reader:
            if not raw:
                continue
            part_raw = str(raw.get("Part", "")).strip().replace(",", "")
            time_raw = str(raw.get("TimeStep [s]", "")).strip().split("#", 1)[0].strip()
            if not part_raw or not time_raw:
                continue
            try:
                part = int(part_raw)
                time_s = finite(time_raw, f"{label}.time")
            except (TypeError, ValueError):
                # RunPARTs may have a trailing status/comment row.  It is
                # excluded as it cannot identify a native saved frame.
                continue
            rows.append({"frame": part, "time_s": time_s})
    if not rows:
        raise ValueError(f"{label} has no numeric rows")
    if [row["frame"] for row in rows] != list(range(len(rows))):
        raise ValueError(f"{label} frame IDs are not contiguous zero-based rows")
    times = [row["time_s"] for row in rows]
    if abs(times[0]) > TIME_TOLERANCE_S or any(right <= left for left, right in zip(times, times[1:])):
        raise ValueError(f"{label} times are not strictly increasing from zero")
    return {
        "record": record(path, label),
        "rows": rows,
        "times_s": times,
        "row_count": len(rows),
        "last_time_s": times[-1],
    }


def bracket(times: list[float], query: float) -> dict[str, Any]:
    query = finite(query, "query time")
    if query < times[0] - TIME_TOLERANCE_S or query > times[-1] + TIME_TOLERANCE_S:
        return {"query_time_s": query, "status": "OUT_OF_RANGE", "field_interpolation": "FORBIDDEN"}
    for frame, time_s in enumerate(times):
        if abs(time_s - query) <= TIME_TOLERANCE_S:
            return {
                "query_time_s": query,
                "status": "EXACT",
                "lower_frame": frame,
                "upper_frame": frame,
                "lower_time_s": time_s,
                "upper_time_s": time_s,
                "bracket_width_s": 0.0,
                "field_interpolation": "FORBIDDEN",
            }
    upper = next(index for index, time_s in enumerate(times) if time_s > query)
    lower = upper - 1
    return {
        "query_time_s": query,
        "status": "BRACKETED",
        "lower_frame": lower,
        "upper_frame": upper,
        "lower_time_s": times[lower],
        "upper_time_s": times[upper],
        "bracket_width_s": times[upper] - times[lower],
        "field_interpolation": "FORBIDDEN",
    }


def contract_scales(contract: dict[str, Any]) -> dict[str, Any]:
    if contract.get("schema") != CONTRACT_SCHEMA:
        raise ValueError("unexpected F7 observer calibration contract schema")
    source = contract.get("source_geometry", {})
    reference = contract.get("reference_scales", {})
    length = finite(reference.get("L_position_reference_scalar_m", source.get("L_position_reference_scalar_m", 0.0)), "L")
    # The contract stores the registered scalar under source_geometry in the
    # current v3 artifact.  Keep the fallback explicit so a malformed contract
    # cannot silently produce a zero gate.
    if length <= 0.0:
        length = finite(source.get("L_position_reference_scalar_m"), "L")
    velocity = finite(reference.get("velocity_scale_m_per_s"), "velocity scale")
    energy = finite(reference.get("kinetic_energy_scale_j"), "kinetic-energy scale")
    if min(length, velocity, energy) <= 0.0:
        raise ValueError("registered F7 scales must be positive")
    base = {
        "position_m": 0.02 * length,
        "velocity_m_per_s": 0.05 * velocity,
        "kinetic_energy_j": 0.05 * energy,
    }
    output = {key: value * 0.25 for key, value in base.items()}
    return {
        "contract": contract,
        "registered_scales": {
            "position_L_m": length,
            "velocity_m_per_s": velocity,
            "kinetic_energy_j": energy,
        },
        "base_task_gates": base,
        "output_sampling_gate_share": 0.25,
        "output_sampling_gates": output,
        "event_time": {
            "status": contract.get("event_time", {}).get("status", "UNKNOWN"),
            "characteristic_time_s": contract.get("event_time", {}).get("characteristic_time_s"),
        },
    }


def observer_fields(observation: dict[str, Any], label: str) -> dict[str, Any]:
    fluid_group = observation.get("groups", {}).get("fluid")
    if not isinstance(fluid_group, dict):
        raise ValueError(f"{label} has no aggregate fluid group")
    if fluid_group.get("mass_semantics") != "native_particle_sample_mass_only":
        raise ValueError(f"{label} has unexpected sample-mass semantics")
    fields = {
        "centroid_m": vector3(fluid_group.get("weighted_centroid_m"), f"{label}.weighted_centroid_m"),
        "velocity_m_per_s": vector3(fluid_group.get("weighted_velocity_m_per_s"), f"{label}.weighted_velocity_m_per_s"),
        "kinetic_energy_j": finite(fluid_group.get("kinetic_energy_j"), f"{label}.kinetic_energy_j"),
        "sample_mass_kg": finite(fluid_group.get("sample_mass_kg"), f"{label}.sample_mass_kg"),
    }
    if fields["sample_mass_kg"] <= 0.0:
        raise ValueError(f"{label}.sample_mass_kg must be positive")
    return fields


def validate_observer(path: Path, runparts: dict[str, Any], label: str) -> dict[str, Any]:
    observer = load_json(path, label)
    if observer.get("schema") != OBSERVER_SCHEMA:
        raise ValueError(f"{label} has unexpected observer schema")
    if observer.get("status") != "PASS_DECODED_SELECTED_NATIVE_FIELDS":
        raise ValueError(f"{label} is not a successful native observer")
    scope = observer.get("scope", {})
    if scope.get("hdf5_read") is not False or scope.get("typed_conversion") != "NOT_PERFORMED":
        raise ValueError(f"{label} scope includes forbidden HDF5/typed conversion")
    if scope.get("particle_field_interpolation") != "NOT_PERFORMED":
        raise ValueError(f"{label} claims particle interpolation")
    observations = observer.get("observations")
    if not isinstance(observations, list) or not observations:
        raise ValueError(f"{label} has no selected observations")
    frames: dict[int, dict[str, Any]] = {}
    times = runparts["times_s"]
    for index, observation in enumerate(observations):
        if not isinstance(observation, dict):
            raise ValueError(f"{label} observation {index} is not an object")
        frame = int(observation.get("frame", -1))
        if frame < 0 or frame >= len(times) or frame in frames:
            raise ValueError(f"{label} frame {frame} is invalid or duplicated")
        timing = observation.get("time", {})
        runparts_time = finite(timing.get("runparts_s"), f"{label}[{frame}].runparts_s")
        decoded_time = finite(timing.get("decoded_s"), f"{label}[{frame}].decoded_s")
        absolute_error = finite(timing.get("absolute_error_s"), f"{label}[{frame}].absolute_error_s")
        if timing.get("status") != "PASS_DECODED_TIME_MATCH" or abs(runparts_time - times[frame]) > TIME_TOLERANCE_S:
            raise ValueError(f"{label} frame {frame} time does not match RunPARTs")
        if absolute_error > TIME_TOLERANCE_S:
            raise ValueError(f"{label} frame {frame} decoded time is outside the registered tolerance")
        if observation.get("finite_fields") != {"position": True, "velocity": True, "density": True}:
            raise ValueError(f"{label} frame {frame} has incomplete finite-field status")
        fields = observer_fields(observation, f"{label}[{frame}]")
        frames[frame] = {"frame": frame, "time_s": runparts_time, "decoded_time_s": decoded_time, **fields}
    if scope.get("selected_frame_count") not in (None, len(frames)):
        raise ValueError(f"{label} selected frame count does not match observations")
    return {
        "record": record(path, label),
        "observer": observer,
        "frames": frames,
        "selected_frames": sorted(frames),
        "selected_frame_count": len(frames),
        "source": observer.get("source", {}),
    }


def interpolate_scalar(left: float, right: float, fraction: float) -> float:
    return (1.0 - fraction) * left + fraction * right


def interpolate_vector(left: list[float], right: list[float], fraction: float) -> list[float]:
    return [interpolate_scalar(left[index], right[index], fraction) for index in range(3)]


def local_reconstruction(mode: str, data: dict[str, Any], runparts: dict[str, Any], scales: dict[str, Any]) -> dict[str, Any]:
    frames = data["frames"]
    times = runparts["times_s"]
    registered: list[dict[str, Any]] = []
    for query in QUERY_TIMES_S:
        nearest = min(frames, key=lambda frame: abs(frames[frame]["time_s"] - query))
        anchor = frames[nearest]
        item: dict[str, Any] = {
            "query_time_s": query,
            "anchor_frame": nearest,
            "anchor_time_s": anchor["time_s"],
            "query_to_anchor_offset_s": anchor["time_s"] - query,
            "runparts_query_bracket": bracket(times, query),
            "reconstruction": {},
        }
        for factor in (2, 4):
            half_span = factor // 2
            left_frame = nearest - half_span
            right_frame = nearest + half_span
            key = f"{factor}x_output_stride"
            if left_frame not in frames or right_frame not in frames:
                item["reconstruction"][key] = {
                    "status": "UNKNOWN_SELECTED_NEIGHBOR_MISSING",
                    "left_frame": left_frame,
                    "right_frame": right_frame,
                    "required_radius": half_span,
                    "field_interpolation": "NOT_COMPUTED",
                    "scientific_role": "output_sampling_diagnostic_only",
                }
                continue
            left = frames[left_frame]
            right = frames[right_frame]
            span = right["time_s"] - left["time_s"]
            if span <= 0.0:
                raise ValueError(f"{mode} output bracket is not increasing at {nearest}")
            fraction = (anchor["time_s"] - left["time_s"]) / span
            reconstructed_centroid = interpolate_vector(left["centroid_m"], right["centroid_m"], fraction)
            reconstructed_velocity = interpolate_vector(left["velocity_m_per_s"], right["velocity_m_per_s"], fraction)
            reconstructed_ke = interpolate_scalar(left["kinetic_energy_j"], right["kinetic_energy_j"], fraction)
            centroid_error = norm(difference(anchor["centroid_m"], reconstructed_centroid))
            velocity_error = norm(difference(anchor["velocity_m_per_s"], reconstructed_velocity))
            energy_error = abs(anchor["kinetic_energy_j"] - reconstructed_ke)
            gates = scales["output_sampling_gates"]
            item["reconstruction"][key] = {
                "status": "PASS_LOCAL_NATIVE_RECONSTRUCTION",
                "left_frame": left_frame,
                "right_frame": right_frame,
                "left_time_s": left["time_s"],
                "right_time_s": right["time_s"],
                "bracket_width_s": span,
                "fraction": fraction,
                "field_interpolation": "LINEAR_SAME_RUN_OBSERVABLES_ONLY",
                "absolute_error": {
                    "centroid_norm_m": centroid_error,
                    "velocity_norm_m_per_s": velocity_error,
                    "kinetic_energy_j": energy_error,
                },
                "registered_output_gate": gates,
                "gate_checks": {
                    "centroid_within_output_share": centroid_error <= gates["position_m"],
                    "velocity_within_output_share": velocity_error <= gates["velocity_m_per_s"],
                    "kinetic_energy_within_output_share": energy_error <= gates["kinetic_energy_j"],
                },
                "scientific_role": "bounded_same_run_output_sampling_diagnostic; not pure output_error_or_physical_truth",
            }
        registered.append(item)
    available = [
        item for item in registered
        for value in item["reconstruction"].values()
        if value.get("status") == "PASS_LOCAL_NATIVE_RECONSTRUCTION"
    ]
    return {
        "mode": mode,
        "status": "PASS_BOUNDED_LOCAL_OUTPUT_DIAGNOSTIC" if available else "UNKNOWN_NO_SELECTED_LOCAL_BRACKETS",
        "query_count": len(registered),
        "registered_queries": registered,
        "available_reconstruction_count": len(available),
        "scientific_role": "same-run native observables; output and local temporal curvature remain entangled",
    }


def same_half_diagnostic(same: dict[str, Any], half: dict[str, Any], scales: dict[str, Any]) -> dict[str, Any]:
    common = sorted(set(same["frames"]) & set(half["frames"]))
    if not common:
        return {"status": "UNKNOWN_NO_COMMON_SELECTED_FRAME", "rows": []}
    rows: list[dict[str, Any]] = []
    for frame in common:
        left = same["frames"][frame]
        right = half["frames"][frame]
        centroid = norm(difference(right["centroid_m"], left["centroid_m"]))
        velocity = norm(difference(right["velocity_m_per_s"], left["velocity_m_per_s"]))
        energy = abs(right["kinetic_energy_j"] - left["kinetic_energy_j"])
        rows.append({
            "frame": frame,
            "same_time_s": left["time_s"],
            "half_time_s": right["time_s"],
            "time_delta_half_minus_same_s": right["time_s"] - left["time_s"],
            "absolute_difference": {
                "centroid_norm_m": centroid,
                "velocity_norm_m_per_s": velocity,
                "kinetic_energy_j": energy,
            },
            "base_task_gate_checks": {
                "centroid_within_2pct_L": centroid <= scales["base_task_gates"]["position_m"],
                "velocity_within_5pct_scale": velocity <= scales["base_task_gates"]["velocity_m_per_s"],
                "kinetic_energy_within_5pct_scale": energy <= scales["base_task_gates"]["kinetic_energy_j"],
            },
            "interpretation": "same_native_frame_diagnostic_with_async_saved_times; not pure integration_error_or_output_error",
        })
    deltas = [abs(row["time_delta_half_minus_same_s"]) for row in rows]
    return {
        "status": "PASS_ASYNCHRONOUS_COMMON_FRAME_DIAGNOSTIC",
        "common_frame_count": len(common),
        "common_frames": common,
        "max_abs_time_delta_s": max(deltas),
        "rows": rows,
        "scientific_role": "diagnostic only; no neighboring-grid truth and no common-time field interpolation",
    }


def manufactured_self_test() -> dict[str, Any]:
    # A quadratic path has a known nonzero error under linear interpolation;
    # this tests the diagnostic arithmetic without touching a native source.
    def path(t: float) -> tuple[list[float], list[float], float]:
        position = [0.2 + 0.03 * t + 0.004 * t * t, -0.1 + 0.02 * t, 0.4]
        velocity = [0.03 + 0.008 * t, 0.02, 0.0]
        energy = 0.5 * sum(item * item for item in velocity)
        return position, velocity, energy

    left = path(0.0)
    middle = path(0.5)
    right = path(1.0)
    reconstructed = [interpolate_scalar(left[0][i], right[0][i], 0.5) for i in range(3)]
    error = norm(difference(middle[0], reconstructed))
    if not (error > 0.0 and math.isfinite(error)):
        raise AssertionError("manufactured curvature did not produce a finite nonzero error")
    try:
        observer_fields({"groups": {"fluid": {"mass_semantics": "native_particle_sample_mass_only", "weighted_centroid_m": [float("nan"), 0.0, 0.0], "weighted_velocity_m_per_s": [0.0, 0.0, 0.0], "kinetic_energy_j": 0.0, "sample_mass_kg": 1.0}}}, "nan")
    except ValueError:
        nan_rejected = True
    else:
        nan_rejected = False
    if not nan_rejected:
        raise AssertionError("non-finite manufactured field was accepted")
    return {
        "status": "PASS",
        "manufactured_linear_interpolation_curvature_nonzero": True,
        "nonfinite_field_rejected": True,
        "bi4_read": False,
        "hdf5_read": False,
        "solver_launch": False,
    }


def build_report(same_observer: Path, half_observer: Path, same_runparts: Path, half_runparts: Path, contract_path: Path, output: Path) -> dict[str, Any]:
    contract = load_json(contract_path, "F7 calibration contract")
    scales = contract_scales(contract)
    same_run = parse_runparts(same_runparts, "same-CFL RunPARTs")
    half_run = parse_runparts(half_runparts, "half-CFL RunPARTs")
    same = validate_observer(same_observer, same_run, "same-CFL observer")
    half = validate_observer(half_observer, half_run, "half-CFL observer")
    same_local = local_reconstruction("same_cfl", same, same_run, scales)
    half_local = local_reconstruction("half_cfl", half, half_run, scales)
    report = {
        "schema": REPORT_SCHEMA,
        "status": "COMPLETED_BOUNDED_OUTPUT_AND_ASYNC_DIAGNOSTICS_NO_QUALIFICATION",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "family_id": FAMILY,
        "sentinel_id": SENTINEL,
        "physical_case_id": PHYSICAL_CASE,
        "read_scope": {
            "same_observer": same["record"],
            "half_observer": half["record"],
            "same_runparts": same_run["record"],
            "half_runparts": half_run["record"],
            "contract": record(contract_path, "F7 calibration contract"),
            "hdf5_read": False,
            "bi4_read": False,
            "native_decoder_invoked": False,
            "typed_conversion": "NOT_PERFORMED",
            "source_scope": "observer JSON and RunPARTs metadata only; no raw native re-read",
        },
        "registered_scales_and_gates": scales,
        "run_metadata": {
            "same_cfl": {"selected_frames": same["selected_frames"], "selected_frame_count": same["selected_frame_count"], "runparts_last_time_s": same_run["last_time_s"], "query_brackets": [bracket(same_run["times_s"], q) for q in QUERY_TIMES_S]},
            "half_cfl": {"selected_frames": half["selected_frames"], "selected_frame_count": half["selected_frame_count"], "runparts_last_time_s": half_run["last_time_s"], "query_brackets": [bracket(half_run["times_s"], q) for q in QUERY_TIMES_S]},
        },
        "local_output_reconstruction": {
            "same_cfl": same_local,
            "half_cfl": half_local,
            "interpretation": "actual decoded observables reconstructed at same-run saved rows; output sampling and local physical temporal curvature are not separable here",
            "four_x_status": "COMPUTED_ONLY_IF_RADIUS_TWO_NATIVE_ROWS_WERE_SELECTED; otherwise explicit UNKNOWN",
        },
        "same_half_native_frame_diagnostic": same_half_diagnostic(same, half, scales),
        "manufactured_semantic_selftests": manufactured_self_test(),
        "error_separation": {
            "time_alignment": "actual RunPARTs query brackets retained; no common-time field interpolation",
            "output_sampling": "local same-run reconstruction only, with output share gates registered before observations",
            "integration": "same native frame differences include CFL/integration and asynchronous output timing",
            "spatial_grid": "not evaluated by this worker",
            "event_time": "UNKNOWN because the source contract has no characteristic event definition",
            "neighboring_grid_truth": "forbidden",
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    atomic_json(output, report)
    return report


def input_paths(paths: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in [Path(__file__), PYTHON, RUNNER, STRICT, RUNTIME, CONTRACT, *paths]:
        resolved = path.expanduser().resolve()
        if resolved.suffix.lower() in {".bi4", ".h5", ".hdf5"}:
            raise ValueError(f"output calibration worker cannot bind raw BI4/HDF5 input: {resolved}")
        if str(resolved) not in seen:
            regular(resolved, "request input")
            result.append(resolved)
            seen.add(str(resolved))
    return result


def build_request(same_observer: Path, half_observer: Path, same_runparts: Path, half_runparts: Path, contract_path: Path) -> dict[str, Any]:
    if REQUEST_PATH.exists():
        raise FileExistsError(f"refuse to overwrite immutable request: {REQUEST_PATH}")
    paths = input_paths([same_observer, half_observer, same_runparts, half_runparts, contract_path])
    records = {str(path): record(path, "request input") for path in paths}
    command = [str(PYTHON), str(Path(__file__).resolve()), "--run",
               "--same-observer", str(same_observer.resolve()),
               "--half-observer", str(half_observer.resolve()),
               "--same-runparts", str(same_runparts.resolve()),
               "--half-runparts", str(half_runparts.resolve()),
               "--contract", str(contract_path.resolve()),
               "--output", OUTPUT_RELATIVE]
    request = {
        "schema": REQUEST_SCHEMA,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": FAMILY,
        "sentinel_id": SENTINEL,
        "physical_case_id": PHYSICAL_CASE,
        "case_id": CASE_ID,
        "attempt_id": ATTEMPT_ID,
        "qualification_stage": "stage2_f7_s2_bounded_native_output_sampling_and_async_diagnostic_no_qualification",
        "command": command,
        "cwd": str(REPO),
        "worktree_root": str(REPO),
        "input_files": [str(path) for path in paths],
        "input_hashes": {str(path): item["sha256"] for path, item in records.items()},
        "input_records": records,
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 600,
        "estimated_input_read_bytes": sum(item["bytes"] for item in records.values()),
        "estimated_native_read_bytes": 0,
        "estimated_bi4_read_bytes": 0,
        "estimated_hdf5_read_bytes": 0,
        "estimated_storage_bytes": 32 * 1024 * 1024,
        "estimated_peak_memory_bytes": 512 * 1024 * 1024,
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "hdf5_read": False,
        "bi4_decode": False,
        "deferred_input_files": [],
        "scope": {
            "same_run_output_sampling": "same-run local 2x reconstruction; 4x only if selected radius-two rows are present",
            "half_run_output_sampling": "half-run local 2x reconstruction; 4x only if selected radius-two rows are present",
            "same_half_pair": "equal native frame IDs with independent saved times; no interpolation",
            "query_times_s": list(QUERY_TIMES_S),
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "source_binding": {
            "observer_fields": "weighted fluid centroid/velocity and native sample kinetic energy from completed enforcer output",
            "sample_mass_is_not_continuum_or_rigid_mass": True,
            "output_share_of_frozen_task_tolerance": 0.25,
            "same_run_reconstruction_is_not_physical_truth": True,
            "no_neighboring_grid_truth": True,
            "event_characteristic_time": "UNKNOWN_FROM_FROZEN_CONTRACT",
        },
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(RUNNER),
            "strict_guard": str(STRICT),
            "runtime": str(RUNTIME),
            "cpu_parent_binding": "required",
            "gpu": "none",
            "solver_launch": "forbidden",
            "bi4_read": "forbidden",
            "hdf5_read": "forbidden",
            "parent_v8_review_required": True,
        },
        "output": {"atomic": True, "refuse_overwrite": True, "path": OUTPUT_RELATIVE},
        "output_root": str(DATA_ROOT / "families/F7" / CASE_ID / ATTEMPT_ID),
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    atomic_json(REQUEST_PATH, request)
    return request


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--build-request", action="store_true")
    parser.add_argument("--same-observer", type=Path)
    parser.add_argument("--half-observer", type=Path)
    parser.add_argument("--same-runparts", type=Path)
    parser.add_argument("--half-runparts", type=Path)
    parser.add_argument("--contract", type=Path, default=CONTRACT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    selected = [args.self_test, args.run, args.build_request]
    if sum(selected) != 1:
        parser.error("choose exactly one of --self-test, --run, or --build-request")
    if args.self_test:
        result = manufactured_self_test()
    else:
        required = (args.same_observer, args.half_observer, args.same_runparts, args.half_runparts)
        if any(item is None for item in required):
            parser.error("the same/half observer and RunPARTs paths are required")
        assert args.same_observer and args.half_observer and args.same_runparts and args.half_runparts
        if args.build_request:
            request = build_request(args.same_observer, args.half_observer, args.same_runparts, args.half_runparts, args.contract)
            result = {"status": "PASS_REQUEST_BUILT", "path": str(REQUEST_PATH), "sha256": sha256(REQUEST_PATH), "input_count": len(request["input_files"])}
        else:
            if args.output is None:
                parser.error("--run requires --output")
            result = build_report(args.same_observer, args.half_observer, args.same_runparts, args.half_runparts, args.contract, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
