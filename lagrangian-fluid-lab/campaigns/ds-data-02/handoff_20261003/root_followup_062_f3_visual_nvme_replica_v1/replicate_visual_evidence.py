#!/usr/bin/env python3
"""Root-only byte-preserving replica worker for the F3 visual evidence scope.

The worker discovers bindings from the selected Root113 case decisions, but it
only copies/hash-verifies eligible large H5/GIF/native blob artifacts.  It
never decodes a particle file, opens an H5 dataset, starts a solver, changes a
source path, or publishes a derived decision.  Every publication is a
same-directory temporary file followed by an atomic rename after the streamed
digest equals the frozen expected digest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping


DEFAULT_SCOPE = "F3_STAGE1_FIRST24_AY0250_AY0750_VISUAL_V1"
DEFAULT_CACHE_ROOT = Path("/tmp/ds02-visual-evidence-cache")
DEFAULT_MIN_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_CACHE_BYTES = 24 * 1024**3
DEFAULT_MIN_FREE_BYTES = 100 * 1024**3
MAX_JSON_BYTES = 64 * 1024 * 1024
LARGE_SUFFIXES = {
    ".h5",
    ".hdf5",
    ".gif",
    ".bi4",
    ".bin",
    ".dat",
    ".raw",
    ".blob",
    ".vtk",
    ".vtu",
}


class ReplicaError(RuntimeError):
    pass


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReplicaError(f"cannot load JSON metadata: {path}") from exc


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stat_record(path: Path) -> dict[str, Any]:
    st = path.stat()
    return {
        "size_bytes": int(st.st_size),
        "mtime_ns": int(st.st_mtime_ns),
        "inode": int(st.st_ino),
        "device": int(st.st_dev),
        "mode": int(stat.S_IMODE(st.st_mode)),
    }


def stat_unchanged(before: Mapping[str, Any], after: Mapping[str, Any]) -> bool:
    return all(before.get(key) == after.get(key) for key in ("size_bytes", "mtime_ns", "inode", "device", "mode"))


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial-{os.getpid()}-{uuid.uuid4().hex}")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            directory_fd = os.open(path.parent, os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        if temporary.exists():
            temporary.unlink()


def require_absolute(path_value: str, label: str) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        raise ReplicaError(f"{label} must be absolute: {path_value}")
    return path


def collect_binding_pairs(value: Any, trail: str = "") -> Iterable[tuple[str, str, str]]:
    if isinstance(value, Mapping):
        path_value = value.get("path")
        sha_value = value.get("sha256")
        if isinstance(path_value, str) and isinstance(sha_value, str):
            yield path_value, sha_value, trail or "/"
        for key, child in value.items():
            yield from collect_binding_pairs(child, f"{trail}/{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from collect_binding_pairs(child, f"{trail}/{index}")


def discover_scope(candidate_index: Path, scope_id: str) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    candidate = load_json(candidate_index)
    scopes = candidate.get("scopes")
    if not isinstance(scopes, list):
        raise ReplicaError("candidate-index has no scopes list")
    matches = [scope for scope in scopes if isinstance(scope, Mapping) and scope.get("scope_id") == scope_id]
    if len(matches) != 1:
        raise ReplicaError(f"candidate-index must have one scope {scope_id}")
    scope = dict(matches[0])
    observed = scope.get("visual_evidence", {}).get("observed", [])
    if not isinstance(observed, list) or len(observed) != 3:
        raise ReplicaError("Root113 F3 scope must have exactly three observed visual entries")
    records: dict[tuple[str, str], dict[str, Any]] = {}
    queued_json: list[tuple[Path, str, str]] = []
    visited_json: set[Path] = set()

    def add_pair(path_value: str, expected: str, trail: str, case_id: str, source_kind: str, queue: bool = True) -> None:
        source = require_absolute(path_value, f"binding {trail}")
        if len(expected) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in expected):
            raise ReplicaError(f"binding has invalid SHA-256 at {trail}: {expected!r}")
        key = (str(source), expected.lower())
        record = records.setdefault(
            key,
            {
                "source_absolute_path": str(source),
                "expected_sha256": expected.lower(),
                "binding_locations": [],
                "case_ids": [],
                "source_kinds": [],
            },
        )
        record["binding_locations"].append(trail)
        if case_id not in record["case_ids"]:
            record["case_ids"].append(case_id)
        if source_kind not in record["source_kinds"]:
            record["source_kinds"].append(source_kind)
        if queue and source.suffix.lower() == ".json" and source not in visited_json:
            if source.stat().st_size > MAX_JSON_BYTES:
                raise ReplicaError(f"JSON binding exceeds safe recursive metadata limit: {source}")
            queued_json.append((source, case_id, source_kind))

    for observed_entry in observed:
        if not isinstance(observed_entry, Mapping):
            raise ReplicaError("observed visual entry is not an object")
        case_id = str(observed_entry.get("case_id", ""))
        if not case_id:
            raise ReplicaError("observed visual entry has no case_id")
        for name in ("decision", "integrity_report", "full_saved_animation"):
            reference = observed_entry.get(name)
            if not isinstance(reference, Mapping):
                raise ReplicaError(f"{case_id} has no {name} binding")
            add_pair(str(reference["path"]), str(reference["sha256"]), f"/visual_evidence/observed/{case_id}/{name}", case_id, f"scope.{name}")

    while queued_json:
        json_path, case_id, source_kind = queued_json.pop()
        if json_path in visited_json:
            continue
        visited_json.add(json_path)
        document = load_json(json_path)
        for path_value, expected, trail in collect_binding_pairs(document):
            add_pair(path_value, expected, f"{json_path}{trail}", case_id, f"nested:{source_kind}")

    return scope, list(records.values()), sha256_file(candidate_index)


def cache_usage(root: Path) -> int:
    if not root.exists():
        return 0
    total = 0
    for path in root.rglob("*"):
        try:
            if path.is_file() and not path.is_symlink():
                total += int(path.stat().st_size)
        except FileNotFoundError:
            continue
    return total


def disk_snapshot(path: Path) -> dict[str, int]:
    usage = shutil.disk_usage(path)
    return {"total_bytes": int(usage.total), "used_bytes": int(usage.used), "free_bytes": int(usage.free)}


def eligible(path: Path, size: int, minimum: int) -> tuple[bool, str]:
    suffix = path.suffix.lower()
    if suffix not in LARGE_SUFFIXES:
        return False, "suffix_not_H5_GIF_or_native_blob"
    if size < minimum:
        return False, "below_64MiB_threshold"
    return True, "large_visual_artifact"


def cache_name(expected_sha: str, source: Path) -> str:
    suffix = source.suffix.lower()
    if not suffix or len(suffix) > 16 or any(ch not in ".abcdefghijklmnopqrstuvwxyz0123456789_-" for ch in suffix):
        suffix = ".blob"
    return f"{expected_sha}{suffix}"


def copy_one(source: Path, expected_sha: str, cache_path: Path, root: Path, current_usage: int, max_bytes: int, min_free: int) -> tuple[dict[str, Any], int]:
    if not source.is_file() or source.is_symlink():
        raise ReplicaError(f"source is not a regular non-symlink file: {source}")
    before = stat_record(source)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists():
        if cache_path.is_symlink() or not cache_path.is_file():
            raise ReplicaError(f"existing cache target is not a regular file: {cache_path}")
        cache_stat = stat_record(cache_path)
        if cache_stat["size_bytes"] != before["size_bytes"] or sha256_file(cache_path) != expected_sha:
            raise ReplicaError(f"existing cache target failed digest/size validation: {cache_path}")
        after = stat_record(source)
        if not stat_unchanged(before, after):
            raise ReplicaError(f"source stat changed while validating existing cache: {source}")
        return {
            "source_stat_before": before,
            "source_stat_after": after,
            "source_stat_unchanged": True,
            "hash_verified": True,
            "copy_status": "existing_cache_revalidated",
            "cache_absolute_path": str(cache_path),
            "cache_sha256_actual": expected_sha,
            "cache_actual": True,
            "cache_stat_after": cache_stat,
        }, 0
    if disk_snapshot(root.parent)["free_bytes"] < min_free + before["size_bytes"]:
        raise ReplicaError(f"free-space floor would be violated before {source}")
    if before["size_bytes"] + current_usage > max_bytes:
        raise ReplicaError(f"cache peak exceeds {max_bytes} bytes before {source}")
    temporary = cache_path.with_name(f".{cache_path.name}.partial-{os.getpid()}-{uuid.uuid4().hex}")
    digest = hashlib.sha256()
    copied = 0
    try:
        with source.open("rb") as source_handle, temporary.open("wb") as destination:
            for block in iter(lambda: source_handle.read(8 * 1024 * 1024), b""):
                digest.update(block)
                destination.write(block)
                copied += len(block)
            destination.flush()
            os.fsync(destination.fileno())
        after = stat_record(source)
        actual = digest.hexdigest()
        if not stat_unchanged(before, after):
            raise ReplicaError(f"source stat changed during copy: {source}")
        if actual != expected_sha:
            raise ReplicaError(f"source digest mismatch: {source}: {actual} != {expected_sha}")
        if copied != before["size_bytes"]:
            raise ReplicaError(f"source byte count changed during copy: {source}")
        os.replace(temporary, cache_path)
        try:
            directory_fd = os.open(cache_path.parent, os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
        cache_stat = stat_record(cache_path)
        if cache_stat["size_bytes"] != copied:
            raise ReplicaError(f"published cache size mismatch: {cache_path}")
        if disk_snapshot(root.parent)["free_bytes"] < min_free:
            raise ReplicaError("free-space floor was violated after publish")
        return {
            "source_stat_before": before,
            "source_stat_after": after,
            "source_stat_unchanged": True,
            "hash_verified": True,
            "copy_status": "published_atomically",
            "cache_absolute_path": str(cache_path),
            "cache_sha256_actual": actual,
            "cache_actual": True,
            "cache_stat_after": cache_stat,
        }, copied
    finally:
        if temporary.exists():
            temporary.unlink()


def execute(args: argparse.Namespace) -> dict[str, Any]:
    candidate_index = require_absolute(args.candidate_index, "candidate-index")
    cache_root = require_absolute(args.cache_root, "cache-root")
    receipt_path = require_absolute(args.receipt, "receipt")
    scope, discovered, candidate_index_sha = discover_scope(candidate_index, args.scope_id)
    observed = scope["visual_evidence"]["observed"]
    if cache_root.exists() and cache_root.is_symlink():
        raise ReplicaError(f"cache root must not be a symlink: {cache_root}")
    cache_root.mkdir(parents=True, exist_ok=True)
    initial_disk = disk_snapshot(cache_root.parent)
    initial_usage = cache_usage(cache_root)
    if initial_usage > args.max_cache_bytes:
        raise ReplicaError(f"existing cache already exceeds peak limit: {initial_usage}")
    if initial_disk["free_bytes"] < args.min_free_bytes:
        raise ReplicaError(f"free-space floor is unavailable: {initial_disk['free_bytes']}")
    # The frozen cache contract is /tmp/ds02-visual-evidence-cache/SHA.ext.
    cache_artifacts = cache_root
    current_usage = initial_usage
    unique_results: dict[tuple[str, str], dict[str, Any]] = {}
    for item in discovered:
        source = Path(item["source_absolute_path"])
        if not source.exists() or not source.is_file():
            raise ReplicaError(f"source evidence file is missing: {source}")
        source_stat = stat_record(source)
        is_selected, reason = eligible(source, source_stat["size_bytes"], args.min_artifact_bytes)
        item["source_suffix"] = source.suffix.lower()
        item["source_size_bytes"] = source_stat["size_bytes"]
        item["selected_for_cache"] = is_selected
        item["selection_reason"] = reason
        if not is_selected:
            after = stat_record(source)
            source_hash_verified = False
            if source.suffix.lower() == ".json":
                actual_source_sha = sha256_file(source)
                if actual_source_sha != item["expected_sha256"]:
                    raise ReplicaError(f"JSON source digest mismatch: {source}: {actual_source_sha} != {item['expected_sha256']}")
                source_hash_verified = True
            item.update(
                {
                    "source_stat_before": source_stat,
                    "source_stat_after": after,
                    "source_stat_unchanged": stat_unchanged(source_stat, after),
                    "source_hash_verified": source_hash_verified,
                    "cache_absolute_path": None,
                    "cache_actual": False,
                    "copy_status": "not_selected",
                }
            )
            if not item["source_stat_unchanged"]:
                raise ReplicaError(f"source stat changed while inspecting metadata: {source}")
            continue
        key = (item["expected_sha256"], source.suffix.lower())
        if key not in unique_results:
            cache_path = cache_artifacts / cache_name(item["expected_sha256"], source)
            proof, added = copy_one(source, item["expected_sha256"], cache_path, cache_root, current_usage, args.max_cache_bytes, args.min_free_bytes)
            current_usage += added
            unique_results[key] = {**proof, "cache_key": f"{key[0]}|{key[1]}"}
        proof = unique_results[key]
        item.update(proof)
        item["source_hash_verified"] = True
    final_disk = disk_snapshot(cache_root.parent)
    if current_usage > args.max_cache_bytes or final_disk["free_bytes"] < args.min_free_bytes:
        raise ReplicaError("final cache capacity policy failed")
    return {
        "schema": "ds02.f3.visual-nvme-replica-receipt.v1",
        "status": "completed",
        "returncode": 0,
        "scope_id": args.scope_id,
        "family_id": "F3",
        "candidate_index": {
            "source_absolute_path": str(candidate_index),
            "source_sha256": candidate_index_sha,
        },
        "observed_cases": [
            {
                "case_id": entry["case_id"],
                "decision_source_absolute_path": entry["decision"]["path"],
                "decision_expected_sha256": entry["decision"]["sha256"],
                "status": entry["status"],
            }
            for entry in observed
        ],
        "cache_policy": {
            "root": str(cache_root),
            "min_artifact_bytes": args.min_artifact_bytes,
            "max_cache_bytes": args.max_cache_bytes,
            "min_free_bytes": args.min_free_bytes,
            "atomic_publish": True,
            "source_stat_before_after_required": True,
            "existing_cache_rehash_required": True,
        },
        "disk": {"before": initial_disk, "after": final_disk, "cache_regular_file_bytes_after": current_usage},
        "artifacts": discovered,
        "large_artifact_count": sum(1 for item in discovered if item["selected_for_cache"]),
        "large_artifact_bytes": sum(int(item["source_size_bytes"]) for item in discovered if item["selected_for_cache"]),
        "independent_physical_case_count_increment": 0,
        "q_n": "not_granted",
        "q_e": "not_assessed",
        "production_approval": "none",
        "raw_arrays_read": False,
        "h5_datasets_decoded": False,
        "source_files_modified": False,
        "derived_decisions_published": False,
        "failure_policy": "On any mismatch, retain a failed receipt and do not publish derived decisions or alter original evidence.",
        "worker": {"path": str(Path(__file__).resolve()), "sha256": sha256_file(Path(__file__))},
        "completed_at_unix": time.time(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-index", required=True)
    parser.add_argument("--scope-id", default=DEFAULT_SCOPE)
    parser.add_argument("--cache-root", default=str(DEFAULT_CACHE_ROOT))
    parser.add_argument("--receipt", default=str(DEFAULT_CACHE_ROOT / "receipts" / "F3_STAGE1_FIRST24_AY0250_AY0750.replica-receipt.json"))
    parser.add_argument("--min-artifact-bytes", type=int, default=DEFAULT_MIN_BYTES)
    parser.add_argument("--max-cache-bytes", type=int, default=DEFAULT_MAX_CACHE_BYTES)
    parser.add_argument("--min-free-bytes", type=int, default=DEFAULT_MIN_FREE_BYTES)
    args = parser.parse_args()
    try:
        result = execute(args)
        atomic_json(Path(args.receipt), result)
        print(json.dumps({"status": result["status"], "receipt": str(Path(args.receipt).resolve()), "large_artifact_count": result["large_artifact_count"], "large_artifact_bytes": result["large_artifact_bytes"]}, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:  # preserve an auditable failure receipt for Root
        failure = {
            "schema": "ds02.f3.visual-nvme-replica-receipt.v1",
            "status": "failed",
            "returncode": 1,
            "scope_id": getattr(args, "scope_id", DEFAULT_SCOPE),
            "failure": {"type": type(exc).__name__, "message": str(exc)},
            "source_files_modified": False,
            "derived_decisions_published": False,
            "independent_physical_case_count_increment": 0,
            "q_n": "not_granted",
            "production_approval": "none",
            "raw_arrays_read": False,
            "h5_datasets_decoded": False,
            "worker": {"path": str(Path(__file__).resolve())},
            "failed_at_unix": time.time(),
        }
        try:
            atomic_json(Path(args.receipt), failure)
        except Exception as receipt_error:
            print(f"could not write failure receipt: {receipt_error}", file=sys.stderr)
        print(json.dumps(failure, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
