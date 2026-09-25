#!/usr/bin/env python3
"""Refresh F8 R008 readiness without treating caller evidence as trusted.

This v5 reconciles the v4 readiness receipt with later static per-case and
metric verifier work. It records stale review bindings explicitly and keeps
execution, native-integrity, T1, and qualification gates closed.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts import f8_r008_execution_readiness_audit_v4 as audit_v4
from scripts import f8_r008_native_fluid_table_metric_review_v2 as metric_review
from scripts import f8_r008_per_case_provenance_implementation_review_v2 as per_case_review
from scripts import f8_r008_t1_metric_matrix_adapter_v2 as matrix_adapter
from scripts import f8_r008_t1_metric_matrix_review_v2 as matrix_review


ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008")
V4_RECEIPT = ROOT / "t1-execution-readiness-audit-v4/receipt.json"
OUTPUT = LAB / ROOT / "t1-execution-readiness-audit-v5/receipt.json"
SCHEMA = "core.cfd.f8.r008_execution_readiness_audit.v5"
RECORD_ID = "f8-r008-execution-readiness-audit-v5"
MAX_EVIDENCE_BYTES = 128 * 1024 * 1024
O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)

MATRIX_IMPLEMENTATION_PATHS = {
    "scripts/f8_r008_t1_metric_matrix_adapter_v2.py",
    "scripts/f8_r008_native_fluid_table_metric_bundle_verifier_v2.py",
}
MATRIX_TEST_PATHS = {
    "tests/test_f8_r008_t1_metric_matrix_adapter_v2.py",
    "tests/test_f8_r008_native_fluid_table_metric_bundle_verifier_v2.py",
    "tests/test_f8_r008_t1_metric_matrix_review_v2.py",
}
EVIDENCE_PATHS = (
    V4_RECEIPT,
    Path("scripts/f8_r008_execution_readiness_audit_v4.py"),
    Path("tests/test_f8_r008_execution_readiness_audit_v4.py"),
    Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/per-case-provenance-implementation-review-v2/receipt.json"),
    Path("scripts/f8_r008_per_case_provenance_implementation_review_v2.py"),
    Path("scripts/f8_r008_per_case_bundle_verifier_v1.py"),
    Path("scripts/f8_r008_per_case_bundle_verifier_v2.py"),
    Path("tests/test_f8_r008_per_case_bundle_verifier_v2.py"),
    Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/native-fluid-table-schema-v2/metric-review-v2/receipt.json"),
    Path("scripts/f8_r008_native_fluid_table_metric_review_v2.py"),
    Path("scripts/f8_r008_native_fluid_table_metric_bundle_verifier_v2.py"),
    Path("scripts/f8_r008_t1_metric_adapter_v2.py"),
    Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/native-fluid-table-schema-v2/metric-matrix-review-v2/receipt.json"),
    Path("scripts/f8_r008_t1_metric_matrix_review_v2.py"),
    Path("scripts/f8_r008_t1_metric_matrix_adapter_v2.py"),
    Path("tests/test_f8_r008_t1_metric_matrix_adapter_v2.py"),
    Path("tests/test_f8_r008_t1_metric_matrix_review_v2.py"),
    Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/t1-scope-design-v1/receipt.json"),
    Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/cpu-native-preflight-v3/receipt.json"),
)


class ReadinessAuditError(ValueError):
    """The versioned R008 readiness evidence is unsafe or inconsistent."""


def _read_regular(relative: str | Path) -> tuple[bytes, dict[str, Any]]:
    path = Path(relative)
    if not path.is_absolute() and ".." in path.parts:
        raise ReadinessAuditError("readiness evidence path must remain beneath the lab root")
    target = path if path.is_absolute() else LAB / path
    display_path = path.as_posix()
    fd = os.open(target, os.O_RDONLY | O_NOFOLLOW | O_CLOEXEC)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ReadinessAuditError(f"readiness evidence must be a single-link regular file: {path}")
        if before.st_size > MAX_EVIDENCE_BYTES:
            raise ReadinessAuditError(f"readiness evidence exceeds the byte limit: {path}")
        chunks: list[bytes] = []
        size = 0
        while True:
            block = os.read(fd, min(1024 * 1024, MAX_EVIDENCE_BYTES + 1 - size))
            if not block:
                break
            size += len(block)
            if size > MAX_EVIDENCE_BYTES:
                raise ReadinessAuditError(f"readiness evidence exceeds the byte limit: {path}")
            chunks.append(block)
        after = os.fstat(fd)
        named = os.stat(target, follow_symlinks=False)
        identity = lambda value: (
            value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns, value.st_nlink,
        )
        if identity(before) != identity(after) or identity(after) != identity(named) or size != before.st_size:
            raise ReadinessAuditError(f"readiness evidence changed while being read: {path}")
        payload = b"".join(chunks)
        return payload, {
            "path": display_path,
            "bytes": size,
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    finally:
        os.close(fd)


def _load_json(relative: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    raw, reference = _read_regular(relative)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReadinessAuditError(f"readiness evidence is not strict UTF-8 JSON: {relative}") from error
    if not isinstance(value, dict):
        raise ReadinessAuditError(f"readiness evidence must be a JSON object: {relative}")
    return value, reference


def _matrix_review_drift(receipt: dict[str, Any]) -> dict[str, Any]:
    if receipt.get("schema") != matrix_review.SCHEMA or receipt.get("status") != "static_implementation_review_passed_no_execution_or_t1_credit":
        raise ReadinessAuditError("archived matrix review has an unexpected schema or status")
    rows = receipt.get("evidence")
    if not isinstance(rows, list) or not rows:
        raise ReadinessAuditError("archived matrix review has no source bindings")
    seen: set[str] = set()
    drift: list[str] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"path", "bytes", "sha256"}:
            raise ReadinessAuditError("archived matrix review has a malformed evidence binding")
        relative = row.get("path")
        if not isinstance(relative, str) or relative in seen:
            raise ReadinessAuditError("archived matrix review has a duplicate or invalid evidence path")
        seen.add(relative)
        try:
            _, current = _read_regular(relative)
        except (OSError, ReadinessAuditError):
            drift.append(relative)
            continue
        if current["bytes"] != row.get("bytes") or current["sha256"] != row.get("sha256"):
            drift.append(relative)
    return {
        "archived_verdict": receipt.get("reviewer", {}).get("verdict"),
        "archive_current": not drift,
        "binding_drift_paths": sorted(drift),
        "implementation_source_drift_paths": sorted(set(drift) & MATRIX_IMPLEMENTATION_PATHS),
        "test_binding_drift_paths": sorted(set(drift) & MATRIX_TEST_PATHS),
        "stale_review_is_counted_as_current_pass": False,
    }


def build_audit() -> dict[str, Any]:
    v4 = audit_v4.verify_audit(LAB / V4_RECEIPT)
    if v4.get("readiness_pass") is not False or v4.get("qualification_credit") != 0:
        raise ReadinessAuditError("immutable R008 readiness v4 does not retain its zero-credit hold")
    prior_codes = {item.get("code") for item in v4.get("blocking_gaps", [])}
    if "reviewed_per_case_materialization_verifier_missing" not in prior_codes:
        raise ReadinessAuditError("v4 no longer exposes the per-case verifier gap this audit reconciles")

    per_case = per_case_review.verify_receipt()
    metric = metric_review.verify_receipt()
    matrix_receipt, matrix_ref = _load_json(matrix_review.OUTPUT.relative_to(LAB))
    matrix_drift = _matrix_review_drift(matrix_receipt)
    if per_case.get("status") != "PASS":
        raise ReadinessAuditError("current per-case B/C/D implementation review is not PASS")
    if metric.get("status") != "static_metric_implementation_review_passed_no_execution_or_t1_credit":
        raise ReadinessAuditError("current metric bundle implementation review is not a zero-credit PASS")
    if not matrix_drift["test_binding_drift_paths"] or matrix_drift["implementation_source_drift_paths"]:
        raise ReadinessAuditError("expected matrix-test-only review drift was not confirmed")

    evidence = []
    for path in EVIDENCE_PATHS:
        _, reference = _read_regular(path)
        evidence.append({**reference, "role": path.as_posix()})
    evidence.sort(key=lambda item: item["path"])
    if len({item["path"] for item in evidence}) != len(evidence):
        raise ReadinessAuditError("v5 evidence inventory contains duplicate paths")

    blocking_gaps = [
        {
            "code": "matrix_implementation_review_binding_stale_after_test_update",
            "severity": "medium",
            "detail": (
                "The archived matrix review no longer matches its bound test inventory. "
                "The current matrix implementation sources still match the archive, but an "
                "added fail-closed regression test has not been included in a refreshed review."
            ),
        },
        {
            "code": "trusted_worker_execution_source_and_runtime_identity_missing",
            "severity": "high",
            "detail": (
                "The reviewed B/C/D and metric verifiers validate caller-supplied bytes and "
                "synthetic fixtures; there is still no authenticated authority issuer, trusted "
                "worker/supervisor process source, or loaded-module/runtime identity closure."
            ),
        },
        {
            "code": "real_provenance_verified_15_case_t1_results_missing",
            "severity": "high",
            "detail": (
                "No complete, provenance-verified real 15-row solver-result matrix has been "
                "evaluated. Synthetic verifier/metric tests and the one-case zero-credit "
                "CPU/native anchor are not R008 T1 evidence."
            ),
        },
        {
            "code": "native_integrity_and_solver_timestep_adjudication_missing",
            "severity": "high",
            "detail": (
                "The static metric matrix review explicitly leaves native-integrity gates, "
                "solver timestep audit adjudication, and final qualification separate and unevaluated."
            ),
        },
    ]
    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "scope_id": "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008",
        "status": "static_verifiers_present_execution_trust_and_t1_pending",
        "supersedes": {
            "path": V4_RECEIPT.as_posix(),
            "sha256": audit_v4.sha256(LAB / V4_RECEIPT),
            "reason": (
                "A Terra High source-bound per-case B/C/D verifier and reviewed v2 metric "
                "bundle verifier now exist; v4's missing-verifier blocker is replaced by "
                "execution-trust, stale-matrix-review, native-integrity, and real-result gaps."
            ),
        },
        "verifier_stack": {
            "per_case_b_c_d_bundle": {
                "schema": "core.cfd.f8.r008_per_case_bundle_verifier.v1",
                "implementation_review_status": per_case["status"],
                "review_receipt_current_for_bound_sources": True,
                "authenticates_execution_source": False,
            },
            "native_fluid_table_metric_bundle_v2": {
                "schema": "core.cfd.f8.r008_native_fluid_table_metric_bundle_verifier.v2",
                "implementation_review_status": metric["status"],
                "review_receipt_current_for_bound_sources": True,
                "adjudicates_native_integrity_or_t1": False,
            },
            "15_case_metric_matrix_v2": {
                "schema": matrix_adapter.SCHEMA,
                "archived_verdict": matrix_drift["archived_verdict"],
                "review_archive_current": matrix_drift["archive_current"],
                "review_binding_drift_paths": matrix_drift["binding_drift_paths"],
                "implementation_source_drift_paths": matrix_drift["implementation_source_drift_paths"],
                "test_binding_drift_paths": matrix_drift["test_binding_drift_paths"],
                "counts_as_current_review_pass": False,
                "adjudicates_native_integrity_or_t1": False,
            },
        },
        "execution_authority": {
            "solver": False,
            "worker": False,
            "gpu": False,
            "queue": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
        },
        "execution_controls": {
            "solver_invoked": False,
            "worker_started": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
        },
        "native_integrity_adjudicated": False,
        "solver_timestep_audit_adjudicated": False,
        "readiness_pass": False,
        "full_t1_decision": False,
        "T1_numerical": False,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "blocking_gaps": blocking_gaps,
        "evidence": evidence,
        "implementation": {
            "path": "scripts/f8_r008_execution_readiness_audit_v5.py",
            **_read_regular("scripts/f8_r008_execution_readiness_audit_v5.py")[1],
        },
        "test": {
            "path": "tests/test_f8_r008_execution_readiness_audit_v5.py",
            **_read_regular("tests/test_f8_r008_execution_readiness_audit_v5.py")[1],
        },
    }


def verify_audit(path: str | Path = OUTPUT) -> dict[str, Any]:
    receipt, _ = _load_json(Path(path))
    if receipt.get("schema") != SCHEMA or receipt != build_audit():
        raise ReadinessAuditError("R008 execution-readiness audit v5 no longer matches its pinned evidence")
    return receipt


def write_audit(path: str | Path = OUTPUT) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = LAB / target
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable R008 execution-readiness audit v5: {target}")
    payload = json.dumps(build_audit(), indent=2, sort_keys=True, allow_nan=False) + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0o644)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        raise
    return target


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the immutable R008 readiness v5 receipt once")
    arguments = parser.parse_args()
    if arguments.write:
        print(write_audit().relative_to(LAB))
    else:
        print(json.dumps(build_audit(), indent=2, sort_keys=True))
