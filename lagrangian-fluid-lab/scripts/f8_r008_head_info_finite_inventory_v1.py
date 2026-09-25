"""Bounded, synthetic-only finite inventory for native F8 Part_Head/PartInfo BI4.

The API consumes an already-held regular-file descriptor and never opens a path.
It recognizes only the writer layouts reviewed in JPartDataHead.cpp,
JPartDataBi4.cpp, and JSph.cpp. Results are diagnostic; they carry no
qualification credit or authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import os
import re
import stat
import struct
from typing import Any, Iterable


SCHEMA = "core.cfd.f8.r008_head_info_finite_inventory.v1"
STATUS_FINITE = "diagnostic_only_finite_not_adjudicated"
STATUS_NONFINITE = "diagnostic_only_nonfinite_observed"

HEADER_BYTES = 64
MAX_INPUT_BYTES = 32 * 1024 * 1024
MAX_ITEM_DEPTH = 3
MAX_HEAD_BLOCKS = 4096
MAX_PARTINFO_RECORDS = 50_000
MAX_TOTAL_ITEMS = MAX_PARTINFO_RECORDS + MAX_HEAD_BLOCKS + 4
MAX_VALUES_PER_ITEM = 128
MAX_ITEM_DEFINITION_BYTES = 4096
MAX_VALUE_BLOCK_BYTES = 64 * 1024
MAX_NAME_BYTES = 128
MAX_STRING_BYTES = 4096
MAX_SUBDOMAINS = 256
IO_CHUNK_BYTES = 1024 * 1024

FILECODE_HEAD = "#FileJBD JPartDataHead"
FILECODE_INFO = "#FileJBD JPartDataBi4_Info"
ITEM_MARKER = "\nITEM\n"
VALUES_MARKER = "\nVALUES"
FLOAT_TYPES = {11: ("float", "<f", 4), 12: ("double", "<d", 8),
               22: ("float3", "<fff", 12), 23: ("double3", "<ddd", 24)}
VALUE_TYPES: dict[int, tuple[str, str, int, bool]] = {
    1: ("text", "", 0, False),
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

_SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z", re.ASCII)
_INFO_FILENAME = re.compile(r"PartInfo_p([0-9]{2,})\.ibi4\Z", re.ASCII)
_PART_ITEM = re.compile(r"PART_([0-9]{4,})\Z", re.ASCII)


class HeadInfoFiniteInventoryError(ValueError):
    """Held BI4 bytes do not match this bounded writer-backed subset."""


@dataclass(frozen=True)
class _Value:
    name: str
    type_code: int
    value: Any


@dataclass(frozen=True)
class _Item:
    name: str
    values: tuple[_Value, ...]
    arrays: int
    children: tuple["_Item", ...]


class _Cursor:
    def __init__(self, data: bytes, start: int, end: int):
        if start < 0 or end < start or end > len(data):
            raise HeadInfoFiniteInventoryError("invalid BI4 record interval")
        self.data = data
        self.pos = start
        self.end = end

    def read(self, size: int) -> bytes:
        if size < 0 or size > self.end - self.pos:
            raise HeadInfoFiniteInventoryError("BI4 field exceeds its bounded record")
        value = self.data[self.pos:self.pos + size]
        self.pos += size
        return value

    def unpack(self, fmt: str) -> Any:
        result = struct.unpack(fmt, self.read(struct.calcsize(fmt)))
        return result[0] if len(result) == 1 else result

    def string(self, maximum: int = MAX_STRING_BYTES) -> str:
        size = self.unpack("<I")
        if size > maximum:
            raise HeadInfoFiniteInventoryError("BI4 string exceeds its frozen bound")
        try:
            return self.read(size).decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise HeadInfoFiniteInventoryError("BI4 string is not valid UTF-8") from error

    def finish(self) -> None:
        if self.pos != self.end:
            raise HeadInfoFiniteInventoryError("BI4 record has unparsed trailing bytes")


class _Parser:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = HEADER_BYTES
        self.item_count = 0

    def _u32(self) -> int:
        if self.pos > len(self.data) - 4:
            raise HeadInfoFiniteInventoryError("truncated BI4 item length")
        value = struct.unpack_from("<I", self.data, self.pos)[0]
        self.pos += 4
        return value

    def _name(self, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_NAME_BYTES or not _NAME.fullmatch(value):
            raise HeadInfoFiniteInventoryError("unsafe or unsupported BI4 item/value name")
        return value

    def _value(self, cursor: _Cursor) -> _Value:
        name = self._name(cursor.string(MAX_NAME_BYTES))
        type_code = cursor.unpack("<i")
        info = VALUE_TYPES.get(type_code)
        if info is None:
            raise HeadInfoFiniteInventoryError("unsupported BI4 metadata type")
        _label, fmt, _size, vector = info
        if type_code == 1:
            value: Any = cursor.string(MAX_STRING_BYTES)
        else:
            value = cursor.unpack(fmt)
            if type_code == 2:
                if value not in (0, 1):
                    raise HeadInfoFiniteInventoryError("BI4 boolean is not encoded as 0 or 1")
                value = bool(value)
            elif vector:
                value = tuple(value)
        return _Value(name, type_code, value)

    def item(self, depth: int) -> _Item:
        if depth > MAX_ITEM_DEPTH or self.item_count >= MAX_TOTAL_ITEMS:
            raise HeadInfoFiniteInventoryError("BI4 item depth/count exceeds the frozen bound")
        self.item_count += 1

        definition_bytes = self._u32()
        if definition_bytes > MAX_ITEM_DEFINITION_BYTES:
            raise HeadInfoFiniteInventoryError("BI4 item definition exceeds its bound")
        definition_end = self.pos + definition_bytes
        definition = _Cursor(self.data, self.pos, definition_end)
        if definition.string(32) != ITEM_MARKER:
            raise HeadInfoFiniteInventoryError("invalid JBinaryData item marker")
        name = self._name(definition.string(MAX_NAME_BYTES))
        hidden = definition.unpack("<i")
        hide_values = definition.unpack("<i")
        if hidden not in (0, 1) or hide_values not in (0, 1):
            raise HeadInfoFiniteInventoryError("invalid BI4 item visibility flags")
        if definition.string(64) != "%.7E" or definition.string(64) != "%.15E":
            raise HeadInfoFiniteInventoryError("BI4 numeric display format is unsupported")
        num_arrays = definition.unpack("<I")
        num_items = definition.unpack("<I")
        values_bytes = definition.unpack("<I")
        definition.finish()
        self.pos = definition_end

        # Both reviewed writers omit arrays from these files. Reject at the
        # declaration before consuming or allocating any alleged array payload.
        if num_arrays:
            raise HeadInfoFiniteInventoryError("unexpected BI4 arrays in Part_Head/PartInfo")
        if num_items > MAX_HEAD_BLOCKS + 1 or values_bytes > MAX_VALUE_BLOCK_BYTES:
            raise HeadInfoFiniteInventoryError("BI4 item structure exceeds its frozen bound")

        values: list[_Value] = []
        if values_bytes:
            if values_bytes > len(self.data) - self.pos:
                raise HeadInfoFiniteInventoryError("BI4 values block extends past EOF")
            values_end = self.pos + values_bytes
            value_cursor = _Cursor(self.data, self.pos, values_end)
            if value_cursor.string(32) != VALUES_MARKER:
                raise HeadInfoFiniteInventoryError("invalid JBinaryData values marker")
            count = value_cursor.unpack("<I")
            if count > MAX_VALUES_PER_ITEM:
                raise HeadInfoFiniteInventoryError("BI4 value count exceeds its frozen bound")
            values = [self._value(value_cursor) for _ in range(count)]
            value_cursor.finish()
            self.pos = values_end
        if len({entry.name for entry in values}) != len(values):
            raise HeadInfoFiniteInventoryError("duplicate sibling BI4 metadata field")

        children = tuple(self.item(depth + 1) for _ in range(num_items))
        sibling_names = {entry.name for entry in values}
        for child in children:
            if child.name in sibling_names:
                raise HeadInfoFiniteInventoryError("duplicate BI4 value/item sibling name")
            sibling_names.add(child.name)
        return _Item(name, tuple(values), num_arrays, children)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise HeadInfoFiniteInventoryError(message)


def _identity(st: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_nlink)


def _read_fd(fd: int, size: int) -> bytes:
    if size < 0 or size > MAX_INPUT_BYTES:
        raise HeadInfoFiniteInventoryError("held BI4 byte length exceeds its frozen cap")
    result = bytearray()
    offset = 0
    while offset < size:
        block = os.pread(fd, min(IO_CHUNK_BYTES, size - offset), offset)
        if not block:
            raise HeadInfoFiniteInventoryError("held BI4 was truncated while reading")
        result.extend(block)
        offset += len(block)
    return bytes(result)


def _stable_input(
    raw_fd: int, expected_sha256: str,
) -> tuple[bytes, str, tuple[int, int, int, int, int, int]]:
    _require(type(raw_fd) is int and raw_fd >= 0, "API requires an already-held file descriptor")
    _require(type(expected_sha256) is str and bool(_SHA256.fullmatch(expected_sha256)),
             "an exact lowercase expected SHA-256 is required")
    try:
        before = os.fstat(raw_fd)
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
                 "held BI4 must be a single-link regular file")
        _require(HEADER_BYTES <= before.st_size <= MAX_INPUT_BYTES,
                 "held BI4 byte length is outside the frozen cap")
        identity = _identity(before)
        data = _read_fd(raw_fd, before.st_size)
        digest = hashlib.sha256(data).hexdigest()
        _require(digest == expected_sha256, "held BI4 SHA-256 differs from expected manifest digest")

        after = os.fstat(raw_fd)
        _require(_identity(after) == identity,
                 "held BI4 identity changed during bounded input read")
        second = hashlib.sha256(_read_fd(raw_fd, before.st_size)).hexdigest()
        _require(_identity(os.fstat(raw_fd)) == identity and second == digest,
                 "held BI4 identity/bytes changed during finite inventory")
        return data, digest, identity
    except HeadInfoFiniteInventoryError:
        raise
    except OSError as error:
        raise HeadInfoFiniteInventoryError("held BI4 descriptor could not be read safely") from error


def _validate_filename(exact_filename: str) -> str:
    _require(type(exact_filename) is str and "/" not in exact_filename
             and "\\" not in exact_filename,
             "API accepts an exact native filename, not a path")
    if exact_filename == "Part_Head.ibi4":
        return "head"
    if exact_filename == "PartInfo.ibi4" or _INFO_FILENAME.fullmatch(exact_filename):
        return "info"
    raise HeadInfoFiniteInventoryError("filename is outside the exact Part_Head/PartInfo subset")


def _header(data: bytes, filecode: str) -> None:
    encoded = filecode.encode("ascii")
    _require(len(encoded) <= 58
             and data[:58] == encoded.ljust(58, b" ")
             and data[58:60] == b"\n\0"
             and data[60:64] == b"\0\0\0\0",
             "BI4 filecode or fixed native header differs from its exact writer contract")


def _field_map(item: _Item, required: dict[str, int], optional: dict[str, int] | None = None,
               *, allow_children: bool = False) -> dict[str, _Value]:
    optional = optional or {}
    _require(item.arrays == 0, f"{item.name} contains unsupported arrays")
    if not allow_children:
        _require(not item.children, f"{item.name} contains unsupported child items")
    values = {entry.name: entry for entry in item.values}
    _require(len(values) == len(item.values), f"{item.name} contains duplicate metadata")
    names = set(values)
    _require(set(required) <= names <= set(required) | set(optional),
             f"{item.name} metadata fields are missing or unknown")
    for name, type_code in {**required, **optional}.items():
        if name in values:
            _require(values[name].type_code == type_code,
                     f"{item.name}.{name} has an unsupported native type")
    return values


HEAD_TYPES: dict[str, int] = {
    "FmtVersion": 8, "AppName": 1, "Date": 1, "RunCode": 1, "CaseName": 1,
    "Data2d": 2, "Data2dPosY": 12, "Npiece": 8, "FirstPart": 8,
    "CasePosMin": 23, "CasePosMax": 23, "NpDynamic": 2, "ReuseIds": 2,
    "MapPosMin": 23, "MapPosMax": 23, "PeriMode": 7,
    "PeriXinc": 23, "PeriYinc": 23, "PeriZinc": 23, "ViscoType": 8,
    "ViscoValue": 11, "ViscoBoundFactor": 11, "Symmetry": 2, "Splitting": 2,
    "Dp": 12, "H": 12, "B": 12, "Gamma": 12, "RhopZero": 12,
    "MassBound": 12, "MassFluid": 12, "Gravity": 22,
    "CaseNp": 10, "CaseNfixed": 10, "CaseNmoving": 10,
    "CaseNfloat": 10, "CaseNfluid": 10,
}
HEAD_FLOATING_FIELDS = frozenset({
    "Data2dPosY", "CasePosMin", "CasePosMax", "MapPosMin", "MapPosMax",
    "PeriXinc", "PeriYinc", "PeriZinc", "ViscoValue", "ViscoBoundFactor",
    "Dp", "H", "B", "Gamma", "RhopZero", "MassBound", "MassFluid", "Gravity",
})


def _inventory_values(items: Iterable[tuple[tuple[str, ...], dict[str, _Value]]]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    total_finite = total_nonfinite = 0
    for item_path, values in items:
        for name, value in values.items():
            floating = FLOAT_TYPES.get(value.type_code)
            if floating is None:
                continue
            label, _fmt, _size = floating
            components = value.value if isinstance(value.value, tuple) else (value.value,)
            finite_count = sum(1 for component in components if math.isfinite(float(component)))
            nonfinite_count = len(components) - finite_count
            total_finite += finite_count
            total_nonfinite += nonfinite_count
            records.append({
                "item_path": list(item_path),
                "metadata_name": name,
                "type_code": value.type_code,
                "dtype": "<f4" if value.type_code in (11, 22) else "<f8",
                "component_count": len(components),
                "finite_count": finite_count,
                "nonfinite_count": nonfinite_count,
                "all_components_finite": nonfinite_count == 0,
            })
    return {
        "records": records,
        "finite_component_count": total_finite,
        "nonfinite_component_count": total_nonfinite,
        "total_component_count": total_finite + total_nonfinite,
        "all_components_finite": total_nonfinite == 0,
    }


def _validate_head(root: _Item) -> tuple[dict[str, Any], list[tuple[tuple[str, ...], dict[str, _Value]]]]:
    _require(root.name == "JPartDataHead", "Part_Head root item name is not native")
    values = _field_map(root, HEAD_TYPES, allow_children=True)
    _require(values["FmtVersion"].value == 180324,
             "Part_Head FmtVersion differs from the reviewed native writer")
    _require(values["Npiece"].value > 0, "Part_Head Npiece must be positive")
    _require(len(root.children) == 1 and root.children[0].name == "MkBlocks",
             "Part_Head must contain exactly one MkBlocks child")

    mkblocks = root.children[0]
    block_root_values = _field_map(mkblocks, {"Count": 8}, allow_children=True)
    count = block_root_values["Count"].value
    _require(type(count) is int and count <= MAX_HEAD_BLOCKS,
             "Part_Head MkBlocks.Count exceeds the frozen block cap")
    _require(len(mkblocks.children) == count,
             "Part_Head MkBlocks.Count differs from its child block inventory")

    block_types = {"Fixed": 0, "Moving": 1, "Floating": 2, "Fluid": 3}
    totals = {"Fixed": 0, "Moving": 0, "Floating": 0, "Fluid": 0}
    seen_mk: set[int] = set()
    seen_mktype: dict[str, set[int]] = {name: set() for name in block_types}
    previous_type = -1
    inventory: list[tuple[tuple[str, ...], dict[str, _Value]]] = [((root.name,), values)]
    for index, block in enumerate(mkblocks.children):
        _require(block.name == f"MkBlock_{index:03d}",
                 "Part_Head MkBlock child names are not in writer order")
        fields = _field_map(block, {"Type": 1, "Mk": 8, "MkType": 8, "Count": 8})
        kind = fields["Type"].value
        _require(kind in block_types, "Part_Head MkBlock.Type is not a native particle kind")
        _require(block_types[kind] >= previous_type,
                 "Part_Head MkBlock order differs from the source writer invariant")
        previous_type = block_types[kind]
        mk = fields["Mk"].value
        mktype = fields["MkType"].value
        particle_count = fields["Count"].value
        _require(particle_count > 0, "Part_Head MkBlock.Count must be positive")
        _require(mk not in seen_mk and mktype not in seen_mktype[kind],
                 "Part_Head Mk/MkType labels duplicate a source-writer key")
        seen_mk.add(mk)
        seen_mktype[kind].add(mktype)
        totals[kind] += particle_count
        inventory.append(((root.name, mkblocks.name, block.name), fields))

    expected = {
        "CaseNp": sum(totals.values()), "CaseNfixed": totals["Fixed"],
        "CaseNmoving": totals["Moving"], "CaseNfloat": totals["Floating"],
        "CaseNfluid": totals["Fluid"],
    }
    _require(all(values[name].value == total for name, total in expected.items()),
             "Part_Head CaseN* values differ from the native MkBlocks population sums")
    return ({"mk_block_count": count, "particle_counts_by_type": totals}, inventory)


INFO_ROOT_TYPES: dict[str, int] = {
    "Piece": 8, "Npiece": 8, "RunCode": 1, "Date": 1, "AppName": 1,
    "CaseName": 1, "Data2d": 2, "Data2dPosY": 12,
    "MapPosMin": 23, "MapPosMax": 23, "PeriMode": 7,
    "PeriXinc": 23, "PeriYinc": 23, "PeriZinc": 23, "AxisDiv": 7,
    "CaseNp": 10, "CaseNfixed": 10, "CaseNmoving": 10,
    "CaseNfloat": 10, "CaseNfluid": 10, "CasePosMin": 23, "CasePosMax": 23,
    "NpDynamic": 2, "ReuseIds": 2,
    "Dp": 12, "H": 12, "B": 12, "Rhop0": 12, "Gamma": 12,
    "MassBound": 12, "MassFluid": 12, "Symmetry": 2, "Splitting": 2,
}
INFO_FLOATING_FIELDS = frozenset(name for name, type_code in INFO_ROOT_TYPES.items()
                                 if type_code in FLOAT_TYPES)
PART_REQUIRED_TYPES: dict[str, int] = {
    "Cpart": 8, "TimeStep": 12, "Npok": 8, "Nout": 8, "Step": 8,
    "RunTime": 12, "DomainMin": 23, "DomainMax": 23,
}
PART_INFO_REQUIRED_TYPES: dict[str, int] = {
    "dtmean": 12, "dtmin": 12, "dtmax": 12, "timesim": 12,
    "nct": 8, "nctsize": 8, "npsim": 8, "npsize": 8, "npnormal": 8,
    "npsave": 8, "npnew": 8, "noutpos": 8, "noutrho": 8, "noutmov": 8,
    "npbin": 8, "npbout": 8, "npf": 8, "npbper": 8, "npfper": 8,
    "cpualloc": 9,
}
PART_INFO_OPTIONAL_TYPES: dict[str, int] = {
    "dterror": 12, "nctalloc": 9, "nctused": 9, "npalloc": 9, "npused": 9,
}
PART_FLOATING_BASE = frozenset({"TimeStep", "RunTime", "DomainMin", "DomainMax"})
PART_FLOATING_INFO = frozenset({"dtmean", "dtmin", "dtmax", "timesim", "dterror"})


def _validate_info_root(root: _Item, exact_filename: str) -> tuple[dict[str, _Value], dict[str, Any]]:
    _require(root.name == "JPartDataBi4" and not root.children,
             "PartInfo must start with a flat native JPartDataBi4 root item")
    values = _field_map(root, INFO_ROOT_TYPES)
    piece = values["Piece"].value
    npiece = values["Npiece"].value
    _require(type(piece) is int and type(npiece) is int and npiece > 0 and piece < npiece,
             "PartInfo Piece/Npiece values are outside the native piece range")
    if exact_filename == "PartInfo.ibi4":
        _require(piece == 0 and npiece == 1,
                 "unsuffixed PartInfo filename requires the native single-piece metadata")
    else:
        match = _INFO_FILENAME.fullmatch(exact_filename)
        assert match is not None
        _require(npiece > 1 and int(match.group(1)) == piece
                 and exact_filename == f"PartInfo_p{piece:02d}.ibi4",
                 "PartInfo piece filename differs from its root Piece/Npiece values")
    return values, {"piece": piece, "piece_count": npiece}


def _validate_info_part(
    part: _Item, seen_cparts: set[int],
) -> tuple[int, dict[str, _Value]]:
    match = _PART_ITEM.fullmatch(part.name)
    _require(match is not None, "PartInfo appended item name is not PART_NNNN")
    name_cpart = int(match.group(1))
    _require(part.name == f"PART_{name_cpart:04d}",
             "PartInfo appended PART item has a noncanonical name")

    required = {**PART_REQUIRED_TYPES, **PART_INFO_REQUIRED_TYPES}
    optional = {
        "NpTotal": 10, "IdMax": 10, "SymplecticDtPre": 12, "DemDtForce": 12,
        **PART_INFO_OPTIONAL_TYPES,
    }
    dynamic_domains: dict[str, int] = {}
    provisional = {entry.name: entry for entry in part.values}
    _require(len(provisional) == len(part.values), "PartInfo PART record has duplicate values")
    subdomain_count_value = provisional.get("subdomain_count")
    if subdomain_count_value is not None:
        _require(subdomain_count_value.type_code == 8
                 and type(subdomain_count_value.value) is int
                 and 2 <= subdomain_count_value.value <= MAX_SUBDOMAINS,
                 "PartInfo subdomain_count is outside the reviewed writer range")
        for domain in range(subdomain_count_value.value):
            dynamic_domains[f"subdomainmin_{domain:02d}"] = 23
            dynamic_domains[f"subdomainmax_{domain:02d}"] = 23
        optional["subdomain_count"] = 8
    values = _field_map(part, required, {**optional, **dynamic_domains})
    cpart = values["Cpart"].value
    _require(cpart == name_cpart and cpart not in seen_cparts,
             "PartInfo Cpart differs from its appended name or is duplicated")
    seen_cparts.add(cpart)
    for name in ("NpTotal", "IdMax"):
        if name in values:
            _require(values[name].value > 0,
                     f"PartInfo {name} is only emitted by the writer when nonzero")

    gpu_fields = {"nctalloc", "nctused", "npalloc", "npused"} & set(values)
    _require(not gpu_fields or gpu_fields == {"nctalloc", "nctused", "npalloc", "npused"},
             "PartInfo GPU memory metadata must be emitted as one writer-controlled group")
    _require(("subdomain_count" in values) == bool(dynamic_domains),
             "PartInfo subdomain vectors do not match subdomain_count")
    return cpart, values


def _parse_native(data: bytes, kind: str, exact_filename: str) -> tuple[dict[str, Any], dict[str, Any]]:
    expected_filecode = FILECODE_HEAD if kind == "head" else FILECODE_INFO
    _header(data, expected_filecode)
    parser = _Parser(data)
    root = parser.item(1)
    if kind == "head":
        _require(parser.pos == len(data), "Part_Head must contain exactly one BI4 root tree")
        summary, inventory = _validate_head(root)
        return summary, {"items": inventory, "record_count": 1}

    root_values, summary = _validate_info_root(root, exact_filename)
    records: list[_Item] = []
    while parser.pos < len(data):
        _require(len(records) < MAX_PARTINFO_RECORDS,
                 "PartInfo appended item count exceeds its frozen cap")
        records.append(parser.item(1))
    _require(bool(records), "PartInfo list-appended file has no PART records")
    seen_cparts: set[int] = set()
    inventory: list[tuple[tuple[str, ...], dict[str, _Value]]] = [((root.name,), root_values)]
    part_ids: list[int] = []
    for part in records:
        cpart, values = _validate_info_part(part, seen_cparts)
        part_ids.append(cpart)
        inventory.append(((root.name, part.name), values))
    summary.update({"record_count": len(records), "cpart_values": part_ids})
    return summary, {"items": inventory, "record_count": len(records)}


def _verify_held_input_after_parse(
    raw_fd: int,
    expected_size: int,
    expected_digest: str,
    expected_identity: tuple[int, int, int, int, int, int],
) -> None:
    try:
        before = os.fstat(raw_fd)
        _require(_identity(before) == expected_identity and before.st_size == expected_size,
                 "held BI4 identity changed during schema parsing")
        digest = hashlib.sha256(_read_fd(raw_fd, expected_size)).hexdigest()
        after = os.fstat(raw_fd)
        _require(_identity(after) == expected_identity and digest == expected_digest,
                 "held BI4 bytes or identity changed during schema parsing")
    except HeadInfoFiniteInventoryError:
        raise
    except OSError as error:
        raise HeadInfoFiniteInventoryError(
            "held BI4 descriptor failed its post-parse stability check"
        ) from error


def summarize_head_info_fd(
    raw_fd: int,
    exact_filename: str,
    expected_sha256: str,
) -> dict[str, Any]:
    """Summarize one held synthetic/raw Part_Head or PartInfo BI4 file.

    ``raw_fd`` must already be open. ``exact_filename`` is only checked against
    the writer's literal basename conventions; no path is resolved or opened.
    The expected SHA-256 is verified before and after parsing. This diagnostic
    cannot authenticate bundle membership, runtime mode, or qualification.
    """
    kind = _validate_filename(exact_filename)
    data, digest, identity = _stable_input(raw_fd, expected_sha256)
    try:
        summary, parsed = _parse_native(data, kind, exact_filename)
        _verify_held_input_after_parse(raw_fd, identity[2], digest, identity)
    except HeadInfoFiniteInventoryError:
        raise
    except (OverflowError, struct.error, UnicodeError, ValueError) as error:
        raise HeadInfoFiniteInventoryError("held BI4 is malformed or outside the reviewed subset") from error

    floating = _inventory_values(parsed["items"])
    return {
        "schema": SCHEMA,
        "status": STATUS_FINITE if floating["all_components_finite"] else STATUS_NONFINITE,
        "input_filename": exact_filename,
        "input_sha256": digest,
        "input_bytes": len(data),
        "input_identity": {
            "device": identity[0], "inode": identity[1], "size": identity[2],
            "mtime_ns": identity[3], "ctime_ns": identity[4], "link_count": identity[5],
        },
        "kind": "Part_Head" if kind == "head" else "PartInfo",
        "native_structure": summary,
        "floating_value_inventory": floating,
        "arrays_present": 0,
        "diagnostic_only": True,
        "qualification_credit": 0,
        "authority": {
            "granted": False,
            "native_integrity": False,
            "t1": False,
            "readiness": False,
        },
    }
