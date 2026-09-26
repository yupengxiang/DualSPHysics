from copy import deepcopy
import hashlib
import json

import pytest

from scripts import f4_tallwall120_pair_acceptance_v2 as acceptance


SOURCE_SHA256 = "a" * 64


def _cdf(*, lower=(0.0, 0.25, 0.5), upper=(0.0, 0.25, 0.5)):
    return {"x_s": [0.0, 1.0, 4.34], "lower": list(lower), "upper": list(upper)}


def _event_window():
    return {
        "normalization_T_s": 4.34,
        "nominal_horizon_s": 4.34,
        "actual_endpoint_s": 4.340002980805959,
        "native_output_interval_s": 0.004,
        "extension_count": 0,
        "initial_window_censored": False,
        "extension_reason": "not_needed",
        "complete": True,
        "right_censored": False,
        "post_return_follow_s": acceptance.GRAVITY_FOLLOW_S,
        "post_return_follow_complete": True,
    }


def _refresh_source_row(row, endpoint):
    records = {record["tracer_id"]: record for record in row["tracer_records"]}
    mass = row["initial_mass_kg"]
    row["unknown_fraction_max"] = sum(
        record["weight_kg"] for record in records.values() if record["unknown"]
    ) / mass
    cdfs = {}
    for event in ("contact", "upward", "return"):
        observed = [
            (record["event_times_s"][event], record["weight_kg"])
            for record in records.values()
            if record["event_times_s"][event] is not None
        ]
        unresolved = [
            (record["first_unreliable_time_s"], record["weight_kg"])
            for record in records.values()
            if record["unknown"]
            and record["event_times_s"][event] is None
            and record["first_unreliable_time_s"] is not None
        ]
        axis = sorted({0.0, endpoint, *(time for time, _ in observed), *(time for time, _ in unresolved)})
        lower = [sum(weight for time, weight in observed if time <= x) / mass for x in axis]
        upper = [
            lo + sum(weight for possible, weight in unresolved if possible <= x) / mass
            for x, lo in zip(axis, lower)
        ]
        cdfs[event] = {"x_s": axis, "lower": lower, "upper": upper}
    intervals = [record["residence_interval_s"] | {"weight_kg": record["weight_kg"]} for record in records.values()]
    axis = sorted({0.0, *(row["lower"] for row in intervals), *(row["upper"] for row in intervals)})
    cdfs["residence"] = {
        "x_s": axis,
        "lower": [sum(row["weight_kg"] for row in intervals if row["upper"] <= x) / mass for x in axis],
        "upper": [sum(row["weight_kg"] for row in intervals if row["lower"] <= x) / mass for x in axis],
    }
    row["cdf_bounds"] = cdfs
    row["residence_mean_s_bounds"] = {
        "lower": sum(row["weight_kg"] * row["lower"] for row in intervals) / mass,
        "upper": sum(row["weight_kg"] * row["upper"] for row in intervals) / mass,
    }


def _refresh_run(run):
    rows = run["source_denominator"]["source_rows"]
    for row in rows:
        _refresh_source_row(row, run["event_window"]["actual_endpoint_s"])
    seed_count = sum(len(row["tracer_records"]) for row in rows)
    coverage = run["output_manifest"]["body"]
    coverage["seed_count"] = seed_count
    coverage["expected_seed_count"] = seed_count
    _resign_manifest(run)
    _resign_summary(run)


def _tracer(tracer_id, weight, *, unknown=False, unreliable=None, events=None, errors=None, residence=(0.0, 0.0)):
    events = events or {name: None for name in acceptance._EVENTS}
    errors = errors or {name: None for name in acceptance._EVENTS}
    return {
        "tracer_id": tracer_id,
        "weight_kg": weight,
        "unknown": unknown,
        "first_unreliable_time_s": unreliable,
        "event_times_s": dict(events),
        "detection_error_bounds_s": dict(errors),
        "residence_interval_s": {"lower": residence[0], "upper": residence[1]},
    }


def _snapshot(tag, *, source_sha256=SOURCE_SHA256, event_window=None):
    event_window = event_window or _event_window()
    generation_sha = ("c" if tag == "candidate" else "e") * 64
    checkpoint_sha = ("d" if tag == "candidate" else "f") * 64
    trace_output_sha = ("1" if tag == "candidate" else "2") * 64
    source_row = {
        "source_id": "source-1",
        "initial_mass_kg": 1.0,
        "unknown_fraction_max": 0.005,
        "tracer_records": [
            {
                "tracer_id": "tracer-1", "weight_kg": 0.03, "unknown": False,
                "first_unreliable_time_s": None,
                "event_times_s": {"contact": 0.5, "upward": 0.7, "return": 1.0},
                "detection_error_bounds_s": {"contact": 0.001, "upward": 0.001, "return": 0.001},
                "residence_interval_s": {"lower": 0.1, "upper": 0.1},
            },
            {
                "tracer_id": "tracer-2", "weight_kg": 0.965, "unknown": False,
                "first_unreliable_time_s": None,
                "event_times_s": {"contact": None, "upward": None, "return": None},
                "detection_error_bounds_s": {"contact": None, "upward": None, "return": None},
                "residence_interval_s": {"lower": 0.0, "upper": 0.0},
            },
            {
                "tracer_id": "tracer-3", "weight_kg": 0.005, "unknown": True,
                "first_unreliable_time_s": 0.2,
                "event_times_s": {"contact": None, "upward": None, "return": None},
                "detection_error_bounds_s": {"contact": None, "upward": None, "return": None},
                "residence_interval_s": {"lower": 0.0, "upper": 0.1},
            },
        ],
        "cdf_bounds": {},
        "residence_mean_s_bounds": {"lower": 0.0, "upper": 0.0},
    }
    _refresh_source_row(source_row, event_window["actual_endpoint_s"])
    output_manifest_body = {
        "event_window": deepcopy(event_window),
        "artifact_hashes": {
            "generation": generation_sha,
            "checkpoint": checkpoint_sha,
            "trace_output": trace_output_sha,
        },
        "source_sha256": source_sha256,
        "complete": True,
        "frame_count": 1086,
        "expected_frame_count": 1086,
        "seed_count": 3,
        "expected_seed_count": 3,
        "time_start_s": 0.0,
        "time_end_s": 4.340002980805959,
        "native_output_interval_s": 0.004,
    }
    output_manifest_sha = hashlib.sha256(
        json.dumps(output_manifest_body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    run = {
        "identity": dict(acceptance.IDENTITY),
        "event_window": deepcopy(event_window),
        "source_sha256": source_sha256,
        "trace_output_sha256": trace_output_sha,
        "artifact_hashes": {
            "generation": {
                "schema": acceptance.GENERATION_SCHEMA,
                "sha256": generation_sha,
                "bound_sha256": generation_sha,
                "identity": dict(acceptance.IDENTITY),
            },
            "checkpoint": {
                "schema": acceptance.CHECKPOINT_SCHEMA,
                "sha256": checkpoint_sha,
                "bound_sha256": checkpoint_sha,
                "identity": dict(acceptance.IDENTITY),
            },
        },
        "output_manifest": {
            "schema": acceptance.OUTPUT_MANIFEST_SCHEMA,
            "identity": dict(acceptance.IDENTITY),
            "body": output_manifest_body,
            "body_sha256": output_manifest_sha,
            "bound_sha256": output_manifest_sha,
        },
        "summary_binding": {"body_sha256": "0" * 64, "bound_sha256": "0" * 64},
        "endpoint_max_error_m": 0.0,
        "saved_chord_crossings": 0,
        "source_denominator": {
            "denominator_policy": "all_initial_mass",
            "total_initial_mass_kg": 1.0,
            "source_rows": [source_row],
        },
    }
    _resign_summary(run)
    return run


def _payload():
    event_window = _event_window()
    return {
        "schema": acceptance.PAIR_SCHEMA,
        "policy_id": acceptance.POLICY_ID,
        "identity": dict(acceptance.IDENTITY),
        "diagnostic_only": True,
        "qualification_claim": "none",
        "credit": 0,
        "T2_macro": False,
        "T2_path": False,
        "event_window": event_window,
        "candidate": _snapshot("candidate", event_window=event_window),
        "reference": _snapshot("reference", event_window=event_window),
    }


def _external_artifacts(payload):
    return {
        side: {
            "generation": payload[side]["artifact_hashes"]["generation"]["sha256"],
            "checkpoint": payload[side]["artifact_hashes"]["checkpoint"]["sha256"],
            "trace_output": payload[side]["trace_output_sha256"],
            "output_manifest": payload[side]["output_manifest"]["body_sha256"],
            "summary": payload[side]["summary_binding"]["body_sha256"],
        }
        for side in ("candidate", "reference")
    }


def _resign_manifest(run):
    body = run["output_manifest"]["body"]
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    run["output_manifest"]["body_sha256"] = digest
    run["output_manifest"]["bound_sha256"] = digest


def _resign_summary(run):
    body = {
        "identity": run["identity"],
        "source_sha256": run["source_sha256"],
        "event_window": run["event_window"],
        "artifact_bindings": {
            "generation": run["artifact_hashes"]["generation"]["sha256"],
            "checkpoint": run["artifact_hashes"]["checkpoint"]["sha256"],
            "trace_output": run["trace_output_sha256"],
            "output_manifest": run["output_manifest"]["body_sha256"],
        },
        "endpoint_max_error_m": run["endpoint_max_error_m"],
        "saved_chord_crossings": run["saved_chord_crossings"],
        "source_denominator": run["source_denominator"],
    }
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    run["summary_binding"] = {"body_sha256": digest, "bound_sha256": digest}


def _run(payload, *, source_sha256=SOURCE_SHA256, artifact_bindings=None):
    payload = deepcopy(payload)
    for side in ("candidate", "reference"):
        _resign_summary(payload[side])
    if artifact_bindings is None:
        artifact_bindings = _external_artifacts(payload)
    return acceptance.evaluate_f4_tallwall120_pair(
        payload,
        externally_bound_source_sha256=source_sha256,
        externally_bound_artifact_sha256=artifact_bindings,
    )


def test_pair_diagnostic_passes_proposed_gates_without_qualification_or_mutation():
    payload = _payload()
    before = deepcopy(payload)
    result = _run(payload)
    assert payload == before
    assert result["passed"] is True
    assert result["policy_status"] == "proposed_not_registered"
    assert result["policy"]["qualification_authority"] is False
    assert result["qualification_claim"] == "none"
    assert result["credit"] == 0
    assert result["T2_macro"] is False and result["T2_path"] is False
    assert result["comparisons"]["maximum_event_mae_s"] == pytest.approx(0.0)
    assert result["comparisons"]["maximum_pairwise_detection_error_sum_s"] == pytest.approx(0.002)


def test_f4_identity_is_fixed_to_active_tallwall120_recipe():
    payload = _payload()
    payload["identity"]["scope_id"] = "F4_drop_resting_pool_x_v2"
    result = _run(payload)
    assert result["passed"] is False
    assert result["failure_reasons"] == ["structural_validation"]
    assert "active F4 tallwall120 scope" in result["blocking_reasons"][0]


def test_external_source_sha_is_required_and_bound_to_both_snapshots():
    payload = _payload()
    missing = acceptance.evaluate_f4_tallwall120_pair(payload)
    assert missing["failure_reasons"] == ["structural_validation"]
    mismatch = _run(payload, source_sha256="b" * 64)
    assert mismatch["failure_reasons"] == ["structural_validation"]
    payload["candidate"]["source_sha256"] = "b" * 64
    bound_output = _run(payload)
    assert bound_output["failure_reasons"] == ["structural_validation"]


def test_artifact_hash_and_identity_bindings_fail_closed():
    payload = _payload()
    payload["candidate"]["artifact_hashes"]["generation"]["bound_sha256"] = "0" * 64
    result = _run(payload)
    assert result["failure_reasons"] == ["structural_validation"]
    payload = _payload()
    external = _external_artifacts(payload)
    external["candidate"]["generation"] = "0" * 64
    result = _run(payload, artifact_bindings=external)
    assert result["failure_reasons"] == ["structural_validation"]
    payload = _payload()
    external = _external_artifacts(payload)
    payload["reference"]["trace_output_sha256"] = "0" * 64
    result = _run(payload, artifact_bindings=external)
    assert result["failure_reasons"] == ["structural_validation"]
    payload = _payload()
    payload["reference"]["artifact_hashes"]["checkpoint"]["identity"]["recipe_id"] = "other"
    result = _run(payload)
    assert result["failure_reasons"] == ["structural_validation"]


def test_summary_digest_closes_over_artifact_hashes_and_manifest_digest():
    payload = _payload()
    candidate = payload["candidate"]
    replacement = "9" * 64
    candidate["artifact_hashes"]["generation"]["sha256"] = replacement
    candidate["artifact_hashes"]["generation"]["bound_sha256"] = replacement
    candidate["output_manifest"]["body"]["artifact_hashes"]["generation"] = replacement
    _resign_manifest(candidate)
    bindings = _external_artifacts(payload)
    result = acceptance.evaluate_f4_tallwall120_pair(
        payload,
        externally_bound_source_sha256=SOURCE_SHA256,
        externally_bound_artifact_sha256=bindings,
    )
    assert result["failure_reasons"] == ["structural_validation"]
    assert "canonical diagnostic-summary SHA-256 binding mismatch" in result["blocking_reasons"][0]


@pytest.mark.parametrize("mutated_field", ("tracer_records", "cdf_bounds", "residence_mean_s_bounds"))
def test_frozen_external_summary_binding_rejects_metric_mutation(mutated_field):
    payload = _payload()
    bindings = _external_artifacts(payload)
    row = payload["candidate"]["source_denominator"]["source_rows"][0]
    if mutated_field == "tracer_records":
        row["tracer_records"][0]["weight_kg"] = 0.04
    elif mutated_field == "cdf_bounds":
        row["cdf_bounds"]["contact"]["lower"][-1] = 0.04
    else:
        row["residence_mean_s_bounds"]["lower"] = 0.004
    result = acceptance.evaluate_f4_tallwall120_pair(
        payload,
        externally_bound_source_sha256=SOURCE_SHA256,
        externally_bound_artifact_sha256=bindings,
    )
    assert result["failure_reasons"] == ["structural_validation"]
    assert "canonical diagnostic-summary SHA-256 binding mismatch" in result["blocking_reasons"][0]


def test_output_coverage_and_source_denominator_are_gates():
    payload = _payload()
    candidate = payload["candidate"]
    candidate["output_manifest"]["body"]["complete"] = False
    records = candidate["source_denominator"]["source_rows"][0]["tracer_records"]
    records[1]["weight_kg"] = 0.95
    records[2]["weight_kg"] = 0.02
    _refresh_run(candidate)
    result = _run(payload)
    assert result["passed"] is False
    assert result["gates"]["output_coverage"] is False
    assert result["gates"]["unknown_bound"] is False
    assert result["credit"] == 0


def test_external_output_manifest_digest_binds_coverage_body():
    payload = _payload()
    external = _external_artifacts(payload)
    payload["candidate"]["output_manifest"]["body"]["seed_count"] = 9
    _resign_manifest(payload["candidate"])
    result = _run(payload, artifact_bindings=external)
    assert result["failure_reasons"] == ["structural_validation"]


def test_expected_frame_count_must_be_reachable_from_event_horizon():
    payload = _payload()
    body = payload["candidate"]["output_manifest"]["body"]
    body.update(frame_count=1087, expected_frame_count=1087)
    _resign_manifest(payload["candidate"])
    result = _run(payload)
    assert result["failure_reasons"] == ["structural_validation"]
    assert "not reachable" in result["blocking_reasons"][0]


def test_declared_endpoint_must_be_reachable_on_uniform_output_cadence():
    payload = _payload()
    payload["event_window"]["native_output_interval_s"] = 1.0
    for run in (payload["candidate"], payload["reference"]):
        run["event_window"] = deepcopy(payload["event_window"])
        run["output_manifest"]["body"].update(
            event_window=deepcopy(payload["event_window"]),
            frame_count=5, expected_frame_count=5, native_output_interval_s=1.0,
        )
        _resign_manifest(run)
    result = _run(payload)
    assert result["failure_reasons"] == ["structural_validation"]
    assert "output frame count/endpoint is not reachable" in result["blocking_reasons"][0]


def test_right_censor_and_completion_claims_are_bound_by_output_manifest():
    payload = _payload()
    payload["event_window"]["right_censored"] = True
    result = _run(payload)
    assert result["failure_reasons"] == ["structural_validation"]
    assert "event window is not bound" in result["blocking_reasons"][0]


def test_cdf_uses_worst_case_interval_gap_on_union_of_right_continuous_axes():
    payload = _payload()
    candidate = payload["candidate"]["source_denominator"]["source_rows"][0]["tracer_records"][0]
    reference = payload["reference"]["source_denominator"]["source_rows"][0]["tracer_records"][0]
    candidate["event_times_s"]["return"] = 1.0
    reference["event_times_s"]["return"] = 2.0
    _refresh_run(payload["candidate"])
    _refresh_run(payload["reference"])
    result = _run(payload)
    assert result["gates"]["cdf_gap"] is False
    assert result["comparisons"]["cdf_gap_by_source_event"]["source-1"]["return"] == pytest.approx(0.035)


def test_cdf_uses_right_value_when_both_curves_jump_at_the_same_knot():
    left = {"x_s": [0.0, 1.0, 4.34], "lower": [0.0, 0.2, 0.2], "upper": [0.0, 0.2, 0.2]}
    right = {"x_s": [0.0, 1.0, 4.34], "lower": [0.0, 0.7, 0.7], "upper": [0.0, 0.7, 0.7]}
    assert acceptance._cdf_gap(left, right, 4.34) == pytest.approx(0.5)


def test_residence_error_is_conservative_gap_between_all_mass_mean_intervals():
    payload = _payload()
    candidate_records = payload["candidate"]["source_denominator"]["source_rows"][0]["tracer_records"]
    candidate_records[1]["residence_interval_s"] = {"lower": 0.5, "upper": 0.5}
    _refresh_run(payload["candidate"])
    result = _run(payload)
    assert result["gates"]["residence_mean_gap"] is False
    assert result["comparisons"]["maximum_residence_mean_interval_gap_s"] == pytest.approx(0.483)


def test_cdf_and_residence_summaries_match_canonical_per_tracer_records():
    payload = _payload()
    candidate_row = payload["candidate"]["source_denominator"]["source_rows"][0]
    candidate_row["cdf_bounds"]["return"]["lower"][1] = 0.0
    candidate_row["cdf_bounds"]["return"]["upper"][1] = 0.02
    result = _run(payload)
    assert result["failure_reasons"] == ["structural_validation"]
    assert "does not match the canonical per-tracer records" in result["blocking_reasons"][0]

    payload = _payload()
    candidate_row = payload["candidate"]["source_denominator"]["source_rows"][0]
    candidate_row["residence_mean_s_bounds"] = {"lower": 0.0, "upper": 0.1}
    result = _run(payload)
    assert result["failure_reasons"] == ["structural_validation"]
    assert "residence mean bounds do not match" in result["blocking_reasons"][0]

    payload = _payload()
    candidate_row = payload["candidate"]["source_denominator"]["source_rows"][0]
    candidate_row["tracer_records"][0]["residence_interval_s"] = {"lower": 5.0, "upper": 5.01}
    _refresh_run(payload["candidate"])
    result = _run(payload)
    assert result["failure_reasons"] == ["structural_validation"]
    assert "residence upper_s must be <=" in result["blocking_reasons"][0]


def test_event_sample_ancestry_and_contact_upward_return_order_are_enforced():
    payload = _payload()
    record = payload["candidate"]["source_denominator"]["source_rows"][0]["tracer_records"][0]
    record["event_times_s"]["return"] = 0.6
    _refresh_run(payload["candidate"])
    result = _run(payload)
    assert result["failure_reasons"] == ["structural_validation"]
    assert "upward/return event samples violate physical event order" in result["blocking_reasons"][0]


def test_unknown_tracers_need_a_reliability_boundary_and_events_after_it_are_rejected():
    payload = _payload()
    unknown = payload["candidate"]["source_denominator"]["source_rows"][0]["tracer_records"][2]
    unknown["first_unreliable_time_s"] = None
    _refresh_run(payload["candidate"])
    result = _run(payload)
    assert result["failure_reasons"] == ["structural_validation"]
    assert "unknown tracer must declare its first_unreliable_time_s" in result["blocking_reasons"][0]

    payload = _payload()
    unknown = payload["candidate"]["source_denominator"]["source_rows"][0]["tracer_records"][2]
    unknown["event_times_s"]["contact"] = 0.3
    unknown["detection_error_bounds_s"]["contact"] = 0.001
    _refresh_run(payload["candidate"])
    result = _run(payload)
    assert result["failure_reasons"] == ["structural_validation"]
    assert "observed event occurs after the tracer first became unreliable" in result["blocking_reasons"][0]


def test_event_time_mae_is_weighted_over_common_ids_and_detection_budget_is_max_pair_sum():
    payload = _payload()
    for side, contact, error in (("candidate", 0.2, 0.001), ("reference", 0.21, 0.002)):
        row = payload[side]["source_denominator"]["source_rows"][0]
        row["tracer_records"][1]["weight_kg"] = 0.715
        row["tracer_records"].append(_tracer(
            "tracer-4", 0.25,
            events={"contact": contact, "upward": None, "return": None},
            errors={"contact": error, "upward": None, "return": None},
        ))
        _refresh_run(payload[side])
    result = _run(payload)
    event_result = result["comparisons"]["event_mae_by_source_event"]["source-1"]["contact"]
    detection_result = result["comparisons"]["event_detection_error_by_source_event"]["source-1"]["contact"]
    assert event_result["value_s"] == pytest.approx(0.25 * 0.01 / 0.28)
    assert event_result["common_event_mass_fraction"] == pytest.approx(0.28)
    assert detection_result["maximum_pairwise_sum_s"] == pytest.approx(0.003)
    assert result["gates"]["event_detection_error"] is False


def test_no_common_observed_events_are_null_not_zero_and_block_timing_gate():
    payload = _payload()
    reference_record = payload["reference"]["source_denominator"]["source_rows"][0]["tracer_records"][0]
    reference_record["event_times_s"] = {event: None for event in acceptance._EVENTS}
    reference_record["detection_error_bounds_s"] = {event: None for event in acceptance._EVENTS}
    _refresh_run(payload["reference"])
    result = _run(payload)
    assert result["passed"] is False
    assert result["comparisons"]["maximum_event_mae_s"] is None
    assert result["comparisons"]["any_common_observed_event"] is False
    assert result["comparisons"]["event_mae_by_source_event"]["source-1"]["contact"]["status"] == "not_applicable"
    assert result["gates"]["event_time_mae"] is False
    assert result["gates"]["event_detection_error"] is False


def test_one_missing_source_event_pair_blocks_aggregate_timing_gates():
    payload = _payload()
    row = payload["reference"]["source_denominator"]["source_rows"][0]
    row["tracer_records"][0]["event_times_s"]["return"] = None
    row["tracer_records"][0]["detection_error_bounds_s"]["return"] = None
    _refresh_run(payload["reference"])
    result = _run(payload)
    comparisons = result["comparisons"]
    assert comparisons["event_mae_by_source_event"]["source-1"]["return"]["status"] == "not_applicable"
    assert comparisons["event_mae_by_source_event"]["source-1"]["return"]["value_s"] is None
    assert comparisons["maximum_event_mae_s"] is None
    assert comparisons["maximum_pairwise_detection_error_sum_s"] is None
    assert result["gates"]["event_time_mae"] is False
    assert result["gates"]["event_detection_error"] is False


def test_partial_tracer_id_intersection_is_not_silently_scored_as_complete_pairing():
    payload = _payload()
    for side in ("candidate", "reference"):
        row = payload[side]["source_denominator"]["source_rows"][0]
        row["tracer_records"][1]["weight_kg"] = 0.25
        row["tracer_records"].append(_tracer("tracer-4", 0.25))
        row["tracer_records"].append(_tracer("tracer-5", 0.465))
    candidate = payload["candidate"]["source_denominator"]["source_rows"][0]
    reference = payload["reference"]["source_denominator"]["source_rows"][0]
    candidate["tracer_records"][1]["event_times_s"]["contact"] = 0.3
    candidate["tracer_records"][1]["detection_error_bounds_s"]["contact"] = 0.001
    reference["tracer_records"][3]["event_times_s"]["contact"] = 0.4
    reference["tracer_records"][3]["detection_error_bounds_s"]["contact"] = 0.001
    _refresh_run(payload["candidate"])
    _refresh_run(payload["reference"])
    result = _run(payload)
    contact = result["comparisons"]["event_mae_by_source_event"]["source-1"]["contact"]
    assert contact["status"] == "incomplete_pairing"
    assert contact["value_s"] is None
    assert contact["common_event_mass_kg"] == pytest.approx(0.03)
    assert contact["candidate_unpaired_mass_kg"] == 0.25
    assert contact["reference_unpaired_mass_kg"] == 0.25
    assert result["comparisons"]["maximum_event_mae_s"] is None
    assert result["gates"]["event_time_mae"] is False
    assert result["gates"]["event_detection_error"] is False


def test_single_extended_window_keeps_T_normalization_and_gravity_follow_separate():
    payload = _payload()
    payload["event_window"].update({
        "nominal_horizon_s": 8.68,
        "actual_endpoint_s": 8.680002980805959,
        "extension_count": 1,
        "initial_window_censored": True,
        "extension_reason": "right_censor_at_initial_horizon",
    })
    for run in (payload["candidate"], payload["reference"]):
        run["output_manifest"]["body"].update(
            frame_count=2171, expected_frame_count=2171, time_end_s=8.680002980805959
        )
        run["event_window"] = deepcopy(payload["event_window"])
        run["output_manifest"]["body"]["event_window"] = deepcopy(payload["event_window"])
        _refresh_run(run)
    result = _run(payload)
    assert result["policy"]["normalization_T_s"] == 4.34
    assert result["event_window"]["nominal_horizon_s"] == 8.68
    assert result["policy"]["event_window_max_s"] == 8.68
    assert result["policy"]["residence_mean_interval_gap_limit_s"] == 0.0868
    assert result["policy"]["event_mae_limit_s"] == 0.01085
    assert result["policy"]["pairwise_detection_error_budget_s"] == 0.00217
    payload["event_window"]["extension_count"] = 2
    invalid = _run(payload)
    assert invalid["failure_reasons"] == ["structural_validation"]


def test_event_and_wall_tolerance_failures_do_not_change_diagnostic_status():
    payload = _payload()
    payload["candidate"]["endpoint_max_error_m"] = 2.0e-8
    payload["reference"]["saved_chord_crossings"] = 1
    payload["reference"]["source_denominator"]["source_rows"][0]["tracer_records"][0]["detection_error_bounds_s"]["return"] = 0.01
    _refresh_run(payload["reference"])
    result = _run(payload)
    assert result["gates"]["endpoint_tolerance"] is False
    assert result["gates"]["saved_chord_tolerance"] is False
    assert result["gates"]["event_detection_error"] is False
    assert result["qualification_claim"] == "none"
    assert result["credit"] == 0
