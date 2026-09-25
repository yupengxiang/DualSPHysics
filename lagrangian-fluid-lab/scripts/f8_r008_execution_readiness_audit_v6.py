#!/usr/bin/env python3
"""Reconcile the stale R008 matrix review with the current diagnostic review v3."""
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

from scripts import f8_r008_execution_readiness_audit_v5 as audit_v5
from scripts import f8_r008_native_fluid_table_metric_review_v2 as metric_review
from scripts import f8_r008_per_case_provenance_implementation_review_v2 as per_case_review
from scripts import f8_r008_t1_metric_matrix_adapter_v4 as matrix_adapter
from scripts import f8_r008_t1_metric_matrix_review_v3 as matrix_review


ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008")
V5_RECEIPT = ROOT / "t1-execution-readiness-audit-v5/receipt.json"
OUTPUT = LAB / ROOT / "t1-execution-readiness-audit-v6/receipt.json"
SCHEMA = "core.cfd.f8.r008_execution_readiness_audit.v6"
RECORD_ID = "f8-r008-execution-readiness-audit-v6"
EXPECTED_PENDING_GAPS = {
    "trusted_worker_execution_source_and_runtime_identity_missing",
    "real_provenance_verified_15_case_t1_results_missing",
    "native_integrity_and_solver_timestep_adjudication_missing",
}
EVIDENCE_PATHS = (
    Path("scripts/f8_r008_execution_readiness_audit_v5.py"),
    Path("tests/test_f8_r008_execution_readiness_audit_v5.py"),
    Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/t1-execution-readiness-audit-v4/receipt.json"),
    Path("scripts/f8_r008_execution_readiness_audit_v4.py"),
    Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/per-case-provenance-implementation-review-v2/receipt.json"),
    Path("scripts/f8_r008_per_case_provenance_implementation_review_v2.py"),
    Path("scripts/f8_r008_per_case_bundle_verifier_v1.py"),
    Path("scripts/f8_r008_per_case_bundle_verifier_v2.py"),
    Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/native-fluid-table-schema-v2/metric-review-v2/receipt.json"),
    Path("scripts/f8_r008_native_fluid_table_metric_review_v2.py"),
    Path("scripts/f8_r008_native_fluid_table_metric_bundle_verifier_v2.py"),
    Path("scripts/f8_r008_t1_metric_adapter_v2.py"),
    Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/native-fluid-table-schema-v2/metric-matrix-review-v2/receipt.json"),
    Path("scripts/f8_r008_t1_metric_matrix_review_v2.py"),
    Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/native-fluid-table-schema-v2/metric-matrix-review-v3/receipt.json"),
    Path("scripts/f8_r008_t1_metric_matrix_review_v3.py"),
    Path("scripts/f8_r008_t1_metric_matrix_adapter_v2.py"),
    Path("scripts/f8_r008_t1_metric_matrix_adapter_v4.py"),
    Path("scripts/f8_r008_runparts_timestep_diagnostic_v1.py"),
    Path("scripts/f8_r008_runparts_timestep_diagnostic_v2.py"),
    Path("tests/test_f8_r008_t1_metric_matrix_review_v2.py"),
    Path("tests/test_f8_r008_t1_metric_matrix_review_v3.py"),
    Path("tests/test_f8_r008_t1_metric_matrix_adapter_v2.py"),
    Path("tests/test_f8_r008_runparts_timestep_diagnostic_v1.py"),
    Path("tests/test_f8_r008_runparts_timestep_diagnostic_v2.py"),
    Path("tests/test_f8_r008_native_fluid_table_metric_bundle_verifier_v2.py"),
    Path("tests/test_f8_r008_per_case_bundle_verifier_v2.py"),
    Path("tests/test_f8_r008_t1_metric_adapter_v1.py"),
    Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/t1-scope-design-v1/receipt.json"),
    Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/definition-control-pack-v1/receipt.json"),
    Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/cpu-native-preflight-v3/receipt.json"),
)
O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)


class ReadinessAuditError(ValueError):
    """The versioned R008 readiness evidence is unsafe or inconsistent."""


def _read_regular(relative: str | Path) -> tuple[bytes, dict[str, Any]]:
    path = Path(relative)
    if not path.is_absolute() and ".." in path.parts:
        raise ReadinessAuditError("readiness evidence path must remain beneath the lab root")
    target = path if path.is_absolute() else LAB / path
    descriptor = os.open(target, os.O_RDONLY | O_NOFOLLOW | O_CLOEXEC)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ReadinessAuditError(f"readiness evidence must be a single-link regular file: {path}")
        if before.st_size > audit_v5.MAX_EVIDENCE_BYTES:
            raise ReadinessAuditError(f"readiness evidence exceeds the byte limit: {path}")
        chunks: list[bytes] = []
        size = 0
        while True:
            block = os.read(descriptor, min(1024 * 1024, audit_v5.MAX_EVIDENCE_BYTES + 1 - size))
            if not block:
                break
            size += len(block)
            if size > audit_v5.MAX_EVIDENCE_BYTES:
                raise ReadinessAuditError(f"readiness evidence exceeds the byte limit: {path}")
            chunks.append(block)
        after = os.fstat(descriptor)
        named = os.stat(target, follow_symlinks=False)
        identity = lambda value: (
            value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns, value.st_nlink,
        )
        if identity(before) != identity(after) or identity(after) != identity(named) or size != before.st_size:
            raise ReadinessAuditError(f"readiness evidence changed while being read: {path}")
        payload = b"".join(chunks)
        return payload, {"path": path.as_posix(), "bytes": size, "sha256": hashlib.sha256(payload).hexdigest()}
    finally:
        os.close(descriptor)


def _load_json(relative: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    raw, reference = _read_regular(relative)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReadinessAuditError(f"readiness evidence is not strict UTF-8 JSON: {relative}") from error
    if not isinstance(value, dict):
        raise ReadinessAuditError(f"readiness evidence must be a JSON object: {relative}")
    return value, reference


def build_audit() -> dict[str, Any]:
    previous, previous_ref = _load_json(V5_RECEIPT)
    if not (
        previous.get("schema") == "core.cfd.f8.r008_execution_readiness_audit.v5"
        and previous.get("record_id") == "f8-r008-execution-readiness-audit-v5"
        and previous.get("readiness_pass") is False
        and previous.get("full_t1_decision") is False
        and previous.get("T1_numerical") is False
        and previous.get("qualification_credit") == 0
    ):
        raise ReadinessAuditError("historical R008 readiness v5 does not retain its zero-credit hold")
    prior_gaps = {item.get("code") for item in previous.get("blocking_gaps", []) if isinstance(item, dict)}
    if "matrix_implementation_review_binding_stale_after_test_update" not in prior_gaps:
        raise ReadinessAuditError("historical v5 no longer records the matrix review drift being reconciled")
    if previous["verifier_stack"]["15_case_metric_matrix_v2"].get("review_archive_current") is not False:
        raise ReadinessAuditError("historical v5 matrix review is not explicitly marked stale")

    per_case = per_case_review.verify_receipt()
    metric = metric_review.verify_receipt()
    matrix = matrix_review.verify_receipt()
    if per_case.get("status") != "PASS":
        raise ReadinessAuditError("current per-case B/C/D implementation review is not PASS")
    if metric.get("status") != "static_metric_implementation_review_passed_no_execution_or_t1_credit":
        raise ReadinessAuditError("current metric bundle implementation review is not a zero-credit PASS")
    if matrix.get("status") != "static_implementation_review_passed_no_execution_or_t1_credit":
        raise ReadinessAuditError("current parser/matrix implementation review is not a zero-credit PASS")
    if matrix.get("reviewed_scope", {}).get("execution_attempt_identity_verified") is not False:
        raise ReadinessAuditError("matrix review unexpectedly claims execution-attempt identity")

    evidence = []
    for path in EVIDENCE_PATHS:
        _, reference = _read_regular(path)
        evidence.append({**reference, "role": path.as_posix()})
    evidence.append({**previous_ref, "role": "immutable_historical_v5_readiness_receipt"})
    evidence.sort(key=lambda item: item["path"])
    if len({item["path"] for item in evidence}) != len(evidence):
        raise ReadinessAuditError("v6 evidence inventory contains duplicate paths")
    evidence.append({
        "path": "scripts/f8_r008_execution_readiness_audit_v6.py",
        **_read_regular("scripts/f8_r008_execution_readiness_audit_v6.py")[1],
        "role": "this readiness audit implementation",
    })
    evidence.append({
        "path": "tests/test_f8_r008_execution_readiness_audit_v6.py",
        **_read_regular("tests/test_f8_r008_execution_readiness_audit_v6.py")[1],
        "role": "this readiness audit tests",
    })

    blocking_gaps = [
        {
            "code": "trusted_worker_execution_source_and_runtime_identity_missing",
            "severity": "high",
            "detail": "No authenticated authority issuer, trusted worker/supervisor process source, or loaded-module/runtime identity closure exists for an F8 solver attempt.",
        },
        {
            "code": "real_provenance_verified_15_case_t1_results_missing",
            "severity": "high",
            "detail": "No complete, provenance-verified real 15-row solver-result matrix has been evaluated; synthetic diagnostics and CPU/native preflight are not R008 T1 evidence.",
        },
        {
            "code": "native_integrity_and_solver_timestep_adjudication_missing",
            "severity": "high",
            "detail": "The reviewed matrix v4 recomputes only recorded PART DtMax diagnostics; native-integrity checks, effective solver timestep adjudication, full completion, and final T1 remain separate and unevaluated.",
        },
    ]
    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "scope_id": "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008",
        "status": "static_diagnostic_matrix_reviewed_execution_trust_and_t1_pending",
        "supersedes": {
            "path": V5_RECEIPT.as_posix(),
            "sha256": previous_ref["sha256"],
            "reason": "The stale v2 matrix review is preserved as historical evidence and replaced for current review status by a source-bound Terra High PASS for the RunPARTs parser v2/matrix adapter v4; execution and T1 blockers remain.",
        },
        "historical_v5": {
            "status": previous.get("status"),
            "matrix_review_was_current": False,
            "matrix_implementation_source_drift_paths_at_v5": previous["verifier_stack"]["15_case_metric_matrix_v2"].get("implementation_source_drift_paths", []),
            "matrix_test_binding_drift_paths_at_v5": previous["verifier_stack"]["15_case_metric_matrix_v2"].get("test_binding_drift_paths", []),
            "historical_receipt_preserved": True,
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
            "15_case_metric_matrix_v4": {
                "schema": matrix_adapter.SCHEMA,
                "implementation_review_status": matrix["status"],
                "review_archive_current": True,
                "review_receipt_path": matrix_review.OUTPUT.relative_to(LAB).as_posix(),
                "review_receipt_sha256": matrix_review._file_binding(
                    matrix_review.OUTPUT.relative_to(LAB).as_posix()
                )["sha256"],
                "diagnostic_input_policy": matrix["reviewed_scope"]["diagnostic_input_policy"],
                "execution_attempt_identity_verified": False,
                "normal_completion_verified": False,
                "cross_field_native_semantics_verified": False,
                "counts_as_current_static_review_pass": True,
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
            "path": "scripts/f8_r008_execution_readiness_audit_v6.py",
            **_read_regular("scripts/f8_r008_execution_readiness_audit_v6.py")[1],
        },
        "test": {
            "path": "tests/test_f8_r008_execution_readiness_audit_v6.py",
            **_read_regular("tests/test_f8_r008_execution_readiness_audit_v6.py")[1],
        },
    }


def verify_audit(path: str | Path = OUTPUT) -> dict[str, Any]:
    receipt, _ = _load_json(Path(path))
    if receipt.get("schema") != SCHEMA or receipt != build_audit():
        raise ReadinessAuditError("R008 execution-readiness audit v6 no longer matches its pinned evidence")
    return receipt


def write_audit(path: str | Path = OUTPUT) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = LAB / target
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable R008 execution-readiness audit v6: {target}")
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
    parser.add_argument("--write", action="store_true", help="write the immutable R008 readiness v6 receipt once")
    arguments = parser.parse_args()
    if arguments.write:
        print(write_audit().relative_to(LAB))
    else:
        print(json.dumps(build_audit(), indent=2, sort_keys=True))
