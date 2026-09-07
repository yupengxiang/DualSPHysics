import numpy as np
import pytest

from scripts.protocol_metrics import (
    first_passage_metrics,
    mass_fraction_tv,
    trajectory_metrics,
    validate_affine_transforms,
    validate_split_lineage,
)


def test_corresponded_trajectory_metrics_obey_valid_mask():
    ref = np.zeros((2, 2, 3))
    pred = ref.copy()
    pred[1, 0, 0] = 0.2
    pred[1, 1] = np.nan
    valid = np.asarray([[1, 1], [1, 0]], dtype=bool)
    result = trajectory_metrics(ref, pred, valid, dp=0.1)
    assert result["fde_m"] == pytest.approx(0.2)
    assert result["position_rmse_over_dp"] == pytest.approx(np.sqrt(4 / 3))


def test_mass_tv_requires_explicit_closure_categories():
    assert mass_fraction_tv({"a": 0.7, "loss": 0.3}, {"a": 0.6, "loss": 0.4}) == pytest.approx(0.1)
    with pytest.raises(ValueError):
        mass_fraction_tv({"a": 0.7, "loss": 0.3}, {"a": 1.2})
    with pytest.raises(ValueError):
        mass_fraction_tv({"a": -0.1, "loss": 1.1}, {"a": -0.1, "loss": 1.1})
    with pytest.raises(ValueError):
        mass_fraction_tv({"a": 0.7, "loss": 0.3}, {"a": np.nan, "loss": np.nan})


def test_first_passage_scores_event_and_time_separately():
    result = first_passage_metrics([1.0, np.nan, 2.0], [1.2, np.nan, np.nan])
    assert result["event_classification_accuracy"] == pytest.approx(2 / 3)
    assert result["time_mae_s"] == pytest.approx(0.2)


def test_lineage_cannot_cross_splits():
    with pytest.raises(ValueError):
        validate_split_lineage([
            {"lineage_group_id": "a", "split": "train"},
            {"lineage_group_id": "a", "split": "test"},
        ])


def test_physical_case_cannot_cross_splits_even_with_different_lineage_labels():
    with pytest.raises(ValueError, match="physical case crosses splits"):
        validate_split_lineage([
            {"physical_case_id": "case-a", "lineage_group_id": "lineage-train", "split": "train"},
            {"physical_case_id": "case-a", "lineage_group_id": "lineage-test", "split": "test"},
        ])


def test_paired_background_may_be_reused_across_controlled_splits():
    # A fixed nuisance/background context is deliberately shared by a causal
    # intervention study.  It is not the split key and must not trigger the
    # physical-lineage gate by itself.
    validate_split_lineage([
        {"paired_background_id": "background-a", "physical_case_id": "case-train",
         "lineage_group_id": "lineage-train", "split": "train"},
        {"paired_background_id": "background-a", "physical_case_id": "case-test",
         "lineage_group_id": "lineage-test", "split": "test"},
    ])


def test_affine_transform_rejects_nan_translation():
    transforms = np.eye(4)[None]
    transforms[0, 0, 3] = np.nan
    with pytest.raises(ValueError):
        validate_affine_transforms(transforms)
