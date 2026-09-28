"""Bind verified F8/R008 handoffs and replay transitions to matrix claims.

This is a deliberately disjoint, synthetic-only adapter.  It consumes only
in-memory canonical fixture bytes for the already-reviewed UPDATE-308/309
contracts and the frozen R008 case-id set.  It never imports or calls either
post-run worker, never reads a production bundle, and has no solver, worker,
GPU, queue, registry, ledger, or gate mutation path.

The UPDATE-309 verifier remains the sole owner of handoff and witness field
validation.  This layer only extracts projections after that verifier returns
success, compares them with the caller's case-level claim, and enforces
matrix-wide uniqueness/shared-identity invariants.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any, Mapping

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts import f8_r008_t1_metric_matrix_adapter_v5 as matrix_v5
from scripts import f8_r008_trusted_worker_runtime_replay_ledger_binding_v1 as replay_contract


SCHEMA = "core.cfd.f8.r008_trusted_worker_runtime_postrun_matrix_claim_adapter.v1"
REPORT_SCHEMA = "core.cfd.f8.r008_trusted_worker_runtime_postrun_matrix_claim_report.v1"
RECORD_ID = "f8-r008-trusted-worker-runtime-postrun-matrix-claim-adapter-v1"
REPORT_RECORD_ID = "f8-r008-trusted-worker-runtime-postrun-matrix-claim-report-v1"
STATUS = "diagnostic_frozen_15_case_handoff_replay_claim_matrix_bound"
REPORT_STATUS = "synthetic_only_non_authorizing_postrun_matrix_claim_binding_design"
CASE_CLAIM_SCHEMA = "core.cfd.f8.r008.synthetic_postrun_case_claim.v1"
CASE_CLAIM_RECORD_ID = "f8-r008-synthetic-postrun-case-claim-v1"
CASE_CLAIM_STATUS = "synthetic_only_verified_handoff_replay_case_claim"
SCOPE_ID = replay_contract.SCOPE_ID
CASE_COUNT = 15
HANDOFF_VERIFIED_STATUS = "synthetic_worker_runtime_handoff_consistent_non_authorizing"
MAX_CLAIM_BYTES = 32 * 1024

FIXTURE_FIELDS = frozenset({
    "case_claim",
    "handoff_raw",
    "identity_bundle_raw",
    "trust_root_public_key_bytes",
    "pre_ledger_witness_raw",
    "post_ledger_witness_raw",
    "trusted_ledger_public_key_bytes",
})
CASE_CLAIM_FIELDS = frozenset({
    "schema", "record_id", "status", "synthetic_only", "input_origin",
    "scope_id", "case_id", "handoff", "replay",
})
HANDOFF_CLAIM_FIELDS = frozenset({
    "scope_id", "handoff_sha256", "attempt_id", "attempt_case_id",
    "nonce_hex", "issuer", "subject",
})
REPLAY_CLAIM_FIELDS = frozenset({
    "scope_id", "handoff_sha256", "attempt_id", "attempt_case_id",
    "nonce_hex", "ledger_id", "entry_id", "pre_generation",
    "post_generation", "consumed_epoch", "consumption_id_sha256", "issuer",
})
HANDOFF_ISSUER_FIELDS = frozenset({"active_key_id", "authority_binding_sha256"})
HANDOFF_SUBJECT_FIELDS = frozenset({
    "worker_principal_id", "worker_binding_sha256", "runtime_principal_id",
    "runtime_binding_sha256",
})
REPLAY_ISSUER_FIELDS = frozenset({
    "ledger_principal_id", "key_id", "key_sha256",
})

NON_AUTHORIZING_BOUNDARY = {
    "diagnostic_only": True,
    "capability_minted": False,
    "execution_authority": False,
    "formal": False,
    "readiness_pass": False,
    "T1_numerical": False,
    "formal_eligible": False,
    "qualification_credit": 0,
    "real_ledger_mutation": 0,
    "registry_mutation": 0,
    "gate_mutation": 0,
}


class TrustedPostrunMatrixClaimAdapterError(ValueError):
    """The frozen matrix claim binding is incomplete or inconsistent."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise TrustedPostrunMatrixClaimAdapterError(message)


def _canonical_claim(value: Any) -> bytes:
    try:
        raw = json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, OverflowError, RecursionError) as error:
        raise TrustedPostrunMatrixClaimAdapterError(
            "case claim is not canonical JSON serializable"
        ) from error
    _require(0 < len(raw) <= MAX_CLAIM_BYTES,
             "case claim exceeds the bounded canonical JSON size")
    return raw


def _frozen_case_ids() -> list[str]:
    try:
        case_ids, _rows = matrix_v5._frozen_rows()
    except Exception as error:
        raise TrustedPostrunMatrixClaimAdapterError(
            f"frozen R008 case IDs could not be loaded: {error}"
        ) from error
    _require(
        len(case_ids) == CASE_COUNT and len(set(case_ids)) == CASE_COUNT,
        "frozen R008 matrix must contain exactly 15 unique case IDs",
    )
    return list(case_ids)


def _snapshot_fixture_rows(
    value: Any, case_ids: list[str],
) -> dict[str, dict[str, Any]]:
    _require(isinstance(value, Mapping), "case fixtures must be a mapping")
    try:
        rows = dict(value)
    except (TypeError, ValueError) as error:
        raise TrustedPostrunMatrixClaimAdapterError(
            "case fixtures cannot be snapshotted"
        ) from error
    _require(set(rows) == set(case_ids),
             "case fixtures must contain exactly the 15 frozen case IDs")

    snapshots: dict[str, dict[str, Any]] = {}
    for case_id in case_ids:
        row = rows[case_id]
        _require(isinstance(row, Mapping) and set(row) == FIXTURE_FIELDS,
                 f"case fixture fields are not exact: {case_id}")
        try:
            snapshot = copy.deepcopy(dict(row))
        except Exception as error:
            raise TrustedPostrunMatrixClaimAdapterError(
                f"case fixture cannot be snapshotted: {case_id}"
            ) from error
        for field in (
            "handoff_raw", "identity_bundle_raw", "trust_root_public_key_bytes",
            "pre_ledger_witness_raw", "post_ledger_witness_raw",
            "trusted_ledger_public_key_bytes",
        ):
            _require(type(snapshot[field]) is bytes,
                     f"{case_id} {field} must be in-memory bytes")
        _canonical_claim(snapshot["case_claim"])
        snapshots[case_id] = snapshot
    return snapshots


def _decode_after_verified(raw: bytes, *, label: str) -> dict[str, Any]:
    """Decode a witness only after UPDATE-309 has already verified it.

    This is projection extraction, not a second witness validator.  All
    canonicality, signatures, scope, generation, and replay checks remain in
    ``verify_synthetic_replay_consumption``.
    """
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TrustedPostrunMatrixClaimAdapterError(
            f"{label} could not be decoded after delegated verification"
        ) from error
    _require(type(value) is dict,
             f"{label} projection is not an object after delegated verification")
    return value


def _verify_replay_result(result: Any, case_id: str) -> None:
    """Check only the stable UPDATE-309 result boundary, not its input fields."""
    _require(
        type(result) is dict
        and result.get("schema") == replay_contract.SCHEMA
        and result.get("status") == replay_contract.STATUS
        and result.get("scope_id") == SCOPE_ID
        and result.get("input_origin") == "synthetic_fixture"
        and result.get("synthetic_only") is True
        and result.get("handoff_dependency_status") == HANDOFF_VERIFIED_STATUS,
        f"UPDATE-309 result is not the verified synthetic transition: {case_id}",
    )
    for field in (
        "handoff_digest_bound", "handoff_identity_projection_bound",
        "attempt_case_nonce_bound", "issuer_subject_bound",
        "bounded_epoch_window_bound", "trusted_ledger_witness_verified",
        "single_use_consumption_transition_verified",
    ):
        _require(result.get(field) is True,
                 f"UPDATE-309 result lacks {field}: {case_id}")
    for field in (
        "production_ledger_authenticated", "real_ledger_read", "diagnostic_only",
        "capability_minted", "execution_authority", "formal_admission",
        "readiness_pass", "formal_eligible", "T1_numerical",
        "production_bundle_read", "kernel_or_solver_access", "worker_gpu_queue_access",
    ):
        expected = True if field == "diagnostic_only" else False
        _require(result.get(field) is expected,
                 f"UPDATE-309 result boundary is not fixed for {field}: {case_id}")
    for field in (
        "real_ledger_mutation", "qualification_credit", "registry_mutation",
        "ledger_mutation", "denominator_mutation", "gate_mutation",
    ):
        _require(type(result.get(field)) is int and result[field] == 0,
                 f"UPDATE-309 result boundary is not zero for {field}: {case_id}")
    _require(result.get("generation_delta") == 1
             and result.get("pre_consumed") is False
             and result.get("post_consumed") is True,
             f"UPDATE-309 result transition summary is inconsistent: {case_id}")


def _project_verified_transition(
    handoff_raw: bytes, pre_raw: bytes, post_raw: bytes,
) -> tuple[dict[str, Any], dict[str, Any]]:
    binding = replay_contract.derive_handoff_binding(handoff_raw)
    pre = _decode_after_verified(pre_raw, label="pre-consumption witness")
    post = _decode_after_verified(post_raw, label="post-consumption witness")
    try:
        pre_ledger = pre["ledger"]
        post_ledger = post["ledger"]
        pre_issuer = pre["issuer"]
        post_issuer = post["issuer"]
        handoff_issuer = binding["handoff_issuer"]
        handoff_subject = binding["handoff_subject"]
        handoff_projection = {
            "scope_id": binding["scope_id"],
            "handoff_sha256": binding["handoff_sha256"],
            "attempt_id": binding["attempt_id"],
            "attempt_case_id": binding["case_id"],
            "nonce_hex": binding["nonce_hex"],
            "issuer": {
                "active_key_id": handoff_issuer["active_key_id"],
                "authority_binding_sha256": handoff_issuer["authority_binding_sha256"],
            },
            "subject": {
                "worker_principal_id": handoff_subject["worker_principal_id"],
                "worker_binding_sha256": handoff_subject["worker_binding_sha256"],
                "runtime_principal_id": handoff_subject["runtime_principal_id"],
                "runtime_binding_sha256": handoff_subject["runtime_binding_sha256"],
            },
        }
        replay_projection = {
            "scope_id": binding["scope_id"],
            "handoff_sha256": binding["handoff_sha256"],
            "attempt_id": binding["attempt_id"],
            "attempt_case_id": binding["case_id"],
            "nonce_hex": binding["nonce_hex"],
            "ledger_id": pre_ledger["ledger_id"],
            "entry_id": pre_ledger["entry_id"],
            "pre_generation": pre_ledger["generation"],
            "post_generation": post_ledger["generation"],
            "consumed_epoch": post_ledger["consumed_epoch"],
            "consumption_id_sha256": post_ledger["consumption_id_sha256"],
            "issuer": {
                "ledger_principal_id": post_issuer["ledger_principal_id"],
                "key_id": post_issuer["key_id"],
                "key_sha256": post_issuer["key_sha256"],
            },
        }
        _require(pre_issuer == post_issuer,
                 "verified replay witness issuer changed during projection")
    except (KeyError, TypeError) as error:
        raise TrustedPostrunMatrixClaimAdapterError(
            "verified replay transition lacks its required projection fields"
        ) from error
    return handoff_projection, replay_projection


def _validate_claim(
    claim: Any,
    *,
    case_id: str,
    expected_handoff: Mapping[str, Any],
    expected_replay: Mapping[str, Any],
) -> None:
    _require(type(claim) is dict and set(claim) == CASE_CLAIM_FIELDS,
             f"case claim fields are not exact: {case_id}")
    _require(
        claim.get("schema") == CASE_CLAIM_SCHEMA
        and claim.get("record_id") == CASE_CLAIM_RECORD_ID
        and claim.get("status") == CASE_CLAIM_STATUS
        and claim.get("synthetic_only") is True
        and claim.get("input_origin") == "synthetic_fixture"
        and claim.get("scope_id") == SCOPE_ID
        and claim.get("case_id") == case_id,
        f"case claim identity is not bound to frozen R008 case: {case_id}",
    )
    _require(type(claim.get("handoff")) is dict
             and set(claim["handoff"]) == HANDOFF_CLAIM_FIELDS
             and claim["handoff"] == expected_handoff,
             f"case claim handoff projection differs from UPDATE-308/309: {case_id}")
    _require(type(claim.get("replay")) is dict
             and set(claim["replay"]) == REPLAY_CLAIM_FIELDS
             and claim["replay"] == expected_replay,
             f"case claim replay projection differs from UPDATE-309: {case_id}")


def _unique_or_fail(
    seen: dict[Any, str], value: Any, *, label: str, case_id: str,
) -> None:
    previous = seen.get(value)
    _require(previous is None,
             f"{label} is reused across frozen cases {previous} and {case_id}")
    seen[value] = case_id


def bind_synthetic_postrun_matrix_claims(
    case_fixtures: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Bind 15 verified synthetic transitions to frozen case-level claims.

    Each row is an in-memory fixture.  The row's raw bytes are passed to the
    existing UPDATE-309 verifier, which delegates UPDATE-308.  No path-like
    input is accepted and no post-run worker is imported or called.
    """
    case_ids = _frozen_case_ids()
    rows = _snapshot_fixture_rows(case_fixtures, case_ids)
    bindings: dict[str, dict[str, Any]] = {}
    seen_handoff: dict[str, str] = {}
    seen_attempt: dict[str, str] = {}
    seen_attempt_case: dict[str, str] = {}
    seen_nonce: dict[str, str] = {}
    seen_consumption: dict[str, str] = {}
    seen_ledger_entry: dict[tuple[str, str], str] = {}
    seen_generation: dict[tuple[int, int], str] = {}
    shared_handoff_issuer: dict[str, Any] | None = None
    shared_handoff_subject: dict[str, Any] | None = None
    shared_replay_issuer: dict[str, Any] | None = None

    for case_id in case_ids:
        row = rows[case_id]
        try:
            result = replay_contract.verify_synthetic_replay_consumption(
                row["handoff_raw"],
                identity_bundle_raw=row["identity_bundle_raw"],
                trust_root_public_key_bytes=row["trust_root_public_key_bytes"],
                pre_ledger_witness_raw=row["pre_ledger_witness_raw"],
                post_ledger_witness_raw=row["post_ledger_witness_raw"],
                trusted_ledger_public_key_bytes=row["trusted_ledger_public_key_bytes"],
            )
        except replay_contract.TrustedReplayLedgerBindingError as error:
            raise TrustedPostrunMatrixClaimAdapterError(
                f"UPDATE-309 verification failed for frozen case {case_id}: {error}"
            ) from error
        _verify_replay_result(result, case_id)
        handoff_projection, replay_projection = _project_verified_transition(
            row["handoff_raw"], row["pre_ledger_witness_raw"],
            row["post_ledger_witness_raw"],
        )
        _validate_claim(
            row["case_claim"], case_id=case_id,
            expected_handoff=handoff_projection,
            expected_replay=replay_projection,
        )
        expected_attempt_case_id = f"synthetic-matrix-{case_id}"
        _require(handoff_projection["attempt_case_id"] == expected_attempt_case_id,
                 f"handoff attempt case does not map to frozen case: {case_id}")

        handoff_issuer = handoff_projection["issuer"]
        handoff_subject = handoff_projection["subject"]
        replay_issuer = replay_projection["issuer"]
        if shared_handoff_issuer is None:
            shared_handoff_issuer = copy.deepcopy(handoff_issuer)
            shared_handoff_subject = copy.deepcopy(handoff_subject)
            shared_replay_issuer = copy.deepcopy(replay_issuer)
        else:
            _require(handoff_issuer == shared_handoff_issuer,
                     f"trusted handoff issuer projection crosses cases: {case_id}")
            _require(handoff_subject == shared_handoff_subject,
                     f"trusted handoff subject projection crosses cases: {case_id}")
            _require(replay_issuer == shared_replay_issuer,
                     f"trusted replay issuer projection crosses cases: {case_id}")

        _unique_or_fail(seen_handoff, handoff_projection["handoff_sha256"],
                        label="handoff digest", case_id=case_id)
        _unique_or_fail(seen_attempt, handoff_projection["attempt_id"],
                        label="attempt ID", case_id=case_id)
        _unique_or_fail(seen_attempt_case, handoff_projection["attempt_case_id"],
                        label="attempt case ID", case_id=case_id)
        _unique_or_fail(seen_nonce, handoff_projection["nonce_hex"],
                        label="handoff nonce", case_id=case_id)
        _unique_or_fail(seen_consumption, replay_projection["consumption_id_sha256"],
                        label="replay consumption ID", case_id=case_id)
        _unique_or_fail(
            seen_ledger_entry,
            (replay_projection["ledger_id"], replay_projection["entry_id"]),
            label="replay ledger/entry identity", case_id=case_id,
        )
        _unique_or_fail(
            seen_generation,
            (replay_projection["pre_generation"], replay_projection["post_generation"]),
            label="replay generation transition", case_id=case_id,
        )

        bindings[case_id] = {
            "scope_id": SCOPE_ID,
            "case_id": case_id,
            "handoff_sha256": handoff_projection["handoff_sha256"],
            "attempt_id": handoff_projection["attempt_id"],
            "attempt_case_id": handoff_projection["attempt_case_id"],
            "nonce_hex": handoff_projection["nonce_hex"],
            "trusted_issuer": copy.deepcopy(handoff_issuer),
            "trusted_subject": copy.deepcopy(handoff_subject),
            "replay_issuer": copy.deepcopy(replay_issuer),
            "ledger_id": replay_projection["ledger_id"],
            "entry_id": replay_projection["entry_id"],
            "pre_generation": replay_projection["pre_generation"],
            "post_generation": replay_projection["post_generation"],
            "consumed_epoch": replay_projection["consumed_epoch"],
            "replay_consumption_id_sha256": replay_projection["consumption_id_sha256"],
            "handoff_verified": True,
            "replay_transition_verified": True,
        }

    _require(len(bindings) == CASE_COUNT,
             "adapter did not produce all 15 frozen case bindings")
    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "status": STATUS,
        "scope_id": SCOPE_ID,
        "input_origin": "synthetic_fixture",
        "synthetic_only": True,
        "case_count": CASE_COUNT,
        "case_ids": list(case_ids),
        "frozen_case_set_bound": True,
        "case_bindings": bindings,
        "matrix_invariants": {
            "frozen_case_ids_exact": True,
            "same_r008_scope": True,
            "trusted_handoff_issuer_projection_shared": True,
            "trusted_handoff_subject_projection_shared": True,
            "trusted_replay_issuer_projection_shared": True,
            "unique_handoff_digests": True,
            "unique_attempt_ids": True,
            "unique_attempt_case_ids": True,
            "unique_nonces": True,
            "unique_replay_consumption_ids": True,
            "unique_replay_ledger_entries": True,
            "unique_replay_generation_transitions": True,
            "cross_case_replay_reuse_rejected": True,
        },
        "non_authorizing_boundary": copy.deepcopy(NON_AUTHORIZING_BOUNDARY),
    }


def build_report() -> dict[str, Any]:
    """Return the deterministic diagnostic-only adapter report."""
    return {
        "schema": REPORT_SCHEMA,
        "record_id": REPORT_RECORD_ID,
        "status": REPORT_STATUS,
        "contract_schema": SCHEMA,
        "case_claim_schema": CASE_CLAIM_SCHEMA,
        "scope_id": SCOPE_ID,
        "matrix_contract": {
            "case_count": CASE_COUNT,
            "case_ids_source": "frozen R008 matrix-v5 case IDs only",
            "required_input": "exactly 15 unique in-memory case fixture rows",
            "missing_or_extra_rows": "reject",
            "postrun_case_worker_called": False,
            "postrun_matrix_worker_called": False,
            "production_bundle_read": False,
        },
        "delegated_verifiers": {
            "update_308": {
                "contract": "core.cfd.f8.r008_trusted_worker_runtime_handoff_contract.v1",
                "delegated_by": "UPDATE-309 replay verifier",
                "field_validation_reimplemented": False,
            },
            "update_309": {
                "contract": replay_contract.SCHEMA,
                "used_for": "one in-memory synthetic replay transition per frozen case",
                "field_validation_reimplemented": False,
            },
        },
        "case_claim_requirements": [
            "exact frozen matrix case_id and deterministic synthetic attempt-case projection",
            "same F8/R008 scope across claim, handoff, and replay projections",
            "handoff SHA-256, attempt ID, attempt case ID, and nonce exact equality",
            "trusted handoff issuer and worker/runtime subject projection exact equality",
            "replay ledger/entry identity, generation pair, consumed epoch, and consumption ID exact equality",
        ],
        "matrix_rejection_rules": [
            "reject missing, extra, or duplicate frozen case rows",
            "reject cross-case handoff digest, attempt, nonce, or replay consumption reuse",
            "reject cross-case replay ledger/entry or generation-transition reuse",
            "reject claim digest, nonce, scope, issuer/subject, or generation mismatch",
            "reject any delegated UPDATE-308/309 result that is not synthetic and non-authorizing",
        ],
        "non_authorizing_boundary": copy.deepcopy(NON_AUTHORIZING_BOUNDARY),
        "prohibited_operations": [
            "postrun_case_worker_invocation",
            "postrun_matrix_worker_invocation",
            "production_bundle_read",
            "production_ledger_read_or_write",
            "registry_or_gate_mutation",
            "solver_or_native_execution",
            "worker_gpu_or_queue",
        ],
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print-report", action="store_true",
                        help="print the deterministic synthetic-only design report")
    args = parser.parse_args()
    if args.print_report:
        print(json.dumps(build_report(), indent=2, sort_keys=True, allow_nan=False))
    else:
        print(json.dumps({
            "schema": SCHEMA,
            "status": STATUS,
            "synthetic_only": True,
            "diagnostic_only": True,
            "capability_minted": False,
            "execution_authority": False,
            "readiness_pass": False,
            "T1_numerical": False,
            "formal": False,
            "qualification_credit": 0,
            "real_ledger_mutation": 0,
            "registry_mutation": 0,
            "gate_mutation": 0,
        }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CASE_CLAIM_SCHEMA", "CASE_COUNT", "CASE_CLAIM_STATUS", "REPORT_SCHEMA",
    "SCHEMA", "SCOPE_ID", "STATUS", "TrustedPostrunMatrixClaimAdapterError",
    "bind_synthetic_postrun_matrix_claims", "build_report",
]
