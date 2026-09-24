"""Bounded, no-follow BI4 scanner and safe raw-array materializer for F8 R008.

This is a Python implementation of the narrow JBinaryData v5.4 subset used by
R008. It does not call or shell out to ``bi4_dump``. The caller supplies held
directory descriptors for the authorized raw-input root and output parent.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import os
import re
import stat
import struct
from typing import Any, BinaryIO
import xml.etree.ElementTree as ET


SCHEMA = "core.cfd.f8.r008.safe_bi4_decode.v1"
HEADER_BYTES = 64
FILE_PREFIX = b"#FileJBD JPartDataBi4"
CODE_ITEM = b"\nITEM\n"
CODE_VALUES = b"\nVALUES"
CODE_ARRAY = b"\nARRAY"

MAX_RAW_BYTES = 64 * 1024 * 1024
MAX_ITEM_NODES = 2
MAX_ITEM_DEPTH = 2
MAX_ARRAYS = 64
MAX_VALUES_PER_ITEM = 128
MAX_NAME_BYTES = 128
MAX_STRING_BYTES = 4096
MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_ARRAY_COUNT = 10752
MAX_ARRAY_BYTES = MAX_ARRAY_COUNT * 24
MAX_ARRAY_BYTES_TOTAL = 16 * 1024 * 1024
MAX_OUTPUT_BYTES = 24 * 1024 * 1024
MAX_ITEM_DEFINITION_BYTES = MAX_METADATA_BYTES
MAX_ARRAY_DEFINITION_BYTES = 4096
IO_CHUNK_BYTES = 1024 * 1024

# BI4 names cap at 128 bytes; sidecar filenames append ".bin" or ".xml".
_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,131}\Z", re.ASCII)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)

# JBinaryDataDef::TpData and SizeOfType() on the pinned little-endian format.
TYPE_INFO: dict[int, tuple[str, str, int, bool]] = {
    2: ("bool", "<i", 4, False),
    3: ("char", "<b", 1, False),
    4: ("uchar", "<B", 1, False),
    5: ("short", "<h", 2, False),
    6: ("ushort", "<H", 2, False),
    7: ("int", "<i", 4, False),
    8: ("uint", "<I", 4, False),
    9: ("llong", "<q", 8, False),
    10: ("ullong", "<Q", 8, False),
    11: ("float", "<f", 4, False),
    12: ("double", "<d", 8, False),
    20: ("int3", "<iii", 12, True),
    21: ("uint3", "<III", 12, True),
    22: ("float3", "<fff", 12, True),
    23: ("double3", "<ddd", 24, True),
}
VALUE_INFO = {**TYPE_INFO, 1: ("text", "", 0, False)}


class Bi4FormatError(ValueError):
    """The input is outside the bounded F8 R008 BI4 subset."""


@dataclass(frozen=True)
class ValueRecord:
    name: str
    type_code: int
    value: Any


@dataclass(frozen=True)
class ArrayRecord:
    name: str
    type_code: int
    count: int
    offset: int
    byte_count: int
    hidden: bool
    item_path: tuple[str, ...]


@dataclass(frozen=True)
class ItemRecord:
    name: str
    hidden: bool
    hide_values: bool
    float_format: str
    double_format: str
    values: tuple[ValueRecord, ...]
    arrays: tuple[ArrayRecord, ...]
    children: tuple["ItemRecord", ...]


@dataclass(frozen=True)
class ScanResult:
    input_sha256: str
    input_bytes: int
    input_identity: tuple[int, int, int, int, int]
    root: ItemRecord
    arrays: tuple[ArrayRecord, ...]


def _component(name: str, max_bytes: int = MAX_NAME_BYTES) -> str:
    if (
        not isinstance(name, str)
        or not _COMPONENT.fullmatch(name)
        or len(name) > max_bytes
    ):
        raise Bi4FormatError(f"unsafe or unsupported path component: {name!r}")
    if name in {".", ".."}:
        raise Bi4FormatError("dot path components are forbidden")
    return name


def _identity(st: os.stat_result) -> tuple[int, int, int, int, int]:
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def _check_input_stat(fd: int) -> os.stat_result:
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode):
        raise Bi4FormatError("raw BI4 input must be a regular file")
    if st.st_nlink != 1:
        raise Bi4FormatError("raw BI4 input must have exactly one hard link")
    if st.st_size < HEADER_BYTES or st.st_size > MAX_RAW_BYTES:
        raise Bi4FormatError("raw BI4 byte length is outside the frozen R008 cap")
    return st


def _pread_exact(fd: int, size: int, offset: int, file_size: int) -> bytes:
    if size < 0 or offset < 0 or size > file_size - offset:
        raise Bi4FormatError("read is outside the bounded BI4 input")
    chunks = bytearray()
    remaining = size
    position = offset
    while remaining:
        part = os.pread(fd, min(remaining, IO_CHUNK_BYTES), position)
        if not part:
            raise Bi4FormatError("unexpected end of BI4 input")
        chunks.extend(part)
        position += len(part)
        remaining -= len(part)
    return bytes(chunks)


def _hash_fd(fd: int, size: int) -> str:
    digest = hashlib.sha256()
    offset = 0
    while offset < size:
        block = os.pread(fd, min(IO_CHUNK_BYTES, size - offset), offset)
        if not block:
            raise Bi4FormatError("raw BI4 changed or truncated while hashing")
        digest.update(block)
        offset += len(block)
    return digest.hexdigest()


class _Cursor:
    def __init__(self, fd: int, start: int, end: int, file_size: int):
        if start < 0 or end < start or end > file_size:
            raise Bi4FormatError("invalid bounded BI4 record interval")
        self.fd = fd
        self.pos = start
        self.end = end
        self.file_size = file_size

    def read(self, size: int) -> bytes:
        if size < 0 or size > self.end - self.pos:
            raise Bi4FormatError("BI4 field exceeds its declared record")
        value = _pread_exact(self.fd, size, self.pos, self.file_size)
        self.pos += size
        return value

    def unpack(self, fmt: str) -> Any:
        size = struct.calcsize(fmt)
        values = struct.unpack(fmt, self.read(size))
        return values[0] if len(values) == 1 else values

    def string(self, max_bytes: int = MAX_STRING_BYTES) -> str:
        size = self.unpack("<I")
        if size > max_bytes:
            raise Bi4FormatError("BI4 string exceeds its frozen byte cap")
        try:
            return self.read(size).decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise Bi4FormatError("BI4 string is not valid UTF-8") from error

    def finish(self) -> None:
        if self.pos != self.end:
            raise Bi4FormatError("BI4 record has trailing or unparsed bytes")


class _Scanner:
    def __init__(self, fd: int, file_size: int):
        self.fd = fd
        self.file_size = file_size
        self.pos = HEADER_BYTES
        self.item_nodes = 0
        self.array_count = 0
        self.array_bytes = 0
        self.metadata_bytes = 0
        self.all_arrays: list[ArrayRecord] = []

    def _u32(self) -> int:
        value = struct.unpack("<I", _pread_exact(self.fd, 4, self.pos, self.file_size))[0]
        self.pos += 4
        return value

    def _reserve_metadata(self, size: int) -> None:
        if size < 0 or self.metadata_bytes > MAX_METADATA_BYTES - size:
            raise Bi4FormatError("aggregate BI4 metadata exceeds the R008 cap")
        self.metadata_bytes += size

    @staticmethod
    def _xml_text(value: str) -> str:
        for char in value:
            codepoint = ord(char)
            xml_10_char = (
                codepoint in (0x9, 0xA, 0xD)
                or 0x20 <= codepoint <= 0xD7FF
                or 0xE000 <= codepoint <= 0xFFFD
                or 0x10000 <= codepoint <= 0x10FFFF
            )
            if not xml_10_char:
                raise Bi4FormatError("text metadata contains an XML 1.0-invalid character")
        return value

    def _value(self, cursor: _Cursor) -> ValueRecord:
        name = cursor.string(MAX_NAME_BYTES)
        type_code = cursor.unpack("<i")
        info = VALUE_INFO.get(type_code)
        if info is None:
            raise Bi4FormatError(f"unsupported JBinaryData value type: {type_code}")
        if type_code == 1:
            value = self._xml_text(cursor.string(MAX_STRING_BYTES))
        else:
            _tag, fmt, _size, triple = info
            value = cursor.unpack(fmt)
            if type_code == 2:
                if value not in (0, 1):
                    raise Bi4FormatError("boolean metadata must be encoded as 0 or 1")
                value = bool(value)
            elif triple:
                value = tuple(value)
        return ValueRecord(name=name, type_code=type_code, value=value)

    def _item(self, depth: int, item_path: tuple[str, ...]) -> ItemRecord:
        if depth > MAX_ITEM_DEPTH:
            raise Bi4FormatError("BI4 item nesting exceeds the R008 depth cap")
        if self.item_nodes >= MAX_ITEM_NODES:
            raise Bi4FormatError("BI4 item count exceeds the R008 cap")
        self.item_nodes += 1

        definition_bytes = self._u32()
        if definition_bytes > MAX_ITEM_DEFINITION_BYTES:
            raise Bi4FormatError("BI4 item definition exceeds its cap")
        self._reserve_metadata(definition_bytes + 4)
        definition_end = self.pos + definition_bytes
        definition = _Cursor(self.fd, self.pos, definition_end, self.file_size)
        if definition.string(32).encode("utf-8") != CODE_ITEM:
            raise Bi4FormatError("invalid JBinaryData item marker")
        name = _component(definition.string(MAX_NAME_BYTES))
        item_hidden_code = definition.unpack("<i")
        hide_values_code = definition.unpack("<i")
        if item_hidden_code not in (0, 1) or hide_values_code not in (0, 1):
            raise Bi4FormatError("invalid item visibility flags")
        float_format = definition.string(64)
        double_format = definition.string(64)
        if float_format != "%.7E" or double_format != "%.15E":
            raise Bi4FormatError("BI4 numeric metadata format is outside the frozen R008 contract")
        num_arrays = definition.unpack("<I")
        num_items = definition.unpack("<I")
        values_bytes = definition.unpack("<I")
        definition.finish()
        self.pos = definition_end

        if num_arrays > MAX_ARRAYS or self.array_count + num_arrays > MAX_ARRAYS:
            raise Bi4FormatError("BI4 per-item/total array count exceeds the cap")
        if num_items > MAX_ITEM_NODES or self.item_nodes + num_items > MAX_ITEM_NODES:
            raise Bi4FormatError("BI4 child item count exceeds the cap")
        if values_bytes > MAX_METADATA_BYTES:
            raise Bi4FormatError("BI4 values block exceeds the cap")
        self._reserve_metadata(values_bytes)

        values: list[ValueRecord] = []
        if values_bytes:
            values_end = self.pos + values_bytes
            values_cursor = _Cursor(self.fd, self.pos, values_end, self.file_size)
            if values_cursor.string(32).encode("utf-8") != CODE_VALUES:
                raise Bi4FormatError("invalid JBinaryData values marker")
            value_count = values_cursor.unpack("<I")
            if value_count > MAX_VALUES_PER_ITEM:
                raise Bi4FormatError("BI4 value count exceeds the per-item cap")
            for _ in range(value_count):
                values.append(self._value(values_cursor))
            values_cursor.finish()
            self.pos = values_end

        arrays: list[ArrayRecord] = []
        sibling_names = {value.name for value in values}
        if len(sibling_names) != len(values):
            raise Bi4FormatError("duplicate sibling BI4 value name")
        for _ in range(num_arrays):
            definition_size = self._u32()
            if definition_size > MAX_ARRAY_DEFINITION_BYTES:
                raise Bi4FormatError("BI4 array definition exceeds its cap")
            self._reserve_metadata(definition_size + 4)
            definition_end = self.pos + definition_size
            array_definition = _Cursor(self.fd, self.pos, definition_end, self.file_size)
            if array_definition.string(32).encode("utf-8") != CODE_ARRAY:
                raise Bi4FormatError("invalid JBinaryData array marker")
            array_name = _component(array_definition.string(MAX_NAME_BYTES))
            array_hidden_code = array_definition.unpack("<i")
            type_code = array_definition.unpack("<i")
            count = array_definition.unpack("<I")
            byte_count = array_definition.unpack("<I")
            array_definition.finish()
            self.pos = definition_end

            if array_hidden_code not in (0, 1):
                raise Bi4FormatError("invalid array visibility flag")
            info = TYPE_INFO.get(type_code)
            if info is None:
                raise Bi4FormatError(f"unsupported or text JBinaryData array type: {type_code}")
            _tag, _fmt, element_bytes, _triple = info
            if count > MAX_ARRAY_COUNT:
                raise Bi4FormatError("BI4 array element count exceeds the R008 cap")
            expected_bytes = count * element_bytes
            if expected_bytes > MAX_ARRAY_BYTES or byte_count != expected_bytes:
                raise Bi4FormatError("BI4 array count/byte-size contract mismatch")
            if self.array_count >= MAX_ARRAYS:
                raise Bi4FormatError("BI4 total array count exceeds the cap")
            if self.array_bytes > MAX_ARRAY_BYTES_TOTAL - byte_count:
                raise Bi4FormatError("aggregate BI4 array bytes exceed the R008 cap")
            if byte_count > self.file_size - self.pos:
                raise Bi4FormatError("BI4 array payload extends beyond end of file")
            if array_name in sibling_names:
                raise Bi4FormatError("duplicate sibling BI4 value/array/item name")
            sibling_names.add(array_name)

            record = ArrayRecord(
                name=array_name,
                type_code=type_code,
                count=count,
                offset=self.pos,
                byte_count=byte_count,
                hidden=bool(array_hidden_code),
                item_path=item_path + (name,),
            )
            arrays.append(record)
            self.all_arrays.append(record)
            self.array_count += 1
            self.array_bytes += byte_count
            self.pos += byte_count

        children: list[ItemRecord] = []
        for _ in range(num_items):
            child = self._item(depth + 1, item_path + (name,))
            if child.name in sibling_names:
                raise Bi4FormatError("duplicate sibling BI4 value/array/item name")
            sibling_names.add(child.name)
            children.append(child)

        return ItemRecord(
            name=name,
            hidden=bool(item_hidden_code),
            hide_values=bool(hide_values_code),
            float_format=float_format,
            double_format=double_format,
            values=tuple(values),
            arrays=tuple(arrays),
            children=tuple(children),
        )

    def scan(self) -> tuple[ItemRecord, tuple[ArrayRecord, ...]]:
        header = _pread_exact(self.fd, HEADER_BYTES, 0, self.file_size)
        title = header[:60]
        if not title.startswith(FILE_PREFIX):
            raise Bi4FormatError("BI4 filecode is not JPartDataBi4")
        if title[len(FILE_PREFIX):58] != b" " * (58 - len(FILE_PREFIX)):
            raise Bi4FormatError("invalid JBinaryData filecode padding")
        if title[58:] != b"\n\0":
            raise Bi4FormatError("invalid JBinaryData fixed header terminator")
        if header[60] != 0:
            raise Bi4FormatError("only little-endian BI4 input is supported")
        if header[61] != 0:
            raise Bi4FormatError("SI64 BI4 input is outside the frozen R008 subset")
        if header[62:64] != b"\0\0":
            raise Bi4FormatError("nonzero reserved BI4 header bytes")

        root = self._item(1, ())
        if self.pos != self.file_size:
            raise Bi4FormatError("trailing bytes or multiple BI4 top-level records are forbidden")
        if root.name != "JPartDataBi4" or root.arrays or len(root.children) != 1:
            raise Bi4FormatError("input is not one R008 JPartDataBi4 frame")
        part = root.children[0]
        if not re.fullmatch(r"PART_[0-9]{4}", part.name, re.ASCII) or part.children:
            raise Bi4FormatError("R008 frame must contain exactly one PART_#### item")
        return root, tuple(self.all_arrays)


def _same_stat(left: os.stat_result, right: os.stat_result) -> bool:
    return _identity(left) == _identity(right) and left.st_nlink == right.st_nlink


def scan_bi4_fd(fd: int, expected_sha256: str) -> ScanResult:
    """Validate a held BI4 descriptor without writing.

    The caller must have opened it with O_NOFOLLOW beneath a trusted root (or
    otherwise established equivalent path provenance).
    """
    if not _SHA256.fullmatch(expected_sha256):
        raise Bi4FormatError("an expected raw BI4 SHA-256 is required")
    before = _check_input_stat(fd)
    before_identity = _identity(before)
    raw_hash = _hash_fd(fd, before.st_size)
    if raw_hash != expected_sha256:
        raise Bi4FormatError("raw BI4 hash does not match its frozen solver manifest")

    scanner = _Scanner(fd, before.st_size)
    root, arrays = scanner.scan()
    after_parse = _check_input_stat(fd)
    if not _same_stat(before, after_parse):
        raise Bi4FormatError("raw BI4 identity changed during bounded scan")
    if _hash_fd(fd, before.st_size) != raw_hash:
        raise Bi4FormatError("raw BI4 content changed during bounded scan")
    return ScanResult(
        input_sha256=raw_hash,
        input_bytes=before.st_size,
        input_identity=before_identity,
        root=root,
        arrays=arrays,
    )


def open_regular_beneath(root_fd: int, relative_path: str) -> int:
    """Open a relative raw path beneath a held directory FD without symlinks."""
    if not isinstance(relative_path, str) or relative_path.startswith("/"):
        raise Bi4FormatError("raw path must be relative to the held root descriptor")
    parts = relative_path.split("/")
    if not parts:
        raise Bi4FormatError("raw path contains an unsafe component")
    for part in parts:
        _component(part)
    current = os.dup(root_fd)
    try:
        for component in parts[:-1]:
            next_fd = os.open(
                component,
                os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW | _O_CLOEXEC,
                dir_fd=current,
            )
            os.close(current)
            current = next_fd
        fd = os.open(
            parts[-1], os.O_RDONLY | _O_NOFOLLOW | _O_CLOEXEC, dir_fd=current
        )
        try:
            _check_input_stat(fd)
        except Exception:
            os.close(fd)
            raise
        return fd
    finally:
        os.close(current)


def _xml_value(
    parent: ET.Element,
    value: ValueRecord,
    float_format: str,
    double_format: str,
) -> None:
    type_name, _fmt, _size, triple = VALUE_INFO[value.type_code]
    attrs = {"name": value.name}
    if value.type_code == 1:
        attrs["v"] = value.value
    elif value.type_code == 2:
        attrs["v"] = "1" if value.value else "0"
    elif triple:
        numeric_format = {22: float_format, 23: double_format}.get(value.type_code)
        if numeric_format is None:
            attrs.update({axis: str(number) for axis, number in zip("xyz", value.value)})
        else:
            attrs.update(
                {axis: numeric_format % number for axis, number in zip("xyz", value.value)}
            )
    elif value.type_code == 11:
        attrs["v"] = float_format % value.value
    elif value.type_code == 12:
        attrs["v"] = double_format % value.value
    else:
        attrs["v"] = str(value.value)
    node = ET.SubElement(parent, type_name, attrs)
    node.text = None


def _xml_item(parent: ET.Element, item: ItemRecord) -> None:
    node = ET.SubElement(
        parent,
        "item",
        {
            "name": item.name,
            "hide": "1" if item.hidden else "0",
            "hidevalues": "1" if item.hide_values else "0",
        },
    )
    for value in item.values:
        _xml_value(node, value, item.float_format, item.double_format)
    for array in item.arrays:
        type_name = TYPE_INFO[array.type_code][0]
        ET.SubElement(
            node,
            f"array_{type_name}",
            {
                "name": array.name,
                "size": str(array.count),
                "count": str(array.count),
                "hide": "1" if array.hidden else "0",
            },
        )
    for child in item.children:
        _xml_item(node, child)


def _xml_document(scan: ScanResult) -> bytes:
    root = ET.Element(
        "data",
        {
            "fmt": "JBinaryData",
            "si64_required": "false",
            "datasize32": str(scan.input_bytes - HEADER_BYTES),
        },
    )
    _xml_item(root, scan.root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("short write while materializing safe BI4 output")
        view = view[written:]


def _open_new_file(parent_fd: int, name: str) -> int:
    _component(name, max_bytes=MAX_NAME_BYTES + 4)
    return os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW | _O_CLOEXEC,
        0o600,
        dir_fd=parent_fd,
    )


def _check_output_parent(parent_fd: int) -> None:
    """Enforce basic POSIX ownership/mode bits on the dedicated output parent.

    The caller additionally guarantees there is no ACL, capability, privileged
    mount, or other cross-UID writer that bypasses these mode bits. This module
    does not inspect host-specific ACL policy; same-UID writers are trusted.
    """
    st = os.fstat(parent_fd)
    if not stat.S_ISDIR(st.st_mode):
        raise Bi4FormatError("output parent must be an already-open directory")
    if st.st_uid != os.geteuid() or st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise Bi4FormatError(
            "output parent must be current-user-owned and not group/world-writable"
        )


def _open_new_dir(parent_fd: int, name: str) -> int:
    # _check_output_parent() is enforced at the public entry point. This
    # mkdir/open sequence relies on its documented dedicated-parent threat model.
    _component(name)
    os.mkdir(name, mode=0o700, dir_fd=parent_fd)
    return os.open(
        name,
        os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW | _O_CLOEXEC,
        dir_fd=parent_fd,
    )


def _write_xml(parent_fd: int, name: str, content: bytes) -> dict[str, Any]:
    fd = _open_new_file(parent_fd, name)
    digest = hashlib.sha256(content).hexdigest()
    try:
        _write_all(fd, content)
        os.fsync(fd)
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size != len(content):
            raise Bi4FormatError("XML output is not a closed single-link regular file")
    finally:
        os.close(fd)
    return {"path": name, "bytes": len(content), "sha256": digest, "regular_file": True, "link_count": 1}


def _copy_array(fd: int, array: ArrayRecord, destination_fd: int) -> dict[str, Any]:
    filename = f"{array.name}.bin"
    output_fd = _open_new_file(destination_fd, filename)
    digest = hashlib.sha256()
    remaining = array.byte_count
    offset = array.offset
    try:
        while remaining:
            block = os.pread(fd, min(IO_CHUNK_BYTES, remaining), offset)
            if not block:
                raise Bi4FormatError("raw BI4 array changed or truncated while copying")
            digest.update(block)
            _write_all(output_fd, block)
            offset += len(block)
            remaining -= len(block)
        os.fsync(output_fd)
        st = os.fstat(output_fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size != array.byte_count:
            raise Bi4FormatError("decoded array is not a closed single-link regular file")
    finally:
        os.close(output_fd)
    type_name, _fmt, _element_bytes, triple = TYPE_INFO[array.type_code]
    return {
        # The top JPartDataBi4 item is represented by output_name itself; only
        # descendants are directories beneath that output root.
        "path": "/".join(array.item_path[1:] + (filename,)),
        "array_name": array.name,
        "type_code": array.type_code,
        "type_name": type_name,
        "dtype": TYPE_INFO[array.type_code][1],
        "shape": [array.count, 3] if triple else [array.count],
        "count": array.count,
        "bytes": array.byte_count,
        "sha256": digest.hexdigest(),
        "regular_file": True,
        "link_count": 1,
    }


def _write_arrays(fd: int, item: ItemRecord, item_dir_fd: int) -> list[dict[str, Any]]:
    manifest = [_copy_array(fd, array, item_dir_fd) for array in item.arrays]
    for child in item.children:
        child_fd = _open_new_dir(item_dir_fd, child.name)
        try:
            manifest.extend(_write_arrays(fd, child, child_fd))
        finally:
            os.close(child_fd)
    return manifest


def _actual_tree(dir_fd: int, prefix: tuple[str, ...] = ()) -> tuple[set[str], set[str]]:
    files: set[str] = set()
    directories: set[str] = set()
    for name in os.listdir(dir_fd):
        st = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        _component(
            name,
            max_bytes=(MAX_NAME_BYTES if stat.S_ISDIR(st.st_mode) else MAX_NAME_BYTES + 4),
        )
        relative = "/".join(prefix + (name,))
        if stat.S_ISDIR(st.st_mode):
            child_fd = os.open(
                name,
                os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW | _O_CLOEXEC,
                dir_fd=dir_fd,
            )
            directories.add(relative)
            try:
                child_files, child_dirs = _actual_tree(child_fd, prefix + (name,))
                files.update(child_files)
                directories.update(child_dirs)
            finally:
                os.close(child_fd)
        elif stat.S_ISREG(st.st_mode) and st.st_nlink == 1:
            files.add(relative)
        else:
            raise Bi4FormatError("output tree contains a symlink or non-regular object")
    return files, directories


def _verify_file_at(parent_fd: int, name: str, expected_bytes: int, expected_sha: str) -> None:
    fd = os.open(name, os.O_RDONLY | _O_NOFOLLOW | _O_CLOEXEC, dir_fd=parent_fd)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size != expected_bytes:
            raise Bi4FormatError(f"output file failed regular-file/size closure: {name}")
        if _hash_fd(fd, st.st_size) != expected_sha:
            raise Bi4FormatError(f"output file changed after decode: {name}")
    finally:
        os.close(fd)


def _verify_output_tree(
    output_fd: int,
    parent_fd: int,
    output_name: str,
    root_item: ItemRecord,
    expected_arrays: list[dict[str, Any]],
    expected_xml: dict[str, Any],
) -> None:
    held_stat = os.fstat(output_fd)
    named_stat = os.stat(output_name, dir_fd=parent_fd, follow_symlinks=False)
    if (
        not stat.S_ISDIR(held_stat.st_mode)
        or not stat.S_ISDIR(named_stat.st_mode)
        or (held_stat.st_dev, held_stat.st_ino) != (named_stat.st_dev, named_stat.st_ino)
    ):
        raise Bi4FormatError("output directory name no longer identifies the held directory")
    actual_files, actual_dirs = _actual_tree(output_fd)
    expected_files = {entry["path"] for entry in expected_arrays}
    expected_dirs = {child.name for child in root_item.children}
    if actual_files != expected_files or actual_dirs != expected_dirs:
        raise Bi4FormatError("safe decoder output tree does not exactly match its array manifest")
    for entry in expected_arrays:
        parts = entry["path"].split("/")
        current_fd = os.dup(output_fd)
        try:
            for component in parts[:-1]:
                next_fd = os.open(
                    component,
                    os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW | _O_CLOEXEC,
                    dir_fd=current_fd,
                )
                os.close(current_fd)
                current_fd = next_fd
            _verify_file_at(current_fd, parts[-1], entry["bytes"], entry["sha256"])
        finally:
            os.close(current_fd)
    _verify_file_at(parent_fd, expected_xml["path"], expected_xml["bytes"], expected_xml["sha256"])
    final_stat = os.stat(output_name, dir_fd=parent_fd, follow_symlinks=False)
    if (held_stat.st_dev, held_stat.st_ino) != (final_stat.st_dev, final_stat.st_ino):
        raise Bi4FormatError("output directory was replaced during final tree verification")


def decode_bi4_fd(
    input_fd: int,
    expected_sha256: str,
    output_parent_fd: int,
    output_name: str,
) -> dict[str, Any]:
    """Safely scan and materialize a single R008 BI4 from a held input FD.

    A failed output is deliberately retained in its one-shot namespace; this
    function never deletes, replaces, or retries partial evidence.
    The caller must have opened input_fd without following symlinks.
    output_parent_fd must refer to a current-user-owned directory that is not
    group/world-writable; the caller must keep same-UID processes from mutating
    this one-shot namespace concurrently and guarantee that no ACL, capability,
    privileged mount, or other cross-UID writer bypasses its mode bits. ACLs are
    not inspected by this module.
    """
    output_name = _component(output_name)
    _check_output_parent(output_parent_fd)
    scan = scan_bi4_fd(input_fd, expected_sha256)
    xml_bytes = _xml_document(scan)
    planned_total = len(xml_bytes) + sum(array.byte_count for array in scan.arrays)
    if planned_total > MAX_OUTPUT_BYTES:
        raise Bi4FormatError("planned decode output exceeds the R008 total byte cap")

    before_write = _check_input_stat(input_fd)
    if _identity(before_write) != scan.input_identity or _hash_fd(input_fd, scan.input_bytes) != scan.input_sha256:
        raise Bi4FormatError("raw BI4 changed after preflight and before output creation")

    output_fd = _open_new_dir(output_parent_fd, output_name)
    try:
        array_manifest = _write_arrays(input_fd, scan.root, output_fd)
        xml_manifest = _write_xml(output_parent_fd, f"{output_name}.xml", xml_bytes)
        if len(array_manifest) + 1 > 65:
            raise Bi4FormatError("decoded file count exceeds the frozen R008 output cap")
        _verify_output_tree(
            output_fd,
            output_parent_fd,
            output_name,
            scan.root,
            array_manifest,
            xml_manifest,
        )
        after_write = _check_input_stat(input_fd)
        if _identity(after_write) != scan.input_identity or _hash_fd(input_fd, scan.input_bytes) != scan.input_sha256:
            raise Bi4FormatError("raw BI4 changed during safe materialization")
        os.fsync(output_fd)
        os.fsync(output_parent_fd)
    finally:
        os.close(output_fd)
    return {
        "schema": SCHEMA,
        "status": "safe_decode_complete",
        "input": {
            "sha256": scan.input_sha256,
            "bytes": scan.input_bytes,
            "identity": list(scan.input_identity),
        },
        "xml": xml_manifest,
        "arrays": array_manifest,
        "array_file_count": len(array_manifest),
        "total_output_bytes": planned_total,
        "tree_closed": True,
        "execution_authority": {
            "native_binary_invoked": False,
            "gencase_invoked": False,
            "solver_invoked": False,
            "worker_started": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "qualification_credit": 0,
        },
    }


def decode_bi4_beneath(
    raw_root_fd: int,
    relative_input_path: str,
    expected_sha256: str,
    output_parent_fd: int,
    output_name: str,
) -> dict[str, Any]:
    """Open the raw input beneath a held root and run the safe materializer.

    The root and output-parent descriptors must be trusted. The output parent
    must satisfy decode_bi4_fd()'s dedicated, private one-shot namespace
    precondition, including its explicit ACL/privileged-writer assumptions.
    """
    input_fd = open_regular_beneath(raw_root_fd, relative_input_path)
    try:
        return decode_bi4_fd(input_fd, expected_sha256, output_parent_fd, output_name)
    finally:
        os.close(input_fd)
