from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np

from scripts import f4_reconstruction_gate_repair_v1 as repair
from scripts.f4_reconstruction_gate_zoh_short_canary_v1 import (
    DP_M,
    EVENT_WINDOW_S,
    FIRST_LOSS_FROM_FRAME,
    Q,
    SCHEMA,
    SEEDS,
    STOP_AFTER_FRAME,
    SUBSTEPS,
    _result_summary,
    compare_replays,
)


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / (
    "campaigns/core-v1/material/evidence/"
    "f4-reconstruction-gate-zoh-short-canary-v1-20260920/"
    "f4-reconstruction-gate-zoh-short-canary-v1.json"
)


def test_short_canary_contract_keeps_fixed_gate_and_full_denominator() -> None:
    candidate = repair.candidate_contract()
    assert SCHEMA == "core.material.f4.reconstruction_gate_zoh_short_canary.v1"
    assert (Q, DP_M, SEEDS, SUBSTEPS) == (0.5, 0.0075, 512, 2)
    assert FIRST_LOSS_FROM_FRAME == 40
    assert STOP_AFTER_FRAME == 50
    assert candidate["neighbour_variant"] == "baseline24"
    assert candidate["neighbours"] == 24
    assert candidate["support_gate"]["maximum_reconstruction_error_mps"] == 0.05 * (9.81 * 0.09) ** 0.5
    assert candidate["maximum_support_distance_m"] == 0.03
    assert candidate["unknown_denominator"] == "all 512 independent source seeds"
    assert EVENT_WINDOW_S == 4.34


def test_result_summary_reports_censoring_against_registered_window() -> None:
    result = {
        "status": "partial",
        "committed_frame": 50,
        "committed_time_s": 0.200011,
        "mass_closed": True,
        "unknown_gate_pass": True,
        "common_reliable_path_coverage": 1.0,
        "event_window_complete": False,
        "event_window_status": "right_censored_or_unresolved",
        "binding": {"source_sha256": "source"},
        "by_source": [{"unknown_fraction_max": 0.0}],
    }
    summary = _result_summary(result)
    assert summary["seed_denominator"] == 512
    assert summary["unknown_fraction_max"] == 0.0
    assert summary["event_window_required_s"] == 4.34
    assert summary["event_window_observed_s"] == result["committed_time_s"]
    assert summary["event_window_missing_s"] > 4.0
    assert summary["event_window_complete"] is False


def _write_trace(path: Path, *, committed: int = 1) -> None:
    with h5py.File(path, "w") as handle:
        handle.attrs.update(
            schema="core.material.f4.tallwall120.v1",
            binding=json.dumps({"candidate": "zoh"}),
            provider_role="reference",
            seed_identity="independent geometric seed",
            committed=committed,
        )
        handle.create_dataset("time", data=np.array([0.0, 0.01]))
        handle.create_dataset("position", data=np.zeros((2, 2, 3)))


def test_compare_replays_is_exact_and_detects_changed_dataset(tmp_path: Path) -> None:
    left = tmp_path / "left.h5"
    right = tmp_path / "right.h5"
    _write_trace(left)
    _write_trace(right)
    exact = compare_replays(left, right)
    assert exact["exact"] is True
    assert exact["mismatches"] == []

    with h5py.File(right, "r+") as handle:
        handle["position"][1, 0, 0] = 1.0
    changed = compare_replays(left, right)
    assert changed["exact"] is False
    assert changed["mismatches"] == ["dataset:position"]


def test_recorded_short_canary_preserves_negative_t2_and_hash_closure() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert evidence["schema"] == SCHEMA
    assert evidence["qualification_claim"] == "none"
    assert evidence["qualification_credit"] == "none"
    assert evidence["T2_macro"] is False
    assert evidence["T2_path"] is False
    assert evidence["candidate_result"]["seed_denominator"] == 512
    assert evidence["candidate_result"]["unknown_fraction_max"] == 0.42578125
    assert evidence["candidate_result"]["unknown_gate_pass"] is False
    assert evidence["candidate_result"]["event_window_complete"] is False
    assert evidence["candidate_result"]["event_window_required_s"] == 4.34
    assert evidence["candidate_result"]["event_window_missing_s"] > 4.13
    assert evidence["diagnosis"]["first_failure"]["failed_seed_count"] == 218
    assert evidence["acceptance_checks"]["exact_replay_pass"] is True
    assert evidence["acceptance_checks"]["zero_new_failure_at_first_loss_interval"] is True
    assert evidence["root_review_closure"]["queue_submission"] is False
    assert evidence["execution_constraints"]["registry_mutation"] == 0
    assert evidence["execution_constraints"]["central_ledger_mutation"] == 0
