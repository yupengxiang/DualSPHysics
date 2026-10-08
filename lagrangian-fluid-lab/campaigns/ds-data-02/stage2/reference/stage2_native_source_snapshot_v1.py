#!/usr/bin/env python3
"""Hash exactly the selected native BI4 files for later observer binding.

The observer requests intentionally leave their selected ``Part_*.bi4``
digests deferred until the parent has a fresh CPU/I/O reservation.  This
worker closes that small provenance gap without walking or hashing the raw
directory.  It consumes only the request metadata and the explicitly listed
selected files, and writes an immutable SHA manifest for a later observer
request builder.  It never decodes BI4, reads HDF5, starts a solver, or
modifies a source file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable


SCHEMA = "ds02.stage2.native-source-snapshot.v1"
PART_RE = re.compile(r"^Part_(\d+)\.bi4$")
CHUNK = 1024 * 1024


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def file_record(path: Path) -> dict[str, Any]:
    path = path.expanduser()
    if path.is_symlink():
        raise ValueError(f"selected native input must be a regular non-symlink file: {path}")
    path = path.resolve()
    if not path.is_file():
        raise ValueError(f"selected native input must be a regular non-symlink file: {path}")
    digest, size = sha256_file(path)
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": size,
        "mtime_ns": int(stat.st_mtime_ns),
        "sha256": digest,
    }


def record_without_content(path: Path) -> dict[str, Any]:
    path = path.expanduser()
    if path.is_symlink():
        raise ValueError(f"required request metadata must be a regular file: {path}")
    path = path.resolve()
    if not path.is_file():
        raise ValueError(f"required request metadata must be a regular file: {path}")
    stat = path.stat()
    digest, size = sha256_file(path)
    return {"path": str(path), "bytes": size, "mtime_ns": int(stat.st_mtime_ns), "sha256": digest}


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def command_value(command: list[Any], flag: str) -> str | None:
    for index, value in enumerate(command):
        if value == flag and index + 1 < len(command):
            candidate = command[index + 1]
            if isinstance(candidate, str):
                return candidate
    return None


def frame_ids_from_request(request: dict[str, Any]) -> list[int]:
    raw = request.get("selected_native_frame_ids")
    if raw is None:
        command = request.get("command", [])
        try:
            start = command.index("--frames") + 1
        except ValueError as exc:
            raise ValueError("observer request has no selected_native_frame_ids or --frames") from exc
        raw = []
        for value in command[start:]:
            if not isinstance(value, str) or value.startswith("--"):
                break
            raw.append(value)
    if not isinstance(raw, list) or not raw:
        raise ValueError("selected native frame list must be non-empty")
    try:
        frames = [int(value) for value in raw]
    except (TypeError, ValueError) as exc:
        raise ValueError("selected native frame list contains a non-integer") from exc
    if any(frame < 0 for frame in frames) or len(set(frames)) != len(frames):
        raise ValueError("selected native frame IDs must be unique non-negative integers")
    return frames


def raw_root_from_request(request: dict[str, Any]) -> Path:
    raw_root = request.get("source_binding", {}).get("raw_root")
    if not isinstance(raw_root, str):
        raw_root = command_value(request.get("command", []), "--raw-root")
    if not isinstance(raw_root, str) or not raw_root:
        raise ValueError("observer request has no raw-root binding")
    path = Path(raw_root).expanduser()
    if path.is_symlink():
        raise ValueError(f"raw-root is not a regular directory: {path}")
    path = path.resolve()
    if not path.is_dir():
        raise ValueError(f"raw-root is not a regular directory: {path}")
    return path


def selected_paths(request: dict[str, Any]) -> tuple[Path, list[int], list[Path]]:
    raw_root = raw_root_from_request(request)
    frames = frame_ids_from_request(request)
    deferred = request.get("deferred_input_files")
    if not isinstance(deferred, list) or not deferred:
        raise ValueError("observer request has no deferred_input_files")
    listed: dict[int, Path] = {}
    for value in deferred:
        if not isinstance(value, str):
            raise ValueError("deferred_input_files must contain strings")
        path = Path(value).expanduser()
        if path.is_symlink():
            raise ValueError(f"deferred selected BI4 must not be a symlink: {path}")
        path = path.resolve()
        match = PART_RE.fullmatch(path.name)
        if match is None:
            continue
        if path.parent != raw_root:
            raise ValueError(f"selected BI4 is outside its bound raw-root: {path}")
        frame = int(match.group(1))
        if frame in listed and listed[frame] != path:
            raise ValueError(f"duplicate frame with different paths: {frame}")
        listed[frame] = path
    missing = [frame for frame in frames if frame not in listed]
    if missing:
        raise FileNotFoundError(f"deferred request omits selected frame(s): {missing}")
    extra = sorted(set(listed) - set(frames))
    if extra:
        raise ValueError(f"deferred request includes unregistered BI4 frame(s): {extra}")
    paths = [listed[frame] for frame in frames]
    if len(set(paths)) != len(paths):
        raise ValueError("selected frame paths are not unique")
    return raw_root, frames, paths


def request_snapshot(request_path: Path) -> dict[str, Any]:
    request_path = request_path.resolve()
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if not isinstance(request, dict) or request.get("schema") != "ds02.request.v1":
        raise ValueError(f"not a ds02.request.v1 observer request: {request_path}")
    raw_root, frames, paths = selected_paths(request)
    files = []
    for frame, path in zip(frames, paths):
        item = file_record(path)
        item["frame"] = frame
        files.append(item)
    source_digest = canonical_digest(
        [{key: item[key] for key in ("frame", "path", "bytes", "sha256")} for item in files]
    )
    return {
        "observer_request": record_without_content(request_path),
        "case_id": request.get("case_id", "UNKNOWN"),
        "sentinel_id": request.get("sentinel_id", "UNKNOWN"),
        "family_id": request.get("family_id", "UNKNOWN"),
        "physical_case_id": request.get("physical_case_id", "UNKNOWN"),
        "raw_root": str(raw_root),
        "selected_native_frame_ids": frames,
        "selected_native_files": files,
        "selected_native_bytes": sum(item["bytes"] for item in files),
        "selected_source_sha256": source_digest,
        "scope": {
            "selected_files_only": True,
            "directory_hash": "NOT_COMPUTED_BY_WORKER",
            "raw_root_hash": "NOT_COMPUTED_BY_WORKER",
            "unlisted_part_files": "NOT_INSPECTED_BY_WORKER",
            "hdf5_read": False,
            "bi4_decode": False,
            "solver_launch": False,
        },
    }


def build_snapshot(request_paths: Iterable[Path], output_path: Path) -> dict[str, Any]:
    paths = [Path(path).resolve() for path in request_paths]
    if not paths:
        raise ValueError("at least one observer request is required")
    if len(set(paths)) != len(paths):
        raise ValueError("observer requests must be unique")
    if output_path.exists():
        raise FileExistsError(f"refuse to overwrite immutable snapshot: {output_path}")
    entries = [request_snapshot(path) for path in paths]
    all_files = [item for entry in entries for item in entry["selected_native_files"]]
    if len({item["path"] for item in all_files}) != len(all_files):
        raise ValueError("two observer requests bind the same selected native file")
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "PASS_SELECTED_NATIVE_SOURCE_HASHED",
        "worker_scope": {
            "selected_native_bi4_only": True,
            "selected_request_count": len(entries),
            "selected_file_count": len(all_files),
            "full_raw_tree_hash": "NOT_COMPUTED_BY_WORKER",
            "full_raw_tree_scan": "FORBIDDEN",
            "hdf5_read": False,
            "bi4_decode": False,
            "solver_launch": False,
        },
        "requests": entries,
        "immutable_source_sha_list": [
            {"frame": item["frame"], "path": item["path"], "bytes": item["bytes"], "sha256": item["sha256"]}
            for item in all_files
        ],
        "selected_native_total_bytes": sum(item["bytes"] for item in all_files),
        "source_sha_list_digest": canonical_digest([
            {"frame": item["frame"], "path": item["path"], "bytes": item["bytes"], "sha256": item["sha256"]}
            for item in all_files
        ]),
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    temporary = output_path.with_name(output_path.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_bytes(encoded)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, output_path)
    finally:
        temporary.unlink(missing_ok=True)
    return result


def self_test() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ds02-native-source-snapshot-") as root_text:
        root = Path(root_text) / "data"
        root.mkdir()
        for frame in (0, 10):
            (root / f"Part_{frame:04d}.bi4").write_bytes(f"frame-{frame}".encode())
        request_path = Path(root_text) / "observer.json"
        request_path.write_text(json.dumps({
            "schema": "ds02.request.v1",
            "case_id": "SELFTEST",
            "sentinel_id": "F1-S1",
            "family_id": "F1",
            "physical_case_id": "SELFTEST",
            "selected_native_frame_ids": [0, 10],
            "command": ["python", "worker", "--raw-root", str(root)],
            "deferred_input_files": [str(root), str(root / "Part_0000.bi4"), str(root / "Part_0010.bi4")],
        }, indent=2))
        output = Path(root_text) / "snapshot.json"
        result = build_snapshot([request_path], output)
        assert result["status"] == "PASS_SELECTED_NATIVE_SOURCE_HASHED"
        assert result["worker_scope"]["selected_file_count"] == 2
        try:
            bad = json.loads(request_path.read_text())
            bad["selected_native_frame_ids"] = [0, 11]
            bad_path = Path(root_text) / "bad.json"
            bad_path.write_text(json.dumps(bad))
            build_snapshot([bad_path], Path(root_text) / "bad-output.json")
        except FileNotFoundError:
            missing_rejected = True
        else:
            missing_rejected = False
        assert missing_rejected
        return {"status": "PASS", "positive_files": 2, "missing_frame_rejected": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observer-request", action="append", type=Path, default=[])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2))
        return 0
    if not args.observer_request or args.output is None:
        parser.error("--observer-request and --output are required unless --self-test is used")
    result = build_snapshot(args.observer_request, args.output)
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve()), "selected_native_total_bytes": result["selected_native_total_bytes"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
