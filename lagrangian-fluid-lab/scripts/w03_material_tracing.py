#!/usr/bin/env python3
"""W03 independent material-tracing audit."""

from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np

from passive_tracers import advect_hdf5, deterministic_seeds


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "v0.1-candidate"
REPORT = CAMPAIGN / "w03-material-tracing.json"
ARTIFACT = CAMPAIGN / "artifacts" / "w03"


def particle_endpoint(h5_path, indices):
    with h5py.File(h5_path, "r") as h5:
        return h5["position"][-1, indices], h5["valid"][-1, indices]


def endpoint_audit(h5_path, dp, maximum=256, frame_stride=1):
    seeds = deterministic_seeds(h5_path, maximum)
    traced = advect_hdf5(h5_path, seeds["position"], neighbours=24,
                         regularization=0.1 * dp, maximum_support_distance=1.75 * dp,
                         frame_stride=frame_stride)
    endpoint, valid = particle_endpoint(h5_path, seeds["indices"])
    common = traced["reliable"] & valid
    error = np.linalg.norm(traced["position"][-1] - endpoint, axis=1)
    support = traced["nearest_support_distance"]
    return seeds, traced, {
        "seed_count": len(seeds["indices"]), "reliable_endpoint_count": int(common.sum()),
        "reliable_fraction": float(common.mean()),
        "endpoint_error_over_dp": {
            "median": float(np.median(error[common])),
            "p95": float(np.quantile(error[common], 0.95)),
            "max": float(np.max(error[common])),
        },
        "nearest_support_distance_over_dp": {
            "median": float(np.median(support / dp)),
            "p95": float(np.quantile(support / dp, 0.95)),
        },
    }


def category(x):
    return np.where(x < 0.4, 0, np.where(x < 0.8, 1, 2))


def fractions(values):
    return np.bincount(values, minlength=3).astype(float) / max(1, len(values))


def transport_audit(h5_path, dp):
    seeds, traced, endpoint = endpoint_audit(h5_path, dp, maximum=10_000)
    particle_final, particle_valid = particle_endpoint(h5_path, seeds["indices"])
    reports = {}
    for source in sorted(int(value) for value in np.unique(seeds["source_mk"])):
        selected = (seeds["source_mk"] == source) & traced["reliable"] & particle_valid
        particle_distribution = fractions(category(particle_final[selected, 0]))
        tracer_distribution = fractions(category(traced["position"][-1, selected, 0]))
        reports[str(source)] = {
            "count": int(selected.sum()),
            "destinations": ["x_lt_0.4", "0.4_le_x_lt_0.8", "x_ge_0.8"],
            "sph_particle_fraction": particle_distribution.tolist(),
            "independent_tracer_fraction": tracer_distribution.tolist(),
            "total_variation_distance": float(0.5 * np.abs(particle_distribution - tracer_distribution).sum()),
        }
    endpoint["source_destination_comparison"] = reports
    return seeds, traced, endpoint


def save_trace(path, seeds, traced):
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, time=traced["time"], position=traced["position"],
                        reliable=traced["reliable"], particle_id=seeds["particle_id"],
                        particle_zone=seeds["particle_zone"], source_mk=seeds["source_mk"])


def main():
    inputs = {
        "shift_off": (CAMPAIGN / "data" / "w02" / "W02_shift_off.h5", 0.04),
        "shift_full": (CAMPAIGN / "data" / "w02" / "W02_shift_full.h5", 0.04),
    }
    endpoints = {}
    for name, (path, dp) in inputs.items():
        seeds, traced, report = endpoint_audit(path, dp)
        endpoints[name] = report
        save_trace(ARTIFACT / f"{name}.npz", seeds, traced)
    cadence = {}
    cadence_path = inputs["shift_off"][0]
    with h5py.File(cadence_path, "r") as h5:
        base_dt = float(np.median(np.diff(h5["time"][:])))
    for stride in (1, 2, 5, 10):
        _, _, audit = endpoint_audit(cadence_path, 0.04, frame_stride=stride)
        cadence[str(stride)] = {
            "nominal_output_dt_s": base_dt * stride,
            "endpoint_error_over_dp": audit["endpoint_error_over_dp"],
            "reliable_fraction": audit["reliable_fraction"],
        }
    f2_path = CAMPAIGN / "data" / "F2_two_source_layers.h5"
    seeds, traced, transport = transport_audit(f2_path, 0.04)
    save_trace(ARTIFACT / "two_source_transport.npz", seeds, traced)
    payload = {
        "schema_version": 1,
        "method": {
            "name": "independent passive tracer",
            "velocity_interpolation": "24-neighbour inverse-distance Shepard; no Idp lookup after t=0",
            "time_integration": "Heun / explicit trapezoidal",
            "support_rule": "unreliable if nearest source sample exceeds 1.75 dp at any substep",
            "important_non_claim": "This is an independent consistency check, not experimental ground truth.",
        },
        "fixed_resolution_endpoint_audit": endpoints,
        "output_cadence_sensitivity_shift_off": cadence,
        "two_source_material_transport": transport,
        "official_tracerparts_assessment": {
            "version": "5.4.266.02",
            "result": "not independent",
            "reason": "TracerParts selects existing simulated particles by Id/position/type and renders their tails; it does not inject separately integrated material tracers.",
        },
    }
    REPORT.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
