import copy
import json

import torch

from scripts.core_learning import load_training_checkpoint, train_model
from scripts.core_dataset import CoreDataset
from scripts.f3_long_horizon_training_candidate_v1 import (
    CANDIDATE_ID,
    build_diagnostic_receipt,
    clip_gradients,
    run_bounded_candidate,
    train_candidate,
    validate_gradient_clip_norm,
)

from test_core_contract import tiny_manifest


def _diagnostic_manifest(tmp_path):
    manifest = tiny_manifest(tmp_path)
    test_case = copy.deepcopy(manifest["cases"][0])
    test_case.update(
        case_id="tiny-test",
        physical_case_id="tiny-test",
        lineage_group_id="tiny-test",
        split="test",
        evaluation_role="development_extrapolation",
    )
    manifest["cases"].append(test_case)
    return manifest


def _baseline_reference(path):
    path.write_text(json.dumps({
        "evaluation": {
            "metric_summary": {"selection_score": 0.01},
            "position_rmse_m": {"step_1": 100.0, "frame_mean": 100.0},
            "velocity_rmse_mps": {"step_1": 100.0, "frame_mean": 100.0},
        }
    }), encoding="utf-8")


def test_gradient_clip_norm_validation_and_synthetic_clip():
    assert validate_gradient_clip_norm(None) is None
    assert validate_gradient_clip_norm(1) == 1.0
    for invalid in (True, 0, -1, float("inf")):
        try:
            validate_gradient_clip_norm(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted invalid clipping bound {invalid!r}")

    parameter = torch.nn.Parameter(torch.tensor([3.0, 4.0]))
    (parameter.square().sum() / 2).backward()
    model = torch.nn.Module()
    model.register_parameter("parameter", parameter)
    result = clip_gradients(model, 1.0)
    assert result["pre_clip_l2"] == 5.0
    assert result["clipped"] is True
    assert result["post_clip_l2"] <= 1.0 + 1e-6
    assert torch.allclose(parameter.grad, torch.tensor([0.6, 0.8]), atol=1e-6)


def test_default_no_clip_is_bitwise_paired_with_core_training(tmp_path):
    manifest = tiny_manifest(tmp_path)
    baseline_checkpoint = tmp_path / "baseline.pt"
    candidate_checkpoint = tmp_path / "candidate.pt"
    baseline_output = tmp_path / "baseline.json"
    candidate_output = tmp_path / "candidate.json"
    with CoreDataset(manifest, tmp_path) as dataset:
        baseline = train_model(
            dataset, model_kind="graph_raw", seed=17, updates=3,
            centers_per_update=1, hidden=8, learning_rate=1e-3,
            normalization_transitions=1, max_neighbors=3,
            checkpoint=baseline_checkpoint, output=baseline_output,
            checkpoint_every=100, log_every=1, validation_every=0,
            evaluate_milestones=False)
        candidate = train_candidate(
            dataset, model_kind="graph_raw", seed=17, updates=3,
            centers_per_update=1, hidden=8, learning_rate=1e-3,
            normalization_transitions=1, max_neighbors=3, device="cpu",
            gradient_clip_norm=None, checkpoint=candidate_checkpoint,
            output=candidate_output, log_every=1)

    baseline_payload = load_training_checkpoint(baseline_checkpoint, restore_rng=False)
    candidate_payload = load_training_checkpoint(candidate_checkpoint, restore_rng=False)
    assert baseline["history"] == candidate["history"]
    assert baseline["completed_updates"] == candidate["completed_updates"] == 3
    assert candidate["config"]["gradient_clipping"] is None
    for name, value in baseline_payload["model_state"].items():
        assert torch.equal(value, candidate_payload["model_state"][name]), name
    assert candidate["formal_eligible"] is False
    assert candidate["qualification_credit"] == 0
    assert candidate["future_state_inputs"] is False


def test_enabled_clipping_is_recorded_and_bounded_on_cpu(tmp_path):
    manifest = tiny_manifest(tmp_path)
    checkpoint = tmp_path / "clipped.pt"
    with CoreDataset(manifest, tmp_path) as dataset:
        result = train_candidate(
            dataset, model_kind="graph_raw", seed=17, updates=3,
            centers_per_update=1, hidden=8, learning_rate=1e-3,
            normalization_transitions=1, max_neighbors=3, device="cpu",
            gradient_clip_norm=0.01, checkpoint=checkpoint, log_every=1)
    assert result["candidate_id"] == CANDIDATE_ID
    assert result["gradient_clipping"]["enabled"] is True
    assert result["gradient_clipping"]["clipped_updates"] >= 1
    assert result["gradient_clipping"]["post_clip_l2_max"] <= 0.01 + 1e-5
    payload = load_training_checkpoint(checkpoint, restore_rng=False)
    assert payload["config"]["gradient_clipping"] == {
        "kind": "global_l2", "max_norm": 0.01}


def test_bounded_run_receipt_is_diagnostic_and_causal(tmp_path):
    manifest = _diagnostic_manifest(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    baseline = tmp_path / "raw500-reference.json"
    _baseline_reference(baseline)
    checkpoint = tmp_path / "candidate.pt"
    training_output = tmp_path / "training.json"
    evaluation_output = tmp_path / "evaluation.json"
    receipt_output = tmp_path / "receipt.json"
    trajectory = tmp_path / "trajectory.h5"
    receipt = run_bounded_candidate(
        manifest_path=manifest_path,
        data_root=tmp_path,
        case_id="tiny-test",
        baseline_path=baseline,
        checkpoint=checkpoint,
        training_output=training_output,
        evaluation_output=evaluation_output,
        receipt_output=receipt_output,
        trajectory_output=trajectory,
        model_kind="graph_raw", seed=17, updates=2,
        centers_per_update=1, hidden=8, normalization_transitions=1,
        max_neighbors=3, device="cpu", gradient_clip_norm=0.01,
        chunk_size=2, maximum_steps=1)
    assert receipt_output.is_file()
    assert receipt["schema"].endswith("candidate.v1")
    assert receipt["decision"]["candidate_status"] == "retained_for_followup"
    assert receipt["qualification"] == {
        "formal_eligible": False,
        "T1_numerical": False,
        "T2_macro": False,
        "qualification_credit": 0,
    }
    assert receipt["side_effects"]["manifest_modified"] is False
    assert receipt["side_effects"]["future_state_inputs"] is False
    assert receipt["evaluation"]["requested_maximum_steps"] == 1


def test_receipt_builder_rejects_formal_or_future_state_claims(tmp_path):
    manifest = tiny_manifest(tmp_path)
    baseline = tmp_path / "reference.json"
    _baseline_reference(baseline)
    with CoreDataset(manifest, tmp_path) as dataset:
        training = {
            "diagnostic_only": True,
            "formal_eligible": False,
            "model_kind": "graph_raw",
            "seed": 17,
            "config": {"gradient_clipping": None, "hidden": 8,
                       "centers_per_update": 1, "normalization_transitions": 1,
                       "max_neighbors": 3, "learning_rate": 1e-3},
            "completed_updates": 1, "device": "cpu", "wall_seconds": 0.1,
            "peak_rss_mib": 1.0, "peak_gpu_memory_bytes": 0,
            "parameter_count": 1, "checkpoint": {"path": str(tmp_path / "c.pt")},
            "evidence_status": "complete", "gradient_clipping": {"enabled": False},
        }
        evaluation = {"formal_eligible": False, "future_state_inputs": True}
        try:
            build_diagnostic_receipt(
                manifest_path=tmp_path / "manifest.json", dataset=dataset,
                case_id="tiny", training=training,
                training_output=tmp_path / "training.json",
                evaluation=evaluation, evaluation_output=tmp_path / "evaluation.json",
                trajectory_output=tmp_path / "trajectory.h5",
                progress_output=None, baseline_path=baseline, chunk_size=2,
                maximum_steps=1)
        except ValueError as error:
            assert "diagnostic-only/casual" in str(error)
        else:
            raise AssertionError("future-state evaluation was accepted")
