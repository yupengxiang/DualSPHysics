import copy
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace

import h5py
import numpy as np
import pytest
import torch

import scripts.core_learning as learning
from scripts.core_dataset import CoreDataset
from scripts.core_learning import (TransitionSampler, compute_normalization,
                                   checkpoint_refs_from_receipt, evaluate, evaluate_checkpoints,
                                   formal_evaluation_gate,
                                   load_training_checkpoint, main, MILESTONE_UPDATES,
                                   model_parameter_digest, profile_case, rollout_case,
                                   save_training_checkpoint, sha256_file, train_model,
                                   restore_rng_state,
                                   _characteristic_scales,
                                   _execution_summary, rollout_completion_semantics,
                                   _validate_fixed_denominator,
                                   _validate_milestone_evaluation)
from scripts.core_models import DualIncrementModel, Normalization

from test_core_contract import tiny_manifest


def _formal_test_manifest(tmp_path, case_count=2):
    manifest = tiny_manifest(tmp_path)
    template = manifest["cases"][0]
    cases = []
    for index in range(case_count):
        row = copy.deepcopy(template)
        row.update(
            case_id=f"formal-test-{index}",
            physical_case_id=f"formal-test-{index}",
            lineage_group_id=f"formal-test-{index}",
            split="test",
            evaluation_role="development_extrapolation",
        )
        cases.append(row)
    manifest["cases"] = cases
    manifest["formal_release"] = True
    return manifest


def test_normalization_and_sampler_are_train_only_and_resumable(tmp_path):
    manifest = tiny_manifest(tmp_path)
    with CoreDataset(manifest, tmp_path) as data:
        normalization = compute_normalization(data, maximum_transitions=None)
        assert normalization.source_split == "train"
        all_normalizations = [compute_normalization(data, model_kind=kind, maximum_transitions=None)
                              for kind in ("mlp", "graph_raw", "graph_residual")]
        assert all(normalization.as_dict() == item.as_dict() for item in all_normalizations)
        assert data.read_log and all(case_id == "tiny" for case_id, _ in data.read_log)
        sampler = TransitionSampler(data, centers_per_update=1, seed=17)
        first = sampler.sample()
        state = sampler.state_dict()
        second_sampler = TransitionSampler(data, centers_per_update=1, seed=17)
        second_sampler.load_state_dict(state)
        assert second_sampler.sample()[0:2] == sampler.sample()[0:2]
        assert first[6].shape == (1,)


def test_seed_paired_sampler_sequence_is_independent_of_model_kind(tmp_path):
    manifest = tiny_manifest(tmp_path)
    with CoreDataset(manifest, tmp_path) as data:
        samplers = {kind: TransitionSampler(data, centers_per_update=1, seed=17)
                    for kind in ("mlp", "graph_raw", "graph_residual")}
        for _ in range(5):
            draws = {kind: (sample[0], sample[1])
                     for kind, sampler in samplers.items()
                     for sample in [sampler.sample()]}
            assert len({tuple(value) for value in draws.values()}) == 1


def test_checkpoint_contains_rng_sampler_and_autonomous_rollout(tmp_path):
    manifest = tiny_manifest(tmp_path)
    checkpoint = tmp_path / "graph-residual.pt"
    result_file = tmp_path / "training.json"
    with CoreDataset(manifest, tmp_path) as data:
        receipt = train_model(data, model_kind="graph_residual", seed=17, updates=2,
                              centers_per_update=1, hidden=8, normalization_transitions=1,
                              checkpoint=checkpoint, output=result_file,
                              checkpoint_every=1, log_every=1)
        assert receipt["schema"] == "core.training.v1"
        assert receipt["completed_updates"] == 2
        payload = load_training_checkpoint(checkpoint, restore_rng=False)
        assert payload["schema"] == "core.checkpoint.v1"
        assert payload["sampler_state"]["draws"] == 2
        assert set(payload["rng_state"]) >= {"python", "numpy", "torch"}
        progress = tmp_path / "training-progress.json"
        assert receipt["progress_path"] == str(progress)
        assert json.loads(progress.read_text())["status"] == "completed"

        from scripts.core_learning import _build_predictor_from_checkpoint
        predictor, _ = _build_predictor_from_checkpoint(checkpoint, "cpu", 1)
        trajectory_path = tmp_path / "predicted" / "tiny.h5"
        rollout_progress = tmp_path / "predicted" / "tiny-progress.json"
        rollout = rollout_case(data, "tiny", predictor, trajectory_output=trajectory_path,
                               progress_output=rollout_progress, progress_every=1)
        assert rollout["autonomous"] is True
        assert rollout["future_state_inputs"] is False
        assert rollout["frames_predicted"] == 1
        assert rollout["physics"]["summary"]["completed_frames"] == 1
        assert rollout["execution_complete"] is True
        assert rollout["finite_rollout_complete"] is True
        assert rollout["scientific_status"] == "not_assessed"
        progress_payload = json.loads(rollout_progress.read_text())
        assert progress_payload["status"] == "completed"
        assert progress_payload["completed_frames"] == progress_payload["expected_frames"] == 1
        assert progress_payload["execution_complete"] is True
        assert progress_payload["finite_rollout_complete"] is True
    with h5py.File(trajectory_path, "r") as trajectory:
        assert set(("time", "position", "velocity", "particle_id", "particle_zone",
                    "mass", "valid")) <= set(trajectory)
        assert trajectory["valid"].shape == (2, 2)
        assert trajectory.attrs["future_state_inputs"] == 0


def test_cuda_mapped_checkpoint_rng_states_restore_from_cpu_bytes(tmp_path):
    """A CUDA map_location must not feed GPU RNG tensors to set_rng_state."""
    if not torch.cuda.is_available():
        pytest.skip("CUDA is unavailable")

    path = tmp_path / "mapped-rng.pt"
    cpu_before = torch.get_rng_state().clone()
    cuda_before = [state.clone() for state in torch.cuda.get_rng_state_all()]
    try:
        payload = {
            "rng_state": {
                "python": __import__("random").getstate(),
                "numpy": np.random.get_state(),
                "torch": cpu_before,
                "torch_cuda": cuda_before,
            }
        }
        torch.save(payload, path)
        mapped = torch.load(path, map_location="cuda", weights_only=False)
        assert mapped["rng_state"]["torch"].is_cuda
        assert all(state.is_cuda for state in mapped["rng_state"]["torch_cuda"])
        restore_rng_state(mapped["rng_state"])
        assert torch.equal(torch.get_rng_state(), cpu_before)
        assert all(torch.equal(actual, expected)
                   for actual, expected in zip(torch.cuda.get_rng_state_all(), cuda_before))
    finally:
        torch.set_rng_state(cpu_before)
        torch.cuda.set_rng_state_all(cuda_before)


def test_restore_rng_state_rejects_non_byte_tensors():
    state = {
        "python": __import__("random").getstate(),
        "numpy": np.random.get_state(),
        "torch": torch.zeros(8, dtype=torch.int64),
    }
    with pytest.raises(TypeError, match="torch.uint8"):
        restore_rng_state(state)


def test_training_evidence_records_initial_normalization_and_residual_prior(tmp_path):
    manifest = tiny_manifest(tmp_path)
    checkpoint = tmp_path / "evidence.pt"
    with CoreDataset(manifest, tmp_path) as data:
        receipt = train_model(
            data, model_kind="graph_residual", seed=17, updates=2,
            centers_per_update=1, hidden=8, normalization_transitions=1,
            checkpoint=checkpoint, output=tmp_path / "evidence.json",
            progress_output=tmp_path / "evidence-progress.json",
            checkpoint_every=1, log_every=1, validation_every=0,
            run_id="graph_residual-seed17", evaluate_milestones=False,
        )
    evidence = receipt["evidence"]
    assert receipt["evidence_status"] == evidence["status"] == "complete"
    initialization = evidence["initialization"]
    assert initialization["status"] == "captured"
    assert initialization["constructed_before_first_update"] is True
    assert len(initialization["parameter_digest"]) == 64
    normalization = evidence["normalization"]
    assert normalization["selected_transition_count"] == 1
    assert normalization["train_case_ids"] == ["tiny"]
    assert normalization["selected_transition_bindings"] == [{"case_id": "tiny", "frame": 0}]
    prior = evidence["residual_prior"]
    assert prior["enabled"] is True and prior["history_complete"] is True
    assert prior["execution_calls"] == 2 and prior["rows"] == 4
    assert prior["finite"] is True
    payload = load_training_checkpoint(checkpoint, restore_rng=False)
    assert payload["evidence"] == evidence
    assert payload["evidence_status"] == "complete"


def test_intermediate_checkpoint_evidence_uses_checkpoint_update_frontier(tmp_path, monkeypatch):
    """A residual milestone is complete before the requested run endpoint."""
    manifest = tiny_manifest(tmp_path)
    monkeypatch.setattr(learning, "MILESTONE_UPDATES", (2, 4))
    final_checkpoint = tmp_path / "frontier.pt"
    with CoreDataset(manifest, tmp_path) as data:
        receipt = train_model(
            data, model_kind="graph_residual", seed=17, updates=4,
            centers_per_update=1, hidden=8, normalization_transitions=1,
            checkpoint=final_checkpoint, checkpoint_every=4,
            log_every=4, validation_every=0, evaluate_milestones=False,
        )
    milestone = load_training_checkpoint(
        tmp_path / "frontier.step-00000002.pt", restore_rng=False)
    assert milestone["update"] == 2
    assert milestone["evidence_status"] == "complete"
    assert milestone["evidence"]["residual_prior"]["execution_calls"] == 2
    assert receipt["evidence_status"] == "complete"


def test_resume_preserves_construction_digest_and_rejects_tampering(tmp_path):
    manifest = tiny_manifest(tmp_path)
    first_path, resumed_path = tmp_path / "first.pt", tmp_path / "resumed.pt"
    with CoreDataset(manifest, tmp_path) as data:
        train_model(data, model_kind="graph_residual", seed=17, updates=2,
                    centers_per_update=1, hidden=8, normalization_transitions=1,
                    checkpoint=first_path, checkpoint_every=1, log_every=1,
                    validation_every=0, run_id="graph_residual-seed17",
                    evaluate_milestones=False)
        first_payload = load_training_checkpoint(first_path, restore_rng=False)
        resumed = train_model(data, model_kind="graph_residual", seed=17, updates=4,
                              centers_per_update=1, hidden=8, normalization_transitions=1,
                              checkpoint=resumed_path, resume=first_path,
                              checkpoint_every=1, log_every=1, validation_every=0,
                              run_id="graph_residual-seed17", evaluate_milestones=False)
    first_evidence = first_payload["evidence"]
    resumed_evidence = resumed["evidence"]
    assert resumed_evidence["status"] == "complete"
    assert resumed_evidence["initialization"]["parameter_digest"] == (
        first_evidence["initialization"]["parameter_digest"]
    )
    assert resumed_evidence["initialization"]["resume"]["loaded_digest_is_initial"] is False
    assert resumed_evidence["initialization"]["resume"]["initial_digest_reused"] is True
    assert resumed_evidence["residual_prior"]["execution_calls"] == 4
    loaded_model = DualIncrementModel("graph_residual", hidden=8)
    loaded_model.load_state_dict(first_payload["model_state"])
    assert resumed_evidence["initialization"]["resume"]["loaded_parameter_digest"] == model_parameter_digest(loaded_model)
    assert resumed_evidence["initialization"]["resume"]["loaded_parameter_digest"] != (
        resumed_evidence["initialization"]["parameter_digest"]
    )

    tampered = copy.deepcopy(first_payload)
    tampered["evidence"]["initialization"]["parameter_digest"] = "0" * 64
    tampered_path = tmp_path / "tampered.pt"
    torch.save(tampered, tampered_path)
    with CoreDataset(manifest, tmp_path) as data:
        with pytest.raises(ValueError, match="initialization evidence digest"):
            train_model(data, model_kind="graph_residual", seed=17, updates=3,
                        centers_per_update=1, hidden=8, normalization_transitions=1,
                        checkpoint=tmp_path / "tampered-resumed.pt", resume=tampered_path,
                        checkpoint_every=1, log_every=1, validation_every=0,
                        run_id="graph_residual-seed17", evaluate_milestones=False)


def test_legacy_checkpoint_resume_marks_initial_evidence_missing(tmp_path):
    manifest = tiny_manifest(tmp_path)
    first_path, legacy_path, resumed_path = (tmp_path / name for name in
                                              ("first.pt", "legacy.pt", "legacy-resumed.pt"))
    with CoreDataset(manifest, tmp_path) as data:
        train_model(data, model_kind="mlp", seed=17, updates=2, centers_per_update=1,
                    hidden=8, normalization_transitions=1, checkpoint=first_path,
                    checkpoint_every=1, log_every=1, validation_every=0,
                    run_id="mlp-seed17", evaluate_milestones=False)
        legacy = load_training_checkpoint(first_path, restore_rng=False)
        legacy.pop("evidence", None)
        legacy.pop("evidence_status", None)
        torch.save(legacy, legacy_path)
        resumed = train_model(data, model_kind="mlp", seed=17, updates=3,
                              centers_per_update=1, hidden=8, normalization_transitions=1,
                              checkpoint=resumed_path, resume=legacy_path,
                              checkpoint_every=1, log_every=1, validation_every=0,
                              run_id="mlp-seed17", evaluate_milestones=False)
    initialization = resumed["evidence"]["initialization"]
    assert resumed["evidence_status"] == "incomplete"
    assert initialization["status"] == "missing_legacy"
    assert initialization["parameter_digest"] is None
    assert initialization["resume"]["loaded_digest_is_initial"] is False


def test_fixed_validation_schedule_is_recorded_without_train_leakage(tmp_path):
    manifest = tiny_manifest(tmp_path)
    validation = copy.deepcopy(manifest["cases"][0])
    validation.update(case_id="validation", physical_case_id="validation", lineage_group_id="validation",
                      split="validation", evaluation_role="validation")
    manifest["cases"].append(validation)
    with CoreDataset(manifest, tmp_path) as data:
        receipt = train_model(data, model_kind="mlp", seed=29, updates=2, centers_per_update=1,
                              hidden=8, normalization_transitions=1, checkpoint=tmp_path / "m.pt",
                              validation_every=1, validation_transitions=1, validation_centers=1)
        assert len(receipt["validation_history"]) == 2
        assert all(item["available"] and item["transition_count"] == 1 for item in receipt["validation_history"])
        assert receipt["normalization"]["source_split"] == "train"


def test_rollout_failure_keeps_expected_frame_denominator(tmp_path):
    manifest = tiny_manifest(tmp_path)

    class FailingPredictor:
        def predict_step(self, *_):
            raise FloatingPointError("test divergence")

    with CoreDataset(manifest, tmp_path) as data:
        result = rollout_case(data, "tiny", FailingPredictor())
    assert result["frames_expected"] == 1
    assert result["frames_executed"] == 0
    assert result["executed"] is True
    assert result["position_rmse"] == [None]
    assert result["failure_category"] == "nonfinite_prediction"
    assert result["first_failure_frame"] == 1
    assert result["execution_complete"] is False
    assert result["finite_rollout_complete"] is False
    assert result["scientific_status"] == "not_assessed"


def test_rollout_failure_marks_unexecuted_public_state_invalid(tmp_path):
    manifest = tiny_manifest(tmp_path)

    class FailingPredictor:
        def predict_step(self, *_):
            raise FloatingPointError("test divergence")

    trajectory_path = tmp_path / "failed.h5"
    progress_path = tmp_path / "failed-progress.json"
    with CoreDataset(manifest, tmp_path) as data:
        result = rollout_case(data, "tiny", FailingPredictor(), trajectory_output=trajectory_path,
                              progress_output=progress_path)
    assert result["frames_expected"] == 1 and result["frames_executed"] == 0
    with h5py.File(trajectory_path, "r") as trajectory:
        assert trajectory["valid"][0].all() and not trajectory["valid"][1].any()
        assert np.isnan(trajectory["position"][1]).all()
    progress_payload = json.loads(progress_path.read_text())
    assert progress_payload["status"] == "failed"
    assert progress_payload["completed_frames"] == 0
    assert progress_payload["execution_complete"] is False
    assert progress_payload["finite_rollout_complete"] is False
    assert progress_payload["scientific_status"] == "not_assessed"


def test_completion_semantics_separate_finite_execution_from_science():
    complete = rollout_completion_semantics(
        expected_frames=3, frames_executed=3, failure_category=None,
        position_rmse=[0.0, 0.1, 0.2], velocity_rmse=[0.0, 0.1, 0.2])
    assert complete == {
        "execution_complete": True,
        "finite_rollout_complete": True,
        "scientific_status": "not_assessed",
        "scientific_failure_category": None,
        "scientific_first_failure_frame": None,
    }
    negative = dict(complete, scientific_status="failed",
                    scientific_failure_category="finite_wall_penetration",
                    scientific_first_failure_frame=2)
    missing = rollout_completion_semantics(
        expected_frames=3, frames_executed=0, failure_category="rollout_setup_error",
        position_rmse=[None, None, None], velocity_rmse=[None, None, None])
    summary = _execution_summary({
        "negative": {"rollout": negative, "score": {"executed": True, "complete": False}},
        "missing": {"rollout": missing, "score": {"executed": False, "complete": False}},
    })
    assert summary["executed_case_count"] == 1
    assert summary["missing_execution_case_count"] == 1
    assert summary["scientifically_negative_executed_case_count"] == 1
    assert summary["scientific_status_counts"] == {"failed": 1, "not_assessed": 1}


def test_completion_semantics_rejects_fractional_or_boolean_counts():
    for invalid in (3.0, np.float64(3.0), 3.5, True):
        with pytest.raises(ValueError, match="expected_frames"):
            rollout_completion_semantics(
                expected_frames=invalid, frames_executed=3, failure_category=None,
                position_rmse=[0.0, 0.0, 0.0], velocity_rmse=[0.0, 0.0, 0.0])
    for invalid in (3.0, np.float64(3.0), 3.5, True):
        with pytest.raises(ValueError, match="frames_executed"):
            rollout_completion_semantics(
                expected_frames=3, frames_executed=invalid, failure_category=None,
                position_rmse=[0.0, 0.0, 0.0], velocity_rmse=[0.0, 0.0, 0.0])


def test_legacy_known_inputs_geometry_contract_remains_scoreable(tmp_path):
    """The v3 bundle exposes ``geometry`` without ``geometry_at``."""
    manifest = tiny_manifest(tmp_path)

    class LegacyDataset:
        def __init__(self, wrapped):
            self._wrapped = wrapped

        def times(self, case_id):
            return self._wrapped.times(case_id)

        def read_state(self, case_id, frame):
            return self._wrapped.read_state(case_id, frame)

        def known_inputs(self, case_id):
            current = self._wrapped.known_inputs(case_id)
            return SimpleNamespace(geometry=current.geometry, physics=current.physics,
                                   numerics=current.numerics, control=current.control)

    class ZeroPredictor:
        def predict_step(self, state, known, dt):
            from scripts.core_contract import StepPrediction
            return StepPrediction(np.zeros_like(state.position), np.zeros_like(state.velocity))

    with CoreDataset(manifest, tmp_path) as data:
        expected = _characteristic_scales(data.known_inputs("tiny"))
        result = rollout_case(LegacyDataset(data), "tiny", ZeroPredictor())
        profile = profile_case(LegacyDataset(data), "tiny", model_kind="mlp", steps=1,
                               hidden=8, chunk_size=1)
    assert result["frames_executed"] == 1
    assert result["physics"]["summary"]["completed_frames"] == 1
    assert result["length_m"] == expected[0] and result["speed_mps"] == expected[1]
    assert profile["steps_completed"] == 1


def test_resume_rejects_run_and_learning_rate_mismatch(tmp_path):
    manifest = tiny_manifest(tmp_path)
    checkpoint = tmp_path / "bound.pt"
    with CoreDataset(manifest, tmp_path) as data:
        train_model(data, model_kind="mlp", seed=17, updates=1, centers_per_update=1,
                    hidden=8, normalization_transitions=1, learning_rate=1e-3,
                    run_id="formal-mlp-seed17", checkpoint=checkpoint,
                    checkpoint_every=1, validation_every=0)
        with pytest.raises(ValueError, match="run_id"):
            train_model(data, model_kind="mlp", seed=17, updates=2, centers_per_update=1,
                        hidden=8, normalization_transitions=1, learning_rate=1e-3,
                        run_id="different-run", checkpoint=tmp_path / "bad-run.pt",
                        resume=checkpoint, checkpoint_every=1, validation_every=0)
        with pytest.raises(ValueError, match="learning rate"):
            train_model(data, model_kind="mlp", seed=17, updates=2, centers_per_update=1,
                        hidden=8, normalization_transitions=1, learning_rate=2e-3,
                        run_id="formal-mlp-seed17", checkpoint=tmp_path / "bad-lr.pt",
                        resume=checkpoint, checkpoint_every=1, validation_every=0)


def test_formal_evaluation_requires_manifest_release_even_with_family_counts(tmp_path):
    manifest = tiny_manifest(tmp_path)
    template = manifest["cases"][0]
    for family_index in range(3):
        for case_index in range(4):
            row = copy.deepcopy(template)
            row.update(case_id=f"validation-f{family_index}-{case_index}",
                       physical_case_id=f"validation-f{family_index}-{case_index}",
                       lineage_group_id=f"validation-f{family_index}-{case_index}",
                       family=f"F{family_index + 1}", split="validation",
                       evaluation_role="validation")
            manifest["cases"].append(row)
    with CoreDataset(manifest, tmp_path) as data:
        with pytest.raises(ValueError, match="formal_release"):
            evaluate_checkpoints(data, ["missing-1.pt", "missing-2.pt", "missing-3.pt", "missing-4.pt"])


def test_training_receipt_milestones_require_hashes():
    receipt = {"checkpoints": [
        {"path": f"step-{update:08d}.pt", "update": update, "sha256": "a" * 63}
        for update in MILESTONE_UPDATES
    ]}
    with pytest.raises(ValueError, match="SHA-256"):
        checkpoint_refs_from_receipt(receipt)


def test_checkpoint_selection_rejects_mixed_normalization_bindings(tmp_path):
    manifest = tiny_manifest(tmp_path)
    template = manifest["cases"][0]
    for index in range(4):
        row = copy.deepcopy(template)
        row.update(case_id=f"validation-{index}", physical_case_id=f"validation-{index}",
                   lineage_group_id=f"validation-{index}", split="validation",
                   evaluation_role="validation")
        manifest["cases"].append(row)
    paths = []
    with CoreDataset(manifest, tmp_path) as data:
        normalization = compute_normalization(data, maximum_transitions=1)
        sampler = TransitionSampler(data, centers_per_update=1, seed=17)
        model = DualIncrementModel("mlp", hidden=8)
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
        for update in MILESTONE_UPDATES:
            path = tmp_path / f"mixed-{update}.pt"
            save_training_checkpoint(path, model=model, optimizer=optimizer, sampler=sampler,
                                     normalization=normalization, update=update,
                                     config={"update": update}, seed=17)
            paths.append(path)
        payload = torch.load(paths[-1], map_location="cpu", weights_only=False)
        payload["normalization"]["feature_mean"][0] += 1.0
        torch.save(payload, paths[-1])
        with pytest.raises(ValueError, match="training/data/normalization binding"):
            evaluate_checkpoints(data, paths, device="cpu", chunk_size=1,
                                 qualification_only=True)


def test_cli_analytic_baselines_need_no_checkpoint_and_keep_receipt_identity(tmp_path):
    manifest = tiny_manifest(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    for baseline in ("constant_velocity", "known_force"):
        output = tmp_path / f"{baseline}.json"
        assert main(["evaluate", "--manifest", str(manifest_path), "--data-root", str(tmp_path),
                     "--baseline", baseline, "--case-id", "tiny", "--max-steps", "1",
                     "--output", str(output)]) == 0
        receipt = json.loads(output.read_text())
        assert receipt["checkpoint"] is None
        assert receipt["baseline"] == baseline
        assert receipt["training"] is False
        case = receipt["cases"]["tiny"]
        assert case["expected_frames"] == 1
        assert case["executed"] is True
        assert case["frames_executed"] == 1
        assert receipt["execution_summary"] == {
            "execution_complete_case_count": 1,
            "executed_case_count": 1,
            "finite_rollout_complete_case_count": 1,
            "missing_execution_case_count": 0,
            "registered_case_count": 1,
            "scientific_status_counts": {"not_assessed": 1},
            "scientifically_negative_executed_case_count": 0,
        }


def test_cli_relative_manifest_is_resolved_under_data_root_from_other_cwd(tmp_path, monkeypatch):
    manifest = tiny_manifest(tmp_path)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    caller = tmp_path / "caller"
    caller.mkdir()
    output = tmp_path / "relative-manifest-evaluate.json"
    monkeypatch.chdir(caller)
    assert main(["evaluate", "--manifest", "manifest.json", "--data-root", str(tmp_path),
                 "--baseline", "constant_velocity", "--case-id", "tiny", "--max-steps", "1",
                 "--output", str(output)]) == 0
    receipt = json.loads(output.read_text())
    assert receipt["cases"]["tiny"]["expected_frames"] == 1
    assert receipt["future_state_inputs"] is False


def test_formal_evaluate_rejects_short_horizon_subset_and_non_test_split(tmp_path):
    manifest = _formal_test_manifest(tmp_path, case_count=2)
    with CoreDataset(manifest, tmp_path) as data:
        predictor, _ = learning._build_predictor_from_baseline("constant_velocity")
        with pytest.raises(ValueError, match="maximum_steps"):
            evaluate(data, predictor, maximum_steps=1)
        with pytest.raises(ValueError, match="every registered test case"):
            evaluate(data, predictor, case_ids=["formal-test-0"])
        with pytest.raises(ValueError, match="split='test'"):
            evaluate(data, predictor, split="validation")


def test_formal_evaluate_cli_binds_full_registered_test_registry(tmp_path):
    manifest = _formal_test_manifest(tmp_path, case_count=2)
    manifest_path = tmp_path / "formal-manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    output = tmp_path / "formal-evaluate.json"
    assert main([
        "evaluate", "--manifest", str(manifest_path), "--data-root", str(tmp_path),
        "--baseline", "constant_velocity", "--output", str(output),
    ]) == 0
    receipt = json.loads(output.read_text())
    assert receipt["evaluation_mode"] == "formal"
    assert receipt["registered_case_count"] == 2
    assert receipt["aggregate"]["registered_cases"] == 2
    assert set(receipt["cases"]) == {"formal-test-0", "formal-test-1"}
    assert all(row["expected_frames"] == 1 for row in receipt["cases"].values())
    with pytest.raises(ValueError, match="every registered test case"):
        main([
            "evaluate", "--manifest", str(manifest_path), "--data-root", str(tmp_path),
            "--baseline", "constant_velocity", "--case-id", "formal-test-0",
            "--output", str(tmp_path / "subset.json"),
        ])


def test_formal_evaluate_rejects_unknown_and_duplicate_cases(tmp_path):
    manifest = _formal_test_manifest(tmp_path, case_count=2)
    with CoreDataset(manifest, tmp_path) as data:
        predictor, _ = learning._build_predictor_from_baseline("constant_velocity")
        with pytest.raises(ValueError, match="unknown case"):
            evaluate(data, predictor, case_ids=["formal-test-0", "missing"])
        with pytest.raises(ValueError, match="duplicate cases"):
            evaluate(data, predictor, case_ids=["formal-test-0", "formal-test-0"])
    with pytest.raises(ValueError, match="every registered test case"):
        formal_evaluation_gate(
            registered_case_ids=("formal-test-0", "formal-test-1"),
            selected_case_ids=("formal-test-0",),
        )


def test_formal_evaluation_rejects_missing_fixed_denominator():
    with pytest.raises(ValueError, match="fixed evaluation denominator"):
        _validate_fixed_denominator(("formal-test-0",), {})


def test_formal_evaluate_retains_finite_failed_rollout_as_incomplete(tmp_path, monkeypatch):
    manifest = _formal_test_manifest(tmp_path, case_count=1)

    def finite_but_failed_rollout(dataset, case_id, predictor, **kwargs):
        return {
            "schema": learning.ROLLOUT_SCHEMA,
            "case_id": case_id,
            "frames_predicted": 1,
            "frames_expected": 1,
            "frames_executed": 1,
            "expected_frames": 1,
            "executed": True,
            "position_rmse": [0.0],
            "velocity_rmse": [0.0],
            "position_ade": [0.0],
            "velocity_ade": [0.0],
            "failure_category": "catastrophic_rollout",
            "first_failure_frame": 1,
            "execution_complete": False,
            "finite_rollout_complete": False,
            "scientific_status": "not_assessed",
            "physics": {"frames": [{}], "summary": {"expected_frames": 1,
                                                        "completed_frames": 1}},
        }

    monkeypatch.setattr(learning, "rollout_case", finite_but_failed_rollout)
    with CoreDataset(manifest, tmp_path) as data:
        predictor, _ = learning._build_predictor_from_baseline("constant_velocity")
        result = evaluate(data, predictor)
    row = result["cases"]["formal-test-0"]
    assert result["registered_case_count"] == 1
    assert result["aggregate"]["registered_cases"] == 1
    assert result["aggregate"]["complete_fraction"] == 0.0
    assert result["execution_summary"]["execution_complete_case_count"] == 0
    assert result["finite_summary"]["finite_rollout_complete_case_count"] == 0
    assert row["score"]["complete"] is False
    assert row["rollout"]["position_rmse"] == [0.0]


def test_diagnostic_short_horizon_keeps_null_tail_and_incomplete_score(tmp_path, monkeypatch):
    manifest = tiny_manifest(tmp_path)

    def short_rollout(dataset, case_id, predictor, **kwargs):
        return {
            "schema": learning.ROLLOUT_SCHEMA,
            "case_id": case_id,
            "frames_predicted": 1,
            "frames_expected": 1,
            "frames_executed": 1,
            "expected_frames": 1,
            "executed": True,
            "position_rmse": [0.0],
            "velocity_rmse": [0.0],
            "position_ade": [0.0],
            "velocity_ade": [0.0],
            "failure_category": None,
            "first_failure_frame": None,
            "execution_complete": True,
            "finite_rollout_complete": True,
            "scientific_status": "not_assessed",
            "physics": {"frames": [{}], "summary": {"expected_frames": 1,
                                                        "completed_frames": 1}},
        }

    monkeypatch.setattr(learning, "rollout_case", short_rollout)
    monkeypatch.setattr(
        learning,
        "_fixed_denominator_for_cases",
        lambda dataset, case_ids: {
            case_id: {"expected_frames": 2, "length_m": 1.0, "speed_mps": 1.0}
            for case_id in case_ids
        },
    )
    with CoreDataset(manifest, tmp_path) as data:
        predictor, _ = learning._build_predictor_from_baseline("constant_velocity")
        result = evaluate(data, predictor, case_ids=["tiny"], maximum_steps=1,
                          diagnostic=True)
    row = result["cases"]["tiny"]
    assert row["expected_frames"] == 2
    assert row["position_rmse"] == [0.0, None]
    assert row["velocity_rmse"] == [0.0, None]
    assert row["execution_complete"] is False
    assert row["finite_rollout_complete"] is False
    assert row["score"]["complete"] is False
    assert result["aggregate"]["complete_fraction"] == 0.0


def test_diagnostic_evaluate_is_explicit_and_keeps_protocol_fields(tmp_path):
    manifest = tiny_manifest(tmp_path)
    with CoreDataset(manifest, tmp_path) as data:
        predictor, _ = learning._build_predictor_from_baseline("constant_velocity")
        result = evaluate(data, predictor, split="test", case_ids=["tiny"],
                          maximum_steps=1, diagnostic=True)
    assert result["evaluation_mode"] == "diagnostic"
    assert result["formal_eligible"] is False
    assert result["registered_case_count"] == 1
    assert result["fixed_denominator"]["tiny"]["expected_frames"] == 1
    assert result["aggregate"]["registered_cases"] == 1
    assert result["cases"]["tiny"]["expected_frames"] == 1


def test_normalization_torch_values_stay_on_input_device_and_dtype():
    normalization = Normalization(np.zeros(23), np.ones(23), np.zeros(6), np.ones(6))
    features = torch.ones((2, 23), dtype=torch.float64)
    target = torch.ones((2, 6), dtype=torch.float64)
    normalized_features = normalization.normalize_features(features)
    normalized_target = normalization.normalize_target(target)
    restored_target = normalization.denormalize_target(normalized_target)
    assert normalized_features.dtype == features.dtype and normalized_features.device == features.device
    assert normalized_target.dtype == target.dtype and normalized_target.device == target.device
    assert torch.allclose(restored_target, target)
    if torch.cuda.is_available():
        gpu_features = features.to("cuda")
        gpu_target = target.to("cuda")
        assert normalization.normalize_features(gpu_features).device.type == "cuda"
        assert normalization.denormalize_target(normalization.normalize_target(gpu_target)).device.type == "cuda"


def test_kill_resume_restores_rng_optimizer_sampler_and_history_exactly(tmp_path):
    manifest = tiny_manifest(tmp_path)
    full_path, partial_path, resumed_path = (tmp_path / name for name in ("full.pt", "partial.pt", "resumed.pt"))
    with CoreDataset(manifest, tmp_path) as data:
        full = train_model(data, model_kind="mlp", seed=17, updates=4, centers_per_update=1,
                           hidden=8, normalization_transitions=1, checkpoint=full_path,
                           checkpoint_every=1, validation_every=1)
        train_model(data, model_kind="mlp", seed=17, updates=2, centers_per_update=1,
                    hidden=8, normalization_transitions=1, checkpoint=partial_path,
                    checkpoint_every=1, validation_every=1)
        resumed = train_model(data, model_kind="mlp", seed=17, updates=4, centers_per_update=1,
                              hidden=8, normalization_transitions=1, checkpoint=resumed_path,
                              resume=partial_path, checkpoint_every=1, validation_every=1)
        full_payload = load_training_checkpoint(full_path, restore_rng=False)
        resumed_payload = load_training_checkpoint(resumed_path, restore_rng=False)
    for key, value in full_payload["model_state"].items():
        assert torch.equal(value, resumed_payload["model_state"][key])
    assert full_payload["optimizer_state"]["param_groups"] == resumed_payload["optimizer_state"]["param_groups"]
    for parameter_id, full_state in full_payload["optimizer_state"]["state"].items():
        resumed_state = resumed_payload["optimizer_state"]["state"][parameter_id]
        for key, value in full_state.items():
            assert torch.equal(value, resumed_state[key])
    assert resumed["history"] == full["history"]
    assert resumed["validation_history"] == full["validation_history"]
    assert resumed["sampler"]["draws"] == full["sampler"]["draws"] == 4


def test_real_process_kill_after_checkpoint_resumes_equivalently(tmp_path):
    manifest = tiny_manifest(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    killed_checkpoint = tmp_path / "killed.pt"
    child = subprocess.Popen([
        sys.executable, "scripts/core_learning.py", "train",
        "--manifest", str(manifest_path), "--data-root", str(tmp_path),
        "--model", "mlp", "--seed", "17", "--updates", "100000",
        "--centers", "1", "--hidden", "8", "--normalization-transitions", "1",
        "--checkpoint", str(killed_checkpoint), "--checkpoint-every", "1",
        "--log-every", "100000", "--validation-every", "0", "--device", "cpu",
        "--output", str(tmp_path / "killed.json"),
    ], cwd=Path(__file__).resolve().parents[1], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    observed = False
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and child.poll() is None:
            if killed_checkpoint.exists():
                # Freeze the worker before reading the atomically published
                # file; otherwise a tiny fixture can advance several updates
                # between the directory poll and torch.load.
                child.send_signal(signal.SIGSTOP)
                try:
                    payload = load_training_checkpoint(killed_checkpoint, restore_rng=False)
                    if int(payload["update"]) >= 1:
                        observed = True
                        child.kill()
                        break
                except Exception:
                    child.send_signal(signal.SIGCONT)
            time.sleep(.01)
        if child.poll() is None:
            child.kill()
        return_code = child.wait(timeout=10)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
    assert observed and return_code == -signal.SIGKILL

    full_path, resumed_path = tmp_path / "full-process.pt", tmp_path / "resumed-process.pt"
    with CoreDataset(manifest, tmp_path) as data:
        full = train_model(data, model_kind="mlp", seed=17, updates=4, centers_per_update=1,
                           hidden=8, normalization_transitions=1, checkpoint=full_path,
                           checkpoint_every=1, validation_every=0)
        resumed = train_model(data, model_kind="mlp", seed=17, updates=4, centers_per_update=1,
                              hidden=8, normalization_transitions=1, checkpoint=resumed_path,
                              resume=killed_checkpoint, checkpoint_every=1, validation_every=0)
        full_payload = load_training_checkpoint(full_path, restore_rng=False)
        resumed_payload = load_training_checkpoint(resumed_path, restore_rng=False)
    for key, value in full_payload["model_state"].items():
        assert torch.equal(value, resumed_payload["model_state"][key])
    assert resumed["history"] == full["history"]


def test_milestone_rollouts_are_consumed_and_resume_deduplicates(tmp_path, monkeypatch):
    """Exercise the in-process queue with short test-only milestone numbers."""
    manifest = tiny_manifest(tmp_path)
    template = manifest["cases"][0]
    for family_index in range(3):
        for case_index in range(4):
            row = copy.deepcopy(template)
            row.update(
                case_id=f"validation-f{family_index}-{case_index}",
                physical_case_id=f"validation-f{family_index}-{case_index}",
                lineage_group_id=f"validation-f{family_index}-{case_index}",
                family=f"F{family_index + 1}", split="validation",
                evaluation_role="validation",
            )
            manifest["cases"].append(row)
    # The production constant remains the frozen 8/16/24/32k protocol. This
    # local substitution only makes the scheduler/recovery behavior cheap to
    # test with the same persistence and deduplication code paths.
    monkeypatch.setattr(learning, "MILESTONE_UPDATES", (2, 4))
    partial_path = tmp_path / "partial.pt"
    with CoreDataset(manifest, tmp_path) as data:
        partial = learning.train_model(
            data, model_kind="mlp", seed=17, updates=2, centers_per_update=1,
            hidden=8, normalization_transitions=1, checkpoint=partial_path,
            checkpoint_every=1, validation_every=0, log_every=10,
        )
        assert [row["update"] for row in partial["milestone_evaluations"]] == [2]
        assert partial["milestone_evaluations"][0]["validation_case_count"] == 12
        assert partial["milestone_evaluations"][0]["metrics"]["registered_cases"] == 12
        assert (tmp_path / "partial.step-00000002.evaluation.json").is_file()
        resumed = learning.train_model(
            data, model_kind="mlp", seed=17, updates=4, centers_per_update=1,
            hidden=8, normalization_transitions=1, checkpoint=tmp_path / "resumed.pt",
            resume=partial_path, checkpoint_every=1, validation_every=0, log_every=10,
        )
    updates = [row["update"] for row in resumed["milestone_evaluations"]]
    assert updates == [2, 4]
    assert len(updates) == len(set(updates))
    assert [row["status"] for row in resumed["milestone_evaluation_plan"]] == ["completed", "completed"]
    assert all("evaluation_path" in row for row in resumed["milestone_evaluation_plan"])
    assert all(row["validation_case_count"] == 12 for row in resumed["milestone_evaluations"])


def _minimal_milestone_evaluation_fixture(tmp_path):
    manifest = tiny_manifest(tmp_path)
    manifest["cases"][0]["split"] = "validation"
    checkpoint_path = tmp_path / "model.step-00000002.pt"
    checkpoint_path.write_bytes(b"hash-bound checkpoint")
    checkpoint = {
        "path": str(checkpoint_path), "sha256": sha256_file(checkpoint_path),
        "bytes": checkpoint_path.stat().st_size, "update": 2,
    }
    return manifest, checkpoint


def _minimal_milestone_evaluation(data, checkpoint):
    from scripts.core_evaluation import aggregate_cases, score_case

    validation_cases = tuple(data.case_ids("validation"))
    validation_registry = {
        case_id: data.record(case_id)["family"] for case_id in validation_cases
    }
    case_rows, scores, denominators = {}, {}, {}
    for case_id in validation_cases:
        expected_frames = len(data.times(case_id)) - 1
        length_m, speed_mps = _characteristic_scales(data.known_inputs(case_id))
        denominators[case_id] = {
            "expected_frames": expected_frames,
            "length_m": length_m,
            "speed_mps": speed_mps,
        }
        rollout = {
            "expected_frames": expected_frames,
            "position_rmse": [0.0] * expected_frames,
            "velocity_rmse": [0.0] * expected_frames,
            "executed": True,
            "failure_category": None,
        }
        score = score_case(
            rollout["position_rmse"], rollout["velocity_rmse"],
            expected_frames=expected_frames, length_m=length_m,
            speed_mps=speed_mps, executed=True, failure_category=None,
        )
        scores[case_id] = score
        case_rows[case_id] = {"score": score, "rollout": rollout}
    return {
        "schema": "core.milestone_evaluation.v1", "update": 2,
        "split": "validation", "test_included": False,
        "checkpoint": copy.deepcopy(checkpoint),
        "validation_case_count": len(validation_cases),
        "family_registry": validation_registry,
        "fixed_denominator": denominators,
        "cases": case_rows,
        "metrics": aggregate_cases(validation_registry, scores),
        "execution_summary": {"registered_case_count": len(validation_cases)},
    }


def test_milestone_evaluation_rejects_original_checkpoint_hash_mismatch(tmp_path):
    manifest, checkpoint = _minimal_milestone_evaluation_fixture(tmp_path)
    with CoreDataset(manifest, tmp_path) as data:
        report = _minimal_milestone_evaluation(data, checkpoint)
        report["checkpoint"]["sha256"] = "0" * 64
        with pytest.raises(ValueError, match="checkpoint hash mismatch"):
            _validate_milestone_evaluation(
                report, dataset=data, checkpoint=checkpoint,
                validation_cases=data.case_ids("validation"),
                validation_registry={"tiny": "F3"},
            )


def test_milestone_evaluation_rejects_tampered_self_reported_hash(tmp_path):
    manifest, checkpoint = _minimal_milestone_evaluation_fixture(tmp_path)
    attacker_checkpoint = tmp_path / "attacker.pt"
    attacker_checkpoint.write_bytes(b"tampered evaluation binding")
    with CoreDataset(manifest, tmp_path) as data:
        report = _minimal_milestone_evaluation(data, checkpoint)
        report["checkpoint"] = {
            "path": str(attacker_checkpoint),
            "sha256": sha256_file(attacker_checkpoint),
            "bytes": attacker_checkpoint.stat().st_size,
            "update": 2,
        }
        with pytest.raises(ValueError, match="checkpoint hash mismatch"):
            _validate_milestone_evaluation(
                report, dataset=data, checkpoint=checkpoint,
                validation_cases=data.case_ids("validation"),
                validation_registry={"tiny": "F3"},
            )


def test_milestone_evaluation_accepts_hash_bound_ledger_reference(tmp_path):
    manifest, checkpoint = _minimal_milestone_evaluation_fixture(tmp_path)
    with CoreDataset(manifest, tmp_path) as data:
        report = _minimal_milestone_evaluation(data, checkpoint)
        assert _validate_milestone_evaluation(
            report, dataset=data, checkpoint=checkpoint,
            validation_cases=data.case_ids("validation"),
            validation_registry={"tiny": "F3"},
        ) == report


def test_milestone_selection_rejects_incomplete_case_sidecar(tmp_path, monkeypatch):
    manifest = tiny_manifest(tmp_path)
    template = manifest["cases"][0]
    for family_index in range(3):
        for case_index in range(4):
            row = copy.deepcopy(template)
            row.update(case_id=f"validation-f{family_index}-{case_index}",
                       physical_case_id=f"validation-f{family_index}-{case_index}",
                       lineage_group_id=f"validation-f{family_index}-{case_index}",
                       family=f"F{family_index + 1}",
                       split="validation", evaluation_role="validation")
            manifest["cases"].append(row)
    monkeypatch.setattr(learning, "MILESTONE_UPDATES", (2, 4))
    with CoreDataset(manifest, tmp_path) as data:
        receipt = learning.train_model(
            data, model_kind="mlp", seed=17, updates=2, centers_per_update=1,
            hidden=8, normalization_transitions=1, checkpoint=tmp_path / "bound.pt",
            checkpoint_every=1, validation_every=0, log_every=10,
        )
        report = copy.deepcopy(receipt["milestone_evaluations"][0])
        report["cases"].pop(next(iter(report["cases"])))
        with pytest.raises(ValueError, match="missing validation cases"):
            _validate_milestone_evaluation(
                report, dataset=data,
                checkpoint=report["checkpoint"],
                validation_cases=data.case_ids("validation"),
                validation_registry={case_id: data.record(case_id)["family"]
                                     for case_id in data.case_ids("validation")},
            )


def test_milestone_selection_rejects_tampered_aggregate_metrics(tmp_path, monkeypatch):
    manifest = tiny_manifest(tmp_path)
    template = manifest["cases"][0]
    for family_index in range(3):
        for case_index in range(4):
            row = copy.deepcopy(template)
            row.update(case_id=f"validation-f{family_index}-{case_index}",
                       physical_case_id=f"validation-f{family_index}-{case_index}",
                       lineage_group_id=f"validation-f{family_index}-{case_index}",
                       family=f"F{family_index + 1}", split="validation",
                       evaluation_role="validation")
            manifest["cases"].append(row)
    monkeypatch.setattr(learning, "MILESTONE_UPDATES", (2, 4))
    with CoreDataset(manifest, tmp_path) as data:
        receipt = learning.train_model(
            data, model_kind="mlp", seed=17, updates=2, centers_per_update=1,
            hidden=8, normalization_transitions=1, checkpoint=tmp_path / "bound.pt",
            checkpoint_every=1, validation_every=0, log_every=10,
        )
        report = copy.deepcopy(receipt["milestone_evaluations"][0])
        report["metrics"]["selection_score"] = 0.0
        with pytest.raises(ValueError, match="aggregate metrics mismatch"):
            _validate_milestone_evaluation(
                report, dataset=data,
                checkpoint=report["checkpoint"],
                validation_cases=data.case_ids("validation"),
                validation_registry={case_id: data.record(case_id)["family"]
                                     for case_id in data.case_ids("validation")},
            )


def test_milestone_selection_rejects_truncated_rollout_arrays(tmp_path, monkeypatch):
    manifest = tiny_manifest(tmp_path)
    template = manifest["cases"][0]
    for family_index in range(3):
        for case_index in range(4):
            row = copy.deepcopy(template)
            row.update(case_id=f"validation-f{family_index}-{case_index}",
                       physical_case_id=f"validation-f{family_index}-{case_index}",
                       lineage_group_id=f"validation-f{family_index}-{case_index}",
                       family=f"F{family_index + 1}", split="validation",
                       evaluation_role="validation")
            manifest["cases"].append(row)
    monkeypatch.setattr(learning, "MILESTONE_UPDATES", (2, 4))
    with CoreDataset(manifest, tmp_path) as data:
        receipt = learning.train_model(
            data, model_kind="mlp", seed=17, updates=2, centers_per_update=1,
            hidden=8, normalization_transitions=1, checkpoint=tmp_path / "bound.pt",
            checkpoint_every=1, validation_every=0, log_every=10,
        )
        report = copy.deepcopy(receipt["milestone_evaluations"][0])
        case_id = next(iter(report["cases"]))
        report["cases"][case_id]["rollout"]["position_rmse"].pop()
        with pytest.raises(ValueError, match="frame coverage mismatch"):
            _validate_milestone_evaluation(
                report, dataset=data,
                checkpoint=report["checkpoint"],
                validation_cases=data.case_ids("validation"),
                validation_registry={case_id: data.record(case_id)["family"]
                                     for case_id in data.case_ids("validation")},
            )


def test_milestone_selection_rejects_tampered_case_score(tmp_path, monkeypatch):
    manifest = tiny_manifest(tmp_path)
    template = manifest["cases"][0]
    for family_index in range(3):
        for case_index in range(4):
            row = copy.deepcopy(template)
            row.update(case_id=f"validation-f{family_index}-{case_index}",
                       physical_case_id=f"validation-f{family_index}-{case_index}",
                       lineage_group_id=f"validation-f{family_index}-{case_index}",
                       family=f"F{family_index + 1}", split="validation",
                       evaluation_role="validation")
            manifest["cases"].append(row)
    monkeypatch.setattr(learning, "MILESTONE_UPDATES", (2, 4))
    with CoreDataset(manifest, tmp_path) as data:
        receipt = learning.train_model(
            data, model_kind="mlp", seed=17, updates=2, centers_per_update=1,
            hidden=8, normalization_transitions=1, checkpoint=tmp_path / "bound.pt",
            checkpoint_every=1, validation_every=0, log_every=10,
        )
        report = copy.deepcopy(receipt["milestone_evaluations"][0])
        case_id = next(iter(report["cases"]))
        report["cases"][case_id]["score"]["selection_score"] = 0.0
        with pytest.raises(ValueError, match="case score mismatch"):
            _validate_milestone_evaluation(
                report, dataset=data,
                checkpoint=report["checkpoint"],
                validation_cases=data.case_ids("validation"),
                validation_registry={case_id: data.record(case_id)["family"]
                                     for case_id in data.case_ids("validation")},
            )


def test_completed_formal_milestones_use_registered_selector():
    reports = []
    for update, score in zip(MILESTONE_UPDATES, (.4, .2, .3, .1)):
        reports.append({
            "update": update, "split": "validation", "formal_eligible": True,
            "checkpoint": {"path": f"step-{update}.pt", "sha256": "a" * 64},
            "metrics": {"complete_fraction": 1.0, "selection_score": score,
                        "missing_execution": 0},
        })
    selected, error = learning.select_completed_milestones(reports)
    assert error is None and selected["update"] == MILESTONE_UPDATES[3]


def test_four_milestone_rollouts_are_validation_only_and_select_with_hashes(tmp_path):
    manifest = tiny_manifest(tmp_path)
    template = manifest["cases"][0]
    for index in range(4):
        source = tmp_path / template["hdf5"]
        target = tmp_path / f"validation-{index}.h5"
        shutil.copyfile(source, target)
        row = copy.deepcopy(template)
        row.update(case_id=f"validation-{index}", physical_case_id=f"validation-{index}",
                   lineage_group_id=f"validation-{index}", split="validation",
                   hdf5=target.name, sha256=sha256_file(target),
                   bytes=target.stat().st_size, evaluation_role="validation")
        manifest["cases"].append(row)
    test_row = copy.deepcopy(template)
    test_row.update(case_id="test-only", physical_case_id="test-only", lineage_group_id="test-only",
                    split="test", evaluation_role="development_extrapolation")
    manifest["cases"].append(test_row)
    receipt_rows = []
    with CoreDataset(manifest, tmp_path) as data:
        normalization = compute_normalization(data, maximum_transitions=1)
        sampler = TransitionSampler(data, centers_per_update=1, seed=17)
        model = DualIncrementModel("mlp", hidden=8)
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
        for update in MILESTONE_UPDATES:
            path = tmp_path / f"model.step-{update:08d}.pt"
            info = save_training_checkpoint(
                path, model=model, optimizer=optimizer, sampler=sampler,
                normalization=normalization, update=update, config={"update": update}, seed=17)
            receipt_rows.append(info)
        with pytest.raises(ValueError, match="3 families"):
            evaluate_checkpoints(data, receipt_rows, device="cpu", chunk_size=2,
                                 run_id="mlp-seed17")
        report = evaluate_checkpoints(data, receipt_rows, device="cpu", chunk_size=2,
                                      run_id="mlp-seed17", qualification_only=True)
    assert report["schema"] == "core.checkpoint_evaluation.v1"
    assert report["split"] == "validation" and report["test_included"] is False
    assert report["qualification_only"] is True and report["formal_eligible"] is False
    assert report["checkpoint_count"] == 4
    assert set(report["family_registry"]) == {f"validation-{index}" for index in range(4)}
    assert report["selection"]["update"] == 8000
    assert all(candidate["metrics"]["complete_fraction"] == 1.0 for candidate in report["checkpoints"])
    assert all(len(candidate["cases"]) == 4 for candidate in report["checkpoints"])
    assert all(row["score"]["expected_frames"] == 1
               for candidate in report["checkpoints"] for row in candidate["cases"].values())
    assert all(row["checkpoint"]["sha256"] for row in report["checkpoints"])
    receipt = {"checkpoints": receipt_rows + [{**receipt_rows[-1], "path": str(tmp_path / "final.pt")} ]}
    assert [Path(row["path"]).name for row in checkpoint_refs_from_receipt(receipt)] == [
        f"model.step-{update:08d}.pt" for update in MILESTONE_UPDATES
    ]
    manifest_path = tmp_path / "formal-manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    cli_output = tmp_path / "formal-evaluation.json"
    argv = ["evaluate-checkpoints", "--manifest", str(manifest_path), "--data-root", str(tmp_path)]
    for row in receipt_rows:
        argv.extend(("--checkpoint", row["path"]))
    argv.extend(("--output", str(cli_output), "--run-id", "mlp-seed17", "--qualification-only"))
    assert main(argv) == 0
    assert json.loads(cli_output.read_text())["selection"]["update"] == 8000
