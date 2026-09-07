import importlib.util
from pathlib import Path

import numpy as np
import torch


ROOT = Path(__file__).parents[1]


def load_module():
    path = ROOT / "experiments/r3_g4_baselines.py"
    spec = importlib.util.spec_from_file_location("r3_g4_baselines", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def tiny_case(module):
    return {
        "case_id": "tiny", "family": "F1", "split": "validation", "background_id": "tiny_bg",
        "position": np.asarray([[[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]], [[0.1, 0.0, 0.0], [2.1, 0.0, 0.0]]], dtype=np.float32),
        "velocity": np.asarray([[[1.0, 0.0, 0.0], [1.0, 0.0, 0.0]], [[1.0, 0.0, 0.0], [1.0, 0.0, 0.0]]], dtype=np.float32),
        "density0": np.asarray([1000.0, 1000.0], dtype=np.float32),
        "pressure0": np.asarray([0.0, 0.0], dtype=np.float32),
        "mass0": np.asarray([1.0, 3.0], dtype=np.float32),
        "time": np.asarray([0.0, 0.1]), "dp": 0.1, "length_scale": 2.0, "time_scale": 0.45,
        "gravity": np.asarray([0.0, 0.0, -9.81], dtype=np.float32),
        "physics": np.asarray([1.0, 0.001, 0.0], dtype=np.float32),
        "controls": np.zeros((2, module.CONTROL_WIDTH), dtype=np.float32),
        "control_source": "missing_control_group", "control_available": False,
        "boundary": np.zeros(module.BOUNDARY_WIDTH, dtype=np.float32),
        "boundary_source": "missing_boundary_sidecar", "boundary_available": False,
        "gravity_source": "default_world_z", "mass_initial_kg": 4.0,
    }


def test_feature_width_and_smooth_cap_are_finite():
    module = load_module()
    assert module.feature_width() == 43
    model = module.ParticleMLP(module.feature_width(), 8)
    features = torch.randn(5, module.feature_width())
    prediction = module.predict(model, "particle_mlp", features, None)
    assert prediction.shape == (5, 3)
    assert torch.isfinite(prediction).all()
    assert torch.abs(prediction).max() <= module.OUTPUT_CAP


def test_centering_uses_initial_mass_weighted_com_and_global_velocity():
    module = load_module()
    case = tiny_case(module)
    device = torch.device("cpu")
    target_position = torch.from_numpy(case["position"][0])
    target_velocity = torch.from_numpy(case["velocity"][0])
    context_mass = torch.from_numpy(case["mass0"])
    features = module.build_features(
        case, target_position, target_velocity, target_position, torch.from_numpy(case["velocity"][0]),
        context_mass, 0, np.arange(2), 0.1, device,
    )
    # Weighted COM is 1.5, so the first target has -0.75 in normalized units.
    assert float(features[0, 0]) == -0.75
    # Weighted COM velocity is one m/s, scaled by dt/dp = 1.
    assert torch.allclose(features[:, 6:9], torch.tensor([[1.0, 0.0, 0.0], [1.0, 0.0, 0.0]]), atol=1e-6)


def test_vector_metric_uses_vector_norm_not_flattened_components():
    module = load_module()
    rmse, ade, fde = module._metric([np.asarray([[1.0, 1.0, 1.0]])], scale=1.0)
    assert rmse == np.sqrt(3.0)
    assert ade == np.sqrt(3.0)
    assert fde == np.sqrt(3.0)


def test_next_velocity_target_is_canonical_and_not_position_displacement():
    module = load_module()
    case = tiny_case(module)
    case["velocity"][1, :, 0] = 2.0
    target = module.target_for(case, 0, np.asarray([0, 1]), "particle_mlp").numpy()
    assert np.allclose(target[:, 0], 2.0)


def test_local_features_are_bounded_and_finite():
    module = load_module()
    case = tiny_case(module)
    position = torch.from_numpy(case["position"][0])
    velocity = torch.from_numpy(case["velocity"][0])
    local = module.local_neighbour_features(position, velocity, position, velocity, case["dp"], 0.1)
    assert local.shape == (2, module.LOCAL_WIDTH)
    assert torch.isfinite(local).all()


def test_pilot_excludes_body_only_f6_case_and_declares_no_future_state():
    module = load_module()
    cases = module.load_cases(ROOT / "release/v0.1-development/manifest.json")
    assert all(case["case_id"] != "W05_F6_fine" for case in cases)
    assert all("density" not in case and "pressure" not in case for case in cases)
    model = module.model_for("physics_residual", module.feature_width(), 8)
    assert model is not None
