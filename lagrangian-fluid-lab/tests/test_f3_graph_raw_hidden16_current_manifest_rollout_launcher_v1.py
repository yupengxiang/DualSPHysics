"""Tests for the bounded graph_raw hidden16 current-manifest contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest

from scripts import f3_graph_raw_hidden16_current_manifest_rollout_launcher_v1 as launcher


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_json(path: Path, value: object) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    path.write_bytes(raw)
    return raw


def _fixture(tmp_path: Path) -> dict[str, object]:
    root = tmp_path / "lab"
    fixture_inputs = tmp_path / "fixture-inputs"
    fixture_inputs.mkdir()
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "reports").mkdir()
    python = root / ".venv" / "bin" / "python"
    python.write_bytes(Path(sys.executable).resolve().read_bytes())
    python.chmod(0o755)
    (root / "scripts" / "core_learning.py").write_text("# bounded fixture\n", encoding="utf-8")

    manifest_payload = {
        "schema": launcher.MANIFEST_SCHEMA,
        "case_count": 32,
        "dataset_id": "F3_registered32_core_native_v2",
        "formal_release": False,
        "source_manifest_sha256": "1" * 64,
    }
    manifest = root / "campaigns" / "core-v1" / "f3-dataset-v2.json"
    manifest_raw = _write_json(manifest, manifest_payload)
    manifest_sha = launcher.canonical_digest(manifest_payload)

    seed = 17
    run_id = "f3-graph_raw500-hidden16-currentmanifest-seed17-20260929-v3"
    checkpoint = fixture_inputs / "f3-graph_raw500-hidden16-currentmanifest-seed17-20260929-v3-checkpoint.pt"
    checkpoint_raw = b"checkpoint bytes are never opened by this contract"
    checkpoint.write_bytes(checkpoint_raw)
    checkpoint_meta = {
        "schema": launcher.CHECKPOINT_SCHEMA,
        "path": str(checkpoint),
        "sha256": _sha_bytes(checkpoint_raw),
        "bytes": len(checkpoint_raw),
        "update": launcher.UPDATES,
    }
    training = fixture_inputs / "f3-graph_raw500-hidden16-currentmanifest-seed17-20260929-v3-training.json"
    receipt = {
        "schema": launcher.TRAINING_SCHEMA,
        "evidence_status": "complete",
        "model_kind": launcher.MODEL,
        "seed": seed,
        "run_id": run_id,
        "completed_updates": launcher.UPDATES,
        "checkpoint_verified": True,
        "checkpoint": checkpoint_meta,
        "checkpoints": [checkpoint_meta],
        "config": {
            "manifest_sha256": manifest_sha,
            "model_kind": launcher.MODEL,
            "hidden": launcher.HIDDEN,
            "updates": launcher.UPDATES,
            "run_id": run_id,
            "seed": seed,
            "manifest_formal_release": False,
            "validation_formal_eligible": False,
        },
        **launcher.ZERO_CREDIT,
    }
    training_raw = _write_json(training, receipt)
    return {
        "root": root,
        "manifest": manifest,
        "manifest_raw": manifest_raw,
        "manifest_sha": manifest_sha,
        "training": training,
        "training_raw": training_raw,
        "checkpoint": checkpoint,
        "checkpoint_meta": checkpoint_meta,
        "run_id": run_id,
    }


def _plan(fixture: dict[str, object], tmp_path: Path, *, seed: int = 17, nonce: str = "a" * 32):
    name = f"f3-graph_raw500-hidden16-currentmanifest-seed{seed}-full835-nonce{nonce}"
    return launcher.build_plan(
        fixture["root"],
        seed=seed,
        manifest=fixture["manifest"],
        training_receipt=fixture["training"],
        checkpoint=fixture["checkpoint"],
        nonce=nonce,
        output_namespace=tmp_path / name,
        gpu_index=5,
    )


def _terminal_receipt(plan: launcher.RolloutPlan, fixture: dict[str, object], path: Path) -> Path:
    digest = _sha_bytes(b"evaluation-identity")
    receipt = {
        "schema": launcher.TERMINAL_RECEIPT_SCHEMA,
        "report_id": f"f3-graph-raw-hidden16-seed{plan.seed}-current-manifest-full835-terminal-v1",
        "status": "terminal_verified",
        "source_bound": True,
        "seed": plan.seed,
        "run_id": plan.run_id,
        "model": launcher.MODEL,
        "model_kind": launcher.MODEL,
        "hidden": launcher.HIDDEN,
        "updates": launcher.UPDATES,
        "case_id": launcher.CASE_ID,
        "split": launcher.SPLIT,
        "transitions": launcher.TRANSITIONS,
        "frames": launcher.FRAMES,
        "namespace": str(plan.namespace),
        "namespace_nonce": plan.nonce,
        "command": list(plan.command),
        "command_sha256": plan.command_sha256,
        "cwd": str(plan.root),
        "env_overrides": dict(plan.env),
        "manifest": {
            "path": str(plan.manifest),
            "sha256": plan.manifest_sha256,
            "bytes": plan.manifest.stat().st_size,
        },
        "training_receipt": {
            "path": str(plan.training_receipt),
            "sha256": plan.training_receipt_sha256,
            "bytes": plan.training_receipt.stat().st_size,
        },
        "checkpoint": {**dict(plan.checkpoint), "schema": launcher.CHECKPOINT_SCHEMA, "update": launcher.UPDATES},
        "evaluation_artifact": {"path": str(plan.outputs["evaluation"]), "sha256": digest, "bytes": 128},
        "trajectory_artifact": {"path": str(plan.outputs["trajectory"]), "sha256": _sha_bytes(b"trajectory-identity"), "bytes": 256},
        "progress_artifact": {"path": str(plan.outputs["progress"]), "sha256": _sha_bytes(b"progress-identity"), "bytes": 128},
        "validator_artifact": {"path": str(plan.outputs["validator"]), "sha256": _sha_bytes(b"validator-identity"), "bytes": 128},
        "validator_receipt": {
            "schema": launcher.VALIDATOR_SCHEMA,
            "status": "validated",
            "passed": True,
            "complete": True,
            "expected_transitions": launcher.TRANSITIONS,
            "trajectory_transitions": launcher.TRANSITIONS,
            "trajectory_frames": launcher.FRAMES,
            "production_artifacts_touched": False,
            "actual_future_state_inputs": False,
            "synthetic_only": False,
        },
        "terminal_markers": {
            "terminal": True,
            "execution_complete": True,
            "finite_rollout_complete": True,
            "terminal_status": "completed",
            "progress_is_not_completion": True,
        },
        "process_exit": {
            "schema": launcher.PROCESS_EXIT_SCHEMA,
            "status": "exited_successfully",
            "evaluator_returncode": 0,
            "launcher_returncode": 0,
            "returncode": 0,
            "evaluator_alive": False,
            "launcher_alive": False,
            "stopped_processes": 0,
            "restarted_processes": 0,
            "command_sha256": plan.command_sha256,
            "observed_after_exit": True,
        },
        "input_boundary": {
            "checkpoint_content_opened": False,
            "evaluation_content_opened": False,
            "progress_content_opened": False,
            "trajectory_hdf5_content_opened": False,
        },
        **launcher.ZERO_CREDIT,
        "zero_credit_only": True,
        "future_state_inputs": False,
    }
    _write_json(path, receipt)
    return path


def test_plan_binds_current_manifest_graph_raw_and_never_opens_checkpoint(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    before = fixture["checkpoint"].read_bytes()
    plan = _plan(fixture, tmp_path)
    assert plan.run_id == fixture["run_id"]
    assert plan.manifest_sha256 == fixture["manifest_sha"]
    assert plan.checkpoint["path"] == str(fixture["checkpoint"])
    assert plan.as_dict()["launch_allowed"] is False
    assert plan.as_dict()["input_boundary"]["checkpoint_content_opened"] is False
    assert fixture["checkpoint"].read_bytes() == before
    assert "graph_raw" in plan.command_sha256 or len(plan.command_sha256) == 64


def test_matrix_generates_unique_fresh_nonce_namespaces(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    receipts = {seed: fixture["training"] for seed in launcher.SEEDS}
    checkpoints = {seed: fixture["checkpoint"] for seed in launcher.SEEDS}
    # Make the seed-specific identities valid for the matrix fixture.
    for seed in launcher.SEEDS[1:]:
        source = Path(fixture["training"])
        fixture_inputs = tmp_path / "fixture-inputs"
        receipt_path = fixture_inputs / f"f3-graph_raw500-hidden16-currentmanifest-seed{seed}-20260929-v3-training.json"
        checkpoint_path = fixture_inputs / f"f3-graph_raw500-hidden16-currentmanifest-seed{seed}-20260929-v3-checkpoint.pt"
        checkpoint_path.write_bytes(b"checkpoint-" + str(seed).encode())
        payload = json.loads(source.read_text())
        payload["seed"] = seed
        payload["run_id"] = f"f3-graph_raw500-hidden16-currentmanifest-seed{seed}-20260929-v3"
        payload["config"]["seed"] = seed
        payload["config"]["run_id"] = payload["run_id"]
        payload["checkpoint"] = {
            **payload["checkpoint"],
            "path": str(checkpoint_path),
            "sha256": _sha_bytes(checkpoint_path.read_bytes()),
            "bytes": checkpoint_path.stat().st_size,
        }
        payload["checkpoints"] = [payload["checkpoint"]]
        _write_json(receipt_path, payload)
        receipts[seed] = receipt_path
        checkpoints[seed] = checkpoint_path
    plans = launcher.build_matrix(
        fixture["root"],
        manifest=fixture["manifest"],
        training_receipts=receipts,
        checkpoints=checkpoints,
        nonces={17: "a" * 32, 29: "b" * 32, 43: "c" * 32},
        output_root=tmp_path,
    )
    assert [plan.seed for plan in plans] == list(launcher.SEEDS)
    assert len({plan.nonce for plan in plans}) == 3
    assert len({str(plan.namespace) for plan in plans}) == 3
    assert len({plan.command_sha256 for plan in plans}) == 3
    assert all(plan.launch_allowed is False for plan in plans)


def test_duplicate_nonce_and_running_receipt_fail_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    with pytest.raises(launcher.ContractError, match="nonces must be unique"):
        launcher.build_matrix(
            fixture["root"],
            manifest=fixture["manifest"],
            training_receipts={seed: fixture["training"] for seed in launcher.SEEDS},
            nonces={seed: "a" * 32 for seed in launcher.SEEDS},
            output_root=tmp_path,
        )
    payload = json.loads(Path(fixture["training"]).read_text())
    payload["evidence_status"] = "running"
    _write_json(Path(fixture["training"]), payload)
    (tmp_path / "running").mkdir()
    with pytest.raises(launcher.ContractError, match="evidence_status"):
        _plan(fixture, tmp_path / "running")


def test_naked_execute_is_rejected_without_starting_process(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plan = _plan(fixture, tmp_path)
    with pytest.raises(launcher.ContractError, match="naked launch|not admitted"):
        launcher.execute_plan(plan)
    with pytest.raises(launcher.ContractError, match="not admitted"):
        launcher.execute_plan(plan, {"schema": launcher.EXECUTE_CAPABILITY_SCHEMA})


def test_terminal_receipt_verifier_binds_process_exit_and_validator(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plan = _plan(fixture, tmp_path, nonce="d" * 32)
    receipt = _terminal_receipt(plan, fixture, tmp_path / "receipt.json")
    verified = launcher.verify_terminal_receipt(
        receipt,
        root=fixture["root"],
        manifest_sha256=plan.manifest_sha256,
        expected_plan=plan,
    )
    assert verified["status"] == "terminal_verified"
    assert verified["credit"] == 0
    assert verified["evidence"]["process_exit"]["returncode"] == 0
    assert verified["evidence"]["validator_receipt"]["trajectory_frames"] == launcher.FRAMES


def test_terminal_receipt_rejects_command_drift_and_credit_alias(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plan = _plan(fixture, tmp_path, nonce="e" * 32)
    receipt_path = _terminal_receipt(plan, fixture, tmp_path / "receipt.json")
    payload = json.loads(receipt_path.read_text())
    payload["command"][0] = "/tmp/other-python"
    _write_json(receipt_path, payload)
    with pytest.raises(launcher.ContractError, match="command_sha256"):
        launcher.verify_terminal_receipt(receipt_path, root=fixture["root"], manifest_sha256=plan.manifest_sha256)
    payload = json.loads(_terminal_receipt(plan, fixture, receipt_path).read_text())
    payload["credit_alias"] = 0
    _write_json(receipt_path, payload)
    with pytest.raises(launcher.ContractError, match="authority/process alias"):
        launcher.verify_terminal_receipt(receipt_path, root=fixture["root"], manifest_sha256=plan.manifest_sha256)


def test_terminal_receipt_rejects_output_path_drift_and_partial_terminal(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plan = _plan(fixture, tmp_path, nonce="f" * 32)
    receipt_path = _terminal_receipt(plan, fixture, tmp_path / "receipt.json")
    payload = json.loads(receipt_path.read_text())
    payload["trajectory_artifact"]["path"] = str(plan.namespace) + "-other-trajectory.h5"
    _write_json(receipt_path, payload)
    with pytest.raises(launcher.ContractError, match="trajectory_artifact.path"):
        launcher.verify_terminal_receipt(receipt_path, root=fixture["root"], manifest_sha256=plan.manifest_sha256)
    payload = json.loads(_terminal_receipt(plan, fixture, receipt_path).read_text())
    payload["terminal_markers"]["finite_rollout_complete"] = False
    _write_json(receipt_path, payload)
    with pytest.raises(launcher.ContractError, match="finite_rollout_complete"):
        launcher.verify_terminal_receipt(receipt_path, root=fixture["root"], manifest_sha256=plan.manifest_sha256)
    payload = json.loads(_terminal_receipt(plan, fixture, receipt_path).read_text())
    payload["schema"] = "core.f3.graph_raw.hidden8.legacy_terminal.v1"
    _write_json(receipt_path, payload)
    with pytest.raises(launcher.ContractError, match="schema"):
        launcher.verify_terminal_receipt(receipt_path, root=fixture["root"], manifest_sha256=plan.manifest_sha256)


def test_terminal_matrix_missing_receipts_is_blocked_and_zero_credit(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    report = launcher.build_terminal_report(
        fixture["root"],
        receipt_paths={seed: tmp_path / f"missing-{seed}.json" for seed in launcher.SEEDS},
        manifest=fixture["manifest"],
    )
    assert report["status"] == "blocked_fail_closed"
    assert report["launch_allowed"] is False
    assert report["terminal_receipts_verified"] == 0
    assert report["credit"] == 0
    assert all(row["status"] == "missing" for row in report["seed_rows"])
    assert launcher.validate_report(report) == []


def test_cli_execute_flag_is_fail_closed(tmp_path: Path, capsys) -> None:
    fixture = _fixture(tmp_path)
    result = launcher.main(["--root", str(fixture["root"]), "--execute"])
    assert result == 2
    assert json.loads(capsys.readouterr().out)["status"] == "blocked_fail_closed"
