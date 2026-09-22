"""Prove that center chunking preserves the formal training objective.

These checks intentionally call the model forward directly.  They do not run
the training loop: the only gradients collected here are local autograd
derivatives of one fixed synthetic transition, with one shared complete-field
neighbor table and its immutable provenance.
"""

import numpy as np
import pytest
import torch

from scripts.core_learning import _target_tensor
from scripts.core_models import DualIncrementModel, Normalization, tensors
from scripts.core_contract import State, StepPrediction

from test_core_contract import example_known


def _synthetic_transition():
    """Return a small connected field whose graph needs more than one hop."""
    count = 7
    position = np.column_stack((.008 * np.arange(count),
                                np.zeros(count), np.full(count, .10)))
    velocity = np.column_stack((.03 * np.arange(count),
                                -.02 * np.arange(count),
                                np.full(count, .04)))
    state = State(
        0.0,
        position,
        velocity,
        np.arange(100, 100 + count),
        np.zeros(count, dtype=int),
        np.ones(count),
        np.ones(count, dtype=bool),
    )
    known = example_known()
    dt = .0125
    return state, known, dt


def _normalization():
    """Use nontrivial affine scales so the residual/prior path is exercised."""
    return Normalization(
        np.linspace(-.2, .2, 23),
        np.linspace(.7, 1.3, 23),
        np.array([.001, -.002, .003, .04, -.05, .06]),
        np.array([.2, .3, .4, .5, .6, .7]),
    )


def _loss(model, args, target, centers):
    prediction = model(*args, centers=centers)
    return torch.mean((prediction - target[centers]) ** 2)


def _full_field_loss(model, args, target):
    centers = torch.arange(args[0].shape[0], dtype=torch.long)
    return _loss(model, args, target, centers)


def _chunked_loss(model, args, target, chunk_size=2):
    centers = torch.arange(args[0].shape[0], dtype=torch.long)
    squared_errors = []
    for chunk in torch.split(centers, chunk_size):
        prediction = model(*args, centers=chunk)
        squared_errors.append((prediction - target[chunk]) ** 2)
    # Aggregate sums before taking the mean.  Averaging per-chunk means would
    # silently change the fixed denominator when the final chunk is shorter.
    return torch.cat(squared_errors, dim=0).mean()


def _loss_and_gradients(model, loss_fn):
    loss = loss_fn(model)
    parameters = tuple(model.named_parameters())
    gradients = torch.autograd.grad(loss, tuple(parameter for _, parameter in parameters))
    return loss.detach(), {
        name: gradient.detach().clone() for (name, _), gradient in zip(parameters, gradients)
    }


@pytest.mark.parametrize("model_kind", ["graph_raw", "graph_residual"])
def test_fullfield_and_chunked_loss_and_parameter_gradients_are_equivalent(model_kind):
    state, known, dt = _synthetic_transition()
    normalization = _normalization()
    args, prior, diagnostics = tensors(state, known, dt, "cpu")
    assert diagnostics["neighbor_provenance_bound"] is True
    assert args[4].required_two_hop_sources()  # the same bound object is reused below

    target = StepPrediction(
        prior[:, :3].numpy() + np.array([
            [.001, -.002, .003], [.002, -.001, .004], [.003, .001, -.002],
            [.004, .002, -.001], [.005, -.003, .002], [.006, .001, .003],
            [.007, -.002, -.003],
        ]),
        prior[:, 3:].numpy() + np.array([
            [.10, -.04, .02], [.08, -.03, .01], [.06, -.02, -.01],
            [.04, .01, .03], [.02, .03, -.02], [.01, -.01, .04],
            [.03, .02, -.03],
        ]),
    )
    target_tensor = _target_tensor(
        state, known, dt, target, prior, model_kind, "cpu", normalization
    )
    if model_kind == "graph_residual":
        # The residual route must actually use a nonzero known-force prior;
        # otherwise this test could pass while bypassing its distinct target
        # semantics.
        assert float(prior.abs().sum()) > 0.0
        raw_target = _target_tensor(
            state, known, dt, target, prior, "graph_raw", "cpu", normalization
        )
        assert not torch.equal(target_tensor, raw_target)

    torch.manual_seed(73)
    model = DualIncrementModel(model_kind, hidden=8).eval()
    full_loss, full_gradients = _loss_and_gradients(
        model, lambda current: _full_field_loss(current, args, target_tensor)
    )
    chunked_loss, chunked_gradients = _loss_and_gradients(
        model, lambda current: _chunked_loss(current, args, target_tensor)
    )

    torch.testing.assert_close(chunked_loss, full_loss, rtol=1e-6, atol=1e-7)
    assert full_gradients.keys() == chunked_gradients.keys()
    for name in full_gradients:
        torch.testing.assert_close(
            chunked_gradients[name], full_gradients[name], rtol=2e-5, atol=2e-6,
            msg=f"gradient mismatch for {model_kind}.{name}",
        )
