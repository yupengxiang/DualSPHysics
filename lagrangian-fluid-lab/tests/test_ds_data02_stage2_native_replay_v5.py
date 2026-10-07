"""Manufactured checks for the v5 native replay and manual evaluator APIs."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ds_data02_stage2_native_replay_v5 import (  # noqa: E402
    FIRST_PASSAGE_STATUSES,
    NativeReplayBindingError,
    classify_first_passage,
    evaluate_manual_predictions,
    read_initial_frame,
)


def _bindings() -> dict[str, str]:
    return {
        "catalog_sha256": "a" * 64,
        "case_row_sha256": "b" * 64,
        "source_hdf5_sha256": "c" * 64,
        "operator_config_sha256": "d" * 64,
    }


def _manual_bundles() -> tuple[dict, dict]:
    bindings = _bindings()
    reference = {
        "schema": "ds02.stage2.manual-observation-reference.v1",
        "bindings": bindings,
        "macros": {
            "com_x": {"kind": "position", "reference_scale": 1.0,
                      "values": [0.0, 0.1, 0.2]},
            "source_to_target": {"kind": "mass_fraction", "reference_scale": 1.0,
                                  "values": [0.0, 0.25, 0.5]},
        },
        "events": [
            {"event_id": "e-observed", "zone": 0, "idp": 10, "status": "observed",
             "event_time_s": 0.5, "feature_time_s": 1.0,
             "event_time_interval_s": [0.0, 1.0], "saved_brackets": [[0.0, 1.0]]},
            {"event_id": "e-right", "zone": 0, "idp": 11, "status": "right_censored",
             "event_time_s": None, "saved_brackets": [[0.0, 1.0]]},
            {"event_id": "e-failed", "zone": 0, "idp": 12, "status": "failed_before_observation",
             "event_time_s": None, "saved_brackets": [[1.0, 2.0]]},
            {"event_id": "e-inside", "zone": 0, "idp": 13, "status": "initially_inside",
             "event_time_s": None, "saved_brackets": []},
            {"event_id": "e-ambiguous", "zone": 0, "idp": 14,
             "status": "ambiguous_multiple_crossing", "event_time_s": None,
             "saved_brackets": [[1.0, 2.0], [1.0, 2.0]]},
        ],
    }
    prediction = {
        "schema": "ds02.stage2.manual-observation-predictions.v1",
        "bindings": dict(bindings),
        "macros": {"com_x": [0.0, 0.1, 0.2], "source_to_target": [0.0, 0.25, 0.5]},
        "events": [dict(event) for event in reference["events"]],
    }
    return reference, prediction


def test_first_passage_has_five_states_and_retains_brackets():
    observed = classify_first_passage(saved_brackets=[[1.0, 2.0]],
                                      crossing_times_s=[1.5], event_time_s=1.5)
    assert observed["status"] == "observed"
    assert observed["event_time_interval_s"] == [1.0, 2.0]

    right = classify_first_passage(saved_brackets=[[1.0, 2.0]])
    failed = classify_first_passage(saved_brackets=[[1.0, 2.0]], failed_before_observation=True)
    inside = classify_first_passage(initially_inside=True)
    ambiguous = classify_first_passage(saved_brackets=[[1.0, 2.0], [1.0, 2.0]],
                                       ambiguous_multiple_crossing=True)
    assert [item["status"] for item in (observed, right, failed, inside, ambiguous)] == list(FIRST_PASSAGE_STATUSES)
    assert all(item["event_time_s"] is None for item in (right, failed, inside, ambiguous))
    assert ambiguous["hidden_recross_status"] == "UNRESOLVED"
    with pytest.raises(NativeReplayBindingError, match="must not carry"):
        classify_first_passage(saved_brackets=[[0.0, 1.0]], event_time_s=0.0)


def test_manual_evaluator_scores_macro_and_all_event_states_without_model():
    reference, prediction = _manual_bundles()
    report = evaluate_manual_predictions(reference, prediction)
    assert report["status"] == "PASS_DEVELOPMENT_OBSERVABLES"
    assert report["failures"] == []
    assert report["model_invoked"] is False
    assert report["quality"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    assert {record["expected_status"] for record in report["event_checks"]} == set(FIRST_PASSAGE_STATUSES)


def test_manual_evaluator_rejects_wrong_source_identity_and_time_interpolation():
    reference, prediction = _manual_bundles()
    prediction["bindings"]["source_hdf5_sha256"] = "e" * 64
    prediction["events"][0]["event_time_s"] = 0.51
    report = evaluate_manual_predictions(reference, prediction)
    assert report["status"] == "FAIL_DEVELOPMENT_OBSERVABLES"
    assert "binding.source_hdf5_sha256" in report["failures"]
    assert any(name.endswith(".time") for name in report["failures"])


def test_initial_frame_reader_requires_parent_io_slot_before_hdf5_access():
    with pytest.raises(NativeReplayBindingError, match="explicit parent stage2guard I/O slot"):
        read_initial_frame(None)  # type: ignore[arg-type]
