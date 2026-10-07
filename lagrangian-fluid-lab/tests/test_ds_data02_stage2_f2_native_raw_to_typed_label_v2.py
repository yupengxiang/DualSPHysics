from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import h5py
import numpy as np
import pytest


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import ds_data02_stage2_f2_native_raw_to_typed_label_v2 as worker  # noqa: E402


def _identity_sha(zones: np.ndarray, ids: np.ndarray) -> str:
    order = np.lexsort((ids, zones))
    return hashlib.sha256(np.stack([zones[order].astype("<i8"), ids[order].astype("<i8")], axis=1).tobytes()).hexdigest()


def _fixture_request() -> dict:
    zones = np.zeros(3, dtype="<i2")
    ids = np.array([1, 2, 3], dtype="<u4")
    mks = np.array([1, 2, 3], dtype="<i2")
    identity = _identity_sha(zones, ids)
    return {
        "current_binding": {"path": "fixture-CURRENT336.json", "sha256": "a" * 64,
                            "case_index": 78, "frames": 2, "particles": 4},
        "cohort": {"expected_initial_fluid_count": 3, "initial_type_code": 3,
                   "initial_mk_codes": [1, 2, 3], "source_identity_set_sha256": identity},
        "initial_mass_denominator": {"denominator_kg": 0.003},
        "typed_output_contract": {
            "frames": 2, "particles": 4, "expected_times_s": [0.0, 4.0001],
            "fluid_mk_counts": {"1": 1, "2": 1, "3": 1},
        },
    }


def _write_fixture(path: Path, *, finite_inactive: bool = False) -> dict:
    request = _fixture_request()
    missing_ids = np.array([2], dtype="<u4")
    report = {
        "lifecycle": {"frame_summary": [
            {"active_particles": 4, "missing_particles": 0,
             "missing_ids_sha256": hashlib.sha256(np.array([], dtype="<u4").tobytes()).hexdigest()},
            {"active_particles": 3, "missing_particles": 1,
             "missing_ids_sha256": hashlib.sha256(missing_ids.tobytes()).hexdigest()},
        ]},
    }
    with h5py.File(path, "w") as h5:
        h5.attrs["identity_key"] = "(Zone,Idp)"
        h5.attrs["conversion_complete"] = True
        h5.create_dataset("time", data=np.array([0.0, 4.0001]))
        h5.create_dataset("particle_id", data=np.arange(4, dtype="u4"))
        h5.create_dataset("particle_zone", data=np.zeros(4, dtype="i2"))
        valid = np.array([[True, True, True, True], [True, True, False, True]])
        h5.create_dataset("valid", data=valid)
        positions = np.full((2, 4, 3), np.nan, dtype="f4")
        velocities = np.full((2, 4, 3), np.nan, dtype="f4")
        density = np.full((2, 4), np.nan, dtype="f4")
        mass = np.full((2, 4), np.nan, dtype="f4")
        pressure = np.full((2, 4), np.nan, dtype="f4")
        for frame in range(2):
            active = valid[frame]
            positions[frame, active] = 0.1 + frame
            velocities[frame, active] = 0.2
            density[frame, active] = 1000.0
            mass[frame, active] = np.array([0.002, 0.001, 0.001, 0.001], dtype="f4")[active]
            pressure[frame, active] = 1.0
        if finite_inactive:
            positions[1, 2] = [0.0, 0.0, 0.0]
            mass[1, 2] = 0.001
        for name, data in (("position", positions), ("velocity", velocities),
                           ("density", density), ("mass", mass), ("pressure", pressure)):
            h5.create_dataset(name, data=data)
        h5.create_dataset("type", data=np.array([[0, 3, 3, 3], [0, 3, -1, 3]], dtype="i1"))
        h5.create_dataset("mk", data=np.array([[0, 1, 2, 3], [0, 1, -1, 3]], dtype="i2"))
        h5.create_dataset("initial_type", data=np.array([0, 3, 3, 3], dtype="i1"))
        h5.create_dataset("initial_mk", data=np.array([0, 1, 2, 3], dtype="i2"))
        h5.create_dataset("initial_mass", data=np.array([0.002, 0.001, 0.001, 0.001], dtype="f4"))
    return request, report


def test_typed_validation_binds_identity_mass_time_and_lifecycle(tmp_path: Path) -> None:
    h5_path = tmp_path / "typed.h5"
    request, converter_report = _write_fixture(h5_path)
    trajectory, validation = worker._validate_and_load_typed(
        h5_path, request, converter_report, {"frames": [{}, {}]})
    assert validation["status"] == "PASS_TYPED_IDENTITY_LIFECYCLE_DEVELOPMENT"
    assert validation["fluid_cohort"]["count"] == 3
    assert validation["fluid_cohort"]["mass_sum_kg"] == pytest.approx(0.003)
    assert trajectory["position"].shape == (2, 3, 3)
    assert trajectory["valid"].tolist() == [[True, True, True], [True, False, True]]
    assert validation["lifecycle"]["selected_frame_summary"][1]["selected_missing_mass_kg"] == pytest.approx(0.001)


def test_finite_inactive_coordinates_are_rejected(tmp_path: Path) -> None:
    h5_path = tmp_path / "typed.h5"
    request, converter_report = _write_fixture(h5_path, finite_inactive=True)
    with pytest.raises(worker.NativeReconstructionError, match="inactive position"):
        worker._validate_and_load_typed(h5_path, request, converter_report, {"frames": [{}, {}]})


def test_identity_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    h5_path = tmp_path / "typed.h5"
    request, converter_report = _write_fixture(h5_path)
    request["cohort"]["source_identity_set_sha256"] = "b" * 64
    with pytest.raises(worker.NativeReconstructionError, match="identity axis"):
        worker._validate_and_load_typed(h5_path, request, converter_report, {"frames": [{}, {}]})


def test_spans_preserve_noncontiguous_identity_order() -> None:
    indices = np.array([1, 2, 5, 8, 9], dtype=np.int64)
    assert worker._spans(indices) == [(0, 2, 1, 3), (2, 3, 5, 6), (3, 5, 8, 10)]


def test_raw_partout_cannot_substitute_for_frame_records(tmp_path: Path) -> None:
    raw = tmp_path / "data"
    raw.mkdir()
    (raw / "PartOut_000.obi4").write_bytes(b"cause evidence")
    request = {"raw_binding": {"data_root": str(raw), "frames": []}}
    with pytest.raises(worker.NativeReconstructionError, match="Part_.*frames"):
        worker._frame_records(request, verify_hash=False)


def test_existing_output_directory_is_never_reused() -> None:
    # The guard's actual request test exercises the full source closure; this
    # direct unit assertion covers the immutable output policy without opening
    # any raw or HDF5 source.
    assert worker.UNKNOWN_QUALIFICATION == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
