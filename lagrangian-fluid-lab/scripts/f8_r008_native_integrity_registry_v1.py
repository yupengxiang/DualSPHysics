"""Fail-closed aggregation for the frozen F8 R008 native-integrity gate registry.

This module validates a fixed 15-by-8 matrix of caller-supplied gate states. It
does not evaluate scientific gates or verify evidence bytes; the output is an
aggregation report only and never grants native-integrity, T1, readiness, or
qualification credit.
"""
from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any

from scripts import f8_r008_per_case_bundle_verifier_v1 as bundle


SCHEMA = "core.cfd.f8.r008_native_integrity_registry.v1"
CASE_COUNT = 15
GATE_COUNT = 8
VALID_STATES = ("defined_pass", "defined_fail", "open", "missing")
FROZEN_SCOPE_SHA256 = "65671b42523cd3a5f82338cc7e2d88890af634195d7013ad969311166ab36ac8"
FROZEN_DEFINITION_PACK_SHA256 = "d5b657db398e0c0b102cdb84de8fe0a302c22c85d4bbf16bc0b6e6bf16065fcb"

EXPECTED_QUALIFICATION_CASE_IDS = (
    "space-q0-dp0p0090",
    "space-q0-dp0p0075",
    "space-q0-dp0p0060",
    "space-q0p5-dp0p0090",
    "space-q0p5-dp0p0075",
    "space-q0p5-dp0p0060",
    "space-q1-dp0p0090",
    "space-q1-dp0p0075",
    "space-q1-dp0p0060",
    "internal-q0p25-dp0p0075",
    "internal-q0p25-dp0p0060",
    "internal-q0p75-dp0p0075",
    "internal-q0p75-dp0p0060",
    "time-q0p5-dp0p0075-cfl0p1",
    "cadence-q0p5-dp0p0075-output128",
)

GATE_REGISTRY = (
    ("native_state_finite", "open", ("defined_fail", "open", "missing")),
    ("density_range", "defined", VALID_STATES),
    ("mach_limit", "defined", VALID_STATES),
    ("wall_penetration_limit", "open", ("open", "missing")),
    ("excluded_fluid_particles_zero", "open", ("defined_fail", "open", "missing")),
    ("particle_overlap_absent", "open", ("open", "missing")),
    ("inclusive_three_period_window_complete", "defined", VALID_STATES),
    ("control_no_extrapolation", "defined", VALID_STATES),
)
GATE_IDS = tuple(item[0] for item in GATE_REGISTRY)
_GATE_BY_ID = MappingProxyType({gate_id: (definition_status, outcomes)
                                for gate_id, definition_status, outcomes in GATE_REGISTRY})
_SHA256_HEX = frozenset("0123456789abcdef")
_CELL_FIELDS = frozenset({"status", "evidence_sha256"})
_CASE_FIELDS = frozenset({"case_id", "gate_results"})


class NativeIntegrityRegistryError(ValueError):
    """A fixed-registry input is malformed or does not match the frozen scope."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise NativeIntegrityRegistryError(message)


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in _SHA256_HEX for char in value)
    )


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def _read_frozen_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    _require(
        bundle.FROZEN_INPUT_SHA256.get("scope") == FROZEN_SCOPE_SHA256
        and bundle.FROZEN_INPUT_SHA256.get("definition_pack") == FROZEN_DEFINITION_PACK_SHA256,
        "bundle verifier frozen hashes differ from the registry's pinned inputs",
    )
    lab_fd, _lab_path = bundle._open_absolute_directory(bundle.LAB)
    try:
        scope_payload = bundle._stable_read_beneath(
            lab_fd, bundle.FROZEN_SCOPE_RECEIPT.relative_to(bundle.LAB).as_posix(),
            bundle.MAX_RECEIPT_BYTES,
        )
        pack_payload = bundle._stable_read_beneath(
            lab_fd, bundle.FROZEN_DEFINITION_PACK.relative_to(bundle.LAB).as_posix(),
            bundle.MAX_RECEIPT_BYTES,
        )
    finally:
        os.close(lab_fd)
    _require(hashlib.sha256(scope_payload).hexdigest() == FROZEN_SCOPE_SHA256,
             "frozen R008 scope receipt hash changed")
    _require(hashlib.sha256(pack_payload).hexdigest() == FROZEN_DEFINITION_PACK_SHA256,
             "frozen R008 Definition/control pack hash changed")
    scope = bundle._parse_json(scope_payload, "frozen R008 scope receipt")
    pack = bundle._parse_json(pack_payload, "frozen R008 Definition/control pack")
    _require(isinstance(scope, dict) and isinstance(pack, dict),
             "frozen R008 inputs must be JSON objects")
    return scope, pack


def frozen_qualification_case_ids() -> tuple[str, ...]:
    """Return the pinned qualification denominator after verifying both receipts."""
    scope, pack = _read_frozen_inputs()
    matrix = scope.get("matrix")
    _require(isinstance(matrix, dict), "frozen R008 scope matrix is malformed")
    scope_rows = matrix.get("rows")
    pack_rows = pack.get("cases")
    _require(isinstance(scope_rows, list) and isinstance(pack_rows, list),
             "frozen R008 case rows are missing")
    scope_ids = tuple(
        row.get("case_id") for row in scope_rows
        if isinstance(row, dict) and row.get("qualification_only") is True
    )
    pack_ids = tuple(
        row.get("case_id") for row in pack_rows
        if isinstance(row, dict) and row.get("qualification_only") is True
    )
    _require(all(isinstance(case_id, str) and case_id for case_id in scope_ids + pack_ids),
             "frozen R008 qualification case ID is malformed")
    _require(len(scope_ids) == CASE_COUNT and len(set(scope_ids)) == CASE_COUNT,
             "frozen R008 scope qualification denominator is not exactly 15 unique cases")
    _require(scope_ids == EXPECTED_QUALIFICATION_CASE_IDS,
             "frozen R008 scope qualification IDs/order differ from the registry")
    _require(pack_ids == EXPECTED_QUALIFICATION_CASE_IDS,
             "frozen Definition/control qualification IDs/order differ from the registry")
    return EXPECTED_QUALIFICATION_CASE_IDS


def _validate_case_results(
    case_results: Sequence[Mapping[str, Any]],
    expected_case_ids: Sequence[str],
) -> tuple[list[dict[str, Any]], Counter[str], dict[str, Counter[str]]]:
    _require(isinstance(case_results, Sequence) and not isinstance(case_results, (str, bytes)),
             "case results must be an ordered sequence")
    _require(len(expected_case_ids) == CASE_COUNT
             and len(set(expected_case_ids)) == CASE_COUNT
             and tuple(expected_case_ids) == EXPECTED_QUALIFICATION_CASE_IDS,
             "expected case denominator differs from the pinned 15-case registry")
    _require(len(case_results) == CASE_COUNT,
             "native-integrity matrix must contain exactly 15 case rows")

    observed_ids: list[str] = []
    normalized: list[dict[str, Any]] = []
    state_counts: Counter[str] = Counter({state: 0 for state in VALID_STATES})
    by_gate: dict[str, Counter[str]] = {
        gate_id: Counter({state: 0 for state in VALID_STATES}) for gate_id in GATE_IDS
    }

    for row_index, row in enumerate(case_results):
        _require(isinstance(row, Mapping) and set(row) == _CASE_FIELDS,
                 f"case row {row_index} has unexpected or missing fields")
        case_id = row["case_id"]
        _require(isinstance(case_id, str) and case_id,
                 f"case row {row_index} has an invalid case_id")
        observed_ids.append(case_id)
        gates = row["gate_results"]
        _require(isinstance(gates, Mapping) and set(gates) == set(GATE_IDS),
                 f"case {case_id} must contain the exact fixed eight gate IDs")

        normalized_gates: dict[str, dict[str, Any]] = {}
        for gate_id in GATE_IDS:
            result = gates[gate_id]
            _require(isinstance(result, Mapping) and set(result) == _CELL_FIELDS,
                     f"case {case_id} gate {gate_id} has unexpected or missing fields")
            state = result["status"]
            evidence_sha256 = result["evidence_sha256"]
            _require(state in VALID_STATES,
                     f"case {case_id} gate {gate_id} has an invalid state")
            _definition_status, allowed_outcomes = _GATE_BY_ID[gate_id]
            _require(state in allowed_outcomes,
                     f"case {case_id} gate {gate_id} cannot report {state} under its reviewed definition")
            if state in ("defined_pass", "defined_fail"):
                _require(_is_sha256(evidence_sha256),
                         f"case {case_id} gate {gate_id} adjudication lacks a valid evidence SHA-256")
            else:
                _require(evidence_sha256 is None or _is_sha256(evidence_sha256),
                         f"case {case_id} gate {gate_id} has an invalid optional evidence SHA-256")
            state_counts[state] += 1
            by_gate[gate_id][state] += 1
            normalized_gates[gate_id] = {
                "status": state,
                "evidence_sha256": evidence_sha256,
            }
        normalized.append({"case_id": case_id, "gate_results": normalized_gates})

    _require(tuple(observed_ids) == tuple(expected_case_ids),
             "case IDs are missing, duplicated, substituted, or out of frozen order")
    return normalized, state_counts, by_gate


def _aggregate_for_case_ids(
    case_results: Sequence[Mapping[str, Any]],
    expected_case_ids: Sequence[str],
) -> dict[str, Any]:
    normalized, state_counts, by_gate = _validate_case_results(case_results, expected_case_ids)
    has_failure = state_counts["defined_fail"] > 0
    has_incomplete = state_counts["open"] > 0 or state_counts["missing"] > 0
    if has_failure:
        aggregate = "failed"
    elif has_incomplete:
        aggregate = "incomplete"
    else:
        aggregate = "passed"

    registry_projection = [
        {
            "gate_id": gate_id,
            "definition_status": definition_status,
            "outcomes": list(outcomes),
        }
        for gate_id, definition_status, outcomes in GATE_REGISTRY
    ]
    registry_bytes = _canonical_json(registry_projection)
    case_ids_bytes = _canonical_json(list(expected_case_ids))
    return {
        "schema": SCHEMA,
        "aggregation_status": aggregate,
        "aggregation_only": True,
        "evidence_bindings_verified": False,
        "native_integrity_evaluated": False,
        "T1_numerical": False,
        "readiness_pass": False,
        "qualification_credit": 0,
        "case_count": CASE_COUNT,
        "gate_count": GATE_COUNT,
        "denominator_cells": CASE_COUNT * GATE_COUNT,
        "case_ids": list(expected_case_ids),
        "case_ids_sha256": hashlib.sha256(case_ids_bytes).hexdigest(),
        "gate_registry": [
            dict(item) for item in registry_projection
        ],
        "gate_registry_sha256": hashlib.sha256(registry_bytes).hexdigest(),
        "frozen_scope_sha256": FROZEN_SCOPE_SHA256,
        "frozen_definition_pack_sha256": FROZEN_DEFINITION_PACK_SHA256,
        "state_counts": {state: state_counts[state] for state in VALID_STATES},
        "gate_state_counts": {
            gate_id: {state: by_gate[gate_id][state] for state in VALID_STATES}
            for gate_id in GATE_IDS
        },
        "case_results": normalized,
    }


def aggregate_native_integrity_statuses(
    case_results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Aggregate 120 reviewed status cells without evaluating their evidence."""
    return _aggregate_for_case_ids(case_results, frozen_qualification_case_ids())


__all__ = [
    "CASE_COUNT", "GATE_COUNT", "GATE_IDS", "GATE_REGISTRY", "SCHEMA",
    "EXPECTED_QUALIFICATION_CASE_IDS", "NativeIntegrityRegistryError",
    "aggregate_native_integrity_statuses", "frozen_qualification_case_ids",
]
