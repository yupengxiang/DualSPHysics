#!/usr/bin/env python3
"""Attempt records and complete failure denominators for B2R.

This is accounting only.  It does not launch a worker, reserve a GPU, update a
shared ledger, or mark ``B2R`` in ``l2_resume``.  Every logical raw/hybrid seed
is counted exactly once in the logical-run denominator; retries remain visible
as execution attempts but cannot manufacture extra physical cases or improve a
success rate.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping
import uuid

try:
    from scripts.l2_b2r_contract import (
        ATTEMPT_SCHEMA,
        DENOMINATOR_SCHEMA,
        B2RContractError,
        StudySpec,
    )
except ModuleNotFoundError:  # direct ``python scripts/l2_b2r_prepare.py``
    from l2_b2r_contract import (
        ATTEMPT_SCHEMA,
        DENOMINATOR_SCHEMA,
        B2RContractError,
        StudySpec,
    )


ATTEMPT_STATES = frozenset({"not_started", "running", "completed", "failed"})
WORKER_EXIT_STATES = frozenset({
    "not_started",
    "running",
    "zero",
    "nonzero",
    "exception",
    "timeout",
    "guard_terminated",
})
EVALUATION_STATES = frozenset({"not_started", "running", "completed", "failed", "unknown"})
MODEL_PHYSICAL_STATES = frozenset({"not_evaluated", "pass", "fail", "unknown"})
OUTCOME_STATES = (
    "not_started",
    "worker_incomplete",
    "training_failure",
    "evaluation_failure",
    "physical_failure",
    "physical_pass",
    "physical_unknown",
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise B2RContractError(f"{field} must be a safe identifier")
    return value


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _finite_nonnegative(value: Any, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise B2RContractError(f"{field} must be a finite nonnegative number or null")
    if value < 0 or value != value or value in (float("inf"), float("-inf")):
        raise B2RContractError(f"{field} must be a finite nonnegative number or null")
    return float(value)


def create_attempt_record(
    *,
    logical_run_id: str,
    route: str,
    seed: int,
    physical_case_ids: Iterable[str],
    execution_attempt_id: str | None = None,
    status: str = "not_started",
    worker_exit_status: str = "not_started",
    training_completed: bool = False,
    evaluation_completed: bool = False,
    model_physical_pass: str = "not_evaluated",
    retry_of: str | None = None,
    data_contract_sha256: str | None = None,
    model_contract_sha256: str | None = None,
    r2_evidence_sha256: str | None = None,
    gpu_index: int | None = None,
    gpu_uuid: str | None = None,
    cpu_cores: int | None = None,
    elapsed_seconds: float | None = None,
    failure_reason: str | None = None,
    artifacts: Mapping[str, Any] | None = None,
    finished_at_utc: str | None = None,
) -> dict[str, Any]:
    """Create an immutable-shaped record before a worker is launched.

    The default ``not_started`` record is useful for registering the full
    denominator up front.  A later runner may atomically replace its own
    record with terminal facts, but this function itself never executes it.
    """

    _safe_id(logical_run_id, "logical_run_id")
    execution_attempt_id = execution_attempt_id or (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid.uuid4().hex[:8]
    )
    _safe_id(execution_attempt_id, "execution_attempt_id")
    if route not in {"raw", "hybrid"}:
        raise B2RContractError("route must be raw or hybrid")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise B2RContractError("seed must be a nonnegative integer")
    cases = list(physical_case_ids)
    if not cases or any(not isinstance(case_id, str) or not _SAFE_ID.fullmatch(case_id) for case_id in cases):
        raise B2RContractError("physical_case_ids must be a nonempty list of safe identifiers")
    if len(set(cases)) != len(cases):
        raise B2RContractError("physical_case_ids must be unique")
    if status not in ATTEMPT_STATES:
        raise B2RContractError(f"unknown attempt status: {status}")
    if worker_exit_status not in WORKER_EXIT_STATES:
        raise B2RContractError(f"unknown worker exit status: {worker_exit_status}")
    if model_physical_pass not in MODEL_PHYSICAL_STATES:
        raise B2RContractError(f"unknown model physical status: {model_physical_pass}")
    if not isinstance(training_completed, bool) or not isinstance(evaluation_completed, bool):
        raise B2RContractError("stage completion fields must be boolean")
    if retry_of is not None:
        _safe_id(retry_of, "retry_of")
    for field_name, digest in (
        ("data_contract_sha256", data_contract_sha256),
        ("model_contract_sha256", model_contract_sha256),
        ("r2_evidence_sha256", r2_evidence_sha256),
    ):
        if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise B2RContractError(f"{field_name} must be a lowercase SHA-256 or null")
    if gpu_index is not None and (isinstance(gpu_index, bool) or not isinstance(gpu_index, int) or gpu_index < 0):
        raise B2RContractError("gpu_index must be a nonnegative integer or null")
    if cpu_cores is not None and (isinstance(cpu_cores, bool) or not isinstance(cpu_cores, int) or cpu_cores < 1):
        raise B2RContractError("cpu_cores must be a positive integer or null")
    _finite_nonnegative(elapsed_seconds, "elapsed_seconds")
    if failure_reason is not None and not isinstance(failure_reason, str):
        raise B2RContractError("failure_reason must be text or null")
    record = {
        "schema": ATTEMPT_SCHEMA,
        "logical_run_id": logical_run_id,
        "execution_attempt_id": execution_attempt_id,
        "retry_of": retry_of,
        "route": route,
        "seed": seed,
        "physical_case_ids": sorted(cases),
        "status": status,
        "training_completed": training_completed,
        "worker_exit_status": worker_exit_status,
        "evaluation_completed": evaluation_completed,
        "model_physical_pass": model_physical_pass,
        "failure_reason": failure_reason,
        "data_contract_sha256": data_contract_sha256,
        "model_contract_sha256": model_contract_sha256,
        "r2_evidence_sha256": r2_evidence_sha256,
        "resource": {
            "gpu_index": gpu_index,
            "gpu_uuid": gpu_uuid,
            "cpu_cores": cpu_cores,
            "elapsed_seconds": elapsed_seconds,
        },
        "artifacts": dict(artifacts or {}),
        "created_at_utc": utc_now(),
        "finished_at_utc": finished_at_utc,
    }
    validate_attempt_record(record)
    return record


def validate_attempt_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the four independent outcome layers of one attempt."""

    if not isinstance(record, Mapping) or record.get("schema") != ATTEMPT_SCHEMA:
        raise B2RContractError("invalid B2R training attempt schema")
    _safe_id(record.get("logical_run_id"), "logical_run_id")
    _safe_id(record.get("execution_attempt_id"), "execution_attempt_id")
    if record.get("route") not in {"raw", "hybrid"}:
        raise B2RContractError("invalid training route")
    if isinstance(record.get("seed"), bool) or not isinstance(record.get("seed"), int) or record["seed"] < 0:
        raise B2RContractError("invalid training seed")
    if record.get("status") not in ATTEMPT_STATES:
        raise B2RContractError("invalid attempt lifecycle status")
    if record.get("worker_exit_status") not in WORKER_EXIT_STATES:
        raise B2RContractError("invalid worker_exit_status")
    if record.get("model_physical_pass") not in MODEL_PHYSICAL_STATES:
        raise B2RContractError("invalid model_physical_pass")
    for key in ("training_completed", "evaluation_completed"):
        if not isinstance(record.get(key), bool):
            raise B2RContractError(f"{key} must be boolean")
    cases = record.get("physical_case_ids")
    if not isinstance(cases, list) or not cases or len(set(cases)) != len(cases):
        raise B2RContractError("attempt must retain a nonempty unique physical_case_ids list")
    for case_id in cases:
        _safe_id(case_id, "physical_case_id")
    resource = record.get("resource")
    if not isinstance(resource, Mapping):
        raise B2RContractError("attempt resource block is required")
    _finite_nonnegative(resource.get("elapsed_seconds"), "resource.elapsed_seconds")
    for digest_key in ("data_contract_sha256", "model_contract_sha256", "r2_evidence_sha256"):
        digest = record.get(digest_key)
        if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise B2RContractError(f"invalid {digest_key}")
    # A physical pass is only legal after all earlier stages are complete.
    if record["model_physical_pass"] == "pass" and not (
        record["training_completed"]
        and record["worker_exit_status"] == "zero"
        and record["evaluation_completed"]
        and record["status"] == "completed"
    ):
        raise B2RContractError("model_physical_pass=pass lacks completed training/worker/evaluation facts")
    if record["status"] == "not_started" and record["worker_exit_status"] != "not_started":
        raise B2RContractError("not_started attempt must have worker_exit_status=not_started")
    if record["status"] == "running" and record["worker_exit_status"] not in {"running", "not_started"}:
        raise B2RContractError("running attempt has a terminal worker exit status")
    if record["status"] == "completed" and record["worker_exit_status"] != "zero":
        raise B2RContractError("completed attempt must have worker_exit_status=zero")
    if record["evaluation_completed"] and not (
        record["training_completed"] and record["worker_exit_status"] == "zero"
    ):
        raise B2RContractError("evaluation_completed requires completed training and a zero worker exit")
    if record["model_physical_pass"] in {"pass", "fail"} and not record["evaluation_completed"]:
        raise B2RContractError("physical verdict requires evaluation_completed=true")
    return {"valid": True, "execution_attempt_id": record["execution_attempt_id"]}


def write_attempt_record(path: str | Path, record: Mapping[str, Any], *, overwrite: bool = False) -> dict[str, Any]:
    """Write one compact record atomically; never updates a scheduler/ledger."""

    validate_attempt_record(record)
    destination = Path(path)
    if destination.exists() and not overwrite:
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(record, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n"
    temporary = destination.with_name(destination.name + ".partial")
    temporary.write_bytes(raw)
    temporary.replace(destination)
    return {"path": str(destination), "sha256": _sha256_bytes(raw), "bytes": len(raw)}


def _record_outcome(record: Mapping[str, Any] | None) -> str:
    if record is None or record.get("status") == "not_started":
        return "not_started"
    if record.get("status") == "running" or record.get("worker_exit_status") in {"running", "not_started"}:
        return "worker_incomplete"
    if not record.get("training_completed") or record.get("worker_exit_status") != "zero":
        return "training_failure"
    if not record.get("evaluation_completed"):
        return "evaluation_failure"
    physical = record.get("model_physical_pass")
    if physical == "pass":
        return "physical_pass"
    if physical == "fail":
        return "physical_failure"
    return "physical_unknown"


def _latest_attempt(records: list[Mapping[str, Any]]) -> Mapping[str, Any]:
    # Input order is not trusted; timestamps are used when available, with the
    # stable execution ID as a deterministic tie breaker.
    return max(records, key=lambda row: (str(row.get("finished_at_utc") or row.get("created_at_utc") or ""), row["execution_attempt_id"]))


def _validate_eval_rows(
    spec: StudySpec,
    evaluation_results: Iterable[Mapping[str, Any]] | None,
    attempt_records: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    expected_runs = {row["logical_run_id"] for row in spec.logical_runs}
    expected_cases = set(spec.evaluation_case_ids)
    attempts_by_id = {
        str(record["execution_attempt_id"]): record for record in attempt_records
    }
    rows: list[dict[str, Any]] = []
    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in evaluation_results or ():
        if not isinstance(raw, Mapping):
            raise B2RContractError("evaluation result must be a mapping")
        logical_run_id = raw.get("logical_run_id")
        physical_case_id = raw.get("physical_case_id")
        execution_attempt_id = raw.get("execution_attempt_id")
        _safe_id(logical_run_id, "evaluation.logical_run_id")
        _safe_id(physical_case_id, "evaluation.physical_case_id")
        _safe_id(execution_attempt_id, "evaluation.execution_attempt_id")
        if logical_run_id not in expected_runs or physical_case_id not in expected_cases:
            raise B2RContractError("evaluation row is outside the declared B2R denominator")
        attempt = attempts_by_id.get(execution_attempt_id)
        if attempt is None:
            raise B2RContractError("evaluation row is not bound to a recorded training attempt")
        if attempt.get("logical_run_id") != logical_run_id:
            raise B2RContractError("evaluation row is bound to a different logical run")
        key = (logical_run_id, physical_case_id)
        if key in lookup:
            raise B2RContractError("duplicate logical-run/physical-case evaluation row")
        status = raw.get("status")
        if status not in {"completed", "failed", "unknown"}:
            raise B2RContractError("evaluation status must be completed, failed, or unknown")
        physical = raw.get("model_physical_pass", "unknown")
        if physical not in {"pass", "fail", "unknown"}:
            raise B2RContractError("invalid evaluation physical verdict")
        if status in {"completed", "unknown"} and not (
            attempt.get("training_completed")
            and attempt.get("worker_exit_status") == "zero"
            and attempt.get("evaluation_completed")
        ):
            raise B2RContractError(
                "completed/unknown evaluation row lacks completed training and evaluation facts"
            )
        row = {
            "logical_run_id": logical_run_id,
            "physical_case_id": physical_case_id,
            "execution_attempt_id": execution_attempt_id,
            "status": status,
            "model_physical_pass": physical,
            "failure_reason": raw.get("failure_reason"),
        }
        lookup[key] = row
        rows.append(row)
    return rows, lookup


def build_failure_denominator(
    spec: StudySpec,
    records: Iterable[Mapping[str, Any]],
    *,
    evaluation_results: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compute logical-run and evaluation-case denominators without omission."""

    record_list = [dict(record) for record in records]
    for record in record_list:
        validate_attempt_record(record)
    expected_runs = {row["logical_run_id"] for row in spec.logical_runs}
    grouped: dict[str, list[dict[str, Any]]] = {run_id: [] for run_id in expected_runs}
    extra: list[str] = []
    for record in record_list:
        logical_run_id = record["logical_run_id"]
        if logical_run_id not in grouped:
            extra.append(logical_run_id)
            continue
        if sorted(record["physical_case_ids"]) != sorted(spec.evaluation_case_ids):
            raise B2RContractError(
                f"attempt {record['execution_attempt_id']} does not retain the full physical-case denominator"
            )
        grouped[logical_run_id].append(record)
    if extra:
        raise B2RContractError("attempts outside the declared logical-run matrix: " + ", ".join(sorted(set(extra))))

    logical_rows = []
    for logical_run in spec.logical_runs:
        run_id = logical_run["logical_run_id"]
        attempts = grouped[run_id]
        latest = _latest_attempt(attempts) if attempts else None
        logical_rows.append(
            {
                "logical_run_id": run_id,
                "route": logical_run["route"],
                "seed": logical_run["seed"],
                "attempt_count": len(attempts),
                "retry_count": max(0, len(attempts) - 1),
                "attempt_ids": [row["execution_attempt_id"] for row in attempts],
                "latest_attempt_id": latest["execution_attempt_id"] if latest else None,
                "outcome": _record_outcome(latest),
            }
        )
    outcome_counts = {outcome: sum(row["outcome"] == outcome for row in logical_rows) for outcome in OUTCOME_STATES}

    eval_rows, lookup = _validate_eval_rows(spec, evaluation_results, record_list)
    expected_eval_rows = []
    for logical_run in spec.logical_runs:
        for physical_case_id in spec.evaluation_case_ids:
            row = lookup.get((logical_run["logical_run_id"], physical_case_id))
            expected_eval_rows.append(
                row
                if row is not None
                else {
                    "logical_run_id": logical_run["logical_run_id"],
                    "physical_case_id": physical_case_id,
                    "status": "missing",
                    "model_physical_pass": "unknown",
                    "failure_reason": "no evaluation result recorded",
                }
            )
    eval_statuses = {"completed_pass", "completed_fail", "failed", "unknown", "missing"}
    evaluation_counts = {key: 0 for key in sorted(eval_statuses)}
    for row in expected_eval_rows:
        if row["status"] == "completed" and row["model_physical_pass"] == "pass":
            key = "completed_pass"
        elif row["status"] == "completed" and row["model_physical_pass"] == "fail":
            key = "completed_fail"
        elif row["status"] == "failed":
            key = "failed"
        elif row["status"] == "unknown":
            key = "unknown"
        else:
            key = "missing"
        evaluation_counts[key] += 1

    logical_complete = all(
        row["outcome"] not in {"not_started", "worker_incomplete"} for row in logical_rows
    )
    denominator_complete = logical_complete and evaluation_counts["missing"] == 0
    denominator = {
        "schema": DENOMINATOR_SCHEMA,
        "study_id": spec.study_id,
        "status": "complete" if denominator_complete else "incomplete",
        "logical_run_denominator": {
            "unit": "unique logical raw/hybrid seed run",
            "planned": len(spec.logical_runs),
            "observed_attempt_records": len(record_list),
            "retries_included_as_attempts": True,
            "retries_excluded_from_planned_denominator": True,
            "outcome_counts": outcome_counts,
            "failure_count": len(logical_rows) - outcome_counts["physical_pass"],
            "rows": logical_rows,
        },
        "evaluation_case_denominator": {
            "unit": "logical_run x unique physical_case_id",
            "physical_case_count": len(spec.evaluation_case_ids),
            "logical_run_count": len(spec.logical_runs),
            "planned_case_run_count": len(expected_eval_rows),
            "observed_case_run_records": len(eval_rows),
            "status_counts": evaluation_counts,
            "all_missing_and_failed_rows_retained": True,
            "complete_only_when_no_case_run_is_missing": True,
            "rows": expected_eval_rows,
        },
        "no_model_qualification_claim": True,
        "r2_dependency": spec.r2_gate.as_dict(),
    }
    validate_failure_denominator(denominator)
    return denominator


def validate_failure_denominator(denominator: Mapping[str, Any]) -> dict[str, Any]:
    if denominator.get("schema") != DENOMINATOR_SCHEMA:
        raise B2RContractError("invalid failure denominator schema")
    logical = denominator.get("logical_run_denominator", {})
    planned = logical.get("planned")
    rows = logical.get("rows", [])
    counts = logical.get("outcome_counts", {})
    if not isinstance(planned, int) or planned != len(rows) or sum(counts.values()) != planned:
        raise B2RContractError("logical failure denominator does not cover every planned run")
    if logical.get("failure_count") != planned - counts.get("physical_pass", 0):
        raise B2RContractError("logical failure count is inconsistent")
    evaluation = denominator.get("evaluation_case_denominator", {})
    eval_rows = evaluation.get("rows", [])
    status_counts = evaluation.get("status_counts", {})
    if evaluation.get("planned_case_run_count") != len(eval_rows) or sum(status_counts.values()) != len(eval_rows):
        raise B2RContractError("evaluation denominator omits a case-run row")
    return {
        "valid": True,
        "logical_planned": planned,
        "logical_failures": logical["failure_count"],
        "evaluation_case_runs": len(eval_rows),
        "evaluation_missing": status_counts.get("missing", 0),
    }
