#!/usr/bin/env python3
"""Strict CPU audit for a completed Root-only visual replica receipt.

This audit reads the NVMe cache and small JSON metadata only.  It does not
open any original H5/GIF/native source artifact and never changes source files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import shutil
import time
from pathlib import Path
from typing import Any, Mapping


DEFAULT_SCOPE = "F3_STAGE1_FIRST24_AY0250_AY0750_VISUAL_V1"
MAX_CACHE_BYTES = 24 * 1024**3
MIN_FREE_BYTES = 100 * 1024**3


class AuditError(RuntimeError):
    pass


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial-{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def cache_bytes(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            total += path.stat().st_size
    return total


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--candidate-index", required=True)
    parser.add_argument("--scope-id", default=DEFAULT_SCOPE)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result: dict[str, Any] = {
        "schema": "ds02.f3.visual-nvme-replica-strict-cpu-audit.v1",
        "scope_id": args.scope_id,
        "raw_arrays_read": False,
        "h5_datasets_decoded": False,
        "source_files_modified": False,
        "independent_physical_case_count_increment": 0,
        "q_n": "not_granted",
        "production_approval": "none",
    }
    try:
        receipt_path = Path(args.receipt).resolve()
        candidate_path = Path(args.candidate_index).resolve()
        receipt = load(receipt_path)
        if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
            raise AuditError("replica receipt is not completed")
        if receipt.get("scope_id") != args.scope_id:
            raise AuditError("receipt scope mismatch")
        if receipt.get("source_files_modified") is not False or receipt.get("derived_decisions_published") is not False:
            raise AuditError("receipt immutability flags are not clean")
        if receipt.get("independent_physical_case_count_increment") != 0:
            raise AuditError("receipt increments case count")
        candidate = load(candidate_path)
        scopes = candidate.get("scopes", [])
        matches = [scope for scope in scopes if isinstance(scope, Mapping) and scope.get("scope_id") == args.scope_id]
        if len(matches) != 1:
            raise AuditError("candidate-index scope is missing")
        observed = matches[0].get("visual_evidence", {}).get("observed", [])
        observed_ids = sorted(str(entry["case_id"]) for entry in observed)
        receipt_ids = sorted(str(entry["case_id"]) for entry in receipt.get("observed_cases", []))
        if observed_ids != receipt_ids or len(receipt_ids) != 3:
            raise AuditError("observed-case membership changed")
        candidate_sha = sha256_file(candidate_path)
        if receipt.get("candidate_index", {}).get("source_sha256") != candidate_sha:
            raise AuditError("candidate-index digest no longer matches receipt")
        cache_root = Path(str(receipt["cache_policy"]["root"])).resolve()
        if not cache_root.is_dir() or cache_root.is_symlink():
            raise AuditError("cache root is missing or symlinked")
        policy = receipt["cache_policy"]
        if int(policy["max_cache_bytes"]) != MAX_CACHE_BYTES or int(policy["min_free_bytes"]) != MIN_FREE_BYTES:
            raise AuditError("cache policy differs from frozen 24 GiB/100 GiB limits")
        artifacts = receipt.get("artifacts", [])
        if not isinstance(artifacts, list) or not artifacts:
            raise AuditError("receipt has no opaque artifact inventory")
        selected = []
        selected_bytes = 0
        for artifact in artifacts:
            if "path" in artifact or "source_absolute_path" not in artifact:
                raise AuditError("opaque artifact inventory must use source_absolute_path")
            source = Path(str(artifact["source_absolute_path"]))
            if not source.is_absolute():
                raise AuditError("source path is not absolute")
            if artifact.get("source_stat_unchanged") is not True:
                raise AuditError(f"source stat changed: {source}")
            if artifact.get("selected_for_cache"):
                cache_path = Path(str(artifact.get("cache_absolute_path", "")))
                if not cache_path.is_absolute() or not cache_path.is_file() or cache_path.is_symlink():
                    raise AuditError(f"selected artifact has no regular cache file: {source}")
                expected = str(artifact["expected_sha256"]).lower()
                if artifact.get("cache_actual") is not True or artifact.get("cache_sha256_actual") != expected:
                    raise AuditError(f"selected artifact lacks actual cache proof: {source}")
                if cache_path.stat().st_size != int(artifact["source_size_bytes"]):
                    raise AuditError(f"cache size differs from source metadata: {cache_path}")
                actual = sha256_file(cache_path)
                if actual != expected:
                    raise AuditError(f"cache digest mismatch: {cache_path}")
                selected.append(str(cache_path))
                selected_bytes += int(artifact["source_size_bytes"])
            else:
                if artifact.get("cache_actual") is not False or artifact.get("cache_absolute_path") is not None:
                    raise AuditError(f"unselected artifact has a cache claim: {source}")
        used = cache_bytes(cache_root)
        if used > MAX_CACHE_BYTES:
            raise AuditError(f"cache usage exceeds 24 GiB: {used}")
        free = shutil.disk_usage(cache_root.parent).free
        if free < MIN_FREE_BYTES:
            raise AuditError(f"free-space floor is below 100 GiB: {free}")
        if int(receipt.get("large_artifact_count", -1)) != len(selected):
            raise AuditError("large artifact count mismatch")
        if int(receipt.get("large_artifact_bytes", -1)) != selected_bytes:
            raise AuditError("large artifact byte total mismatch")
        result.update(
            {
                "status": "completed",
                "returncode": 0,
                "receipt": {"source_absolute_path": str(receipt_path), "source_sha256": sha256_file(receipt_path)},
                "candidate_index": {"source_absolute_path": str(candidate_path), "source_sha256": candidate_sha},
                "cache_root": str(cache_root),
                "verified_large_cache_files": selected,
                "verified_large_artifact_count": len(selected),
                "verified_large_artifact_bytes": selected_bytes,
                "cache_regular_file_bytes": used,
                "free_bytes_after_audit": free,
                "visual_decisions_unchanged": True,
                "byte_identity_basis": "Each selected cache file was rehashed on NVMe and matched the frozen expected source digest; source stat before/after was unchanged in the Root copy receipt.",
                "completed_at_unix": time.time(),
            }
        )
        atomic_json(Path(args.output), result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        result.update({"status": "failed", "returncode": 1, "failure": {"type": type(exc).__name__, "message": str(exc)}})
        atomic_json(Path(args.output), result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
