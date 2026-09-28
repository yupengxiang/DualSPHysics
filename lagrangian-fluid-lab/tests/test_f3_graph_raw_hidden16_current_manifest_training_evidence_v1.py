"""Tests for the bounded graph_raw current-manifest training intake."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from scripts import f3_graph_raw_hidden16_current_manifest_training_evidence_v1 as intake


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _write(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _manifest(tmp_path: Path) -> tuple[Path, str, str]:
    payload = {
        "case_count": 32,
        "dataset_id": "F3_registered32_core_native_v2",
        "formal_release": False,
        "input_asset_policy": "content_addressed_compressed_npz",
        "schema": intake.MANIFEST_SCHEMA,
        "source_manifest_sha256": _sha("source-manifest"),
    }
    path = _write(tmp_path / "f3-dataset-v2.json", payload)
    raw_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    canonical_sha = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    return path, raw_sha, canonical_sha


def _receipt(tmp_path: Path, seed: int, manifest_sha: str, *, date: str = "20260929") -> Path:
    run_id = f"f3-graph_raw500-hidden16-currentmanifest-seed{seed}-{date}-v3"
    checkpoint = {
        "bytes": 152000 + seed,
        "path": str(tmp_path / f"f3-graph_raw500-hidden16-currentmanifest-seed{seed}-{date}-v3-checkpoint.pt"),
        "schema": intake.CHECKPOINT_SCHEMA,
        "sha256": _sha(f"checkpoint-{seed}"),
        "update": intake.UPDATES,
    }
    config = deepcopy(intake.STATIC_CONFIG)
    config.update({"manifest_sha256": manifest_sha, "paired_seed": seed, "run_id": run_id, "sampler_seed": seed, "seed": seed})
    evidence = {
        "schema": "core.training.evidence.v1",
        "status": "complete",
        "initialization": {
            "constructed_before_first_update": True,
            "construction_update": 0,
            "hidden": intake.HIDDEN,
            "model_kind": intake.MODEL,
            "parameter_count": 6086,
            "parameter_digest": _sha(f"initialization-{seed}"),
            "schema": "core.training.initialization_evidence.v1",
            "seed": seed,
            "status": "captured",
        },
        "normalization": {
            "available_transition_count": 13360,
            "requested_maximum_transitions": 16,
            "schema": "core.training.normalization_evidence.v1",
            "selected_case_ids": [],
            "selected_transition_bindings": [],
            "selected_transition_count": 16,
            "selected_transition_counts": {},
            "selection_policy": "deterministic_evenly_spaced_train_transitions_v1",
            "selection_seed": seed,
            "source_split": "train",
            "target_reference": "raw_dual_increment_train_shared",
            "train_case_ids": [],
        },
    }
    payload = {
        "checkpoint": checkpoint,
        "checkpoints": [deepcopy(checkpoint)],
        "checkpoint_verified": True,
        "completed_updates": intake.UPDATES,
        "config": config,
        "evidence": evidence,
        "evidence_status": "complete",
        "model_kind": intake.MODEL,
        "parameter_count": 6086,
        "run_id": run_id,
        "schema": intake.TRAINING_SCHEMA,
        "seed": seed,
    }
    return _write(tmp_path / f"f3-graph_raw500-hidden16-currentmanifest-seed{seed}-{date}-v3-training.json", payload)


def _receipts(tmp_path: Path, manifest_sha: str) -> dict[int, Path]:
    return {seed: _receipt(tmp_path, seed, manifest_sha) for seed in intake.SEEDS}


def test_complete_receipts_bind_manifest_raw_and_canonical_identity_without_opening_checkpoint(tmp_path: Path) -> None:
    manifest, raw_sha, canonical_sha = _manifest(tmp_path)
    receipts = _receipts(tmp_path, canonical_sha)
    checkpoint = tmp_path / "f3-graph_raw500-hidden16-currentmanifest-seed17-20260929-v3-checkpoint.pt"
    checkpoint.write_bytes(b"binary sentinel: intake must not open this")

    report = intake.build_report(manifest, receipts, root=tmp_path)

    assert report["status"] == "diagnostic_bound"
    assert report["source_bound"] is True
    assert report["manifest"]["sha256"] == raw_sha
    assert report["manifest"]["canonical_sha256"] == canonical_sha
    assert all(row["status"] == "bound" for row in report["runs"])
    assert all(row["evidence"]["manifest_identity"]["raw_sha256"] == raw_sha for row in report["runs"])
    assert report["input_boundary"]["checkpoint_content_opened"] is False
    assert report["input_boundary"]["progress_content_opened"] is False
    assert intake.validate_report(report) == []
    assert checkpoint.read_bytes().startswith(b"binary sentinel")


def test_default_v3_receipt_paths_fail_closed_when_receipts_are_missing(tmp_path: Path) -> None:
    manifest, _, _ = _manifest(tmp_path)
    paths = {seed: tmp_path / f"f3-graph_raw500-hidden16-currentmanifest-seed{seed}-20260929-v3-training.json" for seed in intake.SEEDS}

    report = intake.build_report(manifest, paths, root=tmp_path)

    assert report["status"] == "blocked_fail_closed"
    assert report["source_bound"] is False
    assert {row["status"] for row in report["runs"]} == {"missing"}
    assert report["credit"] == 0
    assert report["input_boundary"]["progress_content_opened"] is False
    assert intake.validate_report(report) == []


def test_nonterminal_declared_status_is_rejected_before_receipt_read(tmp_path: Path) -> None:
    manifest, _, canonical_sha = _manifest(tmp_path)
    paths = _receipts(tmp_path, canonical_sha)
    paths[17] = tmp_path / "missing-f3-graph_raw500-hidden16-currentmanifest-seed17-20260929-v3-training.json"

    report = intake.build_report(manifest, paths, root=tmp_path, seed_statuses={17: "running", 29: "complete", 43: "complete"})

    assert report["status"] == "blocked_fail_closed"
    assert report["runs"][0]["status"] == "blocked"
    assert any("non-terminal" in reason for reason in report["runs"][0]["blocked_reasons"])
    assert report["input_boundary"]["bounded_training_receipts_json_opened"] == 2


@pytest.mark.parametrize(
    ("mutation", "needle"),
    [
        (lambda payload: payload["config"].update({"hidden": 32}), "config.hidden"),
        (lambda payload: payload.update({"unexpected": True}), "unknown field"),
        (lambda payload: payload.update({"credit": 1}), "credit"),
        (lambda payload: payload.update({"evidence_status": "running"}), "evidence_status"),
    ],
)
def test_protocol_authority_and_unknown_field_drift_blocks(tmp_path: Path, mutation, needle: str) -> None:
    manifest, _, canonical_sha = _manifest(tmp_path)
    receipts = _receipts(tmp_path, canonical_sha)
    payload = json.loads(receipts[17].read_text(encoding="utf-8"))
    mutation(payload)
    _write(receipts[17], payload)

    report = intake.build_report(manifest, receipts, root=tmp_path)

    assert report["status"] == "blocked_fail_closed"
    assert any(needle in error for error in report["errors"])
    assert intake.validate_report(report) == []


def test_manifest_canonical_drift_blocks_and_preserves_zero_credit(tmp_path: Path) -> None:
    manifest, _, current_sha = _manifest(tmp_path)
    receipts = _receipts(tmp_path, _sha("old-manifest"))

    report = intake.build_report(manifest, receipts, root=tmp_path)

    assert report["status"] == "blocked_fail_closed"
    assert current_sha != _sha("old-manifest")
    assert any("manifest_sha256" in error for error in report["errors"])
    assert report["formal"] is False and report["T1_numerical"] is False and report["T2_macro"] is False and report["T2_path"] is False
    assert report["credit"] == 0


def test_receipt_and_checkpoint_path_drift_blocks_without_touching_binary(tmp_path: Path) -> None:
    manifest, _, canonical_sha = _manifest(tmp_path)
    receipts = _receipts(tmp_path, canonical_sha)
    payload = json.loads(receipts[29].read_text(encoding="utf-8"))
    payload["checkpoint"]["path"] = str(tmp_path / "f3-graph_raw500-hidden16-currentmanifest-seed17-20260929-v3-checkpoint.pt")
    payload["checkpoints"][0]["path"] = payload["checkpoint"]["path"]
    _write(receipts[29], payload)
    binary = tmp_path / "f3-graph_raw500-hidden16-currentmanifest-seed17-20260929-v3-checkpoint.pt"
    binary.write_bytes(b"do not open")

    report = intake.build_report(manifest, receipts, root=tmp_path)

    assert report["status"] == "blocked_fail_closed"
    assert any("path drifted" in error for error in report["errors"])
    assert binary.read_bytes() == b"do not open"


def test_duplicate_identity_and_missing_seed_are_fail_closed(tmp_path: Path) -> None:
    manifest, _, canonical_sha = _manifest(tmp_path)
    receipts = _receipts(tmp_path, canonical_sha)
    second = json.loads(receipts[29].read_text(encoding="utf-8"))
    first = json.loads(receipts[17].read_text(encoding="utf-8"))
    second["run_id"] = first["run_id"]
    second["config"]["run_id"] = first["config"]["run_id"]
    second["checkpoint"] = deepcopy(first["checkpoint"])
    second["checkpoints"] = [deepcopy(first["checkpoint"])]
    _write(receipts[29], second)
    receipts.pop(43)

    report = intake.build_report(manifest, receipts, root=tmp_path)

    assert report["status"] == "blocked_fail_closed"
    assert any("missing training receipt" in error for error in report["errors"])
    assert intake.validate_report(report) == []


def test_report_validation_rejects_authority_tampering_and_write_is_additive(tmp_path: Path) -> None:
    manifest, _, canonical_sha = _manifest(tmp_path)
    report = intake.build_report(manifest, _receipts(tmp_path, canonical_sha), root=tmp_path)
    report["credit"] = 1
    assert any("credit" in error for error in intake.validate_report(report))
    report["credit"] = 0
    output = tmp_path / "intake-report.json"
    assert intake.write_report(report, output, root=tmp_path) == output
    before = output.read_bytes()
    with pytest.raises(intake.IntakeError, match="refuses overwrite"):
        intake.write_report(report, output, root=tmp_path)
    assert output.read_bytes() == before
