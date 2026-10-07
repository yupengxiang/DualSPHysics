#!/usr/bin/env python3
"""Root-registered metadata inventory for F6 PartFloatInfo.ibi4 inputs.

The source request is disabled.  When Root142 enables it, this worker reads
only the explicitly listed small PartFloatInfo.ibi4 files, checks their
before/after stats, and emits one immutable SHA inventory.  Source validation
never opens or hashes those files and this worker never reads particle BI4/H5
payloads.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Sequence


SCHEMA = "ds02.f6.partfloatinfo-inventory-result.v1"
REQUEST_SCHEMA = "ds02.f6.partfloatinfo-inventory-request.v1"


class InventoryError(RuntimeError):
    pass


def _dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InventoryError(f"{label} must be an object")
    return value


def _load(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise InventoryError(f"{label} is missing: {path}")
    try:
        return _dict(json.loads(path.read_text(encoding="utf-8")), label)
    except InventoryError:
        raise
    except Exception as exc:  # pragma: no cover - environment-specific parser errors
        raise InventoryError(f"{label} is invalid JSON: {path}") from exc


def _absolute(raw: Any, label: str) -> Path:
    if not isinstance(raw, str) or not raw:
        raise InventoryError(f"{label} must be an absolute path")
    path = Path(raw)
    if not path.is_absolute():
        raise InventoryError(f"{label} is not absolute: {raw!r}")
    return path


def _safe_relative(raw: Any, label: str) -> str:
    if not isinstance(raw, str) or not raw:
        raise InventoryError(f"{label} must be a relative path")
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise InventoryError(f"{label} escapes its data root: {raw!r}")
    return raw


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_request(request: dict[str, Any]) -> tuple[list[dict[str, Any]], Path, Path]:
    if request.get("schema") != REQUEST_SCHEMA:
        raise InventoryError(f"unexpected request schema: {request.get('schema')!r}")
    if request.get("disabled") is True or request.get("source_only") is True or request.get("execution_allowed") is not True:
        raise InventoryError("inventory request must be enabled by Root before execution")
    if request.get("launch_owner") != "root" or int(request.get("cpu_threads", 0)) != 2:
        raise InventoryError("inventory request is not Root-owned CPU2")
    if int(request.get("max_wall_seconds", 0)) != 600:
        raise InventoryError("inventory wall bound must remain 600 seconds")
    entries = request.get("entries")
    if not isinstance(entries, list) or not entries:
        raise InventoryError("inventory entries are missing")
    output = _dict(request.get("output"), "output")
    output_dir = _absolute(output.get("directory"), "output.directory")
    report_path = _absolute(output.get("report_path"), "output.report_path")
    if output_dir in report_path.parents and report_path.parent != output_dir:
        raise InventoryError("report path must be directly inside the private output directory")
    if report_path.parent != output_dir:
        raise InventoryError("report path must be inside output.directory")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise InventoryError(f"private inventory output is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    seen: set[str] = set()
    for number, entry in enumerate(entries):
        item = _dict(entry, f"entries[{number}]")
        case_id = item.get("case_id")
        physical_id = item.get("physical_case_id")
        if not isinstance(case_id, str) or not case_id or not isinstance(physical_id, str) or not physical_id:
            raise InventoryError(f"entries[{number}] identity is incomplete")
        if physical_id in seen:
            raise InventoryError(f"duplicate physical case: {physical_id}")
        seen.add(physical_id)
        root = _absolute(item.get("data_root"), f"entries[{number}].data_root")
        relative = _safe_relative(item.get("relative_path"), f"entries[{number}].relative_path")
        if relative != "PartFloatInfo.ibi4":
            raise InventoryError(f"entries[{number}] is not the official PartFloatInfo input")
        expected = item.get("expected_stat_bytes")
        if not isinstance(expected, int) or expected <= 0:
            raise InventoryError(f"entries[{number}] expected stat is invalid")
        path = root / relative
        if not path.is_file():
            raise InventoryError(f"entries[{number}] input is missing: {path}")
        if path.stat().st_size != expected:
            raise InventoryError(f"entries[{number}] input stat changed: {path}")
    return entries, output_dir, report_path


def _write(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def execute(request_path: Path, report_override: Path | None = None) -> int:
    base: dict[str, Any] = {"schema": SCHEMA, "request": str(request_path), "future_hashes_null": False}
    report_path: Path | None = report_override
    try:
        request = _load(request_path, "inventory request")
        entries, output_dir, configured_report_path = _validate_request(request)
        report_path = report_path or configured_report_path
        output: list[dict[str, Any]] = []
        for entry in entries:
            root = _absolute(entry["data_root"], "entry.data_root")
            path = root / entry["relative_path"]
            before = path.stat()
            if before.st_size != entry["expected_stat_bytes"]:
                raise InventoryError(f"input stat changed before hashing: {path}")
            digest = _sha256(path)
            after = path.stat()
            if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
                raise InventoryError(f"input changed while hashing: {path}")
            output.append({
                "case_id": entry["case_id"],
                "physical_case_id": entry["physical_case_id"],
                "path": str(path),
                "relative_path": entry["relative_path"],
                "bytes_before": before.st_size,
                "bytes_after": after.st_size,
                "sha256": digest,
                "stat_before_mtime_ns": before.st_mtime_ns,
                "stat_after_mtime_ns": after.st_mtime_ns,
            })
        report = {
            **base,
            "status": "completed",
            "returncode": 0,
            "request_id": request.get("request_id"),
            "entries": output,
            "entry_count": len(output),
            "input_policy": "Only the explicitly listed PartFloatInfo.ibi4 files are read and hashed by this Root-registered worker; particle BI4/H5 payloads are not opened.",
        }
        _write(report_path, report)
        return 0
    except Exception as exc:
        if report_path is None:
            report_path = report_override or request_path.with_name(request_path.stem + ".failure.json")
        _write(report_path, {**base, "status": "failed", "returncode": 1, "error_type": type(exc).__name__, "error": str(exc), "entries": None})
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    return execute(args.request, args.report)


if __name__ == "__main__":
    raise SystemExit(main())
