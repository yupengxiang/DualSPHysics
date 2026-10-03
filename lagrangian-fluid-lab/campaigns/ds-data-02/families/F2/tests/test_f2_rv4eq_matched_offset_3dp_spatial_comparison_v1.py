#!/usr/bin/env python3
"""Synthetic unit tests for the 3DP full-window transport spatial comparison runner.

Boundaries:
1. Strict campaign write isolation: all tests write exclusively to pytest `tmp_path`.
   Zero writes to canonical campaign or handoff directories.
2. Zero unmetered campaign H5 computation: no heavy H5 array slicing or numerical simulations.
3. Strict shared-runner compliance: verifies `ds_data02_runtime_v2.validate_request`.
4. Tests cover:
   - Provenance and mass semantics sidecar verification
   - Physical condition hash (327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef)
   - Exact OFFSET receiver geometry (low corner [0.45, -0.16, 0.0] m, offset y = +0.14 m)
   - Continuum initial fluid domain (0.024576 m^3, 24.576 kg) across 3DP
   - Discrete XML paths and bit-for-bit identical motion dat (ff966330...)
   - Mass ledger vs native float32 mass distinction and weight drift recording
   - Coarse/medium completed observations integration and spatial transport comparison
   - Deferred fine observation handling and post-labels synthetic fixture resolution
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
COMPARISON_SCRIPT = F2_DIR / "f2_rv4eq_matched_offset_3dp_spatial_comparison_v1.py"
RUNTIME_SCRIPT = INTEGRATION_LAB / "scripts/ds_data02_runtime_v2.py"
SIDECAR_FILE = F2_DIR / "handoff_20261003/spatial_reference_3dp_audit_v1/f2_rv4eq_matched_offset_3dp_source_provenance_and_mass_sidecar_v1.json"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load module from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


comparison_mod = load_module(COMPARISON_SCRIPT, "comparison_mod_v1")
runtime_mod = load_module(RUNTIME_SCRIPT, "runtime_mod_v2")


def test_sidecar_provenance_and_mass_semantics():
    """Verify that the sidecar documents the exact 3DP provenance, physical projection, and mass semantics."""
    assert SIDECAR_FILE.is_file()
    sidecar = json.loads(SIDECAR_FILE.read_text(encoding="utf-8"))

    # Physical condition & geometry
    cond = sidecar["physical_condition"]
    assert cond["physical_condition_hash_declared"] == comparison_mod.PHYSICAL_HASH
    assert cond["time_window"]["frames"] == 401
    assert cond["time_window"]["dt_s"] == 0.010
    assert "Save001 name historical" in cond["time_window"]["note_on_fine_naming"] or "401 frames" in cond["time_window"]["note_on_fine_naming"]
    assert cond["timing_budget"]["save_budget_relaxation_applied"] is False

    geom = cond["geometry_comparison"]
    assert geom["receiver"]["point_low_m"] == [0.45, -0.16, 0.0]
    assert geom["receiver"]["offset_y_m"] == 0.14
    assert geom["cup"]["point_low_m"] == [0.0, -0.15, 0.65]
    assert geom["catch_tray"]["point_low_m"] == [-1.20, -1.0, -0.20]
    assert geom["motion_control"]["motion_dat_sha256"] == "ff966330e01e565987ebf182a7dfd7401d76577ae1c266894fc7db4aa34c5b70"

    fluid = geom["continuum_initial_fluid_domain"]
    assert fluid["continuum_volume_m3"] == 0.024576
    assert fluid["continuum_mass_kg"] == 24.576
    assert fluid["layer_count"] == 3

    # Discrete 3DP sources
    prov = sidecar["discrete_3dp_source_provenance"]
    assert prov["coarse"]["dp_m"] == 0.010
    assert prov["coarse"]["discrete_particles"]["fluid_particles"] == 24576
    assert prov["medium"]["dp_m"] == 0.008
    assert prov["medium"]["discrete_particles"]["fluid_particles"] == 48000
    assert prov["fine"]["dp_m"] == 0.005
    assert prov["fine"]["discrete_particles"]["fluid_particles"] == 196608

    # Mass semantics and weight drift review
    mass_rev = sidecar["mass_semantics_and_weight_drift_review"]
    table = mass_rev["mass_table"]
    assert math.isclose(table["coarse"]["native_float32_sum_kg"], 24.576001167297363, rel_tol=1e-12)
    assert math.isclose(table["medium"]["native_float32_sum_kg"], 24.575999937951565, rel_tol=1e-12)
    assert math.isclose(table["fine"]["native_float32_sum_kg"], 24.576001167297363, rel_tol=1e-12)
    assert table["coarse"]["label_ledger_total_kg"] == 24.576
    assert table["medium"]["label_ledger_total_kg"] == 24.576
    assert table["fine"]["label_ledger_total_kg"] == 24.576

    unknown = mass_rev["unknown_loss_policy"]
    assert unknown["fine_invalid_particle_count"] == 2151
    assert unknown["physical_spill_inferred_from_invalid"] is False


def test_build_comparison_artifacts_isolated_tmp_path(tmp_path: Path):
    """Test full comparison artifact generation strictly inside pytest tmp_path (complete write isolation)."""
    manifest = comparison_mod.build_all(output_root=tmp_path)
    assert manifest["schema"] == "ds02.f2.matched-offset-3dp-spatial-comparison-manifest.v1"
    assert manifest["status"] == "ready_for_coarse_medium_evaluation_fine_deferred"
    assert manifest["deferred_sources"]["fine"]["status"] == "deferred_until_root_execution"

    # Check config
    cfg_path = tmp_path / "configs" / "offset_3dp_spatial_comparison_config_v1.json"
    assert cfg_path.is_file()
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert cfg["schema"] == "ds02.f2.matched-offset-3dp-spatial-comparison-config.v1"
    assert cfg["time_window"]["frames"] == 401
    assert "coarse" in cfg["completed_sources"]
    assert "medium" in cfg["completed_sources"]

    # Check request
    req_path = tmp_path / "requests" / "offset_3dp_spatial_comparison_request_v1.json"
    assert req_path.is_file()
    req = json.loads(req_path.read_text(encoding="utf-8"))
    assert req["schema"] == "ds02.runner-request.v2"
    assert req["family_id"] == "F2"
    assert req["kind"] == "cpu"
    assert req["cpu_task_kind"] == "audit"
    assert req["cpu_threads"] == 2
    assert req["max_wall_seconds"] == 3600
    assert req["conversion_launch_forbidden"] is True
    assert len(req["input_files"]) == len(req["input_sha256"])


def test_validate_runner_request_with_runtime_v2(tmp_path: Path):
    """Verify that the generated 3DP comparison request passes shared runner validation."""
    comparison_mod.build_all(output_root=tmp_path)
    req_path = tmp_path / "requests" / "offset_3dp_spatial_comparison_request_v1.json"
    req = json.loads(req_path.read_text(encoding="utf-8"))

    runtime_mod.validate_request(req)


def test_run_comparison_with_completed_coarse_medium(tmp_path: Path):
    """Test running comparison over completed coarse and medium observation reports."""
    comparison_mod.build_all(output_root=tmp_path)
    cfg_path = tmp_path / "configs" / "offset_3dp_spatial_comparison_config_v1.json"
    out_dir = tmp_path / "run_output"

    report = comparison_mod.run_comparison(cfg_path, out_dir)
    assert report["schema"] == "ds02.f2.matched-offset-3dp-spatial-comparison-report.v1"
    assert report["physical_condition_hash"] == comparison_mod.PHYSICAL_HASH

    res = report["comparison_results"]
    assert "coarse" in res
    assert "medium" in res

    # Check coarse mass observables: receiver ~3.787 kg, tray ~20.436 kg, cup = 0.0 kg
    c_mass = res["coarse"]["final_mass_kg_by_destination"]
    assert math.isclose(c_mass["receiver"], 3.787, rel_tol=1e-4)
    assert math.isclose(c_mass["tray"], 20.436, rel_tol=1e-4)
    assert c_mass["cup"] == 0.0

    # Check medium mass observables: receiver ~3.484 kg, tray ~20.712 kg, cup = 0.0 kg
    m_mass = res["medium"]["final_mass_kg_by_destination"]
    assert math.isclose(m_mass["receiver"], 3.48416, rel_tol=1e-4)
    assert math.isclose(m_mass["tray"], 20.712448, rel_tol=1e-4)
    assert m_mass["cup"] == 0.0

    assert report["scientific_summary"]["cup_empty_across_all_completed"] is True
    assert report["scientific_summary"]["receiver_offset_y_m"] == 0.14


def test_resolve_and_run_with_synthetic_fine_fixture(tmp_path: Path):
    """Test resolving prospective fine observation with a synthetic fixture and executing 3DP comparison."""
    comparison_mod.build_all(output_root=tmp_path)

    # Create mock fine observation report
    mock_fine_dir = tmp_path / "mock_fine_attempt"
    mock_fine_dir.mkdir(parents=True, exist_ok=True)
    mock_fine_obs = mock_fine_dir / "f2-v6-observations.json"
    mock_fine_receipt = mock_fine_dir / "execution-receipt.json"

    fine_data = {
        "schema": "ds-data-02.f2.event-semantics.v6",
        "case_id": "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001",
        "family_id": "F2",
        "resolution": "FINE",
        "final_mass_kg_by_destination": {
            "cup": 0.0,
            "receiver": 3.350,
            "tray": 20.850,
            "inflight": 0.250,
            "unknown": 0.126,
        },
        "native_mass_and_weights": {
            "xml_continuous_fluid_mass_kg": 24.576,
            "xml_decimal_massfluid_kg": 0.000125,
            "native_float32_fluid_sum_kg": 24.576001167297363,
            "delta_native_minus_xml_kg": 1.1672973627696592e-06,
        },
        "residence": {
            "fractional_cohort_time_by_destination": {"receiver": 0.14, "tray": 0.84},
        },
    }
    mock_fine_obs.write_text(json.dumps(fine_data, indent=2) + "\n", encoding="utf-8")
    mock_fine_receipt.write_text(json.dumps({"status": "completed", "returncode": 0}, indent=2) + "\n", encoding="utf-8")

    resolved_cfg, resolved_req = comparison_mod.resolve_comparison_with_fine_observation(
        mock_fine_obs,
        mock_fine_receipt,
        output_root=tmp_path,
    )

    assert resolved_cfg["status"] == "all_three_sources_resolved"
    assert "fine" in resolved_cfg["completed_sources"]
    assert resolved_req["status"] == "fully_resolved_ready_for_3dp_execution"

    # Validate resolved request using shared runtime
    runtime_mod.validate_request(resolved_req)

    # Run full 3DP comparison with the mock fine fixture
    out_dir = tmp_path / "3dp_run_output"
    cfg_file = tmp_path / "configs" / "offset_3dp_spatial_comparison_config_v1.json"
    rep = comparison_mod.run_comparison(cfg_file, out_dir)
    assert len(rep["comparison_results"]) == 3
    assert "fine" in rep["comparison_results"]
    assert rep["comparison_results"]["fine"]["receiver_mass_kg"] == 3.350
