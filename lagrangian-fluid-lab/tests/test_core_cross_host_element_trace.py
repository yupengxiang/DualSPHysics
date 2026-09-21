import importlib

import numpy as np
import torch


def test_capture_forward_is_transparent_to_registered_model_on_cpu_multi_chunk():
    tracer = importlib.import_module("scripts.core_cross_host_element_trace")
    models = importlib.import_module("scripts.core_models")

    torch.manual_seed(17)
    model = models.DualIncrementModel("graph_residual", hidden=8).eval()
    features = torch.randn(9, models.FEATURE_DIM, dtype=torch.float32)
    position = torch.randn(9, 3, dtype=torch.float32)
    neighbors = torch.tensor([
        [1, 2, -1], [0, 2, 3], [0, 1, 4], [1, 4, 5],
        [2, 3, 5], [3, 4, 6], [5, 7, -1], [6, 8, -1], [7, -1, -1],
    ], dtype=torch.long)
    centers = torch.tensor([0, 1, 2], dtype=torch.long)
    with torch.no_grad():
        registered = model(features, position, neighbors, 0.5, centers=centers)
        captured, trace = tracer._capture_forward(
            model, features, position, neighbors, 0.5, centers, models,
            capture=True, capture_edge_input=True,
        )
        uncaptured, no_trace = tracer._capture_forward(
            model, features, position, neighbors, 0.5,
            torch.tensor([3, 4, 5], dtype=torch.long), models,
            capture=False,
        )
        registered_second = model(
            features, position, neighbors, 0.5,
            centers=torch.tensor([3, 4, 5], dtype=torch.long),
        )

    assert torch.equal(captured, registered)
    assert torch.equal(uncaptured, registered_second)
    transparency = tracer._tensor_transparency(registered, captured)
    assert transparency["exact_equal"]
    assert transparency["max_abs_error"] == 0.0
    assert trace is not None
    assert no_trace is None
    assert len(trace["layers"]) == 2
    assert trace["encoder"].shape == (len(trace["encoder_node_index"]), 8)
    for layer in trace["layers"]:
        valid = layer["edge_valid_mask"]
        assert layer["message_raw_valid"].shape[0] == int(np.count_nonzero(valid))
        assert layer["edge_input_valid"].shape[0] == layer["message_raw_valid"].shape[0]
        assert layer["edge_destination_index_valid"].shape == layer["edge_neighbor_index_valid"].shape
        assert layer["aggregate"].shape[0] == layer["destination_node_index"].shape[0]


def test_capture_forward_does_not_mutate_model_parameters_or_input_arrays():
    tracer = importlib.import_module("scripts.core_cross_host_element_trace")
    models = importlib.import_module("scripts.core_models")

    torch.manual_seed(29)
    model = models.DualIncrementModel("graph_raw", hidden=8).eval()
    features = torch.randn(6, models.FEATURE_DIM)
    position = torch.randn(6, 3)
    neighbors = torch.tensor([
        [1, 2], [0, 2], [0, 1], [4, 5], [3, 5], [3, 4],
    ], dtype=torch.long)
    before = {name: value.detach().clone() for name, value in model.state_dict().items()}
    features_before, position_before, neighbors_before = features.clone(), position.clone(), neighbors.clone()
    with torch.no_grad():
        tracer._capture_forward(
            model, features, position, neighbors, 0.5,
            torch.tensor([0, 1], dtype=torch.long), models,
            capture=True, capture_edge_input=True,
        )
    assert all(torch.equal(value, before[name]) for name, value in model.state_dict().items())
    assert torch.equal(features, features_before)
    assert torch.equal(position, position_before)
    assert torch.equal(neighbors, neighbors_before)
