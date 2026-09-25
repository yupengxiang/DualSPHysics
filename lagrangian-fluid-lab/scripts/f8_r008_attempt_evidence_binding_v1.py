"""Bind F8 R008 attempt projections to supplied ledger and artifact bytes.

This additive diagnostic composes the exact V2 attempt projection, the
attempt-ledger raw-reference binder, and the 15-row unresolved aggregate. It
also cross-checks each caller status against its referenced raw stage-receipt
envelope. Inputs remain untrusted claims: no descriptor root, supervisor,
producer, execution, native semantics, or qualification is authenticated.
"""
from __future__ import annotations

from typing import Any, Mapping

from scripts import f8_r008_attempt_ledger_v1 as ledger_v1


SCHEMA = "core.cfd.f8.r008_attempt_evidence_binding.v1"
STAGES = ("B", "C", "D")


class AttemptEvidenceBindingError(ValueError):
    """The supplied attempt projection and untrusted raw evidence disagree."""


def bind_untrusted_attempt_evidence_v1(
    qualification_matrix_raw: bytes,
    ledger_raw: bytes,
    *,
    attempt_ledger_ref: Any,
    attempt_results: Any,
    artifact_raw_by_ref: Any,
) -> dict[str, Any]:
    """Bind the complete observed attempt inventory to supplied raw objects.

    The ledger reference, event log, per-attempt results, receipt envelopes,
    and artifact map are all caller supplied. Success proves only their
    bounded structural and byte-level consistency. All 15 case rows and all
    observed attempts are retained; outcomes stay unresolved and credit stays
    zero.
    """
    try:
        raw_binding = ledger_v1.bind_untrusted_attempt_ledger_raw_objects(
            ledger_raw,
            qualification_matrix_raw=qualification_matrix_raw,
            artifact_raw_by_ref=artifact_raw_by_ref,
        )
        aggregate = ledger_v1.build_untrusted_attempt_aggregate_v2(
            qualification_matrix_raw,
            ledger_raw,
            attempt_ledger_ref=attempt_ledger_ref,
            attempt_results=attempt_results,
        )
    except ledger_v1.AttemptLedgerV1Error as error:
        raise AttemptEvidenceBindingError(str(error)) from error

    envelopes: dict[tuple[str, str, str], dict[str, Any]] = {}
    for envelope in raw_binding["stage_receipt_envelopes"]:
        key = (envelope["stage"], envelope["case_id"], envelope["attempt_id"])
        if key in envelopes:
            raise AttemptEvidenceBindingError("duplicate stage receipt envelope for one attempt and stage")
        envelopes[key] = envelope

    expected_envelopes: set[tuple[str, str, str]] = set()
    status_bindings: list[dict[str, Any]] = []
    unbound_non_not_run_status_count = 0
    for case_row in aggregate["case_rows"]:
        for attempt in case_row["attempts"]:
            for stage in STAGES:
                ref = attempt["stage_bundle_refs"][stage]
                if ref is None:
                    if attempt["stage_receipt_statuses"][stage] != "not_run":
                        unbound_non_not_run_status_count += 1
                    continue
                key = (stage, attempt["case_id"], attempt["attempt_id"])
                expected_envelopes.add(key)
                envelope = envelopes.get(key)
                if envelope is None:
                    raise AttemptEvidenceBindingError(
                        f"{stage} stage receipt has no supplied raw envelope for its ledger reference"
                    )
                if envelope["receipt_raw_sha256"] != ref["sha256"]:
                    raise AttemptEvidenceBindingError(
                        f"{stage} stage receipt envelope digest differs from the attempt projection"
                    )
                projection_status = attempt["stage_receipt_statuses"][stage]
                if envelope["receipt_status_claim"] != projection_status:
                    raise AttemptEvidenceBindingError(
                        f"{stage} raw receipt status claim differs from the attempt projection"
                    )
                status_bindings.append({
                    "stage": stage,
                    "case_id": attempt["case_id"],
                    "attempt_id": attempt["attempt_id"],
                    "projection_status_claim": projection_status,
                    "raw_receipt_status_claim": envelope["receipt_status_claim"],
                    "raw_receipt_sha256": envelope["receipt_raw_sha256"],
                    "claims_consistent": True,
                })
    if set(envelopes) != expected_envelopes:
        raise AttemptEvidenceBindingError(
            "raw stage receipt envelope inventory differs from the complete attempt projection"
        )

    return {
        "schema": SCHEMA,
        "scope_id": aggregate["scope_id"],
        "qualification_matrix_raw_sha256": aggregate["qualification_matrix_raw_sha256"],
        "attempt_ledger_ref": aggregate["attempt_ledger_ref"],
        "attempt_ledger_raw_sha256": aggregate["attempt_ledger_raw_sha256"],
        "case_count": aggregate["expected_case_count"],
        "case_rows": aggregate["case_rows"],
        "attempt_count": sum(len(row["attempts"]) for row in aggregate["case_rows"]),
        "raw_reference_count": raw_binding["reference_occurrence_count"],
        "raw_object_count": raw_binding["referenced_object_count"],
        "raw_object_bytes": raw_binding["supplied_raw_bytes"],
        "all_non_null_refs_bound_to_supplied_raw_bytes": True,
        "referenced_stage_receipt_status_claims_match_projection": True,
        "unbound_non_not_run_stage_status_count": unbound_non_not_run_status_count,
        "all_stage_status_claims_have_receipt_or_not_run": unbound_non_not_run_status_count == 0,
        "stage_receipt_status_binding_count": len(status_bindings),
        "stage_receipt_status_bindings": status_bindings,
        "c_v5_process_journal_check_count": raw_binding["c_v5_process_journal_check_count"],
        "c_v5_process_journal_nonce_bindings_match_ledger": (
            raw_binding["c_v5_process_journal_nonce_bindings_match_ledger"]
        ),
        "attempt_ledger_complete": False,
        "artifact_producer_authenticated": False,
        "descriptor_root_authenticated": False,
        "stage_bundle_semantics_verified": False,
        "process_journal_semantics_verified": False,
        "attempt_outcomes_resolved": False,
        "qualification_adjudicated": False,
        "T1_numerical": False,
        "qualification_credit": 0,
    }


__all__ = ["AttemptEvidenceBindingError", "SCHEMA", "bind_untrusted_attempt_evidence_v1"]
