import copy
import json
from pathlib import Path

import numpy as np
import torch

from scripts import core_cross_host_canary_float64 as variant
from scripts import core_models
from scripts.core_models import DualIncrementModel, ModelPredictor, Normalization

from test_core_contract import example_known, example_state


def _normalization():
    return Normalization(np.zeros(23), np.ones(23),
                         np.zeros(6), np.ones(6))


def _paired_models(kind="graph_residual", hidden=8):
    torch.manual_seed(41)
    reference = DualIncrementModel(kind, hidden=hidden).eval()
    promoted = DualIncrementModel(kind, hidden=hidden).eval()
    promoted.load_state_dict(copy.deepcopy(reference.state_dict()))
    promoted = promoted.to(dtype=torch.float64).eval()
    return reference, promoted


def test_float64_input_contract_promotes_public_values_without_changing_neighbors():
    state, known, dt = example_state(), example_known(), .01
    model = DualIncrementModel("graph_residual", hidden=8).to(dtype=torch.float64).eval()

    args, prior, metadata = variant.build_inference_inputs(
        state=state, known=known, dt=dt,
        core_models=core_models,
        device=torch.device("cpu"), inference_dtype="float64",
    )

    assert metadata["source_features"]["dtype"] == "float32"
    assert metadata["promoted_features"]["dtype"] == "float64"
    assert metadata["positions"]["dtype"] == "float64"
    assert metadata["neighbors"]["dtype"] == "int64"
    assert metadata["prior"]["dtype"] == "float64"
    assert args[0].dtype is torch.float64
    assert args[1].dtype is torch.float64
    assert args[2].dtype is torch.int64
    assert prior.dtype is torch.float64

    reference_args, reference_prior, _ = variant.build_inference_inputs(
        state=state, known=known, dt=dt,
        core_models=core_models,
        device=torch.device("cpu"), inference_dtype="float32",
    )
    assert np.array_equal(args[2].numpy(), reference_args[2].numpy())
    assert np.array_equal(prior.detach().numpy().astype(np.float32), reference_prior.numpy())


def test_float32_variant_matches_frozen_model_predictor_on_cpu():
    state, known, dt = example_state(), example_known(), .01
    reference, promoted = _paired_models()
    normalization = _normalization()
    expected = ModelPredictor(reference, device="cpu", chunk_size=1,
                              normalization=normalization).predict_step(state, known, dt)

    observed, trace = variant.predict_step(
        state=state, known=known, dt=dt, model=promoted.to(dtype=torch.float32),
        normalization=normalization, device=torch.device("cpu"), chunk_size=1,
        core_models=core_models,
        inference_dtype="float32",
    )
    expected_values = np.column_stack((expected.displacement, expected.delta_velocity))
    observed_values = np.column_stack((observed.displacement, observed.delta_velocity))
    assert np.array_equal(observed_values, expected_values)
    assert trace["chunks"]
    assert trace["chunks"][0]["normalized_output"]["dtype"] == "float32"


def test_float64_prediction_uses_float64_model_and_shared_prior_semantics():
    state, known, dt = example_state(), example_known(), .01
    _, model = _paired_models()
    normalization = _normalization()
    observed, trace = variant.predict_step(
        state=state, known=known, dt=dt, model=model,
        normalization=normalization, device=torch.device("cpu"), chunk_size=1,
        core_models=__import__("scripts.core_models", fromlist=["core_models"]),
        inference_dtype="float64",
    )
    values = np.column_stack((observed.displacement, observed.delta_velocity))
    acceleration = known.control.acceleration(state)
    prior = np.column_stack((state.velocity * dt + .5 * acceleration * dt * dt,
                             acceleration * dt))
    assert values.shape == (state.count, 6)
    assert np.isfinite(values).all()
    assert trace["inputs"]["normalized_features"]["dtype"] == "float64"
    assert trace["chunks"][0]["normalized_output"]["dtype"] == "float64"
    # The model is not forced to emit zero residuals, but the prior is part of
    # the exact SI output path and is independently recorded at float64.
    assert trace["inputs"]["prior"]["dtype"] == "float64"
    _, direct_prior, _ = variant.build_inference_inputs(
        state=state, known=known, dt=dt, core_models=core_models,
        device=torch.device("cpu"), inference_dtype="float64")
    assert np.array_equal(direct_prior.detach().numpy(), prior)
    assert all(parameter.dtype is torch.float64 for parameter in model.parameters())


def test_variant_parser_defaults_to_diagnostic_float64_and_protocol_keeps_frozen_tolerances():
    args = variant.build_parser().parse_args([
        "--bundle-root", "/bundle", "--case-id", "case", "--output", "/out.json",
    ])
    assert args.inference_dtype == "float64"
    assert args.chunk_size == 256
    assert args.maximum_steps == 20
    contract = variant.dtype_contract(args.inference_dtype)
    assert contract["default_float32_path"] == "core_cross_host_canary.py remains frozen float32"
    assert variant.POSITION_ATOL_M == 1.0e-5
    assert variant.VELOCITY_ATOL_MPS == 1.0e-4
    assert variant.RELATIVE_TOLERANCE == 1.0e-4


def test_trajectory_sidecar_contains_actual_frames_and_is_hash_bound(tmp_path):
    path = tmp_path / "trajectory.npz"
    positions = [np.zeros((2, 3)), np.ones((2, 3))]
    velocities = [np.zeros((2, 3)), np.full((2, 3), 2.0)]
    record = variant.atomic_trajectory_arrays(
        path, positions=positions, velocities=velocities, times=[0.0, 0.01])
    assert record["frames"] == 2
    assert record["particle_count"] == 2
    assert record["dtype"] == "float64"
    assert record["sha256"] == variant.sha256_file(path)
    with np.load(path, allow_pickle=False) as archive:
        assert np.array_equal(archive["position"], np.stack(positions))
        assert np.array_equal(archive["velocity"], np.stack(velocities))
        assert np.array_equal(archive["time_s"], np.array([0.0, 0.01]))


def test_variant_registration_and_proposals_bind_only_full_sha256_values():
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "campaigns/core-v1/reproduction/core-cross-host-float64-variant-v1.json",
        root / "campaigns/core-v1/environments/cross-host-py312-torch212-cu132-v1/specs/ada-f3-cross-host-float64-canary20-v1-proposal.json",
        root / "campaigns/core-v1/environments/cross-host-py312-torch212-cu132-v1/specs/h200-f3-cross-host-float64-canary20-v1-proposal.json",
    ]

    def visit(value, key=""):
        if isinstance(value, dict):
            for name, child in value.items():
                yield from visit(child, name)
        elif isinstance(value, list):
            for child in value:
                yield from visit(child, key)
        elif key.endswith("sha256"):
            yield value

    for path in paths:
        payload = json.loads(path.read_text())
        hashes = list(visit(payload))
        assert hashes and all(isinstance(item, str) and len(item) == 64
                              and all(char in "0123456789abcdef" for char in item)
                              for item in hashes)
