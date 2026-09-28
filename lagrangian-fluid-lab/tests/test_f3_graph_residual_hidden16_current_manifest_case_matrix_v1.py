"""Tests for the bounded graph_residual current-manifest case matrix."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import f3_graph_residual_hidden16_current_manifest_case_matrix_v1 as matrix


def _sha(seed: int) -> str:
    return f"{seed:064x}"[-64:]


def _manifest() -> dict:
    cases = []
    for index in range(32):
        case_id = f"F3_DEV_{index:02d}_a{index}p903125"
        cases.append(
            {
                "bytes": 1000 + index,
                "case_id": case_id,
                "evaluation_role": "development_extrapolation",
                "family": "F3",
                "hdf5": f"campaigns/core-v1/data/{case_id}.h5",
                "known_inputs_ref": {
                    "contract_version": "core.inputs.v1",
                    "control": {"path": f"campaigns/core-v1/inputs/control-{index}.npz"},
                    "geometry": {"path": f"campaigns/core-v1/inputs/geometry-{index}.npz"},
                },
                "known_inputs_sha256": _sha(100 + index),
                "lineage_group_id": _sha(200 + index),
                "physical_case_id": case_id,
                "provenance": {"source": f"source-{index}"},
                "qualification_case": False,
                "scope_id": "F3_TEST_SCOPE",
                "semantics": {"identity": "particle_zone,particle_id"},
                "sha256": _sha(300 + index),
                "split": "test",
            }
        )
    return {
        "case_count": 32,
        "cases": cases,
        "dataset_id": "F3_registered32_core_native_v2",
        "formal_release": False,
        "input_asset_policy": "content_addressed_compressed_npz",
        "schema": "core.dataset.v2",
        "source_manifest_sha256": _sha(400),
    }


def _historical(manifest_sha: str) -> dict:
    return {
        "diagnostic_only": True,
        "formal_eligible": False,
        "manifest_sha256": manifest_sha,
        "model": "graph_residual",
        "qualification": {
            "credit": 0,
            "full_rollout_evaluations": "pending",
            "qualification": False,
            "t1": False,
            "t2": False,
            "training_evidence_complete": True,
        },
        "report_id": "f3-graph-residual-hidden16-seeds17-29-43-training-2026-09-28",
        "runs": [
            {
                "checkpoint_sha256": _sha(500 + seed),
                "checkpoint_verified": True,
                "completed_updates": 500,
                "initialization_parameter_digest": _sha(600 + seed),
                "neighbor_truncation_fraction": 0.0,
                "normalization_identity_sha256": _sha(700 + seed),
                "parameter_count": matrix.PARAMETER_COUNT,
                "residual_prior_identity_sha256": _sha(800 + seed),
                "run_id": f"f3-graph-residual500-hidden16-seed{seed}-20260928",
                "seed": seed,
                "training_receipt_sha256": _sha(900 + seed),
            }
            for seed in matrix.SEEDS
        ],
        "schema": matrix.HISTORICAL_SCHEMA,
        "shared_config": copy.deepcopy(matrix.REFERENCE_SHARED_CONFIG),
    }


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "lab"
    (root / "campaigns/core-v1").mkdir(parents=True, exist_ok=True)
    (root / "reports").mkdir(exist_ok=True)
    manifest_path = root / "campaigns/core-v1/f3-dataset-v2.json"
    manifest_path.write_text(json.dumps(_manifest(), sort_keys=True), encoding="utf-8")
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_sha = matrix._canonical_sha(manifest_payload)
    historical_path = root / "reports/historical.json"
    historical_path.write_text(json.dumps(_historical(manifest_sha), sort_keys=True), encoding="utf-8")
    return root, manifest_path, historical_path


def _v3_paths() -> dict[int, Path]:
    return {
        seed: Path(
            f"/tmp/f3-graph_residual500-hidden16-currentmanifest-seed{seed}-20260929-v3-training.json"
        )
        for seed in matrix.SEEDS
    }


def _build(tmp_path: Path, *, paths=None, statuses=None):
    root, manifest, historical = _fixture(tmp_path)
    return matrix.build_report(
        root=root,
        manifest=manifest,
        historical_matrix=historical,
        plan_date="20260929",
        python_executable=Path("/tmp/fake-python"),
        seed_receipts=_v3_paths() if paths is None else paths,
        seed_statuses={seed: "running" for seed in matrix.SEEDS} if statuses is None else statuses,
    )


def _receipt(plan: dict) -> dict:
    seed = plan["seed"]
    prior = {
        "dv_abs_max_mps": 0.1 + seed / 1000,
        "dv_abs_sum_mps": 1000.0 + seed,
        "dx_abs_max_m": 0.01 + seed / 10000,
        "dx_abs_sum_m": 100.0 + seed,
        "enabled": True,
        "execution_calls": 500,
        "finite": True,
        "history_complete": True,
        "last_update": {"case_id": "F3_DEV_00_a0p903125", "frame": seed, "update": 500},
        "rows": matrix.PRIOR_ROWS,
        "schema": matrix.PRIOR_SCHEMA,
        "semantic": "graph_residual subtracts this SI prior before shared raw-target normalization; predictor adds it back",
        "units": {"delta_velocity": "m/s", "displacement": "m"},
    }
    normalization = {
        "available_transition_count": 13360,
        "requested_maximum_transitions": 16,
        "selected_transition_count": 16,
        "selection_policy": "deterministic_evenly_spaced_train_transitions_v1",
        "selection_seed": seed,
        "schema": matrix.NORMALIZATION_SCHEMA,
        "source_split": "train",
        "target_reference": "raw_dual_increment_train_shared",
    }
    return {
        "checkpoint": {
            "bytes": 155000 + seed,
            "path": plan["outputs"]["checkpoint"],
            "schema": matrix.CHECKPOINT_SCHEMA,
            "sha256": _sha(1000 + seed),
            "update": 500,
        },
        "checkpoint_verified": True,
        "completed_updates": 500,
        "config": dict(plan["launch_config"]),
        "evidence": {
            "initialization": {
                "constructed_before_first_update": True,
                "construction_update": 0,
                "hidden": 16,
                "model_kind": "graph_residual",
                "parameter_count": matrix.PARAMETER_COUNT,
                "parameter_digest": _sha(1100 + seed),
                "schema": matrix.INITIALIZATION_SCHEMA,
                "seed": seed,
                "status": "captured",
            },
            "normalization": normalization,
            "residual_prior": prior,
            "schema": matrix.EVIDENCE_SCHEMA,
            "status": "complete",
        },
        "evidence_status": "complete",
        "model_kind": "graph_residual",
        "parameter_count": matrix.PARAMETER_COUNT,
        "run_id": plan["run_id"],
        "schema": matrix.TRAINING_SCHEMA,
        "seed": seed,
        "status": "completed",
    }


def _write_receipts(report: dict, paths: dict[int, Path]) -> None:
    for plan in report["training_plans"]:
        path = paths[plan["seed"]]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_receipt(plan), sort_keys=True), encoding="utf-8")


def test_v3_running_explicit_paths_are_fail_closed_without_opening_receipts(tmp_path: Path) -> None:
    report = _build(tmp_path)

    assert report["status"] == "blocked_fail_closed"
    assert report["source_bound"] is False
    assert report["training_receipts"] == {
        "required_count": 3,
        "observed_count": 0,
        "missing_count": 3,
        "status": "running_or_missing_or_rejected_current_manifest_receipts",
    }
    assert report["input_boundary"]["bounded_training_receipt_json_opened"] == 0
    assert all(plan["status"] == "running" for plan in report["training_plans"])
    assert all(plan["run_id"].endswith("-v3") for plan in report["training_plans"])
    assert all(plan["status"] == "blocked_missing_training_receipt" for plan in report["plans"])
    assert all(plan["launch_allowed"] is False and plan["credit"] == 0 for plan in report["plans"])
    matrix.validate_report(report)


def test_complete_v3_receipts_bind_current_manifest_config_and_case_matrix(tmp_path: Path) -> None:
    paths = _v3_paths()
    running = _build(tmp_path, paths=paths)
    _write_receipts(running, paths)
    root, manifest, historical = _fixture(tmp_path)
    report = matrix.build_report(
        root=root,
        manifest=manifest,
        historical_matrix=historical,
        plan_date="20260929",
        python_executable=Path("/tmp/fake-python"),
        seed_receipts=paths,
        seed_statuses={seed: "terminal" for seed in matrix.SEEDS},
    )
    assert report["status"] == "dry_run_matrix_ready"
    assert report["source_bound"] is True
    assert report["training_receipts"]["observed_count"] == 3
    assert report["input_boundary"]["bounded_training_receipt_json_opened"] == 3
    assert all(plan["status"] == "bound_complete" for plan in report["training_plans"])
    assert all(plan["status"] == "dry_run_ready" for plan in report["plans"])
    assert report["coverage"]["unique_namespaces"] == 99
    assert report["coverage"]["unique_nonces"] == 99
    assert report["coverage"]["unique_command_identities"] == 99
    matrix.validate_report(report)


def test_receipt_config_drift_is_rejected_and_remains_zero_credit(tmp_path: Path) -> None:
    paths = _v3_paths()
    report = _build(tmp_path, paths=paths)
    _write_receipts(report, paths)
    payload = json.loads(paths[29].read_text(encoding="utf-8"))
    payload["config"]["manifest_sha256"] = _sha(9999)
    paths[29].write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    rejected = _build(tmp_path / "rejected", paths=paths, statuses={seed: "terminal" for seed in matrix.SEEDS})

    assert rejected["source_bound"] is False
    assert rejected["training_plans"][1]["status"] == "rejected"
    assert rejected["training_receipts"]["observed_count"] == 2
    assert rejected["credit"] == 0
    assert all(plan["launch_allowed"] is False for plan in rejected["plans"])
    matrix.validate_report(rejected)


def test_namespace_nonce_and_command_identity_tampering_fails_closed(tmp_path: Path) -> None:
    report = _build(tmp_path)
    tampered = copy.deepcopy(report)
    tampered["plans"][0]["namespace_nonce"] = "1" * 32
    with pytest.raises(matrix.MatrixError, match="command|namespace|identity"):
        matrix.validate_report(tampered)

    tampered = copy.deepcopy(report)
    tampered["training_plans"][0]["command"][0] = "/tmp/other-python"
    with pytest.raises(matrix.MatrixError, match="command"):
        matrix.validate_report(tampered)


def test_cli_json_markdown_and_read_only_verify(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root, manifest, historical = _fixture(tmp_path)
    paths = _v3_paths()
    output = root / "reports/F3-GRAPH-RESIDUAL-HIDDEN16-CURRENT-MANIFEST-CASE-MATRIX-TEST.json"
    markdown = root / "reports/F3-GRAPH-RESIDUAL-HIDDEN16-CURRENT-MANIFEST-CASE-MATRIX-TEST.zh-CN.md"
    result = matrix.main(
        [
            "--root",
            str(root),
            "--manifest",
            str(manifest),
            "--historical-matrix",
            str(historical),
            "--seed-receipt",
            f"17={paths[17]}",
            "--seed-receipt",
            f"29={paths[29]}",
            "--seed-receipt",
            f"43={paths[43]}",
            "--seed-status",
            "17=running",
            "--seed-status",
            "29=running",
            "--seed-status",
            "43=running",
            "--python-executable",
            "/tmp/fake-python",
            "--output",
            str(output),
            "--markdown-output",
            str(markdown),
        ]
    )
    assert result == 0
    assert json.loads(capsys.readouterr().out)["case_jobs"] == 96
    before = output.read_bytes()
    assert matrix.main(["--verify-report", str(output)]) == 0
    capsys.readouterr()
    assert output.read_bytes() == before
    assert "blocked_fail_closed" in markdown.read_text(encoding="utf-8")


def test_manifest_case_drift_fails_closed_before_planning(tmp_path: Path) -> None:
    root, manifest, historical = _fixture(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["cases"][1]["case_id"] = payload["cases"][0]["case_id"]
    manifest.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    with pytest.raises(matrix.MatrixError, match="unique|identit|bound"):
        matrix.build_report(
            root=root,
            manifest=manifest,
            historical_matrix=historical,
            plan_date="20260929",
            python_executable=Path("/tmp/fake-python"),
        )
