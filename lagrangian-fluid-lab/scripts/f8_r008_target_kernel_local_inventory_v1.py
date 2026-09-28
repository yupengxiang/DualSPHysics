#!/usr/bin/env python3
"""Read-only, bounded inventory of the local F8/R008 target-kernel profile.

This module deliberately inventories only the running ``uname`` identity, the
exact matching ``/boot/config-<release>`` file, the metadata of
``/lib/modules/<release>/build``, and bounded files below the resolved
``/usr/src`` header root.  It does not recursively walk or hash a kernel
tree.  It never reads a kernel image, production BI4/HDF5, sysfs/procfs
probe, fanotify state, or any native/solver/worker/GPU/queue input.

The resulting receipt is diagnostic-only.  A header package and a handful of
UAPI hashes are useful local evidence, but they are not a source-tree hash,
source commit, or kernel build-id.  Missing or unprovable identity pins are
therefore never promoted to readiness, T1, formal admission, or credit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Mapping


LAB_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = Path(
    "reports/F8-R008-TARGET-KERNEL-LOCAL-INVENTORY-V1-2026-09-28.json"
)
DEFAULT_ZH_REPORT = Path(
    "reports/F8-R008-TARGET-KERNEL-LOCAL-INVENTORY-V1-2026-09-28.zh-CN.md"
)

REPORT_SCHEMA = "core.cfd.f8.r008.target_kernel_local_inventory_report.v1"
REPORT_RECORD_ID = "f8-r008-target-kernel-local-inventory-v1"
R008_SCOPE_ID = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008"
STATUS = "diagnostic_only_local_target_kernel_inventory_incomplete"

MAX_CONFIG_BYTES = 1 * 1024 * 1024
MAX_HEADER_BYTES = 512 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_RELEASE_LENGTH = 128
MAX_SYMLINK_LENGTH = 512

RELEASE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+:-]{0,127}\Z", re.ASCII)
SAFE_HEADER_NAME_RE = re.compile(r"[A-Za-z0-9._+~-]{1,160}\Z", re.ASCII)
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)

CONFIG_OPTIONS = (
    "CONFIG_FANOTIFY",
    "CONFIG_FANOTIFY_ACCESS_PERMISSIONS",
    "CONFIG_SECCOMP",
    "CONFIG_SECCOMP_FILTER",
    "CONFIG_X86_X32_ABI",
)

# These are deliberately a small, fixed evidence set.  Their hashes are a
# bounded sample inventory, never a claim that the complete UAPI/header tree
# has been authenticated.
UAPI_SAMPLE_FILES = (
    "include/uapi/linux/fanotify.h",
    "include/uapi/linux/seccomp.h",
    "include/uapi/linux/unistd.h",
    "arch/x86/include/uapi/asm/unistd.h",
    "arch/x86/include/uapi/asm/ptrace.h",
)
HEADER_METADATA_FILES = (
    "Makefile",
    ".config",
    "include/config/kernel.release",
    "include/generated/utsrelease.h",
    "include/generated/uapi/linux/version.h",
)

AUTHORIZATION = {
    "diagnostic_only": True,
    "readiness_pass": False,
    "T1_numerical": False,
    "formal_admission": False,
    "execution_authority": False,
    "capability_minted": False,
    "qualification_credit": 0,
}

SIDE_EFFECTS = {
    "system_write": 0,
    "mount_operation": 0,
    "privileged_probe": False,
    "production_bi4_hdf5_read": False,
    "native_started": False,
    "solver_started": False,
    "worker_started": False,
    "gpu_started": False,
    "queue_started": False,
    "registry_mutation": 0,
    "ledger_mutation": 0,
    "gate_mutation": 0,
    "plan_mutation": 0,
}

READ_POLICY = {
    "uname_only_for_running_kernel_identity": True,
    "matching_boot_config_only": True,
    "modules_build_link_metadata_only": True,
    "usr_src_bounded_metadata_and_fixed_hash_samples_only": True,
    "bounded_regular_file_reads": True,
    "recursive_unbounded_tree_scan": False,
    "kernel_image_read": False,
    "sysfs_or_procfs_probe": False,
    "privileged_probe": False,
    "mount_or_system_write": False,
    "production_bi4_hdf5_read": False,
    "native_solver_worker_gpu_queue": False,
}


class LocalInventoryError(ValueError):
    """A bounded local inventory operation failed closed."""


def _identity(value: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_nlink,
    )


def _display(path: Path | str) -> str:
    value = Path(os.path.abspath(os.fspath(path)))
    try:
        return value.relative_to(LAB_ROOT).as_posix()
    except ValueError:
        return value.as_posix()


def _within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath(
            (os.path.realpath(os.fspath(path)), os.path.realpath(os.fspath(root)))
        ) == os.path.realpath(os.fspath(root))
    except ValueError:
        return False


def _empty_snapshot(path: Path | str, *, error: str) -> dict[str, Any]:
    return {
        "path": _display(path),
        "resolved_path": None,
        "exists": False,
        "regular": False,
        "readable": False,
        "bytes": None,
        "sha256": None,
        "mode": None,
        "nlink": None,
        "error": error,
    }


def _bounded_read(path: Path, *, label: str, limit: int) -> tuple[bytes, dict[str, Any]]:
    """Read one stable, final-component non-symlink regular file."""

    descriptor: int | None = None
    try:
        named_before = os.lstat(path)
    except FileNotFoundError as error:
        raise LocalInventoryError(f"{label} is missing") from error
    except OSError as error:
        raise LocalInventoryError(f"{label} metadata is unreadable") from error

    if stat.S_ISLNK(named_before.st_mode):
        raise LocalInventoryError(f"{label} final component is a symlink")
    if not stat.S_ISREG(named_before.st_mode):
        raise LocalInventoryError(f"{label} is not a regular file")
    if named_before.st_size > limit:
        raise LocalInventoryError(f"{label} exceeds bounded byte limit")

    nofollow = getattr(os, "O_NOFOLLOW", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(os.fspath(path), os.O_RDONLY | nofollow | cloexec)
    except OSError as error:
        raise LocalInventoryError(f"{label} cannot be opened safely") from error

    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise LocalInventoryError(f"{label} changed to a non-regular file")
        if before.st_size > limit:
            raise LocalInventoryError(f"{label} exceeds bounded byte limit")

        chunks: list[bytes] = []
        total = 0
        while True:
            block = os.read(descriptor, min(256 * 1024, limit + 1 - total))
            if not block:
                break
            total += len(block)
            if total > limit:
                raise LocalInventoryError(f"{label} exceeds bounded byte limit")
            chunks.append(block)

        after = os.fstat(descriptor)
        named_after = os.lstat(path)
        if (
            _identity(before) != _identity(after)
            or _identity(after) != _identity(named_after)
            or total != before.st_size
        ):
            raise LocalInventoryError(f"{label} changed while being read")

        raw = b"".join(chunks)
        return raw, {
            "path": _display(path),
            "resolved_path": _display(path),
            "exists": True,
            "regular": True,
            "readable": True,
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "mode": stat.S_IMODE(after.st_mode),
            "nlink": after.st_nlink,
            "error": None,
        }
    except LocalInventoryError:
        raise
    except OSError as error:
        raise LocalInventoryError(f"{label} could not be read safely") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _capture_file(
    path: Path | None,
    *,
    label: str,
    limit: int,
    resolved_from: Path | None = None,
    allowed_root: Path = Path("/usr/src"),
) -> tuple[dict[str, Any], bytes | None]:
    if path is None:
        return _empty_snapshot("<unavailable>", error=f"{label} has no bounded path"), None
    read_path = path
    if resolved_from is not None:
        read_path = Path(os.path.realpath(os.fspath(path)))
        if not _within(read_path, allowed_root):
            return _empty_snapshot(path, error=f"{label} resolves outside allowed header root"), None
    try:
        raw, snapshot = _bounded_read(read_path, label=label, limit=limit)
    except LocalInventoryError as error:
        snapshot = _empty_snapshot(path, error=str(error))
        if read_path != path:
            snapshot["resolved_path"] = _display(read_path)
        return snapshot, None
    if read_path != path:
        snapshot["path"] = _display(path)
        snapshot["resolved_path"] = _display(read_path)
    return snapshot, raw


def _directory_metadata(path: Path | None, *, label: str) -> dict[str, Any]:
    if path is None:
        return {
            "path": "<unavailable>",
            "resolved_path": None,
            "exists": False,
            "directory": False,
            "mode": None,
            "bytes": None,
            "nlink": None,
            "error": f"{label} has no bounded path",
        }
    try:
        value = os.lstat(path)
    except FileNotFoundError:
        result = {
            "path": _display(path),
            "resolved_path": None,
            "exists": False,
            "directory": False,
            "mode": None,
            "bytes": None,
            "nlink": None,
            "error": f"{label} is missing",
        }
        return result
    except OSError:
        return {
            "path": _display(path),
            "resolved_path": None,
            "exists": False,
            "directory": False,
            "mode": None,
            "bytes": None,
            "nlink": None,
            "error": f"{label} metadata is unreadable",
        }

    if stat.S_ISLNK(value.st_mode):
        return {
            "path": _display(path),
            "resolved_path": _display(Path(os.path.realpath(os.fspath(path)))),
            "exists": True,
            "directory": False,
            "mode": stat.S_IMODE(value.st_mode),
            "bytes": value.st_size,
            "nlink": value.st_nlink,
            "error": f"{label} final component is a symlink",
        }
    return {
        "path": _display(path),
        "resolved_path": _display(path),
        "exists": True,
        "directory": stat.S_ISDIR(value.st_mode),
        "mode": stat.S_IMODE(value.st_mode),
        "bytes": value.st_size,
        "nlink": value.st_nlink,
        "error": None if stat.S_ISDIR(value.st_mode) else f"{label} is not a directory",
    }


def _build_link_metadata(
    path: Path, *, allowed_root: Path = Path("/usr/src")
) -> tuple[dict[str, Any], Path | None]:
    result: dict[str, Any] = {
        "path": _display(path),
        "exists": False,
        "kind": None,
        "mode": None,
        "bytes": None,
        "nlink": None,
        "link_target": None,
        "resolved_target": None,
        "target_within_usr_src": False,
        "target_directory": False,
        "error": None,
    }
    try:
        value = os.lstat(path)
    except FileNotFoundError:
        result["error"] = "build link is missing"
        return result, None
    except OSError:
        result["error"] = "build link metadata is unreadable"
        return result, None

    result.update(
        exists=True,
        mode=stat.S_IMODE(value.st_mode),
        bytes=value.st_size,
        nlink=value.st_nlink,
    )
    if stat.S_ISLNK(value.st_mode):
        result["kind"] = "symlink"
        try:
            target_text = os.readlink(path)
        except OSError:
            result["error"] = "build link target is unreadable"
            return result, None
        if len(target_text) > MAX_SYMLINK_LENGTH:
            result["error"] = "build link target exceeds bounded length"
            return result, None
        result["link_target"] = target_text
        resolved = Path(os.path.realpath(os.fspath(path)))
    elif stat.S_ISDIR(value.st_mode):
        result["kind"] = "directory"
        resolved = Path(os.path.realpath(os.fspath(path)))
    else:
        result["kind"] = "other"
        result["error"] = "build path is neither a directory nor a symlink"
        return result, None

    result["resolved_target"] = _display(resolved)
    if not _within(resolved, allowed_root):
        result["error"] = "build target resolves outside allowed /usr/src header root"
        return result, None
    result["target_within_usr_src"] = True
    try:
        target_stat = os.lstat(resolved)
    except OSError:
        result["error"] = "resolved build target is missing or unreadable"
        return result, None
    if not stat.S_ISDIR(target_stat.st_mode):
        result["error"] = "resolved build target is not a directory"
        return result, None
    result["target_directory"] = True
    if not (
        resolved.name.startswith("linux-headers-")
        or (resolved.name.startswith("linux-hwe-") and "-headers-" in resolved.name)
    ):
        result["error"] = "resolved build target is not a recognized /usr/src header root"
        return result, None
    return result, resolved


def _snapshot_for_relative(
    root: Path | None,
    relative: str,
    *,
    label: str,
    limit: int,
    allowed_root: Path = Path("/usr/src"),
) -> tuple[dict[str, Any], bytes | None]:
    if root is None:
        return _empty_snapshot(relative, error=f"{label} has no resolved header root"), None
    candidate = root / relative
    try:
        candidate_info = os.lstat(candidate)
    except FileNotFoundError:
        candidate_info = None
    except OSError:
        candidate_info = None
    if candidate_info is not None and stat.S_ISLNK(candidate_info.st_mode):
        return _empty_snapshot(candidate, error=f"{label} final component is a symlink"), None
    resolved = Path(os.path.realpath(os.fspath(candidate)))
    if not _within(resolved, allowed_root):
        return _empty_snapshot(candidate, error=f"{label} resolves outside allowed header root"), None
    return _capture_file(
        candidate,
        label=label,
        limit=limit,
        resolved_from=root,
        allowed_root=allowed_root,
    )


def _directory_for_relative(
    root: Path | None,
    relative: str,
    *,
    label: str,
    allowed_root: Path = Path("/usr/src"),
) -> dict[str, Any]:
    if root is None:
        return {
            "path": relative,
            "resolved_path": None,
            "exists": False,
            "directory": False,
            "mode": None,
            "bytes": None,
            "nlink": None,
            "error": f"{label} has no resolved header root",
        }
    candidate = root / relative
    resolved = Path(os.path.realpath(os.fspath(candidate)))
    if not _within(resolved, allowed_root):
        return {
            "path": _display(candidate),
            "resolved_path": _display(resolved),
            "exists": False,
            "directory": False,
            "mode": None,
            "bytes": None,
            "nlink": None,
            "error": f"{label} resolves outside /usr/src",
        }
    result = _directory_metadata(resolved, label=label)
    result["path"] = _display(candidate)
    result["resolved_path"] = _display(resolved)
    return result


def _digest_inventory(entries: list[Mapping[str, Any]]) -> str:
    reduced = [
        {
            "path": entry.get("path"),
            "resolved_path": entry.get("resolved_path"),
            "exists": entry.get("exists"),
            "regular": entry.get("regular"),
            "directory": entry.get("directory"),
            "bytes": entry.get("bytes"),
            "sha256": entry.get("sha256"),
        }
        for entry in entries
    ]
    encoded = json.dumps(reduced, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parse_required_options(raw: bytes | None) -> dict[str, str | None]:
    values = {name: None for name in CONFIG_OPTIONS}
    if raw is None:
        return values
    try:
        text = raw.decode("ascii", errors="strict")
    except UnicodeDecodeError:
        return values
    for line in text.splitlines():
        if line.startswith("# ") and line.endswith(" is not set"):
            name = line[2:-len(" is not set")]
            if name in values:
                values[name] = "n"
        elif "=" in line:
            name, value = line.split("=", 1)
            if name in values and value in {"y", "m", "n"}:
                values[name] = value
    return values


def _release_matches(raw: bytes | None, release: str | None) -> bool:
    if raw is None or release is None:
        return False
    try:
        return raw == (release + "\n").encode("ascii")
    except UnicodeEncodeError:
        return False


def _utsrelease_matches(raw: bytes | None, release: str | None) -> bool:
    if raw is None or release is None:
        return False
    try:
        text = raw.decode("ascii", errors="strict")
    except UnicodeDecodeError:
        return False
    match = re.search(r'^#define UTS_RELEASE "([^"]+)"$', text, re.MULTILINE)
    return match is not None and match.group(1) == release


def _uname_observation(uname_value: Any | None = None) -> tuple[dict[str, Any], str | None, str | None]:
    if uname_value is None:
        try:
            uname_value = os.uname()
        except OSError:
            return {
                "available": False,
                "sysname": None,
                "release": None,
                "version": None,
                "machine": None,
                "error": "uname is unavailable",
            }, None, "uname is unavailable"
    release = getattr(uname_value, "release", None)
    if not isinstance(release, str) or not RELEASE_RE.fullmatch(release):
        return {
            "available": False,
            "sysname": getattr(uname_value, "sysname", None),
            "release": release if isinstance(release, str) else None,
            "version": getattr(uname_value, "version", None),
            "machine": getattr(uname_value, "machine", None),
            "error": "uname release is absent or malformed",
        }, None, "uname release is absent or malformed"
    return {
        "available": True,
        "sysname": getattr(uname_value, "sysname", None),
        "release": release,
        "version": getattr(uname_value, "version", None),
        "machine": getattr(uname_value, "machine", None),
        "error": None,
    }, release, None


def collect_inventory(
    *,
    uname_value: Any | None = None,
    boot_config_path: Path | None = None,
    build_link_path: Path | None = None,
    allowed_usr_src_root: Path | None = None,
) -> dict[str, Any]:
    """Collect a bounded local inventory without any execution side effect.

    Optional paths and ``uname_value`` are dependency-injection hooks for
    focused tests.  Production defaults are derived from the running kernel
    release and are restricted to the paths described in the module docstring.
    """

    uname, release, uname_error = _uname_observation(uname_value)
    allowed_usr_src_root = (
        Path("/usr/src") if allowed_usr_src_root is None
        else Path(os.path.realpath(os.fspath(allowed_usr_src_root)))
    )
    blockers: list[str] = []
    if uname_error:
        blockers.append(uname_error)

    if boot_config_path is None:
        boot_config_path = (
            Path("/boot") / f"config-{release}" if release is not None else None
        )
    if build_link_path is None:
        build_link_path = (
            Path("/lib/modules") / release / "build" if release is not None else None
        )

    boot_config, boot_raw = _capture_file(
        boot_config_path,
        label="matching /boot config",
        limit=MAX_CONFIG_BYTES,
    )
    if not boot_config["readable"]:
        blockers.append(str(boot_config["error"]))

    build_link: dict[str, Any]
    header_root: Path | None
    if build_link_path is None:
        build_link = {
            "path": "<unavailable>",
            "exists": False,
            "kind": None,
            "mode": None,
            "bytes": None,
            "nlink": None,
            "link_target": None,
            "resolved_target": None,
            "target_within_usr_src": False,
            "target_directory": False,
            "error": "build link has no bounded path",
        }
        header_root = None
    else:
        build_link, header_root = _build_link_metadata(
            build_link_path, allowed_root=allowed_usr_src_root
        )
        if build_link["error"]:
            blockers.append(str(build_link["error"]))

    header_root_metadata = _directory_metadata(header_root, label="resolved /usr/src header root")
    if not header_root_metadata["directory"]:
        blockers.append(str(header_root_metadata["error"]))

    header_files: dict[str, dict[str, Any]] = {}
    header_raw: dict[str, bytes | None] = {}
    for relative in HEADER_METADATA_FILES:
        snapshot, raw = _snapshot_for_relative(
            header_root,
            relative,
            label=f"header metadata {relative}",
            limit=MAX_HEADER_BYTES,
            allowed_root=allowed_usr_src_root,
        )
        header_files[relative] = snapshot
        header_raw[relative] = raw
        if not snapshot["readable"]:
            blockers.append(f"header metadata unavailable: {relative}")

    release_file_match = _release_matches(
        header_raw["include/config/kernel.release"], release
    )
    utsrelease_match = _utsrelease_matches(
        header_raw["include/generated/utsrelease.h"], release
    )
    config_hash_match = bool(
        boot_config["readable"]
        and header_files[".config"]["readable"]
        and boot_config["sha256"] == header_files[".config"]["sha256"]
    )
    if not config_hash_match:
        blockers.append("/boot config does not exactly match bounded header .config")
    if not release_file_match or not utsrelease_match:
        blockers.append("bounded header release markers do not exactly match uname release")

    uapi_files: dict[str, dict[str, Any]] = {}
    for relative in UAPI_SAMPLE_FILES:
        snapshot, _ = _snapshot_for_relative(
            header_root,
            relative,
            label=f"UAPI sample {relative}",
            limit=MAX_HEADER_BYTES,
            allowed_root=allowed_usr_src_root,
        )
        uapi_files[relative] = snapshot
    uapi_root = _directory_for_relative(
        header_root,
        "include/uapi",
        label="UAPI root",
        allowed_root=allowed_usr_src_root,
    )
    uapi_sample_complete = bool(
        uapi_root["directory"] and all(entry["readable"] for entry in uapi_files.values())
    )
    if not uapi_sample_complete:
        blockers.append("fixed UAPI sample inventory is incomplete")

    header_metadata_digest = _digest_inventory(list(header_files.values()))
    uapi_sample_digest = _digest_inventory(list(uapi_files.values()))

    source_git = _directory_metadata(
        header_root / ".git" if header_root is not None else None,
        label="bounded header-root .git metadata",
    )
    source_marker = _directory_metadata(
        header_root / "source" if header_root is not None else None,
        label="bounded header-root source marker",
    )
    source_tree_observed = bool(source_git["exists"] or source_marker["exists"])
    if not source_tree_observed:
        blockers.append("source tree and source commit are not observed in the bounded header scope")
    else:
        blockers.append("source tree/commit are not authenticated by bounded metadata")
    blockers.append("kernel build-id is not observed in the allowed bounded paths")
    blockers = list(dict.fromkeys(blockers))

    kernel_release_pinned = bool(
        uname["available"]
        and boot_config["readable"]
        and build_link["target_directory"]
        and release_file_match
        and utsrelease_match
    )
    config_pinned = config_hash_match
    uapi_pinned = False
    header_pinned = False
    build_id_pinned = False
    source_commit_pinned = False
    source_tree_pinned = False
    pins = {
        "kernel_release_pinned": kernel_release_pinned,
        "config_pinned": config_pinned,
        "uapi_pinned": uapi_pinned,
        "header_pinned": header_pinned,
        "build_id_pinned": build_id_pinned,
        "source_commit_pinned": source_commit_pinned,
        "source_tree_pinned": source_tree_pinned,
    }

    return {
        "schema": REPORT_SCHEMA,
        "record_id": REPORT_RECORD_ID,
        "scope_id": R008_SCOPE_ID,
        "status": STATUS,
        "uname": uname,
        "paths": {
            "boot_config": boot_config,
            "modules_build": build_link,
            "header_root": header_root_metadata,
            "uapi_root": uapi_root,
        },
        "evidence": {
            "kernel_release": {
                "status": "present" if uname["available"] else "not_proven",
                "observed": uname["available"],
                "proven": kernel_release_pinned,
                "release": release,
                "uname_bound": uname["available"],
                "header_kernel_release_match": release_file_match and utsrelease_match,
            },
            "config": {
                "status": "present" if config_hash_match else "not_proven",
                "observed": boot_config["readable"],
                "proven": config_pinned,
                "boot_config": boot_config,
                "header_config": header_files[".config"],
                "sha256_equal": config_hash_match,
                "required_options": _parse_required_options(boot_raw),
            },
            "uapi": {
                "status": "present" if uapi_sample_complete else "not_proven",
                "observed": uapi_sample_complete,
                "proven": uapi_sample_complete,
                "sample_only": True,
                "complete_tree_hash": None,
                "sample_inventory_sha256": uapi_sample_digest,
                "root": uapi_root,
                "files": uapi_files,
            },
            "headers": {
                "status": "present" if header_root_metadata["directory"] else "not_proven",
                "observed": header_root_metadata["directory"],
                "proven": header_root_metadata["directory"],
                "complete_tree_hash": None,
                "bounded_metadata_sha256": header_metadata_digest,
                "metadata_files": header_files,
                "release_marker_match": release_file_match and utsrelease_match,
            },
            "build_id": {
                "status": "not_observed_in_allowed_scope",
                "observed": False,
                "proven": False,
                "value": None,
                "reason": "No kernel image, debug ELF, sysfs note, or other build-id source was read.",
            },
            "source_commit": {
                "status": "not_observed_in_bounded_header_scope",
                "observed": False,
                "proven": False,
                "value": None,
                "git_metadata": source_git,
                "reason": "A header package does not prove a target source commit; no bounded commit object was found.",
            },
            "source_tree": {
                "status": "not_proven",
                "observed": source_tree_observed,
                "proven": False,
                "complete_tree_hash": None,
                "git_metadata": source_git,
                "source_marker": source_marker,
                "reason": "The bounded header/UAPI sample is not a complete authenticated source tree.",
            },
        },
        "pins": pins,
        "validation": {
            "fail_closed": True,
            "blockers": blockers,
            "kernel_release_observed": uname["available"],
            "matching_config_observed": config_hash_match,
            "uapi_sample_complete": uapi_sample_complete,
            "header_root_observed": header_root_metadata["directory"],
            "build_id_proven": False,
            "source_commit_proven": False,
            "source_tree_proven": False,
            "required_pins_complete": False,
            "read_scope_bounded": True,
        },
        "read_policy": READ_POLICY,
        "authorization": AUTHORIZATION,
        "side_effects": SIDE_EFFECTS,
    }


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise LocalInventoryError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_constant(token: str) -> Any:
    raise LocalInventoryError(f"non-standard JSON constant is not permitted: {token}")


def _read_json(path: Path) -> dict[str, Any]:
    raw, _ = _bounded_read(path, label="inventory report", limit=MAX_JSON_BYTES)
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except LocalInventoryError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LocalInventoryError("inventory report is not strict UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise LocalInventoryError("inventory report must be a JSON object")
    return value


def validate_report(report: Mapping[str, Any]) -> None:
    if not isinstance(report, Mapping):
        raise LocalInventoryError("report must be an object")
    if report.get("schema") != REPORT_SCHEMA:
        raise LocalInventoryError("report schema differs")
    if report.get("record_id") != REPORT_RECORD_ID:
        raise LocalInventoryError("report record_id differs")
    if report.get("scope_id") != R008_SCOPE_ID:
        raise LocalInventoryError("report scope differs")
    if report.get("status") != STATUS:
        raise LocalInventoryError("report status differs")
    if report.get("authorization") != AUTHORIZATION:
        raise LocalInventoryError("authorization boundary differs")
    if report.get("side_effects") != SIDE_EFFECTS:
        raise LocalInventoryError("side-effect boundary differs")
    if report.get("read_policy") != READ_POLICY:
        raise LocalInventoryError("read policy differs")
    validation = report.get("validation")
    if not isinstance(validation, Mapping):
        raise LocalInventoryError("validation section is missing")
    if validation.get("fail_closed") is not True:
        raise LocalInventoryError("report is not fail-closed")
    if validation.get("required_pins_complete") is not False:
        raise LocalInventoryError("report cannot claim complete target pins")
    pins = report.get("pins")
    if not isinstance(pins, Mapping):
        raise LocalInventoryError("pins section is missing")
    expected_pin_names = {
        "kernel_release_pinned", "config_pinned", "uapi_pinned", "header_pinned",
        "build_id_pinned", "source_commit_pinned", "source_tree_pinned",
    }
    if set(pins) != expected_pin_names or any(type(value) is not bool for value in pins.values()):
        raise LocalInventoryError("pin fields are malformed")
    if any(pins[name] for name in ("build_id_pinned", "source_commit_pinned", "source_tree_pinned")):
        raise LocalInventoryError("unproven build/source identity was promoted")
    evidence = report.get("evidence")
    if not isinstance(evidence, Mapping):
        raise LocalInventoryError("evidence section is missing")
    for name in ("build_id", "source_commit", "source_tree"):
        entry = evidence.get(name)
        if not isinstance(entry, Mapping) or entry.get("proven") is not False:
            raise LocalInventoryError(f"{name} evidence crossed the fail-closed boundary")


def build_report(
    *,
    uname_value: Any | None = None,
    boot_config_path: Path | None = None,
    build_link_path: Path | None = None,
    allowed_usr_src_root: Path | None = None,
) -> dict[str, Any]:
    report = collect_inventory(
        uname_value=uname_value,
        boot_config_path=boot_config_path,
        build_link_path=build_link_path,
        allowed_usr_src_root=allowed_usr_src_root,
    )
    validate_report(report)
    return report


def verify_report(path: Path = LAB_ROOT / DEFAULT_REPORT) -> dict[str, Any]:
    checked = _read_json(path)
    validate_report(checked)
    expected = build_report()
    if checked != expected:
        raise LocalInventoryError("checked-in report does not equal build_report()")
    return checked


def render_zh_report(report: Mapping[str, Any]) -> str:
    validate_report(report)
    evidence = report["evidence"]
    pins = report["pins"]
    blockers = report["validation"]["blockers"]
    options = evidence["config"]["required_options"]
    option_lines = "\n".join(
        f"- `{name}` = `{options[name] if options[name] is not None else '未观测'}`"
        for name in CONFIG_OPTIONS
    )
    blocker_lines = "\n".join(f"- {item}" for item in blockers)
    return (
        "# F8/R008 本机 target-kernel bounded inventory V1\n\n"
        f"- 状态：`{report['status']}`\n"
        f"- uname release：`{report['uname']['release'] or '未观测'}`\n"
        f"- kernel release evidence：`{evidence['kernel_release']['status']}`；"
        f"config：`{evidence['config']['status']}`；"
        f"UAPI 样本：`{evidence['uapi']['status']}`；"
        f"headers：`{evidence['headers']['status']}`\n"
        f"- build-id：`{evidence['build_id']['status']}`；"
        f"source commit：`{evidence['source_commit']['status']}`；"
        f"source tree：`{evidence['source_tree']['status']}`\n\n"
        "## 只读边界\n\n"
        "仅读取 uname、匹配的 `/boot/config-<release>`、"
        "`/lib/modules/<release>/build` 链接元数据，以及 `/usr/src` 下有限的"
        "header/UAPI 元数据与固定样本哈希；未读取 kernel image、生产 BI4/HDF5，"
        "未执行 privileged probe、挂载、系统写入、native/solver/worker/GPU/queue。\n\n"
        "## 配置样本\n\n"
        f"- `/boot/config` 与 header `.config` SHA-256 相等：`{evidence['config']['sha256_equal']}`\n"
        f"- UAPI 样本 inventory SHA-256：`{evidence['uapi']['sample_inventory_sha256']}`\n"
        f"- header bounded metadata SHA-256：`{evidence['headers']['bounded_metadata_sha256']}`\n"
        f"- complete UAPI/header/source tree hash：`未生成（bounded sample only）`\n\n"
        f"{option_lines}\n\n"
        "## Fail-closed 结论\n\n"
        f"- pins：`{json.dumps(dict(pins), sort_keys=True, ensure_ascii=False)}`\n"
        "- readiness / T1 / formal admission：`false`\n"
        "- qualification credit：`0`\n"
        "- source commit/tree 与 build-id 未被证明，不能把本机 header package 升格为 target pin。\n\n"
        "## Blockers\n\n"
        f"{blocker_lines}\n"
    )


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=LAB_ROOT / DEFAULT_REPORT)
    parser.add_argument("--zh-report", type=Path, default=LAB_ROOT / DEFAULT_ZH_REPORT)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.verify:
            report = verify_report(args.report)
        else:
            report = build_report()
            _write_json(args.report, report)
            args.zh_report.parent.mkdir(parents=True, exist_ok=True)
            args.zh_report.write_text(render_zh_report(report), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    except (LocalInventoryError, OSError, ValueError) as error:
        print(f"f8 target-kernel local inventory failed closed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
