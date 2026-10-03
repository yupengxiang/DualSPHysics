"""Tests for DS-DATA-02 F5 SWL Gauge Discretization Diagnostic Script (v1).

Tests operate entirely on isolated synthetic mock fixtures in tmp_path.
Zero access to actual campaign data / H5 files.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from scripts.ds_data02_f5_swl_gauge_discretization_diagnostic_v1 import (
    diagnose_gauge_comparison,
    sha256_file,
)


def _create_synthetic_comparison_report(path: Path) -> None:
    mock_data = {
        "schema": "ds02.f5.surface-first-3dp-gauge-comparison-report.v1",
        "mechanism": "runup",
        "h_ref_m": 0.4,
        "tol_relative": 0.05,
        "pairwise_comparisons": {
            "medium_vs_fine": {
                "gauges": {
                    "WG1": {
                        "relative_eta_rmse": 0.128,
                        "normalized_eta_rmse_m": 0.0512,
                        "relative_eta_max_abs": 0.437,
                        "dry_occupancy": {
                            "left_dry_samples": 0,
                            "right_dry_samples": 0,
                            "both_dry_samples": 0,
                            "both_wet_samples": 800,
                            "resolution_dropout_samples": 0,
                            "wet_only_normalized_eta_rmse_m": 0.0512,
                            "wet_only_relative_eta_rmse": 0.128,
                        },
                    },
                    "WG3": {
                        "relative_eta_rmse": 0.354,
                        "normalized_eta_rmse_m": 0.1416,
                        "relative_eta_max_abs": 1.106,
                        "dry_occupancy": {
                            "left_dry_samples": 167,
                            "right_dry_samples": 88,
                            "both_dry_samples": 66,
                            "both_wet_samples": 614,
                            "resolution_dropout_samples": 120,
                            "wet_only_normalized_eta_rmse_m": 0.0514,
                            "wet_only_relative_eta_rmse": 0.1285,
                        },
                    },
                    "WG4": {
                        "relative_eta_rmse": 0.564,
                        "normalized_eta_rmse_m": 0.2256,
                        "relative_eta_max_abs": 1.536,
                        "dry_occupancy": {
                            "left_dry_samples": 800,
                            "right_dry_samples": 690,
                            "both_dry_samples": 688,
                            "both_wet_samples": 0,
                            "resolution_dropout_samples": 112,
                            "wet_only_normalized_eta_rmse_m": None,
                            "wet_only_relative_eta_rmse": None,
                        },
                    },
                    "Crest": {
                        "relative_eta_rmse": 0.0,
                        "normalized_eta_rmse_m": 0.0,
                        "relative_eta_max_abs": 0.0,
                        "dry_occupancy": {
                            "left_dry_samples": 800,
                            "right_dry_samples": 800,
                            "both_dry_samples": 800,
                            "both_wet_samples": 0,
                            "resolution_dropout_samples": 0,
                            "wet_only_normalized_eta_rmse_m": None,
                            "wet_only_relative_eta_rmse": None,
                        },
                    },
                }
            }
        },
    }
    path.write_text(json.dumps(mock_data), encoding="utf-8")


def test_diagnose_gauge_comparison(tmp_path: Path) -> None:
    report_file = tmp_path / "mock_comparison_report.json"
    _create_synthetic_comparison_report(report_file)

    out_dir = tmp_path / "diag_out"
    res = diagnose_gauge_comparison(
        report_path=report_file,
        output_dir=out_dir,
        output_name="diag.json",
    )

    assert res["schema"] == "ds02.f5.swl-gauge-discretization-diagnostic-report.v1"
    assert res["mechanism"] == "runup"
    assert (out_dir / "diag.json").is_file()

    per_probe = res["per_probe_diagnostics"]
    assert per_probe["WG1"]["classification"] == "pure_hydrodynamic_numerical_dispersion"
    assert per_probe["WG3"]["classification"] == "mixed_hydrodynamic_and_threshold_dropout"
    assert per_probe["WG3"]["dropout_samples"] == 120
    assert per_probe["WG3"]["dropout_impact_percentage"] > 50.0

    assert per_probe["WG4"]["classification"] == "pure_resolution_threshold_activation"
    assert per_probe["WG4"]["dropout_impact_percentage"] == 100.0

    assert per_probe["Crest"]["classification"] == "permanently_dry_gauge"
    assert per_probe["Crest"]["both_dry_samples"] == 800
