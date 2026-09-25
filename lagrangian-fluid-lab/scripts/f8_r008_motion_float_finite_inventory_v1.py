"""Bounded synthetic-only finite inventory for F8 R008 motion/float BI4.

The caller supplies an already-held regular-file descriptor, one exact
supported basename, and the expected raw SHA-256. This module never resolves
or opens paths and never writes files. It parses only the official
JPartMotRefBi4 / JPartFloatInfoBi4 header-plus-list-appended-PART layouts.

This diagnostic is not production provenance, output-completeness, native
integrity, or qualification evidence. Non-finite data are reported as counts;
unsupported or structurally inconsistent layouts fail closed.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import struct
from typing import Any

from scripts import f8_r008_safe_bi4_decoder_v1 as bi4


SCHEMA = "core.cfd.f8.r008_motion_float_finite_inventory.v1"
FORMAT_VERSION = 230729
SUPPORTED_BASENAMES = frozenset({
    "PartMotionRef.ibi4", "PartMotionRef2.ibi4",
    "PartFloatInfo.ibi4", "PartFloatInfo2.ibi4",
})
FILECODES = {
    "PartMotionRef.ibi4": "JPartMotRefBi4",
    "PartMotionRef2.ibi4": "JPartMotRefBi4",
    "PartFloatInfo.ibi4": "JPartFloatInfoBi4",
    "PartFloatInfo2.ibi4": "JPartFloatInfoBi4",
}
ROOT_NAMES = dict(FILECODES)
MAIN_BASENAMES = frozenset({"PartMotionRef.ibi4", "PartFloatInfo.ibi4"})
PART_NAME = re.compile(r"PART_([0-9]{4,})\Z", re.ASCII)
UINT32_MAX = (1 << 32) - 1

# Appended list items do not use the ordinary decoder's two-node/tree shape.
# Permit a bounded flat list stream without applying the single-frame array
# count cap to the whole file. Each official motion/float item has at most 16
# arrays; aggregate payload bytes remain bounded by the held file's raw cap.
MAX_TOP_LEVEL_ITEMS = bi4.MAX_ARRAYS
MAX_ARRAYS_PER_LIST_ITEM = 16
MAX_TOTAL_ARRAYS = MAX_TOP_LEVEL_ITEMS * MAX_ARRAYS_PER_LIST_ITEM
MAX_TOTAL_METADATA_BYTES = bi4.MAX_METADATA_BYTES
MAX_TOTAL_ARRAY_BYTES = bi4.MAX_RAW_BYTES
STREAM_BYTES = min(bi4.IO_CHUNK_BYTES, 256 * 1024)

MOTION_ROOT_VALUES = {
    "AppName": 1, "FormatVer": 8, "MainFile": 2, "TimeOut": 12,
    "MkBoundFirst": 6, "MkMovingCount": 8, "MkFloatCount": 8,
    "MkCount": 8,
}
MOTION_ROOT_ARRAYS = {
    "MkBound": (6, "MkCount"), "Nid": (8, "MkCount"),
    "Id": (8, "MkCount3"), "Ps": (23, "MkCount3"),
    "Dis": (12, "MkCount3"),
}
FLOAT_ROOT_VALUES = {
    "AppName": 1, "FormatVer": 8, "MainFile": 2, "TimeOut": 12,
    "MkBoundFirst": 6, "FtCount": 8, "FptCount": 8,
}
FLOAT_ROOT_ARRAYS = {
    "MkBound": (6, "FtCount"), "Beginp": (8, "FtCount"),
    "Countp": (8, "FtCount"), "Mass": (11, "FtCount"),
    "Massp": (11, "FtCount"), "Radius": (11, "FtCount"),
}
MOTION_FLOAT_ARRAYS = {11: ("<f", 1), 12: ("<d", 1),
                       22: ("<f", 3), 23: ("<d", 3)}
FLOAT_BODY_ARRAYS = {
    "center": (23, "<d", 3),
    "fvel": (22, "<f", 3), "fomega": (22, "<f", 3),
    "facelin": (22, "<f", 3), "faceang": (22, "<f", 3),
    "extforcelin": (22, "<f", 3), "extforceang": (22, "<f", 3),
    "fluforcelin": (22, "<f", 3), "fluforceang": (22, "<f", 3),
    "preacelin": (22, "<f", 3), "preaceang": (22, "<f", 3),
}


class MotionFloatInventoryError(ValueError):
    """A held raw BI4 violates the bounded motion/float diagnostic contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MotionFloatInventoryError(message)


def _u32(value: Any, label: str) -> int:
    _require(type(value) is int and 0 <= value <= UINT32_MAX,
             f"{label} must be an unsigned 32-bit integer")
    return value


def _value_map(item: bi4.ItemRecord, label: str) -> dict[str, bi4.ValueRecord]:
    values = {entry.name: entry for entry in item.values}
    _require(len(values) == len(item.values), f"{label} contains duplicate values")
    return values


def _array_map(item: bi4.ItemRecord, label: str) -> dict[str, bi4.ArrayRecord]:
    arrays = {entry.name: entry for entry in item.arrays}
    _require(len(arrays) == len(item.arrays), f"{label} contains duplicate arrays")
    return arrays


def _check_item_flags(item: bi4.ItemRecord, *, hidden: bool, label: str) -> None:
    _require(item.hidden is hidden and item.hide_values is False,
             f"{label} item visibility flags differ from the official writer")
    _require(all(not array.hidden for array in item.arrays),
             f"{label} arrays must use the official visible-array layout")
    _require(not item.children, f"{label} must be a flat BI4 item")


def _scan_held_stream(
    fd: int, basename: str, expected_sha256: str,
) -> tuple[bi4.ItemRecord, list[bi4.ItemRecord], int, str,
           tuple[int, int, int, int, int]]:
    _require(type(basename) is str and basename in SUPPORTED_BASENAMES,
             "exact PartMotionRef/PartFloatInfo basename is required")
    _require(type(expected_sha256) is str
             and bool(bi4._SHA256.fullmatch(expected_sha256)),
             "a lowercase expected raw BI4 SHA-256 is required")
    try:
        before = bi4._check_input_stat(fd)
        before_identity = bi4._identity(before)
        expected_filecode = (b"#FileJBD " + FILECODES[basename].encode("ascii"))
        header = bi4._pread_exact(fd, bi4.HEADER_BYTES, 0, before.st_size)
        title = header[:60]
        _require(title.startswith(expected_filecode)
                 and title[len(expected_filecode):58]
                 == b" " * (58 - len(expected_filecode))
                 and title[58:] == b"\n\0",
                 "BI4 filecode/padding does not match the exact supported family")
        _require(header[60] == 0 and header[61] == 0
                 and header[62:64] == b"\0\0",
                 "only SAFE little-endian non-SI64 BI4 headers are supported")
        raw_hash = bi4._hash_fd(fd, before.st_size)
        _require(raw_hash == expected_sha256,
                 "raw BI4 SHA-256 differs from the expected manifest binding")

        items: list[bi4.ItemRecord] = []
        position = bi4.HEADER_BYTES
        aggregate_metadata = 0
        aggregate_arrays = 0
        aggregate_array_bytes = 0
        while position < before.st_size:
            _require(len(items) < MAX_TOP_LEVEL_ITEMS,
                     "BI4 top-level/list-appended item count exceeds SAFE cap")
            scanner = bi4._Scanner(fd, before.st_size)
            scanner.pos = position
            item = scanner._item(1, ())
            _require(scanner.pos > position,
                     "BI4 item parser failed to advance through the held input")
            _require(not item.children,
                     "nested items are unsupported in these list-appended writers")
            aggregate_metadata += scanner.metadata_bytes
            aggregate_arrays += scanner.array_count
            aggregate_array_bytes += scanner.array_bytes
            _require(aggregate_metadata <= MAX_TOTAL_METADATA_BYTES,
                     "aggregate BI4 metadata exceeds the SAFE decoder cap")
            _require(aggregate_arrays <= MAX_TOTAL_ARRAYS,
                     "aggregate BI4 array count exceeds the SAFE decoder cap")
            _require(aggregate_array_bytes <= MAX_TOTAL_ARRAY_BYTES,
                     "aggregate BI4 array payload exceeds the SAFE decoder cap")
            items.append(item)
            position = scanner.pos
        _require(position == before.st_size and bool(items),
                 "BI4 item stream is empty or has trailing bytes")
        root = items[0]
        _require(root.name == ROOT_NAMES[basename],
                 "BI4 first list item is not the official family root")
        _check_item_flags(root, hidden=False, label="BI4 root")
        _require(len(items) >= 1, "BI4 root item is missing")

        after_parse = bi4._check_input_stat(fd)
        _require(bi4._same_stat(before, after_parse)
                 and bi4._hash_fd(fd, before.st_size) == raw_hash,
                 "held BI4 identity or bytes changed during structural parsing")
        return root, items[1:], before.st_size, raw_hash, before_identity
    except MotionFloatInventoryError:
        raise
    except (OSError, bi4.Bi4FormatError, OverflowError, ValueError, TypeError) as error:
        raise MotionFloatInventoryError(
            f"held input is not a stable bounded motion/float BI4: "
            f"{type(error).__name__}: {error}"
        ) from error


def _exact_values(
    item: bi4.ItemRecord, expected: dict[str, int], label: str,
) -> dict[str, bi4.ValueRecord]:
    values = _value_map(item, label)
    _require(set(values) == set(expected),
             f"{label} values do not match the exact official writer schema")
    for name, type_code in expected.items():
        _require(values[name].type_code == type_code,
                 f"{label}.{name} has a type code outside the official schema")
    return values


def _exact_arrays(
    item: bi4.ItemRecord,
    expected: dict[str, tuple[int, int]],
    label: str,
) -> dict[str, bi4.ArrayRecord]:
    arrays = _array_map(item, label)
    _require(set(arrays) == set(expected),
             f"{label} arrays do not match the exact official writer schema")
    for name, (type_code, count) in expected.items():
        array = arrays[name]
        _require(array.type_code == type_code and array.count == count,
                 f"{label}.{name} type/count differs from the official writer")
    return arrays


def _root_contract(
    root: bi4.ItemRecord, basename: str, fd: int, file_size: int,
) -> tuple[dict[str, Any], list[bi4.ArrayRecord]]:
    family = "motion" if basename.startswith("PartMotionRef") else "float"
    if family == "motion":
        values = _exact_values(root, MOTION_ROOT_VALUES, "motion root")
        _require(values["FormatVer"].value == FORMAT_VERSION,
                 "motion FormatVer differs from the reviewed official writer")
        _require(type(values["MainFile"].value) is bool
                 and values["MainFile"].value == (basename in MAIN_BASENAMES),
                 "motion MainFile value disagrees with the exact basename")
        _require(isinstance(values["AppName"].value, str)
                 and bool(values["AppName"].value),
                 "motion AppName must be nonempty text")
        moving = _u32(values["MkMovingCount"].value, "MkMovingCount")
        floating = _u32(values["MkFloatCount"].value, "MkFloatCount")
        mk_count = _u32(values["MkCount"].value, "MkCount")
        _require(mk_count > 0 and moving + floating == mk_count,
                 "motion MkCount must equal the positive moving+floating count")
        _u32(values["MkBoundFirst"].value, "MkBoundFirst")
        _require(type(values["TimeOut"].value) is float,
                 "motion TimeOut must be a binary64 value")
        expected = {
            name: (type_code, mk_count * (3 if count_key == "MkCount3" else 1))
            for name, (type_code, count_key) in MOTION_ROOT_ARRAYS.items()
        }
        _require(all(count <= bi4.MAX_ARRAY_COUNT for _, count in expected.values()),
                 "motion header arrays exceed the SAFE element-count cap")
        arrays = _exact_arrays(root, expected, "motion root")
        nid = arrays["Nid"]
        for value in _read_uint_array(fd, file_size, nid):
            _require(value <= 3, "motion Nid exceeds the three reference slots per body")
        meta = {
            "family": "PartMotionRef", "format_version": FORMAT_VERSION,
            "main_file": values["MainFile"].value,
            "mk_moving_count": moving, "mk_float_count": floating,
            "mk_count": mk_count,
        }
        return meta, list(arrays.values())

    values = _exact_values(root, FLOAT_ROOT_VALUES, "float root")
    _require(values["FormatVer"].value == FORMAT_VERSION,
             "float FormatVer differs from the reviewed official writer")
    _require(type(values["MainFile"].value) is bool
             and values["MainFile"].value == (basename in MAIN_BASENAMES),
             "float MainFile value disagrees with the exact basename")
    _require(isinstance(values["AppName"].value, str)
             and bool(values["AppName"].value),
             "float AppName must be nonempty text")
    ft_count = _u32(values["FtCount"].value, "FtCount")
    fpt_count = _u32(values["FptCount"].value, "FptCount")
    _u32(values["MkBoundFirst"].value, "MkBoundFirst")
    _require(ft_count > 0 and fpt_count <= bi4.MAX_ARRAY_COUNT,
             "float FtCount/FptCount is outside the SAFE bounds")
    _require(type(values["TimeOut"].value) is float,
             "float TimeOut must be a binary64 value")
    expected = {name: (type_code, ft_count)
                for name, (type_code, _count_key) in FLOAT_ROOT_ARRAYS.items()}
    arrays = _exact_arrays(root, expected, "float root")
    meta = {
        "family": "PartFloatInfo", "format_version": FORMAT_VERSION,
        "main_file": values["MainFile"].value,
        "ft_count": ft_count, "fpt_count": fpt_count,
    }
    return meta, list(arrays.values())


def _read_uint_array(
    fd: int, file_size: int, array: bi4.ArrayRecord,
) -> tuple[int, ...]:
    raw = bi4._pread_exact(fd, array.byte_count, array.offset, file_size)
    if array.count == 0:
        return ()
    return struct.unpack(f"<{array.count}I", raw)


def _metadata_finite_record(
    item: bi4.ItemRecord, label: str,
) -> list[dict[str, Any]]:
    records = []
    for value in item.values:
        if value.type_code not in {11, 12, 22, 23}:
            continue
        components = value.value if isinstance(value.value, tuple) else (value.value,)
        finite_count = sum(math.isfinite(float(component)) for component in components)
        records.append({
            "item": label, "name": value.name, "type_code": value.type_code,
            "component_count": len(components), "finite_component_count": finite_count,
            "nonfinite_component_count": len(components) - finite_count,
            "all_components_finite": finite_count == len(components),
        })
    return records


def _finite_array_record(
    fd: int, file_size: int, item_name: str, array: bi4.ArrayRecord,
) -> dict[str, Any]:
    try:
        fmt, components_per_element = MOTION_FLOAT_ARRAYS[array.type_code]
    except KeyError as error:
        raise MotionFloatInventoryError(
            f"{item_name}.{array.name} is not a supported floating BI4 array"
        ) from error
    scalar_bytes = struct.calcsize(fmt)
    digest = hashlib.sha256()
    finite_count = 0
    nonfinite_count = 0
    offset = array.offset
    remaining = array.byte_count
    while remaining:
        block = bi4._pread_exact(fd, min(STREAM_BYTES, remaining), offset, file_size)
        digest.update(block)
        values = struct.iter_unpack(fmt, block)
        for (value,) in values:
            if math.isfinite(value):
                finite_count += 1
            else:
                nonfinite_count += 1
        offset += len(block)
        remaining -= len(block)
    components = array.count * components_per_element
    _require(finite_count + nonfinite_count == components
             and (finite_count + nonfinite_count) * scalar_bytes == array.byte_count,
             f"{item_name}.{array.name} finite scan did not cover every scalar")
    return {
        "item": item_name, "name": array.name,
        "type_code": array.type_code, "element_count": array.count,
        "components_per_element": components_per_element,
        "component_count": components,
        "raw_array_sha256": digest.hexdigest(),
        "finite_component_count": finite_count,
        "nonfinite_component_count": nonfinite_count,
        "all_components_finite": nonfinite_count == 0,
    }


def _validate_part_name(item: bi4.ItemRecord, family: str) -> int:
    match = PART_NAME.fullmatch(item.name)
    _require(match is not None, f"{family} appended item name is not PART_####")
    part = int(match.group(1))
    _require(part <= UINT32_MAX and item.name == f"PART_{part:04d}",
             f"{family} PART name is not the writer's canonical Cpart name")
    _check_item_flags(item, hidden=True, label=f"{family} {item.name}")
    return part


def _motion_part(
    item: bi4.ItemRecord, mk_count: int,
) -> tuple[int, int, str, list[bi4.ArrayRecord]]:
    part = _validate_part_name(item, "PartMotionRef")
    values = _value_map(item, item.name)
    arrays = _array_map(item, item.name)
    _require("Cpart" in values and values["Cpart"].type_code == 8
             and _u32(values["Cpart"].value, f"{item.name}.Cpart") == part,
             f"{item.name} Cpart differs from its writer-generated item name")
    if set(values) == {"Cpart", "TimeStep", "Step"}:
        _require(values["TimeStep"].type_code == 12
                 and values["Step"].type_code == 8,
                 f"{item.name} single-record TimeStep/Step types are invalid")
        _u32(values["Step"].value, f"{item.name}.Step")
        _exact_arrays(item, {"PosRef": (23, mk_count * 3)}, item.name)
        return part, 1, "single", list(arrays.values())
    _require(set(values) == {"Cpart", "Count"},
             f"{item.name} metadata is neither official single nor batch layout")
    count = _u32(values["Count"].value, f"{item.name}.Count")
    _require(count > 1, f"{item.name} batch Count must exceed one")
    _exact_arrays(item, {
        "TimeStep": (12, count), "Step": (8, count),
        "PosRef": (23, count * mk_count * 3),
    }, item.name)
    return part, count, "batch", list(arrays.values())


def _float_part(
    item: bi4.ItemRecord, ft_count: int, fpt_count: int,
) -> tuple[int, int, str, list[bi4.ArrayRecord]]:
    part = _validate_part_name(item, "PartFloatInfo")
    values = _value_map(item, item.name)
    arrays = _array_map(item, item.name)
    _require("Cpart" in values and values["Cpart"].type_code == 8
             and _u32(values["Cpart"].value, f"{item.name}.Cpart") == part,
             f"{item.name} Cpart differs from its writer-generated item name")
    force_arrays: dict[str, tuple[int, int]] = {}
    if fpt_count:
        force_arrays = {
            "FptMkbound": (6, fpt_count), "FptPos": (23, fpt_count),
            "FptForce": (22, fpt_count),
        }
    if set(values) == {"Cpart", "TimeStep", "Step"}:
        _require(values["TimeStep"].type_code == 12
                 and values["Step"].type_code == 8,
                 f"{item.name} single-record TimeStep/Step types are invalid")
        _u32(values["Step"].value, f"{item.name}.Step")
        expected = {
            name: (type_code, ft_count)
            for name, (type_code, _fmt, _components) in FLOAT_BODY_ARRAYS.items()
        }
        expected.update(force_arrays)
        _exact_arrays(item, expected, item.name)
        return part, 1, "single", list(arrays.values())

    _require(set(values) == {"Cpart", "Count"},
             f"{item.name} metadata is neither official single nor batch layout")
    count = _u32(values["Count"].value, f"{item.name}.Count")
    _require(count > 1, f"{item.name} batch Count must exceed one")
    expected = {"TimeStep": (12, count), "Step": (8, count)}
    expected.update({
        name: (type_code, ft_count * count)
        for name, (type_code, _fmt, _components) in FLOAT_BODY_ARRAYS.items()
    })
    expected.update({
        "FptMkbound": (6, fpt_count * count),
        "FptPos": (23, fpt_count * count),
        "FptForce": (22, fpt_count * count),
    } if fpt_count else {})
    _exact_arrays(item, expected, item.name)
    return part, count, "batch", list(arrays.values())


def summarize_motion_float_fd(
    raw_fd: int,
    basename: str,
    expected_sha256: str,
) -> dict[str, Any]:
    """Return a read-only, diagnostic-only inventory for a synthetic BI4 fd.

    ``raw_fd`` must already refer to the input. ``basename`` is an exact
    allow-listed leaf name used only to select the expected filecode and
    ``MainFile`` bit; the module never resolves it against a directory.
    """
    root, parts, file_size, raw_hash, identity = _scan_held_stream(
        raw_fd, basename, expected_sha256,
    )
    family = "motion" if basename.startswith("PartMotionRef") else "float"
    header, root_arrays = _root_contract(root, basename, raw_fd, file_size)
    _require(len(parts) + 1 <= MAX_TOP_LEVEL_ITEMS,
             "BI4 top-level item count exceeds SAFE cap")
    finite_metadata = _metadata_finite_record(root, root.name)
    finite_arrays = [
        _finite_array_record(raw_fd, file_size, root.name, array)
        for array in root_arrays if array.type_code in MOTION_FLOAT_ARRAYS
    ]
    part_summaries = []
    previous_part: int | None = None
    for item in parts:
        if family == "motion":
            part, count, layout, arrays = _motion_part(item, header["mk_count"])
        else:
            part, count, layout, arrays = _float_part(
                item, header["ft_count"], header["fpt_count"],
            )
        _require(previous_part is None or part == previous_part + 1,
                 f"{item.name} is not the next list-appended Cpart")
        previous_part = part
        finite_metadata.extend(_metadata_finite_record(item, item.name))
        finite_arrays.extend(
            _finite_array_record(raw_fd, file_size, item.name, array)
            for array in arrays if array.type_code in MOTION_FLOAT_ARRAYS
        )
        part_summaries.append({
            "item": item.name, "cpart": part,
            "layout": layout, "record_count": count,
        })

    # Recheck after every raw float-array read as well as after structural scan.
    try:
        after = bi4._check_input_stat(raw_fd)
        _require(bi4._identity(after) == identity
                 and bi4._hash_fd(raw_fd, file_size) == raw_hash,
                 "held BI4 identity or bytes changed during finite inventory")
    except MotionFloatInventoryError:
        raise
    except (OSError, bi4.Bi4FormatError, ValueError) as error:
        raise MotionFloatInventoryError(
            "held BI4 failed its final identity/hash verification"
        ) from error

    metadata_finite = sum(record["finite_component_count"] for record in finite_metadata)
    metadata_nonfinite = sum(record["nonfinite_component_count"] for record in finite_metadata)
    arrays_finite = sum(record["finite_component_count"] for record in finite_arrays)
    arrays_nonfinite = sum(record["nonfinite_component_count"] for record in finite_arrays)
    all_finite = metadata_nonfinite + arrays_nonfinite == 0
    family_name = "PartMotionRef" if family == "motion" else "PartFloatInfo"
    return {
        "schema": SCHEMA,
        "status": "diagnostic_only_not_adjudicated",
        "source": {
            "basename": basename, "bytes": file_size, "sha256": raw_hash,
            "identity": list(identity),
        },
        "metadata": header,
        "part_items": part_summaries,
        "floating_value_inventory": {
            "metadata": finite_metadata,
            "arrays": finite_arrays,
            "metadata_finite_component_count": metadata_finite,
            "metadata_nonfinite_component_count": metadata_nonfinite,
            "array_finite_component_count": arrays_finite,
            "array_nonfinite_component_count": arrays_nonfinite,
            "finite_component_count": metadata_finite + arrays_finite,
            "nonfinite_component_count": metadata_nonfinite + arrays_nonfinite,
            "all_floating_components_finite": all_finite,
        },
        "checks": {
            "safe_raw_and_structure_bounds_passed": True,
            "official_filecode_and_list_item_contract_passed": True,
            "exact_family_schema_passed": True,
            "finite_scan_complete": True,
        },
        "interpretation": {
            "family": family_name,
            "production_provenance_verified": False,
            "output_mode_verified": False,
            "bundle_membership_verified": False,
            "output_completeness_verified": False,
            "execution_horizon_verified": False,
            "terminal_flush_verified": False,
            "native_integrity_eligible": False,
            "gate_decision_eligible": False,
            "qualification_credit": 0,
        },
        "execution_authority": {
            "path_opened_or_resolved": False,
            "bundle_output_written": False,
            "native_binary_invoked": False,
            "gencase_invoked": False,
            "solver_invoked": False,
            "worker_started": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
        },
    }
