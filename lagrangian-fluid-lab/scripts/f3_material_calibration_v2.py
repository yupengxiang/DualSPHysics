"""Manufactured calibration for the prospective F3 material interpolator.

The original ``f3_material_calibration`` record is historical evidence for the
legacy interpolator.  This runner is deliberately separate: a new material
plan must prove the actual ``f3_material_neighbors`` backend on the four
registered affine cases before any CFD material result is accepted.

Running this module charges four material configurations.  Importing it and
using :func:`manufactured_trace` are CPU-only operations; no solver is
started by this module.
"""

from __future__ import annotations

import argparse
import json
import time

import h5py
import numpy as np

from scripts.f3_material_calibration import exact
from scripts.f3_material_labels import residence_times
from scripts.f3_material_neighbors import shepard_velocity_with_diagnostics
from scripts.l1r_continuation_evidence import LAB, OUT, ledger, resource_limits, write
from scripts.l1r_q2_mdbc_bridge import sha256
from scripts.passive_tracers import advect_hdf5, box_surface_triangles


PROGRAM_RELATIVE = "scripts/f3_material_calibration_v2.py"
INTERPOLATOR_RELATIVE = "scripts/f3_material_neighbors.py"
TRACER_RELATIVE = "scripts/passive_tracers.py"
TARGET_NAME = "F3-MATERIAL-AFFINE-CALIBRATION-material-neighbors-v1.json"
DATA_RELATIVE = "campaigns/l1-resume/data/f3-material-calibration-material-neighbors-v1"
CONFIGURATIONS = tuple(
    {"flow": flow, "dp_m": dp}
    for flow in ("shear", "rotation")
    for dp in (0.01, 0.006)
)


def seed_positions() -> np.ndarray:
    axes = [[-.021, -.007, .007, .021], [-.021, -.007, .007, .021],
            [.024, .036, .048, .060]]
    return np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)


def calibration_design() -> dict:
    seeds = seed_positions()
    return dict(
        rate_per_s=1., time_window_s=[0., .5], output_interval_s=.01,
        substeps=2, seeds=len(seeds), same_physical_seeds_across_resolutions=True,
        seed_positions_m=seeds.tolist(), neighbours=24, regularization_m=.004,
        maximum_support_distance_m=.03,
        acceptance=dict(maximum_path_error_m=.001,
                        maximum_residence_error_s=.01,
                        required_reliable_fraction=1.,
                        terminal_disagreement_fraction=0.),
    )


def manufactured_trace(source, seeds, walls):
    """Run one manufactured case with the hash-bound production backend."""
    return advect_hdf5(
        source, seeds, substeps_per_interval=2,
        barrier_provider=lambda h5, frame0, frame1, alpha: walls,
        maximum_support_distance=.03,
        support_gate={
            "minimum_effective_sample_size": 4.,
            "minimum_geometry_rank": 3,
            "minimum_anisotropy": .005,
            "maximum_reconstruction_error_mps": .05 * np.sqrt(9.81 * .09),
        },
        velocity_interpolator=shepard_velocity_with_diagnostics,
    )


def run():
    target = OUT / TARGET_NAME
    if target.exists():
        raise ValueError("calibration already registered; inspect without rerunning")
    ledger()
    if json.loads((OUT / "RESOURCE-LEDGER.json").read_text())["material_configurations_used"] + 4 > resource_limits()["materials"]:
        raise ValueError("material configuration budget")

    times = np.linspace(0., .5, 51)
    seeds = seed_positions()
    design = calibration_design()
    record = dict(
        status="running", schema="f3.material.affine_calibration.v2",
        backend="f3_ckdtree_visible_shepard_cpu1_v1", configuration_charge=4,
        configurations=[dict(row) for row in CONFIGURATIONS], design=design,
        scope="manufactured reference reconstruction calibration bound to the prospective material backend; not CFD source or full-window material qualification",
        program_path=PROGRAM_RELATIVE,
        program_sha256=sha256(LAB / PROGRAM_RELATIVE),
        tracer_sha256=sha256(LAB / TRACER_RELATIVE),
        interpolator_path=INTERPOLATOR_RELATIVE,
        interpolator_sha256=sha256(LAB / INTERPOLATOR_RELATIVE),
        results=[],
    )
    write(TARGET_NAME, record)
    folder = LAB / DATA_RELATIVE
    folder.mkdir(parents=True, exist_ok=True)
    walls = box_surface_triangles([-.45, -.09, 0.], [.45, .09, .51],
                                  sides=("xmin", "xmax", "ymin", "ymax", "zmin"))
    outputs = {}
    for cfg in CONFIGURATIONS:
        started = time.monotonic()
        flow, dp = cfg["flow"], cfg["dp_m"]
        name = f"{flow}-dp{dp}"
        xy = np.arange(-.06, .060001, dp)
        z = np.arange(.005, .085001, dp)
        cloud = np.stack(np.meshgrid(xy, xy, z, indexing="ij"), axis=-1).reshape(-1, 3)
        states = [exact(cloud, t, flow) for t in times]
        source = folder / f"{name}.h5"
        with h5py.File(source, "w") as h5:
            h5["time"] = times
            h5["position"] = np.stack([p for p, _ in states])
            h5["velocity"] = np.stack([v for _, v in states])
            h5["valid"] = np.ones((len(times), len(cloud)), bool)
            h5["type"] = np.full((len(times), len(cloud)), 3, np.int8)
        trace = manufactured_trace(source, seeds, walls)
        truth = np.stack([exact(seeds, t, flow)[0] for t in times])
        errors = np.linalg.norm(trace["position"] - truth, axis=-1)
        reliable = trace["reliability_history"]
        residence = residence_times(times, trace["position"], reliable)
        left = np.where(seeds[:, 0] < 0, .5, 0.)
        crossed = (seeds[:, 0] < 0) != (truth[-1, :, 0] < 0)
        crossing = (-seeds[:, 0] / seeds[:, 1] if flow == "shear"
                    else np.mod(np.arctan2(seeds[:, 0], seeds[:, 1]), np.pi))
        left[crossed] = np.where(seeds[crossed, 0] < 0,
                                 crossing[crossed], .5 - crossing[crossed])
        terminal = np.where(reliable[-1], (trace["position"][-1, :, 0] >= 0).astype(int), 2)
        expected = (truth[-1, :, 0] >= 0).astype(int)
        artifact = folder / f"{name}.npz"
        np.savez_compressed(artifact, time=times, position=trace["position"],
                            truth=truth, reliable=reliable,
                            initial_position=seeds,
                            residence_left_s=residence[0],
                            exact_residence_left_s=left,
                            terminal_label=terminal)
        row = dict(
            **cfg, source=str(source.relative_to(LAB)), source_sha256=sha256(source),
            artifact=str(artifact.relative_to(LAB)), artifact_sha256=sha256(artifact),
            max_path_error_m=float(errors.max()),
            max_path_error_over_dp=float(errors.max() / dp),
            reliable_fraction=float(reliable.mean()),
            maximum_residence_error_s=float(np.max(np.abs(residence[0] - left))),
            terminal_disagreement_fraction=float(np.mean(terminal != expected)),
            elapsed_seconds=time.monotonic() - started,
        )
        row["passed"] = bool(
            row["max_path_error_m"] <= .001
            and row["maximum_residence_error_s"] <= .01
            and reliable.all()
            and row["terminal_disagreement_fraction"] == 0
        )
        record["results"].append(row)
        write(TARGET_NAME, record)
        outputs[(flow, dp)] = trace["position"]
        print(json.dumps(row), flush=True)
    record["same_seed_cross_resolution_max_path_difference_m"] = {
        flow: float(np.linalg.norm(outputs[flow, .01] - outputs[flow, .006], axis=-1).max())
        for flow in ("shear", "rotation")
    }
    record.update(status="completed", calibrated=all(row["passed"] for row in record["results"]),
                  qualified_T2=False)
    write(TARGET_NAME, record)
    ledger()


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()
