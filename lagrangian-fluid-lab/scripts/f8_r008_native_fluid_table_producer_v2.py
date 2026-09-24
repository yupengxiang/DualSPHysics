"""Bounded streaming writer for the reviewed F8 R008 native-fluid table v2.

This is a serialization primitive, not a B/C/D authority or solver worker. The
caller must supply canonical frozen attributes and a fresh source-frame stream
that is independently reopened/hash-checked on both passes. The producer
creates only the registered table file under a held output-directory FD, then
reuses the v2 semantic verifier before returning its byte binding.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
import secrets
import stat
import struct
from typing import Any, Callable, Iterable, Mapping

import h5py
import numpy as np

from scripts import f8_r008_native_fluid_table_v2 as table_v2
from scripts import f8_r008_safe_bi4_decoder_v1 as decoder


SCHEMA = "core.cfd.f8.r008_native_fluid_table_producer.v2"
TABLE_FILENAME = "native-fluid-frame-table-v2.h5"
HDF5_BOOLEAN = h5py.enum_dtype({"FALSE": 0, "TRUE": 1}, basetype=np.dtype("u1"))


class NativeFluidTableProducerError(ValueError):
    """The source stream, output namespace, or generated v2 table is invalid."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise NativeFluidTableProducerError(message)


def _fd_identity(st: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (st.st_dev, st.st_ino, st.st_mode, st.st_size,
            st.st_mtime_ns, st.st_ctime_ns)


def _close_stream(stream: Any) -> None:
    close = getattr(stream, "close", None)
    if callable(close):
        close()


def _validate_source_frame(
    frame: table_v2.NativeSourceFrame,
    ordinal: int,
    *,
    time_values: np.ndarray,
    fluid_ids: np.ndarray,
    case_np: int,
    massfluid_bytes: bytes,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    _require(isinstance(frame, table_v2.NativeSourceFrame),
             f"raw source frame {ordinal} is not a bounded NativeSourceFrame")
    _require(frame.case_np == case_np and frame.massfluid_binary64_le == massfluid_bytes,
             f"raw source frame {ordinal} CaseNp or binary64 MassFluid differs from B")
    _require(isinstance(frame.time_ieee754_hex, str) and len(frame.time_ieee754_hex) <= 32,
             f"raw source frame {ordinal} time encoding exceeds its bound")
    try:
        time_value = float.fromhex(frame.time_ieee754_hex)
    except (TypeError, ValueError) as error:
        raise NativeFluidTableProducerError(f"raw source frame {ordinal} time is malformed") from error
    _require(math.isfinite(time_value) and time_value.hex() == frame.time_ieee754_hex
             and struct.pack("<d", time_value) == struct.pack("<d", float(time_values[ordinal])),
             f"raw source frame {ordinal} time differs from the frozen native axis")

    raw_ids = np.asarray(frame.particle_id)
    _require(raw_ids.dtype == np.dtype("<u4") and raw_ids.shape == (case_np,),
             f"raw source frame {ordinal} Idp is not the exact full CaseNp uint32 axis")
    order = np.argsort(raw_ids, kind="stable")
    _require(np.array_equal(raw_ids[order], np.arange(case_np, dtype="<u4")),
             f"raw source frame {ordinal} Idp has a missing, duplicate, or unknown ID")
    fluid_indices = order[fluid_ids.astype(np.int64)]

    position = np.asarray(frame.position_m)
    velocity = np.asarray(frame.velocity_m_s)
    density = np.asarray(frame.density_kg_m3)
    _require(position.shape == (case_np, 3)
             and position.dtype in (np.dtype("<f4"), np.dtype("<f8")),
             f"raw source frame {ordinal} Pos/Posd shape or dtype is invalid")
    _require(velocity.shape == (case_np, 3) and velocity.dtype == np.dtype("<f4"),
             f"raw source frame {ordinal} Vel shape or dtype is invalid")
    _require(density.shape == (case_np,) and density.dtype == np.dtype("<f4"),
             f"raw source frame {ordinal} Rhop shape or dtype is invalid")
    selected_position = np.asarray(position[fluid_indices], dtype="<f8")
    selected_velocity = np.asarray(velocity[fluid_indices], dtype="<f4")
    selected_density = np.asarray(density[fluid_indices], dtype="<f4")
    _require(np.isfinite(selected_position).all() and np.isfinite(selected_velocity).all()
             and np.isfinite(selected_density).all() and np.all(selected_density > 0.0),
             f"raw source frame {ordinal} has non-finite state or non-positive fluid density")
    return selected_position, selected_velocity, selected_density


def _initialize_table(
    handle: h5py.File,
    *,
    attributes: Mapping[str, Any],
    times: np.ndarray,
    fluid_ids: np.ndarray,
) -> tuple[h5py.Dataset, ...]:
    for name, value in attributes.items():
        if name == "schema_version":
            handle.attrs.create(name, np.asarray(value, dtype="<u4"), dtype="<u4")
        elif name == "conversion_complete":
            # The published final name is created only after the full table has
            # been flushed and semantically verified. A visible temp file must
            # never claim conversion is complete while rows are still written.
            handle.attrs.create(name, np.asarray(0, dtype="u1"), dtype=HDF5_BOOLEAN)
        else:
            encoded = value.encode("utf-8")
            handle.attrs.create(
                name, value, dtype=h5py.string_dtype(encoding="utf-8", length=len(encoded)),
            )

    time_ds = handle.create_dataset("time", data=times, dtype="<f8")
    ids_ds = handle.create_dataset("particle_id", data=fluid_ids, dtype="<u4")
    t_count, p_count = len(times), len(fluid_ids)
    chunks_vector = (1, min(p_count, table_v2.MAX_CHUNK_PARTICLES), 3)
    chunks_scalar = (1, min(p_count, table_v2.MAX_CHUNK_PARTICLES))
    position_ds = handle.create_dataset(
        "position", shape=(t_count, p_count, 3), dtype="<f8",
        chunks=chunks_vector, compression="lzf", shuffle=False, fletcher32=False,
    )
    velocity_ds = handle.create_dataset(
        "velocity", shape=(t_count, p_count, 3), dtype="<f4",
        chunks=chunks_vector, compression="lzf", shuffle=False, fletcher32=False,
    )
    density_ds = handle.create_dataset(
        "density", shape=(t_count, p_count), dtype="<f4",
        chunks=chunks_scalar, compression="lzf", shuffle=False, fletcher32=False,
    )
    mass_ds = handle.create_dataset(
        "mass", shape=(t_count, p_count), dtype="<f4",
        chunks=chunks_scalar, compression="lzf", shuffle=False, fletcher32=False,
    )
    valid_ds = handle.create_dataset(
        "valid", shape=(t_count, p_count), dtype=HDF5_BOOLEAN,
        chunks=chunks_scalar, compression="lzf", shuffle=False, fletcher32=False,
    )
    return position_ds, velocity_ds, density_ds, mass_ds, valid_ds


def _remove_created_entry(
    parent_fd: int, name: str, output_fd: int, initial: os.stat_result,
) -> None:
    try:
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        held = os.fstat(output_fd)
        if (current.st_dev, current.st_ino) == (initial.st_dev, initial.st_ino) == (held.st_dev, held.st_ino):
            os.unlink(name, dir_fd=parent_fd)
            os.fsync(parent_fd)
    except FileNotFoundError:
        pass
    except OSError:
        # Preserve an uncertain/replaced entry; never unlink by name unless its
        # inode still matches the file this call created.
        pass


def produce_native_fluid_table_v2_at(
    output_directory_fd: int,
    *,
    expected_attributes: Mapping[str, Any],
    expected_time_axis_hex: Iterable[str],
    expected_fluid_ids: np.ndarray,
    expected_case_np: int,
    initial_massfluid_binary64_le: bytes,
    source_frames_factory: Callable[[], Iterable[table_v2.NativeSourceFrame]],
) -> dict[str, Any]:
    """Create and independently verify a v2 table beneath a held output dirfd.

    The frame factory is invoked twice. Both invocations must reopen the same
    caller-hash-bound C inputs safely: once for streaming projection and once
    for verifier recomputation. This primitive does not verify B/C receipts,
    authorization authenticity, or solver provenance by itself.
    """
    parent = os.fstat(output_directory_fd)
    _require(stat.S_ISDIR(parent.st_mode), "table output parent FD is not a directory")
    _require(callable(source_frames_factory), "source frame factory must be callable for two independent passes")
    table_v2._validate_expected_attributes(expected_attributes)
    times = table_v2._canonical_times(expected_time_axis_hex)
    _require(isinstance(expected_case_np, int) and not isinstance(expected_case_np, bool)
             and 0 < expected_case_np <= decoder.MAX_ARRAY_COUNT,
             "expected CaseNp is outside the reviewed raw BI4 limit")
    raw_fluid_ids = np.asarray(expected_fluid_ids)
    _require(raw_fluid_ids.ndim == 1 and raw_fluid_ids.dtype == np.dtype("<u4")
             and raw_fluid_ids.size > 0 and raw_fluid_ids.size <= table_v2.MAX_PARTICLE_ROWS,
             "expected fluid IDs are not a bounded uint32 vector")
    fluid_ids = np.ascontiguousarray(raw_fluid_ids)
    _require(np.all(fluid_ids[1:] > fluid_ids[:-1])
             and int(fluid_ids[-1]) < expected_case_np,
             "expected fluid IDs are not strictly increasing within CaseNp")
    _require(isinstance(initial_massfluid_binary64_le, bytes)
             and len(initial_massfluid_binary64_le) == 8,
             "initial MassFluid must be exact little-endian binary64 bytes")
    massfluid = struct.unpack("<d", initial_massfluid_binary64_le)[0]
    _require(math.isfinite(massfluid) and massfluid > 0.0,
             "initial MassFluid must be positive finite binary64")
    mass_f32 = np.asarray([massfluid], dtype="<f4")[0]
    _require(np.isfinite(mass_f32) and mass_f32 > 0.0,
             "initial MassFluid cannot be represented as positive finite float32")

    t_count, p_count = len(times), len(fluid_ids)
    logical_bytes = 8 * t_count + 4 * p_count + 45 * t_count * p_count
    _require(t_count <= table_v2.MAX_TIME_ROWS and p_count <= table_v2.MAX_PARTICLE_ROWS
             and t_count * p_count <= table_v2.MAX_TIME_PARTICLE_CELLS
             and logical_bytes <= table_v2.MAX_LOGICAL_BYTES,
             "requested v2 table dimensions exceed the reviewed uncompressed resource caps")

    try:
        os.stat(TABLE_FILENAME, dir_fd=output_directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        raise FileExistsError(f"registered table output already exists: {TABLE_FILENAME}")

    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    temporary_name = f"native-fluid-frame-table-v2-tmp-{secrets.token_hex(12)}.h5"
    output_fd = os.open(temporary_name, flags, 0o600, dir_fd=output_directory_fd)
    created = os.fstat(output_fd)
    published = False
    try:
        _require(stat.S_ISREG(created.st_mode) and created.st_nlink == 1 and created.st_size == 0,
                 "exclusive table output is not a new single-link regular file")
        output_stream = os.fdopen(os.dup(output_fd), "r+b", buffering=0)
        try:
            with h5py.File(output_stream, "w", driver="fileobj") as handle:
                datasets = _initialize_table(
                    handle, attributes=expected_attributes, times=times, fluid_ids=fluid_ids,
                )
                position_ds, velocity_ds, density_ds, mass_ds, valid_ds = datasets
                mass_row = np.full(p_count, mass_f32, dtype="<f4")
                valid_row = np.ones(p_count, dtype="u1")
                stream = iter(source_frames_factory())
                seen = 0
                try:
                    for ordinal, frame in enumerate(stream):
                        _require(ordinal < t_count,
                                 "first raw-source pass supplied more frames than the frozen time axis")
                        position, velocity, density = _validate_source_frame(
                            frame, ordinal, time_values=times, fluid_ids=fluid_ids,
                            case_np=expected_case_np,
                            massfluid_bytes=initial_massfluid_binary64_le,
                        )
                        position_ds[ordinal, :, :] = position
                        velocity_ds[ordinal, :, :] = velocity
                        density_ds[ordinal, :] = density
                        mass_ds[ordinal, :] = mass_row
                        valid_ds[ordinal, :] = valid_row
                        seen += 1
                finally:
                    _close_stream(stream)
                _require(seen == t_count,
                         "first raw-source pass does not cover the complete frozen time axis")
        finally:
            output_stream.close()
        os.fsync(output_fd)
        os.fsync(output_directory_fd)

        # Flip the registered boolean only after every row is present and the
        # first complete HDF5 image is durable. The final public basename stays
        # absent until independent source/table recomputation has passed.
        completion_stream = os.fdopen(os.dup(output_fd), "r+b", buffering=0)
        try:
            with h5py.File(completion_stream, "r+", driver="fileobj") as handle:
                attribute = handle.attrs.get_id("conversion_complete")
                raw_true = np.asarray(1, dtype="u1")
                attribute.write(raw_true, mtype=h5py.h5t.NATIVE_UINT8)
                handle.flush()
        finally:
            completion_stream.close()
        os.fsync(output_fd)

        written = os.fstat(output_fd)
        _require(written.st_size > 0 and written.st_size <= table_v2.MAX_TABLE_FILE_BYTES,
                 "generated v2 table is empty or exceeds the exact file-size cap")
        output_ro_fd = decoder.open_regular_beneath(output_directory_fd, temporary_name)
        try:
            ro_identity = os.fstat(output_ro_fd)
            _require((ro_identity.st_dev, ro_identity.st_ino, ro_identity.st_nlink)
                     == (created.st_dev, created.st_ino, 1)
                     and _fd_identity(os.fstat(output_fd)) == _fd_identity(written),
                     "created table output path was rebound before semantic verification")
            table_bytes = ro_identity.st_size
            table_sha256 = table_v2._sha256_fd(output_ro_fd, table_bytes)
            verify_stream = iter(source_frames_factory())
            try:
                table_result = table_v2.verify_native_fluid_table_fd(
                    output_ro_fd,
                    expected_table_bytes=table_bytes,
                    expected_table_sha256=table_sha256,
                    expected_attributes=expected_attributes,
                    expected_time_axis_hex=[value.hex() for value in times],
                    expected_fluid_ids=fluid_ids,
                    expected_case_np=expected_case_np,
                    initial_massfluid_binary64_le=initial_massfluid_binary64_le,
                    source_frames=verify_stream,
                )
            finally:
                _close_stream(verify_stream)
            after_verify = os.fstat(output_ro_fd)
            _require(_fd_identity(after_verify) == _fd_identity(ro_identity)
                     and table_v2._sha256_fd(output_ro_fd, table_bytes) == table_sha256,
                     "generated v2 table changed during independent semantic verification")
        finally:
            os.close(output_ro_fd)

        # Publish only the fully written, independently verified inode, without
        # replacing an existing final artifact. link+unlink is atomic at the
        # public name and leaves one hard link after successful publication.
        os.fchmod(output_fd, 0o644)
        os.fsync(output_fd)
        os.link(
            temporary_name, TABLE_FILENAME,
            src_dir_fd=output_directory_fd, dst_dir_fd=output_directory_fd,
            follow_symlinks=False,
        )
        published = True
        os.unlink(temporary_name, dir_fd=output_directory_fd)
        os.fsync(output_directory_fd)

        final_ro_fd = decoder.open_regular_beneath(output_directory_fd, TABLE_FILENAME)
        try:
            final_stat = os.fstat(final_ro_fd)
            _require((final_stat.st_dev, final_stat.st_ino, final_stat.st_nlink)
                     == (created.st_dev, created.st_ino, 1)
                     and final_stat.st_size == table_bytes
                     and table_v2._sha256_fd(final_ro_fd, table_bytes) == table_sha256,
                     "table output path no longer resolves to the verified single-link inode")
        finally:
            os.close(final_ro_fd)

        return {
            "schema": SCHEMA,
            "status": "v2_table_written_and_semantically_verified_caller_context_unverified",
            "table_binding": {
                "path": TABLE_FILENAME,
                "bytes": table_bytes,
                "sha256": table_sha256,
            },
            "native_fluid_table": table_result,
            "B_C_provenance_verified_by_this_primitive": False,
            "authorization_authenticity_verified_by_this_primitive": False,
            "native_integrity_evaluated": False,
            "T1_numerical": False,
            "qualification_credit": 0,
        }
    except BaseException:
        _remove_created_entry(output_directory_fd, temporary_name, output_fd, created)
        if published:
            _remove_created_entry(output_directory_fd, TABLE_FILENAME, output_fd, created)
        raise
    finally:
        os.close(output_fd)


__all__ = [
    "NativeFluidTableProducerError", "SCHEMA", "TABLE_FILENAME",
    "produce_native_fluid_table_v2_at",
]
