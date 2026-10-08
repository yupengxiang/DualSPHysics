#!/usr/bin/env python3
"""Guarded, source-bound copy materialization for F1 owner runs.

This is deliberately separate from the GPU solver entry.  A parent CPU-v8
task runs it after reservation and before a v6 GPU request.  It copies the
producer BI4 into a new, parent-reserved preparation namespace.  It never
changes the source BI4 and fails closed on an existing destination or a
changed source.  A hard link is intentionally not used: creating one changes
the producer inode ctime/link count and would invalidate a prior complete
stat join even when bytes are unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat as statmod
import tempfile
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f1.owner-bi4-copy-materialization.v2"
CHUNK = 8 * 1024 * 1024


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(CHUNK)
            if not b:
                return h.hexdigest()
            h.update(b)


def file_stat(path: Path) -> dict[str, Any]:
    s = path.stat()
    return {
        "path": str(path),
        "device": int(s.st_dev),
        "inode": int(s.st_ino),
        "bytes": int(s.st_size),
        "mode": int(statmod.S_IMODE(s.st_mode)),
        "mtime_ns": int(s.st_mtime_ns),
        "ctime_ns": int(s.st_ctime_ns),
        "nlink": int(s.st_nlink),
    }


def stable_source(before: dict[str, Any], after: dict[str, Any]) -> bool:
    # A byte-for-byte copy must leave every source stat field unchanged.
    fields = ("device", "inode", "bytes", "mode", "mtime_ns", "ctime_ns", "nlink")
    return all(before[k] == after[k] for k in fields)


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def materialize(plan_path: Path, output_path: Path) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("schema") != SCHEMA:
        raise ValueError(f"unsupported plan schema: {plan.get('schema')!r}")
    src_info = plan.get("source_bi4")
    if not isinstance(src_info, dict):
        raise ValueError("source_bi4 is required")
    source = Path(str(src_info["path"])).resolve()
    expected_sha = str(src_info["sha256"])
    expected_bytes = int(src_info["bytes"])
    if not source.is_file() or source.is_symlink():
        raise FileNotFoundError(f"source is not a regular file: {source}")

    before = file_stat(source)
    digest_before = sha256_file(source)
    if digest_before != expected_sha or before["bytes"] != expected_bytes:
        raise ValueError("source pre-hash/stat does not match bound QA evidence")

    destinations = plan.get("destinations")
    if not isinstance(destinations, list) or not destinations:
        raise ValueError("at least one destination is required")
    created: list[dict[str, Any]] = []
    try:
        for item in destinations:
            if not isinstance(item, dict) or "path" not in item:
                raise ValueError("destination path is required")
            destination = Path(str(item["path"])).resolve()
            if destination == source:
                raise ValueError("destination aliases source path")
            if destination.exists() or destination.is_symlink():
                raise FileExistsError(f"refusing to overwrite destination: {destination}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copyfile(source, destination)
            dstat = file_stat(destination)
            if (
                dstat["inode"] == before["inode"]
                or dstat["bytes"] != expected_bytes
            ):
                raise ValueError(f"copy identity check failed: {destination}")
            digest_destination = sha256_file(destination)
            if digest_destination != expected_sha:
                raise ValueError(f"destination digest differs: {destination}")
            created.append(
                {
                    "path": str(destination),
                    "stat": dstat,
                    "same_inode_as_source": False,
                    "sha256": digest_destination,
                    "bytes_copied": expected_bytes,
                }
            )
    except Exception:
        # Never silently leave a partial materialization that a later solver
        # could mistake for a complete predecessor.
        for entry in reversed(created):
            try:
                Path(entry["path"]).unlink()
            except FileNotFoundError:
                pass
        raise

    after = file_stat(source)
    digest_after = sha256_file(source)
    if digest_after != digest_before or not stable_source(before, after):
        for entry in reversed(created):
            try:
                Path(entry["path"]).unlink()
            except FileNotFoundError:
                pass
        raise ValueError("source content/stat changed during copy materialization")
    result = {
        "schema": "ds02.stage2.f1.owner-bi4-copy-materialization-receipt.v2",
        "status": "PASS_COPY_SOURCE_BOUND",
        "plan": str(plan_path.resolve()),
        "plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        "source": {
            "path": str(source),
            "sha256_pre": digest_before,
            "sha256_post": digest_after,
            "expected_sha256": expected_sha,
            "stat_pre": before,
            "stat_post": after,
            "content_stable": True,
            "stat_stable_all_fields": True,
            "source_inode_link_count_untouched": True,
        },
        "destinations": created,
        "source_copied_to_new_namespace": True,
        "source_not_modified": True,
        "copy_is_not_a_hardlink": True,
    }
    atomic_json(output_path, result)
    return result


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="ds02-f1-link-selftest-") as td:
        root = Path(td)
        source = root / "source.bi4"
        source.write_bytes(bytes(range(256)) * 64)
        digest = sha256_file(source)
        plan = root / "plan.json"
        plan.write_text(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "source_bi4": {"path": str(source), "sha256": digest, "bytes": source.stat().st_size},
                    "destinations": [{"path": str(root / "a.bi4")}, {"path": str(root / "b.bi4")}],
                }
            ),
            encoding="utf-8",
        )
        out = root / "receipt.json"
        result = materialize(plan, out)
        assert result["status"] == "PASS_COPY_SOURCE_BOUND"
        assert (root / "a.bi4").stat().st_ino != source.stat().st_ino
        assert (root / "b.bi4").stat().st_ino != source.stat().st_ino
        assert file_stat(source)["nlink"] == 1
        print("PASS f1 owner BI4 copy self-test")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", type=Path)
    ap.add_argument("--output", type=Path)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.plan or not args.output:
        ap.error("--plan and --output are required unless --self-test is used")
    result = materialize(args.plan.resolve(), args.output.resolve())
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve())}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
