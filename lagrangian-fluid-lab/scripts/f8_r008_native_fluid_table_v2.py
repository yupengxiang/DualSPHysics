"""Strict F8 R008 v2 fluid-table semantics and raw-BI4 source reader.

This module is a static/data-audit component. It never launches a native tool,
solver, worker, GPU job, or queue operation, and it never grants T1 credit.
Callers must supply already hash-bound per-case source frames and a held table
file descriptor opened beneath the verified D output root with O_NOFOLLOW.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import h5py
import math
import os
from pathlib import Path
import re
import stat
import struct
from typing import Any, Iterable, Mapping

import numpy as np

from scripts import f8_r008_per_case_bundle_verifier_v1 as bundle
from scripts import f8_r008_safe_bi4_decoder_v1 as decoder
from scripts import f8_r008_safe_bi4_metadata_binding_v1 as metadata_binding


SCHEMA = "core.cfd.f8.r008_native_fluid_table_semantics.v1"
TABLE_SCHEMA = "core.cfd.f8.r008_native_fluid_frame_table.v2"
SCOPE_ID = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008"
LAB = Path(__file__).resolve().parents[1]
CONTRACT_PATH = LAB / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/native-fluid-table-schema-v2/schema.json"
MAX_TABLE_FILE_BYTES = 2 * 1024**3
MAX_LOGICAL_BYTES = 1024**3
MAX_TIME_ROWS = 1497
MAX_PARTICLE_ROWS = decoder.MAX_ARRAY_COUNT
MAX_TIME_PARTICLE_CELLS = MAX_TIME_ROWS * MAX_PARTICLE_ROWS
MAX_CHUNK_PARTICLES = 65536
READ_CHUNK_BYTES = 1024 * 1024
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)

ROOT_ATTRIBUTE_NAMES = {
    "schema", "schema_version", "f8_table_schema", "scope_id", "case_id",
    "identity_key", "trajectory_semantics", "conversion_complete",
    "data_qualification_status", "generated_xml_sha256", "definition_sha256",
    "materialization_receipt_sha256", "raw_solver_manifest_sha256",
    "scope_receipt_sha256", "parameter_contract_sha256",
}
STRING_ATTRIBUTE_NAMES = ROOT_ATTRIBUTE_NAMES - {"schema_version", "conversion_complete"}
DATASET_DTYPES = {
    "time": np.dtype("<f8"),
    "particle_id": np.dtype("<u4"),
    "position": np.dtype("<f8"),
    "velocity": np.dtype("<f4"),
    "density": np.dtype("<f4"),
    "mass": np.dtype("<f4"),
    "valid": np.dtype("?"),
}
VECTOR_DATASETS = {"position", "velocity"}
PARTICLE_DATASETS = {"position", "velocity", "density", "mass", "valid"}
ARRAY_DTYPES = {8: np.dtype("<u4"), 11: np.dtype("<f4"),
                22: np.dtype("<f4"), 23: np.dtype("<f8")}


class NativeFluidTableError(ValueError):
    """An F8 v2 table or its upstream raw-frame semantics are invalid."""


@dataclass(frozen=True)
class NativeSourceFrame:
    """One native BI4 frame after bounded parsing, preserving raw mass bits."""

    time_ieee754_hex: str
    particle_id: np.ndarray
    position_m: np.ndarray
    velocity_m_s: np.ndarray
    density_kg_m3: np.ndarray
    massfluid_binary64_le: bytes
    case_np: int


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise NativeFluidTableError(message)


def _identity(st: os.stat_result) -> tuple[int, int, int, int, int]:
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns


def _sha256_fd(fd: int, expected_bytes: int) -> str:
    digest = hashlib.sha256()
    offset = 0
    while offset < expected_bytes:
        block = os.pread(fd, min(READ_CHUNK_BYTES, expected_bytes - offset), offset)
        _require(bool(block), "table file truncated while hashing")
        digest.update(block)
        offset += len(block)
    _require(os.pread(fd, 1, expected_bytes) == b"", "table file grew while hashing")
    return digest.hexdigest()


def _read_array(fd: int, array: decoder.ArrayRecord) -> np.ndarray:
    dtype = ARRAY_DTYPES.get(array.type_code)
    _require(dtype is not None, f"unsupported upstream array type for {array.name}")
    _require(array.byte_count <= decoder.MAX_ARRAY_BYTES,
             f"upstream array {array.name} exceeds the reviewed per-array byte cap")
    payload = bundle._read_fd_range(fd, array.offset, array.byte_count)
    expected_size = array.count * (3 if array.type_code in (22, 23) else 1)
    values = np.frombuffer(payload, dtype=dtype)
    _require(values.size == expected_size, f"upstream array {array.name} has an invalid element count")
    shape = (array.count, 3) if array.type_code in (22, 23) else (array.count,)
    return values.reshape(shape).copy()


def read_native_source_frame_fd(
    fd: int,
    expected_sha256: str,
    *,
    expected_bytes: int | None = None,
) -> NativeSourceFrame:
    """Read only the bounded Idp/Pos[d]/Vel/Rhop arrays from a held BI4 FD."""
    _require(bool(SHA256_RE.fullmatch(expected_sha256)), "raw BI4 SHA-256 is malformed")
    before = os.fstat(fd)
    _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
             "raw BI4 must be a single-link regular file")
    if expected_bytes is not None:
        _require(before.st_size == expected_bytes, "raw BI4 size differs from its source manifest")
    bound = metadata_binding.bind_metadata_fd(fd, expected_sha256)
    scan = bound["scan"]
    metadata = bound["manifest"]
    _require(scan.input_bytes == before.st_size and scan.input_identity == _identity(before),
             "raw BI4 changed before source arrays were read")
    bundle._require_native_arrays(scan, metadata)
    case_np, _group_counts = bundle._bi4_case_counts(metadata)

    by_name: dict[str, list[decoder.ArrayRecord]] = {}
    for array in scan.arrays:
        if array.name in {"Idp", "Pos", "Posd", "Vel", "Rhop"}:
            by_name.setdefault(array.name, []).append(array)
    for name in ("Idp", "Vel", "Rhop"):
        _require(len(by_name.get(name, ())) == 1, f"raw BI4 lacks one exact {name} array")
    _require((len(by_name.get("Pos", ())), len(by_name.get("Posd", ()))) in {(1, 0), (0, 1)},
             "raw BI4 must have exactly one of Pos or Posd")
    selected_pos = by_name["Pos"][0] if by_name.get("Pos") else by_name["Posd"][0]
    arrays = {
        "Idp": by_name["Idp"][0], "Position": selected_pos,
        "Vel": by_name["Vel"][0], "Rhop": by_name["Rhop"][0],
    }
    expected_codes = {"Idp": 8, "Vel": 22, "Rhop": 11,
                      "Position": 22 if selected_pos.name == "Pos" else 23}
    for name, array in arrays.items():
        _require(array.type_code == expected_codes[name] and array.count == case_np,
                 f"raw BI4 {name} type/count differs from the exact R008 contract")

    part_paths = [
        (item_path, name) for item_path, name in
        ((tuple(record["item_path"]), record["metadata_name"])
         for record in metadata["metadata_records"])
        if name == "TimeStep"
    ]
    _require(len(part_paths) == 1, "raw BI4 must expose exactly one TimeStep")
    time_record = bundle._metadata_record(metadata, part_paths[0][0], "TimeStep")
    time_components = time_record.get("float_hex_components")
    _require(time_record.get("type_code") == 12 and isinstance(time_components, list)
             and len(time_components) == 1, "raw BI4 TimeStep is not one binary64 value")
    time_hex = time_components[0]
    _require(isinstance(time_hex, str) and len(time_hex) <= 32,
             "raw BI4 TimeStep hexadecimal value exceeds its binary64 bound")
    mass_record = bundle._metadata_record(metadata, ("JPartDataBi4",), "MassFluid")
    mass_bytes_hex = mass_record.get("raw_value_bytes_hex")
    _require(mass_record.get("type_code") == 12 and isinstance(mass_bytes_hex, str)
             and len(mass_bytes_hex) == 16
             and bool(re.fullmatch(r"[0-9a-f]{16}", mass_bytes_hex, re.ASCII)),
             "raw BI4 MassFluid is not exact canonical binary64")
    mass_bits = bytes.fromhex(mass_bytes_hex)

    result = NativeSourceFrame(
        time_ieee754_hex=time_hex,
        particle_id=_read_array(fd, arrays["Idp"]),
        position_m=_read_array(fd, arrays["Position"]),
        velocity_m_s=_read_array(fd, arrays["Vel"]),
        density_kg_m3=_read_array(fd, arrays["Rhop"]),
        massfluid_binary64_le=mass_bits,
        case_np=case_np,
    )
    after = os.fstat(fd)
    _require(_identity(before) == _identity(after)
             and decoder._hash_fd(fd, before.st_size) == expected_sha256,
             "raw BI4 changed while native source arrays were verified")
    return result


def expected_root_attributes(
    *,
    case_id: str,
    generated_xml_sha256: str,
    definition_sha256: str,
    materialization_receipt_sha256: str,
    raw_solver_manifest_sha256: str,
    scope_receipt_sha256: str,
    parameter_contract_sha256: str,
) -> dict[str, Any]:
    """Construct the exact v2 root attribute set from verified B/C bindings."""
    _require(isinstance(case_id, str)
             and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", case_id, re.ASCII)),
             "table case_id is outside the bounded R008 identifier format")
    hashes = {
        "generated_xml_sha256": generated_xml_sha256,
        "definition_sha256": definition_sha256,
        "materialization_receipt_sha256": materialization_receipt_sha256,
        "raw_solver_manifest_sha256": raw_solver_manifest_sha256,
        "scope_receipt_sha256": scope_receipt_sha256,
        "parameter_contract_sha256": parameter_contract_sha256,
    }
    _require(all(isinstance(value, str) and SHA256_RE.fullmatch(value) for value in hashes.values()),
             "table provenance attribute contains a malformed SHA-256")
    return {
        "schema": "core.cfd.v1",
        "schema_version": 3,
        "f8_table_schema": TABLE_SCHEMA,
        "scope_id": SCOPE_ID,
        "case_id": case_id,
        "identity_key": "particle_id",
        "trajectory_semantics": "native numerical SPH particle identity; fluid cohort only; not material identity",
        "conversion_complete": True,
        "data_qualification_status": "qualification_only",
        **hashes,
    }


def _validate_expected_attributes(expected: Mapping[str, Any]) -> None:
    _require(set(expected) == ROOT_ATTRIBUTE_NAMES,
             "caller expected root attributes do not exactly equal the v2 contract")
    try:
        canonical = expected_root_attributes(
            case_id=expected["case_id"],
            generated_xml_sha256=expected["generated_xml_sha256"],
            definition_sha256=expected["definition_sha256"],
            materialization_receipt_sha256=expected["materialization_receipt_sha256"],
            raw_solver_manifest_sha256=expected["raw_solver_manifest_sha256"],
            scope_receipt_sha256=expected["scope_receipt_sha256"],
            parameter_contract_sha256=expected["parameter_contract_sha256"],
        )
    except (KeyError, TypeError) as error:
        raise NativeFluidTableError("caller expected attributes lack a canonical v2 provenance identity") from error
    _require(dict(expected) == canonical,
             "caller expected root attributes override a fixed v2 contract value")


MAX_ROOT_ATTRIBUTE_STRING_BYTES = 256


def _attr_string(handle: h5py.File, name: str, expected_value: str) -> str:
    attr_id = handle.attrs.get_id(name)
    info = h5py.check_string_dtype(attr_id.dtype)
    _require(len(expected_value) <= MAX_ROOT_ATTRIBUTE_STRING_BYTES,
             f"caller expected root attribute {name} exceeds the bounded UTF-8 string size")
    encoded = expected_value.encode("utf-8")
    type_id = attr_id.get_type()
    _require(attr_id.shape == () and info is not None and info.encoding == "utf-8"
             and info.length == len(encoded) and len(encoded) <= MAX_ROOT_ATTRIBUTE_STRING_BYTES
             and type_id.get_class() == h5py.h5t.STRING
             and type_id.get_cset() == h5py.h5t.CSET_UTF8
             and type_id.get_size() == len(encoded),
             f"HDF5 root attribute {name} is not a bounded fixed-size scalar UTF-8 string")
    buffer = np.zeros((), dtype=attr_id.dtype)
    attr_id.read(buffer)
    raw = buffer.tobytes()
    _require(raw == encoded, f"HDF5 root attribute {name} is not the exact UTF-8 byte sequence")
    try:
        return raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise NativeFluidTableError(f"HDF5 root attribute {name} is not valid UTF-8") from error


def _validate_root_attributes(handle: h5py.File, expected: Mapping[str, Any]) -> None:
    _require(set(expected) == ROOT_ATTRIBUTE_NAMES,
             "caller expected root attributes do not exactly equal the v2 contract")
    try:
        for name in ROOT_ATTRIBUTE_NAMES:
            handle.attrs.get_id(name)
    except (KeyError, OSError, RuntimeError) as error:
        raise NativeFluidTableError("HDF5 root attributes do not exactly equal the v2 contract") from error
    for name in STRING_ATTRIBUTE_NAMES:
        _require(isinstance(expected[name], str)
                 and _attr_string(handle, name, expected[name]) == expected[name],
                 f"HDF5 root attribute {name} differs from the verified B/C source")
    version_id = handle.attrs.get_id("schema_version")
    version_type = version_id.get_type()
    _require(version_id.shape == () and version_id.dtype == np.dtype("<u4")
             and version_type.get_class() == h5py.h5t.INTEGER
             and version_type.get_size() == 4
             and version_type.get_sign() == h5py.h5t.SGN_NONE
             and version_type.get_order() == h5py.h5t.ORDER_LE
             and int(handle.attrs["schema_version"]) == expected["schema_version"],
             "HDF5 schema_version is not the exact little-endian uint32 scalar")
    valid_id = handle.attrs.get_id("conversion_complete")
    _require(valid_id.shape == () and valid_id.dtype == np.dtype("?")
             and _is_exact_hdf5_boolean(valid_id.get_type()),
             "HDF5 conversion_complete is not the exact boolean enum")
    raw_value = np.zeros((), dtype=np.uint8)
    valid_id.read(raw_value, mtype=h5py.h5t.NATIVE_UINT8)
    _require(int(raw_value) == 1 and expected["conversion_complete"] is True,
             "HDF5 conversion_complete raw enum value is not exactly TRUE=1")


def _is_exact_hdf5_boolean(type_id: h5py.h5t.TypeID) -> bool:
    """Require the canonical HDF5 FALSE=0/TRUE=1 unsigned-byte enum."""
    try:
        if type_id.get_class() != h5py.h5t.ENUM or type_id.get_size() != 1:
            return False
        if type_id.get_nmembers() != 2:
            return False
        members = {
            type_id.get_member_name(index): type_id.get_member_value(index)
            for index in range(type_id.get_nmembers())
        }
        base = type_id.get_super()
        return (members == {b"FALSE": 0, b"TRUE": 1}
                and base.get_class() == h5py.h5t.INTEGER
                and base.get_size() == 1
                and base.get_sign() == h5py.h5t.SGN_NONE)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False


def _is_exact_numeric_type(type_id: h5py.h5t.TypeID, dtype: np.dtype) -> bool:
    try:
        if dtype.kind == "f":
            return (type_id.get_class() == h5py.h5t.FLOAT
                    and type_id.get_size() == dtype.itemsize
                    and type_id.get_order() == h5py.h5t.ORDER_LE)
        if dtype.kind == "u":
            return (type_id.get_class() == h5py.h5t.INTEGER
                    and type_id.get_size() == dtype.itemsize
                    and type_id.get_sign() == h5py.h5t.SGN_NONE
                    and type_id.get_order() == h5py.h5t.ORDER_LE)
        return False
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False


def _validate_filters_and_layout(dataset: h5py.Dataset, name: str, p_count: int) -> None:
    _require(len(dataset.attrs) == 0, f"HDF5 dataset {name} has unregistered attributes")
    _require(dataset.external is None and not dataset.is_virtual,
             f"HDF5 dataset {name} uses external storage or a virtual layout")
    creation = dataset.id.get_create_plist()
    filter_count = creation.get_nfilters()
    if name in {"time", "particle_id"}:
        _require(dataset.chunks is None and dataset.compression is None and filter_count == 0,
                 f"HDF5 {name} must be contiguous and unfiltered")
        _require(dataset.id.get_storage_size() == dataset.size * dataset.dtype.itemsize,
                 f"HDF5 {name} has unallocated or overallocated backing storage")
        return
    if name == "valid":
        _require(_is_exact_hdf5_boolean(dataset.id.get_type()),
                 "HDF5 valid is not the exact FALSE=0/TRUE=1 unsigned-byte enum")
    expected_chunks = ((1, min(p_count, MAX_CHUNK_PARTICLES), 3)
                       if name in VECTOR_DATASETS
                       else (1, min(p_count, MAX_CHUNK_PARTICLES)))
    _require(dataset.chunks == expected_chunks and dataset.compression == "lzf"
             and dataset.shuffle is False and dataset.fletcher32 is False
             and dataset.scaleoffset is None and filter_count == 1,
             f"HDF5 dataset {name} does not use the exact bounded LZF chunk layout")
    filter_id, _flags, _values, _filter_name = creation.get_filter(0)
    _require(filter_id == h5py.h5z.FILTER_LZF,
             f"HDF5 dataset {name} has an unregistered compression/filter pipeline")
    _require(dataset.id.get_num_chunks() == dataset.shape[0],
             f"HDF5 dataset {name} does not allocate exactly one complete chunk per time row")


def _read_valid_chunk_raw(dataset: h5py.Dataset, ordinal: int, start: int, stop: int) -> np.ndarray:
    """Read enum bytes without bool conversion, preserving invalid values such as 2."""
    file_space = dataset.id.get_space()
    file_space.select_hyperslab((ordinal, start), (1, stop - start))
    memory_space = h5py.h5s.create_simple((stop - start,))
    raw = np.empty(stop - start, dtype=np.uint8)
    dataset.id.read(memory_space, file_space, raw, mtype=h5py.h5t.NATIVE_UINT8)
    return raw


def _canonical_times(values: Iterable[str]) -> np.ndarray:
    items: list[str] = []
    for value in values:
        _require(len(items) < MAX_TIME_ROWS,
                 "expected native time axis exceeds the R008 table cap")
        items.append(value)
    _require(2 <= len(items), "expected native time axis is too short")
    numbers: list[float] = []
    for text in items:
        _require(isinstance(text, str) and len(text) <= 32,
                 "expected native time is not a bounded binary64 hex string")
        try:
            number = float.fromhex(text)
        except ValueError as error:
            raise NativeFluidTableError("expected native time is malformed") from error
        _require(math.isfinite(number) and number.hex() == text,
                 "expected native time is non-finite or non-canonical")
        numbers.append(number)
    _require(numbers[0] == 0.0 and not math.copysign(1.0, numbers[0]) < 0.0,
             "expected native axis must start at positive zero")
    _require(all(right > left for left, right in zip(numbers, numbers[1:])),
             "expected native time axis is not strictly increasing")
    return np.asarray(numbers, dtype="<f8")


def _same_bits(actual: np.ndarray, expected: np.ndarray) -> bool:
    left = np.ascontiguousarray(actual)
    right = np.ascontiguousarray(expected)
    return left.dtype == right.dtype and left.shape == right.shape and left.tobytes() == right.tobytes()


def verify_native_fluid_table_fd(
    table_fd: int,
    *,
    expected_table_bytes: int,
    expected_table_sha256: str,
    expected_attributes: Mapping[str, Any],
    expected_time_axis_hex: Iterable[str],
    expected_fluid_ids: Any,
    expected_case_np: int,
    initial_massfluid_binary64_le: bytes,
    source_frames: Iterable[NativeSourceFrame],
) -> dict[str, Any]:
    """Recompute every v2 HDF5 row from the exact ordered native BI4 frames.

    The function validates the held table FD and hashes it before HDF5 reads,
    checks all dimensions and storage before dataset-value reads, then compares
    each field in bounded time-row/particle chunks. The caller must verify that
    ``expected_*`` values came from the immutable B/C/D bundle chain.
    """
    _require(isinstance(expected_table_bytes, int) and not isinstance(expected_table_bytes, bool)
             and 0 < expected_table_bytes <= MAX_TABLE_FILE_BYTES,
             "table byte count is outside the v2 file cap")
    _require(isinstance(expected_table_sha256, str) and bool(SHA256_RE.fullmatch(expected_table_sha256)),
             "table SHA-256 is malformed")
    _validate_expected_attributes(expected_attributes)
    before = os.fstat(table_fd)
    _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
             and before.st_size == expected_table_bytes,
             "table must be the exact-size single-link regular file from the D manifest")
    _require(_sha256_fd(table_fd, expected_table_bytes) == expected_table_sha256,
             "table bytes do not match the D output manifest")

    times = _canonical_times(expected_time_axis_hex)
    raw_ids = np.asarray(expected_fluid_ids)
    _require(raw_ids.ndim == 1 and raw_ids.dtype == np.dtype("<u4") and raw_ids.size > 0
             and raw_ids.size <= MAX_PARTICLE_ROWS,
             "expected fluid axis is not a bounded uint32 vector")
    _require(isinstance(expected_case_np, int) and not isinstance(expected_case_np, bool)
             and 0 < expected_case_np <= decoder.MAX_ARRAY_COUNT,
             "expected CaseNp exceeds the reviewed raw BI4 limit")
    fluid_ids = np.ascontiguousarray(raw_ids)
    _require(np.all(fluid_ids[1:] > fluid_ids[:-1])
             and int(fluid_ids[-1]) < expected_case_np,
             "expected fluid IDs are not unique, sorted, or inside CaseNp")
    _require(isinstance(initial_massfluid_binary64_le, bytes)
             and len(initial_massfluid_binary64_le) == 8,
             "B initial MassFluid is not exact binary64 bytes")
    initial_massfluid = struct.unpack("<d", initial_massfluid_binary64_le)[0]
    _require(math.isfinite(initial_massfluid) and initial_massfluid > 0.0,
             "B initial MassFluid is not positive finite binary64")
    mass_f32 = np.asarray([initial_massfluid], dtype="<f4")[0]
    _require(np.isfinite(mass_f32) and mass_f32 > 0.0,
             "MassFluid cannot be represented as positive finite float32")

    t_count, p_count = len(times), len(fluid_ids)
    logical_bytes = 8 * t_count + 4 * p_count + 45 * t_count * p_count
    _require(t_count <= MAX_TIME_ROWS and p_count <= MAX_PARTICLE_ROWS
             and t_count * p_count <= MAX_TIME_PARTICLE_CELLS
             and logical_bytes <= MAX_LOGICAL_BYTES,
             "table dimensions or uncompressed logical bytes exceed the v2 limits")

    file_obj = os.fdopen(os.dup(table_fd), "rb", buffering=0)
    try:
        try:
            handle = h5py.File(file_obj, "r", driver="fileobj")
        except (OSError, ValueError, RuntimeError) as error:
            raise NativeFluidTableError("table is not a readable HDF5 file") from error
        with handle:
            _require(handle.userblock_size == 0, "HDF5 user block is forbidden")
            # H5Gget_num_objs counts all direct links, including soft and
            # external links. Requiring the exact cardinality and then
            # resolving all seven unique registered names as distinct hard
            # links proves that no unregistered root link is present, without
            # materializing potentially attacker-sized unknown link names.
            _require(handle.id.get_num_objs() == len(DATASET_DTYPES)
                     and len(handle.attrs) == len(ROOT_ATTRIBUTE_NAMES),
                     "HDF5 root object or attribute count exceeds the exact v2 contract")
            _validate_root_attributes(handle, expected_attributes)
            object_addresses: set[int] = set()
            for name in sorted(DATASET_DTYPES):
                link = handle.get(name, getlink=True)
                _require(isinstance(link, h5py.HardLink),
                         f"HDF5 object {name} is missing or is not a hard link")
                dataset = handle[name]
                _require(isinstance(dataset, h5py.Dataset), f"HDF5 root object {name} is not a dataset")
                address = int(h5py.h5o.get_info(dataset.id).addr)
                _require(address not in object_addresses, "HDF5 dataset names alias one hard-linked object")
                object_addresses.add(address)
                _require(dataset.dtype == DATASET_DTYPES[name],
                         f"HDF5 dataset {name} has a noncanonical dtype")
                if name != "valid":
                    _require(_is_exact_numeric_type(dataset.id.get_type(), DATASET_DTYPES[name]),
                             f"HDF5 dataset {name} is not the exact little-endian numeric type")
                expected_shape = ((t_count,) if name == "time" else
                                  (p_count,) if name == "particle_id" else
                                  (t_count, p_count, 3) if name in VECTOR_DATASETS else
                                  (t_count, p_count))
                _require(dataset.shape == expected_shape,
                         f"HDF5 dataset {name} has the wrong dimensions")
                _validate_filters_and_layout(dataset, name, p_count)

            # Only small time and ID axes are read before the frame loop.
            table_times = np.asarray(handle["time"][:], dtype="<f8")
            _require(_same_bits(table_times, times),
                     "HDF5 time dataset differs bitwise from the complete frozen C axis")
            table_ids = np.asarray(handle["particle_id"][:], dtype="<u4")
            _require(_same_bits(table_ids, fluid_ids),
                     "HDF5 particle_id differs from the exact sorted XML fluid cohort")

            seen_frames = 0
            mass_expected = np.full(p_count, mass_f32, dtype="<f4")
            for ordinal, frame in enumerate(source_frames):
                _require(ordinal < t_count, "more raw C frames were supplied than the frozen axis")
                _require(isinstance(frame, NativeSourceFrame), "source frame is not a bounded BI4 record")
                _require(frame.case_np == expected_case_np,
                         f"raw C frame {ordinal} CaseNp differs from the B generated XML universe")
                _require(frame.massfluid_binary64_le == initial_massfluid_binary64_le,
                         f"raw C frame {ordinal} MassFluid binary64 bits differ from B before conversion")
                _require(isinstance(frame.time_ieee754_hex, str)
                         and len(frame.time_ieee754_hex) <= 32,
                         f"raw C frame {ordinal} TimeStep exceeds its binary64 bound")
                try:
                    source_time = float.fromhex(frame.time_ieee754_hex)
                except (TypeError, ValueError) as error:
                    raise NativeFluidTableError(f"raw C frame {ordinal} TimeStep is malformed") from error
                _require(math.isfinite(source_time) and source_time.hex() == frame.time_ieee754_hex
                         and struct.pack("<d", source_time) == struct.pack("<d", times[ordinal]),
                         f"raw C frame {ordinal} TimeStep differs from the frozen full axis")

                ids = np.asarray(frame.particle_id)
                _require(ids.dtype == np.dtype("<u4") and ids.shape == (expected_case_np,),
                         f"raw C frame {ordinal} Idp is not the complete uint32 CaseNp axis")
                sorted_indices = np.argsort(ids, kind="stable")
                _require(_same_bits(ids[sorted_indices], np.arange(expected_case_np, dtype="<u4")),
                         f"raw C frame {ordinal} Idp contains missing, duplicate, unknown, or changed IDs")
                fluid_indices = sorted_indices[fluid_ids.astype(np.int64)]

                position = np.asarray(frame.position_m)
                velocity = np.asarray(frame.velocity_m_s)
                density = np.asarray(frame.density_kg_m3)
                _require(position.shape == (expected_case_np, 3)
                         and position.dtype in (np.dtype("<f4"), np.dtype("<f8")),
                         f"raw C frame {ordinal} Pos/Posd shape or dtype is invalid")
                _require(velocity.shape == (expected_case_np, 3) and velocity.dtype == np.dtype("<f4"),
                         f"raw C frame {ordinal} Vel shape or dtype is invalid")
                _require(density.shape == (expected_case_np,) and density.dtype == np.dtype("<f4"),
                         f"raw C frame {ordinal} Rhop shape or dtype is invalid")
                selected_position = np.asarray(position[fluid_indices], dtype="<f8")
                selected_velocity = np.asarray(velocity[fluid_indices], dtype="<f4")
                selected_density = np.asarray(density[fluid_indices], dtype="<f4")
                _require(np.isfinite(selected_position).all() and np.isfinite(selected_velocity).all(),
                         f"raw C frame {ordinal} fluid position/velocity contains non-finite values")
                _require(np.isfinite(selected_density).all() and np.all(selected_density > 0.0),
                         f"raw C frame {ordinal} fluid density is not positive finite")

                for start in range(0, p_count, MAX_CHUNK_PARTICLES):
                    stop = min(p_count, start + MAX_CHUNK_PARTICLES)
                    actual_position = np.asarray(handle["position"][ordinal, start:stop, :], dtype="<f8")
                    actual_velocity = np.asarray(handle["velocity"][ordinal, start:stop, :], dtype="<f4")
                    actual_density = np.asarray(handle["density"][ordinal, start:stop], dtype="<f4")
                    actual_mass = np.asarray(handle["mass"][ordinal, start:stop], dtype="<f4")
                    actual_valid = _read_valid_chunk_raw(handle["valid"], ordinal, start, stop)
                    _require(_same_bits(actual_position, selected_position[start:stop]),
                             f"HDF5 position row {ordinal} differs from raw BI4 projection")
                    _require(_same_bits(actual_velocity, selected_velocity[start:stop]),
                             f"HDF5 velocity row {ordinal} differs from raw BI4 projection")
                    _require(_same_bits(actual_density, selected_density[start:stop]),
                             f"HDF5 density row {ordinal} differs from raw BI4 Rhop projection")
                    _require(_same_bits(actual_mass, mass_expected[start:stop]),
                             f"HDF5 mass row {ordinal} differs from the exact B/C MassFluid conversion")
                    _require(actual_valid.shape == (stop - start,) and np.all(actual_valid == 1),
                             f"HDF5 valid row {ordinal} contains a non-TRUE enum value or absent fluid identity")
                seen_frames += 1
            _require(seen_frames == t_count,
                     "raw C source frame count does not equal the complete frozen native axis")
    finally:
        file_obj.close()

    after = os.fstat(table_fd)
    _require(_identity(before) == _identity(after)
             and _sha256_fd(table_fd, expected_table_bytes) == expected_table_sha256,
             "HDF5 table changed while its semantics were verified")
    return {
        "schema": SCHEMA,
        "table_schema": TABLE_SCHEMA,
        "case_id": expected_attributes["case_id"],
        "table_bytes": expected_table_bytes,
        "table_sha256": expected_table_sha256,
        "time_rows": t_count,
        "fluid_particle_count": p_count,
        "raw_frames_recomputed": seen_frames,
        "full_time_axis_matches": True,
        "fluid_id_projection_matches": True,
        "position_velocity_density_mass_recomputed": True,
        "all_valid": True,
        "native_integrity_evaluated": False,
        "T1_numerical": False,
        "qualification_credit": 0,
    }


__all__ = [
    "NativeFluidTableError", "NativeSourceFrame", "SCHEMA", "TABLE_SCHEMA",
    "expected_root_attributes", "read_native_source_frame_fd",
    "verify_native_fluid_table_fd",
]
