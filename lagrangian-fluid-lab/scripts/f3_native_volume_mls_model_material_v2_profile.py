"""Synthetic-only phase profiler for the streaming F3 material evaluator v2.

The command manufactures its own temporary State HDF5 and seed cloud.  It
cannot accept a source-file path, so it cannot accidentally profile production
data.  A one-minute load gate prevents even this diagnostic workload from
starting when the host is already oversubscribed.  Instrumentation wraps the
existing implementation and does not modify its numerical return values.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import tempfile
import time
from unittest.mock import patch

import h5py
import numpy as np
import scipy

from scripts import f3_native_volume_mls_model_material_v2 as material


SCHEMA = "core.material.f3.native_volume_mls.model_material_profile.v2"
PROFILE_KIND = "synthetic_only_no_qualification_credit"
SYNTHETIC_SEED = 20260926
MAX_SYNTHETIC_SEEDS = 4096
MAX_SYNTHETIC_PARTICLES = 8192
MAX_SYNTHETIC_INTERVALS = 20
MAX_SYNTHETIC_SUBSTEPS = 4


class ProfileDeferred(RuntimeError):
    """The synthetic profiler declined to add work to an overloaded host."""


def _cpu_capacity() -> int:
    if hasattr(os, "sched_getaffinity"):
        return max(1, len(os.sched_getaffinity(0)))
    return max(1, os.cpu_count() or 1)


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def check_load_gate(load_one_minute: float, cpu_capacity: int) -> None:
    """Refuse to add profiling work above the process-visible CPU capacity."""
    if not np.isfinite(load_one_minute) or load_one_minute < 0:
        raise ValueError("one-minute load must be finite and nonnegative")
    if isinstance(cpu_capacity, bool) or not isinstance(cpu_capacity, int) or cpu_capacity < 1:
        raise ValueError("CPU capacity must be a positive integer")
    if load_one_minute > cpu_capacity:
        raise ProfileDeferred(
            f"synthetic profile deferred: 1-minute load {load_one_minute:.3f} "
            f"exceeds process-visible CPU capacity {cpu_capacity}"
        )


def _synthetic_source(path: Path, *, particle_count: int, intervals: int,
                      dp_m: float, role: str) -> np.ndarray:
    if particle_count < 8:
        raise ValueError("particle_count must be at least 8 for a useful synthetic profile")
    if intervals < 1:
        raise ValueError("intervals must be positive")
    rng = np.random.default_rng(SYNTHETIC_SEED)
    low = np.asarray([-0.45, -0.09, 0.0], dtype=np.float64)
    size = np.asarray([0.9, 0.18, 0.09], dtype=np.float64)
    high = low + size
    base_position = rng.uniform(low, high, size=(particle_count, 3)).astype(np.float32)
    velocity = rng.normal(0.0, 0.01, size=(particle_count, 3)).astype(np.float32)
    times = np.arange(intervals + 1, dtype=np.float64) * 0.01
    positions = np.stack([
        base_position + np.float32(time_s) * velocity for time_s in times
    ])
    velocities = np.broadcast_to(velocity, positions.shape).copy()
    particle_id = np.arange(particle_count, dtype=np.int64)
    particle_zone = np.zeros(particle_count, dtype=np.int64)
    masses = np.full(particle_count, 1000.0 * dp_m**3, dtype=np.float64)
    valid = np.ones((intervals + 1, particle_count), dtype=bool)
    particle_type = np.full(particle_count, 3, dtype=np.int8)
    density = np.full((intervals + 1, particle_count), 1000.0, dtype=np.float32)
    mass_dataset = (masses if role == material.MODEL_ROLE else
                    np.broadcast_to(masses, (intervals + 1, particle_count)).copy())
    type_dataset = (particle_type if role == material.MODEL_ROLE else
                    np.broadcast_to(particle_type, (intervals + 1, particle_count)).copy())

    with h5py.File(path, "x") as handle:
        handle.attrs.update(
            schema_version=1,
            state_schema="core.state.native_velocity.v1",
            velocity_semantics="native saved numerical velocity",
            future_state_inputs=False,
            autonomous_prediction=True,
            identity_semantics="particle_zone,particle_id",
            synthetic_profile=True,
        )
        handle["time"] = times
        handle["position"] = positions
        handle["velocity"] = velocities
        handle["particle_id"] = particle_id
        handle["particle_zone"] = particle_zone
        handle["mass"] = mass_dataset
        handle["valid"] = valid
        handle["type"] = type_dataset
        handle["density"] = density

    return times


def _timing_bucket() -> dict:
    return {
        "initial_reconstruct_seconds": 0.0,
        "initial_field_seconds": 0.0,
        "initial_field_calls": 0,
        "provider_init_seconds": 0.0,
        "reconstruct_seconds": 0.0,
        "reconstruct_calls": 0,
        "field_seconds": 0.0,
        "field_calls": 0,
        "advance_seconds": 0.0,
        "advance_calls": 0,
        "append_seconds": 0.0,
        "append_calls": 0,
        "trace_create_seconds": 0.0,
        "recovery_validation_seconds": 0.0,
        "report_seconds": 0.0,
        "sha256_seconds": 0.0,
        "active_interval": None,
        "intervals": {},
    }


def _interval(bucket: dict, index: int) -> dict:
    return bucket["intervals"].setdefault(str(int(index)), {
        "advance_seconds": 0.0,
        "reconstruct_seconds": 0.0,
        "reconstruct_calls": 0,
        "field_seconds": 0.0,
        "field_calls": 0,
        "append_seconds": 0.0,
        "append_calls": 0,
    })


def _synthetic_seeds(seed_count: int, dp_m: float) -> np.ndarray:
    if isinstance(seed_count, bool) or not isinstance(seed_count, int) or seed_count < 1:
        raise ValueError("seed_count must be a positive integer")
    rng = np.random.default_rng(SYNTHETIC_SEED + 1)
    low = np.asarray([-0.45, -0.09, 0.0], dtype=np.float64)
    high = low + np.asarray([0.9, 0.18, 0.09], dtype=np.float64)
    margin = max(2.0 * material.h_from_dp(dp_m), 1.0e-6)
    return rng.uniform(low + margin, high - margin, size=(seed_count, 3))


def run_synthetic_profile(*, seed_count: int = 512, particle_count: int = 4096,
                          intervals: int = 20, substeps: int = 1,
                          role: str = material.MODEL_ROLE,
                          rho0_kgm3: float = 1000.0, dp_m: float = 0.0075) -> dict:
    """Run bounded v2 material timing against a generated temporary HDF5."""
    if role not in {material.MODEL_ROLE, material.REFERENCE_ROLE}:
        raise ValueError("role must select the model or reference provider")
    if isinstance(substeps, bool) or not isinstance(substeps, int) or substeps < 1:
        raise ValueError("substeps must be a positive integer")
    if isinstance(intervals, bool) or not isinstance(intervals, int) or intervals < 1:
        raise ValueError("intervals must be a positive integer")
    if seed_count > MAX_SYNTHETIC_SEEDS:
        raise ValueError(f"seed_count exceeds the fixed {MAX_SYNTHETIC_SEEDS} limit")
    if particle_count > MAX_SYNTHETIC_PARTICLES:
        raise ValueError(f"particle_count exceeds the fixed {MAX_SYNTHETIC_PARTICLES} limit")
    if intervals > MAX_SYNTHETIC_INTERVALS:
        raise ValueError(f"intervals exceeds the fixed {MAX_SYNTHETIC_INTERVALS} limit")
    if substeps > MAX_SYNTHETIC_SUBSTEPS:
        raise ValueError(f"substeps exceeds the fixed {MAX_SYNTHETIC_SUBSTEPS} limit")
    material.h_from_dp(dp_m)

    cpu_capacity = _cpu_capacity()
    try:
        load_one = float(os.getloadavg()[0])
    except (AttributeError, OSError) as exc:
        raise ProfileDeferred("cannot inspect host load; refusing synthetic profile") from exc
    check_load_gate(load_one, cpu_capacity)

    seeds = _synthetic_seeds(seed_count, dp_m)
    bucket = _timing_bucket()

    model_field = material.v1.ModelRho0CurrentProvider.field_at
    reference_field = material.v1.ReferenceRho0CurrentProvider.field_at
    model_init = material.v1.ModelRho0CurrentProvider.__init__
    reference_init = material.v1.ReferenceRho0CurrentProvider.__init__
    reconstruct = material.F3NativeVolumeMLS.reconstruct
    advance = material._advance_rk4_with_first_failure
    append = material._append_row
    trace_create = material._create_trace
    recovery = material._validate_and_recover_tail
    report = material._report
    sha256 = material._sha256_file

    def timed_reconstruct(self, query, frame, walls):
        started = time.perf_counter()
        result = reconstruct(self, query, frame, walls)
        elapsed = time.perf_counter() - started
        bucket["reconstruct_seconds"] += elapsed
        bucket["reconstruct_calls"] += 1
        active = bucket["active_interval"]
        if active is None:
            bucket["initial_reconstruct_seconds"] += elapsed
        else:
            row = _interval(bucket, active)
            row["reconstruct_seconds"] += elapsed
            row["reconstruct_calls"] += 1
        return result

    def timed_field(original):
        def wrapper(self, interval_index, time_s):
            started = time.perf_counter()
            result = original(self, interval_index, time_s)
            elapsed = time.perf_counter() - started
            bucket["field_seconds"] += elapsed
            bucket["field_calls"] += 1
            active = bucket["active_interval"]
            if active is None:
                bucket["initial_field_seconds"] += elapsed
                bucket["initial_field_calls"] += 1
            else:
                row = _interval(bucket, active)
                row["field_seconds"] += elapsed
                row["field_calls"] += 1
            return result
        return wrapper

    def timed_init(original):
        def wrapper(self, *args, **kwargs):
            started = time.perf_counter()
            try:
                return original(self, *args, **kwargs)
            finally:
                bucket["provider_init_seconds"] += time.perf_counter() - started
        return wrapper

    def timed_advance(state, tracer, provider, walls, interval_index,
                      segment_time, dt, diagnostics):
        bucket["active_interval"] = int(interval_index)
        started = time.perf_counter()
        try:
            return advance(state, tracer, provider, walls, interval_index,
                           segment_time, dt, diagnostics)
        finally:
            elapsed = time.perf_counter() - started
            bucket["advance_seconds"] += elapsed
            bucket["advance_calls"] += 1
            _interval(bucket, interval_index)["advance_seconds"] += elapsed
            bucket["active_interval"] = None

    def timed_append(handle, row, state, step_index, diagnostics):
        started = time.perf_counter()
        try:
            return append(handle, row, state, step_index, diagnostics)
        finally:
            elapsed = time.perf_counter() - started
            bucket["append_seconds"] += elapsed
            bucket["append_calls"] += 1
            if step_index >= 0:
                interval_index = int(step_index) // substeps
                entry = _interval(bucket, interval_index)
                entry["append_seconds"] += elapsed
                entry["append_calls"] += 1

    def timed_call(name, original):
        def wrapper(*args, **kwargs):
            started = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                bucket[name] += time.perf_counter() - started
        return wrapper

    with tempfile.TemporaryDirectory(prefix="f3-material-v2-synthetic-profile-") as temp:
        temp_path = Path(temp)
        source = temp_path / "synthetic-state.h5"
        output = temp_path / "trace.h5"
        times = _synthetic_source(source, particle_count=particle_count,
                                  intervals=intervals, dp_m=dp_m, role=role)
        walls = material.f3_walls()
        with ExitStack() as stack:
            stack.enter_context(patch.object(material.F3NativeVolumeMLS,
                                              "reconstruct", timed_reconstruct))
            stack.enter_context(patch.object(material.v1.ModelRho0CurrentProvider,
                                              "field_at", timed_field(model_field)))
            stack.enter_context(patch.object(material.v1.ReferenceRho0CurrentProvider,
                                              "field_at", timed_field(reference_field)))
            stack.enter_context(patch.object(material.v1.ModelRho0CurrentProvider,
                                              "__init__", timed_init(model_init)))
            stack.enter_context(patch.object(material.v1.ReferenceRho0CurrentProvider,
                                              "__init__", timed_init(reference_init)))
            stack.enter_context(patch.object(material, "_advance_rk4_with_first_failure",
                                              timed_advance))
            stack.enter_context(patch.object(material, "_append_row", timed_append))
            stack.enter_context(patch.object(material, "_create_trace",
                                              timed_call("trace_create_seconds", trace_create)))
            stack.enter_context(patch.object(material, "_validate_and_recover_tail",
                                              timed_call("recovery_validation_seconds", recovery)))
            stack.enter_context(patch.object(material, "_report",
                                              timed_call("report_seconds", report)))
            stack.enter_context(patch.object(material, "_sha256_file",
                                              timed_call("sha256_seconds", sha256)))
            process_started = time.process_time()
            wall_started = time.perf_counter()
            result = material.run_material_trace(
                source, output, role=role, rho0_kgm3=rho0_kgm3, dp_m=dp_m,
                seeds=seeds, intervals=intervals, substeps=substeps, walls=walls,
            )
            elapsed_wall = time.perf_counter() - wall_started
            elapsed_cpu = time.process_time() - process_started
        trace_sha256 = result["trace_h5_sha256"]
        source_sha256 = result["source"]["sha256"]

    interval_rows = []
    for index in range(intervals):
        row = bucket["intervals"].get(str(index), {})
        stage_reconstruction = float(row.get("reconstruct_seconds", 0.0))
        field_read = float(row.get("field_seconds", 0.0))
        advance_wall = float(row.get("advance_seconds", 0.0))
        interval_rows.append({
            "interval_index": index,
            "rk4_wall_seconds": advance_wall,
            "mls_reconstruct_seconds": stage_reconstruction,
            "provider_field_seconds": field_read,
            "rk4_unattributed_seconds": max(0.0, advance_wall - stage_reconstruction - field_read),
            "append_seconds": float(row.get("append_seconds", 0.0)),
            "reconstruct_calls": int(row.get("reconstruct_calls", 0)),
            "field_calls": int(row.get("field_calls", 0)),
            "append_calls": int(row.get("append_calls", 0)),
        })

    return {
        "schema": SCHEMA,
        "profile_kind": PROFILE_KIND,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "qualification_claim": "none",
        "material_reliability": "not_established",
        "configuration": {
            "seed_count": int(seed_count),
            "particle_count": int(particle_count),
            "intervals": int(intervals),
            "substeps_per_interval": int(substeps),
            "role": role,
            "rho0_kgm3": float(rho0_kgm3),
            "dp_m": float(dp_m),
            "synthetic_rng_seed": SYNTHETIC_SEED,
            "time_step_s": 0.01,
            "source_frames": len(times),
        },
        "implementation": {
            "module": str(Path(material.__file__).resolve()),
            "module_sha256": _sha256_file(Path(material.__file__)),
            "provider_module": str(Path(material.v1.__file__).resolve()),
            "provider_module_sha256": _sha256_file(Path(material.v1.__file__)),
            "profile_wrapper": str(Path(__file__).resolve()),
            "profile_wrapper_sha256": _sha256_file(Path(__file__)),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "h5py": h5py.__version__,
            "python": platform.python_version(),
        },
        "synthetic_artifacts": {
            "source_sha256": source_sha256,
            "trace_sha256": trace_sha256,
            "temporary_files_removed": True,
        },
        "timing": {
            "wall_seconds": float(elapsed_wall),
            "cpu_seconds": float(elapsed_cpu),
            "peak_rss_kib": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
            "phase_totals": {
                name: (int(value) if name.endswith("calls") else float(value))
                for name, value in bucket.items()
                if name.endswith("_seconds") or name.endswith("_calls")
            },
            "rk4_overhead_excludes_nested_mls_and_provider": True,
            "intervals": interval_rows,
        },
        "scientific_summary": {
            "unknown_fraction_final": result["unknown_fraction_final"],
            "common_reliable_path_fraction": result["common_reliable_path_fraction"],
            "stage_failure_counts": result["diagnostics"]["stage_failure_counts"],
        },
        "environment": {
            "visible_cpu_capacity": cpu_capacity,
            "one_minute_load_at_start": load_one,
            "thread_limits": {
                name: os.environ.get(name)
                for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                             "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")
            },
        },
        "limitations": [
            "synthetic random support cloud is not a production F3 particle distribution",
            "timings characterize this host and code path, not a root resource decision",
            "BLAS/OpenMP thread limits are reported, not mutated by importing this module",
            "no production HDF5, qualification evidence, solver, worker, GPU or queue was used",
        ],
    }


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-count", type=int, default=512)
    parser.add_argument("--particle-count", type=int, default=4096)
    parser.add_argument("--intervals", type=int, default=20)
    parser.add_argument("--substeps", type=int, default=1)
    parser.add_argument("--role", choices=(material.MODEL_ROLE, material.REFERENCE_ROLE),
                        default=material.MODEL_ROLE)
    parser.add_argument("--rho0-kgm3", type=float, default=1000.0)
    parser.add_argument("--dp-m", type=float, default=0.0075)
    parser.add_argument("--report", type=Path,
                        help="optional new JSON output path; existing files are never replaced")
    args = parser.parse_args()
    if args.report is not None:
        if args.report.exists() or args.report.is_symlink():
            raise FileExistsError(f"refusing to overwrite existing report: {args.report}")
        if not args.report.parent.is_dir():
            raise FileNotFoundError(f"report parent directory does not exist: {args.report.parent}")
    try:
        profile = run_synthetic_profile(
            seed_count=args.seed_count, particle_count=args.particle_count,
            intervals=args.intervals, substeps=args.substeps, role=args.role,
            rho0_kgm3=args.rho0_kgm3, dp_m=args.dp_m,
        )
    except ProfileDeferred as exc:
        print(json.dumps({
            "schema": SCHEMA,
            "status": "deferred_resource_gate",
            "profile_started": False,
            "reason": str(exc),
        }, sort_keys=True))
        return 2
    payload = json.dumps(profile, indent=2, sort_keys=True) + "\n"
    if args.report is None:
        print(payload, end="")
    else:
        with args.report.open("x", encoding="utf-8") as stream:
            stream.write(payload)
        print(json.dumps({
            "schema": SCHEMA,
            "status": "completed_synthetic_only",
            "report": str(args.report.resolve()),
            "wall_seconds": profile["timing"]["wall_seconds"],
            "cpu_seconds": profile["timing"]["cpu_seconds"],
        }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
