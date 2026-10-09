#!/usr/bin/env python3
"""Sequential guarded worker for a bounded group of V4 lifecycle audits.

The batch manifest contains only small source metadata and per-case V4
manifests.  The trajectory HDF5 paths remain deferred inputs.  After the
shared runner has reserved the request, this worker calls the V4 audit for one
case at a time; V4 performs that case's pre-hash, stream, and post-hash.  Each
case has independent atomic outputs and a receipt, so a malformed later case
preserves earlier evidence and the failure itself rather than rewriting the
batch history.

This worker is a diagnostic transport for saved typed lifecycle fields.  It
does not grant QI/QN/QE, native exit causes, physical fate, flux, or dynamics
credit.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
import time
import traceback
from typing import Any

import ds_data02_stage2_typed_lifecycle_sidecar_v4 as lifecycle

SCRIPT = Path(__file__).resolve()
BATCH_SCHEMA = "ds02.stage2.typed-lifecycle-batch.v1"
BATCH_SUMMARY_SCHEMA = "ds02.stage2.typed-lifecycle-batch-summary.v1"
MAX_SUMMARY_BYTES = 2 * 1024 * 1024
H5_SUFFIXES = {".h5", ".hdf5"}


class BatchError(ValueError):
    """Raised when the immutable batch source contract is not closed."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise BatchError(f"{label} must be a SHA-256 digest")
    value = value.lower()
    if any(char not in "0123456789abcdef" for char in value):
        raise BatchError(f"{label} is not hexadecimal")
    return value


def _file(value: Any, label: str, *, allow_h5: bool = False) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not value:
        raise BatchError(f"{label} lacks a path")
    path = Path(value).expanduser().resolve()
    if not allow_h5 and path.suffix.lower() in H5_SUFFIXES:
        raise BatchError(f"{label} must remain a deferred HDF5 input")
    if not path.is_file():
        raise BatchError(f"{label} is missing: {path}")
    return path


def _json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BatchError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise BatchError(f"{label} must be a JSON object")
    return value


def _atomic_json(path: Path, value: dict[str, Any], *, max_bytes: int = MAX_SUMMARY_BYTES) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise BatchError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size > max_bytes:
            raise BatchError(f"JSON output exceeds {max_bytes} bytes: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _safe_case_id(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in "._-" else "_" for char in value)
    if not safe or safe in {".", ".."}:
        raise BatchError(f"case id cannot form an output directory: {value!r}")
    return safe


def _validate_input_refs(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    refs = manifest.get("input_refs")
    if not isinstance(refs, list) or not refs:
        raise BatchError("batch manifest input_refs is missing")
    checked: dict[str, dict[str, Any]] = {}
    for ref in refs:
        if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
            raise BatchError("batch input reference is malformed")
        path = _file(ref["path"], str(ref.get("role", "input")))
        expected = _sha(ref.get("sha256"), f"{path} input SHA")
        actual = _sha256_file(path)
        if actual != expected:
            raise BatchError(f"batch input changed: {path}")
        key = str(path)
        if key in checked and checked[key]["sha256"] != expected:
            raise BatchError(f"conflicting input SHA: {path}")
        checked[key] = {**ref, "path": key, "sha256": expected, "bytes": int(path.stat().st_size)}
    return checked


def _load_manifest(path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    path = _file(path, "batch manifest")
    manifest = _json(path, "batch manifest")
    if manifest.get("schema") != BATCH_SCHEMA or manifest.get("status") != "READY_FOR_GUARDED_BATCH":
        raise BatchError("batch manifest is not guarded-ready")
    refs = _validate_input_refs(manifest)
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise BatchError("batch manifest cases are missing")
    seen: set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("physical_case_id"), str):
            raise BatchError("batch case row is malformed")
        case_id = case["physical_case_id"]
        if case_id in seen:
            raise BatchError(f"duplicate batch case: {case_id}")
        seen.add(case_id)
        if case.get("source_join_status") != "EXACT_CURRENT_AUDIT_METADATA_JOIN":
            raise BatchError(f"case is not an exact CURRENT/audit join: {case_id}")
        manifest_path = _file(case.get("case_manifest"), f"{case_id} case manifest")
        declared_sha = _sha(case.get("case_manifest_sha256"), f"{case_id} case manifest SHA")
        if _sha256_file(manifest_path) != declared_sha:
            raise BatchError(f"case manifest changed: {case_id}")
        # The per-case V4 manifest is checked again by lifecycle.audit after
        # the batch has entered the guarded worker.  Do not inspect its HDF5
        # payload here.
        if str(manifest_path) not in refs:
            raise BatchError(f"case manifest is not in the batch input closure: {case_id}")
    return manifest, refs


def _case_receipt(path: Path, case: dict[str, Any], *, status: str, started: float, ended: float, **extra: Any) -> dict[str, Any]:
    return {
        "schema": "ds02.stage2.typed-lifecycle-case-receipt.v1",
        "status": status,
        "physical_case_id": case["physical_case_id"],
        "family_id": case.get("family_id"),
        "case_manifest": case.get("case_manifest"),
        "case_manifest_sha256": case.get("case_manifest_sha256"),
        "started_monotonic_s": started,
        "ended_monotonic_s": ended,
        "wall_seconds": max(0.0, ended - started),
        "source_read_policy": "V4 audit owns deferred H5 pre-hash/stream/post-hash after reservation",
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
        **extra,
    }


def run_batch(manifest_path: Path, output_root: Path, *, chunk: int = 65536) -> dict[str, Any]:
    started = time.monotonic()
    manifest, _refs = _load_manifest(manifest_path)
    output_root = output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    case_results: list[dict[str, Any]] = []
    for case in manifest["cases"]:
        case_id = str(case["physical_case_id"])
        case_started = time.monotonic()
        case_dir = output_root / "cases" / _safe_case_id(case_id)
        case_dir.mkdir(parents=True, exist_ok=True)
        receipt_path = case_dir / "case-execution-receipt.json"
        try:
            case_manifest_path = Path(case["case_manifest"]).expanduser().resolve()
            summary_path = case_dir / "typed-lifecycle-v4-summary.json"
            records_path = case_dir / "typed-lifecycle-v4-records.jsonl"
            result = lifecycle.audit(case_manifest_path, summary_path, records_path, chunk=chunk)
            ended = time.monotonic()
            receipt = _case_receipt(
                receipt_path,
                case,
                status="COMPLETED",
                started=case_started,
                ended=ended,
                output_summary={"path": str(summary_path), "bytes": int(summary_path.stat().st_size), "sha256": _sha256_file(summary_path)},
                output_records={"path": str(records_path), "bytes": int(records_path.stat().st_size), "sha256": _sha256_file(records_path), "rows": result.get("record_count")},
                h5_pre_post_sha256_equal=result.get("h5_pre_post_sha256_equal"),
            )
            _atomic_json(receipt_path, receipt)
            case_results.append({"physical_case_id": case_id, "status": "COMPLETED", "receipt": str(receipt_path), "receipt_sha256": _sha256_file(receipt_path), "record_count": result.get("record_count")})
        except Exception as exc:
            ended = time.monotonic()
            failure = _case_receipt(
                receipt_path,
                case,
                status="FAILED",
                started=case_started,
                ended=ended,
                error_type=type(exc).__name__,
                error_message=str(exc),
                traceback=traceback.format_exc(limit=12),
                output_summary={"path": str(case_dir / "typed-lifecycle-v4-summary.json"), "status": "NOT_WRITTEN_OR_PARTIAL"},
                output_records={"path": str(case_dir / "typed-lifecycle-v4-records.jsonl"), "status": "NOT_WRITTEN_OR_PARTIAL"},
            )
            _atomic_json(receipt_path, failure)
            case_results.append({"physical_case_id": case_id, "status": "FAILED", "receipt": str(receipt_path), "receipt_sha256": _sha256_file(receipt_path), "error_type": type(exc).__name__, "error_message": str(exc)})
        finally:
            # V4 returns no record list, but force a collection boundary before
            # the next H5 so a group does not retain prior Python objects.
            gc.collect()
    counts = {
        "cases_requested": len(case_results),
        "completed": sum(row["status"] == "COMPLETED" for row in case_results),
        "failed": sum(row["status"] == "FAILED" for row in case_results),
    }
    summary = {
        "schema": BATCH_SUMMARY_SCHEMA,
        "status": "COMPLETED_WITH_CASE_RESULTS" if counts["failed"] == 0 else "COMPLETED_WITH_CASE_FAILURES",
        "manifest": {"path": str(Path(manifest_path).expanduser().resolve()), "sha256": _sha256_file(Path(manifest_path).expanduser().resolve())},
        "batch_scope": {"family_id": manifest.get("family_id"), "case_ids": [case["physical_case_id"] for case in manifest["cases"]], "sequential_one_case_at_a_time": True},
        "counts": counts,
        "case_results": case_results,
        "source_read_policy": {"small_json_opened_after_reservation": True, "trajectory_h5_content_opened_by_batch_worker": True, "trajectory_h5_opened_sequentially": True, "native_or_bi4_opened": False, "solver_started": False, "cfd_or_model_started": False},
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "native_exit_cause": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
        "resource_accounting": {"attempt_remaining": "ROOT_OWNED_NOT_COMPUTED_BY_WORKER", "hard_limits": "ROOT_OWNED_NOT_COMPUTED_BY_WORKER", "wall_seconds": time.monotonic() - started},
    }
    summary_path = output_root / "batch-summary.json"
    _atomic_json(summary_path, summary)
    return {"status": summary["status"], "summary": str(summary_path), "summary_sha256": _sha256_file(summary_path), "counts": counts}


def self_test() -> dict[str, Any]:
    return {"status": "PASS", "schema": BATCH_SCHEMA, "sequential_one_case_at_a_time": True, "launch_allowed": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    run = sub.add_parser("run")
    run.add_argument("--manifest", required=True, type=Path)
    run.add_argument("--output-root", required=True, type=Path)
    run.add_argument("--chunk", type=int, default=65536)
    args = parser.parse_args(argv)
    if args.action == "self-test":
        print(json.dumps(self_test(), sort_keys=True))
        return 0
    try:
        result = run_batch(args.manifest, args.output_root, chunk=args.chunk)
    except BatchError as exc:
        raise SystemExit(f"BatchError: {exc}") from exc
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
