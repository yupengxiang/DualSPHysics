#!/usr/bin/env python3
"""Stage a bounded time window and invoke the existing direct BI4 converter.

The wrapper is an orchestration shim, not a decoder.  A parent-created frame
manifest supplies the exact source files, native times, byte sizes, and hashes.
The wrapper selects every frame in the requested time interval, retains every
spatial particle in each selected BI4 frame, and renames only the staged frame
sequence so the existing converter's contiguous ``Part_0000.bi4`` contract is
preserved.  It never samples particles or invents identities.

No work is performed at import time.  A launch reads the manifest and copies
or hardlinks the selected BI4 files before invoking
``scripts/ds_data02_direct_convert.py`` unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping


MANIFEST_SCHEMA = "ds-data-02.m4.bi4-frame-manifest.v1"
STAGE_SCHEMA = "ds-data-02.m4.bi4-event-stage.v1"
FRAME_LIMIT = 1000
BYTE_LIMIT = 40 * 1024 * 1024 * 1024


class BoundedConversionError(ValueError):
    """Raised when a frame manifest cannot support a bounded conversion."""


def _regular(path: Path, label: str) -> Path:
    if not path.is_file() or path.is_symlink():
        raise BoundedConversionError(f"{label} is not a regular file: {path}")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_manifest(path: Path) -> dict[str, Any]:
    _regular(path, "frame manifest")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BoundedConversionError(f"frame manifest is not valid JSON: {path}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != MANIFEST_SCHEMA:
        raise BoundedConversionError(f"frame manifest schema must be {MANIFEST_SCHEMA!r}")
    frames = payload.get("frames")
    if not isinstance(frames, list) or len(frames) < 2:
        raise BoundedConversionError("frame manifest needs at least two frames")
    return payload


def _number(value: Any, label: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise BoundedConversionError(f"{label} is not numeric: {value!r}") from exc


def _select_frames(payload: Mapping[str, Any], start_s: float, end_s: float) -> list[dict[str, Any]]:
    if end_s <= start_s:
        raise BoundedConversionError("event window end must be greater than start")
    source_frames = payload.get("frames")
    assert isinstance(source_frames, list)
    ordered = []
    for index, row in enumerate(source_frames):
        if not isinstance(row, Mapping):
            raise BoundedConversionError(f"frame manifest row {index} is not an object")
        time_s = _number(row.get("time_s"), f"frame manifest row {index}.time_s")
        if start_s - 1.0e-9 <= time_s <= end_s + 1.0e-9:
            ordered.append(dict(row))
    ordered.sort(key=lambda row: (_number(row.get("time_s"), "frame time"), int(row.get("frame_index", -1))))
    if len(ordered) < 2:
        raise BoundedConversionError("selected event window contains fewer than two frames")
    if len(ordered) > FRAME_LIMIT:
        raise BoundedConversionError(f"selected event window exceeds {FRAME_LIMIT} frames")
    times = [_number(row.get("time_s"), "selected frame time") for row in ordered]
    if any(right <= left for left, right in zip(times, times[1:])):
        raise BoundedConversionError("selected frame times are not strictly increasing")
    if times[0] > start_s + 1.0e-3 or times[-1] < end_s - 1.0e-3:
        raise BoundedConversionError(
            f"selected frame times [{times[0]}, {times[-1]}] do not cover "
            f"the requested event window [{start_s}, {end_s}]"
        )
    source_indices = [int(row.get("frame_index", -1)) for row in ordered]
    if any(index < 0 for index in source_indices) or len(set(source_indices)) != len(source_indices):
        raise BoundedConversionError("selected frame indices must be unique non-negative integers")
    if any(right <= left for left, right in zip(source_indices, source_indices[1:])):
        raise BoundedConversionError("selected frame indices are not ordered")
    return ordered


def _source_path(source_root: Path, row: Mapping[str, Any]) -> Path:
    relative = row.get("relative_path", row.get("path"))
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise BoundedConversionError("frame manifest paths must be relative to source_root")
    if not Path(relative).name.startswith("Part_") or Path(relative).suffix != ".bi4":
        raise BoundedConversionError(f"frame manifest path is not a Part_*.bi4 file: {relative}")
    source = (source_root / relative).resolve()
    try:
        source.relative_to(source_root.resolve())
    except ValueError as exc:
        raise BoundedConversionError(f"frame escapes source root: {relative}") from exc
    return _regular(source, "BI4 frame")


def _copy_or_link(source: Path, destination: Path, mode: str) -> str:
    if mode == "hardlink":
        try:
            os.link(source, destination)
            return "hardlink"
        except OSError:
            mode = "copy"
    if mode != "copy":
        raise BoundedConversionError(f"unsupported staging mode: {mode}")
    with source.open("rb") as src, destination.open("xb") as dst:
        shutil.copyfileobj(src, dst, length=8 * 1024 * 1024)
    shutil.copystat(source, destination, follow_symlinks=False)
    return "copy"


def stage_frames(
    source_root: Path,
    frame_manifest: Path,
    destination: Path,
    *,
    start_s: float,
    end_s: float,
    staging_mode: str = "hardlink",
) -> dict[str, Any]:
    """Create a fresh contiguous frame directory from a parent-bound manifest."""

    source_root = source_root.resolve()
    if not source_root.is_dir() or source_root.is_symlink():
        raise BoundedConversionError(f"source BI4 root is not a regular directory: {source_root}")
    payload = _load_manifest(frame_manifest)
    selected = _select_frames(payload, start_s, end_s)
    source_bytes = sum(int(row.get("bytes", 0)) for row in selected)
    if source_bytes <= 0 or source_bytes > BYTE_LIMIT:
        raise BoundedConversionError(f"selected BI4 bytes exceed bounded staging limit: {source_bytes}")
    if destination.exists() or destination.is_symlink():
        raise BoundedConversionError(f"refusing to overwrite staging directory: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + f".partial-{os.getpid()}")
    if partial.exists() or partial.is_symlink():
        raise BoundedConversionError(f"stale staging directory exists: {partial}")
    partial.mkdir()
    records: list[dict[str, Any]] = []
    actual_modes: set[str] = set()
    try:
        for ordinal, row in enumerate(selected):
            source = _source_path(source_root, row)
            expected_bytes = int(row.get("bytes", -1))
            if expected_bytes != source.stat().st_size:
                raise BoundedConversionError(f"frame byte size changed before staging: {source}")
            expected_hash = row.get("sha256")
            if not isinstance(expected_hash, str) or len(expected_hash) != 64:
                raise BoundedConversionError(f"frame manifest lacks SHA-256: {source}")
            if _sha256(source) != expected_hash:
                raise BoundedConversionError(f"frame hash changed before staging: {source}")
            target = partial / f"Part_{ordinal:04d}.bi4"
            actual_modes.add(_copy_or_link(source, target, staging_mode))
            if target.stat().st_size != expected_bytes or _sha256(target) != expected_hash:
                raise BoundedConversionError(f"staged frame hash/size mismatch: {target}")
            records.append(
                {
                    "staged_path": target.name,
                    "source_relative_path": source.relative_to(source_root).as_posix(),
                    "source_frame_index": row.get("frame_index"),
                    "time_s": _number(row.get("time_s"), "frame time"),
                    "bytes": expected_bytes,
                    "sha256": expected_hash,
                }
            )
        stage = {
            "schema": STAGE_SCHEMA,
            "source_root_not_published": True,
            "source_root_sha256": payload.get("source_root_sha256"),
            "frame_manifest_sha256": _sha256(frame_manifest),
            "event_window_s": [start_s, end_s],
            "selected_frame_count": len(records),
            "selected_bytes": source_bytes,
            "staging_modes": sorted(actual_modes),
            "frames": records,
            "identity_contract": "all spatial particles in every selected BI4 frame; no spatial subsampling",
        }
        (partial / "event-stage.json").write_text(json.dumps(stage, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(partial, destination)
        return stage
    except Exception:
        shutil.rmtree(partial, ignore_errors=True)
        raise


def _converter_command(args: argparse.Namespace, staged_root: Path) -> list[str]:
    python = args.python or sys.executable
    converter = _regular(args.converter, "direct BI4 converter")
    command = [
        python,
        str(converter),
        "--data-root", str(staged_root),
        "--generated-xml", str(_regular(args.generated_xml, "generated XML")),
        "--output", str(args.attempt_root / "trajectory.h5"),
        "--report", str(args.attempt_root / "direct-conversion-report.json"),
        "--solver-log", str(_regular(args.solver_log, "solver log")),
        "--solver-receipt", str(_regular(args.solver_receipt, "solver receipt")),
        "--gencase-receipt", str(_regular(args.gencase_receipt, "GenCase receipt")),
        "--owner-metadata", str(_regular(args.owner_metadata, "owner metadata")),
        "--decoder", str(_regular(args.decoder, "BI4 decoder")),
        "--partvtk", str(_regular(args.partvtk, "PartVTK")),
        "--validation-dir", str(args.attempt_root / "partvtk-validation"),
        "--particle-chunk", str(args.particle_chunk),
    ]
    if args.keep_validation_csv:
        command.append("--keep-validation-csv")
    return command


def run(args: argparse.Namespace) -> dict[str, Any]:
    args.attempt_root = args.attempt_root.resolve()
    if args.attempt_root.exists() and any(args.attempt_root.iterdir()):
        raise BoundedConversionError(f"refusing non-empty conversion attempt root: {args.attempt_root}")
    args.attempt_root.mkdir(parents=True, exist_ok=True)
    staged_root = args.attempt_root / "staged-data"
    stage = stage_frames(
        args.source_root,
        args.frame_manifest,
        staged_root,
        start_s=args.event_start_s,
        end_s=args.event_end_s,
        staging_mode=args.staging_mode,
    )
    command = _converter_command(args, staged_root)
    completed = subprocess.run(command, check=False)
    result = {
        "schema": "ds-data-02.m4.bounded-conversion-receipt.v1",
        "status": "completed" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "event_window_s": [args.event_start_s, args.event_end_s],
        "stage": stage,
        "converter": "existing scripts/ds_data02_direct_convert.py",
        "command": command,
        "spatial_subsampling": "forbidden",
        "native_lifecycle_sidecar": "required in the subsequent report-only audit",
    }
    receipt = args.attempt_root / "bounded-conversion-receipt.json"
    receipt.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if completed.returncode:
        raise BoundedConversionError(f"direct BI4 converter failed with exit code {completed.returncode}")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--frame-manifest", required=True, type=Path)
    parser.add_argument("--event-start-s", required=True, type=float)
    parser.add_argument("--event-end-s", required=True, type=float)
    parser.add_argument("--attempt-root", required=True, type=Path)
    parser.add_argument("--converter", required=True, type=Path)
    parser.add_argument("--generated-xml", required=True, type=Path)
    parser.add_argument("--solver-log", required=True, type=Path)
    parser.add_argument("--solver-receipt", required=True, type=Path)
    parser.add_argument("--gencase-receipt", required=True, type=Path)
    parser.add_argument("--owner-metadata", required=True, type=Path)
    parser.add_argument("--decoder", required=True, type=Path)
    parser.add_argument("--partvtk", required=True, type=Path)
    parser.add_argument("--python")
    parser.add_argument("--particle-chunk", type=int, default=65536)
    parser.add_argument("--staging-mode", choices=("hardlink", "copy"), default="hardlink")
    parser.add_argument("--keep-validation-csv", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run(args)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, BoundedConversionError, subprocess.SubprocessError) as exc:
        print(f"bounded-conversion: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
