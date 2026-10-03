"""Unit tests for DS-DATA-02 F5 Gauge Spatial Disagreement Diagnostic Script (v2).

Tests operate entirely on synthetic mock fixtures in tmp_path.
Zero access to actual campaign data / H5 files.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from scripts.ds_data02_f5_gauge_spatial_diagnostic_v2 import (
    audit_boundary_padding_and_kernel,
    audit_gauge_geometry,
    compute_bed_elevation,
    decompose_dry_occupancy_cohorts,
    execute_source_diagnostic,
)


def test_compute_bed_elevation() -> None:
    # Flat bed before toe
    assert np.isclose(compute_bed_elevation(2.00), 0.0)
    assert np.isclose(compute_bed_elevation(3.10), 0.0)
    assert np.isclose(compute_bed_elevation(3.55), 0.0)

    # Slope bed (slope = 0.280)
    # WG3 at 4.35 -> dx = 4.35 - 3.55 = 0.80 -> z = 0.80 * 0.280 = 0.224 m
    assert np.isclose(compute_bed_elevation(4.35), 0.224)

    # WG4 at 5.45 -> dx = 5.45 - 3.55 = 1.90 -> z = 1.90 * 0.280 = 0.532 m
    assert np.isclose(compute_bed_elevation(5.45), 0.532)


def test_audit_gauge_geometry() -> None:
    gauges = {
        "WG1": 2.00,
        "WG3": 4.35,
        "WG4": 5.45,
    }
    audit = audit_gauge_geometry(gauges)

    # WG1: flat bed, z_bed = 0.0, point0_z = -0.02, d_embed = 0.02 m
    assert np.isclose(audit["WG1"]["z_bed_m"], 0.0)
    assert np.isclose(audit["WG1"]["embedding_depth_below_bed_m"], 0.02)
    assert audit["WG1"]["submerged_at_rest_h0p40"] is True

    # WG3: slope, z_bed = 0.224, d_embed = 0.244 m (0.61 H)
    assert np.isclose(audit["WG3"]["z_bed_m"], 0.224)
    assert np.isclose(audit["WG3"]["embedding_depth_below_bed_m"], 0.244)
    assert np.isclose(audit["WG3"]["embedding_relative_to_H"], 0.61)

    # WG4: upper slope, z_bed = 0.532, d_embed = 0.552 m (1.38 H), dry at rest
    assert np.isclose(audit["WG4"]["z_bed_m"], 0.532)
    assert np.isclose(audit["WG4"]["embedding_depth_below_bed_m"], 0.552)
    assert audit["WG4"]["submerged_at_rest_h0p40"] is False


def test_audit_boundary_padding_and_kernel() -> None:
    resolutions = {
        "coarse": 0.050,
        "medium": 0.025,
        "fine": 0.010,
    }
    audit = audit_boundary_padding_and_kernel(resolutions)

    assert np.isclose(audit["coarse"]["boundary_padding_thickness_m"], 0.100)
    assert np.isclose(audit["fine"]["boundary_padding_thickness_m"], 0.020)

    # Initial fluid node placement shift between coarse and fine: 0.5 * (0.050 - 0.010) = 0.020 m = 0.05 H
    shift_info = audit["geometric_discretization_shift"]
    assert np.isclose(shift_info["coarse_vs_fine_fluid_node_shift_m"], 0.020)
    assert np.isclose(shift_info["shift_relative_to_H"], 0.05)
    assert shift_info["consumes_5pct_budget_at_frame0"] is True


def test_decompose_dry_occupancy_cohorts() -> None:
    n = 100
    z_bed = 0.224
    ref = np.full(n, 0.40)  # fine resolution stays wet at 0.40 m
    cand = np.full(n, 0.40)

    # Let 20 frames drop to floor (-0.02 m) in candidate (dropout artifact)
    cand[:20] = -0.02

    decomp = decompose_dry_occupancy_cohorts(ref, cand, z_bed, h_ref_m=0.40, tol_rel=0.05)
    assert decomp["total_frames"] == 100
    assert decomp["cohort_joint_wet_frames"] == 80
    assert decomp["cohort_resolution_dropout_frames"] == 20
    assert decomp["cohort_joint_dry_frames"] == 0

    # On the 80 joint wet frames, error is strictly 0.0
    assert np.isclose(decomp["wet_only_rmse_m"], 0.0)
    assert decomp["wet_only_within_5pct_gate"] is True

    # Global error is driven entirely by dropout
    assert decomp["global_relative_rmse"] > 0.05
    assert decomp["global_within_5pct_gate"] is False
    assert decomp["dropout_dominant_cause"] is True


def test_execute_source_diagnostic_end_to_end(tmp_path: Path) -> None:
    config_path = tmp_path / "diag_config.json"
    output_path = tmp_path / "diag_report.json"

    config_data = {
        "h_ref_m": 0.40,
        "tol_relative": 0.05,
        "case_scope": "SYNTHETIC_MOCK_CASE",
    }
    config_path.write_text(json.dumps(config_data, indent=2), encoding="utf-8")

    report = execute_source_diagnostic(config_path, output_path)
    assert output_path.is_file()
    assert report["schema"] == "ds02.f5.gauge-spatial-diagnostic-report.v2"
    assert "WG3" in report["gauge_physical_embedding_audit"]
    assert "geometric_discretization_shift" in report["boundary_padding_and_kernel_audit"]
