from __future__ import annotations

import json
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import h5py
import numpy as np
import pytest


M2_ROOT = Path(__file__).resolve().parent
if str(M2_ROOT) not in sys.path:
    sys.path.insert(0, str(M2_ROOT))

import lagrangebench_v2_loader as ldc  # noqa: E402
import portable_bundle  # noqa: E402
import portable_relocate_worker  # noqa: E402


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
    owner = root / "owner-metadata.json"
    generated_xml = root / "generated-case.xml"
    frames, particles = 3, 4
    with h5py.File(source, "w") as handle:
        handle.attrs["coordinate_frame_source"] = "/home/jade/Projects/DualSPHysics-data/old.xml"
        handle.attrs["solver_dimension"] = 3
        handle.attrs["identity_key"] = "(Zone,Idp)"
        handle.attrs["coordinate_frame"] = "DualSPHysics case Cartesian coordinates (x,y,z)"
        handle.attrs["units_json"] = json.dumps(
            {
                "density": "kg/m^3",
                "mass": "kg",
                "position": "m",
                "pressure": "Pa",
                "time": "s",
                "velocity": "m/s",
            }
        )
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
    owner.write_text(
        json.dumps(
            {
                "schema": "ds-data-02.f1.generator.v1",
                "case_id": "F1_TEST",
                "geometry": {"tank_length_m": 1.0},
                "geometry_family_id": "G",
                "control_family_id": "C",
                "recipe_id": "R",
                "event_window": {"complete_event_window_s": 0.2},
                "parameter_values": {"obstacle_offset_y_m": 0.0},
                "solver_parameters": {"TimeMax": "0.2"},
                "observables": {"native_labels": ["source_label", "final_category"]},
                "metadata_path": "/home/jade/Projects/DualSPHysics-data/CURRENT/owner.json",
            }
        ),
        encoding="utf-8",
    )
    generated_xml.write_text(
        "<case><geometry><definition dp=\"0.01\" /></geometry></case>",
        encoding="utf-8",
    )
    report.write_text(
        json.dumps(
            {
                "coordinate_frame": "DualSPHysics case Cartesian coordinates (x,y,z)",
                "solver_dimension": {"solver_dimension": 3},
                "units": {"position": "m"},
                "conversion_claim": "conversion evidence only",
                "hash_scopes": {
                    "numerical_parameters_sha256": "n",
                },
                "source_provenance": {
                    "geometry_sha256": "g",
                    "control_sha256": "c",
                    "owner_metadata": {
                        "path": str(owner),
                        "sha256": hashlib.sha256(owner.read_bytes()).hexdigest(),
                    },
                    "generated_xml": {
                        "path": str(generated_xml),
                        "sha256": hashlib.sha256(generated_xml.read_bytes()).hexdigest(),
                    },
                },
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
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifacts"]["runtime_portable_bundle"]["path"] == "runtime/portable_bundle.py"
    assert manifest["artifacts"]["runtime_l2_reader"]["path"] == "runtime/l2_reader.py"


def test_isolated_validation_probes_denied_source_roots(tmp_path: Path) -> None:
    if shutil.which("bwrap") is None:
        pytest.skip("bubblewrap is unavailable")
    source, report = _make_3d_fixture(tmp_path)
    bundle = tmp_path / "bundle"
    portable_bundle.build_bundle(source, report, bundle, "F1_TEST")
    output = tmp_path / "isolated-validation.json"
    wrapper = M2_ROOT / "portable_isolated_validate.py"
    completed = subprocess.run(
        [
            sys.executable,
            str(wrapper),
            "--bundle-root",
            str(bundle),
            "--python",
            sys.executable,
            "--output",
            str(output),
            "--max-wall-seconds",
            "120",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    validation = json.loads(output.read_text(encoding="utf-8"))
    assert validation["namespace"]["denied_probes_passed"] is True
    assert validation["validation"]["portable"] is True
    assert "worktree_mount" not in validation["namespace"]
    assert validation["namespace"]["runtime_from_bundle"] == "/srv/runtime"


def test_relocate_worker_copies_fresh_bundle_before_isolation(tmp_path: Path) -> None:
    if shutil.which("bwrap") is None:
        pytest.skip("bubblewrap is unavailable")
    source, report = _make_3d_fixture(tmp_path)
    bundle = tmp_path / "bundle"
    portable_bundle.build_bundle(source, report, bundle, "F1_TEST")
    relocated = tmp_path / "fresh-attempt" / "bundle"
    validation_output = tmp_path / "fresh-attempt" / "isolated-validation.json"
    receipt = tmp_path / "fresh-attempt" / "relocation-receipt.json"
    wrapper = M2_ROOT / "portable_isolated_validate.py"
    completed = subprocess.run(
        [
            sys.executable,
            str(M2_ROOT / "portable_relocate_worker.py"),
            "--source-bundle",
            str(bundle),
            "--relocated-bundle",
            str(relocated),
            "--isolation-wrapper",
            str(wrapper),
            "--python",
            sys.executable,
            "--validation-output",
            str(validation_output),
            "--receipt",
            str(receipt),
            "--max-bytes",
            str(128 * 1024 * 1024),
            "--max-wall-seconds",
            "120",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert relocated.is_dir()
    worker_receipt = json.loads(receipt.read_text(encoding="utf-8"))
    assert worker_receipt["status"] == "completed"
    assert worker_receipt["validation"]["portable"] is True
    assert worker_receipt["validation"]["denied_probes_passed"] is True
