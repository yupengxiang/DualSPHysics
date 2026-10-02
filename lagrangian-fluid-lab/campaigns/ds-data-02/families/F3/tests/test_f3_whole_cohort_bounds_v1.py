"""Meaningful tests for the F3 whole-cohort censor diagnostic."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest


HANDOFF = Path(__file__).resolve().parents[1] / "handoff_20261003/whole_cohort_quantiles_v1"
MODULE_PATH = HANDOFF / "f3_quarter_half_whole_cohort_bounds_v1.py"
EVIDENCE = HANDOFF / "whole_cohort_bounds_final_evidence_v1.json"


def load_module():
    spec = importlib.util.spec_from_file_location("f3_whole_cohort_bounds", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_contract_preregisters_diagnostic_qlevels_and_keeps_qn_closed():
    contract = json.loads((HANDOFF / "contract.json").read_text(encoding="utf-8"))
    assert contract["quantile_fractions"] == [0.1, 0.5, 0.9]
    assert contract["canonical_initial_mass_kg"] == 14.58
    assert contract["budget_contract"]["save_or_integration_share"] == 0.2
    assert contract["q_n_status"] == "not_assessed"
    assert contract["qualification_claim"].startswith("none;")


def test_conservative_bounds_keep_censored_cohort_in_quantile_denominator():
    module = load_module()
    rows = module.conservative_quantile_bounds(
        intervals=np.array([[1.0, 2.0], [3.0, 4.0], [np.nan, np.nan]]),
        chord_times=np.array([1.5, 3.5, np.nan]),
        censor=np.array([False, False, True]),
        unresolved=np.array([False, False, False]),
        weights=np.ones(3),
        window_end_s=10.0,
        fractions=[0.5, 0.9],
    )
    q50, q90 = rows["whole_cohort_conservative_bounds"]
    assert q50["lower_s"] == 3.0
    assert q50["upper_s"] == 4.0
    assert q90["lower_s"] == 10.0
    assert q90["upper_s"] is None
    conditional = rows["conditional_observed"]
    assert conditional["observed_mass_kg"] == 2.0
    assert conditional["censored_or_unresolved_mass_kg"] == 1.0


def test_fraction_error_is_already_native_mass_normalized():
    module = load_module()
    row = module._difference(0.4, 0.5, units="kg_fraction", canonical_mass=14.58)
    assert row["absolute_error"] == pytest.approx(0.1)
    assert row["native_mass_normalized_error"] == pytest.approx(0.1)


def test_actual_cpu_evidence_is_terminal_and_keeps_temporal_scope_pending():
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert evidence["status"] == "actual_cpu_diagnostic_completed"
    assert evidence["receipt"]["status"] == "completed"
    assert evidence["receipt"]["returncode"] == 0
    assert evidence["receipt"]["gpu_seconds"] == 0.0
    assert evidence["receipt"]["input_hashes_after_run_match"] is True
    assert evidence["qlevels"] == [0.1, 0.5, 0.9]
    assert evidence["q_n_status"] == "not_assessed"
    assert evidence["scope_support"]["half_supports_structural_transport_label_scope"] is True
    assert evidence["scope_support"]["half_supports_temporal_integration_scope"] is False
    assert evidence["scope_support"]["independent_reference_required"] is True
    assert [row["status"] for row in evidence["observed_event_integration_allocation"][:2]] == [
        "exceeds_allocation", "exceeds_allocation"
    ]
