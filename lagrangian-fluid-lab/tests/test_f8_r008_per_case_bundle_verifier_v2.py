from __future__ import annotations

import copy

import pytest

from scripts import f8_r008_per_case_bundle_verifier_v2 as verifier


def _diagnostic() -> dict[str, object]:
    return {
        "schema": verifier.SCHEMA,
        "scope_id": "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008",
        "case_id": "space-q0-dp0p0090",
        "qualification_row_sha256": "a" * 64,
        "attempt_id": "attempt-001",
        "nonce_hex": "b" * 32,
        "attempt_ledger_registration_seq": 7,
        "attempt_ledger_event_seqs": [7, 9, 12],
        "stage_bundle_refs": {
            stage: {
                "stage": stage,
                "role": f"{stage.lower()}_receipt",
                "object_id": f"{stage.lower()}-receipt-001",
                "bytes": 1,
                "sha256": "c" * 64,
            }
            for stage in ("B", "C", "D")
        },
        "stage_receipt_statuses": {stage: "passed" for stage in ("B", "C", "D")},
        "definition_control_raw_bindings_verified": False,
        "materialization_binary_semantics_verified": False,
        "gencase_execution_semantics_verified": False,
        "solver_execution_semantics_verified": False,
        "native_table_content_matches_C_raw_frames": False,
        "loaded_module_code_identity_verified": False,
        "attempt_outcome": "unresolved",
        "expected_frame_count": 2,
        "actual_frame_ordinals": [0],
        "actual_time_axis_ieee754_hex": [0.0.hex()],
        "failure_class": "unresolved_evidence",
        "failure_position": None,
        "qualification_adjudicated": False,
        "T1_numerical": False,
        "qualification_credit": 0,
    }


def test_structural_pass_statuses_remain_non_authorizing_diagnostics() -> None:
    result = _diagnostic()
    assert set(result["stage_receipt_statuses"].values()) == {"passed"}
    assert verifier.validate_untrusted_attempt_result_v2(result) is None
    assert result["attempt_outcome"] == "unresolved"
    assert result["qualification_adjudicated"] is False
    assert result["T1_numerical"] is False
    assert result["qualification_credit"] == 0


@pytest.mark.parametrize("field", sorted(verifier.SEMANTIC_BOOLEAN_FIELDS))
def test_caller_asserted_semantic_true_is_rejected(field: str) -> None:
    result = _diagnostic()
    result[field] = True
    with pytest.raises(verifier.AttemptResultV2Error, match="cannot be caller-asserted true"):
        verifier.validate_untrusted_attempt_result_v2(result)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("attempt_outcome", "passed"),
        ("qualification_adjudicated", True),
        ("T1_numerical", True),
        ("qualification_credit", 1),
    ],
)
def test_pass_and_qualification_claims_are_rejected(field: str, value: object) -> None:
    result = _diagnostic()
    result[field] = value
    with pytest.raises(verifier.AttemptResultV2Error):
        verifier.validate_untrusted_attempt_result_v2(result)


def test_v2_exact_schema_excludes_ambiguous_legacy_stage_boolean() -> None:
    result = _diagnostic()
    result["all_stages_passed"] = True
    with pytest.raises(verifier.AttemptResultV2Error, match="exact V2 field set"):
        verifier.validate_untrusted_attempt_result_v2(result)


@pytest.mark.parametrize("mutate", [
    lambda item: item.__setitem__("attempt_ledger_registration_seq", True),
    lambda item: item["stage_bundle_refs"]["B"].__setitem__("bytes", True),
    lambda item: item["attempt_ledger_event_seqs"].__setitem__(1, 7),
    lambda item: item.__setitem__("actual_frame_ordinals", [1]),
    lambda item: item.__setitem__("actual_time_axis_ieee754_hex", ["nan"]),
])
def test_invalid_primitive_types_and_noncanonical_sequences_fail_closed(mutate) -> None:
    result = copy.deepcopy(_diagnostic())
    mutate(result)
    with pytest.raises(verifier.AttemptResultV2Error):
        verifier.validate_untrusted_attempt_result_v2(result)
