"""Tests for the bounded current-manifest graph_residual full835 contract."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from scripts import f3_graph_residual_hidden16_current_manifest_rollout_launcher_v1 as launcher


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode()
        + b"\n"
    )


def _fixture(tmp_path: Path, *, seed: int = 17) -> dict[str, object]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    run_id = f"f3-graph_residual500-hidden16-currentmanifest-seed{seed}-20260929-v3"
    checkpoint = tmp_path / f"{run_id}-checkpoint.pt"
    checkpoint_bytes = b"isolated synthetic checkpoint metadata fixture"
    checkpoint.write_bytes(checkpoint_bytes)
    receipt = tmp_path / f"{run_id}-training.json"
    config = dict(launcher.STATIC_CONFIG)
    config.update(
        {
            "manifest_sha256": launcher.CURRENT_CANONICAL_MANIFEST_SHA256,
            "paired_seed": seed,
            "run_id": run_id,
            "sampler_seed": seed,
            "seed": seed,
        }
    )
    training = {
        "schema": launcher.TRAINING_SCHEMA,
        "status": "completed",
        "evidence_status": "complete",
        "model_kind": launcher.MODEL,
        "seed": seed,
        "run_id": run_id,
        "completed_updates": launcher.UPDATES,
        "parameter_count": launcher.PARAMETER_COUNT,
        "checkpoint_verified": True,
        "checkpoint": {
            "schema": launcher.CHECKPOINT_SCHEMA,
            "path": str(checkpoint),
            "sha256": _sha_bytes(checkpoint_bytes),
            "bytes": len(checkpoint_bytes),
            "update": launcher.UPDATES,
        },
        "config": config,
        "evidence": {
            "schema": "core.training.evidence.v1",
            "status": "complete",
            "initialization": {
                "schema": "core.training.initialization_evidence.v1",
                "status": "captured",
                "model_kind": launcher.MODEL,
                "hidden": launcher.HIDDEN,
                "parameter_count": launcher.PARAMETER_COUNT,
                "seed": seed,
                "constructed_before_first_update": True,
                "parameter_digest": _sha_bytes(f"parameter-{seed}".encode()),
            },
            "normalization": {
                "schema": "core.training.normalization_evidence.v1",
                "requested_maximum_transitions": 16,
                "selected_transition_count": 16,
                "selection_seed": seed,
                "source_split": "train",
                "target_reference": "raw_dual_increment_train_shared",
            },
            "residual_prior": {
                "schema": "core.training.prior_evidence.v1",
                "enabled": True,
                "history_complete": True,
                "execution_calls": launcher.UPDATES,
                "rows": 17_280_000,
                "finite": True,
            },
        },
    }
    _write_json(receipt, training)
    namespace_parent = tmp_path / "isolated-namespace-parent"
    namespace_parent.mkdir()
    nonce = hashlib.sha256(str(tmp_path).encode()).hexdigest()[:32]
    return {
        "root": launcher.LAB_ROOT,
        "manifest": launcher.LAB_ROOT / launcher.MANIFEST_RELATIVE,
        "checkpoint": checkpoint,
        "receipt": receipt,
        "run_id": run_id,
        "seed": seed,
        "nonce": nonce,
        "namespace": namespace_parent / f"f3-graph-residual500-hidden16-currentmanifest-seed{seed}-full835-nonce{nonce}",
    }


def _plan(fixture: dict[str, object]):
    return launcher.build_plan(
        fixture["root"],
        seed=fixture["seed"],
        manifest=fixture["manifest"],
        checkpoint=fixture["checkpoint"],
        training_receipt=fixture["receipt"],
        run_id=fixture["run_id"],
        nonce=fixture["nonce"],
        output_namespace=fixture["namespace"],
        gpu_index=7,
    )


def test_plan_binds_current_manifest_v3_identity_without_opening_checkpoint_content(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    before = fixture["checkpoint"].read_bytes()
    plan = _plan(fixture)

    assert plan.manifest == fixture["manifest"]
    assert plan.manifest_binding["canonical_sha256"] == launcher.CURRENT_CANONICAL_MANIFEST_SHA256
    assert plan.run_id.endswith("-v3")
    assert plan.nonce == fixture["nonce"]
    assert plan.command_sha256 == launcher._command_digest(plan.command, cwd=plan.cwd, env=plan.env)
    assert plan.as_dict()["launch_allowed"] is False
    assert plan.as_dict()["credit"] == 0
    assert plan.as_dict()["input_boundary"]["checkpoint_content_opened"] is False
    assert fixture["checkpoint"].read_bytes() == before


def test_plan_uses_unique_isolated_namespace_and_rejects_collision(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plan = _plan(fixture)
    assert plan.output_namespace.parent == tmp_path / "isolated-namespace-parent"
    assert not any(path.exists() for path in plan.outputs.values())

    collision = Path(plan.outputs["evaluation"])
    collision.write_bytes(b"collision")
    with pytest.raises(launcher.LauncherError, match="already exists|reuse"):
        _plan(fixture)


def test_manifest_path_and_legacy_or_partial_training_identity_fail_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    copied_manifest = tmp_path / "f3-dataset-v2.json"
    copied_manifest.write_bytes(Path(fixture["manifest"]).read_bytes())
    with pytest.raises(launcher.LauncherError, match="fixed current canonical manifest"):
        launcher.build_plan(
            fixture["root"],
            seed=fixture["seed"],
            manifest=copied_manifest,
            checkpoint=fixture["checkpoint"],
            training_receipt=fixture["receipt"],
            run_id=fixture["run_id"],
            nonce=fixture["nonce"],
            output_namespace=fixture["namespace"],
        )

    payload = json.loads(Path(fixture["receipt"]).read_text(encoding="utf-8"))
    payload["run_id"] = "f3-graph-residual500-hidden16-seed17-20260928"
    _write_json(Path(fixture["receipt"]), payload)
    with pytest.raises(launcher.LauncherError, match="run_id"):
        _plan(fixture)


def test_manifest_checkpoint_and_credit_drift_fail_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    payload = json.loads(Path(fixture["receipt"]).read_text(encoding="utf-8"))
    payload["config"]["manifest_sha256"] = "f" * 64
    _write_json(Path(fixture["receipt"]), payload)
    with pytest.raises(launcher.LauncherError, match="current manifest"):
        _plan(fixture)

    missing_root = tmp_path / "missing-checkpoint"
    missing_root.mkdir()
    fixture = _fixture(missing_root)
    fixture["checkpoint"].unlink()
    with pytest.raises(launcher.LauncherError, match="checkpoint input"):
        _plan(fixture)

    fixture = _fixture(tmp_path / "credit-alias")
    payload = json.loads(Path(fixture["receipt"]).read_text(encoding="utf-8"))
    payload["credit_alias"] = 1
    _write_json(Path(fixture["receipt"]), payload)
    with pytest.raises(launcher.LauncherError, match="unknown fields"):
        _plan(fixture)


def test_default_cli_is_blocked_dry_run_and_execute_path_is_not_available(tmp_path: Path, capsys) -> None:
    result = launcher.main(["--root", str(launcher.LAB_ROOT)])
    assert result == 2
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "blocked_fail_closed"
    assert output["launch_allowed"] is False
    assert output["credit"] == 0

    fixture = _fixture(tmp_path)
    plan = _plan(fixture)
    with pytest.raises(launcher.LauncherError, match="audited execute capability"):
        launcher.execute_plan(plan)


def _artifact(path: Path, content: bytes) -> dict[str, object]:
    path.write_bytes(content)
    return {
        "path": str(path),
        "sha256": _sha_bytes(content),
        "bytes": len(content),
        "content_opened": False,
        "stat_only": True,
    }


def _terminal_receipt(plan, tmp_path: Path) -> dict[str, object]:
    artifacts = {
        key: _artifact(path, f"isolated-{key}".encode())
        for key, path in plan.outputs.items()
        if key in {"evaluation", "trajectory", "progress", "validator"}
    }
    return {
        "schema": launcher.TERMINAL_RECEIPT_SCHEMA,
        "report_id": f"f3-graph-residual-hidden16-current-manifest-seed{plan.seed}-full835-terminal-receipt-v1",
        "status": "terminal_verified",
        "source_bound": True,
        **launcher.ZERO_CREDIT,
        "seed": plan.seed,
        "run_id": plan.run_id,
        "namespace": str(plan.output_namespace),
        "namespace_nonce": plan.nonce,
        "model_kind": launcher.MODEL,
        "hidden": launcher.HIDDEN,
        "updates": launcher.UPDATES,
        "case_id": launcher.CASE_ID,
        "split": launcher.SPLIT,
        "transitions": launcher.TRANSITIONS,
        "frames": launcher.FRAMES,
        "manifest_sha256": plan.manifest_binding["canonical_sha256"],
        "training_receipt": {
            "path": str(plan.training_receipt),
            "sha256": plan.training_binding["sha256"],
            "bytes": plan.training_binding["bytes"],
        },
        "checkpoint": dict(plan.checkpoint),
        "command": {
            "argv": list(plan.command),
            "cwd": str(plan.cwd),
            "env_overrides": dict(plan.env),
            "sha256": plan.command_sha256,
        },
        "process_exit_proof": {
            "schema": launcher.PROCESS_SCHEMA,
            "status": "exited_successfully",
            "source_bound": True,
            "seed": plan.seed,
            "run_id": plan.run_id,
            "namespace": str(plan.output_namespace),
            "namespace_nonce": plan.nonce,
            "command_sha256": plan.command_sha256,
            "launcher_command_sha256": plan.command_sha256,
            "evaluator_alive": False,
            "launcher_alive": False,
            "evaluator_returncode": 0,
            "launcher_returncode": 0,
            "returncode": 0,
            "natural_exit": True,
            "observed_after_exit": True,
        },
        "terminal_markers": {
            "terminal": True,
            "terminal_status": "completed",
            "execution_complete": True,
            "finite_rollout_complete": True,
            "requested_window_complete": True,
            "transitions_executed": launcher.TRANSITIONS,
            "frames_executed": launcher.FRAMES,
            "future_state_inputs": False,
        },
        "evaluation": {
            **artifacts["evaluation"],
            "schema": "core.evaluation.v1",
            "model_kind": launcher.MODEL,
            "seed": plan.seed,
            "hidden": launcher.HIDDEN,
            "updates": launcher.UPDATES,
            "case_id": launcher.CASE_ID,
            "split": launcher.SPLIT,
            "evaluation_mode": "diagnostic",
            "diagnostic": True,
            "autonomous": True,
            "maximum_steps": launcher.TRANSITIONS,
            "transitions": launcher.TRANSITIONS,
            "frames": launcher.FRAMES,
            "execution_complete": True,
            "finite_rollout_complete": True,
            "future_state_inputs": False,
            "status": "completed",
            "namespace": str(plan.output_namespace),
            "namespace_fresh": True,
            "namespace_nonce": plan.nonce,
        },
        "trajectory": artifacts["trajectory"],
        "progress": artifacts["progress"],
        "hdf5_validator": {
            **artifacts["validator"],
            "schema": launcher.VALIDATOR_SCHEMA,
            "passed": True,
            "complete": True,
            "diagnostic_only": True,
            "case_id": launcher.CASE_ID,
            "expected_transitions": launcher.TRANSITIONS,
            "frames_executed": launcher.FRAMES,
            "trajectory_frames": launcher.FRAMES,
            "trajectory_transitions": launcher.TRANSITIONS,
            "tail_frame_count": 0,
            "qualification_credit": 0,
            "production_artifacts_touched": False,
            "actual_future_state_inputs": False,
        },
        "side_effects": {
            "processes_started": 2,
            "processes_stopped": 0,
            "processes_restarted": 0,
            "registry_writes": 0,
            "ledger_writes": 0,
            "denominator_writes": 0,
            "gate_writes": 0,
            "completion_writes": 0,
            "plan_writes": 0,
        },
        "input_boundary": {
            "bounded_receipt_json_opened": True,
            "checkpoint_content_opened": False,
            "evaluation_content_opened": False,
            "trajectory_hdf5_opened": False,
            "progress_content_opened": False,
            "runtime_started": False,
            "runtime_stopped": False,
            "runtime_restarted": False,
        },
    }


def test_terminal_receipt_verifier_is_metadata_only_and_binds_full835(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plan = _plan(fixture)
    receipt = _terminal_receipt(plan, tmp_path)
    verified = launcher.verify_terminal_receipt(receipt, plan)
    assert verified["status"] == "terminal_verified"
    assert verified["credit"] == 0
    assert verified["artifacts"]["trajectory"]["path"] == str(plan.outputs["trajectory"])

    receipt_path = tmp_path / "isolated-terminal-receipt.json"
    _write_json(receipt_path, receipt)
    from_file = launcher.verify_terminal_receipt_file(receipt_path, plan)
    assert from_file["receipt_source"]["opened"] is True


@pytest.mark.parametrize(
    ("mutation", "needle"),
    [
        (lambda value: value["process_exit_proof"].update({"evaluator_alive": True}), "evaluator_alive"),
        (lambda value: value.update({"credit_alias": 1}), "unknown fields"),
        (lambda value: value["terminal_markers"].update({"transitions_executed": 834}), "transitions_executed"),
        (lambda value: value["command"].update({"sha256": "0" * 64}), "sha256"),
    ],
)
def test_terminal_receipt_running_alias_partial_and_command_drift_fail_closed(tmp_path: Path, mutation, needle: str) -> None:
    fixture = _fixture(tmp_path)
    plan = _plan(fixture)
    receipt = _terminal_receipt(plan, tmp_path)
    mutation(deepcopy(receipt))
    tampered = deepcopy(receipt)
    mutation(tampered)
    with pytest.raises(launcher.LauncherError, match=needle):
        launcher.verify_terminal_receipt(tampered, plan)


def test_blocked_report_is_zero_credit_and_self_validating() -> None:
    report = launcher.build_blocked_report(observed_at_utc="2026-09-29T00:00:00Z")
    launcher.validate_report(report)
    assert report["launch_allowed"] is False
    assert report["terminal_receipt_verified"] is False
    assert report["credit"] == 0
