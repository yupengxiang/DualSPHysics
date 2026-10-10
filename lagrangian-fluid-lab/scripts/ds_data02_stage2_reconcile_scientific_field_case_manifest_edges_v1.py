#!/usr/bin/env python3
"""Reconcile typed-lifecycle case-manifest edges without opening payloads.

The 335-case scientific-field source manifest deliberately excludes one
historical CURRENT alias.  This consumer checks the immutable 335/336 source
and lifecycle metadata joins and reports any missing *created case-manifest*
edge.  It may inspect the small producer proof/request/receipt/summary for a
missing edge, but it never opens, hashes, or stats a trajectory HDF5, BI4, or
records JSONL payload.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any


MAX_JSON_BYTES = 10 * 1024 * 1024
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
SOURCE_SCHEMA = "ds02.stage2.scientific-field-h5-batch-source.v1"
CURRENT_SCHEMA = "ds02.stage2.current336.v1"
PLAN_SCHEMA = "ds02.stage2.typed-lifecycle-continuation-plan.v4"
REGISTRY_SCHEMA = "ds02.stage2.typed-lifecycle-evidence-registry.v4"
ROOT_PROOF_SCHEMA = "ds02.stage2.root-lifecycle-metadata-independent-closure.v1"
HISTORICAL_ALIAS = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
JSON_SUFFIXES = {".json"}
PAYLOAD_SUFFIXES = {
    ".h5", ".hdf5", ".hdf", ".h5part", ".bi4", ".obi4", ".ibi4",
    ".vtk", ".vtu", ".vti", ".vtr", ".vtp", ".pvtu", ".pvd", ".xmf",
    ".xdmf", ".jsonl", ".csv", ".bin", ".npy", ".npz", ".raw", ".dat",
    ".out",
}


class ReconciliationError(ValueError):
    """A source or identity edge is not safe to reconcile."""


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ReconciliationError(f"{label} must be a SHA-256 digest")
    value = value.lower()
    if any(char not in "0123456789abcdef" for char in value):
        raise ReconciliationError(f"{label} is not hexadecimal")
    return value


def stat_snapshot(path: Path, label: str) -> dict[str, Any]:
    try:
        value = path.stat()
    except OSError as exc:
        raise ReconciliationError(f"{label} cannot be stat-ed: {path}") from exc
    if not path.is_file():
        raise ReconciliationError(f"{label} is not a regular file: {path}")
    return {
        "path": str(path),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
    }


def compare_stat(before: dict[str, Any], after: dict[str, Any], label: str) -> None:
    for key in ("path", "bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
        if before.get(key) != after.get(key):
            raise ReconciliationError(f"{label} changed at {key}")


def bounded_json_path(value: Any, label: str) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not value:
        raise ReconciliationError(f"{label} lacks a path")
    lexical = Path(value).expanduser()
    try:
        if lexical.is_symlink():
            raise ReconciliationError(f"{label} is a symlink: {lexical}")
    except OSError as exc:
        raise ReconciliationError(f"{label} cannot be inspected") from exc
    if lexical.suffix.lower() in PAYLOAD_SUFFIXES:
        raise ReconciliationError(f"{label} names a deferred scientific payload: {lexical}")
    path = lexical.resolve()
    if path.suffix.lower() not in JSON_SUFFIXES:
        raise ReconciliationError(f"{label} is not bounded JSON metadata: {path}")
    current = stat_snapshot(path, label)
    if current["bytes"] > MAX_JSON_BYTES:
        raise ReconciliationError(f"{label} exceeds the 10 MiB metadata cap: {path}")
    return path


def read_json(value: Any, label: str, expected_sha: str | None = None) -> tuple[Path, Any, dict[str, Any], str]:
    path = bounded_json_path(value, label)
    before = stat_snapshot(path, f"{label} pre-stat")
    try:
        raw = path.read_bytes()
        if len(raw) > MAX_JSON_BYTES:
            raise ReconciliationError(f"{label} exceeds the 10 MiB metadata cap: {path}")
        parsed = json.loads(raw.decode("utf-8"))
    except ReconciliationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReconciliationError(f"{label} is invalid JSON: {path}") from exc
    after = stat_snapshot(path, f"{label} post-stat")
    compare_stat(before, after, f"{label} changed during read")
    actual_sha = sha256_bytes(raw)
    if expected_sha is not None and actual_sha != digest(expected_sha, f"{label} expected SHA"):
        raise ReconciliationError(f"{label} content differs from its declared SHA")
    return path, parsed, after, actual_sha


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReconciliationError(f"{label} must be an object")
    return value


def ref_value(ref: Any, label: str) -> tuple[Path, dict[str, Any], str, dict[str, Any]]:
    ref_obj = require_object(ref, label)
    path_value = ref_obj.get("path")
    expected_sha = digest(ref_obj.get("sha256"), f"{label} SHA")
    path, document, stat, actual_sha = read_json(path_value, label, expected_sha)
    return path, document, actual_sha, stat


def check_ref_match(expected: Any, actual_path: Path, actual_sha: str, label: str) -> None:
    ref = require_object(expected, label)
    expected_sha = digest(ref.get("sha256"), f"{label} SHA")
    if expected_sha != actual_sha:
        raise ReconciliationError(f"{label} SHA differs from the producer declaration")
    declared_path = Path(ref.get("path", "")).expanduser().resolve()
    if declared_path != actual_path:
        raise ReconciliationError(f"{label} path differs from the producer declaration")


def source_case_map(source: dict[str, Any], current: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    source_rows = source.get("cases")
    current_rows = current.get("cases")
    if not isinstance(source_rows, list) or len(source_rows) != 335:
        raise ReconciliationError("source manifest must contain exactly 335 canonical cases")
    if not isinstance(current_rows, list) or len(current_rows) != 336:
        raise ReconciliationError("CURRENT must contain exactly 336 cases")
    source_map: dict[str, dict[str, Any]] = {}
    current_map: dict[str, dict[str, Any]] = {}
    for row in source_rows:
        row = require_object(row, "source case")
        case_id = row.get("physical_case_id")
        if not isinstance(case_id, str) or case_id in source_map:
            raise ReconciliationError("source manifest has a missing or duplicate physical_case_id")
        source_map[case_id] = row
    for row in current_rows:
        row = require_object(row, "CURRENT case")
        case_id = row.get("physical_case_id")
        if not isinstance(case_id, str) or case_id in current_map:
            raise ReconciliationError("CURRENT has a missing or duplicate physical_case_id")
        current_map[case_id] = row
    missing = set(current_map) - set(source_map)
    extra = set(source_map) - set(current_map)
    if missing != {HISTORICAL_ALIAS} or extra:
        raise ReconciliationError(
            "source/CURRENT identity difference is not the single declared historical alias"
        )
    for case_id, row in source_map.items():
        current_row = current_map[case_id]
        if row.get("current_index") != current_rows.index(current_row):
            raise ReconciliationError(f"{case_id}: source current_index does not bind CURRENT")
        if row.get("family_id") != current_row.get("family_id"):
            raise ReconciliationError(f"{case_id}: source family differs from CURRENT")
    return source_map, current_map


def plan_case_map(plan: dict[str, Any], current_map: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if plan.get("schema") != PLAN_SCHEMA:
        raise ReconciliationError("continuation plan schema is not the frozen V4 plan")
    records = plan.get("case_records")
    if not isinstance(records, list) or len(records) != 336:
        raise ReconciliationError("continuation plan must contain 336 case records")
    mapped: dict[str, dict[str, Any]] = {}
    for record in records:
        record = require_object(record, "continuation plan case record")
        case_id = record.get("physical_case_id")
        if not isinstance(case_id, str) or case_id in mapped:
            raise ReconciliationError("continuation plan case IDs are not unique")
        if case_id not in current_map:
            raise ReconciliationError(f"continuation plan has non-CURRENT case {case_id}")
        mapped[case_id] = record
    if set(mapped) != set(current_map):
        raise ReconciliationError("continuation plan case set differs from CURRENT")
    return mapped


def producer_edge(row: dict[str, Any], case_id: str) -> dict[str, Any]:
    evidence = require_object(row.get("typed_lifecycle_evidence"), f"{case_id} typed lifecycle evidence")
    producer = require_object(row.get("producer"), f"{case_id} producer")
    proof = require_object(producer.get("proof"), f"{case_id} producer proof")
    request = require_object(producer.get("request"), f"{case_id} producer request")
    receipt = require_object(evidence.get("case_receipt"), f"{case_id} case receipt")
    summary = require_object(evidence.get("typed_summary"), f"{case_id} typed summary")
    return {"producer": producer, "evidence": evidence, "proof": proof, "request": request, "receipt": receipt, "summary": summary}


def inspect_missing_case(row: dict[str, Any], plan_row: dict[str, Any]) -> dict[str, Any]:
    case_id = row["physical_case_id"]
    edge = producer_edge(row, case_id)
    producer = edge["producer"]
    proof_path, proof, proof_sha, proof_stat = ref_value(edge["proof"], f"{case_id} terminal proof")
    request_path, request, request_sha, request_stat = ref_value(edge["request"], f"{case_id} producer request")
    receipt_path, receipt, receipt_sha, receipt_stat = ref_value(edge["receipt"], f"{case_id} case receipt")
    summary_path, summary, summary_sha, summary_stat = ref_value(edge["summary"], f"{case_id} typed summary")

    # The terminal proof is the authoritative producer identity.  The
    # duplicate source refs must agree with the proof's top-level edges.
    if proof.get("physical_case_id") != case_id:
        raise ReconciliationError(f"{case_id}: terminal proof has another physical_case_id")
    if proof.get("request") != str(request_path) or digest(proof.get("request_sha256"), f"{case_id} proof request SHA") != request_sha:
        raise ReconciliationError(f"{case_id}: proof/request edge is not exact")
    if proof.get("receipt") != str(receipt_path) or digest(proof.get("receipt_sha256"), f"{case_id} proof receipt SHA") != receipt_sha:
        raise ReconciliationError(f"{case_id}: proof/receipt edge is not exact")
    if proof.get("report") != str(summary_path) or digest(proof.get("report_sha256"), f"{case_id} proof report SHA") != summary_sha:
        raise ReconciliationError(f"{case_id}: proof/summary edge is not exact")
    if edge["evidence"].get("case_manifest") is not None:
        raise ReconciliationError(f"{case_id}: inspect_missing_case received an existing manifest edge")
    if not isinstance(proof.get("guarded_receipt_status"), str) or proof["guarded_receipt_status"].lower() != "completed":
        raise ReconciliationError(f"{case_id}: producer proof is not completed")
    if not isinstance(proof.get("outer_unit_result"), str) or proof["outer_unit_result"].lower() != "success":
        raise ReconciliationError(f"{case_id}: producer proof is not successful")
    if receipt.get("status", "").upper() not in {"COMPLETED", "COMPLETED_DEVELOPMENT_UNKNOWN", "SUCCESS"}:
        raise ReconciliationError(f"{case_id}: producer receipt is not a completed receipt")
    if summary.get("physical_case_id") not in (None, case_id):
        raise ReconciliationError(f"{case_id}: typed summary belongs to another case")
    trajectory = require_object(row.get("trajectory_h5"), f"{case_id} trajectory HDF5")
    h5_path = trajectory.get("path")
    if not isinstance(h5_path, str) or Path(h5_path).suffix.lower() not in {".h5", ".hdf5", ".hdf"}:
        raise ReconciliationError(f"{case_id}: deferred trajectory path is not an HDF5 declaration")
    known_h5 = digest(trajectory.get("known_sha256"), f"{case_id} trajectory declared SHA")
    if trajectory.get("content_read_by_preparer") is not False or trajectory.get("content_hashed_by_preparer") is not False:
        raise ReconciliationError(f"{case_id}: deferred trajectory was marked as read by preparer")

    plan_evidence = require_object(plan_row.get("producer_evidence"), f"{case_id} plan producer evidence")
    for ref_name, source_ref in (("proof", edge["proof"]), ("request", edge["request"]), ("receipt", edge["receipt"]), ("summary", edge["summary"])):
        plan_ref = plan_evidence.get(ref_name)
        if not isinstance(plan_ref, dict) or digest(plan_ref.get("sha256"), f"{case_id} plan {ref_name} SHA") != digest(source_ref.get("sha256"), f"{case_id} source {ref_name} SHA"):
            raise ReconciliationError(f"{case_id}: plan {ref_name} does not bind source producer edge")

    return {
        "physical_case_id": case_id,
        "family_id": row.get("family_id"),
        "current_index": row.get("current_index"),
        "producer_id": producer.get("producer_id"),
        "producer_attempt_id": producer.get("attempt_id"),
        "producer_chain": {
            "terminal_proof": {"path": str(proof_path), "sha256": proof_sha, "stat": proof_stat},
            "request": {"path": str(request_path), "sha256": request_sha, "stat": request_stat},
            "receipt": {"path": str(receipt_path), "sha256": receipt_sha, "stat": receipt_stat},
            "typed_summary": {"path": str(summary_path), "sha256": summary_sha, "stat": summary_stat},
            "terminal_status": proof.get("status"),
            "receipt_status": receipt.get("status"),
        },
        "deferred_trajectory": {
            "path": h5_path,
            "bytes": trajectory.get("bytes"),
            "known_sha256": known_h5,
            "content_read_by_sidecar": False,
            "content_hashed_by_sidecar": False,
            "stat_checked_by_sidecar": False,
        },
        "edge_status": "MISSING_CREATED_CASE_MANIFEST",
        "actual_producer_chain": "REQUEST_PROOF_RECEIPT_SUMMARY_PRESENT",
        "metadata_recovery_possible": True,
        "production_eligible": False,
        "scientific_credit": "NONE",
        "recovery_credit": 0,
        "recovery_requirement": "CREATE_VERSIONED_CASE_MANIFEST_AND_NEW_TERMINAL_EDGE",
        "required_new_edge_fields": [
            "case_manifest.path_and_sha256",
            "case_manifest.current_catalog_path_and_sha256",
            "case_manifest.trajectory_h5_declared_path_and_sha256",
            "case_manifest.typed_summary_path_and_sha256",
            "case_manifest.case_receipt_path_and_sha256",
            "new_terminal_proof_request_receipt_manifest_identity",
        ],
        "physical_fate": "UNKNOWN",
        "legal_flux": "UNKNOWN",
        "dynamics": "UNKNOWN",
        "QI": "UNKNOWN",
        "QN": "UNKNOWN",
        "QE": "UNKNOWN",
    }


def reconcile(args: argparse.Namespace) -> dict[str, Any]:
    current_path, current, current_stat, current_sha = read_json(args.current, "CURRENT", CURRENT_SHA256)
    if current.get("schema") != CURRENT_SCHEMA or current_sha != CURRENT_SHA256:
        raise ReconciliationError("CURRENT is not the frozen 336-case catalog")
    source_path, source, source_stat, source_sha = read_json(args.source_manifest, "source manifest", None)
    if source.get("schema") != SOURCE_SCHEMA:
        raise ReconciliationError("source manifest schema is not the frozen 335-case source manifest")
    plan_path, plan, plan_stat, plan_sha = read_json(args.plan, "continuation plan", None)
    registry_path, registry, registry_stat, registry_sha = read_json(args.registry, "evidence registry", None)
    proof_path, root_proof, root_proof_stat, root_proof_sha = read_json(args.root307_proof, "ROOT307 closure proof", None)
    if registry.get("schema") != REGISTRY_SCHEMA:
        raise ReconciliationError("evidence registry schema is not the frozen V4 registry")
    if root_proof.get("schema") != ROOT_PROOF_SCHEMA or root_proof.get("status") != "PASS_ACTUAL_TERMINAL_METADATA_ACCOUNTING_AND_SOURCE_JOINS":
        raise ReconciliationError("ROOT307 closure proof is not the expected actual closure")
    source_binding = require_object(source.get("current_binding"), "source manifest CURRENT binding")
    if digest(source_binding.get("sha256"), "source manifest CURRENT SHA") != CURRENT_SHA256:
        raise ReconciliationError("source manifest is bound to another CURRENT catalog")
    plan_current = require_object(plan.get("current_catalog"), "continuation plan CURRENT binding")
    if digest(plan_current.get("sha256"), "continuation plan CURRENT SHA") != CURRENT_SHA256:
        raise ReconciliationError("continuation plan is bound to another CURRENT catalog")
    registry_current = require_object(registry.get("current"), "evidence registry CURRENT binding")
    if digest(registry_current.get("sha256"), "evidence registry CURRENT SHA") != CURRENT_SHA256:
        raise ReconciliationError("evidence registry is bound to another CURRENT catalog")
    coverage = require_object(root_proof.get("coverage"), "ROOT307 coverage")
    expected_coverage = {
        "actual_saved_mask_cases": 335,
        "current_cases": 336,
        "exact_current_audit_rows": 335,
        "historical_alias_unresolved": 1,
        "physical_or_scientific_credit_cases": 0,
    }
    for key, expected in expected_coverage.items():
        if coverage.get(key) != expected:
            raise ReconciliationError(f"ROOT307 coverage {key} is not {expected}")
    source_map, current_map = source_case_map(source, current)
    plan_map = plan_case_map(plan, current_map)
    missing_rows: list[dict[str, Any]] = []
    present_count = 0
    invalid_count = 0
    for case_id, row in source_map.items():
        evidence = require_object(row.get("typed_lifecycle_evidence"), f"{case_id} typed lifecycle evidence")
        if evidence.get("case_manifest") is None:
            missing_rows.append(inspect_missing_case(row, plan_map[case_id]))
        elif isinstance(evidence.get("case_manifest"), dict):
            present_count += 1
        else:
            invalid_count += 1
    if invalid_count:
        raise ReconciliationError(f"{invalid_count} source cases have malformed case_manifest edges")
    if len(missing_rows) != 1 or missing_rows[0]["physical_case_id"] != "F2H10V2_OFFSET_V1":
        raise ReconciliationError("missing case-manifest set changed from the audited single F2 edge")
    output = {
        "schema": "ds02.stage2.scientific-field-case-manifest-edge-reconciliation.v1",
        "status": "SOURCE_METADATA_RECONCILIATION_INCOMPLETE_CASE_MANIFEST_EDGE",
        "source_read_policy": {
            "metadata_only": True,
            "json_max_bytes": MAX_JSON_BYTES,
            "h5_bi4_jsonl_content_read": False,
            "trajectory_h5_content_read": False,
            "trajectory_h5_content_hashed": False,
            "trajectory_h5_stat_checked": False,
        },
        "frozen_bindings": {
            "current": {"path": str(current_path), "sha256": current_sha, "stat": current_stat},
            "source_manifest": {"path": str(source_path), "sha256": source_sha, "stat": source_stat},
            "continuation_plan": {"path": str(plan_path), "sha256": plan_sha, "stat": plan_stat},
            "evidence_registry": {"path": str(registry_path), "sha256": registry_sha, "stat": registry_stat},
            "root307_closure": {"path": str(proof_path), "sha256": root_proof_sha, "stat": root_proof_stat},
        },
        "scope": {
            "current_cases": len(current_map),
            "canonical_source_cases": len(source_map),
            "canonical_case_manifest_edges": present_count,
            "missing_case_manifest_edges": len(missing_rows),
            "historical_alias_cases_excluded": 1,
            "historical_alias_id": HISTORICAL_ALIAS,
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "current_manifest_edge_gaps": missing_rows,
        "conclusion": {
            "producer_chain_metadata_recoverable": True,
            "canonical_production_admission": False,
            "reason": "ROOT192 completed proof/request/receipt/summary are exact, but no created case-manifest edge exists in the immutable 335-case source manifest.",
            "required_action": "Create a new versioned case manifest and terminal proof edge; do not mutate CURRENT, the source manifest, or ROOT192 artifacts.",
        },
    }
    encoded = json.dumps(output, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    if len(encoded) > MAX_OUTPUT_BYTES:
        raise ReconciliationError("reconciliation output exceeds the 2 MiB bound")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", required=True)
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--root307-proof", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        value = reconcile(args)
        output = Path(args.output).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"status": value["status"], "output": str(output), "missing_edges": value["scope"]["missing_case_manifest_edges"]}, sort_keys=True))
        return 0
    except (OSError, ReconciliationError, TypeError, ValueError) as exc:
        print(f"reconciliation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
