from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts.core_strict_json import read_bounded_raw_json, strict_json_object
from scripts import f8_r008_attempt_ledger_v1 as ledger_v1
from scripts import f8_r008_native_integrity_registry_v1 as native_registry
from scripts import f8_r008_per_case_bundle_verifier_v2 as attempt_v2


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


def test_structurally_closed_ledger_stays_untrusted_and_unresolved() -> None:
    raw = _raw()
    result = ledger_v1.inspect_untrusted_attempt_ledger(raw, qualification_matrix_raw=MATRIX_RAW)
    assert result["ledger_structure_valid"] is True
    assert result["ledger_raw_bytes"] == len(raw)
    assert result["ledger_raw_sha256"] == hashlib.sha256(raw).hexdigest()
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
