"""Tests for the independent bounded F3 graph_residual hidden16 matrix."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import f3_graph_residual_hidden16_training_evidence_matrix_v1 as matrix


def _sha(char: str) -> str:
    return char * 63 + ("0" if char != "0" else "1")


def _normalization(seed: int) -> dict:
    return {
        "schema": matrix.NORMALIZATION_SCHEMA,
        "available_transition_count": 13360,
        "requested_maximum_transitions": 16,
        "selected_transition_count": 16,
        "selection_policy": "deterministic_evenly_spaced_train_transitions_v1",
        "selection_seed": seed,
        "source_split": "train",
        "target_reference": "raw_dual_increment_train_shared",
    }


def _prior(seed: int) -> dict:
    return {
        "schema": matrix.PRIOR_SCHEMA,
        "enabled": True,
        "history_complete": True,
        "units": {"displacement": "m", "delta_velocity": "m/s"},
        "execution_calls": 500,
        "rows": matrix.PRIOR_ROWS,
        "finite": True,
        "dx_abs_max_m": 0.01 + seed / 100000,
        "dv_abs_max_mps": 0.1 + seed / 100000,
        "dx_abs_sum_m": 40000.0 + seed,
        "dv_abs_sum_mps": 1700000.0 + seed,
        "last_update": {"update": 500, "case_id": f"F3_DEV_{seed:02d}", "frame": seed},
        "semantic": "graph_residual subtracts this SI prior before shared raw-target normalization; predictor adds it back",
    }


def _receipt(seed: int) -> dict:
    config = copy.deepcopy(matrix.STATIC_CONFIG)
    config.update(
        {
            "manifest_sha256": _sha("a"),
            "paired_seed": seed,
            "run_id": f"graph_residual-hidden16-seed{seed}",
            "sampler_seed": seed,
            "seed": seed,
        }
    )
    return {
        "schema": matrix.TRAINING_SCHEMA,
        "evidence_status": "complete",
        "status": "completed",
        "model_kind": "graph_residual",
        "seed": seed,
        "run_id": f"graph_residual-hidden16-seed{seed}",
        "completed_updates": 500,
        "parameter_count": matrix.PARAMETER_COUNT,
        "checkpoint_verified": True,
        "config": config,
        "checkpoint": {
            "schema": matrix.CHECKPOINT_SCHEMA,
            "path": f"/tmp/f3-graph-residual500-hidden16-seed{seed}-20260928-checkpoint.pt",
            "sha256": _sha("b" if seed == 17 else "c" if seed == 29 else "d"),
            "update": 500,
        },
        "evidence": {
            "schema": matrix.EVIDENCE_SCHEMA,
            "status": "complete",
            "initialization": {
                "schema": matrix.INITIALIZATION_SCHEMA,
                "status": "captured",
                "constructed_before_first_update": True,
                "construction_update": 0,
                "hidden": 16,
                "model_kind": "graph_residual",
                "parameter_count": matrix.PARAMETER_COUNT,
                "parameter_digest": _sha("e" if seed == 17 else "f" if seed == 29 else "1"),
                "seed": seed,
            },
            "normalization": _normalization(seed),
            "residual_prior": _prior(seed),
        },
    }


def _reference(receipts: dict[int, dict], source_shas: dict[int, str]) -> dict:
    return {
        "schema": matrix.REFERENCE_SCHEMA,
        "report_id": "f3-graph-residual-hidden16-seeds17-29-43-training-2026-09-28",
        "diagnostic_only": True,
        "formal_eligible": False,
        "model": "graph_residual",
        "manifest_sha256": _sha("a"),
        "shared_config": copy.deepcopy(matrix.REFERENCE_SHARED_CONFIG),
        "runs": [
            {
                "seed": seed,
                "run_id": f"graph_residual-hidden16-seed{seed}",
                "completed_updates": 500,
                "parameter_count": matrix.PARAMETER_COUNT,
                "checkpoint_verified": True,
                "checkpoint_sha256": receipts[seed]["checkpoint"]["sha256"],
                "training_receipt_sha256": source_shas[seed],
                "initialization_parameter_digest": receipts[seed]["evidence"]["initialization"]["parameter_digest"],
                "normalization_identity_sha256": matrix.identity_sha256(
                    matrix._normalization_identity(receipts[seed]["evidence"]["normalization"])
                ),
                "residual_prior_identity_sha256": matrix.identity_sha256(
                    matrix._prior_identity(receipts[seed]["evidence"]["residual_prior"])
                ),
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
    source_shas = {seed: _sha("7" if seed == 17 else "8" if seed == 29 else "9") for seed in matrix.SEEDS}
    sources = {
        seed: {
            "path": f"/tmp/f3-graph-residual500-hidden16-seed{seed}-20260928-training.json",
            "exists": True,
            "opened": True,
            "bytes": 1000 + seed,
            "sha256": source_shas[seed],
            "schema": matrix.TRAINING_SCHEMA,
        }
        for seed in matrix.SEEDS
    }
    return receipts, sources, _reference(receipts, source_shas)


def _evaluate(receipts=None, sources=None, reference=None):
    base_receipts, base_sources, base_reference = _payloads()
    return matrix.evaluate_payloads(
        base_receipts if receipts is None else receipts,
        base_sources if sources is None else sources,
        base_reference if reference is None else reference,
        {
            "path": "/tmp/f3-graph-residual-hidden16-reference.json",
            "exists": True,
            "opened": True,
            "bytes": 2000,
            "sha256": _sha("6"),
            "schema": matrix.REFERENCE_SCHEMA,
        },
    )


def test_complete_matrix_binds_all_identity_components_without_authority():
    report = _evaluate()
    assert report["source_bound"] is True
    assert report["status"] == "training_evidence_bound_diagnostic_only"
    assert report["formal_training_runs_counted"] == 0
    assert report["authorization"]["credit"] == 0
    assert report["expected_contract"]["model_kind"] == "graph_residual"
    assert report["expected_contract"]["hidden"] == 16
    assert report["expected_contract"]["updates"] == 500
    assert all(row["status"] == "bound_complete" for row in report["runs"])
    assert all(row["evidence"]["residual_prior"]["enabled"] is True for row in report["runs"])
    assert matrix.validate_report(report) == []


def test_exact_seed_set_is_required():
    receipts, sources, reference = _payloads()
    receipts.pop(29)
    sources.pop(29)
    report = _evaluate(receipts, sources, reference)
    assert report["status"] == "blocked_fail_closed"
    assert report["source_bound"] is False
    assert "exact_seed_set" in {item["check"] for item in report["checks"]}
    assert any("seed 29" in error for error in report["errors"])


def test_model_hidden_and_updates_drift_fail_closed():
    receipts, sources, reference = _payloads()
    receipts[29]["model_kind"] = "graph_raw"
    report = _evaluate(receipts, sources, reference)
    assert report["source_bound"] is False
    assert any("seed29" in error and "model_kind" in error for error in report["errors"])

    receipts, sources, reference = _payloads()
    receipts[43]["evidence"]["initialization"]["hidden"] = 8
    report = _evaluate(receipts, sources, reference)
    assert report["source_bound"] is False
    assert any("seed43" in error and "initialization evidence" in error for error in report["errors"])

    receipts, sources, reference = _payloads()
    receipts[17]["completed_updates"] = 499
    report = _evaluate(receipts, sources, reference)
    assert report["source_bound"] is False
    assert any("seed17" in error and "seed/updates drift" in error for error in report["errors"])


def test_checkpoint_training_init_and_normalization_reference_drift_fail_closed():
    receipts, sources, reference = _payloads()
    reference["runs"][1]["checkpoint_sha256"] = _sha("0")
    report = _evaluate(receipts, sources, reference)
    assert report["source_bound"] is False
    assert any("checkpoint SHA drifts" in error for error in report["errors"])

    receipts, sources, reference = _payloads()
    sources[17]["sha256"] = _sha("0")
    report = _evaluate(receipts, sources, reference)
    assert report["source_bound"] is False
    assert any("training receipt SHA drifts" in error for error in report["errors"])

    receipts, sources, reference = _payloads()
    reference["runs"][2]["initialization_parameter_digest"] = _sha("0")
    report = _evaluate(receipts, sources, reference)
    assert report["source_bound"] is False
    assert any("initialization digest drifts" in error for error in report["errors"])

    receipts, sources, reference = _payloads()
    reference["runs"][0]["normalization_identity_sha256"] = _sha("0")
    report = _evaluate(receipts, sources, reference)
    assert report["source_bound"] is False
    assert any("normalization identity drifts" in error for error in report["errors"])


def test_residual_prior_must_be_complete_enabled_and_finite():
    receipts, sources, reference = _payloads()
    receipts[17]["evidence"]["residual_prior"]["enabled"] = False
    report = _evaluate(receipts, sources, reference)
    assert report["source_bound"] is False
    assert any("residual_prior must be enabled" in error for error in report["errors"])

    receipts, sources, reference = _payloads()
    receipts[29]["evidence"]["residual_prior"]["rows"] = 1
    report = _evaluate(receipts, sources, reference)
    assert report["source_bound"] is False
    assert any("execution/row identity" in error for error in report["errors"])

    receipts, sources, reference = _payloads()
    receipts[43]["evidence"]["residual_prior"]["dx_abs_max_m"] = float("nan")
    report = _evaluate(receipts, sources, reference)
    assert report["source_bound"] is False
    assert any("non-finite" in error or "finite nonnegative" in error for error in report["errors"])


def test_duplicate_json_keys_and_non_json_inputs_are_rejected(tmp_path: Path):
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema":"x","schema":"y"}\n', encoding="utf-8")
    with pytest.raises(matrix.MatrixError, match="duplicate JSON object key"):
        matrix.read_bounded_json(tmp_path, duplicate)

    checkpoint = tmp_path / "checkpoint.pt"
    checkpoint.write_bytes(b"not opened")
    with pytest.raises(matrix.MatrixError, match="only .json inputs"):
        matrix.read_bounded_json(tmp_path, checkpoint)


def test_zero_credit_and_input_boundary_are_explicit():
    report = _evaluate()
    assert report["input_boundary"]["bounded_json_only"] is True
    assert report["input_boundary"]["checkpoint_content_opened"] is False
    assert report["input_boundary"]["case_hdf5_opened"] is False
    assert report["side_effects"]["registry_mutation"] == 0
    assert report["side_effects"]["ledger_mutation"] == 0
    tampered = copy.deepcopy(report)
    tampered["credit"] = 1
    assert any("credit must be zero" in error for error in matrix.validate_report(tampered))


def test_reference_seed_or_shared_config_drift_fails_closed():
    receipts, sources, reference = _payloads()
    reference["runs"][0]["seed"] = 29
    report = _evaluate(receipts, sources, reference)
    assert report["source_bound"] is False
    assert any("reference matrix" in error for error in report["errors"])

    receipts, sources, reference = _payloads()
    reference["shared_config"]["model_kind"] = "graph_raw"
    report = _evaluate(receipts, sources, reference)
    assert report["source_bound"] is False
    assert any("shared_config drifts" in error for error in report["errors"])


def test_path_namespace_and_duplicate_identity_fail_closed():
    receipts, sources, reference = _payloads()
    receipts[17]["checkpoint"]["path"] = "/tmp/f3-graph-residual500-hidden16-seed29-20260928-checkpoint.pt"
    report = _evaluate(receipts, sources, reference)
    assert report["source_bound"] is False
    assert any("checkpoint.path" in error for error in report["errors"])

    receipts, sources, reference = _payloads()
    receipts[43]["checkpoint"]["sha256"] = receipts[17]["checkpoint"]["sha256"]
    report = _evaluate(receipts, sources, reference)
    assert report["source_bound"] is False
    assert any("identity is duplicated" in error for error in report["errors"])


def test_manifest_identity_drift_fails_closed():
    receipts, sources, reference = _payloads()
    receipts[17]["config"]["manifest_sha256"] = _sha("c")
    report = _evaluate(receipts, sources, reference)
    assert report["source_bound"] is False
    assert any("manifest" in error for error in report["errors"])


def test_source_and_reference_metadata_are_complete():
    receipts, sources, reference = _payloads()
    del sources[17]["opened"]
    report = _evaluate(receipts, sources, reference)
    assert report["source_bound"] is False
    assert any("source metadata" in error for error in report["errors"])

    receipts, sources, reference = _payloads()
    report = matrix.evaluate_payloads(receipts, sources, reference, None)
    assert report["source_bound"] is False
    assert any("reference source" in error for error in report["errors"])


def test_strict_numeric_identity_and_prior_semantics_fail_closed():
    receipts, sources, reference = _payloads()
    receipts[29]["seed"] = 29.0
    report = _evaluate(receipts, sources, reference)
    assert report["source_bound"] is False
    assert any("seed" in error for error in report["errors"])

    receipts, sources, reference = _payloads()
    receipts[43]["evidence"]["residual_prior"]["dx_abs_max_m"] += 1.0
    report = _evaluate(receipts, sources, reference)
    assert report["source_bound"] is False
    assert any("residual-prior identity" in error for error in report["errors"])


def test_report_run_schema_tampering_is_rejected():
    report = _evaluate()
    report["runs"] = [{"seed": seed} for seed in matrix.SEEDS]
    assert matrix.validate_report(report)

    report = _evaluate()
    report["unexpected"] = True
    assert any("envelope keys" in error for error in matrix.validate_report(report))


def test_symlink_input_and_unsafe_output_are_rejected(tmp_path: Path, monkeypatch):
    target = tmp_path / "target.json"
    target.write_text("{}\n", encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(matrix.MatrixError, match="symlink"):
        matrix.read_bounded_json(tmp_path, link)

    monkeypatch.chdir(tmp_path)
    with pytest.raises(matrix.MatrixError, match="protected artifact"):
        matrix.write_report(_evaluate(), "checkpoint.json")
    with pytest.raises(matrix.MatrixError, match="parent traversal"):
        matrix.write_report(_evaluate(), "../matrix.json")
    output_target = tmp_path / "output-target.json"
    output_target.write_text("old\n", encoding="utf-8")
    output_link = tmp_path / "output.json"
    output_link.symlink_to(output_target)
    with pytest.raises(matrix.MatrixError, match="symlink"):
        matrix.write_report(_evaluate(), output_link)
