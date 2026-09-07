import importlib.util
from pathlib import Path


ROOT = Path(__file__).parents[1]


def load_module():
    path = ROOT / "experiments/r3_g4_aggregate.py"
    spec = importlib.util.spec_from_file_location("r3_g4_aggregate", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _run(seed, value):
    return {
        "route": "local_interaction", "seed": seed, "parameter_count": 10,
        "epochs_run": 3, "best_epoch": 2, "training_seconds": 1.0, "inference_seconds": 0.1,
        "peak_gpu_memory_bytes": 100, "test_rollout": {
            "case_a": {
                "case_id": "case_a", "family": "F1", "background_id": "bg_a", "split": "test",
                "status": "completed", "learned_rmse_over_dp": value, "learned_ade_m": value,
                "learned_fde_m": value, "learned_velocity_rmse_mps": value,
                "learned_com_rmse_m": value, "output_saturation_fraction": 0.0,
                "constant_velocity_rmse_over_dp": 2.0, "constant_velocity_fde_m": 0.2,
                "control_source": "missing", "boundary_source": "missing", "boundary_available": False,
                "mass_identity_preserved": True,
            }
        },
    }


def test_aggregate_reports_case_bootstrap_and_route_seed_values():
    module = load_module()
    result = module.aggregate_route("local_interaction", [_run(17, 1.0), _run(29, 2.0), _run(43, 3.0)])
    assert result["seeds"] == [17, 29, 43]
    assert result["per_case"]["case_a"]["learned_position_rmse_over_dp"]["mean"] == 2.0
    assert result["macro_position_rmse_over_dp"]["bootstrap"]["cases"] == 1
    assert result["per_family"]["F1"]["position_rmse_over_dp"]["estimate"] == 2.0


def test_bootstrap_is_case_level_and_deterministic():
    module = load_module()
    first = module.bootstrap_cases([1.0, 2.0, 5.0], draws=100)
    second = module.bootstrap_cases([1.0, 2.0, 5.0], draws=100)
    assert first == second
    assert first["resampling_unit"] == "independent physical case, not frame"
