from __future__ import annotations

from dataclasses import replace
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "f3_mlp_hidden16_diagnostic_rollout_launcher_v1.py"
)
SPEC = importlib.util.spec_from_file_location(
    "f3_mlp_hidden16_diagnostic_rollout_launcher_v1", SCRIPT
)
assert SPEC and SPEC.loader
launcher = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = launcher
SPEC.loader.exec_module(launcher)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode()
        + b"\n"
    )


def _checkpoint(seed: int, path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "sha256": _sha(f"checkpoint-{seed}"),
        "bytes": path.stat().st_size,
        "schema": "core.checkpoint.v1",
        "update": 500,
    }


def _fixture(tmp_path: Path) -> dict[str, object]:
    root = tmp_path / "lab"
    reports = root / "reports"
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "campaigns" / "core-v1").mkdir(parents=True)
    (root / ".venv" / "bin" / "python").write_text("placeholder", encoding="utf-8")
    (root / "scripts" / "core_learning.py").write_text("placeholder", encoding="utf-8")
    (root / "campaigns" / "core-v1" / "f3-dataset-v2.json").write_text("{}", encoding="utf-8")
    reports.mkdir()

    runs: list[dict[str, object]] = []
    histories: dict[int, Path] = {}
    checkpoint_paths: dict[int, Path] = {}
    for seed in launcher.SEEDS:
        checkpoint_path = tmp_path / f"f3-mlp500-hidden16-seed{seed}-20260928-checkpoint.pt"
        checkpoint_path.write_bytes(f"checkpoint-{seed}".encode())
        checkpoint_paths[seed] = checkpoint_path
        training_receipt = tmp_path / f"f3-mlp500-hidden16-seed{seed}-20260928-training.json"
        training_receipt.write_text("{}", encoding="utf-8")
        checkpoint = _checkpoint(seed, checkpoint_path)
        training_sha = _sha(f"training-{seed}")
        runs.append(
            {
                "seed": seed,
                "status": "bound_complete",
                "source": {
                    "path": str(training_receipt),
                    "sha256": training_sha,
                    "bytes": training_receipt.stat().st_size,
                    "schema": "core.training.v1",
                },
                "evidence": {
                    "model_kind": "mlp",
                    "hidden": 16,
                    "updates": 500,
                    "run_id": launcher._expected_run_id(seed),
                    "evidence_status": "complete",
                    "manifest_sha256": "1" * 64,
                    "checkpoint": checkpoint,
                },
            }
        )
        history = {
            "schema": f"core.f3.mlp.hidden16.seed{seed}.full835_rollout_diagnostic.summary.v1",
            "status": "completed",
            "diagnostic_only": True,
            "formal": False,
            "formal_eligible": False,
            "qualification": False,
            "T1_numerical": False,
            "T2_macro": False,
            "T2_path": False,
            "qualification_credit": 0,
            "credit": 0,
            "source": {"manifest": {"sha256": "2" * 64}},
            "protocol": {
                "model": "mlp",
                "seed": seed,
                "training_updates": 500,
                "hidden": 16,
                "case_id": launcher.CASE_ID,
                "split": "test",
                "maximum_steps": 835,
                "diagnostic": True,
                "autonomous": True,
                "future_state_inputs": False,
            },
            "checkpoint": checkpoint,
            "evaluation": {
                "status": "completed",
                "transitions_executed": 835,
                "trajectory_frames_including_initial": 836,
                "finite_rollout_complete": True,
                "future_state_inputs": False,
            },
        }
        history_path = reports / launcher.HISTORY_FILENAME.format(seed=seed)
        _write_json(history_path, history)
        histories[seed] = history_path

    matrix = {
        "schema": launcher.TRAINING_SCHEMA,
        "source_bound": True,
        "diagnostic_only": True,
        "formal": False,
        "formal_eligible": False,
        "qualification": False,
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "qualification_credit": 0,
        "credit": 0,
        "shared_config": {"model_kind": "mlp", "hidden": 16, "updates": 500},
        "runs": runs,
    }
    matrix_path = reports / launcher.TRAINING_MATRIX_FILENAME
    _write_json(matrix_path, matrix)
    return {
        "root": root,
        "matrix": matrix_path,
        "histories": histories,
        "checkpoints": checkpoint_paths,
    }


def _nonce(tmp_path: Path, seed: int) -> str:
    return hashlib.sha256(f"{tmp_path}-{seed}".encode()).hexdigest()[:32]


def _plan(fixture: dict[str, object], tmp_path: Path, seed: int = 17):
    return launcher.build_plan(
        fixture["root"],
        seed=seed,
        nonce=_nonce(tmp_path, seed),
        history_summary=fixture["histories"][seed],
        training_matrix=fixture["matrix"],
        gpu_index=seed % 8,
    )


def _identity(plan, *, evaluation_bytes: int, trajectory_bytes: int, validator_bytes: int) -> dict[str, object]:
    return {
        "schema": f"{launcher.IDENTITY_SCHEMA_PREFIX}{plan.seed}{launcher.IDENTITY_SCHEMA_SUFFIX}",
        "status": "completed_diagnostic",
        "seed": plan.seed,
        "run_id": plan.run_id,
        "namespace": str(plan.namespace),
        "namespace_nonce": plan.nonce,
        "manifest_sha256": plan.manifest_sha256,
        "training_manifest_sha256": plan.training_manifest_sha256,
        "training_receipt_sha256": plan.training_receipt_sha256,
        "diagnostic_only": True,
        **launcher.ZERO_CREDIT_FIELDS,
        "checkpoint": dict(plan.checkpoint),
        "evaluation": {
            "path": str(plan.outputs["evaluation"]),
            "sha256": "3" * 64,
            "bytes": evaluation_bytes,
        },
        "trajectory": {
            "path": str(plan.outputs["trajectory"]),
            "sha256": "4" * 64,
            "bytes": trajectory_bytes,
        },
        "validator": {
            "path": str(plan.outputs["validator"]),
            "sha256": "5" * 64,
            "bytes": validator_bytes,
        },
    }


def _cleanup_external_outputs(plan) -> None:
    for key in ("evaluation", "trajectory", "progress", "log", "artifact_identity", "validator"):
        path = plan.outputs[key]
        if path.exists() or path.is_symlink():
            path.unlink()


def test_all_fixed_seeds_construct_fresh_zero_credit_commands(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plans = [_plan(fixture, tmp_path, seed) for seed in launcher.SEEDS]
    assert len({plan.namespace for plan in plans}) == 3
    for plan in plans:
        payload = plan.as_dict()
        assert payload["status"] == "dry_run_ready"
        assert payload["launched"] is False
        assert payload["case_id"] == launcher.CASE_ID
        assert payload["transitions"] == 835
        assert payload["frames"] == 836
        assert "--diagnostic" in plan.command
        assert "--formal" not in plan.command
        assert "credit" not in plan.command
        assert payload["diagnostic_only"] is True
        assert payload["formal"] is False
        assert payload["credit"] == 0
        assert payload["zero_credit_only"] is True
        assert not any(path.exists() or path.is_symlink() for path in plan.outputs.values())


def test_cli_default_is_dry_run_and_never_calls_popen(tmp_path: Path, monkeypatch, capsys) -> None:
    fixture = _fixture(tmp_path)

    def forbidden_popen(*args, **kwargs):
        raise AssertionError("dry-run must not call Popen")

    monkeypatch.setattr(launcher.subprocess, "Popen", forbidden_popen)
    result = launcher.main(
        [
            "--root", str(fixture["root"]),
            "--seed", "17",
            "--nonce", _nonce(tmp_path, 17),
            "--history-summary", str(fixture["histories"][17]),
            "--training-matrix", str(fixture["matrix"]),
            "--gpu-index", "3",
        ]
    )
    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "dry_run"
    assert output["launched"] is False
    assert output["input_boundary"]["runtime_started"] is False


def test_namespace_alias_is_rejected(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    nonce = _nonce(tmp_path, 17)
    with pytest.raises(launcher.LauncherError, match="lexical path alias"):
        launcher.build_plan(
            fixture["root"],
            seed=17,
            nonce=nonce,
            namespace=f"/tmp/alias/../f3-mlp500-hidden16-seed17-full835-nonce{nonce}",
            history_summary=fixture["histories"][17],
            training_matrix=fixture["matrix"],
        )


def test_symlink_and_hardlink_output_reuse_are_rejected(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    symlink_nonce = _nonce(tmp_path, 29)
    symlink_plan = _plan(fixture, tmp_path, 29)
    # Use a second plan so the collision target is not shared with the other tests.
    symlink_plan = replace(
        symlink_plan,
        nonce=symlink_nonce,
        namespace=Path(launcher._expected_namespace(29, symlink_nonce)),
        outputs=launcher._output_paths(Path(launcher._expected_namespace(29, symlink_nonce)), fixture["root"], 29),
        proof_output=fixture["root"] / "reports" / launcher.PROCESS_PROOF_FILENAME.format(seed=29),
    )
    symlink_plan.outputs["evaluation"].symlink_to(tmp_path / "missing-evaluation.json")
    try:
        with pytest.raises(launcher.LauncherError, match="symlink"):
            launcher.build_plan(
                fixture["root"],
                seed=29,
                nonce=symlink_nonce,
                history_summary=fixture["histories"][29],
                training_matrix=fixture["matrix"],
            )
    finally:
        symlink_plan.outputs["evaluation"].unlink(missing_ok=True)

    hardlink_nonce = _nonce(tmp_path, 43)
    hardlink_plan = _plan(fixture, tmp_path, 43)
    hardlink_plan.outputs["evaluation"].write_bytes(b"old")
    hardlink_alias = tmp_path / "hardlink-alias"
    os.link(hardlink_plan.outputs["evaluation"], hardlink_alias)
    try:
        with pytest.raises(launcher.LauncherError, match="hardlink"):
            launcher.build_plan(
                fixture["root"],
                seed=43,
                nonce=hardlink_nonce,
                history_summary=fixture["histories"][43],
                training_matrix=fixture["matrix"],
            )
    finally:
        hardlink_plan.outputs["evaluation"].unlink(missing_ok=True)
        hardlink_alias.unlink(missing_ok=True)


def test_history_formal_or_credit_claims_fail_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    history_path = fixture["histories"][17]
    history = json.loads(history_path.read_text(encoding="utf-8"))
    history["credit"] = 1
    _write_json(history_path, history)
    with pytest.raises(launcher.LauncherError, match="credit"):
        _plan(fixture, tmp_path, 17)


def test_process_exit_proof_is_strict_and_zero_credit(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plan = _plan(fixture, tmp_path, 17)
    plan.outputs["evaluation"].write_bytes(b"evaluation receipt")
    plan.outputs["trajectory"].write_bytes(b"trajectory placeholder")
    plan.outputs["validator"].write_bytes(b"validator receipt")
    identity = _identity(
        plan,
        evaluation_bytes=plan.outputs["evaluation"].stat().st_size,
        trajectory_bytes=plan.outputs["trajectory"].stat().st_size,
        validator_bytes=plan.outputs["validator"].stat().st_size,
    )
    try:
        proof = launcher.build_process_exit_proof(
            plan,
            artifact_identity=identity,
            evaluator_pid=12345,
            evaluator_returncode=0,
            launcher_pid=23456,
        )
        assert proof["status"] == "exited_successfully"
        assert proof["evaluator_alive"] is False
        assert proof["launcher_alive"] is False
        assert proof["evaluator_reaped"] is True
        assert proof["launcher_reaped"] is True
        assert proof["returncode"] == 0
        assert proof["source_bound"] is True
        assert proof["formal"] is False
        assert proof["formal_eligible"] is False
        assert proof["credit"] == 0
        assert proof["exit_proof_sha256"] == launcher._canonical_digest(launcher._proof_without_digest(proof))
    finally:
        _cleanup_external_outputs(plan)


def test_artifact_identity_pseudo_authority_field_is_rejected(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plan = _plan(fixture, tmp_path, 17)
    plan.outputs["evaluation"].write_bytes(b"evaluation receipt")
    plan.outputs["trajectory"].write_bytes(b"trajectory placeholder")
    plan.outputs["validator"].write_bytes(b"validator receipt")
    identity = _identity(
        plan,
        evaluation_bytes=plan.outputs["evaluation"].stat().st_size,
        trajectory_bytes=plan.outputs["trajectory"].stat().st_size,
        validator_bytes=plan.outputs["validator"].stat().st_size,
    )
    identity["formal"] = True
    try:
        with pytest.raises(launcher.LauncherError, match="formal"):
            launcher.build_process_exit_proof(
                plan,
                artifact_identity=identity,
                evaluator_pid=12345,
                evaluator_returncode=0,
                launcher_pid=23456,
            )
    finally:
        _cleanup_external_outputs(plan)


def test_execute_with_fake_natural_exit_writes_no_real_evaluator(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plan = _plan(fixture, tmp_path, 29)
    proof_path = fixture["root"] / "reports" / launcher.PROCESS_PROOF_FILENAME.format(seed=29)
    plan = replace(plan, proof_output=proof_path, outputs={**plan.outputs, "process_proof": proof_path})
    sizes = {
        "evaluation": len(b"evaluation"),
        "trajectory": len(b"trajectory"),
        "validator": len(b"validator"),
    }
    identity = _identity(
        plan,
        evaluation_bytes=sizes["evaluation"],
        trajectory_bytes=sizes["trajectory"],
        validator_bytes=sizes["validator"],
    )

    class FakeProcess:
        pid = 54321

        def __init__(self) -> None:
            self.returncode = None

        def wait(self) -> int:
            plan.outputs["evaluation"].write_bytes(b"evaluation")
            plan.outputs["trajectory"].write_bytes(b"trajectory")
            plan.outputs["validator"].write_bytes(b"validator")
            _write_json(plan.outputs["artifact_identity"], identity)
            self.returncode = 0
            return 0

        def poll(self) -> int | None:
            return self.returncode

    calls: list[list[str]] = []

    def fake_popen(command, **kwargs):
        calls.append(command)
        assert kwargs["start_new_session"] is True
        return FakeProcess()

    try:
        result = launcher.execute_plan(plan, popen_factory=fake_popen, launcher_pid=65432)
        assert result["status"] == "exited_successfully"
        assert result["proof_written"] is True
        assert calls and calls[0] == list(plan.command)
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        assert proof["evaluator_pid_observed"] == 54321
        assert proof["launcher_pid_observed"] == 65432
        assert proof["credit"] == 0
    finally:
        _cleanup_external_outputs(plan)


def test_nonzero_evaluator_never_mints_success_proof(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plan = _plan(fixture, tmp_path, 43)

    class FailedProcess:
        pid = 65431

        def wait(self) -> int:
            return 7

        def poll(self) -> int:
            return 7

    try:
        result = launcher.execute_plan(
            plan,
            popen_factory=lambda command, **kwargs: FailedProcess(),
            launcher_pid=65432,
        )
        assert result["status"] == "blocked_evaluator_returncode"
        assert result["proof_written"] is False
        assert not plan.proof_output.exists()
    finally:
        _cleanup_external_outputs(plan)
