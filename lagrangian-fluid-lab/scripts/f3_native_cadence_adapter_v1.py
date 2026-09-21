#!/usr/bin/env python3
"""Bounded F3 native-cadence adapter and canary runner.

This adapter is a provenance and execution boundary around the frozen native
volume MLS runners.  It binds an actual solver-saved ``.002 s`` source, can
materialise a direct every-fifth native-frame view for the diagnostic ``.01 s``
comparison, and refuses to run when the source is not actually at the native
cadence.  The every-fifth view is explicitly a selected view of the dense
source; it is never described as an independently solved ``.01 s`` source.

The default execution is a four-interval canary.  A full event window, unknown
fraction, or CDF result is never inferred from that canary.  The existing
unknown/CDF/event thresholds are recorded as immutable gate metadata and are
not evaluated or relaxed here.  The adapter only writes its own preflight,
selection, and receipt files; it does not touch a registry, ledger, CFD
solver, or GPU.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Any

import h5py
import numpy as np


LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))


SCHEMA = "core.material.f3.native_cadence_adapter.v1"
FRAME_SELECTION_SCHEMA = "core.material.f3.native_volume_mls.frame_selection.v1"
NATIVE_INTERVAL_S = 0.002
MATCHED_INTERVAL_S = 0.01
MATCHED_STRIDE = 5
# This is a source-integrity tolerance, not a material acceptance threshold.
# It covers the saved-time jitter of the checked native source (about 22 us
# cumulative) while rejecting a .01 s source passed off as .002 s.
CADENCE_TOLERANCE_S = 5.0e-5
EXPECTED_EVENT_HORIZON_S = 8.35
DEFAULT_CANARY_INTERVALS = 4
MAX_UNREVIEWED_CANARY_INTERVALS = 20

# These are copied as gate metadata only.  They deliberately remain separate
# from source-integrity checks and are never changed by this adapter.
FIXED_GATES = {
    "per_source_unknown_fraction_max": 0.01,
    "cdf_sup_abs_max": 0.02,
    "event_window": "full_registered_window_required",
    "right_censored_counts_as_acceptance": False,
}

DENOMINATOR = {
    "seed_population": "all geometric seeds, including unknown and censored paths",
    "source_population": "seed x < 0 => source 0; seed x >= 0 => source 1",
    "unknown_fraction": "unknown seeds / all seeds in each source half",
    "cdf": "all seeds in each source half; no reliable-only denominator",
    "event_window": "a canary with right-censored paths is not an acceptance denominator",
}

# Measured on the existing native-.002, 512-seed, s=4, full-window run.  The
# estimates below are intentionally conservative linear planning estimates;
# they are not a qualification result and are not a queue registration.
MEASURED_NATIVE002 = {
    "seed_count": 512,
    "frame_count": 4176,
    "substeps": 4,
    "wall_seconds": 14743.410969495773,
    "cpu_child_seconds": 13340.05529,
    "peak_rss_mib": 731.75,
    "trace_bytes": 326373000,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def array_hash(value: np.ndarray) -> str:
    value = np.ascontiguousarray(np.asarray(value, dtype=np.int64))
    digest = hashlib.sha256()
    digest.update(canonical({"dtype": value.dtype.str, "shape": list(value.shape)}).encode())
    digest.update(value.tobytes())
    return digest.hexdigest()


def _atomic_json(path: str | Path, value: dict[str, Any]) -> None:
    path = Path(path).resolve()
    serialized = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != serialized:
            raise FileExistsError(f"immutable output differs from existing file: {path}")
        return
    partial = path.with_name(path.name + ".partial")
    partial.write_text(serialized, encoding="utf-8")
    partial.replace(path)


def _scalar(record: dict[str, Any], key: str, *, required: bool = True) -> Any:
    values: list[tuple[str, Any]] = []
    for container_name in ("case", "config"):
        container = record.get(container_name)
        if isinstance(container, dict) and container.get(key) is not None:
            values.append((container_name, container[key]))
    if record.get(key) is not None:
        values.append(("top_level", record[key]))
    if not values:
        if required:
            raise ValueError(f"prepared record has no {key!r}")
        return None
    first_name, first = values[0]
    for name, value in values[1:]:
        if isinstance(first, (int, float)) and isinstance(value, (int, float)):
            if float(first) != float(value):
                raise ValueError(f"prepared {key} disagrees between {first_name} and {name}")
        elif value != first:
            raise ValueError(f"prepared {key} disagrees between {first_name} and {name}")
    return first


def _resolve_candidate(prepared_path: Path, record: dict[str, Any]) -> Path:
    raw = record.get("candidate_definition")
    if not raw:
        prefix = record.get("generated_prefix")
        if prefix:
            raw = str(Path(str(prefix)).with_suffix(".xml"))
    if not raw:
        raise ValueError("prepared record has no candidate_definition or generated_prefix")
    candidate = Path(str(raw))
    candidates = [candidate]
    if not candidate.is_absolute():
        candidates.extend([
            Path.cwd() / candidate,
            prepared_path.parent / candidate,
            prepared_path.parent / candidate.name,
        ])
    for value in candidates:
        value = value.resolve()
        if value.is_file():
            return value
    raise FileNotFoundError(f"candidate XML does not exist: {raw}")


def inspect_prepared(prepared: str | Path) -> dict[str, Any]:
    """Validate prepared/XML lineage without changing either input."""
    prepared_path = Path(prepared).resolve()
    record = json.loads(prepared_path.read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        raise ValueError("prepared record must be a JSON object")
    dp_m = float(_scalar(record, "dp_m"))
    if not math.isfinite(dp_m) or dp_m <= 0.0:
        raise ValueError("prepared dp_m must be finite and positive")
    candidate = _resolve_candidate(prepared_path, record)
    candidate_sha = sha256_file(candidate)
    expected = None
    assets = record.get("input_assets")
    if isinstance(assets, dict):
        expected = assets.get(candidate.name)
        if expected is None:
            expected = assets.get(str(candidate))
    if expected is None and isinstance(record.get("inputs"), dict):
        expected = record["inputs"].get(str(candidate)) or record["inputs"].get(candidate.name)
    if expected is not None and str(expected) != candidate_sha:
        raise ValueError("candidate XML hash does not match prepared input binding")
    xml_text = candidate.read_text(encoding="utf-8")
    kernel_match = re.search(r'<parameter\s+key="Kernel"\s+value="(\d+)"', xml_text)
    kernel_id = int(kernel_match.group(1)) if kernel_match else None
    if kernel_id != 2:
        raise ValueError(f"candidate XML Kernel must be 2 (Wendland), got {kernel_id}")
    return {
        "path": str(prepared_path),
        "sha256": sha256_file(prepared_path),
        "case_id": _scalar(record, "case_id", required=False),
        "recipe_id": _scalar(record, "recipe_id", required=False),
        "dp_m": dp_m,
        "candidate_definition": str(candidate),
        "candidate_definition_sha256": candidate_sha,
        "kernel_id": kernel_id,
        "qualified": bool(_scalar(record, "qualified", required=False) or False),
        "formal_release": bool(_scalar(record, "formal_release", required=False) or False),
    }


def inspect_native_source(source: str | Path) -> dict[str, Any]:
    """Read source metadata and prove that its saved frames are native .002 s."""
    source_path = Path(source).resolve()
    required = ("time", "position", "velocity", "mass", "density", "valid", "type")
    with h5py.File(source_path, "r") as handle:
        missing = [name for name in required if name not in handle]
        if missing:
            raise ValueError(f"native source is missing datasets: {missing}")
        time_axis = np.asarray(handle["time"][:], dtype=np.float64)
        if (time_axis.ndim != 1 or len(time_axis) < 2 or not np.isfinite(time_axis).all()
                or np.any(np.diff(time_axis) <= 0.0)):
            raise ValueError("native source time must be finite and strictly increasing")
        frame_count, particle_count = handle["position"].shape[:2]
        expected_shapes = {
            "position": (frame_count, particle_count, 3),
            "velocity": (frame_count, particle_count, 3),
            "mass": (frame_count, particle_count),
            "density": (frame_count, particle_count),
            "valid": (frame_count, particle_count),
            "type": (frame_count, particle_count),
        }
        for name, shape in expected_shapes.items():
            if handle[name].shape != shape:
                raise ValueError(f"native source {name} has shape {handle[name].shape}, expected {shape}")
        valid0 = np.asarray(handle["valid"][0], dtype=bool)
        type0 = np.asarray(handle["type"][0], dtype=np.int64)
        fluid0 = valid0 & (type0 == 3)
        mass0 = np.asarray(handle["mass"][0], dtype=np.float64)
        density0 = np.asarray(handle["density"][0], dtype=np.float64)
        valid_mass = fluid0 & np.isfinite(mass0) & (mass0 > 0.0)
        valid_density = fluid0 & np.isfinite(density0) & (density0 > 0.0)
        if not np.all(valid_mass & valid_density):
            raise ValueError("native frame 0 has nonpositive or nonfinite fluid mass/density")
    dt = np.diff(time_axis)
    dt_error = np.abs(dt - NATIVE_INTERVAL_S)
    time_error = np.abs((time_axis - time_axis[0])
                        - np.arange(len(time_axis), dtype=np.float64) * NATIVE_INTERVAL_S)
    cadence_pass = bool(np.all(dt_error <= CADENCE_TOLERANCE_S)
                        and np.all(time_error <= CADENCE_TOLERANCE_S))
    if not cadence_pass:
        raise ValueError(
            "source is not native .002 s: saved timestamp error exceeds source-integrity tolerance")
    source_sha = sha256_file(source_path)
    return {
        "path": str(source_path),
        "sha256": source_sha,
        "frames": int(frame_count),
        "particles_axis": int(particle_count),
        "fluid_rows_frame0": int(np.count_nonzero(fluid0)),
        "time_start_s": float(time_axis[0]),
        "time_end_s": float(time_axis[-1]),
        "native_interval_target_s": NATIVE_INTERVAL_S,
        "interval_min_s": float(np.min(dt)),
        "interval_median_s": float(np.median(dt)),
        "interval_max_s": float(np.max(dt)),
        "max_interval_error_s": float(np.max(dt_error)),
        "max_cumulative_time_error_s": float(np.max(time_error)),
        "cadence_tolerance_s": CADENCE_TOLERANCE_S,
        "cadence_pass": cadence_pass,
        "full_event_window_available": bool(
            time_axis[-1] >= EXPECTED_EVENT_HORIZON_S - CADENCE_TOLERANCE_S),
        "datasets": list(required),
        "interpolation": False,
        "initial_mass_kg": float(mass0[valid_mass].sum()),
    }


def _selection_record(source_report: dict[str, Any], indices: np.ndarray) -> dict[str, Any]:
    indices = np.asarray(indices, dtype=np.int64)
    return {
        "schema": FRAME_SELECTION_SCHEMA,
        "selection_id": "f3-native002-every-fifth-direct-v1",
        "selection_mode": "every_fifth_direct_native_frame",
        "derived_view_role": "matched-.01 diagnostic view of native-.002 source; not an independent .01 solve",
        "source_h5": source_report["path"],
        "source_sha256": source_report["sha256"],
        "source_frame_count": source_report["frames"],
        "source_native_saved_interval_s": NATIVE_INTERVAL_S,
        "target_nominal_interval_s": MATCHED_INTERVAL_S,
        "target_time_tolerance_s": CADENCE_TOLERANCE_S,
        "logical_frame_count": int(len(indices)),
        "source_frame_indices": indices.tolist(),
        "selection_sha256": array_hash(indices),
        "interpolation": False,
        "qualification_claim": "none",
    }


def make_direct_selection(source: str | Path, output: str | Path) -> dict[str, Any]:
    """Write an immutable every-fifth direct native-frame selection manifest."""
    source_report = inspect_native_source(source)
    if (source_report["frames"] - 1) % MATCHED_STRIDE:
        raise ValueError("native frame count does not terminate on an exact every-fifth .01 s frame")
    indices = np.arange(0, source_report["frames"], MATCHED_STRIDE, dtype=np.int64)
    if int(indices[-1]) != source_report["frames"] - 1:
        raise AssertionError("direct selection did not retain source endpoint")
    selection = _selection_record(source_report, indices)
    _atomic_json(output, selection)
    selection["path"] = str(Path(output).resolve())
    selection["sha256"] = sha256_file(output)
    return selection


def _resource_estimate(seed_count: int, frame_count: int, substeps: int) -> dict[str, Any]:
    scale = (float(seed_count) / MEASURED_NATIVE002["seed_count"]
             * max(1, frame_count - 1) / (MEASURED_NATIVE002["frame_count"] - 1)
             * float(substeps) / MEASURED_NATIVE002["substeps"])
    return {
        "basis": {
            "schema": "measured_native002_512_seed_s4_full_window_v1",
            **MEASURED_NATIVE002,
        },
        "estimate_method": "linear seed*interval*substep scaling from existing native-.002 run",
        "seed_count": int(seed_count),
        "frame_count": int(frame_count),
        "substeps": int(substeps),
        "wall_seconds_estimate": float(MEASURED_NATIVE002["wall_seconds"] * scale),
        "cpu_child_seconds_estimate": float(MEASURED_NATIVE002["cpu_child_seconds"] * scale),
        "peak_rss_mib_budget": 4096.0,
        "peak_rss_mib_basis": MEASURED_NATIVE002["peak_rss_mib"],
        "trace_bytes_estimate": int(math.ceil(MEASURED_NATIVE002["trace_bytes"] * scale)),
        "gpu_required": False,
        "queue_action": "preflight_only; no queue or ledger mutation",
    }


def build_preflight(source: str | Path, prepared: str | Path, *,
                    backend_script: str | Path | None = None,
                    frame_selection: str | Path | None = None,
                    seeds: int = 512, substeps: int = 4,
                    canary_intervals: int = DEFAULT_CANARY_INTERVALS) -> dict[str, Any]:
    """Build a root-review-ready bounded preflight with immutable lineage."""
    if int(seeds) not in (512, 4096, 8192):
        raise ValueError("seeds must be one of 512, 4096, or 8192")
    if int(substeps) < 1:
        raise ValueError("substeps must be positive")
    if int(canary_intervals) < 1 or int(canary_intervals) > MAX_UNREVIEWED_CANARY_INTERVALS:
        raise ValueError("canary_intervals must be between 1 and 20")
    source_report = inspect_native_source(source)
    prepared_report = inspect_prepared(prepared)
    selection_report = None
    if frame_selection is not None:
        # Validate source binding and directness without importing the numerical backend.
        selection_path = Path(frame_selection).resolve()
        value = json.loads(selection_path.read_text(encoding="utf-8"))
        if value.get("schema") != FRAME_SELECTION_SCHEMA:
            raise ValueError("unsupported frame-selection schema")
        if value.get("source_h5") != source_report["path"]:
            raise ValueError("frame-selection source path mismatch")
        if value.get("source_sha256") != source_report["sha256"]:
            raise ValueError("frame-selection source hash mismatch")
        indices = np.asarray(value.get("source_frame_indices"), dtype=np.int64)
        if (indices.ndim != 1 or len(indices) < 2 or indices[0] != 0
                or indices[-1] != source_report["frames"] - 1
                or np.any(np.diff(indices) <= 0)
                or value.get("interpolation") is not False
                or value.get("selection_sha256") != array_hash(indices)):
            raise ValueError("frame-selection is not a strict direct native selection")
        selection_report = {
            "path": str(selection_path),
            "sha256": sha256_file(selection_path),
            "selection_sha256": value["selection_sha256"],
            "source_frame_indices": indices.tolist(),
            "logical_frame_count": int(len(indices)),
            "selection_mode": value.get("selection_mode"),
            "derived_view_role": value.get("derived_view_role"),
            "interpolation": False,
        }
    if backend_script is None:
        backend_script = (Path(__file__).with_name("f3_native_volume_mls_high_seed_v1.py")
                          if int(seeds) == 8192 else
                          Path(__file__).with_name("f3_native_volume_mls_v2.py"))
    backend_path = Path(backend_script).resolve()
    if not backend_path.is_file():
        raise FileNotFoundError(backend_path)
    event_window = {
        "required_registered_horizon_s": EXPECTED_EVENT_HORIZON_S,
        "source_horizon_s": source_report["time_end_s"],
        "full_window_available": source_report["full_event_window_available"],
        "right_censored_canary_is_acceptance": False,
        "status": "available_for_full_source" if source_report["full_event_window_available"]
                  else "short_canary_only; full_window_missing",
    }
    lineage = {
        "adapter": {"path": str(Path(__file__).resolve()), "sha256": sha256_file(__file__)},
        "backend": {"path": str(backend_path), "sha256": sha256_file(backend_path)},
        "source": {"path": source_report["path"], "sha256": source_report["sha256"]},
        "prepared": {"path": prepared_report["path"], "sha256": prepared_report["sha256"]},
        "candidate_definition": {
            "path": prepared_report["candidate_definition"],
            "sha256": prepared_report["candidate_definition_sha256"],
        },
        "frame_selection": selection_report,
    }
    lineage["lineage_sha256"] = sha256_json(lineage)
    return {
        "schema": SCHEMA,
        "adapter_version": 1,
        "created_at_utc": utc_now(),
        "status": "ready_for_bounded_canary" if source_report["cadence_pass"] else "blocked_cadence",
        "qualification_claim": "none",
        "numerical_backend_change": False,
        "future_state_access": False,
        "registry_mutations": 0,
        "ledger_mutations": 0,
        "gpu_started": False,
        "cadence_contract": {
            "native_output_interval_s": NATIVE_INTERVAL_S,
            "source_is_solver_saved_native_frames": True,
            "source_integrity_tolerance_s": CADENCE_TOLERANCE_S,
            "interpolation": False,
            "matched_view": "direct every-fifth native frame only; not an independent .01 s solve",
        },
        "source": source_report,
        "prepared_case": prepared_report,
        "frame_selection": selection_report,
        "fixed_gates_unchanged": dict(FIXED_GATES),
        "failure_denominator": dict(DENOMINATOR),
        "event_window": event_window,
        "bounded_canary": {
            "seed_count": int(seeds),
            "substeps": int(substeps),
            "intervals": int(canary_intervals),
            "frames_including_initial": int(canary_intervals) + 1,
            "stop_after_semantics": "backend stop_after is interval count; no full-window default",
            "recovery_protocol": [
                "first invocation may SIGKILL after committed HDF5 frame 2",
                "second invocation uses --resume and the same lineage/configuration",
                "checkpoint generations and HDF5 truncation must pass before any interpretation",
            ],
            "high_seed_role": "8192 seeds are a bounded numerical diagnostic only; no T2 claim",
        },
        "resource_estimate": _resource_estimate(int(seeds), int(canary_intervals) + 1, int(substeps)),
        "lineage": lineage,
    }


def run_canary(source: str | Path, prepared: str | Path, output: str | Path, *,
               frame_selection: str | Path | None = None, seeds: int = 512,
               substeps: int = 4, stop_after: int = DEFAULT_CANARY_INTERVALS,
               resume: bool = False, kill_after_h5_append: int | None = None,
               kill_after_generation: int | None = None,
               backend_script: str | Path | None = None) -> dict[str, Any]:
    """Run only a bounded, resumable canary through the frozen backend."""
    if stop_after > MAX_UNREVIEWED_CANARY_INTERVALS:
        raise ValueError("refusing an unreviewed long run; use the reviewed backend directly")
    preflight = build_preflight(
        source, prepared, backend_script=backend_script,
        frame_selection=frame_selection, seeds=seeds, substeps=substeps,
        canary_intervals=stop_after,
    )
    if preflight["status"] != "ready_for_bounded_canary":
        raise ValueError("native cadence preflight is blocked")
    if int(seeds) == 8192:
        from scripts import f3_native_volume_mls_high_seed_v1 as backend
    else:
        from scripts import f3_native_volume_mls_v2 as backend
    result = backend.run_trace(
        source, output, prepared, seeds=int(seeds), substeps=int(substeps),
        stop_after=int(stop_after), resume=bool(resume),
        frame_index_map=frame_selection,
        kill_after_h5_append=kill_after_h5_append,
        kill_after_generation=kill_after_generation,
    )
    receipt = {
        "schema": SCHEMA,
        "created_at_utc": utc_now(),
        "status": "completed_bounded_canary",
        "qualification_claim": "none",
        "preflight": preflight,
        "result": result,
    }
    receipt_path = Path(output).with_suffix(".cadence-adapter.json")
    _atomic_json(receipt_path, receipt)
    result["cadence_adapter_receipt"] = {
        "path": str(receipt_path.resolve()),
        "sha256": sha256_file(receipt_path),
    }
    return result


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--backend-script", type=Path)
    parser.add_argument("--frame-selection", type=Path)
    parser.add_argument("--make-frame-selection", type=Path,
                        help="write a direct every-fifth native-frame manifest")
    parser.add_argument("--preflight-output", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--seeds", type=int, default=512)
    parser.add_argument("--substeps", type=int, default=4)
    parser.add_argument("--stop-after", type=int, default=DEFAULT_CANARY_INTERVALS)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--kill-after-h5-append", type=int)
    parser.add_argument("--kill-after-generation", type=int)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    selection = args.frame_selection
    if args.make_frame_selection is not None:
        made = make_direct_selection(args.source, args.make_frame_selection)
        selection = Path(made["path"])
    preflight = build_preflight(
        args.source, args.prepared, backend_script=args.backend_script,
        frame_selection=selection, seeds=args.seeds, substeps=args.substeps,
        canary_intervals=args.stop_after,
    )
    _atomic_json(args.preflight_output, preflight)
    if args.preflight_only:
        print(json.dumps({"schema": SCHEMA, "status": preflight["status"],
                          "lineage_sha256": preflight["lineage"]["lineage_sha256"],
                          "preflight": str(args.preflight_output.resolve())}, sort_keys=True))
        return 0
    if args.output is None:
        parser.error("--output is required unless --preflight-only is used")
    result = run_canary(
        args.source, args.prepared, args.output, frame_selection=selection,
        seeds=args.seeds, substeps=args.substeps, stop_after=args.stop_after,
        resume=args.resume, kill_after_h5_append=args.kill_after_h5_append,
        kill_after_generation=args.kill_after_generation,
        backend_script=args.backend_script,
    )
    print(json.dumps({"schema": SCHEMA, "status": result["status"],
                      "qualification_claim": "none",
                      "output": result.get("output"),
                      "receipt": result.get("cadence_adapter_receipt")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
