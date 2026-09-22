from __future__ import annotations

import hashlib
import json
import resource
import time
from pathlib import Path

import numpy as np

from scripts.core_material import (
    CurrentField,
    GATE,
    H2_NEIGHBOURS,
    MAXIMUM_SUPPORT_DISTANCE_M,
    NEIGHBOURS,
    _hash_array,
    digest,
    f3_walls,
)


def exact_velocity(points):
    """Smooth manufactured velocity with a wall-normal curvature term."""
    points = np.asarray(points, dtype=np.float64)
    x, y, z = points.T
    xn = x + 0.45
    return np.column_stack(
        (
            0.12 + 2.5 * xn + 900.0 * xn * xn + 180.0 * z * z + 80.0 * xn * z,
            -0.08 + 1.1 * y + 240.0 * xn * z + 70.0 * y * y,
            0.03 + 0.7 * z + 120.0 * xn * xn + 110.0 * y * z,
        )
    )


def main():
    started = time.monotonic()
    # A fixed 7.5 mm F3-like cloud, deliberately retained only in a local
    # near-wall slab so this is a diagnostic of support geometry, not a CFD run.
    axes = (
        np.arange(-0.4425, -0.33749, 0.0075),
        np.arange(-0.0825, 0.08251, 0.0075),
        np.arange(0.0075, 0.14251, 0.0075),
    )
    cloud = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)
    # Off-grid queries span the first 6.5 cm from the closed x wall and the
    # lower free-surface-adjacent slab.  They remain inside the static box.
    qaxes = (
        np.array([-0.43875, -0.43375, -0.42875, -0.41875, -0.39875]),
        np.array([-0.07125, -0.02625, 0.01875, 0.06375]),
        np.array([0.06125, 0.09125, 0.12125]),
    )
    query = np.stack(np.meshgrid(*qaxes, indexing="ij"), axis=-1).reshape(-1, 3)
    velocity = exact_velocity(cloud)
    truth = exact_velocity(query)
    walls = f3_walls()
    field = CurrentField(cloud, velocity)
    rows = []
    variants = (
        ("baseline24", "f3_ckdtree_visible_shepard_distance_v1", NEIGHBOURS, "local_residual"),
        ("h2_k48", "f3_ckdtree_visible_shepard_distance_k48_v1", H2_NEIGHBOURS, "local_residual"),
        ("h1_affine_bound", "f3_ckdtree_visible_shepard_query_error_bound_v1", NEIGHBOURS, "residual_plus_local_affine_query_bias"),
    )
    for variant, backend, neighbours, estimator in variants:
        interpolated, support, passed, diagnostics = field.sample(
            query,
            walls,
            neighbours=neighbours,
            gate=GATE,
            error_estimator=estimator,
            return_diagnostics=True,
        )
        actual_error = np.linalg.norm(interpolated - truth, axis=1)
        reconstruction = diagnostics["interpolation_reconstruction_error_mps"]
        estimated = diagnostics["estimated_interpolation_error_mps"]
        threshold = float(GATE["maximum_reconstruction_error_mps"])
        rows.append(
            {
                "variant": variant,
                "backend": backend,
                "error_estimator": estimator,
                "neighbours": neighbours,
                "query_count": len(query),
                "reliable_count": int(passed.sum()),
                "reliable_fraction": float(passed.mean()),
                "actual_error_max_mps": float(np.nanmax(actual_error)),
                "actual_error_p95_mps": float(np.nanpercentile(actual_error, 95)),
                "actual_error_mean_mps": float(np.nanmean(actual_error)),
                "diagnostic_reconstruction_max_mps": float(np.nanmax(reconstruction)),
                "diagnostic_reconstruction_p95_mps": float(np.nanpercentile(reconstruction, 95)),
                "diagnostic_reconstruction_mean_mps": float(np.nanmean(reconstruction)),
                "estimated_error_max_mps": float(np.nanmax(estimated)),
                "estimated_error_p95_mps": float(np.nanpercentile(estimated, 95)),
                "estimated_error_mean_mps": float(np.nanmean(estimated)),
                "actual_error_over_gate_fraction": float(np.mean(actual_error > threshold)),
                "diagnostic_gate_fail_fraction": float(np.mean(~passed)),
                "actual_bad_but_diagnostic_pass_fraction": float(np.mean((actual_error > threshold) & passed)),
                "actual_good_but_diagnostic_fail_fraction": float(np.mean((actual_error <= threshold) & ~passed)),
                "max_support_distance_m": float(np.nanmax(support)),
                "visible_neighbours_min": int(np.min(diagnostics["visible_neighbours"])),
                "visible_neighbours_max": int(np.max(diagnostics["visible_neighbours"])),
                "selected_visible_neighbours_min": int(np.min(diagnostics["selected_visible_neighbours"])),
                "selected_visible_neighbours_max": int(np.max(diagnostics["selected_visible_neighbours"])),
                "ess_p05": float(np.percentile(diagnostics["effective_sample_size"], 5)),
                "rank_min": int(np.min(diagnostics["geometry_rank"])),
                "anisotropy_p05": float(np.percentile(diagnostics["anisotropy"], 5)),
            }
        )
    payload = {
        "schema": "core.material.h2.manufactured.v1",
        "input_definition": {
            "cloud_hash": _hash_array(cloud),
            "query_hash": _hash_array(query),
            "velocity_hash": _hash_array(velocity),
            "truth_hash": _hash_array(truth),
            "walls_hash": _hash_array(walls),
            "cloud_shape": list(cloud.shape),
            "query_shape": list(query.shape),
            "field": "quadratic wall-normal x/z curvature plus y/z cross terms",
        },
        "gate": GATE,
        "support_distance_limit_m": MAXIMUM_SUPPORT_DISTANCE_M,
        "rows": rows,
        "execution": {
            "command": "PYTHONPATH=. .venv/bin/python /tmp/core_material_h2_manufactured.py",
            "device": "CPU",
            "elapsed_seconds": time.monotonic() - started,
            "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "gpu_started": False,
            "ledger_touched": False,
            "slot_acquired": False,
            "script_sha256": digest(Path(__file__)),
            "code_sha256": digest(Path("scripts/core_material.py")),
            "neighbor_code_sha256": digest(Path("scripts/f3_material_neighbors.py")),
            "passive_code_sha256": digest(Path("scripts/passive_tracers.py")),
        },
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
