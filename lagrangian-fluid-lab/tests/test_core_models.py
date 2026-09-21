import numpy as np
import pytest
import torch

from scripts.core_models import (AnalyticPredictor, DualIncrementModel, ModelPredictor,
                                 Normalization, neighbor_table, nearest_geometry, tensors,
                                 two_hop_halo)
from scripts.core_contract import PrescribedGeometry, State, StepPrediction
from scripts.core_learning import _target_tensor

from test_core_contract import example_known, example_state


def _grid_state():
    position = np.array([
        [0.00, 0.00, 0.10], [0.01, 0.00, 0.10], [-0.01, 0.00, 0.10],
        [0.00, 0.01, 0.10], [0.00, -0.01, 0.10], [0.05, 0.00, 0.10],
    ])
    ids = np.array([50, 3, 4, 2, 1, 9])
    return State(0., position, np.zeros_like(position), ids, np.zeros(len(ids), dtype=int),
                 np.ones(len(ids)), np.ones(len(ids), dtype=bool))


def test_neighbors_use_complete_field_distance_then_identity_order():
    state = _grid_state()
    table, diagnostics = neighbor_table(state, .01, limit=3)
    # Center 0 sees the four equidistant points at .01; IDs, rather than the
    # input array order, resolve the tie. The point at .05 is outside 2h.
    assert table[0, :3].tolist() == [4, 3, 1]
    assert np.all(table[:, 3:] == -1)
    assert diagnostics["field_particle_count"] == 6
    assert diagnostics["neighbor_truncation_fraction"] > 0


def test_two_hop_halo_and_edge_contract_are_explicit():
    state = _grid_state()
    table, _ = neighbor_table(state, .01, limit=64)
    centers = np.array([0])
    one, two = two_hop_halo(centers, table)
    assert 0 in one and set(one) <= set(two)
    model = DualIncrementModel("graph_raw", hidden=64)
    assert model.messages[0][0].in_features == 2 * 64 + 7
    args, _, _ = tensors(state, example_known(), .01, "cpu")
    output = model(*args, centers=torch.tensor([0]))
    assert output.shape == (1, 6)


def test_halo_rejects_truncated_or_out_of_axis_neighbor_tables():
    centers = np.array([0], dtype=np.int64)
    with pytest.raises(ValueError, match="particle axis"):
        two_hop_halo(centers, np.array([[1]], dtype=np.int64), n=2)
    with pytest.raises(ValueError, match="outside particle field"):
        two_hop_halo(centers, np.array([[2], [0]], dtype=np.int64))
    with pytest.raises(ValueError, match="integer"):
        two_hop_halo([0], np.array([[1.5], [0.0]]))


def test_graph_chunking_preserves_full_field_predictions():
    state, known, dt = example_state(), example_known(), .01
    for kind in ("mlp", "graph_raw", "graph_residual"):
        torch.manual_seed(23)
        model = DualIncrementModel(kind, hidden=8)
        whole = ModelPredictor(model, chunk_size=state.count).predict_step(state, known, dt)
        chunked = ModelPredictor(model, chunk_size=1).predict_step(state, known, dt)
        assert np.allclose(whole.displacement, chunked.displacement, rtol=1e-6, atol=1e-7)
        assert np.allclose(whole.delta_velocity, chunked.delta_velocity, rtol=1e-6, atol=1e-7)


def test_same_seed_pairs_common_encoder_and_head_across_baselines():
    torch.manual_seed(17)
    mlp = DualIncrementModel("mlp", hidden=8)
    torch.manual_seed(17)
    raw = DualIncrementModel("graph_raw", hidden=8)
    torch.manual_seed(17)
    residual = DualIncrementModel("graph_residual", hidden=8)
    for left, right in ((mlp, raw), (raw, residual)):
        assert all(torch.equal(a, b) for a, b in zip(left.encoder.parameters(), right.encoder.parameters()))
        assert all(torch.equal(a, b) for a, b in zip(left.head.parameters(), right.head.parameters()))
    assert all(torch.equal(a, b) for a, b in zip(raw.parameters(), residual.parameters()))


def test_graph_loss_backpropagates_through_two_hop_source():
    # 0 sees 1, while 2 is only reachable through 1.  A center-only loss
    # must still carry a gradient to that second-hop full-field feature.
    torch.manual_seed(19)
    model = DualIncrementModel("graph_raw", hidden=8)
    features = torch.ones((3, 23), dtype=torch.float32, requires_grad=True)
    position = torch.tensor([[0., 0., 0.], [.015, 0., 0.], [.030, 0., 0.]])
    neighbors = torch.tensor([[1, -1], [0, 2], [1, -1]], dtype=torch.long)
    output = model(features, position, neighbors, .01, centers=torch.tensor([0]))
    output.square().sum().backward()
    assert torch.isfinite(features.grad).all()
    assert float(features.grad[2].abs().sum()) > 0.0


def test_all_baselines_emit_dual_increment_and_residual_adds_known_prior():
    state, known, dt = example_state(), example_known(), .01
    args, prior, _ = tensors(state, known, dt, "cpu")
    normalization = Normalization(np.zeros(23), np.ones(23), np.zeros(6), np.ones(6))
    model = DualIncrementModel("graph_residual", hidden=8)
    for parameter in model.parameters():
        torch.nn.init.zeros_(parameter)
    prediction = ModelPredictor(model, normalization=normalization, chunk_size=1).predict_step(state, known, dt)
    assert np.allclose(np.column_stack((prediction.displacement, prediction.delta_velocity)), prior.numpy())
    for kind in ("mlp", "graph_raw", "graph_residual"):
        output = DualIncrementModel(kind, hidden=8)(*args, centers=torch.tensor([0, 1]))
        assert output.shape == (2, 6)


def test_prescribed_rotation_wall_velocity_uses_each_nearest_surface_point():
    geometry = PrescribedGeometry(
        triangles=np.array([[[1., 0., 0.], [2., 0., 0.], [1., 0., 1.]]]),
        component_id=np.array([0]), body_id=np.array([0]), wall_velocity=np.zeros((1, 3)),
        coordinate_frame="test", sample_times=np.array([0., 1.]),
        sample_angles_degrees=np.array([0., 30.]), axis_point=np.zeros(3),
        axis_direction=np.array([0., 1., 0.]), moving_body_id=0)
    snapshot = geometry.at(.5)
    # Both queries project to the same moving triangle, but have different
    # radii.  A centroid-constant velocity would incorrectly make them equal.
    a, b, c = snapshot.triangles[0]
    surface = np.array([.6 * a + .2 * b + .2 * c, .2 * a + .6 * b + .2 * c])
    query = surface + np.array([0., .1, 0.])
    _, _, velocity = nearest_geometry(query, snapshot)
    omega = np.array([0., np.deg2rad(30.), 0.])
    expected = np.cross(np.broadcast_to(omega, (2, 3)), surface)
    assert np.allclose(velocity, expected)
    assert not np.allclose(velocity[0], velocity[1])


def test_known_force_residual_units_prior_and_shared_denormalization_are_equivalent():
    state, known, dt = example_state(time=0.2), example_known(), .025
    args, prior, _ = tensors(state, known, dt, "cpu")
    acceleration = known.control.acceleration(state)
    expected_prior = np.column_stack((
        state.velocity * dt + .5 * acceleration * dt * dt,
        acceleration * dt,
    ))
    assert np.allclose(prior.numpy(), expected_prior, rtol=0., atol=2e-7)

    # Use a nontrivial target scale to exercise raw SI units through the
    # residual subtraction and the later denormalization/add-back path.
    residual = np.array([
        [.001, -.002, .003, .11, -.07, .05],
        [-.004, .005, -.006, -.03, .02, -.09],
    ])
    target = StepPrediction(expected_prior[:, :3] + residual[:, :3],
                            expected_prior[:, 3:] + residual[:, 3:])
    normalization = Normalization(
        np.zeros(23), np.ones(23),
        np.array([.01, -.02, .03, .04, -.05, .06]),
        np.array([.2, .3, .4, .5, .6, .7]))
    raw_encoded = _target_tensor(state, known, dt, target, prior, "graph_raw", "cpu", normalization)
    residual_encoded = _target_tensor(state, known, dt, target, prior,
                                      "graph_residual", "cpu", normalization)
    recovered = normalization.denormalize_target(residual_encoded) + prior
    assert np.allclose(recovered.numpy(), np.column_stack((target.displacement,
                                                            target.delta_velocity)),
                       rtol=0., atol=2e-7)
    assert not torch.allclose(raw_encoded, residual_encoded)

    class ResidualStub(torch.nn.Module):
        kind = "graph_residual"

        def __init__(self, encoded):
            super().__init__()
            self.register_buffer("encoded", encoded)

        def forward(self, features, position, neighbors, h, centers=None):
            return self.encoded[centers]

    predictor = ModelPredictor(ResidualStub(residual_encoded), normalization=normalization,
                               chunk_size=1)
    prediction = predictor.predict_step(state, known, dt)
    assert np.allclose(np.column_stack((prediction.displacement, prediction.delta_velocity)),
                       np.column_stack((target.displacement, target.delta_velocity)),
                       rtol=0., atol=2e-6)
    analytic = AnalyticPredictor("known_force").predict_step(state, known, dt)
    assert np.allclose(np.column_stack((analytic.displacement, analytic.delta_velocity)),
                       expected_prior, rtol=0., atol=2e-12)
