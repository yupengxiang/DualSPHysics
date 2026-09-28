"""Tests for the additive current-manifest MLP diagnostic intake."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from scripts import f3_mlp_hidden16_current_manifest_training_evidence_v1 as intake


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _manifest(tmp_path: Path) -> tuple[Path, str]:
    path = _write_json(
        tmp_path / "current-manifest.json",
        {"dataset_id": "fixture-current", "schema": "core.dataset.v2"},
    )
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _receipt(
    tmp_path: Path,
    seed: int,
    manifest_sha256: str,
    *,
    checkpoint_path: str | None = None,
) -> Path:
    run_id = f"fixture-mlp-hidden16-seed{seed}"
    declared_checkpoint = checkpoint_path or str(tmp_path / f"checkpoint-{seed}.pt")
    checkpoint = {
        "bytes": 123 + seed,
        "path": declared_checkpoint,
        "schema": intake.CHECKPOINT_SCHEMA,
        "sha256": _sha(f"checkpoint-{seed}"),
        "update": intake.UPDATES,
    }
    payload = {
        "checkpoint": checkpoint,
        "checkpoints": [deepcopy(checkpoint)],
        "checkpoint_verified": True,
        "completed_updates": intake.UPDATES,
        "config": {
            "hidden": intake.HIDDEN,
            "manifest_formal_release": False,
            "manifest_sha256": manifest_sha256,
            "model_kind": intake.MODEL,
            "paired_seed": seed,
            "run_id": run_id,
            "sampler_seed": seed,
            "seed": seed,
            "updates": intake.UPDATES,
            "validation_formal_eligible": False,
        },
        "evidence_status": "complete",
        "model_kind": intake.MODEL,
        "run_id": run_id,
        "schema": intake.TRAINING_SCHEMA,
        "seed": seed,
        "status": "completed",
    }
    return _write_json(tmp_path / f"training-{seed}.json", payload)


def _paths(tmp_path: Path, manifest_sha256: str) -> dict[int, Path]:
    return {seed: _receipt(tmp_path, seed, manifest_sha256) for seed in intake.SEEDS}


def test_matching_current_manifest_binds_without_opening_checkpoint(tmp_path: Path) -> None:
    manifest, manifest_sha256 = _manifest(tmp_path)
    receipts = _paths(tmp_path, manifest_sha256)

    report = intake.build_report(manifest, receipts, root=tmp_path)

    assert report["status"] == "diagnostic_bound"
    assert report["source_bound"] is True
    assert report["manifest"]["sha256"] == manifest_sha256
    assert report["input_boundary"]["checkpoint_content_opened"] is False
    assert report["input_boundary"]["hdf5_content_opened"] is False
    assert all(row["status"] == "bound" for row in report["runs"])
    assert all(row["evidence"]["checkpoint_identity"]["bytes"] > 0 for row in report["runs"])
    assert intake.validate_report(report) == []


def test_existing_training_receipts_bind_to_actual_manifest_only(tmp_path: Path) -> None:
    manifest, current_sha = _manifest(tmp_path)
    old_sha = _sha("historical-manifest")
    receipts = _paths(tmp_path, old_sha)

    report = intake.build_report(manifest, receipts, root=tmp_path)

    assert current_sha != old_sha
    assert report["status"] == "blocked_fail_closed"
    assert report["manifest"]["sha256"] == current_sha
    assert any("config.manifest_sha256" in error or "actual manifest SHA" in error for error in report["errors"])
    assert report["credit"] == 0
    assert report["formal"] is False
    assert report["T1_numerical"] is False
    assert report["T2_macro"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model_kind", "graph_raw"),
        ("completed_updates", 499),
        ("status", "running"),
    ],
)
def test_receipt_protocol_or_completion_drift_blocks(tmp_path: Path, field: str, value: object) -> None:
    manifest, manifest_sha256 = _manifest(tmp_path)
    receipts = _paths(tmp_path, manifest_sha256)
    payload = json.loads(receipts[17].read_text(encoding="utf-8"))
    payload[field] = value
    _write_json(receipts[17], payload)

    report = intake.build_report(manifest, receipts, root=tmp_path)

    assert report["status"] == "blocked_fail_closed"
    assert any("seed17" in error for error in report["errors"])


def test_config_hidden_and_updates_are_checked(tmp_path: Path) -> None:
    manifest, manifest_sha256 = _manifest(tmp_path)
    receipts = _paths(tmp_path, manifest_sha256)
    payload = json.loads(receipts[29].read_text(encoding="utf-8"))
    payload["config"]["hidden"] = 32
    _write_json(receipts[29], payload)

    report = intake.build_report(manifest, receipts, root=tmp_path)

    assert report["status"] == "blocked_fail_closed"
    assert any("config.hidden" in error for error in report["errors"])


def test_checkpoint_terminal_identity_drift_blocks(tmp_path: Path) -> None:
    manifest, manifest_sha256 = _manifest(tmp_path)
    receipts = _paths(tmp_path, manifest_sha256)
    payload = json.loads(receipts[43].read_text(encoding="utf-8"))
    payload["checkpoints"][0]["sha256"] = _sha("different-checkpoint")
    _write_json(receipts[43], payload)

    report = intake.build_report(manifest, receipts, root=tmp_path)

    assert report["status"] == "blocked_fail_closed"
    assert any("checkpoint identity" in error for error in report["errors"])


@pytest.mark.parametrize(
    ("field", "value"),
    [("formal", True), ("credit", 1), ("qualification_credit", 1)],
)
def test_receipt_authority_markers_must_remain_zero_credit(
    tmp_path: Path, field: str, value: object
) -> None:
    manifest, manifest_sha256 = _manifest(tmp_path)
    receipts = _paths(tmp_path, manifest_sha256)
    payload = json.loads(receipts[17].read_text(encoding="utf-8"))
    payload[field] = value
    _write_json(receipts[17], payload)

    report = intake.build_report(manifest, receipts, root=tmp_path)

    assert report["status"] == "blocked_fail_closed"
    assert any("seed17" in error and field in error for error in report["errors"])
    assert intake.validate_report(report) == []


def test_duplicate_receipt_or_checkpoint_identity_blocks(tmp_path: Path) -> None:
    manifest, manifest_sha256 = _manifest(tmp_path)
    receipts = _paths(tmp_path, manifest_sha256)
    second = json.loads(receipts[29].read_text(encoding="utf-8"))
    first = json.loads(receipts[17].read_text(encoding="utf-8"))
    second["run_id"] = first["run_id"]
    second["config"]["run_id"] = first["run_id"]
    second["checkpoint"] = deepcopy(first["checkpoint"])
    second["checkpoints"] = [deepcopy(first["checkpoint"])]
    _write_json(receipts[29], second)

    report = intake.build_report(manifest, receipts, root=tmp_path)

    assert report["status"] == "blocked_fail_closed"
    assert any("identity" in error for error in report["errors"])


def test_exact_seed_set_is_required(tmp_path: Path) -> None:
    manifest, manifest_sha256 = _manifest(tmp_path)
    receipts = _paths(tmp_path, manifest_sha256)
    receipts.pop(29)

    report = intake.build_report(manifest, receipts, root=tmp_path)

    assert report["status"] == "blocked_fail_closed"
    assert any(item["check"] == "exact_seed_set" and item["passed"] is False for item in report["checks"])


def test_duplicate_json_keys_and_non_json_checkpoint_content_are_not_opened(tmp_path: Path) -> None:
    manifest, manifest_sha256 = _manifest(tmp_path)
    receipts = _paths(tmp_path, manifest_sha256)
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema":"core.training.v1","schema":"other"}\n', encoding="utf-8")
    receipts[17] = duplicate
    checkpoint = tmp_path / "checkpoint-17.pt"
    checkpoint.write_bytes(b"not parsed and not opened by intake")

    report = intake.build_report(manifest, receipts, root=tmp_path)

    assert report["status"] == "blocked_fail_closed"
    assert any("duplicate JSON object key" in error for error in report["errors"])
    assert checkpoint.read_bytes() == b"not parsed and not opened by intake"


def test_report_tampering_cannot_add_authority(tmp_path: Path) -> None:
    manifest, manifest_sha256 = _manifest(tmp_path)
    report = intake.build_report(manifest, _paths(tmp_path, manifest_sha256), root=tmp_path)
    report["credit"] = 1
    report["authorization"]["formal"] = True

    errors = intake.validate_report(report)

    assert any("credit must be integer zero" in error for error in errors)
    assert any("authorization.formal must be false" in error for error in errors)


def test_write_report_is_additive_and_refuses_existing_v1_matrix(tmp_path: Path) -> None:
    manifest, manifest_sha256 = _manifest(tmp_path)
    report = intake.build_report(manifest, _paths(tmp_path, manifest_sha256), root=tmp_path)
    output = tmp_path / "current-manifest-report.json"

    written = intake.write_report(report, output, root=tmp_path)
    assert written == output
    before = output.read_bytes()
    with pytest.raises(intake.IntakeError, match="refuses overwrite"):
        intake.write_report(report, output, root=tmp_path)
    assert output.read_bytes() == before
