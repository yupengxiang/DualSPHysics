from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import h5py
import numpy as np
import pytest

from scripts import f3_mlp_hidden16_terminal_workflow_v1 as workflow


def _nonce(tmp_path: Path, suffix: str = "") -> str:
    return hashlib.sha256(f"{tmp_path}:{suffix}".encode()).hexdigest()[:32]


def _namespace(nonce: str, seed: int = 17) -> Path:
    return workflow._expected_namespace(seed, nonce)


def _paths(nonce: str, seed: int = 17) -> dict[str, Path]:
    namespace = _namespace(nonce, seed)
    return {
        "namespace": namespace,
        "evaluation": Path(str(namespace) + "-evaluation.json"),
        "trajectory": Path(str(namespace) + "-trajectory.h5"),
        "validator": Path(str(namespace) + "-hdf5-validation.json"),
        "metadata": workflow.trajectory_metadata_path(namespace),
        "sidecar": Path(str(namespace) + "-artifact-identity.json"),
        "proof": Path(f"/tmp/f3-workflow-test-reports-{seed}-{nonce}.json"),
    }


def _cleanup(paths: dict[str, Path]) -> None:
    for path in paths.values():
        if path.is_file() or path.is_symlink():
            path.unlink()


def _write_complete_fixture(paths: dict[str, Path]) -> None:
    frames = workflow.FRAMES
    transitions = workflow.TRANSITIONS
    particles = 1
    with h5py.File(paths["trajectory"], "w") as handle:
        handle.attrs["schema_version"] = 1
        handle.attrs["future_state_inputs"] = False
        handle.attrs["autonomous_prediction"] = True
        handle.attrs["case_id"] = workflow.CASE_ID
        handle["time"] = np.arange(frames, dtype=np.float64) * 0.01
        handle["position"] = np.zeros((frames, particles, 3), dtype=np.float32)
        handle["velocity"] = np.ones((frames, particles, 3), dtype=np.float32)
        handle["particle_id"] = np.array([101], dtype=np.int64)
        handle["particle_zone"] = np.array([0], dtype=np.int32)
        handle["mass"] = np.ones(particles, dtype=np.float64)
        handle["valid"] = np.ones((frames, particles), dtype=np.bool_)

    metrics = [0.001] * transitions
    row = {
        "case_id": workflow.CASE_ID,
        "frames_predicted": transitions,
        "frames_expected": transitions,
        "frames_executed": transitions,
        "expected_frames": transitions,
        "executed": True,
        "position_rmse": metrics,
        "velocity_rmse": metrics,
        "position_ade": metrics,
        "velocity_ade": metrics,
        "failure_category": None,
        "first_failure_frame": None,
        "execution_complete": True,
        "finite_rollout_complete": True,
        "scientific_status": "not_assessed",
        "scientific_failure_category": None,
        "scientific_first_failure_frame": None,
        "future_state_inputs": False,
        "trajectory_output": paths["trajectory"].name,
        "score": {
            "expected_frames": transitions,
            "finite_prefix_frames": transitions,
            "executed": True,
            "complete": True,
            "failure_category": None,
            "raw_error_coverage": 1.0,
            "selection_score": 0.0,
        },
    }
    evaluation = {
        "schema": "core.evaluation.v1",
        "evaluation_mode": "diagnostic",
        "diagnostic": True,
        "formal_eligible": False,
        "registered_case_ids": [workflow.CASE_ID],
        "selected_case_ids": [workflow.CASE_ID],
        "expected_frames": {workflow.CASE_ID: transitions},
        "cases": {workflow.CASE_ID: row},
        "maximum_steps": transitions,
        "autonomous": True,
        "future_state_inputs": False,
    }
    paths["evaluation"].write_text(json.dumps(evaluation), encoding="utf-8")


def _capability(paths: dict[str, Path], root: Path) -> SimpleNamespace:
    nonce = paths["namespace"].name.rsplit("nonce", 1)[1]
    return SimpleNamespace(
        root=root,
        seed=17,
        nonce=nonce,
        evaluation=paths["evaluation"],
        trajectory=paths["trajectory"],
        validator=paths["validator"],
    )


def _fake_rollout(paths: dict[str, Path], root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        root=root,
        seed=17,
        nonce=paths["namespace"].name.rsplit("nonce", 1)[1],
        namespace=paths["namespace"],
        run_id="f3-mlp500-hidden16-seed17-20260928",
        command_sha256="a" * 64,
        env={"CUDA_VISIBLE_DEVICES": "3"},
        outputs={
            "evaluation": paths["evaluation"],
            "trajectory": paths["trajectory"],
            "validator": paths["validator"],
            "artifact_identity": paths["sidecar"],
            "process_proof": paths["proof"],
            "log": Path(str(paths["namespace"]) + "-evaluation.log"),
            "progress": Path(str(paths["namespace"]) + "-evaluation-progress.json"),
            "namespace": paths["namespace"],
        },
        proof_output=paths["proof"],
    )


def test_default_workflow_plan_is_dry_run_and_has_no_process_side_effects(monkeypatch, tmp_path):
    nonce = _nonce(tmp_path, "dry-run")
    paths = _paths(nonce)
    rollout = _fake_rollout(paths, tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(workflow.launcher, "build_plan", lambda *args, **kwargs: rollout)
    monkeypatch.setattr(workflow.launcher, "execute_plan", lambda *args, **kwargs: calls.append("execute"))

    plan = workflow.build_workflow_plan(tmp_path, seed=17, nonce=nonce, gpu_index=7)
    receipt = plan.as_receipt()

    assert receipt["status"] == "dry_run_ready"
    assert receipt["launched"] is False
    assert receipt["gpu_index"] == 7
    assert receipt["credit"] == 0
    assert receipt["side_effects"]["processes_started"] == 0
    assert calls == []
    assert len(receipt["namespace_nonce"]) == 32


def test_build_workflow_plan_rejects_existing_trajectory_metadata(monkeypatch, tmp_path):
    nonce = _nonce(tmp_path, "metadata-collision")
    paths = _paths(nonce)
    paths["metadata"].write_text("existing", encoding="utf-8")
    rollout = _fake_rollout(paths, tmp_path)
    monkeypatch.setattr(workflow.launcher, "build_plan", lambda *args, **kwargs: rollout)
    try:
        with pytest.raises(workflow.WorkflowError, match="already exists"):
            workflow.build_workflow_plan(tmp_path, seed=17, nonce=nonce)
    finally:
        _cleanup(paths)


def test_terminal_validator_calls_independent_validator_and_writes_metadata(tmp_path):
    nonce = _nonce(tmp_path, "validator-success")
    paths = _paths(nonce)
    _write_complete_fixture(paths)
    capability = _capability(paths, tmp_path)
    try:
        workflow.terminal_validator(capability)

        validator_payload = json.loads(paths["validator"].read_text(encoding="utf-8"))
        metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
        assert validator_payload["passed"] is True
        assert validator_payload["complete"] is True
        assert metadata["schema"] == workflow.TRAJECTORY_METADATA_SCHEMA
        assert metadata["seed"] == 17
        assert metadata["model"] == "mlp"
        assert metadata["hidden"] == 16
        assert metadata["updates"] == 500
        assert metadata["case_id"] == workflow.CASE_ID
        assert metadata["split"] == "test"
        assert metadata["transitions"] == 835
        assert metadata["frames"] == 836
        assert metadata["source_bound"] is True
        assert metadata["diagnostic_only"] is True
        assert metadata["future_state_inputs"] is False
        assert metadata["trajectory"]["bytes"] == paths["trajectory"].stat().st_size
        assert metadata["trajectory"]["sha256"] == metadata["stream_hash"]["sha256"]
        assert metadata["trajectory"]["bytes"] == metadata["stream_hash"]["bytes"]
    finally:
        _cleanup(paths)


def test_terminal_validator_fails_closed_without_writing_on_bad_receipt(tmp_path, monkeypatch):
    nonce = _nonce(tmp_path, "validator-fail")
    paths = _paths(nonce)
    paths["evaluation"].write_text("{}", encoding="utf-8")
    paths["trajectory"].write_bytes(b"not-an-hdf5")
    monkeypatch.setattr(
        workflow.validator,
        "run_validation",
        lambda *args, **kwargs: {
            "schema": workflow.VALIDATOR_SCHEMA,
            "passed": False,
            "fail_closed": True,
            "diagnostic_only": True,
            "synthetic_only": False,
            "production_artifacts_touched": False,
            "qualification_credit": 0,
            "failure_reason": "fixture failure",
        },
    )
    try:
        with pytest.raises(workflow.WorkflowError, match="passed"):
            workflow.terminal_validator(_capability(paths, tmp_path))
        assert not paths["validator"].exists()
        assert not paths["metadata"].exists()
    finally:
        _cleanup(paths)


def test_terminal_validator_rejects_capability_path_drift_before_validator_call(tmp_path, monkeypatch):
    nonce = _nonce(tmp_path, "path-drift")
    paths = _paths(nonce)
    paths["evaluation"].write_text("{}", encoding="utf-8")
    paths["trajectory"].write_bytes(b"x")
    capability = _capability(paths, tmp_path)
    capability.evaluation = Path(str(paths["namespace"]) + "-other-evaluation.json")
    called: list[str] = []
    monkeypatch.setattr(workflow.validator, "run_validation", lambda *args, **kwargs: called.append("run"))
    try:
        with pytest.raises(workflow.WorkflowError, match="drifts"):
            workflow.terminal_validator(capability)
        assert called == []
    finally:
        _cleanup(paths)


def test_validator_receipt_no_follow_rejects_preexisting_symlink(tmp_path):
    nonce = _nonce(tmp_path, "nofollow")
    paths = _paths(nonce)
    _write_complete_fixture(paths)
    target = tmp_path / "validator-target.json"
    target.write_text("sentinel", encoding="utf-8")
    paths["validator"].symlink_to(target)
    try:
        with pytest.raises(workflow.WorkflowError, match="symlink|overwrite"):
            workflow.terminal_validator(_capability(paths, tmp_path))
        assert target.read_text(encoding="utf-8") == "sentinel"
        assert not paths["metadata"].exists()
    finally:
        _cleanup(paths)


def test_artifact_producer_delegates_only_to_existing_sidecar(monkeypatch, tmp_path):
    nonce = _nonce(tmp_path, "producer")
    paths = _paths(nonce)
    calls: list[tuple[str, Any]] = []
    identity = {"schema": "fixture.identity.v1", "credit": 0}

    def build_identity(*args, **kwargs):
        calls.append(("build", (args, kwargs)))
        return identity

    def write_identity(*args, **kwargs):
        calls.append(("write", (args, kwargs)))
        kwargs["output"].write_text(json.dumps(identity), encoding="utf-8")
        return kwargs["output"]

    monkeypatch.setattr(workflow.sidecar, "build_identity", build_identity)
    monkeypatch.setattr(workflow.sidecar, "write_identity", write_identity)
    capability = SimpleNamespace(
        root=tmp_path,
        seed=17,
        nonce=nonce,
        evaluation_json=paths["evaluation"],
        trajectory_hdf5=paths["trajectory"],
        validator_receipt=paths["validator"],
        sidecar=paths["sidecar"],
    )

    workflow.artifact_identity_producer(capability)

    assert [item[0] for item in calls] == ["build", "write"]
    assert calls[0][1][1]["seed"] == 17
    assert calls[1][1][1]["output"] == paths["sidecar"]
    assert paths["sidecar"].is_file()


def test_execute_workflow_returns_bounded_zero_credit_receipt_without_real_process(monkeypatch, tmp_path):
    nonce = _nonce(tmp_path, "execute-fake")
    paths = _paths(nonce)
    rollout = _fake_rollout(paths, tmp_path)
    plan = workflow.TerminalWorkflowPlan(rollout=rollout, trajectory_metadata=paths["metadata"], gpu_index=3)

    def fake_build_identity(*args, **kwargs):
        def identity(path: Path) -> dict[str, Any]:
            raw = path.read_bytes()
            return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}

        return {
            "schema": "core.f3.mlp.hidden16.seed17.evaluator_artifact_identity.v1",
            "status": "completed_diagnostic",
            "seed": 17,
            "run_id": rollout.run_id,
            "namespace": str(rollout.namespace),
            "namespace_nonce": nonce,
            **workflow.ZERO_CREDIT,
            "evaluation": identity(paths["evaluation"]),
            "trajectory": identity(paths["trajectory"]),
            "validator": identity(paths["validator"]),
        }

    def fake_write_identity(identity, **kwargs):
        kwargs["output"].write_text(json.dumps(identity), encoding="utf-8")
        return kwargs["output"]

    monkeypatch.setattr(workflow.sidecar, "build_identity", fake_build_identity)
    monkeypatch.setattr(workflow.sidecar, "write_identity", fake_write_identity)

    def fake_execute(rollout_plan, *, artifact_identity_path, terminal_validator, artifact_identity_producer):
        _write_complete_fixture(paths)
        terminal_validator(_capability(paths, tmp_path))
        artifact_identity_producer(
            SimpleNamespace(
                root=tmp_path,
                seed=17,
                nonce=nonce,
                evaluation_json=paths["evaluation"],
                trajectory_hdf5=paths["trajectory"],
                validator_receipt=paths["validator"],
                sidecar=paths["sidecar"],
            )
        )
        proof = {
            "schema": "core.f3.mlp.hidden16.seed17.process_exit_proof.v1",
            "status": "exited_successfully",
            "source_bound": True,
            "seed": 17,
            "run_id": rollout_plan.run_id,
            "namespace": str(rollout_plan.namespace),
            "namespace_nonce": nonce,
            "evaluator_alive": False,
            "launcher_alive": False,
            "evaluator_returncode": 0,
            "launcher_returncode": 0,
            "returncode": 0,
            "evaluator_reaped": True,
            "launcher_reaped": True,
            **workflow.ZERO_CREDIT,
            "evaluation": {"path": str(paths["evaluation"])},
            "trajectory": {"path": str(paths["trajectory"])},
            "validator": {"path": str(paths["validator"])},
        }
        proof["exit_proof_sha256"] = hashlib.sha256(
            json.dumps({k: v for k, v in proof.items()}, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
        paths["proof"].parent.mkdir(parents=True, exist_ok=True)
        paths["proof"].write_text(json.dumps(proof), encoding="utf-8")
        return {"status": "exited_successfully", "proof_written": True}

    monkeypatch.setattr(workflow.launcher, "execute_plan", fake_execute)
    try:
        receipt = workflow.execute_workflow(plan)
        assert receipt["status"] == "exited_successfully"
        assert receipt["diagnostic_only"] is True
        assert receipt["credit"] == 0
        assert receipt["formal"] is False
        assert receipt["trusted_process_proof_sha256"] == receipt["process_proof"]["sha256"]
        assert receipt["validator"]["bytes"] > 0
        assert receipt["trajectory_metadata"]["bytes"] > 0
        assert receipt["side_effects"]["processes_stopped"] == 0
        assert receipt["side_effects"]["registry_writes"] == 0
        assert len(json.dumps(receipt, separators=(",", ":")).encode()) <= workflow.MAX_RECEIPT_BYTES
    finally:
        _cleanup(paths)
