"""Tests for the bounded graph_residual current-manifest training intake."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from scripts import f3_graph_residual_hidden16_current_manifest_training_evidence_v1 as intake


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _manifest(tmp_path: Path) -> tuple[Path, str]:
    payload = {
        "case_count": 32,
        "dataset_id": "fixture-current-manifest",
        "formal_release": False,
        "schema": "core.dataset.v2",
    }
    path = _write_json(tmp_path / "current-manifest.json", payload)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return path, hashlib.sha256(canonical).hexdigest()


def _receipt(tmp_path: Path, seed: int, manifest_sha256: str, *, plan_date: str = intake.PLAN_DATE) -> Path:
    run_id = intake._expected_run_id(seed, plan_date)
    path = tmp_path / f"{run_id}-training.json"
    checkpoint_path = tmp_path / f"{run_id}-checkpoint.pt"
    config = intake.matrix._launch_config(
        manifest_sha256,
        seed,
        run_id,
        deferred_validation=True,
    )
    payload = {
        "checkpoint": {
            "bytes": 155000 + seed,
            "path": str(checkpoint_path),
            "schema": intake.CHECKPOINT_SCHEMA,
            "sha256": _sha(f"checkpoint-{seed}"),
            "update": intake.UPDATES,
        },
        "checkpoint_verified": True,
        "completed_updates": intake.UPDATES,
        "config": config,
        "evidence": {
            "initialization": {
                "constructed_before_first_update": True,
                "construction_update": 0,
                "hidden": intake.HIDDEN,
                "model_kind": intake.MODEL,
                "parameter_count": intake.PARAMETER_COUNT,
                "parameter_digest": _sha(f"parameter-{seed}"),
                "schema": intake.INITIALIZATION_SCHEMA,
                "seed": seed,
                "status": "captured",
            },
            "normalization": {
                "available_transition_count": 13360,
                "requested_maximum_transitions": intake.NORMALIZATION_TRANSITIONS,
                "schema": intake.NORMALIZATION_SCHEMA,
                "selected_transition_count": intake.NORMALIZATION_TRANSITIONS,
                "selection_policy": "deterministic_evenly_spaced_train_transitions_v1",
                "selection_seed": seed,
                "source_split": "train",
                "target_reference": "raw_dual_increment_train_shared",
            },
            "residual_prior": {
                "dv_abs_max_mps": 0.1 + seed / 1000,
                "dv_abs_sum_mps": 1000.0 + seed,
                "dx_abs_max_m": 0.01 + seed / 10000,
                "dx_abs_sum_m": 100.0 + seed,
                "enabled": True,
                "execution_calls": intake.UPDATES,
                "finite": True,
                "history_complete": True,
                "last_update": {
                    "case_id": "F3_DEV_00_a0p903125",
                    "frame": seed,
                    "update": intake.UPDATES,
                },
                "rows": intake.PRIOR_ROWS,
                "schema": intake.PRIOR_SCHEMA,
                "semantic": "graph_residual subtracts this SI prior before shared raw-target normalization; predictor adds it back",
                "units": {"delta_velocity": "m/s", "displacement": "m"},
            },
            "schema": intake.EVIDENCE_SCHEMA,
            "status": "complete",
        },
        "evidence_status": "complete",
        "model_kind": intake.MODEL,
        "parameter_count": intake.PARAMETER_COUNT,
        "run_id": run_id,
        "schema": intake.TRAINING_SCHEMA,
        "seed": seed,
        "status": "completed",
    }
    return _write_json(path, payload)


def _paths(tmp_path: Path, manifest_sha256: str) -> dict[int, Path]:
    return {seed: _receipt(tmp_path, seed, manifest_sha256) for seed in intake.SEEDS}


def test_matching_current_manifest_binds_residual_training_only(tmp_path: Path) -> None:
    manifest, manifest_sha256 = _manifest(tmp_path)
    receipts = _paths(tmp_path, manifest_sha256)

    report = intake.build_report(manifest, receipts, root=tmp_path)

    assert report["status"] == "diagnostic_bound"
    assert report["source_bound"] is True
    assert report["manifest"]["canonical_sha256"] == manifest_sha256
    assert report["manifest"]["raw_sha256"] != manifest_sha256
    assert report["input_boundary"]["bounded_training_receipt_json_opened"] == 3
    assert report["input_boundary"]["checkpoint_content_opened"] is False
    assert report["input_boundary"]["hdf5_content_opened"] is False
    assert all(row["status"] == "bound" for row in report["runs"])
    assert all(row["evidence"]["model_kind"] == intake.MODEL for row in report["runs"])
    assert intake.validate_report(report) == []


def test_known_core_learning_producer_metadata_is_non_authoritative_but_accepted(tmp_path: Path) -> None:
    manifest, manifest_sha256 = _manifest(tmp_path)
    receipts = _paths(tmp_path, manifest_sha256)
    payload = json.loads(receipts[17].read_text(encoding="utf-8"))
    payload.update(
        {
            "checkpoints": [deepcopy(payload["checkpoint"])],
            "device": "cuda:0",
            "history": [],
            "host": {"hostname": "fixture"},
            "milestone_evaluations": [],
            "normalization": {},
            "peak_gpu_memory_bytes": 123,
            "peak_rss_mib": 456,
            "progress_path": "/tmp/fixture-progress.json",
            "sampler": {"kind": "fixture"},
            "torch_version": "fixture",
            "validation_history": [],
            "wall_seconds": 1.0,
        }
    )
    payload["evidence"]["resume_semantics"] = {
        "construction_digest_preserved_across_resume": True,
        "loaded_weights_are_not_initial": True,
    }
    _write_json(receipts[17], payload)

    report = intake.build_report(manifest, receipts, root=tmp_path)

    assert report["status"] == "diagnostic_bound"
    assert report["source_bound"] is True
    assert report["credit"] == 0
    assert intake.validate_report(report) == []


def test_without_receipt_paths_defaults_fail_closed(tmp_path: Path) -> None:
    manifest, _ = _manifest(tmp_path)

    report = intake.build_report(manifest, root=tmp_path)

    assert report["status"] == "blocked_fail_closed"
    assert report["source_bound"] is False
    assert report["input_boundary"]["bounded_training_receipt_json_opened"] == 0
    assert all(row["status"] == "missing" for row in report["runs"])
    assert report["credit"] == 0
    assert intake.validate_report(report) == []


def test_explicit_running_status_does_not_open_receipt(tmp_path: Path) -> None:
    manifest, manifest_sha256 = _manifest(tmp_path)
    receipts = _paths(tmp_path, manifest_sha256)
    before = {seed: path.read_bytes() for seed, path in receipts.items()}

    report = intake.build_report(
        manifest,
        receipts,
        seed_statuses={seed: "running" for seed in intake.SEEDS},
        root=tmp_path,
    )

    assert report["status"] == "blocked_fail_closed"
    assert report["input_boundary"]["bounded_training_receipt_json_opened"] == 0
    assert all(row["status"] == "running" for row in report["runs"])
    assert {seed: path.read_bytes() for seed, path in receipts.items()} == before


def test_manifest_canonical_drift_blocks_all_receipts(tmp_path: Path) -> None:
    manifest, current_sha = _manifest(tmp_path)
    receipts = _paths(tmp_path, _sha("historical-manifest"))

    report = intake.build_report(manifest, receipts, root=tmp_path)

    assert report["status"] == "blocked_fail_closed"
    assert current_sha != _sha("historical-manifest")
    assert report["credit"] == 0
    assert any("config" in error and "manifest" in error for error in report["errors"])


@pytest.mark.parametrize(
    ("mutation", "needle"),
    [
        (lambda payload: payload.update({"unexpected": True}), "unknown fields"),
        (lambda payload: payload["config"].update({"unexpected": True}), "unknown fields"),
        (lambda payload: payload["evidence"]["residual_prior"].update({"unexpected": True}), "unknown fields"),
        (lambda payload: payload.update({"status": "running"}), "status"),
        (lambda payload: payload.update({"credit": 1}), "credit"),
    ],
)
def test_unknown_partial_running_and_nonzero_inputs_are_rejected(
    tmp_path: Path, mutation, needle: str
) -> None:
    manifest, manifest_sha256 = _manifest(tmp_path)
    receipts = _paths(tmp_path, manifest_sha256)
    payload = json.loads(receipts[17].read_text(encoding="utf-8"))
    mutation(payload)
    _write_json(receipts[17], payload)

    report = intake.build_report(manifest, receipts, root=tmp_path)

    assert report["status"] == "blocked_fail_closed"
    assert any("seed17" in error and needle in error for error in report["errors"])
    assert intake.validate_report(report) == []


def test_receipt_and_checkpoint_path_drift_is_fail_closed(tmp_path: Path) -> None:
    manifest, manifest_sha256 = _manifest(tmp_path)
    receipts = _paths(tmp_path, manifest_sha256)
    payload = json.loads(receipts[29].read_text(encoding="utf-8"))
    payload["checkpoint"]["path"] = str(tmp_path / "other-checkpoint.pt")
    _write_json(receipts[29], payload)

    report = intake.build_report(manifest, receipts, root=tmp_path)

    assert report["status"] == "blocked_fail_closed"
    assert any("seed29" in error and "checkpoint" in error for error in report["errors"])


def test_placeholder_declared_checkpoint_identity_is_rejected_without_opening_checkpoint(tmp_path: Path) -> None:
    manifest, manifest_sha256 = _manifest(tmp_path)
    receipts = _paths(tmp_path, manifest_sha256)
    checkpoint = tmp_path / f"{intake._expected_run_id(17, intake.PLAN_DATE)}-checkpoint.pt"
    checkpoint.write_bytes(b"checkpoint content must not be opened")
    payload = json.loads(receipts[17].read_text(encoding="utf-8"))
    payload["checkpoint"]["sha256"] = "0" * 64
    _write_json(receipts[17], payload)

    report = intake.build_report(manifest, receipts, root=tmp_path)

    assert report["status"] == "blocked_fail_closed"
    assert any("seed17" in error and "sha256" in error for error in report["errors"])
    assert checkpoint.read_bytes() == b"checkpoint content must not be opened"
    assert report["input_boundary"]["checkpoint_content_opened"] is False
    assert report["input_boundary"]["checkpoint_lstat_performed"] is False


def test_duplicate_identity_is_rejected(tmp_path: Path) -> None:
    manifest, manifest_sha256 = _manifest(tmp_path)
    receipts = _paths(tmp_path, manifest_sha256)
    first = json.loads(receipts[17].read_text(encoding="utf-8"))
    second = json.loads(receipts[29].read_text(encoding="utf-8"))
    second["checkpoint"] = deepcopy(first["checkpoint"])
    second["run_id"] = first["run_id"]
    second["config"] = deepcopy(first["config"])
    _write_json(receipts[29], second)

    report = intake.build_report(manifest, receipts, root=tmp_path)

    assert report["status"] == "blocked_fail_closed"
    assert any("seed29" in error for error in report["errors"])


def test_report_write_is_additive_and_verify_is_read_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    manifest, manifest_sha256 = _manifest(tmp_path)
    report = intake.build_report(manifest, _paths(tmp_path, manifest_sha256), root=tmp_path)
    output = tmp_path / "reports/F3-GRAPH-RESIDUAL-HIDDEN16-CURRENT-MANIFEST-TRAINING-EVIDENCE-TEST.json"
    markdown = tmp_path / "reports/F3-GRAPH-RESIDUAL-HIDDEN16-CURRENT-MANIFEST-TRAINING-EVIDENCE-TEST.zh-CN.md"

    written = intake.write_report(report, output, root=tmp_path)
    intake._write_text(intake.render_markdown(report), markdown, root=tmp_path, suffix=".md")
    assert written == output
    with pytest.raises(intake.IntakeError, match="refuses overwrite"):
        intake.write_report(report, output, root=tmp_path)

    assert intake.main(["--verify-report", str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "verified"
