"""Structural-only inspector for the synthetic F8 R008 append-only ledger.

The inspector validates strict JSON encoding, the fixed event union, ledger
ordering, per-attempt identity, and local stage/process event relationships.
It has no descriptor-root, receipt reader, attestation key registry, trusted
supervisor, or execution capability. Its summaries therefore always remain
untrusted and unresolved, even when the supplied ledger is structurally closed.
"""
from __future__ import annotations

import copy
import json
import re
from typing import Any

from scripts.core_strict_json import sha256_bytes, strict_json_object
from scripts.f8_r008_per_case_bundle_verifier_v2 import (
    AttemptResultV2Error,
    validate_untrusted_attempt_result_v2,
)


LEDGER_SCHEMA = "core.cfd.f8.r008_attempt_ledger.v1"
DIAGNOSTIC_SCHEMA = "core.cfd.f8.r008_untrusted_attempt_ledger_diagnostic.v1"
AGGREGATE_SCHEMA = "core.cfd.f8.r008_t1_case_attempt_aggregate.v2"
SCOPE_ID = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008"
MATRIX_SCHEMA = "core.cfd.f8.t1_scope_design.v1"
MATRIX_RECORD_ID = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008-t1-scope-design-v1"
LEDGER_FIELDS = frozenset({
    "schema", "scope_id", "qualification_matrix_raw_sha256", "supervisor_source_id",
    "coverage_start_ns_hex", "coverage_end_ns_hex", "event_count", "overflow",
    "lost_count", "events",
})
MATRIX_FIELDS = frozenset({
    "all_rows_are_qualification_only", "case_count", "control_count", "design_rule",
    "gate_applicability", "independent_internal_count", "no_failure_deletion_or_replacement",
    "rows", "spatial_anchor_count",
})
MATRIX_ROW_FIELDS = frozenset({
    "alpha", "case_id", "cflnumber", "compare_to", "control_amplitude_m_s2",
    "control_samples_per_period", "dp_m", "expected_observation_output_count", "kind",
    "native_output_dt_s", "native_output_samples_per_period", "observation_cycles",
    "observation_end_output_index", "observation_end_s", "observation_start_output_index",
    "observation_start_s", "omega_rad_s", "period_s", "q", "qualification_only",
})
AGGREGATE_FIELDS = frozenset({
    "schema", "scope_id", "qualification_matrix_raw_sha256", "attempt_ledger_ref",
    "attempt_ledger_raw_sha256", "attempt_ledger_attestation_ref", "expected_case_count",
    "case_rows", "case_outcome_counts", "attempt_outcome_counts", "aggregate_outcome",
    "attempt_ledger_complete", "qualification_adjudicated", "T1_numerical", "qualification_credit",
})
EVENT_COMMON_FIELDS = frozenset({
    "seq", "mono_ns_hex", "kind", "case_id", "qualification_row_sha256", "attempt_id", "nonce_hex",
})
EVENT_FIELDS = {
    "attempt_registered": EVENT_COMMON_FIELDS,
    "attempt_spawn": EVENT_COMMON_FIELDS | frozenset({"stage", "process_generation_id"}),
    "stage_receipt": EVENT_COMMON_FIELDS | frozenset({"stage", "receipt_ref"}),
    "process_terminal": EVENT_COMMON_FIELDS | frozenset({"stage", "process_generation_id", "process_journal_ref"}),
    "attempt_terminal": EVENT_COMMON_FIELDS | frozenset({"outcome", "terminal_ref"}),
}
STAGES = ("B", "C", "D")
ATTEMPT_OUTCOMES = frozenset({
    "not_started", "passed", "failed", "incomplete", "timeout", "oom", "signaled", "unresolved",
})
REFERENCE_FIELDS = frozenset({"stage", "role", "object_id", "bytes", "sha256"})
MAX_LEDGER_BYTES = 67_108_864
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_HEX16 = re.compile(r"^[0-9a-f]{16}$")
_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class AttemptLedgerV1Error(ValueError):
    """The raw ledger is malformed or violates its structural event contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AttemptLedgerV1Error(message)


def _int(value: Any, label: str, *, minimum: int = 0) -> None:
    _require(type(value) is int and value >= minimum,
             f"{label} must be a builtin integer >= {minimum}")


def _string(value: Any, label: str) -> None:
    _require(type(value) is str, f"{label} must be a builtin string")


def _identifier(value: Any, label: str) -> None:
    _require(type(value) is str and bool(_IDENTIFIER.fullmatch(value)),
             f"{label} does not match the fixed lowercase ASCII identifier grammar")


def _digest(value: Any, label: str) -> None:
    _require(type(value) is str and bool(_SHA256.fullmatch(value)),
             f"{label} must be 64 lowercase hexadecimal characters")


def _canonical_json_bytes(value: Any, label: str) -> bytes:
    """Use the shared V12 canonical JSON byte rule (default ASCII escaping, no LF)."""
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, OverflowError, RecursionError) as error:
        raise AttemptLedgerV1Error(f"{label} is not canonically JSON-serializable") from error


def inspect_untrusted_qualification_matrix(raw: bytes) -> dict[str, Any]:
    """Return ordered case IDs and row digests from an untrusted frozen-matrix object.

    Row identity is SHA-256 of the exact row encoded with V12 canonical JSON
    bytes. The raw matrix digest is kept separate; neither value authenticates
    that the supplied scope receipt is the active frozen artifact.
    """
    _require(type(raw) is bytes, "qualification matrix input must be exact raw bytes")
    try:
        document = strict_json_object(raw, label="F8 R008 frozen qualification matrix",
                                      max_bytes=MAX_LEDGER_BYTES)
    except ValueError as error:
        raise AttemptLedgerV1Error(str(error)) from error
    _require(document.get("schema") == MATRIX_SCHEMA and document.get("scope_id") == SCOPE_ID
             and document.get("record_id") == MATRIX_RECORD_ID,
             "qualification matrix schema, record, or scope is not the fixed F8 R008 design")
    matrix = document.get("matrix")
    _require(type(matrix) is dict and set(matrix) == MATRIX_FIELDS,
             "qualification matrix fields are not exact")
    _require(type(matrix["case_count"]) is int and matrix["case_count"] == 15,
             "qualification matrix case_count must be the builtin integer 15")
    _require(type(matrix["all_rows_are_qualification_only"]) is bool
             and matrix["all_rows_are_qualification_only"] is True,
             "qualification matrix must assert all rows are qualification-only")
    rows = matrix["rows"]
    _require(type(rows) is list and len(rows) == 15,
             "qualification matrix must contain exactly 15 rows in frozen order")
    row_index: list[dict[str, str]] = []
    seen_case_ids: set[str] = set()
    for ordinal, row in enumerate(rows):
        _require(type(row) is dict and set(row) == MATRIX_ROW_FIELDS,
                 f"qualification row {ordinal} fields are not exact")
        _identifier(row["case_id"], f"qualification row {ordinal}.case_id")
        _require(row["case_id"] not in seen_case_ids,
                 f"qualification matrix duplicates case_id {row['case_id']}")
        seen_case_ids.add(row["case_id"])
        _require(type(row["qualification_only"]) is bool and row["qualification_only"] is True,
                 f"qualification row {ordinal} is not marked qualification-only")
        row_index.append({
            "case_id": row["case_id"],
            "qualification_row_sha256": sha256_bytes(_canonical_json_bytes(row, f"qualification row {ordinal}")),
        })
    return {
        "matrix_raw_bytes": len(raw),
        "matrix_raw_sha256": sha256_bytes(raw),
        "matrix_schema": MATRIX_SCHEMA,
        "scope_id": SCOPE_ID,
        "row_count": len(row_index),
        "rows": row_index,
        "frozen_matrix_source_authenticated": False,
    }


def _reference(value: Any, *, expected_stage: str | None, label: str) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == REFERENCE_FIELDS,
             f"{label} must use the exact descriptor-ref fields")
    _string(value["stage"], f"{label}.stage")
    if expected_stage is not None:
        _require(value["stage"] == expected_stage, f"{label} names a different stage")
    else:
        _require(value["stage"] in {*STAGES, "runtime"},
                 f"{label}.stage is outside the fixed stage registry")
    _identifier(value["role"], f"{label}.role")
    _identifier(value["object_id"], f"{label}.object_id")
    _int(value["bytes"], f"{label}.bytes", minimum=1)
    _digest(value["sha256"], f"{label}.sha256")
    return value


def _parse_event(value: Any, expected_seq: int, *, start_ns: int, end_ns: int) -> dict[str, Any]:
    _require(type(value) is dict, f"event {expected_seq} must be an object")
    kind = value.get("kind")
    _string(kind, f"event {expected_seq}.kind")
    _require(kind in EVENT_FIELDS, f"event {expected_seq} has an unknown kind")
    _require(set(value) == EVENT_FIELDS[kind], f"event {expected_seq} fields are not exact for {kind}")
    _int(value["seq"], f"event {expected_seq}.seq")
    _require(value["seq"] == expected_seq, "ledger seq values must be the exact contiguous range 0..event_count-1")
    mono = value["mono_ns_hex"]
    _require(type(mono) is str and bool(_HEX16.fullmatch(mono)),
             f"event {expected_seq}.mono_ns_hex must be 16 lowercase hexadecimal characters")
    mono_ns = int(mono, 16)
    _require(start_ns <= mono_ns <= end_ns, f"event {expected_seq} lies outside ledger coverage")
    _identifier(value["case_id"], f"event {expected_seq}.case_id")
    _digest(value["qualification_row_sha256"], f"event {expected_seq}.qualification_row_sha256")
    _identifier(value["attempt_id"], f"event {expected_seq}.attempt_id")
    nonce = value["nonce_hex"]
    _require(type(nonce) is str and bool(_HEX32.fullmatch(nonce)),
             f"event {expected_seq}.nonce_hex must be 32 lowercase hexadecimal characters")

    if kind in {"attempt_spawn", "stage_receipt", "process_terminal"}:
        stage = value["stage"]
        _string(stage, f"event {expected_seq}.stage")
        _require(stage in STAGES, f"event {expected_seq}.stage is not B, C, or D")
    if kind == "attempt_spawn":
        _identifier(value["process_generation_id"], f"event {expected_seq}.process_generation_id")
    elif kind == "stage_receipt":
        _reference(value["receipt_ref"], expected_stage=value["stage"],
                   label=f"event {expected_seq}.receipt_ref")
    elif kind == "process_terminal":
        _identifier(value["process_generation_id"], f"event {expected_seq}.process_generation_id")
        _reference(value["process_journal_ref"], expected_stage=value["stage"],
                   label=f"event {expected_seq}.process_journal_ref")
    elif kind == "attempt_terminal":
        outcome = value["outcome"]
        _string(outcome, f"event {expected_seq}.outcome")
        _require(outcome in ATTEMPT_OUTCOMES, f"event {expected_seq}.outcome is outside the fixed enum")
        if outcome == "not_started":
            _require(value["terminal_ref"] is None,
                     f"event {expected_seq} not_started terminal_ref must be null")
        else:
            _reference(value["terminal_ref"], expected_stage=None,
                       label=f"event {expected_seq}.terminal_ref")
    return {"event": value, "mono_ns": mono_ns}


def _check_attempt_events(key: tuple[str, str], rows: list[dict[str, Any]]) -> dict[str, Any]:
    attempt_id, nonce = key
    events = [row["event"] for row in rows]
    seqs = [event["seq"] for event in events]
    registrations = [event for event in events if event["kind"] == "attempt_registered"]
    _require(len(registrations) == 1 and events[0]["kind"] == "attempt_registered",
             f"attempt {attempt_id} must have exactly one first registration event")
    registration = registrations[0]
    for event in events:
        for field in ("case_id", "qualification_row_sha256"):
            _require(event[field] == registration[field],
                     f"attempt {attempt_id} changes its registered {field}")
    terminal_events = [event for event in events if event["kind"] == "attempt_terminal"]
    _require(len(terminal_events) <= 1, f"attempt {attempt_id} has duplicate attempt_terminal events")
    if terminal_events:
        _require(events[-1] is terminal_events[0], f"attempt {attempt_id} has events after its terminal event")

    spawns: dict[str, dict[str, Any]] = {}
    receipts: dict[str, dict[str, Any]] = {}
    process_terminals: dict[tuple[str, str], dict[str, Any]] = {}
    for event in events:
        kind = event["kind"]
        if kind == "attempt_spawn":
            stage = event["stage"]
            _require(stage not in spawns, f"attempt {attempt_id} has more than one {stage} invocation root")
            _require(event["process_generation_id"] not in {
                row["process_generation_id"] for row in spawns.values()
            }, f"attempt {attempt_id} reuses a process generation across stages")
            spawns[stage] = event
        elif kind == "stage_receipt":
            stage = event["stage"]
            _require(stage not in receipts, f"attempt {attempt_id} has duplicate {stage} stage receipts")
            receipts[stage] = event
        elif kind == "process_terminal":
            stage = event["stage"]
            generation = event["process_generation_id"]
            key_pair = (stage, generation)
            _require(key_pair not in process_terminals,
                     f"attempt {attempt_id} has duplicate process terminal for {stage}/{generation}")
            _require(stage in spawns and spawns[stage]["process_generation_id"] == generation,
                     f"attempt {attempt_id} process terminal has no matching invocation root")
            _require(spawns[stage]["seq"] < event["seq"],
                     f"attempt {attempt_id} process terminal precedes its invocation root")
            process_terminals[key_pair] = event

    for stage, spawn in spawns.items():
        receipt = receipts.get(stage)
        terminal = process_terminals.get((stage, spawn["process_generation_id"]))
        if receipt is not None:
            _require(terminal is not None,
                     f"attempt {attempt_id} {stage} receipt exists without a process terminal")
            _require(terminal["seq"] < receipt["seq"],
                     f"attempt {attempt_id} {stage} process terminal must precede its receipt")
            _require(spawn["seq"] < terminal["seq"] < receipt["seq"],
                     f"attempt {attempt_id} {stage} process event order is invalid")
    for stage in ("B", "C"):
        if stage in receipts:
            _require(stage in spawns,
                     f"attempt {attempt_id} {stage} receipt lacks its required process invocation root")
    if "C" in spawns or "C" in receipts:
        _require("B" in receipts and receipts["B"]["seq"] <
                 (spawns.get("C") or receipts["C"])["seq"],
                 f"attempt {attempt_id} C stage appears before a completed B receipt")
    if "D" in spawns or "D" in receipts:
        _require("C" in receipts and receipts["C"]["seq"] <
                 (spawns.get("D") or receipts["D"])["seq"],
                 f"attempt {attempt_id} D stage appears before a completed C receipt")
    for stage in STAGES:
        receipt = receipts.get(stage)
        if receipt is None:
            continue
        previous = [receipts[prior]["seq"] for prior in STAGES[:STAGES.index(stage)] if prior in receipts]
        _require(not previous or max(previous) < receipt["seq"],
                 f"attempt {attempt_id} stage receipts are not ordered B→C→D")

    terminal_outcome = terminal_events[0]["outcome"] if terminal_events else None
    if terminal_outcome == "not_started":
        _require(not spawns and not receipts and not process_terminals,
                 f"attempt {attempt_id} not_started terminal conflicts with stage events")
    if terminal_outcome == "passed":
        _require(set(receipts) == set(STAGES),
                 f"attempt {attempt_id} passed terminal lacks B/C/D stage receipts")
    process_terminals_closed = all(
        (stage, spawn["process_generation_id"]) in process_terminals
        for stage, spawn in spawns.items()
    )
    attempt_events_closed = bool(terminal_events) and process_terminals_closed

    common_identity = {
        field: events[0][field]
        for field in ("case_id", "qualification_row_sha256", "attempt_id", "nonce_hex")
    }
    return {
        **common_identity,
        "registration_seq": registrations[0]["seq"],
        "event_seqs": seqs,
        "stage_spawn_seqs": {stage: spawns[stage]["seq"] if stage in spawns else None for stage in STAGES},
        "stage_receipt_seqs": {stage: receipts[stage]["seq"] if stage in receipts else None for stage in STAGES},
        "stage_bundle_refs": {
            stage: receipts[stage]["receipt_ref"] if stage in receipts else None for stage in STAGES
        },
        "claimed_terminal_outcome": terminal_outcome,
        "terminal_seq": terminal_events[0]["seq"] if terminal_events else None,
        "process_terminals_closed": process_terminals_closed,
        "attempt_events_closed": attempt_events_closed,
        "attempt_outcome": "unresolved",
    }


def _inspect(raw: bytes, qualification_matrix_raw: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        ledger = strict_json_object(raw, label="F8 R008 attempt ledger", max_bytes=MAX_LEDGER_BYTES)
    except ValueError as error:
        raise AttemptLedgerV1Error(str(error)) from error
    _require(set(ledger) == LEDGER_FIELDS, "ledger top-level fields are not exact")
    _require(ledger["schema"] == LEDGER_SCHEMA, "ledger schema is not the fixed V1 schema")
    _require(ledger["scope_id"] == SCOPE_ID, "ledger scope is not the fixed F8 R008 scope")
    _digest(ledger["qualification_matrix_raw_sha256"], "qualification_matrix_raw_sha256")
    matrix = inspect_untrusted_qualification_matrix(qualification_matrix_raw)
    _require(matrix["matrix_raw_sha256"] == ledger["qualification_matrix_raw_sha256"],
             "raw qualification matrix bytes do not match the ledger matrix digest")
    matrix_rows = {row["case_id"]: row["qualification_row_sha256"] for row in matrix["rows"]}
    _identifier(ledger["supervisor_source_id"], "supervisor_source_id")
    start_hex = ledger["coverage_start_ns_hex"]
    end_hex = ledger["coverage_end_ns_hex"]
    _require(type(start_hex) is str and bool(_HEX16.fullmatch(start_hex)),
             "coverage_start_ns_hex must be 16 lowercase hexadecimal characters")
    _require(type(end_hex) is str and bool(_HEX16.fullmatch(end_hex)),
             "coverage_end_ns_hex must be 16 lowercase hexadecimal characters")
    start_ns, end_ns = int(start_hex, 16), int(end_hex, 16)
    _require(start_ns <= end_ns, "ledger coverage start exceeds its end")
    _int(ledger["event_count"], "event_count")
    _require(type(ledger["overflow"]) is bool and ledger["overflow"] is False,
             "ledger overflow must be the builtin false boolean")
    _int(ledger["lost_count"], "lost_count")
    _require(ledger["lost_count"] == 0, "ledger lost_count must be zero")
    events = ledger["events"]
    _require(type(events) is list and len(events) == ledger["event_count"],
             "event_count must exactly equal the builtin events list length")

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    ids_seen: dict[str, tuple[str, str]] = {}
    nonces_seen: dict[str, tuple[str, str]] = {}
    row_by_case: dict[str, str] = {}
    previous_mono = start_ns
    parsed_events: list[dict[str, Any]] = []
    for expected_seq, raw_event in enumerate(events):
        parsed = _parse_event(raw_event, expected_seq, start_ns=start_ns, end_ns=end_ns)
        _require(parsed["mono_ns"] >= previous_mono,
                 f"event {expected_seq} monotonic time moved backwards")
        previous_mono = parsed["mono_ns"]
        event = parsed["event"]
        identity = (event["attempt_id"], event["nonce_hex"])
        prior_id = ids_seen.setdefault(event["attempt_id"], identity)
        prior_nonce = nonces_seen.setdefault(event["nonce_hex"], identity)
        _require(prior_id == identity, "attempt_id is reused with a different nonce")
        _require(prior_nonce == identity, "nonce_hex is reused by another attempt")
        prior_row = row_by_case.setdefault(event["case_id"], event["qualification_row_sha256"])
        _require(prior_row == event["qualification_row_sha256"],
                 f"case {event['case_id']} is bound to multiple qualification row digests")
        grouped.setdefault(identity, []).append(parsed)
        parsed_events.append(parsed)

    attempts = [
        _check_attempt_events(key, rows)
        for key, rows in sorted(grouped.items(), key=lambda item: item[1][0]["event"]["seq"])
    ]
    for attempt in attempts:
        _require(attempt["case_id"] in matrix_rows,
                 f"ledger attempt references non-qualification case {attempt['case_id']}")
        _require(attempt["qualification_row_sha256"] == matrix_rows[attempt["case_id"]],
                 f"ledger row digest differs from frozen matrix row {attempt['case_id']}")
    attempt_by_identity = {
        (item["attempt_id"], item["nonce_hex"]): item for item in attempts
    }
    return ledger, {
        "attempts": attempts,
        "attempt_by_identity": attempt_by_identity,
        "events": parsed_events,
        "coverage_start_ns": start_ns,
        "coverage_end_ns": end_ns,
        "matrix": matrix,
    }


def inspect_untrusted_attempt_ledger(raw: bytes, *, qualification_matrix_raw: bytes) -> dict[str, Any]:
    """Parse a bounded raw ledger and return only an untrusted structural summary.

    ``attempt_ledger_complete`` is fixed false: this API has no trusted
    descriptor-root, supervisor attestation, coverage admission record, or
    active key registry. Per-attempt outcomes are likewise fixed unresolved;
    ``claimed_terminal_outcome`` is preserved only as an explicitly untrusted
    ledger claim.
    """
    _require(type(raw) is bytes, "ledger input must be exact raw bytes")
    ledger, parsed = _inspect(raw, qualification_matrix_raw)
    return {
        "schema": DIAGNOSTIC_SCHEMA,
        "ledger_schema": LEDGER_SCHEMA,
        "scope_id": SCOPE_ID,
        "qualification_matrix_raw_sha256": ledger["qualification_matrix_raw_sha256"],
        "qualification_matrix_row_count": parsed["matrix"]["row_count"],
        "qualification_matrix_rows": parsed["matrix"]["rows"],
        "frozen_matrix_source_authenticated": False,
        "supervisor_source_id": ledger["supervisor_source_id"],
        "coverage_start_ns_hex": ledger["coverage_start_ns_hex"],
        "coverage_end_ns_hex": ledger["coverage_end_ns_hex"],
        "event_count": ledger["event_count"],
        "attempt_count": len(parsed["attempts"]),
        "ledger_raw_bytes": len(raw),
        "ledger_raw_sha256": sha256_bytes(raw),
        "ledger_structure_valid": True,
        "attempt_events_closed": bool(parsed["attempts"])
        and all(item["attempt_events_closed"] for item in parsed["attempts"]),
        "supervisor_attestation_verified": False,
        "attempt_ledger_complete": False,
        "attempts": parsed["attempts"],
        "qualification_adjudicated": False,
        "T1_numerical": False,
        "qualification_credit": 0,
    }


def validate_attempt_result_ledger_projection_v2(
    attempt_result: Any,
    ledger_raw: bytes,
    *,
    qualification_matrix_raw: bytes,
) -> None:
    """Check an untrusted V2 result's identity/seq/receipt-ref projection.

    This proves only that the two caller-provided structures agree with one
    another. It does not prove either structure came from a trusted producer.
    """
    try:
        validate_untrusted_attempt_result_v2(attempt_result)
    except AttemptResultV2Error as error:
        raise AttemptLedgerV1Error(f"attempt result is not an admissible unresolved V2 diagnostic: {error}") from error
    ledger, parsed = _inspect(ledger_raw, qualification_matrix_raw)
    _validate_attempt_projection(attempt_result, ledger, parsed)


def _validate_attempt_projection(
    attempt_result: dict[str, Any],
    ledger: dict[str, Any],
    parsed: dict[str, Any],
) -> dict[str, Any]:
    _require(attempt_result["scope_id"] == ledger["scope_id"],
             "attempt result scope differs from ledger scope")
    attempt = parsed["attempt_by_identity"].get(
        (attempt_result["attempt_id"], attempt_result["nonce_hex"]),
    )
    _require(attempt is not None, "attempt result does not identify exactly one ledger attempt")
    for field in ("case_id", "qualification_row_sha256"):
        _require(attempt_result[field] == attempt[field],
                 f"attempt result {field} differs from its ledger registration")
    _require(attempt_result["attempt_ledger_registration_seq"] == attempt["registration_seq"],
             "attempt result registration seq differs from ledger")
    _require(attempt_result["attempt_ledger_event_seqs"] == attempt["event_seqs"],
             "attempt result event seq inventory differs from ledger")
    _require(attempt_result["stage_bundle_refs"] == attempt["stage_bundle_refs"],
             "attempt result stage refs differ from ledger stage_receipt refs")
    for stage in STAGES:
        ref = attempt_result["stage_bundle_refs"][stage]
        status = attempt_result["stage_receipt_statuses"][stage]
        if status == "passed":
            _require(ref is not None,
                     f"attempt result {stage} passed status lacks a ledger stage_receipt ref")
        if status == "not_run":
            _require(ref is None,
                     f"attempt result {stage} not_run status conflicts with a ledger stage_receipt ref")
    return attempt


def build_untrusted_attempt_aggregate_v2(
    qualification_matrix_raw: bytes,
    ledger_raw: bytes,
    *,
    attempt_ledger_ref: Any,
    attempt_results: Any,
    attempt_ledger_attestation_ref: Any = None,
) -> dict[str, Any]:
    """Build the exact V2 aggregate shape, conservatively unresolved and untrusted.

    It requires one unresolved per-attempt diagnostic for every registration
    observed in the supplied ledger, preserves retries and all 15 matrix rows,
    and never infers missing. The ledger ref is checked against supplied bytes,
    not resolved through a trusted descriptor registry. Non-null attestations
    are rejected until the active supervisor-key trust verifier exists.
    """
    _require(attempt_ledger_attestation_ref is None,
             "non-null ledger attestations require an active supervisor trust verifier")
    ledger, parsed = _inspect(ledger_raw, qualification_matrix_raw)
    _reference(attempt_ledger_ref, expected_stage=None, label="attempt_ledger_ref")
    _require(attempt_ledger_ref["stage"] == "runtime"
             and attempt_ledger_ref["role"] == "attempt_ledger",
             "attempt_ledger_ref must target the fixed runtime/attempt_ledger role")
    _require(attempt_ledger_ref["bytes"] == len(ledger_raw)
             and attempt_ledger_ref["sha256"] == sha256_bytes(ledger_raw),
             "attempt_ledger_ref byte count or raw SHA differs from the supplied ledger")
    _require(type(attempt_results) is list,
             "attempt_results must be a builtin list containing every observed ledger attempt")

    ledger_by_identity = parsed["attempt_by_identity"]
    result_by_identity: dict[tuple[str, str], tuple[int, dict[str, Any]]] = {}
    seen_attempt_ids: set[str] = set()
    seen_nonces: set[str] = set()
    for result in attempt_results:
        try:
            validate_untrusted_attempt_result_v2(result)
        except AttemptResultV2Error as error:
            raise AttemptLedgerV1Error(
                f"aggregate attempt is not an admissible unresolved V2 diagnostic: {error}"
            ) from error
        identity = (result["attempt_id"], result["nonce_hex"])
        _require(identity in ledger_by_identity,
                 "aggregate contains an attempt not registered in the supplied ledger")
        _require(result["attempt_id"] not in seen_attempt_ids and result["nonce_hex"] not in seen_nonces,
                 "aggregate repeats an attempt ID or nonce")
        seen_attempt_ids.add(result["attempt_id"])
        seen_nonces.add(result["nonce_hex"])
        ledger_attempt = _validate_attempt_projection(result, ledger, parsed)
        result_by_identity[identity] = (ledger_attempt["registration_seq"], result)
    _require(set(result_by_identity) == set(ledger_by_identity),
             "aggregate attempt records do not preserve the complete observed ledger registration inventory")

    ordered_results = sorted(result_by_identity.values(), key=lambda item: item[0])
    results_by_case: dict[str, list[dict[str, Any]]] = {
        row["case_id"]: [] for row in parsed["matrix"]["rows"]
    }
    attempt_counts = {
        "not_started": 0, "passed": 0, "failed": 0, "incomplete": 0,
        "timeout": 0, "oom": 0, "signaled": 0, "unresolved": 0,
    }
    for _registration_seq, result in ordered_results:
        results_by_case[result["case_id"]].append(copy.deepcopy(result))
        attempt_counts[result["attempt_outcome"]] += 1

    case_rows = [
        {
            "case_id": row["case_id"],
            "qualification_row_sha256": row["qualification_row_sha256"],
            "case_outcome": "unresolved",
            "qualifying_attempt_id": None,
            "attempts": results_by_case[row["case_id"]],
        }
        for row in parsed["matrix"]["rows"]
    ]
    aggregate = {
        "schema": AGGREGATE_SCHEMA,
        "scope_id": SCOPE_ID,
        "qualification_matrix_raw_sha256": parsed["matrix"]["matrix_raw_sha256"],
        "attempt_ledger_ref": copy.deepcopy(attempt_ledger_ref),
        "attempt_ledger_raw_sha256": sha256_bytes(ledger_raw),
        "attempt_ledger_attestation_ref": None,
        "expected_case_count": 15,
        "case_rows": case_rows,
        "case_outcome_counts": {"passed": 0, "failed": 0, "missing": 0, "unresolved": 15},
        "attempt_outcome_counts": attempt_counts,
        "aggregate_outcome": "accounting_unresolved",
        "attempt_ledger_complete": False,
        "qualification_adjudicated": False,
        "T1_numerical": False,
        "qualification_credit": 0,
    }
    _require(set(aggregate) == AGGREGATE_FIELDS,
             "internal aggregate projection no longer matches the exact V2 field set")
    return aggregate


__all__ = [
    "AGGREGATE_FIELDS", "AGGREGATE_SCHEMA", "AttemptLedgerV1Error", "DIAGNOSTIC_SCHEMA", "LEDGER_SCHEMA",
    "build_untrusted_attempt_aggregate_v2",
    "inspect_untrusted_attempt_ledger", "inspect_untrusted_qualification_matrix",
    "validate_attempt_result_ledger_projection_v2",
]
