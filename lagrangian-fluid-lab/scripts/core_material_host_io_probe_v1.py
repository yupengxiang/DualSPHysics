#!/usr/bin/env python3
"""A bounded, diagnostic-only host-I/O probe for F3/F4 material proposals.

The probe performs one small write -> fsync -> read cycle inside a newly
created directory below the operating-system temporary directory.  It never
opens a production HDF5 file, imports a material worker, starts a solver or
GPU, touches a queue, or changes a campaign admission/registry/ledger.

The result is an *observation*, not an authorization.  A successful result
therefore still has ``worker_launch_authorized == False`` and
``formal_admission == False``.  The report is deliberately fail-closed:
input errors, measurement exceptions, and incomplete reports can never be
interpreted as a passing probe.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
import time
from typing import Any, Mapping, Sequence


SCHEMA = "core.material.host_io_probe.v1"
PROBE_NAME = "f3_f4_material_host_io_admission_probe"
WORKSPACE_PREFIX = "core-material-host-io-probe-v1-"
PROBE_FILE_NAME = "io-probe.bin"

# The workspace is intentionally small and fixed.  This is a contract bound
# for the probe itself, not a capacity claim for a future material worker.
MAX_WORKSPACE_BYTES = 8 * 1024 * 1024
DEFAULT_PROBE_BYTES = 64 * 1024
DEFAULT_MINIMUM_FREE_DISK_BYTES = 8 * 1024**3
IO_CHUNK_BYTES = 64 * 1024
MAX_CONCURRENCY = 4096
MAX_PROJECTED_IO_BYTES = 1 << 50

LAB_ROOT = Path(__file__).resolve().parents[1]

_MOUNT_ESCAPE = re.compile(r"\\([0-7]{3})")

REQUIRED_TOP_LEVEL_FIELDS = (
    "schema",
    "probe",
    "status",
    "observed_at_utc",
    "request",
    "workspace",
    "filesystem",
    "disk",
    "cpu",
    "ram",
    "owned_io_projection",
    "io_measurement",
    "authorization_boundary",
    "execution_controls",
    "failure",
)

REQUIRED_PATHS = (
    ("probe", "probe_pass"),
    ("probe", "contract_valid"),
    ("probe", "measurement_complete"),
    ("probe", "checks"),
    ("request", "family_scope"),
    ("request", "probe_bytes"),
    ("request", "concurrency"),
    ("request", "owned_io_bytes_per_worker"),
    ("request", "minimum_free_disk_bytes"),
    ("workspace", "kind"),
    ("workspace", "parent"),
    ("workspace", "path"),
    ("workspace", "file_name"),
    ("workspace", "max_files"),
    ("workspace", "max_bytes"),
    ("workspace", "requested_payload_bytes"),
    ("workspace", "used_bytes"),
    ("workspace", "cleaned"),
    ("workspace", "exists_after_cleanup"),
    ("filesystem", "before"),
    ("filesystem", "after"),
    ("filesystem", "stable"),
    ("disk", "before"),
    ("disk", "after"),
    ("disk", "required_free_bytes"),
    ("disk", "minimum_free_bytes"),
    ("disk", "free_disk_pass"),
    ("cpu", "before"),
    ("cpu", "after"),
    ("ram", "before"),
    ("ram", "after"),
    ("owned_io_projection", "concurrency"),
    ("owned_io_projection", "owned_io_bytes_per_worker"),
    ("owned_io_projection", "projected_owned_io_bytes"),
    ("owned_io_projection", "probe_write_bytes"),
    ("owned_io_projection", "probe_read_bytes"),
    ("owned_io_projection", "projected_total_io_bytes"),
    ("owned_io_projection", "observed"),
    ("io_measurement", "bytes_requested"),
    ("io_measurement", "bytes_written"),
    ("io_measurement", "bytes_read"),
    ("io_measurement", "fsync_count"),
    ("io_measurement", "write_elapsed_seconds"),
    ("io_measurement", "fsync_elapsed_seconds"),
    ("io_measurement", "read_elapsed_seconds"),
    ("io_measurement", "elapsed_seconds"),
    ("io_measurement", "readback_sha256_match"),
    ("io_measurement", "workspace_file_count_after_write"),
    ("io_measurement", "workspace_bytes_after_write"),
    ("io_measurement", "workspace_file_count_after_remove"),
    ("io_measurement", "workspace_bytes_after_remove"),
    ("authorization_boundary", "probe_is_authorization"),
    ("authorization_boundary", "root_authorization_required"),
    ("authorization_boundary", "scheduler_authorization_required"),
    ("authorization_boundary", "worker_launch_authorized"),
    ("authorization_boundary", "formal_admission"),
    ("authorization_boundary", "formal_eligible"),
    ("authorization_boundary", "qualification_credit"),
    ("execution_controls", "production_hdf5_opened"),
    ("execution_controls", "material_worker_started"),
    ("execution_controls", "solver_started"),
    ("execution_controls", "gpu_initialized"),
    ("execution_controls", "queue_or_scheduler_started"),
    ("execution_controls", "core_runtime_admission_mutated"),
    ("execution_controls", "registry_mutations"),
    ("execution_controls", "completion_mutations"),
    ("execution_controls", "ledger_mutations"),
    ("execution_controls", "denominator_mutations"),
    ("execution_controls", "gate_mutations"),
)

_REQUIRED_FS_FIELDS = (
    "path",
    "device_id",
    "device_major",
    "device_minor",
    "filesystem_id",
    "filesystem_type",
    "mount_point",
    "block_size",
)
_REQUIRED_DISK_FIELDS = ("free_bytes", "total_bytes", "block_size")
_REQUIRED_CPU_FIELDS = (
    "logical_cpu_count",
    "affinity_cpu_count",
    "load_average_1_5_15",
)
_REQUIRED_RAM_FIELDS = ("total_bytes", "available_bytes", "source")

_SUCCESS_CHECK_NAMES = frozenset(
    {
        "workspace_bounded",
        "workspace_cleaned",
        "workspace_usage_exact",
        "filesystem_identity_present",
        "filesystem_identity_stable",
        "free_disk_headroom",
        "concurrency_within_affinity",
        "bytes_exact",
        "fsync_completed",
        "readback_hash_match",
        "elapsed_fields_finite",
    }
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_nonnegative_int(value: Any) -> bool:
    return _is_int(value) and value >= 0


def _is_positive_int(value: Any) -> bool:
    return _is_int(value) and value > 0


def _is_finite_nonnegative(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) and float(value) >= 0.0


def _pattern_chunk(offset: int, size: int) -> bytes:
    """Return deterministic bytes without reading any project artifact."""

    return bytes(((offset + index) % 251 for index in range(size)))


def _decode_mount_field(value: str) -> str:
    return _MOUNT_ESCAPE.sub(lambda match: chr(int(match.group(1), 8)), value)


def _mount_identity(path: Path) -> tuple[str, str, str]:
    """Return mount point, filesystem type, and source from Linux mountinfo."""

    target = str(path.resolve())
    mountinfo = Path("/proc/self/mountinfo")
    if not mountinfo.is_file():
        raise OSError("/proc/self/mountinfo is unavailable")

    best: tuple[str, str, str] | None = None
    for line in mountinfo.read_text(encoding="utf-8").splitlines():
        if " - " not in line:
            continue
        pre, post = line.split(" - ", 1)
        pre_fields = pre.split()
        post_fields = post.split()
        if len(pre_fields) < 5 or len(post_fields) < 3:
            continue
        mount_point = _decode_mount_field(pre_fields[4])
        if target != mount_point and not target.startswith(mount_point.rstrip("/") + "/"):
            continue
        if best is None or len(mount_point) > len(best[0]):
            best = (mount_point, post_fields[0], post_fields[1])
    if best is None:
        raise OSError(f"filesystem mount identity unavailable for {path}")
    return best


def _filesystem_identity(path: Path) -> dict[str, Any]:
    path = path.resolve()
    stat_result = path.stat()
    statvfs_result = os.statvfs(path)
    filesystem_id = getattr(statvfs_result, "f_fsid", None)
    block_size = getattr(statvfs_result, "f_frsize", 0) or getattr(statvfs_result, "f_bsize", 0)
    if not _is_nonnegative_int(int(stat_result.st_dev)):
        raise ValueError("filesystem device id is invalid")
    if filesystem_id is None:
        raise ValueError("filesystem id is unavailable")
    if not _is_nonnegative_int(int(filesystem_id)):
        raise ValueError("filesystem id is invalid")
    if not _is_positive_int(int(block_size)):
        raise ValueError("filesystem block size is invalid")
    mount_point, filesystem_type, mount_source = _mount_identity(path)
    if not filesystem_type or not mount_point:
        raise ValueError("filesystem type or mount point is missing")
    device_id = int(stat_result.st_dev)
    return {
        "path": str(path),
        "device_id": device_id,
        "device_major": int(os.major(device_id)) if hasattr(os, "major") else None,
        "device_minor": int(os.minor(device_id)) if hasattr(os, "minor") else None,
        "filesystem_id": int(filesystem_id),
        "filesystem_type": filesystem_type,
        "mount_point": mount_point,
        "mount_source": mount_source,
        "block_size": int(block_size),
    }


def _disk_snapshot(path: Path) -> dict[str, Any]:
    statvfs_result = os.statvfs(path)
    block_size = getattr(statvfs_result, "f_frsize", 0) or getattr(statvfs_result, "f_bsize", 0)
    values = {
        "free_bytes": int(statvfs_result.f_bavail) * int(block_size),
        "total_bytes": int(statvfs_result.f_blocks) * int(block_size),
        "block_size": int(block_size),
        "available_blocks": int(statvfs_result.f_bavail),
        "free_blocks": int(statvfs_result.f_bfree),
    }
    if not all(_is_nonnegative_int(values[name]) for name in _REQUIRED_DISK_FIELDS):
        raise ValueError("disk snapshot contains an invalid required field")
    if values["total_bytes"] < values["free_bytes"]:
        raise ValueError("disk snapshot free bytes exceed total bytes")
    return values


def _cpu_snapshot() -> dict[str, Any]:
    logical = os.cpu_count()
    if logical is None or logical < 1:
        raise OSError("logical CPU count is unavailable")
    if hasattr(os, "sched_getaffinity"):
        affinity_ids = sorted(int(item) for item in os.sched_getaffinity(0))
    else:
        affinity_ids = list(range(int(logical)))
    if not affinity_ids:
        raise OSError("process CPU affinity is empty")
    load_average = tuple(float(item) for item in os.getloadavg())
    if len(load_average) != 3 or not all(math.isfinite(item) and item >= 0.0 for item in load_average):
        raise ValueError("load average snapshot is invalid")
    return {
        "logical_cpu_count": int(logical),
        "affinity_cpu_count": len(affinity_ids),
        "affinity_cpu_ids": affinity_ids,
        "load_average_1_5_15": list(load_average),
        "source": "os.cpu_count+process_affinity+os.getloadavg",
    }


def _ram_snapshot() -> dict[str, Any]:
    meminfo = Path("/proc/meminfo")
    values: dict[str, int] = {}
    source = "sysconf"
    if meminfo.is_file():
        source = str(meminfo)
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0].endswith(":") and _is_int(int(parts[1])):
                multiplier = 1024 if len(parts) >= 3 and parts[2].lower() == "kb" else 1
                values[parts[0][:-1]] = int(parts[1]) * multiplier
    if "MemTotal" not in values or "MemAvailable" not in values:
        try:
            page_size = int(os.sysconf("SC_PAGE_SIZE"))
            page_count = int(os.sysconf("SC_PHYS_PAGES"))
            available_pages = int(os.sysconf("SC_AVPHYS_PAGES"))
        except (AttributeError, OSError, ValueError) as error:
            raise OSError("RAM snapshot is unavailable") from error
        values["MemTotal"] = page_size * page_count
        values["MemAvailable"] = page_size * available_pages
        source = "sysconf"
    total = int(values["MemTotal"])
    available = int(values["MemAvailable"])
    if total <= 0 or available < 0 or available > total:
        raise ValueError("RAM snapshot contains invalid totals")
    return {
        "total_bytes": total,
        "available_bytes": available,
        "source": source,
    }


def _resolve_temp_parent(temp_parent: Path | str | None) -> Path:
    system_temp = Path(tempfile.gettempdir()).resolve()
    candidate = (system_temp if temp_parent is None else Path(temp_parent)).expanduser().resolve()
    try:
        candidate.relative_to(system_temp)
    except ValueError as error:
        raise ValueError("temporary parent must be below the system temporary directory") from error
    try:
        LAB_ROOT.relative_to(candidate)
    except ValueError:
        pass
    else:
        raise ValueError("temporary parent cannot contain the project workspace")
    try:
        candidate.relative_to(LAB_ROOT)
    except ValueError:
        pass
    else:
        raise ValueError("temporary parent cannot be inside the project workspace")
    if not candidate.is_dir():
        raise FileNotFoundError(f"temporary parent is not a directory: {candidate}")
    return candidate


def _validate_request(
    probe_bytes: int,
    concurrency: int,
    owned_io_bytes_per_worker: int,
    minimum_free_disk_bytes: int,
) -> None:
    if not _is_positive_int(probe_bytes) or probe_bytes > MAX_WORKSPACE_BYTES:
        raise ValueError(f"probe_bytes must be in [1,{MAX_WORKSPACE_BYTES}]")
    if not _is_positive_int(concurrency) or concurrency > MAX_CONCURRENCY:
        raise ValueError(f"concurrency must be in [1,{MAX_CONCURRENCY}]")
    if not _is_nonnegative_int(owned_io_bytes_per_worker):
        raise ValueError("owned_io_bytes_per_worker must be a non-negative integer")
    if not _is_nonnegative_int(minimum_free_disk_bytes):
        raise ValueError("minimum_free_disk_bytes must be a non-negative integer")
    projected_owned = concurrency * owned_io_bytes_per_worker
    projected_total = projected_owned + (2 * probe_bytes)
    if projected_total > MAX_PROJECTED_IO_BYTES:
        raise ValueError(f"projected I/O exceeds {MAX_PROJECTED_IO_BYTES} bytes")


def _execution_controls() -> dict[str, Any]:
    return {
        "probe_only": True,
        "temporary_workspace_only": True,
        "production_hdf5_opened": False,
        "material_worker_started": False,
        "solver_started": False,
        "gpu_initialized": False,
        "queue_or_scheduler_started": False,
        "core_runtime_admission_mutated": False,
        "registry_mutations": 0,
        "completion_mutations": 0,
        "ledger_mutations": 0,
        "denominator_mutations": 0,
        "gate_mutations": 0,
    }


def _authorization_boundary() -> dict[str, Any]:
    return {
        "probe_is_authorization": False,
        "root_authorization_required": True,
        "scheduler_authorization_required": True,
        "worker_launch_authorized": False,
        "formal_admission": False,
        "formal_eligible": False,
        "qualification_credit": 0,
        "interpretation": "diagnostic resource observation only; no launch or formal credit",
    }


def _projection(
    concurrency: int,
    owned_io_bytes_per_worker: int,
    probe_bytes: int,
) -> dict[str, Any]:
    owned = concurrency * owned_io_bytes_per_worker
    probe_write = probe_bytes
    probe_read = probe_bytes
    return {
        "concurrency": concurrency,
        "concurrency_source": "caller_declared_projection",
        "owned_io_bytes_per_worker": owned_io_bytes_per_worker,
        "projected_owned_io_bytes": owned,
        "probe_write_bytes": probe_write,
        "probe_read_bytes": probe_read,
        "projected_total_io_bytes": owned + probe_write + probe_read,
        "projection_unit": "declared_io_volume_bytes",
        "observed": False,
        "scheduler_owned_io_verified": False,
    }


def _request(
    probe_bytes: int | None,
    concurrency: int | None,
    owned_io_bytes_per_worker: int | None,
    minimum_free_disk_bytes: int | None,
    temp_parent: Path | None,
) -> dict[str, Any]:
    return {
        "family_scope": ["F3", "F4"],
        "probe_bytes": probe_bytes,
        "concurrency": concurrency,
        "owned_io_bytes_per_worker": owned_io_bytes_per_worker,
        "minimum_free_disk_bytes": minimum_free_disk_bytes,
        "temporary_parent": str(temp_parent) if temp_parent is not None else None,
    }


def _empty_workspace(request: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "kind": "bounded_temporary_directory",
        "parent": request.get("temporary_parent"),
        "path": None,
        "file_name": PROBE_FILE_NAME,
        "owned": True,
        "max_files": 1,
        "max_bytes": MAX_WORKSPACE_BYTES,
        "requested_payload_bytes": request.get("probe_bytes"),
        "used_bytes": None,
        "cleaned": False,
        "exists_after_cleanup": None,
    }


def _empty_io(request: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "bytes_requested": request.get("probe_bytes"),
        "bytes_written": None,
        "bytes_read": None,
        "fsync_count": None,
        "write_elapsed_seconds": None,
        "fsync_elapsed_seconds": None,
        "read_elapsed_seconds": None,
        "elapsed_seconds": None,
        "write_sha256": None,
        "read_sha256": None,
        "readback_sha256_match": False,
        "file_size_after_write": None,
        "file_size_after_read": None,
        "file_removed": False,
        "workspace_file_count_after_write": None,
        "workspace_bytes_after_write": None,
        "workspace_file_count_after_remove": None,
        "workspace_bytes_after_remove": None,
    }


def _empty_sections(request: Mapping[str, Any]) -> dict[str, Any]:
    projection_values = {
        "concurrency": request.get("concurrency"),
        "concurrency_source": "caller_declared_projection",
        "owned_io_bytes_per_worker": request.get("owned_io_bytes_per_worker"),
        "projected_owned_io_bytes": None,
        "probe_write_bytes": request.get("probe_bytes"),
        "probe_read_bytes": request.get("probe_bytes"),
        "projected_total_io_bytes": None,
        "projection_unit": "declared_io_volume_bytes",
        "observed": False,
        "scheduler_owned_io_verified": False,
    }
    return {
        "workspace": _empty_workspace(request),
        "filesystem": {"before": None, "after": None, "stable": False},
        "disk": {
            "before": None,
            "after": None,
            "required_free_bytes": None,
            "minimum_free_bytes": request.get("minimum_free_disk_bytes"),
            "free_disk_pass": False,
            "projection_headroom_after_bytes": None,
        },
        "cpu": {"before": None, "after": None, "concurrency_within_affinity": False},
        "ram": {"before": None, "after": None},
        "owned_io_projection": projection_values,
        "io_measurement": _empty_io(request),
    }


def _base_report(request: Mapping[str, Any]) -> dict[str, Any]:
    sections = _empty_sections(request)
    return {
        "schema": SCHEMA,
        "probe": {
            "name": PROBE_NAME,
            "probe_pass": False,
            "contract_valid": False,
            "measurement_complete": False,
            "checks": {},
        },
        "status": "failed_closed",
        "observed_at_utc": _utc_now(),
        "request": dict(request),
        **sections,
        "authorization_boundary": _authorization_boundary(),
        "execution_controls": _execution_controls(),
        "failure": {
            "fail_closed": True,
            "kind": "uninitialized",
            "stage": "initialization",
            "errors": ["probe did not complete"],
        },
    }


def _node_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_mode),
        int(value.st_nlink),
        int(value.st_size),
        int(value.st_mtime_ns),
        int(value.st_ctime_ns),
    )


def _regular_node(value: os.stat_result, label: str) -> os.stat_result:
    if not stat.S_ISREG(value.st_mode):
        raise ValueError(f"{label} is not a regular file")
    if value.st_nlink != 1:
        raise ValueError(f"{label} must have exactly one hard link")
    return value


def _workspace_usage(workspace: Path, *, directory_fd: int | None = None) -> tuple[int, int]:
    if directory_fd is None:
        entries = list(os.scandir(workspace))
        snapshots = [
            entry.stat(follow_symlinks=False)
            for entry in entries
        ]
    else:
        names = os.listdir(directory_fd)
        snapshots = [
            os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            for name in names
        ]
    total_bytes = 0
    for info in snapshots:
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("temporary workspace contains a non-regular entry")
        total_bytes += int(info.st_size)
    return len(snapshots), total_bytes


def _measure_io(workspace: Path, requested_bytes: int) -> dict[str, Any]:
    probe_path = workspace / PROBE_FILE_NAME
    if probe_path.parent != workspace:
        raise ValueError("probe path escaped temporary workspace")
    started_ns = time.perf_counter_ns()
    digest_written = hashlib.sha256()
    written = 0
    fsync_elapsed = 0.0
    fsync_count = 0
    fd = -1
    directory_fd = -1
    open_directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    directory_fd = os.open(workspace, open_directory_flags)
    try:
        directory_info = os.fstat(directory_fd)
        if not stat.S_ISDIR(directory_info.st_mode):
            raise ValueError("temporary workspace is not a directory")

        fd = os.open(
            PROBE_FILE_NAME,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=directory_fd,
        )
        try:
            write_started_ns = time.perf_counter_ns()
            while written < requested_bytes:
                size = min(IO_CHUNK_BYTES, requested_bytes - written)
                chunk = _pattern_chunk(written, size)
                offset = 0
                while offset < len(chunk):
                    count = os.write(fd, chunk[offset:])
                    if count <= 0:
                        raise OSError("short write returned zero bytes")
                    digest_written.update(chunk[offset : offset + count])
                    offset += count
                    written += count
            write_elapsed = (time.perf_counter_ns() - write_started_ns) / 1_000_000_000.0
            fsync_started_ns = time.perf_counter_ns()
            os.fsync(fd)
            fsync_elapsed = (time.perf_counter_ns() - fsync_started_ns) / 1_000_000_000.0
            fsync_count = 1
            write_info = _regular_node(os.fstat(fd), "probe write descriptor")
        finally:
            os.close(fd)
            fd = -1

        named_after_write = _regular_node(
            os.stat(PROBE_FILE_NAME, dir_fd=directory_fd, follow_symlinks=False),
            "probe file",
        )
        if _node_identity(named_after_write) != _node_identity(write_info):
            raise RuntimeError("probe file path identity changed after write")
        file_size_after_write = write_info.st_size
        workspace_file_count_after_write, workspace_bytes_after_write = _workspace_usage(
            workspace, directory_fd=directory_fd
        )
        if workspace_file_count_after_write != 1 or workspace_bytes_after_write > MAX_WORKSPACE_BYTES:
            raise ValueError("bounded temporary workspace usage exceeded its contract")

        read_started_ns = time.perf_counter_ns()
        digest_read = hashlib.sha256()
        read = 0
        fd = os.open(
            PROBE_FILE_NAME,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
            dir_fd=directory_fd,
        )
        try:
            read_before = _regular_node(os.fstat(fd), "probe read descriptor")
            if _node_identity(read_before) != _node_identity(write_info):
                raise RuntimeError("probe file identity changed before read")
            while True:
                chunk = os.read(fd, IO_CHUNK_BYTES)
                if not chunk:
                    break
                digest_read.update(chunk)
                read += len(chunk)
            read_after = _regular_node(os.fstat(fd), "probe read descriptor")
        finally:
            os.close(fd)
            fd = -1
        read_elapsed = (time.perf_counter_ns() - read_started_ns) / 1_000_000_000.0
        if _node_identity(read_after) != _node_identity(read_before):
            raise RuntimeError("probe file changed while being read")
        named_after_read = _regular_node(
            os.stat(PROBE_FILE_NAME, dir_fd=directory_fd, follow_symlinks=False),
            "probe file",
        )
        if _node_identity(named_after_read) != _node_identity(read_after):
            raise RuntimeError("probe file path identity changed while being read")
        file_size_after_read = read_after.st_size
        written_digest = digest_written.hexdigest()
        read_digest = digest_read.hexdigest()
        readback_match = written_digest == read_digest and read == requested_bytes
        os.unlink(PROBE_FILE_NAME, dir_fd=directory_fd)
        try:
            os.stat(PROBE_FILE_NAME, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            file_removed = True
        else:
            file_removed = False
        workspace_file_count_after_remove, workspace_bytes_after_remove = _workspace_usage(
            workspace, directory_fd=directory_fd
        )
        if workspace_file_count_after_remove != 0 or workspace_bytes_after_remove != 0:
            raise ValueError("temporary workspace was not empty after probe cleanup")
        elapsed = (time.perf_counter_ns() - started_ns) / 1_000_000_000.0
        values = {
            "bytes_requested": requested_bytes,
            "bytes_written": written,
            "bytes_read": read,
            "fsync_count": fsync_count,
            "write_elapsed_seconds": write_elapsed,
            "fsync_elapsed_seconds": fsync_elapsed,
            "read_elapsed_seconds": read_elapsed,
            "elapsed_seconds": elapsed,
            "write_sha256": written_digest,
            "read_sha256": read_digest,
            "readback_sha256_match": readback_match,
            "file_size_after_write": int(file_size_after_write),
            "file_size_after_read": int(file_size_after_read),
            "file_removed": file_removed,
            "workspace_file_count_after_write": workspace_file_count_after_write,
            "workspace_bytes_after_write": workspace_bytes_after_write,
            "workspace_file_count_after_remove": workspace_file_count_after_remove,
            "workspace_bytes_after_remove": workspace_bytes_after_remove,
        }
        if not all(_is_finite_nonnegative(values[name]) for name in ("write_elapsed_seconds", "fsync_elapsed_seconds", "read_elapsed_seconds", "elapsed_seconds")):
            raise ValueError("I/O elapsed measurement is invalid")
        return values
    finally:
        if fd >= 0:
            os.close(fd)
        if directory_fd >= 0:
            os.close(directory_fd)


def _build_completed_report(
    request: Mapping[str, Any],
    state: Mapping[str, Any],
    *,
    workspace_cleaned: bool,
    workspace_exists_after_cleanup: bool,
) -> dict[str, Any]:
    report = _base_report(request)
    report["status"] = "diagnostic_pass"
    report["probe"]["contract_valid"] = True
    report["probe"]["measurement_complete"] = True
    report["workspace"] = {
        "kind": "bounded_temporary_directory",
        "parent": str(state["temp_parent"]),
        "path": str(state["workspace_path"]),
        "file_name": PROBE_FILE_NAME,
        "owned": True,
        "max_files": 1,
        "max_bytes": MAX_WORKSPACE_BYTES,
        "requested_payload_bytes": request["probe_bytes"],
        "used_bytes": state["io_measurement"]["workspace_bytes_after_write"],
        "file_count_before_cleanup": state["io_measurement"]["workspace_file_count_after_write"],
        "file_count_after_probe": state["io_measurement"]["workspace_file_count_after_remove"],
        "cleaned": bool(workspace_cleaned),
        "exists_after_cleanup": bool(workspace_exists_after_cleanup),
    }
    report["filesystem"] = {
        "before": state["filesystem_before"],
        "after": state["filesystem_after"],
        "stable": state["filesystem_before"] == state["filesystem_after"],
    }
    projection = _projection(
        request["concurrency"],
        request["owned_io_bytes_per_worker"],
        request["probe_bytes"],
    )
    report["owned_io_projection"] = projection
    required_free = request["minimum_free_disk_bytes"] + projection["projected_total_io_bytes"]
    before_disk = state["disk_before"]
    after_disk = state["disk_after"]
    free_disk_pass = before_disk["free_bytes"] >= required_free and after_disk["free_bytes"] >= required_free
    report["disk"] = {
        "before": before_disk,
        "after": after_disk,
        "required_free_bytes": required_free,
        "minimum_free_bytes": request["minimum_free_disk_bytes"],
        "free_disk_pass": free_disk_pass,
        "projection_headroom_after_bytes": after_disk["free_bytes"] - required_free,
    }
    report["cpu"] = {
        "before": state["cpu_before"],
        "after": state["cpu_after"],
        "concurrency_within_affinity": request["concurrency"] <= state["cpu_after"]["affinity_cpu_count"],
    }
    report["ram"] = {"before": state["ram_before"], "after": state["ram_after"]}
    report["io_measurement"] = state["io_measurement"]

    checks = {
        "workspace_bounded": report["workspace"]["max_files"] == 1 and report["workspace"]["used_bytes"] <= MAX_WORKSPACE_BYTES,
        "workspace_cleaned": workspace_cleaned and not workspace_exists_after_cleanup,
        "workspace_usage_exact": report["io_measurement"]["workspace_file_count_after_write"] == 1 and report["io_measurement"]["workspace_bytes_after_write"] == request["probe_bytes"] and report["io_measurement"]["workspace_file_count_after_remove"] == 0 and report["io_measurement"]["workspace_bytes_after_remove"] == 0,
        "filesystem_identity_present": all(
            all(
                field in report["filesystem"][side]
                and report["filesystem"][side][field] is not None
                for field in _REQUIRED_FS_FIELDS
            )
            for side in ("before", "after")
        ),
        "filesystem_identity_stable": report["filesystem"]["stable"],
        "free_disk_headroom": free_disk_pass,
        "concurrency_within_affinity": report["cpu"]["concurrency_within_affinity"],
        "bytes_exact": report["io_measurement"]["bytes_written"] == request["probe_bytes"] and report["io_measurement"]["bytes_read"] == request["probe_bytes"],
        "fsync_completed": report["io_measurement"]["fsync_count"] == 1,
        "readback_hash_match": report["io_measurement"]["readback_sha256_match"],
        "elapsed_fields_finite": all(
            _is_finite_nonnegative(report["io_measurement"][field])
            for field in ("write_elapsed_seconds", "fsync_elapsed_seconds", "read_elapsed_seconds", "elapsed_seconds")
        ),
    }
    reasons = [name for name, passed in checks.items() if not passed]
    report["probe"]["checks"] = checks
    report["probe"]["probe_pass"] = not reasons
    if reasons:
        report["status"] = "diagnostic_fail_closed"
        report["failure"] = {
            "fail_closed": True,
            "kind": "diagnostic_check_failed",
            "stage": "post_measurement_validation",
            "errors": reasons,
        }
    else:
        report["failure"] = None
    return report


def _failure_report(
    request: Mapping[str, Any],
    stage: str,
    error: BaseException,
    state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    report = _base_report(request)
    if state:
        # Preserve only non-sensitive, already collected observations.  The
        # report remains non-passing if any operation failed.
        for name in ("temp_parent", "workspace_path"):
            if name in state:
                report["workspace"]["parent" if name == "temp_parent" else "path"] = str(state[name])
        if "workspace_cleaned" in state:
            report["workspace"]["cleaned"] = bool(state["workspace_cleaned"])
        if "workspace_exists_after_cleanup" in state:
            report["workspace"]["exists_after_cleanup"] = bool(state["workspace_exists_after_cleanup"])
    report["failure"] = {
        "fail_closed": True,
        "kind": "exception_or_invalid_input",
        "stage": stage,
        "error_type": type(error).__name__,
        "errors": [str(error) or type(error).__name__],
    }
    report["status"] = "failed_closed"
    report["probe"]["checks"] = {"exception_free": False}
    report["probe"]["probe_pass"] = False
    report["probe"]["contract_valid"] = False
    report["probe"]["measurement_complete"] = False
    return report


def run_probe(
    *,
    temp_parent: Path | str | None = None,
    probe_bytes: int = DEFAULT_PROBE_BYTES,
    concurrency: int,
    owned_io_bytes_per_worker: int,
    minimum_free_disk_bytes: int = DEFAULT_MINIMUM_FREE_DISK_BYTES,
) -> dict[str, Any]:
    """Run the probe and always return a fail-closed report."""

    request = _request(
        probe_bytes,
        concurrency,
        owned_io_bytes_per_worker,
        minimum_free_disk_bytes,
        None,
    )
    state: dict[str, Any] = {}
    stage = "input_validation"
    try:
        _validate_request(probe_bytes, concurrency, owned_io_bytes_per_worker, minimum_free_disk_bytes)
        stage = "temporary_parent_validation"
        parent = _resolve_temp_parent(temp_parent)
        request["temporary_parent"] = str(parent)
        state["temp_parent"] = parent
        stage = "temporary_workspace_creation"
        with tempfile.TemporaryDirectory(prefix=WORKSPACE_PREFIX, dir=str(parent)) as workspace_name:
            workspace = Path(workspace_name).resolve()
            state["workspace_path"] = workspace
            stage = "resource_snapshot_before"
            state["filesystem_before"] = _filesystem_identity(workspace)
            state["disk_before"] = _disk_snapshot(workspace)
            state["cpu_before"] = _cpu_snapshot()
            state["ram_before"] = _ram_snapshot()
            stage = "bounded_io_measurement"
            state["io_measurement"] = _measure_io(workspace, probe_bytes)
            stage = "resource_snapshot_after"
            state["filesystem_after"] = _filesystem_identity(workspace)
            state["disk_after"] = _disk_snapshot(workspace)
            state["cpu_after"] = _cpu_snapshot()
            state["ram_after"] = _ram_snapshot()
            state["workspace_cleaned"] = False
            state["workspace_exists_after_cleanup"] = True
        state["workspace_cleaned"] = True
        state["workspace_exists_after_cleanup"] = bool(state["workspace_path"].exists())
        stage = "report_assembly"
        return _build_completed_report(
            request,
            state,
            workspace_cleaned=state["workspace_cleaned"],
            workspace_exists_after_cleanup=state["workspace_exists_after_cleanup"],
        )
    except BaseException as error:  # fail closed for every exception, including unexpected ones
        if "workspace_path" in state:
            state["workspace_cleaned"] = not state["workspace_path"].exists()
            state["workspace_exists_after_cleanup"] = state["workspace_path"].exists()
        return _failure_report(request, stage, error, state)


def _get_path(value: Mapping[str, Any], path: Sequence[str]) -> Any:
    current: Any = value
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            raise KeyError(".".join(path))
        current = current[key]
    return current


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _is_absolute_direct_child(parent: Any, child: Any) -> bool:
    if not isinstance(parent, str) or not isinstance(child, str):
        return False
    parent_path = Path(parent)
    child_path = Path(child)
    return (
        parent_path.is_absolute()
        and child_path.is_absolute()
        and child_path.parent == parent_path
    )


def validate_report(report: Mapping[str, Any]) -> list[str]:
    """Return structural/contract errors; never infer a pass from omissions."""

    errors: list[str] = []
    if not isinstance(report, Mapping):
        return ["report must be an object"]
    for name in REQUIRED_TOP_LEVEL_FIELDS:
        if name not in report:
            errors.append(f"missing top-level field: {name}")
    for path in REQUIRED_PATHS:
        try:
            _get_path(report, path)
        except KeyError:
            errors.append(f"missing field: {'.'.join(path)}")
    if report.get("schema") != SCHEMA:
        errors.append("schema mismatch")
    status = report.get("status")
    if status not in {"diagnostic_pass", "diagnostic_fail_closed", "failed_closed"}:
        errors.append("invalid status")
    boundary = report.get("authorization_boundary")
    if isinstance(boundary, Mapping):
        if boundary.get("probe_is_authorization") is not False:
            errors.append("probe cannot be authorization")
        if boundary.get("worker_launch_authorized") is not False:
            errors.append("probe cannot authorize worker launch")
        if boundary.get("formal_admission") is not False:
            errors.append("probe cannot grant formal admission")
        if boundary.get("qualification_credit") != 0:
            errors.append("probe cannot grant qualification credit")
    controls = report.get("execution_controls")
    if isinstance(controls, Mapping):
        for key in (
            "production_hdf5_opened",
            "material_worker_started",
            "solver_started",
            "gpu_initialized",
            "queue_or_scheduler_started",
            "core_runtime_admission_mutated",
        ):
            if controls.get(key) is not False:
                errors.append(f"execution control must remain false: {key}")
        for key in ("registry_mutations", "completion_mutations", "ledger_mutations", "denominator_mutations", "gate_mutations"):
            if controls.get(key) != 0:
                errors.append(f"execution control must remain zero: {key}")

    if status in {"diagnostic_pass", "diagnostic_fail_closed"}:
        probe = report.get("probe")
        if not isinstance(probe, Mapping):
            errors.append("diagnostic result requires a probe object")
        else:
            checks = probe.get("checks")
            if not isinstance(checks, Mapping) or set(checks) != _SUCCESS_CHECK_NAMES:
                errors.append("diagnostic result has an incomplete checks map")
            else:
                if any(type(value) is not bool for value in checks.values()):
                    errors.append("diagnostic checks must be boolean")
                expected_probe_pass = all(checks.values())
                if probe.get("probe_pass") is not expected_probe_pass:
                    errors.append("probe_pass is inconsistent with diagnostic checks")
            if probe.get("contract_valid") is not True:
                errors.append("diagnostic result requires a valid probe contract")
            if probe.get("measurement_complete") is not True:
                errors.append("diagnostic result requires complete measurements")
            if status == "diagnostic_pass" and probe.get("probe_pass") is not True:
                errors.append("diagnostic_pass requires a complete passing probe")
            if status == "diagnostic_fail_closed" and probe.get("probe_pass") is not False:
                errors.append("diagnostic_fail_closed requires a failed resource check")
        if status == "diagnostic_pass" and report.get("failure") is not None:
            errors.append("diagnostic_pass cannot carry a failure")
        try:
            _validate_success_measurements(report, errors)
        except Exception as error:  # a malformed report is never a validator pass
            errors.append(f"validator failed closed: {type(error).__name__}: {error}")
    else:
        failure = report.get("failure")
        if not isinstance(failure, Mapping) or failure.get("fail_closed") is not True or not failure.get("errors"):
            errors.append("non-passing report must carry fail-closed errors")
        probe = report.get("probe")
        if isinstance(probe, Mapping) and probe.get("probe_pass") is True:
            errors.append("non-passing report cannot have probe_pass=true")
    return errors


def _validate_success_measurements(report: Mapping[str, Any], errors: list[str]) -> None:
    request = report.get("request")
    if not isinstance(request, Mapping):
        errors.append("request must be an object")
        return
    if request.get("family_scope") != ["F3", "F4"]:
        errors.append("request family_scope must cover F3 and F4")
    requested_probe_bytes = request.get("probe_bytes")
    probe_bytes_valid = _is_positive_int(requested_probe_bytes) and requested_probe_bytes <= MAX_WORKSPACE_BYTES
    if not probe_bytes_valid:
        errors.append("request probe_bytes is invalid")
    concurrency = request.get("concurrency")
    concurrency_valid = _is_positive_int(concurrency) and concurrency <= MAX_CONCURRENCY
    if not concurrency_valid:
        errors.append("request concurrency is invalid")
    owned_io_bytes = request.get("owned_io_bytes_per_worker")
    owned_io_valid = _is_nonnegative_int(owned_io_bytes)
    if not owned_io_valid:
        errors.append("request owned_io_bytes_per_worker is invalid")
    minimum_free_disk_bytes = request.get("minimum_free_disk_bytes")
    minimum_free_valid = _is_nonnegative_int(minimum_free_disk_bytes)
    if not minimum_free_valid:
        errors.append("request minimum_free_disk_bytes is invalid")
    temporary_parent = request.get("temporary_parent")
    if not isinstance(temporary_parent, str) or not Path(temporary_parent).is_absolute():
        errors.append("request temporary_parent must be absolute")

    workspace = report.get("workspace")
    if not isinstance(workspace, Mapping):
        errors.append("workspace is not an object")
    else:
        if workspace.get("kind") != "bounded_temporary_directory":
            errors.append("temporary workspace kind is invalid")
        if workspace.get("owned") is not True:
            errors.append("temporary workspace must be owned")
        if workspace.get("file_name") != PROBE_FILE_NAME:
            errors.append("temporary workspace file name is invalid")
        if workspace.get("max_files") != 1 or workspace.get("max_bytes") != MAX_WORKSPACE_BYTES:
            errors.append("temporary workspace bounds are invalid")
        if workspace.get("parent") != temporary_parent:
            errors.append("temporary workspace parent is not bound to the request")
        if not _is_absolute_direct_child(temporary_parent, workspace.get("path")):
            errors.append("temporary workspace path is not a direct child of its parent")
        elif not Path(workspace["path"]).name.startswith(WORKSPACE_PREFIX):
            errors.append("temporary workspace path is not a fresh probe namespace")
        if workspace.get("requested_payload_bytes") != requested_probe_bytes:
            errors.append("workspace requested bytes do not match request")
        if workspace.get("used_bytes") != requested_probe_bytes:
            errors.append("workspace used bytes do not match request")
        if workspace.get("file_count_before_cleanup") != 1:
            errors.append("workspace pre-cleanup file count is invalid")
        if workspace.get("file_count_after_probe") != 0:
            errors.append("workspace post-probe file count is invalid")
        if workspace.get("cleaned") is not True or workspace.get("exists_after_cleanup") is not False:
            errors.append("temporary workspace was not proven cleaned")

    io_measurement = report.get("io_measurement")
    if not isinstance(io_measurement, Mapping):
        errors.append("I/O measurement is not an object")
    else:
        for key in ("bytes_requested", "bytes_written", "bytes_read", "file_size_after_write", "file_size_after_read"):
            if not probe_bytes_valid or io_measurement.get(key) != requested_probe_bytes:
                errors.append(f"I/O field does not match requested bytes: {key}")
        if io_measurement.get("workspace_file_count_after_write") != 1:
            errors.append("temporary workspace write file count is invalid")
        if io_measurement.get("workspace_bytes_after_write") != requested_probe_bytes:
            errors.append("temporary workspace write bytes are invalid")
        if io_measurement.get("workspace_file_count_after_remove") != 0 or io_measurement.get("workspace_bytes_after_remove") != 0:
            errors.append("temporary workspace was not empty after the probe")
        if io_measurement.get("fsync_count") != 1:
            errors.append("exactly one fsync is required")
        if io_measurement.get("file_removed") is not True:
            errors.append("probe file removal was not proven")
        if io_measurement.get("readback_sha256_match") is not True:
            errors.append("readback digest did not match")
        if not _is_sha256(io_measurement.get("write_sha256")) or not _is_sha256(io_measurement.get("read_sha256")):
            errors.append("I/O digests are not valid SHA-256 values")
        elif io_measurement.get("write_sha256") != io_measurement.get("read_sha256"):
            errors.append("write/read digests differ")
        for key in ("write_elapsed_seconds", "fsync_elapsed_seconds", "read_elapsed_seconds", "elapsed_seconds"):
            if not _is_finite_nonnegative(io_measurement.get(key)):
                errors.append(f"invalid elapsed field: {key}")
    for section_name, fields in (
        ("filesystem", _REQUIRED_FS_FIELDS),
        ("disk", _REQUIRED_DISK_FIELDS),
        ("cpu", _REQUIRED_CPU_FIELDS),
        ("ram", _REQUIRED_RAM_FIELDS),
    ):
        section = report.get(section_name)
        if section_name in {"filesystem", "disk"}:
            snapshots = (section.get("before"), section.get("after")) if isinstance(section, Mapping) else ()
        else:
            snapshots = (section.get("before"), section.get("after")) if isinstance(section, Mapping) else ()
        if len(snapshots) != 2 or any(not isinstance(snapshot, Mapping) for snapshot in snapshots):
            errors.append(f"{section_name} snapshots are incomplete")
            continue
        for snapshot in snapshots:
            for field in fields:
                if field not in snapshot or snapshot[field] is None:
                    errors.append(f"missing {section_name} snapshot field: {field}")

    filesystem = report.get("filesystem")
    if isinstance(filesystem, Mapping):
        before = filesystem.get("before")
        after = filesystem.get("after")
        if filesystem.get("stable") is not True:
            errors.append("filesystem identity is not marked stable")
        if isinstance(before, Mapping) and isinstance(after, Mapping):
            if before != after:
                errors.append("filesystem identity changed between snapshots")
            if isinstance(workspace, Mapping) and before.get("path") != workspace.get("path"):
                errors.append("filesystem path is not bound to the probe workspace")

    disk = report.get("disk")
    if isinstance(disk, Mapping):
        before = disk.get("before")
        after = disk.get("after")
        required_free = disk.get("required_free_bytes")
        if not minimum_free_valid or not isinstance(required_free, int) or isinstance(required_free, bool):
            errors.append("disk required free bytes are invalid")
        elif not (probe_bytes_valid and concurrency_valid and owned_io_valid):
            errors.append("disk requirement cannot be recomputed from the request")
        else:
            projected_total = concurrency * owned_io_bytes + 2 * requested_probe_bytes
            expected_required_free = minimum_free_disk_bytes + projected_total
            if required_free != expected_required_free:
                errors.append("disk required free bytes are not bound to the request")
            if disk.get("minimum_free_bytes") != minimum_free_disk_bytes:
                errors.append("disk minimum free bytes are not bound to the request")
            if isinstance(after, Mapping) and disk.get("projection_headroom_after_bytes") != after.get("free_bytes", 0) - required_free:
                errors.append("disk projection headroom is inconsistent")
            if isinstance(before, Mapping) and isinstance(after, Mapping):
                expected_free_pass = before.get("free_bytes", -1) >= required_free and after.get("free_bytes", -1) >= required_free
                if disk.get("free_disk_pass") is not expected_free_pass:
                    errors.append("disk free pass is inconsistent with snapshots")

    cpu = report.get("cpu")
    if isinstance(cpu, Mapping) and isinstance(concurrency, int) and not isinstance(concurrency, bool):
        after = cpu.get("after")
        if isinstance(after, Mapping):
            affinity = after.get("affinity_cpu_count")
            expected_cpu_pass = _is_positive_int(affinity) and concurrency <= affinity
            if cpu.get("concurrency_within_affinity") is not expected_cpu_pass:
                errors.append("CPU concurrency check is inconsistent with the request")

    ram = report.get("ram")
    if isinstance(ram, Mapping):
        for side in ("before", "after"):
            snapshot = ram.get(side)
            if isinstance(snapshot, Mapping):
                total = snapshot.get("total_bytes")
                available = snapshot.get("available_bytes")
                if not _is_positive_int(total) or not _is_nonnegative_int(available) or available > total:
                    errors.append(f"RAM {side} snapshot is invalid")

    projection = report.get("owned_io_projection")
    if isinstance(projection, Mapping):
        projection_fields = tuple(
            projection.get(name)
            for name in ("projected_owned_io_bytes", "probe_write_bytes", "probe_read_bytes")
        )
        if not all(_is_nonnegative_int(value) for value in projection_fields):
            errors.append("owned I/O projection contains invalid byte fields")
        elif projection.get("projected_total_io_bytes") != sum(projection_fields):
            errors.append("owned I/O projection total is inconsistent")
        if probe_bytes_valid and projection.get("probe_write_bytes") != requested_probe_bytes:
            errors.append("owned I/O write projection is not bound to the request")
        if probe_bytes_valid and projection.get("probe_read_bytes") != requested_probe_bytes:
            errors.append("owned I/O read projection is not bound to the request")
        if concurrency_valid and owned_io_valid:
            if projection.get("concurrency") != concurrency:
                errors.append("owned I/O concurrency is not bound to the request")
            if projection.get("owned_io_bytes_per_worker") != owned_io_bytes:
                errors.append("owned I/O worker bytes are not bound to the request")
            if projection.get("projected_owned_io_bytes") != concurrency * owned_io_bytes:
                errors.append("owned I/O worker projection is inconsistent")
        if (
            _is_nonnegative_int(projection.get("projected_total_io_bytes"))
            and projection["projected_total_io_bytes"] > MAX_PROJECTED_IO_BYTES
        ):
            errors.append("owned I/O projection exceeds the bounded maximum")
        if projection.get("concurrency_source") != "caller_declared_projection":
            errors.append("owned I/O concurrency source is invalid")
        if projection.get("projection_unit") != "declared_io_volume_bytes":
            errors.append("owned I/O projection unit is invalid")
        if projection.get("observed") is not False:
            errors.append("owned I/O projection must remain declared, not observed")
        if projection.get("scheduler_owned_io_verified") is not False:
            errors.append("diagnostic probe cannot claim scheduler-owned I/O")
    else:
        errors.append("owned I/O projection is not an object")


def write_report(report: Mapping[str, Any], destination: Path | str) -> Path:
    """Write a validated report without overwriting an existing artifact."""

    errors = validate_report(report)
    if errors:
        raise ValueError("cannot write invalid host-I/O probe report: " + "; ".join(errors))
    destination_path = Path(destination).absolute()
    if not destination_path.parent.is_dir():
        raise FileNotFoundError(destination_path.parent)
    current = Path(destination_path.anchor)
    for component in destination_path.parts[1:-1]:
        current /= component
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("report destination contains a symlinked parent")

    descriptor = os.open(
        destination_path,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
        0o644,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = -1
            json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    parent_fd = os.open(
        destination_path.parent,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)
    return destination_path


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True, help="new diagnostic JSON path; never overwritten")
    parser.add_argument("--temp-parent", type=Path, default=None, help="optional directory below the OS temp directory")
    parser.add_argument("--probe-bytes", type=int, default=DEFAULT_PROBE_BYTES)
    parser.add_argument("--concurrency", type=int, required=True)
    parser.add_argument("--owned-io-bytes-per-worker", type=int, required=True)
    parser.add_argument("--minimum-free-disk-bytes", type=int, default=DEFAULT_MINIMUM_FREE_DISK_BYTES)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report = run_probe(
        temp_parent=args.temp_parent,
        probe_bytes=args.probe_bytes,
        concurrency=args.concurrency,
        owned_io_bytes_per_worker=args.owned_io_bytes_per_worker,
        minimum_free_disk_bytes=args.minimum_free_disk_bytes,
    )
    write_report(report, args.report)
    print(json.dumps({"status": report["status"], "report": str(args.report)}, sort_keys=True))
    return 0 if report["status"] == "diagnostic_pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
