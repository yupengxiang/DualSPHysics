#!/usr/bin/env python3
"""Test suite for F5 Fine Halfstep Negative Result Audit and Fallback Specification."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from audit_halfstep_discrepancies import (
    DEFAULT_DATA_BINDINGS,
    EXPECTED_GAUGES,
    EXPECTED_ROWS,
    EXPECTED_TMAX_S,
    audit_single_gauge_discrepancy,
    compute_bed_z,
    execute_audit,
    read_gauge_csv,
    sha256_file,
)

SCOPE_DIR = Path(__file__).resolve().parent
REQUESTS_DIR = SCOPE_DIR / "requests"
ROOT_COMPARISON_JSON = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_FINE_ACTUAL_FULL_HALFSTEP_ALL_GAUGES/root-fine-two-mechanism-native-schedule-halfstep-all-six-gauges-042/halfstep-gauge-comparison.json"
)


def test_source_csv_and_receipt_integrity():
    """Verify that all source gauge CSVs and execution receipts exist, have 800 rows, and monotonic times."""
    assert ROOT_COMPARISON_JSON.is_file(), f"Root comparison JSON missing: {ROOT_COMPARISON_JSON}"

    for pair_key, pair_meta in DEFAULT_DATA_BINDINGS.items():
        for role in ["nominal", "halfstep"]:
            role_meta = pair_meta[role]
            receipt_path = Path(role_meta["receipt"])
            assert receipt_path.is_file(), f"Receipt missing: {receipt_path}"

            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            assert receipt.get("returncode") == 0, f"Receipt returncode != 0: {receipt_path}"
            assert receipt.get("status") == "completed"

            for g in EXPECTED_GAUGES:
                csv_path = Path(role_meta["gauges"][g])
                assert csv_path.is_file(), f"Gauge CSV missing: {csv_path}"
                parsed = read_gauge_csv(csv_path)
                assert parsed["rows"] == EXPECTED_ROWS
                assert parsed["time_start_s"] >= 0.0
                assert parsed["time_end_s"] >= EXPECTED_TMAX_S - 0.01
                assert len(parsed["times"]) == EXPECTED_ROWS


def test_exact_metric_replication_against_root042():
    """Verify that audit script replicates Root042 relative RMSE and max abs metrics to 4 decimal places."""
    with ROOT_COMPARISON_JSON.open() as f:
        root_comp = json.load(f)

    audit_result = execute_audit(DEFAULT_DATA_BINDINGS)

    for pair_idx, pair_data in enumerate(audit_result["pairs"]):
        root_pair = root_comp["pairs"][pair_idx]
        assert pair_data["mechanism"] == root_pair["mechanism"]
        assert pair_data["mechanism_conjunction_pass"] is False

        for root_g in root_pair["gauges"]:
            gname = root_g["gauge_name"]
            audit_g = pair_data["gauges"][gname]["primary_error_metrics"]

            np.testing.assert_allclose(
                audit_g["relative_eta_rmse"],
                root_g["relative_eta_rmse"],
                rtol=1e-4,
                atol=1e-5,
                err_msg=f"Mismatch in RMSE for {pair_data['mechanism']} {gname}",
            )
            np.testing.assert_allclose(
                audit_g["relative_eta_max_abs"],
                root_g["relative_eta_max_abs"],
                rtol=1e-4,
                atol=1e-5,
                err_msg=f"Mismatch in max abs for {pair_data['mechanism']} {gname}",
            )


def test_discrepancy_peak_localization():
    """Verify that peak discrepancies localize to documented wave arrival / dropout timestamps."""
    audit_result = execute_audit(DEFAULT_DATA_BINDINGS)
    runup_gauges = audit_result["pairs"][0]["gauges"]
    weir_gauges = audit_result["pairs"][1]["gauges"]

    # Runup WG1: peak error at steep front ~3.10 s
    assert abs(runup_gauges["WG1"]["max_discrepancy_event"]["time_s"] - 3.10) < 0.04
    assert runup_gauges["WG1"]["max_discrepancy_event"]["relative_error_to_H"] > 0.11

    # Runup WG2: peak error at crest ~7.48 s
    assert abs(runup_gauges["WG2"]["max_discrepancy_event"]["time_s"] - 7.48) < 0.04
    assert runup_gauges["WG2"]["max_discrepancy_event"]["relative_error_to_H"] > 0.10

    # Runup WG3: peak error at floor dropout ~6.76 s
    assert abs(runup_gauges["WG3"]["max_discrepancy_event"]["time_s"] - 6.76) < 0.04
    assert runup_gauges["WG3"]["max_discrepancy_event"]["relative_error_to_H"] > 0.70
    assert runup_gauges["WG3"]["max_discrepancy_event"]["nominal_at_floor"] is True

    # Runup WG4: peak error at floor dropout ~8.48 s
    assert abs(runup_gauges["WG4"]["max_discrepancy_event"]["time_s"] - 8.48) < 0.04
    assert runup_gauges["WG4"]["max_discrepancy_event"]["relative_error_to_H"] > 1.50
    assert runup_gauges["WG4"]["max_discrepancy_event"]["halfstep_at_floor"] is True

    # Weir WG2: peak error at single-frame dip ~2.62 s
    assert abs(weir_gauges["WG2"]["max_discrepancy_event"]["time_s"] - 2.62) < 0.04
    assert weir_gauges["WG2"]["max_discrepancy_event"]["relative_error_to_H"] > 0.08


def test_concentration_and_floor_flags_bounded():
    """Verify that concentration fractions are bounded in [0, 1] and descriptive only."""
    audit_result = execute_audit(DEFAULT_DATA_BINDINGS)
    for pair_data in audit_result["pairs"]:
        for gname, gdata in pair_data["gauges"].items():
            conc = gdata["concentration"]
            assert 0.0 <= conc["top_1pct_samples_sse_fraction"] <= 1.0001
            assert 0.0 <= conc["top_5pct_samples_sse_fraction"] <= 1.0001
            assert 0.0 <= conc["top_10pct_samples_sse_fraction"] <= 1.0001
            assert conc["top_1pct_samples_sse_fraction"] <= conc["top_5pct_samples_sse_fraction"] + 1e-6
            assert conc["top_5pct_samples_sse_fraction"] <= conc["top_10pct_samples_sse_fraction"] + 1e-6

            floor_diag = gdata["descriptive_floor_diagnostics"]
            assert floor_diag["nominal_floor_samples"] >= 0
            assert floor_diag["halfstep_floor_samples"] >= 0
            assert "Descriptive only" in floor_diag["note"]


def test_audit_runner_request_schema():
    """Verify that audit runner request conforms to ds02.runner-request.v2 with launch_allowed=False."""
    req_path = REQUESTS_DIR / "F5_HALFSTEP_DISCREPANCY_AUDIT_REQUEST.json"
    assert req_path.is_file(), f"Audit request missing: {req_path}"

    req = json.loads(req_path.read_text(encoding="utf-8"))
    assert req["schema"] == "ds02.runner-request.v2"
    assert req["family_id"] == "F5"
    assert req["kind"] == "cpu"
    assert req["cpu_task_kind"] == "audit"
    assert req["launch_allowed"] is False
    assert req["launch_owner"] == "root"
    assert req["production_approval"] == "none"
    assert req["q_n_status"] == "not_assessed"
    assert req["root_review_required"] is True

    # Verify input hashes
    for in_file, expected_hash in req["input_sha256"].items():
        p = Path(in_file)
        assert p.is_file(), f"Input file in request does not exist: {p}"
        assert sha256_file(p) == expected_hash, f"Hash mismatch for {p}"


def test_prospective_fallback_definition():
    """Verify prospective fallback specification has valid geometry, single packet motion, and corrected observer."""
    def_path = SCOPE_DIR / "prospective_fallback_definition.json"
    assert def_path.is_file(), f"Prospective fallback definition missing: {def_path}"

    spec = json.loads(def_path.read_text(encoding="utf-8"))
    assert spec["schema"] == "ds02.f5.prospective-fallback-specification.v1"
    assert spec["family_id"] == "F5"
    assert spec["governance"]["launch_allowed"] is False
    assert spec["governance"]["launch_owner"] == "root"
    assert spec["governance"]["q_n_status"] == "not_assessed"

    # Both mechanisms present
    mechanisms = {m["mechanism_id"]: m for m in spec["mechanisms"]}
    assert "runup_return" in mechanisms
    assert "weir_pair" in mechanisms

    # Corrected observer baseline
    for m in spec["mechanisms"]:
        for g in m["observer_specification"]["gauges"]:
            assert g["point0_z_m"] == pytest.approx(g["z_bed_m"], abs=1e-4), (
                f"Probe {g['name']} in {m['mechanism_id']} has point0.z != z_bed"
            )

    # Invariants
    inv = spec["frozen_budget_invariants"]
    assert inv["characteristic_depth_H_m"] == 0.40
    assert inv["macro_relative_error_budget"] == 0.05
    assert inv["integration_budget_relative"] == 0.01
    assert inv["phase_alignment_allowed"] is False
    assert inv["dry_sample_dropping_allowed"] is False


def test_prospective_preparation_request_schema():
    """Verify prospective preparation runner request schema and governance fields."""
    req_path = REQUESTS_DIR / "F5_PROSPECTIVE_FALLBACK_PREPARATION_REQUEST.json"
    assert req_path.is_file(), f"Prospective fallback request missing: {req_path}"

    req = json.loads(req_path.read_text(encoding="utf-8"))
    assert req["schema"] == "ds02.runner-request.v2"
    assert req["family_id"] == "F5"
    assert req["kind"] == "cpu"
    assert req["launch_allowed"] is False
    assert req["launch_owner"] == "root"
    assert req["production_approval"] == "none"
    assert req["q_n_status"] == "not_assessed"
    assert req["root_review_required"] is True
