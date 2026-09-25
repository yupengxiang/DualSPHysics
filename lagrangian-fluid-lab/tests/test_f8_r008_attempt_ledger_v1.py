from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
import test_f8_r008_per_case_bundle_verifier_v1 as bundle_fixtures

from scripts.core_strict_json import read_bounded_raw_json, strict_json_object
from scripts import f8_r008_attempt_ledger_v1 as ledger_v1
from scripts import f8_r008_attempt_evidence_binding_v1 as evidence_binding_v1
from scripts import f8_r008_c_execution_journal_v5 as journal_v5
from scripts import f8_r008_native_integrity_registry_v1 as native_registry
from scripts import f8_r008_per_case_bundle_verifier_v2 as attempt_v2
from scripts import f8_r008_per_case_bundle_verifier_v1 as stage_v1


CASE_ID = "space-q0-dp0p0090"
ATTEMPT_ID = "attempt-001"
NONCE = "b" * 32


SCOPE_RECEIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/t1-scope-design-v1/receipt.json"
)
MATRIX_RAW = read_bounded_raw_json(SCOPE_RECEIPT_PATH, max_bytes=ledger_v1.MAX_LEDGER_BYTES,
                                   label="frozen F8 R008 scope receipt")


def _matrix_document() -> dict[str, object]:
    return strict_json_object(MATRIX_RAW, label="frozen F8 R008 scope receipt",
                              max_bytes=ledger_v1.MAX_LEDGER_BYTES)


MATRIX_INDEX = ledger_v1.inspect_untrusted_qualification_matrix(MATRIX_RAW)
ROW_SHA = MATRIX_INDEX["rows"][0]["qualification_row_sha256"]
MATRIX_SHA = hashlib.sha256(MATRIX_RAW).hexdigest()


def _ref(stage: str, role: str, object_id: str) -> dict[str, object]:
    return {
        "stage": stage,
        "role": role,
        "object_id": object_id,
        "bytes": 17,
        "sha256": "c" * 64,
    }


def _event(kind: str, seq: int, **fields: object) -> dict[str, object]:
    return {
        "seq": seq,
        "mono_ns_hex": f"{seq:016x}",
        "kind": kind,
        "case_id": CASE_ID,
        "qualification_row_sha256": ROW_SHA,
        "attempt_id": ATTEMPT_ID,
        "nonce_hex": NONCE,
        **fields,
    }


def _complete_event_chain() -> list[dict[str, object]]:
    return [
        _event("attempt_registered", 0),
        _event("attempt_spawn", 1, stage="B", process_generation_id="b-root-001"),
        _event("process_terminal", 2, stage="B", process_generation_id="b-root-001",
               process_journal_ref=_ref("B", "process_journal", "b-process-journal-001")),
        _event("stage_receipt", 3, stage="B", receipt_ref=_ref("B", "b_receipt", "b-receipt-001")),
        _event("attempt_spawn", 4, stage="C", process_generation_id="c-root-001"),
        _event("process_terminal", 5, stage="C", process_generation_id="c-root-001",
               process_journal_ref=_ref("C", "process_journal", "c-process-journal-001")),
        _event("stage_receipt", 6, stage="C", receipt_ref=_ref("C", "c_v1_receipt", "c-receipt-001")),
        _event("attempt_spawn", 7, stage="D", process_generation_id="d-root-001"),
        _event("process_terminal", 8, stage="D", process_generation_id="d-root-001",
               process_journal_ref=_ref("D", "process_journal", "d-process-journal-001")),
        _event("stage_receipt", 9, stage="D", receipt_ref=_ref("D", "d_receipt", "d-receipt-001")),
        _event("attempt_terminal", 10, outcome="unresolved",
               terminal_ref=_ref("runtime", "attempt_terminal", "attempt-terminal-001")),
    ]


def _ledger_document(events: list[dict[str, object]] | None = None) -> dict[str, object]:
    actual_events = _complete_event_chain() if events is None else events
    end = max(len(actual_events), 1) - 1
    return {
        "schema": ledger_v1.LEDGER_SCHEMA,
        "scope_id": ledger_v1.SCOPE_ID,
        "qualification_matrix_raw_sha256": MATRIX_SHA,
        "supervisor_source_id": "f8-supervisor-v1",
        "coverage_start_ns_hex": "0000000000000000",
        "coverage_end_ns_hex": f"{end:016x}",
        "event_count": len(actual_events),
        "overflow": False,
        "lost_count": 0,
        "events": actual_events,
    }


def _raw(document: dict[str, object] | None = None) -> bytes:
    return json.dumps(document or _ledger_document(), separators=(",", ":"), allow_nan=False).encode()


def _synthetic_stage_receipt_raw(event: dict[str, object], *, status: str = "failed") -> bytes:
    stage = event["stage"]
    receipt = {field: None for field in stage_v1.STAGE_REQUIRED_FIELDS[stage]}
    receipt.update({
        "schema": stage_v1.STAGE_RECEIPT_SCHEMAS[stage],
        "scope_id": ledger_v1.SCOPE_ID,
        "case_id": event["case_id"],
        "attempt_id": event["attempt_id"],
        "nonce": event["nonce_hex"],
        "status": status,
        "started_at_utc": "2026-09-25T00:00:00Z",
        "ended_at_utc": "2026-09-25T00:00:00Z",
    })
    return json.dumps(receipt, separators=(",", ":"), allow_nan=False).encode()


def _synthetic_c_v5_journal_raw(event: dict[str, object], *, close_process: bool = True) -> bytes:
    process = {
        "pid_namespace_inode_hex": "0000000000000001",
        "pid": 42,
        "start_monotonic_ns_hex": "0000000000000002",
        "kernel_starttime_ticks_hex": "0000000000000003",
        "birth_seq_hex": "0000000000000000",
    }
    events = [
        {
            "seq": 0, "mono_ns_hex": "0000000000000000", "kind": "spawn",
            "attempt_nonce_hex": event["nonce_hex"], "process_generation_id": process,
            "supervisor_identity_binding": {"synthetic": True},
        },
        {
            "seq": 1, "mono_ns_hex": "0000000000000001", "kind": "exec",
            "attempt_nonce_hex": event["nonce_hex"], "process_generation_id": process,
            "executable_binding": {"synthetic": True}, "argv_sha256": "b" * 64,
            "cwd_object_id": "synthetic-cwd", "environment_sha256": "c" * 64,
        },
    ]
    if close_process:
        events.extend([
            {
                "seq": 2, "mono_ns_hex": "0000000000000002", "kind": "exit",
                "attempt_nonce_hex": event["nonce_hex"], "process_generation_id": process,
                "exit_code": 0, "signal": None,
            },
            {
                "seq": 3, "mono_ns_hex": "0000000000000003", "kind": "reap",
                "attempt_nonce_hex": event["nonce_hex"], "process_generation_id": process,
            },
        ])
    journal = {
        "schema": journal_v5.JOURNAL_SCHEMA,
        "attempt_nonce_hex": event["nonce_hex"],
        "source_id": "synthetic-c-runtime",
        "source_binary_sha256": "a" * 64,
        "coverage_start_ns_hex": "0000000000000000",
        "coverage_end_ns_hex": f"{len(events) - 1:016x}",
        "event_count": len(events),
        "overflow": False,
        "lost_count": 0,
        "events": events,
    }
    return json.dumps(journal, separators=(",", ":"), allow_nan=False).encode()


def _replace_artifact_raw(raw: bytes, artifacts: dict, key: tuple[str, str, str],
                          replacement: bytes) -> bytes:
    document = json.loads(raw)
    for event in document["events"]:
        ref = event.get("receipt_ref", event.get("process_journal_ref", event.get("terminal_ref")))
        if ref is not None and (ref["stage"], ref["role"], ref["object_id"]) == key:
            ref["bytes"] = len(replacement)
            ref["sha256"] = hashlib.sha256(replacement).hexdigest()
    artifacts[key] = replacement
    return _raw(document)


def _ledger_and_raw_objects(
    events: list[dict[str, object]] | None = None,
    *,
    stage_receipt_status: str = "failed",
) -> tuple[bytes, dict[tuple[str, str, str], bytes]]:
    document = _ledger_document(events)
    artifacts = {}
    for event in document["events"]:
        ref = event.get("receipt_ref", event.get("process_journal_ref", event.get("terminal_ref")))
        if ref is None:
            continue
        key = (ref["stage"], ref["role"], ref["object_id"])
        if event["kind"] == "stage_receipt":
            object_raw = _synthetic_stage_receipt_raw(event, status=stage_receipt_status)
        elif event["kind"] == "process_terminal" and event["stage"] == "C":
            object_raw = _synthetic_c_v5_journal_raw(event)
        else:
            object_raw = b"synthetic\x00raw:" + "/".join(key).encode()
        ref["bytes"] = len(object_raw)
        ref["sha256"] = hashlib.sha256(object_raw).hexdigest()
        artifacts[key] = object_raw
    return _raw(document), artifacts


def _attempt_result() -> dict[str, object]:
    events = _complete_event_chain()
    refs = {
        stage: next(event["receipt_ref"] for event in events
                    if event["kind"] == "stage_receipt" and event["stage"] == stage)
        for stage in ledger_v1.STAGES
    }
    return {
        "schema": attempt_v2.SCHEMA,
        "scope_id": ledger_v1.SCOPE_ID,
        "case_id": CASE_ID,
        "qualification_row_sha256": ROW_SHA,
        "attempt_id": ATTEMPT_ID,
        "nonce_hex": NONCE,
        "attempt_ledger_registration_seq": 0,
        "attempt_ledger_event_seqs": list(range(len(events))),
        "stage_bundle_refs": refs,
        "stage_receipt_statuses": {stage: "passed" for stage in ledger_v1.STAGES},
        "definition_control_raw_bindings_verified": False,
        "materialization_binary_semantics_verified": False,
        "gencase_execution_semantics_verified": False,
        "solver_execution_semantics_verified": False,
        "native_table_content_matches_C_raw_frames": False,
        "loaded_module_code_identity_verified": False,
        "attempt_outcome": "unresolved",
        "expected_frame_count": 193,
        "actual_frame_ordinals": [0],
        "actual_time_axis_ieee754_hex": [0.0.hex()],
        "failure_class": "unresolved_evidence",
        "failure_position": None,
        "qualification_adjudicated": False,
        "T1_numerical": False,
        "qualification_credit": 0,
    }


def _attempt_result_bound_to_ledger(
    raw: bytes,
    *,
    attempt_id: str = ATTEMPT_ID,
    nonce_hex: str = NONCE,
) -> dict[str, object]:
    result = _attempt_result()
    events = json.loads(raw)["events"]
    matching_events = [event for event in events
                       if event["attempt_id"] == attempt_id and event["nonce_hex"] == nonce_hex]
    result["attempt_id"] = attempt_id
    result["nonce_hex"] = nonce_hex
    result["attempt_ledger_registration_seq"] = matching_events[0]["seq"]
    result["attempt_ledger_event_seqs"] = [event["seq"] for event in matching_events]
    result["stage_bundle_refs"] = {
        stage: next(event["receipt_ref"] for event in matching_events
                    if event["kind"] == "stage_receipt" and event["stage"] == stage)
        for stage in ledger_v1.STAGES
    }
    return result


def _bundle_inputs(roots: dict, auth_bytes: dict, auth: dict) -> dict[str, object]:
    return {
        "bundle_roots": roots,
        "trusted_authorization_bytes": auth_bytes,
        "trusted_authorization_sha256": {
            stage: hashlib.sha256(raw).hexdigest() for stage, raw in auth_bytes.items()
        },
        "expected_authorization_envelopes": auth,
        "trusted_code_review_receipt_bytes": bundle_fixtures._trusted_code_review_receipt_bytes(),
        "trusted_runtime_assumption": bundle_fixtures._trusted_runtime_assumption(),
    }


def test_structurally_closed_ledger_stays_untrusted_and_unresolved() -> None:
    raw = _raw()
    result = ledger_v1.inspect_untrusted_attempt_ledger(raw, qualification_matrix_raw=MATRIX_RAW)
    assert result["ledger_structure_valid"] is True
    assert result["ledger_raw_bytes"] == len(raw)
    assert result["ledger_raw_sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["overflow"] is False
    assert result["lost_count"] == 0
    assert result["supervisor_attestation_verified"] is False
    assert result["attempt_ledger_complete"] is False
    assert result["attempt_count"] == 1
    attempt = result["attempts"][0]
    assert attempt["event_seqs"] == list(range(11))
    assert attempt["stage_receipt_seqs"] == {"B": 3, "C": 6, "D": 9}
    assert attempt["claimed_terminal_outcome"] == "unresolved"
    assert attempt["attempt_outcome"] == "unresolved"
    assert result["qualification_adjudicated"] is False
    assert result["T1_numerical"] is False
    assert result["qualification_credit"] == 0


def test_raw_object_binding_requires_exact_refs_and_only_proves_bytes_and_digest() -> None:
    raw, artifacts = _ledger_and_raw_objects()
    result = ledger_v1.bind_untrusted_attempt_ledger_raw_objects(
        raw, qualification_matrix_raw=MATRIX_RAW, artifact_raw_by_ref=artifacts,
    )
    assert result["all_non_null_refs_bound_to_supplied_raw_bytes"] is True
    assert result["reference_occurrence_count"] == 7
    assert result["referenced_object_count"] == 7
    assert result["supplied_raw_object_count"] == 7
    assert all(item["raw_bytes_match_ref"] for item in result["objects"])
    assert result["stage_receipt_envelope_count"] == 3
    assert result["stage_receipt_envelope_identity_matches_ledger"] is True
    assert all(item["receipt_envelope_identity_matches_ledger"]
               and not item["stage_bundle_verified"]
               for item in result["stage_receipt_envelopes"])
    assert result["c_v5_process_journal_check_count"] == 1
    assert result["c_v5_process_journal_nonce_bindings_match_ledger"] is True
    assert result["c_v5_process_journal_checks"][0]["outer_attempt_nonce_matches"] is True
    assert result["c_v5_process_journal_checks"][0][
        "journal_local_observed_process_lifecycle_complete_unverified"
    ] is True
    assert result["c_v5_process_journal_checks"][0]["event_source_completeness_verified"] is False
    assert result["c_v5_process_journal_checks"][0]["process_generation_identity_linked"] is False
    assert result["artifact_producer_authenticated"] is False
    assert result["descriptor_root_authenticated"] is False
    assert result["stage_receipt_semantics_verified"] is False
    assert result["process_journal_semantics_verified"] is False
    assert result["attempt_ledger_complete"] is False
    assert result["attempt_outcomes_resolved"] is False
    assert result["T1_numerical"] is False
    assert result["qualification_credit"] == 0


@pytest.mark.parametrize(("field", "value"), [
    ("case_id", "other-case"),
    ("attempt_id", "other-attempt"),
    ("nonce", "e" * 32),
])
def test_raw_object_binding_rejects_stage_receipt_identity_mismatch(field: str, value: str) -> None:
    raw, artifacts = _ledger_and_raw_objects()
    key = next(item for item in artifacts if item[1] == "b_receipt")
    receipt = json.loads(artifacts[key])
    receipt[field] = value
    replacement = json.dumps(receipt, separators=(",", ":"), allow_nan=False).encode()
    raw = _replace_artifact_raw(raw, artifacts, key, replacement)
    expected_message = "nonce differs from ledger" if field == "nonce" else f"{field} differs from ledger"
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match=expected_message):
        ledger_v1.bind_untrusted_attempt_ledger_raw_objects(
            raw, qualification_matrix_raw=MATRIX_RAW, artifact_raw_by_ref=artifacts,
        )


def test_raw_object_binding_rejects_malformed_stage_receipt_even_when_ref_matches() -> None:
    raw, artifacts = _ledger_and_raw_objects()
    key = next(item for item in artifacts if item[1] == "c_v1_receipt")
    raw = _replace_artifact_raw(raw, artifacts, key, b"{malformed-json")
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match="stage receipt envelope is invalid"):
        ledger_v1.bind_untrusted_attempt_ledger_raw_objects(
            raw, qualification_matrix_raw=MATRIX_RAW, artifact_raw_by_ref=artifacts,
        )


def test_raw_object_binding_rejects_cross_attempt_c_v5_journal_replay() -> None:
    raw, artifacts = _ledger_and_raw_objects()
    key = next(item for item in artifacts if item[0] == "C" and item[1] == "process_journal")
    journal = json.loads(artifacts[key])
    journal["attempt_nonce_hex"] = "e" * 32
    replacement = json.dumps(journal, separators=(",", ":"), allow_nan=False).encode()
    raw = _replace_artifact_raw(raw, artifacts, key, replacement)
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match="nonce-mismatched"):
        ledger_v1.bind_untrusted_attempt_ledger_raw_objects(
            raw, qualification_matrix_raw=MATRIX_RAW, artifact_raw_by_ref=artifacts,
        )


@pytest.mark.parametrize("terminal_outcome", [
    "passed", "failed", "incomplete", "timeout", "oom", "signaled", "unresolved",
])
def test_raw_object_binding_preserves_incomplete_journal_for_all_terminal_claims(
    terminal_outcome: str,
) -> None:
    events = _complete_event_chain()
    events[-1]["outcome"] = terminal_outcome
    raw, artifacts = _ledger_and_raw_objects(
        events, stage_receipt_status="passed" if terminal_outcome == "passed" else "failed",
    )
    key = next(item for item in artifacts if item[0] == "C" and item[1] == "process_journal")
    replacement = _synthetic_c_v5_journal_raw({"nonce_hex": NONCE}, close_process=False)
    raw = _replace_artifact_raw(raw, artifacts, key, replacement)
    result = ledger_v1.bind_untrusted_attempt_ledger_raw_objects(
        raw, qualification_matrix_raw=MATRIX_RAW, artifact_raw_by_ref=artifacts,
    )
    check = result["c_v5_process_journal_checks"][0]
    assert result["attempt_outcomes_resolved"] is False
    expected_receipt_status = "passed" if terminal_outcome == "passed" else "failed"
    assert all(item["receipt_status_claim"] == expected_receipt_status
               for item in result["stage_receipt_envelopes"])
    assert check["journal_local_observed_process_lifecycle_complete_unverified"] is False
    assert check["process_generation_identity_linked"] is False


def test_raw_object_binding_preserves_open_attempt_with_incomplete_c_v5_journal() -> None:
    raw, artifacts = _ledger_and_raw_objects(_complete_event_chain()[:6])
    key = next(item for item in artifacts if item[0] == "C" and item[1] == "process_journal")
    replacement = _synthetic_c_v5_journal_raw({"nonce_hex": NONCE}, close_process=False)
    raw = _replace_artifact_raw(raw, artifacts, key, replacement)
    result = ledger_v1.bind_untrusted_attempt_ledger_raw_objects(
        raw, qualification_matrix_raw=MATRIX_RAW, artifact_raw_by_ref=artifacts,
    )
    ledger_summary = ledger_v1.inspect_untrusted_attempt_ledger(
        raw, qualification_matrix_raw=MATRIX_RAW,
    )
    assert ledger_summary["attempt_events_closed"] is False
    assert result["attempt_outcomes_resolved"] is False
    assert result["c_v5_process_journal_checks"][0][
        "journal_local_observed_process_lifecycle_complete_unverified"
    ] is False


def test_raw_object_binding_rejects_malformed_c_v5_journal_after_ref_match() -> None:
    raw, artifacts = _ledger_and_raw_objects()
    key = next(item for item in artifacts if item[0] == "C" and item[1] == "process_journal")
    raw = _replace_artifact_raw(raw, artifacts, key, b"{malformed-c-v5-journal")
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match="C V5 process journal is invalid"):
        ledger_v1.bind_untrusted_attempt_ledger_raw_objects(
            raw, qualification_matrix_raw=MATRIX_RAW, artifact_raw_by_ref=artifacts,
        )


def test_raw_object_binding_enforces_c_v5_journal_byte_cap_before_hash(monkeypatch) -> None:
    raw, artifacts = _ledger_and_raw_objects()
    key = next(item for item in artifacts if item[0] == "C" and item[1] == "process_journal")
    c_journal_raw = artifacts[key]
    monkeypatch.setattr(ledger_v1, "MAX_C_V5_JOURNAL_BINDING_BYTES", len(c_journal_raw) - 1)
    hashed: list[bytes] = []
    original_sha256_bytes = ledger_v1.sha256_bytes

    def observe_hashed_bytes(value: bytes) -> str:
        hashed.append(value)
        return original_sha256_bytes(value)

    monkeypatch.setattr(ledger_v1, "sha256_bytes", observe_hashed_bytes)
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match="C V5 journal exceeds"):
        ledger_v1.bind_untrusted_attempt_ledger_raw_objects(
            raw, qualification_matrix_raw=MATRIX_RAW, artifact_raw_by_ref=artifacts,
        )
    assert c_journal_raw not in hashed


def test_raw_object_binding_enforces_stage_receipt_parser_byte_cap(monkeypatch) -> None:
    raw, artifacts = _ledger_and_raw_objects()
    key = next(item for item in artifacts if item[1] == "b_receipt")
    monkeypatch.setattr(stage_v1, "MAX_RECEIPT_BYTES", len(artifacts[key]) - 1)
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match="stage receipt envelope is invalid"):
        ledger_v1.bind_untrusted_attempt_ledger_raw_objects(
            raw, qualification_matrix_raw=MATRIX_RAW, artifact_raw_by_ref=artifacts,
        )


@pytest.mark.parametrize(("edit", "message"), [
    (lambda receipt: receipt.__setitem__("schema", "wrong-schema"), "unexpected stage receipt schema"),
    (lambda receipt: receipt.__setitem__("scope_id", "wrong-scope"), "stage receipt scope mismatch"),
    (lambda receipt: receipt.__setitem__("status", "unknown"), "status is outside the frozen enum"),
    (lambda receipt: receipt.__setitem__("started_at_utc", "not-a-time"), "started_at_utc must be an RFC3339"),
    (lambda receipt: receipt.__setitem__("ended_at_utc", "2026-09-24T00:00:00Z"),
     "stage receipt end precedes its start"),
    (lambda receipt: receipt.pop("authorization_binding"), "missing required fields"),
])
def test_raw_object_binding_rejects_invalid_stage_receipt_envelopes(edit, message: str) -> None:
    raw, artifacts = _ledger_and_raw_objects()
    key = next(item for item in artifacts if item[1] == "d_receipt")
    receipt = json.loads(artifacts[key])
    edit(receipt)
    replacement = json.dumps(receipt, separators=(",", ":"), allow_nan=False).encode()
    raw = _replace_artifact_raw(raw, artifacts, key, replacement)
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match=message):
        ledger_v1.bind_untrusted_attempt_ledger_raw_objects(
            raw, qualification_matrix_raw=MATRIX_RAW, artifact_raw_by_ref=artifacts,
        )


@pytest.mark.parametrize("inventory_edit, message", [
    (lambda artifacts: artifacts.pop(next(iter(artifacts))), "inventory differs"),
    (lambda artifacts: artifacts.__setitem__(("runtime", "unreferenced", "extra"), b"extra"),
     "inventory differs"),
    (lambda artifacts: artifacts.__setitem__(next(iter(artifacts)), b"x" * len(next(iter(artifacts.values())))),
     "SHA-256 differs"),
])
def test_raw_object_binding_rejects_missing_extra_or_mismatched_objects(inventory_edit, message: str) -> None:
    raw, artifacts = _ledger_and_raw_objects()
    inventory_edit(artifacts)
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match=message):
        ledger_v1.bind_untrusted_attempt_ledger_raw_objects(
            raw, qualification_matrix_raw=MATRIX_RAW, artifact_raw_by_ref=artifacts,
        )


def test_raw_object_binding_rejects_non_builtin_containers_and_non_bytes_values() -> None:
    raw, artifacts = _ledger_and_raw_objects()

    class DictSubclass(dict):
        pass

    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match="builtin dict"):
        ledger_v1.bind_untrusted_attempt_ledger_raw_objects(
            raw, qualification_matrix_raw=MATRIX_RAW, artifact_raw_by_ref=DictSubclass(artifacts),
        )
    bad_values = dict(artifacts)
    bad_values[next(iter(bad_values))] = bytearray(bad_values[next(iter(bad_values))])
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match="exact raw bytes"):
        ledger_v1.bind_untrusted_attempt_ledger_raw_objects(
            raw, qualification_matrix_raw=MATRIX_RAW, artifact_raw_by_ref=bad_values,
        )


def test_raw_object_binding_rejects_conflicting_descriptors_for_one_identity() -> None:
    document = _ledger_document()
    original_ref = copy.deepcopy(document["events"][3]["receipt_ref"])
    second_attempt_id = "attempt-002"
    second_nonce = "d" * 32
    document["events"].extend([
        _event("attempt_registered", 11, attempt_id=second_attempt_id, nonce_hex=second_nonce),
        _event("attempt_spawn", 12, stage="B", process_generation_id="b-root-002",
               attempt_id=second_attempt_id, nonce_hex=second_nonce),
        _event("process_terminal", 13, stage="B", process_generation_id="b-root-002",
               process_journal_ref=_ref("B", "process_journal", "b-process-journal-002"),
               attempt_id=second_attempt_id, nonce_hex=second_nonce),
        _event("stage_receipt", 14, stage="B", receipt_ref=original_ref,
               attempt_id=second_attempt_id, nonce_hex=second_nonce),
    ])
    document["event_count"] = len(document["events"])
    document["coverage_end_ns_hex"] = f"{len(document['events']) - 1:016x}"
    document["events"][-1]["receipt_ref"]["bytes"] += 1
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match="conflicting byte-count or SHA"):
        ledger_v1.bind_untrusted_attempt_ledger_raw_objects(
            _raw(document), qualification_matrix_raw=MATRIX_RAW, artifact_raw_by_ref={},
        )


@pytest.mark.parametrize("bad_key", [("B",), ("B", "b_receipt", 1)])
def test_raw_object_binding_rejects_malformed_reference_map_keys(bad_key) -> None:
    raw, artifacts = _ledger_and_raw_objects()
    artifacts[bad_key] = b"extra"
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match=r"exact \(stage, role, object_id\)"):
        ledger_v1.bind_untrusted_attempt_ledger_raw_objects(
            raw, qualification_matrix_raw=MATRIX_RAW, artifact_raw_by_ref=artifacts,
        )


def test_raw_object_binding_checks_byte_count_before_digest() -> None:
    raw, artifacts = _ledger_and_raw_objects()
    key = next(iter(artifacts))
    artifacts[key] += b"x"
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match="byte count differs"):
        ledger_v1.bind_untrusted_attempt_ledger_raw_objects(
            raw, qualification_matrix_raw=MATRIX_RAW, artifact_raw_by_ref=artifacts,
        )


def test_raw_object_binding_accepts_empty_not_started_inventory_without_qualifying() -> None:
    events = [
        _event("attempt_registered", 0),
        _event("attempt_terminal", 1, outcome="not_started", terminal_ref=None),
    ]
    result = ledger_v1.bind_untrusted_attempt_ledger_raw_objects(
        _raw(_ledger_document(events)), qualification_matrix_raw=MATRIX_RAW,
        artifact_raw_by_ref={},
    )
    assert result["reference_occurrence_count"] == 0
    assert result["referenced_object_count"] == 0
    assert result["all_non_null_refs_bound_to_supplied_raw_bytes"] is True
    assert result["attempt_ledger_complete"] is False
    assert result["qualification_credit"] == 0
    assert result["c_v5_process_journal_check_count"] == 0
    assert result["c_v5_process_journal_nonce_bindings_match_ledger"] is False


def test_integrated_attempt_binding_cross_checks_receipts_and_preserves_unresolved_denominator() -> None:
    raw, artifacts = _ledger_and_raw_objects(stage_receipt_status="passed")
    result = evidence_binding_v1.bind_untrusted_attempt_evidence_v1(
        MATRIX_RAW,
        raw,
        attempt_ledger_ref=_ledger_ref(raw),
        attempt_results=[_attempt_result_bound_to_ledger(raw)],
        artifact_raw_by_ref=artifacts,
    )

    assert result["schema"] == evidence_binding_v1.SCHEMA
    assert result["case_count"] == 15
    assert result["attempt_count"] == 1
    assert result["raw_object_count"] == 7
    assert result["stage_receipt_status_binding_count"] == 3
    assert result["referenced_stage_receipt_status_claims_match_projection"] is True
    assert result["unbound_non_not_run_stage_status_count"] == 0
    assert result["all_stage_status_claims_have_receipt_or_not_run"] is True
    assert result["c_v5_process_journal_nonce_bindings_match_ledger"] is True
    assert result["case_rows"][0]["case_outcome"] == "unresolved"
    assert result["case_rows"][0]["attempts"][0]["attempt_outcome"] == "unresolved"
    assert result["case_rows"][1]["case_outcome"] == "unresolved"
    assert result["attempt_ledger_complete"] is False
    assert result["stage_bundle_semantics_verified"] is False
    assert result["T1_numerical"] is False
    assert result["qualification_credit"] == 0


def test_integrated_open_attempt_does_not_overstate_unreferenced_failure_statuses() -> None:
    raw = _raw(_ledger_document([_event("attempt_registered", 0)]))
    result_row = _attempt_result()
    result_row["attempt_ledger_event_seqs"] = [0]
    result_row["stage_bundle_refs"] = {stage: None for stage in ledger_v1.STAGES}
    result_row["stage_receipt_statuses"] = {stage: "failed" for stage in ledger_v1.STAGES}
    result = evidence_binding_v1.bind_untrusted_attempt_evidence_v1(
        MATRIX_RAW,
        raw,
        attempt_ledger_ref=_ledger_ref(raw),
        attempt_results=[result_row],
        artifact_raw_by_ref={},
    )

    assert result["attempt_count"] == 1
    assert result["referenced_stage_receipt_status_claims_match_projection"] is True
    assert result["unbound_non_not_run_stage_status_count"] == 3
    assert result["all_stage_status_claims_have_receipt_or_not_run"] is False
    assert result["case_rows"][0]["attempts"][0]["attempt_outcome"] == "unresolved"
    assert result["case_rows"][0]["case_outcome"] == "unresolved"
    assert result["T1_numerical"] is False
    assert result["qualification_credit"] == 0


def test_integrated_retry_preserves_every_attempt_in_registration_order() -> None:
    events = _complete_event_chain()
    retry_registration = _event("attempt_registered", 11)
    retry_registration.update({"attempt_id": "attempt-002", "nonce_hex": "e" * 32})
    events.append(retry_registration)
    raw, artifacts = _ledger_and_raw_objects(events, stage_receipt_status="passed")

    first_result = _attempt_result_bound_to_ledger(raw)
    retry_result = copy.deepcopy(_attempt_result())
    retry_result.update({
        "attempt_id": "attempt-002",
        "nonce_hex": "e" * 32,
        "attempt_ledger_registration_seq": 11,
        "attempt_ledger_event_seqs": [11],
        "stage_bundle_refs": {stage: None for stage in ledger_v1.STAGES},
        "stage_receipt_statuses": {stage: "not_run" for stage in ledger_v1.STAGES},
        "actual_frame_ordinals": [],
        "actual_time_axis_ieee754_hex": [],
    })
    result = evidence_binding_v1.bind_untrusted_attempt_evidence_v1(
        MATRIX_RAW,
        raw,
        attempt_ledger_ref=_ledger_ref(raw),
        attempt_results=[first_result, retry_result],
        artifact_raw_by_ref=artifacts,
    )

    attempts = result["case_rows"][0]["attempts"]
    assert [attempt["attempt_id"] for attempt in attempts] == [ATTEMPT_ID, "attempt-002"]
    assert [attempt["attempt_outcome"] for attempt in attempts] == ["unresolved", "unresolved"]
    assert result["attempt_count"] == 2
    assert result["stage_receipt_status_binding_count"] == 3
    assert result["case_rows"][0]["case_outcome"] == "unresolved"
    assert result["case_rows"][1]["case_outcome"] == "unresolved"
    assert result["T1_numerical"] is False
    assert result["qualification_credit"] == 0


def test_case_bundle_binding_closes_each_retry_chain_against_ledger_references(tmp_path) -> None:
    first_identity = (CASE_ID, ATTEMPT_ID, NONCE)
    retry_id, retry_nonce = "attempt-002", "e" * 32
    retry_identity = (CASE_ID, retry_id, retry_nonce)
    first_dir = tmp_path / "first"
    retry_dir = tmp_path / "retry"
    first_dir.mkdir()
    retry_dir.mkdir()
    first_roots, first_auth_bytes, first_auth, _ = bundle_fixtures._build_chain(
        first_dir, attempt_id=ATTEMPT_ID, nonce=NONCE,
    )
    retry_roots, retry_auth_bytes, retry_auth, _ = bundle_fixtures._build_chain(
        retry_dir, attempt_id=retry_id, nonce=retry_nonce,
    )
    bundle_inputs = {
        first_identity: _bundle_inputs(first_roots, first_auth_bytes, first_auth),
        retry_identity: _bundle_inputs(retry_roots, retry_auth_bytes, retry_auth),
    }

    events = _complete_event_chain()
    retry_offset = len(events)
    for original in _complete_event_chain():
        retry_event = copy.deepcopy(original)
        retry_event["seq"] += retry_offset
        retry_event["mono_ns_hex"] = f"{retry_event['seq']:016x}"
        retry_event["attempt_id"] = retry_id
        retry_event["nonce_hex"] = retry_nonce
        if "process_generation_id" in retry_event:
            retry_event["process_generation_id"] += "-002"
        for field in ("receipt_ref", "process_journal_ref", "terminal_ref"):
            ref = retry_event.get(field)
            if ref is not None:
                ref["object_id"] += "-002"
        events.append(retry_event)

    raw, artifacts = _ledger_and_raw_objects(events, stage_receipt_status="passed")
    for event in events:
        if event["kind"] != "stage_receipt":
            continue
        identity = (event["case_id"], event["attempt_id"], event["nonce_hex"])
        stage = event["stage"]
        receipt_raw = (bundle_inputs[identity]["bundle_roots"][stage] / "receipt.json").read_bytes()
        ref = event["receipt_ref"]
        raw = _replace_artifact_raw(
            raw, artifacts, (ref["stage"], ref["role"], ref["object_id"]), receipt_raw,
        )

    first_result = _attempt_result_bound_to_ledger(raw)
    retry_result = _attempt_result_bound_to_ledger(
        raw, attempt_id=retry_id, nonce_hex=retry_nonce,
    )
    with pytest.raises(evidence_binding_v1.AttemptEvidenceBindingError,
                       match="only for each explicitly selected attempt"):
        evidence_binding_v1.bind_untrusted_attempt_evidence_with_case_bundles_v1(
            MATRIX_RAW,
            raw,
            attempt_ledger_ref=_ledger_ref(raw),
            attempt_results=[first_result, retry_result],
            artifact_raw_by_ref=artifacts,
            case_bundle_inputs_by_attempt=bundle_inputs,
            attempt_identities_to_verify=[first_identity],
        )

    bound_first = evidence_binding_v1.bind_untrusted_attempt_evidence_with_case_bundles_v1(
        MATRIX_RAW,
        raw,
        attempt_ledger_ref=_ledger_ref(raw),
        attempt_results=[first_result, retry_result],
        artifact_raw_by_ref=artifacts,
        case_bundle_inputs_by_attempt={first_identity: bundle_inputs[first_identity]},
        attempt_identities_to_verify=[first_identity],
    )

    bound_retry = evidence_binding_v1.bind_untrusted_attempt_evidence_with_case_bundles_v1(
        MATRIX_RAW,
        raw,
        attempt_ledger_ref=_ledger_ref(raw),
        attempt_results=[first_result, retry_result],
        artifact_raw_by_ref=artifacts,
        case_bundle_inputs_by_attempt={retry_identity: bundle_inputs[retry_identity]},
        attempt_identities_to_verify=[retry_identity],
    )

    attempts = bound_first["case_rows"][0]["attempts"]
    checks = bound_first["per_attempt_case_bundle_checks"]
    assert [item["attempt_id"] for item in attempts] == [ATTEMPT_ID, retry_id]
    assert [item["attempt_outcome"] for item in attempts] == ["unresolved", "unresolved"]
    assert [item["attempt_id"] for item in checks] == [ATTEMPT_ID]
    assert all(item["provenance_chain_references_closed"] is True for item in checks)
    assert all(item["safe_decode_receipts_and_metadata_artifacts_rehashed"] is True for item in checks)
    assert bound_first["complete_b_c_d_case_bundle_check_count"] == 1
    assert bound_first["complete_b_c_d_case_bundle_inventory_count"] == 2
    assert bound_first["unverified_complete_b_c_d_attempts"] == [
        {"case_id": CASE_ID, "attempt_id": retry_id, "nonce_hex": retry_nonce},
    ]
    assert bound_first["all_supplied_complete_b_c_d_chains_closed"] is False
    assert bound_retry["per_attempt_case_bundle_checks"][0]["attempt_id"] == retry_id
    assert bound_retry["unverified_complete_b_c_d_attempts"] == [
        {"case_id": CASE_ID, "attempt_id": ATTEMPT_ID, "nonce_hex": NONCE},
    ]
    for bound in (bound_first, bound_retry):
        assert bound["case_bundle_authority_authenticated"] is False
        assert bound["worker_execution_authenticated"] is False
        assert bound["case_rows"][0]["case_outcome"] == "unresolved"
        assert bound["case_rows"][1]["case_outcome"] == "unresolved"
        assert bound["T1_numerical"] is False
        assert bound["qualification_credit"] == 0

    with pytest.raises(evidence_binding_v1.AttemptEvidenceBindingError,
                       match="resource limit"):
        evidence_binding_v1.bind_untrusted_attempt_evidence_with_case_bundles_v1(
            MATRIX_RAW,
            raw,
            attempt_ledger_ref=_ledger_ref(raw),
            attempt_results=[first_result, retry_result],
            artifact_raw_by_ref=artifacts,
            case_bundle_inputs_by_attempt=bundle_inputs,
            attempt_identities_to_verify=[first_identity, retry_identity],
        )

    oversized_auth_inputs = {first_identity: copy.deepcopy(bundle_inputs[first_identity])}
    oversized_auth_inputs[first_identity]["trusted_authorization_bytes"]["B"] = (
        b"x" * (stage_v1.MAX_RECEIPT_BYTES + 1)
    )
    with pytest.raises(evidence_binding_v1.AttemptEvidenceBindingError,
                       match="authorization bytes exceed"):
        evidence_binding_v1.bind_untrusted_attempt_evidence_with_case_bundles_v1(
            MATRIX_RAW,
            raw,
            attempt_ledger_ref=_ledger_ref(raw),
            attempt_results=[first_result, retry_result],
            artifact_raw_by_ref=artifacts,
            case_bundle_inputs_by_attempt=oversized_auth_inputs,
            attempt_identities_to_verify=[first_identity],
        )

    swapped_bundle_inputs = {first_identity: bundle_inputs[retry_identity]}
    with pytest.raises(evidence_binding_v1.AttemptEvidenceBindingError,
                       match="receipt SHA-256 differs from the ledger attempt reference"):
        evidence_binding_v1.bind_untrusted_attempt_evidence_with_case_bundles_v1(
            MATRIX_RAW,
            raw,
            attempt_ledger_ref=_ledger_ref(raw),
            attempt_results=[first_result, retry_result],
            artifact_raw_by_ref=artifacts,
            case_bundle_inputs_by_attempt=swapped_bundle_inputs,
            attempt_identities_to_verify=[first_identity],
        )


def test_case_bundle_binding_keeps_open_attempt_without_bundle_unresolved() -> None:
    raw = _raw(_ledger_document([_event("attempt_registered", 0)]))
    result_row = _attempt_result()
    result_row["attempt_ledger_event_seqs"] = [0]
    result_row["stage_bundle_refs"] = {stage: None for stage in ledger_v1.STAGES}
    result_row["stage_receipt_statuses"] = {stage: "not_run" for stage in ledger_v1.STAGES}

    bound = evidence_binding_v1.bind_untrusted_attempt_evidence_with_case_bundles_v1(
        MATRIX_RAW,
        raw,
        attempt_ledger_ref=_ledger_ref(raw),
        attempt_results=[result_row],
        artifact_raw_by_ref={},
        case_bundle_inputs_by_attempt={},
        attempt_identities_to_verify=[],
    )

    assert bound["complete_b_c_d_case_bundle_check_count"] == 0
    assert bound["per_attempt_case_bundle_checks"] == []
    assert bound["case_rows"][0]["case_outcome"] == "unresolved"
    assert bound["case_rows"][0]["attempts"][0]["attempt_outcome"] == "unresolved"
    assert sum(row["case_outcome"] == "missing" for row in bound["case_rows"]) == 0
    assert bound["T1_numerical"] is False
    assert bound["qualification_credit"] == 0


def test_integrated_attempt_binding_rejects_receipt_status_claim_mismatch() -> None:
    raw, artifacts = _ledger_and_raw_objects(stage_receipt_status="failed")
    with pytest.raises(evidence_binding_v1.AttemptEvidenceBindingError,
                       match="raw receipt status claim differs"):
        evidence_binding_v1.bind_untrusted_attempt_evidence_v1(
        MATRIX_RAW,
        raw,
        attempt_ledger_ref=_ledger_ref(raw),
        attempt_results=[_attempt_result_bound_to_ledger(raw)],
        artifact_raw_by_ref=artifacts,
        )


def test_integrated_attempt_binding_retains_not_started_case_as_unresolved() -> None:
    events = [
        _event("attempt_registered", 0),
        _event("attempt_terminal", 1, outcome="not_started", terminal_ref=None),
    ]
    raw = _raw(_ledger_document(events))
    result_row = _attempt_result()
    result_row["attempt_ledger_event_seqs"] = [0, 1]
    result_row["stage_bundle_refs"] = {stage: None for stage in ledger_v1.STAGES}
    result_row["stage_receipt_statuses"] = {stage: "not_run" for stage in ledger_v1.STAGES}
    result = evidence_binding_v1.bind_untrusted_attempt_evidence_v1(
        MATRIX_RAW,
        raw,
        attempt_ledger_ref=_ledger_ref(raw),
        attempt_results=[result_row],
        artifact_raw_by_ref={},
    )

    assert result["attempt_count"] == 1
    assert result["raw_object_count"] == 0
    assert result["stage_receipt_status_binding_count"] == 0
    assert result["case_rows"][0]["case_outcome"] == "unresolved"
    assert result["case_rows"][0]["attempts"][0]["attempt_outcome"] == "unresolved"
    assert sum(row["case_outcome"] == "missing" for row in result["case_rows"]) == 0
    assert result["qualification_credit"] == 0


@pytest.mark.parametrize("limit_name", ["MAX_REFERENCED_OBJECTS", "MAX_REFERENCED_RAW_BYTES"])
def test_raw_object_binding_enforces_resource_limits(monkeypatch, limit_name: str) -> None:
    raw, artifacts = _ledger_and_raw_objects()
    if limit_name == "MAX_REFERENCED_OBJECTS":
        monkeypatch.setattr(ledger_v1, limit_name, len(artifacts) - 1)
        message = "object-count limit"
    else:
        monkeypatch.setattr(ledger_v1, limit_name, sum(map(len, artifacts.values())) - 1)
        message = "aggregate byte limit"
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match=message):
        ledger_v1.bind_untrusted_attempt_ledger_raw_objects(
            raw, qualification_matrix_raw=MATRIX_RAW, artifact_raw_by_ref=artifacts,
        )


def test_structural_terminal_pass_claim_is_preserved_but_never_derived() -> None:
    events = _complete_event_chain()
    events[-1]["outcome"] = "passed"
    result = ledger_v1.inspect_untrusted_attempt_ledger(
        _raw(_ledger_document(events)), qualification_matrix_raw=MATRIX_RAW,
    )
    assert result["attempts"][0]["claimed_terminal_outcome"] == "passed"
    assert result["attempts"][0]["attempt_outcome"] == "unresolved"
    assert result["attempt_ledger_complete"] is False
    assert result["T1_numerical"] is False
    assert result["qualification_credit"] == 0


def test_empty_ledger_does_not_prove_any_case_missing() -> None:
    result = ledger_v1.inspect_untrusted_attempt_ledger(
        _raw(_ledger_document([])), qualification_matrix_raw=MATRIX_RAW,
    )
    assert result["ledger_structure_valid"] is True
    assert result["attempt_count"] == 0
    assert result["attempt_events_closed"] is False
    assert result["attempt_ledger_complete"] is False


def test_matrix_row_digest_uses_v12_canonical_json_and_preserves_order() -> None:
    matrix = _matrix_document()
    raw = MATRIX_RAW
    inspected = ledger_v1.inspect_untrusted_qualification_matrix(raw)
    first_row = matrix["matrix"]["rows"][0]
    canonical = json.dumps(first_row, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    assert inspected["row_count"] == 15
    assert [item["case_id"] for item in inspected["rows"]] == [
        row["case_id"] for row in matrix["matrix"]["rows"]
    ]
    assert inspected["rows"][0]["qualification_row_sha256"] == hashlib.sha256(canonical).hexdigest()
    assert inspected["frozen_matrix_source_authenticated"] is False
    assert inspected["matrix_raw_sha256"] == ledger_v1.FROZEN_MATRIX_RAW_SHA256
    assert ledger_v1.FROZEN_MATRIX_RAW_SHA256 == native_registry.FROZEN_SCOPE_SHA256


@pytest.mark.parametrize(("field", "value"), [
    ("alpha", 1.0),
    ("control_amplitude_m_s2", 0.02),
])
def test_semantically_valid_but_changed_scope_matrix_fails_frozen_digest(field: str, value: float) -> None:
    document = copy.deepcopy(_matrix_document())
    document["matrix"]["rows"][0][field] = value
    raw = json.dumps(document, separators=(",", ":"), allow_nan=False).encode()
    with pytest.raises(ledger_v1.AttemptLedgerV1Error,
                       match="raw digest differs from the pinned F8 R008 frozen scope"):
        ledger_v1.inspect_untrusted_qualification_matrix(raw)


@pytest.mark.parametrize("mutate, message", [
    (lambda doc: doc["matrix"].__setitem__("case_count", True), "case_count must be the builtin integer 15"),
    (lambda doc: doc["matrix"]["rows"][1].__setitem__("case_id", CASE_ID), "duplicates case_id"),
    (lambda doc: doc["matrix"]["rows"][0].__setitem__("qualification_only", False),
     "not marked qualification-only"),
    (lambda doc: doc["matrix"]["rows"][0].__setitem__("alpha", None),
     "alpha must be a finite builtin float"),
    (lambda doc: doc["matrix"]["rows"][0].__setitem__("dp_m", []),
     "dp_m must be a finite builtin float"),
    (lambda doc: doc["matrix"]["rows"][0].__setitem__("control_samples_per_period", True),
     "control_samples_per_period must be a builtin integer"),
    (lambda doc: doc["matrix"]["rows"][13].__setitem__("compare_to", None),
     "must compare to the fixed spatial anchor"),
    (lambda doc: doc["matrix"]["rows"][0].__setitem__("observation_end_output_index", 321),
     "output count differs from its inclusive indices"),
    (lambda doc: doc["matrix"]["rows"][0].__setitem__("unfrozen_extra", 1), "row 0 fields are not exact"),
])
def test_invalid_frozen_matrix_rows_reject(mutate, message: str) -> None:
    document = copy.deepcopy(_matrix_document())
    mutate(document)
    raw = json.dumps(document, separators=(",", ":"), allow_nan=False).encode()
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match=message):
        ledger_v1.inspect_untrusted_qualification_matrix(raw)


def test_ledger_matrix_raw_digest_and_event_row_digest_must_both_match() -> None:
    document = _ledger_document()
    document["qualification_matrix_raw_sha256"] = "e" * 64
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match="do not match the ledger matrix digest"):
        ledger_v1.inspect_untrusted_attempt_ledger(
            _raw(document), qualification_matrix_raw=MATRIX_RAW,
        )
    document = _ledger_document()
    for event in document["events"]:
        event["qualification_row_sha256"] = "e" * 64
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match="row digest differs from frozen matrix row"):
        ledger_v1.inspect_untrusted_attempt_ledger(
            _raw(document), qualification_matrix_raw=MATRIX_RAW,
        )


def test_ledger_cannot_reference_case_outside_frozen_qualification_matrix() -> None:
    document = _ledger_document()
    for event in document["events"]:
        event["case_id"] = "not-in-frozen-matrix"
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match="non-qualification case"):
        ledger_v1.inspect_untrusted_attempt_ledger(
            _raw(document), qualification_matrix_raw=MATRIX_RAW,
        )


def test_open_attempt_is_retained_but_not_marked_locally_closed() -> None:
    events = [_event("attempt_registered", 0)]
    result = ledger_v1.inspect_untrusted_attempt_ledger(
        _raw(_ledger_document(events)), qualification_matrix_raw=MATRIX_RAW,
    )
    assert result["attempt_count"] == 1
    assert result["attempt_events_closed"] is False
    assert result["attempts"][0]["attempt_events_closed"] is False
    assert result["attempts"][0]["claimed_terminal_outcome"] is None
    assert result["attempts"][0]["attempt_outcome"] == "unresolved"


def test_not_started_terminal_requires_no_spawn_and_is_still_unresolved() -> None:
    events = [
        _event("attempt_registered", 0),
        _event("attempt_terminal", 1, outcome="not_started", terminal_ref=None),
    ]
    result = ledger_v1.inspect_untrusted_attempt_ledger(
        _raw(_ledger_document(events)), qualification_matrix_raw=MATRIX_RAW,
    )
    attempt = result["attempts"][0]
    assert attempt["claimed_terminal_outcome"] == "not_started"
    assert attempt["attempt_events_closed"] is True
    assert attempt["attempt_outcome"] == "unresolved"


@pytest.mark.parametrize("mutate, message", [
    (lambda doc: doc["events"][1].__setitem__("seq", 4), "contiguous range"),
    (lambda doc: doc["events"][2].__setitem__("mono_ns_hex", "0000000000000000"), "moved backwards"),
    (lambda doc: doc.__setitem__("overflow", 0), "overflow must be the builtin false"),
    (lambda doc: doc.__setitem__("lost_count", True), "lost_count must be a builtin integer"),
    (lambda doc: doc["events"][3]["receipt_ref"].__setitem__("stage", "C"), "different stage"),
    (lambda doc: doc["events"][3].__setitem__("unexpected", 1), "fields are not exact"),
])
def test_malformed_top_level_event_domains_and_refs_reject(mutate, message: str) -> None:
    document = copy.deepcopy(_ledger_document())
    mutate(document)
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match=message):
        ledger_v1.inspect_untrusted_attempt_ledger(_raw(document), qualification_matrix_raw=MATRIX_RAW)


@pytest.mark.parametrize("event_index,reference_field,role", [
    (2, "process_journal_ref", "arbitrary_journal"),
    (3, "receipt_ref", "arbitrary_receipt"),
    (10, "terminal_ref", "arbitrary_terminal"),
])
def test_ledger_reference_roles_are_fixed_by_event_kind(
    event_index: int, reference_field: str, role: str,
) -> None:
    document = _ledger_document()
    document["events"][event_index][reference_field]["role"] = role
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match="does not target the fixed role"):
        ledger_v1.inspect_untrusted_attempt_ledger(
            _raw(document), qualification_matrix_raw=MATRIX_RAW,
        )


def test_attempt_terminal_reference_must_use_runtime_stage() -> None:
    document = _ledger_document()
    document["events"][10]["terminal_ref"]["stage"] = "B"
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match="names a different stage"):
        ledger_v1.inspect_untrusted_attempt_ledger(
            _raw(document), qualification_matrix_raw=MATRIX_RAW,
        )


def test_duplicate_json_keys_reject_before_structural_validation() -> None:
    raw = _raw()
    duplicate = raw.replace(b'"schema":"core.cfd.f8.r008_attempt_ledger.v1",',
                            b'"schema":"core.cfd.f8.r008_attempt_ledger.v1",'
                            b'"schema":"core.cfd.f8.r008_attempt_ledger.v1",', 1)
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match="duplicate JSON object key"):
        ledger_v1.inspect_untrusted_attempt_ledger(duplicate, qualification_matrix_raw=MATRIX_RAW)


@pytest.mark.parametrize("reuse", ["attempt_id", "nonce_hex"])
def test_attempt_id_and_nonce_are_unique_across_scope(reuse: str) -> None:
    events = _complete_event_chain()
    second_id = ATTEMPT_ID if reuse == "attempt_id" else "attempt-002"
    second_nonce = "e" * 32 if reuse == "attempt_id" else NONCE
    event = _event("attempt_registered", 11)
    event.update({"seq": 11, "attempt_id": second_id, "nonce_hex": second_nonce,
                  "case_id": "space-q1-dp0p0090", "qualification_row_sha256": "f" * 64})
    events.append(event)
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match="reused"):
        ledger_v1.inspect_untrusted_attempt_ledger(
            _raw(_ledger_document(events)), qualification_matrix_raw=MATRIX_RAW,
        )


def test_attempt_cannot_change_case_or_row_after_registration() -> None:
    events = _complete_event_chain()
    events[6]["case_id"] = "space-q1-dp0p0090"
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match="changes its registered case_id"):
        ledger_v1.inspect_untrusted_attempt_ledger(
            _raw(_ledger_document(events)), qualification_matrix_raw=MATRIX_RAW,
        )


@pytest.mark.parametrize("edit, message", [
    (lambda events: events.insert(1, _event("attempt_spawn", 1, stage="B",
                                            process_generation_id="b-root-001")),
     "exact contiguous range"),
    (lambda events: events[5].update(process_generation_id="other-root-001"),
     "no matching invocation root"),
    (lambda events: events[10].update(outcome="not_started", terminal_ref=None),
     "not_started terminal conflicts"),
    (lambda events: events.append(_event("stage_receipt", 11, stage="B",
                                         receipt_ref=_ref("B", "b_receipt", "late-b-receipt"))),
     "events after its terminal"),
])
def test_attempt_level_order_and_terminal_conflicts_reject(edit, message: str) -> None:
    events = copy.deepcopy(_complete_event_chain())
    edit(events)
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match=message):
        ledger_v1.inspect_untrusted_attempt_ledger(
            _raw(_ledger_document(events)), qualification_matrix_raw=MATRIX_RAW,
        )


def test_cannot_start_c_before_b_receipt() -> None:
    events = [
        _event("attempt_registered", 0),
        _event("attempt_spawn", 1, stage="C", process_generation_id="c-root-001"),
        _event("process_terminal", 2, stage="C", process_generation_id="c-root-001",
               process_journal_ref=_ref("C", "process_journal", "c-process-journal-001")),
        _event("stage_receipt", 3, stage="C", receipt_ref=_ref("C", "c_v1_receipt", "c-receipt-001")),
        _event("attempt_spawn", 4, stage="B", process_generation_id="b-root-001"),
        _event("process_terminal", 5, stage="B", process_generation_id="b-root-001",
               process_journal_ref=_ref("B", "process_journal", "b-process-journal-001")),
        _event("stage_receipt", 6, stage="B", receipt_ref=_ref("B", "b_receipt", "b-receipt-001")),
    ]
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match="C stage appears before"):
        ledger_v1.inspect_untrusted_attempt_ledger(
            _raw(_ledger_document(events)), qualification_matrix_raw=MATRIX_RAW,
        )


def test_attempt_result_projection_must_match_exact_ledger_inventory() -> None:
    ledger_v1.validate_attempt_result_ledger_projection_v2(
        _attempt_result(), _raw(), qualification_matrix_raw=MATRIX_RAW,
    )


@pytest.mark.parametrize("mutate, message", [
    (lambda result: result.__setitem__("qualification_row_sha256", "f" * 64), "differs from its ledger"),
    (lambda result: result["attempt_ledger_event_seqs"].pop(), "event seq inventory differs"),
    (lambda result: result.__setitem__("expected_frame_count", 2), "differs from its frozen qualification row"),
    (lambda result: result["stage_bundle_refs"]["C"].__setitem__("sha256", "e" * 64),
     "stage refs differ"),
    (lambda result: result["stage_bundle_refs"].__setitem__("D", None), "stage refs differ"),
])
def test_attempt_result_projection_rejects_cross_attempt_or_partial_claims(mutate, message: str) -> None:
    result = _attempt_result()
    mutate(result)
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match=message):
        ledger_v1.validate_attempt_result_ledger_projection_v2(
            result, _raw(), qualification_matrix_raw=MATRIX_RAW,
        )


def test_attempt_result_pass_status_without_stage_receipt_event_is_rejected() -> None:
    result = _attempt_result()
    result["stage_bundle_refs"]["C"] = None
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match="stage refs differ"):
        ledger_v1.validate_attempt_result_ledger_projection_v2(
            result, _raw(), qualification_matrix_raw=MATRIX_RAW,
        )


def _ledger_ref(raw: bytes) -> dict[str, object]:
    return {
        "stage": "runtime",
        "role": "attempt_ledger",
        "object_id": "ledger-object-001",
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _aggregate(raw: bytes, attempt_results: list[dict[str, object]]) -> dict[str, object]:
    return ledger_v1.build_untrusted_attempt_aggregate_v2(
        MATRIX_RAW,
        raw,
        attempt_ledger_ref=_ledger_ref(raw),
        attempt_results=attempt_results,
    )


def _aggregate_raw(aggregate: dict[str, object]) -> bytes:
    return json.dumps(aggregate, separators=(",", ":"), allow_nan=False).encode()


def test_untrusted_aggregate_emits_all_matrix_rows_and_preserves_unresolved_record() -> None:
    raw = _raw()
    aggregate = _aggregate(raw, [_attempt_result()])

    assert set(aggregate) == ledger_v1.AGGREGATE_FIELDS
    assert aggregate["schema"] == ledger_v1.AGGREGATE_SCHEMA
    assert aggregate["expected_case_count"] == 15
    assert [row["case_id"] for row in aggregate["case_rows"]] == [
        row["case_id"] for row in MATRIX_INDEX["rows"]
    ]
    assert aggregate["case_rows"][0]["attempts"] == [_attempt_result()]
    assert all(row["case_outcome"] == "unresolved" for row in aggregate["case_rows"])
    assert all(row["qualifying_attempt_id"] is None for row in aggregate["case_rows"])
    assert aggregate["case_outcome_counts"] == {
        "passed": 0, "failed": 0, "missing": 0, "unresolved": 15,
    }
    assert aggregate["attempt_outcome_counts"]["unresolved"] == 1
    assert aggregate["aggregate_outcome"] == "accounting_unresolved"
    assert aggregate["attempt_ledger_attestation_ref"] is None
    assert aggregate["attempt_ledger_complete"] is False
    assert aggregate["qualification_adjudicated"] is False
    assert aggregate["T1_numerical"] is False
    assert aggregate["qualification_credit"] == 0


def test_empty_ledger_aggregate_keeps_all_rows_unresolved_not_missing() -> None:
    raw = _raw(_ledger_document([]))
    aggregate = _aggregate(raw, [])

    assert len(aggregate["case_rows"]) == 15
    assert all(row["case_outcome"] == "unresolved" for row in aggregate["case_rows"])
    assert all(row["attempts"] == [] for row in aggregate["case_rows"])
    assert aggregate["case_outcome_counts"] == {
        "passed": 0, "failed": 0, "missing": 0, "unresolved": 15,
    }
    assert sum(aggregate["attempt_outcome_counts"].values()) == 0
    assert aggregate["aggregate_outcome"] == "accounting_unresolved"


def test_aggregate_preserves_retry_history_in_registration_order() -> None:
    events = _complete_event_chain()
    retry_registration = _event("attempt_registered", 11)
    retry_registration.update({"attempt_id": "attempt-002", "nonce_hex": "e" * 32})
    events.append(retry_registration)
    raw = _raw(_ledger_document(events))

    retry_result = copy.deepcopy(_attempt_result())
    retry_result.update({
        "attempt_id": "attempt-002",
        "nonce_hex": "e" * 32,
        "attempt_ledger_registration_seq": 11,
        "attempt_ledger_event_seqs": [11],
        "stage_bundle_refs": {stage: None for stage in ledger_v1.STAGES},
        "stage_receipt_statuses": {stage: "not_run" for stage in ledger_v1.STAGES},
        "actual_frame_ordinals": [],
        "actual_time_axis_ieee754_hex": [],
    })
    aggregate = _aggregate(raw, [_attempt_result(), retry_result])
    first_case = aggregate["case_rows"][0]

    assert [attempt["attempt_id"] for attempt in first_case["attempts"]] == [
        ATTEMPT_ID, "attempt-002",
    ]
    assert all(attempt["attempt_outcome"] == "unresolved" for attempt in first_case["attempts"])
    assert aggregate["attempt_outcome_counts"]["unresolved"] == 2
    assert aggregate["case_outcome_counts"]["unresolved"] == 15


def test_aggregate_requires_exact_registration_inventory() -> None:
    raw = _raw()
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match="complete observed ledger registration inventory"):
        _aggregate(raw, [])

    extra = copy.deepcopy(_attempt_result())
    extra.update({"attempt_id": "unregistered-attempt", "nonce_hex": "e" * 32})
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match="not registered"):
        _aggregate(raw, [extra])


@pytest.mark.parametrize("mutate, message", [
    (lambda ref: ref.__setitem__("stage", "B"), "different stage"),
    (lambda ref: ref.__setitem__("role", "other_role"), "fixed role attempt_ledger"),
    (lambda ref: ref.__setitem__("bytes", ref["bytes"] + 1), "byte count or raw SHA differs"),
    (lambda ref: ref.__setitem__("sha256", "f" * 64), "byte count or raw SHA differs"),
    (lambda ref: ref.__setitem__("unexpected", True), "exact descriptor-ref fields"),
])
def test_aggregate_rejects_unbound_or_malformed_ledger_reference(mutate, message: str) -> None:
    raw = _raw()
    reference = _ledger_ref(raw)
    mutate(reference)
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match=message):
        ledger_v1.build_untrusted_attempt_aggregate_v2(
            MATRIX_RAW, raw, attempt_ledger_ref=reference, attempt_results=[_attempt_result()],
        )


def test_aggregate_rejects_attestation_reference_without_trust_verifier() -> None:
    raw = _raw()
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match="active supervisor trust verifier"):
        ledger_v1.build_untrusted_attempt_aggregate_v2(
            MATRIX_RAW,
            raw,
            attempt_ledger_ref=_ledger_ref(raw),
            attempt_results=[_attempt_result()],
            attempt_ledger_attestation_ref=_ref("runtime", "ledger_attestation", "attestation-001"),
        )


def test_aggregate_rejects_caller_asserted_attempt_pass() -> None:
    result = _attempt_result()
    result["attempt_outcome"] = "passed"
    raw = _raw()
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match="attempt outcome must remain unresolved"):
        _aggregate(raw, [result])


def test_untrusted_aggregate_validator_accepts_exact_rederived_projection() -> None:
    raw = _raw()
    aggregate = _aggregate(raw, [_attempt_result()])
    assert ledger_v1.validate_untrusted_attempt_aggregate_v2(
        _aggregate_raw(aggregate), MATRIX_RAW, raw,
    ) is None


@pytest.mark.parametrize("mutate,message", [
    (lambda aggregate: aggregate.__setitem__("expected_case_count", 14),
     "expected_case_count must be the builtin integer 15"),
    (lambda aggregate: aggregate["case_rows"].__setitem__(0, aggregate["case_rows"][1]),
     "identity/order differs from the frozen matrix"),
    (lambda aggregate: aggregate["case_rows"][0].__setitem__("case_outcome", "missing"),
     "must remain unresolved without trusted adjudication"),
    (lambda aggregate: aggregate["case_outcome_counts"].__setitem__("missing", 1),
     "case_outcome_counts.missing differs"),
    (lambda aggregate: aggregate["attempt_outcome_counts"].__setitem__("unresolved", False),
     "attempt_outcome_counts.unresolved must be a builtin integer"),
    (lambda aggregate: aggregate.__setitem__("qualification_credit", False),
     "qualification_credit must be the builtin integer zero"),
])
def test_untrusted_aggregate_validator_rejects_tampered_projection(mutate, message: str) -> None:
    raw = _raw()
    aggregate = _aggregate(raw, [_attempt_result()])
    mutate(aggregate)
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match=message):
        ledger_v1.validate_untrusted_attempt_aggregate_v2(_aggregate_raw(aggregate), MATRIX_RAW, raw)


def test_untrusted_aggregate_validator_rejects_extra_row_fields() -> None:
    raw = _raw()
    aggregate = _aggregate(raw, [_attempt_result()])
    aggregate["case_rows"][0]["unreviewed_claim"] = True
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match="exact field set"):
        ledger_v1.validate_untrusted_attempt_aggregate_v2(_aggregate_raw(aggregate), MATRIX_RAW, raw)


def test_untrusted_aggregate_validator_bounds_rows_before_processing() -> None:
    raw = _raw()
    aggregate = _aggregate(raw, [_attempt_result()])
    aggregate["case_rows"].append(copy.deepcopy(aggregate["case_rows"][-1]))
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match="exactly the 15 frozen matrix rows"):
        ledger_v1.validate_untrusted_attempt_aggregate_v2(_aggregate_raw(aggregate), MATRIX_RAW, raw)


def test_untrusted_aggregate_validator_rejects_unverified_attestation() -> None:
    raw = _raw()
    aggregate = _aggregate(raw, [_attempt_result()])
    aggregate["attempt_ledger_attestation_ref"] = _ref(
        "runtime", "ledger_attestation", "attestation-001",
    )
    with pytest.raises(ledger_v1.AttemptLedgerV1Error, match="active supervisor trust verifier"):
        ledger_v1.validate_untrusted_attempt_aggregate_v2(_aggregate_raw(aggregate), MATRIX_RAW, raw)
