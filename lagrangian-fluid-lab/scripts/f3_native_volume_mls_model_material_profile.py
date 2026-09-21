"""Profile wrapper for the v1 model-material evaluator.

This module deliberately leaves ``f3_native_volume_mls_model_material``
unchanged.  It wraps only provider reads, MLS reconstruction calls and RK4
interval calls to obtain a bounded 512-seed timing profile.  The wrapped
functions return the original values, so the trace numerical result remains
the v1 rho0/current-frame implementation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from scripts import f3_native_volume_mls_model_material as material


SCHEMA = "core.material.f3.native_volume_mls.model_material_profile.v1"


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_seeds(path: str) -> np.ndarray:
    value = np.load(path, allow_pickle=False)
    seeds = np.asarray(value, dtype=np.float64)
    if seeds.ndim != 2 or seeds.shape[1:] != (3,) or len(seeds) == 0:
        raise ValueError("seed file must contain a nonempty [N,3] array")
    return seeds


def run_profile(source: str | Path, output: str | Path, report: str | Path, *,
                role: str, rho0_kgm3: float, dp_m: float, seeds: np.ndarray,
                intervals: int, substeps: int) -> dict:
    stats = {
        "interval_wall_seconds": {},
        "interval_reconstruct_seconds": {},
        "interval_field_seconds": {},
        "interval_field_calls": {},
        "initial_reconstruct_seconds": 0.0,
        "reconstruct_calls": 0,
        "field_calls": 0,
        "field_seconds": 0.0,
        "reconstruct_seconds": 0.0,
        "advance_calls": 0,
        "active_interval": None,
    }

    def add(mapping, key, value):
        key = str(key)
        mapping[key] = float(mapping.get(key, 0.0) + value)

    original_advance = material._advance_rk4
    original_reconstruct = material.F3NativeVolumeMLS.reconstruct
    original_model_field = material.ModelRho0CurrentProvider.field_at
    original_reference_field = material.ReferenceRho0CurrentProvider.field_at

    def timed_reconstruct(self, query, frame, walls):
        started = time.perf_counter()
        result = original_reconstruct(self, query, frame, walls)
        elapsed = time.perf_counter() - started
        stats["reconstruct_calls"] += 1
        stats["reconstruct_seconds"] += elapsed
        interval = stats["active_interval"]
        if interval is None:
            stats["initial_reconstruct_seconds"] += elapsed
        else:
            add(stats["interval_reconstruct_seconds"], interval, elapsed)
        return result

    def timed_field(original):
        def wrapper(self, interval_index, time_s):
            started = time.perf_counter()
            result = original(self, interval_index, time_s)
            elapsed = time.perf_counter() - started
            stats["field_calls"] += 1
            stats["field_seconds"] += elapsed
            add(stats["interval_field_seconds"], interval_index, elapsed)
            stats["interval_field_calls"][str(interval_index)] = (
                int(stats["interval_field_calls"].get(str(interval_index), 0)) + 1
            )
            return result
        return wrapper

    def timed_advance(state, tracer, provider, walls, interval_index, segment_time, dt, diagnostics):
        stats["active_interval"] = int(interval_index)
        started = time.perf_counter()
        try:
            return original_advance(
                state, tracer, provider, walls, interval_index, segment_time, dt, diagnostics,
            )
        finally:
            elapsed = time.perf_counter() - started
            add(stats["interval_wall_seconds"], interval_index, elapsed)
            stats["advance_calls"] += 1
            stats["active_interval"] = None

    material.F3NativeVolumeMLS.reconstruct = timed_reconstruct
    material.ModelRho0CurrentProvider.field_at = timed_field(original_model_field)
    material.ReferenceRho0CurrentProvider.field_at = timed_field(original_reference_field)
    material._advance_rk4 = timed_advance
    try:
        result = material.run_material_trace(
            source, output, role=role, rho0_kgm3=rho0_kgm3, dp_m=dp_m,
            seeds=seeds, intervals=intervals, substeps=substeps,
        )
    finally:
        material.F3NativeVolumeMLS.reconstruct = original_reconstruct
        material.ModelRho0CurrentProvider.field_at = original_model_field
        material.ReferenceRho0CurrentProvider.field_at = original_reference_field
        material._advance_rk4 = original_advance

    interval_rows = []
    for index in range(int(intervals)):
        key = str(index)
        interval_rows.append({
            "interval_index": index,
            "wall_seconds": float(stats["interval_wall_seconds"].get(key, 0.0)),
            "reconstruct_seconds": float(stats["interval_reconstruct_seconds"].get(key, 0.0)),
            "field_seconds": float(stats["interval_field_seconds"].get(key, 0.0)),
            "field_calls": int(stats["interval_field_calls"].get(key, 0)),
        })
    result["profile"] = {
        "schema": SCHEMA,
        "wrapper": str(Path(__file__).resolve()),
        "wrapper_sha256": sha256_file(__file__),
        "numerical_entrypoint": str(Path(material.__file__).resolve()),
        "numerical_entrypoint_sha256": sha256_file(material.__file__),
        "method": "wall-clock instrumentation around existing provider/MLS/RK4 calls; no numerical mutation",
        "intervals": interval_rows,
        "phase_totals": {
            "initial_reconstruct_seconds": float(stats["initial_reconstruct_seconds"]),
            "advance_wall_seconds": float(sum(stats["interval_wall_seconds"].values())),
            "reconstruct_seconds": float(stats["reconstruct_seconds"]),
            "field_seconds": float(stats["field_seconds"]),
            "reconstruct_calls": int(stats["reconstruct_calls"]),
            "field_calls": int(stats["field_calls"]),
            "advance_calls": int(stats["advance_calls"]),
        },
        "resource": result["diagnostics"],
    }
    report_path = Path(report).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--role", choices=(material.MODEL_ROLE, material.REFERENCE_ROLE), required=True)
    parser.add_argument("--seeds", required=True)
    parser.add_argument("--rho0-kgm3", type=float, default=1000.0)
    parser.add_argument("--dp-m", type=float, default=0.0075)
    parser.add_argument("--intervals", type=int, default=20)
    parser.add_argument("--substeps", type=int, default=1)
    args = parser.parse_args()
    result = run_profile(
        args.source, args.output, args.report, role=args.role,
        rho0_kgm3=args.rho0_kgm3, dp_m=args.dp_m, seeds=_load_seeds(args.seeds),
        intervals=args.intervals, substeps=args.substeps,
    )
    print(json.dumps({
        "schema": result["schema"],
        "role": result["source"]["role"],
        "seed_count": result["seed_count"],
        "intervals": result["binding"]["intervals_requested"],
        "wall_seconds": result["diagnostics"]["elapsed_seconds"],
        "cpu_seconds": result["diagnostics"]["cpu_seconds"],
        "peak_rss_kib": result["diagnostics"]["peak_rss_kib"],
        "profile_report": str(Path(args.report).resolve()),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
