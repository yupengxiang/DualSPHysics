"""Contract tests for the bounded F3 cross-seed rollout matrix adapter."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from scripts import f3_cross_seed_rollout_consistency_v1 as consistency


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / (
    "reports/F3-GRAPH-RAW-HIDDEN16-CROSS-SEED-ROLLOUT-CONSISTENCY-V1-2026-09-28.json"
)
EXPECTED_SEEDS = (17, 29, 43)


def _sha(letter: str) -> str:
    return letter * 64


def _training(seed: int) -> dict:
    checkpoint_sha = _sha(chr(ord("a") + EXPECTED_SEEDS.index(seed)))
    config = copy.deepcopy(consistency.REQUIRED_TRAINING_CONFIG)
    config.update(
        {
            "manifest_sha256": _sha("f"),
            "paired_seed": seed,
            "run_id": f"graph_raw-hidden16-seed{seed}",
            "sampler_seed": seed,
            "seed": seed,
        }
    )
    return {
        "schema": "core.training.v1",
        "run_id": f"graph_raw-hidden16-seed{seed}",
        "model_kind": "graph_raw",
        "seed": seed,
        "completed_updates": 500,
        "evidence_status": "complete",
        "checkpoint_verified": True,
        "parameter_count": 6086,
        "config": config,
        "evidence": {
            "schema": "core.training.evidence.v1",
            "status": "complete",
            "initialization": {
                "schema": "core.training.initialization_evidence.v1",
                "status": "captured",
                "model_kind": "graph_raw",
                "seed": seed,
                "hidden": 16,
                "parameter_count": 6086,
                "parameter_digest": _sha("1"),
            },
            "normalization": {
                "schema": "core.training.normalization_evidence.v1",
                "requested_maximum_transitions": 16,
                "selected_transition_count": 16,
                "selection_policy": "deterministic_evenly_spaced_train_transitions_v1",
                "source_split": "train",
                "target_reference": "raw_dual_increment_train_shared",
            },
            "residual_prior": {
                "enabled": False,
            },
        },
        "checkpoint": {
            "schema": "core.checkpoint.v1",
            "path": f"/tmp/f3-graph-raw500-hidden16-seed{seed}-checkpoint.pt",
            "sha256": checkpoint_sha,
            "update": 500,
        },
    }


def _rollout(seed: int, training: dict, training_source: dict) -> dict:
    prefix = f"/tmp/f3-graph-raw500-hidden16-seed{seed}-full835-test"
    checkpoint = training["checkpoint"]
    return {
        "schema": "core.f3.graph_raw.hidden16.full835.rollout_diagnostic.summary.v1",
        "report_id": f"synthetic-seed{seed}",
        "status": "completed_diagnostic",
        "diagnostic_only": True,
        "formal_eligible": False,
        "qualification_credit": 0,
        "future_state_inputs": False,
        "qualification": {
            "T1_numerical": False,
            "T2_macro": False,
            "T2_path": False,
            "formal_eligible": False,
            "formal_training": False,
            "qualification_credit": 0,
            "credit": 0,
        },
        "side_effects": {
            "completion_mutation": False,
            "denominator_mutation": 0,
            "diagnostic_counted_as_T1_or_T2": False,
            "formal_training_counted": False,
            "future_state_inputs": False,
            "gate_mutation": 0,
            "ledger_mutation": 0,
            "manifest_modified": False,
            "production_hdf5_modified": False,
            "registry_mutation": 0,
            "rollout_inputs_read_only": True,
            "source_modified_by_rollout": False,
        },
        "protocol": {
            "autonomous": True,
            "case_id": "F3_DEV_00_a0p903125",
            "centers_per_update": 256,
            "diagnostic": True,
            "future_state_inputs": False,
            "hidden": 16,
            "learning_rate": 0.001,
            "max_neighbors": 192,
            "maximum_steps": 835,
            "model_kind": "graph_raw",
            "normalization_source_split": "train",
            "normalization_transitions": 16,
            "parameter_count": 6086,
            "seed": seed,
            "split": "test",
            "target_normalization": "raw_dual_increment_train_shared",
            "training_started_for_this_rollout": False,
            "updates": 500,
        },
        "training": {
            "schema": "core.training.v1",
            "status": "completed",
            "evidence_status": "complete",
            "model_kind": "graph_raw",
            "seed": seed,
            "hidden": 16,
            "completed_updates": 500,
            "parameter_count": 6086,
            "checkpoint_verified": True,
            "residual_prior_enabled": False,
        },
        "bindings": {
            "checkpoint": {
                "schema": "core.checkpoint.v1",
                "path": checkpoint["path"],
                "sha256": checkpoint["sha256"],
                "update": 500,
                "model_kind": "graph_raw",
                "seed": seed,
                "hidden": 16,
                "parameter_count": 6086,
            },
            "checkpoint_hash_matches_training_receipt": True,
            "checkpoint_verified": True,
            "evaluation_checkpoint_path_matches_training": True,
            "training_protocol_binding_exact": True,
            "training_receipt": {
                "path": training_source["path"],
                "sha256": training_source["sha256"],
            },
        },
        "evaluation": {
            "schema": "core.evaluation.v1",
            "mode": "diagnostic",
            "diagnostic": True,
            "formal_eligible": False,
            "future_state_inputs": False,
            "status": "completed",
            "requested_steps": 835,
            "expected_full_case_transitions": 835,
            "expected_full_case_frames": 836,
            "frames_executed": 835,
            "trajectory_frames_including_initial": 836,
            "requested_window_complete": True,
            "finite_rollout_complete_for_requested_window": True,
            "full_registered_denominator_complete": True,
            "failure_category": None,
            "scientific_failure_category": None,
            "scientific_status": "not_assessed",
            "split": "test",
            "raw_error_coverage": {
                "denominator_transitions": 835,
                "numerator_transitions": 835,
                "fraction": 1.0,
            },
            "receipt": {
                "path": prefix + "-evaluation.json",
                "bytes": 100,
                "sha256": _sha("2"),
            },
            "progress": {
                "path": prefix + "-evaluation-progress.json",
                "bytes": 100,
                "sha256": _sha("3"),
                "status": "completed",
                "expected_frames": 835,
                "frames_executed": 835,
                "future_state_inputs": False,
            },
            "hdf5_validation": {
                "schema": "core.f3.full_rollout_receipt_hdf5_validation.v1",
                "passed": True,
                "complete": True,
                "executed_frame_count": 836,
                "trajectory_frames": 836,
                "trajectory_transitions": 835,
                "qualification_credit": 0,
                "synthetic_only": False,
            },
        },
        "trajectory": {
            "path": prefix + "-trajectory.h5",
            "bytes": 100,
            "sha256": _sha("4"),
            "hdf5_attrs": {"future_state_inputs": False},
            "shapes": {
                "position": [836, 34560, 3],
                "velocity": [836, 34560, 3],
                "valid": [836, 34560],
                "time": [836],
            },
            "position_finite": True,
            "velocity_finite": True,
            "valid_all_true": True,
            "mass_finite": True,
            "mass_positive": True,
            "mass_static": True,
        },
    }


def _fixture() -> tuple[dict, dict, dict, dict, dict]:
    trainings = {seed: _training(seed) for seed in EXPECTED_SEEDS}
    training_sources = {
        seed: consistency._source_ref_for_payload(
            trainings[seed], f"/tmp/synthetic-training-seed{seed}.json"
        )
        for seed in EXPECTED_SEEDS
    }
    rollouts = {
        seed: _rollout(seed, trainings[seed], training_sources[seed])
        for seed in EXPECTED_SEEDS
    }
    rollout_sources = {
        seed: consistency._source_ref_for_payload(
            rollouts[seed], f"/tmp/synthetic-rollout-seed{seed}.json"
        )
        for seed in EXPECTED_SEEDS
    }
    matrix = {
        "schema": "core.f3.graph_raw.hidden16.training_matrix.v1",
        "model": "graph_raw",
        "diagnostic_only": True,
        "formal_eligible": False,
        "qualification": {
            "qualification": False,
            "t1": False,
            "t2": False,
            "credit": 0,
        },
        "shared_config": {
            "hidden": 16,
            "updates": 500,
            "centers_per_update": 256,
            "learning_rate": 0.001,
            "max_neighbors": 192,
            "normalization_transitions": 16,
            "target_normalization": "raw_dual_increment_train_shared",
            "validation_transition_count": 4,
            "manifest_formal_release": False,
        },
        "runs": [
            {
                "seed": seed,
                "run_id": f"graph_raw-hidden16-seed{seed}",
                "completed_updates": 500,
                "checkpoint_verified": True,
                "parameter_count": 6086,
                "checkpoint_sha256": trainings[seed]["checkpoint"]["sha256"],
                "training_receipt_sha256": training_sources[seed]["sha256"],
            }
            for seed in EXPECTED_SEEDS
        ],
    }
    return trainings, rollouts, training_sources, rollout_sources, matrix


def _evaluate(fixture: tuple[dict, dict, dict, dict, dict]) -> dict:
    trainings, rollouts, training_sources, rollout_sources, matrix = fixture
    return consistency.evaluate_payloads(
        trainings,
        rollouts,
        training_sources=training_sources,
        rollout_sources=rollout_sources,
        training_matrix=matrix,
        training_matrix_source={"path": "synthetic://matrix.json", "opened": False},
    )


def test_three_seed_terminal_matrix_binds_shared_config_and_zero_side_effects():
    report = _evaluate(_fixture())

    assert report["status"] == "bound_terminal_diagnostic"
    assert report["source_bound"] is True
    assert report["fail_closed"] is False
    assert [row["status"] for row in report["seed_matrix"]] == [
        "bound_terminal_diagnostic",
        "bound_terminal_diagnostic",
        "bound_terminal_diagnostic",
    ]
    assert report["expected_contract"]["expected_transitions"] == 835
    assert report["expected_contract"]["expected_frames"] == 836
    assert report["diagnostic_only"] is True
    assert report["formal_eligible"] is False
    assert report["T1_numerical"] is False
    assert report["T2_macro"] is False
    assert report["qualification"] is False
    assert report["qualification_credit"] == 0
    assert report["credit"] == 0
    assert report["side_effects"]["registry_mutation"] == 0
    assert report["side_effects"]["ledger_mutation"] == 0
    assert report["side_effects"]["denominator_mutation"] == 0
    assert report["side_effects"]["gate_mutation"] == 0


def test_seed29_hidden_mismatch_fails_closed():
    fixture = _fixture()
    fixture[1][29]["protocol"]["hidden"] = 8

    report = _evaluate(fixture)

    assert report["status"] == "blocked_fail_closed"
    assert report["fail_closed"] is True
    row = next(item for item in report["seed_matrix"] if item["seed"] == 29)
    assert row["status"] == "blocked"
    assert row["rollout"]["status"] == "rejected"
    assert "hidden" in row["rollout"]["error"]
    assert report["qualification_credit"] == 0
    assert report["credit"] == 0


def test_missing_or_partial_terminal_receipt_fails_closed():
    missing = _fixture()
    missing[1].pop(29)
    report = _evaluate(missing)
    assert report["status"] == "blocked_fail_closed"
    missing_row = next(item for item in report["seed_matrix"] if item["seed"] == 29)
    assert missing_row["rollout"]["status"] == "missing"

    partial = _fixture()
    partial[1][17]["status"] = "partial"
    report = _evaluate(partial)
    assert report["status"] == "blocked_fail_closed"
    partial_row = next(item for item in report["seed_matrix"] if item["seed"] == 17)
    assert partial_row["rollout"]["status"] == "rejected"
    assert "terminal" in partial_row["rollout"]["error"] or "running/partial" in partial_row["rollout"]["error"]


def test_zero_credit_formal_and_future_state_markers_fail_closed():
    for mutation in ("credit", "formal", "future_state"):
        fixture = _fixture()
        rollout = fixture[1][43]
        if mutation == "credit":
            rollout["qualification_credit"] = 1
        elif mutation == "formal":
            rollout["formal_eligible"] = True
        else:
            rollout["future_state_inputs"] = True

        report = _evaluate(fixture)

        assert report["status"] == "blocked_fail_closed"
        assert report["qualification_credit"] == 0
        assert report["credit"] == 0
        assert report["formal_eligible"] is False
        assert report["input_boundary"]["manifest_opened"] is False
        assert report["input_boundary"]["progress_opened"] is False


def test_report_binding_and_current_external_blockers_are_explicit():
    report = json.loads(REPORT.read_text(encoding="utf-8"))

    assert consistency.build_report(ROOT) == report
    assert report["status"] == "blocked_fail_closed"
    assert report["diagnostic_only"] is True
    assert report["formal_eligible"] is False
    assert report["qualification_credit"] == 0
    assert report["credit"] == 0
    seed29 = next(item for item in report["seed_matrix"] if item["seed"] == 29)
    assert seed29["rollout"]["status"] == "rejected"
    assert seed29["rollout"]["observed"]["hidden"] == 8
    assert any("seed29 rollout" in reason for reason in report["blocked_reasons"])
    seed43 = next(item for item in report["seed_matrix"] if item["seed"] == 43)
    assert seed43["rollout"]["status"] == "missing"
    assert any("duplicate JSON object key" in reason for reason in report["blocked_reasons"])

    tampered = copy.deepcopy(report)
    tampered["qualification_credit"] = 1
    assert tampered != consistency.build_report(ROOT)


def test_build_report_never_opens_disallowed_artifacts(monkeypatch):
    original_read_bytes = Path.read_bytes

    def guarded_read_bytes(path: Path):
        if path.suffix.lower() in {".h5", ".hdf5", ".pt", ".pth"} or "progress" in path.name:
            raise AssertionError(f"adapter attempted to open disallowed artifact: {path}")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)
    report = consistency.build_report(ROOT)

    assert report["input_boundary"]["case_hdf5_opened"] is False
    assert report["input_boundary"]["checkpoint_opened"] is False
    assert report["input_boundary"]["trajectory_hdf5_opened"] is False
    assert report["input_boundary"]["progress_opened"] is False
