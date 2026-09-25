from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
import struct

import pytest

from scripts import f8_r008_motion_float_finite_inventory_v1 as inventory
from scripts import f8_r008_safe_bi4_decoder_v1 as bi4


def _string(value: str) -> bytes:
    raw = value.encode("utf-8")
    return struct.pack("<I", len(raw)) + raw


def _value(name: str, type_code: int, payload: bytes) -> bytes:
    return _string(name) + struct.pack("<i", type_code) + payload


def _array(name: str, type_code: int, payload: bytes, *, hidden: int = 0) -> bytes:
    sizes = {6: 2, 8: 4, 11: 4, 12: 8, 22: 12, 23: 24}
    size = sizes[type_code]
    assert len(payload) % size == 0
    count = len(payload) // size
    definition = (
        _string(bi4.CODE_ARRAY.decode("ascii")) + _string(name)
        + struct.pack("<iiII", hidden, type_code, count, len(payload))
    )
    return struct.pack("<I", len(definition)) + definition + payload


def _item(
    name: str,
    *,
    values: tuple[bytes, ...] = (),
    arrays: tuple[bytes, ...] = (),
    hidden: int = 0,
) -> bytes:
    values_block = b""
    if values:
        values_block = (
            _string(bi4.CODE_VALUES.decode("ascii"))
            + struct.pack("<I", len(values)) + b"".join(values)
        )
    definition = (
        _string(bi4.CODE_ITEM.decode("ascii")) + _string(name)
        + struct.pack("<ii", hidden, 0) + _string("%.7E") + _string("%.15E")
        + struct.pack("<III", len(arrays), 0, len(values_block))
    )
    return struct.pack("<I", len(definition)) + definition + values_block + b"".join(arrays)


def _v_text(name: str, value: str) -> bytes:
    return _value(name, 1, _string(value))


def _v_bool(name: str, value: bool) -> bytes:
    return _value(name, 2, struct.pack("<i", int(value)))


def _v_ushort(name: str, value: int) -> bytes:
    return _value(name, 6, struct.pack("<H", value))


def _v_uint(name: str, value: int) -> bytes:
    return _value(name, 8, struct.pack("<I", value))


def _v_double(name: str, value: float) -> bytes:
    return _value(name, 12, struct.pack("<d", value))


def _pack(fmt: str, values) -> bytes:
    return struct.pack("<" + fmt * len(values), *values)


def _motion_payload(
    basename: str = "PartMotionRef.ibi4",
    *,
    layout: str = "single",
    timeout: float = 0.25,
    timestep: float = 0.125,
    nonfinite_pos: bool = False,
    root_name: str = "JPartMotRefBi4",
    main_file: bool | None = None,
    extra_root_value: bytes | None = None,
    wrong_root_array: bool = False,
    parts: tuple[bytes, ...] | None = None,
) -> bytes:
    if main_file is None:
        main_file = basename == "PartMotionRef.ibi4"
    values = [
        _v_text("AppName", "DualSPHysics synthetic"),
        _v_uint("FormatVer", inventory.FORMAT_VERSION),
        _v_bool("MainFile", main_file),
        _v_double("TimeOut", timeout),
        _v_ushort("MkBoundFirst", 10),
        _v_uint("MkMovingCount", 1),
        _v_uint("MkFloatCount", 0),
        _v_uint("MkCount", 1),
    ]
    if extra_root_value is not None:
        values.append(extra_root_value)
    arrays = [
        _array("MkBound", 6, _pack("H", [10])),
        _array("Nid", 8, _pack("I", [3])),
        _array("Id", 8, _pack("I", [0, 1, 2])),
        _array("Ps", 23, _pack("d", [1, 2, 3, 4, 5, 6, 7, 8, 9])),
        _array("Dis", 12, _pack("d", [0.1, 0.2, 0.3])),
    ]
    if wrong_root_array:
        arrays[-1] = _array("Dis", 11, _pack("f", [0.1, 0.2, 0.3]))
    root = _item(root_name, values=tuple(values), arrays=tuple(arrays))
    if parts is None:
        if layout == "single":
            part_arrays = (_array("PosRef", 23, _pack("d", [1, 2, 3, 4, 5, 6, 7, 8, 9])),)
            part_values = (
                _v_uint("Cpart", 0), _v_double("TimeStep", timestep), _v_uint("Step", 9),
            )
        else:
            part_arrays = (
                _array("TimeStep", 12, _pack("d", [timestep, timestep + 0.125])),
                _array("Step", 8, _pack("I", [9, 18])),
                _array("PosRef", 23, _pack("d", [float(i) for i in range(18)])),
            )
            part_values = (_v_uint("Cpart", 0), _v_uint("Count", 2))
        if nonfinite_pos:
            pos = [float(i) for i in range(9 if layout == "single" else 18)]
            pos[4] = float("nan")
            if layout == "single":
                part_arrays = (_array("PosRef", 23, _pack("d", pos)),)
            else:
                part_arrays = (*part_arrays[:2], _array("PosRef", 23, _pack("d", pos)))
        parts = (_item("PART_0000", values=part_values, arrays=part_arrays, hidden=1),)
    prefix = b"#FileJBD " + inventory.FILECODES[basename].encode("ascii")
    header = prefix + b" " * (58 - len(prefix)) + b"\n\0\0\0\0\0"
    assert len(header) == bi4.HEADER_BYTES
    return header + root + b"".join(parts)


def _float_payload(
    basename: str = "PartFloatInfo.ibi4",
    *,
    layout: str = "single",
    fpt_count: int = 0,
    timeout: float = 0.5,
    timestep: float = 0.25,
    nonfinite_root: bool = False,
    nonfinite_body: bool = False,
    nonfinite_force: bool = False,
    root_name: str = "JPartFloatInfoBi4",
    main_file: bool | None = None,
    extra_part_array: bytes | None = None,
    omit_force_array: str | None = None,
    append_count: int = 1,
) -> bytes:
    if main_file is None:
        main_file = basename == "PartFloatInfo.ibi4"
    root_values = (
        _v_text("AppName", "DualSPHysics synthetic"),
        _v_uint("FormatVer", inventory.FORMAT_VERSION),
        _v_bool("MainFile", main_file),
        _v_double("TimeOut", timeout),
        _v_ushort("MkBoundFirst", 10),
        _v_uint("FtCount", 2),
        _v_uint("FptCount", fpt_count),
    )
    masses = [1.5, 2.5]
    if nonfinite_root:
        masses[1] = float("nan")
    root_arrays = (
        _array("MkBound", 6, _pack("H", [10, 11])),
        _array("Beginp", 8, _pack("I", [2, 8])),
        _array("Countp", 8, _pack("I", [6, 9])),
        _array("Mass", 11, _pack("f", masses)),
        _array("Massp", 11, _pack("f", [0.5, 0.75])),
        _array("Radius", 11, _pack("f", [0.25, 0.5])),
    )
    root = _item(root_name, values=root_values, arrays=root_arrays)
    body_count = 2 if layout == "batch" else 1
    body_arrays = []
    for name, (type_code, fmt, components) in inventory.FLOAT_BODY_ARRAYS.items():
        values = [float(i + 1) for i in range(body_count * 2 * components)]
        if nonfinite_body and name == "center":
            values[5] = float("inf")
        body_arrays.append(_array(name, type_code, _pack(fmt[-1], values)))
    if fpt_count:
        force_count = body_count * fpt_count
        force_values = {
            "FptMkbound": _array("FptMkbound", 6, _pack("H", [12] * force_count)),
            "FptPos": _array("FptPos", 23, _pack("d", [0.1] * (force_count * 3))),
            "FptForce": _array(
                "FptForce", 22,
                _pack("f", [float("inf") if nonfinite_force and i == 2 else 0.2
                             for i in range(force_count * 3)]),
            ),
        }
        if omit_force_array is not None:
            force_values.pop(omit_force_array)
        body_arrays.extend(force_values.values())
    if layout == "batch":
        body_arrays.extend((
            _array("TimeStep", 12, _pack("d", [timestep, timestep + 0.25])),
            _array("Step", 8, _pack("I", [7, 14])),
        ))
    if extra_part_array is not None:
        body_arrays.append(extra_part_array)
    parts = []
    for part_number in range(append_count):
        if layout == "single":
            part_values = (
                _v_uint("Cpart", part_number),
                _v_double("TimeStep", timestep + 0.25 * part_number),
                _v_uint("Step", 7 + part_number),
            )
        else:
            part_values = (_v_uint("Cpart", part_number), _v_uint("Count", body_count))
        parts.append(_item(f"PART_{part_number:04d}", values=part_values,
                           arrays=tuple(body_arrays), hidden=1))
    prefix = b"#FileJBD " + inventory.FILECODES[basename].encode("ascii")
    header = prefix + b" " * (58 - len(prefix)) + b"\n\0\0\0\0\0"
    assert len(header) == bi4.HEADER_BYTES
    return header + root + b"".join(parts)


def _held_file(tmp_path: Path, basename: str, payload: bytes) -> tuple[int, str, Path]:
    path = tmp_path / basename
    path.write_bytes(payload)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    return fd, hashlib.sha256(payload).hexdigest(), path


def _summarize(fd: int, basename: str, digest: str) -> dict:
    return inventory.summarize_motion_float_fd(fd, basename, digest)


@pytest.mark.parametrize("basename", ["PartMotionRef.ibi4", "PartMotionRef2.ibi4"])
@pytest.mark.parametrize("layout", ["single", "batch"])
def test_motion_main_and_extra_single_batch_layouts_are_scanned(tmp_path, basename, layout):
    payload = _motion_payload(basename, layout=layout)
    fd, digest, _path = _held_file(tmp_path, basename, payload)
    try:
        result = _summarize(fd, basename, digest)
    finally:
        os.close(fd)
    assert result["status"] == "diagnostic_only_not_adjudicated"
    assert result["metadata"]["family"] == "PartMotionRef"
    assert result["part_items"] == [{
        "item": "PART_0000", "cpart": 0,
        "layout": layout, "record_count": 1 if layout == "single" else 2,
    }]
    assert result["floating_value_inventory"]["nonfinite_component_count"] == 0
    assert result["floating_value_inventory"]["all_floating_components_finite"] is True
    assert result["interpretation"]["qualification_credit"] == 0
    assert result["interpretation"]["native_integrity_eligible"] is False


@pytest.mark.parametrize("basename", ["PartFloatInfo.ibi4", "PartFloatInfo2.ibi4"])
@pytest.mark.parametrize("layout", ["single", "batch"])
@pytest.mark.parametrize("fpt_count", [0, 2])
def test_float_main_extra_single_batch_and_conditional_force_points(
    tmp_path, basename, layout, fpt_count,
):
    payload = _float_payload(basename, layout=layout, fpt_count=fpt_count)
    fd, digest, _path = _held_file(tmp_path, basename, payload)
    try:
        result = _summarize(fd, basename, digest)
    finally:
        os.close(fd)
    inv = result["floating_value_inventory"]
    assert result["metadata"]["family"] == "PartFloatInfo"
    assert result["metadata"]["fpt_count"] == fpt_count
    assert result["part_items"][0]["layout"] == layout
    assert result["part_items"][0]["record_count"] == (2 if layout == "batch" else 1)
    assert inv["all_floating_components_finite"] is True
    assert inv["nonfinite_component_count"] == 0
    assert ("FptForce" in {entry["name"] for entry in inv["arrays"]}) is bool(fpt_count)


def test_valid_appended_float_stream_can_exceed_single_frame_array_cap(tmp_path):
    payload = _float_payload(fpt_count=2, append_count=6)
    fd, digest, _path = _held_file(tmp_path, "PartFloatInfo.ibi4", payload)
    try:
        result = _summarize(fd, "PartFloatInfo.ibi4", digest)
    finally:
        os.close(fd)
    assert len(result["part_items"]) == 6
    assert result["floating_value_inventory"]["all_floating_components_finite"] is True


def test_valid_motion_stream_can_exceed_single_frame_array_cap(tmp_path):
    parts = tuple(
        _item(
            f"PART_{part:04d}",
            values=(_v_uint("Cpart", part), _v_double("TimeStep", part * 0.1),
                    _v_uint("Step", part)),
            arrays=(_array("PosRef", 23, _pack("d", [float(part)] * 9)),),
            hidden=1,
        )
        for part in range(60)
    )
    payload = _motion_payload(parts=parts)
    fd, digest, _path = _held_file(tmp_path, "PartMotionRef.ibi4", payload)
    try:
        result = _summarize(fd, "PartMotionRef.ibi4", digest)
    finally:
        os.close(fd)
    assert len(result["part_items"]) == 60
    assert result["floating_value_inventory"]["all_floating_components_finite"] is True


def test_motion_nonfinite_metadata_and_all_double_array_components_are_counted(tmp_path):
    payload = _motion_payload(timeout=float("inf"), timestep=float("nan"), nonfinite_pos=True)
    fd, digest, _path = _held_file(tmp_path, "PartMotionRef.ibi4", payload)
    try:
        result = _summarize(fd, "PartMotionRef.ibi4", digest)
    finally:
        os.close(fd)
    inv = result["floating_value_inventory"]
    assert inv["metadata_nonfinite_component_count"] == 2
    assert inv["array_nonfinite_component_count"] == 1
    assert inv["nonfinite_component_count"] == 3
    assert inv["all_floating_components_finite"] is False
    assert all("nan" not in str(record).lower() and "inf" not in str(record).lower()
               for record in inv["metadata"])


def test_float_nonfinite_metadata_and_float_double_force_arrays_are_counted(tmp_path):
    payload = _float_payload(
        fpt_count=1, nonfinite_root=True, nonfinite_body=True,
        nonfinite_force=True, timeout=float("nan"),
    )
    fd, digest, _path = _held_file(tmp_path, "PartFloatInfo.ibi4", payload)
    try:
        result = _summarize(fd, "PartFloatInfo.ibi4", digest)
    finally:
        os.close(fd)
    inv = result["floating_value_inventory"]
    assert inv["metadata_nonfinite_component_count"] == 1
    assert inv["array_nonfinite_component_count"] == 3
    assert inv["nonfinite_component_count"] == 4
    assert inv["all_floating_components_finite"] is False


@pytest.mark.parametrize(
    ("basename", "payload", "match"),
    [
        ("PartMotionRef.ibi4", _motion_payload(root_name="JPartFloatInfoBi4"), "root"),
        ("PartMotionRef.ibi4", _motion_payload(main_file=False), "MainFile"),
        ("PartMotionRef.ibi4", _motion_payload(wrong_root_array=True), "Dis type/count"),
        ("PartFloatInfo.ibi4", _float_payload(root_name="WrongRoot"), "root"),
        ("PartFloatInfo.ibi4", _float_payload(main_file=False), "MainFile"),
        ("PartFloatInfo.ibi4", _float_payload(fpt_count=1, omit_force_array="FptForce"), "exact official"),
        ("PartFloatInfo.ibi4", _float_payload(extra_part_array=None, fpt_count=0), None),
    ],
)
def test_rejects_bad_root_filecode_or_required_conditional_schema(
    tmp_path, basename, payload, match,
):
    fd, digest, _path = _held_file(tmp_path, basename, payload)
    try:
        if match is None:
            # The nominal control remains accepted; the other parametrized
            # cases exercise malformed root/file/array contracts.
            assert _summarize(fd, basename, digest)["status"] == "diagnostic_only_not_adjudicated"
        else:
            with pytest.raises(inventory.MotionFloatInventoryError, match=match):
                _summarize(fd, basename, digest)
    finally:
        os.close(fd)


def test_rejects_unknown_metadata_and_wrong_part_identity(tmp_path):
    extra = _v_double("FutureField", 1.0)
    payload = _motion_payload(extra_root_value=extra)
    fd, digest, _path = _held_file(tmp_path, "PartMotionRef.ibi4", payload)
    try:
        with pytest.raises(inventory.MotionFloatInventoryError, match="exact official writer schema"):
            _summarize(fd, "PartMotionRef.ibi4", digest)
    finally:
        os.close(fd)

    wrong_part = _item(
        "PART_0001", values=(_v_uint("Cpart", 0), _v_double("TimeStep", 0.1), _v_uint("Step", 1)),
        arrays=(_array("PosRef", 23, _pack("d", [0.0] * 9)),), hidden=1,
    )
    payload = _motion_payload(parts=(wrong_part,))
    fd, digest, _path = _held_file(tmp_path, "PartMotionRef.ibi4", payload)
    try:
        with pytest.raises(inventory.MotionFloatInventoryError, match="Cpart differs"):
            _summarize(fd, "PartMotionRef.ibi4", digest)
    finally:
        os.close(fd)


@pytest.mark.parametrize("basename,payload", [
    ("PartMotionRef.ibi4", _motion_payload()),
    ("PartFloatInfo2.ibi4", _float_payload("PartFloatInfo2.ibi4")),
])
def test_hash_basename_regular_file_and_identity_are_required(tmp_path, basename, payload):
    fd, digest, path = _held_file(tmp_path, basename, payload)
    try:
        with pytest.raises(inventory.MotionFloatInventoryError, match="lowercase expected"):
            _summarize(fd, basename, "not-a-sha256")
        with pytest.raises(inventory.MotionFloatInventoryError, match="SHA-256"):
            _summarize(fd, basename, "0" * 64)
        with pytest.raises(inventory.MotionFloatInventoryError, match="basename"):
            _summarize(fd, str(path), digest)
        with pytest.raises(inventory.MotionFloatInventoryError, match="hard link"):
            os.link(path, tmp_path / "second-link")
            _summarize(fd, basename, digest)
    finally:
        os.close(fd)


def test_raw_size_and_list_item_bounds_are_enforced(tmp_path, monkeypatch):
    payload = _motion_payload()
    fd, digest, _path = _held_file(tmp_path, "PartMotionRef.ibi4", payload)
    try:
        monkeypatch.setattr(bi4, "MAX_RAW_BYTES", len(payload) - 1)
        with pytest.raises(inventory.MotionFloatInventoryError, match="byte length"):
            _summarize(fd, "PartMotionRef.ibi4", digest)
    finally:
        os.close(fd)

    payload = _motion_payload()
    fd, digest, _path = _held_file(tmp_path, "PartMotionRef.ibi4", payload)
    monkeypatch.setattr(bi4, "MAX_RAW_BYTES", 64 * 1024 * 1024)
    monkeypatch.setattr(inventory, "MAX_TOTAL_METADATA_BYTES", 1)
    try:
        with pytest.raises(inventory.MotionFloatInventoryError, match="aggregate BI4 metadata"):
            _summarize(fd, "PartMotionRef.ibi4", digest)
    finally:
        os.close(fd)


def test_held_fd_content_change_after_float_scan_fails_final_binding(tmp_path, monkeypatch):
    payload = _float_payload(fpt_count=1)
    fd, digest, path = _held_file(tmp_path, "PartFloatInfo.ibi4", payload)
    original_scan = inventory._finite_array_record
    mutated = False

    def scan_then_mutate(scan_fd, size, item_name, array):
        nonlocal mutated
        result = original_scan(scan_fd, size, item_name, array)
        if not mutated:
            write_fd = os.open(path, os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                os.pwrite(write_fd, struct.pack("<f", 9.5), array.offset)
            finally:
                os.close(write_fd)
            mutated = True
        return result

    monkeypatch.setattr(inventory, "_finite_array_record", scan_then_mutate)
    try:
        with pytest.raises(inventory.MotionFloatInventoryError, match="changed during finite inventory"):
            _summarize(fd, "PartFloatInfo.ibi4", digest)
    finally:
        os.close(fd)


def test_diagnostic_api_never_opens_paths_or_writes_outputs(tmp_path, monkeypatch):
    payload = _motion_payload()
    fd, digest, path = _held_file(tmp_path, "PartMotionRef.ibi4", payload)
    monkeypatch.setattr(inventory.os, "open", lambda *args, **kwargs: pytest.fail("path open attempted"))
    try:
        result = _summarize(fd, "PartMotionRef.ibi4", digest)
    finally:
        os.close(fd)
    assert set(p.name for p in tmp_path.iterdir()) == {path.name}
    assert result["execution_authority"]["path_opened_or_resolved"] is False
    assert result["execution_authority"]["bundle_output_written"] is False
