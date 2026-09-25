from __future__ import annotations

import hashlib
import os
import struct

import pytest

from scripts import f8_r008_part_extra_finite_inventory_v1 as inventory
from scripts import f8_r008_safe_bi4_decoder_v1 as decoder
from tests import test_f8_r008_native_state_finite_scan_v1 as state_fixture
from tests import test_f8_r008_per_case_bundle_verifier_v1 as bi4_fixture


def _synthetic_part_extra(
    *,
    part: int = 2,
    case_nbound: int = 3,
    case_nfloat: int = 1,
    use_normals_ft: bool = False,
    timestep: float = 0.125,
    normals: tuple[float, ...] | None = None,
    format_version: int = inventory.FORMAT_VERSION,
    unknown_metadata: bool = False,
    unknown_array: bool = False,
    root_name: str = "JPartExtraBi4",
) -> bytes:
    count = case_nbound if use_normals_ft else case_nbound - case_nfloat
    if normals is None:
        normals = tuple(float(index + 1) for index in range(count * 3))
    values = [
        bi4_fixture._value("AppName", 1, bi4_fixture._string("F8-R008-test")),
        bi4_fixture._value("FormatVer", 8, struct.pack("<I", format_version)),
        bi4_fixture._value("CaseNbound", 8, struct.pack("<I", case_nbound)),
        bi4_fixture._value("CaseNfloat", 8, struct.pack("<I", case_nfloat)),
        bi4_fixture._value("Cpart", 7, struct.pack("<i", part)),
        bi4_fixture._value("Step", 8, struct.pack("<I", 17)),
        bi4_fixture._value("TimeStep", 12, struct.pack("<d", timestep)),
        bi4_fixture._value("UseNormalsFt", 2, struct.pack("<i", int(use_normals_ft))),
    ]
    if unknown_metadata:
        values.append(bi4_fixture._value("FutureFloat", 12, struct.pack("<d", 4.0)))
    payload = struct.pack(f"<{len(normals)}f", *normals)
    arrays = [state_fixture._array("Normals", 22, payload)]
    if unknown_array:
        arrays.append(state_fixture._array("FutureArray", 22, struct.pack("<3f", 1, 2, 3)))
    root = bi4_fixture._item(root_name, values=tuple(values), arrays=tuple(arrays))
    title = inventory.FILE_PREFIX + b" " * (58 - len(inventory.FILE_PREFIX)) + b"\n\0"
    return title + b"\0\0\0\0" + root


def _open_tmp(tmp_path, payload: bytes):
    path = tmp_path / "PartExtra_0002.bi4"
    path.write_bytes(payload)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    return fd, hashlib.sha256(payload).hexdigest()


def _summarize(fd: int, digest: str, *, expected_part: int = 2,
               expected_case_nbound: int = 3, expected_case_nfloat: int = 1):
    return inventory.summarize_part_extra_fd(
        fd, digest, expected_part=expected_part,
        expected_case_nbound=expected_case_nbound,
        expected_case_nfloat=expected_case_nfloat,
    )


def test_scans_all_part_extra_normals_and_float_metadata(tmp_path) -> None:
    payload = _synthetic_part_extra()
    fd, digest = _open_tmp(tmp_path, payload)
    try:
        result = _summarize(fd, digest)
    finally:
        os.close(fd)

    assert result["status"] == "diagnostic_only_not_adjudicated"
    assert result["source_part_extra_sha256"] == digest
    assert result["arrays"][0]["shape"] == [2, 3]
    assert result["arrays"][0]["finite_component_count"] == 6
    assert result["arrays"][0]["all_components_finite"] is True
    assert result["floating_metadata"]["finite_count"] == 1
    assert result["floating_value_inventory"]["finite_count"] == 7
    assert result["floating_value_inventory"]["all_floating_values_finite"] is True
    assert result["bundle_membership_verified"] is False
    assert result["bundle_output_completeness_verified"] is False
    assert result["qualification_credit"] == 0


def test_normals_population_includes_floating_boundary_when_enabled(tmp_path) -> None:
    payload = _synthetic_part_extra(use_normals_ft=True)
    fd, digest = _open_tmp(tmp_path, payload)
    try:
        result = _summarize(fd, digest)
    finally:
        os.close(fd)
    assert result["arrays"][0]["shape"] == [3, 3]
    assert result["arrays"][0]["finite_component_count"] == 9
    assert result["metadata"]["use_normals_ft"] is True


def test_counts_nonfinite_normals_and_timestep_without_json_nonfinite_values(tmp_path) -> None:
    payload = _synthetic_part_extra(
        timestep=float("inf"), normals=(1.0, float("nan"), 3.0, 4.0, 5.0, 6.0),
    )
    fd, digest = _open_tmp(tmp_path, payload)
    try:
        result = _summarize(fd, digest)
    finally:
        os.close(fd)
    assert result["arrays"][0]["nonfinite_component_count"] == 1
    assert result["arrays"][0]["all_components_finite"] is False
    assert result["floating_metadata"]["nonfinite_count"] == 1
    assert result["metadata"]["time_step_s"] is None
    assert result["floating_value_inventory"]["nonfinite_count"] == 2
    assert result["floating_value_inventory"]["all_floating_values_finite"] is False


@pytest.mark.parametrize(
    ("kwargs", "claims", "match"),
    [
        ({"part": 3}, {}, "Cpart differs"),
        ({}, {"expected_case_nbound": 4}, "populations differ"),
        ({"format_version": inventory.FORMAT_VERSION + 1}, {}, "FormatVer differs"),
        ({"unknown_metadata": True}, {}, "unknown fields"),
        ({"unknown_array": True}, {}, "classified Normals array"),
        ({"root_name": "JPartDataBi4"}, {}, "JPartExtraBi4 root"),
        ({"use_normals_ft": True, "case_nfloat": 0}, {"expected_case_nfloat": 0}, "cannot be true"),
    ],
)
def test_rejects_mismatched_part_extra_contract(tmp_path, kwargs, claims, match) -> None:
    payload = _synthetic_part_extra(**kwargs)
    fd, digest = _open_tmp(tmp_path, payload)
    try:
        with pytest.raises(inventory.PartExtraFiniteInventoryError, match=match):
            _summarize(fd, digest, **claims)
    finally:
        os.close(fd)


def test_rejects_wrong_held_bytes_digest(tmp_path) -> None:
    fd, _digest = _open_tmp(tmp_path, _synthetic_part_extra())
    try:
        with pytest.raises(inventory.PartExtraFiniteInventoryError, match="hash"):
            _summarize(fd, "0" * 64)
    finally:
        os.close(fd)


def test_rejects_non_normals_array_type_and_extent(tmp_path) -> None:
    payload = _synthetic_part_extra(normals=(1.0, 2.0, 3.0))
    fd, digest = _open_tmp(tmp_path, payload)
    try:
        with pytest.raises(inventory.PartExtraFiniteInventoryError, match="dtype or population"):
            _summarize(fd, digest)
    finally:
        os.close(fd)


def test_rejects_part_extra_mutation_during_finite_scan(tmp_path, monkeypatch) -> None:
    payload = _synthetic_part_extra()
    fd, digest = _open_tmp(tmp_path, payload)
    writer = os.open(tmp_path / "PartExtra_0002.bi4", os.O_WRONLY)
    root, _size, _raw_hash, _identity = inventory._scan_part_extra_fd(fd, digest)
    array_offset = root.arrays[0].offset
    original_pread = os.pread
    mutated = False

    def mutate_after_array_read(read_fd: int, size: int, offset: int) -> bytes:
        nonlocal mutated
        data = original_pread(read_fd, size, offset)
        if read_fd == fd and offset == array_offset and not mutated:
            os.pwrite(writer, b"\x01", array_offset)
            mutated = True
        return data

    monkeypatch.setattr(inventory.decoder.os, "pread", mutate_after_array_read)
    try:
        with pytest.raises(inventory.PartExtraFiniteInventoryError, match="changed during finite-value scan"):
            _summarize(fd, digest)
        assert mutated
    finally:
        os.close(writer)
        os.close(fd)
