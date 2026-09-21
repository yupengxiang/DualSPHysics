"""Causal model-material adapter and short rollout evaluator.

The current model State contract contains position, velocity, mass and valid,
but deliberately contains no density.  Native-volume MLS therefore cannot
silently consume a reference CFD density.  This module provides one explicit
model-side density policy, ``rho0_constant_public_v1``: a positive public
reference density is broadcast over the *same current* predicted State.

The evaluator uses the shared native-volume MLS field adapter and the existing
affine MLS/RK4 implementation.  It holds the current predicted field during
each saved interval; it never reads the next model frame for an RK stage.  A
reference run can use the same rho0 policy as a separate control.  Neither run
is an F3 qualification result and the reference run does not use native CFD
density in the reconstructed weights.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
import platform
from pathlib import Path
import resource
import sys
import time
from typing import Any, Mapping

import h5py
import numpy as np

from scripts.core_material import StateH5Provider
from scripts.f3_native_volume_mls_shared import (
    BACKEND as SHARED_BACKEND,
    from_predicted_state,
    from_reference_frame,
)
from scripts.f3_native_volume_mls_temporal_v3 import (
    F3CurrentFrame,
    F3NativeVolumeMLS,
    F3TemporalReferenceProvider,
    _advance_events,
    _advance_rk4,
    _new_state,
    f3_walls,
    h_from_dp,
    source_labels,
)


SCHEMA = "core.material.f3.native_volume_mls.model_material.v1"
TRACE_SCHEMA = "core.material.f3.native_volume_mls.model_material_trace.v1"
BACKEND = "f3_native_volume_mls_shared_current_model_rho0_v1"
DENSITY_STRATEGY = "rho0_constant_public_current_state_v1"
MODEL_ROLE = "predicted_model_rollout"
REFERENCE_ROLE = "reference_control_rho0"


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _implementation_binding() -> dict[str, Any]:
    """Pin the evaluator and the two imported numerical layers."""
    shared = Path(__file__).with_name("f3_native_volume_mls_shared.py")
    runner = Path(__file__).with_name("f3_native_volume_mls_temporal_v3.py")
    return {
        "module": str(Path(__file__).resolve()),
        "module_sha256": sha256_file(__file__),
        "shared_adapter": str(shared.resolve()),
        "shared_adapter_sha256": sha256_file(shared),
        "mls_runner": str(runner.resolve()),
        "mls_runner_sha256": sha256_file(runner),
        "python": sys.version,
        "platform": platform.platform(),
        "numpy": np.__version__,
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


@dataclass(frozen=True)
class PublicRho0DensityEstimator:
    """Versioned density estimate made only from a public rho0 and State."""

    rho0_kgm3: float
    schema: str = "core.material.f3.native_volume_mls.model_density_rho0_constant.v1"

    def __post_init__(self):
        value = float(self.rho0_kgm3)
        if not np.isfinite(value) or value <= 0.0:
            raise ValueError("rho0_kgm3 must be finite and positive")
        object.__setattr__(self, "rho0_kgm3", value)

    @property
    def binding(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "strategy": DENSITY_STRATEGY,
            "rho0_kgm3": self.rho0_kgm3,
            "input": "public rho0 and one current core_contract.State",
            "time_binding": "estimate time equals State.time_s",
            "future_state_inputs": False,
            "reference_density_input": False,
            "spatial_density_model": "constant_over_current_support_rows",
        }

    def estimate(self, state) -> np.ndarray:
        from scripts.core_contract import State, validate_state

        if not isinstance(state, State):
            raise TypeError("density estimation requires a core_contract.State")
        validate_state(state)
        result = np.full(state.count, self.rho0_kgm3, dtype=np.float64)
        result.setflags(write=False)
        return result


def _check_interval(times: np.ndarray, index: int, time_s: float) -> None:
    if isinstance(index, (bool, np.bool_)) or not isinstance(index, (int, np.integer)):
        raise TypeError("interval index must be an integer")
    index = int(index)
    if not 0 <= index < len(times) - 1:
        raise IndexError("current interval is outside the registered source window")
    query = float(time_s)
    if not np.isfinite(query):
        raise ValueError("current field time must be finite")
    t0, t1 = float(times[index]), float(times[index + 1])
    tolerance = max(1.0e-13, 32.0 * np.finfo(np.float64).eps * max(1.0, abs(t0), abs(t1)))
    if query < t0 - tolerance or query > t1 + tolerance:
        raise ValueError(f"current field time {query} is outside [{t0}, {t1}]")


class ModelRho0CurrentProvider:
    """Causal model State provider with no future-frame access."""

    provider_role = "predicted_model_current_state_rho0_v1"

    def __init__(self, source: str | Path, *, rho0_kgm3: float, max_cache: int = 2):
        self.source = Path(source).resolve()
        self.state_provider = StateH5Provider(self.source, max_cache=max_cache, require_complete=True)
        self.estimator = PublicRho0DensityEstimator(rho0_kgm3)
        self.times = np.asarray(self.state_provider.times, dtype=np.float64)
        self.times.setflags(write=False)
        self.frame_count = len(self.times)
        self.source_sha256 = self.state_provider.source_sha256

    @property
    def loaded_indices(self):
        return self.state_provider.loaded_indices

    @property
    def binding(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "backend": BACKEND,
            "shared_field_backend": SHARED_BACKEND,
            "provider_role": MODEL_ROLE,
            "source_semantics": "autonomous_predicted_current_state_h5",
            "source_h5": str(self.source),
            "source_sha256": self.source_sha256,
            "state_schema": self.state_provider.state_schema,
            "density_estimator": self.estimator.binding,
            "field_time_policy": "current_frame_hold_within_registered_interval",
            "future_state_inputs": False,
            "native_reference_density_used": False,
            "native_particle_id_is_tracer_identity": False,
            "qualification_claim": "none",
        }

    def frame(self, index: int):
        state = self.state_provider.state(index)
        density = self.estimator.estimate(state)
        return from_predicted_state(
            state,
            density,
            density_semantics="model_rho0_constant_public_v1",
            source_semantics="predicted_current_state_h5_v1",
            frame_index=int(index),
            density_time_s=state.time_s,
        )

    def field_at(self, interval_index: int, time_s: float):
        _check_interval(self.times, interval_index, time_s)
        # Current-frame hold is deliberate: the next State is not loaded for
        # RK stages.  The argument is checked only to prevent extrapolation.
        return self.frame(int(interval_index))

    def future(self, *_args, **_kwargs):
        raise PermissionError("model material provider cannot access a future state")

    def close(self):
        self.state_provider.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


class ReferenceRho0CurrentProvider:
    """Reference support provider with native density intentionally replaced."""

    provider_role = "reference_control_current_frame_rho0_v1"

    def __init__(self, source: str | Path, *, rho0_kgm3: float, max_cache: int = 2):
        self.source = Path(source).resolve()
        self.reference = F3TemporalReferenceProvider(self.source, max_cache=max_cache)
        self.estimator = PublicRho0DensityEstimator(rho0_kgm3)
        self.times = np.asarray(self.reference.times, dtype=np.float64)
        self.times.setflags(write=False)
        self.frame_count = len(self.times)
        self.source_sha256 = self.reference.source_sha256
        self._cache: dict[int, Any] = {}

    @property
    def loaded_indices(self):
        return self.reference.loaded_indices

    @property
    def binding(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "backend": BACKEND,
            "shared_field_backend": SHARED_BACKEND,
            "provider_role": REFERENCE_ROLE,
            "source_semantics": "registered_reference_support_frame_native_position_velocity_mass",
            "source_h5": str(self.source),
            "source_sha256": self.source_sha256,
            "density_estimator": {
                **self.estimator.binding,
                "role": "reference_control",
                "density_semantics": "reference_rho0_constant_public_v1",
            },
            "field_time_policy": "current_frame_hold_within_registered_interval",
            "future_state_inputs": False,
            "native_reference_density_used": False,
            "native_density_read_for_weight": False,
            "native_particle_id_is_tracer_identity": False,
            "qualification_claim": "none",
        }

    def frame(self, index: int):
        index = int(index)
        if index in self._cache:
            return self._cache[index]
        native = self.reference.frame(index)
        # Keep native support geometry, mass, velocity and validity, while
        # replacing density for the declared rho0 control.  This makes the
        # reference comparison use the same density policy as the model.
        density = np.full(len(native.position), self.estimator.rho0_kgm3, dtype=np.float64)
        controlled = F3CurrentFrame(
            native.position,
            native.velocity,
            native.mass,
            density,
            native.valid,
            frame_index=native.frame_index,
            time_s=native.time_s,
            native_indices=native.native_indices,
        )
        field = from_reference_frame(
            controlled,
            source_semantics="reference_control_support_only_v1",
            density_semantics="reference_rho0_constant_public_v1",
        )
        self._cache[index] = field
        return field

    def field_at(self, interval_index: int, time_s: float):
        _check_interval(self.times, interval_index, time_s)
        return self.frame(int(interval_index))

    def future(self, *_args, **_kwargs):
        raise PermissionError("reference control provider has no implicit future access")

    def close(self):
        self.reference.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


def _quantiles(values: np.ndarray) -> dict[str, Any]:
    values = np.asarray(values, dtype=np.float64)
    values = values[np.isfinite(values)]
    if not len(values):
        return {"count": 0, "p50": None, "p90": None, "p95": None, "p99": None}
    q = np.quantile(values, [0.50, 0.90, 0.95, 0.99])
    return {"count": int(len(values)), "p50": float(q[0]), "p90": float(q[1]),
            "p95": float(q[2]), "p99": float(q[3])}


def _frame_record(state: dict[str, np.ndarray], result, time_s: float) -> dict[str, Any]:
    return {
        "time": float(time_s),
        "position": np.asarray(state["position"], dtype=np.float64).copy(),
        "reliable": np.asarray(state["reliable"], dtype=bool).copy(),
        "permanent_unknown": np.asarray(state["permanent_unknown"], dtype=bool).copy(),
        "first_passage": np.asarray(state["first_passage"], dtype=np.float64).copy(),
        "return_time": np.asarray(state["return_time"], dtype=np.float64).copy(),
        "residence_opposite": np.asarray(state["residence_opposite"], dtype=np.float64).copy(),
        "returned": np.asarray(state["returned"], dtype=bool).copy(),
        "support_count": np.asarray(result.support_count, dtype=np.int64).copy(),
        "effective_sample_size": np.asarray(result.effective_sample_size, dtype=np.float64).copy(),
        "geometry_rank": np.asarray(result.geometry_rank, dtype=np.int8).copy(),
        "condition_number": np.asarray(result.condition_number, dtype=np.float64).copy(),
        "reconstruction_error_mps": np.asarray(result.reconstruction_error_mps, dtype=np.float64).copy(),
        "candidate_count": np.asarray(result.candidate_count, dtype=np.int64).copy(),
        "wall_rejected_count": np.asarray(result.wall_rejected_count, dtype=np.int64).copy(),
        "old_gate_pass": np.asarray(result.old_gate_pass, dtype=bool).copy(),
        "candidate_support_pass": np.asarray(result.candidate_support_pass, dtype=bool).copy(),
        "failure_reason": np.asarray([str(v) for v in result.failure_reason], dtype=object),
    }


def _write_trace(path: Path, records: list[dict[str, Any]], initial: np.ndarray,
                 labels: np.ndarray, binding: Mapping[str, Any], seed_hash: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    nframes = len(records)
    nseed = len(initial)
    string_dtype = h5py.string_dtype(encoding="utf-8")
    with h5py.File(path, "w") as handle:
        handle.attrs.update(
            schema_version=1,
            trace_schema=TRACE_SCHEMA,
            backend=BACKEND,
            qualification_claim="none",
            material_reliability="not_established",
            binding_json=_canonical(binding),
            seed_hash=seed_hash,
            seed_count=nseed,
        )
        handle.create_dataset("time", data=np.asarray([row["time"] for row in records], dtype=np.float64))
        handle.create_dataset("seed_position", data=np.asarray(initial, dtype=np.float64))
        handle.create_dataset("source_label", data=np.asarray(labels, dtype=np.int8))
        for name, dtype in (
            ("position", "f8"), ("first_passage", "f8"), ("return_time", "f8"),
            ("residence_opposite", "f8"), ("effective_sample_size", "f8"),
            ("condition_number", "f8"), ("reconstruction_error_mps", "f8"),
        ):
            handle.create_dataset(name, data=np.asarray([row[name] for row in records], dtype=dtype))
        for name, dtype in (
            ("reliable", "?"), ("permanent_unknown", "?"), ("returned", "?"),
            ("old_gate_pass", "?"), ("candidate_support_pass", "?"),
            ("support_count", "i8"), ("geometry_rank", "i1"),
            ("candidate_count", "i8"), ("wall_rejected_count", "i8"),
        ):
            handle.create_dataset(name, data=np.asarray([row[name] for row in records], dtype=dtype))
        failure = handle.create_dataset("failure_reason", shape=(nframes, nseed), dtype=string_dtype)
        failure[...] = np.asarray([row["failure_reason"] for row in records], dtype=object)
        handle.flush()


def _source_rows(records: list[dict[str, Any]], labels: np.ndarray) -> list[dict[str, Any]]:
    final = records[-1]
    reliable_history = np.asarray([row["reliable"] for row in records], dtype=bool)
    unknown_history = ~reliable_history
    nseed = len(labels)
    rows = []
    for source in sorted(np.unique(labels).tolist()):
        select = labels == source
        source_count = int(np.count_nonzero(select))
        final_unknown = select & ~final["reliable"]
        full_path = np.all(reliable_history[:, select], axis=0)
        first_failure = np.full(nseed, -1, dtype=np.int64)
        for seed in np.flatnonzero(np.any(unknown_history[:, select], axis=0)):
            global_seed = np.flatnonzero(select)[seed]
            first_failure[global_seed] = int(np.flatnonzero(unknown_history[:, global_seed])[0])
        first = final["first_passage"]
        returned = final["return_time"]
        residence = final["residence_opposite"]
        first_select = select & np.isfinite(first)
        return_select = select & np.isfinite(returned)
        failure_indices = first_failure[select]
        rows.append({
            "source": int(source),
            "seed_count": source_count,
            "initial_mass_fraction": float(source_count / nseed),
            "unknown_fraction_final": float(np.count_nonzero(final_unknown) / source_count),
            "common_reliable_path_fraction": float(np.count_nonzero(full_path) / source_count),
            "observed_first_passage_fraction": float(np.count_nonzero(first_select) / source_count),
            "observed_return_fraction": float(np.count_nonzero(return_select) / source_count),
            "first_failure_frame": int(np.min(failure_indices[failure_indices >= 0]))
            if np.any(failure_indices >= 0) else None,
            "first_failure_time_s": float(records[int(np.min(failure_indices[failure_indices >= 0]))]["time"])
            if np.any(failure_indices >= 0) else None,
            "first_passage_time_quantiles_s": _quantiles(first[select]),
            "return_time_quantiles_s": _quantiles(returned[select]),
            "residence_opposite_quantiles_s_lower_bound": _quantiles(residence[select]),
            "residence_censored_fraction": float(np.count_nonzero(final_unknown) / source_count),
        })
    return rows


def run_material_trace(source: str | Path, output: str | Path, *, role: str,
                       rho0_kgm3: float, dp_m: float, seeds: np.ndarray,
                       intervals: int = 20, substeps: int = 1,
                       walls: np.ndarray | None = None) -> dict[str, Any]:
    """Run a bounded causal model/reference material trace and score events."""
    started = time.monotonic()
    source = Path(source).resolve()
    output = Path(output).resolve()
    seeds = np.asarray(seeds, dtype=np.float64)
    if seeds.ndim != 2 or seeds.shape[1:] != (3,) or len(seeds) == 0 or not np.isfinite(seeds).all():
        raise ValueError("seeds must be a nonempty finite [N,3] array")
    if role == MODEL_ROLE:
        provider = ModelRho0CurrentProvider(source, rho0_kgm3=rho0_kgm3)
    elif role == REFERENCE_ROLE:
        provider = ReferenceRho0CurrentProvider(source, rho0_kgm3=rho0_kgm3)
    else:
        raise ValueError(f"role must be {MODEL_ROLE!r} or {REFERENCE_ROLE!r}")
    intervals = int(intervals)
    substeps = int(substeps)
    if intervals < 1 or intervals >= provider.frame_count:
        provider.close()
        raise ValueError("intervals must select at least one and fewer than all source intervals")
    if substeps < 1:
        provider.close()
        raise ValueError("substeps must be positive")
    if walls is None:
        walls = f3_walls()
    walls = np.asarray(walls, dtype=np.float64)
    if walls.ndim != 3 or walls.shape[1:] != (3, 3) or not np.isfinite(walls).all():
        provider.close()
        raise ValueError("walls must be finite [M,3,3]")
    labels = source_labels(seeds)
    seed_hash = _array_hash(seeds, labels)
    tracer = F3NativeVolumeMLS(h_from_dp(dp_m))
    diagnostics = {"stage_failure_counts": Counter()}
    try:
        times = np.asarray(provider.times[: intervals + 1], dtype=np.float64)
        initial_result = tracer.reconstruct(seeds, provider.field_at(0, float(times[0])), walls)
        state = _new_state(seeds, labels)
        state["failure_reason"] = np.asarray(initial_result.failure_reason, dtype=object)
        state["reliable"] = np.asarray(initial_result.reliable, dtype=bool)
        state["permanent_unknown"] = ~state["reliable"]
        records = [_frame_record(state, initial_result, float(times[0]))]
        for interval in range(intervals):
            t0, t1 = float(times[interval]), float(times[interval + 1])
            dt = (t1 - t0) / substeps
            for step in range(substeps):
                segment_time = t0 + step * dt
                result = _advance_rk4(
                    state, tracer, provider, walls, interval, segment_time, dt, diagnostics,
                )
                frame_time = t1 if step == substeps - 1 else segment_time + dt
                records.append(_frame_record(state, result, frame_time))
        binding = {
            **provider.binding,
            "trace_schema": TRACE_SCHEMA,
            "dp_m": float(dp_m),
            "h_m": float(tracer.h_m),
            "substeps_per_saved_interval": substeps,
            "intervals_requested": intervals,
            "time_start_s": float(records[0]["time"]),
            "time_end_s": float(records[-1]["time"]),
            "seed_hash": seed_hash,
            "event_definition": {
                "source_label": "initial_x_ge_0",
                "event_plane": "x=0",
                "first_passage": "first usable crossing to opposite x side",
                "return": "first later usable crossing back to origin side",
                "residence": "integrated opposite-side time over usable segments",
            },
            "support_reliability": "native-volume MLS numerical support only; material error uncalibrated",
        }
        _write_trace(output, records, seeds, labels, binding, seed_hash)
        reliable_history = np.asarray([row["reliable"] for row in records], dtype=bool)
        unknown_by_frame = np.mean(~reliable_history, axis=1)
        report = {
            "schema": SCHEMA,
            "trace_schema": TRACE_SCHEMA,
            "backend": BACKEND,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "completed",
            "qualification_claim": "none",
            "material_reliability": "not_established",
            "native_density_qualification": "not_applicable",
            "source": {
                "path": str(source),
                "sha256": sha256_file(source),
                "role": role,
                "future_state_inputs": False,
                "frames_registered": int(provider.frame_count),
            },
            "output_trace_h5": str(output),
            "trace_h5_sha256": sha256_file(output),
            "binding": binding,
            "implementation": _implementation_binding(),
            "density_policy": provider.estimator.binding,
            "seed_count": int(len(seeds)),
            "seed_hash": seed_hash,
            "source_rows": _source_rows(records, labels),
            "unknown_fraction_max": float(np.max(unknown_by_frame)),
            "unknown_fraction_final": float(unknown_by_frame[-1]),
            "unknown_fraction_by_frame": {
                "time_s": [float(row["time"]) for row in records],
                "fraction": unknown_by_frame.tolist(),
            },
            "common_reliable_path_fraction": float(np.mean(np.all(reliable_history, axis=0))),
            "mass_closure": {
                "seed_weight_definition": "uniform 1/N independent tracer weights",
                "closed": True,
                "closure_error": 0.0,
                "native_support_mass_used_for_weight": True,
            },
            "diagnostics": {
                "stage_failure_counts": dict(diagnostics["stage_failure_counts"]),
                "loaded_frame_indices": [int(v) for v in provider.loaded_indices],
                "peak_rss_kib": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
                "elapsed_seconds": float(time.monotonic() - started),
                "cpu_seconds": float(resource.getrusage(resource.RUSAGE_SELF).ru_utime
                                      + resource.getrusage(resource.RUSAGE_SELF).ru_stime),
            },
        }
        return report
    finally:
        provider.close()


def _load_seeds(path: str | None) -> np.ndarray:
    if path is None:
        # Small, reproducible seeds close to x=0 expose event scoring without
        # treating source IDs as tracer identities.
        return np.asarray([
            [-0.0010, -0.010, 0.040], [-0.0005, 0.010, 0.045],
            [0.0005, -0.010, 0.050], [0.0010, 0.010, 0.055],
        ], dtype=np.float64)
    value = np.load(path, allow_pickle=False)
    return np.asarray(value, dtype=np.float64)


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
    args = parser.parse_args()
    report = run_material_trace(
        args.source, args.output, role=args.role, rho0_kgm3=args.rho0_kgm3,
        dp_m=args.dp_m, seeds=_load_seeds(args.seeds), intervals=args.intervals,
        substeps=args.substeps,
    )
    report_path = Path(args.report).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "schema": report["schema"], "role": report["source"]["role"],
        "seed_count": report["seed_count"], "intervals": report["binding"]["intervals_requested"],
        "unknown_final": report["unknown_fraction_final"],
        "common_path": report["common_reliable_path_fraction"],
        "trace_h5": report["output_trace_h5"], "report": str(report_path),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
