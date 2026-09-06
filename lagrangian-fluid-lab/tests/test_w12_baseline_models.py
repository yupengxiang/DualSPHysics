import importlib.util
from pathlib import Path

import torch


def load_training_module():
    path = Path(__file__).parents[1] / "experiments/w12/train_baseline.py"
    spec = importlib.util.spec_from_file_location("w12_train_baseline", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_both_w12_routes_map_particles_to_displacements():
    module = load_training_module()
    features = torch.randn(11, 13)
    for model in (module.ParticleMLP(13, 16), module.DeepSetContext(13, 16)):
        prediction = model(features)
        assert prediction.shape == (11, 3)
        assert torch.isfinite(prediction).all()
