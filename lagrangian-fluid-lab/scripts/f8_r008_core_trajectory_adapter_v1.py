"""Materialize a diagnostic Core trajectory from a verified F8 fluid table.

The adapter adds Core's explicit ``particle_zone`` axis to R008's fluid-only
table and preserves its native position/velocity/time/ID/mass/valid values.
It validates the source table against the caller-supplied frozen contract and
raw-frame iterator, publishes one no-replace HDF5 artifact beneath a held
directory FD, and always labels the result qualification-only and
non-authorizing. It does not authenticate the caller, bundle roots, or
supervisor and cannot grant Core/F8 qualification credit.
"""
from __future__ import annotations

import ctypes
import fcntl
import hashlib
import h5py
import os
import stat
from typing import Any, Callable, Iterable, Mapping

import numpy as np

from scripts import f8_r008_native_fluid_table_v2 as table_v2
from scripts import f8_r008_native_integrity_registry_v1 as registry
from scripts import f8_r008_safe_bi4_decoder_v1 as decoder


SCHEMA = "core.cfd.f8.r008_core_trajectory_adapter.v1"
CORE_TRAJECTORY_SCHEMA = "core.f8.r008.diagnostic_trajectory.v1"
OUTPUT_FILENAME = "core-trajectory-v1.h5"
OUTPUT_DATASETS = frozenset({
    "time", "position", "velocity", "particle_id", "particle_zone",
    "mass", "valid", "density",
})
OUTPUT_ATTRIBUTES = {
    "schema": CORE_TRAJECTORY_SCHEMA,
    "source_table_schema": table_v2.TABLE_SCHEMA,
    "scope_id": table_v2.SCOPE_ID,
    "trajectory_semantics": "native_f8_fluid_only_qualification_diagnostic",
    "particle_zone_semantics": "all_native_fluid_particles_zone_zero",
    "split": "qualification",
    "diagnostic_only": True,
    "formal_eligible": False,
    "qualification_credit": 0,
}
PARTICLE_CHUNK = 4096
READ_CHUNK_BYTES = 1024 * 1024
_HEX = frozenset("0123456789abcdef")


class CoreTrajectoryAdapterError(ValueError):
    """The table or its derived diagnostic Core trajectory is invalid."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CoreTrajectoryAdapterError(message)


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _sha256_fd(fd: int, size: int) -> str:
    digest = hashlib.sha256()
    offset = 0
    while offset < size:
        block = os.pread(fd, min(READ_CHUNK_BYTES, size - offset), offset)
        _require(bool(block), "held HDF5 descriptor was truncated while hashing")
        digest.update(block)
        offset += len(block)
    _require(os.pread(fd, 1, size) == b"", "held HDF5 descriptor grew while hashing")
    return digest.hexdigest()


def _require_readonly_single_link(fd: int, *, expected_bytes: int, label: str) -> os.stat_result:
    _require(type(expected_bytes) is int and expected_bytes > 0,
             f"{label} byte count must be a positive builtin integer")
    _require(type(fd) is int and fd >= 0, f"{label} FD must be a nonnegative builtin integer")
    try:
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        descriptor_flags = fcntl.fcntl(fd, fcntl.F_GETFD)
        info = os.fstat(fd)
    except OSError as error:
        raise CoreTrajectoryAdapterError(f"{label} FD is not open") from error
    _require(flags & os.O_ACCMODE == os.O_RDONLY,
             f"{label} FD must be read-only")
    _require(bool(descriptor_flags & fcntl.FD_CLOEXEC),
             f"{label} FD must be close-on-exec")
    _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
             and info.st_size == expected_bytes,
             f"{label} FD must be the exact-size single-link regular file")
    return info


def _open_readonly_held_fd(fd: int) -> int:
    """Reopen a held Linux FD read-only without resolving a caller path."""
    before = os.fstat(fd)
    readonly_fd = os.open(f"/proc/self/fd/{fd}", os.O_RDONLY | os.O_CLOEXEC)
    try:
        after = os.fstat(readonly_fd)
        _require(stat.S_ISREG(after.st_mode)
                 and (after.st_dev, after.st_ino, after.st_size)
                 == (before.st_dev, before.st_ino, before.st_size),
                 "read-only proc-fd reopen changed the held output inode")
        return readonly_fd
    except BaseException:
        os.close(readonly_fd)
        raise


def _open_h5_file(fd: int, mode: str) -> tuple[Any, h5py.File]:
    file_mode = "rb" if mode == "r" else "r+b"
    stream = os.fdopen(os.dup(fd), file_mode, buffering=0)
    try:
        return stream, h5py.File(stream, mode, driver="fileobj")
    except BaseException:
        stream.close()
        raise


def _close_h5_pair(handle: h5py.File, stream: Any) -> None:
    try:
        handle.close()
    finally:
        stream.close()


def _write_attributes(handle: h5py.File, attributes: Mapping[str, Any]) -> None:
    for name, value in attributes.items():
        handle.attrs[name] = value


def _same_bits(actual: Any, expected: Any, dtype: str) -> bool:
    left = np.ascontiguousarray(actual, dtype=np.dtype(dtype))
    right = np.ascontiguousarray(expected, dtype=np.dtype(dtype))
    return left.shape == right.shape and left.tobytes() == right.tobytes()


def _validate_and_copy_table(
    table_fd: int,
    output_fd: int,
    *,
    expected_bytes: int,
    expected_sha256: str,
    expected_attributes: Mapping[str, Any],
    expected_time_axis_hex: Iterable[str],
    expected_fluid_ids: Any,
    expected_case_np: int,
    initial_massfluid_binary64_le: bytes,
    source_frames_factory: Callable[[], Iterable[table_v2.NativeSourceFrame]],
) -> tuple[dict[str, Any], int, int]:
    _require(type(expected_bytes) is int and 0 < expected_bytes <= table_v2.MAX_TABLE_FILE_BYTES,
             "native-fluid table byte count is outside the frozen v2 file-size cap")
    before = _require_readonly_single_link(
        table_fd, expected_bytes=expected_bytes, label="native-fluid table",
    )
    _require(bool(expected_sha256) and len(expected_sha256) == 64
             and all(character in _HEX for character in expected_sha256),
             "native-fluid table SHA-256 must be lowercase hexadecimal")
    _require(_sha256_fd(table_fd, expected_bytes) == expected_sha256,
             "native-fluid table raw bytes differ from the declared binding")
    _require(callable(source_frames_factory),
             "native source-frame factory must be callable")
    source_frames = source_frames_factory()
    try:
        table_verification = table_v2.verify_native_fluid_table_fd(
            table_fd,
            expected_table_bytes=expected_bytes,
            expected_table_sha256=expected_sha256,
            expected_attributes=expected_attributes,
            expected_time_axis_hex=expected_time_axis_hex,
            expected_fluid_ids=expected_fluid_ids,
            expected_case_np=expected_case_np,
            initial_massfluid_binary64_le=initial_massfluid_binary64_le,
            source_frames=source_frames,
        )
    finally:
        close = getattr(source_frames, "close", None)
        if callable(close):
            close()

    stream, source = _open_h5_file(table_fd, "r")
    try:
        time_count, particle_count = source["position"].shape[:2]
        _require(2 <= time_count <= table_v2.MAX_TIME_ROWS
                 and 1 <= particle_count <= table_v2.MAX_PARTICLE_ROWS
                 and time_count * particle_count <= table_v2.MAX_TIME_PARTICLE_CELLS,
                 "verified table dimensions exceed Core trajectory resource bounds")
        destination_stream, destination = _open_h5_file(output_fd, "w")
        try:
            _write_attributes(destination, {
                **OUTPUT_ATTRIBUTES,
                "case_id": expected_attributes["case_id"],
                "source_table_bytes": expected_bytes,
                "source_table_sha256": expected_sha256,
            })
            destination.create_dataset("time", shape=(time_count,), dtype="<f8")
            destination.create_dataset("particle_id", shape=(particle_count,), dtype="<u4")
            destination.create_dataset(
                "particle_zone", data=np.zeros(particle_count, dtype="<i8"), dtype="<i8",
            )
            chunks_vector = (1, min(PARTICLE_CHUNK, particle_count), 3)
            chunks_scalar = (1, min(PARTICLE_CHUNK, particle_count))
            for name, dtype in (("position", "<f8"), ("velocity", "<f4")):
                destination.create_dataset(
                    name, shape=(time_count, particle_count, 3), dtype=dtype,
                    chunks=chunks_vector, compression="lzf",
                )
            for name, dtype in (("density", "<f4"), ("mass", "<f4"), ("valid", "u1")):
                destination.create_dataset(
                    name, shape=(time_count, particle_count), dtype=dtype,
                    chunks=chunks_scalar, compression="lzf",
                )
            destination["time"][:] = source["time"][:]
            destination["particle_id"][:] = source["particle_id"][:]
            for ordinal in range(time_count):
                for start in range(0, particle_count, PARTICLE_CHUNK):
                    stop = min(particle_count, start + PARTICLE_CHUNK)
                    for name in ("position", "velocity", "density", "mass"):
                        destination[name][ordinal, start:stop] = source[name][ordinal, start:stop]
                    destination["valid"][ordinal, start:stop] = np.asarray(
                        source["valid"][ordinal, start:stop], dtype="u1",
                    )
            destination.flush()
        finally:
            _close_h5_pair(destination, destination_stream)
    finally:
        _close_h5_pair(source, stream)

    after = os.fstat(table_fd)
    _require(_identity(after) == _identity(before)
             and _sha256_fd(table_fd, expected_bytes) == expected_sha256,
             "native-fluid table changed while deriving the Core trajectory")
    return table_verification, time_count, particle_count


def _verify_trajectory_fd(
    output_fd: int,
    table_fd: int,
    *,
    expected_output_bytes: int,
    expected_output_sha256: str,
    expected_table_sha256: str,
    case_id: str,
    expected_output_links: int = 1,
) -> None:
    output_before = os.fstat(output_fd)
    output_flags = fcntl.fcntl(output_fd, fcntl.F_GETFL)
    output_descriptor_flags = fcntl.fcntl(output_fd, fcntl.F_GETFD)
    _require(stat.S_ISREG(output_before.st_mode)
             and output_flags & os.O_ACCMODE == os.O_RDONLY
             and output_descriptor_flags & fcntl.FD_CLOEXEC
             and type(expected_output_links) is int
             and output_before.st_nlink == expected_output_links
             and output_before.st_size == expected_output_bytes,
             "Core trajectory FD has the wrong inode link count or exact size")
    _require(_sha256_fd(output_fd, expected_output_bytes) == expected_output_sha256,
             "Core trajectory hash differs from its exact post-write binding")
    output_stream, output = _open_h5_file(output_fd, "r")
    table_stream, table = _open_h5_file(table_fd, "r")
    try:
        _require(output.userblock_size == 0 and output.id.get_num_objs() == len(OUTPUT_DATASETS)
                 and set(output) == OUTPUT_DATASETS,
                 "Core trajectory root datasets do not match the exact adapter schema")
        required_attributes = {
            **OUTPUT_ATTRIBUTES, "case_id": case_id,
            "source_table_bytes": os.fstat(table_fd).st_size,
            "source_table_sha256": expected_table_sha256,
        }
        _require(set(output.attrs) == set(required_attributes),
                 "Core trajectory root attributes do not match the exact adapter schema")
        for name, expected in required_attributes.items():
            observed = output.attrs[name]
            if isinstance(expected, str) and isinstance(observed, bytes):
                observed = observed.decode("utf-8", errors="strict")
            _require(observed == expected,
                     f"Core trajectory attribute {name} differs from its frozen value")

        time_count, particle_count = table["position"].shape[:2]
        expected_shapes = {
            "time": (time_count,), "particle_id": (particle_count,),
            "particle_zone": (particle_count,),
            "position": (time_count, particle_count, 3),
            "velocity": (time_count, particle_count, 3),
            "density": (time_count, particle_count),
            "mass": (time_count, particle_count), "valid": (time_count, particle_count),
        }
        for name, shape in expected_shapes.items():
            _require(isinstance(output.get(name, getlink=True), h5py.HardLink)
                     and isinstance(output[name], h5py.Dataset)
                     and output[name].shape == shape,
                     f"Core trajectory dataset {name} has a noncanonical link or shape")
        object_addresses = set()
        for name in sorted(OUTPUT_DATASETS):
            address = int(h5py.h5o.get_info(output[name].id).addr)
            _require(address not in object_addresses,
                     "Core trajectory dataset names alias one hard-linked HDF5 object")
            object_addresses.add(address)
        _require(output["time"].dtype == np.dtype("<f8")
                 and output["particle_id"].dtype == np.dtype("<u4")
                 and output["particle_zone"].dtype == np.dtype("<i8")
                 and output["position"].dtype == np.dtype("<f8")
                 and output["velocity"].dtype == np.dtype("<f4")
                 and output["density"].dtype == np.dtype("<f4")
                 and output["mass"].dtype == np.dtype("<f4")
                 and output["valid"].dtype == np.dtype("u1"),
                 "Core trajectory dataset dtypes differ from the exact adapter schema")
        _require(_same_bits(output["time"][:], table["time"][:], "<f8")
                 and _same_bits(output["particle_id"][:], table["particle_id"][:], "<u4")
                 and np.array_equal(output["particle_zone"][:], np.zeros(particle_count, dtype="<i8")),
                 "Core time, identity, or fluid-zone axis differs from its native table")
        for ordinal in range(time_count):
            for start in range(0, particle_count, PARTICLE_CHUNK):
                stop = min(particle_count, start + PARTICLE_CHUNK)
                for name, dtype in (("position", "<f8"), ("velocity", "<f4"),
                                    ("density", "<f4"), ("mass", "<f4"),
                                    ("valid", "u1")):
                    _require(_same_bits(
                        output[name][ordinal, start:stop],
                        table[name][ordinal, start:stop], dtype,
                    ), f"Core trajectory {name} differs from its verified native-fluid table")
    finally:
        try:
            _close_h5_pair(output, output_stream)
        finally:
            _close_h5_pair(table, table_stream)
    output_after = os.fstat(output_fd)
    _require(_identity(output_after) == _identity(output_before)
             and _sha256_fd(output_fd, expected_output_bytes) == expected_output_sha256,
             "published Core trajectory changed during post-write verification")


def _link_unnamed_noreplace_at(
    output_fd: int, directory_fd: int, destination: str,
) -> None:
    """Publish the exact held O_TMPFILE inode without replacing a name."""
    before = os.fstat(output_fd)
    _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 0,
             "trajectory publication source must be an unnamed regular inode")
    libc = ctypes.CDLL(None, use_errno=True)
    linkat = getattr(libc, "linkat", None)
    if linkat is None:
        raise CoreTrajectoryAdapterError(
            "FD-bound AT_SYMLINK_FOLLOW publication is unavailable on this platform",
        )
    linkat.argtypes = [ctypes.c_int, ctypes.c_char_p,
                       ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    linkat.restype = ctypes.c_int
    held_fd_path = os.fsencode(f"/proc/self/fd/{output_fd}")
    result = linkat(-100, held_fd_path, directory_fd,
                    os.fsencode(destination), 0x400)  # AT_FDCWD, AT_SYMLINK_FOLLOW
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), destination)
    after = os.fstat(output_fd)
    named = os.stat(destination, dir_fd=directory_fd, follow_symlinks=False)
    _require((after.st_dev, after.st_ino, after.st_nlink)
             == (before.st_dev, before.st_ino, 1)
             and (named.st_dev, named.st_ino, named.st_nlink)
             == (before.st_dev, before.st_ino, 1),
             "published trajectory name differs from the exact held O_TMPFILE inode")


def materialize_diagnostic_core_trajectory_v1_at(
    table_fd: int,
    output_directory_fd: int,
    *,
    case_id: str,
    expected_table_bytes: int,
    expected_table_sha256: str,
    expected_attributes: Mapping[str, Any],
    expected_time_axis_hex: Iterable[str],
    expected_fluid_ids: Any,
    expected_case_np: int,
    initial_massfluid_binary64_le: bytes,
    source_frames_factory: Callable[[], Iterable[table_v2.NativeSourceFrame]],
) -> dict[str, Any]:
    """Create one no-replace Core-readable, qualification-only HDF5 trajectory.

    The trajectory is built in an unnamed ``O_TMPFILE`` inode and published
    directly from its held FD. Pre-publication errors leave no named partial;
    post-publication errors retain the final artifact for explicit review.
    No temporary source pathname or failure-path unlink is used.
    """
    _require(type(expected_table_bytes) is int
             and 0 < expected_table_bytes <= table_v2.MAX_TABLE_FILE_BYTES,
             "native-fluid table byte count is outside the frozen v2 file-size cap")
    _require(type(expected_table_sha256) is str and len(expected_table_sha256) == 64
             and all(character in _HEX for character in expected_table_sha256),
             "native-fluid table SHA-256 must be lowercase hexadecimal")
    _require(type(case_id) is str
             and case_id in set(registry.frozen_qualification_case_ids()),
             "case_id is outside the frozen R008 qualification denominator")
    _require(isinstance(expected_attributes, Mapping)
             and expected_attributes.get("scope_id") == table_v2.SCOPE_ID
             and expected_attributes.get("case_id") == case_id
             and expected_attributes.get("data_qualification_status") == "qualification_only",
             "native table attributes must name this case as a qualification row")
    _require(type(output_directory_fd) is int and output_directory_fd >= 0,
             "output directory must be supplied as a held nonnegative FD")
    try:
        directory_stat = os.fstat(output_directory_fd)
    except OSError as error:
        raise CoreTrajectoryAdapterError("output directory FD is not open") from error
    _require(stat.S_ISDIR(directory_stat.st_mode)
             and directory_stat.st_uid == os.geteuid()
             and not (directory_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH)),
             "output directory must be current-user-owned and not group/world-writable")
    directory_flags = fcntl.fcntl(output_directory_fd, fcntl.F_GETFL)
    directory_descriptor_flags = fcntl.fcntl(output_directory_fd, fcntl.F_GETFD)
    _require(directory_flags & os.O_ACCMODE == os.O_RDONLY
             and directory_descriptor_flags & fcntl.FD_CLOEXEC,
             "output directory FD must be read-only and close-on-exec")
    for required_flag in ("O_NOFOLLOW", "O_CLOEXEC", "O_DIRECTORY"):
        _require(hasattr(os, required_flag), f"platform lacks {required_flag}")
    try:
        os.stat(OUTPUT_FILENAME, dir_fd=output_directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        raise FileExistsError(OUTPUT_FILENAME)

    table_before = _require_readonly_single_link(
        table_fd, expected_bytes=expected_table_bytes, label="native-fluid table",
    )
    _require(_sha256_fd(table_fd, expected_table_bytes) == expected_table_sha256,
             "native-fluid table hash differs from the exact caller binding")
    _require(bool(getattr(os, "O_TMPFILE", 0)),
             "platform lacks unnamed O_TMPFILE trajectory staging")
    try:
        output_fd = os.open(
            ".", os.O_TMPFILE | os.O_RDWR | os.O_CLOEXEC, 0o600,
            dir_fd=output_directory_fd,
        )
    except OSError as error:
        raise CoreTrajectoryAdapterError(
            "output filesystem does not support unnamed O_TMPFILE staging",
        ) from error
    created = os.fstat(output_fd)
    try:
        _require(stat.S_ISREG(created.st_mode) and created.st_nlink == 0
                 and created.st_size == 0,
                 "unnamed Core trajectory output is not a new empty unlinked file")
        table_verification, time_count, particle_count = _validate_and_copy_table(
            table_fd, output_fd,
            expected_bytes=expected_table_bytes,
            expected_sha256=expected_table_sha256,
            expected_attributes=expected_attributes,
            expected_time_axis_hex=expected_time_axis_hex,
            expected_fluid_ids=expected_fluid_ids,
            expected_case_np=expected_case_np,
            initial_massfluid_binary64_le=initial_massfluid_binary64_le,
            source_frames_factory=source_frames_factory,
        )
        os.fsync(output_fd)
        os.fsync(output_directory_fd)
        output_size = os.fstat(output_fd).st_size
        _require(0 < output_size <= table_v2.MAX_TABLE_FILE_BYTES,
                 "Core trajectory output size is outside the bounded file limit")
        output_sha256 = _sha256_fd(output_fd, output_size)
        temp_ro_fd = _open_readonly_held_fd(output_fd)
        try:
            temp_stat = os.fstat(temp_ro_fd)
            _require((temp_stat.st_dev, temp_stat.st_ino, temp_stat.st_nlink)
                     == (created.st_dev, created.st_ino, 0),
                     "read-only trajectory FD differs from the unnamed output inode")
            _verify_trajectory_fd(
                temp_ro_fd, table_fd,
                expected_output_bytes=output_size,
                expected_output_sha256=output_sha256,
                expected_table_sha256=expected_table_sha256,
                case_id=case_id,
                expected_output_links=0,
            )
        finally:
            os.close(temp_ro_fd)

        _link_unnamed_noreplace_at(output_fd, output_directory_fd, OUTPUT_FILENAME)
        os.fsync(output_directory_fd)
        final_fd = os.open(
            OUTPUT_FILENAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=output_directory_fd,
        )
        try:
            final_stat = os.fstat(final_fd)
            _require((final_stat.st_dev, final_stat.st_ino, final_stat.st_nlink)
                     == (created.st_dev, created.st_ino, 1)
                     and final_stat.st_size == output_size
                     and _sha256_fd(final_fd, output_size) == output_sha256,
                     "published Core trajectory is not the verified single-link inode")
            _verify_trajectory_fd(
                final_fd, table_fd,
                expected_output_bytes=output_size,
                expected_output_sha256=output_sha256,
                expected_table_sha256=expected_table_sha256,
                case_id=case_id,
            )
            final_info = os.fstat(final_fd)
            name_info = os.stat(
                OUTPUT_FILENAME, dir_fd=output_directory_fd, follow_symlinks=False,
            )
            _require(stat.S_ISREG(name_info.st_mode)
                     and _identity(name_info) == _identity(final_info)
                     and (name_info.st_dev, name_info.st_ino, name_info.st_nlink,
                          name_info.st_size)
                     == (created.st_dev, created.st_ino, 1, output_size)
                     and _sha256_fd(final_fd, output_size) == output_sha256,
                     "published Core trajectory path no longer resolves to the verified inode")
        finally:
            os.close(final_fd)
        _require(_identity(os.fstat(table_fd)) == _identity(table_before)
                 and _sha256_fd(table_fd, expected_table_bytes) == expected_table_sha256,
                 "native-fluid table changed before trajectory publication completed")
        return {
            "schema": SCHEMA,
            "status": "diagnostic_qualification_trajectory_written_and_reverified",
            "scope_id": table_v2.SCOPE_ID,
            "case_id": case_id,
            "trajectory_schema": CORE_TRAJECTORY_SCHEMA,
            "trajectory_binding": {
                "path": OUTPUT_FILENAME,
                "bytes": output_size,
                "sha256": output_sha256,
            },
            "source_table_sha256": expected_table_sha256,
            "time_rows": time_count,
            "fluid_particle_count": particle_count,
            "particle_zone_value": 0,
            "split": "qualification",
            "source_provenance_authenticated": False,
            "formal_eligible": False,
            "full_t1_decision": False,
            "qualification_credit": 0,
            "native_table_verification": table_verification,
        }
    finally:
        os.close(output_fd)


__all__ = [
    "CORE_TRAJECTORY_SCHEMA", "CoreTrajectoryAdapterError", "OUTPUT_FILENAME",
    "OUTPUT_ATTRIBUTES", "SCHEMA", "materialize_diagnostic_core_trajectory_v1_at",
]
