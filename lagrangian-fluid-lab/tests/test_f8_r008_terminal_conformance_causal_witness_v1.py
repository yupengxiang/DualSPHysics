from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

import pytest

from scripts import f8_r008_terminal_conformance_causal_witness_v1 as contract


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _supervisor_projection() -> dict[str, Any]:
    journal_sha = _sha("synthetic-c-journal-1")
    return {
        "schema": "core.cfd.f8.r008_untrusted_supervisor_session_claim_projection.v1",
        "status": "untrusted_candidate_signed_supervisor_session_claims_consistent",
        "projection_source": "f8_r008_supervisor_session_claims_v1",
        "attempt_id": "attempt-1",
        "nonce_hex": "01" * 16,
        "process_terminal_seq": 17,
        "ledger_process_generation_id": "generation-1",
        "process_journal_raw_sha256": journal_sha,
        "c_journal_raw_sha256": journal_sha,
        "candidate_key_is_active": False,
        "active_key_registry_verified": False,
        "trusted_root_capability_present": False,
        "supervisor_identity_authenticated": False,
        "worker_execution_authenticated": False,
        "runtime_identity_verified": False,
        "event_source_completeness_verified": False,
        "readiness_pass": False,
        "T1_numerical": False,
        "qualification_credit": 0,
    }


def _final_fput_projection() -> dict[str, Any]:
    return {
        "schema": "core.cfd.f8.r008_final_fput_join_diagnostic.v3",
        "status": "diagnostic_raw_bytes_and_declared_queue_barrier_order_consistent_untrusted",
        "projection_source": "f8_r008_final_fput_join_reducer_v3",
        "attempt_id": "attempt-1",
        "close_token_ref": "close-token-1",
        "object_id": "output-object-1",
        "file_cookie_digest": _sha("synthetic-file-cookie-1"),
        "observer_event_order": [
            "fd_install_entry", "__fput_entry", "fsnotify_close", "__fput_return",
        ],
        "fanotify_name_group_seq_range": [7, 8],
        "pre_close_barrier_group_seq": 7,
        "post_close_barrier_group_seq": 8,
        "fanotify_close_write_group_seq": 8,
        "fanotify_raw_bytes_reparsed": True,
        "queue_barrier_declared_order_consistent": True,
        "queue_barrier_source_authenticated": False,
        "shared_journal_contract_implemented": False,
        "final_close_claim": False,
        "trusted_observation": False,
        "kernel_source_pinned": False,
        "observer_runtime_authenticated": False,
        "close_token_cookie_bridge_authenticated": False,
        "runtime_observation_authenticated": False,
        "readiness_pass": False,
        "T1_numerical": False,
        "execution_authority": False,
        "qualification_credit": 0,
    }


def _causal_witness() -> dict[str, Any]:
    file_cookie = _sha("synthetic-file-cookie-1")
    close_token = "close-token-1"
    object_id = "output-object-1"
    rows: list[dict[str, Any]] = []
    for seq, kind in enumerate(contract.EXPECTED_CAUSAL_KINDS, start=1):
        lifecycle_identity = kind in {
            "close_entry", "fput_entry", "fsnotify_close", "fput_return",
            "close_exit", "fanotify_close_write", "terminal_seal",
        }
        close_token_identity = kind in {
            "close_entry", "fput_entry", "fsnotify_close", "fput_return",
            "close_exit", "fanotify_close_write",
        }
        rows.append({
            "seq": seq,
            "kind": kind,
            "attempt_id": "attempt-1",
            "ref_id": contract.EXPECTED_CAUSAL_REFS[kind],
            "token_ref": close_token if close_token_identity else None,
            "object_id": object_id if lifecycle_identity else None,
            "file_cookie_digest": file_cookie if lifecycle_identity else None,
            "group_seq": (
                7 if kind == "pre_close_eagain"
                else 8 if kind in {"fanotify_close_write", "post_close_eagain"}
                else None
            ),
            "event_symbol": "FAN_CLOSE_WRITE" if kind == "fanotify_close_write" else None,
            "trusted": False,
        })
    return {
        "schema": "core.cfd.f8.r008_terminal_supervisor_final_fput_causal_witness.v1",
        "attempt_id": "attempt-1",
        "nonce_hex": "01" * 16,
        "supervisor_terminal_seq": 17,
        "close_token_ref": close_token,
        "object_id": object_id,
        "file_cookie_digest": file_cookie,
        "pre_close_barrier_group_seq": 7,
        "fanotify_close_write_group_seq": 8,
        "post_close_barrier_group_seq": 8,
        "witness_origin": "synthetic_fixture",
        "trusted_authority_ref": None,
        "runtime_conformance_verified": False,
        "runtime_claims": {
            "source_authenticated": False,
            "kernel_conformance_verified": False,
            "fanotify_runtime_verified": False,
            "terminal_supervisor_runtime_verified": False,
            "final_fput_runtime_verified": False,
            "causal_bridge_verified": False,
        },
        "loss_counters": {
            "fanotify_overflow": 0,
            "fanotify_lost": 0,
            "observer_lost": 0,
            "journal_loss": 0,
            "short_read": 0,
            "sequence_gap": 0,
        },
        "timeline": rows,
        "edges": [
            {
                "edge_id": f"edge-{index + 1}",
                "from_seq": from_seq,
                "to_seq": to_seq,
                "relation": relation,
                "contract_ref": contract_ref,
                "trusted": False,
            }
            for index, (from_seq, to_seq, relation, contract_ref)
            in enumerate(contract.EXPECTED_EDGE_ROWS)
        ],
    }


def _fixture() -> dict[str, Any]:
    return {
        "schema": contract.SCHEMA,
        "record_id": "f8-r008-terminal-conformance-causal-witness-v1",
        "status": contract.STATUS,
        "synthetic_only": True,
        "input_origin": "synthetic_fixture",
        "scope_id": contract.SCOPE_ID,
        "bindings": copy.deepcopy(contract.STATIC_BINDINGS),
        "source_claims": copy.deepcopy(contract.SOURCE_CLAIMS),
        "kernel_claims": copy.deepcopy(contract.KERNEL_CLAIMS),
        "abi_claims": copy.deepcopy(contract.ABI_CLAIMS),
        "fanotify_profile_claims": copy.deepcopy(contract.PROFILE_CLAIMS),
        "event_dispositions": list(copy.deepcopy(contract.EXPECTED_DISPOSITIONS)),
        "trust_boundary": copy.deepcopy(contract.TRUST_BOUNDARY),
        "supervisor_projection": _supervisor_projection(),
        "final_fput_projection": _final_fput_projection(),
        "causal_witness": _causal_witness(),
    }


def test_complete_static_witness_is_cross_bound_but_never_authorizing() -> None:
    result = contract.build_diagnostic_receipt(_fixture())

    assert result["schema"] == contract.RESULT_SCHEMA
    assert result["status"] == contract.RESULT_STATUS
    assert result["source_bindings_consistent"] is True
    assert result["kernel_config_abi_claims_bound"] is True
    assert result["fanotify_event_disposition_consistent"] is True
    assert result["terminal_supervisor_projection_consistent"] is True
    assert result["final_fput_projection_consistent"] is True
    assert result["causal_witness_declared_order_consistent"] is True
    assert result["causal_witness_source_authenticated"] is False
    assert result["fanotify_runtime_conformance_verified"] is False
    assert result["terminal_supervisor_runtime_authenticated"] is False
    assert result["final_fput_runtime_authenticated"] is False
    assert result["trusted_authority_present"] is False
    assert result["runtime_claims_accepted"] is False
    assert result["final_close_claim"] is False
    assert result["execution_authority"] is False
    assert result["readiness_pass"] is False
    assert result["T1_numerical"] is False
    assert result["qualification_credit"] == 0
    assert all(result[field] == 0 for field in (
        "registry_mutation", "ledger_mutation", "denominator_mutation",
        "gate_mutation", "completion_mutation",
    ))
    assert len(result["input_sha256"]) == 64


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda value: value["trust_boundary"]["runtime_claims"].update(
                fanotify_conformance=True
            ),
            "runtime claim",
        ),
        (
            lambda value: value["trust_boundary"].update(trusted_authority_present=True),
            "runtime claims cannot",
        ),
        (
            lambda value: value["kernel_claims"].update(target_build_id="untrusted-build"),
            "kernel/config claims",
        ),
        (
            lambda value: value["abi_claims"]["target_abi_raw_values"].update(
                name_init_flags_hex="0x1e83"
            ),
            "ABI claims",
        ),
        (
            lambda value: value["event_dispositions"][5].update(mask_hex="0x0000000a"),
            "frozen V17/V18 disposition",
        ),
        (
            lambda value: value["supervisor_projection"].update(
                supervisor_identity_authenticated=True
            ),
            "unauthorized runtime claim",
        ),
        (
            lambda value: value["final_fput_projection"].update(
                close_token_ref="other-token"
            ),
            "close token/object/file-cookie join",
        ),
        (
            lambda value: value["causal_witness"]["timeline"][6].update(
                kind="fput_return"
            ),
            "lifecycle kind is missing",
        ),
        (
            lambda value: value["causal_witness"]["edges"][5].update(
                trusted=True
            ),
            "causal witness edge is marked trusted",
        ),
    ],
)
def test_witness_fails_closed_on_cross_contract_or_authority_mutations(mutate, message: str) -> None:
    value = copy.deepcopy(_fixture())
    mutate(value)
    with pytest.raises(contract.TerminalConformanceWitnessError, match=message):
        contract.build_diagnostic_receipt(value)


def test_runtime_claim_cannot_be_smuggled_by_an_extra_field() -> None:
    value = _fixture()
    value["causal_witness"]["runtime_verified"] = True
    with pytest.raises(contract.TerminalConformanceWitnessError, match="fields differ"):
        contract.build_diagnostic_receipt(value)


def test_causal_witness_requires_source_fput_order_and_reader_barrier_order() -> None:
    value = _fixture()
    rows = value["causal_witness"]["timeline"]
    rows[7]["seq"], rows[8]["seq"] = rows[8]["seq"], rows[7]["seq"]
    with pytest.raises(contract.TerminalConformanceWitnessError, match="sequence has a gap or reorder"):
        contract.build_diagnostic_receipt(value)


def test_report_is_static_and_records_the_non_overlap_boundary() -> None:
    report = contract.build_report()
    assert report["schema"] == contract.REPORT_SCHEMA
    assert report["contract_schema"] == contract.SCHEMA
    assert report["static_bindings"] == contract.STATIC_BINDINGS
    assert report["event_disposition"]["rows"] == len(contract.EXPECTED_DISPOSITIONS)
    assert report["causal_witness"]["edge_count"] == len(contract.EXPECTED_EDGE_ROWS)
    assert report["trust_boundary"]["trusted_authority_present"] is False
    assert report["non_authorizing_boundary"]["readiness_pass"] is False
    assert report["non_overlap"]["raw_parser"].startswith("not reimplemented")


def test_canonical_fixture_has_no_nonfinite_json_values() -> None:
    raw = json.dumps(_fixture(), sort_keys=True, separators=(",", ":"), allow_nan=False)
    assert len(raw.encode("utf-8")) < contract.MAX_INPUT_BYTES
