import numpy as np
import pytest
from scripts.core_evaluation import (
    aggregate_cases,
    bootstrap_case_interval,
    score_case,
    select_checkpoint,
    summarize_case_scores,
)


def score(x, v=None, **kwargs):
    return score_case(x, x if v is None else v, expected_frames=4, length_m=1, speed_mps=1, **kwargs)


def test_failures_keep_registered_denominator_and_raw_errors():
    assert score([0, 0])["selection_score"] == .5
    result = score([0, np.nan, 0, 0])
    assert result["selection_score"] == .75
    assert result["finite_prefix_frames"] == 1
    assert result["failure_category"] == "nonfinite_state"
    assert score([10] * 4)["raw_position_rmse_frame_mean_m"] == 10
    assert score([10] * 4)["selection_score"] == 1
    assert score([], executed=False)["selection_score"] == 1


def test_unexecuted_setup_failure_keeps_explicit_frame_denominator():
    # Setup failures retain one missing marker per future frame.  The
    # evaluator must score that row as a fixed all-penalty denominator while
    # rejecting any finite values attached to an unexecuted case.
    result = score([None] * 4, [None] * 4, executed=False,
                   failure_category="rollout_setup_error")
    assert result["expected_frames"] == 4
    assert result["finite_prefix_frames"] == 0
    assert result["selection_score"] == 1.0
    assert result["failure_category"] == "rollout_setup_error"
    with pytest.raises(ValueError, match="cannot contain predictions"):
        score([0.0] * 4, [0.0] * 4, executed=False)


def test_fixed_denominator_rejects_non_integer_frame_counts():
    for invalid in (4.0, np.float64(4.0), True):
        with pytest.raises(ValueError, match="expected_frames"):
            score_case([0.0] * 4, [0.0] * 4, expected_frames=invalid,
                       length_m=1.0, speed_mps=1.0)


def test_family_macro_and_missing_execution():
    result = aggregate_cases({"a": "F1", "b": "F1", "c": "F3"},
                             {"a": score([0]*4), "b": score([0]*4)})
    assert result["selection_score"] == .5
    assert result["complete_fraction"] == .5
    assert result["missing_execution"] == 1
    assert summarize_case_scores({"a": "F1", "b": "F1", "c": "F3"},
                                 {"a": score([0]*4), "b": score([0]*4)}) == result


def test_summary_rejects_nonfinite_or_favorable_unexecuted_score():
    invalid = score([0] * 4)
    invalid["selection_score"] = np.nan
    with pytest.raises(ValueError, match="selection_score"):
        aggregate_cases({"a": "F1"}, {"a": invalid})

    invalid = score([None] * 4, executed=False)
    invalid["selection_score"] = 0.0
    with pytest.raises(ValueError, match="fixed penalty"):
        aggregate_cases({"a": "F1"}, {"a": invalid})


def test_selection_prioritizes_completion_and_rejects_test_data():
    def candidate(update, complete, error):
        return {"update": update, "split": "validation", "metrics": {
            "families": {"F1": {"case_count": 4, "complete_fraction": complete,
                                  "selection_score": error, "missing_execution": 0}},
            "registered_cases": 4, "complete_fraction": complete,
            "selection_score": error, "missing_execution": 0}}
    first = candidate(8000, 1, .3)
    rest = [candidate(24000, .8, .1), candidate(32000, .8, .1)]
    assert select_checkpoint([candidate(16000, .9, .1), first, *rest]) == first
    assert select_checkpoint([candidate(16000, 1, .3), first, *rest]) == first
    with pytest.raises(ValueError):
        select_checkpoint([first])
    bad = candidate(32000, 1, 0)
    bad["split"] = "test"
    with pytest.raises(ValueError):
        select_checkpoint([bad])
    bad = candidate(32000, 1, 0)
    bad["test_included"] = True
    with pytest.raises(ValueError, match="test data"):
        select_checkpoint([candidate(8000, 1, .3), candidate(16000, 1, .3),
                           candidate(24000, 1, .3), bad])


def test_selector_rejects_fractional_updates_and_denominator_tampering():
    def candidate(update):
        return {"update": update, "split": "validation", "metrics": {
            "families": {"F1": {"case_count": 4, "complete_fraction": 1.0,
                                  "selection_score": 0.1, "missing_execution": 0}},
            "registered_cases": 4, "complete_fraction": 1.0,
            "selection_score": 0.1, "missing_execution": 0}}

    rows = [candidate(update) for update in (8000, 16000, 24000, 32000)]
    rows[0]["update"] = 8000.0
    with pytest.raises(ValueError, match="integer"):
        select_checkpoint(rows)

    rows = [candidate(update) for update in (8000, 16000, 24000, 32000)]
    rows[1]["metrics"]["registered_cases"] = 3
    with pytest.raises(ValueError, match="denominator"):
        select_checkpoint(rows)

    rows = [candidate(update) for update in (8000, 16000, 24000, 32000)]
    rows[2]["metrics"]["missing_execution"] = -1
    with pytest.raises(ValueError, match="integer"):
        select_checkpoint(rows)


def test_bootstrap_does_not_treat_derived_views_as_independent_cases():
    registry = {"a": "F1", "b": "F1"}
    results = {"a": score([0]*4), "b": score([1]*4)}
    baseline = bootstrap_case_interval(registry, results, physical_case_ids={"a":"p1", "b":"p2"})
    registry["a_crop"] = "F1"
    results["a_crop"] = results["a"]
    derived = bootstrap_case_interval(registry, results, physical_case_ids={"a":"p1", "a_crop":"p1", "b":"p2"})
    assert derived["independent_cases_by_family"] == {"F1":2}
    assert (derived["lower"], derived["upper"]) == (baseline["lower"], baseline["upper"])


def test_bootstrap_rejects_fake_draw_counts_and_cross_family_clusters():
    registry = {"a": "F1", "b": "F2"}
    results = {"a": score([0] * 4), "b": score([1] * 4)}
    with pytest.raises(ValueError, match="draws"):
        bootstrap_case_interval(registry, results,
                                physical_case_ids={"a": "p1", "b": "p2"}, draws=2.5)
    with pytest.raises(ValueError, match="multiple mechanism families"):
        bootstrap_case_interval(registry, results,
                                physical_case_ids={"a": "same", "b": "same"})
