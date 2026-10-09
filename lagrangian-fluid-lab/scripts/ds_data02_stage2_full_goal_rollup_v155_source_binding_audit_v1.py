#!/usr/bin/env python3
"""Audit every static input binding of the unconsumed v155 rollup request.

The v155 request is immutable evidence.  This forward-only audit opens that
request and its JSON manifest, hashes every path listed by the request, and
reports whether the request still binds the current worker byte-for-byte.  It
does not run the rollup and does not treat a stale request as a science
failure.  A stale worker hash requires a new request with the current worker
hash; the old request remains preserved.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.full-goal-rollup-v155.source-binding-audit.v1"
MANIFEST_SCHEMA = "ds02.stage2.full-goal-rollup.manifest.v1"
REQUEST_SCHEMA = "ds02.request.v1"
FORBIDDEN_PAYLOAD_SUFFIXES = {".h5", ".hdf5", ".hdf", ".bi4", ".obi4", ".vtk", ".bi2", ".bi1"}


class BindingError(ValueError):
    """Raised when the binding audit contract is malformed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise BindingError(f"missing static input: {path}")
    stat = path.stat()
    return {
        "path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns, "st_dev": stat.st_dev, "st_ino": stat.st_ino,
        "sha256": sha256_file(path),
    }


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BindingError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise BindingError(f"{label} must be an object: {path}")
    return value


def expect(actual: Any, wanted: Any, label: str) -> None:
    if actual != wanted:
        raise BindingError(f"{label}: expected {wanted!r}, got {actual!r}")


def audit(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    manifest_path = manifest_path.expanduser().resolve()
    manifest = read_json(manifest_path, "binding manifest")
    expect(manifest.get("schema"), SCHEMA.replace(".source-binding-audit.v1", ".manifest.v1"), "binding manifest schema")
    old_request_path = Path(str(manifest.get("old_request_path", ""))).expanduser().resolve()
    expected_old_request_sha = str(manifest.get("old_request_sha256", ""))
    old_request_record = record(old_request_path)
    expect(old_request_record["sha256"], expected_old_request_sha, "old request SHA")
    old_request = read_json(old_request_path, "old v155 request")
    expect(old_request.get("schema"), REQUEST_SCHEMA, "old request schema")
    expect(old_request.get("case_id"), "DS02_STAGE2_FULL_GOAL_ROLLUP_V155", "old request case")
    command = old_request.get("command")
    if not isinstance(command, list) or len(command) < 4:
        raise BindingError("old request command is incomplete")
    worker_path = Path(str(command[1])).expanduser().resolve()
    manifest_from_command = Path(str(command[3])).expanduser().resolve()
    old_manifest_path = Path(str(manifest.get("old_manifest_path", ""))).expanduser().resolve()
    expect(manifest_from_command, old_manifest_path, "old command manifest path")
    manifest_record = record(old_manifest_path)
    old_expected_manifest_sha = old_request.get("input_sha256", {}).get(str(old_manifest_path))
    manifest_binding = {
        "path": str(manifest_path),
        "request_expected_sha256": old_expected_manifest_sha,
        "actual_sha256": manifest_record["sha256"],
        "matches": old_expected_manifest_sha == manifest_record["sha256"],
        "record": manifest_record,
    }
    input_files = old_request.get("input_files")
    input_hashes = old_request.get("input_sha256")
    if not isinstance(input_files, list) or not isinstance(input_hashes, dict):
        raise BindingError("old request lacks input file/hash lists")
    if len(input_files) != len(set(input_files)):
        raise BindingError("old request input_files contains duplicate paths")
    expected_input_paths = {str(Path(str(path)).expanduser().resolve()) for path in input_files}
    if set(input_hashes) != expected_input_paths:
        raise BindingError("old request input_files and input_sha256 path sets differ")
    checks: list[dict[str, Any]] = []
    for raw_path in input_files:
        path = Path(str(raw_path)).expanduser().resolve()
        suffix = path.suffix.lower()
        if suffix in FORBIDDEN_PAYLOAD_SUFFIXES:
            raise BindingError(f"old request unexpectedly references native payload: {path}")
        actual = record(path)
        expected = str(input_hashes[str(path)])
        checks.append({
            "path": str(path),
            "expected_sha256": expected,
            "actual_sha256": actual["sha256"],
            "matches": expected == actual["sha256"],
            "bytes": actual["bytes"],
            "suffix": suffix,
        })
    mismatches = [row for row in checks if not row["matches"]]
    worker_check = next((row for row in checks if Path(row["path"]).resolve() == worker_path), None)
    if worker_check is None:
        raise BindingError("worker is absent from old request input_files")
    old_manifest = read_json(old_manifest_path, "old v155 manifest")
    source_refs = old_manifest.get("source_refs")
    if not isinstance(source_refs, list) or not source_refs:
        raise BindingError("v155 manifest source_refs is empty")
    manifest_refs: list[dict[str, Any]] = []
    for ref in source_refs:
        if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
            raise BindingError("malformed v155 source reference")
        path = Path(ref["path"]).expanduser().resolve()
        actual = record(path)
        expected = str(ref.get("sha256", ""))
        manifest_refs.append({
            "key": ref.get("key"), "path": str(path), "expected_sha256": expected,
            "actual_sha256": actual["sha256"], "matches": expected == actual["sha256"],
            "bytes": actual["bytes"],
        })
    manifest_mismatches = [row for row in manifest_refs if not row["matches"]]
    return {
        "schema": SCHEMA,
        "status": "STALE_OLD_REQUEST_WORKER_BINDING" if not worker_check["matches"] else ("SOURCE_BINDING_AUDIT_PASS" if not mismatches and not manifest_mismatches else "SOURCE_BINDING_AUDIT_MISMATCH"),
        "old_request": old_request_record,
        "old_request_case": old_request.get("case_id"),
        "old_request_attempt": old_request.get("attempt_id"),
        "worker_binding": {
            "path": str(worker_path),
            "request_expected_sha256": worker_check["expected_sha256"],
            "current_sha256": worker_check["actual_sha256"],
            "matches": worker_check["matches"],
            "forward_request_required": not worker_check["matches"],
        },
        "manifest_binding": manifest_binding,
        "input_audit": {
            "request_input_count": len(checks),
            "request_input_matches": len(checks) - len(mismatches),
            "request_input_mismatches": mismatches,
            "manifest_source_ref_count": len(manifest_refs),
            "manifest_source_ref_matches": len(manifest_refs) - len(manifest_mismatches),
            "manifest_source_ref_mismatches": manifest_mismatches,
            "all_referenced_inputs_are_json_or_python": all(row["suffix"] in {".json", ".py"} for row in checks),
        },
        "forward_contract": {
            "old_request_bytes_immutable": True,
            "new_request_must_bind_current_worker_sha256": worker_check["actual_sha256"],
            "new_request_must_retain_manifest_sha256": manifest_record["sha256"],
            "all_other_input_hashes_must_be_rechecked": True,
            "rollup_result_not_run_by_this_audit": True,
        },
        "read_policy": {
            "json_python_static_inputs_only": True,
            "h5_opened": False, "bi4_opened": False, "obi4_opened": False,
            "vtk_opened": False, "solver_started": False,
            "old_request_modified": False, "old_manifest_modified": False,
        },
    }


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise BindingError(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        atomic_json(args.output, audit(args.manifest, args.output))
    except BindingError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
