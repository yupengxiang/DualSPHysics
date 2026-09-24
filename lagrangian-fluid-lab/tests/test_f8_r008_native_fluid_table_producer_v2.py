from __future__ import annotations

import os
from pathlib import Path
import threading

import h5py
import numpy as np
import pytest

from scripts import f8_r008_native_fluid_table_producer_v2 as producer
from scripts import f8_r008_native_fluid_table_v2 as table_v2

from tests import test_f8_r008_native_fluid_table_v2 as fixtures


def _produce(directory: Path, factory):
    directory_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        return producer.produce_native_fluid_table_v2_at(
            directory_fd,
            expected_attributes=fixtures.ATTRS,
            expected_time_axis_hex=[0.0.hex(), 0.1.hex(), 0.2.hex()],
            expected_fluid_ids=fixtures.FLUID_IDS,
            expected_case_np=4,
            initial_massfluid_binary64_le=fixtures.MASS_BYTES,
            source_frames_factory=factory,
        )
    finally:
        os.close(directory_fd)


def test_v2_producer_streams_two_raw_frame_passes_and_verifies_output(tmp_path: Path) -> None:
    frames = [fixtures._frame(time) for time in (0.0, 0.1, 0.2)]
    calls = 0

    def frame_factory():
        nonlocal calls
        calls += 1
        return iter(frames)

    result = _produce(tmp_path, frame_factory)
    binding = result["table_binding"]
    path = tmp_path / binding["path"]
    assert calls == 2
    assert path.is_file()
    assert binding["bytes"] == path.stat().st_size
    assert result["native_fluid_table"]["table_sha256"] == binding["sha256"]
    assert result["native_fluid_table"]["raw_frames_recomputed"] == 3
    assert result["native_fluid_table"]["position_velocity_density_mass_recomputed"] is True
    assert result["B_C_provenance_verified_by_this_primitive"] is False
    assert result["native_integrity_evaluated"] is False
    assert result["T1_numerical"] is False
    assert result["qualification_credit"] == 0
    with h5py.File(path, "r") as handle:
        assert set(handle.keys()) == set(table_v2.DATASET_DTYPES)
        assert handle["time"].dtype == np.dtype("<f8")
        assert handle["particle_id"].dtype == np.dtype("<u4")
        assert handle["position"].shape == (3, 3, 3)
        assert handle["position"].dtype == np.dtype("<f8")
        assert handle["velocity"].dtype == np.dtype("<f4")
        assert handle["density"].dtype == np.dtype("<f4")
        assert handle["mass"].dtype == np.dtype("<f4")
        assert np.array_equal(handle["valid"][:], np.ones((3, 3), dtype=bool))
        assert np.array_equal(handle["time"][:], [0.0, 0.1, 0.2])
        assert np.array_equal(handle["particle_id"][:], fixtures.FLUID_IDS)


def test_v2_producer_does_not_publish_final_name_until_complete_verification(tmp_path: Path) -> None:
    frames = [fixtures._frame(time) for time in (0.0, 0.1, 0.2)]
    first_pass_started = threading.Event()
    release_writer = threading.Event()
    call_count = 0
    outcome: list[object] = []

    def frame_factory():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            def paused_stream():
                yield frames[0]
                first_pass_started.set()
                if not release_writer.wait(timeout=10):
                    raise TimeoutError("synthetic producer synchronization timed out")
                yield from frames[1:]
            return paused_stream()
        return iter(frames)

    def run_writer():
        try:
            outcome.append(_produce(tmp_path, frame_factory))
        except BaseException as error:
            outcome.append(error)

    writer = threading.Thread(target=run_writer, daemon=True)
    writer.start()
    try:
        assert first_pass_started.wait(timeout=10)
        assert not (tmp_path / producer.TABLE_FILENAME).exists()
    finally:
        release_writer.set()
        writer.join(timeout=10)
    assert not writer.is_alive()
    assert len(outcome) == 1 and isinstance(outcome[0], dict)
    with h5py.File(tmp_path / producer.TABLE_FILENAME, "r") as handle:
        assert bool(handle.attrs["conversion_complete"]) is True


def test_v2_producer_rejects_duplicate_raw_ids_and_removes_only_its_output(tmp_path: Path) -> None:
    bad_ids = np.asarray([3, 1, 0, 0], dtype="<u4")
    bad = fixtures._frame(0.0, particle_id=bad_ids)
    with pytest.raises(producer.NativeFluidTableProducerError, match="missing, duplicate, or unknown ID"):
        _produce(tmp_path, lambda: iter([bad]))
    assert not (tmp_path / producer.TABLE_FILENAME).exists()


def test_v2_producer_rechecks_fresh_second_source_pass(tmp_path: Path) -> None:
    frames = [fixtures._frame(time) for time in (0.0, 0.1, 0.2)]
    calls = 0

    def changed_source_pass():
        nonlocal calls
        calls += 1
        if calls == 1:
            return iter(frames)
        changed_velocity = frames[1].velocity_m_s.copy()
        changed_velocity[0, 0] += np.float32(0.5)
        changed_middle = table_v2.NativeSourceFrame(
            frames[1].time_ieee754_hex, frames[1].particle_id,
            frames[1].position_m, changed_velocity, frames[1].density_kg_m3,
            frames[1].massfluid_binary64_le, frames[1].case_np,
        )
        return iter([frames[0], changed_middle, frames[2]])

    with pytest.raises(table_v2.NativeFluidTableError, match="HDF5 velocity row"):
        _produce(tmp_path, changed_source_pass)
    assert calls == 2
    assert not (tmp_path / producer.TABLE_FILENAME).exists()


@pytest.mark.parametrize("existing_kind", ["file", "symlink"])
def test_v2_producer_never_overwrites_an_existing_output_name(tmp_path: Path, existing_kind: str) -> None:
    target = tmp_path / producer.TABLE_FILENAME
    marker = tmp_path / "user-owned-marker.txt"
    marker.write_bytes(b"keep me")
    if existing_kind == "file":
        target.write_bytes(b"existing output")
    else:
        target.symlink_to(marker.name)

    with pytest.raises(FileExistsError):
        _produce(tmp_path, lambda: iter([]))
    assert marker.read_bytes() == b"keep me"
    if existing_kind == "file":
        assert target.read_bytes() == b"existing output"
    else:
        assert target.is_symlink() and target.resolve() == marker


def test_v2_producer_rejects_incomplete_time_axis_before_publishing(tmp_path: Path) -> None:
    with pytest.raises(producer.NativeFluidTableProducerError,
                       match="does not cover the complete frozen time axis"):
        _produce(tmp_path, lambda: iter([fixtures._frame(0.0), fixtures._frame(0.1)]))
    assert not (tmp_path / producer.TABLE_FILENAME).exists()
