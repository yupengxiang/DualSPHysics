"""Tests for the read-only F7 causal-control sidecar producer."""

from __future__ import annotations

import h5py
import numpy as np
import pytest

from scripts.f7_pump_causal_sidecar_v1 import (
    ANGULAR_CONTROL_DATASET,
    BODY_FRAME_DATASET,
    SCHEMA,
    make_sidecar,
)
from scripts.f7_pump_geometry_adapter_v1 import (
    DEFAULT_DEFINITION,
    parse_pump_definition,
    pump_angular_velocity_degrees_per_second,
)


def _trajectory(path, times=None):
    times = np.asarray([0.0, 1.0, 2.0, 6.0] if times is None else times, dtype=float)
    with h5py.File(path, "w") as h5:
        h5["time"] = times
        h5["position"] = np.zeros((len(times), 2, 3), dtype=float)
        h5["particle_id"] = np.asarray([1, 2], dtype=np.int64)
        h5["particle_zone"] = np.asarray([1, 1], dtype=np.int8)
        h5.attrs["unrelated_attribute"] = "preserved"


def test_sidecar_binds_source_and_exact_public_motion_without_torque(tmp_path):
    source = tmp_path / "trajectory.h5"
    output = tmp_path / "trajectory.f7.h5"
    _trajectory(source)

    receipt = make_sidecar(source, output, DEFAULT_DEFINITION)

    assert receipt["schema"] == SCHEMA
    assert receipt["status"] == "interface_sidecar_written_not_runtime_evidence"
    assert receipt["trajectory_source"]["frame_count"] == 4
    assert receipt["torque"] == {
        "present": False,
        "fabricated": False,
        "required_for_physical_independence": True,
    }
    assert receipt["execution_controls"]["solver_invoked"] is False
    assert receipt["execution_controls"]["qualification_credit"] == 0

    contract = parse_pump_definition(DEFAULT_DEFINITION)
    expected_speed = pump_angular_velocity_degrees_per_second(1.0, contract)
    with h5py.File(output, "r") as h5:
        assert h5.attrs["f7_causal_sidecar_schema"] == SCHEMA
        assert h5.attrs["f7_source_trajectory_sha256"] == receipt["trajectory_source"]["sha256"]
        assert bool(h5.attrs["f7_torque_dataset_present"]) is False
        assert "position" not in h5
        assert "particle_id" not in h5
        np.testing.assert_allclose(h5["time"][:], [0.0, 1.0, 2.0, 6.0])
        assert h5[BODY_FRAME_DATASET].shape == (4, 4, 4)
        assert h5[ANGULAR_CONTROL_DATASET].shape == (4, 3)
        rotation = h5[BODY_FRAME_DATASET][1, :3, :3]
        np.testing.assert_allclose(rotation.T @ rotation, np.eye(3), atol=1e-12)
        assert np.linalg.det(rotation) == pytest.approx(1.0)
        assert np.linalg.norm(h5[ANGULAR_CONTROL_DATASET][1]) == pytest.approx(
            np.deg2rad(expected_speed)
        )
        # The official example's first segment lasts 2 s, but its finish knot
        # is at 1000 s; TimeMax=6 s therefore remains on the constant-speed
        # second segment rather than being clamped.
        assert np.linalg.norm(h5[ANGULAR_CONTROL_DATASET][-1]) > 0.0
        assert not np.allclose(h5[BODY_FRAME_DATASET][-1], h5[BODY_FRAME_DATASET][-2])


def test_sidecar_never_overwrites_or_reuses_partial_output(tmp_path):
    source = tmp_path / "trajectory.h5"
    output = tmp_path / "trajectory.f7.h5"
    _trajectory(source)
    output.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        make_sidecar(source, output, DEFAULT_DEFINITION)


def test_sidecar_rejects_time_beyond_official_runtime(tmp_path):
    source = tmp_path / "trajectory.h5"
    _trajectory(source, times=[0.0, 1.0, 6.1])
    with pytest.raises(ValueError, match="TimeMax"):
        make_sidecar(source, tmp_path / "out.h5", DEFAULT_DEFINITION)


def test_sidecar_rejects_existing_pump_controls(tmp_path):
    source = tmp_path / "trajectory.h5"
    _trajectory(source)
    with h5py.File(source, "a") as h5:
        h5["control/pump_world_from_body"] = np.repeat(np.eye(4)[None], 4, axis=0)
    with pytest.raises(ValueError, match="already contains F7 Pump"):
        make_sidecar(source, tmp_path / "out.h5", DEFAULT_DEFINITION)
