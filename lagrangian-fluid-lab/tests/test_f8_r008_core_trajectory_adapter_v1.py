from __future__ import annotations

import hashlib
import os

import h5py
import numpy as np
import pytest

from scripts.core_cfd_dataset import adapt_manifest
from scripts.core_dataset import CoreDataset
from scripts.core_cfd_dataset import known_inputs_from_cfd_config
from scripts import f8_r008_core_trajectory_adapter_v1 as adapter
from scripts import f8_r008_native_fluid_table_v2 as table_v2
from tests import test_f8_r008_native_fluid_table_v2 as table_fixtures


CASE_ID = table_fixtures.CASE_ID


def _config(root) -> dict:
    samples = np.asarray([
        [0., 0., 0., 0., 0., 0., 0.],
        [.5, .01, 0., 0., 0., 0., 0.],
        [1., 0., 0., 0., 0., 0., 0.],
    ])
    path = root / "control.csv"
    lines = ["#Time;LinearAccX;LinearAccY;LinearAccZ;AngularAccX;AngularAccY;AngularAccZ"]
    lines.extend(";".join(f"{value:.17g}" for value in row) for row in samples)
    raw = ("\n".join(lines) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return {
        "family": "F8", "scope_id": table_v2.SCOPE_ID,
        "stage": "qualification", "qualification_only": True,
        "dp_m": .009, "density_kg_m3": 1000., "gravity_m_s2": [0., 0., 0.],
        "physical_kinematic_viscosity_m2_s": .0005,
        "viscosity_formulation": "laminar", "time_max_s": 1.,
        "periodic_axes": "xy", "periodic_lengths_m": [.24, .12, 0.],
        "wall_bounds": {"xmin": 0., "xmax": .24, "ymin": 0., "ymax": .12,
                        "zmin": -.045, "zmax": .045},
        "closed_faces": ["bottom", "top"],
        "control_amplitude_m_s2": .01, "omega_rad_s": .9876543209876544,
        "alpha": 2.,
        "control_asset": {"path": path.name, "sha256": hashlib.sha256(raw).hexdigest(),
                           "bytes": len(raw), "format": "dualsphysics_accinput_csv_v1"},
    }


def _table(tmp_path, *, mutate=None):
    frames = [table_fixtures._frame(0.), table_fixtures._frame(.5),
              table_fixtures._frame(1.)]
    path = tmp_path / "native-table.h5"
    table_fixtures._write_table(path, frames, mutate=mutate)
    raw = path.read_bytes()
    return path, frames, len(raw), hashlib.sha256(raw).hexdigest()


def _convert(tmp_path, table_path, frames, table_bytes, table_sha256):
    output_directory = tmp_path / "converted"
    output_directory.mkdir(mode=0o700)
    table_fd = os.open(table_path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    output_fd = os.open(output_directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        result = adapter.materialize_diagnostic_core_trajectory_v1_at(
            table_fd, output_fd, case_id=CASE_ID,
            expected_table_bytes=table_bytes, expected_table_sha256=table_sha256,
            expected_attributes=table_fixtures.ATTRS,
            expected_time_axis_hex=[frame.time_ieee754_hex for frame in frames],
            expected_fluid_ids=table_fixtures.FLUID_IDS,
            expected_case_np=4,
            initial_massfluid_binary64_le=table_fixtures.MASS_BYTES,
            source_frames_factory=lambda: iter(frames),
        )
    finally:
        os.close(table_fd)
        os.close(output_fd)
    return output_directory, result


def test_verified_f8_table_materializes_as_core_qualification_only(tmp_path):
    table_path, frames, table_bytes, table_sha256 = _table(tmp_path)
    output_directory, result = _convert(
        tmp_path, table_path, frames, table_bytes, table_sha256,
    )
    trajectory = output_directory / adapter.OUTPUT_FILENAME

    assert result["schema"] == adapter.SCHEMA
    assert result["status"] == "diagnostic_qualification_trajectory_written_and_reverified"
    assert result["source_table_sha256"] == table_sha256
    assert result["time_rows"] == len(frames)
    assert result["fluid_particle_count"] == len(table_fixtures.FLUID_IDS)
    assert result["particle_zone_value"] == 0
    assert result["split"] == "qualification"
    assert result["source_provenance_authenticated"] is False
    assert result["formal_eligible"] is False
    assert result["full_t1_decision"] is False
    assert result["qualification_credit"] == 0
    assert trajectory.stat().st_nlink == 1
    assert trajectory.stat().st_mode & 0o777 == 0o600

    config = _config(tmp_path)
    source = {
        "schema": "core.f8.oscillatory_pressure_channel.v1",
        "family": "F8",
        "cases": [{
            "case_id": CASE_ID, "family": "F8", "split": "train",
            "qualification_only": True,
            "prepared_record": {"config": config},
            "trajectory": f"converted/{adapter.OUTPUT_FILENAME}",
            "sha256": result["trajectory_binding"]["sha256"],
        }],
    }
    manifest = adapt_manifest(source, tmp_path)
    assert manifest["formal_release"] is False
    assert manifest["cases"][0]["split"] == "qualification"
    assert manifest["cases"][0]["qualification_case"] is True
    assert manifest["cases"][0]["bytes"] == result["trajectory_binding"]["bytes"]

    with CoreDataset(manifest, tmp_path) as dataset:
        assert dataset.formal_eligible is False
        state = dataset.read_state(CASE_ID, 1)
        expected = table_fixtures._expected_tables(frames)
        np.testing.assert_array_equal(state.particle_id, table_fixtures.FLUID_IDS)
        np.testing.assert_array_equal(state.particle_zone, np.zeros(len(state.particle_id), dtype=np.int64))
        np.testing.assert_array_equal(state.position, expected["position"][1])
        np.testing.assert_array_equal(state.velocity, expected["velocity"][1])
        np.testing.assert_array_equal(state.mass, expected["mass"][0])
        np.testing.assert_array_equal(state.valid, np.ones(len(state.particle_id), dtype=bool))
        with pytest.raises(ValueError, match="train cases only"):
            dataset.training_transition(CASE_ID, 0)


def test_semantically_invalid_table_never_publishes_a_core_trajectory(tmp_path):
    table_path, frames, table_bytes, table_sha256 = _table(
        tmp_path, mutate=("velocity", "wrong_value"),
    )
    output_directory = tmp_path / "converted"
    output_directory.mkdir(mode=0o700)
    table_fd = os.open(table_path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    output_fd = os.open(output_directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        with pytest.raises(table_v2.NativeFluidTableError,
                           match="velocity row 0 differs from raw BI4 projection"):
            adapter.materialize_diagnostic_core_trajectory_v1_at(
                table_fd, output_fd, case_id=CASE_ID,
                expected_table_bytes=table_bytes, expected_table_sha256=table_sha256,
                expected_attributes=table_fixtures.ATTRS,
                expected_time_axis_hex=[frame.time_ieee754_hex for frame in frames],
                expected_fluid_ids=table_fixtures.FLUID_IDS,
                expected_case_np=4,
                initial_massfluid_binary64_le=table_fixtures.MASS_BYTES,
                source_frames_factory=lambda: iter(frames),
            )
    finally:
        os.close(table_fd)
        os.close(output_fd)

    assert list(output_directory.iterdir()) == []


def test_existing_final_name_is_never_overwritten(tmp_path):
    table_path, frames, table_bytes, table_sha256 = _table(tmp_path)
    output_directory = tmp_path / "converted"
    output_directory.mkdir(mode=0o700)
    final_path = output_directory / adapter.OUTPUT_FILENAME
    final_path.write_bytes(b"keep existing artifact")
    table_fd = os.open(table_path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    output_fd = os.open(output_directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        with pytest.raises(FileExistsError):
            adapter.materialize_diagnostic_core_trajectory_v1_at(
                table_fd, output_fd, case_id=CASE_ID,
                expected_table_bytes=table_bytes, expected_table_sha256=table_sha256,
                expected_attributes=table_fixtures.ATTRS,
                expected_time_axis_hex=[frame.time_ieee754_hex for frame in frames],
                expected_fluid_ids=table_fixtures.FLUID_IDS,
                expected_case_np=4,
                initial_massfluid_binary64_le=table_fixtures.MASS_BYTES,
                source_frames_factory=lambda: iter(frames),
            )
    finally:
        os.close(table_fd)
        os.close(output_fd)

    assert final_path.read_bytes() == b"keep existing artifact"


def test_oversized_table_is_rejected_before_any_content_hash(tmp_path, monkeypatch):
    table_path, frames, _table_bytes, table_sha256 = _table(tmp_path)
    output_directory = tmp_path / "converted"
    output_directory.mkdir(mode=0o700)
    table_fd = os.open(table_path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    output_fd = os.open(output_directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)

    def fail_if_hashed(*_args, **_kwargs):
        raise AssertionError("oversized input reached raw hashing")

    monkeypatch.setattr(adapter, "_sha256_fd", fail_if_hashed)
    try:
        with pytest.raises(adapter.CoreTrajectoryAdapterError,
                           match="outside the frozen v2 file-size cap"):
            adapter.materialize_diagnostic_core_trajectory_v1_at(
                table_fd, output_fd, case_id=CASE_ID,
                expected_table_bytes=table_v2.MAX_TABLE_FILE_BYTES + 1,
                expected_table_sha256=table_sha256,
                expected_attributes=table_fixtures.ATTRS,
                expected_time_axis_hex=[frame.time_ieee754_hex for frame in frames],
                expected_fluid_ids=table_fixtures.FLUID_IDS,
                expected_case_np=4,
                initial_massfluid_binary64_le=table_fixtures.MASS_BYTES,
                source_frames_factory=lambda: iter(frames),
            )
    finally:
        os.close(table_fd)
        os.close(output_fd)

    assert list(output_directory.iterdir()) == []


def test_directory_entry_rebinding_after_content_verification_is_rejected(
    tmp_path, monkeypatch,
):
    table_path, frames, table_bytes, table_sha256 = _table(tmp_path)
    output_directory = tmp_path / "converted"
    output_directory.mkdir(mode=0o700)
    final_path = output_directory / adapter.OUTPUT_FILENAME
    displaced_path = output_directory / "verified-inode-displaced.h5"
    original_verify = adapter._verify_trajectory_fd
    calls = 0

    def verify_then_rebind(*args, **kwargs):
        nonlocal calls
        result = original_verify(*args, **kwargs)
        calls += 1
        if calls == 2:  # The published-name pass, after byte/content validation.
            final_path.rename(displaced_path)
            final_path.write_bytes(b"same-user replacement")
        return result

    monkeypatch.setattr(adapter, "_verify_trajectory_fd", verify_then_rebind)
    table_fd = os.open(table_path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    output_fd = os.open(output_directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        with pytest.raises(adapter.CoreTrajectoryAdapterError,
                           match="path no longer resolves to the verified inode"):
            adapter.materialize_diagnostic_core_trajectory_v1_at(
                table_fd, output_fd, case_id=CASE_ID,
                expected_table_bytes=table_bytes, expected_table_sha256=table_sha256,
                expected_attributes=table_fixtures.ATTRS,
                expected_time_axis_hex=[frame.time_ieee754_hex for frame in frames],
                expected_fluid_ids=table_fixtures.FLUID_IDS,
                expected_case_np=4,
                initial_massfluid_binary64_le=table_fixtures.MASS_BYTES,
                source_frames_factory=lambda: iter(frames),
            )
    finally:
        os.close(table_fd)
        os.close(output_fd)

    assert final_path.read_bytes() == b"same-user replacement"
    assert displaced_path.is_file()
