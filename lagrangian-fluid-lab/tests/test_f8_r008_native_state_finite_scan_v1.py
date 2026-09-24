from __future__ import annotations

import hashlib
import os
import struct

import numpy as np
import pytest

from scripts import f8_r008_native_state_finite_scan_v1 as finite_scan
from scripts import f8_r008_safe_bi4_decoder_v1 as decoder
from tests import test_f8_r008_per_case_bundle_verifier_v1 as bi4_fixture


def _array(name: str, type_code: int, payload: bytes) -> bytes:
    element_bytes = decoder.TYPE_INFO[type_code][2]
    assert len(payload) % element_bytes == 0
    count = len(payload) // element_bytes
    definition = (
        bi4_fixture._string(decoder.CODE_ARRAY)
        + bi4_fixture._string(name)
        + struct.pack("<iiII", 0, type_code, count, len(payload))
    )
    return struct.pack("<I", len(definition)) + definition + payload


def _raw_array(type_code: int, values: tuple[float | int, ...]) -> bytes:
    formats = {8: "I", 11: "f", 12: "d", 22: "f", 23: "d"}
    return struct.pack(f"<{len(values)}{formats[type_code]}", *values)


def _synthetic_bi4(
    *,
    position_type: int = 23,
    positions: tuple[float, ...] = (1.0, 2.0, 3.0, 4.0, 5.0, 6.0),
    velocities: tuple[float, ...] = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6),
    densities: tuple[float, ...] = (1000.0, 1001.0),
    position_name: str | None = None,
    position_count: int = 2,
    position_code: int | None = None,
    velocity_code: int = 22,
    density_code: int = 11,
    include_position: bool = True,
    include_velocity: bool = True,
    include_density: bool = True,
    duplicate_velocity: bool = False,
) -> bytes:
    particle_ids = (0, 1)
    position_name = position_name or ("Pos" if position_type == 22 else "Posd")
    position_code = position_type if position_code is None else position_code
    arrays = [_array("Idp", 8, _raw_array(8, particle_ids))]
    if include_position:
        components = 3
        pos_payload = _raw_array(position_code, positions[: position_count * components])
        arrays.append(_array(position_name, position_code, pos_payload))
    if include_velocity:
        arrays.append(_array("Vel", velocity_code, _raw_array(velocity_code, velocities)))
        if duplicate_velocity:
            arrays.append(_array("Vel", velocity_code, _raw_array(velocity_code, velocities)))
    if include_density:
        arrays.append(_array("Rhop", density_code, _raw_array(density_code, densities)))
    part_values = (
        bi4_fixture._value("TimeStep", 12, struct.pack("<d", 0.0)),
        bi4_fixture._value("Npok", 8, struct.pack("<I", len(particle_ids))),
    )
    part = bi4_fixture._item("PART_0000", values=part_values, arrays=tuple(arrays))
    root_values = (
        bi4_fixture._value("CaseNp", 10, struct.pack("<Q", len(particle_ids))),
        bi4_fixture._value("CaseNfluid", 10, struct.pack("<Q", 1)),
        bi4_fixture._value("CaseNfixed", 10, struct.pack("<Q", 1)),
        bi4_fixture._value("CaseNmoving", 10, struct.pack("<Q", 0)),
        bi4_fixture._value("CaseNfloat", 10, struct.pack("<Q", 0)),
        bi4_fixture._value("MassFluid", 12, struct.pack("<d", 0.000421875)),
    )
    root = bi4_fixture._item("JPartDataBi4", values=root_values, children=(part,))
    title = decoder.FILE_PREFIX + b" " * (58 - len(decoder.FILE_PREFIX)) + b"\n\0"
    return title + b"\0\0\0\0" + root


def _scan_tmp(tmp_path, payload: bytes):
    path = tmp_path / "synthetic-state.bi4"
    path.write_bytes(payload)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    raw_sha = hashlib.sha256(payload).hexdigest()
    scan = decoder.scan_bi4_fd(fd, raw_sha)
    return fd, scan, raw_sha


def test_streams_posd_and_counts_nonfluid_nan_and_infinities(tmp_path) -> None:
    payload = _synthetic_bi4(
        position_type=23,
        positions=(1.0, 2.0, 3.0, float("nan"), 5.0, 6.0),
        velocities=(0.1, 0.2, 0.3, 0.4, float("inf"), 0.6),
        densities=(1000.0, float("-inf")),
    )
    fd, scan, raw_sha = _scan_tmp(tmp_path, payload)
    try:
        result = finite_scan.summarize_native_state_fd(fd, raw_sha, scan, case_np=2)
    finally:
        os.close(fd)

    assert [item["array_name"] for item in result] == ["Posd", "Vel", "Rhop"]
    assert [item["dtype"] for item in result] == ["<f8", "<f4", "<f4"]
    assert result[0]["shape"] == [2, 3]
    assert (result[0]["finite_count"], result[0]["nan_count"]) == (5, 1)
    assert (result[1]["finite_count"], result[1]["positive_infinity_count"]) == (5, 1)
    assert (result[2]["finite_count"], result[2]["negative_infinity_count"]) == (1, 1)
    assert all(item["required_state_values_finite"] is False for item in result)
    assert all(len(item["raw_array_sha256"]) == 64 for item in result)


def test_all_nonfinite_arrays_have_null_extrema(tmp_path) -> None:
    payload = _synthetic_bi4(
        positions=(float("nan"),) * 6,
        velocities=(float("inf"),) * 6,
        densities=(float("-inf"),) * 2,
    )
    fd, scan, raw_sha = _scan_tmp(tmp_path, payload)
    try:
        result = finite_scan.summarize_native_state_fd(fd, raw_sha, scan, case_np=2)
    finally:
        os.close(fd)

    for array in result:
        assert array["finite_count"] == 0
        assert array["minimum_finite_source_bits_le_hex"] is None
        assert array["minimum_finite_component_ordinal"] is None
        assert array["maximum_finite_source_bits_le_hex"] is None
        assert array["maximum_finite_component_ordinal"] is None


def test_rejects_case_np_above_the_frozen_particle_cap(tmp_path) -> None:
    payload = _synthetic_bi4()
    fd, scan, raw_sha = _scan_tmp(tmp_path, payload)
    try:
        with pytest.raises(finite_scan.NativeStateFiniteScanError, match="CaseNp"):
            finite_scan.summarize_native_state_fd(
                fd, raw_sha, scan, case_np=decoder.MAX_ARRAY_COUNT + 1,
            )
    finally:
        os.close(fd)


@pytest.mark.parametrize(("position_type", "dtype"), [(22, "<f4"), (23, "<f8")])
def test_preserves_position_source_dtype_and_bits(tmp_path, position_type: int, dtype: str) -> None:
    values = (-2.5, 3.25, 0.0, 4.5, 5.5, 6.5)
    payload = _synthetic_bi4(position_type=position_type, positions=values)
    fd, scan, raw_sha = _scan_tmp(tmp_path, payload)
    try:
        result = finite_scan.summarize_native_state_fd(fd, raw_sha, scan, case_np=2)
    finally:
        os.close(fd)

    position = result[0]
    assert position["dtype"] == dtype
    assert position["type_code"] == position_type
    assert position["minimum_finite_source_bits_le_hex"] == np.asarray([-2.5], dtype=dtype).tobytes().hex()
    assert position["maximum_finite_source_bits_le_hex"] == np.asarray([6.5], dtype=dtype).tobytes().hex()
    assert position["minimum_finite_component_ordinal"] == 0
    assert position["maximum_finite_component_ordinal"] == 5


def test_equal_signed_zero_extrema_keep_first_source_bits(tmp_path) -> None:
    payload = _synthetic_bi4(
        position_type=22,
        positions=(0.0, 1.0, 2.0, 3.0, 4.0, 5.0),
        densities=(-0.0, 0.0),
    )
    fd, scan, raw_sha = _scan_tmp(tmp_path, payload)
    try:
        result = finite_scan.summarize_native_state_fd(fd, raw_sha, scan, case_np=2)
    finally:
        os.close(fd)
    density = result[2]
    assert density["minimum_finite_source_bits_le_hex"] == "00000080"
    assert density["maximum_finite_source_bits_le_hex"] == "00000080"
    assert density["minimum_finite_component_ordinal"] == 0
    assert density["maximum_finite_component_ordinal"] == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"include_position": False},
        {"include_velocity": False},
        {"include_density": False},
        {"duplicate_velocity": True},
        {"position_count": 1},
        {"position_name": "Pos", "position_type": 22, "position_code": 23},
        {"velocity_code": 23},
        {"density_code": 12},
    ],
)
def test_rejects_missing_duplicate_count_or_type_mismatch(tmp_path, kwargs) -> None:
    payload = _synthetic_bi4(**kwargs)
    with pytest.raises((finite_scan.NativeStateFiniteScanError, decoder.Bi4FormatError)):
        fd = None
        try:
            fd, scan, raw_sha = _scan_tmp(tmp_path, payload)
            finite_scan.summarize_native_state_fd(fd, raw_sha, scan, case_np=2)
        finally:
            if fd is not None:
                os.close(fd)


@pytest.mark.parametrize("mutation", ["overwrite", "truncate"])
def test_rejects_source_mutation_during_scan(tmp_path, monkeypatch, mutation: str) -> None:
    payload = _synthetic_bi4()
    path = tmp_path / "synthetic-state.bi4"
    path.write_bytes(payload)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    writer = os.open(path, os.O_WRONLY)
    raw_sha = hashlib.sha256(payload).hexdigest()
    scan = decoder.scan_bi4_fd(fd, raw_sha)
    first = next(item for item in scan.arrays if item.name == "Posd")
    original_pread = os.pread
    mutated = False

    def changing_pread(read_fd: int, size: int, offset: int) -> bytes:
        nonlocal mutated
        data = original_pread(read_fd, size, offset)
        if read_fd == fd and offset == first.offset and not mutated:
            mutated = True
            if mutation == "overwrite":
                os.pwrite(writer, b"\x01", first.offset)
            else:
                os.ftruncate(writer, first.offset + 1)
        return data

    monkeypatch.setattr(finite_scan.os, "pread", changing_pread)
    try:
        with pytest.raises(finite_scan.NativeStateFiniteScanError):
            finite_scan.summarize_native_state_fd(fd, raw_sha, scan, case_np=2)
        assert mutated
    finally:
        os.close(writer)
        os.close(fd)


def test_array_reads_are_bounded_and_scalar_aligned(tmp_path, monkeypatch) -> None:
    payload = _synthetic_bi4(position_type=23)
    fd, scan, raw_sha = _scan_tmp(tmp_path, payload)
    arrays = [item for item in scan.arrays if item.name in {"Posd", "Vel", "Rhop"}]
    original_pread = os.pread
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(finite_scan, "STREAM_CHUNK_BYTES", 17)

    def recording_pread(read_fd: int, size: int, offset: int) -> bytes:
        if any(item.offset <= offset < item.offset + item.byte_count for item in arrays):
            calls.append((size, offset))
        return original_pread(read_fd, size, offset)

    monkeypatch.setattr(finite_scan.os, "pread", recording_pread)
    try:
        finite_scan.summarize_native_state_fd(fd, raw_sha, scan, case_np=2)
    finally:
        os.close(fd)

    assert calls
    for item in arrays:
        itemsize = decoder.TYPE_INFO[item.type_code][2] // (3 if item.type_code in (22, 23) else 1)
        array_calls = [(size, offset) for size, offset in calls
                       if item.offset <= offset < item.offset + item.byte_count]
        assert array_calls
        assert all(size <= 16 and (size % itemsize) == 0 for size, _ in array_calls)
