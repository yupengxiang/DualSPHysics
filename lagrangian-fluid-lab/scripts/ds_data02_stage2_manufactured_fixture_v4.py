#!/usr/bin/env python3
"""Build the v4 analytic operator-replay fixture without scientific inputs.

The trajectory is intentionally piecewise linear and small.  Its expected
values are written independently in ``manufactured_expected_v4.json``; this
builder never calls the label operator to derive those expectations.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import h5py
import numpy as np


CASE_ID = "MANUFACTURED_ANALYTIC_REPLAY_V4"
COORDINATE_FRAME = "manufactured_replay_world"
TIMES = np.asarray([0.0, 1.0, 2.0, 3.0, 4.0], dtype="float64")
PARTICLE_MASSES = np.asarray([2.0, 3.0, 5.0, 7.0, 11.0], dtype="float32")
INITIAL_TYPE = np.asarray([3, 3, 3, 3, 3], dtype="int8")
INITIAL_MK = np.asarray([10, 10, 10, 10, 10], dtype="int16")
PARTICLE_ID = np.asarray([100, 101, 102, 103, 104], dtype="uint32")
PARTICLE_ZONE = np.asarray([0, 0, 0, 0, 0], dtype="int16")

# Particle 100 crosses x=0 forward, backward, forward.  Particle 101 stays
# left.  Particle 102 is initially missing, particle 103 is initially active
# and then disappears, and particle 104 stays outside the registered boxes.
# These separate no-event paths exercise censoring, missing mass, and unknown
# destination mass without using a scientific trajectory.
POSITION = np.asarray([
    [[-1.0, .5, .5], [-.5, .5, .5], [np.nan, np.nan, np.nan], [-.75, .5, .5], [3.0, .5, .5]],
    [[ 1.0, .5, .5], [-.5, .5, .5], [np.nan, np.nan, np.nan], [-.75, .5, .5], [3.0, .5, .5]],
    [[-1.0, .5, .5], [-.5, .5, .5], [np.nan, np.nan, np.nan], [np.nan, np.nan, np.nan], [3.0, .5, .5]],
    [[ 1.0, .5, .5], [-.5, .5, .5], [np.nan, np.nan, np.nan], [np.nan, np.nan, np.nan], [3.0, .5, .5]],
    [[ 1.0, .5, .5], [-.5, .5, .5], [np.nan, np.nan, np.nan], [np.nan, np.nan, np.nan], [3.0, .5, .5]],
], dtype="float32")
VELOCITY = np.asarray([
    [[ 2.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
    [[ 2.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
    [[-2.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
    [[ 2.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
    [[ 0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
], dtype="float32")
VALID = np.asarray([
    [True, True, False, True, True],
    [True, True, False, True, True],
    [True, True, False, False, True],
    [True, True, False, False, True],
    [True, True, False, False, True],
], dtype=bool)

CONFIG = {
    "schema": "ds02.stage2.observation-config.v2",
    "frame_kind": "fixed_solver_frame",
    "coordinate_frame": COORDINATE_FRAME,
    "source_assignment": "initial_regions",
    "source_regions": [{"id": "left_source", "bounds": [[-2, 0], [0, 1], [0, 1]]}],
    "destination_regions": [
        {"id": "left", "bounds": [[-2, 0], [0, 1], [0, 1]]},
        {"id": "right", "bounds": [[0, 2], [0, 1], [0, 1]]},
    ],
    "events": [{
        "id": "fixed_midplane",
        "surface": {
            "kind": "fixed_plane",
            "point_m": [0, 0, 0],
            "normal_m": [1, 0, 0],
            "velocity_m_s": [0, 0, 0],
            "aperture_axes": [1, 2],
            "aperture_bounds": [[0, 1], [0, 1]],
            "aperture_frame": "surface_local",
            "reference_time_s": 0,
        },
    }],
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _fields(path: Path) -> dict[str, dict[str, object]]:
    with h5py.File(path, "r") as handle:
        return {name: {"shape": list(dataset.shape), "dtype": str(dataset.dtype),
                       "chunks": list(dataset.chunks) if dataset.chunks is not None else None}
                for name, dataset in handle.items()}


def build_bundle(root: Path | str, expected_source: Path | str) -> dict[str, Path]:
    """Write one reproducible fixture bundle and return its component paths."""
    root = Path(root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=False)
    source = root / "trajectory.h5"
    with h5py.File(source, "w") as handle:
        handle.attrs.update(
            schema="ds-data-02.hdf5-schema.v1",
            identity_key="(Zone,Idp)",
            coordinate_frame=COORDINATE_FRAME,
            units_json=json.dumps({"density": "kg/m^3", "mass": "kg", "position": "m",
                                   "pressure": "Pa", "time": "s", "velocity": "m/s"}),
        )
        for name, data in {
            "time": TIMES, "particle_id": PARTICLE_ID, "particle_zone": PARTICLE_ZONE,
            "initial_type": INITIAL_TYPE, "initial_mass": PARTICLE_MASSES, "initial_mk": INITIAL_MK,
        }.items():
            handle.create_dataset(name, data=data)
        frame_mass = np.broadcast_to(PARTICLE_MASSES, (len(TIMES), len(PARTICLE_MASSES))).copy()
        frame_type = np.broadcast_to(INITIAL_TYPE, (len(TIMES), len(INITIAL_TYPE))).copy()
        frame_mk = np.broadcast_to(INITIAL_MK, (len(TIMES), len(INITIAL_MK))).copy()
        density = np.full((len(TIMES), len(PARTICLE_MASSES)), 1000.0, dtype="float32")
        pressure = np.zeros_like(density)
        for name, data in {
            "valid": VALID, "type": frame_type, "mk": frame_mk, "density": density,
            "mass": frame_mass, "pressure": pressure,
        }.items():
            handle.create_dataset(name, data=data, chunks=(1, len(PARTICLE_MASSES)))
        handle.create_dataset("position", data=POSITION, chunks=(1, len(PARTICLE_MASSES), 3))
        handle.create_dataset("velocity", data=VELOCITY, chunks=(1, len(PARTICLE_MASSES), 3))

    source_catalog = root / "CASES_336.json"
    row = {
        "family_id": "F0",
        "physical_case_id": CASE_ID,
        "frames": len(TIMES),
        "particles": len(PARTICLE_ID),
        "actual_time_window_s": [float(TIMES[0]), float(TIMES[-1])],
        "manifest": None,
        "xmf": None,
        "trajectory": {"path": str(source), "producer_declared_sha256": _sha256(source),
                       "recomputed_sha256": None, "bytes": source.stat().st_size,
                       "mtime_ns": source.stat().st_mtime_ns},
        "header": {"fields": _fields(source),
                   "units": {"density": "kg/m^3", "mass": "kg", "position": "m",
                             "pressure": "Pa", "time": "s", "velocity": "m/s"},
                   "identity_key": "(Zone,Idp)", "coordinate_frame": COORDINATE_FRAME},
        "source_bindings": {},
        "quality": {"visual": "MANUFACTURED_ONLY", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    source_catalog.write_text(json.dumps({"cases": [row]}, indent=2) + "\n", encoding="utf-8")
    catalog = root / "CURRENT336.json"
    catalog.write_text(json.dumps({"schema": "ds02.stage2.current336.v1", "source_catalog": str(source_catalog),
                                   "source_catalog_sha256": _sha256(source_catalog), "unresolved": 0,
                                   "total_hdf5_bytes": source.stat().st_size, "cases": [row]}, indent=2) + "\n",
                        encoding="utf-8")
    config_path = root / "operator-config.json"
    config_path.write_text(json.dumps(CONFIG, indent=2) + "\n", encoding="utf-8")
    expected_path = Path(expected_source).expanduser().resolve()
    copied_expected = root / "manufactured_expected_v4.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    expected["bindings"] = {
        "catalog_sha256": _sha256(catalog),
        "source_catalog_sha256": _sha256(source_catalog),
        "source_hdf5_sha256": _sha256(source),
        "case_row_sha256": _canonical_sha256(row),
    }
    copied_expected.write_text(json.dumps(expected, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"catalog": catalog, "source": source, "config": config_path,
            "expected": copied_expected, "source_catalog": source_catalog}


__all__ = ["CASE_ID", "CONFIG", "build_bundle"]
