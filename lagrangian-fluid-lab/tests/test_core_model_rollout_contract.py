import numpy as np
import pytest

from scripts.core_contract import (
    Predictor,
    StepPrediction,
    apply_prediction,
    commit,
    reference_displacement_oracle,
    updater_oracle,
)
from scripts.core_learning import rollout_case
from scripts.core_models import AnalyticPredictor, CausalPredictorAdapter
from scripts.core_dataset import CoreDataset

from test_core_contract import example_known, example_state, tiny_manifest


def test_predictor_adapter_exposes_only_current_state_inputs():
    state, known = example_state(), example_known()

    class RecordingPredictor:
        def __init__(self):
            self.calls = []

        def predict_step(self, current, current_inputs, dt):
            self.calls.append((current, current_inputs, dt))
            assert current is state
            assert current_inputs is known
            return StepPrediction(np.full_like(current.position, .003),
                                  np.full_like(current.velocity, .7))

    wrapped = RecordingPredictor()
    adapter = CausalPredictorAdapter(wrapped)
    assert isinstance(adapter, Predictor)
    prediction = adapter.predict_step(state, known, .01)
    assert len(wrapped.calls) == 1
    assert wrapped.calls[0][2] == .01
    assert np.allclose(prediction.displacement, .003)
    assert np.allclose(prediction.delta_velocity, .7)


def test_commit_and_legacy_apply_alias_are_interface_equivalent():
    state, known, dt = example_state(), example_known(), .01
    predictor = CausalPredictorAdapter(AnalyticPredictor("known_force"))
    prediction = predictor.predict_step(state, known, dt)
    committed = commit(state, prediction, dt)
    legacy = apply_prediction(state, prediction, dt)
    assert np.array_equal(committed.position, legacy.position)
    assert np.array_equal(committed.velocity, legacy.velocity)
    assert committed.time_s == legacy.time_s == dt
    # The velocity target is native and independent from the displacement
    # chord.  A public commit must preserve that distinction.
    assert not np.allclose(committed.velocity - state.velocity,
                           prediction.displacement / dt)


def test_reference_displacement_oracle_reuses_commit_without_velocity_reconstruction():
    state = example_state()
    displacement = np.array([[.003, 0., -.001], [.004, .001, -.002]])
    delta_velocity = np.array([[.7, -.2, .1], [.6, -.3, .2]])
    following = type(state)(state.time_s + .01, state.position + displacement,
                            state.velocity + delta_velocity, state.particle_id,
                            state.particle_zone, state.mass, state.valid)

    prediction = reference_displacement_oracle(state, following)
    committed = commit(state, prediction, .01)
    report = updater_oracle(state, following)
    assert np.allclose(prediction.displacement, displacement, rtol=0., atol=1e-15)
    assert np.allclose(prediction.delta_velocity, delta_velocity, rtol=0., atol=1e-15)
    assert not np.allclose(prediction.displacement / .01, prediction.delta_velocity)
    assert np.array_equal(committed.position, following.position)
    assert np.array_equal(committed.velocity, following.velocity)
    assert report["dt_s"] == .01
    assert report["position_max_abs_error"] == 0.
    assert report["native_velocity_max_abs_error"] == 0.


def test_rollout_calls_predictor_before_reading_the_following_reference(tmp_path):
    manifest = tiny_manifest(tmp_path)
    with CoreDataset(manifest, tmp_path) as data:
        class GuardPredictor:
            def predict_step(self, state, known, dt):
                # The current frame is the only source read before inference.
                assert data.read_log == [("tiny", 0)]
                assert not hasattr(known, "read_state")
                return StepPrediction(np.zeros_like(state.position),
                                      np.zeros_like(state.velocity))

        result = rollout_case(data, "tiny", CausalPredictorAdapter(GuardPredictor()))
        assert result["frames_executed"] == 1
        assert data.read_log == [("tiny", 0), ("tiny", 1)]


def test_adapter_rejects_non_contract_outputs_and_nonadvancing_intervals():
    state, known = example_state(), example_known()

    class LegacyPredictor:
        def predict_step(self, *_):
            return np.zeros((state.count, 6))

    with pytest.raises(ValueError, match="StepPrediction"):
        CausalPredictorAdapter(LegacyPredictor()).predict_step(state, known, .01)
    with pytest.raises(ValueError, match="positive advancing dt"):
        CausalPredictorAdapter(AnalyticPredictor()).predict_step(state, known, 0.)
