"""Tests for the bounded F3 hidden16 training-evidence matrix adapter."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import f3_graph_raw_hidden16_training_evidence_matrix_v1 as matrix


def _sha(char: str) -> str:
    return char * 63 + ("0" if char != "0" else "1")


def _receipt(seed: int) -> dict:
    config = copy.deepcopy(matrix.STATIC_CONFIG)
    config.update(
        {
            "manifest_sha256": _sha("a"),
            "paired_seed": seed,
            "run_id": f"graph_raw-hidden16-seed{seed}",
            "sampler_seed": seed,
            "seed": seed,
        }
    )
    return {
        "schema": matrix.TRAINING_SCHEMA,
        "evidence_status": "complete",
        "status": "completed",
        "model_kind": "graph_raw",
        "seed": seed,
        "run_id": f"graph_raw-hidden16-seed{seed}",
        "completed_updates": 500,
        "parameter_count": 6086,
        "checkpoint_verified": True,
        "config": config,
        "checkpoint": {
            "schema": matrix.CHECKPOINT_SCHEMA,
            "path": f"/tmp/f3-graph-raw500-hidden16-seed{seed}-20260928-checkpoint.pt",
            "sha256": _sha("b" if seed == 17 else "c" if seed == 29 else "d"),
            "update": 500,
        },
        "evidence": {
            "schema": "core.training.evidence.v1",
            "status": "complete",
            "initialization": {
                "schema": matrix.INITIALIZATION_SCHEMA,
                "status": "captured",
                "constructed_before_first_update": True,
                "construction_update": 0,
                "hidden": 16,
                "model_kind": "graph_raw",
                "parameter_count": 6086,
                "parameter_digest": _sha("e" if seed == 17 else "f" if seed == 29 else "1"),
                "seed": seed,
            },
            "normalization": {
                "schema": matrix.NORMALIZATION_SCHEMA,
                "available_transition_count": 13360,
                "requested_maximum_transitions": 16,
                "selected_transition_count": 16,
                "selection_policy": "deterministic_evenly_spaced_train_transitions_v1",
                "selection_seed": seed,
                "source_split": "train",
                "target_reference": "raw_dual_increment_train_shared",
            },
            "residual_prior": {"enabled": False, "execution_calls": 0, "rows": 0},
        },
    }


def _reference(receipts: dict[int, dict]) -> dict:
    return {
        "schema": matrix.REFERENCE_SCHEMA,
        "report_id": "f3-graph-raw-hidden16-seeds17-29-43-training-2026-09-28",
        "diagnostic_only": True,
        "formal_eligible": False,
        "model": "graph_raw",
        "shared_config": {
            "hidden": 16,
            "centers_per_update": 256,
            "max_neighbors": 192,
            "updates": 500,
            "learning_rate": 0.001,
            "normalization_transitions": 16,
            "gradient_clipping": None,
            "validation_transition_count": 4,
            "manifest_formal_release": False,
            "target_normalization": "raw_dual_increment_train_shared",
        },
        "runs": [
            {
                "seed": seed,
                "run_id": f"graph_raw-hidden16-seed{seed}",
                "completed_updates": 500,
                "parameter_count": 6086,
                "checkpoint_verified": True,
                "checkpoint_sha256": receipts[seed]["checkpoint"]["sha256"],
                "training_receipt_sha256": _sha("7"),
                "progress_receipt_sha256": _sha("8"),
                "initialization_parameter_digest": receipts[seed]["evidence"]["initialization"]["parameter_digest"],
                "neighbor_truncation_fraction": 0.0,
            }
            for seed in matrix.SEEDS
        ],
        "qualification": {
            "training_evidence_complete": True,
            "full_rollout_evaluations": "pending",
            "qualification": False,
            "t1": False,
            "t2": False,
            "credit": 0,
        },
    }


def _payloads():
    receipts = {seed: _receipt(seed) for seed in matrix.SEEDS}
    sources = {
        seed: {"path": f"synthetic://seed{seed}.json", "sha256": _sha("7"), "opened": False}
        for seed in matrix.SEEDS
    }
    return receipts, sources, _reference(receipts)


def _evaluate(receipts=None, reference=None):
    base_receipts, sources, base_reference = _payloads()
    return matrix.evaluate_payloads(
        base_receipts if receipts is None else receipts,
        sources,
        base_reference if reference is None else reference,
        {"path": "synthetic://reference.json", "schema": matrix.REFERENCE_SCHEMA},
    )


def test_exact_seed_set_is_required():
    receipts, _, _ = _payloads()
    receipts.pop(29)
    report = _evaluate(receipts)
    assert report["status"] == "blocked_fail_closed"
    assert "exact_seed_set" in {item["check"] for item in report["checks"]}
    assert any("seed 29" in error for error in report["errors"])


def test_config_drift_fails_closed():
    receipts, _, _ = _payloads()
    receipts[29]["config"]["max_neighbors"] = 191
    report = _evaluate(receipts)
    assert report["source_bound"] is False
    assert any("seed29" in error and "config.max_neighbors" in error for error in report["errors"])


def test_checkpoint_drift_against_reference_fails_closed():
    receipts, _, reference = _payloads()
    reference["runs"][1]["checkpoint_sha256"] = _sha("9")
    report = _evaluate(receipts, reference)
    assert report["source_bound"] is False
    assert any("checkpoint SHA drifts" in error for error in report["errors"])


def test_missing_receipt_is_fail_closed():
    receipts, _, _ = _payloads()
    receipts.pop(43)
    report = _evaluate(receipts)
    assert report["fail_closed"] is True
    assert report["runs"][2]["status"] == "missing"


def test_zero_credit_and_report_binding_are_explicit():
    report = _evaluate()
    assert matrix.validate_report(report) == []
    tampered = copy.deepcopy(report)
    tampered["credit"] = 1
    assert any("credit must be zero" in error for error in matrix.validate_report(tampered))


def test_duplicate_json_keys_are_rejected(tmp_path: Path):
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema":"x","schema":"y"}\n', encoding="utf-8")
    with pytest.raises(matrix.MatrixError, match="duplicate JSON object key"):
        matrix.read_bounded_json(tmp_path, path)


def test_placeholder_checkpoint_hash_is_rejected():
    receipts, _, _ = _payloads()
    receipts[17]["checkpoint"]["sha256"] = "0" * 64
    report = _evaluate(receipts)
    assert report["source_bound"] is False
    assert any("checkpoint.sha256" in error for error in report["errors"])


def test_complete_report_has_no_authority_or_side_effects():
    report = _evaluate()
    assert report["source_bound"] is True
    assert report["formal_training_runs_counted"] == 0
    assert report["authorization"]["credit"] == 0
    assert all(value == 0 for key, value in report["side_effects"].items() if key.endswith("_mutation"))
    assert report["side_effects"]["checkpoint_opened"] is False
