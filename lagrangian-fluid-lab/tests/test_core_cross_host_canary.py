import numpy as np
import torch

from scripts import core_cross_host_canary as canary
from scripts.core_models import DualIncrementModel, two_hop_halo


def _ring_neighbors(count, width=4):
    rows = []
    for index in range(count):
        rows.append([(index + offset) % count for offset in range(1, width + 1)])
    return torch.tensor(rows, dtype=torch.long)


def test_trace_forward_matches_registered_graph_forward_on_cpu():
    torch.manual_seed(23)
    count = 12
    model = DualIncrementModel("graph_residual", hidden=64).eval()
    features = torch.randn(count, 23)
    position = torch.randn(count, 3)
    neighbors = _ring_neighbors(count)
    centers = torch.tensor([0, 3, 7, 11], dtype=torch.long)

    with torch.no_grad():
        expected = model(features, position, neighbors, 0.5, centers=centers)
        observed, trace = canary._trace_forward(
            model, features, position, neighbors, 0.5, centers,
            two_hop_halo, capture_encoder=True,
        )

    assert torch.equal(observed, expected)
    assert trace["encoder"]["shape"] == [count, 64]
    assert [row["destination"] for row in trace["layers"]] == ["one_hop", "centers"]
    assert all(row["aggregate"]["finite"] for row in trace["layers"])


def test_digest_is_shape_dtype_and_value_sensitive():
    left = canary.array_digest(np.array([1.0, 2.0], dtype=np.float32))
    same = canary.array_digest(np.array([1.0, 2.0], dtype=np.float32))
    changed = canary.array_digest(np.array([1.0, 2.0], dtype=np.float64))

    assert left["sha256"] == same["sha256"]
    assert left["dtype"] == "float32"
    assert changed["dtype"] == "float64"
    assert left["sha256"] != changed["sha256"]
