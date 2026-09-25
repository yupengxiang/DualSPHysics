from __future__ import annotations

import base64
import copy
import hashlib
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts import f8_r008_attempt_ledger_v1 as ledger_v1
from scripts import f8_r008_c_execution_journal_v5 as journal_v5
from scripts import f8_r008_supervisor_session_claims_v1 as bridge_v1
from tests import test_f8_r008_attempt_ledger_attestation_v1 as attestation_fixtures
from tests import test_f8_r008_attempt_ledger_v1 as ledger_fixtures
from tests import test_f8_r008_c_execution_journal_v5 as journal_fixtures


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _journal_raw(*, nonce: str = ledger_fixtures.NONCE, loads: bool = True,
                 root_execs: int = 1, child_load_only: bool = False) -> bytes:
    process = journal_fixtures._process(birth_seq=0)
    events = [
        journal_fixtures._event(
            "spawn", 0, process_generation_id=process,
            supervisor_identity_binding={"supervisor_source_id": "f8-supervisor-v1"},
        ),
    ]
    for _ in range(root_execs):
        events.append(journal_fixtures._event(
            "exec", len(events), process_generation_id=process,
            executable_binding={"path_object_id": "solver-bin", "sha256": "a" * 64},
            argv_sha256="b" * 64, cwd_object_id="cfd-case", environment_sha256="c" * 64,
        ))
    if loads:
        events.append(journal_fixtures._event(
            "load", len(events), process_generation_id=process,
            object_binding={"path_object_id": "solver-module", "sha256": "d" * 64},
            object_kind="elf_mapping",
        ))
    child = None
    if child_load_only:
        child = journal_fixtures._process(birth_seq=len(events), pid=43)
        events.extend([
            journal_fixtures._event(
                "fork", len(events), parent_generation_id=process,
                process_generation_id=child,
            ),
            journal_fixtures._event(
                "load", len(events) + 1, process_generation_id=child,
                object_binding={"path_object_id": "child-only-module", "sha256": "f" * 64},
                object_kind="elf_mapping",
            ),
        ])
    if root_execs:
        if child is not None:
            events.extend([
                journal_fixtures._event(
                    "exit", len(events), process_generation_id=child, exit_code=0, signal=None,
                ),
                journal_fixtures._event(
                    "reap", len(events) + 1, process_generation_id=child,
                ),
            ])
        events.extend([
            journal_fixtures._event(
                "exit", len(events), process_generation_id=process, exit_code=0, signal=None,
            ),
            journal_fixtures._event(
                "reap", len(events) + 1, process_generation_id=process,
            ),
        ])
    # Rebuild all common fields after changing the attempt nonce.
    for event in events:
        event["attempt_nonce_hex"] = nonce
        event["mono_ns_hex"] = f"{event['seq']:016x}"
    journal = {
        "schema": journal_v5.JOURNAL_SCHEMA,
        "attempt_nonce_hex": nonce,
        "source_id": "synthetic-c-runtime",
        "source_binary_sha256": "e" * 64,
        "coverage_start_ns_hex": "0000000000000000",
        "coverage_end_ns_hex": f"{len(events) - 1:016x}",
        "event_count": len(events),
        "overflow": False,
        "lost_count": 0,
        "events": events,
    }
    return _canonical(journal)


def _fixture(*, journal_raw: bytes | None = None, session_mutation: tuple[str, object] | None = None,
             resign_session: bool = True):
    key = Ed25519PrivateKey.generate()
    nonce = ledger_fixtures.NONCE
    c_journal = _journal_raw() if journal_raw is None else journal_raw
    events = copy.deepcopy(ledger_fixtures._complete_event_chain())
    c_terminal = next(event for event in events
                      if event["kind"] == "process_terminal" and event["stage"] == "C")
    journal_ref = c_terminal["process_journal_ref"]
    journal_ref["bytes"] = len(c_journal)
    journal_ref["sha256"] = hashlib.sha256(c_journal).hexdigest()
    ledger_raw = ledger_fixtures._raw(ledger_fixtures._ledger_document(events))
    attestation_raw, _, matrix_raw, public_key, key = attestation_fixtures._signed_fixture(
        ledger_raw=ledger_raw, private_key=key,
    )
    ledger_projection = ledger_v1.inspect_untrusted_c_process_terminal_projection_v1(
        ledger_raw,
        qualification_matrix_raw=matrix_raw,
        case_id=ledger_fixtures.CASE_ID,
        attempt_id=ledger_fixtures.ATTEMPT_ID,
        nonce_hex=nonce,
    )
    journal_nonce = json.loads(c_journal)["attempt_nonce_hex"]
    journal_projection = journal_v5.inspect_untrusted_v5_runtime_identity_projection_v1(
        c_journal, expected_attempt_nonce_hex=journal_nonce,
    )
    unsigned = {
        "schema": bridge_v1.SESSION_SCHEMA,
        "scope_id": ledger_projection.scope_id,
        "qualification_matrix_raw_sha256": ledger_projection.qualification_matrix_raw_sha256,
        "qualification_row_sha256": ledger_projection.qualification_row_sha256,
        "attempt_ledger_raw_sha256": ledger_projection.ledger_raw_sha256,
        "ledger_attestation_raw_sha256": hashlib.sha256(attestation_raw).hexdigest(),
        "ledger_coverage_start_ns_hex": ledger_projection.coverage_start_ns_hex,
        "ledger_coverage_end_ns_hex": ledger_projection.coverage_end_ns_hex,
        "ledger_event_count": ledger_projection.event_count,
        "ledger_overflow": ledger_projection.overflow,
        "ledger_lost_count": ledger_projection.lost_count,
        "case_id": ledger_projection.case_id,
        "attempt_id": ledger_projection.attempt_id,
        "nonce_hex": ledger_projection.nonce_hex,
        "process_terminal_seq": ledger_projection.process_terminal_seq,
        "ledger_process_generation_id": ledger_projection.ledger_process_generation_id,
        "process_journal_ref": {
            "stage": ledger_projection.process_journal_ref_stage,
            "role": ledger_projection.process_journal_ref_role,
            "object_id": ledger_projection.process_journal_ref_object_id,
            "bytes": ledger_projection.process_journal_ref_bytes,
            "sha256": ledger_projection.process_journal_ref_sha256,
        },
        "process_journal_raw_sha256": journal_projection.journal_raw_sha256,
        "supervisor_source_id": ledger_projection.supervisor_source_id,
        "verification_key_id": attestation_fixtures.KEY_ID,
        "candidate_public_key_sha256": hashlib.sha256(public_key).hexdigest(),
        "journal_source_id": journal_projection.source_id_observed,
        "journal_source_binary_sha256": journal_projection.source_binary_sha256_observed,
        "root_spawn_seq": journal_projection.root_spawn_seq,
        "root_process_generation_sha256": journal_projection.root_process_generation_sha256,
        "root_supervisor_identity_binding_sha256": (
            journal_projection.root_supervisor_identity_binding_sha256
        ),
        "root_exec_seq": journal_projection.root_exec_seq,
        "root_exec_event_sha256": journal_projection.root_exec_event_sha256,
        "observed_load_event_count": journal_projection.observed_load_event_count,
        "observed_load_events_sha256": journal_projection.observed_load_events_sha256,
        "signature_algorithm": "ed25519",
    }
    if session_mutation is not None:
        field, value = session_mutation
        unsigned[field] = value
    signature = key.sign(bridge_v1.DOMAIN + _canonical(unsigned))
    session = {**unsigned, "signature_base64": base64.b64encode(signature).decode("ascii")}
    if not resign_session:
        session["signature_base64"] = base64.b64encode(b"x" * 64).decode("ascii")
    return {
        "matrix_raw": matrix_raw,
        "ledger_raw": ledger_raw,
        "attestation_raw": attestation_raw,
        "journal_raw": c_journal,
        "session_raw": _canonical(session),
        "public_key": public_key,
        "key": key,
    }


def _verify(fixture: dict[str, object]) -> dict[str, object]:
    return bridge_v1.bind_untrusted_supervisor_session_claims_v1(
        fixture["matrix_raw"], fixture["ledger_raw"], fixture["attestation_raw"],
        fixture["journal_raw"], fixture["session_raw"],
        candidate_key_id=attestation_fixtures.KEY_ID,
        candidate_public_key_bytes=fixture["public_key"],
        case_id=ledger_fixtures.CASE_ID,
        attempt_id=ledger_fixtures.ATTEMPT_ID,
        nonce_hex=ledger_fixtures.NONCE,
    )


def _fixture_with_rebound_journal(raw_journal: bytes) -> dict[str, object]:
    fixture = _fixture()
    ledger = json.loads(fixture["ledger_raw"])
    c_terminal = next(event for event in ledger["events"]
                      if event["kind"] == "process_terminal" and event["stage"] == "C")
    c_terminal["process_journal_ref"]["bytes"] = len(raw_journal)
    c_terminal["process_journal_ref"]["sha256"] = hashlib.sha256(raw_journal).hexdigest()
    ledger_raw = _canonical(ledger)
    attestation_raw, _, _, _, _ = attestation_fixtures._signed_fixture(
        ledger_raw=ledger_raw, matrix_raw=fixture["matrix_raw"], private_key=fixture["key"],
    )
    fixture["ledger_raw"] = ledger_raw
    fixture["attestation_raw"] = attestation_raw
    fixture["journal_raw"] = raw_journal
    return fixture


def test_candidate_signed_session_bridges_ledger_and_v5_claims_without_authenticating_them():
    result = _verify(_fixture())

    assert result["status"] == "untrusted_candidate_signed_supervisor_session_claims_consistent"
    assert result["candidate_key_fingerprint_matches"] is True
    assert result["ledger_signature_valid_for_candidate"] is True
    assert result["session_signature_valid_for_candidate"] is True
    assert result["ledger_derived_c_process_terminal"] is True
    assert result["ledger_session_claims_consistent"] is True
    assert result["journal_claims_consistent"] is True
    assert result["observed_load_bindings_consistent"] is True
    assert result["observed_load_event_count"] == 1
    for field in (
        "candidate_key_is_active", "active_key_registry_verified",
        "trusted_root_capability_present", "descriptor_root_authenticated",
        "supervisor_identity_authenticated", "worker_execution_authenticated",
        "artifact_producer_authenticated", "process_generation_identity_linked",
        "event_source_completeness_verified", "runtime_identity_verified",
        "loaded_module_code_identity_verified", "attempt_ledger_complete",
        "attempt_outcomes_resolved", "qualification_adjudicated", "T1_numerical",
    ):
        assert result[field] is False
    assert result["qualification_credit"] == 0


def test_child_process_load_is_in_the_observed_tree_digest_not_a_verified_load_map():
    fixture = _fixture(journal_raw=_journal_raw(loads=False, child_load_only=True))
    result = _verify(fixture)

    assert result["observed_load_event_count"] == 1
    assert result["observed_load_bindings_consistent"] is True
    assert result["loaded_module_code_identity_verified"] is False
    assert result["event_source_completeness_verified"] is False


@pytest.mark.parametrize(("field", "value"), [
    ("qualification_matrix_raw_sha256", "1" * 64),
    ("qualification_row_sha256", "2" * 64),
    ("attempt_ledger_raw_sha256", "3" * 64),
    ("ledger_attestation_raw_sha256", "4" * 64),
    ("ledger_coverage_start_ns_hex", "0000000000000001"),
    ("ledger_coverage_end_ns_hex", "0000000000000002"),
    ("ledger_event_count", 9),
    ("ledger_overflow", True),
    ("ledger_lost_count", 1),
    ("case_id", "other-case"),
    ("attempt_id", "attempt-002"),
    ("nonce_hex", "f" * 32),
    ("process_terminal_seq", 999),
    ("ledger_process_generation_id", "other-c-generation"),
    ("process_journal_raw_sha256", "5" * 64),
    ("supervisor_source_id", "other-supervisor"),
    ("verification_key_id", "other-key"),
    ("candidate_public_key_sha256", "6" * 64),
    ("journal_source_id", "other-runtime"),
    ("journal_source_binary_sha256", "7" * 64),
    ("root_spawn_seq", 99),
    ("root_process_generation_sha256", "8" * 64),
    ("root_supervisor_identity_binding_sha256", "9" * 64),
    ("root_exec_seq", 99),
    ("root_exec_event_sha256", "a" * 64),
    ("observed_load_event_count", 9),
    ("observed_load_events_sha256", "b" * 64),
])
def test_resigned_session_claim_must_match_ledger_and_journal(field: str, value: object):
    fixture = _fixture(session_mutation=(field, value))
    with pytest.raises(bridge_v1.SupervisorSessionClaimsError, match=field):
        _verify(fixture)


def test_session_process_journal_ref_must_match_the_ledger_derived_reference():
    ref = {
        "stage": "C", "role": "process_journal", "object_id": "other-object",
        "bytes": 100, "sha256": "c" * 64,
    }
    fixture = _fixture(session_mutation=("process_journal_ref", ref))
    with pytest.raises(bridge_v1.SupervisorSessionClaimsError, match="process_journal_ref"):
        _verify(fixture)


def test_session_signature_must_verify_for_the_candidate_key():
    fixture = _fixture(resign_session=False)
    with pytest.raises(bridge_v1.SupervisorSessionClaimsError, match="signature is invalid"):
        _verify(fixture)


def test_c_journal_raw_bytes_must_match_the_ledger_reference():
    fixture = _fixture()
    fixture["journal_raw"] += b" "
    with pytest.raises(bridge_v1.SupervisorSessionClaimsError, match="raw bytes differ"):
        _verify(fixture)


def test_c_journal_attempt_nonce_must_match_ledger_registration():
    fixture = _fixture(journal_raw=_journal_raw(nonce="d" * 32))
    with pytest.raises(bridge_v1.SupervisorSessionClaimsError, match="nonce differs"):
        _verify(fixture)


@pytest.mark.parametrize("root_execs", [0, 2])
def test_runtime_identity_projection_requires_one_root_exec(root_execs: int):
    fixture = _fixture_with_rebound_journal(_journal_raw(root_execs=root_execs))
    with pytest.raises(bridge_v1.SupervisorSessionClaimsError, match="exactly one root-generation exec"):
        _verify(fixture)


def test_empty_load_observation_list_is_bound_but_never_claimed_complete():
    fixture = _fixture(journal_raw=_journal_raw(loads=False))
    result = _verify(fixture)

    assert result["observed_load_event_count"] == 0
    assert result["observed_load_bindings_consistent"] is True
    assert result["loaded_module_code_identity_verified"] is False
    assert result["event_source_completeness_verified"] is False


def test_session_json_must_be_canonical_and_duplicate_free():
    fixture = _fixture()
    fixture["session_raw"] += b"\n"
    with pytest.raises(bridge_v1.SupervisorSessionClaimsError, match="canonical JSON"):
        _verify(fixture)


def test_session_json_rejects_duplicate_keys():
    fixture = _fixture()
    fixture["session_raw"] = b'{"schema":"spoofed",' + fixture["session_raw"][1:]
    with pytest.raises(bridge_v1.SupervisorSessionClaimsError, match="duplicate JSON object key"):
        _verify(fixture)


@pytest.mark.parametrize("invalid_bytes", [True, journal_v5.MAX_RAW_BYTES + 1])
def test_session_rejects_invalid_or_oversized_process_journal_reference(invalid_bytes):
    ref = {
        "stage": "C", "role": "process_journal", "object_id": "c-process-journal-001",
        "bytes": invalid_bytes, "sha256": "c" * 64,
    }
    fixture = _fixture(session_mutation=("process_journal_ref", ref))
    with pytest.raises(bridge_v1.SupervisorSessionClaimsError, match="process_journal_ref"):
        _verify(fixture)


def test_empty_case_selector_fails_closed_against_raw_ledger():
    fixture = _fixture()
    with pytest.raises(bridge_v1.SupervisorSessionClaimsError, match="case_id selector is malformed"):
        bridge_v1.bind_untrusted_supervisor_session_claims_v1(
            fixture["matrix_raw"], fixture["ledger_raw"], fixture["attestation_raw"],
            fixture["journal_raw"], fixture["session_raw"],
            candidate_key_id=attestation_fixtures.KEY_ID,
            candidate_public_key_bytes=fixture["public_key"],
            case_id="", attempt_id=ledger_fixtures.ATTEMPT_ID,
            nonce_hex=ledger_fixtures.NONCE,
        )
