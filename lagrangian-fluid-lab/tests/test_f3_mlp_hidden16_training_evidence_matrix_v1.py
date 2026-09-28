"""Tests for the independent bounded F3 MLP hidden16 training matrix."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import f3_mlp_hidden16_training_evidence_matrix_v1 as matrix


def _sha(char: str) -> str:
    return char * 63 + ("0" if char != "0" else "1")


def _normalization(seed: int) -> dict:
    return {
        "available_transition_count": 13360,
        "requested_maximum_transitions": 16,
        "schema": matrix.NORMALIZATION_SCHEMA,
        "selected_case_ids": list(matrix.TRAIN_CASE_IDS),
        "selected_transition_bindings": [dict(item) for item in matrix.TRAIN_BINDINGS],
        "selected_transition_count": 16,
        "selected_transition_counts": {case_id: 1 for case_id in matrix.TRAIN_CASE_IDS},
        "selection_policy": "deterministic_evenly_spaced_train_transitions_v1",
        "selection_seed": seed,
        "source_split": "train",
        "target_reference": "raw_dual_increment_train_shared",
        "train_case_ids": list(matrix.TRAIN_CASE_IDS),
    }


def _receipt(seed: int, *, model_kind: str = "mlp") -> dict:
    config = copy.deepcopy(matrix.STATIC_CONFIG)
    config.update(
        {
            "evaluate_milestones": True,
            "milestone_evaluation_mode": "in_process",
            "validation_every": 1000,
            "manifest_sha256": _sha("a"),
            "paired_seed": seed,
            "run_id": f3_run_id(seed),
            "sampler_seed": seed,
            "seed": seed,
        }
    )
    return {
        "schema": matrix.TRAINING_SCHEMA,
        "evidence_status": "complete",
        "status": "completed",
        "model_kind": model_kind,
        "seed": seed,
        "run_id": f3_run_id(seed),
        "completed_updates": 500,
        "parameter_count": matrix.PARAMETER_COUNT,
        "checkpoint_verified": True,
        "config": config,
        "checkpoint": {
            "schema": matrix.CHECKPOINT_SCHEMA,
            "path": f"/tmp/{matrix._checkpoint_path(seed)}",
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
                "model_kind": model_kind,
                "parameter_count": matrix.PARAMETER_COUNT,
                "parameter_digest": _sha("e" if seed == 17 else "f" if seed == 29 else "1"),
                "seed": seed,
            },
            "normalization": _normalization(seed),
            "residual_prior": {"enabled": False, "execution_calls": 0, "rows": 0},
        },
    }


def f3_run_id(seed: int) -> str:
    return f"f3-mlp500-hidden16-seed{seed}-20260928"


def _reference(receipts: dict[int, dict]) -> dict:
    rows = []
    for seed in matrix.SEEDS:
        receipt = receipts[seed]
        config = receipt["config"]
        normalization = receipt["evidence"]["normalization"]
        rows.append(
            {
                "seed": seed,
                "run_id": f3_run_id(seed),
                "model_kind": "mlp",
                "hidden": 16,
                "completed_updates": 500,
                "parameter_count": matrix.PARAMETER_COUNT,
                "checkpoint_verified": True,
                "checkpoint_path": matrix._checkpoint_path(seed),
                "checkpoint_sha256": receipt["checkpoint"]["sha256"],
                "training_receipt_sha256": _sha("7"),
                "progress_receipt_sha256": _sha("8"),
                "initialization_parameter_digest": receipt["evidence"]["initialization"]["parameter_digest"],
                "config_identity_sha256": matrix._identity_sha256(config),
                "normalization_identity_sha256": matrix._identity_sha256(normalization),
                "normalization_transition_count": 16,
            }
        )
    return {
        "schema": matrix.REFERENCE_SCHEMA,
        "report_id": "f3-mlp-hidden16-seeds17-29-43-training-2026-09-28",
        "diagnostic_only": True,
        "formal_eligible": False,
        "model": "mlp",
        "manifest_sha256": _sha("a"),
        "shared_config": copy.deepcopy(matrix.STATIC_CONFIG),
        "runs": rows,
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
        seed: {
            "path": f"/tmp/f3-mlp500-hidden16-seed{seed}-20260928-training.json",
            "exists": True,
            "opened": True,
            "bytes": 1000 + seed,
            "sha256": _sha("7"),
            "schema": matrix.TRAINING_SCHEMA,
        }
        for seed in matrix.SEEDS
    }
    return receipts, sources, _reference(receipts)


def _evaluate(receipts=None, reference=None, sources=None):
    base_receipts, base_sources, base_reference = _payloads()
    return matrix.evaluate_payloads(
        base_receipts if receipts is None else receipts,
        base_sources if sources is None else sources,
        base_reference if reference is None else reference,
        {
            "path": "/tmp/f3-mlp-hidden16-reference.json",
            "exists": True,
            "opened": True,
            "bytes": 2000,
            "sha256": _sha("6"),
            "schema": matrix.REFERENCE_SCHEMA,
        },
    )


def test_complete_mlp_matrix_binds_without_authority():
    report = _evaluate()
    assert report["source_bound"] is True
    assert report["status"] == "training_evidence_bound_diagnostic_only"
    assert report["formal_training_runs_counted"] == 0
    assert report["authorization"]["credit"] == 0
    assert matrix.validate_report(report) == []


def test_graph_raw_receipt_is_rejected_by_model_identity():
    receipts, _, _ = _payloads()
    receipts[29]["model_kind"] = "graph_raw"
    report = _evaluate(receipts)
    assert report["source_bound"] is False
    assert any("seed29" in error and "model_kind" in error for error in report["errors"])


@pytest.mark.parametrize(
    ("field", "value", "needle"),
    [
        ("hidden", 8, "config.hidden"),
        ("updates", 499, "config.updates"),
    ],
)
def test_model_protocol_drift_fails_closed(field, value, needle):
    receipts, _, _ = _payloads()
    receipts[17]["config"][field] = value
    report = _evaluate(receipts)
    assert report["source_bound"] is False
    assert any(needle in error for error in report["errors"])


def test_exact_three_seed_set_is_required():
    receipts, _, _ = _payloads()
    receipts.pop(29)
    report = _evaluate(receipts)
    assert report["status"] == "blocked_fail_closed"
    assert "exact_seed_set" in {item["check"] for item in report["checks"]}
    assert any("seed 29" in error for error in report["errors"])


def test_checkpoint_identity_drift_against_reference_fails_closed():
    receipts, _, reference = _payloads()
    reference["runs"][1]["checkpoint_sha256"] = _sha("9")
    report = _evaluate(receipts, reference)
    assert report["source_bound"] is False
    assert any("checkpoint SHA drifts" in error for error in report["errors"])


def test_training_config_identity_drift_against_reference_fails_closed():
    receipts, _, reference = _payloads()
    receipts[43]["config"]["validation_every"] = 0
    report = _evaluate(receipts, reference)
    assert report["source_bound"] is False
    assert any("training config identity" in error for error in report["errors"])


def test_initialization_identity_drift_against_reference_fails_closed():
    receipts, _, reference = _payloads()
    receipts[17]["evidence"]["initialization"]["parameter_digest"] = _sha("9")
    report = _evaluate(receipts, reference)
    assert report["source_bound"] is False
    assert any("initialization digest" in error for error in report["errors"])


def test_normalization_identity_drift_fails_closed():
    receipts, _, _ = _payloads()
    receipts[29]["evidence"]["normalization"]["selected_transition_bindings"][0]["frame"] = 1
    report = _evaluate(receipts)
    assert report["source_bound"] is False
    assert any("normalization identity" in error for error in report["errors"])


def test_missing_receipt_is_fail_closed():
    receipts, _, _ = _payloads()
    receipts.pop(43)
    report = _evaluate(receipts)
    assert report["fail_closed"] is True
    assert report["runs"][2]["status"] == "missing"


def test_placeholder_checkpoint_hash_is_rejected():
    receipts, _, _ = _payloads()
    receipts[17]["checkpoint"]["sha256"] = "0" * 64
    report = _evaluate(receipts)
    assert report["source_bound"] is False
    assert any("checkpoint.sha256" in error for error in report["errors"])


def test_source_hash_drift_is_rejected():
    receipts, sources, _ = _payloads()
    sources[17]["sha256"] = _sha("9")
    report = _evaluate(receipts, sources=sources)
    assert report["source_bound"] is False
    assert any("training receipt SHA drifts" in error for error in report["errors"])


def test_duplicate_json_keys_are_rejected(tmp_path: Path):
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema":"x","schema":"y"}\n', encoding="utf-8")
    with pytest.raises(matrix.MatrixError, match="duplicate JSON object key"):
        matrix.read_bounded_json(tmp_path, path)


def test_nonfinite_json_is_rejected(tmp_path: Path):
    path = tmp_path / "nonfinite.json"
    path.write_text('{"value":NaN}\n', encoding="utf-8")
    with pytest.raises(matrix.MatrixError, match="non-finite JSON"):
        matrix.read_bounded_json(tmp_path, path)


def test_checkpoint_file_is_not_an_accepted_input(tmp_path: Path):
    path = tmp_path / "weights.pt"
    path.write_bytes(b"not opened as checkpoint content")
    with pytest.raises(matrix.MatrixError, match=r"only \.json inputs"):
        matrix.read_bounded_json(tmp_path, path)


def test_report_tampering_breaks_zero_credit_envelope():
    report = _evaluate()
    tampered = copy.deepcopy(report)
    tampered["credit"] = 1
    assert any("credit must be zero" in error for error in matrix.validate_report(tampered))


def test_cli_returns_blocked_status_for_missing_reference(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "matrix.json"
    markdown = tmp_path / "matrix.md"
    status = matrix.main(
        [
            "--reference-matrix",
            str(tmp_path / "missing-reference.json"),
            "--output",
            "matrix.json",
            "--markdown-output",
            "matrix.md",
        ]
    )
    assert status == 2
    assert output.is_file()
    assert markdown.is_file()
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "blocked_fail_closed"
    assert matrix.validate_report(report) == []


def test_source_metadata_and_exact_source_seed_set_are_required():
    receipts, sources, reference = _payloads()
    del sources[17]["schema"]
    report = _evaluate(receipts, reference, sources)
    assert report["source_bound"] is False
    assert any("source metadata" in error for error in report["errors"])

    receipts, sources, reference = _payloads()
    sources[99] = copy.deepcopy(sources[17])
    report = _evaluate(receipts, reference, sources)
    assert report["source_bound"] is False
    assert any("source seed set" in error for error in report["errors"])

    receipts, sources, reference = _payloads()
    report = matrix.evaluate_payloads(receipts, sources, reference, None)
    assert report["source_bound"] is False
    assert any("reference source" in error for error in report["errors"])


def test_strict_numeric_identity_fails_closed():
    receipts, sources, reference = _payloads()
    receipts[29]["config"]["hidden"] = 16.0
    report = _evaluate(receipts, reference, sources)
    assert report["source_bound"] is False
    assert any("config.hidden" in error for error in report["errors"])


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
