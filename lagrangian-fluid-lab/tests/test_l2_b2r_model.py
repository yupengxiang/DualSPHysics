import pytest
import torch

from scripts.l2_b2r_model import (
    B2RInputContractError,
    GraphBatch,
    build_radius_graph,
    graph_model_contract,
    model_for,
    validate_causal_payload,
)


def _batch():
    position = torch.tensor(
        [[0.0, 0.0, 0.0], [0.1, 0.0, 0.0], [0.0, 0.1, 0.0], [1.0, 1.0, 1.0]],
        dtype=torch.float32,
    )
    velocity = torch.tensor(
        [[0.0, 0.0, 0.0], [0.2, 0.0, 0.0], [0.0, 0.2, 0.0], [0.0, 0.0, 0.1]],
        dtype=torch.float32,
    )
    ids = torch.tensor([40, 10, 30, 20], dtype=torch.int64)
    edge_index, edge_features = build_radius_graph(
        position, velocity, ids, radius_m=0.2, max_neighbors=2
    )
    return GraphBatch(
        position=position,
        velocity=velocity,
        node_features=torch.zeros((4, 8), dtype=torch.float32),
        edge_index=edge_index,
        edge_features=edge_features,
        interval_s=0.05,
        control_acceleration=torch.tensor([0.0, 0.0, -9.81]),
        particle_id=ids,
    )


def test_graph_builder_is_current_state_only_and_deterministic():
    batch = _batch()
    again_index, again_features = build_radius_graph(
        batch.position,
        batch.velocity,
        batch.particle_id,
        radius_m=0.2,
        max_neighbors=2,
    )
    assert torch.equal(batch.edge_index, again_index)
    assert torch.equal(batch.edge_features, again_features)
    assert batch.edge_features.shape[1] == 7
    assert batch.edge_index.shape[0] == 2


def test_graph_builder_uses_local_spatial_query_contract():
    contract = graph_model_contract(node_features=8)
    assert "spatial hash" in contract["architecture"]["neighbor_query"]
    assert "N-by-N" in contract["architecture"]["neighbor_query"]
    position = torch.tensor(
        [[0.0, 0.0, 0.0], [0.05, 0.0, 0.0], [10.0, 10.0, 10.0]], dtype=torch.float32
    )
    velocity = torch.zeros_like(position)
    edge_index, edge_features = build_radius_graph(
        position, velocity, torch.tensor([3, 1, 2]), radius_m=0.1, max_neighbors=None
    )
    assert edge_index.shape[1] == 2
    assert torch.all(edge_features[:, 6] <= 0.1)


@pytest.mark.parametrize("route", ["raw", "hybrid"])
def test_same_graph_model_supports_both_controlled_routes(route):
    model = model_for(route=route, node_features=8, hidden=16, message_steps=2)
    prediction, diagnostics = model(_batch(), return_diagnostics=True)
    assert prediction.shape == (4, 3)
    assert diagnostics["route"] == route
    assert diagnostics["posthoc_wall_projection"] is False
    assert diagnostics["output_clipping"] is False
    if route == "raw":
        assert torch.equal(diagnostics["prior_displacement"], torch.zeros_like(prediction))
    else:
        expected = _batch().velocity * 0.05 + 0.5 * torch.tensor([0.0, 0.0, -9.81]) * 0.05**2
        assert torch.allclose(diagnostics["prior_displacement"], expected)


def test_graph_model_rejects_future_state_contract_key():
    with pytest.raises(B2RInputContractError, match="future"):
        validate_causal_payload({"current": {"future_fluid_velocity": [1, 2, 3]}})
    valid = validate_causal_payload({"current_control": {"angular_velocity": [0, 0, 1]}})
    assert valid["future_fluid_or_free_body_state_allowed"] is False


def test_graph_model_rejects_invalid_edge_index():
    batch = _batch()
    bad = GraphBatch(
        position=batch.position,
        velocity=batch.velocity,
        node_features=batch.node_features,
        edge_index=torch.tensor([[0], [99]], dtype=torch.long),
        edge_features=torch.zeros((1, 7)),
        interval_s=batch.interval_s,
        control_acceleration=batch.control_acceleration,
    )
    with pytest.raises(B2RInputContractError, match="out-of-range"):
        model_for(route="raw", node_features=8)(bad)


def test_graph_contract_explicitly_disallows_hidden_corrections():
    contract = graph_model_contract(node_features=8)
    assert contract["schema"] == "l2r.b2r.graph_model.v1"
    assert contract["routes"]["raw"]["posthoc_wall_projection"] is False
    assert contract["routes"]["hybrid"]["prior"].startswith("velocity")
    assert contract["qualification_claim"] is False
