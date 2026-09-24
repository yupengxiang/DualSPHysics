from __future__ import annotations

import hashlib
import os
from pathlib import Path
import struct
import xml.etree.ElementTree as ET

import pytest

from scripts import f8_r008_safe_bi4_decoder_v1 as decoder


def _string(value: str | bytes) -> bytes:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return struct.pack("<I", len(raw)) + raw


def _value(name: str, type_code: int, payload: bytes) -> bytes:
    return _string(name) + struct.pack("<i", type_code) + payload


def _array(
    name: str,
    type_code: int,
    count: int,
    payload: bytes,
    *,
    declared_bytes: int | None = None,
    hidden: bool = False,
) -> tuple[bytes, int]:
    size = len(payload) if declared_bytes is None else declared_bytes
    definition = (
        _string(decoder.CODE_ARRAY)
        + _string(name)
        + struct.pack("<iiII", int(hidden), type_code, count, size)
    )
    return struct.pack("<I", len(definition)) + definition + payload, size


def _item(
    name: str,
    *,
    values: tuple[bytes, ...] = (),
    arrays: tuple[bytes, ...] = (),
    children: tuple[bytes, ...] = (),
    values_bytes_override: int | None = None,
    hidden: bool = False,
    hide_values: bool = False,
    float_format: str = "%.7E",
    double_format: str = "%.15E",
) -> bytes:
    values_block = b""
    if values:
        values_block = _string(decoder.CODE_VALUES) + struct.pack("<I", len(values)) + b"".join(values)
    values_size = len(values_block) if values_bytes_override is None else values_bytes_override
    definition = (
        _string(decoder.CODE_ITEM)
        + _string(name)
        + struct.pack("<ii", int(hidden), int(hide_values))
        + _string(float_format)
        + _string(double_format)
        + struct.pack("<III", len(arrays), len(children), values_size)
    )
    return (
        struct.pack("<I", len(definition))
        + definition
        + values_block
        + b"".join(arrays)
        + b"".join(children)
    )


def _frame_bytes(
    *,
    arrays: tuple[bytes, ...] | None = None,
    root_values: tuple[bytes, ...] | None = None,
    part_values: tuple[bytes, ...] | None = None,
    header_tail: bytes = b"\0\0\0\0",
    root_hidden: bool = False,
    part_hidden: bool = False,
    part_double_format: str = "%.15E",
) -> bytes:
    if arrays is None:
        arrays = (
            _array("Idp", 8, 2, struct.pack("<II", 0, 1))[0],
            _array("Posd", 23, 2, struct.pack("<6d", 0.1, 0.2, 0.3, 0.4, 0.5, 0.6))[0],
            _array("Vel", 22, 2, struct.pack("<6f", 1, 2, 3, 4, 5, 6))[0],
            _array("Rhop", 11, 2, struct.pack("<2f", 1000, 1001))[0],
        )
    if root_values is None:
        root_values = (
            _value("CaseNfixed", 10, struct.pack("<Q", 1)),
            _value("Gamma", 12, struct.pack("<d", 7.1)),
        )
    if part_values is None:
        part_values = (
            _value("Cpart", 8, struct.pack("<I", 0)),
            _value("TimeStep", 12, struct.pack("<d", 0.01)),
            _value("Npok", 8, struct.pack("<I", 2)),
            _value("Nout", 8, struct.pack("<I", 0)),
        )
    part = _item(
        "PART_0000",
        values=part_values,
        arrays=arrays,
        hidden=part_hidden,
        double_format=part_double_format,
    )
    root = _item("JPartDataBi4", values=root_values, children=(part,), hidden=root_hidden)
    title = decoder.FILE_PREFIX + b" " * (58 - len(decoder.FILE_PREFIX)) + b"\n\0"
    assert len(title) == 60
    return title + header_tail + root


def _put_input(root: Path, payload: bytes, name: str = "raw.bi4") -> tuple[Path, str]:
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_bytes(payload)
    return path, hashlib.sha256(payload).hexdigest()


def _open_dir(path: Path) -> int:
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)


def test_synthetic_r008_frame_scans_and_materializes_closed_output_tree(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    output_parent = tmp_path / "output"
    raw_root.mkdir()
    output_parent.mkdir(mode=0o700)
    payload = _frame_bytes()
    source, raw_sha = _put_input(raw_root, payload)

    raw_fd = _open_dir(raw_root)
    output_fd = _open_dir(output_parent)
    try:
        input_fd = decoder.open_regular_beneath(raw_fd, "raw.bi4")
        try:
            scan = decoder.scan_bi4_fd(input_fd, raw_sha)
            assert scan.input_bytes == len(payload)
            assert scan.root.name == "JPartDataBi4"
            assert scan.root.children[0].name == "PART_0000"
            assert {entry.name: entry.count for entry in scan.arrays} == {
                "Idp": 2,
                "Posd": 2,
                "Vel": 2,
                "Rhop": 2,
            }
            for entry in scan.arrays:
                assert payload[entry.offset : entry.offset + entry.byte_count]

            receipt = decoder.decode_bi4_fd(input_fd, raw_sha, output_fd, "native")
        finally:
            os.close(input_fd)
    finally:
        os.close(raw_fd)
        os.close(output_fd)

    assert receipt["status"] == "safe_decode_complete"
    assert receipt["tree_closed"] is True
    assert receipt["execution_authority"] == {
        "native_binary_invoked": False,
        "gencase_invoked": False,
        "solver_invoked": False,
        "worker_started": False,
        "gpu_invoked": False,
        "queue_mutation": 0,
        "qualification_credit": 0,
    }
    assert {entry["path"] for entry in receipt["arrays"]} == {
        "PART_0000/Idp.bin",
        "PART_0000/Posd.bin",
        "PART_0000/Vel.bin",
        "PART_0000/Rhop.bin",
    }
    assert sorted(path.name for path in (output_parent / "native" / "PART_0000").iterdir()) == [
        "Idp.bin",
        "Posd.bin",
        "Rhop.bin",
        "Vel.bin",
    ]
    assert (output_parent / "native" / "PART_0000" / "Posd.bin").read_bytes() == struct.pack(
        "<6d", 0.1, 0.2, 0.3, 0.4, 0.5, 0.6
    )
    xml_root = ET.parse(output_parent / "native.xml").getroot()
    assert xml_root.get("fmt") == "JBinaryData"
    root_item = xml_root.find("item")
    assert root_item is not None and root_item.get("name") == "JPartDataBi4"
    part_item = root_item.find("item")
    assert part_item is not None and part_item.get("name") == "PART_0000"
    assert part_item.find("double[@name='TimeStep']").get("v") == "1.000000000000000E-02"


def test_empty_part_array_set_still_has_an_exactly_closed_directory_tree(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    output_parent = tmp_path / "output"
    raw_root.mkdir()
    output_parent.mkdir(mode=0o700)
    _, raw_sha = _put_input(raw_root, _frame_bytes(arrays=()))
    raw_fd = _open_dir(raw_root)
    output_fd = _open_dir(output_parent)
    try:
        receipt = decoder.decode_bi4_beneath(raw_fd, "raw.bi4", raw_sha, output_fd, "native")
    finally:
        os.close(raw_fd)
        os.close(output_fd)
    assert receipt["arrays"] == []
    assert list((output_parent / "native" / "PART_0000").iterdir()) == []


@pytest.mark.parametrize(
    "bad_array,match",
    [
        (_array("../escape", 8, 1, struct.pack("<I", 0))[0], "path component"),
        (_array("Huge", 8, decoder.MAX_ARRAY_COUNT + 1, b"")[0], "element count exceeds"),
        (_array("Short", 8, 2, struct.pack("<I", 1), declared_bytes=4)[0], "count/byte-size"),
    ],
)
def test_rejected_tree_or_array_never_creates_output(
    tmp_path: Path, bad_array: bytes, match: str
) -> None:
    raw_root = tmp_path / "raw"
    output_parent = tmp_path / "output"
    raw_root.mkdir()
    output_parent.mkdir(mode=0o700)
    _, raw_sha = _put_input(raw_root, _frame_bytes(arrays=(bad_array,)))
    raw_fd = _open_dir(raw_root)
    output_fd = _open_dir(output_parent)
    try:
        with pytest.raises(decoder.Bi4FormatError, match=match):
            decoder.decode_bi4_beneath(raw_fd, "raw.bi4", raw_sha, output_fd, "native")
    finally:
        os.close(raw_fd)
        os.close(output_fd)
    assert list(output_parent.iterdir()) == []


@pytest.mark.parametrize("header_tail", [b"\x01\0\0\0", b"\x0a\x01\0\0"])
def test_unsupported_endian_or_si64_header_is_rejected_prewrite(
    tmp_path: Path, header_tail: bytes
) -> None:
    raw_root = tmp_path / "raw"
    output_parent = tmp_path / "output"
    raw_root.mkdir()
    output_parent.mkdir(mode=0o700)
    _, raw_sha = _put_input(raw_root, _frame_bytes(header_tail=header_tail))
    raw_fd = _open_dir(raw_root)
    output_fd = _open_dir(output_parent)
    try:
        with pytest.raises(decoder.Bi4FormatError, match="little-endian|SI64"):
            decoder.decode_bi4_beneath(raw_fd, "raw.bi4", raw_sha, output_fd, "native")
    finally:
        os.close(raw_fd)
        os.close(output_fd)
    assert list(output_parent.iterdir()) == []


def test_input_hash_and_no_follow_path_checks_precede_output(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    output_parent = tmp_path / "output"
    raw_root.mkdir()
    output_parent.mkdir(mode=0o700)
    _source, raw_sha = _put_input(raw_root, _frame_bytes())
    (raw_root / "alias.bi4").symlink_to("raw.bi4")
    raw_fd = _open_dir(raw_root)
    output_fd = _open_dir(output_parent)
    try:
        with pytest.raises(OSError):
            decoder.open_regular_beneath(raw_fd, "alias.bi4")
        with pytest.raises(decoder.Bi4FormatError, match="unsafe or unsupported path component"):
            decoder.open_regular_beneath(raw_fd, "../raw.bi4")
        with pytest.raises(decoder.Bi4FormatError, match="hash does not match"):
            decoder.decode_bi4_beneath(raw_fd, "raw.bi4", "0" * 64, output_fd, "native")
    finally:
        os.close(raw_fd)
        os.close(output_fd)
    assert list(output_parent.iterdir()) == []


def test_hardlinked_raw_input_is_rejected(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    source, _ = _put_input(raw_root, _frame_bytes())
    os.link(source, raw_root / "hardlink.bi4")
    raw_fd = _open_dir(raw_root)
    try:
        with pytest.raises(decoder.Bi4FormatError, match="exactly one hard link"):
            decoder.open_regular_beneath(raw_fd, "raw.bi4")
    finally:
        os.close(raw_fd)


def test_max_length_array_name_fits_the_bounded_sidecar_filename(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    output_parent = tmp_path / "output"
    raw_root.mkdir()
    output_parent.mkdir(mode=0o700)
    long_name = "A" * decoder.MAX_NAME_BYTES
    payload = _frame_bytes(arrays=(_array(long_name, 8, 1, struct.pack("<I", 5))[0],))
    _, raw_sha = _put_input(raw_root, payload)
    raw_fd = _open_dir(raw_root)
    output_fd = _open_dir(output_parent)
    try:
        receipt = decoder.decode_bi4_beneath(raw_fd, "raw.bi4", raw_sha, output_fd, "native")
    finally:
        os.close(raw_fd)
        os.close(output_fd)
    filename = long_name + ".bin"
    assert len(filename) == decoder.MAX_NAME_BYTES + 4
    assert (output_parent / "native" / "PART_0000" / filename).read_bytes() == struct.pack("<I", 5)
    assert receipt["arrays"][0]["path"] == f"PART_0000/{filename}"


def test_xml_invalid_metadata_character_is_rejected_before_output(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    output_parent = tmp_path / "output"
    raw_root.mkdir()
    output_parent.mkdir(mode=0o700)
    values = (_value("Label", 1, _string("not-xml\0-safe")),)
    _, raw_sha = _put_input(raw_root, _frame_bytes(root_values=values))
    raw_fd = _open_dir(raw_root)
    output_fd = _open_dir(output_parent)
    try:
        with pytest.raises(decoder.Bi4FormatError, match="XML 1.0-invalid"):
            decoder.decode_bi4_beneath(raw_fd, "raw.bi4", raw_sha, output_fd, "native")
    finally:
        os.close(raw_fd)
        os.close(output_fd)
    assert list(output_parent.iterdir()) == []


def test_item_and_array_visibility_flags_remain_independent(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    output_parent = tmp_path / "output"
    raw_root.mkdir()
    output_parent.mkdir(mode=0o700)
    arrays = (
        _array("Idp", 8, 2, struct.pack("<II", 0, 1), hidden=True)[0],
        _array("Posd", 23, 2, struct.pack("<6d", 0, 0, 0, 1, 1, 1))[0],
        _array("Vel", 22, 2, struct.pack("<6f", 0, 0, 0, 1, 1, 1))[0],
        _array("Rhop", 11, 2, struct.pack("<2f", 1000, 1000))[0],
    )
    _, raw_sha = _put_input(raw_root, _frame_bytes(arrays=arrays, root_hidden=True))
    raw_fd = _open_dir(raw_root)
    output_fd = _open_dir(output_parent)
    try:
        decoder.decode_bi4_beneath(raw_fd, "raw.bi4", raw_sha, output_fd, "native")
    finally:
        os.close(raw_fd)
        os.close(output_fd)
    root_item = ET.parse(output_parent / "native.xml").getroot().find("item")
    assert root_item is not None and root_item.get("hide") == "1"
    part_item = root_item.find("item")
    assert part_item is not None and part_item.get("hide") == "0"
    assert part_item.find("array_uint[@name='Idp']").get("hide") == "1"
    assert part_item.find("array_double3[@name='Posd']").get("hide") == "0"


def test_noncanonical_numeric_format_is_rejected_before_output(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    output_parent = tmp_path / "output"
    raw_root.mkdir()
    output_parent.mkdir(mode=0o700)
    _, raw_sha = _put_input(raw_root, _frame_bytes(part_double_format="%.6f"))
    raw_fd = _open_dir(raw_root)
    output_fd = _open_dir(output_parent)
    try:
        with pytest.raises(decoder.Bi4FormatError, match="numeric metadata format"):
            decoder.decode_bi4_beneath(raw_fd, "raw.bi4", raw_sha, output_fd, "native")
    finally:
        os.close(raw_fd)
        os.close(output_fd)
    assert list(output_parent.iterdir()) == []


def test_float_double_and_vector_metadata_use_pinned_jbd_formats(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    output_parent = tmp_path / "output"
    raw_root.mkdir()
    output_parent.mkdir(mode=0o700)
    values = (
        _value("FloatValue", 11, struct.pack("<f", 0.125)),
        _value("FloatVector", 22, struct.pack("<fff", 0.125, -0.25, 1.0)),
        _value("DoubleVector", 23, struct.pack("<ddd", 0.125, -0.25, 1.0)),
    )
    _, raw_sha = _put_input(raw_root, _frame_bytes(part_values=values))
    raw_fd = _open_dir(raw_root)
    output_fd = _open_dir(output_parent)
    try:
        decoder.decode_bi4_beneath(raw_fd, "raw.bi4", raw_sha, output_fd, "native")
    finally:
        os.close(raw_fd)
        os.close(output_fd)
    part_item = ET.parse(output_parent / "native.xml").getroot().find("item/item")
    assert part_item is not None
    assert part_item.find("float[@name='FloatValue']").get("v") == "1.2500000E-01"
    float_vector = part_item.find("float3[@name='FloatVector']")
    assert float_vector is not None
    assert (float_vector.get("x"), float_vector.get("y"), float_vector.get("z")) == (
        "1.2500000E-01",
        "-2.5000000E-01",
        "1.0000000E+00",
    )
    double_vector = part_item.find("double3[@name='DoubleVector']")
    assert double_vector is not None
    assert (double_vector.get("x"), double_vector.get("y"), double_vector.get("z")) == (
        "1.250000000000000E-01",
        "-2.500000000000000E-01",
        "1.000000000000000E+00",
    )


def test_writable_shared_output_parent_is_rejected_prewrite(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    output_parent = tmp_path / "output"
    raw_root.mkdir()
    output_parent.mkdir(mode=0o700)
    output_parent.chmod(0o775)
    _, raw_sha = _put_input(raw_root, _frame_bytes())
    raw_fd = _open_dir(raw_root)
    output_fd = _open_dir(output_parent)
    try:
        with pytest.raises(decoder.Bi4FormatError, match="not group/world-writable"):
            decoder.decode_bi4_beneath(raw_fd, "raw.bi4", raw_sha, output_fd, "native")
    finally:
        os.close(raw_fd)
        os.close(output_fd)
        output_parent.chmod(0o755)
    assert list(output_parent.iterdir()) == []


def test_raw_input_mutation_during_array_copy_is_detected(tmp_path: Path, monkeypatch) -> None:
    raw_root = tmp_path / "raw"
    output_parent = tmp_path / "output"
    raw_root.mkdir()
    output_parent.mkdir(mode=0o700)
    probe_payload = struct.pack("<" + "d" * 1536, *[float(value) for value in range(1536)])
    arrays = (
        _array("Idp", 8, 2, struct.pack("<II", 0, 1))[0],
        _array("Posd", 23, 2, struct.pack("<6d", 0, 0, 0, 1, 1, 1))[0],
        _array("Vel", 22, 2, struct.pack("<6f", 0, 0, 0, 1, 1, 1))[0],
        _array("Rhop", 11, 2, struct.pack("<2f", 1000, 1000))[0],
        _array("Probe", 23, 512, probe_payload)[0],
    )
    source, raw_sha = _put_input(raw_root, _frame_bytes(arrays=arrays))
    raw_fd = _open_dir(raw_root)
    output_fd = _open_dir(output_parent)
    original_copy = decoder._copy_array
    original_pread = decoder.os.pread
    mutated = False

    def copy_then_mutate(input_fd: int, array, destination_fd: int):
        nonlocal mutated
        if array.name != "Probe":
            return original_copy(input_fd, array, destination_fd)
        original_chunk_bytes = decoder.IO_CHUNK_BYTES
        decoder.IO_CHUNK_BYTES = 16
        mutation_fd = os.open(source, os.O_WRONLY | os.O_NOFOLLOW)

        def pread_mutating(fd: int, size: int, offset: int) -> bytes:
            nonlocal mutated
            result = original_pread(fd, size, offset)
            if fd == input_fd and offset == array.offset and not mutated:
                os.pwrite(mutation_fd, b"\x01", array.offset + 32)
                os.fsync(mutation_fd)
                mutated = True
            return result

        monkeypatch.setattr(decoder.os, "pread", pread_mutating)
        try:
            return original_copy(input_fd, array, destination_fd)
        finally:
            monkeypatch.setattr(decoder.os, "pread", original_pread)
            decoder.IO_CHUNK_BYTES = original_chunk_bytes
            os.close(mutation_fd)

    monkeypatch.setattr(decoder, "_copy_array", copy_then_mutate)
    try:
        with pytest.raises(decoder.Bi4FormatError, match="changed during safe materialization"):
            decoder.decode_bi4_beneath(raw_fd, "raw.bi4", raw_sha, output_fd, "native")
    finally:
        os.close(raw_fd)
        os.close(output_fd)
    assert mutated
    # A detected mid-copy mutation is retained as failed one-shot evidence;
    # it must never be reported as a successful closed decode.
    assert (output_parent / "native").is_dir()
    assert (output_parent / "native.xml").is_file()


def test_duplicate_value_names_and_invalid_header_padding_are_rejected(tmp_path: Path) -> None:
    duplicate_values = (
        _value("Gamma", 12, struct.pack("<d", 7.1)),
        _value("Gamma", 12, struct.pack("<d", 7.2)),
    )
    payload = bytearray(_frame_bytes(root_values=duplicate_values))
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    path, raw_sha = _put_input(raw_root, bytes(payload))
    raw_fd = _open_dir(raw_root)
    try:
        input_fd = decoder.open_regular_beneath(raw_fd, "raw.bi4")
        try:
            with pytest.raises(decoder.Bi4FormatError, match="duplicate sibling BI4 value"):
                decoder.scan_bi4_fd(input_fd, raw_sha)
        finally:
            os.close(input_fd)
        padded = bytearray(_frame_bytes())
        padded[len(decoder.FILE_PREFIX)] = ord("X")
        path.write_bytes(padded)
        input_fd = decoder.open_regular_beneath(raw_fd, "raw.bi4")
        try:
            with pytest.raises(decoder.Bi4FormatError, match="filecode padding"):
                decoder.scan_bi4_fd(input_fd, hashlib.sha256(padded).hexdigest())
        finally:
            os.close(input_fd)
    finally:
        os.close(raw_fd)
