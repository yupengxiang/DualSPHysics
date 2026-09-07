"""Regression tests for the independent R3 G4 route sidecar."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import torch


ROOT = Path(__file__).resolve().parents[2]
SIDEcar = Path(__file__).resolve().parent


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_launcher_restricts_routes_seeds_and_reserved_gpus():
    module = load_module(SIDEcar / "run_candidate.py", "r3_g4_candidate_runner_test")
    assert module.ROUTES == ("local_interaction", "physics_residual")
    assert module.SEEDS == (17, 29, 43)
    assert module.ALLOWED_GPU_INDICES == (4, 5)
    command = module.build_command(
        "local_interaction",
        17,
        SIDEcar / "results" / "x.json",
        SIDEcar / "checkpoints" / "x.pt",
        epochs=3,
        min_epochs=2,
        patience=1,
        max_particles=64,
        validation_particles=96,
        hidden=32,
        learning_rate=1e-3,
        clip_dp=0.0,
    )
    assert "--route" in command and command[command.index("--route") + 1] == "local_interaction"
    assert "--device" in command and command[command.index("--device") + 1] == "cuda"


def test_contract_audit_reports_common_inputs_and_three_seed_coverage():
    module = load_module(SIDEcar / "audit_routes.py", "r3_g4_route_audit_test")
    report = module.audit_contract()
    assert report["status"] == "complete"
    assert all(report["checks"].values())
    assert report["feature_contract"]["feature_width"] == 43
    assert report["feature_contract"]["physics_widths"] == [3]
    assert report["feature_contract"]["boundary_sidecar_schemas"] == ["boundary-sidecar-v1"]
    assert report["existing_matrix"]["found_count"] == 12


def test_route_forward_shapes_and_local_width():
    module = load_module(ROOT / "experiments/r3_g4_baselines.py", "r3_g4_route_trainer_test")
    features = torch.zeros((4, module.feature_width()))
    local = torch.zeros((4, module.LOCAL_WIDTH))
    for route in ("particle_mlp", "deepset_context", "local_interaction", "physics_residual"):
        model = module.model_for(route, module.feature_width(), 8)
        prediction = module.predict(model, route, features, local if route == "local_interaction" else None)
        assert prediction.shape == (4, 3)
        assert torch.isfinite(prediction).all()
        assert float(torch.abs(prediction).detach().max()) <= module.OUTPUT_CAP


def test_candidate_artifacts_are_explicitly_non_formal_if_present():
    path = SIDEcar / "run_manifest.json"
    if not path.is_file():
        return
    payload = json.loads(path.read_text())
    assert payload["formal_ready"] is False
    assert payload["allowed_gpu_indices"] == [4, 5]
    assert set(payload["routes"]) == {"local_interaction", "physics_residual"}
    for record in payload["runs"]:
        assert record["physical_gpu_index"] in (4, 5)
        assert record["child_visible_devices"] in ("4", "5")


def test_candidate_results_are_finite_and_current_boundary_aware_if_present():
    manifest_path = SIDEcar / "run_manifest.json"
    if not manifest_path.is_file():
        return
    manifest = json.loads(manifest_path.read_text())
    for record in manifest["runs"]:
        result = json.loads((ROOT / record["output"]).read_text())
        assert result["route"] == record["route"]
        assert result["seed"] == record["seed"]
        assert result["feature_width"] == 43
        assert result["physics_budget_scope"].startswith("diagnostic only")
        assert result["input_contract"]["initial_only_state"] == ["density", "pressure", "mass"]
        assert result["input_contract"]["boundary_geometry"].startswith("current-frame")
        for rollout in result["test_rollout"].values():
            assert rollout["status"] == "completed"
            assert rollout["boundary_source"] == "sidecar_world_triangles"
            assert rollout["boundary_available"] is True
            assert rollout["mass_identity_preserved"] is True
            assert np.isfinite(rollout["learned_rmse_over_dp"])
