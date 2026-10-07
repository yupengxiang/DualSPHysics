"""Manufactured checks for the v6 observer and v4 adapter."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ds_data02_stage2_observer_v6 import (  # noqa: E402
    ObserverBindingError,
    adapt_v4_label_payload,
    classify_first_passage_v6,
    manufactured_observer_calibration,
    observe_point_cloud,
    validate_observer_config,
)


def _config() -> dict:
    return {
        "schema": "ds02.stage2.reference-observer-config.v1",
        "physical_case_id": "manufactured",
        "source_binding": {"scan_path": "/tmp/scan.json", "scan_sha256": "a" * 64},
        "time_window_s": [0.0, 4.0],
        "control_duration_s": 0.9,
        "query_times_s": [0.0, 0.9, 2.0, 4.0],
        "fixed_physical_scales": {"position_scale_m": 2.0, "mass_scale_m": 2.0,
                                  "feature_time_s": 4.0},
        "mass_quantiles": [0.5, 0.75, 1.0],
        "mass_distribution": {"normalized_bin_edges": [-0.25, 0.25, 0.75, 1.25]},
        "cross_grid_policy": {"identity_binding": "source_region_and_mass_distribution"},
        "tolerance_profile": {"schema": "frozen", "mutable": False,
                               "manufactured_absolute": 1e-12},
    }


def test_v6_first_passage_rejects_wrong_time_and_candidate_order_and_marks_same_bracket_ambiguous():
    with pytest.raises(ObserverBindingError, match="earliest crossing candidate"):
        classify_first_passage_v6(saved_brackets=[[0.0, 1.0]], crossing_times_s=[0.2], event_time_s=0.3)
    with pytest.raises(ObserverBindingError, match="chronological"):
        classify_first_passage_v6(saved_brackets=[[0.0, 1.0]], crossing_times_s=[0.8, 0.2])
    ambiguous = classify_first_passage_v6(saved_brackets=[[0.0, 1.0], [2.0, 3.0]],
                                          crossing_times_s=[0.2, 0.8, 2.2])
    assert ambiguous["status"] == "ambiguous_multiple_crossing"
    assert ambiguous["event_time_s"] is None


def test_v4_adapter_preserves_binary_limit_and_uses_auxiliary_states_when_bound():
    payload = {
        "schema": "ds02.stage2.observation-labels.v2",
        "first_passage_censor": [0, 1, 1, 1, 1],
        "first_passage_interval": [
            [[0.0, 1.0]], [[0.0, 1.0]], [[0.0, 1.0]], [[0.0, 1.0]], [[0.0, 1.0]],
        ],
        "first_passage_chord_time": [0.5, float("nan"), float("nan"), float("nan"), float("nan")],
        "crossing_count": [1, 0, 2, 0, 0],
    }
    partial = adapt_v4_label_payload(payload)
    assert [row["status"] for row in partial["records"]] == [
        "observed", "right_censored", "ambiguous_multiple_crossing", "right_censored", "right_censored"]
    assert partial["adapter_status"].startswith("PARTIAL_")
    complete = adapt_v4_label_payload(
        payload,
        initial_inside=[False, False, False, True, False],
        failed_before_observation=[False, False, False, False, True],
    )
    assert [row["status"] for row in complete["records"]] == [
        "observed", "right_censored", "ambiguous_multiple_crossing", "initially_inside", "failed_before_observation"]
    assert complete["adapter_status"] == "COMPLETE_DEVELOPMENT_ADAPTER"


def test_manufactured_observer_has_hand_expected_mass_weighted_values_and_no_ids():
    config = _config()
    assert validate_observer_config(config)["_validated_bin_edges"] == [-0.25, 0.25, 0.75, 1.25]
    calibration = manufactured_observer_calibration(config)
    assert calibration["status"] == "PASS_MANUFACTURED_OBSERVER"
    observed = observe_point_cloud(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]],
        [1.0, 2.0, 1.0],
        [[1.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 3.0]],
        axis=0, quantiles=[0.5, 0.75, 1.0], physical_scale_m=2.0,
        normalized_bin_edges=[-0.25, 0.25, 0.75, 1.25], missing_mass_kg=0.5)
    assert observed["mass_weighted_com_m"] == [1.0, 0.0, 0.0]
    assert observed["mass_weighted_kinetic_energy_J"] == 9.0
    assert observed["mass_distribution_missing_bucket_kg"] == 0.5
    assert observed["identity_binding"].endswith("no particle IDs")


def test_frozen_observer_rejects_mutable_tolerance_and_wrong_query_shape():
    config = _config()
    config["tolerance_profile"]["mutable"] = True
    with pytest.raises(ObserverBindingError, match="frozen"):
        validate_observer_config(config)
    config = _config()
    with pytest.raises(ObserverBindingError, match="query_times_s"):
        config["query_times_s"] = [0.0, 0.9, 4.1]
        validate_observer_config(config)
