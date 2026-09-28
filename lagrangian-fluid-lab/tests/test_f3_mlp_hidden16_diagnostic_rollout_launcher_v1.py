from __future__ import annotations

from dataclasses import replace
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
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
    (root / "scripts" / "core_learning.py").write_text(
        """import hashlib
import json
import re
import sys
from pathlib import Path


def argument(flag: str) -> Path:
    return Path(sys.argv[sys.argv.index(flag) + 1])


evaluation = argument("--output")
trajectory = argument("--trajectory-output")
prefix = str(evaluation)[:-len("-evaluation.json")]
validator = Path(prefix + "-hdf5-validation.json")
identity_path = Path(prefix + "-artifact-identity.json")
checkpoint = argument("--checkpoint").resolve()
seed = int(re.search(r"seed(17|29|43)", checkpoint.name).group(1))
evaluation.write_bytes(b"evaluation")
trajectory.write_bytes(b"trajectory")
validator.write_bytes(b"validator")
identity = {
    "schema": f"core.f3.mlp.hidden16.seed{seed}.evaluator_artifact_identity.v1",
    "status": "completed_diagnostic",
    "seed": seed,
    "run_id": f"f3-mlp500-hidden16-seed{seed}-20260928",
    "namespace": prefix,
    "namespace_nonce": prefix.rsplit("nonce", 1)[1],
    "manifest_sha256": "2" * 64,
    "training_manifest_sha256": "1" * 64,
    "training_receipt_sha256": hashlib.sha256(f"training-{seed}".encode()).hexdigest(),
    "diagnostic_only": True,
    "formal": False,
    "formal_eligible": False,
    "T1_numerical": False,
    "T2_macro": False,
    "T2_path": False,
    "qualification": False,
    "qualification_credit": 0,
    "credit": 0,
    "checkpoint": {
        "path": str(checkpoint),
        "sha256": hashlib.sha256(f"checkpoint-{seed}".encode()).hexdigest(),
        "bytes": checkpoint.stat().st_size,
    },
    "evaluation": {"path": str(evaluation), "sha256": "3" * 64, "bytes": evaluation.stat().st_size},
    "trajectory": {"path": str(trajectory), "sha256": "4" * 64, "bytes": trajectory.stat().st_size},
    "validator": {"path": str(validator), "sha256": "5" * 64, "bytes": validator.stat().st_size},
}
identity_path.write_text(json.dumps(identity, sort_keys=True), encoding="utf-8")
""",
        encoding="utf-8",
    )
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


def _install_real_fixture_interpreter(fixture: dict[str, object]) -> None:
    path = fixture["root"] / ".venv" / "bin" / "python"
    path.unlink()
    path.write_bytes(Path(sys.executable).resolve().read_bytes())
    path.chmod(0o755)


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


def test_all_zero_nonce_is_rejected(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    with pytest.raises(launcher.LauncherError, match="non-zero"):
        launcher.build_plan(
            fixture["root"],
            seed=17,
            nonce="0" * 32,
            history_summary=fixture["histories"][17],
            training_matrix=fixture["matrix"],
        )


def test_build_plan_rejects_symlinked_input_parent(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    scripts = fixture["root"] / "scripts"
    real_scripts = fixture["root"] / "scripts-real"
    scripts.rename(real_scripts)
    scripts.symlink_to(real_scripts, target_is_directory=True)
    try:
        with pytest.raises(launcher.LauncherError, match="symlink directory"):
            _plan(fixture, tmp_path, 17)
    finally:
        scripts.unlink()
        real_scripts.rename(scripts)


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


def test_process_exit_proof_rejects_synthetic_pid_and_returncode(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plan = _plan(fixture, tmp_path, 17)
    with pytest.raises(launcher.LauncherError, match="execution_record"):
        launcher.build_process_exit_proof(
            plan,
            artifact_identity={},
            evaluator_pid=12345,
            evaluator_returncode=0,
            launcher_pid=23456,
        )


def test_process_exit_proof_rejects_unsealed_record(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plan = _plan(fixture, tmp_path, 17)
    with pytest.raises(launcher.LauncherError, match="minted by the actual execute_plan"):
        launcher.build_process_exit_proof(
            plan,
            artifact_identity={},
            execution_record={"status": "exited_successfully"},
        )


def test_artifact_identity_pseudo_authority_field_is_rejected_on_execute(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    _install_real_fixture_interpreter(fixture)
    core_path = fixture["root"] / "scripts" / "core_learning.py"
    core_path.write_text(core_path.read_text(encoding="utf-8").replace('"formal": False', '"formal": True'), encoding="utf-8")
    plan = _plan(fixture, tmp_path, 17)
    try:
        with pytest.raises(launcher.LauncherError, match="(?:formal|cmdline)"):
            launcher.execute_plan(plan)
    finally:
        _cleanup_external_outputs(plan)


def test_execute_with_real_popen_natural_exit_writes_zero_credit_proof(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    _install_real_fixture_interpreter(fixture)
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

    calls: list[list[str]] = []
    real_popen = launcher.subprocess.Popen

    def recording_popen(command, **kwargs):
        calls.append(command)
        assert kwargs["start_new_session"] is True
        assert kwargs["pass_fds"]
        assert kwargs["cwd"].startswith("/proc/self/fd/")
        expected_environment = os.environ.copy()
        expected_environment.update(plan.env)
        assert kwargs["env"] == expected_environment
        process = real_popen(command, **kwargs)
        assert tuple(process.args) == tuple(command)
        assert os.stat(f"/proc/{process.pid}/cwd").st_ino == plan.root.stat().st_ino
        return process

    try:
        result = launcher.execute_plan(plan, popen_factory=recording_popen)
        assert result["status"] == "exited_successfully"
        assert result["proof_written"] is True
        assert calls and calls[0] != list(plan.command)
        assert calls[0][0].startswith("/proc/self/fd/")
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        assert proof["evaluator_pid_observed"] > 0
        assert proof["launcher_pid_observed"] == os.getpid()
        assert proof["evaluator_start_identity"]["pid"] == proof["evaluator_pid_observed"]
        assert isinstance(proof["evaluator_start_identity"]["proc_starttime_ticks"], int)
        assert proof["evaluator_end_identity"]["returncode"] == 0
        assert proof["launcher_start_identity"]["pid"] == os.getpid()
        assert proof["launcher_end_identity"]["returncode"] == 0
        assert proof["command_sha256"] == plan.command_sha256
        assert proof["credit"] == 0
        assert proof["exit_proof_sha256"] == launcher._canonical_digest(launcher._proof_without_digest(proof))
    finally:
        _cleanup_external_outputs(plan)


def test_nonzero_evaluator_never_mints_success_proof(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plan = _plan(fixture, tmp_path, 43)

    real_popen = launcher.subprocess.Popen
    processes: list[subprocess.Popen] = []

    def failed_popen(command, **kwargs):
        process = real_popen(
            [sys.executable, "-c", "raise SystemExit(7)"],
            cwd=kwargs["cwd"],
            env=kwargs["env"],
            stdout=kwargs["stdout"],
            stderr=kwargs["stderr"],
            start_new_session=kwargs["start_new_session"],
            pass_fds=kwargs["pass_fds"],
        )
        processes.append(process)
        return process

    try:
        with pytest.raises(launcher.LauncherError, match="different command"):
            launcher.execute_plan(plan, popen_factory=failed_popen)
        assert processes and processes[0].wait() == 7
        assert not plan.proof_output.exists()
    finally:
        _cleanup_external_outputs(plan)


def test_factory_successful_different_command_is_rejected_before_proof(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plan = _plan(fixture, tmp_path, 17)

    real_popen = launcher.subprocess.Popen
    processes: list[subprocess.Popen] = []

    def successful_different_popen(command, **kwargs):
        process = real_popen(
            [sys.executable, "-c", "import time; time.sleep(0.05); raise SystemExit(0)"],
            cwd=kwargs["cwd"],
            env=kwargs["env"],
            stdout=kwargs["stdout"],
            stderr=kwargs["stderr"],
            start_new_session=kwargs["start_new_session"],
            pass_fds=kwargs["pass_fds"],
        )
        processes.append(process)
        return process

    try:
        with pytest.raises(launcher.LauncherError, match="different command"):
            launcher.execute_plan(plan, popen_factory=successful_different_popen)
        assert processes and processes[0].wait() == 0
        assert not plan.proof_output.exists()
    finally:
        _cleanup_external_outputs(plan)


@pytest.mark.parametrize("input_name", ["interpreter", "core_learning", "manifest", "checkpoint"])
def test_execute_rejects_input_identity_drift_before_popen(tmp_path: Path, input_name: str) -> None:
    fixture = _fixture(tmp_path)
    plan = _plan(fixture, tmp_path, 17)
    path = Path(plan.input_snapshots[input_name]["path"])
    path.write_bytes(path.read_bytes() + b"-drift")
    calls = 0

    def forbidden_popen(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("identity drift must be rejected before Popen")

    with pytest.raises(launcher.LauncherError, match="identity drift"):
        launcher.execute_plan(plan, popen_factory=forbidden_popen)
    assert calls == 0


def test_execute_rejects_spoofed_launcher_pid(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plan = _plan(fixture, tmp_path, 17)
    with pytest.raises(launcher.LauncherError, match="launcher_pid overrides"):
        launcher.execute_plan(plan, popen_factory=lambda *args, **kwargs: None, launcher_pid=os.getpid() + 1)


def test_execute_rejects_non_popen_factory_result(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plan = _plan(fixture, tmp_path, 17)

    class SyntheticProcess:
        pid = 99999

    try:
        with pytest.raises(launcher.LauncherError, match="actual subprocess.Popen"):
            launcher.execute_plan(plan, popen_factory=lambda *args, **kwargs: SyntheticProcess())
    finally:
        _cleanup_external_outputs(plan)
