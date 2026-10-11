#!/usr/bin/env python3
"""Forward-only admission wrapper for the bounded upstream-first M4 batch.

The consumed v6 runtime owns execution, UUID leases, parent reservations,
single-heavy-task admission, NAS checks, Home-floor checks, and terminal
receipts.  This module adds the next-batch boundary without changing v6 or
the shared ledger: a root-issued, self-hashed admission must bind completed
M1--M3 evidence and an exact historical ledger baseline before v6 is called.

Batch 2 has its own 24 GPU-hour, 96 CPU-core-hour, 24-solver-attempt, and
bounded additional-storage allowance.  Those are an incremental allowance;
the parent ledger limits and live guards remain authoritative.  A separate
immutable root grant binds each concrete request after the batch audit, so
later conversion/solver requests do not require mutating the admission.  The
wrapper creates neither artifact, resets no counters, promotes no requests,
and launches no request without both artifacts.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Iterator, Mapping

import ds_data02_runtime_v6 as v6


DATA_ROOT = v6.DATA_ROOT
RUNTIME_PATH = str(Path(__file__).resolve())
ADMISSION_SCHEMA = "ds02.upstream-first.batch-admission.v1"
GRANT_SCHEMA = "ds02.upstream-first.batch-request-grant.v1"
MILESTONE_EVIDENCE_SCHEMA = "ds02.upstream-first.milestone-evidence.v1"
COST_AUDIT_SCHEMA = "ds02.upstream.cost-audit.v1"
BATCH_INDEX = 2
PREVIOUS_BATCH_INDEX = 1
BATCH_GPU_SECONDS = 24 * 3600
BATCH_CPU_CORE_SECONDS = 96 * 3600
BATCH_SOLVER_ATTEMPTS = 24
# A root admission may choose a smaller bound for the actual M4 product.  The
# explicit operational ceiling leaves room for a four-condition portable
# product while preventing an artifact from turning the incremental storage
# allowance into an unbounded parent-budget bypass.  Persistent bytes remain
# in the parent ledger; this is never a batch reset.
MAX_ADDITIONAL_STORAGE_BYTES = 256 * 1024**3
TERMINAL_RECEIPT_STATUSES = {"completed", "complete", "accepted", "passed", "verified"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PARENT_RESOURCE_KEYS = (
    "gpu_seconds",
    "cpu_core_seconds",
    "new_storage_bytes",
    "qualification_attempts",
    "production_attempts",
)
PARENT_POLICY_KEYS = (
    "storage_policy",
    "home_min_free_bytes",
    "home_path",
)


class BatchAdmissionError(RuntimeError):
    """Raised when the root-issued batch boundary cannot be verified."""


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise BatchAdmissionError(f"admission is not canonical JSON: {error}") from error


def _payload_hash(admission: Mapping[str, Any]) -> str:
    payload = deepcopy(dict(admission))
    payload.pop("payload_sha256", None)
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _sha256_file(path: Path) -> str:
    if path.is_symlink():
        raise BatchAdmissionError(f"refusing to hash a symlink: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as error:
        raise BatchAdmissionError(f"cannot hash {path}: {error}") from error
    return digest.hexdigest()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise BatchAdmissionError(f"{label} must be a regular non-symlink file: {path}")

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant {value}")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicate_keys,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise BatchAdmissionError(f"{label} is not valid JSON: {path}") from error
    if not isinstance(value, dict):
        raise BatchAdmissionError(f"{label} must be a JSON object")
    return value


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise BatchAdmissionError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _require_nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BatchAdmissionError(f"{label} must be a non-negative integer")
    return value


def _require_positive_int(value: Any, label: str) -> int:
    number = _require_nonnegative_int(value, label)
    if number == 0:
        raise BatchAdmissionError(f"{label} must be positive")
    return number


def _normalised_path(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise BatchAdmissionError(f"{label} must be an absolute path")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise BatchAdmissionError(f"{label} must be absolute")
    if path.is_symlink():
        raise BatchAdmissionError(f"{label} must not be a symlink")
    return path.resolve()


def _require_exact_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise BatchAdmissionError(f"{label} must be a list of non-empty strings")
    if value != sorted(set(value)):
        raise BatchAdmissionError(f"{label} must be sorted and unique")
    return value


def _row_hash(row: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(dict(row))).hexdigest()


def _rows_projection_hash(rows: list[Mapping[str, Any]]) -> str:
    ordered = sorted((dict(row) for row in rows), key=lambda row: row.get("id", ""))
    return hashlib.sha256(_canonical_json(ordered)).hexdigest()


def _usage(rows: list[Mapping[str, Any]]) -> dict[str, float | int]:
    return {
        key: sum(row.get(key, 0) for row in rows)
        for key in ("gpu_seconds", "cpu_core_seconds", "new_storage_bytes")
    }


def _upstream_attempt_id(value: Any) -> bool:
    return v6._upstream_id(value)


def _validate_evidence(admission: Mapping[str, Any]) -> None:
    evidence = admission.get("evidence")
    if not isinstance(evidence, dict):
        raise BatchAdmissionError("admission evidence is missing")
    for milestone in ("M1", "M2", "M3"):
        item = evidence.get(milestone)
        if not isinstance(item, dict):
            raise BatchAdmissionError(f"{milestone} evidence is missing")
        if item.get("status") != "complete":
            raise BatchAdmissionError(f"{milestone} evidence is not complete")
        if item.get("acceptance_status") != "accepted":
            raise BatchAdmissionError(f"{milestone} evidence is not accepted")
        path = _normalised_path(item.get("path"), f"{milestone} evidence path")
        expected = _require_sha256(item.get("sha256"), f"{milestone} evidence hash")
        actual = _sha256_file(path)
        if actual != expected:
            raise BatchAdmissionError(f"{milestone} evidence hash mismatch")
        certificate = _read_json(path, f"{milestone} milestone certificate")
        if certificate.get("schema") != MILESTONE_EVIDENCE_SCHEMA:
            raise BatchAdmissionError(f"{milestone} evidence certificate schema is unsupported")
        if certificate.get("milestone") != milestone or certificate.get("status") != "complete":
            raise BatchAdmissionError(f"{milestone} evidence certificate is incomplete")
        if certificate.get("acceptance_status") != "accepted":
            raise BatchAdmissionError(f"{milestone} evidence certificate is not accepted")
        receipts = certificate.get("receipts")
        if not isinstance(receipts, list) or not receipts:
            raise BatchAdmissionError(f"{milestone} evidence has no bound receipts")
        seen_receipts: set[Path] = set()
        for index, binding in enumerate(receipts):
            if not isinstance(binding, dict):
                raise BatchAdmissionError(f"{milestone} receipt binding {index} is invalid")
            receipt_path = _normalised_path(binding.get("path"), f"{milestone} receipt path")
            if receipt_path in seen_receipts or receipt_path == path:
                raise BatchAdmissionError(f"{milestone} receipt binding is duplicated or self-referential")
            seen_receipts.add(receipt_path)
            receipt_hash = _require_sha256(binding.get("sha256"), f"{milestone} receipt hash")
            if _sha256_file(receipt_path) != receipt_hash:
                raise BatchAdmissionError(f"{milestone} receipt hash mismatch")
            receipt = _read_json(receipt_path, f"{milestone} bound receipt")
            if receipt.get("status") not in TERMINAL_RECEIPT_STATUSES:
                raise BatchAdmissionError(f"{milestone} bound receipt is not terminal")
            if binding.get("status") != receipt.get("status"):
                raise BatchAdmissionError(f"{milestone} receipt status binding differs")


def _validate_cost_audit(admission: Mapping[str, Any]) -> None:
    cost_audit = admission.get("cost_audit")
    if not isinstance(cost_audit, dict) or cost_audit.get("status") != "complete":
        raise BatchAdmissionError("M1-M3 cost audit is missing or incomplete")
    if cost_audit.get("acceptance_status") != "accepted":
        raise BatchAdmissionError("M1-M3 cost audit is not accepted")
    cost_path = _normalised_path(cost_audit.get("path"), "cost audit path")
    expected = _require_sha256(cost_audit.get("sha256"), "cost audit hash")
    if _sha256_file(cost_path) != expected:
        raise BatchAdmissionError("cost audit hash mismatch")
    audit = _read_json(cost_path, "M1-M3 cost audit")
    if audit.get("schema") != COST_AUDIT_SCHEMA or audit.get("status") != "complete":
        raise BatchAdmissionError("M1-M3 cost audit certificate is incomplete")
    if audit.get("acceptance_status") != "accepted":
        raise BatchAdmissionError("M1-M3 cost audit certificate is not accepted")
    if audit.get("charged_ids") != admission.get("prior_charged_ids"):
        raise BatchAdmissionError("M1-M3 cost audit charged ids differ from the preserved baseline")
    if audit.get("prior_usage") != admission.get("prior_usage"):
        raise BatchAdmissionError("M1-M3 cost audit baseline differs from the preserved usage")


def _validate_baseline_shape(admission: Mapping[str, Any]) -> tuple[list[str], dict[str, str], list[str], dict[str, str]]:
    ids = _require_exact_list(admission.get("prior_charged_ids"), "prior_charged_ids")
    charge_hashes = admission.get("prior_charge_row_sha256")
    if not isinstance(charge_hashes, dict):
        raise BatchAdmissionError("prior charge row hashes are missing")
    if set(charge_hashes) != set(ids):
        raise BatchAdmissionError("prior charge ids and row hashes differ")
    for attempt_id, digest in charge_hashes.items():
        _require_sha256(digest, f"prior charge hash {attempt_id}")

    attempt_ids = _require_exact_list(admission.get("prior_attempt_ids"), "prior_attempt_ids")
    attempt_hashes = admission.get("prior_attempt_row_sha256")
    if not isinstance(attempt_hashes, dict):
        raise BatchAdmissionError("prior attempt row hashes are missing")
    if set(attempt_hashes) != set(attempt_ids):
        raise BatchAdmissionError("prior attempt ids and row hashes differ")
    for attempt_id, digest in attempt_hashes.items():
        _require_sha256(digest, f"prior attempt hash {attempt_id}")
    if admission.get("prior_reservation_ids") != []:
        raise BatchAdmissionError("M4 admission requires an empty prior reservation set")

    prior_usage = admission.get("prior_usage")
    if not isinstance(prior_usage, dict):
        raise BatchAdmissionError("prior usage baseline is missing")
    for key in ("gpu_seconds", "cpu_core_seconds", "new_storage_bytes"):
        value = prior_usage.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise BatchAdmissionError(f"prior usage {key} is invalid")
    _require_sha256(admission.get("prior_charges_sha256"), "prior charges projection hash")
    return ids, charge_hashes, attempt_ids, attempt_hashes


def validate_admission(admission_path: Path, *, data_root: Path = DATA_ROOT) -> dict[str, Any]:
    """Verify the immutable root artifact and its real evidence files."""
    path = Path(admission_path).expanduser()
    if path.is_symlink():
        raise BatchAdmissionError("batch admission must not be a symlink")
    path = path.resolve()
    admission = _read_json(path, "batch admission")
    if admission.get("schema") != ADMISSION_SCHEMA:
        raise BatchAdmissionError("unsupported batch admission schema")
    if admission.get("status") != "admitted" or admission.get("issuer") != "root":
        raise BatchAdmissionError("batch admission is not root-issued and admitted")
    if admission.get("immutable") is not True:
        raise BatchAdmissionError("batch admission is not immutable")
    if admission.get("batch_index") != BATCH_INDEX or admission.get("previous_batch_index") != PREVIOUS_BATCH_INDEX:
        raise BatchAdmissionError("batch admission is not the forward batch-2 boundary")
    payload_hash = _require_sha256(admission.get("payload_sha256"), "admission payload hash")
    if _payload_hash(admission) != payload_hash:
        raise BatchAdmissionError("batch admission payload hash mismatch")
    _validate_baseline_shape(admission)
    _validate_evidence(admission)
    _validate_cost_audit(admission)

    limits = admission.get("batch_limits")
    if not isinstance(limits, dict):
        raise BatchAdmissionError("batch limits are missing")
    if limits.get("gpu_seconds") != BATCH_GPU_SECONDS:
        raise BatchAdmissionError("batch-2 GPU allowance is not 24 hours")
    if limits.get("cpu_core_seconds") != BATCH_CPU_CORE_SECONDS:
        raise BatchAdmissionError("batch-2 CPU allowance is not 96 core-hours")
    if limits.get("solver_attempts") != BATCH_SOLVER_ATTEMPTS:
        raise BatchAdmissionError("batch-2 solver allowance is not 24 attempts")
    additional_storage = _require_positive_int(
        limits.get("additional_storage_bytes"), "batch-2 additional storage allowance"
    )
    if additional_storage > MAX_ADDITIONAL_STORAGE_BYTES:
        raise BatchAdmissionError("batch-2 additional storage allowance exceeds the hard bound")

    ledger_path = _normalised_path(admission.get("parent_ledger_path"), "parent ledger path")
    expected_ledger = (Path(data_root).expanduser().resolve() / "runtime" / "resource-ledger.json")
    if ledger_path != expected_ledger:
        raise BatchAdmissionError("admission is bound to a different shared ledger")
    parent_limits = admission.get("parent_limits")
    if not isinstance(parent_limits, dict):
        raise BatchAdmissionError("parent limits baseline is missing")
    for key in PARENT_RESOURCE_KEYS:
        value = parent_limits.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise BatchAdmissionError(f"parent limit {key} is invalid")
    for key in PARENT_POLICY_KEYS:
        if key not in parent_limits:
            raise BatchAdmissionError(f"parent policy {key} is missing")
    deadline = admission.get("parent_deadline_utc")
    if not isinstance(deadline, str):
        raise BatchAdmissionError("parent deadline baseline is missing")
    try:
        datetime.fromisoformat(deadline)
    except ValueError as error:
        raise BatchAdmissionError("parent deadline baseline is invalid") from error

    return admission


def _live_parent_limits_match(ledger: Mapping[str, Any], admission: Mapping[str, Any]) -> None:
    expected = admission["parent_limits"]
    actual = ledger.get("limits")
    if not isinstance(actual, dict):
        raise BatchAdmissionError("shared ledger limits are missing")
    if actual != expected:
        changed = sorted(set(actual) | set(expected))
        key = next((name for name in changed if actual.get(name) != expected.get(name)), "unknown")
        raise BatchAdmissionError(f"shared parent limit changed after admission: {key}")
    if ledger.get("deadline_utc") != admission["parent_deadline_utc"]:
        raise BatchAdmissionError("shared parent deadline changed after admission")


def _baseline_rows_match(
    ledger: Mapping[str, Any], admission: Mapping[str, Any]
) -> tuple[set[str], set[str]]:
    prior_charge_ids, prior_charge_hashes, prior_attempt_ids, prior_attempt_hashes = _validate_baseline_shape(admission)
    charges = ledger.get("charges")
    attempts = ledger.get("attempts")
    reservations = ledger.get("reservations")
    if not isinstance(charges, list) or not isinstance(attempts, list) or not isinstance(reservations, list):
        raise BatchAdmissionError("shared ledger lists are malformed")

    charge_by_id: dict[str, Mapping[str, Any]] = {}
    for row in charges:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise BatchAdmissionError("shared ledger contains a malformed charge")
        if row["id"] in charge_by_id:
            raise BatchAdmissionError("shared ledger contains duplicate charge ids")
        charge_by_id[row["id"]] = row
    for attempt_id in prior_charge_ids:
        row = charge_by_id.get(attempt_id)
        if row is None or _row_hash(row) != prior_charge_hashes[attempt_id]:
            raise BatchAdmissionError(f"historical charge baseline changed: {attempt_id}")

    attempt_by_id: dict[str, Mapping[str, Any]] = {}
    for row in attempts:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise BatchAdmissionError("shared ledger contains a malformed attempt")
        if row["id"] in attempt_by_id:
            raise BatchAdmissionError("shared ledger contains duplicate attempt ids")
        attempt_by_id[row["id"]] = row
    for attempt_id in prior_attempt_ids:
        row = attempt_by_id.get(attempt_id)
        if row is None or _row_hash(row) != prior_attempt_hashes[attempt_id]:
            raise BatchAdmissionError(f"historical attempt baseline changed: {attempt_id}")

    # M4 admission is only issued after the first tranche is quiescent.  New
    # reservations that appear after admission are permitted only when they
    # are upstream rows consumed by this wrapper.  This lets v6 retain its
    # normal light-task concurrency while rejecting an unrelated launcher.
    prior_reservation_ids = admission.get("prior_reservation_ids")
    if prior_reservation_ids != []:
        raise BatchAdmissionError("historical reservations must be empty at M4 admission")
    for row in reservations:
        if not isinstance(row, dict) or not _upstream_attempt_id(row.get("id")):
            raise BatchAdmissionError("post-admission reservation is outside the UF namespace")

    expected_usage = admission["prior_usage"]
    actual_usage = _usage([charge_by_id[item] for item in prior_charge_ids])
    for key in actual_usage:
        # Charge row hashes above enforce exact historical preservation. Float
        # addition can differ after sorting the same thousands of rows by id.
        equal = (actual_usage[key] == expected_usage[key]) if key == "new_storage_bytes" else math.isclose(
            actual_usage[key], expected_usage[key], rel_tol=1e-12, abs_tol=1e-8
        )
        if not equal:
            raise BatchAdmissionError(f"historical usage baseline changed: {key}")
    if _rows_projection_hash([charge_by_id[item] for item in prior_charge_ids]) != admission["prior_charges_sha256"]:
        raise BatchAdmissionError("historical charge projection hash changed")
    return set(prior_charge_ids), set(prior_attempt_ids)


def validate_request_grant(
    grant_path: Path,
    *,
    admission_path: Path,
    admission: Mapping[str, Any],
    request_path: Path,
) -> dict[str, Any]:
    """Verify one immutable root grant created after the batch admission.

    The batch admission deliberately does not enumerate future conversion or
    solver request files.  Each concrete request therefore needs its own
    root-signed-by-convention grant that binds the request bytes and the
    admission payload hash; adding a request never changes the cumulative
    baseline or batch counters.
    """
    path = Path(grant_path).expanduser()
    if path.is_symlink():
        raise BatchAdmissionError("batch request grant must not be a symlink")
    path = path.resolve()
    grant = _read_json(path, "batch request grant")
    if grant.get("schema") != GRANT_SCHEMA:
        raise BatchAdmissionError("unsupported batch request grant schema")
    if grant.get("status") != "granted" or grant.get("issuer") != "root":
        raise BatchAdmissionError("batch request grant is not root-issued and granted")
    if grant.get("immutable") is not True:
        raise BatchAdmissionError("batch request grant is not immutable")
    if grant.get("batch_index") != BATCH_INDEX:
        raise BatchAdmissionError("batch request grant is outside batch 2")
    payload_hash = _require_sha256(grant.get("payload_sha256"), "grant payload hash")
    if _payload_hash(grant) != payload_hash:
        raise BatchAdmissionError("batch request grant payload hash mismatch")
    expected_admission = _normalised_path(str(admission_path), "batch admission path")
    bound_admission = _normalised_path(grant.get("admission_path"), "grant admission path")
    if bound_admission != expected_admission:
        raise BatchAdmissionError("grant binds a different batch admission path")
    if grant.get("admission_payload_sha256") != admission.get("payload_sha256"):
        raise BatchAdmissionError("grant binds a different batch admission payload")
    expected_request = _normalised_path(str(request_path), "batch request path")
    bound_request = _normalised_path(grant.get("request_path"), "grant request path")
    if bound_request != expected_request:
        raise BatchAdmissionError("grant binds a different request path")
    expected_request_hash = _require_sha256(grant.get("request_sha256"), "grant request hash")
    if _sha256_file(expected_request) != expected_request_hash:
        raise BatchAdmissionError("request changed after root grant")
    attempt_id = grant.get("attempt_id")
    if not isinstance(attempt_id, str) or not _upstream_attempt_id(attempt_id):
        raise BatchAdmissionError("grant has an unsafe upstream attempt id")
    return grant


def _validate_request_binding(
    request_path: Path,
    request: Mapping[str, Any],
    *,
    grant_path: Path,
    admission_path: Path,
    admission: Mapping[str, Any],
) -> dict[str, Any]:
    attempt_id = f"{request.get('family_id')}/{request.get('case_id')}/{request.get('attempt_id')}"
    if not _upstream_attempt_id(attempt_id):
        raise BatchAdmissionError("batch-2 wrapper accepts only UF_ upstream attempts")
    grant = validate_request_grant(
        grant_path,
        admission_path=admission_path,
        admission=admission,
        request_path=request_path,
    )
    if grant["attempt_id"] != attempt_id:
        raise BatchAdmissionError("request identity differs from root grant")
    if request.get("output_storage") not in {"upstream_nas", "home"}:
        raise BatchAdmissionError("request has an unsupported output storage policy")
    return grant


def _load_and_validate(admission_path: Path, *, data_root: Path) -> dict[str, Any]:
    admission = validate_admission(admission_path, data_root=data_root)
    # The second hash read protects the closure used by v6 from a path swap
    # between request preflight and the shared-ledger lock.
    current = validate_admission(admission_path, data_root=data_root)
    if current.get("payload_sha256") != admission.get("payload_sha256"):
        raise BatchAdmissionError("batch admission changed during preflight")
    return current


def _post_admission_rows(ledger: Mapping[str, Any], prior_charge_ids: set[str]) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    for collection in (ledger.get("charges", []), ledger.get("reservations", [])):
        for row in collection:
            row_id = row.get("id")
            if row_id in prior_charge_ids:
                continue
            if not _upstream_attempt_id(row_id):
                raise BatchAdmissionError(f"post-admission row is outside the UF batch namespace: {row_id}")
            rows.append(row)
    return rows


def _check_batch2(ledger: Mapping[str, Any], reservation: Mapping[str, Any], request: Mapping[str, Any], admission: Mapping[str, Any]) -> None:
    _live_parent_limits_match(ledger, admission)
    prior_charge_ids, prior_attempt_ids = _baseline_rows_match(ledger, admission)
    attempt_id = reservation.get("id")
    if not _upstream_attempt_id(attempt_id):
        raise BatchAdmissionError("batch-2 reservation must be an upstream UF attempt")
    rows = _post_admission_rows(ledger, prior_charge_ids)
    caps = {
        "gpu_seconds": BATCH_GPU_SECONDS,
        "cpu_core_seconds": BATCH_CPU_CORE_SECONDS,
        "new_storage_bytes": admission["batch_limits"]["additional_storage_bytes"],
    }
    for key, cap in caps.items():
        used = sum(row.get(key, 0) for row in rows)
        if used + reservation[key] > cap:
            raise RuntimeError(f"upstream batch-2 allocation exhausted: {key}")

    prior_attempt_set = prior_attempt_ids
    attempt_rows = []
    for row in ledger.get("attempts", []):
        if row.get("id") in prior_attempt_set:
            continue
        if not _upstream_attempt_id(row.get("id")):
            raise BatchAdmissionError("post-admission attempt is outside the UF namespace")
        attempt_rows.append(row)
    new_solver_attempts = sum(row.get("kind") in {"qualification", "production"} for row in attempt_rows)
    if reservation.get("kind") in {"qualification", "production"} and new_solver_attempts >= BATCH_SOLVER_ATTEMPTS:
        raise RuntimeError("upstream batch-2 solver attempt cap reached")

    heavy = lambda row: row.get("kind") in {"qualification", "production"} or row.get("cpu_task_kind") == "conversion"
    if heavy(reservation) and any(heavy(row) for row in ledger.get("reservations", [])):
        raise RuntimeError("upstream single heavy-task queue is occupied")

    parent_rows = list(ledger.get("charges", [])) + list(ledger.get("reservations", []))
    for key in ("gpu_seconds", "cpu_core_seconds"):
        parent_used = sum(row.get(key, 0) for row in parent_rows)
        if parent_used + reservation[key] > admission["parent_limits"][key]:
            raise RuntimeError(f"parent budget exhausted: {key}")
    # Under Home-floor accounting, the legacy cumulative byte field is not an
    # active parent cap.  v6 instead enforces live Home statvfs minus every
    # ledger reservation.  Keep that policy intact; only the incremental
    # batch-2 storage bound above applies here.  Non-Home policies retain the
    # parent's cumulative byte ceiling.
    if admission["parent_limits"].get("storage_policy") != "home_free_floor":
        parent_used = sum(row.get("new_storage_bytes", 0) for row in parent_rows)
        if parent_used + reservation["new_storage_bytes"] > admission["parent_limits"]["new_storage_bytes"]:
            raise RuntimeError("parent budget exhausted: new_storage_bytes")

    if request.get("output_storage") == "upstream_nas":
        reserved = v6._nas_reserved_bytes(ledger, exclude_id=reservation["id"])
        if v6._nas_available() - reserved < reservation["new_storage_bytes"] + v6.NAS_HEADROOM_FLOOR_BYTES:
            raise RuntimeError("insufficient upstream NAS headroom")


def _terminal_batch2(
    ledger: Mapping[str, Any],
    reservation: Mapping[str, Any],
    *,
    gpu_seconds: float,
    cpu_core_seconds: float,
    storage_bytes: int,
    admission: Mapping[str, Any],
) -> dict[str, Any] | None:
    _live_parent_limits_match(ledger, admission)
    prior_charge_ids, _ = _baseline_rows_match(ledger, admission)
    rows = [
        row for row in _post_admission_rows(ledger, prior_charge_ids)
        if row.get("id") != reservation.get("id")
    ]
    measured = {
        "gpu_seconds": gpu_seconds,
        "cpu_core_seconds": cpu_core_seconds,
        "new_storage_bytes": storage_bytes,
    }
    batch_caps = {
        "gpu_seconds": BATCH_GPU_SECONDS,
        "cpu_core_seconds": BATCH_CPU_CORE_SECONDS,
        "new_storage_bytes": admission["batch_limits"]["additional_storage_bytes"],
    }
    parent_caps = {
        key: admission["parent_limits"][key]
        for key in ("gpu_seconds", "cpu_core_seconds")
    }
    if admission["parent_limits"].get("storage_policy") != "home_free_floor":
        parent_caps["new_storage_bytes"] = admission["parent_limits"]["new_storage_bytes"]
    overrun: dict[str, Any] = {}
    parent_rows = [
        row
        for collection in (ledger.get("charges", []), ledger.get("reservations", []))
        for row in collection
        if row.get("id") != reservation.get("id")
    ]
    for scope, caps in (("batch2", batch_caps), ("parent", parent_caps)):
        details = {}
        for key, cap in caps.items():
            source_rows = rows if scope == "batch2" else parent_rows
            used_before = sum(row.get(key, 0) for row in source_rows)
            total = used_before + measured[key]
            if total > cap:
                details[key] = {
                    "used_before": used_before,
                    "measured": measured[key],
                    "cap": cap,
                    "excess": total - cap,
                }
        if details:
            overrun[scope] = details
    return overrun or None


@contextmanager
def _bind_v6_guards(
    admission_path: Path,
    admission: Mapping[str, Any],
    *,
    grant_path: Path,
    grant: Mapping[str, Any],
    data_root: Path,
) -> Iterator[None]:
    """Install guards only for this in-process v6 call, then restore v6."""
    saved_check = v6._check_upstream_batch
    saved_terminal = v6._terminal_upstream_overrun
    saved_receipt = v6._guarded_atomic_json

    def check(ledger: Mapping[str, Any], reservation: Mapping[str, Any], request: Mapping[str, Any]) -> None:
        current = validate_admission(admission_path, data_root=data_root)
        if current.get("payload_sha256") != admission.get("payload_sha256"):
            raise BatchAdmissionError("batch admission changed before reservation")
        _check_batch2(ledger, reservation, request, current)

    def terminal(
        ledger: Mapping[str, Any],
        reservation: Mapping[str, Any],
        *,
        gpu_seconds: float,
        cpu_core_seconds: float,
        storage_bytes: int,
    ) -> dict[str, Any] | None:
        current = validate_admission(admission_path, data_root=data_root)
        if current.get("payload_sha256") != admission.get("payload_sha256"):
            raise BatchAdmissionError("batch admission changed before terminal charge")
        return _terminal_batch2(
            ledger,
            reservation,
            gpu_seconds=gpu_seconds,
            cpu_core_seconds=cpu_core_seconds,
            storage_bytes=storage_bytes,
            admission=current,
        )

    def receipt(path: Path, value: dict[str, Any]) -> Any:
        if path.name == "execution-receipt.json" and value.get("schema") == "ds02.execution-receipt.v1":
            value["upstream_batch_admission"] = {
                "schema": ADMISSION_SCHEMA,
                "batch_index": BATCH_INDEX,
                "path": str(admission_path.resolve()),
                "payload_sha256": admission["payload_sha256"],
            }
            value["upstream_batch_request_grant"] = {
                "schema": GRANT_SCHEMA,
                "path": str(grant_path.resolve()),
                "payload_sha256": grant["payload_sha256"],
                "request_sha256": grant["request_sha256"],
            }
        return saved_receipt(path, value)

    v6._check_upstream_batch = check
    v6._terminal_upstream_overrun = terminal
    v6._guarded_atomic_json = receipt
    try:
        yield
    finally:
        v6._check_upstream_batch = saved_check
        v6._terminal_upstream_overrun = saved_terminal
        v6._guarded_atomic_json = saved_receipt


def run_request(
    request_path: Path,
    *,
    data_root: Path = DATA_ROOT,
    batch_admission: Path | None = None,
    batch_grant: Path | None = None,
) -> dict[str, Any]:
    """Run one exact root-granted batch-2 request through consumed v6."""
    if batch_admission is None:
        raise BatchAdmissionError("batch-2 admission artifact is required")
    if batch_grant is None:
        raise BatchAdmissionError("batch-2 request grant is required")
    request_path = Path(request_path).expanduser()
    if request_path.is_symlink():
        raise BatchAdmissionError("batch-2 request must not be a symlink")
    request_path = request_path.resolve()
    data_root = Path(data_root).expanduser().resolve()
    batch_admission = Path(batch_admission).expanduser().resolve()
    batch_grant = Path(batch_grant).expanduser().resolve()
    admission = _load_and_validate(batch_admission, data_root=data_root)
    request = _read_json(request_path, "batch-2 request")
    grant = _validate_request_binding(
        request_path,
        request,
        grant_path=batch_grant,
        admission_path=batch_admission,
        admission=admission,
    )
    with _bind_v6_guards(
        batch_admission,
        admission,
        grant_path=batch_grant,
        grant=grant,
        data_root=data_root,
    ):
        return v6.run_request(request_path, data_root=data_root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("inventory", "status", "run"))
    parser.add_argument("--request", type=Path)
    parser.add_argument("--batch-admission", type=Path)
    parser.add_argument("--batch-grant", type=Path)
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    args = parser.parse_args()
    if args.action == "inventory":
        result = v6.base.inventory()
    elif args.action == "status":
        ledger = _read_json(args.data_root / "runtime" / "resource-ledger.json", "shared ledger")
        if ledger.get("limits", {}).get("storage_policy") == "home_free_floor":
            # The parent v6 reservation path uses live statvfs plus ledger
            # rows for this policy.  Do not introduce a redundant recursive
            # Home/data-root scan merely to render status.
            actual_bytes = None
            home_free_bytes = os.statvfs(args.data_root).f_bavail * os.statvfs(args.data_root).f_frsize
        else:
            actual_bytes = v6.tree_bytes(args.data_root)
            home_free_bytes = None
        result = dict(
            totals_with_reservations=v6.base.usage_totals(ledger),
            actual_bytes=actual_bytes,
            home_free_bytes=home_free_bytes,
            ledger=ledger,
        )
    else:
        if args.request is None:
            parser.error("--request is required for run")
        if args.batch_admission is None:
            parser.error("--batch-admission is required for run")
        if args.batch_grant is None:
            parser.error("--batch-grant is required for run")
        result = run_request(
            args.request,
            data_root=args.data_root,
            batch_admission=args.batch_admission,
            batch_grant=args.batch_grant,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(args.action == "run" and result.get("status") != "completed")


if __name__ == "__main__":
    raise SystemExit(main())
