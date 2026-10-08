#!/usr/bin/env python3
"""Stream the completed F2 coarse canary BI4 frames into a bounded ledger.

This forward consumer is deliberately separate from the PartVTKOut-only
native-motive QA.  It reads the already completed ``Part_*.bi4`` frames one at
a time through the repository's pinned ``bi4_dump`` adapter and writes JSON
summaries only; it never creates an HDF5 trajectory product or starts a
solver.  The generated XML typed ranges provide the initial fluid MK/type
axis.  Every active fluid row is checked for finite position, velocity,
density, mass, type, MK and Idp membership.  Missing identities are reported
as open-lifecycle censoring.  They are not labelled as spill, legal flux,
physical destination, or dynamical error.

The native ``TimeStep`` from each decoded BI4 frame is the observation clock.
RunPARTs saved times are a cross-check and bracket source; a requested tmax is
recorded as a declaration only.  Integration-step uncertainty and output
sampling uncertainty are kept as separate fields.  The optional half-CFL and
native-output projection contract is metadata-only and cannot grant QI/QN/QE.
"""
from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import importlib.util
import json
import math
import os
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f2.coarse-active-stream.v2"
MANIFEST_SCHEMA = "ds02.stage2.f2.coarse-active-stream.manifest.v2"
NATIVE_QA_SCHEMA = "ds02.stage2.f2.coarse-canary-native-qa.v1"
NATIVE_QA_STATUS = "COMPLETED_F2_COARSE_CANARY_NATIVE_IDENTITY_MOTIVE_QA"
CASE_KEY = "F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0088_T4_COARSE_CANARY_ROOT_095"
PHYSICAL_CASE_ID = CASE_KEY
FRAME_RE = re.compile(r"^Part_(\d{4})\.bi4$")
TIME_TOLERANCE_S = 1.0e-8
MASS_TOLERANCE_KG = 1.0e-12


class StreamObservationError(ValueError):
    """Raised when the active-fluid source contract is not closed."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stat_record(path: Path, *, digest: str | None = None) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise StreamObservationError(f"missing input: {path}")
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "st_dev": stat.st_dev,
        "st_ino": stat.st_ino,
        "sha256": digest if digest is not None else sha256(path),
    }


def require_file(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise StreamObservationError(f"{label} is not a regular file: {path}")
    if path.suffix.lower() in {".h5", ".hdf5"}:
        raise StreamObservationError(f"{label} points to forbidden HDF5 content: {path}")
    return path


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StreamObservationError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise StreamObservationError(f"{label} is not a JSON object: {path}")
    return value


def bind_ref(ref: dict[str, Any], label: str, *, digest: bool = True) -> tuple[Path, dict[str, Any]]:
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
        raise StreamObservationError(f"{label} lacks a path")
    path = require_file(ref["path"], label)
    actual = stat_record(path, digest=sha256(path) if digest else None)
    expected = ref.get("sha256")
    if expected and expected != "PARENT_GUARD_COMPUTED" and actual["sha256"] != str(expected):
        raise StreamObservationError(f"{label} SHA differs: {path}")
    for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
        if ref.get(field) is not None and actual[field] != int(ref[field]):
            raise StreamObservationError(f"{label} {field} differs: {path}")
    return path, actual


def bind_frame_stat(ref: dict[str, Any], raw_root: Path, label: str) -> Path:
    """Validate a deferred frame without hashing it before the stream pre-pass."""
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
        raise StreamObservationError(f"{label} lacks a path")
    path = require_file(ref["path"], label)
    if path.parent != raw_root:
        raise StreamObservationError(f"{label} is outside the exact raw data root: {path}")
    match = FRAME_RE.fullmatch(path.name)
    if match is None:
        raise StreamObservationError(f"{label} is not a Part_####.bi4 frame: {path}")
    stat = path.stat()
    if ref.get("bytes") is not None and stat.st_size != int(ref["bytes"]):
        raise StreamObservationError(f"{label} byte count differs: {path}")
    for field in ("mtime_ns", "ctime_ns", "st_dev", "st_ino"):
        if ref.get(field) is not None and getattr(stat, field) != int(ref[field]):
            raise StreamObservationError(f"{label} {field} differs: {path}")
    return path


def snapshot(paths: list[Path]) -> list[dict[str, Any]]:
    return [stat_record(path) for path in paths]


def directory_bytes(path: Path) -> int:
    """Return actor-owned scratch bytes without following source symlinks."""
    total = 0
    for child in Path(path).rglob("*"):
        if child.is_file() and not child.is_symlink():
            total += child.stat().st_size
    return total


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists():
        raise StreamObservationError(f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise StreamObservationError(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise StreamObservationError(f"{label} is not finite")
    return result


def case_qualified_rows(case_key: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Require exact ``(case_key, Idp)`` identity keys before enrichment."""
    if not isinstance(case_key, str) or not case_key:
        raise StreamObservationError("case_key is empty")
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise StreamObservationError("native row is not an object")
        row_case = row.get("case_key", case_key)
        if row_case != case_key:
            raise StreamObservationError(f"native row case_key differs: {row_case!r}")
        try:
            idp = int(row["idp"])
        except (KeyError, TypeError, ValueError) as exc:
            raise StreamObservationError("native row Idp is not an integer") from exc
        key = (case_key, idp)
        if key in seen:
            raise StreamObservationError(f"duplicate case-qualified native identity: {key}")
        seen.add(key)
        result.append({**row, "case_key": case_key, "idp": idp})
    return result


def weighted_active_summary(position: Any, velocity: Any, density: Any, mass: Any, mks: Any) -> dict[str, Any]:
    """Compute finite active-fluid summaries without assigning physical fate."""
    import numpy as np

    position = np.asarray(position, dtype=np.float64)
    velocity = np.asarray(velocity, dtype=np.float64)
    density = np.asarray(density, dtype=np.float64)
    mass = np.asarray(mass, dtype=np.float64)
    mks = np.asarray(mks, dtype=np.int64)
    if position.ndim != 2 or position.shape[1] != 3 or velocity.shape != position.shape:
        raise StreamObservationError("active position/velocity shape is invalid")
    if density.ndim != 1 or mass.ndim != 1 or mks.ndim != 1 or len(density) != len(position) or len(mass) != len(position) or len(mks) != len(position):
        raise StreamObservationError("active density/mass/MK shape is invalid")
    if len(position) == 0:
        raise StreamObservationError("frame has no active fluid rows")
    if not np.isfinite(position).all() or not np.isfinite(velocity).all() or not np.isfinite(density).all() or not np.isfinite(mass).all():
        raise StreamObservationError("active fluid position/velocity/density/mass is not finite")
    if np.any(density <= 0.0) or np.any(mass <= 0.0):
        raise StreamObservationError("active fluid density/mass is not positive")
    total_mass = float(mass.sum(dtype=np.float64))
    result: dict[str, Any] = {
        "active_count": int(len(position)),
        "active_mass_kg": total_mass,
        "mass_weighted_excluded_or_active_com_m": [float(x) for x in (position * mass[:, None]).sum(axis=0, dtype=np.float64) / total_mass],
        "mass_weighted_velocity_m_s": [float(x) for x in (velocity * mass[:, None]).sum(axis=0, dtype=np.float64) / total_mass],
        "position_min_m": [float(x) for x in position.min(axis=0)],
        "position_max_m": [float(x) for x in position.max(axis=0)],
        "density_min_kg_m3": float(density.min()),
        "density_max_kg_m3": float(density.max()),
        "finite": True,
        "mk": {},
    }
    for mk in sorted(set(int(value) for value in mks.tolist())):
        selected = mks == mk
        mk_mass = mass[selected]
        mk_total = float(mk_mass.sum(dtype=np.float64))
        result["mk"][str(mk)] = {
            "active_count": int(selected.sum()),
            "active_mass_kg": mk_total,
            "mass_weighted_position_m": [float(x) for x in (position[selected] * mk_mass[:, None]).sum(axis=0, dtype=np.float64) / mk_total],
            "mass_weighted_velocity_m_s": [float(x) for x in (velocity[selected] * mk_mass[:, None]).sum(axis=0, dtype=np.float64) / mk_total],
            "density_min_kg_m3": float(density[selected].min()),
            "density_max_kg_m3": float(density[selected].max()),
        }
    return result


def update_lifecycle(
    lifecycle: dict[int, dict[str, Any]],
    initial_ids: set[int],
    active_ids: set[int],
    frame: int,
    time_s: float,
    previous_missing: set[int],
) -> tuple[set[int], set[int]]:
    missing = initial_ids - active_ids
    for idp in missing:
        row = lifecycle[idp]
        row["missing_frame_count"] += 1
        if row["first_missing_frame"] is None:
            row["first_missing_frame"] = frame
            row["first_missing_time_s"] = time_s
        if idp in previous_missing:
            row["consecutive_missing_frame_count"] += 1
        else:
            # A fresh missing run follows a present observation.  It is not a
            # re-entry; re-entry is counted only when the identity is observed
            # again after this missing run.
            row["consecutive_missing_frame_count"] = 1
    for idp in active_ids:
        row = lifecycle[idp]
        row["last_present_frame"] = frame
        row["last_present_time_s"] = time_s
        row["consecutive_missing_frame_count"] = 0
        if idp in previous_missing:
            row["reappeared_after_missing"] = True
            row["reentry_count"] += 1
    return missing, active_ids


def read_runparts(path: Path) -> dict[str, Any]:
    lines = [line for line in path.read_text(encoding="utf-8")
             .splitlines() if line.strip() and not line.lstrip().startswith("#")]
    reader = csv.DictReader(lines, delimiter=";")
    required = {"Part", "TimeStep [s]", "NpOut", "NpOutPos", "NpOutRho", "NpOutMov"}
    if not reader.fieldnames or not required <= set(reader.fieldnames):
        raise StreamObservationError("RunPARTs lacks native saved-time/counter fields")
    rows: list[dict[str, Any]] = []
    totals = {name: 0 for name in ("NpOut", "NpOutPos", "NpOutRho", "NpOutMov")}
    optional = {"Steps", "DtMin [s]", "DtMax [s]"}
    for raw in reader:
        try:
            part = int(str(raw["Part"]).replace(",", ""))
            time_s = finite(raw["TimeStep [s]"], f"RunPARTs Part {part} time")
            counters = {name: int(str(raw[name]).replace(",", "")) for name in totals}
        except (KeyError, TypeError, ValueError) as exc:
            raise StreamObservationError("RunPARTs row is malformed") from exc
        if part != len(rows) or (rows and time_s <= rows[-1]["time_s"]):
            raise StreamObservationError("RunPARTs Part/time sequence is invalid")
        if any(value < 0 for value in counters.values()) or counters["NpOut"] != sum(counters[name] for name in ("NpOutPos", "NpOutRho", "NpOutMov")):
            raise StreamObservationError(f"RunPARTs motive counters are invalid at Part {part}")
        row: dict[str, Any] = {"part": part, "time_s": time_s, **counters}
        if optional <= set(reader.fieldnames):
            try:
                row["steps"] = int(str(raw["Steps"]).replace(",", ""))
                row["dt_min_s"] = finite(raw["DtMin [s]"], f"RunPARTs Part {part} DtMin")
                row["dt_max_s"] = finite(raw["DtMax [s]"], f"RunPARTs Part {part} DtMax")
            except (KeyError, TypeError, ValueError) as exc:
                raise StreamObservationError(f"RunPARTs integration fields are malformed at Part {part}") from exc
            if row["steps"] < 0 or row["dt_min_s"] < 0 or row["dt_max_s"] < row["dt_min_s"]:
                raise StreamObservationError(f"RunPARTs integration bounds are invalid at Part {part}")
        rows.append(row)
        for name, value in counters.items():
            totals[name] += value
    if not rows:
        raise StreamObservationError("RunPARTs has no records")
    return {"rows": rows, "totals": totals, "integration_fields_present": optional <= set(reader.fieldnames)}


def load_backend(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("ds02_direct_convert_for_f2_stream", path)
    if spec is None or spec.loader is None:
        raise StreamObservationError(f"cannot import direct converter: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _validate_contract(contract: dict[str, Any]) -> dict[str, Any]:
    if contract.get("schema") != "ds02.stage2.f2.coarse-observation-contract.v2":
        raise StreamObservationError("observation contract schema differs")
    frozen = contract.get("frozen_tolerances")
    if not isinstance(frozen, dict) or frozen.get("whole_initial_unknown_mass_fraction_max") != 0.003:
        raise StreamObservationError("whole-initial unknown-mass gate is not frozen at 0.003")
    if frozen.get("mk_region_flux_error_fraction_whole_initial") != 0.03:
        raise StreamObservationError("MK/region/flux diagnostic fraction is not frozen at 0.03")
    if frozen.get("integration_error_allocation_fraction") != 0.25 or frozen.get("output_sampling_error_allocation_fraction") != 0.25:
        raise StreamObservationError("integration/output allocation is not frozen at one quarter")
    if contract.get("native_time_policy") != "BI4 decoder TimeStep is actual observation time; nominal request tmax is metadata only":
        raise StreamObservationError("native actual-time policy differs")
    return contract


def _runtime_closure(manifest: dict[str, Any], backend: Any) -> dict[str, Any]:
    """Record the interpreter/array runtime and fail on an unbounded thread policy."""
    runtime = manifest.get("runtime")
    if not isinstance(runtime, dict):
        raise StreamObservationError("active stream manifest lacks runtime closure")
    expected_python = runtime.get("python_executable")
    if not isinstance(expected_python, str) or Path(sys.executable).resolve() != Path(expected_python).expanduser().resolve():
        raise StreamObservationError("active stream interpreter is not the manifest-bound venv")
    required_threads = runtime.get("required_one_thread_env")
    if not isinstance(required_threads, list) or not required_threads:
        raise StreamObservationError("active stream manifest lacks one-thread environment contract")
    observed_threads = {name: os.environ.get(name) for name in required_threads}
    if any(value != "1" for value in observed_threads.values()):
        raise StreamObservationError(f"active stream thread environment is not one-thread: {observed_threads}")
    numpy_module = getattr(backend, "np", None)
    h5py_module = getattr(backend, "h5py", None)
    if numpy_module is None:
        raise StreamObservationError("direct converter did not expose numpy runtime")
    closure = {
        "python_executable": str(Path(sys.executable).resolve()),
        "python_version": sys.version,
        "numpy_version": getattr(numpy_module, "__version__", None),
        "numpy_module_path": str(Path(getattr(numpy_module, "__file__", "")).resolve()),
        "h5py_version_imported_by_direct_converter": getattr(h5py_module, "__version__", None),
        "thread_environment_required_one": required_threads,
        "thread_environment_observed": observed_threads,
        "cpu_threads": int(runtime.get("cpu_threads", 1)),
        "no_hdf5_open_policy": True,
    }
    if closure["cpu_threads"] != 1:
        raise StreamObservationError("active stream runtime contract is not CPU1")
    for key in ("numpy_version", "h5py_version"):
        expected_version = runtime.get(key)
        observed_version = closure.get(f"{key}_imported_by_direct_converter" if key == "h5py_version" else key)
        if expected_version is not None and observed_version != expected_version:
            raise StreamObservationError(f"active stream {key} differs: {observed_version!r}!={expected_version!r}")
    return closure


def _validate_native_request(request: dict[str, Any], qa_manifest_path: Path) -> None:
    if request.get("case_id") != "STAGE2_F2_COARSE_CANARY_NATIVE_QA_V1" or request.get("family_id") != "F2":
        raise StreamObservationError("native QA request identity differs")
    if request.get("physical_case_id") != CASE_KEY:
        raise StreamObservationError("native QA request physical case differs")
    command = request.get("command")
    if not isinstance(command, list) or "--manifest" not in command:
        raise StreamObservationError("native QA request has no manifest command binding")
    manifest_index = command.index("--manifest")
    if manifest_index + 1 >= len(command):
        raise StreamObservationError("native QA request has no manifest path")
    request_manifest_path = require_file(command[manifest_index + 1], "native QA request manifest")
    if str(request_manifest_path) not in [str(path) for path in request.get("input_files", [])]:
        raise StreamObservationError("native QA request input files omit its manifest")
    # ROOT105's receipt/report preserved the producer manifest under the
    # primary worktree path while the producer command retained the forensic
    # worktree alias.  Permit that alias only when both immutable files have
    # the same complete SHA; a path-only or arbitrary same-case join remains
    # rejected.
    if sha256(request_manifest_path) != sha256(qa_manifest_path):
        raise StreamObservationError("native QA request manifest is not byte-identical to producer manifest")
    for key in ("hdf5_read", "solver_launch", "gencase_launch", "gpu_launch"):
        if request.get(key) is True:
            raise StreamObservationError(f"native QA request enables forbidden {key}")


def _validate_native_report(report: dict[str, Any], qa_manifest_path: Path, qa_manifest: dict[str, Any], qa_request: dict[str, Any]) -> list[dict[str, Any]]:
    if report.get("schema") != NATIVE_QA_SCHEMA or report.get("status") != NATIVE_QA_STATUS:
        raise StreamObservationError("native QA report is not the completed F2 canary product")
    manifest_record = report.get("manifest")
    if not isinstance(manifest_record, dict) or manifest_record.get("path") != str(qa_manifest_path):
        raise StreamObservationError("native QA report does not bind exact producer manifest")
    if manifest_record.get("sha256") != sha256(qa_manifest_path):
        raise StreamObservationError("native QA producer manifest SHA differs")
    if qa_manifest.get("case_id") != CASE_KEY or qa_manifest.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise StreamObservationError("native QA manifest physical identity differs")
    if qa_manifest.get("source_scope", {}).get("old_1078_identity_rows_reused") is not False:
        raise StreamObservationError("native QA report does not explicitly reject old 1078 identity reuse")
    _validate_native_request(qa_request, qa_manifest_path)
    policy = report.get("read_policy", {})
    for key in ("trajectory_h5_opened", "part_frames_opened", "solver_started", "gencase_started", "model_or_cfd_started"):
        if policy.get(key) is not False:
            raise StreamObservationError(f"native QA read policy is not closed for {key}")
    cause = report.get("source_cause", {})
    if any(cause.get(key) not in {"UNKNOWN", "UNKNOWN_NOT_PROVEN", "UNKNOWN; saved record brackets only"} for key in ("physical_fate", "legal_outflow_or_spill", "dynamical_impact")):
        raise StreamObservationError("native QA report widens physical claim boundary")
    rows = report.get("native_identity", {}).get("rows")
    if not isinstance(rows, list) or not rows:
        raise StreamObservationError("native QA report has no native identity rows")
    return case_qualified_rows(CASE_KEY, rows)


def _source_paths(manifest: dict[str, Any]) -> dict[str, Path]:
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict):
        raise StreamObservationError("active stream manifest lacks inputs")
    paths: dict[str, Path] = {}
    for key in ("native_qa_report", "native_qa_manifest", "native_qa_request", "runparts", "generated_xml", "solver_receipt", "solver_request", "direct_converter", "bi4_dump", "timing_contract"):
        if key not in inputs:
            raise StreamObservationError(f"active stream manifest lacks {key}")
        path, _ = bind_ref(inputs[key], key, digest=True)
        paths[key] = path
    return paths


def _validate_frames(manifest: dict[str, Any], raw_root: Path) -> list[Path]:
    refs = manifest.get("frames")
    if not isinstance(refs, list) or not refs:
        raise StreamObservationError("active stream manifest has no deferred frames")
    paths = [bind_frame_stat(ref, raw_root, f"frame[{index}]") for index, ref in enumerate(refs)]
    indexed = []
    for path in paths:
        match = FRAME_RE.fullmatch(path.name)
        assert match is not None
        indexed.append((int(match.group(1)), path))
    if [index for index, _ in indexed] != list(range(len(indexed))):
        raise StreamObservationError("frame inventory is not contiguous from Part_0000.bi4")
    if manifest.get("expected", {}).get("frame_count") != len(paths):
        raise StreamObservationError("frame inventory count differs from manifest")
    return [path for _, path in indexed]


def _requested_endpoint(solver_request: dict[str, Any]) -> dict[str, Any]:
    for key in ("physical_window_s", "time_window_s"):
        value = solver_request.get(key)
        if isinstance(value, list) and len(value) == 2:
            try:
                values = [finite(item, f"solver request {key}") for item in value]
            except StreamObservationError:
                continue
            return {"declared_window_s": values, "source_key": key, "used_as_observation_time": False}
    for key in ("tmax", "time_max_s", "TimeMax"):
        if key in solver_request:
            return {"declared_endpoint_s": finite(solver_request[key], f"solver request {key}"), "source_key": key, "used_as_observation_time": False}
    return {"declared_window_s": None, "source_key": None, "used_as_observation_time": False}


def _integration_output_separation(runparts: dict[str, Any], times: list[float], contract: dict[str, Any], solver_request: dict[str, Any]) -> dict[str, Any]:
    deltas = [b - a for a, b in zip(times, times[1:])]
    timing: dict[str, Any] = {
        "actual_native_time_axis": {
            "source": "BI4 decoder frame metadata TimeStep",
            "first_time_s": times[0],
            "last_time_s": times[-1],
            "frame_count": len(times),
            "strictly_increasing": all(delta > 0 for delta in deltas),
        },
        "saved_output_time_axis": {
            "source": "RunPARTs.csv TimeStep [s]",
            "first_time_s": runparts["rows"][0]["time_s"],
            "last_time_s": runparts["rows"][-1]["time_s"],
            "interval_min_s": min(deltas) if deltas else None,
            "interval_max_s": max(deltas) if deltas else None,
            "interval_mean_s": sum(deltas) / len(deltas) if deltas else None,
        },
        "declared_solver_endpoint": _requested_endpoint(solver_request),
        "integration_error": {
            "status": "OBSERVED_LAST_STEP_BOUND" if runparts["integration_fields_present"] else "UNKNOWN_UNMEASURED",
            "fields": (runparts["rows"][-1].get("steps"), runparts["rows"][-1].get("dt_min_s"), runparts["rows"][-1].get("dt_max_s")) if runparts["integration_fields_present"] else None,
            "meaning": "integration-step bound is kept separate from saved-output sampling and is not a continuous event-time error",
        },
        "output_sampling_error": {
            "status": "SAVED_INTERVAL_OBSERVED_CONTINUOUS_ERROR_UNKNOWN",
            "meaning": "saved-frame intervals describe observation cadence; hidden sub-frame motion/event error is UNKNOWN",
        },
        "frozen_allocation": {
            "integration_error_fraction": contract["frozen_tolerances"]["integration_error_allocation_fraction"],
            "output_sampling_error_fraction": contract["frozen_tolerances"]["output_sampling_error_allocation_fraction"],
            "these_are_preregistration_fields_not_pass_results": True,
        },
    }
    if abs(timing["actual_native_time_axis"]["last_time_s"] - timing["saved_output_time_axis"]["last_time_s"]) > TIME_TOLERANCE_S:
        raise StreamObservationError("BI4 actual final time differs from RunPARTs saved final time")
    return timing


def _validate_solver_binding(paths: dict[str, Path]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Reject a wrong solver/output tree before opening the first BI4 frame."""
    solver_request = read_json(paths["solver_request"], "solver request")
    solver_receipt = read_json(paths["solver_receipt"], "solver receipt")
    if solver_receipt.get("schema") != "ds02.stage2.external-solver-report.v5" or solver_receipt.get("status") != "COMPLETED_DEVELOPMENT_UNKNOWN":
        raise StreamObservationError("solver receipt is not the completed external v5 product")
    if solver_request.get("case_id") != CASE_KEY or solver_request.get("family_id") != "F2":
        raise StreamObservationError("solver request physical identity differs")
    receipt_request = solver_receipt.get("request")
    if not isinstance(receipt_request, dict) or receipt_request.get("path") != str(paths["solver_request"]):
        raise StreamObservationError("solver receipt does not bind the exact solver request")
    if receipt_request.get("sha256") != sha256(paths["solver_request"]):
        raise StreamObservationError("solver receipt request SHA differs")
    command = solver_request.get("command")
    launch = solver_receipt.get("execution", {}).get("launch_argv")
    if not isinstance(command, list) or not isinstance(launch, list) or len(command) < 4 or len(launch) < 4:
        raise StreamObservationError("solver request/receipt command binding is incomplete")
    generated_from_request = Path(str(command[2])).expanduser().resolve().with_suffix(".xml")
    if generated_from_request != paths["generated_xml"]:
        raise StreamObservationError("solver request generated source differs from active XML")
    generated_from_receipt = Path(str(launch[2])).expanduser().resolve().with_suffix(".xml")
    if generated_from_receipt != paths["generated_xml"]:
        raise StreamObservationError("solver receipt generated source differs from active XML")
    output_root = Path(str(launch[3])).expanduser().resolve()
    if output_root != paths["runparts"].parent.resolve():
        raise StreamObservationError("solver receipt output root differs from RunPARTs parent")
    return solver_request, solver_receipt


def _stream(manifest: dict[str, Any], paths: dict[str, Path], frames: list[Path], native_rows: list[dict[str, Any]], output_path: Path) -> dict[str, Any]:
    solver_request, solver_receipt = _validate_solver_binding(paths)
    backend = load_backend(paths["direct_converter"])
    runtime_closure = _runtime_closure(manifest, backend)
    blocks = backend.parse_particle_blocks(paths["generated_xml"])
    expected = manifest.get("expected", {})
    if blocks["np"] != int(expected.get("initial_particles_total", blocks["np"])):
        raise StreamObservationError("generated XML CaseNp differs from active-stream manifest")
    fluid_blocks = [block for block in blocks["blocks"] if block["type"] == 3]
    if sum(block["count"] for block in fluid_blocks) != int(expected.get("initial_fluid_count", -1)):
        raise StreamObservationError("generated XML fluid block count differs")
    expected_fluid_blocks = expected.get("fluid_blocks")
    actual_fluid_blocks = [
        {key: block[key] for key in ("begin", "count", "mkfluid", "mk")}
        for block in fluid_blocks
    ]
    if not isinstance(expected_fluid_blocks, list) or actual_fluid_blocks != expected_fluid_blocks:
        raise StreamObservationError("generated XML typed fluid block layout differs")
    expected_whole_mass = expected.get("whole_initial_fluid_mass_kg")
    import numpy as np

    base_ids = np.arange(blocks["np"], dtype=np.uint32)
    base_type, base_mk = backend._assign_types(base_ids, blocks)
    fluid_mask = base_type == 3
    fluid_ids_array = base_ids[fluid_mask]
    fluid_ids = {int(value) for value in fluid_ids_array.tolist()}
    if not fluid_ids:
        raise StreamObservationError("generated XML has no fluid identity axis")
    lifecycle = {
        int(idp): {
            "case_key": CASE_KEY, "idp": int(idp), "mk": int(base_mk[idp]), "type": int(base_type[idp]),
            "first_missing_frame": None, "first_missing_time_s": None,
            "last_present_frame": None, "last_present_time_s": None,
            "missing_frame_count": 0, "consecutive_missing_frame_count": 0,
            "reappeared_after_missing": False, "reentry_count": 0,
        }
        for idp in fluid_ids
    }
    first_metadata: dict[str, Any] | None = None
    first_massfluid: float | None = None
    previous_time: float | None = None
    previous_missing: set[int] = set()
    frame_summaries: list[dict[str, Any]] = []
    times: list[float] = []
    scratch_limit = int(manifest.get("runtime", {}).get("max_scratch_bytes", 128 * 1024 * 1024))
    if scratch_limit <= 0:
        raise StreamObservationError("active stream scratch limit is not positive")
    scratch_parent = Path(output_path).expanduser().resolve().parent
    scratch_parent.mkdir(parents=True, exist_ok=True)
    scratch_peak_bytes = 0
    scratch_peak_frame: int | None = None
    decoder_input_bytes = 0
    dynamic_contract: dict[str, Any] | None = None
    with tempfile.TemporaryDirectory(prefix=".ds02-f2-coarse-active-stream-", dir=str(scratch_parent)) as scratch:
        for index, path in enumerate(frames):
            decoder_input_bytes += path.stat().st_size
            # Keep each decoder's binary/XML scratch in its own actor-owned
            # directory.  The directory is deleted as soon as this frame has
            # been reduced to JSON scalars, so scratch cannot grow with 401
            # frames and no source path can be removed by cleanup.
            with tempfile.TemporaryDirectory(prefix=f"frame-{index:04d}-", dir=scratch) as frame_scratch:
                frame = backend.decode_frame(path, paths["bi4_dump"], Path(frame_scratch), index)
                current_scratch_bytes = directory_bytes(Path(frame_scratch))
                if current_scratch_bytes > scratch_limit:
                    raise StreamObservationError(
                        f"BI4 decoder scratch exceeds bounded per-frame limit at frame {index}: "
                        f"{current_scratch_bytes}>{scratch_limit}"
                    )
                if current_scratch_bytes > scratch_peak_bytes:
                    scratch_peak_bytes = current_scratch_bytes
                    scratch_peak_frame = index
            time_s = finite(frame.time, f"BI4 frame {index} TimeStep")
            if previous_time is not None and time_s <= previous_time:
                raise StreamObservationError(f"BI4 TimeStep is not increasing at frame {index}")
            previous_time = time_s
            times.append(time_s)
            if first_metadata is None:
                first_metadata = dict(frame.metadata)
                try:
                    if int(first_metadata.get("CaseNp", blocks["np"])) != blocks["np"]:
                        raise StreamObservationError("BI4 CaseNp differs from generated XML")
                    if int(first_metadata.get("CaseNfluid", len(fluid_ids))) != len(fluid_ids):
                        raise StreamObservationError("BI4 CaseNfluid differs from generated XML")
                except (TypeError, ValueError) as exc:
                    raise StreamObservationError("BI4 initial case count metadata is malformed") from exc
                first_massfluid = finite(first_metadata.get("MassFluid"), "BI4 MassFluid")
                if abs(first_massfluid - float(expected.get("massfluid_kg", first_massfluid))) > MASS_TOLERANCE_KG:
                    raise StreamObservationError("BI4 MassFluid differs from source-bound XML/manifest")
                dynamic_contract = backend._reject_dynamic_contract(paths["generated_xml"], first_metadata)
            else:
                backend._check_frame_constants(first_metadata, frame.metadata)
                current_massfluid = finite(frame.metadata.get("MassFluid"), f"BI4 frame {index} MassFluid")
                if abs(current_massfluid - first_massfluid) > MASS_TOLERANCE_KG:
                    raise StreamObservationError(f"BI4 MassFluid changed at frame {index}")
            ids = frame.ids
            if len(ids) == 0 or len(np.unique(ids)) != len(ids):
                raise StreamObservationError(f"BI4 frame {index} has empty or duplicate Idp")
            if ids.dtype != np.dtype("uint32"):
                raise StreamObservationError(f"BI4 frame {index} Idp dtype is not uint32")
            if np.any(ids >= blocks["np"]):
                raise StreamObservationError(f"BI4 frame {index} has Idp outside generated axis")
            if frame.position.shape != (len(ids), 3) or frame.velocity.shape != (len(ids), 3):
                raise StreamObservationError(f"BI4 frame {index} position/velocity array shape differs from Idp")
            if frame.density.shape != (len(ids),):
                raise StreamObservationError(f"BI4 frame {index} density array shape differs from Idp")
            info_time = finite(frame.info.get("TimeStep"), f"BI4 frame {index} decoder TimeStep")
            if abs(info_time - time_s) > TIME_TOLERANCE_S:
                raise StreamObservationError(f"BI4 frame {index} decoder TimeStep differs from frame time")
            types, mks = backend._assign_types(ids, blocks)
            masses = backend._mass_for_types(types, frame.metadata)
            active_fluid = types == 3
            if not np.isfinite(frame.position[active_fluid]).all() or not np.isfinite(frame.velocity[active_fluid]).all() or not np.isfinite(frame.density[active_fluid]).all() or not np.isfinite(masses[active_fluid]).all():
                raise StreamObservationError(f"BI4 frame {index} has non-finite active fluid field")
            if np.any(frame.density[active_fluid] <= 0) or np.any(masses[active_fluid] <= 0):
                raise StreamObservationError(f"BI4 frame {index} has non-positive active fluid density/mass")
            active_ids = {int(value) for value in ids[active_fluid].tolist()}
            missing, _ = update_lifecycle(lifecycle, fluid_ids, active_ids, index, time_s, previous_missing)
            previous_missing = missing
            active_summary = weighted_active_summary(
                frame.position[active_fluid], frame.velocity[active_fluid], frame.density[active_fluid], masses[active_fluid], mks[active_fluid]
            )
            missing_ids = np.asarray(sorted(missing), dtype=np.uint32)
            frame_summaries.append({
                "frame": index,
                "actual_native_time_s": time_s,
                "decoder_fields": {
                    "idp_dtype": str(frame.ids.dtype),
                    "idp_count": int(frame.ids.size),
                    "idp_nbytes": int(frame.ids.nbytes),
                    "position_shape": list(frame.position.shape),
                    "position_dtype": str(frame.position.dtype),
                    "position_nbytes": int(frame.position.nbytes),
                    "velocity_shape": list(frame.velocity.shape),
                    "velocity_dtype": str(frame.velocity.dtype),
                    "velocity_nbytes": int(frame.velocity.nbytes),
                    "density_shape": list(frame.density.shape),
                    "density_dtype": str(frame.density.dtype),
                    "density_nbytes": int(frame.density.nbytes),
                    "time_source": "decoded frame.info.TimeStep",
                },
                "active_fluid": active_summary,
                "missing_fluid_count": int(len(missing)),
                "missing_fluid_mass_kg": float(len(missing) * first_massfluid),
                "missing_fluid_ids_sha256": hashlib.sha256(missing_ids.tobytes()).hexdigest(),
                "finite_active_fields": {"position": True, "velocity": True, "density": True, "mass": True, "idp": True},
                "typed_fields": {
                    "type": {"finite": True, "source": "generated XML Idp ranges", "independently_decoded": False},
                    "mk": {"finite": True, "source": "generated XML Idp ranges", "independently_decoded": False},
                },
            })
            # Release all numpy arrays before the per-frame scratch directory
            # context exits; this keeps resident memory and scratch ownership
            # bounded independently of frame count.
            del frame
            gc.collect()
    if first_massfluid is None or first_metadata is None:
        raise StreamObservationError("BI4 stream produced no initial frame")
    if len(times) != len(frames):
        raise StreamObservationError("BI4 frame/time count differs")
    runparts = read_runparts(paths["runparts"])
    if len(runparts["rows"]) != len(frames):
        raise StreamObservationError("RunPARTs saved rows differ from BI4 frame count")
    for frame_row, run_row in zip(frame_summaries, runparts["rows"]):
        if abs(frame_row["actual_native_time_s"] - run_row["time_s"]) > TIME_TOLERANCE_S:
            raise StreamObservationError(f"BI4 actual time differs from RunPARTs at Part {run_row['part']}")
    if runparts["totals"]["NpOut"] != len(native_rows):
        raise StreamObservationError("RunPARTs cumulative native count differs from native QA report")
    native_by_id = {row["idp"]: row for row in native_rows}
    missing_lifecycle = {idp: row for idp, row in lifecycle.items() if row["first_missing_frame"] is not None}
    for idp, row in native_by_id.items():
        if idp not in lifecycle:
            raise StreamObservationError(f"native QA Idp {idp} is not a fluid identity")
        if idp not in missing_lifecycle:
            raise StreamObservationError(f"native QA Idp {idp} never appears as a BI4 missing fluid identity")
        part = int(row["part_out"])
        if part < 1 or part >= len(runparts["rows"]):
            raise StreamObservationError(f"native QA Idp {idp} PartOut is outside saved timeline")
        if abs(finite(row.get("saved_record_time_s"), f"native Idp {idp} saved time") - runparts["rows"][part]["time_s"]) > TIME_TOLERANCE_S:
            raise StreamObservationError(f"native QA Idp {idp} saved time differs from RunPARTs")
        row["active_stream_first_missing_frame"] = lifecycle[idp]["first_missing_frame"]
        row["active_stream_first_missing_time_s"] = lifecycle[idp]["first_missing_time_s"]
        row["active_stream_reappeared_after_missing"] = lifecycle[idp]["reappeared_after_missing"]
    final_missing = frame_summaries[-1]["missing_fluid_count"]
    initial_mass = float(first_massfluid * len(fluid_ids))
    if expected_whole_mass is None or abs(initial_mass - float(expected_whole_mass)) > MASS_TOLERANCE_KG:
        raise StreamObservationError("whole-initial fluid mass differs from source-bound manifest")
    native_mass = float(first_massfluid * len(native_rows))
    contract = _validate_contract(read_json(paths["timing_contract"], "timing/projection contract"))
    region = {
        "status": "UNKNOWN_NO_FINITE_REGION_CONTRACT",
        "saved_active_position_by_mk": {
            mk: {
                "mass_weighted_position_m": frame_summaries[-1]["active_fluid"]["mk"].get(mk, {}).get("mass_weighted_position_m"),
                "meaning": "mass-weighted active-fluid position diagnostic; no destination/fate assignment",
            }
            for mk in sorted(frame_summaries[-1]["active_fluid"]["mk"])
        },
        "physical_destination": "UNKNOWN",
    }
    timing = _integration_output_separation(runparts, times, contract, solver_request)
    whole_initial_by_mk = {
        str(block["mk"]): float(block["count"] * first_massfluid)
        for block in blocks["blocks"] if block["type"] == 3
    }
    native_by_mk = Counter(str(row.get("mk")) for row in native_rows)
    native_by_motive = Counter(str(row.get("motive")) for row in native_rows)
    return {
        "schema": SCHEMA,
        "status": "COMPLETED_F2_COARSE_ACTIVE_FLUID_STREAM_OBSERVATION",
        "case_key": CASE_KEY,
        "family_id": "F2",
        "physical_case_id": PHYSICAL_CASE_ID,
        "source": {
            "native_qa_report": stat_record(paths["native_qa_report"]),
            "native_qa_manifest": stat_record(paths["native_qa_manifest"]),
            "native_qa_request": stat_record(paths["native_qa_request"]),
            "generated_xml": stat_record(paths["generated_xml"]),
            "solver_receipt": stat_record(paths["solver_receipt"]),
            "solver_request": stat_record(paths["solver_request"]),
            "direct_converter": stat_record(paths["direct_converter"]),
            "bi4_dump": stat_record(paths["bi4_dump"]),
            "timing_contract": stat_record(paths["timing_contract"]),
            "runtime_closure": runtime_closure,
            "typed_fluid_blocks": actual_fluid_blocks,
            "raw_frame_count": len(frames),
            "raw_frame_pre_post_sha_snapshot": "stored in input_stability; every Part_####.bi4 is covered",
        },
        "native_identity_join": {
            "key": "(case_key, Idp)",
            "native_row_count": len(native_rows),
            "motive_counts": dict(sorted(native_by_motive.items())),
            "motive_by_mk": {mk: dict(sorted(Counter(str(row.get("motive")) for row in native_rows if str(row.get("mk")) == mk).items())) for mk in sorted(native_by_mk)},
            "rows": sorted(native_rows, key=lambda row: row["idp"]),
            "physical_fate": "UNKNOWN",
            "legal_outflow_or_spill": "UNKNOWN",
        },
        "active_fluid_stream": {
            "frame_count": len(frames),
            "initial_particles_total": int(blocks["np"]),
            "initial_fluid_count": len(fluid_ids),
            "initial_massfluid_kg": first_massfluid,
            "whole_initial_fluid_mass_kg": initial_mass,
            "whole_initial_fluid_mass_basis": "generated XML fluid blocks × first BI4 MassFluid; denominator is fixed for all censor screens",
            "initial_mk_mass_kg": whole_initial_by_mk,
            "first_metadata": {key: first_metadata.get(key) for key in ("CaseNp", "CaseNfluid", "Piece", "TimeStep", "MassFluid", "MassBound", "Dp")},
            "frame_summaries": frame_summaries,
            "decoder_dynamic_contract": dynamic_contract,
            "decoder_cost": {
                "decoder_input_bytes_total": decoder_input_bytes,
                "scratch_peak_bytes": scratch_peak_bytes,
                "scratch_peak_frame": scratch_peak_frame,
                "scratch_limit_bytes": scratch_limit,
                "scratch_scope": "one actor-owned per-frame directory; deleted after scalar reduction",
            },
            "missing_identity_lifecycle": sorted(missing_lifecycle.values(), key=lambda row: row["idp"]),
            "final_missing_fluid_count": final_missing,
            "finite_active_fields_all_frames": True,
            "type_mk_semantics": "type/MK are derived from source-bound generated XML Idp ranges; the BI4 decoder does not independently encode these labels",
            "lifecycle_semantics": "missing from saved BI4 identity axis is open-lifecycle censoring; reappearance is recorded and hidden continuous events remain UNKNOWN",
        },
        "mass_and_material": {
            "native_excluded_mass_lower_bound_kg": native_mass,
            "native_excluded_mass_fraction_whole_initial": native_mass / initial_mass,
            "native_excluded_count_by_mk": dict(sorted(native_by_mk.items())),
            "unknown_identity_mass_screen": {
                "whole_initial_fraction_max": contract["frozen_tolerances"]["whole_initial_unknown_mass_fraction_max"],
                "observed_native_lower_bound_fraction": native_mass / initial_mass,
                "screen_result_only": (native_mass / initial_mass) <= contract["frozen_tolerances"]["whole_initial_unknown_mass_fraction_max"],
                "physical_fate": "UNKNOWN",
                "meaning": "source-visible native omission lower bound; not a bound on spill, velocity, impulse, coupling, or dynamics",
            },
            "initial_mk_mass_denominators_kg": whole_initial_by_mk,
            "region_diagnostic": region,
        },
        "timing_and_error_separation": timing,
        "half_cfl_and_native_output_projection": {
            "status": "PREREGISTERED_METADATA_DEPENDENCY_ONLY",
            "half_cfl_comparison": contract["half_cfl_comparison"],
            "native_output_projection": contract["native_output_projection"],
            "no_cross_case_or_resolution_credit": True,
        },
        "claim_boundary": {
            "native_numerical_identity_and_motive": "SOURCE_CLOSED_IF_ALL_INPUT_STABILITY_CHECKS_PASS",
            "active_fluid_finite_fields": "SOURCE_CLOSED_OBSERVED_SAVED_FRAMES",
            "physical_destination_or_legal_flux": "UNKNOWN",
            "continuous_event_time": "UNKNOWN beyond saved BI4/RunPARTs brackets",
            "dynamical_impact": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
        },
        # Filled by audit() around the decoder stream.  Taking this snapshot
        # after decoding would make mutation detection meaningless.
        "input_stability": None,
        "read_policy": {
            "part_bi4_frames_opened": True,
            "hdf5_opened": False,
            "native_qa_partout_redecoded": False,
            "generated_bi4_opened": False,
            "solver_started": False,
            "gencase_started": False,
            "model_or_cfd_started": False,
            "old_products_modified": False,
        },
    }


def audit(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    manifest_path = require_file(manifest_path, "active stream manifest")
    manifest = read_json(manifest_path, "active stream manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise StreamObservationError("unsupported active stream manifest schema")
    if manifest.get("case_key") != CASE_KEY or manifest.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise StreamObservationError("active stream case identity differs")
    paths = _source_paths(manifest)
    qa_manifest = read_json(paths["native_qa_manifest"], "native QA manifest")
    qa_report = read_json(paths["native_qa_report"], "native QA report")
    qa_request = read_json(paths["native_qa_request"], "native QA request")
    native_rows = _validate_native_report(qa_report, paths["native_qa_manifest"], qa_manifest, qa_request)
    raw_root_ref = qa_manifest.get("raw_data_root")
    if not isinstance(raw_root_ref, dict) or not isinstance(raw_root_ref.get("path"), str):
        raise StreamObservationError("native QA manifest lacks raw_data_root")
    raw_root = Path(raw_root_ref["path"]).expanduser().resolve()
    qa_xml_ref = qa_manifest.get("inputs", {}).get("generated_xml")
    if not isinstance(qa_xml_ref, dict) or not isinstance(qa_xml_ref.get("path"), str):
        raise StreamObservationError("native QA manifest lacks generated XML binding")
    qa_xml_path = require_file(qa_xml_ref["path"], "native QA generated XML")
    if qa_xml_path != paths["generated_xml"] and sha256(qa_xml_path) != sha256(paths["generated_xml"]):
        raise StreamObservationError("active generated XML is not the producer-bound XML or a byte-identical alias")
    if qa_manifest.get("source_scope", {}).get("raw_data_root") != str(raw_root):
        raise StreamObservationError("native QA raw data root is not canonical")
    frames = _validate_frames(manifest, raw_root)
    # Deferred BI4 frames and all small source files are snapshotted before
    # any decoder opens them.  The post snapshot is taken after the final
    # RunPARTs/native join, so a source mutation cannot be hidden by a report.
    pre_stability = {
        "frames": snapshot(frames),
        "small_inputs": {key: stat_record(path) for key, path in paths.items()},
    }
    result = _stream(manifest, paths, frames, native_rows, output_path)
    post_stability = {
        "frames": snapshot(frames),
        "small_inputs": {key: stat_record(path) for key, path in paths.items()},
    }
    result["input_stability"] = {
        "pre": pre_stability,
        "post": post_stability,
        "all_equal": pre_stability == post_stability,
    }
    result["manifest"] = stat_record(manifest_path)
    if not result["input_stability"]["all_equal"]:
        raise StreamObservationError("active BI4/source inputs changed during stream")
    atomic_json(output_path, result)
    return {"schema": result["schema"], "status": result["status"], "frame_count": result["active_fluid_stream"]["frame_count"], "native_rows": result["native_identity_join"]["native_row_count"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = audit(args.manifest, args.output)
    except Exception as exc:
        print(f"F2 coarse active stream failed: {exc}", file=os.sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
