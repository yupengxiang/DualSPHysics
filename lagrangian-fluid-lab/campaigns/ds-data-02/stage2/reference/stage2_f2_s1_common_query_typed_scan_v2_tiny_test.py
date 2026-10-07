#!/usr/bin/env python3
"""Exercise the v2 physical-time query interface on a tiny manufactured HDF5.

The temporary trajectory deliberately has nonuniform saved times.  This test
proves that the wrapper derives brackets from those times and does not use
historical frame-number conventions.  The temporary HDF5 is removed before
the receipt is written; no production trajectory is opened.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

import h5py
import numpy as np


HERE = Path(__file__).resolve().parent
WRAPPER = HERE / "stage2_f2_s1_common_query_typed_scan_v2.py"
READER = HERE / "stage2_generic_typed_reader_v1.py"
RECEIPT = HERE / "f2_s1_common_query_scan_v2_tiny_receipt.json"
TIMES = [0.0, 0.73, 1.61, 2.42, 3.70, 4.83]
QUERIES = [0.0, 1.0, 2.0, 3.0, 4.0]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_tiny_trajectory(path: Path) -> None:
    frames, particles = len(TIMES), 4
    particle_id = np.arange(particles, dtype=np.int64)
    zone = np.array([0, 0, 1, 1], dtype=np.int32)
    initial_type = np.array([1, 1, 2, 2], dtype=np.int32)
    initial_mk = np.array([0, 1, 0, 1], dtype=np.int32)
    initial_mass = np.full(particles, 0.25, dtype=np.float64)
    position = np.zeros((frames, particles, 3), dtype=np.float32)
    velocity = np.zeros_like(position)
    for frame, time_s in enumerate(TIMES):
        position[frame, :, 0] = float(time_s)
        velocity[frame, :, 0] = float(frame)
    density = np.full((frames, particles), 1000.0, dtype=np.float32)
    mass = np.broadcast_to(initial_mass, (frames, particles)).copy()
    pressure = np.zeros((frames, particles), dtype=np.float32)
    valid = np.ones((frames, particles), dtype=np.uint8)
    typed = np.broadcast_to(initial_type, (frames, particles)).copy()
    mk = np.broadcast_to(initial_mk, (frames, particles)).copy()
    with h5py.File(path, "w") as handle:
        handle.attrs["schema"] = "manufactured.ds-data-02.typed.v2-test"
        handle.attrs["identity_key"] = "(particle_zone, particle_id)"
        handle.attrs["coordinate_frame"] = "cartesian"
        handle.attrs["conversion_complete"] = True
        handle.attrs["mass_semantics"] = "sample_mass"
        handle.create_dataset("particle_id", data=particle_id)
        handle.create_dataset("particle_zone", data=zone)
        handle.create_dataset("initial_type", data=initial_type)
        handle.create_dataset("initial_mk", data=initial_mk)
        handle.create_dataset("initial_mass", data=initial_mass)
        handle.create_dataset("time", data=np.asarray(TIMES, dtype=np.float64))
        handle.create_dataset("position", data=position)
        handle.create_dataset("velocity", data=velocity)
        handle.create_dataset("density", data=density)
        handle.create_dataset("mass", data=mass)
        handle.create_dataset("pressure", data=pressure)
        handle.create_dataset("valid", data=valid)
        handle.create_dataset("type", data=typed)
        handle.create_dataset("mk", data=mk)


def main() -> int:
    if RECEIPT.exists():
        raise FileExistsError(f"refusing to overwrite receipt: {RECEIPT}")
    wrapper = load_module(WRAPPER, "stage2_f2_s1_query_scan_v2_tiny_wrapper")
    reader = wrapper.load_reader(READER)
    with tempfile.TemporaryDirectory(prefix="ds02-query-v2-tiny-") as directory:
        trajectory = Path(directory) / "manufactured-trajectory.h5"
        make_tiny_trajectory(trajectory)
        result = wrapper.query_scan(
            reader,
            trajectory,
            None,
            QUERIES,
            ("position", "velocity", "density", "mass", "valid", "type", "mk"),
            True,
            16,
        )
        brackets = result["axis_pass"]["query_time_brackets"]
        expected = [
            ("EXACT_OR_LEFT", 0, 0),
            ("BRACKETED", 1, 2),
            ("BRACKETED", 2, 3),
            ("BRACKETED", 3, 4),
            ("BRACKETED", 4, 5),
        ]
        observed = [(b["status"], b.get("lower_index"), b.get("upper_index")) for b in brackets]
        if observed != expected:
            raise AssertionError(f"unexpected physical-time brackets: {observed}")
        if result["selected_frame_indices"] != [0, 1, 2, 3, 4, 5]:
            raise AssertionError(result["selected_frame_indices"])
        if result["axis_pass"]["time_values_s"]["count"] != len(TIMES):
            raise AssertionError(result["axis_pass"]["time_values_s"])
        receipt = {
            "schema": "ds-data-02.stage2.f2-s1.common-query-typed-scan.v2.tiny-manufactured-receipt",
            "status": "PASS",
            "test_scope": {
                "solver_started": False,
                "production_h5_opened": False,
                "temporary_h5_removed_before_receipt": True,
                "worker_full_payload_hash": "NOT_COMPUTED_BY_WORKER",
            },
            "saved_time_values_s": TIMES,
            "query_times_s": QUERIES,
            "observed_brackets": brackets,
            "expected_bracket_index_pairs": [[0, 0], [1, 2], [2, 3], [3, 4], [4, 5]],
            "selected_frame_indices": result["selected_frame_indices"],
            "selected_frame_policy": result["selected_frame_policy"],
            "wrapper": {"path": str(WRAPPER), "sha256": sha256(WRAPPER)},
            "generic_reader": {"path": str(READER), "sha256": sha256(READER)},
            "assertions": [
                "nonuniform saved times are used for all brackets",
                "query 0.0 is exact/left at frame 0",
                "queries 1.0, 2.0, 3.0, 4.0 select adjacent physical-time frames",
                "no query time is converted by a fixed frame-number formula",
            ],
        }
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "receipt": str(RECEIPT), "selected_frame_indices": [0, 1, 2, 3, 4, 5]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
