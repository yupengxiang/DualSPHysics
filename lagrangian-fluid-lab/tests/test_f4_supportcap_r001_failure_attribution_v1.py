from __future__ import annotations

import json

import h5py
import numpy as np
import pytest

from scripts import f4_supportcap_r001_failure_attribution_v1 as attribution


def test_classifies_later_native_frame_against_original_t0_seeds() -> None:
    status = attribution.classify_initial_failure(
        frame_time_s=0.160014986,
        seed_positions_match_t0=True,
        trace_reliable=np.zeros(512, dtype=bool),
        support_distance=np.full(512, 0.12),
        sampler_passed=np.zeros(512, dtype=bool),
        maximum_support_distance_m=0.03,
    )
    assert status == "t0_geometric_seeds_compared_to_later_native_frame_support"


def test_does_not_call_support_failure_a_time_mismatch_without_all_evidence() -> None:
    reliable = np.zeros(8, dtype=bool)
    distance = np.array([0.01] * 8)
    passed = np.zeros(8, dtype=bool)
    assert attribution.classify_initial_failure(
        frame_time_s=0.16, seed_positions_match_t0=True, trace_reliable=reliable,
        support_distance=distance, sampler_passed=passed, maximum_support_distance_m=0.03,
    ) == "initial_support_gate_failure_not_uniquely_attributed"


def test_rejects_misaligned_diagnostic_seed_axes() -> None:
    with pytest.raises(ValueError, match="seed axes differ"):
        attribution.classify_initial_failure(
            frame_time_s=0.1, seed_positions_match_t0=True,
            trace_reliable=np.zeros(2, dtype=bool), support_distance=np.zeros(3),
            sampler_passed=np.zeros(2, dtype=bool), maximum_support_distance_m=0.03,
        )


def _historical_documents() -> tuple[dict, dict, dict, dict, dict]:
    return (
        attribution.load_json(attribution.AUTHORIZATION),
        attribution.load_json(attribution.INPUT_PREFLIGHT),
        attribution.load_json(attribution.ATTEMPT),
        attribution.load_json(attribution.ACCEPTANCE),
        attribution.load_json(attribution.RESULT),
    )


def test_historical_one_attempt_receipt_chain_is_intact_and_tamper_evident() -> None:
    authorization, preflight, attempt, acceptance, result = _historical_documents()
    attribution.validate_historical_attempt(authorization, preflight, attempt, acceptance, result)

    acceptance["gate_evaluation"]["unknown_count"] += 1
    with pytest.raises(PermissionError, match="immutable evidence"):
        attribution.validate_historical_attempt(authorization, preflight, attempt, acceptance, result)


def test_attempt_preflight_hashes_use_the_executor_canonical_json_encoding() -> None:
    attempt = attribution.load_json(attribution.ATTEMPT)
    assert attribution.canonical_json_sha256(attribution.LAB / attribution.INPUT_PREFLIGHT) == attempt[
        "input_preflight_sha256"
    ]
    assert attribution.canonical_json_sha256(attribution.LAB / attribution.ENVIRONMENT_PREFLIGHT) == attempt[
        "environment_preflight_sha256"
    ]
    with pytest.raises(ValueError, match="canonical JSON digest"):
        attribution.validate_canonical_json_digest(
            attribution.INPUT_PREFLIGHT, "0" * 64, "r001 input preflight"
        )


def test_result_file_reference_rejects_changed_digest() -> None:
    acceptance = attribution.load_json(attribution.ACCEPTANCE)
    attribution.validate_result_reference(acceptance, attribution.LAB / attribution.RESULT)
    altered = json.loads(json.dumps(acceptance))
    altered["result"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="immutable file"):
        attribution.validate_result_reference(altered, attribution.LAB / attribution.RESULT)


def test_pinned_trace_digest_and_embedded_binding_match_result() -> None:
    assert attribution.validate_pinned_trace(attribution.LAB / attribution.TRACE) == attribution.EXPECTED_TRACE_SHA256
    authorization = attribution.load_json(attribution.AUTHORIZATION)
    result = attribution.load_json(attribution.RESULT)
    seeds = attribution.material.seeds_f4(512, q=0.5)
    with h5py.File(attribution.LAB / attribution.TRACE, "r") as trace:
        trace_binding = json.loads(trace.attrs["binding"])
    attribution.validate_trace_binding(
        trace_binding, result["binding"], seeds,
        authorization["input_contract"]["source"]["sha256"],
    )


def test_pinned_trace_digest_rejects_a_changed_copy(tmp_path) -> None:
    changed_trace = tmp_path / "trace.h5"
    changed_trace.write_bytes(b"not the immutable r001 trace")
    with pytest.raises(ValueError, match="pinned attribution input"):
        attribution.validate_pinned_trace(changed_trace)


def test_trace_binding_rejects_changed_candidate_contract() -> None:
    authorization = attribution.load_json(attribution.AUTHORIZATION)
    result = attribution.load_json(attribution.RESULT)
    seeds = attribution.material.seeds_f4(512, q=0.5)
    altered = dict(result["binding"])
    altered["neighbours"] += 1
    with pytest.raises(ValueError, match="candidate contract"):
        attribution.validate_trace_binding(
            altered, altered, seeds,
            authorization["input_contract"]["source"]["sha256"],
        )


def test_trace_binding_rejects_disagreement_with_result_binding() -> None:
    authorization = attribution.load_json(attribution.AUTHORIZATION)
    result = attribution.load_json(attribution.RESULT)
    seeds = attribution.material.seeds_f4(512, q=0.5)
    altered_trace_binding = dict(result["binding"])
    altered_trace_binding["neighbours"] += 1
    with pytest.raises(ValueError, match="differs from the trace"):
        attribution.validate_trace_binding(
            altered_trace_binding, result["binding"], seeds,
            authorization["input_contract"]["source"]["sha256"],
        )


def test_acceptance_result_and_both_trace_frames_cross_validate() -> None:
    acceptance = attribution.load_json(attribution.ACCEPTANCE)
    result = attribution.load_json(attribution.RESULT)
    with h5py.File(attribution.LAB / attribution.TRACE, "r") as trace:
        trace_reliable = np.asarray(trace["reliable"][:], dtype=bool)
    attribution.validate_acceptance_result_trace(acceptance, result, trace_reliable, 512)

    altered_result = json.loads(json.dumps(result))
    altered_result["by_source"][0]["final_unknown_fraction"] = 0.0
    with pytest.raises(ValueError, match="acceptance, result, and both saved trace"):
        attribution.validate_acceptance_result_trace(acceptance, altered_result, trace_reliable, 512)


def test_trace_times_match_the_bound_native_frame_window() -> None:
    trace_path = attribution.LAB / attribution.TRACE
    authorization = attribution.load_json(attribution.AUTHORIZATION)
    source_path = attribution.LAB / authorization["input_contract"]["source"]["path"]
    with h5py.File(trace_path, "r") as trace, h5py.File(source_path, "r") as source:
        trace_times = np.asarray(trace["time"][:], dtype=np.float64)
        native_times = np.asarray(source["time"][40:42], dtype=np.float64)
    attribution.validate_trace_times(trace_times, native_times)
    shifted = trace_times.copy()
    shifted[1] += 1e-8
    with pytest.raises(ValueError, match="do not match native frame"):
        attribution.validate_trace_times(shifted, native_times)
