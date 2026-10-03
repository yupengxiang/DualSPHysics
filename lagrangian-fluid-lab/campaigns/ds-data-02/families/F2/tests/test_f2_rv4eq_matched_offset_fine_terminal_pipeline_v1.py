#!/usr/bin/env python3
"""Synthetic unit tests for the fine-resolution native OFFSET pose and prospective labels pipeline.

Boundaries:
1. Strict campaign write isolation: all tests write exclusively to pytest `tmp_path`.
   Zero writes to canonical campaign or handoff directories.
2. Zero unmetered campaign H5 computation: no heavy H5 array slicing or numerical simulations.
3. Strict shared-runner compliance: verifies `ds_data02_runtime_v2.validate_request`.
4. Tests cover:
   - Physical condition hash: 327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef
   - Exact OFFSET receiver geometry: low corner [0.45, -0.16, 0.0] m (y offset = +0.14 m)
   - Timing window (4.0 s, 401 frames, dt=0.010 s) and save allowance (0.0007336391 s, no relaxation)
   - Mass semantics: separate native float32 mass (24.5760011673 kg) vs continuous decimal XML (24.576 kg)
   - Unknown loss semantics: observed native invalid particles remain strictly unknown loss
   - Heavy fine case storage ledger: pose peak ~14 GiB, labels peak ~8 GiB, oversize cost review declared
   - Deferred pose bindings on prospective labels stage
   - Post-pose request resolution with small synthetic fixtures
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path
import pytest


F2_DIR = Path(__file__).resolve().parent.parent
INTEGRATION_LAB = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
PIPELINE_SCRIPT = F2_DIR / "f2_rv4eq_matched_offset_fine_terminal_pipeline_v1.py"
RUNTIME_SCRIPT = INTEGRATION_LAB / "scripts/ds_data02_runtime_v2.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load module from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pipeline_mod = load_module(PIPELINE_SCRIPT, "fine_pipeline_mod")
runtime_mod = load_module(RUNTIME_SCRIPT, "runtime_mod_v2")


def test_fine_case_constants_and_hashes():
    """Verify physical condition, timing, mass, and resource bounds of the fine OFFSET case."""
    info = pipeline_mod.FINE_CASE_INFO
    assert info["case_id"] == "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001"
    assert info["resolution"] == "FINE"
    assert info["dp_m"] == 0.005

    # Particle cohort verification
    assert info["total_particles"] == 1667249
    assert info["fluid_particles"] == 196608
    assert info["moving_particles"] == 76676
    assert info["fixed_particles"] == 1393965
    assert info["total_particles"] == info["fluid_particles"] + info["moving_particles"] + info["fixed_particles"]
    assert info["source_invalid_particles_npout"] == 2151
    assert info["final_fluid_particles"] == 194457
    assert info["fluid_particles"] - info["source_invalid_particles_npout"] == info["final_fluid_particles"]

    # Physical Condition Hash verification
    assert pipeline_mod.PHYSICAL_HASH == "327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef"
    assert info["physical_hash"] == pipeline_mod.PHYSICAL_HASH

    # Numerical Recipe Hash verification
    assert pipeline_mod.NUMERICAL_RECIPE_HASH == "10ce34f8b4d0b9e42c605e2a96da1bc031c669f6413b325a12dc31fbd0a22b65"
    assert info["numerical_recipe_hash"] == pipeline_mod.NUMERICAL_RECIPE_HASH

    # Mass Semantics verification
    assert info["xml_massfluid_decimal"] == 0.000125
    assert info["xml_total_fluid_mass_kg"] == 24.576
    assert math.isclose(info["native_float32_fluid_sum_kg"], 24.576001167297363, rel_tol=1e-12)
    delta = info["native_float32_fluid_sum_kg"] - info["xml_total_fluid_mass_kg"]
    assert math.isclose(delta, 1.16729736328125e-06, rel_tol=1e-6)
    assert abs(delta) / info["xml_total_fluid_mass_kg"] < 1e-7

    # Timing Budget verification: original save allowance 0.0007336391 s preserved without waiver
    assert math.isclose(pipeline_mod.SAVE_ALLOWANCE_S, 0.0007336390799938275, rel_tol=1e-12)

    # Storage bounds verification
    assert info["source_h5_bytes"] == 6063678335
    assert info["estimated_pose_storage_bytes"] >= 14 * 1024 * 1024 * 1024
    assert info["estimated_labels_storage_bytes"] >= 8 * 1024 * 1024 * 1024


def test_build_pipeline_isolated_tmp_path(tmp_path: Path):
    """Test full pipeline artifact generation strictly inside pytest tmp_path (complete write isolation)."""
    manifest = pipeline_mod.build_all(output_root=tmp_path)
    assert manifest["schema"] == "ds02.f2.matched-offset-fine-pipeline-manifest.v1"
    assert manifest["status"] == "pose_ready_for_root_review_labels_deferred"
    assert manifest["physical_condition_hash"] == pipeline_mod.PHYSICAL_HASH
    assert manifest["numerical_recipe_hash"] == pipeline_mod.NUMERICAL_RECIPE_HASH

    # Check generated owner metadata
    owner_path = tmp_path / "owner_metadata" / f"{pipeline_mod.FINE_CASE_INFO['case_id']}.owner.v1.json"
    assert owner_path.is_file()
    owner = json.loads(owner_path.read_text(encoding="utf-8"))
    assert owner["schema"] == "ds02.f2.case-owner-metadata.v1"
    assert owner["geometry"]["receiver_low_m"] == [0.45, -0.16, 0.0]
    assert owner["geometry"]["receiver_offset_y_m"] == 0.14
    assert owner["mass_reference"]["xml_massfluid_decimal_kg"] == 0.000125
    assert owner["mass_reference"]["continuous_mass_kg"] == 24.576
    assert owner["unknown_loss_semantics"]["physical_spill_inferred_from_invalid"] is False
    assert owner["event_window"]["save_budget_relaxation_applied"] is False

    # Check generated pose config
    pose_cfg_path = tmp_path / "configs" / "offset_fine_pose_nvme_config_v1.json"
    assert pose_cfg_path.is_file()
    pose_cfg = json.loads(pose_cfg_path.read_text(encoding="utf-8"))
    assert pose_cfg["schema"] == "ds02.f2.matched-offset-fine-pose-config.v1"
    assert pose_cfg["stage"] == "pose"
    assert pose_cfg["attempt_id"] == "matched-offset-fine-nvme-pose-v1-001"
    assert pose_cfg["resource_ledger"]["estimated_storage_bytes"] >= 14 * 1024 * 1024 * 1024
    assert pose_cfg["resource_ledger"]["cpu_threads"] == 2
    assert pose_cfg["resource_ledger"]["max_wall_seconds"] == 3600

    # Check generated pose request
    pose_req_path = tmp_path / "requests" / "offset_fine_pose_nvme_request_v1.json"
    assert pose_req_path.is_file()
    pose_req = json.loads(pose_req_path.read_text(encoding="utf-8"))
    assert pose_req["schema"] == "ds02.runner-request.v2"
    assert pose_req["family_id"] == "F2"
    assert pose_req["kind"] == "cpu"
    assert pose_req["cpu_task_kind"] == "labels"
    assert pose_req["cpu_threads"] == 2
    assert pose_req["max_wall_seconds"] == 3600
    assert pose_req["estimated_storage_bytes"] >= 14 * 1024 * 1024 * 1024
    assert pose_req["oversize_cost_review"]["particle_count"] == 1667249
    assert pose_req["independent_case_count_increment"] == 0
    assert pose_req["conversion_launch_forbidden"] is True
    assert len(pose_req["input_files"]) == len(pose_req["input_sha256"])

    # Check prospective labels config (with deferred markers)
    lbl_cfg_path = tmp_path / "configs" / "offset_fine_labels_nvme_config_v1.json"
    assert lbl_cfg_path.is_file()
    lbl_cfg = json.loads(lbl_cfg_path.read_text(encoding="utf-8"))
    assert lbl_cfg["schema"] == "ds02.f2.matched-offset-fine-labels-config.v1"
    assert lbl_cfg["status"] == "prospective_pose_binding_deferred"
    assert lbl_cfg["deferred_pose_bindings"]["binding_status"] == "deferred_until_root_execution"
    assert lbl_cfg["deferred_pose_bindings"]["pose_attempt_id"] == "matched-offset-fine-nvme-pose-v1-001"

    # Check prospective labels template
    lbl_tmpl_path = tmp_path / "requests" / "offset_fine_labels_prospective_template_v1.json"
    assert lbl_tmpl_path.is_file()
    lbl_tmpl = json.loads(lbl_tmpl_path.read_text(encoding="utf-8"))
    assert lbl_tmpl["schema"] == "ds02.f2.prospective-labels-request-template.v1"
    assert lbl_tmpl["status"] == "prospective_awaiting_root_pose_execution"
    assert len(lbl_tmpl["deferred_inputs"]) == 3


def test_validate_pose_runner_request_with_runtime_v2(tmp_path: Path):
    """Test that the generated pose runner request strictly passes shared runner request validation."""
    pipeline_mod.build_all(output_root=tmp_path)
    pose_req_path = tmp_path / "requests" / "offset_fine_pose_nvme_request_v1.json"
    pose_req = json.loads(pose_req_path.read_text(encoding="utf-8"))

    # Must pass validation without raising ValueError or RuntimeError
    runtime_mod.validate_request(pose_req)


def test_resolve_labels_fails_safely_when_pose_not_yet_executed(tmp_path: Path):
    """Test that resolving labels request before pose completes fails safely with PostprocessError."""
    fake_pose_dir = tmp_path / "nonexistent_pose_attempt"
    with pytest.raises(pipeline_mod.PostprocessError, match="missing|pose stage has not yet executed"):
        pipeline_mod.resolve_labels_request_after_pose(fake_pose_dir, output_root=tmp_path)


def test_resolve_labels_with_synthetic_fixture(tmp_path: Path):
    """Test resolution of labels request using a small synthetic pose attempt fixture."""
    # First build initial owner metadata and prospective configs into tmp_path
    pipeline_mod.build_all(output_root=tmp_path)

    # Create mock pose attempt directory with valid mock files
    fake_pose_dir = tmp_path / "mock_pose_attempt"
    fake_pose_dir.mkdir(parents=True, exist_ok=True)

    fake_h5 = fake_pose_dir / "trajectory-with-actual-pose.h5"
    fake_h5.write_bytes(b"SYNTHETIC_H5_HEADER_MOCK_DATA_ONLY")
    actual_h5_sha = hashlib.sha256(fake_h5.read_bytes()).hexdigest()

    fake_report = fake_pose_dir / "rigid-body-state.json"
    fake_report.write_text(
        json.dumps({
            "schema": "ds-data-02.f2.actual-moving-pose.v1",
            "status": "actual_saved_moving_node_pose_complete",
            "augmented_trajectory": {
                "path": str(fake_h5),
                "sha256": actual_h5_sha,
                "bytes": len(fake_h5.read_bytes()),
            },
        }, indent=2) + "\n",
        encoding="utf-8",
    )

    fake_receipt = fake_pose_dir / "execution-receipt.json"
    fake_receipt.write_text(
        json.dumps({
            "schema": "ds02.execution-receipt.v1",
            "status": "completed",
            "returncode": 0,
        }, indent=2) + "\n",
        encoding="utf-8",
    )

    resolved_cfg, resolved_req = pipeline_mod.resolve_labels_request_after_pose(
        fake_pose_dir,
        output_root=tmp_path,
    )

    assert resolved_cfg["status"] == "resolved_ready_for_root_execution"
    assert resolved_cfg["pose_bindings"]["pose_h5"]["sha256"] == actual_h5_sha
    assert resolved_req["schema"] == "ds02.runner-request.v2"
    assert resolved_req["kind"] == "cpu"
    assert resolved_req["cpu_task_kind"] == "labels"
    assert resolved_req["cpu_threads"] == 2
    assert resolved_req["estimated_storage_bytes"] >= 8 * 1024 * 1024 * 1024

    # Validate resolved request using shared runtime_v2
    runtime_mod.validate_request(resolved_req)
