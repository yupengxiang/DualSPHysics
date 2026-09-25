"""Bind F8 R008 attempt projections to supplied ledger and artifact bytes.

This additive diagnostic composes the exact V2 attempt projection, the
attempt-ledger raw-reference binder, and the 15-row unresolved aggregate. It
also cross-checks each caller status against its referenced raw stage-receipt
envelope. Inputs remain untrusted claims: no descriptor root, supervisor,
producer, execution, native semantics, or qualification is authenticated.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from scripts import f8_r008_attempt_ledger_v1 as ledger_v1
from scripts import f8_r008_per_case_bundle_verifier_v1 as bundle_v1


SCHEMA = "core.cfd.f8.r008_attempt_evidence_binding.v1"
STAGES = ("B", "C", "D")
CASE_BUNDLE_INPUT_FIELDS = frozenset({
    "bundle_roots",
    "trusted_authorization_bytes",
    "trusted_authorization_sha256",
    "expected_authorization_envelopes",
    "trusted_code_review_receipt_bytes",
    "trusted_runtime_assumption",
})
MAX_COMPLETE_BUNDLE_CHAINS_PER_CALL = 1


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


def bind_untrusted_attempt_evidence_with_case_bundles_v1(
    qualification_matrix_raw: bytes,
    ledger_raw: bytes,
    *,
    attempt_ledger_ref: Any,
    attempt_results: Any,
    artifact_raw_by_ref: Any,
    case_bundle_inputs_by_attempt: Any,
    attempt_identities_to_verify: Any,
) -> dict[str, Any]:
    """Bind complete attempt refs to the existing held-FD B/C/D verifier.

    A bundle input is required only for the explicitly selected complete
    attempt, and is forbidden for unselected, partial, or open attempts. At
    most one complete attempt is scanned per call; other complete retries
    remain listed as unverified so an aggregate ledger cannot multiply
    verifier I/O or trust-input processing in one call. The existing verifier
    independently reopens each caller-named bundle with no-follow
    directory/file handling and recomputes the content chain. Its
    caller-trusted authorizations and runtime assumption are still not
    authenticated here. No result can resolve an attempt or grant credit.
    """
    result = bind_untrusted_attempt_evidence_v1(
        qualification_matrix_raw,
        ledger_raw,
        attempt_ledger_ref=attempt_ledger_ref,
        attempt_results=attempt_results,
        artifact_raw_by_ref=artifact_raw_by_ref,
    )
    attempts = [attempt for row in result["case_rows"] for attempt in row["attempts"]]
    complete_identities = {
        (attempt["case_id"], attempt["attempt_id"], attempt["nonce_hex"])
        for attempt in attempts
        if all(attempt["stage_bundle_refs"][stage] is not None for stage in STAGES)
    }

    if type(attempt_identities_to_verify) not in (list, tuple):
        raise AttemptEvidenceBindingError("attempt_identities_to_verify must be an exact list or tuple")
    if len(attempt_identities_to_verify) > MAX_COMPLETE_BUNDLE_CHAINS_PER_CALL:
        raise AttemptEvidenceBindingError(
            "per-call B/C/D verification batch exceeds the complete-attempt resource limit"
        )
    selected_identities: list[tuple[str, str, str]] = []
    for identity in attempt_identities_to_verify:
        if (type(identity) is not tuple or len(identity) != 3
                or any(type(part) is not str for part in identity)):
            raise AttemptEvidenceBindingError(
                "selected bundle identities must be exact (case_id, attempt_id, nonce_hex) string tuples"
            )
        if identity not in complete_identities:
            raise AttemptEvidenceBindingError("selected bundle identity is not a complete ledger attempt")
        if identity in selected_identities:
            raise AttemptEvidenceBindingError("selected bundle identity is repeated")
        selected_identities.append(identity)
    if complete_identities and not selected_identities:
        raise AttemptEvidenceBindingError("select one complete ledger attempt for this bounded verification call")

    if type(case_bundle_inputs_by_attempt) is not dict:
        raise AttemptEvidenceBindingError(
            "case_bundle_inputs_by_attempt must be a builtin dict keyed by selected attempt identity"
        )
    if len(case_bundle_inputs_by_attempt) != len(selected_identities):
        raise AttemptEvidenceBindingError(
            "bundle inputs must be supplied only for each explicitly selected attempt"
        )

    supplied_identities: set[tuple[str, str, str]] = set()
    for identity, inputs in case_bundle_inputs_by_attempt.items():
        if (type(identity) is not tuple or len(identity) != 3
                or any(type(part) is not str for part in identity)):
            raise AttemptEvidenceBindingError(
                "case bundle map keys must be exact (case_id, attempt_id, nonce_hex) string tuples"
            )
        if identity in supplied_identities:
            raise AttemptEvidenceBindingError("case bundle map repeats an attempt identity")
        supplied_identities.add(identity)
        if identity not in selected_identities:
            raise AttemptEvidenceBindingError("bundle inputs were supplied for an unselected attempt")
        if (type(inputs) is not dict or len(inputs) != len(CASE_BUNDLE_INPUT_FIELDS)
                or set(inputs) != CASE_BUNDLE_INPUT_FIELDS):
            raise AttemptEvidenceBindingError("case bundle input fields are not exact")
        for field in ("bundle_roots", "trusted_authorization_bytes",
                      "trusted_authorization_sha256", "expected_authorization_envelopes"):
            value = inputs[field]
            if type(value) is not dict or len(value) != len(STAGES) or set(value) != set(STAGES):
                raise AttemptEvidenceBindingError(
                    f"case bundle {field} must contain exactly B, C, and D"
                )
        if any(type(root) is not str and not isinstance(root, Path)
               for root in inputs["bundle_roots"].values()):
            raise AttemptEvidenceBindingError("case bundle roots must be exact strings or pathlib paths")
        if any(type(value) is not bytes for value in inputs["trusted_authorization_bytes"].values()):
            raise AttemptEvidenceBindingError("trusted authorization inputs must be exact raw bytes")
        if any(len(value) > bundle_v1.MAX_RECEIPT_BYTES
               for value in inputs["trusted_authorization_bytes"].values()):
            raise AttemptEvidenceBindingError("trusted authorization bytes exceed the verifier receipt cap")
        if type(inputs["trusted_code_review_receipt_bytes"]) is not bytes:
            raise AttemptEvidenceBindingError("trusted code-review receipt must be exact raw bytes")
        if not 0 < len(inputs["trusted_code_review_receipt_bytes"]) <= bundle_v1.MAX_RECEIPT_BYTES:
            raise AttemptEvidenceBindingError("trusted code-review receipt bytes exceed the verifier receipt cap")
        runtime_assumption = inputs["trusted_runtime_assumption"]
        if (type(runtime_assumption) is not dict
                or len(runtime_assumption) != len(bundle_v1.TRUSTED_RUNTIME_ASSUMPTION_FIELDS)
                or set(runtime_assumption) != bundle_v1.TRUSTED_RUNTIME_ASSUMPTION_FIELDS
                or any(value is not True for value in runtime_assumption.values())):
            raise AttemptEvidenceBindingError("trusted runtime assumption fields/values are not exact")

    if supplied_identities != set(selected_identities):
        raise AttemptEvidenceBindingError(
            "selected B/C/D attempt inventory differs from supplied per-attempt bundle inputs"
        )

    checks: list[dict[str, Any]] = []
    for attempt in attempts:
        identity = (attempt["case_id"], attempt["attempt_id"], attempt["nonce_hex"])
        if identity not in selected_identities:
            continue
        inputs = case_bundle_inputs_by_attempt[identity]
        auth_bytes = inputs["trusted_authorization_bytes"]
        auth_hashes = inputs["trusted_authorization_sha256"]
        auth_envelopes = inputs["expected_authorization_envelopes"]
        if any(type(auth_hashes[stage]) is not str or len(auth_hashes[stage]) != 64
               for stage in STAGES):
            raise AttemptEvidenceBindingError("trusted authorization SHA-256 values must be 64-character strings")
        if any(type(auth_envelopes[stage]) is not dict
               or len(auth_envelopes[stage]) != len(bundle_v1.AUTH_FIELDS)
               or set(auth_envelopes[stage]) != bundle_v1.AUTH_FIELDS
               for stage in STAGES):
            raise AttemptEvidenceBindingError("expected authorization envelopes must be builtin dicts")
        try:
            chain = bundle_v1.verify_provenance_chain(
                inputs["bundle_roots"],
                trusted_authorization_bytes=auth_bytes,
                trusted_authorization_sha256=auth_hashes,
                expected_authorization_envelopes=auth_envelopes,
                trusted_code_review_receipt_bytes=inputs["trusted_code_review_receipt_bytes"],
                trusted_runtime_assumption=inputs["trusted_runtime_assumption"],
            )
        except bundle_v1.BundleVerificationError as error:
            raise AttemptEvidenceBindingError(
                f"B/C/D bundle verification failed for attempt {identity!r}: {error}"
            ) from error

        if chain["case_id"] != attempt["case_id"]:
            raise AttemptEvidenceBindingError("verified B/C/D bundle case_id differs from its ledger attempt")
        if chain["provenance_chain_references_closed"] is not True:
            raise AttemptEvidenceBindingError("B/C/D verifier did not close the receipt/manifest chain")
        if chain.get("authority_authenticity") != "external_gate_not_checked_here":
            raise AttemptEvidenceBindingError("B/C/D verifier authority-authenticity boundary changed")
        if chain.get("code_review_authenticity") != "caller_supplied_trust_not_authenticated_here":
            raise AttemptEvidenceBindingError("B/C/D verifier code-review authenticity boundary changed")
        if chain.get("runtime_environment_assumption") != "caller_attested_not_independently_verified":
            raise AttemptEvidenceBindingError("B/C/D verifier runtime-authenticity boundary changed")
        for stage in STAGES:
            ref = attempt["stage_bundle_refs"][stage]
            if chain["receipt_sha256"][stage] != ref["sha256"]:
                raise AttemptEvidenceBindingError(
                    f"{stage} bundle receipt SHA-256 differs from the ledger attempt reference"
                )
            if chain["stage_statuses"][stage] != attempt["stage_receipt_statuses"][stage]:
                raise AttemptEvidenceBindingError(
                    f"{stage} verified bundle status differs from the ledger attempt projection"
                )
        for field in (
            "loaded_module_code_identity_verified",
            "native_integrity_evaluated",
            "metrics_evaluated",
            "readiness_pass",
            "T1_numerical",
        ):
            if chain.get(field) is True:
                raise AttemptEvidenceBindingError(
                    f"B/C/D diagnostic unexpectedly asserts {field}"
                )
        if type(chain.get("qualification_credit")) is not int or chain["qualification_credit"] != 0:
            raise AttemptEvidenceBindingError("B/C/D diagnostic unexpectedly grants qualification credit")

        checks.append({
            "case_id": attempt["case_id"],
            "attempt_id": attempt["attempt_id"],
            "nonce_hex": attempt["nonce_hex"],
            "stage_statuses": chain["stage_statuses"],
            "receipt_sha256": chain["receipt_sha256"],
            "manifest_sha256": chain["manifest_sha256"],
            "frames_paired": chain["frames_paired"],
            "provenance_chain_references_closed": True,
            "attempt_result_frame_projection_crosschecked": False,
            "safe_decode_receipts_and_metadata_artifacts_rehashed": True,
            "raw_metadata_and_decoded_arrays_recomputed": True,
            "authority_authenticity": chain["authority_authenticity"],
            "code_review_authenticity": chain["code_review_authenticity"],
            "lock_exclusive_creation_attestation": chain["lock_exclusive_creation_attestation"],
            "runtime_environment_assumption": chain["runtime_environment_assumption"],
            "loaded_module_code_identity_verified": False,
            "native_integrity_evaluated": False,
            "metrics_evaluated": False,
            "readiness_pass": False,
            "T1_numerical": False,
            "qualification_credit": 0,
        })

    unverified_identities = sorted(complete_identities.difference(selected_identities))
    result["per_attempt_case_bundle_checks"] = checks
    result["complete_b_c_d_case_bundle_check_count"] = len(checks)
    result["complete_b_c_d_case_bundle_inventory_count"] = len(complete_identities)
    result["unverified_complete_b_c_d_attempts"] = [
        {"case_id": case_id, "attempt_id": attempt_id, "nonce_hex": nonce_hex}
        for case_id, attempt_id, nonce_hex in unverified_identities
    ]
    result["per_call_complete_b_c_d_chain_limit"] = MAX_COMPLETE_BUNDLE_CHAINS_PER_CALL
    result["all_supplied_complete_b_c_d_chains_closed"] = not unverified_identities
    result["selected_complete_b_c_d_chains_closed"] = len(checks) == len(selected_identities)
    result["case_bundle_authority_authenticated"] = False
    result["worker_execution_authenticated"] = False
    result["attempt_outcomes_resolved"] = False
    result["qualification_adjudicated"] = False
    result["T1_numerical"] = False
    result["qualification_credit"] = 0
    return result


__all__ = [
    "AttemptEvidenceBindingError", "CASE_BUNDLE_INPUT_FIELDS",
    "MAX_COMPLETE_BUNDLE_CHAINS_PER_CALL", "SCHEMA",
    "bind_untrusted_attempt_evidence_v1",
    "bind_untrusted_attempt_evidence_with_case_bundles_v1",
]
