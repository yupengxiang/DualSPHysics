"""Minimal CPU/static regression tests for the independent R4 G4 audit."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "scripts/r4_g4_training_contract_audit.py"


def load_audit():
    spec = importlib.util.spec_from_file_location("r4_g4_training_contract_audit", AUDIT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_r4_g4_audit_is_static_and_detects_active_input_width():
    module = load_audit()
    report = module.build_audit(ROOT, inspect_checkpoints=False)

    assert report["status"] == "complete_with_findings"
    assert report["audit_execution"]["mode"] == "static_cpu"
    assert report["audit_execution"]["training_invoked"] is False
    assert report["audit_execution"]["gpu_api_invoked"] is False
    assert report["audit_execution"]["trainer_imported"] is False
    assert set(report["source"]["routes"]) == set(module.ROUTES)
    assert report["feature_contract"]["base_width"] == 43
    assert report["feature_contract"]["component_block_width"] == 72
    assert report["feature_contract"]["active_width"] == 115
    assert report["feature_contract"]["local_active_width"] == 123
    assert report["release_data"]["record_count"] == 13
    assert report["release_data"]["linked_sidecar_case_count"] == 12


def test_r4_g4_audit_separates_six_run_scope_from_current_contract():
    module = load_audit()
    report = module.build_audit(ROOT, inspect_checkpoints=False)
    small = report["artifact_collections"]["small_six_rerun"]
    finding_ids = {finding["id"] for finding in report["findings"]}

    assert small["coverage"]["found_count"] == 6
    assert small["coverage"]["all_expected_route_seed_pairs_complete"] is True
    assert set(small["expected_routes"]) == {"local_interaction", "physics_residual"}
    assert report["checks"]["small_six_has_all_four_routes"] is False
    assert report["checks"]["recorded_width_matches_current_source"] is False
    assert "current_sidecar_width_115_vs_recorded_width_43" in finding_ids
    assert "small_rerun_is_not_a_four_route_matrix" in finding_ids
    assert "deepset_train_rollout_context_cardinality_mismatch" in finding_ids
    assert report["comparability"]["current_source_comparison"]["supported"] is False


def test_r4_g4_checkpoint_inspection_uses_cpu_only():
    pytest.importorskip("torch")
    module = load_audit()
    checkpoint = ROOT / "experiments/r3-g4-baseline-routes/checkpoints/local_interaction_seed17.pt"
    info = module.inspect_checkpoint(checkpoint, ROOT)

    assert info["exists"] is True
    assert info["load_mode"] == "cpu_weights_only"
    assert info["metadata"]["route"] == "local_interaction"
    assert info["metadata"]["seed"] == 17
    assert info["metadata"]["feature_width"] == 43
    assert info["first_linear"]["input_width"] == 51
    assert info["first_linear"]["tensor_device"] == "cpu"
    assert info["has_optimizer_state"] is False
    assert info["has_rng_state"] is False


def test_r4_g4_outputs_are_independent_and_machine_readable(tmp_path):
    module = load_audit()
    report = module.build_audit(ROOT, inspect_checkpoints=False)
    json_path = tmp_path / "audit.json"
    markdown_path = tmp_path / "audit.md"
    module.write_outputs(report, json_path, markdown_path)

    assert json.loads(json_path.read_text())["scope"].startswith("R4 G4")
    markdown = markdown_path.read_text()
    assert "6 次小预算复跑：能支持什么" in markdown
    assert "下一轮统一控制输入和训练状态语义：最小改动清单" in markdown
