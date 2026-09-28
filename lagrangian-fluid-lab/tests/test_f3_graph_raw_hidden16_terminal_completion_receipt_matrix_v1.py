"""Focused tests for the F3 three-seed terminal receipt matrix adapter."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts import (
    f3_graph_raw_hidden16_terminal_completion_receipt_matrix_v1 as matrix,
)


def _write_json(path: Path, payload: dict) -> tuple[int, str]:
    raw = matrix.canonical_json(payload).encode("utf-8") + b"\n"
    path.write_bytes(raw)
    return len(raw), hashlib.sha256(raw).hexdigest()


def _checkpoint(seed: int) -> dict[str, object]:
    return {
        "path": f"/opaque/checkpoints/f3-graph-raw500-hidden16-seed{seed}.pt",
        "bytes": 1000 + seed,
        "sha256": f"{seed:064x}"[-64:],
        "update": matrix.UPDATES,
        "schema": "core.checkpoint.v1",
        "content_opened": False,
        "stat_only": True,
    }


def _nested_receipt(seed: int, *, namespace_seed: int | None = None) -> dict:
    namespace_seed = seed if namespace_seed is None else namespace_seed
    prefix = (
        f"/opaque/f3-graph-raw500-hidden16-seed{namespace_seed}-full835-"
        f"matrix-seed{seed}"
    )
    checkpoint = _checkpoint(seed)
    training_path = f"/opaque/seed{seed}-training.json"
    evaluation_path = prefix + "-evaluation.json"
    trajectory_path = prefix + "-trajectory.h5"
    progress_path = prefix + "-evaluation-progress.json"
    return {
        "schema": (
            f"core.f3.graph_raw.hidden16.seed{seed}.full835."
            "terminal_evidence.receipt.v1"
        ),
        "report_id": f"seed{seed}-terminal-evidence",
        "status": "completed_diagnostic",
        "diagnostic_only": True,
        "non_formal_diagnostic": True,
        "formal_eligible": False,
        "seed": seed,
        "model_kind": matrix.MODEL_KIND,
        "hidden": matrix.HIDDEN,
        "updates": matrix.UPDATES,
        "transitions": matrix.TRANSITIONS,
        "frames": matrix.FRAMES,
        "future_state_inputs": False,
        "terminal_markers": {
            "terminal": True,
            "execution_complete": True,
            "finite_rollout_complete": True,
            "terminal_status": "completed",
            "source_evaluation_status": "completed",
            "source_validator_passed": True,
        },
        "case": {
            "case_id": matrix.CASE_ID,
            "family": "F3",
            "split": matrix.SPLIT,
            "registered_transitions": matrix.TRANSITIONS,
            "registered_source_frames": matrix.FRAMES,
        },
        "checkpoint": checkpoint,
        "training_binding": {
            "path": training_path,
            "bytes": 2000 + seed,
            "sha256": f"{seed + 100:064x}"[-64:],
            "schema": "core.training.v1",
            "completed_updates": matrix.UPDATES,
            "config": {
                "model_kind": matrix.MODEL_KIND,
                "hidden": matrix.HIDDEN,
                "seed": seed,
                "updates": matrix.UPDATES,
                "max_neighbors": 192,
                "target_normalization": "raw_dual_increment_train_shared",
            },
            "checkpoint_verified": True,
            "checkpoint": {
                "path": checkpoint["path"],
                "sha256_claimed": checkpoint["sha256"],
                "bytes_claimed": checkpoint["bytes"],
                "update": matrix.UPDATES,
            },
        },
        "evaluation_binding": {
            "path": evaluation_path,
            "bytes": 3000 + seed,
            "sha256": f"{seed + 200:064x}"[-64:],
            "schema": "core.evaluation.v1",
            "mode": "diagnostic",
            "diagnostic": True,
            "requested_steps": matrix.TRANSITIONS,
            "frames_executed": matrix.TRANSITIONS,
            "trajectory_frames_including_initial": matrix.FRAMES,
            "full_registered_denominator_complete": True,
            "future_state_inputs": False,
        },
        "trajectory_binding": {
            "path": trajectory_path,
            "bytes": 4000 + seed,
            "content_opened": False,
            "stat_only": True,
            "hdf5_validator": {
                "passed": True,
                "complete": True,
                "trajectory_frames": matrix.FRAMES,
                "trajectory_transitions": matrix.TRANSITIONS,
                "executed_frame_count": matrix.FRAMES,
                "tail_frame_count": 0,
                "qualification_credit": 0,
                "synthetic_only": False,
                "production_artifacts_touched": False,
            },
        },
        "progress_binding": {
            "path": progress_path,
            "bytes": 500 + seed,
            "content_opened": False,
            "stat_only": True,
            "completion_not_inferred": True,
        },
        "qualification": {
            "formal_training": False,
            "formal_eligible": False,
            "T1_numerical": False,
            "T2_macro": False,
            "T2_path": False,
            "qualification": False,
            "qualification_credit": 0,
        },
        "qualification_credit": 0,
        "credit": 0,
        "side_effects": {
            "manifest_opened": False,
            "case_hdf5_opened": False,
            "checkpoint_opened": False,
            "trajectory_hdf5_opened": False,
            "progress_opened": False,
            "runtime_started": False,
            "solver_started": False,
            "worker_started": False,
            "gpu_started": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "gate_mutation": 0,
            "completion_mutation": 0,
            "rollout_inputs_read_only": True,
        },
    }


def _bridge_report(seed: int) -> dict:
    receipt = _nested_receipt(seed)
    return {
        "schema": matrix.BRIDGE_SCHEMA,
        "report_id": "synthetic-terminal-evidence-bridge",
        "status": "bound_terminal_diagnostic",
        "source_bound": True,
        "fail_closed": False,
        "bound_seed_count": 1,
        "bound_seeds": [seed],
        "missing_seeds": [other for other in matrix.SEEDS if other != seed],
        "rejected_seeds": [],
        "checks": {
            "all_bound_receipts_are_full_horizon": True,
            "all_bound_receipts_are_zero_credit_diagnostic": True,
        },
        "side_effects": matrix._empty_side_effects(),
        "input_boundary": {
            "bounded_summary_validator_training_json": True,
            "checkpoint_stat_only": True,
            "trajectory_stat_only": True,
            "evaluation_json_stream_hashed": True,
            "manifest_opened": False,
            "case_hdf5_opened": False,
            "checkpoint_opened": False,
            "trajectory_hdf5_opened": False,
            "progress_opened": False,
        },
        "seed_matrix": [
            {
                "seed": seed,
                "status": "bound_terminal_diagnostic",
                "blocked_reasons": [],
                "side_effects": {
                    "case_hdf5_opened": False,
                    "checkpoint_opened": False,
                    "trajectory_hdf5_opened": False,
                    "progress_opened": False,
                    "runtime_started": False,
                    "gpu_started": False,
                    "worker_started": False,
                },
                "terminal_receipt": receipt,
            }
        ],
    }


def _completion_report(seed: int, *, nested: bool = True) -> dict:
    if nested:
        terminal = _nested_receipt(seed)
        report = {
            "schema": f"core.f3.graph_raw.hidden16.seed{seed}.terminal_completion_receipt.v1",
            "report_id": f"seed{seed}-terminal-completion",
            "status": "bound_terminal_diagnostic",
            "source_bound": True,
            "fail_closed": False,
            "seed": seed,
            "model_kind": matrix.MODEL_KIND,
            "hidden": matrix.HIDDEN,
            "updates": matrix.UPDATES,
            "diagnostic_only": True,
            "formal_eligible": False,
            "qualification_credit": 0,
            "credit": 0,
            "formal": False,
            "T1_numerical": False,
            "T2_macro": False,
            "T2_path": False,
            "qualification": False,
            "side_effects": matrix._empty_side_effects(),
            "seed29_terminal_receipt": terminal,
        }
        if seed == 29:
            # Match the normalized receipt emitted by the seed29 runner:
            # training identity lives on the outer report, while the nested
            # terminal projection carries the checkpoint claim.
            training = terminal["training_binding"]
            report["training_source"] = {
                "path": training["path"],
                "bytes": training["bytes"],
                "sha256": training["sha256"],
                "schema": "core.training.v1",
                "exists": True,
                "opened": True,
            }
            terminal.pop("status")
            terminal.pop("schema")
            terminal.pop("case")
            terminal["case_id"] = matrix.CASE_ID
            terminal["split"] = matrix.SPLIT
            checkpoint = terminal.pop("checkpoint")
            training["checkpoint"] = {
                "path": checkpoint["path"],
                "bytes_claimed": checkpoint["bytes"],
                "sha256_claimed": checkpoint["sha256"],
                "content_opened": False,
                "update": matrix.UPDATES,
            }
            training.update(
                {
                    "model_kind": matrix.MODEL_KIND,
                    "seed": seed,
                    "hidden": matrix.HIDDEN,
                    "updates": matrix.UPDATES,
                }
            )
            for key in ("path", "bytes", "sha256", "completed_updates", "checkpoint_verified"):
                training.pop(key, None)
            terminal["evaluation_binding"]["evaluation_mode"] = terminal["evaluation_binding"].pop("mode")
            terminal["trajectory_binding"].pop("hdf5_validator")
        return report

    prefix = (
        f"/opaque/f3-graph-raw500-hidden16-seed{seed}-full835-"
        f"completion-seed{seed}"
    )
    training_path = f"/opaque/seed{seed}-training.json"
    evaluation_path = prefix + "-evaluation.json"
    trajectory_path = prefix + "-trajectory.h5"
    validator_path = f"/opaque/seed{seed}-hdf5-validation.json"
    checkpoint_path = f"/opaque/checkpoints/f3-graph-raw500-hidden16-seed{seed}.pt"

    def claim(path: str, byte_count: int, digest: str, **extra: object) -> dict:
        return {
            "path": path,
            "claimed_bytes": byte_count,
            "claimed_sha256": digest,
            "exists": True,
            "regular_file": True,
            "symlink": False,
            "stat_bytes": byte_count,
            "bytes_match": True,
            **extra,
        }

    return {
        "schema": f"core.f3.graph_raw.hidden16.seed{seed}.terminal_completion_receipt.v1",
        "report_id": f"seed{seed}-terminal-completion",
        "status": "bound_existing_terminal_summary",
        "source_bound": True,
        "fail_closed": False,
        "seed": seed,
        "model_kind": matrix.MODEL_KIND,
        "hidden": matrix.HIDDEN,
        "updates": matrix.UPDATES,
        "diagnostic_only": True,
        "formal_eligible": False,
        "qualification_credit": 0,
        "formal": False,
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "qualification": False,
        "terminal_markers": {
            "case_id": matrix.CASE_ID,
            "model_kind": matrix.MODEL_KIND,
            "seed": seed,
            "hidden": matrix.HIDDEN,
            "updates": matrix.UPDATES,
            "transitions": matrix.TRANSITIONS,
            "frames": matrix.FRAMES,
            "validator": {
                "passed": True,
                "complete": True,
                "trajectory_frames": matrix.FRAMES,
                "trajectory_transitions": matrix.TRANSITIONS,
                "tail_frame_count": 0,
            },
        },
        "identity_bindings": {
            "training_receipt": claim(
                training_path,
                2000 + seed,
                f"{seed + 100:064x}"[-64:],
                content_opened=True,
                hash_verification="verified",
                hash_match=True,
            ),
            "evaluation_receipt": claim(
                evaluation_path,
                3000 + seed,
                f"{seed + 200:064x}"[-64:],
                content_opened=True,
                hash_verification="verified",
                hash_match=True,
                actual_sha256=f"{seed + 200:064x}"[-64:],
            ),
            "checkpoint": claim(
                checkpoint_path,
                1000 + seed,
                f"{seed:064x}"[-64:],
                content_opened=False,
            ),
            "trajectory": claim(
                trajectory_path,
                4000 + seed,
                f"{seed + 300:064x}"[-64:],
                content_opened=False,
            ),
            "hdf5_validation": claim(
                validator_path,
                500 + seed,
                f"{seed + 400:064x}"[-64:],
                content_opened=False,
            ),
        },
        "scope": {
            "checkpoint_content_opened": False,
            "denominator_mutation": 0,
            "existing_live_job_restart_count": 0,
            "existing_live_job_stop_count": 0,
            "gate_mutation": 0,
            "hdf5_content_opened": False,
            "ledger_mutation": 0,
            "manifest_content_opened": False,
            "new_evaluation_started": False,
            "progress_content_opened": False,
            "queue_submissions": 0,
            "registry_mutation": 0,
            "solver_started": False,
            "trajectory_content_opened": False,
            "worker_started": False,
        },
    }


def _write_sources(tmp_path: Path, *, seed29_nested: bool = True) -> dict[int, Path]:
    payloads = {
        17: _bridge_report(17),
        29: _completion_report(29, nested=seed29_nested),
        43: _completion_report(43, nested=False),
    }
    paths: dict[int, Path] = {}
    for seed, payload in payloads.items():
        path = tmp_path / f"seed{seed}-terminal-receipt.json"
        _write_json(path, payload)
        paths[seed] = path
    return paths


def test_complete_matrix_accepts_bridge_and_both_completion_projection_shapes(
    tmp_path: Path,
) -> None:
    paths = _write_sources(tmp_path)
    report = matrix.build_report(
        tmp_path,
        terminal_paths=paths,
        observed_at_utc="2026-09-28T12:00:00Z",
    )

    assert report["status"] == "bound_terminal_diagnostic"
    assert report["source_bound"] is True
    assert [row["status"] for row in report["seed_matrix"]] == [
        "bound_terminal_diagnostic",
        "bound_terminal_diagnostic",
        "bound_terminal_diagnostic",
    ]
    assert matrix.validate_report(report) == []
    assert report["credit"] == 0
    assert report["input_boundary"]["checkpoint_opened"] is False
    assert report["input_boundary"]["trajectory_hdf5_opened"] is False
    assert report["input_boundary"]["progress_opened"] is False


def test_default_seed29_is_missing_and_does_not_assume_pending_runner_completion() -> None:
    report = matrix.build_report()

    assert report["source_bound"] is False
    assert report["status"] == "blocked_fail_closed"
    seed29 = next(row for row in report["seed_matrix"] if row["seed"] == 29)
    assert seed29["status"] == "missing"
    assert seed29["projection"] is None
    assert matrix.validate_report(report) == []


@pytest.mark.parametrize(
    ("mutator", "needle"),
    [
        (lambda payload: payload["seed29_terminal_receipt"].update({"frames": 835}), "frames"),
        (lambda payload: payload["seed29_terminal_receipt"].update({"credit": 1}), "credit"),
    ],
)
def test_terminal_drift_is_fail_closed(tmp_path: Path, mutator, needle: str) -> None:
    paths = _write_sources(tmp_path)
    payload = json.loads(paths[29].read_text(encoding="utf-8"))
    mutator(payload)
    _write_json(paths[29], payload)

    report = matrix.build_report(tmp_path, terminal_paths=paths)

    assert report["source_bound"] is False
    assert report["status"] == "blocked_fail_closed"
    seed29 = next(row for row in report["seed_matrix"] if row["seed"] == 29)
    assert seed29["status"] == "rejected"
    if needle == "checkpoint.sha256":
        assert any("checkpoint" in reason for reason in seed29["blocked_reasons"])
    else:
        assert any(needle in reason for reason in seed29["blocked_reasons"])
    assert matrix.validate_report(report) == []


def test_checkpoint_path_or_sha_mismatch_is_fail_closed(tmp_path: Path) -> None:
    paths = _write_sources(tmp_path)
    payload = json.loads(paths[17].read_text(encoding="utf-8"))
    payload["seed_matrix"][0]["terminal_receipt"]["checkpoint"]["sha256"] = "f" * 64
    _write_json(paths[17], payload)

    report = matrix.build_report(tmp_path, terminal_paths=paths)

    assert report["source_bound"] is False
    row = next(row for row in report["seed_matrix"] if row["seed"] == 17)
    assert row["status"] == "rejected"
    assert any("checkpoint" in reason for reason in row["blocked_reasons"])
    assert matrix.validate_report(report) == []


def test_duplicate_output_namespace_is_rejected(tmp_path: Path) -> None:
    paths = _write_sources(tmp_path)
    seed43 = json.loads(paths[43].read_text(encoding="utf-8"))
    seed43["identity_bindings"]["evaluation_receipt"]["path"] = (
        "/opaque/f3-graph-raw500-hidden16-seed29-full835-completion-seed29-evaluation.json"
    )
    seed43["identity_bindings"]["trajectory"]["path"] = (
        "/opaque/f3-graph-raw500-hidden16-seed29-full835-completion-seed29-trajectory.h5"
    )
    _write_json(paths[43], seed43)

    report = matrix.build_report(tmp_path, terminal_paths=paths)

    assert report["source_bound"] is False
    assert any("namespaces" in reason for reason in report["blocked_reasons"])
    assert matrix.validate_report(report) == []


def test_forbidden_progress_input_is_rejected_without_opening_it(tmp_path: Path) -> None:
    paths = _write_sources(tmp_path)
    forbidden = tmp_path / "seed29-evaluation-progress.json"
    forbidden.write_bytes(paths[29].read_bytes())
    paths[29] = forbidden

    report = matrix.build_report(tmp_path, terminal_paths=paths)

    assert report["source_bound"] is False
    seed29 = next(row for row in report["seed_matrix"] if row["seed"] == 29)
    assert seed29["status"] == "rejected"
    assert "forbidden progress" in seed29["blocked_reasons"][0]
    assert seed29["source"]["opened"] is False


def test_current_checked_in_seed17_bridge_and_seed43_receipt_are_compatible() -> None:
    paths = {
        17: matrix.DEFAULT_TERMINAL_PATHS[17],
        29: None,
        43: matrix.DEFAULT_TERMINAL_PATHS[43],
    }
    report = matrix.build_report(terminal_paths=paths)

    assert report["source_bound"] is False
    assert next(row for row in report["seed_matrix"] if row["seed"] == 17)["status"] == "bound_terminal"
    assert next(row for row in report["seed_matrix"] if row["seed"] == 43)["status"] == "bound_terminal"
    assert matrix.validate_report(report) == []


def test_report_validation_catches_zero_credit_or_bound_status_drift(tmp_path: Path) -> None:
    paths = _write_sources(tmp_path)
    report = matrix.build_report(tmp_path, terminal_paths=paths)
    assert matrix.validate_report(report) == []

    drifted = copy.deepcopy(report)
    drifted["credit"] = 1
    assert matrix.validate_report(drifted)

    drifted = copy.deepcopy(report)
    drifted["status"] = "blocked_fail_closed"
    assert matrix.validate_report(drifted)


def test_cli_writes_only_explicit_report_path(tmp_path: Path, capsys) -> None:
    paths = _write_sources(tmp_path)
    output = tmp_path / "matrix-report.json"
    args = [
        "--root",
        str(tmp_path),
        "--receipt",
        f"17={paths[17]}",
        "--receipt",
        f"29={paths[29]}",
        "--receipt",
        f"43={paths[43]}",
        "--output",
        str(output),
    ]
    assert matrix.main(args) == 0
    printed = json.loads(capsys.readouterr().out)
    written = json.loads(output.read_text(encoding="utf-8"))
    assert printed == written
    assert written["source_bound"] is True
    assert matrix.validate_report(written) == []
