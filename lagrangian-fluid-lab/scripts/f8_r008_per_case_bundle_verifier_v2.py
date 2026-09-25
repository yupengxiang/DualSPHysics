"""Non-authorizing shape guard for synthetic F8 R008 attempt-result V2 objects.

This module does not verify receipts, ledgers, supervisor attestations, stage
execution, native table contents, or qualification. Until those independent
producers and trust roots exist, it accepts only unresolved records with every
semantic and qualification claim fixed false. A successful call means only
that the supplied object obeys this restricted diagnostic encoding.
"""
from __future__ import annotations

import math
import re
from typing import Any


SCHEMA = "core.cfd.f8.r008_per_case_attempt_verification.v2"
SCOPE_ID = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008"
ATTEMPT_RESULT_FIELDS = frozenset({
    "schema", "scope_id", "case_id", "qualification_row_sha256", "attempt_id", "nonce_hex",
    "attempt_ledger_registration_seq", "attempt_ledger_event_seqs", "stage_bundle_refs",
    "stage_receipt_statuses", "definition_control_raw_bindings_verified",
    "materialization_binary_semantics_verified", "gencase_execution_semantics_verified",
    "solver_execution_semantics_verified", "native_table_content_matches_C_raw_frames",
    "loaded_module_code_identity_verified", "attempt_outcome", "expected_frame_count",
    "actual_frame_ordinals", "actual_time_axis_ieee754_hex", "failure_class",
    "failure_position", "qualification_adjudicated", "T1_numerical", "qualification_credit",
})
STAGES = ("B", "C", "D")
STAGE_RECEIPT_ROLES = {"B": "b_receipt", "C": "c_v1_receipt", "D": "d_receipt"}
MAX_EXPECTED_FRAME_COUNT = 385
STAGE_STATUSES = frozenset({
    "not_run", "passed", "failed", "incomplete", "timeout", "oom", "signaled",
})
SEMANTIC_BOOLEAN_FIELDS = frozenset({
    "definition_control_raw_bindings_verified",
    "materialization_binary_semantics_verified",
    "gencase_execution_semantics_verified",
    "solver_execution_semantics_verified",
    "native_table_content_matches_C_raw_frames",
    "loaded_module_code_identity_verified",
})
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REFERENCE_FIELDS = frozenset({"stage", "role", "object_id", "bytes", "sha256"})


class AttemptResultV2Error(ValueError):
    """The object is not a valid non-authorizing attempt-result diagnostic."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AttemptResultV2Error(message)


def _builtin_int(value: Any, label: str, *, minimum: int = 0) -> None:
    _require(type(value) is int and value >= minimum, f"{label} must be a builtin integer >= {minimum}")


def _builtin_str(value: Any, label: str) -> None:
    _require(type(value) is str, f"{label} must be a builtin string")


def _identifier(value: Any, label: str) -> None:
    _require(type(value) is str and bool(_IDENTIFIER.fullmatch(value)),
             f"{label} must match the fixed lowercase ASCII identifier grammar")


def _validate_ref(value: Any, stage: str) -> None:
    if value is None:
        return
    _require(type(value) is dict and set(value) == _REFERENCE_FIELDS,
             f"{stage} stage reference fields are not exact")
    _builtin_str(value["stage"], f"{stage} reference stage")
    _require(value["stage"] == stage, f"{stage} stage reference names another stage")
    _identifier(value["role"], f"{stage} reference role")
    _require(value["role"] == STAGE_RECEIPT_ROLES[stage],
             f"{stage} reference does not target the fixed {STAGE_RECEIPT_ROLES[stage]} role")
    _identifier(value["object_id"], f"{stage} reference object_id")
    _builtin_int(value["bytes"], f"{stage} reference bytes", minimum=1)
    _require(type(value["sha256"]) is str and bool(_SHA256.fullmatch(value["sha256"])),
             f"{stage} reference sha256 is malformed")


def validate_untrusted_attempt_result_v2(value: Any) -> None:
    """Validate only the restricted, untrusted V2 diagnostic shape.

    The function deliberately returns no capability or normalized result. It
    rejects every caller-supplied semantic/qualification ``true`` and every
    outcome other than ``unresolved`` because this module has no trusted ledger,
    execution parser, supervisor attestation, or qualification adjudicator.
    """
    _require(type(value) is dict and set(value) == ATTEMPT_RESULT_FIELDS,
             "attempt result must be a builtin object with the exact V2 field set")
    _builtin_str(value["schema"], "schema")
    _require(value["schema"] == SCHEMA, "attempt result schema is not the fixed V2 schema")
    _builtin_str(value["scope_id"], "scope_id")
    _require(value["scope_id"] == SCOPE_ID, "attempt result scope is not the fixed F8 R008 scope")
    _identifier(value["case_id"], "case_id")
    _require(type(value["qualification_row_sha256"]) is str
             and bool(_SHA256.fullmatch(value["qualification_row_sha256"])),
             "qualification row sha256 is malformed")
    _identifier(value["attempt_id"], "attempt_id")
    _require(type(value["nonce_hex"]) is str and bool(_HEX32.fullmatch(value["nonce_hex"])),
             "nonce_hex must be 32 lowercase hexadecimal characters")

    registration_seq = value["attempt_ledger_registration_seq"]
    _builtin_int(registration_seq, "attempt_ledger_registration_seq")
    event_seqs = value["attempt_ledger_event_seqs"]
    _require(type(event_seqs) is list and bool(event_seqs),
             "attempt_ledger_event_seqs must be a nonempty builtin list")
    for index, seq in enumerate(event_seqs):
        _builtin_int(seq, f"attempt_ledger_event_seqs[{index}]")
        if index:
            _require(seq > event_seqs[index - 1], "attempt ledger event seqs must be strictly increasing")
    _require(event_seqs[0] == registration_seq,
             "attempt ledger event seqs must begin with the registration seq")

    refs = value["stage_bundle_refs"]
    _require(type(refs) is dict and set(refs) == set(STAGES), "stage_bundle_refs keys are not exact")
    for stage in STAGES:
        _validate_ref(refs[stage], stage)
    statuses = value["stage_receipt_statuses"]
    _require(type(statuses) is dict and set(statuses) == set(STAGES),
             "stage_receipt_statuses keys are not exact")
    _require(all(type(statuses[stage]) is str and statuses[stage] in STAGE_STATUSES
                 for stage in STAGES), "stage receipt status is outside the fixed enum")

    for field in SEMANTIC_BOOLEAN_FIELDS:
        _require(type(value[field]) is bool, f"{field} must be a builtin boolean")
        _require(value[field] is False,
                 f"{field} cannot be caller-asserted true without an independent verifier")
    _builtin_str(value["attempt_outcome"], "attempt_outcome")
    _require(value["attempt_outcome"] == "unresolved",
             "attempt outcome must remain unresolved without a trusted ledger and execution source")

    expected_count = value["expected_frame_count"]
    _builtin_int(expected_count, "expected_frame_count")
    _require(expected_count <= MAX_EXPECTED_FRAME_COUNT,
             f"expected_frame_count exceeds the fixed F8 R008 maximum {MAX_EXPECTED_FRAME_COUNT}")
    ordinals = value["actual_frame_ordinals"]
    times = value["actual_time_axis_ieee754_hex"]
    _require(type(ordinals) is list and type(times) is list,
             "frame ordinals and time axis must be builtin lists")
    _require(len(ordinals) == len(times) <= expected_count,
             "actual frame prefix lengths exceed or disagree with the expected count")
    for ordinal, value_ordinal in enumerate(ordinals):
        _builtin_int(value_ordinal, f"actual_frame_ordinals[{ordinal}]")
        _require(value_ordinal == ordinal, "actual frame ordinals must be a contiguous zero-based prefix")
    for index, encoded in enumerate(times):
        _require(type(encoded) is str, f"actual_time_axis_ieee754_hex[{index}] must be a string")
        try:
            number = float.fromhex(encoded)
        except (ValueError, OverflowError) as error:
            raise AttemptResultV2Error(f"actual time-axis value {index} is not hexadecimal binary64") from error
        _require(math.isfinite(number) and number.hex() == encoded,
                 f"actual time-axis value {index} is non-finite or noncanonical")

    _builtin_str(value["failure_class"], "failure_class")
    _require(value["failure_class"] == "unresolved_evidence",
             "failure_class must remain unresolved_evidence without a trusted terminal source")
    _require(value["failure_position"] is None,
             "failure_position must remain null without trusted frame-progress evidence")
    for field in ("qualification_adjudicated", "T1_numerical"):
        _require(type(value[field]) is bool and value[field] is False,
                 f"{field} is fixed false in the non-authorizing V2 diagnostic")
    _require(type(value["qualification_credit"]) is int and value["qualification_credit"] == 0,
             "qualification_credit must be the builtin integer zero")


__all__ = [
    "ATTEMPT_RESULT_FIELDS", "AttemptResultV2Error", "SCHEMA",
    "validate_untrusted_attempt_result_v2",
]
