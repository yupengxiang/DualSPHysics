#!/usr/bin/env python3
"""Consume one fresh F3 row-30 resource/scheduler preflight authorization.

This additive v7 wrapper preserves the consumed v1-v6 history and delegates
only read-only resource/scheduler checks to the reviewed v2 implementation.
It never starts a material worker or reserves a queue/ledger slot.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts import f3_material_row30_resource_preflight_v2 as preflight_v2


SCOPE_DIR = LAB / "campaigns/core-v1/material/evidence/f3-material-row30-resource-preflight-v7"
OUTPUT = SCOPE_DIR / "receipt.json"
LOCK = SCOPE_DIR / "one-shot-lock.json"
SCHEMA = "core.material.f3.row30.resource_preflight.v7"
RECORD_ID = "f3-material-row30-resource-preflight-v7"
AUTHORITY = "explicit user authorization: one additional F3 material row-30 resource/scheduler preflight; no worker launch"
PRIOR_RECEIPT = Path("campaigns/core-v1/material/evidence/f3-material-row30-resource-preflight-v6/receipt.json")


def _write_once(path: Path, payload: bytes) -> None:
    temporary = path.with_name(path.name + ".partial")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary, flags, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def build(*, environment_probe=None, process_probe=None, now: datetime | None = None) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"now": now}
    if environment_probe is not None:
        kwargs["environment_probe"] = environment_probe
    if process_probe is not None:
        kwargs["process_probe"] = process_probe
    value = preflight_v2.build(**kwargs)
    value["schema"] = SCHEMA
    value["record_id"] = RECORD_ID
    value["authorized_scope"] = AUTHORITY
    value["supersedes"] = preflight_v2._binding(
        PRIOR_RECEIPT,
        "prior blocked row30 v6 preflight; preserved as historical evidence",
        preflight_v2._read_regular(LAB / PRIOR_RECEIPT),
    )
    value["bindings"].extend((
        preflight_v2._binding(
            Path("scripts/f3_material_row30_resource_preflight_v7.py"),
            "v7 fresh one-shot preflight wrapper",
            preflight_v2._read_regular(LAB / "scripts/f3_material_row30_resource_preflight_v7.py"),
        ),
        preflight_v2._binding(
            Path("tests/test_f3_material_row30_resource_preflight_v7.py"),
            "v7 preflight contract tests",
            preflight_v2._read_regular(LAB / "tests/test_f3_material_row30_resource_preflight_v7.py"),
        ),
    ))
    return value


def write_once(*, scope_dir: Path = SCOPE_DIR) -> dict[str, Any]:
    scope = Path(scope_dir)
    if scope.exists() or scope.is_symlink():
        raise FileExistsError(f"F3 row-30 v7 one-shot namespace already exists: {scope}")
    scope.mkdir(mode=0o755)
    lock = scope / LOCK.name
    lock_value = {
        "schema": "core.material.f3.row30.resource_preflight_one_shot_lock.v2",
        "record_id": RECORD_ID + "-one-shot-lock",
        "authorized_scope": AUTHORITY,
        "consumed_at_utc": datetime.now(timezone.utc).isoformat(),
        "worker_launch_authorized": False,
    }
    _write_once(lock, (json.dumps(lock_value, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    try:
        value = build()
        value["one_shot_lock"] = preflight_v2._binding(
            lock.relative_to(LAB) if lock.is_relative_to(LAB) else Path("one-shot-lock.json"),
            "exclusive lock consuming this single preflight authorization",
            preflight_v2._read_regular(lock),
        )
        receipt = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
        _write_once(scope / OUTPUT.name, receipt)
        return value
    except Exception as error:
        failure = {
            **lock_value,
            "status": "preflight_failed_after_one_shot_consumed",
            "failure_type": type(error).__name__,
            "failure_message": str(error),
        }
        failure_path = scope / "terminal-failure.json"
        if not failure_path.exists():
            _write_once(failure_path, (json.dumps(failure, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        raise


__all__ = ["AUTHORITY", "OUTPUT", "RECORD_ID", "SCHEMA", "build", "write_once"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    value = write_once()
    print(json.dumps({
        key: value[key] for key in (
            "status", "current_environment", "active_f3_row30_workers",
            "scheduler_active_job_count", "blockers", "worker_launch_authorized",
        )
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
