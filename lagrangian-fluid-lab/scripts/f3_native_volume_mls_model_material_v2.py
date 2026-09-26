"""Streaming, resumable v2 of the causal F3 model-material evaluator.

The causal model/reference providers, density policy, event updates, and RK4
step are reused from v1.  Each initial/substep row is appended to an
extendable HDF5 trace.  The same row stores a hash-bound snapshot of the full
integrator state and diagnostics, then a hash-chained commit record is flushed.

Recovery is intentionally fail-closed: committed rows and the commit chain are
verified before any tail is truncated.  This protects recoverable interruption
at row boundaries and detects partial uncommitted HDF5 tails when the file is
still structurally readable.  HDF5 itself is not a transactional filesystem;
an arbitrary power loss that corrupts HDF5 metadata cannot be repaired here.
No qualification credit is produced.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import argparse
import hashlib
import json
import platform
from pathlib import Path
import resource
import sys
import time
from typing import Any

import h5py
import numpy as np
import scipy

from scripts import f3_native_volume_mls_model_material as v1
from scripts.f3_native_volume_mls_temporal_v3 import (
    F3NativeVolumeMLS,
    _advance_events,
    _new_state,
    f3_walls,
    h_from_dp,
    source_labels,
)


SCHEMA = "core.material.f3.native_volume_mls.model_material.v2"
TRACE_SCHEMA = "core.material.f3.native_volume_mls.model_material_trace.v2"
BACKEND = "f3_native_volume_mls_shared_current_model_rho0_stream_v2"
MODEL_ROLE = v1.MODEL_ROLE
REFERENCE_ROLE = v1.REFERENCE_ROLE
_EXECUTION_DEPENDENCY_FILES = (
    "core_material.py",
    "core_contract.py",
    "passive_tracers.py",
    "f3_material_neighbors.py",
)
_V1_TRACE_FIELDS = (
    "position", "reliable", "permanent_unknown", "first_passage", "return_time",
    "residence_opposite", "returned", "support_count", "effective_sample_size",
    "geometry_rank", "condition_number", "reconstruction_error_mps",
    "candidate_count", "wall_rejected_count", "old_gate_pass",
    "candidate_support_pass", "failure_reason",
)
_BOOL_FIELDS = {
    "reliable", "permanent_unknown", "returned", "old_gate_pass",
    "candidate_support_pass",
}
_INT_FIELDS = {"support_count", "geometry_rank", "candidate_count", "wall_rejected_count"}
_STRING_DTYPE = h5py.string_dtype(encoding="utf-8")
_JOURNAL_STRING_FIELDS = {"diagnostics_json", "state_failure_reason"}


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _implementation_binding() -> dict[str, Any]:
    here = Path(__file__).resolve()
    v1_path = Path(v1.__file__).resolve()
    shared_path = here.with_name("f3_native_volume_mls_shared.py")
    runner_path = here.with_name("f3_native_volume_mls_temporal_v3.py")
    scripts_dir = here.parent
    local_dependencies = {}
    for name in _EXECUTION_DEPENDENCY_FILES:
        path = scripts_dir / name
        local_dependencies[name] = {
            "path": str(path.resolve()),
            "sha256": _sha256_file(path),
        }
    return {
        "version": "f3_native_volume_mls_model_material_v2",
        "module": str(here),
        "module_sha256": _sha256_file(here),
        "v1_adapter": str(v1_path),
        "v1_adapter_sha256": _sha256_file(v1_path),
        "shared_adapter": str(shared_path.resolve()),
        "shared_adapter_sha256": _sha256_file(shared_path),
        "mls_runner": str(runner_path.resolve()),
        "mls_runner_sha256": _sha256_file(runner_path),
        "local_execution_dependencies": local_dependencies,
        "python": sys.version,
        "platform": platform.platform(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "h5py": h5py.__version__,
    }


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _array_hash(*values: np.ndarray) -> str:
    digest = hashlib.sha256()
    for value in values:
        array = np.ascontiguousarray(np.asarray(value))
        digest.update(_canonical({"dtype": array.dtype.str, "shape": array.shape}).encode())
        digest.update(array.tobytes())
    return digest.hexdigest()


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, np.bytes_):
        return bytes(value).decode("utf-8")
    return str(value)


def _row_values(state: dict[str, np.ndarray], result, time_s: float) -> dict[str, Any]:
    """Make only the current row (never a history-sized list)."""
    row: dict[str, Any] = {"time": np.float64(time_s)}
    for name in _V1_TRACE_FIELDS:
        if name == "position":
            value = state[name]
        elif name in {"reliable", "permanent_unknown", "first_passage", "return_time",
                      "residence_opposite", "returned"}:
            value = state[name]
        elif name == "failure_reason":
            value = state[name]
        else:
            value = getattr(result, name)
        if name == "failure_reason":
            row[name] = np.asarray([str(v) for v in value], dtype=object)
        else:
            dtype = bool if name in _BOOL_FIELDS else np.int64 if name in _INT_FIELDS else np.float64
            row[name] = np.asarray(value, dtype=dtype)
    return row


def _trace_row_datasets(handle: h5py.File) -> dict[str, h5py.Dataset]:
    return {name: handle[name] for name in ("time", *_V1_TRACE_FIELDS)}


def _journal_row_datasets(handle: h5py.File) -> dict[str, h5py.Dataset]:
    journal = handle["_journal"]
    return {
        "step_index": journal["step_index"],
        "diagnostics_json": journal["diagnostics_json"],
        "residence_left": journal["residence_left"],
        "residence_right": journal["residence_right"],
        "state_failure_reason": journal["state_failure_reason"],
    }


def _read_failure_row(dataset: h5py.Dataset, index: int) -> np.ndarray:
    return np.asarray(dataset.asstr()[index], dtype=object)


def _digest_row(row: dict[str, Any], *, step_index: int, diagnostics_json: str,
                state: dict[str, np.ndarray]) -> str:
    digest = hashlib.sha256()

    def add(name: str, value: Any) -> None:
        digest.update(name.encode("utf-8") + b"\0")
        if name in {"failure_reason", "state_failure_reason", "diagnostics_json"}:
            if name == "failure_reason":
                payload = _canonical([str(v) for v in np.asarray(value, dtype=object)])
            elif name == "state_failure_reason":
                payload = _canonical([str(v) for v in np.asarray(value, dtype=object)])
            else:
                payload = str(value)
            digest.update(payload.encode("utf-8"))
        else:
            array = np.ascontiguousarray(np.asarray(value))
            digest.update(_canonical({"dtype": array.dtype.str, "shape": array.shape}).encode())
            digest.update(array.tobytes())

    add("time", np.asarray(row["time"], dtype=np.float64))
    for name in _V1_TRACE_FIELDS:
        add(name, row[name])
    add("step_index", np.asarray(step_index, dtype=np.int64))
    add("diagnostics_json", diagnostics_json)
    add("residence_left", np.asarray(state["residence_left"], dtype=np.float64))
    add("residence_right", np.asarray(state["residence_right"], dtype=np.float64))
    add("state_failure_reason", np.asarray(state["failure_reason"], dtype=object))
    return digest.hexdigest()


def _read_row(handle: h5py.File, index: int) -> tuple[dict[str, Any], dict[str, np.ndarray], int, str]:
    row: dict[str, Any] = {"time": np.float64(handle["time"][index])}
    for name in _V1_TRACE_FIELDS:
        if name == "failure_reason":
            row[name] = _read_failure_row(handle[name], index)
        else:
            row[name] = np.asarray(handle[name][index])
    journal = handle["_journal"]
    state = {
        "position": np.asarray(row["position"], dtype=np.float64),
        "reliable": np.asarray(row["reliable"], dtype=bool),
        "permanent_unknown": np.asarray(row["permanent_unknown"], dtype=bool),
        "first_passage": np.asarray(row["first_passage"], dtype=np.float64),
        "return_time": np.asarray(row["return_time"], dtype=np.float64),
        "residence_opposite": np.asarray(row["residence_opposite"], dtype=np.float64),
        "returned": np.asarray(row["returned"], dtype=bool),
        "origin": np.asarray(handle["source_label"], dtype=np.int8).astype(bool),
        "residence_left": np.asarray(journal["residence_left"][index], dtype=np.float64),
        "residence_right": np.asarray(journal["residence_right"][index], dtype=np.float64),
        "failure_reason": _read_failure_row(journal["state_failure_reason"], index),
    }
    step_index = int(journal["step_index"][index])
    diagnostics_json = _text(journal["diagnostics_json"].asstr()[index])
    return row, state, step_index, diagnostics_json


def _create_extendable(handle: h5py.File, name: str, dtype: Any, tail: tuple[int, ...],
                       chunks: tuple[int, ...] | None = None) -> h5py.Dataset:
    if chunks is None:
        chunks = (1, *tail)
    return handle.create_dataset(name, shape=(0, *tail), maxshape=(None, *tail),
                                 chunks=chunks, dtype=dtype)


def _create_trace(path: Path, seeds: np.ndarray, labels: np.ndarray, binding: dict[str, Any],
                  seed_hash: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "x") as handle:
        binding_json = _canonical(binding)
        handle.attrs.update(
            schema_version=2,
            trace_schema=TRACE_SCHEMA,
            backend=BACKEND,
            qualification_claim="none",
            material_reliability="not_established",
            binding_json=binding_json,
            binding_sha256=hashlib.sha256(binding_json.encode("utf-8")).hexdigest(),
            seed_hash=seed_hash,
            seed_count=len(seeds),
            committed_rows=0,
        )
        handle.create_dataset("seed_position", data=np.asarray(seeds, dtype=np.float64))
        handle.create_dataset("source_label", data=np.asarray(labels, dtype=np.int8))
        nseed = len(seeds)
        _create_extendable(handle, "time", np.float64, ())
        for name in _V1_TRACE_FIELDS:
            if name == "position":
                _create_extendable(handle, name, np.float64, (nseed, 3), (1, min(nseed, 128), 3))
            elif name == "failure_reason":
                _create_extendable(handle, name, _STRING_DTYPE, (nseed,), (1, min(nseed, 256)))
            else:
                dtype = np.bool_ if name in _BOOL_FIELDS else np.int64 if name in _INT_FIELDS else np.float64
                _create_extendable(handle, name, dtype, (nseed,), (1, min(nseed, 256)))
        journal = handle.create_group("_journal")
        journal.create_dataset("step_index", shape=(0,), maxshape=(None,), chunks=(128,), dtype=np.int64)
        journal.create_dataset("diagnostics_json", shape=(0,), maxshape=(None,), chunks=(128,), dtype=_STRING_DTYPE)
        journal.create_dataset("residence_left", shape=(0, nseed), maxshape=(None, nseed),
                               chunks=(1, min(nseed, 256)), dtype=np.float64)
        journal.create_dataset("residence_right", shape=(0, nseed), maxshape=(None, nseed),
                               chunks=(1, min(nseed, 256)), dtype=np.float64)
        journal.create_dataset("state_failure_reason", shape=(0, nseed), maxshape=(None, nseed),
                               chunks=(1, min(nseed, 256)), dtype=_STRING_DTYPE)
        journal.create_dataset("row_sha256", shape=(0,), maxshape=(None,), chunks=(128,), dtype="S64")
        commit_dtype = np.dtype([
            ("committed_rows", "<u8"), ("row_sha256", "S64"),
            ("chain_sha256", "S64"), ("record_sha256", "S64"),
        ])
        journal.create_dataset("commit_log", shape=(0,), maxshape=(None,), chunks=(128,), dtype=commit_dtype)
        handle.flush()


def _append_1d(dataset: h5py.Dataset, value: Any) -> None:
    old = len(dataset)
    dataset.resize((old + 1,))
    dataset[old] = value


def _append_array_row(dataset: h5py.Dataset, value: Any) -> None:
    old = dataset.shape[0]
    dataset.resize((old + 1, *dataset.shape[1:]))
    dataset[old] = value


def _chain_hash(previous: str, committed_rows: int, row_hash: str) -> tuple[str, str]:
    chain = hashlib.sha256(f"{previous}:{committed_rows}:{row_hash}".encode("ascii")).hexdigest()
    record = hashlib.sha256(f"{committed_rows}:{row_hash}:{chain}".encode("ascii")).hexdigest()
    return chain, record


def _append_row(handle: h5py.File, row: dict[str, Any], state: dict[str, np.ndarray],
                step_index: int, diagnostics: Counter) -> None:
    diagnostics_json = _canonical(dict(diagnostics))
    row_count = len(handle["time"])
    trace = _trace_row_datasets(handle)
    journal = _journal_row_datasets(handle)
    for name, dataset in trace.items():
        if name == "time":
            _append_1d(dataset, row["time"])
        else:
            _append_array_row(dataset, row[name])
    _append_1d(journal["step_index"], np.int64(step_index))
    _append_1d(journal["diagnostics_json"], diagnostics_json)
    _append_array_row(journal["residence_left"], state["residence_left"])
    _append_array_row(journal["residence_right"], state["residence_right"])
    _append_array_row(journal["state_failure_reason"], state["failure_reason"])
    row_hash = _digest_row(row, step_index=step_index, diagnostics_json=diagnostics_json, state=state)
    _append_1d(handle["_journal/row_sha256"], row_hash.encode("ascii"))
    # First durable phase: row data, checkpoint state, and its digest.
    handle.flush()

    log = handle["_journal/commit_log"]
    previous = "0" * 64 if row_count == 0 else _text(log[row_count - 1]["chain_sha256"])
    chain, record = _chain_hash(previous, row_count + 1, row_hash)
    log.resize((row_count + 1,))
    log[row_count] = (row_count + 1, row_hash.encode("ascii"), chain.encode("ascii"), record.encode("ascii"))
    # Second durable phase: a valid log entry is the commit decision.
    handle.flush()
    handle.attrs.modify("committed_rows", row_count + 1)
    handle.flush()


def _validate_header(handle: h5py.File, binding: dict[str, Any], seeds: np.ndarray,
                     labels: np.ndarray, seed_hash: str) -> None:
    expected_binding = _canonical(binding)
    attrs = handle.attrs
    if _text(attrs.get("trace_schema", "")) != TRACE_SCHEMA or _text(attrs.get("backend", "")) != BACKEND:
        raise ValueError("resume trace has an unsupported v2 schema/backend")
    if _text(attrs.get("qualification_claim", "")) != "none":
        raise ValueError("resume trace qualification claim is not none")
    if _text(attrs.get("material_reliability", "")) != "not_established":
        raise ValueError("resume trace reliability status is unsupported")
    actual_binding = _text(attrs.get("binding_json", ""))
    binding_hash = hashlib.sha256(actual_binding.encode("utf-8")).hexdigest()
    if _text(attrs.get("binding_sha256", "")) != binding_hash:
        raise ValueError("resume trace binding hash is corrupt")
    if actual_binding != expected_binding:
        raise ValueError("resume provenance/parameter/implementation binding mismatch")
    if _text(attrs.get("seed_hash", "")) != seed_hash:
        raise ValueError("resume seed hash mismatch")
    if int(attrs.get("seed_count", -1)) != len(seeds):
        raise ValueError("resume seed count mismatch")
    required = {"seed_position", "source_label", "time", *_V1_TRACE_FIELDS, "_journal"}
    if not required <= set(handle):
        raise ValueError("resume trace is missing required datasets")
    stored_seeds = np.asarray(handle["seed_position"], dtype=np.float64)
    stored_labels = np.asarray(handle["source_label"], dtype=np.int8)
    if not np.array_equal(stored_seeds, seeds) or not np.array_equal(stored_labels, labels):
        raise ValueError("resume trace static seed/label arrays mismatch")
    expected_journal = {"step_index", "diagnostics_json", "residence_left", "residence_right",
                        "state_failure_reason", "row_sha256", "commit_log"}
    if not expected_journal <= set(handle["_journal"]):
        raise ValueError("resume trace journal is incomplete")


def _expected_row_time(provider, step_index: int, substeps: int) -> float:
    if step_index == -1:
        return float(provider.times[0])
    interval, step = divmod(step_index, substeps)
    t0, t1 = float(provider.times[interval]), float(provider.times[interval + 1])
    dt = (t1 - t0) / substeps
    segment_time = t0 + step * dt
    return t1 if step == substeps - 1 else segment_time + dt


def _validate_and_recover_tail(handle: h5py.File, provider, substeps: int) -> int:
    """Verify the committed prefix, then truncate only uncommitted row/log tails."""
    journal = handle["_journal"]
    try:
        marker = int(handle.attrs["committed_rows"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("resume trace has an invalid committed-row marker") from error
    if marker < 0:
        raise ValueError("resume trace has a negative committed-row marker")

    trace_sets = _trace_row_datasets(handle)
    journal_sets = _journal_row_datasets(handle)
    row_hashes = journal["row_sha256"]
    commit_log = journal["commit_log"]
    row_lengths = [len(dataset) for dataset in (*trace_sets.values(), *journal_sets.values(), row_hashes)]
    if any(length < marker for length in row_lengths):
        raise ValueError("a row dataset is shorter than the committed marker")

    valid_commits = 0
    previous = "0" * 64
    invalid_log_tail = False
    for index in range(len(commit_log)):
        if index >= len(row_hashes):
            invalid_log_tail = True
            break
        try:
            entry = commit_log[index]
            count = int(entry["committed_rows"])
            row_hash = _text(entry["row_sha256"])
            chain = _text(entry["chain_sha256"])
            record = _text(entry["record_sha256"])
            expected_chain, expected_record = _chain_hash(previous, index + 1, row_hash)
            _, state, step_index, diagnostics_json = _read_row(handle, index)
            expected_row_hash = _digest_row(
                {"time": np.float64(handle["time"][index]), **{
                    name: (_read_failure_row(handle[name], index) if name == "failure_reason"
                           else np.asarray(handle[name][index])) for name in _V1_TRACE_FIELDS
                }},
                step_index=step_index,
                diagnostics_json=diagnostics_json,
                state=state,
            )
            parsed_counts = json.loads(diagnostics_json)
            valid_counts = (isinstance(parsed_counts, dict)
                            and all(isinstance(key, str) and isinstance(value, int) and value >= 0
                                    for key, value in parsed_counts.items())
                            and _canonical(parsed_counts) == diagnostics_json)
            if (count != index + 1 or row_hash != _text(row_hashes[index])
                    or chain != expected_chain or record != expected_record
                    or expected_row_hash != row_hash or not valid_counts
                    or step_index != index - 1
                    or not np.isfinite(float(handle["time"][index]))
                    or float(handle["time"][index]) != _expected_row_time(provider, step_index, substeps)):
                invalid_log_tail = True
                break
            valid_commits += 1
            previous = chain
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
            # A bad record may be discarded only if it is the final uncommitted log entry.
            invalid_log_tail = True
            break

    if invalid_log_tail:
        if valid_commits < marker:
            raise ValueError("committed-prefix integrity or commit-log validation failed")
        if len(commit_log) != valid_commits + 1:
            raise ValueError("commit log corruption is not confined to its uncommitted tail")
        commit_log.resize((valid_commits,))
        handle.flush()
    if marker > valid_commits:
        raise ValueError("committed marker is ahead of the valid hash-chained commit log")
    if valid_commits - marker > 1:
        raise ValueError("commit marker/log disagreement exceeds one interrupted commit")

    # A valid row record was flushed before its commit-log entry. If the process
    # stopped between the log flush and marker flush, promote that one decision.
    if marker != valid_commits:
        handle.attrs.modify("committed_rows", valid_commits)
        handle.flush()

    all_row_sets = (*trace_sets.values(), *journal_sets.values(), row_hashes)
    if any(len(dataset) < valid_commits for dataset in all_row_sets):
        raise ValueError("valid commit log references a missing row payload")
    for dataset in all_row_sets:
        if len(dataset) > valid_commits:
            dataset.resize((valid_commits, *dataset.shape[1:]))
    # Any rows beyond the valid commit count have no durable commit decision.
    if len(commit_log) > valid_commits:
        commit_log.resize((valid_commits,))
    handle.flush()
    return valid_commits


def _restore_state(handle: h5py.File, index: int) -> tuple[dict[str, np.ndarray], Counter]:
    _, state, _, diagnostics_json = _read_row(handle, index)
    state["origin"] = np.asarray(handle["source_label"], dtype=np.int8).astype(bool)
    diagnostics = json.loads(diagnostics_json)
    return state, Counter({str(key): int(value) for key, value in diagnostics.items()})


def _quantiles(values: np.ndarray) -> dict[str, Any]:
    values = np.asarray(values, dtype=np.float64)
    values = values[np.isfinite(values)]
    if not len(values):
        return {"count": 0, "p50": None, "p90": None, "p95": None, "p99": None}
    q = np.quantile(values, [0.50, 0.90, 0.95, 0.99])
    return {"count": int(len(values)), "p50": float(q[0]), "p90": float(q[1]),
            "p95": float(q[2]), "p99": float(q[3])}


def _summaries(handle: h5py.File, labels: np.ndarray) -> tuple[list[dict[str, Any]], list[float], float]:
    committed = int(handle.attrs["committed_rows"])
    nseed = len(labels)
    full_path = np.ones(nseed, dtype=bool)
    first_failure = np.full(nseed, -1, dtype=np.int64)
    unknown_fraction_by_frame: list[float] = []
    for index in range(committed):
        reliable = np.asarray(handle["reliable"][index], dtype=bool)
        full_path &= reliable
        newly_failed = (first_failure < 0) & ~reliable
        first_failure[newly_failed] = index
        unknown_fraction_by_frame.append(float(np.count_nonzero(~reliable) / nseed))

    final = committed - 1
    final_reliable = np.asarray(handle["reliable"][final], dtype=bool)
    final_first = np.asarray(handle["first_passage"][final], dtype=np.float64)
    final_return = np.asarray(handle["return_time"][final], dtype=np.float64)
    final_residence = np.asarray(handle["residence_opposite"][final], dtype=np.float64)
    rows: list[dict[str, Any]] = []
    for source in sorted(np.unique(labels).tolist()):
        select = labels == source
        count = int(np.count_nonzero(select))
        unknown_count = int(np.count_nonzero(select & ~final_reliable))
        fail_indices = first_failure[select]
        fail_indices = fail_indices[fail_indices >= 0]
        first_select = select & np.isfinite(final_first)
        return_select = select & np.isfinite(final_return)
        rows.append({
            "source": int(source),
            "seed_count": count,
            "initial_mass_fraction": float(count / nseed),
            "unknown_fraction_final": float(unknown_count / count),
            "common_reliable_path_fraction": float(np.count_nonzero(full_path[select]) / count),
            "observed_first_passage_fraction": float(np.count_nonzero(first_select) / count),
            "observed_return_fraction": float(np.count_nonzero(return_select) / count),
            "first_failure_frame": int(np.min(fail_indices)) if len(fail_indices) else None,
            "first_failure_time_s": float(handle["time"][int(np.min(fail_indices))]) if len(fail_indices) else None,
            "first_passage_time_quantiles_s": _quantiles(final_first[select]),
            "return_time_quantiles_s": _quantiles(final_return[select]),
            "residence_opposite_quantiles_s_lower_bound": _quantiles(final_residence[select]),
            "residence_censored_fraction": float(unknown_count / count),
        })
    common_path = float(np.count_nonzero(full_path) / nseed)
    return rows, unknown_fraction_by_frame, common_path


def _report(handle: h5py.File, provider, source: Path, output: Path, role: str,
            seeds: np.ndarray, labels: np.ndarray, seed_hash: str, binding: dict[str, Any],
            started: float, cpu_started: float) -> dict[str, Any]:
    source_rows, unknown_by_frame, common_path = _summaries(handle, labels)
    times = np.asarray(handle["time"], dtype=np.float64)
    unknown_final = unknown_by_frame[-1]
    stage_failure_counts = json.loads(_text(handle["_journal/diagnostics_json"].asstr()[-1]))
    completed_steps = len(times) - 1
    loaded_count = max(1, (completed_steps - 1) // int(binding["substeps_per_saved_interval"]) + 1)
    loaded_indices = list(range(min(loaded_count, int(binding["intervals_requested"]))))
    source_hash = provider.source_sha256
    if _sha256_file(source) != source_hash:
        raise ValueError("source bytes changed during material trace execution")
    return {
        "schema": SCHEMA,
        "trace_schema": TRACE_SCHEMA,
        "backend": BACKEND,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "completed",
        "qualification_claim": "none",
        "material_reliability": "not_established",
        "native_density_qualification": "not_applicable",
        "source": {
            "path": str(source), "sha256": source_hash, "role": role,
            "future_state_inputs": False, "frames_registered": int(provider.frame_count),
        },
        "output_trace_h5": str(output),
        "binding": binding,
        "implementation": _implementation_binding(),
        "density_policy": provider.estimator.binding,
        "seed_count": int(len(seeds)),
        "seed_hash": seed_hash,
        "source_rows": source_rows,
        "unknown_fraction_max": float(max(unknown_by_frame)),
        "unknown_fraction_final": float(unknown_final),
        "unknown_fraction_by_frame": {
            "time_s": times.tolist(), "fraction": unknown_by_frame,
        },
        "common_reliable_path_fraction": common_path,
        "mass_closure": {
            "seed_weight_definition": "uniform 1/N independent tracer weights",
            "closed": True, "closure_error": 0.0, "native_support_mass_used_for_weight": True,
        },
        "diagnostics": {
            "stage_failure_counts": stage_failure_counts,
            "loaded_frame_indices": loaded_indices,
            "peak_rss_kib": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
            "elapsed_seconds": float(time.monotonic() - started),
            "cpu_seconds": float(resource.getrusage(resource.RUSAGE_SELF).ru_utime
                                  + resource.getrusage(resource.RUSAGE_SELF).ru_stime - cpu_started),
            "streaming": True,
            "resume_elapsed_scope": "current invocation only",
        },
    }


def _interrupted_report(handle: h5py.File, output: Path, total_steps: int) -> dict[str, Any]:
    rows = int(handle.attrs["committed_rows"])
    return {
        "schema": SCHEMA,
        "trace_schema": TRACE_SCHEMA,
        "backend": BACKEND,
        "status": "interrupted",
        "qualification_claim": "none",
        "material_reliability": "not_established",
        "output_trace_h5": str(output),
        "committed_rows": rows,
        "completed_substeps": max(0, rows - 1),
        "total_substeps": int(total_steps),
        "resume_required": True,
    }


def _advance_rk4_with_first_failure(state: dict[str, np.ndarray], tracer,
                                   provider, walls: np.ndarray,
                                   interval_index: int, segment_time: float, dt: float,
                                   diagnostics: dict[str, Any]):
    """Advance one RK4 segment and preserve the earliest failed stage reason.

    The v2 trace keeps the v3 integration and unknown/censoring semantics, but
    makes the per-seed diagnostic consistent with the all-four-stage gate.  A
    later reliable k4 result must not overwrite an earlier k1/k2/k3 failure.
    """
    q = state["position"]
    active = np.asarray(state["reliable"], dtype=bool)
    k1 = tracer.reconstruct(q, provider.field_at(interval_index, segment_time), walls)
    k2 = tracer.reconstruct(
        q + 0.5 * dt * np.nan_to_num(k1.velocity),
        provider.field_at(interval_index, segment_time + 0.5 * dt), walls,
    )
    k3 = tracer.reconstruct(
        q + 0.5 * dt * np.nan_to_num(k2.velocity),
        provider.field_at(interval_index, segment_time + 0.5 * dt), walls,
    )
    k4 = tracer.reconstruct(
        q + dt * np.nan_to_num(k3.velocity),
        provider.field_at(interval_index, segment_time + dt), walls,
    )
    stages = (k1, k2, k3, k4)
    candidate = q + (dt / 6.0) * np.nan_to_num(
        k1.velocity + 2.0 * k2.velocity + 2.0 * k3.velocity + k4.velocity
    )
    usable = active.copy()
    for stage in stages:
        usable &= np.asarray(stage.reliable, dtype=bool)
    usable &= np.isfinite(candidate).all(axis=1)

    _advance_events(state, q, candidate, segment_time, dt, usable, state["origin"])
    state["position"] = np.where(usable[:, None], candidate, q)
    state["reliable"] = usable
    state["permanent_unknown"] = ~usable

    reasons = np.full(len(active), "reliable", dtype=object)
    first_failure = np.zeros(len(active), dtype=bool)
    for stage in stages:
        failed = active & ~np.asarray(stage.reliable, dtype=bool) & ~first_failure
        stage_reasons = np.asarray(stage.failure_reason, dtype=object)
        reasons[failed] = stage_reasons[failed]
        first_failure |= active & ~np.asarray(stage.reliable, dtype=bool)
        diagnostics["stage_failure_counts"].update(
            str(value) for value in stage.failure_reason[active]
        )
    invalid_candidate = active & ~usable & ~first_failure
    reasons[invalid_candidate] = "nonfinite_rk4_candidate"
    reasons[~active] = np.asarray(state["failure_reason"], dtype=object)[~active]
    reasons[usable] = "reliable"
    state["failure_reason"] = reasons
    return k4


def run_material_trace(source: str | Path, output: str | Path, *, role: str,
                       rho0_kgm3: float, dp_m: float, seeds: np.ndarray,
                       intervals: int = 20, substeps: int = 1,
                       walls: np.ndarray | None = None, resume: bool = False,
                       stop_after_steps: int | None = None) -> dict[str, Any]:
    """Stream an F3 model-material trace, optionally stopping and resuming.

    ``stop_after_steps`` is an absolute integration-step boundary from trace
    start, not a per-invocation allowance.  Resume is explicit and may only
    continue an existing trace whose complete input/implementation binding
    matches exactly.  Output is never silently overwritten.
    """
    started = time.monotonic()
    cpu_started = (resource.getrusage(resource.RUSAGE_SELF).ru_utime
                   + resource.getrusage(resource.RUSAGE_SELF).ru_stime)
    source = Path(source).resolve()
    output = Path(output).resolve()
    if source == output:
        raise ValueError("source and output trace paths must differ")
    if resume:
        if not output.is_file():
            raise FileNotFoundError(f"resume trace does not exist: {output}")
    elif output.exists() or output.is_symlink():
        raise FileExistsError(f"refusing to overwrite existing trace: {output}")

    seeds = np.asarray(seeds, dtype=np.float64)
    if seeds.ndim != 2 or seeds.shape[1:] != (3,) or len(seeds) == 0 or not np.isfinite(seeds).all():
        raise ValueError("seeds must be a nonempty finite [N,3] array")
    if role == MODEL_ROLE:
        provider = v1.ModelRho0CurrentProvider(source, rho0_kgm3=rho0_kgm3)
    elif role == REFERENCE_ROLE:
        provider = v1.ReferenceRho0CurrentProvider(source, rho0_kgm3=rho0_kgm3)
    else:
        raise ValueError(f"role must be {MODEL_ROLE!r} or {REFERENCE_ROLE!r}")

    try:
        intervals = int(intervals)
        substeps = int(substeps)
        if intervals < 1 or intervals >= provider.frame_count:
            raise ValueError("intervals must select at least one and fewer than all source intervals")
        if substeps < 1:
            raise ValueError("substeps must be positive")
        if walls is None:
            walls = f3_walls()
        walls = np.asarray(walls, dtype=np.float64)
        if walls.ndim != 3 or walls.shape[1:] != (3, 3) or not np.isfinite(walls).all():
            raise ValueError("walls must be finite [M,3,3]")
        labels = source_labels(seeds)
        seed_hash = _array_hash(seeds, labels)
        wall_hash = _array_hash(walls)
        tracer = F3NativeVolumeMLS(h_from_dp(dp_m))
        times = np.asarray(provider.times[:intervals + 1], dtype=np.float64)
        binding = {
            **provider.binding,
            "schema": SCHEMA,
            "backend": BACKEND,
            "trace_schema": TRACE_SCHEMA,
            "dp_m": float(dp_m),
            "h_m": float(tracer.h_m),
            "substeps_per_saved_interval": substeps,
            "intervals_requested": intervals,
            "time_start_s": float(times[0]),
            "time_end_s": float(times[-1]),
            "seed_hash": seed_hash,
            "source_label_hash": _array_hash(labels),
            "wall_hash": wall_hash,
            "implementation_versions": _implementation_binding(),
            "event_definition": {
                "source_label": "initial_x_ge_0",
                "event_plane": "x=0",
                "first_passage": "first usable crossing to opposite x side",
                "return": "first later usable crossing back to origin side",
                "residence": "integrated opposite-side time over usable segments",
            },
            "support_reliability": "native-volume MLS numerical support only; material error uncalibrated",
            "checkpoint": "HDF5 row snapshot plus SHA256 row hash and hash-chained commit log",
        }
        if _sha256_file(source) != provider.source_sha256:
            raise ValueError("source bytes changed while binding the material trace")

        total_steps = intervals * substeps
        if stop_after_steps is not None:
            if isinstance(stop_after_steps, (bool, np.bool_)) or not isinstance(stop_after_steps, (int, np.integer)):
                raise TypeError("stop_after_steps must be an integer absolute step boundary")
            stop_after_steps = int(stop_after_steps)
            if not 0 <= stop_after_steps <= total_steps:
                raise ValueError("stop_after_steps must be between zero and total integration steps")

        if not resume:
            _create_trace(output, seeds, labels, binding, seed_hash)
        with h5py.File(output, "r+") as handle:
            _validate_header(handle, binding, seeds, labels, seed_hash)
            committed = _validate_and_recover_tail(handle, provider, substeps)
            completed_steps = max(0, committed - 1)
            if stop_after_steps is not None and stop_after_steps < completed_steps:
                raise ValueError("stop_after_steps precedes the already committed checkpoint")
            diagnostics = Counter()
            state = None
            if committed:
                state, diagnostics = _restore_state(handle, committed - 1)
            else:
                initial_result = tracer.reconstruct(seeds, provider.field_at(0, float(times[0])), walls)
                state = _new_state(seeds, labels)
                state["failure_reason"] = np.asarray(initial_result.failure_reason, dtype=object)
                state["reliable"] = np.asarray(initial_result.reliable, dtype=bool)
                state["permanent_unknown"] = ~state["reliable"]
                initial_row = _row_values(state, initial_result, float(times[0]))
                _append_row(handle, initial_row, state, -1, diagnostics)
                committed = 1
                completed_steps = 0

            for step_index in range(completed_steps, total_steps):
                if stop_after_steps is not None and step_index >= stop_after_steps:
                    break
                interval, substep = divmod(step_index, substeps)
                t0, t1 = float(times[interval]), float(times[interval + 1])
                dt = (t1 - t0) / substeps
                segment_time = t0 + substep * dt
                result = _advance_rk4_with_first_failure(
                    state, tracer, provider, walls, interval, segment_time, dt,
                    {"stage_failure_counts": diagnostics},
                )
                frame_time = t1 if substep == substeps - 1 else segment_time + dt
                row = _row_values(state, result, frame_time)
                _append_row(handle, row, state, step_index, diagnostics)
                completed_steps += 1

            if completed_steps < total_steps:
                return _interrupted_report(handle, output, total_steps)
            report = _report(handle, provider, source, output, role, seeds, labels,
                             seed_hash, binding, started, cpu_started)
        # Hash only after HDF5 has closed and finalized its superblock metadata.
        report["trace_h5_sha256"] = _sha256_file(output)
        return report
    finally:
        provider.close()


def _load_seeds(path: str | None) -> np.ndarray:
    if path is None:
        return np.asarray([
            [-0.0010, -0.010, 0.040], [-0.0005, 0.010, 0.045],
            [0.0005, -0.010, 0.050], [0.0010, 0.010, 0.055],
        ], dtype=np.float64)
    return np.asarray(np.load(path, allow_pickle=False), dtype=np.float64)


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--role", choices=(MODEL_ROLE, REFERENCE_ROLE), required=True)
    parser.add_argument("--rho0-kgm3", type=float, default=1000.0)
    parser.add_argument("--dp-m", type=float, default=0.0075)
    parser.add_argument("--intervals", type=int, default=20)
    parser.add_argument("--substeps", type=int, default=1)
    parser.add_argument("--seeds")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--stop-after-steps", type=int)
    args = parser.parse_args()
    report_path = Path(args.report).resolve()
    if report_path.exists() and not args.resume:
        raise FileExistsError(f"refusing to overwrite existing report: {report_path}")
    report = run_material_trace(
        args.source, args.output, role=args.role, rho0_kgm3=args.rho0_kgm3,
        dp_m=args.dp_m, seeds=_load_seeds(args.seeds), intervals=args.intervals,
        substeps=args.substeps, resume=args.resume, stop_after_steps=args.stop_after_steps,
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "schema": report["schema"], "status": report["status"],
        "qualification_claim": report["qualification_claim"],
        "completed_substeps": report.get("completed_substeps", report.get("binding", {}).get("intervals_requested")),
        "trace_h5": report["output_trace_h5"], "report": str(report_path),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
