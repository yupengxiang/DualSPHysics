"""Strict compare and explicit relocation checks for reference v7."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ds_data02_stage2_observer_v6 import ObserverBindingError  # noqa: E402
from ds_data02_stage2_reference_v7 import (  # noqa: E402
    MIGRATION_SCHEMA,
    evaluate_manual_predictions_v7,
    verify_portable_source,
)


def _config() -> dict:
    return {
        "schema": "ds02.stage2.reference-observer-config.v1",
        "physical_case_id": "manufactured-v7",
        "source_binding": {"scan_path": "/tmp/scan.json", "scan_sha256": "a" * 64},
        "time_window_s": [0.0, 4.0],
        "control_duration_s": 0.9,
        "query_times_s": [0.0, 0.9, 2.0, 4.0],
        "fixed_physical_scales": {"position_scale_m": 2.0, "mass_scale_m": 2.0,
                                  "feature_time_s": 4.0},
        "mass_quantiles": [0.5, 0.75, 1.0],
        "mass_distribution": {"normalized_bin_edges": [-0.25, 0.25, 0.75, 1.25]},
        "cross_grid_policy": {"identity_binding": "source_region_and_mass_distribution"},
        "tolerance_profile": {"schema": "frozen", "mutable": False,
                               "manufactured_absolute": 1e-12},
        "manual_evaluator": {
            "schema": "ds02.stage2.manual-observation-evaluator.v1",
            "macro_total_tolerances": {"position": 0.02, "velocity": 0.05,
                                        "kinetic_energy": 0.05, "mass_fraction": 0.03,
                                        "net_flux_fraction": 0.03},
            "event_time_total_fraction": 0.01,
            "budget_fraction": 0.25,
            "identity_binding": "source_region_id",
        },
    }


def _bundles(tmp_path: Path) -> tuple[dict, dict, Path, str]:
    config_path = tmp_path / "frozen-config.json"
    config_path.write_text(json.dumps(_config(), sort_keys=True, indent=2) + "\n")
    config_hash = hashlib.sha256(config_path.read_bytes()).hexdigest()
    binding = {"catalog_sha256": "a" * 64, "case_row_sha256": "b" * 64,
               "source_hdf5_sha256": "c" * 64, "operator_config_sha256": "d" * 64}
    ref = {
        "schema": "ds02.stage2.manual-observation-reference.v1",
        "config_binding": {"path": str(config_path), "sha256": config_hash},
        "bindings": binding,
        "query_times_s": [0.0, 0.9, 2.0, 4.0],
        "budgets": {"time_fraction_used": 0.2, "output_fraction_used": 0.1},
        "macros": {"com_x": {"kind": "position", "reference_scale": 1.0,
                              "values": [0.0, 0.1, 0.2, 0.3]}},
        "events": [{"event_id": "first", "source_region_id": "rim", "zone": 0, "idp": 4,
                    "status": "observed", "event_time_s": 0.5, "feature_time_s": 1.0,
                    "saved_brackets": [[0.0, 1.0]]}],
    }
    pred = {
        "schema": "ds02.stage2.manual-observation-predictions.v1",
        "config_binding": {"path": str(config_path), "sha256": config_hash},
        "bindings": dict(binding),
        "query_times_s": [0.0, 0.9, 2.0, 4.0],
        "budgets": {"time_fraction_used": 0.2, "output_fraction_used": 0.1},
        "macros": {"com_x": [0.0, 0.1, 0.2, 0.3]},
        "events": [{"event_id": "first", "source_region_id": "rim", "zone": 8, "idp": 99,
                    "status": "observed", "event_time_s": 0.502, "feature_time_s": 1.0,
                    "saved_brackets": [[0.0, 1.0]]}],
    }
    return ref, pred, config_path, config_hash


def test_strict_compare_uses_frozen_config_and_source_region_identity(tmp_path):
    ref, pred, config_path, _ = _bundles(tmp_path)
    report = evaluate_manual_predictions_v7(ref, pred, config_path)
    assert report["status"] == "PASS_DEVELOPMENT_OBSERVABLES_V7"
    assert report["failures"] == []
    assert report["event_checks"][0]["actual_status"] == "observed"


def test_strict_compare_rejects_wrong_shape_query_inf_and_wide_threshold(tmp_path):
    ref, pred, config_path, _ = _bundles(tmp_path)
    pred["macros"]["com_x"] = [[0.0, 0.1, 0.2, 0.3]]
    report = evaluate_manual_predictions_v7(ref, pred, config_path)
    assert report["status"] == "FAIL_DEVELOPMENT_OBSERVABLES_V7"
    assert "macro.com_x.shape" in report["failures"]
    ref, pred, config_path, _ = _bundles(tmp_path)
    pred["query_times_s"][-1] = 3.9
    with pytest.raises(ObserverBindingError, match="query times"):
        evaluate_manual_predictions_v7(ref, pred, config_path)
    ref, pred, config_path, _ = _bundles(tmp_path)
    ref["macros"]["com_x"]["total_tolerance"] = float("inf")
    with pytest.raises(ObserverBindingError, match="finite"):
        evaluate_manual_predictions_v7(ref, pred, config_path)
    ref, pred, config_path, _ = _bundles(tmp_path)
    ref["macros"]["com_x"]["total_tolerance"] = 1.0
    with pytest.raises(ObserverBindingError, match="override"):
        evaluate_manual_predictions_v7(ref, pred, config_path)


def test_explicit_hash_confirmed_mtime_migration_allows_relocation_but_rejects_wrong_content(tmp_path):
    source = tmp_path / "source.json"
    relocated = tmp_path / "moved.json"
    source.write_bytes(b'{"same":true}\n')
    relocated.write_bytes(source.read_bytes())
    source_stat = source.stat()
    os.utime(relocated, ns=(source_stat.st_atime_ns + 1000, source_stat.st_mtime_ns + 1000))
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    expected = {"bytes": source_stat.st_size, "mtime_ns": source_stat.st_mtime_ns, "sha256": digest}
    with pytest.raises(ObserverBindingError, match="migration"):
        verify_portable_source(relocated, expected, verify_source_hash=False)
    migration = {
        "schema": MIGRATION_SCHEMA, "allow_mtime_change": True,
        "source_path": str(source), "relocated_path": str(relocated),
        "source_sha256": digest, "relocated_bytes": relocated.stat().st_size,
        "relocated_mtime_ns": relocated.stat().st_mtime_ns,
        "path_map": {str(source): str(relocated)},
    }
    result = verify_portable_source(relocated, expected, verify_source_hash=True, migration=migration)
    assert result["migration_used"] is True
    relocated.write_bytes(b'{"same":fals}\n')
    with pytest.raises(ObserverBindingError, match="content hash"):
        verify_portable_source(relocated, expected, verify_source_hash=True, migration=migration)
