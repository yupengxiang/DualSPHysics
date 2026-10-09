#!/usr/bin/env python3
"""Rebind ROOT204 axis source records to the primary checkout's fresh stat.

The ROOT204 failure happened before the decoder: the source bytes and SHA were
unchanged, but the manifest carried the stat from the agent checkout.  This
module is deliberately metadata-only.  It reads only small source records,
requires a stable SHA/byte match before changing a path or stat, and never
opens a native Part/VTK/H5 payload.

It is used by the additive ROOT207 request builder.  The consumed ROOT204
manifest and request are never modified.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any


SCHEMA = "ds02.stage2.f1.native-selected-observer-axis-stat-rebind.v1"
FORBIDDEN_SUFFIXES = {".bi4", ".vtk", ".vtu", ".h5", ".hdf5"}
MAX_SOURCE_BYTES = 8 * 1024 * 1024
STAT_FIELDS = ("bytes", "mtime_ns", "ctime_ns", "device", "inode")


class RebindFailure(RuntimeError):
    """A source-only stat rebind cannot be admitted."""


def _path(value: str | Path) -> Path:
    return Path(value).expanduser().absolute()


def _remap_path(path: Path, old_root: Path, primary_root: Path) -> Path:
    old_text = str(old_root)
    value = str(path)
    if value == old_text:
        return primary_root
    prefix = old_text + os.sep
    if value.startswith(prefix):
        return primary_root / value[len(prefix) :]
    return path


def _regular(path: Path, label: str) -> os.stat_result:
    try:
        value = path.lstat()
    except OSError as exc:
        raise RebindFailure(f"{label} cannot be stat'ed: {path}: {exc}") from exc
    if path.is_symlink() or not path.is_file():
        raise RebindFailure(f"{label} is not a regular non-symlink file: {path}")
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise RebindFailure(f"{label} is a native payload, not a source record: {path}")
    if value.st_size > MAX_SOURCE_BYTES:
        raise RebindFailure(f"{label} exceeds source-only limit: {path}")
    return value


def _stat_dict(value: os.stat_result) -> dict[str, int]:
    return {
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "device": int(value.st_dev),
        "inode": int(value.st_ino),
    }


def _stable_sha_stat(path: Path, label: str) -> tuple[str, dict[str, int]]:
    """Hash one small source file and reject a source changing while read."""

    before = _stat_dict(_regular(path, label))
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    after = _stat_dict(_regular(path, label))
    if before != after:
        raise RebindFailure(f"{label} changed while its source SHA was read: {path}")
    return digest.hexdigest(), after


def _valid_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise RebindFailure(f"{label} lacks a SHA256 digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise RebindFailure(f"{label} has a non-hex SHA256 digest") from exc
    return value.lower()


def _source_record(record: Any, index: int, old_root: Path, primary_root: Path) -> tuple[dict[str, Any], dict[str, Any], bool]:
    if not isinstance(record, dict) or not isinstance(record.get("path"), str):
        raise RebindFailure(f"axis source record {index} is malformed")
    old_path = _path(record["path"])
    target = _remap_path(old_path, old_root, primary_root)
    old_sha = _valid_sha(record.get("sha256"), f"axis source record {index}")
    try:
        old_bytes = int(record["bytes"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RebindFailure(f"axis source record {index} lacks integer bytes") from exc

    actual_sha, actual_stat = _stable_sha_stat(target, f"axis source record {index}")
    sha_equal = actual_sha == old_sha
    bytes_equal = actual_stat["bytes"] == old_bytes
    old_stat = {key: record.get(key) for key in STAT_FIELDS}
    changed_stat_fields = [
        key for key in STAT_FIELDS if key in record and record.get(key) != actual_stat[key]
    ]
    report = {
        "index": index,
        "old_path": str(old_path),
        "new_path": str(target),
        "old_sha256": old_sha,
        "new_sha256": actual_sha,
        "old_bytes": old_bytes,
        "new_bytes": actual_stat["bytes"],
        "sha256_equal": sha_equal,
        "bytes_equal": bytes_equal,
        "old_stat": old_stat,
        "new_stat": actual_stat,
        "stat_changed_fields": changed_stat_fields,
        "transition": "STAT_ONLY_REBIND" if sha_equal and bytes_equal else "CONTENT_OR_SIZE_MISMATCH",
    }

    rebound = deepcopy(record)
    # Keep all scientific/source fields from the old record.  Only identity
    # and filesystem stat fields are changed after the content check succeeds.
    rebound["path"] = str(target)
    rebound["bytes"] = actual_stat["bytes"]
    rebound["sha256"] = actual_sha
    for key in ("mtime_ns", "ctime_ns", "device", "inode"):
        rebound[key] = actual_stat[key]
    return rebound, report, sha_equal and bytes_equal


def rebind_axis_source_records(
    manifest: dict[str, Any],
    *,
    primary_root: str | Path,
    old_reference_root: str | Path,
    allow_blocked: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a manifest with fresh primary stats and a complete audit report.

    ``allow_blocked`` is used only to emit a non-runnable diagnostic request
    when a stale/changed source is discovered.  It never permits a runnable
    request to replace a source SHA or byte count.
    """

    result = deepcopy(manifest)
    axis = result.get("axis_authority")
    if not isinstance(axis, dict) or not isinstance(axis.get("source_records"), list):
        raise RebindFailure("manifest has no axis_authority.source_records list")
    primary = _path(primary_root)
    old_root = _path(old_reference_root)
    reports: list[dict[str, Any]] = []
    path_map: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []
    new_records: list[dict[str, Any]] = []
    for index, record in enumerate(axis["source_records"]):
        try:
            rebound, report, equal = _source_record(record, index, old_root, primary)
        except RebindFailure as exc:
            raise
        reports.append(report)
        if not equal:
            errors.append(report)
            if not allow_blocked:
                raise RebindFailure(
                    f"axis source record {index} content differs after primary rebind: "
                    f"{report['old_path']} -> {report['new_path']}"
                )
            # Preserve the old authority values in a blocked manifest.  The
            # request cannot run, so V1 will fail closed if someone bypasses
            # the status gate; no replacement SHA is silently accepted.
            rebound = deepcopy(record)
            rebound["path"] = report["new_path"]
            for key in ("mtime_ns", "ctime_ns", "device", "inode"):
                rebound[key] = report["new_stat"][key]
        new_records.append(rebound)
        path_map[str(_path(record["path"]))] = rebound
        path_map[str(_path(report["new_path"]))] = rebound
    axis["source_records"] = new_records

    # V2 duplicated these records under source_inputs.  Update only records
    # that are the same source authority; do not touch deferred native paths.
    source_inputs = result.get("source_inputs")
    if isinstance(source_inputs, list):
        updated_inputs: list[Any] = []
        for item in source_inputs:
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                match = path_map.get(str(_path(item["path"])))
                if match is not None:
                    updated_inputs.append(deepcopy(match))
                    continue
            updated_inputs.append(item)
        result["source_inputs"] = updated_inputs

    report = {
        "schema": SCHEMA,
        "status": "BLOCKED_CONTENT_OR_SIZE_MISMATCH" if errors else "PASS_STAT_ONLY_REBIND",
        "stat_only": not bool(errors),
        "source_record_count": len(new_records),
        "records": reports,
        "content_mismatch_count": len(errors),
        "content_mismatches": errors,
        "primary_root": str(primary),
        "old_reference_root": str(old_root),
        "source_payload_read": False,
        "native_payload_read": False,
        "science_authority_replaced": False,
        "admission": "BLOCKED" if errors else "PARENT_GUARD_REVIEW_REQUIRED",
    }
    result["root207_axis_stat_rebind"] = report
    result["status"] = (
        "BLOCKED_ROOT207_AXIS_SOURCE_CONTENT_CHANGED"
        if errors
        else "ROOT207_AXIS_SOURCE_STAT_REBOUND_PENDING_PARENT_GUARD"
    )
    return result, report


def _self_test() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="root207-axis-rebind-") as directory:
        root = Path(directory)
        old_root = root / "agent"
        primary_root = root / "primary"
        old_source = old_root / "source.json"
        primary_source = primary_root / "source.json"
        old_source.parent.mkdir(parents=True)
        primary_source.parent.mkdir(parents=True)
        old_source.write_bytes(b"same-source-bytes")
        primary_source.write_bytes(b"same-source-bytes")
        os.utime(old_source, ns=(1_000_000_001, 1_000_000_001))
        os.utime(primary_source, ns=(2_000_000_002, 2_000_000_002))
        old_stat = old_source.stat()
        old_sha = hashlib.sha256(old_source.read_bytes()).hexdigest()
        manifest = {
            "schema": "fixture",
            "axis_authority": {
                "source_records": [
                    {
                        "path": str(old_source),
                        "bytes": old_stat.st_size,
                        "mtime_ns": old_stat.st_mtime_ns,
                        "ctime_ns": old_stat.st_ctime_ns,
                        "device": old_stat.st_dev,
                        "inode": old_stat.st_ino,
                        "sha256": old_sha,
                        "role": "fixture-authority",
                    }
                ]
            },
            "source_inputs": [],
        }
        rebound, report = rebind_axis_source_records(
            manifest, primary_root=primary_root, old_reference_root=old_root
        )
        entry = report["records"][0]
        assert report["status"] == "PASS_STAT_ONLY_REBIND"
        assert entry["sha256_equal"] and entry["bytes_equal"]
        assert entry["stat_changed_fields"]
        assert rebound["axis_authority"]["source_records"][0]["path"] == str(primary_source)

        primary_source.write_bytes(b"changed-source-bytes")
        try:
            rebind_axis_source_records(manifest, primary_root=primary_root, old_reference_root=old_root)
        except RebindFailure:
            changed_rejected = True
        else:
            changed_rejected = False
        assert changed_rejected
    return {
        "schema": SCHEMA,
        "status": "PASS",
        "same_bytes_different_mtime_accepted": True,
        "changed_sha_rejected": True,
        "production_payload_read": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if not args.self_test:
        parser.error("only --self-test is available; ROOT207 request builder owns production manifests")
    print(json.dumps(_self_test(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
