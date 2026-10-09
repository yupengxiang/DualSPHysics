#!/usr/bin/env python3
"""Build a source-bound terminal index for the fourteen Stage2 sentinels.

The producer consumes only explicitly listed JSON files.  It joins the frozen
fourteen-sentinel index to named proof/request/receipt triples and records a
running attempt separately from terminal evidence.  A proof is terminal credit
only when its request case, attempt, receipt, and report are the exact objects
declared by the manifest.  No directory discovery or ``latest`` selection is
performed.

This product is an evidence index.  It does not promote source, saved-time,
native-motive, lifecycle, or mass diagnostics to QI/QN/QE, physical fate,
legal flux, or dynamics.  In particular, lifecycle exposure is kept separate
from the 118 native-omission cases; the former is never renamed ``non-native``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
CURRENT336_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
FAMILIES = tuple(f"F{i}" for i in range(1, 8))
SENTINEL_STATUS_SCHEMA = "ds02.stage2.fourteen-source-status.v3"
SENTINEL_NEXT_SCHEMA = "ds02.stage2.fourteen-source-status.v3-next-requests"
TERMINAL_MATRIX_SCHEMA = "ds02.stage2.fourteen-terminal-next-matrix.v3"
ROOT_PROOF_SCHEMA = "ds02.stage2.root-actual-verification.v1"
RUNNING_SCHEMA = "ds02.stage2.root-running-checkpoint.v1"
INDEX_SCHEMA = "ds02.stage2.fourteen-sentinel-terminal-index.v1"
MANIFEST_SCHEMA = "ds02.stage2.fourteen-sentinel-terminal-index.manifest.v1"
REQUEST_SCHEMA = "ds02.stage2.fourteen-sentinel-terminal-index-request.v1"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_SUFFIXES = {".h5", ".hdf5", ".hdf", ".bi4", ".obi4", ".vtk", ".vtu", ".raw"}
Q_KEYS = ("QI", "QN", "QE")


class IndexError(RuntimeError):
    """Raised when an immutable source binding is incomplete or inconsistent."""


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA_RE.fullmatch(value) is None:
        raise IndexError(f"{label} is not a lowercase SHA-256 digest")
    return value


def _path(value: Any, label: str) -> Path:
    if not isinstance(value, (str, Path)):
        raise IndexError(f"{label} must be an absolute path")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise IndexError(f"{label} must be an absolute path")
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise IndexError(f"{label} points at forbidden scientific payload: {path}")
    if not path.is_file():
        raise IndexError(f"{label} is missing: {path}")
    return path


def _json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IndexError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise IndexError(f"{label} must be a JSON object: {path}")
    return value


def _parse_utc(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise IndexError(f"{label} has no UTC timestamp")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IndexError(f"{label} has invalid UTC timestamp: {value!r}") from exc
    return value


def _ref(path: Path, role: str) -> dict[str, Any]:
    stat = path.stat()
    return {
        "role": role,
        "path": str(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "st_dev": stat.st_dev,
        "st_ino": stat.st_ino,
        "sha256": sha256_file(path),
        "source_scope": "JSON_ONLY",
    }


def _load_sources(manifest_path: Path) -> tuple[dict[str, Any], dict[str, Path], dict[str, dict[str, Any]]]:
    manifest = _json(manifest_path, "terminal-index manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise IndexError(f"unexpected manifest schema: {manifest.get('schema')!r}")
    refs = manifest.get("source_refs")
    if not isinstance(refs, list) or not refs:
        raise IndexError("manifest source_refs is empty")
    paths: dict[str, Path] = {}
    records: dict[str, dict[str, Any]] = {}
    for item in refs:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str):
            raise IndexError("malformed source reference")
        key = item["key"]
        if key in paths:
            raise IndexError(f"duplicate source reference key: {key}")
        path = _path(item.get("path"), f"source {key}")
        expected = _sha(item.get("sha256"), f"source {key}")
        actual = _ref(path, str(item.get("role", key)))
        if actual["sha256"] != expected:
            raise IndexError(f"source {key} digest changed: {expected} != {actual['sha256']}")
        for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
            if field in item and item[field] is not None and actual[field] != item[field]:
                raise IndexError(f"source {key} {field} changed")
        paths[key] = path
        records[key] = actual
    current = records.get("current336")
    if current is None or current["sha256"] != CURRENT336_SHA256:
        raise IndexError(f"CURRENT336 must bind {CURRENT336_SHA256}")
    declared = manifest.get("current_binding")
    if not isinstance(declared, dict) or declared.get("sha256") != CURRENT336_SHA256:
        raise IndexError("manifest current_binding does not bind exact CURRENT336")
    return manifest, paths, records


def _identity_rows(status: dict[str, Any], next_requests: dict[str, Any], matrix: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if status.get("schema") != SENTINEL_STATUS_SCHEMA:
        raise IndexError("historic source-status schema mismatch")
    if next_requests.get("schema") != SENTINEL_NEXT_SCHEMA:
        raise IndexError("historic next-request schema mismatch")
    if matrix.get("schema") != TERMINAL_MATRIX_SCHEMA:
        raise IndexError("historic terminal matrix schema mismatch")
    status_rows, next_rows, matrix_rows = status.get("sentinels"), next_requests.get("requests"), matrix.get("sentinels")
    if not all(isinstance(rows, list) and len(rows) == 14 for rows in (status_rows, next_rows, matrix_rows)):
        raise IndexError("each historic sentinel index must contain exactly 14 rows")
    by_status: dict[str, dict[str, Any]] = {}
    by_next: dict[str, dict[str, Any]] = {}
    by_matrix: dict[str, dict[str, Any]] = {}
    for row in status_rows:
        if not isinstance(row, dict) or not isinstance(row.get("sentinel_id"), str) or row["sentinel_id"] in by_status:
            raise IndexError("duplicate or malformed historic status sentinel")
        by_status[row["sentinel_id"]] = row
    for row in next_rows:
        if not isinstance(row, dict) or not isinstance(row.get("sentinel_id"), str) or row["sentinel_id"] in by_next:
            raise IndexError("duplicate or malformed historic next sentinel")
        by_next[row["sentinel_id"]] = row
    for row in matrix_rows:
        if not isinstance(row, dict) or not isinstance(row.get("sentinel_id"), str) or row["sentinel_id"] in by_matrix:
            raise IndexError("duplicate or malformed historic terminal sentinel")
        by_matrix[row["sentinel_id"]] = row
    expected = {f"F{family}-S{side}" for family in range(1, 8) for side in (1, 2)}
    if set(by_status) != expected or set(by_next) != expected or set(by_matrix) != expected:
        raise IndexError("historic sentinel IDs are not exactly F1..F7 S1/S2")
    result: dict[str, dict[str, Any]] = {}
    for sid in sorted(expected, key=lambda value: (int(value[1]), int(value[-1]))):
        a, b, c = by_status[sid], by_next[sid], by_matrix[sid]
        identity = (a.get("family_id"), a.get("physical_case_id"))
        for label, row in (("next", b), ("terminal", c)):
            if (row.get("family_id"), row.get("physical_case_id")) != identity:
                raise IndexError(f"{sid} identity differs between historic {label} index")
        result[sid] = {
            "sentinel_id": sid,
            "family_id": identity[0],
            "physical_case_id": identity[1],
            "historic_status": a.get("terminal_state", {}).get("status"),
            "historic_category": a.get("terminal_state", {}).get("category"),
            "historic_terminal_status": a.get("terminal_state", {}).get("status"),
            "historic_next_request_id": b.get("request_id"),
            "historic_next_state": b.get("state"),
            "historic_next_kind": b.get("task_kind"),
            "historic_next_action": a.get("next_guarded_task", {}).get("action"),
            "historic_next_success_condition": a.get("next_guarded_task", {}).get("success_condition"),
            "historic_qualification": copy_unknown_q(a.get("terminal_state", {}).get("scientific_qualification")),
            "terminal_credit": False,
            "terminal_attempts": [],
            "nonterminal_attempts": [],
        }
    return result


def copy_unknown_q(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {key: "UNKNOWN" for key in Q_KEYS}
    return {key: value.get(key, "UNKNOWN") for key in Q_KEYS}


def _source_for(paths: dict[str, Path], records: dict[str, dict[str, Any]], key: str) -> tuple[Path, dict[str, Any]]:
    if key not in paths:
        raise IndexError(f"manifest does not declare source key {key}")
    return paths[key], records[key]


def _validate_completed_proof(
    binding: dict[str, Any],
    paths: dict[str, Path],
    records: dict[str, dict[str, Any]],
    rows: dict[str, dict[str, Any]],
    *,
    terminal_credit: bool,
) -> dict[str, Any]:
    sid_list = binding.get("sentinel_ids") or ([binding.get("sentinel_id")] if binding.get("sentinel_id") else [])
    if not isinstance(sid_list, list) or not sid_list:
        raise IndexError("completed binding has no sentinel IDs")
    for sid in sid_list:
        if sid not in rows:
            raise IndexError(f"completed binding refers to unknown sentinel {sid}")
    proof_path, proof_ref = _source_for(paths, records, binding.get("proof_key"))
    request_path, request_ref = _source_for(paths, records, binding.get("request_key"))
    receipt_path, receipt_ref = _source_for(paths, records, binding.get("receipt_key"))
    report_path, report_ref = _source_for(paths, records, binding.get("report_key"))
    proof = _json(proof_path, "completed proof")
    if proof.get("schema") != ROOT_PROOF_SCHEMA:
        raise IndexError(f"{proof_path} is not a root actual verification proof")
    if not str(proof.get("status", "")).startswith("VERIFIED_ACTUAL_"):
        raise IndexError(f"completed proof is not VERIFIED_ACTUAL: {proof_path}")
    proof_utc = _parse_utc(proof.get("utc"), f"proof {proof_path}")
    if proof.get("request") != str(request_path) or proof.get("request_sha256") != request_ref["sha256"]:
        raise IndexError(f"proof/request binding mismatch: {proof_path}")
    if proof.get("receipt") != str(receipt_path) or proof.get("receipt_sha256") != receipt_ref["sha256"]:
        raise IndexError(f"proof/receipt binding mismatch: {proof_path}")
    if proof.get("report") != str(report_path) or proof.get("report_sha256") != report_ref["sha256"]:
        raise IndexError(f"proof/report binding mismatch: {proof_path}")
    if proof.get("guarded_receipt_status") != "completed" or proof.get("parent_reservation_released") is not True:
        raise IndexError(f"proof is not a released completed attempt: {proof_path}")
    request = _json(request_path, "terminal request")
    receipt = _json(receipt_path, "terminal receipt")
    report = _json(report_path, "terminal report")
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed":
        raise IndexError(f"receipt is not completed: {receipt_path}")
    nested = receipt.get("request")
    if not isinstance(nested, dict):
        raise IndexError(f"receipt lacks embedded request: {receipt_path}")
    if receipt.get("request_sha256") != request_ref["sha256"]:
        raise IndexError(f"receipt request SHA differs from declared request: {receipt_path}")
    if nested.get("attempt_id") != receipt.get("request", {}).get("attempt_id"):
        raise IndexError(f"receipt embedded request is internally inconsistent: {receipt_path}")
    expected_case = binding.get("expected_request_case_id")
    expected_attempt = binding.get("expected_attempt_id")
    if nested.get("case_id") != expected_case or nested.get("attempt_id") != expected_attempt:
        raise IndexError(f"case/attempt mismatch for {sid_list}: {receipt_path}")
    if request.get("case_id") != expected_case or request.get("attempt_id") != expected_attempt:
        raise IndexError(f"request case/attempt mismatch for {sid_list}: {request_path}")
    if binding.get("expected_family_id") is not None and nested.get("family_id") not in (None, binding["expected_family_id"]):
        raise IndexError(f"family mismatch for {sid_list}: {receipt_path}")
    expected_sentinel = binding.get("expected_sentinel_id")
    if expected_sentinel is not None and nested.get("sentinel_id") not in (None, expected_sentinel):
        raise IndexError(f"sentinel mismatch for {sid_list}: {receipt_path}")
    if not isinstance(report, dict):
        raise IndexError(f"terminal report is not an object: {report_path}")
    if receipt.get("output_root") and not str(report_path).startswith(str(receipt["output_root"])):
        raise IndexError(f"report is outside the receipt output root: {report_path}")
    record = {
        "status": "ACTUAL_TERMINAL_PROOF_BOUND",
        "terminal_credit": terminal_credit,
        "sentinel_ids": sid_list,
        "family_id": binding.get("expected_family_id"),
        "physical_case_id": binding.get("expected_physical_case_id"),
        "case_id": expected_case,
        "attempt_id": expected_attempt,
        "proof": {"path": str(proof_path), "sha256": proof_ref["sha256"], "utc": proof_utc, "status": proof["status"]},
        "request": {"path": str(request_path), "sha256": request_ref["sha256"]},
        "receipt": {"path": str(receipt_path), "sha256": receipt_ref["sha256"], "status": receipt.get("status")},
        "report": {"path": str(report_path), "sha256": report_ref["sha256"]},
        "scope_note": binding.get("scope_note"),
    }
    for sid in sid_list:
        rows[sid]["terminal_attempts"].append(record)
        if terminal_credit:
            rows[sid]["terminal_credit"] = True
    return record


def _validate_running(binding: dict[str, Any], paths: dict[str, Path], records: dict[str, dict[str, Any]], rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    sid = binding.get("sentinel_id")
    if sid not in rows:
        raise IndexError(f"running binding refers to unknown sentinel {sid}")
    checkpoint_path, checkpoint_ref = _source_for(paths, records, binding.get("checkpoint_key"))
    request_path, request_ref = _source_for(paths, records, binding.get("request_key"))
    checkpoint = _json(checkpoint_path, "running checkpoint")
    if checkpoint.get("schema") != RUNNING_SCHEMA:
        raise IndexError(f"running checkpoint schema mismatch: {checkpoint_path}")
    if checkpoint.get("status") != "ACTUAL_RUNNING_F3_FINE_NOT_TERMINAL":
        raise IndexError(f"running checkpoint is no longer explicitly nonterminal: {checkpoint_path}")
    if checkpoint.get("request") != str(request_path) or checkpoint.get("request_sha256") != request_ref["sha256"]:
        raise IndexError(f"running checkpoint/request binding mismatch: {checkpoint_path}")
    request = _json(request_path, "running request")
    if request.get("attempt_id") != binding.get("expected_attempt_id") or request.get("case_id") != binding.get("expected_request_case_id"):
        raise IndexError(f"running case/attempt mismatch: {request_path}")
    if request.get("sentinel_id") != sid or request.get("physical_case_id") != rows[sid]["physical_case_id"]:
        raise IndexError(f"running sentinel identity mismatch: {request_path}")
    record = {
        "status": "RUNNING_NOT_TERMINAL",
        "terminal_credit": False,
        "sentinel_id": sid,
        "family_id": rows[sid]["family_id"],
        "physical_case_id": rows[sid]["physical_case_id"],
        "case_id": request.get("case_id"),
        "attempt_id": request.get("attempt_id"),
        "checkpoint": {"path": str(checkpoint_path), "sha256": checkpoint_ref["sha256"], "utc": _parse_utc(checkpoint.get("utc"), f"checkpoint {checkpoint_path}"), "status": checkpoint.get("status")},
        "request": {"path": str(request_path), "sha256": request_ref["sha256"]},
        "scope_note": "Running evidence is indexed for as-of tracking and receives no terminal credit or scientific qualification.",
    }
    rows[sid]["nonterminal_attempts"].append(record)
    return record


def _validate_upstream_proof(binding: dict[str, Any], paths: dict[str, Path], records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    proof_path, proof_ref = _source_for(paths, records, binding.get("proof_key"))
    proof = _json(proof_path, "upstream proof")
    if proof.get("schema") != ROOT_PROOF_SCHEMA or not str(proof.get("status", "")).startswith("VERIFIED_ACTUAL_"):
        raise IndexError(f"upstream proof is not a completed actual proof: {proof_path}")
    if proof.get("parent_reservation_released") is not True or proof.get("guarded_receipt_status") != "completed":
        raise IndexError(f"upstream proof is not terminal: {proof_path}")
    request_record = None
    receipt_record = None
    if binding.get("request_key") is not None:
        request_path, request_ref = _source_for(paths, records, binding["request_key"])
        if proof.get("request") != str(request_path) or proof.get("request_sha256") != request_ref["sha256"]:
            raise IndexError(f"upstream proof/request binding mismatch: {proof_path}")
        request_record = _json(request_path, "upstream request")
    if binding.get("receipt_key") is not None:
        receipt_path, receipt_ref = _source_for(paths, records, binding["receipt_key"])
        if proof.get("receipt") != str(receipt_path) or proof.get("receipt_sha256") != receipt_ref["sha256"]:
            raise IndexError(f"upstream proof/receipt binding mismatch: {proof_path}")
        receipt_record = _json(receipt_path, "upstream receipt")
        if receipt_record.get("status") != "completed" or receipt_record.get("request_sha256") != records[binding["request_key"]]["sha256"]:
            raise IndexError(f"upstream receipt is not joined to its request: {receipt_path}")
        nested = receipt_record.get("request")
        if not isinstance(nested, dict) or nested.get("attempt_id") != request_record.get("attempt_id"):
            raise IndexError(f"upstream request/receipt attempt mismatch: {receipt_path}")
    report_path = proof.get("report")
    if isinstance(report_path, str):
        report = _path(report_path, "upstream proof report")
        if proof.get("report_sha256") is not None:
            _sha(proof.get("report_sha256"), "upstream proof report_sha256")
    return {
        "status": "UPSTREAM_COMPLETED_PRODUCT_BOUND",
        "terminal_credit": False,
        "proof": {"path": str(proof_path), "sha256": proof_ref["sha256"], "utc": _parse_utc(proof.get("utc"), f"proof {proof_path}"), "status": proof.get("status")},
        "request": {"path": str(request_path), "sha256": request_ref["sha256"]} if request_record is not None else None,
        "receipt": {"path": str(receipt_path), "sha256": receipt_ref["sha256"], "status": receipt_record.get("status")} if receipt_record is not None else None,
        "native_omission_case_count": proof.get("native_omission_case_count"),
        "lifecycle_exposure_counts": proof.get("lifecycle_exposure_counts"),
        "semantic_limit": "Upstream matrix coverage is provenance only; it does not alter sentinel terminal credit or Q status.",
    }


def build_index(manifest_path: Path | str) -> dict[str, Any]:
    manifest_path = Path(manifest_path).expanduser().resolve()
    manifest, paths, records = _load_sources(manifest_path)
    historic = _identity_rows(_json(paths["sentinel_status_v3"], "historic status"), _json(paths["sentinel_next_v3"], "historic next requests"), _json(paths["sentinel_terminal_matrix_v3"], "historic terminal matrix"))
    current = _json(paths["current336"], "CURRENT336")
    if current.get("schema") != "ds02.stage2.current336.v1" or not isinstance(current.get("cases"), list) or len(current["cases"]) != 336:
        raise IndexError("CURRENT336 must expose exactly 336 cases")
    terminal_bindings = manifest.get("terminal_bindings")
    if not isinstance(terminal_bindings, list):
        raise IndexError("manifest terminal_bindings is not a list")
    completed_records = []
    for binding in terminal_bindings:
        if not isinstance(binding, dict):
            raise IndexError("malformed terminal binding")
        completed_records.append(_validate_completed_proof(binding, paths, records, historic, terminal_credit=bool(binding.get("terminal_credit"))))
    running_records = []
    for binding in manifest.get("running_bindings", []):
        if not isinstance(binding, dict):
            raise IndexError("malformed running binding")
        running_records.append(_validate_running(binding, paths, records, historic))
    scope_only_records = []
    for binding in manifest.get("scope_only_completed_bindings", []):
        scope_only_records.append(_validate_completed_proof(binding, paths, records, historic, terminal_credit=False))
        scope_only_records[-1]["status"] = "ACTUAL_SCOPE_ONLY_PROOF_NO_SENTINEL_TERMINAL_CREDIT"
        scope_only_records[-1]["terminal_credit"] = False
        scope_only_records[-1]["scope_note"] = binding.get("scope_note")
        for sid in scope_only_records[-1]["sentinel_ids"]:
            historic[sid]["terminal_attempts"][-1]["status"] = "ACTUAL_SCOPE_ONLY_PROOF_NO_SENTINEL_TERMINAL_CREDIT"
            historic[sid]["terminal_attempts"][-1]["terminal_credit"] = False
    upstream = _validate_upstream_proof(manifest["upstream_matrix_binding"], paths, records)
    for row in historic.values():
        row["next_ready_gap"] = {
            "status": "TERMINAL_CREDIT_BOUND" if row["terminal_credit"] else "NEXT_GUARDED_GAP_REMAINS",
            "historic_request_id": row["historic_next_request_id"],
            "historic_state": row["historic_next_state"],
            "kind": row["historic_next_kind"],
            "action": row["historic_next_action"],
            "success_condition": row["historic_next_success_condition"],
            "qualification": copy_unknown_q(row["historic_qualification"]),
        }
    rows = [historic[sid] for sid in sorted(historic, key=lambda value: (int(value[1]), int(value[-1])))]
    return {
        "schema": INDEX_SCHEMA,
        "as_of_policy": "Completed rows use proof.utc; running rows use checkpoint.utc; no wall-clock or latest-file inference.",
        "source_scope": {"json_only": True, "arrays_opened": False, "h5_bi4_vtk_opened": False, "solver_started": False, "model_invoked": False},
        "current_binding": {"path": str(paths["current336"]), "sha256": records["current336"]["sha256"], "case_count": 336, "family_counts": {family: 48 for family in FAMILIES}},
        "historic_index_binding": {key: {"path": str(paths[key]), "sha256": records[key]["sha256"]} for key in ("sentinel_status_v3", "sentinel_next_v3", "sentinel_terminal_matrix_v3")},
        "upstream_matrix": upstream,
        "terminal_attempts": completed_records,
        "nonterminal_attempts": running_records,
        "scope_only_completed_proofs": scope_only_records,
        "sentinels": rows,
        "coverage": {
            "sentinel_count": 14,
            "terminal_credit_sentinels": sum(row["terminal_credit"] for row in rows),
            "next_guarded_gap_sentinels": sum(not row["terminal_credit"] for row in rows),
            "nonterminal_attempt_count": len(running_records),
            "scope_only_completed_proof_count": len(scope_only_records),
            "native_omission_cases": 118,
            "lifecycle_missing_exposure_rows": 290,
            "non_native_rows": "NOT_REPORTED",
        },
        "semantic_correction": {
            "native_omission_cases": 118,
            "lifecycle_missing_exposure_rows": 290,
            "non_native_rows": "NOT_REPORTED",
            "rule": "Lifecycle fields missing from an audit projection are a separate exposure count; they are not native-omission or non-native classifications.",
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
        "old_material_immutable": True,
    }


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--manifest", required=True)
    build.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command != "build":
        parser.error("unsupported command")
    result = build_index(Path(args.manifest))
    output = Path(args.output).expanduser()
    if not output.is_absolute():
        raise SystemExit("--output must be absolute")
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(output.suffix + ".tmp")
    temp.write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(output)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(_main())
    except IndexError as exc:
        raise SystemExit(f"terminal-index error: {exc}")
