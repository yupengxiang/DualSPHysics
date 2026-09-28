"""Focused tests for the bounded F3 hidden16 terminal reconciliation."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts import f3_graph_raw_hidden16_terminal_candidate_reconciliation_v1 as reconcile


def _sha(letter: str) -> str:
    return letter * 64


def _write_json(path: Path, payload: dict) -> str:
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _training(seed: int, artifact_root: Path) -> dict:
    return {
        "schema": "core.training.v1",
        "model_kind": "graph_raw",
        "seed": seed,
        "completed_updates": 500,
        "evidence_status": "complete",
        "checkpoint_verified": True,
        "config": {
            "model_kind": "graph_raw",
            "hidden": 16,
            "seed": seed,
            "updates": 500,
        },
        "checkpoint": {
            "path": str(artifact_root / f"f3-graph-raw500-hidden16-seed{seed}-checkpoint.pt"),
            "sha256": _sha(chr(ord("a") + seed % 3)),
            "update": 500,
        },
    }


def _evaluation(seed: int) -> dict:
    return {
        "schema": "core.evaluation.v1",
        "model_kind": "graph_raw",
        "hidden": 16,
        "seed": seed,
        "updates": 500,
        "maximum_steps": 835,
        "transitions": 835,
        "frames": 836,
        "status": "completed",
        "diagnostic_only": True,
        "formal_eligible": False,
        "qualification": False,
        "credit": 0,
        "qualification_credit": 0,
    }


def _terminal(
    seed: int,
    artifact_root: Path,
    training_path: Path,
    training_sha: str,
    evaluation_path: Path,
    evaluation_sha: str,
    checkpoint_sha: str,
) -> dict:
    return {
        "schema": "core.f3.graph_raw.hidden16.terminal_candidate.v1",
        "status": "completed_diagnostic",
        "model_kind": "graph_raw",
        "hidden": 16,
        "seed": seed,
        "updates": 500,
        "transitions": 835,
        "frames": 836,
        "terminal_markers": {
            "terminal": True,
            "execution_complete": True,
            "finite_rollout_complete": True,
            "terminal_status": "completed",
            "progress_is_not_completion": True,
        },
        "bindings": {
            "checkpoint": {
                "path": str(artifact_root / f"f3-graph-raw500-hidden16-seed{seed}-checkpoint.pt"),
                "sha256": checkpoint_sha,
            },
            "training": {"path": str(training_path), "sha256": training_sha},
            "evaluation": {"path": str(evaluation_path), "sha256": evaluation_sha},
        },
        "output": {
            "fresh_output_namespace": str(
                artifact_root / f"f3-graph-raw500-hidden16-seed{seed}-full835-terminal-v1"
            )
        },
        "diagnostic_only": True,
        "formal_eligible": False,
        "qualification": False,
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "credit": 0,
        "qualification_credit": 0,
    }


def _make_complete_matrix(tmp_path: Path) -> tuple[Path, Path, dict[int, dict[str, Path]]]:
    candidate_root = tmp_path / "candidates"
    candidate_root.mkdir()
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    paths: dict[int, dict[str, Path]] = {}
    for seed in reconcile.SEEDS:
        training_path = candidate_root / f"f3-graph-raw500-hidden16-seed{seed}-training.json"
        evaluation_path = candidate_root / f"f3-graph-raw500-hidden16-seed{seed}-evaluation.json"
        training_payload = _training(seed, artifact_root)
        training_sha = _write_json(training_path, training_payload)
        evaluation_sha = _write_json(evaluation_path, _evaluation(seed))
        terminal_path = candidate_root / f"f3-graph-raw500-hidden16-seed{seed}-terminal.json"
        _write_json(
            terminal_path,
            _terminal(
                seed,
                artifact_root,
                training_path.resolve(),
                training_sha,
                evaluation_path.resolve(),
                evaluation_sha,
                training_payload["checkpoint"]["sha256"],
            ),
        )
        paths[seed] = {
            "training": training_path,
            "evaluation": evaluation_path,
            "terminal": terminal_path,
        }
    return tmp_path / "report-root", candidate_root, paths


def _report(tmp_path: Path, candidate_root: Path) -> dict:
    return reconcile.build_report(
        tmp_path / "report-root",
        candidate_roots=[candidate_root],
    )


def test_complete_matrix_is_bound_but_zero_authority(tmp_path: Path):
    _, candidate_root, _ = _make_complete_matrix(tmp_path)
    report = _report(tmp_path, candidate_root)
    assert report["status"] == "bound_terminal_candidate_diagnostic_only"
    assert report["source_bound"] is True
    assert [row["status"] for row in report["seed_matrix"]] == ["accepted"] * 3
    assert report["authorization"]["formal_training_runs_counted"] == 0
    assert report["credit"] == 0
    assert report["formal"] is False
    assert report["T1_numerical"] is False
    assert report["T2_macro"] is False
    assert report["T2_path"] is False
    assert reconcile.validate_report(report) == []


def test_sha_binding_drift_rejects_seed(tmp_path: Path):
    _, candidate_root, paths = _make_complete_matrix(tmp_path)
    terminal_path = paths[29]["terminal"]
    payload = json.loads(terminal_path.read_text())
    payload["bindings"]["checkpoint"]["sha256"] = _sha("f")
    _write_json(terminal_path, payload)
    report = _report(tmp_path, candidate_root)
    row = next(item for item in report["seed_matrix"] if item["seed"] == 29)
    assert row["status"] == "rejected"
    assert "checkpoint_sha256_binding_drift" in row["reasons"]
    assert report["credit"] == 0


def test_training_and_evaluation_sha_binding_drift_rejects_seed(tmp_path: Path):
    _, candidate_root, paths = _make_complete_matrix(tmp_path)
    for seed, binding, digest in ((17, "training", _sha("e")), (29, "evaluation", _sha("f"))):
        terminal_path = paths[seed]["terminal"]
        payload = json.loads(terminal_path.read_text())
        payload["bindings"][binding]["sha256"] = digest
        _write_json(terminal_path, payload)
    report = _report(tmp_path, candidate_root)
    row17 = next(item for item in report["seed_matrix"] if item["seed"] == 17)
    row29 = next(item for item in report["seed_matrix"] if item["seed"] == 29)
    assert "training_sha256_binding_drift" in row17["reasons"]
    assert "evaluation_sha256_binding_drift" in row29["reasons"]


def test_model_hidden_seed_updates_and_horizon_are_strict(tmp_path: Path):
    _, candidate_root, paths = _make_complete_matrix(tmp_path)
    terminal_path = paths[17]["terminal"]
    payload = json.loads(terminal_path.read_text())
    payload["hidden"] = 8
    payload["frames"] = 835
    _write_json(terminal_path, payload)
    report = _report(tmp_path, candidate_root)
    row = next(item for item in report["seed_matrix"] if item["seed"] == 17)
    candidate = next(
        item for item in row["candidates"] if item["path"].endswith("seed17-terminal.json")
    )
    assert row["status"] == "rejected"
    assert "legacy_hidden8_drift" in candidate["reasons"]
    assert any("hidden_drift" in reason for reason in candidate["reasons"])
    assert any("frames_drift" in reason for reason in candidate["reasons"])


def test_missing_seed_is_reported_as_missing(tmp_path: Path):
    candidate_root = tmp_path / "candidates"
    candidate_root.mkdir()
    report = _report(tmp_path, candidate_root)
    assert report["status"] == "blocked_fail_closed"
    assert [row["status"] for row in report["seed_matrix"]] == ["missing"] * 3
    assert all("missing_training_candidate" in row["reasons"] for row in report["seed_matrix"])
    assert all("missing_terminal_candidate" in row["reasons"] for row in report["seed_matrix"])


def test_duplicate_json_key_is_rejected(tmp_path: Path):
    candidate_root = tmp_path / "candidates"
    candidate_root.mkdir()
    path = candidate_root / "f3-graph-raw500-hidden16-seed43-terminal.json"
    path.write_text('{"schema":"x","schema":"y"}\n', encoding="utf-8")
    report = _report(tmp_path, candidate_root)
    row = next(item for item in report["seed_matrix"] if item["seed"] == 43)
    candidate = next(
        item for item in row["candidates"] if item["path"].endswith("seed43-terminal.json")
    )
    assert candidate["parse_status"] == "rejected"
    assert "duplicate_json_key:schema" in candidate["reasons"]
    assert row["status"] == "rejected"


def test_legacy_hidden8_candidate_is_explicitly_rejected(tmp_path: Path):
    candidate_root = tmp_path / "candidates"
    candidate_root.mkdir()
    payload = _training(17, tmp_path)
    payload["config"]["hidden"] = 8
    path = candidate_root / "f3-graph-raw500-hidden8-seed17-training.json"
    _write_json(path, payload)
    report = _report(tmp_path, candidate_root)
    row = next(item for item in report["seed_matrix"] if item["seed"] == 17)
    candidate = next(
        item for item in row["candidates"] if item["path"].endswith("hidden8-seed17-training.json")
    )
    assert "legacy_hidden8_drift" in candidate["reasons"]
    assert row["category_status"]["training"] == "rejected"


def test_oversize_evaluation_is_not_opened(tmp_path: Path):
    candidate_root = tmp_path / "candidates"
    candidate_root.mkdir()
    path = candidate_root / "f3-graph-raw500-hidden16-seed17-full835-evaluation.json"
    path.write_bytes(b"{" + b" " * reconcile.MAX_JSON_BYTES + b"}")
    report = _report(tmp_path, candidate_root)
    row = next(item for item in report["seed_matrix"] if item["seed"] == 17)
    candidate = next(
        item for item in row["candidates"] if item["path"].endswith("full835-evaluation.json")
    )
    assert candidate["source"]["opened"] is False
    assert "bounded_json_size_exceeded" in candidate["reasons"][0]


def test_progress_and_non_json_are_outside_reader_boundary(tmp_path: Path):
    candidate_root = tmp_path / "candidates"
    candidate_root.mkdir()
    (candidate_root / "f3-graph-raw500-hidden16-seed17-evaluation-progress.json").write_text(
        "not opened", encoding="utf-8"
    )
    (candidate_root / "f3-graph-raw500-hidden16-seed17-checkpoint.pt").write_bytes(
        b"not opened"
    )
    report = _report(tmp_path, candidate_root)
    assert report["candidate_inventory"]["scanned_candidate_files"] == 0
    assert report["candidate_inventory"]["progress_files_skipped"] == 1
    assert report["input_boundary"]["non_json_opened"] is False
    assert report["input_boundary"]["progress_opened"] is False


def test_symlink_json_candidate_is_not_opened(tmp_path: Path):
    candidate_root = tmp_path / "candidates"
    candidate_root.mkdir()
    target = tmp_path / "target.json"
    target.write_text('{"schema":"core.training.v1"}\n', encoding="utf-8")
    link = candidate_root / "f3-graph-raw500-hidden16-seed17-training.json"
    link.symlink_to(target)
    report = _report(tmp_path, candidate_root)
    row = next(item for item in report["seed_matrix"] if item["seed"] == 17)
    candidate = next(
        item for item in row["candidates"] if item["path"].endswith("seed17-training.json")
    )
    assert candidate["source"]["opened"] is False
    assert "symlink_json_not_allowed" in candidate["reasons"]


def test_report_serialization_binds_exactly(tmp_path: Path):
    _, candidate_root, _ = _make_complete_matrix(tmp_path)
    report = _report(tmp_path, candidate_root)
    output = tmp_path / "out.json"
    zh_output = tmp_path / "out.zh-CN.md"
    reconcile.write_outputs(report, output, zh_output)
    assert json.loads(output.read_text(encoding="utf-8")) == report
    assert zh_output.exists()
    tampered = copy.deepcopy(report)
    tampered["credit"] = 1
    assert reconcile.validate_report(tampered)


@pytest.mark.parametrize("category", ["training", "evaluation", "terminal"])
def test_each_required_category_is_explicit(tmp_path: Path, category: str):
    _, candidate_root, paths = _make_complete_matrix(tmp_path)
    paths[43][category].unlink()
    report = _report(tmp_path, candidate_root)
    row = next(item for item in report["seed_matrix"] if item["seed"] == 43)
    assert row["category_status"][category] == "missing"
    assert f"missing_{category}_candidate" in row["reasons"]
