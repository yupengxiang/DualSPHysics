from __future__ import annotations

import json
import sys
from pathlib import Path

import h5py
import numpy as np


M2_ROOT = Path(__file__).resolve().parent
if str(M2_ROOT) not in sys.path:
    sys.path.insert(0, str(M2_ROOT))

import lagrangebench_v2_loader as ldc  # noqa: E402
import portable_bundle  # noqa: E402


def _make_ldc_fixture(root: Path) -> Path:
    dataset = root / ldc.DATASET_DIRNAME
    dataset.mkdir()
    metadata = {
        "case": "LDC",
        "solver": "SPH",
        "dim": 2,
        "dx": 0.02,
        "dt": 0.0004,
        "write_every": 100,
        "sequence_length_train": 10001,
        "sequence_length_test": 5001,
        "num_particles_max": 2708,
        "bounds": [[0.0, 1.12], [0.0, 1.12]],
    }
    (dataset / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    for split, frames in (("train", 10001), ("valid", 5001), ("test", 5001)):
        with h5py.File(dataset / f"{split}.h5", "w") as handle:
            group = handle.create_group("00000")
            group.create_dataset("position", shape=(frames, 2, 2), dtype="f4", fillvalue=0.0)
            group.create_dataset("particle_type", data=np.array([0, 1], dtype="i4"))
    return dataset


def test_ldc_reader_preserves_raw_fields_and_bounds(tmp_path: Path) -> None:
    dataset = _make_ldc_fixture(tmp_path)
    report = ldc.inspect_dataset(dataset)
    assert report["splits"]["train"]["trajectory_count"] == 1
    assert report["fields"]["available"] == ["position", "particle_type"]
    assert "velocity" in report["fields"]["unavailable"]
    window = ldc.read_window(dataset, "test", "00000", 1, 3, max_bytes=1024)
    assert window["position"].shape == (2, 2, 2)
    assert window["unavailable_fields"] == list(ldc.UNAVAILABLE_FIELDS)


def _make_3d_fixture(root: Path) -> tuple[Path, Path]:
    source = root / "source.h5"
    report = root / "conversion-report.json"
    frames, particles = 3, 4
    with h5py.File(source, "w") as handle:
        handle.attrs["coordinate_frame_source"] = "/home/jade/Projects/DualSPHysics-data/old.xml"
        handle.create_dataset("time", data=np.array([0.0, 0.1, 0.2]))
        handle.create_dataset("particle_id", data=np.arange(particles, dtype="u4"))
        handle.create_dataset("particle_zone", data=np.zeros(particles, dtype="u4"))
        handle.create_dataset("valid", data=np.ones((frames, particles), dtype=bool))
        position = np.arange(frames * particles * 3, dtype="f4").reshape(frames, particles, 3)
        handle.create_dataset("position", data=position)
        handle.create_dataset("velocity", data=np.ones((frames, particles, 3), dtype="f4"))
        for name in ("density", "mass", "pressure"):
            handle.create_dataset(name, data=np.ones((frames, particles), dtype="f4"))
        for name in ("type", "mk"):
            handle.create_dataset(name, data=np.ones((frames, particles), dtype="i4"))
        handle.create_dataset("initial_type", data=np.ones(particles, dtype="i4"))
        handle.create_dataset("initial_mk", data=np.ones(particles, dtype="i4"))
        handle.create_dataset("initial_mass", data=np.ones(particles, dtype="f4"))
    report.write_text(
        json.dumps(
            {
                "coordinate_frame": "DualSPHysics case Cartesian coordinates (x,y,z)",
                "solver_dimension": {"solver_dimension": 3},
                "units": {"position": "m"},
                "conversion_claim": "conversion evidence only",
                "hash_scopes": {
                    "numerical_parameters_sha256": "n",
                    "physical_condition": {
                        "geometry": {"tank_length_m": 1.0},
                        "geometry_family_id": "G",
                        "control_family_id": "C",
                        "recipe_id": "R",
                        "event_window": {},
                    },
                },
                "source_provenance": {"geometry_sha256": "g", "control_sha256": "c"},
            }
        ),
        encoding="utf-8",
    )
    return source, report


def test_portable_bundle_redacts_source_paths_and_reuses_l2_reader(tmp_path: Path) -> None:
    source, report = _make_3d_fixture(tmp_path)
    bundle = tmp_path / "bundle"
    result = portable_bundle.build_bundle(source, report, bundle, "F1_TEST")
    assert result["portable"] is True
    assert result["original_paths_denied"] is True
    assert portable_bundle.validate_bundle(bundle)["trajectory"]["complete_validity"] is True
