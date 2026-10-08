#!/usr/bin/env python3
"""Forward V2 guarded, source-only snapshot of the F2-S1 GenCase ``generated.bi4``.

The generated BI4 is deliberately not an ``input_files`` digest in the
parent request: the v8 parent must reserve the bounded CPU attempt before
this worker opens the payload.  The worker then opens exactly one regular
file, streams its complete SHA-256 through one file descriptor, and compares
the path and descriptor ``bytes/mtime/ctime/device/inode`` records before and
after the read.  A changed source is a failed immutable report and a non-zero
process exit.  This worker does not decode BI4, read HDF5, scan a directory,
start GenCase, or start a solver.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat as stat_module
import tempfile
from typing import Any


SCHEMA = "ds02.stage2.f2-s1.generated-bi4-source-snapshot.v2"
CHUNK_BYTES = 1024 * 1024
STAT_KEYS = ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino", "st_mode")


def _stat_values(value: os.stat_result) -> dict[str, int]:
    return {
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
        "st_mode": int(value.st_mode),
    }


def _regular_lstat(path: Path, label: str) -> os.stat_result:
    """Return an lstat record and reject a symlink or non-regular source."""

    try:
        value = path.lstat()
    except OSError as exc:
        raise RuntimeError(f"{label} cannot be lstat'ed: {path}: {exc}") from exc
    if stat_module.S_ISLNK(value.st_mode):
        raise RuntimeError(f"{label} must not be a symlink: {path}")
    if not stat_module.S_ISREG(value.st_mode):
        raise RuntimeError(f"{label} must be a regular file: {path}")
    return value


def _open_nofollow(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise RuntimeError(f"cannot open source with no-follow guard: {path}: {exc}") from exc
    try:
        value = os.fstat(fd)
        if not stat_module.S_ISREG(value.st_mode):
            raise RuntimeError(f"opened source is not a regular file: {path}")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _assert_same(before: dict[str, int], after: dict[str, int], label: str) -> None:
    changed = {key: (before.get(key), after.get(key)) for key in STAT_KEYS if before.get(key) != after.get(key)}
    if changed:
        raise RuntimeError(f"{label} changed during source read: {changed}")


def stream_source(path: Path, *, expected_bytes: int | None = None) -> dict[str, Any]:
    """Hash exactly one source file while retaining complete pre/post proof."""

    path = path.expanduser().absolute()
    path_lstat_before = _regular_lstat(path, "generated.bi4")
    fd = _open_nofollow(path)
    try:
        fd_stat_before = os.fstat(fd)
        path_before = _stat_values(path_lstat_before)
        fd_before = _stat_values(fd_stat_before)
        _assert_same(path_before, fd_before, "path/fd source identity before read")
        if expected_bytes is not None and path_before["bytes"] != expected_bytes:
            raise RuntimeError(
                f"generated.bi4 byte count differs from registered GenCase product: "
                f"expected={expected_bytes} actual={path_before['bytes']}"
            )

        digest = hashlib.sha256()
        bytes_read = 0
        while True:
            block = os.read(fd, CHUNK_BYTES)
            if not block:
                break
            digest.update(block)
            bytes_read += len(block)
        fd_stat_after = os.fstat(fd)
        path_lstat_after = _regular_lstat(path, "generated.bi4")
        path_after = _stat_values(path_lstat_after)
        fd_after = _stat_values(fd_stat_after)
        _assert_same(fd_before, fd_after, "open-file source identity")
        _assert_same(path_before, path_after, "path source identity")
        _assert_same(path_after, fd_after, "path/fd source identity after read")
        if bytes_read != path_before["bytes"]:
            raise RuntimeError(
                f"streamed byte count differs from source stat: read={bytes_read} stat={path_before['bytes']}"
            )

        sha256 = digest.hexdigest()
        return {
            "path": str(path),
            "bytes": bytes_read,
            "sha256": sha256,
            "stat_before": path_before,
            "stat_after": path_after,
            "fd_stat_before": fd_before,
            "fd_stat_after": fd_after,
            "pre_post_stat_consistency": "PASS_IDENTICAL_BYTES_MTIME_CTIME_DEVICE_INODE_MODE",
            "hash_scope": "ONE_COMPLETE_STREAM_BETWEEN_PRE_POST_STAT_CHECKS",
        }
    finally:
        os.close(fd)


def _write_immutable(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse to overwrite immutable snapshot output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    if temporary.exists():
        raise FileExistsError(f"temporary snapshot output already exists: {temporary}")
    try:
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        try:
            with os.fdopen(fd, "wb") as handle:
                fd = -1
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            if fd >= 0:
                os.close(fd)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    output = args.output.expanduser().absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"refuse to overwrite immutable snapshot output: {output}")
    source = args.input_bi4.expanduser().absolute()
    expected_bytes = args.expected_bytes
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "FAILED_BEFORE_SOURCE_READ",
        "case_id": args.case_id,
        "family_id": "F2",
        "sentinel_id": "F2-S1",
        "physical_case_id": args.physical_case_id,
        "source": {
            "path": str(source),
            "expected_bytes": expected_bytes,
            "content_sha256": "NOT_COMPUTED_ON_FAILURE",
        },
        "worker_scope": {
            "single_generated_bi4": True,
            "full_payload_streamed": False,
            "read_plan": {
                "passes": 1,
                "estimated_single_stream_read_bytes": expected_bytes,
                "estimated_peak_buffer_bytes": CHUNK_BYTES,
            },
            "bi4_decode": False,
            "hdf5_read": False,
            "raw_directory_scan": False,
            "gencase_launch": False,
            "solver_launch": False,
            "source_sha_computed_after_parent_reservation": True,
            "source_sha_authority": "worker_stream_after_parent_reservation",
            "parent_v8_receipt_hashes_deferred_source": False,
            "parent_v8_deferred_input_hash_scope": "NOT_COMPUTED_BY_PARENT_RUNTIME; deferred_input_files is metadata only",
            "parent_v8_input_hashes_cover": "input_files_only_small_closure",
            "worker_content_sha256_after_reservation": "FULL_STREAM_SHA256_RECORDED_HERE",
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    try:
        source_record = stream_source(source, expected_bytes=expected_bytes)
        report["status"] = "PASS_GENERATED_BI4_HASHED_STABLE"
        report["source"] = {**report["source"], **source_record, "content_sha256": source_record["sha256"]}
        report["worker_scope"]["full_payload_streamed"] = True
    except BaseException as exc:
        report["status"] = "FAILED_GENERATED_BI4_SOURCE_GUARD"
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        report["failure_is_scientific_unknown"] = True
        _write_immutable(output, report)
        raise
    _write_immutable(output, report)
    return report


def self_test() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ds02-f2-bi4-snapshot-") as root_text:
        root = Path(root_text)
        source = root / "generated.bi4"
        source.write_bytes(b"synthetic-bi4-payload\x00" * 13)
        record = stream_source(source, expected_bytes=source.stat().st_size)
        assert record["bytes"] == source.stat().st_size
        assert len(record["sha256"]) == 64
        assert record["stat_before"] == record["stat_after"]
        output = root / "snapshot.json"
        args = argparse.Namespace(
            input_bi4=source,
            output=output,
            expected_bytes=source.stat().st_size,
            case_id="SELFTEST",
            physical_case_id="SELFTEST",
        )
        report = build_report(args)
        assert report["status"] == "PASS_GENERATED_BI4_HASHED_STABLE"
        try:
            build_report(args)
        except FileExistsError:
            immutable_rejected = True
        else:
            immutable_rejected = False
        assert immutable_rejected
        bad_output = root / "bad-size.json"
        bad_args = argparse.Namespace(
            input_bi4=source,
            output=bad_output,
            expected_bytes=source.stat().st_size + 1,
            case_id="SELFTEST_BAD_SIZE",
            physical_case_id="SELFTEST",
        )
        try:
            build_report(bad_args)
        except RuntimeError:
            bad_size_rejected = True
        else:
            bad_size_rejected = False
        assert bad_size_rejected
        bad_report = json.loads(bad_output.read_text(encoding="utf-8"))
        assert bad_report["status"] == "FAILED_GENERATED_BI4_SOURCE_GUARD"
        return {
            "status": "PASS",
            "schema": SCHEMA,
            "full_stream_hash": True,
            "pre_post_bytes_mtime_ctime_device_inode": True,
            "immutable_output_rejected": True,
            "wrong_expected_size_rejected_with_failure_report": True,
            "decoder_or_solver": False,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--input-bi4", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected-bytes", type=int)
    parser.add_argument("--case-id", default="F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0088_ROOT_076")
    parser.add_argument("--physical-case-id", default="F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    if args.input_bi4 is None or args.output is None:
        parser.error("--input-bi4 and --output are required unless --self-test is used")
    if args.expected_bytes is not None and args.expected_bytes <= 0:
        parser.error("--expected-bytes must be positive")
    try:
        report = build_report(args)
    except BaseException as exc:
        # The immutable failure report is written by build_report when the
        # source read has started.  Let the parent receipt retain non-zero
        # child status instead of turning a source mutation into PASS.
        print(json.dumps({"status": "FAILED_GENERATED_BI4_SOURCE_GUARD", "error": str(exc)}, ensure_ascii=False), flush=True)
        return 1
    print(json.dumps({"status": report["status"], "output": str(args.output.expanduser().absolute()), "sha256": report["source"]["sha256"], "bytes": report["source"]["bytes"]}, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
