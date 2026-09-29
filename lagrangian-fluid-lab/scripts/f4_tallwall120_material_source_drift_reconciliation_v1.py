#!/usr/bin/env python3
"""Reconcile the F4 Tallwall120 DEV_07 material source and authority drift.

This is a read-only reconciliation bridge.  It consumes bounded JSON receipts
and small-file metadata, and it performs only ``lstat`` on the target
trajectory HDF5.  It never opens, reads, or hashes that HDF5; it never writes
an authority receipt or material sidecar; and it never starts or controls a
solver, worker, native runtime, GPU, queue, or scheduler.

The bridge makes the current blockers explicit rather than silently choosing
between the archives-v1 collection row, the archives-v2 proposal target, or
the stale reader-manifest SHA.  It also records the minimum external inputs
that a trusted collection/reader authority, root owner, and scheduler would
have to provide before a one-case runner could be reconsidered.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Mapping, Sequence


LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import f4_tallwall120_material_candidate_runner_v1 as candidate_runner
from scripts import f4_tallwall120_material_root_scheduler_intake_v1 as root_intake


SCHEMA = "core.material.f4.tallwall120.source_drift_reconciliation.v1"
RECORD_ID = "f4-tallwall120-material-source-drift-reconciliation-v1"
CREATED_AT = "2026-09-28"
DEFAULT_OBSERVED_AT_UTC = "2026-09-28T00:00:00Z"

FAMILY = root_intake.FAMILY
SCOPE_ID = root_intake.SCOPE_ID
CASE_ID = root_intake.CASE_ID
SOURCE_HDF5 = root_intake.SOURCE_HDF5
SOURCE_SHA256 = root_intake.SOURCE_SHA256
SOURCE_BYTES = root_intake.SOURCE_BYTES
TARGET_COLLECTION_PATH = root_intake.COLLECTION.as_posix()
EXPECTED_Q = 0.23437500000000008
EXPECTED_EVENT_WINDOW_S = 8.68

PROPOSAL = Path("reports/F4-TALLWALL120-MATERIAL-COARSE-PROPOSAL-2026-09-28.json")
COLLECTION = root_intake.COLLECTION
READER = root_intake.READER
CONSISTENCY = root_intake.CONSISTENCY
DIAGNOSTIC = Path(
    "reports/F4-TALLWALL120-DEV07-MATERIAL-BASELINE24-DIAGNOSTIC-2026-09-28.json"
)
# This reconciliation is a historical 2026-09-28 diagnostic receipt.  Keep
# its input anchor immutable when the current root/scheduler intake advances
# to a later rerun; otherwise rebuilding the historical report would silently
# change its bound evidence domain.
ROOT_INTAKE = Path(
    "reports/F4-TALLWALL120-MATERIAL-ROOT-SCHEDULER-INTAKE-V1-2026-09-28.json"
)
CANDIDATE_RUNNER = candidate_runner.DEFAULT_OUTPUT
DEFAULT_OUTPUT = Path(
    "reports/F4-TALLWALL120-MATERIAL-SOURCE-DRIFT-RECONCILIATION-V1-2026-09-28.json"
)
DEFAULT_ZH_OUTPUT = Path(
    "reports/F4-TALLWALL120-MATERIAL-SOURCE-DRIFT-RECONCILIATION-V1-2026-09-28.zh-CN.md"
)

MAX_JSON_BYTES = 8 * 1024 * 1024
HDF5_SUFFIXES = {".h5", ".hdf5"}


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    resolved = path if path.is_absolute() else root / path
    resolved = resolved.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"path escapes lab root: {value}") from error
    return resolved


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _read_json(root: Path, value: str | Path, *, role: str) -> tuple[dict[str, Any], dict[str, Any], str | None]:
    path = _resolve(root, value)
    if path.suffix.lower() in HDF5_SUFFIXES:
        return {}, {"role": role, "path": str(value), "exists": False}, "hdf5_forbidden"
    reference: dict[str, Any] = {
        "role": role,
        "path": _relative(root, path),
        "exists": path.is_file(),
        "bytes": None,
        "sha256": None,
        "content_read": False,
        "content_hash_recomputed": False,
    }
    if not path.is_file():
        return {}, reference, "missing_file"
    size = path.stat().st_size
    reference["bytes"] = size
    if size > MAX_JSON_BYTES:
        return {}, reference, "file_exceeds_bounded_limit"
    try:
        data = path.read_bytes()
        reference.update(
            {
                "sha256": _sha256(data),
                "content_read": True,
                "content_hash_recomputed": True,
            }
        )
        payload = json.loads(data.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}, reference, "invalid_json"
    if not isinstance(payload, dict):
        return {}, reference, "json_not_object"
    return payload, reference, None


def _lstat_hdf5(root: Path, value: str | Path) -> dict[str, Any]:
    """Return filesystem metadata only; never open or read the HDF5."""

    path = _resolve(root, value)
    result: dict[str, Any] = {
        "path": _relative(root, path),
        "exists": False,
        "regular_file": False,
        "symlink": False,
        "bytes": None,
        "mode": "lstat_metadata_only",
        "content_read": False,
        "hash_recomputed": False,
        "opened_as_hdf5": False,
        "declared_sha256": SOURCE_SHA256,
    }
    try:
        info = os.lstat(path)
    except OSError as error:
        result["error"] = type(error).__name__
        return result
    result.update(
        {
            "exists": True,
            "regular_file": stat.S_ISREG(info.st_mode),
            "symlink": stat.S_ISLNK(info.st_mode),
            "bytes": info.st_size,
        }
    )
    return result


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _case_row(collection: Mapping[str, Any]) -> Mapping[str, Any]:
    rows = collection.get("cases")
    if not isinstance(rows, list):
        return {}
    matches = [row for row in rows if isinstance(row, Mapping) and row.get("case_id") == CASE_ID]
    return matches[0] if len(matches) == 1 else {}


def _source_contract(proposal: Mapping[str, Any]) -> dict[str, Any]:
    target = _mapping(proposal.get("target"))
    source = _mapping(proposal.get("source_manifest_contract"))
    collection = _mapping(source.get("core_collection_manifest"))
    direct = _mapping(source.get("direct_source_manifest"))
    return {
        "proposal_target": {
            "source_hdf5": target.get("source_hdf5"),
            "source_sha256": target.get("source_sha256"),
            "source_bytes": target.get("source_bytes"),
            "case_id": target.get("case_id"),
        },
        "proposal_collection": {
            "path": collection.get("path"),
            "sha256": collection.get("sha256"),
            "declared_hdf5": collection.get("case_row_declared_hdf5"),
            "declared_source_sha256": collection.get("case_row_source_sha256"),
            "exact_path_match": collection.get("exact_path_match"),
        },
        "proposal_archive": {
            "path": direct.get("path"),
            "sha256": direct.get("sha256"),
            "trajectory": dict(_mapping(direct.get("trajectory_output"))),
            "exact_target_binding": direct.get("exact_target_binding"),
        },
    }


def _reader_projection(reader: Mapping[str, Any], collection_ref: Mapping[str, Any]) -> dict[str, Any]:
    reader_result = _mapping(reader.get("reader_result"))
    return {
        "manifest": reader.get("manifest"),
        "recorded_manifest_sha256": reader.get("manifest_sha256"),
        "current_manifest_sha256": collection_ref.get("sha256"),
        "reader_formal_eligible": reader_result.get("reader_formal_eligible"),
        "dataset_opened": reader_result.get("dataset_opened"),
        "diagnostic_only": reader_result.get("diagnostic_only"),
    }


def _diagnostic_projection(diagnostic: Mapping[str, Any]) -> dict[str, Any]:
    source = _mapping(diagnostic.get("source"))
    identity = _mapping(source.get("case_identity"))
    params = _mapping(diagnostic.get("parameters"))
    trace = _mapping(diagnostic.get("trace"))
    decision = _mapping(diagnostic.get("decision"))
    binding = _mapping(trace.get("binding"))
    return {
        "status": diagnostic.get("status"),
        "diagnostic_only": diagnostic.get("diagnostic_only"),
        "case_identity": {
            "case_id": identity.get("case_id"),
            "frames": identity.get("frames"),
            "transitions": identity.get("transitions"),
            "time_end_s": identity.get("time_end_s"),
        },
        "source": {
            "repo_relative_path": source.get("repo_relative_path"),
            "before_after_match": source.get("before_after_match"),
            "before_sha256": _mapping(source.get("before")).get("sha256"),
            "after_sha256": _mapping(source.get("after")).get("sha256"),
            "after_bytes": _mapping(source.get("after")).get("size_bytes"),
        },
        "parameters": {
            key: params.get(key)
            for key in ("q", "dp_m", "seeds", "substeps", "neighbour_variant")
        },
        "trace": {
            "status": trace.get("status"),
            "committed_frame": trace.get("committed_frame"),
            "frame_count": trace.get("frame_count"),
            "transition_count": trace.get("transition_count"),
            "event_window_complete": trace.get("event_window_complete"),
            "event_window_status": trace.get("event_window_status"),
            "unknown_gate_pass": trace.get("unknown_gate_pass"),
            "unknown_fraction_max": trace.get("unknown_fraction_max"),
            "common_reliable_path_coverage": trace.get("common_reliable_path_coverage"),
            "result_source_sha256": binding.get("result_source_sha256"),
            "hdf5_attribute_source_sha256": binding.get("hdf5_attribute_source_sha256"),
        },
        "decision": {
            "classification": decision.get("classification"),
            "formal_admission": decision.get("formal_admission"),
            "T1": decision.get("T1"),
            "T2": decision.get("T2"),
            "credit": decision.get("credit"),
        },
    }


def _external_inputs(namespace: str) -> list[dict[str, Any]]:
    return [
        {
            "id": "trusted_collection_refresh",
            "owner": "collection authority",
            "present": False,
            "minimum_fields": {
                "case_id": CASE_ID,
                "trajectory_path": SOURCE_HDF5,
                "trajectory_sha256": SOURCE_SHA256,
                "trajectory_bytes": SOURCE_BYTES,
                "manifest_path": TARGET_COLLECTION_PATH,
                "manifest_sha256": "sha256 of the exact refreshed manifest bytes",
            },
            "purpose": "replace the DEV_07 archives-v1 row with an authoritative archives-v2 row; no path alias inference",
        },
        {
            "id": "trusted_reader_smoke_receipt",
            "owner": "reader authority",
            "present": False,
            "minimum_fields": {
                "manifest": TARGET_COLLECTION_PATH,
                "manifest_sha256": "exact current collection manifest SHA256",
                "reader_formal_eligible": "explicit reader result; not inferred from manifest declaration",
                "diagnostic_only": True,
                "dataset_opened": True,
            },
            "purpose": "bind the reader receipt to the refreshed manifest and keep smoke execution non-crediting",
        },
        {
            "id": "fresh_root_receipt",
            "owner": "root owner",
            "present": False,
            "minimum_fields": {
                "schema": root_intake.ROOT_RECEIPT_SCHEMA,
                "record_id": root_intake.ROOT_RECEIPT_ID,
                "status": "root_authorization_issued",
                "synthetic": False,
                "pair_id": "shared safe identifier with scheduler receipt",
                "binding": "exact current input refs/hashes, source identity, normalized argv/cwd, launch SHA, and fresh namespace SHA",
                "fresh_namespace": f"{namespace} + one-use 64-hex namespace_nonce",
                "root_authorization": "root_owned=true, single_use=true, consumed=false",
                "counterparty": "scheduler receipt path, binding SHA, and pair_id",
                "side_effects": "all starts false and all mutation counters zero",
            },
            "purpose": "authorize one fresh namespace without granting this reconciliation report authority",
        },
        {
            "id": "scheduler_owned_host_io_receipt",
            "owner": "scheduler authority",
            "present": False,
            "minimum_fields": {
                "schema": root_intake.SCHEDULER_RECEIPT_SCHEMA,
                "record_id": root_intake.SCHEDULER_RECEIPT_ID,
                "status": "scheduler_host_io_reserved",
                "synthetic": False,
                "pair_id": "same pair_id as fresh root receipt",
                "binding": "byte-for-byte same current input refs/hashes, source identity, normalized argv/cwd, and namespace binding",
                "scheduler_reservation": "active, scheduler_owned_host_io_verified=true, single_use=true, consumed=false",
                "resource_request": {"cpu_cores": 2, "ram_mib": 24576, "gpu_peak_mib": 6144, "io_weight": 2},
                "host_io_reservation": "filesystem, snapshot_id, capacity headroom, and owned IO weight",
                "counterparty": "root receipt path, binding SHA, and pair_id",
                "side_effects": "all starts false and all mutation counters zero",
            },
            "purpose": "prove scheduler-owned host-I/O reservation; GPU occupancy is not a substitute for this authority",
        },
    ]


def build_report(
    root: str | Path = LAB_ROOT,
    *,
    observed_at_utc: str = DEFAULT_OBSERVED_AT_UTC,
) -> dict[str, Any]:
    root = Path(root).resolve()
    documents = {
        "proposal": (PROPOSAL, "coarse material proposal"),
        "collection": (COLLECTION, "collection manifest"),
        "reader": (READER, "reader smoke receipt"),
        "consistency": (CONSISTENCY, "receipt consistency audit"),
        "diagnostic": (DIAGNOSTIC, "DEV_07 material diagnostic"),
        "root_intake": (ROOT_INTAKE, "root/scheduler intake receipt"),
        "candidate_runner": (CANDIDATE_RUNNER, "material candidate runner receipt"),
    }
    payloads: dict[str, dict[str, Any]] = {}
    refs: dict[str, dict[str, Any]] = {}
    input_errors: list[str] = []
    for name, (path, role) in documents.items():
        payload, reference, error = _read_json(root, path, role=role)
        payloads[name] = payload
        refs[name] = reference
        if error:
            input_errors.append(f"{name}:{error}")

    proposal = payloads["proposal"]
    collection = payloads["collection"]
    reader = payloads["reader"]
    consistency = payloads["consistency"]
    diagnostic = payloads["diagnostic"]
    root_report = payloads["root_intake"]
    runner_report = payloads["candidate_runner"]

    target = _mapping(proposal.get("target"))
    source_contract = _source_contract(proposal)
    row = _case_row(collection)
    row_trajectory = _mapping(row.get("trajectory"))
    reader_projection = _reader_projection(reader, refs["collection"])
    diagnostic_projection = _diagnostic_projection(diagnostic)
    root_validation = _mapping(root_report.get("validation"))
    root_checks = _mapping(root_validation.get("checks"))
    runner_validation_errors = candidate_runner.validate_report(runner_report) if runner_report else ["runner_report_missing"]
    root_validation_errors = root_intake.validate_report(root_report) if root_report else ["root_report_missing"]

    collection_path = row_trajectory.get("path")
    collection_sha = row_trajectory.get("sha256")
    proposal_collection = source_contract["proposal_collection"]
    diagnostic_source = diagnostic_projection["source"]
    diagnostic_trace = diagnostic_projection["trace"]
    diagnostic_params = diagnostic_projection["parameters"]

    checks = {
        "proposal_target_exact": (
            target.get("case_id") == CASE_ID
            and target.get("source_hdf5") == SOURCE_HDF5
            and target.get("source_sha256") == SOURCE_SHA256
            and target.get("source_bytes") == SOURCE_BYTES
        ),
        "collection_manifest_ref_current": (
            refs["collection"].get("sha256") == proposal_collection.get("sha256")
            and refs["collection"].get("path") == TARGET_COLLECTION_PATH
        ),
        "collection_row_path_exact": collection_path == SOURCE_HDF5,
        "collection_row_source_sha_exact": collection_sha == SOURCE_SHA256,
        "collection_row_source_bytes_exact": row_trajectory.get("bytes") == SOURCE_BYTES,
        "reader_manifest_path_exact": reader_projection.get("manifest") == TARGET_COLLECTION_PATH,
        "reader_manifest_sha_exact": reader_projection.get("recorded_manifest_sha256") == refs["collection"].get("sha256"),
        "reader_formal_gate_closed": reader_projection.get("reader_formal_eligible") is False,
        "consistency_audit_confirms_path_drift": (
            _mapping(consistency.get("archives_path_binding")).get("mismatch_class") == "archives-v1_vs_archives-v2"
        ),
        "consistency_audit_confirms_reader_sha_drift": (
            _mapping(consistency.get("reader_smoke_binding")).get("manifest_sha_matches_current") is False
        ),
        "source_sha_consistent_without_hdf5_rehash": (
            target.get("source_sha256") == collection_sha == diagnostic_source.get("before_sha256") == diagnostic_source.get("after_sha256") == diagnostic_trace.get("result_source_sha256") == diagnostic_trace.get("hdf5_attribute_source_sha256") == SOURCE_SHA256
        ),
        "diagnostic_source_path_exact": diagnostic_source.get("repo_relative_path") == SOURCE_HDF5,
        "diagnostic_source_unchanged_claim": diagnostic_source.get("before_after_match") is True,
        "diagnostic_parameter_binding": (
            diagnostic_params.get("q") == EXPECTED_Q
            and diagnostic_params.get("dp_m") == 0.0075
            and diagnostic_params.get("seeds") == 512
            and diagnostic_params.get("substeps") == 2
            and diagnostic_params.get("neighbour_variant") == "baseline24"
        ),
        "diagnostic_full_event_window": (
            diagnostic_trace.get("event_window_complete") is True
            and diagnostic_trace.get("event_window_status") == "complete"
            and isinstance(diagnostic_projection["case_identity"].get("time_end_s"), (int, float))
            and float(diagnostic_projection["case_identity"]["time_end_s"]) >= EXPECTED_EVENT_WINDOW_S
        ),
        "diagnostic_unknown_gate": (
            diagnostic_trace.get("unknown_gate_pass") is True
            and isinstance(diagnostic_trace.get("unknown_fraction_max"), (int, float))
            and float(diagnostic_trace.get("unknown_fraction_max")) <= 0.01
        ),
        "diagnostic_reliable_coverage": diagnostic_trace.get("common_reliable_path_coverage") == 1.0,
        "root_receipt_credible": (
            root_checks.get("future_root_receipt_present") is True
            and root_checks.get("future_root_receipt_valid") is True
        ),
        "scheduler_receipt_credible": (
            root_checks.get("future_scheduler_receipt_present") is True
            and root_checks.get("future_scheduler_receipt_valid") is True
            and root_checks.get("scheduler_owned_host_io_reservation_valid") is True
        ),
        "receipt_pair_cross_bound": root_checks.get("receipt_pair_cross_binding_valid") is True,
        "candidate_runner_report_valid": not runner_validation_errors,
        "candidate_runner_fail_closed": (
            runner_report.get("status") == "blocked_fail_closed"
            and _mapping(runner_report.get("authorization")).get("launch_admitted") is False
            and _mapping(runner_report.get("authorization")).get("worker_launch_authorized") is False
        ),
        "fresh_namespace_absent": (
            _mapping(_mapping(root_report.get("binding_projection")).get("fresh_output_namespace")).get("namespace_path_exists") is False
        ),
    }
    source_ready = bool(
        checks["proposal_target_exact"]
        and checks["collection_manifest_ref_current"]
        and checks["collection_row_path_exact"]
        and checks["collection_row_source_sha_exact"]
        and checks["reader_manifest_path_exact"]
        and checks["reader_manifest_sha_exact"]
        and checks["source_sha_consistent_without_hdf5_rehash"]
    )
    receipts_ready = bool(
        checks["root_receipt_credible"]
        and checks["scheduler_receipt_credible"]
        and checks["receipt_pair_cross_bound"]
    )

    findings: list[dict[str, Any]] = []
    if not checks["collection_row_path_exact"]:
        findings.append(
            {
                "finding": "collection_manifest_archives_v1_vs_target_archives_v2_mismatch",
                "severity": "blocking",
                "observed": collection_path,
                "expected": SOURCE_HDF5,
                "detail": "the DEV_07 collection row remains archives-v1; the proposal target is archives-v2",
            }
        )
    if not checks["reader_manifest_sha_exact"]:
        findings.append(
            {
                "finding": "reader_smoke_manifest_sha_stale",
                "severity": "blocking",
                "observed": reader_projection.get("recorded_manifest_sha256"),
                "expected": reader_projection.get("current_manifest_sha256"),
                "detail": "the reader receipt does not bind the current collection manifest bytes",
            }
        )
    if not checks["diagnostic_parameter_binding"]:
        findings.append(
            {
                "finding": "dev07_diagnostic_parameter_drift",
                "severity": "boundary",
                "observed": diagnostic_params,
                "expected": {"q": EXPECTED_Q, "dp_m": 0.0075, "seeds": 512, "substeps": 2, "neighbour_variant": "baseline24"},
                "detail": "the existing diagnostic used q=0.5 and is not reusable as the proposed q=0.234375 material sidecar",
            }
        )
    if not checks["diagnostic_full_event_window"] or not checks["diagnostic_unknown_gate"] or not checks["diagnostic_reliable_coverage"]:
        findings.append(
            {
                "finding": "dev07_diagnostic_negative_not_qualifying",
                "severity": "boundary",
                "observed": {
                    "event_window_complete": diagnostic_trace.get("event_window_complete"),
                    "unknown_fraction_max": diagnostic_trace.get("unknown_fraction_max"),
                    "common_reliable_path_coverage": diagnostic_trace.get("common_reliable_path_coverage"),
                },
                "detail": "the existing diagnostic is right-censored/unknown-gated and remains diagnostic-only",
            }
        )
    if not receipts_ready:
        findings.append(
            {
                "finding": "fresh_root_and_scheduler_authority_missing",
                "severity": "blocking",
                "detail": "neither a credible fresh root receipt nor a scheduler-owned host-I/O receipt is present and cross-bound",
            }
        )

    blockers = [item["finding"] for item in findings if item.get("severity") == "blocking"]
    if input_errors:
        blockers.extend(f"input:{item}" for item in input_errors)
    if root_validation_errors:
        blockers.extend(f"root_intake:{item}" for item in root_validation_errors)
    if runner_validation_errors:
        blockers.extend(f"candidate_runner:{item}" for item in runner_validation_errors)
    blockers = list(dict.fromkeys(blockers))

    hdf5_metadata = _lstat_hdf5(root, SOURCE_HDF5)
    namespace = _mapping(_mapping(root_report.get("binding_projection")).get("fresh_output_namespace")).get("namespace", root_intake.DEFAULT_OUTPUT_NAMESPACE)
    actual_sidecar_execution_allowed = bool(source_ready and receipts_ready)

    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "created_at": CREATED_AT,
        "observed_at_utc": observed_at_utc,
        "status": "blocked_fail_closed",
        "decision": "diagnostic_only_source_drift_reconciliation",
        "scope": {"family": FAMILY, "scope_id": SCOPE_ID, "case_id": CASE_ID, "split": "train"},
        "inputs": refs,
        "source_identity": {
            "target": {"hdf5": SOURCE_HDF5, "sha256": SOURCE_SHA256, "bytes": SOURCE_BYTES},
            "hdf5_metadata": hdf5_metadata,
            "proposal_collection_contract": source_contract,
            "collection_row": {
                "case_id": row.get("case_id"),
                "trajectory": dict(row_trajectory),
                "reader_eligible": row.get("reader_eligible"),
                "scientific_status": row.get("scientific_status"),
            },
            "reader": reader_projection,
        },
        "existing_diagnostic": diagnostic_projection,
        "root_scheduler": {
            "status": root_report.get("status"),
            "validation_checks": {
                key: root_checks.get(key)
                for key in (
                    "reader_identity_bound",
                    "source_identity_contract_valid",
                    "future_root_receipt_present",
                    "future_root_receipt_valid",
                    "future_scheduler_receipt_present",
                    "future_scheduler_receipt_valid",
                    "receipt_pair_cross_binding_valid",
                    "scheduler_owned_host_io_reservation_valid",
                )
            },
            "blockers": list(root_validation.get("blockers", [])) if isinstance(root_validation.get("blockers"), list) else [],
            "authorization": dict(_mapping(root_report.get("authorization"))),
        },
        "candidate_runner": {
            "status": runner_report.get("status"),
            "validation_errors": runner_validation_errors,
            "blockers": list(runner_report.get("blockers", [])) if isinstance(runner_report.get("blockers"), list) else [],
            "authorization": dict(_mapping(runner_report.get("authorization"))),
            "planned_sidecar": dict(_mapping(runner_report.get("planned_sidecar"))),
        },
        "checks": checks,
        "source_reconciliation": {
            "ready": source_ready,
            "archives_path_reconciled": checks["collection_row_path_exact"],
            "reader_sha_reconciled": checks["reader_manifest_sha_exact"],
            "source_sha_reconciled": checks["source_sha_consistent_without_hdf5_rehash"],
        },
        "authority": {
            "credible_fresh_root_receipt": checks["root_receipt_credible"],
            "credible_scheduler_owned_io_receipt": checks["scheduler_receipt_credible"],
            "pair_cross_bound": checks["receipt_pair_cross_bound"],
            "actual_sidecar_execution_allowed": actual_sidecar_execution_allowed,
            "sidecar_executed": False,
            "material_sidecar_present": False,
            "formal": False,
            "T1": False,
            "T2": False,
            "credit": 0,
        },
        "minimum_external_inputs": _external_inputs(str(namespace)),
        "findings": findings,
        "blockers": blockers,
        "execution_controls": {
            "bounded_json_only": True,
            "trajectory_hdf5_lstat_only": True,
            "source_hdf5_opened": False,
            "source_hdf5_read": False,
            "source_hdf5_hash_recomputed": False,
            "authority_receipt_written": False,
            "material_sidecar_written": False,
            "solver_started": False,
            "worker_started": False,
            "native_started": False,
            "gpu_started": False,
            "queue_or_scheduler_started": False,
            "registry_mutations": 0,
            "ledger_mutations": 0,
            "denominator_mutations": 0,
            "gate_mutations": 0,
            "completion_mutations": 0,
            "plan_mutations": 0,
        },
        "next_safe_action": (
            "由 collection/reader authority 先提供修正后的 archives-v2 collection row 与绑定当前 manifest SHA 的 reader receipt；"
            "再由 root owner 和 scheduler 分别提供严格 cross-bind 的 fresh root receipt 与 scheduler-owned host-I/O receipt。"
            "在这些外部 authority receipt 全部存在且校验通过前，不得执行 actual material sidecar；当前 DEV_07 diagnostic 只能保留为 diagnostic-only。"
        ),
    }


def validate_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {
        "schema", "record_id", "created_at", "observed_at_utc", "status", "decision", "scope", "inputs",
        "source_identity", "existing_diagnostic", "root_scheduler", "candidate_runner", "checks",
        "source_reconciliation", "authority", "minimum_external_inputs", "findings", "blockers",
        "execution_controls", "next_safe_action",
    }
    if not isinstance(report, Mapping) or set(report) != required:
        return ["report.fields"]
    if report.get("schema") != SCHEMA:
        errors.append("schema")
    if report.get("record_id") != RECORD_ID:
        errors.append("record_id")
    if report.get("created_at") != CREATED_AT:
        errors.append("created_at")
    if report.get("status") != "blocked_fail_closed":
        errors.append("status")
    if report.get("decision") != "diagnostic_only_source_drift_reconciliation":
        errors.append("decision")
    if report.get("scope") != {"family": FAMILY, "scope_id": SCOPE_ID, "case_id": CASE_ID, "split": "train"}:
        errors.append("scope")
    checks = report.get("checks")
    if not isinstance(checks, Mapping) or not all(isinstance(value, bool) for value in checks.values()):
        errors.append("checks")
    source_reconciliation = _mapping(report.get("source_reconciliation"))
    if source_reconciliation.get("ready") is not False:
        errors.append("source_reconciliation.ready")
    authority = _mapping(report.get("authority"))
    for key, expected in {
        "credible_fresh_root_receipt": False,
        "credible_scheduler_owned_io_receipt": False,
        "pair_cross_bound": False,
        "actual_sidecar_execution_allowed": False,
        "sidecar_executed": False,
        "material_sidecar_present": False,
        "formal": False,
        "T1": False,
        "T2": False,
        "credit": 0,
    }.items():
        if authority.get(key) is not expected:
            errors.append(f"authority.{key}")
    controls = _mapping(report.get("execution_controls"))
    for key, expected in {
        "bounded_json_only": True,
        "trajectory_hdf5_lstat_only": True,
        "source_hdf5_opened": False,
        "source_hdf5_read": False,
        "source_hdf5_hash_recomputed": False,
        "authority_receipt_written": False,
        "material_sidecar_written": False,
        "solver_started": False,
        "worker_started": False,
        "native_started": False,
        "gpu_started": False,
        "queue_or_scheduler_started": False,
        "registry_mutations": 0,
        "ledger_mutations": 0,
        "denominator_mutations": 0,
        "gate_mutations": 0,
        "completion_mutations": 0,
        "plan_mutations": 0,
    }.items():
        if controls.get(key) is not expected:
            errors.append(f"execution_controls.{key}")
    if not isinstance(report.get("minimum_external_inputs"), list) or len(report["minimum_external_inputs"]) != 4:
        errors.append("minimum_external_inputs")
    if not isinstance(report.get("findings"), list) or not report.get("findings"):
        errors.append("findings")
    if not isinstance(report.get("blockers"), list) or not report.get("blockers"):
        errors.append("blockers")
    if not isinstance(report.get("next_safe_action"), str) or not report.get("next_safe_action"):
        errors.append("next_safe_action")
    return errors


def write_report(report: Mapping[str, Any], output: str | Path) -> Path:
    errors = validate_report(report)
    if errors:
        raise ValueError("refusing to write invalid source-drift reconciliation: " + ", ".join(errors))
    path = Path(output).resolve()
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return path


def write_zh_report(report: Mapping[str, Any], output: str | Path) -> Path:
    errors = validate_report(report)
    if errors:
        raise ValueError("refusing to write invalid source-drift reconciliation markdown: " + ", ".join(errors))
    path = Path(output).resolve()
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    checks = report["checks"]
    findings = report["findings"]
    blockers = report["blockers"]
    lines = [
        "# F4 Tallwall120 DEV_07 material source-drift reconciliation v1",
        "",
        f"- 状态：`{report['status']}`",
        "- 结论：只读诊断；actual material sidecar 未执行，formal/T1/T2/credit 均关闭。",
        f"- source reconciliation ready：`{report['source_reconciliation']['ready']}`",
        f"- fresh root receipt：`{report['authority']['credible_fresh_root_receipt']}`",
        f"- scheduler-owned host-I/O receipt：`{report['authority']['credible_scheduler_owned_io_receipt']}`",
        "",
        "## 已确认的 drift / diagnostic 边界",
        "",
        f"- collection row exact path：`{checks['collection_row_path_exact']}`；当前 row 与 proposal target 的 archives-v1/v2 差异被显式保留。",
        f"- reader manifest SHA exact：`{checks['reader_manifest_sha_exact']}`；stale reader SHA 不得被 manifest formal 声明覆盖。",
        f"- source SHA 一致（未重哈希 HDF5）：`{checks['source_sha_consistent_without_hdf5_rehash']}`。",
        f"- DEV_07 参数绑定：`{checks['diagnostic_parameter_binding']}`；现有 diagnostic q=0.5，不可作为 q=0.234375 sidecar。",
        f"- full event window / unknown gate / reliable coverage：`{checks['diagnostic_full_event_window']}` / `{checks['diagnostic_unknown_gate']}` / `{checks['diagnostic_reliable_coverage']}`。",
        "",
        "## 取得 authority receipt 的最小外部输入",
        "",
        "1. collection authority 提供 DEV_07 archives-v2 row，并给出当前 manifest 的精确 SHA256。",
        "2. reader authority 提供绑定该 manifest path + SHA 的 reader receipt；reader smoke 不自授 formal/T1/T2/credit。",
        "3. root owner 提供非 synthetic、single-use、未消费、fresh namespace + 64-hex nonce 的 root receipt，并绑定当前全部 hashes、normalized argv/cwd 和 scheduler counterparty。",
        "4. scheduler 提供同 pair_id 的 scheduler-owned host-I/O receipt，绑定同一 hashes/argv/namespace、resource request、filesystem/snapshot/capacity 和 root counterparty。",
        "",
        "## 当前 blockers",
        "",
    ]
    lines.extend(f"- `{item}`" for item in blockers)
    lines.extend([
        "",
        "## 边界",
        "",
        "- trajectory HDF5 仅做 `lstat`；未打开、未读取、未重哈希。",
        "- 未写 authority receipt、material sidecar、registry、ledger、denominator、gate、completion 或 PLAN。",
        "- 未启动/停止/重启 solver、worker、native、GPU、queue 或 scheduler。",
        "",
        f"下一安全动作：{report['next_safe_action']}",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--zh-output", type=Path, default=DEFAULT_ZH_OUTPUT)
    parser.add_argument("--observed-at", default=DEFAULT_OBSERVED_AT_UTC)
    args = parser.parse_args(argv)
    report = build_report(args.root, observed_at_utc=args.observed_at)
    write_report(report, args.output)
    write_zh_report(report, args.zh_output)
    print(json.dumps({"status": report["status"], "report": str(args.output)}, ensure_ascii=False, sort_keys=True))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
