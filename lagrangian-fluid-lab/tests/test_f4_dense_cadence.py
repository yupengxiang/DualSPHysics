import hashlib
import json

import h5py
import numpy as np
import pytest

from scripts.f4_dense_cadence import downsample, select_indices


def _trajectory(path, interval=0.002, frames=11):
    times = np.arange(frames, dtype=np.float64) * interval
    position = np.arange(frames * 2 * 3, dtype=np.float64).reshape(frames, 2, 3)
    velocity = position + 100.0
    valid = np.ones((frames, 2), dtype=bool)
    with h5py.File(path, "w") as handle:
        handle.attrs["conversion_complete"] = True
        handle.attrs["case_id"] = "dense-fixture"
        handle.create_dataset("time", data=times)
        handle.create_dataset("position", data=position)
        handle.create_dataset("velocity", data=velocity)
        handle.create_dataset("valid", data=valid)
        handle.create_dataset("particle_id", data=np.array([4, 9], dtype=np.uint32))


def test_select_indices_rejects_native_coarse_source():
    with pytest.raises(ValueError, match="demonstrably denser"):
        select_indices(np.arange(0.0, 0.101, 0.02), target_interval_s=0.02)


def test_downsample_copies_rows_and_records_indices_and_hashes(tmp_path):
    source = tmp_path / "dense.h5"
    output = tmp_path / "matched.h5"
    independent = tmp_path / "independent.h5"
    _trajectory(source, frames=11)
    _trajectory(independent, interval=0.02, frames=2)

    receipt = downsample(
        source,
        output,
        target_interval_s=0.01,
        target_time_max_s=0.02,
        independent_native_source=independent,
    )
    assert receipt["selection"]["source_frame_indices"] == [0, 5, 10]
    assert receipt["independent_native_comparison"]["used_as_downsample_input"] is False
    assert receipt["output"]["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()

    with h5py.File(source, "r") as source_h5, h5py.File(output, "r") as output_h5:
        np.testing.assert_array_equal(output_h5["time"][:], source_h5["time"][[0, 5, 10]])
        np.testing.assert_array_equal(output_h5["position"][:], source_h5["position"][[0, 5, 10]])
        np.testing.assert_array_equal(output_h5["particle_id"][:], source_h5["particle_id"][:])
        assert bool(output_h5.attrs["cadence_derived_from_native_dense"])
        assert not bool(output_h5.attrs["cadence_derivation_interpolation"])

    sidecar = json.loads(output.with_suffix(".json").read_text())
    assert sidecar["source"]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert sidecar["selection"]["source_frame_indices"] == [0, 5, 10]
