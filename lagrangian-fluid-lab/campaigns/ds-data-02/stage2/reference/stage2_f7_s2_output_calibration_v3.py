#!/usr/bin/env python3
"""Bounded F7-S2 output and asynchronous-CFL diagnostics.

This forward worker consumes the already completed strict same-CFL 20-frame
join and the completed half-CFL 17-frame native observer.  It reads only the
two JSON reports, their small RunPARTs summaries, and the frozen calibration
contract.  It never opens BI4/VTK/HDF5 data, invokes the native decoder, or
starts a solver.

The same-CFL join is required to carry complete pre/post provenance for all
20 observations.  The half-CFL input intentionally remains a 17-frame
observer: its radius-two output neighbours (302, 602, 902) are absent and
are reported UNKNOWN.  A same-run observable reconstruction is an output
sampling diagnostic.  Equal native-frame same/half differences retain both
saved times and are an asynchronous integration/output diagnostic; neither
diagnostic grants QI/QN/QE or neighboring-grid truth.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import sys
from typing import Any, Iterable

# Keep the additive worker importable both as a script and through the
# repository's small test/import harnesses.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from stage2_f7_s2_output_calibration_v2 import (
    CONTRACT_SCHEMA,
    FAMILY,
    OBSERVER_SCHEMA,
    PHYSICAL_CASE,
    QUERY_TIMES_S,
    REQUEST_SCHEMA,
    SENTINEL,
    TIME_TOLERANCE_S,
    atomic_json,
    bracket,
    contract_scales,
    local_reconstruction,
    manufactured_self_test,
    norm,
    difference,
    observer_fields,
    parse_runparts,
    record,
    regular,
)


JOIN_SCHEMA = "ds02.stage2.f7-s2.same-cfl-20frame-join.v4"
JOIN_STATUS = "PASS_JOINED_20_NATIVE_OBSERVATIONS_NO_INTERPOLATION_V4"
JOIN_INTEGRITY_STATUS = "PASS_COMPLETE_PRE_POST_RECORDS_FOR_ALL_20_FRAMES_V4"
REPORT_SCHEMA = "ds02.stage2.f7-s2.output-calibration-report.v3"
WORKER_SCHEMA = "ds02.stage2.f7-s2.output-calibration.v3"

ROOT = Path(__file__).resolve().parents[5]
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
RUNNER = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
CONTRACT = ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f7_s2_observer_calibration_contract_v3.json"

JOIN_REPORT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/"
    "F7_S2_SAME_CFL_20FRAME_STRICT_JOIN_V4_ROOT_048/"
    "f7-s2-same-cfl-20frame-strict-join-v4-root-048-001-root-forward-030-001/"
    "report/f7_s2_same_cfl_20frame_join_v4.json"
)
JOIN_RECEIPT = JOIN_REPORT.parents[1] / "execution-receipt.json"
HALF_OBSERVER = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/"
    "F7_S2_HALF_CFL_TIME_OUTPUT_OBSERVER_V1/"
    "f7-s2-half_cfl-time-output-observer-v1-root-001-root-forward-029-001/"
    "observer/f7_s2_half_cfl_time_output_observer_v1.json"
)
HALF_RECEIPT = HALF_OBSERVER.parents[1] / "execution-receipt.json"
SAME_RUNPARTS = Path(
    "/var/tmp/ds02-stage2/F7/F7_S2_NVME_COUNTERPART_V5/"
    "f7-s2-a065-same-cfl-dense-savedt-v5-001/solver_output/RunPARTs.csv"
)
HALF_RUNPARTS = Path(
    "/var/tmp/ds02-stage2/F7/F7_S2_HALF_CFL_SAVEDT_V7/"
    "f7-s2-a065-half-cfl-savedt-v7-001-root-forward-001/solver_output/RunPARTs.csv"
)

OUTPUT_DIR = ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f7-s2-output-calibration-v3"
REQUEST_PATH = OUTPUT_DIR / "f7_s2_output_calibration_v3.json"
CASE_ID = "F7_S2_OUTPUT_CALIBRATION_V3_JOIN20_HALF17"
ATTEMPT_ID = "f7-s2-output-calibration-v3-root-001"
OUTPUT_RELATIVE = "{attempt_root}/report/f7_s2_output_calibration_v3.json"


def load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def finite(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} is boolean")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} is not numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} is not finite")
    return number


def vector3(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{label} must be a length-three list")
    return [finite(item, f"{label}[{index}]") for index, item in enumerate(value)]


def stable_records(paths: Iterable[tuple[Path, str]]) -> dict[str, dict[str, Any]]:
    """Record small input files before and after parsing, rejecting mutation."""
    before = {str(path.resolve()): record(path, label) for path, label in paths}
    return before


def require_stable(before: dict[str, dict[str, Any]], paths: Iterable[tuple[Path, str]]) -> dict[str, dict[str, Any]]:
    after = {str(path.resolve()): record(path, label) for path, label in paths}
    for path, first in before.items():
        if after.get(path) != first:
            raise ValueError(f"small input changed during calibration: {path}")
    return after


def validate_integrity(doc: dict[str, Any], expected_frames: list[int], label: str, required_status: str) -> dict[str, Any]:
    integrity = doc.get("source_integrity")
    if not isinstance(integrity, dict):
        raise ValueError(f"{label} has no source_integrity")
    if integrity.get("status") != required_status:
        raise ValueError(f"{label} source_integrity status is not {required_status}")
    expected = set(expected_frames)
    details: dict[str, Any] = {"status": integrity["status"], "record_count": len(expected_frames)}
    for key in ("pre_decode_records", "post_decode_records"):
        records = integrity.get(key)
        if not isinstance(records, list) or len(records) != len(expected_frames):
            raise ValueError(f"{label}.{key} does not contain all expected records")
        frames = []
        for index, item in enumerate(records):
            if not isinstance(item, dict):
                raise ValueError(f"{label}.{key}[{index}] is not an object")
            frame = int(item.get("frame", -1))
            frames.append(frame)
            if frame not in expected or not item.get("path") or not item.get("sha256"):
                raise ValueError(f"{label}.{key}[{index}] has invalid frame or source digest")
            for stat_key in ("stat_before", "stat_after"):
                stat = item.get(stat_key)
                if not isinstance(stat, dict):
                    raise ValueError(f"{label}.{key}[{index}] has no {stat_key}")
                for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
                    if field not in stat:
                        raise ValueError(f"{label}.{key}[{index}] missing {stat_key}.{field}")
        if set(frames) != expected or len(frames) != len(set(frames)):
            raise ValueError(f"{label}.{key} frame set is not exact")
        details[key] = {"frames": frames, "count": len(records)}
    if integrity.get("pre_post_sha_and_stat_equal") not in (True, "PASS_PRE_POST_SHA_AND_STAT_EQUAL", "PASS_PRE_HASH_IDENTICAL"):
        # The v4 join uses per-record stat consistency rather than the observer
        # enforcer's boolean.  Its exact status is checked by each record below.
        if label != "same-CFL joined report":
            raise ValueError(f"{label} does not prove pre/post equality")
    return details


def validate_record_pair_consistency(doc: dict[str, Any], expected_frames: list[int], label: str) -> None:
    integrity = doc["source_integrity"]
    for key in ("pre_decode_records", "post_decode_records"):
        for item in integrity[key]:
            if item.get("stat_consistency") not in (None, "PASS_PRE_HASH_IDENTICAL"):
                raise ValueError(f"{label}.{key} has non-passing stat consistency")
    pre = {int(item["frame"]): item for item in integrity["pre_decode_records"]}
    post = {int(item["frame"]): item for item in integrity["post_decode_records"]}
    for frame in expected_frames:
        if frame not in pre or frame not in post:
            raise ValueError(f"{label} missing integrity frame {frame}")
        if pre[frame].get("sha256") != post[frame].get("sha256"):
            raise ValueError(f"{label} pre/post digest differs at frame {frame}")
        for side in (pre[frame], post[frame]):
            if side.get("stat_before") != side.get("stat_after"):
                raise ValueError(f"{label} pre/post stat boundary differs at frame {frame}")


def validate_join(path: Path, runparts: dict[str, Any]) -> dict[str, Any]:
    join = load_json(path, "same-CFL strict 20-frame join")
    if join.get("schema") != JOIN_SCHEMA or join.get("status") != JOIN_STATUS:
        raise ValueError("same-CFL input is not the completed strict v4 20-frame join")
    identity = join.get("identity", {})
    if identity.get("family_id") != FAMILY or identity.get("sentinel_id") != SENTINEL or identity.get("physical_case_id") != PHYSICAL_CASE:
        raise ValueError("same-CFL join identity is not F7-S2")
    scope = join.get("scope", {})
    expected = [0, 1, 298, 299, 300, 301, 302, 598, 599, 600, 601, 602, 898, 899, 900, 901, 902, 1198, 1199, 1200]
    if scope.get("old_selected_frame_count") != 17 or scope.get("new_selected_frame_count") != 3:
        raise ValueError("same-CFL join segment counts are not 17+3")
    if scope.get("joined_frame_count") != 20 or scope.get("frame_ids") != expected:
        raise ValueError("same-CFL join frame set is not the registered 20-frame set")
    if scope.get("hdf5_read") is not False or scope.get("bi4_read") is not False or scope.get("decoder_launch") is not False:
        raise ValueError("same-CFL join reports a forbidden read or decoder launch")
    if scope.get("particle_field_interpolation") != "NOT_PERFORMED" or scope.get("neighbor_join_only") is not True:
        raise ValueError("same-CFL join is not a no-interpolation neighbour join")
    integrity = validate_integrity(join, expected, "same-CFL joined report", JOIN_INTEGRITY_STATUS)
    validate_record_pair_consistency(join, expected, "same-CFL joined report")
    observations = join.get("observations")
    if not isinstance(observations, list) or len(observations) != 20:
        raise ValueError("same-CFL join does not carry all 20 observations")
    frames: dict[int, dict[str, Any]] = {}
    for index, observation in enumerate(observations):
        if not isinstance(observation, dict):
            raise ValueError(f"same-CFL joined observation {index} is not an object")
        frame = int(observation.get("frame", -1))
        if frame not in expected or frame in frames:
            raise ValueError(f"same-CFL joined observation frame {frame} is invalid")
        timing = observation.get("time", {})
        runparts_time = finite(timing.get("runparts_s"), f"same-CFL joined frame {frame} time")
        if timing.get("status") != "PASS_DECODED_TIME_MATCH" or abs(runparts_time - runparts["times_s"][frame]) > TIME_TOLERANCE_S:
            raise ValueError(f"same-CFL joined frame {frame} does not match RunPARTs")
        if finite(timing.get("absolute_error_s"), f"same-CFL joined frame {frame} time error") > TIME_TOLERANCE_S:
            raise ValueError(f"same-CFL joined frame {frame} has an excessive decode time error")
        if observation.get("finite_fields") != {"position": True, "velocity": True, "density": True}:
            raise ValueError(f"same-CFL joined frame {frame} has incomplete finite fields")
        frames[frame] = {"frame": frame, "time_s": runparts_time, **observer_fields(observation, f"same-CFL joined frame {frame}")}
    if sorted(frames) != expected:
        raise ValueError("same-CFL joined observations do not cover the exact frame set")
    output_scope = join.get("output_sampling_scope", {})
    if output_scope.get("same_run_4x_neighbor_frames") != [302, 602, 902] or output_scope.get("field_interpolation") != "FORBIDDEN":
        raise ValueError("same-CFL join output scope is not the registered 4x diagnostic scope")
    return {"record": record(path, "same-CFL strict join"), "report": join, "frames": frames, "selected_frames": expected, "selected_frame_count": 20, "integrity": integrity}


def validate_half(path: Path, runparts: dict[str, Any]) -> dict[str, Any]:
    half = load_json(path, "half-CFL 17-frame observer")
    if half.get("schema") != OBSERVER_SCHEMA or half.get("status") != "PASS_DECODED_SELECTED_NATIVE_FIELDS":
        raise ValueError("half-CFL input is not the completed native observer v2")
    if half.get("family_id", FAMILY) not in (None, FAMILY) or half.get("sentinel_id", SENTINEL) not in (None, SENTINEL):
        raise ValueError("half-CFL observer identity is not F7-S2")
    scope = half.get("scope", {})
    if scope.get("hdf5_read") is not False or scope.get("typed_conversion") != "NOT_PERFORMED" or scope.get("particle_field_interpolation") != "NOT_PERFORMED":
        raise ValueError("half-CFL observer includes a forbidden conversion or interpolation")
    expected = [0, 1, 298, 299, 300, 301, 598, 599, 600, 601, 898, 899, 900, 901, 1198, 1199, 1200]
    if scope.get("selected_frame_count") != 17:
        raise ValueError("half-CFL observer must remain the actual 17-frame report")
    integrity = validate_integrity(half, expected, "half-CFL observer", "PASS_PRE_POST_EXPECTED_SOURCE_AND_STAT")
    validate_record_pair_consistency(half, expected, "half-CFL observer")
    observations = half.get("observations")
    if not isinstance(observations, list) or len(observations) != 17:
        raise ValueError("half-CFL observer must carry exactly 17 observations")
    frames: dict[int, dict[str, Any]] = {}
    for index, observation in enumerate(observations):
        if not isinstance(observation, dict):
            raise ValueError(f"half-CFL observation {index} is not an object")
        frame = int(observation.get("frame", -1))
        if frame not in expected or frame in frames:
            raise ValueError(f"half-CFL observation frame {frame} is invalid")
        timing = observation.get("time", {})
        runparts_time = finite(timing.get("runparts_s"), f"half-CFL frame {frame} time")
        if timing.get("status") != "PASS_DECODED_TIME_MATCH" or abs(runparts_time - runparts["times_s"][frame]) > TIME_TOLERANCE_S:
            raise ValueError(f"half-CFL frame {frame} does not match RunPARTs")
        if finite(timing.get("absolute_error_s"), f"half-CFL frame {frame} time error") > TIME_TOLERANCE_S:
            raise ValueError(f"half-CFL frame {frame} has an excessive decode time error")
        if observation.get("finite_fields") != {"position": True, "velocity": True, "density": True}:
            raise ValueError(f"half-CFL frame {frame} has incomplete finite fields")
        frames[frame] = {"frame": frame, "time_s": runparts_time, **observer_fields(observation, f"half-CFL frame {frame}")}
    if sorted(frames) != expected:
        raise ValueError("half-CFL observations do not cover the exact 17-frame set")
    return {"record": record(path, "half-CFL observer"), "report": half, "frames": frames, "selected_frames": expected, "selected_frame_count": 17, "integrity": integrity}


def same_half_diagnostic(same: dict[str, Any], half: dict[str, Any], scales: dict[str, Any]) -> dict[str, Any]:
    common = sorted(set(same["frames"]) & set(half["frames"]))
    rows = []
    for frame in common:
        left, right = same["frames"][frame], half["frames"][frame]
        centroid = norm(difference(right["centroid_m"], left["centroid_m"]))
        velocity = norm(difference(right["velocity_m_per_s"], left["velocity_m_per_s"]))
        energy = abs(right["kinetic_energy_j"] - left["kinetic_energy_j"])
        rows.append({
            "frame": frame,
            "same_time_s": left["time_s"],
            "half_time_s": right["time_s"],
            "time_delta_half_minus_same_s": right["time_s"] - left["time_s"],
            "absolute_difference": {"centroid_norm_m": centroid, "velocity_norm_m_per_s": velocity, "kinetic_energy_j": energy},
            "base_task_gate_checks": {
                "centroid_within_2pct_L": centroid <= scales["base_task_gates"]["position_m"],
                "velocity_within_5pct_scale": velocity <= scales["base_task_gates"]["velocity_m_per_s"],
                "kinetic_energy_within_5pct_scale": energy <= scales["base_task_gates"]["kinetic_energy_j"],
            },
            "interpretation": "same_native_frame_diagnostic_with_async_saved_times; not pure integration_error_or_output_error",
        })
    return {
        "status": "PASS_ASYNCHRONOUS_COMMON_FRAME_DIAGNOSTIC" if rows else "UNKNOWN_NO_COMMON_SELECTED_FRAME",
        "common_frame_count": len(common),
        "common_frames": common,
        "max_abs_time_delta_s": max((abs(row["time_delta_half_minus_same_s"]) for row in rows), default=None),
        "rows": rows,
        "scientific_role": "diagnostic only; no neighboring-grid truth and no common-time field interpolation",
    }


def build_report(join_path: Path, half_path: Path, same_runparts_path: Path, half_runparts_path: Path, contract_path: Path, output: Path) -> dict[str, Any]:
    small_inputs = [(join_path, "same-CFL strict join"), (half_path, "half-CFL observer"), (same_runparts_path, "same-CFL RunPARTs"), (half_runparts_path, "half-CFL RunPARTs"), (contract_path, "F7 calibration contract")]
    before = stable_records(small_inputs)
    contract = load_json(contract_path, "F7 calibration contract")
    scales = contract_scales(contract)
    same_run = parse_runparts(same_runparts_path, "same-CFL RunPARTs")
    half_run = parse_runparts(half_runparts_path, "half-CFL RunPARTs")
    same = validate_join(join_path, same_run)
    half = validate_half(half_path, half_run)
    after = require_stable(before, small_inputs)
    same_local = local_reconstruction("same_cfl_join20", same, same_run, scales)
    half_local = local_reconstruction("half_cfl_17", half, half_run, scales)
    report = {
        "schema": REPORT_SCHEMA,
        "status": "COMPLETED_JOIN20_HALF17_OUTPUT_AND_ASYNC_DIAGNOSTICS_NO_QUALIFICATION",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "family_id": FAMILY,
        "sentinel_id": SENTINEL,
        "physical_case_id": PHYSICAL_CASE,
        "input_lineage": {
            "same_cfl": {"schema": JOIN_SCHEMA, "status": JOIN_STATUS, "joined_frame_count": 20, "integrity_status": JOIN_INTEGRITY_STATUS},
            "half_cfl": {"schema": OBSERVER_SCHEMA, "status": "PASS_DECODED_SELECTED_NATIVE_FIELDS", "selected_frame_count": 17, "missing_radius_two_frames_for_4x": [302, 602, 902]},
            "same3_redecode": "NOT_PERFORMED; existing strict join consumed",
        },
        "read_scope": {
            "same_join": same["record"],
            "half_observer": half["record"],
            "same_runparts": same_run["record"],
            "half_runparts": half_run["record"],
            "contract": record(contract_path, "F7 calibration contract"),
            "input_records_pre_parse": before,
            "input_records_post_parse": after,
            "hdf5_read": False,
            "bi4_read": False,
            "native_decoder_invoked": False,
            "typed_conversion": "NOT_PERFORMED",
            "source_scope": "completed observer/join JSON and RunPARTs metadata only; no raw native reread",
        },
        "registered_scales_and_gates": scales,
        "run_metadata": {
            "same_cfl": {"selected_frames": same["selected_frames"], "selected_frame_count": 20, "runparts_last_time_s": same_run["last_time_s"], "query_brackets": [bracket(same_run["times_s"], q) for q in QUERY_TIMES_S]},
            "half_cfl": {"selected_frames": half["selected_frames"], "selected_frame_count": 17, "runparts_last_time_s": half_run["last_time_s"], "query_brackets": [bracket(half_run["times_s"], q) for q in QUERY_TIMES_S]},
        },
        "local_output_reconstruction": {
            "same_cfl_join20": same_local,
            "half_cfl_17": half_local,
            "interpretation": "actual decoded observables reconstructed at same-run saved rows; output sampling and local physical temporal curvature remain entangled",
            "half_4x_missing_frames": [302, 602, 902],
        },
        "same_half_native_frame_diagnostic": same_half_diagnostic(same, half, scales),
        "manufactured_semantic_selftests": manufactured_self_test(),
        "error_separation": {
            "time_alignment": "actual RunPARTs query brackets retained; no common-time field interpolation",
            "output_sampling": "same-run local reconstruction only; same 4x uses joined radius-two rows, half 4x remains UNKNOWN",
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
        if resolved.suffix.lower() in {".bi4", ".h5", ".hdf5", ".vtk"}:
            raise ValueError(f"F7 calibration v3 cannot bind raw native input: {resolved}")
        regular(resolved, "request input")
        if str(resolved) not in seen:
            result.append(resolved)
            seen.add(str(resolved))
    return result


def build_request(join_path: Path, half_path: Path, same_runparts_path: Path, half_runparts_path: Path, contract_path: Path, output_path: Path = REQUEST_PATH) -> dict[str, Any]:
    if output_path.exists():
        raise FileExistsError(f"refuse to overwrite immutable request: {output_path}")
    paths = input_paths([join_path, JOIN_RECEIPT, half_path, HALF_RECEIPT, same_runparts_path, half_runparts_path, contract_path])
    records = {str(path): record(path, "request input") for path in paths}
    command = [str(PYTHON), str(Path(__file__).resolve()), "--run", "--same-join", str(join_path.resolve()), "--half-observer", str(half_path.resolve()), "--same-runparts", str(same_runparts_path.resolve()), "--half-runparts", str(half_runparts_path.resolve()), "--contract", str(contract_path.resolve()), "--output", OUTPUT_RELATIVE]
    request = {
        "schema": REQUEST_SCHEMA,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": FAMILY,
        "sentinel_id": SENTINEL,
        "physical_case_id": PHYSICAL_CASE,
        "case_id": CASE_ID,
        "attempt_id": ATTEMPT_ID,
        "qualification_stage": "stage2_f7_s2_join20_half17_bounded_output_and_async_diagnostic_no_qualification",
        "command": command,
        "cwd": str(ROOT),
        "worktree_root": str(ROOT),
        "input_files": [str(path) for path in paths],
        "input_hashes": {str(path): item["sha256"] for path, item in records.items()},
        "input_records": records,
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 900,
        "estimated_input_read_bytes": sum(item["bytes"] for item in records.values()),
        "estimated_native_read_bytes": 0,
        "estimated_bi4_read_bytes": 0,
        "estimated_hdf5_read_bytes": 0,
        "estimated_storage_bytes": 64 * 1024 * 1024,
        "estimated_peak_memory_bytes": 1024 * 1024 * 1024,
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "hdf5_read": False,
        "bi4_decode": False,
        "deferred_input_files": [],
        "scope": {
            "same_join": "strict completed v4 join, all 20 pre/post records consumed",
            "half_observer": "completed v2 observer, exactly 17 frames consumed",
            "half_4x_missing_frames": [302, 602, 902],
            "same_run_output_sampling": "same-run observable reconstruction; 4x only at selected radius-two rows",
            "half_run_output_sampling": "same-run 2x where selected; 4x UNKNOWN for missing radius-two rows",
            "same_half_pair": "equal native frame IDs with independent saved times; no interpolation",
            "query_times_s": list(QUERY_TIMES_S),
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "source_binding": {
            "sample_mass_is_not_continuum_or_rigid_mass": True,
            "output_share_of_frozen_task_tolerance": 0.25,
            "same_run_reconstruction_is_not_physical_truth": True,
            "same_half_differences_are_not_pure_integration_error": True,
            "no_neighboring_grid_truth": True,
            "event_characteristic_time": "UNKNOWN_FROM_FROZEN_CONTRACT",
            "same3_redecode": "FORBIDDEN; strict 20-frame join already complete",
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
    atomic_json(output_path, request)
    return request


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--build-request", action="store_true")
    parser.add_argument("--same-join", type=Path)
    parser.add_argument("--half-observer", type=Path)
    parser.add_argument("--same-runparts", type=Path)
    parser.add_argument("--half-runparts", type=Path)
    parser.add_argument("--contract", type=Path, default=CONTRACT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if sum([args.self_test, args.run, args.build_request]) != 1:
        parser.error("choose exactly one of --self-test, --run, or --build-request")
    if args.self_test:
        result = manufactured_self_test()
    else:
        required = (args.same_join, args.half_observer, args.same_runparts, args.half_runparts)
        if any(item is None for item in required):
            parser.error("same join, half observer, and both RunPARTs paths are required")
        assert args.same_join and args.half_observer and args.same_runparts and args.half_runparts
        if args.build_request:
            request = build_request(args.same_join, args.half_observer, args.same_runparts, args.half_runparts, args.contract)
            result = {"status": "PASS_REQUEST_BUILT", "path": str(REQUEST_PATH), "sha256": hashlib.sha256(REQUEST_PATH.read_bytes()).hexdigest(), "input_count": len(request["input_files"])}
        else:
            if args.output is None:
                parser.error("--run requires --output")
            result = build_report(args.same_join, args.half_observer, args.same_runparts, args.half_runparts, args.contract, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
