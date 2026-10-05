#!/usr/bin/env python3
"""Check every Root237 child-audit input without opening science arrays.

The manifest is produced by the fresh089 binder.  JSON, XML, Python and the
small solver-policy files are digest-checked.  Producer-owned ``.bi4`` files
are only checked with ``stat`` and their registered producer digest; this
worker never opens or hashes them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ARRAY_SUFFIXES = {".bi4", ".h5", ".vtk", ".csv"}
HEX64 = set("0123456789abcdef")
REQUIRED_ROLES = {
    "canonical_owner",
    "metadata",
    "source_definition",
    "source_plan",
    "source_build_receipt",
    "registered_root_index",
    "actual_gencase_binding",
    "actual_gencase_receipt",
    "actual_prepared_input_report",
    "generated_xml",
    "generated_bi4",
    "qa_execution_receipt",
    "qa_index",
    "qa_binding",
    "qa_case_report",
    "qa_case_metadata",
    "source_qa_worker",
    "official_audit",
    "native_label_decoder",
    "root237_worker",
    "root237_contract_repair",
    "root236_worker",
    "root236_child_preflight",
    "f2_mass_audit",
    "safe_bi4_decoder",
    "root230_entry",
    "root230_home_policy",
    "root230_gpu_policy",
    "root230_contract",
    "runtime",
    "strict_dispatch",
    "resource_window",
    "solver_binary",
}


def digest(path: Path) -> str:
    if path.suffix.lower() in ARRAY_SUFFIXES:
        raise ValueError(f"array digest is forbidden in this worker: {path}")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    if path.suffix.lower() in ARRAY_SUFFIXES:
        raise ValueError(f"array cannot be parsed as metadata: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def valid_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= HEX64


def check_manifest(manifest_path: Path, *, allow_missing_future: bool = False) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    if manifest.get("schema") != "ds02.f4.root237-child-audit-input-manifest.v1":
        raise ValueError("unexpected child manifest schema")
    case_id = manifest.get("case_id")
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("child manifest has no case identity")
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise ValueError("child manifest entries must be a list")
    by_role: dict[str, dict[str, Any]] = {}
    observations: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("child manifest entry is not an object")
        role = entry.get("role")
        raw_path = entry.get("path")
        if not isinstance(role, str) or not isinstance(raw_path, str):
            raise ValueError("child manifest entry lacks role/path")
        if role in by_role:
            raise ValueError(f"duplicate child manifest role: {role}")
        path = Path(raw_path)
        by_role[role] = entry
        array = path.suffix.lower() in ARRAY_SUFFIXES
        expected = entry.get("expected_sha256")
        producer = entry.get("producer_sha256")
        if array:
            if expected is not None:
                raise ValueError(f"scientific array has a source-computed digest: {path}")
            if not valid_sha(producer):
                raise ValueError(f"scientific array lacks a producer digest: {path}")
        elif expected is not None and not valid_sha(expected):
            raise ValueError(f"invalid expected digest for {path}")
        if not path.exists():
            if allow_missing_future and entry.get("future") is True:
                observations.append({
                    "role": role,
                    "path": str(path),
                    "exists": False,
                    "future": True,
                    "read_by_source": False,
                })
                continue
            raise FileNotFoundError(path)
        if not path.is_file():
            raise ValueError(f"child input is not a file: {path}")
        if array:
            size = path.stat().st_size
            if size <= 0:
                raise ValueError(f"producer array is empty: {path}")
            observations.append({
                "role": role,
                "path": str(path),
                "exists": True,
                "size_bytes_from_stat": size,
                "producer_sha256": producer,
                "read_by_source": False,
                "read_policy": "stat_only_producer_digest_no_open_no_rehash",
            })
            continue
        observed = digest(path)
        if expected is not None and observed != expected:
            raise ValueError(f"digest mismatch for {role}: {path}")
        observations.append({
            "role": role,
            "path": str(path),
            "exists": True,
            "sha256": observed,
            "read_by_source": False,
        })
    missing_roles = REQUIRED_ROLES - set(by_role)
    if missing_roles:
        raise ValueError("child manifest lacks roles: " + ", ".join(sorted(missing_roles)))
    if any(entry.get("read_by_source") is True for entry in entries):
        raise ValueError("manifest claims source array access")
    return {
        "schema": "ds02.f4.root237-child-audit-input-preflight.v1",
        "status": "completed",
        "case_id": case_id,
        "entry_count": len(entries),
        "required_roles": sorted(REQUIRED_ROLES),
        "observations": observations,
        "arrays_read_by_source": False,
        "array_policy": "BI4/other scientific payloads are stat-only with producer digest; no source open or rehash",
        "jobs_started_by_source": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--allow-missing-future", action="store_true")
    args = parser.parse_args()
    result = check_manifest(args.manifest, allow_missing_future=args.allow_missing_future)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("schema", "status", "case_id", "entry_count", "arrays_read_by_source")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
