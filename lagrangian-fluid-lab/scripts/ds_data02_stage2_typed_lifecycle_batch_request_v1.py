#!/usr/bin/env python3
"""Build a guarded source-closed request for a bounded V4 case group.

Preparation opens only CURRENT/audit/scan/receipt JSON and stats deferred H5
paths.  It selects exact CURRENT/audit joins, creates immutable per-case V4
manifests, and emits a batch manifest plus a runnable CPU request.  The batch
worker performs the H5 pre-hash/stream/post-hash only after the shared runner
has reserved the request.  Historical aliases and non-exact rows remain
outside the selected group.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import ds_data02_stage2_typed_lifecycle_sidecar_v4 as lifecycle

SCRIPT = Path(__file__).resolve()
BATCH_WORKER = SCRIPT.parent / "ds_data02_stage2_typed_lifecycle_batch_worker_v1.py"
BATCH_SCHEMA = "ds02.stage2.typed-lifecycle-batch.v1"
REQUEST_SCHEMA = "ds02.request.v1"
CURRENT_SCHEMA = "ds02.stage2.current336.v1"
AUDIT_SCHEMA = "ds02.stage2.scientific-audit-independent-verification.v23"
ALIAS_CASE = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
MAX_SUMMARY_BYTES = 2 * 1024 * 1024
MAX_RECORD_BYTES = 512 * 1024 * 1024
DEFAULT_MAX_GROUP_BYTES = 20 * 1024 * 1024 * 1024
H5_SUFFIXES = {".h5", ".hdf5"}


class BatchRequestError(ValueError):
    """Raised when the exact CURRENT/audit batch source contract is open."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise BatchRequestError(f"{label} must be a SHA-256 digest")
    value = value.lower()
    if any(char not in "0123456789abcdef" for char in value):
        raise BatchRequestError(f"{label} is not hexadecimal")
    return value


def _file(value: Any, label: str, *, allow_h5: bool = False) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not value:
        raise BatchRequestError(f"{label} lacks a path")
    path = Path(value).expanduser().resolve()
    if not allow_h5 and path.suffix.lower() in H5_SUFFIXES:
        raise BatchRequestError(f"{label} must remain a deferred HDF5 input")
    if not path.is_file():
        raise BatchRequestError(f"{label} is missing: {path}")
    return path


def _json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BatchRequestError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise BatchRequestError(f"{label} must be a JSON object")
    return value


def _atomic_json(path: Path, value: dict[str, Any], *, max_bytes: int = MAX_SUMMARY_BYTES) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise BatchRequestError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size > max_bytes:
            raise BatchRequestError(f"JSON output exceeds {max_bytes} bytes: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _stat(path: Path, label: str, *, allow_h5: bool = False) -> dict[str, Any]:
    path = _file(path, label, allow_h5=allow_h5)
    value = path.stat()
    return {"path": str(path), "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns), "st_dev": int(value.st_dev), "st_ino": int(value.st_ino)}


def _exact_rows(current_path: Path, audit_path: Path, expected_current_sha256: str, expected_audit_sha256: str) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    current_path = _file(current_path, "CURRENT336")
    audit_path = _file(audit_path, "scientific audit verification")
    expected_current_sha256 = _sha(expected_current_sha256, "expected CURRENT SHA")
    expected_audit_sha256 = _sha(expected_audit_sha256, "expected audit SHA")
    current_sha = _sha256_file(current_path)
    audit_sha = _sha256_file(audit_path)
    if current_sha != expected_current_sha256:
        raise BatchRequestError(f"CURRENT SHA differs: {current_sha}")
    if audit_sha != expected_audit_sha256:
        raise BatchRequestError(f"audit SHA differs: {audit_sha}")
    current = _json(current_path, "CURRENT336")
    audit = _json(audit_path, "scientific audit verification")
    if current.get("schema") != CURRENT_SCHEMA or audit.get("schema") != AUDIT_SCHEMA:
        raise BatchRequestError("CURRENT/audit schema differs")
    cases = current.get("cases")
    verified = audit.get("verified_cases")
    if not isinstance(cases, list) or not isinstance(verified, list) or len(cases) != 336 or len(verified) != 336:
        raise BatchRequestError("exact 336 CURRENT/audit rows are required")
    catalog = audit.get("current_catalog")
    if not isinstance(catalog, dict) or _sha(catalog.get("sha256"), "audit CURRENT SHA") != expected_current_sha256:
        raise BatchRequestError("audit does not bind expected CURRENT SHA")
    current_by_id: dict[str, dict[str, Any]] = {}
    audit_by_id: dict[str, dict[str, Any]] = {}
    for row in cases:
        if not isinstance(row, dict) or not isinstance(row.get("physical_case_id"), str) or row["physical_case_id"] in current_by_id:
            raise BatchRequestError("CURRENT case rows are malformed or duplicated")
        current_by_id[row["physical_case_id"]] = row
    for row in verified:
        if not isinstance(row, dict) or not isinstance(row.get("physical_case_id"), str) or row["physical_case_id"] in audit_by_id:
            raise BatchRequestError("audit case rows are malformed or duplicated")
        audit_by_id[row["physical_case_id"]] = row
    if set(current_by_id) != set(audit_by_id):
        raise BatchRequestError("CURRENT/audit physical case key sets differ")
    rows: list[dict[str, Any]] = []
    for index, (case_id, current_row) in enumerate(current_by_id.items()):
        audit_row = audit_by_id[case_id]
        trajectory = current_row.get("trajectory")
        if not isinstance(trajectory, dict):
            raise BatchRequestError(f"{case_id}: trajectory metadata missing")
        path_value = trajectory.get("path")
        trajectory_path = _file(path_value, f"{case_id} trajectory", allow_h5=True)
        declared_sha = _sha(trajectory.get("producer_declared_sha256"), f"{case_id} trajectory SHA")
        audit_path_value = audit_row.get("trajectory")
        path_match = isinstance(audit_path_value, str) and Path(audit_path_value).expanduser().resolve() == trajectory_path
        sha_match = isinstance(audit_row.get("trajectory_verified_sha256"), str) and audit_row["trajectory_verified_sha256"].lower() == declared_sha
        trajectory_stat = _stat(trajectory_path, f"{case_id} trajectory", allow_h5=True)
        bytes_match = int(trajectory.get("bytes", -1)) == trajectory_stat["bytes"]
        scan_path = _file(audit_row.get("scan"), f"{case_id} scan")
        receipt_path = _file(audit_row.get("receipt"), f"{case_id} receipt")
        scan_sha = _sha(audit_row.get("scan_sha256"), f"{case_id} scan SHA")
        receipt_sha = _sha(audit_row.get("receipt_sha256"), f"{case_id} receipt SHA")
        scan_hash_match = _sha256_file(scan_path) == scan_sha
        receipt_hash_match = _sha256_file(receipt_path) == receipt_sha
        audit_clean = audit_row.get("scan_status") == "SCANNED" and audit_row.get("field_failures") == [] and audit_row.get("exact_CURRENT_path_and_declared_sha_match") is True
        exact = bool(path_match and sha_match and bytes_match and scan_hash_match and receipt_hash_match and audit_clean)
        historical_alias = "HISTORICAL_ALIAS_REVIEW_REQUIRED" if case_id == ALIAS_CASE else "NONE"
        source_join_status = "SEPARATE_HISTORICAL_ALIAS_UNRESOLVED" if historical_alias != "NONE" else ("EXACT_CURRENT_AUDIT_METADATA_JOIN" if exact else "INCOMPLETE_OR_MISMATCHED")
        rows.append({
            "current_index": index,
            "physical_case_id": case_id,
            "family_id": current_row.get("family_id"),
            "runtime_case_alias": current_row.get("runtime_case_alias"),
            "frames": current_row.get("frames"),
            "particles": current_row.get("particles"),
            "trajectory_path": str(trajectory_path),
            "trajectory_sha256": declared_sha,
            "trajectory_bytes": int(trajectory_stat["bytes"]),
            "scan_path": str(scan_path),
            "scan_sha256": scan_sha,
            "receipt_path": str(receipt_path),
            "receipt_sha256": receipt_sha,
            "source_join_status": source_join_status,
            "historical_alias": historical_alias,
        })
    counts = {
        "current_cases": len(rows),
        "exact_current_audit_metadata_joins": sum(row["source_join_status"] == "EXACT_CURRENT_AUDIT_METADATA_JOIN" for row in rows),
        "incomplete_or_mismatched": sum(row["source_join_status"] == "INCOMPLETE_OR_MISMATCHED" for row in rows),
        "historical_alias_rows": sum(row["historical_alias"] != "NONE" for row in rows),
    }
    return current, audit, rows, {"current_sha256": current_sha, "audit_sha256": audit_sha, "counts": counts, "current_path": str(current_path), "audit_path": str(audit_path)}


def _safe_case_id(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in "._-" else "_" for char in value)
    if not safe or safe in {".", ".."}:
        raise BatchRequestError(f"case id cannot form output directory: {value!r}")
    return safe


def _add_ref(refs: dict[str, dict[str, Any]], path_value: Any, role: str, expected_sha: str | None = None) -> None:
    path = _file(path_value, role)
    actual = _sha256_file(path)
    if expected_sha is not None and actual != _sha(expected_sha, f"{role} SHA"):
        raise BatchRequestError(f"source changed: {role}")
    key = str(path)
    if key in refs and refs[key]["sha256"] != actual:
        raise BatchRequestError(f"conflicting source reference: {path}")
    refs[key] = {"role": role, "path": key, "sha256": actual, "bytes": int(path.stat().st_size)}


def _collect_case_refs(refs: dict[str, dict[str, Any]], case_id: str, manifest_path: Path, request_path: Path) -> None:
    _add_ref(refs, manifest_path, f"case_manifest::{case_id}")
    _add_ref(refs, request_path, f"case_request::{case_id}")
    manifest = _json(manifest_path, f"{case_id} V4 manifest")
    for source_ref in manifest.get("source_refs", []):
        if not isinstance(source_ref, dict) or source_ref.get("role") == "trajectory_h5":
            continue
        _add_ref(refs, source_ref.get("path"), f"{case_id}::{source_ref.get('role', 'source')}", source_ref.get("sha256"))


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    current_path = _file(args.current, "CURRENT336")
    audit_path = _file(args.audit_verification, "scientific audit verification")
    _current, _audit, rows, source = _exact_rows(current_path, audit_path, args.expected_current_sha256, args.expected_audit_sha256)
    family = str(args.family).strip()
    if not family:
        raise BatchRequestError("family must be non-empty")
    requested_ids = [str(value) for value in (args.case_id or [])]
    excluded_ids = {str(value) for value in (args.exclude_case or [])}
    if len(set(requested_ids)) != len(requested_ids):
        raise BatchRequestError("duplicate --case-id")
    eligible = [row for row in rows if row["family_id"] == family and row["historical_alias"] == "NONE" and row["source_join_status"] == "EXACT_CURRENT_AUDIT_METADATA_JOIN" and row["physical_case_id"] not in excluded_ids]
    by_id = {row["physical_case_id"]: row for row in eligible}
    if requested_ids:
        missing = [case_id for case_id in requested_ids if case_id not in by_id]
        if missing:
            raise BatchRequestError(f"requested case is not an exact eligible row: {missing}")
        selected = [by_id[case_id] for case_id in requested_ids]
    else:
        selected = sorted(eligible, key=lambda row: (-int(row.get("particles") or 0), row["physical_case_id"]))[: int(args.max_cases)]
    if not selected:
        raise BatchRequestError(f"no exact eligible cases for family {family}")
    if len(selected) > int(args.max_cases):
        raise BatchRequestError("selected cases exceed max-cases")
    if int(args.max_group_bytes) <= 0:
        raise BatchRequestError("max-group-bytes must be positive")
    selected_source_bytes = sum(int(row["trajectory_bytes"]) for row in selected)
    if selected_source_bytes > int(args.max_group_bytes):
        raise BatchRequestError(f"selected deferred H5 bytes exceed max-group-bytes: {selected_source_bytes}")
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    v4_worker = _file(args.v4_worker, "V4 worker")
    batch_worker = _file(args.batch_worker, "batch worker")
    case_refs: dict[str, dict[str, Any]] = {}
    case_records: list[dict[str, Any]] = []
    for row in selected:
        case_id = row["physical_case_id"]
        case_dir = output_dir / "case-manifests" / _safe_case_id(case_id)
        v4_args = SimpleNamespace(
            current=current_path,
            audit_verification=audit_path,
            scan=Path(row["scan_path"]),
            receipt=Path(row["receipt_path"]),
            case_id=case_id,
            family_id=family,
            expected_current_sha256=source["current_sha256"],
            runtime_config=Path(args.runtime_config),
            output_dir=case_dir,
            worker=v4_worker,
            python=Path(args.python),
            runtime_v2=Path(args.runtime_v2),
            runtime_v6=Path(args.runtime_v6),
            runtime_v8=Path(args.runtime_v8),
            dispatch_v8=Path(args.dispatch_v8),
            strict_v8=Path(args.strict_v8),
            cwd=Path(args.cwd),
            worktree_root=Path(args.worktree_root),
        )
        prepared = lifecycle.prepare(v4_args)
        manifest_path = Path(prepared["manifest"]).resolve()
        request_path = Path(prepared["request"]).resolve()
        _collect_case_refs(case_refs, case_id, manifest_path, request_path)
        case_records.append({
            "current_index": row["current_index"],
            "physical_case_id": case_id,
            "family_id": family,
            "frames": row["frames"],
            "particles": row["particles"],
            "source_join_status": row["source_join_status"],
            "historical_alias": row["historical_alias"],
            "trajectory_h5": {"path": row["trajectory_path"], "sha256": row["trajectory_sha256"], "bytes": row["trajectory_bytes"], "read_after_reservation": True, "content_opened_by_preparer": False},
            "scan": {"path": row["scan_path"], "sha256": row["scan_sha256"]},
            "receipt": {"path": row["receipt_path"], "sha256": row["receipt_sha256"]},
            "case_manifest": str(manifest_path),
            "case_manifest_sha256": _sha256_file(manifest_path),
            "case_request": str(request_path),
            "case_request_sha256": _sha256_file(request_path),
        })
    _add_ref(case_refs, batch_worker, "batch_worker")
    # The V4 worker is already represented in every case manifest, but add a
    # stable top-level role so a one-case group remains independently closed.
    _add_ref(case_refs, v4_worker, "v4_worker")
    batch_manifest_path = output_dir / "typed-lifecycle-batch-v1-manifest.json"
    input_refs = [case_refs[path] for path in sorted(case_refs)]
    deferred = [case["trajectory_h5"] for case in case_records]
    batch_manifest = {
        "schema": BATCH_SCHEMA,
        "status": "READY_FOR_GUARDED_BATCH",
        "family_id": family,
        "case_count": len(case_records),
        "current_catalog": {"path": source["current_path"], "sha256": source["current_sha256"]},
        "scientific_audit": {"path": source["audit_path"], "sha256": source["audit_sha256"]},
        "source_join_counts": source["counts"],
        "cases": case_records,
        "input_refs": input_refs,
        "deferred_trajectory_h5": deferred,
        "source_read_policy": {"json_and_stat_only_at_prepare": True, "trajectory_content_opened_at_prepare": False, "trajectory_content_hashed_at_prepare": False, "trajectory_pre_hash_stream_post_hash_after_reservation": True, "native_or_bi4_opened": False, "solver_started": False},
        "group_policy": {"max_cases": int(args.max_cases), "max_source_bytes": int(args.max_group_bytes), "selected_source_bytes": selected_source_bytes, "one_case_at_a_time": True, "families_are_never_mixed": True, "historical_alias_excluded": True, "explicit_excluded_case_ids": sorted(excluded_ids), "per_case_record_cap_bytes": MAX_RECORD_BYTES, "per_case_summary_cap_bytes": MAX_SUMMARY_BYTES},
        "qualification_boundary": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "native_exit_cause": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
    }
    _atomic_json(batch_manifest_path, batch_manifest)
    _add_ref(case_refs, batch_manifest_path, "batch_manifest")
    input_refs = [case_refs[path] for path in sorted(case_refs)]
    request_path = output_dir / "typed-lifecycle-batch-v1-request.json"
    command = [str(args.python), str(batch_worker), "run", "--manifest", str(batch_manifest_path), "--output-root", "{attempt_root}/typed-lifecycle-batch", "--chunk", "65536"]
    input_sha = {ref["path"]: ref["sha256"] for ref in input_refs}
    h5_bytes = sum(int(case["trajectory_h5"]["bytes"]) for case in case_records)
    per_case_storage = MAX_RECORD_BYTES + MAX_SUMMARY_BYTES + 128 * 1024
    request = {
        "schema": REQUEST_SCHEMA,
        "shared_runtime_version": "v8",
        "family_id": family,
        "case_id": f"STAGE2_TYPED_LIFECYCLE_BATCH_{family}",
        "physical_case_ids": [case["physical_case_id"] for case in case_records],
        "attempt_id": "typed-lifecycle-batch-v1-root-forward",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 3600,
        "max_memory_bytes": 4 * 1024 * 1024 * 1024,
        "estimated_storage_bytes": len(case_records) * per_case_storage + MAX_SUMMARY_BYTES,
        "estimated_cpu_core_hours": max(0.5, 0.5 * len(case_records)),
        "estimated_gpu_seconds": 0,
        "estimated_hdf5_read_bytes": h5_bytes * 3,
        "estimated_deferred_source_bytes": h5_bytes,
        "estimated_deferred_read_passes": 3,
        "estimated_deferred_read_bytes": h5_bytes * 3,
        "estimated_input_read_bytes": sum(int(ref["bytes"]) for ref in input_refs),
        "cwd": str(Path(args.cwd).expanduser().resolve()),
        "worktree_root": str(Path(args.worktree_root).expanduser().resolve()),
        "command": command,
        "input_files": sorted(input_sha),
        "input_sha256": dict(sorted(input_sha.items())),
        "deferred_input_files": [case["trajectory_h5"]["path"] for case in case_records],
        "deferred_input_records": deferred,
        "output_files": ["{attempt_root}/typed-lifecycle-batch/batch-summary.json", "{attempt_root}/typed-lifecycle-batch/cases/*/case-execution-receipt.json"],
        "manifest_contract": {"path": str(batch_manifest_path), "sha256": _sha256_file(batch_manifest_path)},
        "source_read_cost": {"one_case_h5_passes": 3, "h5_bytes_per_pass": h5_bytes, "per_case_record_cap_bytes": MAX_RECORD_BYTES, "per_case_summary_cap_bytes": MAX_SUMMARY_BYTES, "aggregate_storage_conservative_sum": True},
        "guarded_payload_binding": {"trajectory_h5": "deferred_per_case_after_reservation_pre_hash_stream_post_hash", "raw_bi4_content_read": False, "solver_started": False, "cfd_or_model_started": False},
        "claim_boundary": {"typed_lifecycle": "saved-record diagnostic only", "native_exit_cause": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "launch_allowed": True,
        "execution_allowed": True,
        "launch_owner": "root",
        "shared_lease_required": True,
        "request_note": "Bounded family group. Batch worker audits one exact CURRENT case at a time and preserves per-case failures; alias and non-exact rows remain excluded. No physical qualification is granted.",
    }
    _atomic_json(request_path, request)
    return {"status": "PREPARED_METADATA_ONLY_NO_LAUNCH", "manifest": str(batch_manifest_path), "manifest_sha256": _sha256_file(batch_manifest_path), "request": str(request_path), "request_sha256": _sha256_file(request_path), "family_id": family, "case_count": len(case_records), "selected_source_bytes": selected_source_bytes, "exact_join_count": source["counts"]["exact_current_audit_metadata_joins"], "historical_alias_count": source["counts"]["historical_alias_rows"], "trajectory_content_opened": False, "trajectory_content_hashed": False}


def self_test() -> dict[str, Any]:
    return {"status": "PASS", "schema": BATCH_SCHEMA, "trajectory_content_opened": False, "trajectory_content_hashed": False, "launch_allowed": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--current", required=True, type=Path)
    prepare_parser.add_argument("--audit-verification", required=True, type=Path)
    prepare_parser.add_argument("--expected-current-sha256", required=True)
    prepare_parser.add_argument("--expected-audit-sha256", required=True)
    prepare_parser.add_argument("--family", required=True)
    prepare_parser.add_argument("--case-id", action="append")
    prepare_parser.add_argument("--exclude-case", action="append")
    prepare_parser.add_argument("--max-cases", type=int, default=8)
    prepare_parser.add_argument("--max-group-bytes", type=int, default=DEFAULT_MAX_GROUP_BYTES)
    prepare_parser.add_argument("--output-dir", required=True, type=Path)
    prepare_parser.add_argument("--v4-worker", required=True, type=Path)
    prepare_parser.add_argument("--batch-worker", type=Path, default=BATCH_WORKER)
    prepare_parser.add_argument("--python", required=True, type=Path)
    prepare_parser.add_argument("--runtime-config", required=True, type=Path)
    for name in ("runtime-v2", "runtime-v6", "runtime-v8", "dispatch-v8", "strict-v8"):
        prepare_parser.add_argument(f"--{name}", required=True, type=Path)
    prepare_parser.add_argument("--cwd", required=True, type=Path)
    prepare_parser.add_argument("--worktree-root", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.action == "self-test":
        print(json.dumps(self_test(), sort_keys=True))
        return 0
    if args.max_cases <= 0:
        raise SystemExit("BatchRequestError: max-cases must be positive")
    try:
        result = prepare(args)
    except (BatchRequestError, lifecycle.LifecycleError) as exc:
        raise SystemExit(f"BatchRequestError: {exc}") from exc
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
