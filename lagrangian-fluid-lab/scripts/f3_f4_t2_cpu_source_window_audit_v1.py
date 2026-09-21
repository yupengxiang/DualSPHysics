"""Read-only CPU audit for the current F3/F4 material evidence.

This entry point closes a narrow evidence gap between a terminal material
trace and a qualification decision.  It reopens only terminal artifacts,
streams the complete F3 source and material time axes, recomputes per-source
unknown mass and first-failure categories, and checks the fixed F3 CDF bounds.
The retained F4 canaries are audited one result at a time, including their
512-seed denominators and event-window status.

The report is deliberately an independent diagnostic artifact.  It never
submits a job, opens an active worker output, writes a ledger or registry, or
changes an existing score.  A structurally valid audit can therefore still
return ``T2_macro=false`` and ``T2_path=false`` when the scientific gates
fail.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Iterable

import h5py
import numpy as np


SCHEMA = "core.material.t2.cpu_source_window_audit.v1"
AUDIT_CODE = Path(__file__).resolve()
UNKNOWN_LIMIT = 0.01
CDF_LIMIT = 0.02
MASS_RELATIVE_TOLERANCE = 1.0e-8
CADENCE_RELATIVE_TOLERANCE = 1.0e-2
CADENCE_ABSOLUTE_FLOOR_S = 1.0e-7
FRAME_PARTICLE_CHUNK = 65536

F3_TRACE_REQUIRED = (
    "time", "position", "initial_position", "source_label", "tracer_id",
    "reliable", "permanent_unknown", "failure_reason", "first_passage",
    "return_time", "residence_opposite", "returned", "candidate_support_pass",
    "support_count", "effective_sample_size", "geometry_rank", "anisotropy",
    "reconstruction_error_mps", "native_mass_kg", "seed_mass_closure_error",
)
F3_SOURCE_REQUIRED = (
    "particle_id", "particle_zone", "source_label_initial_mk", "time",
    "position", "velocity", "density", "mass", "pressure", "valid", "type",
    "mk",
)
F4_TRACE_REQUIRED = (
    "time", "position", "initial_position", "source_label", "tracer_id",
    "weight", "reliable", "contact_time", "upward_time", "return_time",
    "residence", "contacted", "upward", "returned", "event_status",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _text(value: Any) -> str:
    if isinstance(value, (bytes, np.bytes_)):
        return value.decode("utf-8")
    return str(value)


def _plain(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    return value


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def resolve_path(lab_root: str | Path, value: str | Path) -> Path:
    """Resolve both portable lab-relative and historical absolute paths."""
    value_path = Path(value)
    if value_path.is_absolute():
        return value_path
    lab_root = Path(lab_root).resolve()
    candidates = (lab_root / value_path, lab_root.parent / value_path)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _hash_check(path: Path, expected: str | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "expected_sha256": expected,
        "sha256": None,
        "pass": False,
    }
    if path.is_file():
        result["sha256"] = sha256_file(path)
        result["pass"] = expected is None or result["sha256"] == expected
    return result


def _json_attr(handle: h5py.File, name: str) -> dict[str, Any] | None:
    value = handle.attrs.get(name)
    if value is None:
        return None
    try:
        parsed = json.loads(_text(value))
    except (TypeError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _shape_map(handle: h5py.File) -> dict[str, list[int]]:
    return {name: [int(axis) for axis in handle[name].shape] for name in handle}


def _cadence_stats(times: np.ndarray, nominal_interval_s: float) -> dict[str, Any]:
    times = np.asarray(times, dtype=np.float64)
    finite = bool(np.isfinite(times).all())
    monotone = bool(len(times) >= 1 and finite and (len(times) == 1 or np.all(np.diff(times) > 0.0)) )
    intervals = np.diff(times) if len(times) > 1 else np.empty(0, dtype=np.float64)
    errors = np.abs(times - np.arange(len(times), dtype=np.float64) * nominal_interval_s)
    tolerance = max(CADENCE_ABSOLUTE_FLOOR_S, CADENCE_RELATIVE_TOLERANCE * nominal_interval_s)
    return {
        "frame_count": int(len(times)),
        "time_start_s": float(times[0]) if len(times) else None,
        "time_end_s": float(times[-1]) if len(times) else None,
        "time_finite": finite,
        "time_monotone": monotone,
        "nominal_interval_s": float(nominal_interval_s),
        "interval_min_s": float(np.min(intervals)) if len(intervals) else None,
        "interval_median_s": float(np.median(intervals)) if len(intervals) else None,
        "interval_max_s": float(np.max(intervals)) if len(intervals) else None,
        "max_abs_timestamp_error_s": float(np.max(errors)) if len(errors) else 0.0,
        "cadence_tolerance_s": float(tolerance),
        "cadence_pass": bool(finite and monotone and (len(errors) == 0 or np.max(errors) <= tolerance)),
        "exact_error_alert_2e-5_s": bool(len(errors) and np.max(errors) > 2.0e-5),
        "interpretation": (
            "The one-percent saved-output bound is the structural cadence check; "
            "the exact timestamp error is retained as a diagnostic and is not a "
            "new qualification threshold."
        ),
    }


def _source_field_finite_counts(handle: h5py.File, frame: int, particle_count: int) -> dict[str, int]:
    result = {name: 0 for name in ("position", "velocity", "density", "pressure", "mass")}
    valid = np.asarray(handle["valid"][frame], dtype=bool)
    for start in range(0, particle_count, FRAME_PARTICLE_CHUNK):
        stop = min(start + FRAME_PARTICLE_CHUNK, particle_count)
        active = valid[start:stop]
        for name in result:
            value = np.asarray(handle[name][frame, start:stop])
            if value.ndim == 2:
                finite = np.isfinite(value).all(axis=1)
            else:
                finite = np.isfinite(value)
            result[name] += int((active & ~finite).sum())
    return result


def audit_f3_source_h5(
    path: str | Path,
    *,
    expected_sha256: str | None = None,
    expected_frames: int | None = None,
    expected_particles: int | None = None,
    nominal_interval_s: float = 0.01,
) -> dict[str, Any]:
    """Stream every saved source frame and return an integrity receipt."""
    path = Path(path)
    result: dict[str, Any] = {
        "role": "F3_native_source",
        "path": str(path),
        "qualification_claim": "none",
        "hash": _hash_check(path, expected_sha256),
        "errors": [],
        "frames_scanned": 0,
        "particle_count": None,
        "mass": {},
        "finite_active_counts": {},
    }
    if not path.is_file():
        result["errors"] = ["missing_source_h5"]
        result["integrity_pass"] = False
        return result

    with h5py.File(path, "r") as handle:
        missing = [name for name in F3_SOURCE_REQUIRED if name not in handle]
        result["datasets"] = _shape_map(handle)
        if missing:
            result["errors"].append("missing_dataset:" + ",".join(missing))
            result["integrity_pass"] = False
            return result
        times = np.asarray(handle["time"][:], dtype=np.float64)
        frame_count = len(times)
        particle_count = int(handle["particle_id"].shape[0])
        result["frames_scanned"] = frame_count
        result["particle_count"] = particle_count
        if expected_frames is not None and frame_count != int(expected_frames):
            result["errors"].append("frame_count_mismatch")
        if expected_particles is not None and particle_count != int(expected_particles):
            result["errors"].append("particle_count_mismatch")
        if handle["position"].shape != (frame_count, particle_count, 3):
            result["errors"].append("position_shape_mismatch")
        if handle["velocity"].shape != (frame_count, particle_count, 3):
            result["errors"].append("velocity_shape_mismatch")
        for name in ("mass", "density", "pressure", "valid", "type", "mk"):
            if handle[name].shape != (frame_count, particle_count):
                result["errors"].append(name + "_shape_mismatch")
        ids = np.asarray(handle["particle_id"][:])
        result["particle_ids_unique"] = bool(len(np.unique(ids)) == len(ids))
        if not result["particle_ids_unique"]:
            result["errors"].append("duplicate_particle_id")

        result["cadence"] = _cadence_stats(times, nominal_interval_s)
        if not result["cadence"]["cadence_pass"]:
            result["errors"].append("source_time_or_cadence")

        reference_mass = None
        max_abs_error = 0.0
        max_relative_error = 0.0
        max_error_frame = None
        bad_mass_frames = 0
        nonfinite_mass = 0
        nonpositive_active_mass = 0
        finite_counts = {name: 0 for name in ("position", "velocity", "density", "pressure", "mass")}
        for frame in range(frame_count):
            valid = np.asarray(handle["valid"][frame], dtype=bool)
            mass = np.asarray(handle["mass"][frame], dtype=np.float64)
            active_mass = mass[valid]
            nonfinite_mass += int((~np.isfinite(active_mass)).sum())
            nonpositive_active_mass += int((active_mass <= 0.0).sum())
            frame_mass = float(np.nansum(active_mass))
            if reference_mass is None:
                reference_mass = frame_mass
            absolute_error = abs(frame_mass - reference_mass)
            relative_error = absolute_error / max(abs(reference_mass), np.finfo(float).tiny)
            if absolute_error > max_abs_error:
                max_abs_error = absolute_error
                max_relative_error = relative_error
                max_error_frame = frame
            if relative_error > MASS_RELATIVE_TOLERANCE:
                bad_mass_frames += 1
            counts = _source_field_finite_counts(handle, frame, particle_count)
            for name, count in counts.items():
                finite_counts[name] += int(count)
        mass_pass = bool(
            reference_mass is not None
            and np.isfinite(reference_mass)
            and reference_mass > 0.0
            and nonfinite_mass == 0
            and nonpositive_active_mass == 0
            and bad_mass_frames == 0
        )
        if not mass_pass:
            result["errors"].append("source_mass_closure_or_finiteness")
        if any(finite_counts.values()):
            result["errors"].append("nonfinite_active_source_field")
        result["mass"] = {
            "reference_mass_kg": reference_mass,
            "max_abs_frame_error_kg": float(max_abs_error),
            "max_relative_frame_error": float(max_relative_error),
            "max_error_frame": max_error_frame,
            "bad_frame_count": int(bad_mass_frames),
            "nonfinite_active_mass_count": int(nonfinite_mass),
            "nonpositive_active_mass_count": int(nonpositive_active_mass),
            "relative_tolerance": MASS_RELATIVE_TOLERANCE,
            "mass_closure_pass": mass_pass,
        }
        result["finite_active_counts"] = finite_counts
    result["integrity_pass"] = not result["errors"] and result["hash"]["pass"]
    return result


def _checkpoint_semantic_hash(path: Path, fields: Iterable[str]) -> str | None:
    """Recompute the content hash used by native F3/F4 checkpoint writers."""
    digest = hashlib.sha256()
    try:
        with np.load(path, allow_pickle=False) as archive:
            for name in fields:
                if name not in archive:
                    return None
                value = np.ascontiguousarray(np.asarray(archive[name]))
                digest.update(str(name).encode("utf-8"))
                digest.update(_canonical({"dtype": value.dtype.str, "shape": value.shape}).encode("utf-8"))
                digest.update(value.tobytes())
    except (OSError, ValueError, KeyError):
        return None
    return digest.hexdigest()


def _audit_checkpoint(trace_path: Path, expected_committed: int, expected_schema_prefix: str) -> dict[str, Any]:
    manifest_path = trace_path.with_name(trace_path.name + ".checkpoint.json")
    output: dict[str, Any] = {
        "manifest_path": str(manifest_path),
        "schema": None,
        "committed_frame": None,
        "generation_path": None,
        "state_sha256": None,
        "semantic_state_sha256": None,
        "file_sha256": None,
        "state_hash_pass": False,
        "file_hash_pass": None,
        "pass": False,
        "errors": [],
    }
    if not manifest_path.is_file():
        output["errors"] = ["missing_checkpoint_manifest"]
        return output
    try:
        record = read_json(manifest_path)
    except (OSError, ValueError) as error:
        output["errors"] = ["invalid_checkpoint_manifest:" + str(error)]
        return output
    output["schema"] = record.get("schema")
    output["committed_frame"] = record.get("committed_frame", record.get("committed"))
    output["state_sha256"] = record.get("state_sha256")
    generation = record.get("checkpoint_npz")
    manifest_parent = manifest_path.parent
    if generation is not None:
        generation_path = resolve_path(manifest_parent, generation)
    elif record.get("generation") and record.get("generation_dir"):
        generation_path = manifest_parent / str(record["generation_dir"]) / str(record["generation"])
    elif record.get("generation"):
        generation_path = manifest_parent / str(record["generation"])
    else:
        generation_path = trace_path.with_name(trace_path.name + ".checkpoint.npz")
    output["generation_path"] = str(generation_path)
    if output["schema"] is None or not str(output["schema"]).startswith(expected_schema_prefix):
        output["errors"].append("checkpoint_schema_mismatch")
    if int(output["committed_frame"] or -1) != int(expected_committed):
        output["errors"].append("checkpoint_committed_frame_mismatch")
    fields = record.get("fields", [])
    if record.get("file_sha256"):
        output["file_sha256"] = record["file_sha256"]
        file_hash = _hash_check(generation_path, record["file_sha256"])
        output["file_hash"] = file_hash
        output["file_hash_pass"] = bool(file_hash["pass"])
        if not output["file_hash_pass"]:
            output["errors"].append("checkpoint_file_hash_mismatch")
        semantic_hash = _checkpoint_semantic_hash(generation_path, fields)
        output["semantic_state_sha256"] = semantic_hash
        output["state_hash_pass"] = bool(semantic_hash is not None and semantic_hash == output["state_sha256"])
        output["state_hash"] = {
            "path": str(generation_path),
            "exists": generation_path.is_file(),
            "expected_sha256": output["state_sha256"],
            "sha256": semantic_hash,
            "pass": output["state_hash_pass"],
            "kind": "semantic_fields_hash",
        }
    else:
        state_hash = _hash_check(generation_path, output["state_sha256"])
        output["state_hash_pass"] = bool(state_hash["pass"])
        output["state_hash"] = state_hash
    if not output["state_hash_pass"]:
        output["errors"].append("checkpoint_state_hash_mismatch")
    output["pass"] = not output["errors"]
    return output


def _source_reason_counts(
    failure_reason_rows: Iterable[np.ndarray],
    unknown_rows: Iterable[np.ndarray],
    labels: np.ndarray,
) -> tuple[dict[str, Counter[str]], dict[str, list[int]]]:
    labels = np.asarray(labels)
    source_ids = [str(item) for item in sorted(np.unique(labels).tolist())]
    counters = {source: Counter() for source in source_ids}
    first_frames = {source: [] for source in source_ids}
    seen = np.zeros(len(labels), dtype=bool)
    for frame, (reasons, unknown) in enumerate(zip(failure_reason_rows, unknown_rows)):
        unknown = np.asarray(unknown, dtype=bool)
        newly_failed = unknown & ~seen
        indices = np.flatnonzero(newly_failed)
        for index in indices:
            source = str(labels[index])
            reason = _text(reasons[index])
            if reason in {"", "reliable", "nan", "None"}:
                reason = "unknown_without_failure_reason"
            counters[source][reason] += 1
            first_frames[source].append(frame)
        seen |= unknown
    return {source: dict(sorted(value.items())) for source, value in counters.items()}, first_frames


def _summary_source_rows(value: Any) -> dict[str, dict[str, Any]]:
    """Normalize historical summary rows without changing their evidence."""
    if isinstance(value, dict):
        output: dict[str, dict[str, Any]] = {}
        for source, row in value.items():
            if isinstance(row, dict):
                output[str(source)] = row
        return output
    if isinstance(value, list):
        output = {}
        for row in value:
            if not isinstance(row, dict) or row.get("source") is None:
                continue
            output[str(row["source"])] = row
        return output
    return {}


def _trace_binding_checks(binding: dict[str, Any], family: str) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    checks: dict[str, Any] = {}
    claim = binding.get("qualification_claim")
    checks["qualification_claim_none"] = claim in (None, "none")
    if not checks["qualification_claim_none"]:
        errors.append("trace_binding_carries_qualification_claim")
    # F3 records explicit forbidden fields.  The retained F4 artifacts encode
    # the same contract in their saved-frame/reference-provider semantics and
    # predate those optional binding keys, so absent declarations are accepted
    # while any contradictory declaration is rejected.
    checks["future_state_forbidden"] = (
        binding.get("future_velocity") in (None, "forbidden")
        and binding.get("future_density") in (None, "forbidden")
    )
    if family == "F3":
        checks["current_frame_only"] = binding.get("interpolation") is False and "current" in str(binding.get("frame_policy", ""))
        checks["native_frame_identity"] = binding.get("frame_selection", {}).get("selection_mode") == "identity_all_native_frames"
        checks["backend_present"] = bool(binding.get("backend"))
    else:
        checks["reference_provider"] = binding.get("provider_role") == "reference"
        checks["qualification_only_stage"] = binding.get("f4_definition", {}).get("source_definition", {}).get("stage") in (None, "qualification_only")
        checks["backend_present"] = bool(binding.get("backend"))
    for name, passed in checks.items():
        if not passed:
            errors.append("reader_binding:" + name)
    return checks, errors


def audit_f3_trace_h5(
    path: str | Path,
    *,
    summary: dict[str, Any],
    source_audit: dict[str, Any],
    expected_sha256: str | None = None,
    expected_source_sha256: str | None = None,
    expected_frames: int | None = None,
    expected_seed_count: int | None = None,
    unknown_limit: float = UNKNOWN_LIMIT,
) -> dict[str, Any]:
    """Recompute F3 terminal unknown mass and first-failure classes."""
    path = Path(path)
    result: dict[str, Any] = {
        "role": "F3_material_trace",
        "path": str(path),
        "qualification_claim": "none",
        "errors": [],
        "hash": _hash_check(path, expected_sha256),
        "source_hash_expected": expected_source_sha256,
        "source_hash_pass": expected_source_sha256 is None or source_audit.get("hash", {}).get("sha256") == expected_source_sha256,
    }
    if not path.is_file():
        result["errors"] = ["missing_trace_h5"]
        result["reader_reconstruction_pass"] = False
        return result
    with h5py.File(path, "r") as handle:
        missing = [name for name in F3_TRACE_REQUIRED if name not in handle]
        result["datasets"] = _shape_map(handle)
        result["attrs"] = {
            "schema": _text(handle.attrs.get("schema", "")),
            "trace_backend": _text(handle.attrs.get("trace_backend", "")),
            "committed": int(handle.attrs.get("committed", -1)),
        }
        if missing:
            result["errors"].append("missing_dataset:" + ",".join(missing))
            result["reader_reconstruction_pass"] = False
            return result
        binding = _json_attr(handle, "binding")
        if binding is None:
            result["errors"].append("invalid_or_missing_binding")
            binding = {}
        result["binding_schema"] = binding.get("schema")
        checks, binding_errors = _trace_binding_checks(binding, "F3")
        result["reader_contract"] = checks
        result["errors"].extend(binding_errors)
        times = np.asarray(handle["time"][:], dtype=np.float64)
        frames, seeds = len(times), int(handle["source_label"].shape[0])
        result["frames"] = frames
        result["seed_count"] = seeds
        if expected_frames is not None and frames != int(expected_frames):
            result["errors"].append("trace_frame_count_mismatch")
        if expected_seed_count is not None and seeds != int(expected_seed_count):
            result["errors"].append("trace_seed_count_mismatch")
        if handle["position"].shape != (frames, seeds, 3):
            result["errors"].append("trace_position_shape_mismatch")
        for name in ("reliable", "permanent_unknown", "failure_reason"):
            if handle[name].shape != (frames, seeds):
                result["errors"].append(name + "_shape_mismatch")
        source_nominal = source_audit.get("cadence", {}).get("nominal_interval_s")
        nominal_interval = (
            float(source_nominal)
            if source_nominal is not None and np.isfinite(float(source_nominal)) and float(source_nominal) > 0.0
            else float(binding.get("frame_selection", {}).get("target_nominal_interval_s", 0.01))
        )
        result["cadence"] = _cadence_stats(times, nominal_interval)
        source_times = np.asarray(source_audit.get("_times", []), dtype=np.float64)
        if len(source_times) == frames:
            result["source_time_match_max_abs_s"] = float(np.max(np.abs(times - source_times))) if frames else 0.0
            if result["source_time_match_max_abs_s"] > 1.0e-12:
                result["errors"].append("trace_source_time_mismatch")
        labels = np.asarray(handle["source_label"][:])
        ids = np.asarray(handle["tracer_id"].asstr()[:])
        source_ids = [str(item) for item in sorted(np.unique(labels).tolist())]
        result["source_ids"] = source_ids
        result["source_seed_counts"] = {source: int(np.sum(labels == int(source))) for source in source_ids}
        if len(set(ids.tolist())) != seeds:
            result["errors"].append("duplicate_tracer_id")
        if not np.isfinite(np.asarray(handle["initial_position"][:], dtype=float)).all():
            result["errors"].append("nonfinite_initial_seed")

        first_failure_rows: list[int] = []
        first_failure_reason_rows: list[np.ndarray] = []
        unknown_rows: list[np.ndarray] = []
        previous_unknown = np.zeros(seeds, dtype=bool)
        resurrection_count = 0
        for frame in range(frames):
            unknown = np.asarray(handle["permanent_unknown"][frame], dtype=bool)
            reliable = np.asarray(handle["reliable"][frame], dtype=bool)
            if frame and np.any(previous_unknown & ~unknown):
                resurrection_count += int(np.sum(previous_unknown & ~unknown))
            previous_unknown = unknown
            unknown_rows.append(unknown)
            first_failure_rows.append(int(np.sum(unknown)))
            first_failure_reason_rows.append(np.asarray(handle["failure_reason"][frame]))
        if resurrection_count:
            result["errors"].append("permanent_unknown_recovered")
        terminal_unknown = unknown_rows[-1] if unknown_rows else np.empty(seeds, dtype=bool)
        terminal_reliable = np.asarray(handle["reliable"][-1], dtype=bool)
        if not np.array_equal(~terminal_reliable, terminal_unknown):
            result["errors"].append("terminal_reliable_unknown_disagreement")
        reason_counts, first_frames = _source_reason_counts(first_failure_reason_rows, unknown_rows, labels)
        summary_rows = _summary_source_rows(summary.get("source_rows"))
        source_rows = []
        for source in source_ids:
            select = labels == int(source)
            count = int(select.sum())
            unknown_count = int(np.sum(terminal_unknown & select))
            unknown_fraction = float(unknown_count / count) if count else 1.0
            source_summary = summary_rows.get(source, {})
            summary_count = source_summary.get("final_unknown_count", source_summary.get("unknown_count"))
            summary_fraction = source_summary.get("final_unknown_fraction", source_summary.get("unknown_fraction"))
            if summary_count is not None and int(summary_count) != unknown_count:
                result["errors"].append("summary_unknown_count_mismatch:" + source)
            if summary_fraction is not None and abs(float(summary_fraction) - unknown_fraction) > 1.0e-12:
                result["errors"].append("summary_unknown_fraction_mismatch:" + source)
            source_rows.append({
                "source_id": source,
                "seed_denominator": count,
                "initial_mass_fraction": float(count / seeds) if seeds else 0.0,
                "terminal_unknown_count": unknown_count,
                "terminal_unknown_fraction": unknown_fraction,
                "unknown_gate_pass": bool(unknown_fraction <= unknown_limit),
                "terminal_reliable_fraction": float(np.sum(terminal_reliable & select) / count) if count else 0.0,
                "first_failure_frame": min(first_frames[source]) if first_frames[source] else None,
                "first_failure_time_s": float(times[min(first_frames[source])]) if first_frames[source] else None,
                "first_failure_reason_counts": reason_counts[source],
                "denominator_policy": "all geometric seeds carrying this source label",
            })
        result["source_rows"] = source_rows
        result["unknown_gate"] = {
            "limit": unknown_limit,
            "pass": bool(source_rows and all(row["unknown_gate_pass"] for row in source_rows)),
            "maximum_source_unknown_fraction": max((row["terminal_unknown_fraction"] for row in source_rows), default=None),
        }
        closure = np.asarray(handle["seed_mass_closure_error"][:], dtype=float)
        result["seed_mass_closure"] = {
            "max_abs_error": float(np.max(np.abs(closure))) if len(closure) else None,
            "pass": bool(len(closure) and np.isfinite(closure).all() and np.max(np.abs(closure)) <= 1.0e-12),
        }
        if not result["seed_mass_closure"]["pass"]:
            result["errors"].append("seed_mass_closure")
        native_mass = np.asarray(handle["native_mass_kg"][:], dtype=float)
        source_mass = source_audit.get("mass", {}).get("reference_mass_kg")
        result["native_mass_match"] = {
            "max_abs_error_kg": float(np.max(np.abs(native_mass - source_mass))) if source_mass is not None and len(native_mass) else None,
            "pass": bool(source_mass is not None and len(native_mass) and np.isfinite(native_mass).all() and np.max(np.abs(native_mass - source_mass)) <= 1.0e-6),
        }
        if not result["native_mass_match"]["pass"]:
            result["errors"].append("native_source_mass_mismatch")
        result["checkpoint"] = _audit_checkpoint(path, frames - 1, "core.material.f3.native_volume_mls.checkpoint")
        if not result["checkpoint"]["pass"]:
            result["errors"].append("checkpoint_integrity")
    result["reader_reconstruction_pass"] = not result["errors"] and result["hash"]["pass"] and result["source_hash_pass"]
    result["integrity_pass"] = bool(result["reader_reconstruction_pass"])
    return result


def audit_f4_trace_h5(
    path: str | Path,
    *,
    result_json: dict[str, Any],
    expected_sha256: str | None = None,
    nominal_interval_s: float = 0.002,
    unknown_limit: float = UNKNOWN_LIMIT,
) -> dict[str, Any]:
    """Audit a retained F4 H5 result without assigning qualification credit."""
    path = Path(path)
    result: dict[str, Any] = {
        "role": "F4_material_trace",
        "path": str(path),
        "qualification_claim": "none",
        "errors": [],
        "hash": _hash_check(path, expected_sha256),
    }
    if not path.is_file():
        result["errors"] = ["missing_trace_h5"]
        result["integrity_pass"] = False
        return result
    with h5py.File(path, "r") as handle:
        missing = [name for name in F4_TRACE_REQUIRED if name not in handle]
        result["datasets"] = _shape_map(handle)
        schema = _text(handle.attrs.get("schema", ""))
        result["schema"] = schema
        if missing:
            result["errors"].append("missing_dataset:" + ",".join(missing))
            result["integrity_pass"] = False
            return result
        binding = _json_attr(handle, "binding") or {}
        checks, binding_errors = _trace_binding_checks(binding, "F4")
        result["reader_contract"] = checks
        result["errors"].extend(binding_errors)
        times = np.asarray(handle["time"][:], dtype=float)
        frames, seeds = len(times), int(handle["source_label"].shape[0])
        result["frames"] = frames
        result["seed_count"] = seeds
        result["committed_frame"] = int(handle.attrs.get("committed", -1))
        if result["committed_frame"] != frames - 1:
            result["errors"].append("committed_frame_mismatch")
        result["cadence"] = _cadence_stats(times, nominal_interval_s)
        if not result["cadence"]["time_monotone"]:
            result["errors"].append("trace_time_nonmonotone")
        labels = np.asarray(handle["source_label"][:])
        ids = np.asarray(handle["tracer_id"].asstr()[:])
        weights = np.asarray(handle["weight"][:], dtype=float)
        if len(set(ids.tolist())) != seeds:
            result["errors"].append("duplicate_tracer_id")
        if weights.shape != (seeds,) or not np.isfinite(weights).all() or np.any(weights <= 0.0):
            result["errors"].append("invalid_seed_weights")
        if weights.shape == (seeds,) and abs(float(weights.sum()) - 1.0) > 1.0e-12:
            result["errors"].append("seed_mass_not_closed")
        reliable = np.asarray(handle["reliable"][:], dtype=bool)
        if reliable.shape != (frames, seeds):
            result["errors"].append("reliable_shape_mismatch")
        if reliable.shape == (frames, seeds) and np.any(reliable[1:] & ~reliable[:-1]):
            result["errors"].append("reliability_recovered")
        source_rows = []
        for source in sorted(np.unique(labels).tolist()):
            select = labels == source
            count = int(select.sum())
            unknown_count = int(np.sum(~reliable[-1] & select))
            unknown_fraction = float(unknown_count / count) if count else 1.0
            source_rows.append({
                "source_id": str(source),
                "seed_denominator": count,
                "initial_mass_fraction": float(weights[select].sum()) if weights.shape == (seeds,) else None,
                "terminal_unknown_count": unknown_count,
                "terminal_unknown_fraction": unknown_fraction,
                "unknown_gate_pass": bool(unknown_fraction <= unknown_limit),
                "terminal_reliable_fraction": float(np.sum(reliable[-1] & select) / count) if count else 0.0,
                "denominator_policy": "all geometric seeds carrying this source label",
            })
        result["source_rows"] = source_rows
        result["unknown_gate"] = {
            "limit": unknown_limit,
            "pass": bool(source_rows and all(row["unknown_gate_pass"] for row in source_rows)),
            "maximum_source_unknown_fraction": max((row["terminal_unknown_fraction"] for row in source_rows), default=None),
        }
        expected_by_source = result_json.get("by_source", [])
        for row in source_rows:
            matching = [item for item in expected_by_source if str(item.get("source")) == row["source_id"]]
            if matching and "unknown_fraction_max" in matching[0] and abs(float(matching[0]["unknown_fraction_max"]) - row["terminal_unknown_fraction"]) > 1.0e-12:
                result["errors"].append("summary_unknown_fraction_mismatch:" + row["source_id"])
        result["event_window"] = {
            "complete": bool(result_json.get("event_window_complete") is True and result_json.get("event_window_status") == "complete"),
            "status": result_json.get("event_window_status"),
            "committed_time_s": result_json.get("committed_time_s"),
            "required_for_t2": True,
        }
        result["checkpoint"] = _audit_checkpoint(
            path,
            frames - 1,
            "core.material.f4.",
        )
        if not result["checkpoint"]["pass"]:
            result["errors"].append("checkpoint_integrity")
    result["integrity_pass"] = not result["errors"] and result["hash"]["pass"]
    result["gate_pass"] = bool(result["integrity_pass"] and result["unknown_gate"]["pass"] and result["event_window"]["complete"])
    return result


def classify_failure_reasons(
    *,
    unknown_fraction: float | None = None,
    cdf_max: float | None = None,
    event_window_complete: bool | None = None,
    cadence_pass: bool | None = None,
    text: str = "",
) -> list[str]:
    """Return stable, non-exclusive failure categories for a case."""
    categories: list[str] = []
    lower = text.lower()
    if unknown_fraction is not None and unknown_fraction > UNKNOWN_LIMIT:
        categories.append("unknown_mass_over_1_percent")
    if cdf_max is not None and cdf_max > CDF_LIMIT:
        categories.append("cdf_sup_difference_over_0.02")
    if event_window_complete is False:
        categories.append("event_window_right_censored_or_unresolved")
    if cadence_pass is False:
        categories.append("source_or_trace_cadence_invalid")
    if any(token in lower for token in ("reconstruction-error", "reconstruction error", "reconstruction gate", "fixed reconstruction")):
        categories.append("reconstruction_error_gate")
    if any(token in lower for token in ("wall_occluded", "wall-blocked", "wall blocked", "wall")):
        categories.append("wall_or_visibility_failure")
    if any(token in lower for token in ("low_effective_sample_size", "ess_fail", "ess failure")):
        categories.append("effective_sample_size_failure")
    if any(token in lower for token in ("no_support", "no support")):
        categories.append("no_support_failure")
    return list(dict.fromkeys(categories))


def audit_f3_rows(
    lab_root: str | Path,
    negative_path: str | Path,
    comparison_path: str | Path,
    *,
    scan_h5: bool = True,
) -> dict[str, Any]:
    negative = read_json(negative_path)
    comparison = read_json(comparison_path)
    rows_output = []
    cdf_by_source: dict[str, dict[str, Any]] = {}
    for source, item in comparison.get("source_comparison", {}).items():
        bounds = {
            "first_passage": float(item["difference"]["first_passage_cdf_sup_abs_difference_bound"]),
            "return": float(item["difference"]["return_cdf_sup_abs_difference_bound"]),
            "residence": float(item["difference"]["residence_cdf_sup_abs_difference_bound"]),
        }
        cdf_by_source[str(source)] = {
            "bounds": bounds,
            "maximum": max(bounds.values()),
            "pass": max(bounds.values()) <= CDF_LIMIT,
            "denominator_policy": "all geometric seeds remain in every source CDF denominator",
        }
    f3_rows = []
    for row_id, row_evidence in negative.get("rows_evidence", {}).items():
        summary = row_evidence["summary"]
        summary_path = resolve_path(lab_root, summary["path"])
        summary_value = read_json(summary_path)
        trace_path = Path(str(summary_path).replace(".summary.json", ".h5"))
        preflight_path = resolve_path(lab_root, row_evidence["source_preflight"]["path"])
        preflight = read_json(preflight_path)
        source_info = preflight.get("source", {})
        source_path = resolve_path(lab_root, source_info.get("path", ""))
        expected_source_sha = source_info.get("sha256") or row_evidence.get("parameter_binding", {}).get("source_sha256")
        source_audit = audit_f3_source_h5(
            source_path,
            expected_sha256=expected_source_sha,
            expected_frames=source_info.get("frames", preflight.get("source_frames")),
            expected_particles=source_info.get("particles_axis", source_info.get("fluid_rows_frame0")),
            nominal_interval_s=float(source_info.get("native_output_interval_nominal_s", 0.01)),
        ) if scan_h5 else {"integrity_pass": None, "hash": {"pass": None}, "mass": {}, "_times": []}
        if scan_h5 and source_path.is_file():
            with h5py.File(source_path, "r") as source_handle:
                source_audit["_times"] = np.asarray(source_handle["time"][:], dtype=float).tolist()
        trace_audit = audit_f3_trace_h5(
            trace_path,
            summary=summary_value,
            source_audit=source_audit,
            expected_sha256=row_evidence.get("output_hashes", {}).get("trace_h5", {}).get("sha256"),
            expected_source_sha256=expected_source_sha,
            expected_frames=summary_value.get("committed_frames"),
            expected_seed_count=row_evidence.get("parameter_binding", {}).get("seeds"),
        ) if scan_h5 else {"integrity_pass": None, "source_rows": [], "unknown_gate": {"pass": False}}
        summary_rows = _summary_source_rows(summary_value.get("source_rows"))
        max_unknown = max(
            (
                float(item.get("final_unknown_fraction", item.get("unknown_fraction", 0.0)))
                for item in summary_rows.values()
            ),
            default=None,
        )
        cdf_max = max((item["maximum"] for item in cdf_by_source.values()), default=None)
        row = {
            "row": int(row_id),
            "case_id": row_evidence.get("source_preflight", {}).get("prepared_case"),
            "source_path": str(source_path),
            "trace_path": str(trace_path),
            "source_audit": {k: v for k, v in source_audit.items() if k != "_times"},
            "trace_audit": trace_audit,
            "cdf_comparison": cdf_by_source,
            "failure_classification": classify_failure_reasons(
                unknown_fraction=max_unknown,
                cdf_max=cdf_max,
                event_window_complete=True,
                cadence_pass=source_audit.get("cadence", {}).get("cadence_pass"),
                text=json.dumps(summary_value.get("stage_failure_counts", {})),
            ),
            "qualification_credit": "none",
        }
        f3_rows.append(row)
    f3_rows.sort(key=lambda item: item["row"])
    return {
        "negative_evidence": str(resolve_path(lab_root, negative_path)),
        "comparison_evidence": str(resolve_path(lab_root, comparison_path)),
        "rows": f3_rows,
        "source_denominator": "row-specific source_label seed counts; no source-contact subset",
        "cdf_gate": {
            "limit": CDF_LIMIT,
            "pass": bool(cdf_by_source and all(item["pass"] for item in cdf_by_source.values())),
            "by_source": cdf_by_source,
            "diagnostic_only": True,
        },
        "qualification_claim": "none",
    }


def _f4_h5_path(lab_root: Path, result_path: Path) -> tuple[Path | None, str | None]:
    value = read_json(result_path)
    checkpoint = value.get("checkpoint_manifest")
    if checkpoint:
        checkpoint_path = resolve_path(lab_root, checkpoint)
        trace_path = Path(str(checkpoint_path).removesuffix(".checkpoint.json"))
        return trace_path, value.get("schema")
    return None, value.get("schema")


def audit_f4_cases(lab_root: str | Path, negative_path: str | Path, *, scan_h5: bool = True) -> dict[str, Any]:
    lab_root = Path(lab_root).resolve()
    negative = read_json(negative_path)
    cases: list[dict[str, Any]] = []
    for canary in negative.get("canaries", []):
        result_paths = canary.get("result")
        if isinstance(result_paths, str):
            result_paths = [result_paths]
        elif not isinstance(result_paths, list):
            result_paths = []
        if result_paths:
            for result_rel in result_paths:
                result_path = resolve_path(lab_root, result_rel)
                result_json = read_json(result_path)
                trace_path, _ = _f4_h5_path(lab_root, result_path)
                expected_hash = None
                if trace_path is not None:
                    # The execution receipt is the canonical byte/hash source
                    # for retained F4 outputs.  The result itself remains the
                    # scientific binding used below.
                    for item in result_json.get("outputs", []):
                        if item.get("path", "").endswith(".h5"):
                            expected_hash = item.get("sha256")
                if expected_hash is None and trace_path is not None:
                    expected_hash = None
                interval = 0.002 if "dense" in canary["id"] else 0.02
                committed_frame = result_json.get("committed_frame")
                committed_time = result_json.get("committed_time_s")
                if committed_frame is not None and committed_time is not None and int(committed_frame) > 0:
                    interval = float(committed_time) / int(committed_frame)
                trace_audit = audit_f4_trace_h5(
                    trace_path,
                    result_json=result_json,
                    expected_sha256=expected_hash,
                    nominal_interval_s=interval,
                ) if scan_h5 and trace_path is not None else {"integrity_pass": None, "source_rows": [], "unknown_gate": {"pass": False}}
                max_unknown = max((row["terminal_unknown_fraction"] for row in trace_audit.get("source_rows", [])), default=float(canary.get("unknown_fraction_max", 1.0)))
                text = str(canary.get("negative_finding", ""))
                cases.append({
                    "case_id": f"{canary['id']}::{Path(result_rel).stem}",
                    "canary_id": canary["id"],
                    "result_path": str(result_path),
                    "trace_path": str(trace_path) if trace_path else None,
                    "seed_denominator": int(sum(row.get("seed_denominator", 0) for row in trace_audit.get("source_rows", []))) if trace_audit.get("source_rows") else None,
                    "trace_audit": trace_audit,
                    "mass_closed": bool(result_json.get("mass_closed", canary.get("mass_closed", False))),
                    "event_window_complete": bool(result_json.get("event_window_complete") is True and result_json.get("event_window_status") == "complete"),
                    "unknown_fraction_max": max_unknown,
                    "failure_classification": classify_failure_reasons(
                        unknown_fraction=max_unknown,
                        event_window_complete=result_json.get("event_window_complete") is not True,
                        cadence_pass=trace_audit.get("cadence", {}).get("cadence_pass"),
                        text=text,
                    ),
                    "qualification_credit": "none",
                })
        else:
            # The tallwall short canary has a terminal trace/result pair under
            # its root evidence rather than the generic F4 result field.
            root_rel = canary.get("execution")
            root_path = resolve_path(lab_root, root_rel) if root_rel else None
            root = read_json(root_path) if root_path and root_path.is_file() else {}
            trace_path = None
            expected_hash = None
            for item in root.get("outputs_verified", []):
                if str(item.get("path", "")).endswith(".h5"):
                    trace_path = resolve_path(Path(root.get("attempt_dir", lab_root)), item["path"])
                    expected_hash = item.get("sha256")
                    break
            result_json = {}
            if trace_path is not None:
                candidate_result = trace_path.with_suffix(".json")
                if candidate_result.is_file():
                    result_json = read_json(candidate_result)
            trace_audit = audit_f4_trace_h5(
                trace_path,
                result_json=result_json,
                expected_sha256=expected_hash,
                nominal_interval_s=0.02,
            ) if scan_h5 and trace_path is not None else {"integrity_pass": None, "source_rows": [], "unknown_gate": {"pass": False}}
            diagnosis_summary = resolve_path(lab_root, canary.get("diagnosis_summary", ""))
            summary = read_json(diagnosis_summary) if diagnosis_summary.is_file() else {}
            observed = summary.get("canary_observation", {})
            max_unknown = float(observed.get("unknown_fraction_max", canary.get("unknown_fraction_max", 1.0)))
            cases.append({
                "case_id": canary["id"],
                "canary_id": canary["id"],
                "result_path": str(diagnosis_summary),
                "trace_path": str(trace_path) if trace_path else None,
                "seed_denominator": int(observed.get("seed_count", 512)),
                "trace_audit": trace_audit,
                "mass_closed": bool(observed.get("mass_closed", canary.get("mass_closed", False))),
                "event_window_complete": False,
                "unknown_fraction_max": max_unknown,
                "failure_classification": classify_failure_reasons(
                    unknown_fraction=max_unknown,
                    event_window_complete=False,
                    cadence_pass=trace_audit.get("cadence", {}).get("cadence_pass"),
                    text=json.dumps(summary.get("conclusion", {})),
                ),
                "qualification_credit": "none",
            })
    return {
        "negative_evidence": str(resolve_path(lab_root, negative_path)),
        "case_count": len(cases),
        "cases": cases,
        "denominator_policy": "each retained result is one case; every declared source keeps all geometric seeds in its denominator",
        "qualification_claim": "none",
    }


def build_report(lab_root: str | Path, output_path: str | Path | None = None, *, scan_h5: bool = True) -> dict[str, Any]:
    lab_root = Path(lab_root).resolve()
    evidence_root = lab_root / "campaigns/core-v1/material/evidence"
    f3_negative = evidence_root / "f3-adapter-rows29-31-terminal-negative-result-20260920.json"
    f3_comparison = evidence_root / "f3-adapter-rows29-31-terminal-comparison-20260920.json"
    f4_negative = evidence_root / "f4-material-negative-evidence-audit-20260920.json"
    f3 = audit_f3_rows(lab_root, f3_negative, f3_comparison, scan_h5=scan_h5)
    f4 = audit_f4_cases(lab_root, f4_negative, scan_h5=scan_h5)
    unknown_values = [
        row["trace_audit"].get("unknown_gate", {}).get("maximum_source_unknown_fraction")
        for row in f3["rows"]
    ] + [case.get("unknown_fraction_max") for case in f4["cases"]]
    unknown_values = [float(value) for value in unknown_values if value is not None]
    unknown_pass = bool(unknown_values) and max(unknown_values) <= UNKNOWN_LIMIT
    cdf_pass = bool(f3["cdf_gate"]["pass"])
    full_event_pass = bool(f4["case_count"] and all(case["event_window_complete"] for case in f4["cases"]))
    all_integrity = all(
        row["source_audit"].get("integrity_pass") and row["trace_audit"].get("integrity_pass")
        for row in f3["rows"]
    ) and all(case["trace_audit"].get("integrity_pass") for case in f4["cases"] if case["trace_path"])
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "created_at_utc": utc_now(),
        "status": "completed_negative_cpu_audit",
        "execution_constraints": {
            "cpu_only": True,
            "new_job_submitted": False,
            "gpu_started_by_audit": False,
            "solver_started_by_audit": False,
            "central_ledger_mutation": 0,
            "registry_mutation": 0,
            "existing_scores_modified": False,
            "terminal_h5_read_only": bool(scan_h5),
        },
        "registered_gates": {
            "unknown_fraction_per_source_max": UNKNOWN_LIMIT,
            "f3_cdf_sup_abs_difference_max": CDF_LIMIT,
            "f4_event_window_required": True,
            "source_cadence_relative_tolerance": CADENCE_RELATIVE_TOLERANCE,
        },
        "denominators": {
            "f3_rows": len(f3["rows"]),
            "f3_seed_count_per_row": {str(row["row"]): row["trace_audit"].get("seed_count") for row in f3["rows"]},
            "f4_cases": f4["case_count"],
            "f4_case_seed_denominators": {case["case_id"]: case["seed_denominator"] for case in f4["cases"]},
            "f4_source_denominator_policy": f4["denominator_policy"],
        },
        "f3": f3,
        "f4": f4,
        "gate_evaluation": {
            "source_reader_reconstruction_integrity_pass": bool(all_integrity),
            "unknown_mass_pass": bool(unknown_pass),
            "f3_cdf_pass": cdf_pass,
            "f4_event_window_pass": full_event_pass,
            "T2_macro": False,
            "T2_path": False,
            "qualification_claim": "none",
            "qualification_credit": "none",
        },
        "failure_classification_summary": {
            "f3": sorted({item for row in f3["rows"] for item in row["failure_classification"]}),
            "f4": sorted({item for case in f4["cases"] for item in case["failure_classification"]}),
        },
        "blocking_reasons": [
            "per-source unknown mass exceeds the fixed 1% gate in retained F3/F4 cases",
            "F3 cross-scope first-passage/return/residence CDF bounds exceed 0.02",
            "retained F4 material cases end in a right-censored or unresolved event window",
            "independent material calibration and acceptance record remain absent; this audit cannot create T2 credit",
        ],
        "interpretation_boundary": "A complete read-only audit binds source bytes, full saved time axes, reconstruction provenance, denominators and failure categories. It is diagnostic evidence and does not grant T2.",
    }
    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata-only", action="store_true", help="do not open terminal H5 files")
    args = parser.parse_args(argv)
    report = build_report(args.lab_root, args.output, scan_h5=not args.metadata_only)
    print(json.dumps({
        "output": str(args.output.resolve()),
        "schema": report["schema"],
        "f3_rows": report["denominators"]["f3_rows"],
        "f4_cases": report["denominators"]["f4_cases"],
        "unknown_mass_pass": report["gate_evaluation"]["unknown_mass_pass"],
        "f3_cdf_pass": report["gate_evaluation"]["f3_cdf_pass"],
        "T2_macro": report["gate_evaluation"]["T2_macro"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
