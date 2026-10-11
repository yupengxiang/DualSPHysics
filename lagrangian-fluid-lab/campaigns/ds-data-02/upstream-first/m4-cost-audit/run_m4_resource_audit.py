#!/usr/bin/env python3
"""Read-only final M4 resource audit.

This helper audits the immutable batch-2 boundary, the shared parent ledger,
and the small execution/reconciliation receipts already produced by the UF
runner.  It never launches work, reserves resources, edits requests/grants,
or writes shared campaign state.  The only output is one new checkpoint below
this directory; an existing checkpoint is never replaced.

The audit intentionally hashes JSON receipts and reports only.  It does not
walk the NAS, hash HDF5/BI4 payloads, or infer bytes from a product tree.  The
runner's charged ``bytes`` rows and the external-copy reconciliation receipt
are the authoritative storage metadata for this checkpoint.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping


SCRIPT = Path(__file__).resolve()
UPSTREAM = SCRIPT.parents[1]
ROOT = UPSTREAM.parents[3]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
NAS_ROOT = Path("/data/nas/jade/Simulation/DualSPHysics/upstream-first")
ADMISSION = UPSTREAM / "batch2-runtime" / "root-batch-2-admission.json"
COST_AUDIT = UPSTREAM / "batch2-runtime" / "M1-M3-cost-audit-v1.json"
RELEASE_INPUT = UPSTREAM / "M4_RELEASE_INPUT_V1.json"
LEDGER = DATA_ROOT / "runtime" / "resource-ledger.json"
CHECKPOINT = SCRIPT.parent / "checkpoints" / "M4-resource-audit-v1.json"
REQUESTS = UPSTREAM / "requests"
FIXED_DEADLINE = "2026-10-25T03:11:02+00:00"
AUDIT_SCHEMA = "ds02.upstream-first.m4-resource-audit.v1"
RECEIPT_SCHEMA = "ds02.execution-receipt.v1"
EXTERNAL_SCHEMA = "ds02.upstream-first.external-storage-reconciliation.v1"
ACTUAL_PRODUCT_SCHEMA = "ds-data-02.m4.actual-validation.v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
UF_ID_RE = re.compile(r"^([^/]+)/((?:UF_)[^/]+)/([^/]+)$", re.ASCII)
RESOURCE_KEYS = ("gpu_seconds", "cpu_core_seconds", "new_storage_bytes")
EPSILON = 1.0e-8


class AuditError(RuntimeError):
    """Raised when immutable resource evidence cannot be verified."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AuditError(f"value is not canonical JSON: {exc}") from exc


def _sha256(path: Path) -> str:
    path = Path(path).expanduser()
    if path.is_symlink() or not path.is_file():
        raise AuditError(f"metadata file is not a regular non-symlink file: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise AuditError(f"cannot read metadata file {path}: {exc}") from exc
    return digest.hexdigest()


def _regular(path: Path, label: str) -> Path:
    path = Path(path).expanduser()
    if path.is_symlink() or not path.is_file():
        raise AuditError(f"{label} is not a regular non-symlink file: {path}")
    return path.resolve()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    path = _regular(path, label)

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
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise AuditError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise AuditError(f"{label} must be a JSON object: {path}")
    return value


def _binding(path: Path, label: str) -> dict[str, Any]:
    path = _regular(path, label)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": _sha256(path)}


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise AuditError(f"{label} is not a lowercase SHA-256 digest")
    return value


def _finite_number(value: Any, label: str, *, integer: bool = False) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AuditError(f"{label} is not numeric")
    if integer and not isinstance(value, int):
        raise AuditError(f"{label} is not an integer")
    if not math.isfinite(float(value)) or value < 0:
        raise AuditError(f"{label} is negative or non-finite")
    return value


def _resource_row(row: Mapping[str, Any], label: str) -> dict[str, Any]:
    if not isinstance(row.get("id"), str) or UF_ID_RE.fullmatch(row["id"].split("::", 1)[0]) is None:
        raise AuditError(f"{label} is outside the UF batch namespace: {row.get('id')!r}")
    for key in RESOURCE_KEYS:
        _finite_number(row.get(key), f"{label}.{key}", integer=(key == "new_storage_bytes"))
    return dict(row)


def _close(actual: int | float, expected: int | float, label: str) -> None:
    if isinstance(actual, int) and isinstance(expected, int):
        equal = actual == expected
    else:
        equal = math.isclose(float(actual), float(expected), rel_tol=1.0e-12, abs_tol=EPSILON)
    if not equal:
        raise AuditError(f"{label} differs: actual={actual!r}, expected={expected!r}")


def _sum_usage(
    rows: Iterable[Mapping[str, Any]], *, validate_rows: bool = True
) -> dict[str, int | float]:
    rows = list(rows)
    if validate_rows:
        for index, row in enumerate(rows):
            _resource_row(row, f"resource row {index}")
    return {key: sum(row.get(key, 0) for row in rows) for key in RESOURCE_KEYS}


def _parse_attempt_id(row_id: str) -> tuple[str, str, str]:
    base = row_id.split("::", 1)[0]
    match = UF_ID_RE.fullmatch(base)
    if match is None:
        raise AuditError(f"invalid UF attempt id: {row_id}")
    return match.group(1), match.group(2), match.group(3)


def _execution_receipt_path(row_id: str) -> Path:
    family, case, attempt = _parse_attempt_id(row_id)
    return NAS_ROOT / "runs" / family / case / attempt / "execution-receipt.json"


def _request_path(row_id: str) -> Path:
    _, case, attempt = _parse_attempt_id(row_id)
    return REQUESTS / f"{case}-{attempt}.json"


def _request_hash_check(row_id: str, receipt: Mapping[str, Any]) -> dict[str, Any]:
    request_path = _regular(_request_path(row_id), f"immutable request for {row_id}")
    expected = _sha256(request_path)
    actual = receipt.get("request_sha256")
    if actual != expected:
        raise AuditError(f"{row_id} execution receipt request hash differs from immutable request")
    return {"path": str(request_path), "sha256": expected, "bytes": request_path.stat().st_size}


def _status_matches(row: Mapping[str, Any], receipt: Mapping[str, Any], label: str) -> None:
    row_status = row.get("status")
    receipt_status = receipt.get("status")
    if row_status == "completed":
        if receipt_status != "completed" or receipt.get("returncode") != 0:
            raise AuditError(f"{label} charge is completed but receipt is not a successful completion")
    elif row_status == "failed":
        if receipt_status != "failed" or receipt.get("returncode") == 0:
            raise AuditError(f"{label} failed charge is not bound to a failed receipt")
    elif row_status not in {"complete", "accepted", "passed", "verified"}:
        raise AuditError(f"{label} has unsupported terminal charge status: {row_status!r}")


def _verify_execution_charge(row: Mapping[str, Any]) -> dict[str, Any]:
    row_id = str(row["id"])
    path = _execution_receipt_path(row_id)
    receipt = _read_json(path, f"execution receipt for {row_id}")
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise AuditError(f"{row_id} execution receipt schema is unsupported")
    _, case, attempt = _parse_attempt_id(row_id)
    nested = receipt.get("request")
    if isinstance(nested, Mapping):
        if nested.get("case_id") not in (None, case) or nested.get("attempt_id") not in (None, attempt):
            raise AuditError(f"{row_id} execution receipt request identity differs")
    output_root = receipt.get("output_root")
    if output_root != str(path.parent.resolve()):
        raise AuditError(f"{row_id} execution receipt output_root differs from its charge attempt")
    _status_matches(row, receipt, row_id)
    for key, receipt_key in (
        ("cpu_core_seconds", "cpu_core_seconds"),
        ("gpu_seconds", "gpu_seconds"),
        ("new_storage_bytes", "bytes"),
    ):
        _finite_number(
            receipt.get(receipt_key),
            f"{row_id} receipt.{receipt_key}",
            integer=(key == "new_storage_bytes"),
        )
        _close(row[key], receipt.get(receipt_key), f"{row_id}.{key} vs receipt.{receipt_key}")
    request_binding = _request_hash_check(row_id, receipt)
    return {
        "charge_id": row_id,
        "status": row.get("status"),
        "receipt": _binding(path, f"execution receipt for {row_id}"),
        "request": request_binding,
        "actual": {
            "cpu_core_seconds": receipt["cpu_core_seconds"],
            "gpu_seconds": receipt["gpu_seconds"],
            "new_storage_bytes": receipt["bytes"],
        },
    }


def _verify_external_delta(row: Mapping[str, Any]) -> dict[str, Any]:
    row_id = str(row["id"])
    if not row_id.endswith("::external-nas-copy-delta"):
        raise AuditError(f"unsupported synthetic UF charge id: {row_id}")
    if row.get("status") != "completed_external_storage_reconciliation":
        raise AuditError(f"{row_id} has an unsupported external reconciliation status")
    evidence_path_value = row.get("evidence_path")
    if not isinstance(evidence_path_value, str) or not evidence_path_value:
        raise AuditError(f"{row_id} lacks evidence_path")
    evidence_path = _regular(Path(evidence_path_value), f"external reconciliation for {row_id}")
    expected_hash = _require_sha256(row.get("evidence_sha256"), f"{row_id}.evidence_sha256")
    actual_hash = _sha256(evidence_path)
    if actual_hash != expected_hash:
        raise AuditError(f"{row_id} evidence hash differs from the ledger row")
    evidence = _read_json(evidence_path, f"external reconciliation for {row_id}")
    if evidence.get("schema") != EXTERNAL_SCHEMA or evidence.get("status") != "completed":
        raise AuditError(f"{row_id} external reconciliation is not completed")
    if evidence.get("charge_id") != row_id:
        raise AuditError(f"{row_id} external reconciliation charge_id differs")
    _, case, _ = _parse_attempt_id(row_id)
    if evidence.get("case_id") != case:
        raise AuditError(f"{row_id} external reconciliation case differs")
    if evidence.get("additional_persistent_bytes") != row["new_storage_bytes"]:
        raise AuditError(f"{row_id} external delta differs from the charged bytes row")
    for key in ("cpu_gpu_already_charged_by_original_runner", "original_receipts_and_charge_rows_unchanged", "parent_limits_and_deadline_unchanged", "within_original_validation_storage_reservation"):
        if evidence.get(key) is not True:
            raise AuditError(f"{row_id} reconciliation does not preserve {key}")
    relocation = evidence.get("actual_relocation_evidence")
    if not isinstance(relocation, Mapping):
        raise AuditError(f"{row_id} lacks actual relocation receipt binding")
    relocation_path = _regular(Path(str(relocation.get("path", ""))), f"{row_id} relocation receipt")
    relocation_binding = _binding(relocation_path, f"{row_id} relocation receipt")
    if relocation.get("bytes") != relocation_binding["bytes"] or relocation.get("sha256") != relocation_binding["sha256"]:
        raise AuditError(f"{row_id} relocation receipt binding is stale")
    return {
        "charge_id": row_id,
        "status": row.get("status"),
        "evidence": _binding(evidence_path, f"external reconciliation for {row_id}"),
        "actual_relocation_receipt": relocation_binding,
        "actual": {
            "cpu_core_seconds": row["cpu_core_seconds"],
            "gpu_seconds": row["gpu_seconds"],
            "new_storage_bytes": row["new_storage_bytes"],
        },
    }


def _verify_post_rows(
    post_charges: list[Mapping[str, Any]], post_reservations: list[Mapping[str, Any]], ledger: Mapping[str, Any], admission: Mapping[str, Any]
) -> dict[str, Any]:
    charge_records: list[dict[str, Any]] = []
    for index, row in enumerate(post_charges):
        normalized = _resource_row(row, f"post-admission charge {index}")
        if "::external-nas-copy-delta" in str(normalized["id"]):
            charge_records.append(_verify_external_delta(normalized))
        else:
            charge_records.append(_verify_execution_charge(normalized))
    reservation_records: list[dict[str, Any]] = []
    for index, row in enumerate(post_reservations):
        normalized = _resource_row(row, f"post-admission reservation {index}")
        if normalized.get("output_storage") not in {"upstream_nas", "home"}:
            raise AuditError(f"reservation {normalized['id']} has unsupported output storage")
        reservation_records.append(
            {
                "reservation_id": normalized["id"],
                "status": normalized.get("status", "reserved"),
                "kind": normalized.get("kind"),
                "cpu_task_kind": normalized.get("cpu_task_kind"),
                "reserved_ceiling": {key: normalized[key] for key in RESOURCE_KEYS},
                "output_storage": normalized.get("output_storage"),
            }
        )

    attempts = ledger.get("attempts")
    if not isinstance(attempts, list):
        raise AuditError("shared ledger attempts list is malformed")
    prior_attempts = set(admission.get("prior_attempt_ids", []))
    post_attempts = [row for row in attempts if isinstance(row, Mapping) and row.get("id") not in prior_attempts]
    post_attempt_ids = {str(row.get("id")) for row in post_attempts}
    ordinary_charge_ids = {str(row["id"]) for row in post_charges if "::external-nas-copy-delta" not in str(row["id"])}
    reservation_ids = {str(row["id"]) for row in post_reservations}
    if not ordinary_charge_ids.issubset(post_attempt_ids):
        missing = sorted(ordinary_charge_ids - post_attempt_ids)
        raise AuditError(f"post-admission charged attempts are missing ledger attempt rows: {missing}")
    if not reservation_ids.issubset(post_attempt_ids):
        missing = sorted(reservation_ids - post_attempt_ids)
        raise AuditError(f"post-admission reservations are missing ledger attempt rows: {missing}")
    if post_attempt_ids != ordinary_charge_ids | reservation_ids:
        extra = sorted(post_attempt_ids - ordinary_charge_ids - reservation_ids)
        raise AuditError(f"post-admission attempt rows lack a charge or reservation: {extra}")

    actual_usage = _sum_usage(post_charges)
    reserved_usage = _sum_usage(post_reservations)
    committed_usage = {key: actual_usage[key] + reserved_usage[key] for key in RESOURCE_KEYS}
    caps = {
        "gpu_seconds": admission["batch_limits"]["gpu_seconds"],
        "cpu_core_seconds": admission["batch_limits"]["cpu_core_seconds"],
        "new_storage_bytes": admission["batch_limits"]["additional_storage_bytes"],
    }
    for key in RESOURCE_KEYS:
        if committed_usage[key] > caps[key]:
            raise AuditError(f"batch-2 {key} cap is exceeded by charged plus reserved usage")
    return {
        "charges": charge_records,
        "reservations": reservation_records,
        "actual_charge_usage": actual_usage,
        "reserved_ceiling_usage": reserved_usage,
        "charged_plus_reserved_usage": committed_usage,
        "batch_limits": caps,
        "post_attempt_count": len(post_attempts),
    }


def _verify_historical_boundary(admission: Mapping[str, Any], ledger: Mapping[str, Any]) -> dict[str, Any]:
    if ledger.get("deadline_utc") != FIXED_DEADLINE or admission.get("parent_deadline_utc") != FIXED_DEADLINE:
        raise AuditError("fixed campaign deadline changed")
    if admission.get("parent_ledger_path") != str(LEDGER.resolve()):
        raise AuditError("batch admission points at a different parent ledger")
    if admission.get("prior_reservation_ids") != []:
        raise AuditError("batch admission did not begin with an empty reservation baseline")
    if admission.get("storage_allocation_basis", {}).get("historical_bytes_never_reset") is not True:
        raise AuditError("batch admission does not preserve historical storage bytes")

    # These are the runtime's immutable history checks.  They validate every
    # historical charge/attempt hash and the exact prior usage projection.
    import ds_data02_runtime_v6_batch2 as batch  # type: ignore

    batch._live_parent_limits_match(ledger, admission)
    prior_charge_ids, prior_attempt_ids = batch._baseline_rows_match(ledger, admission)
    post_rows = batch._post_admission_rows(ledger, prior_charge_ids)
    post_charges = [row for row in ledger.get("charges", []) if row.get("id") not in prior_charge_ids]
    post_reservations = [row for row in ledger.get("reservations", []) if row.get("id") not in set(admission.get("prior_reservation_ids", []))]
    if {str(row.get("id")) for row in post_rows} != {
        str(row.get("id")) for row in post_charges + post_reservations
    }:
        raise AuditError("runtime post-admission row helper disagrees with ledger partition")
    prior_rows = [row for row in ledger["charges"] if row.get("id") in prior_charge_ids]
    historical_usage = _sum_usage(prior_rows, validate_rows=False)
    for key in RESOURCE_KEYS:
        _close(historical_usage[key], admission["prior_usage"][key], f"historical {key} baseline")
    all_usage = _sum_usage(ledger["charges"], validate_rows=False)
    post_usage = _sum_usage(post_charges)
    for key in RESOURCE_KEYS:
        _close(all_usage[key], historical_usage[key] + post_usage[key], f"cumulative {key} usage")
        if all_usage[key] < historical_usage[key]:
            raise AuditError(f"cumulative {key} usage appears to have been reset")
    return {
        "fixed_deadline_utc": FIXED_DEADLINE,
        "parent_limits_preserved": True,
        "admission_parent_limits": dict(admission["parent_limits"]),
        "live_parent_limits": dict(ledger["limits"]),
        "historical_charge_count": len(prior_charge_ids),
        "historical_attempt_count": len(prior_attempt_ids),
        "historical_usage_actual_charge_rows": historical_usage,
        "post_charge_count": len(post_charges),
        "post_reservation_count": len(post_reservations),
        "cumulative_parent_usage_actual_charge_rows": all_usage,
        "historical_bytes_never_reset": True,
        "post_charges": post_charges,
        "post_reservations": post_reservations,
    }


def _product_receipts() -> dict[str, Any]:
    release = _read_json(RELEASE_INPUT, "immutable M4 release input")
    conditions = release.get("conditions")
    if not isinstance(conditions, list) or len(conditions) != 4:
        raise AuditError("M4 release input does not enumerate exactly four conditions")
    seen: set[str] = set()
    records: list[dict[str, Any]] = []
    invalid: list[str] = []
    for condition in conditions:
        if not isinstance(condition, Mapping) or not isinstance(condition.get("case_id"), str):
            raise AuditError("M4 release input has a malformed condition")
        case_id = str(condition["case_id"])
        if case_id in seen:
            raise AuditError(f"M4 release input repeats condition {case_id}")
        seen.add(case_id)
        validation = condition.get("actual_validation")
        receipt_value = validation.get("receipt") if isinstance(validation, Mapping) else None
        if not isinstance(receipt_value, str) or not receipt_value:
            raise AuditError(f"{case_id} lacks its final actual-validation receipt path")
        path = Path(receipt_value).expanduser()
        record: dict[str, Any] = {"case_id": case_id, "receipt_path": str(path), "status": "missing"}
        if path.exists() and not path.is_symlink() and path.is_file():
            try:
                receipt = _read_json(path, f"actual product receipt for {case_id}")
                binding = _binding(path, f"actual product receipt for {case_id}")
                record["binding"] = binding
                record["receipt_status"] = receipt.get("status")
                record["receipt_schema"] = receipt.get("schema")
                if receipt.get("schema") != ACTUAL_PRODUCT_SCHEMA or receipt.get("status") != "completed" or receipt.get("case_id") != case_id:
                    record["status"] = "invalid"
                    invalid.append(case_id)
                else:
                    record["status"] = "present"
            except AuditError:
                record["status"] = "invalid"
                invalid.append(case_id)
        records.append(record)
    if seen != {"UF_F1_MDBC_DP010_H050", "UF_F1_MDBC_DP010_H052", "UF_F1_MDBC_DP010_H058", "UF_F1_MDBC_DP010_H060"}:
        raise AuditError("M4 release input condition set differs from H050/H052/H058/H060")
    missing = sorted(item["case_id"] for item in records if item["status"] == "missing")
    present = sorted(item["case_id"] for item in records if item["status"] == "present")
    if invalid:
        status = "rejected_actual_product_receipts"
    elif missing:
        status = "pending_actual_product_receipts"
    else:
        status = "actual_product_receipts_present"
    return {
        "status": status,
        "condition_count": 4,
        "present_case_ids": present,
        "missing_case_ids": missing,
        "invalid_case_ids": sorted(invalid),
        "all_four_product_receipts_missing": len(missing) == 4,
        "receipts": records,
    }


def audit() -> dict[str, Any]:
    """Return a new checkpoint payload without mutating any shared state."""

    scripts = ROOT / "lagrangian-fluid-lab" / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import ds_data02_runtime_v6_batch2 as batch  # type: ignore

    admission = batch.validate_admission(ADMISSION, data_root=DATA_ROOT)
    ledger = _read_json(LEDGER, "shared parent resource ledger")
    cost_audit = _read_json(COST_AUDIT, "accepted M1-M3 cost audit")
    if cost_audit.get("status") != "complete" or cost_audit.get("acceptance_status") != "accepted":
        raise AuditError("accepted M1-M3 cost audit is not complete")
    boundary = _verify_historical_boundary(admission, ledger)
    post = _verify_post_rows(boundary.pop("post_charges"), boundary.pop("post_reservations"), ledger, admission)
    products = _product_receipts()

    historical_cpu_note = cost_audit.get("conservative_charge_note")
    if not isinstance(historical_cpu_note, str) or not historical_cpu_note:
        raise AuditError("M1-M3 audit lacks its conservative CPU ceiling note")
    status = products["status"]
    if status == "actual_product_receipts_present":
        status = "resource_audit_verified"
    elif status == "rejected_actual_product_receipts":
        status = "rejected_actual_product_receipts"
    else:
        status = "pending_actual_product_receipts"
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return {
        "schema": AUDIT_SCHEMA,
        "audit_id": "M4-resource-audit-v1",
        "status": status,
        "immutable": True,
        "candidate_only": True,
        "audited_at_utc": now,
        "launches_performed": False,
        "shared_state_mutations": [],
        "fixed_deadline_utc": FIXED_DEADLINE,
        "input_bindings": {
            "batch_admission": _binding(ADMISSION, "immutable batch-2 admission"),
            "m1_m3_cost_audit": _binding(COST_AUDIT, "accepted M1-M3 cost audit"),
            "parent_ledger_snapshot": _binding(LEDGER, "shared parent resource ledger"),
            "release_input": _binding(RELEASE_INPUT, "immutable M4 release input"),
            "runtime_batch2": _binding(scripts / "ds_data02_runtime_v6_batch2.py", "batch-2 runtime validator"),
        },
        "historical_boundary": boundary,
        "resource_accounting": {
            "cpu_actual_vs_reserved_policy": {
                "prior_m1_m3_actual_charge_rows": boundary["historical_usage_actual_charge_rows"]["cpu_core_seconds"],
                "prior_m1_m3_conservative_reserved_ceiling_note": historical_cpu_note,
                "post_admission_cpu_actual_charge_rows": post["actual_charge_usage"]["cpu_core_seconds"],
                "post_admission_cpu_reserved_ceiling_rows": post["reserved_ceiling_usage"]["cpu_core_seconds"],
                "actual_and_reserved_are_reported_separately": True,
            },
            "post_admission_actual_charge_rows": post["actual_charge_usage"],
            "post_admission_reserved_ceiling_rows": post["reserved_ceiling_usage"],
            "post_admission_charged_plus_reserved": post["charged_plus_reserved_usage"],
            "batch_limits": post["batch_limits"],
            "actual_gpu_and_bytes_are_charge_row_values": True,
        },
        "actual_receipt_charges": post["charges"],
        "active_reservations": post["reservations"],
        "product_receipts": products,
        "review_notes": [
            "This checkpoint is a metadata audit; it does not assert scientific product acceptance.",
            "Missing actual product receipts keep the checkpoint pending until root runs the final release audit.",
            "No HDF5/BI4 payload was read or hashed; frame/product payload accounting remains receipt-bound.",
        ],
    }


def _write_checkpoint(path: Path, payload: Mapping[str, Any]) -> Path:
    path = Path(path).expanduser().resolve()
    try:
        path.relative_to(SCRIPT.parent.resolve())
    except ValueError as exc:
        raise AuditError(f"checkpoint output escaped m4-cost-audit: {path}") from exc
    if path.exists() or path.is_symlink():
        raise AuditError(f"refusing to overwrite immutable checkpoint: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(encoded)
    return path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=CHECKPOINT, help="fresh checkpoint path below m4-cost-audit")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    payload = audit()
    output = _write_checkpoint(args.output, payload)
    print(json.dumps({"status": payload["status"], "checkpoint": str(output), "launches_now": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AuditError as exc:
        print(f"m4 resource audit rejected: {exc}", file=sys.stderr)
        raise SystemExit(2)
