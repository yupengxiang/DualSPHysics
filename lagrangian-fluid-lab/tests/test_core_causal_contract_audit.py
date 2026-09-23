from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.core_causal_contract_audit import audit


ROOT = Path(__file__).resolve().parents[1]


def test_f3_f4_causal_lineage_audit_passes(tmp_path):
    output = tmp_path / "contract.json"
    report = audit(
        root=ROOT,
        manifests=[
            ROOT / "campaigns/core-v1/f3-dataset-v2.json",
            ROOT / "campaigns/core-v1/cfd/f4-tallwall120-production-root-v1/f4-tallwall120-formal-reader-manifest-v2-compact.json",
        ],
        reproduction_reports=[
            ROOT / "campaigns/core-v1/reproduction/a8-full-reproduce-v1/collected/h200/reproduction/reproduction.json",
            ROOT / "campaigns/core-v1/runtime/attempts/ada-a8-f3-mlp-seed17-v3-fullcase-reproduce-v1/20260920T055509-90f7455a5a24/reproduction/reproduction.json",
        ],
        output=output,
    )
    assert report["schema"] == "core.contract_audit.v1"
    assert report["passed"] is True
    assert report["checks"]["physical_case_split_isolation"] is True
    assert report["checks"]["lineage_split_isolation"] is True
    assert report["checks"]["future_frame_intervention_predictions_invariant"] is True
    assert report["interface"]["predict_step_arguments"] == ["previous", "known", "dt"]
    intervention = report["future_frame_intervention"]
    assert intervention["future_reference_frames_replaced"] == 2
    assert intervention["full_horizon_steps"] == 2
    assert intervention["prediction_inputs_bitwise_identical"] is True
    assert intervention["prediction_increments_bitwise_identical"] is True
    assert intervention["evaluator_scores_changed"] is True
    assert intervention["predictor_future_state_inputs"] is False
    assert intervention["read_predict_order"] == [
        "read:0", "predict", "read:1", "predict", "read:2",
    ]
    assert json.loads(output.read_text())["passed"] is True


def test_audit_rejects_cross_split_lineage(tmp_path):
    manifest = {
        "schema": "core.dataset.v2",
        "formal_release": False,
        "cases": [
            {
                "case_id": "a", "physical_case_id": "p", "lineage_group_id": "l",
                "family": "F", "split": "train", "hdf5": "a.h5", "sha256": "0" * 64,
                "known_inputs_sha256": "0" * 64,
                "known_inputs_ref": {
                    "geometry": {"path": "geometry.npz", "sha256": "0" * 64},
                    "control": {"path": "control.npz", "sha256": "1" * 64},
                    "physics": {}, "numerics": {}, "coordinate_frame": "x",
                },
            },
            {
                "case_id": "b", "physical_case_id": "p", "lineage_group_id": "l",
                "family": "F", "split": "test", "hdf5": "b.h5", "sha256": "1" * 64,
                "known_inputs_sha256": "0" * 64,
                "known_inputs_ref": {
                    "geometry": {"path": "geometry.npz", "sha256": "0" * 64},
                    "control": {"path": "control.npz", "sha256": "1" * 64},
                    "physics": {}, "numerics": {}, "coordinate_frame": "x",
                },
            },
        ],
    }
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="known input|physical|lineage|contract"):
        audit(root=ROOT, manifests=[path], output=tmp_path / "out.json")
