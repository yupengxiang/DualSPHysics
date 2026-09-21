"""Bounded, recoverable high-seed F3 quadrature diagnostic.

This module is an explicitly versioned wrapper around the existing F3 native
volume MLS runner.  It adds one deterministic tensor-product midpoint rule
with 8192 geometric seeds (64 x 16 x 8), while preserving the registered F3
source box, half-space labels, finite-wall triangles, native mass semantics,
candidate reconstruction gates, and event definitions.  It is intended for a
short CPU profiling/canary run only.  It never changes the registered matrix,
historical artifacts, thresholds, scores, registry, or ledger, and every
result carries ``qualification_claim=none``.

The underlying runner already publishes an immutable checkpoint after each
committed frame.  The wrapper temporarily supplies the high-seed generator to
that runner, so the same crash-and-resume path can be exercised without
duplicating the integration implementation.  The companion receipt records
both code hashes and the high-seed geometry binding.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np


LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import f3_native_volume_mls_v2 as base  # noqa: E402


SCHEMA = "core.material.f3.native_volume_mls.high_seed_quadrature.v1"
QUALIFICATION_CLAIM = "none; bounded CPU high-seed diagnostic only"
HIGH_SEED_COUNT = 8192
HIGH_SEED_SHAPE = (64, 16, 8)


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False)


def _array_hash(*arrays: np.ndarray) -> str:
    digest = hashlib.sha256()
    for array in arrays:
        value = np.ascontiguousarray(np.asarray(array))
        digest.update(_canonical({"dtype": value.dtype.str,
                                  "shape": list(value.shape)}).encode())
        digest.update(value.tobytes())
    return digest.hexdigest()


def seeds_f3_high(count: int = HIGH_SEED_COUNT) -> np.ndarray:
    """Return the fixed 8192-point midpoint quadrature in the registered box."""
    count = int(count)
    if count != HIGH_SEED_COUNT:
        raise ValueError("high-seed diagnostic accepts exactly 8192 seeds")
    shape = HIGH_SEED_SHAPE
    axes = [low + (np.arange(n, dtype=np.float64) + 0.5) * size / n
            for low, size, n in zip(base.F3_SOURCE_LOW_M,
                                    base.F3_SOURCE_SIZE_M, shape)]
    points = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)
    points = np.ascontiguousarray(points, dtype=np.float64)
    if points.shape != (HIGH_SEED_COUNT, 3):
        raise AssertionError(f"unexpected high-seed shape: {points.shape}")
    if np.any(points < base.F3_SOURCE_LOW_M) or np.any(
            points >= base.F3_SOURCE_LOW_M + base.F3_SOURCE_SIZE_M):
        raise AssertionError("high-seed point escaped registered source box")
    return points


def high_seed_binding(count: int = HIGH_SEED_COUNT) -> dict[str, Any]:
    points = seeds_f3_high(count)
    labels = base.source_labels(points)
    return {
        "schema": SCHEMA,
        "qualification_claim": QUALIFICATION_CLAIM,
        "seed_count": int(len(points)),
        "seed_shape_xyz": list(HIGH_SEED_SHAPE),
        "seed_rule": "tensor_product_midpoint_uniform_volume_quadrature",
        "source_low_m": base.F3_SOURCE_LOW_M.tolist(),
        "source_size_m": base.F3_SOURCE_SIZE_M.tolist(),
        "source_label_semantics": "x < 0 => source 0; x >= 0 => source 1",
        "source_seed_counts": {
            "0": int(np.count_nonzero(labels == 0)),
            "1": int(np.count_nonzero(labels == 1)),
        },
        "source_geometry_sha256": _array_hash(
            base.F3_SOURCE_LOW_M, base.F3_SOURCE_SIZE_M,
            base.f3_walls(),
        ),
        "seed_points_sha256": _array_hash(points, labels),
        "semantics_inherited_from": {
            "runner": str(Path(base.__file__).resolve()),
            "runner_sha256": _sha256_file(base.__file__),
            "candidate_gate": dict(base.MLS_GATE),
            "original_f3_gate": dict(base.F3_ORIGINAL_GATE),
            "interpolation": False,
            "future_state": "forbidden",
            "event_definition": {
                "first_passage": "continuous crossing of x=0 into opposite source half",
                "return": "first later crossing back to seed origin half",
                "residence": "accepted segment time in opposite source half",
            },
        },
    }


def run_trace(source: str | Path, output: str | Path, prepared: str | Path, *,
              seeds: int = HIGH_SEED_COUNT, substeps: int = 4,
              stop_after: int = 4, dp_m: float | None = None,
              resume: bool = False, frame_index_map: str | Path | None = None,
              kill_after_h5_append: int | None = None,
              kill_after_generation: int | None = None) -> dict[str, Any]:
    """Run the bounded high-seed trace through the audited resumable runner."""
    binding = high_seed_binding(seeds)
    original = base.seeds_f3
    # ``audit_source`` performs an internal shape sanity check with the
    # registered 512-point rule before the trace asks for the requested seed
    # count.  Dispatch only the requested high count to this wrapper and keep
    # that preflight check on the original generator.
    def dispatch(count: int = 512) -> np.ndarray:
        if int(count) == int(seeds):
            return seeds_f3_high(count)
        return original(count)

    base.seeds_f3 = dispatch
    try:
        result = base.run_trace(
            source, output, prepared, seeds=seeds, substeps=substeps,
            stop_after=stop_after, dp_m=dp_m, resume=resume,
            frame_index_map=frame_index_map,
            kill_after_h5_append=kill_after_h5_append,
            kill_after_generation=kill_after_generation,
        )
    finally:
        base.seeds_f3 = original

    result["high_seed_quadrature"] = binding
    result["wrapper_code_sha256"] = _sha256_file(__file__)
    result["qualification_claim"] = QUALIFICATION_CLAIM
    receipt_path = Path(result["output"]["path"]).with_suffix(
        ".high-seed-receipt.json")
    receipt = {
        "schema": SCHEMA,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "completed",
        "qualification_claim": QUALIFICATION_CLAIM,
        "runner_result": result,
        "high_seed_quadrature": binding,
        "wrapper_code_sha256": _sha256_file(__file__),
    }
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8")
    result["high_seed_receipt"] = {
        "path": str(receipt_path),
        "sha256": _sha256_file(receipt_path),
    }
    return result


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", type=int, default=HIGH_SEED_COUNT)
    parser.add_argument("--substeps", type=int, default=4)
    parser.add_argument("--stop-after", type=int, default=4)
    parser.add_argument("--dp", type=float, default=None)
    parser.add_argument("--frame-index-map", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--kill-after-h5-append", type=int)
    parser.add_argument("--kill-after-generation", type=int)
    args = parser.parse_args()
    result = run_trace(
        args.source, args.output, args.prepared, seeds=args.seeds,
        substeps=args.substeps, stop_after=args.stop_after, dp_m=args.dp,
        frame_index_map=args.frame_index_map, resume=args.resume,
        kill_after_h5_append=args.kill_after_h5_append,
        kill_after_generation=args.kill_after_generation,
    )
    print(json.dumps({
        "schema": result["schema"],
        "status": result["status"],
        "qualification_claim": result["qualification_claim"],
        "seed_count": result["seed_count"],
        "committed_frame": result["source_window"]["last_frame"],
        "output": result["output"],
        "high_seed_receipt": result["high_seed_receipt"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
