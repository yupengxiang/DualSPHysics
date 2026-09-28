"""Tests for the bounded F3 live terminal-evidence intake contract."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import f3_live_rollout_terminal_evidence_intake_v1 as intake


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / (
    "reports/F3-GRAPH-RAW-HIDDEN16-LIVE-ROLLOUT-TERMINAL-EVIDENCE-"
    "INTAKE-V1-2026-09-28.json"
)


def _sha(letter: str) -> str:
    return letter * 64


def _valid(seed: int) -> dict:
    prefix = f"/tmp/f3-graph-raw500-hidden16-seed{seed}-full835-live-v1"
    return {
        "schema": "core.f3.graph_raw.hidden16.full835.rollout_diagnostic.summary.v1",
        "status": "completed_diagnostic",
        "model_kind": "graph_raw",
        "seed": seed,
        "hidden": 16,
        "updates": 500,
        "transitions": 835,
        "frames": 836,
        "terminal_markers": {
            "terminal": True,
            "execution_complete": True,
            "finite_rollout_complete": True,
            "terminal_status": "completed",
        },
        "checkpoint": {
            "path": f"/tmp/f3-graph-raw500-hidden16-seed{seed}-checkpoint.pt",
            "sha256": _sha(chr(ord("a") + (seed % 3))),
            "update": 500,
        },
        "output": {
            "fresh_output_namespace": prefix,
            "evaluation_path": prefix + "-evaluation.json",
            "trajectory_path": prefix + "-trajectory.h5",
            "progress_path": prefix + "-evaluation-progress.json",
        },
        "diagnostic_only": True,
        "formal_eligible": False,
        "qualification": False,
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "future_state_inputs": False,
        "qualification_credit": 0,
        "credit": 0,
        "qualification_markers": {
            "formal": False,
            "formal_eligible": False,
            "T1_numerical": False,
            "T2_macro": False,
            "T2_path": False,
            "qualification": False,
            "credit": 0,
        },
        "side_effects": {
            "rollout_inputs_read_only": True,
            "future_state_inputs": False,
            "diagnostic_counted_as_T1_or_T2": False,
            "formal_training_counted": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "gate_mutation": 0,
            "completion_mutation": 0,
        },
    }


def _evaluate(receipts: dict[int, dict]) -> dict:
    sources = {
        seed: {"path": f"synthetic://terminal/{seed}.json", "opened": False}
        for seed in receipts
    }
    return intake.evaluate_payloads(receipts, sources)


def test_valid_three_seed_matrix_is_terminal_diagnostic_and_zero_credit():
    report = _evaluate({seed: _valid(seed) for seed in intake.SEEDS})
    assert report["status"] == "bound_terminal_diagnostic"
    assert report["source_bound"] is True
    assert report["credit"] == 0
    assert report["qualification_credit"] == 0
    assert report["input_boundary"]["progress_opened"] is False
    assert report["side_effects"]["gpu_started"] is False


def test_missing_terminal_is_not_completed():
    report = _evaluate({})
    assert report["status"] == "blocked_missing_terminal_evidence"
    assert report["fail_closed"] is True
    assert all(row["status"] == "missing" for row in report["seed_matrix"])
    assert report["input_boundary"]["terminal_json_opened"] == 0


def test_running_or_partial_terminal_is_rejected():
    for status in ("running", "partial"):
        receipts = {seed: _valid(seed) for seed in intake.SEEDS}
        receipts[17]["status"] = status
        report = _evaluate(receipts)
        row = next(item for item in report["seed_matrix"] if item["seed"] == 17)
        assert report["status"] == "blocked_fail_closed"
        assert row["status"] == "rejected"
        assert "completed" in row["error"]


def test_hidden_drift_is_rejected_fail_closed():
    receipts = {seed: _valid(seed) for seed in intake.SEEDS}
    receipts[29]["hidden"] = 8
    report = _evaluate(receipts)
    row = next(item for item in report["seed_matrix"] if item["seed"] == 29)
    assert report["status"] == "blocked_fail_closed"
    assert row["status"] == "rejected"
    assert "hidden" in row["error"]


def test_nonzero_credit_or_formal_marker_cannot_bind():
    receipts = {seed: _valid(seed) for seed in intake.SEEDS}
    receipts[43]["credit"] = 1
    report = _evaluate(receipts)
    assert report["status"] == "blocked_fail_closed"
    assert report["credit"] == 0
    assert report["qualification_credit"] == 0
    assert next(row for row in report["seed_matrix"] if row["seed"] == 43)["status"] == "rejected"


def test_report_binding_and_disallowed_input_are_explicit(tmp_path: Path):
    report = intake.build_report(tmp_path)
    assert report["status"] == "blocked_missing_terminal_evidence"
    output = tmp_path / "report.json"
    output.write_text(intake.canonical_json(report) + "\n", encoding="utf-8")
    assert json.loads(output.read_text(encoding="utf-8")) == intake.build_report(tmp_path)
    tampered = copy.deepcopy(report)
    tampered["credit"] = 1
    assert tampered != intake.build_report(tmp_path)
    bad = intake.build_report(tmp_path, terminal_paths={seed: tmp_path / "bad.h5" for seed in intake.SEEDS})
    assert bad["status"] == "blocked_fail_closed"
    assert bad["input_boundary"]["progress_opened"] is False
