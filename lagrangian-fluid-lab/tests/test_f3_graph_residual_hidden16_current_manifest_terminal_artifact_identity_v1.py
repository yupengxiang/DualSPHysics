"""Safety tests for the residual current-manifest terminal identity boundary."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest

from scripts import f3_graph_residual_hidden16_current_manifest_terminal_artifact_identity_v1 as identity


def _admission(gpu: int = 4) -> dict[str, object]:
    return identity.probe_resource_admission(
        gpu,
        gpu_rows={gpu: {"total_mib": 49140, "used_mib": 1000, "free_mib": 48140}},
        cpu_count=128,
        load_1m=1.0,
        tmp_free_bytes=100 * 1024**3,
        root_free_bytes=100 * 1024**3,
    )


@pytest.fixture()
def current_plan(tmp_path: Path):
    required = [
        identity.DEFAULT_MANIFEST,
        *identity.DEFAULT_RECEIPTS.values(),
        *identity.DEFAULT_CHECKPOINTS.values(),
    ]
    if not all(path.exists() for path in required):
        pytest.skip("current diagnostic residual receipts are not present")
    seed = 17
    nonce = "a" * 32
    namespace = tmp_path / (
        f"f3-graph-residual500-hidden16-currentmanifest-seed{seed}-full835-nonce{nonce}"
    )
    return identity.build_audited_plan(
        identity.LAB_ROOT,
        seed=seed,
        manifest=identity.DEFAULT_MANIFEST,
        training_receipt=identity.DEFAULT_RECEIPTS[seed],
        checkpoint=identity.DEFAULT_CHECKPOINTS[seed],
        run_id=identity._expected_run_id(seed),
        nonce=nonce,
        output_namespace=namespace,
        gpu_index=4,
        admission=_admission(),
    )


def _artifact(path: Path, label: str) -> dict[str, object]:
    digest = hashlib.sha256(label.encode()).hexdigest()
    return {"path": str(path), "sha256": digest, "bytes": len(label)}


def _terminal_evidence(plan) -> dict[str, object]:
    evaluation = _artifact(plan.outputs["evaluation"], "evaluation")
    trajectory = _artifact(plan.outputs["trajectory"], "trajectory")
    return {
        "schema": identity.SCHEMA,
        "status": "terminal_identity_candidate",
        "seed": plan.seed,
        "run_id": plan.base.run_id,
        "namespace": str(plan.namespace),
        "namespace_nonce": plan.nonce,
        "namespace_fresh": True,
        "model_kind": identity.MODEL,
        "hidden": identity.HIDDEN,
        "updates": identity.UPDATES,
        "case_id": identity.CASE_ID,
        "split": identity.SPLIT,
        "transitions": identity.TRANSITIONS,
        "frames": identity.FRAMES,
        "manifest_sha256": plan.base.manifest_binding["canonical_sha256"],
        "training_receipt_sha256": plan.base.training_binding["sha256"],
        "checkpoint": dict(plan.base.checkpoint),
        "command_sha256": plan.base.command_sha256,
        "process_proof": {
            "schema": identity.PROCESS_PROOF_SCHEMA,
            "producer": "subprocess.Popen",
            "evidence_kind": "runtime_process_observation",
            "synthetic": False,
            "popen_called": True,
            "pid_observed": True,
            "pid": 424242,
            "wait_called": True,
            "wait_returncode": 0,
            "exit_status_verified": True,
            "command_sha256": plan.base.command_sha256,
            "cwd": str(plan.base.cwd),
            "argv": list(plan.base.command),
        },
        "evaluation_artifact": evaluation,
        "trajectory_artifact": trajectory,
        "hdf5_validator": {
            "schema": identity.HDF5_VALIDATOR_SCHEMA,
            "producer": "independent_hdf5_validator",
            "independent": True,
            "synthetic": False,
            "passed": True,
            "complete": True,
            "hdf5_content_opened": True,
            "trajectory_content_opened": True,
            "expected_transitions": identity.TRANSITIONS,
            "frames_executed": identity.FRAMES,
            "trajectory_transitions": identity.TRANSITIONS,
            "trajectory_frames": identity.FRAMES,
            "tail_frame_count": 1,
            "trajectory_artifact": trajectory,
            "evaluation_artifact": evaluation,
            "validator_returncode": 0,
        },
    }


def test_current_manifest_plan_binds_real_v3_residual_receipt(current_plan) -> None:
    assert current_plan.base.run_id.endswith("-20260929-v3")
    assert current_plan.base.manifest_binding["canonical_sha256"] == identity.launcher.CURRENT_CANONICAL_MANIFEST_SHA256
    assert current_plan.base.training_binding["model_kind"] == "graph_residual"
    assert current_plan.base.training_binding["checkpoint"]["update"] == 500
    assert current_plan.admission["status"] == "admitted"
    assert not current_plan.namespace.exists()


def test_terminal_identity_cross_binds_process_and_independent_hdf5_validator(current_plan) -> None:
    result = identity.validate_terminal_artifact_identity(_terminal_evidence(current_plan), current_plan)
    assert result["process_proof_bound"] is True
    assert result["hdf5_validator_bound"] is True
    assert result["artifact_identity_bound"] is True
    assert result["trusted_for_formal_credit"] is False
    assert result["credit"] == 0


def test_terminal_identity_rejects_nonce_drift(current_plan) -> None:
    evidence = _terminal_evidence(current_plan)
    evidence["namespace_nonce"] = "b" * 32
    with pytest.raises(identity.IdentityError, match="namespace_nonce"):
        identity.validate_terminal_artifact_identity(evidence, current_plan)


def test_terminal_identity_rejects_command_drift(current_plan) -> None:
    evidence = _terminal_evidence(current_plan)
    evidence["process_proof"]["command_sha256"] = "1" * 64
    with pytest.raises(identity.IdentityError, match="command_sha256"):
        identity.validate_terminal_artifact_identity(evidence, current_plan)


def test_terminal_identity_rejects_hdf5_frame_drift(current_plan) -> None:
    evidence = _terminal_evidence(current_plan)
    evidence["hdf5_validator"]["trajectory_frames"] = identity.FRAMES - 1
    with pytest.raises(identity.IdentityError, match="trajectory_frames"):
        identity.validate_terminal_artifact_identity(evidence, current_plan)


def test_execute_blocks_before_popen_without_terminal_capability(current_plan) -> None:
    called = {"count": 0}

    def forbidden_popen(*_args, **_kwargs):
        called["count"] += 1
        raise AssertionError("Popen must not be reached without terminal capability")

    with pytest.raises(identity.IdentityError, match="not implemented/admitted"):
        identity.execute_plan(
            current_plan,
            popen_factory=forbidden_popen,
            admission_probe=lambda _gpu: _admission(),
        )
    assert called["count"] == 0
    assert not current_plan.namespace.exists()


def test_spoof_process_cannot_mint_real_popen_proof(current_plan, monkeypatch: pytest.MonkeyPatch) -> None:
    token = object()
    monkeypatch.setattr(identity, "_TERMINAL_CAPABILITY_TOKEN", token)

    class SpoofProcess:
        pid = 4242

        def wait(self):
            return 0

    with pytest.raises(identity.IdentityError, match="real subprocess.Popen"):
        identity._run_popen_wait(
            current_plan,
            terminal_capability=token,
            popen_factory=lambda *_args, **_kwargs: SpoofProcess(),
            admission_probe=lambda _gpu: _admission(),
        )


def test_blocked_report_has_zero_terminal_counts_and_no_side_effects(tmp_path: Path) -> None:
    missing_receipts = {
        seed: tmp_path / f"f3-graph_residual500-hidden16-currentmanifest-seed{seed}-20260929-v3-training.json"
        for seed in identity.SEEDS
    }
    missing_checkpoints = {
        seed: tmp_path / f"f3-graph_residual500-hidden16-currentmanifest-seed{seed}-20260929-v3-checkpoint.pt"
        for seed in identity.SEEDS
    }
    report = identity.build_report(
        identity.LAB_ROOT,
        manifest=identity.DEFAULT_MANIFEST,
        training_receipts=missing_receipts,
        checkpoints=missing_checkpoints,
        nonces={17: "1" * 32, 29: "2" * 32, 43: "3" * 32},
        output_root=tmp_path,
        gpu_rows={
            gpu: {"total_mib": 49140, "used_mib": 1000, "free_mib": 48140}
            for gpu in (4, 5, 6)
        },
        cpu_count=128,
        load_1m=1.0,
        tmp_free_bytes=100 * 1024**3,
        root_free_bytes=100 * 1024**3,
    )
    assert identity.validate_report(report) == []
    assert report["launch_allowed"] is False
    assert report["process_proofs_verified"] == 0
    assert report["hdf5_validators_verified"] == 0
    assert report["terminal_artifacts_verified"] == 0
    assert report["side_effects"]["processes_started"] == 0


def test_report_validator_rejects_forged_terminal_count(tmp_path: Path) -> None:
    missing = {
        seed: tmp_path / f"missing-{seed}-20260929-v3.json" for seed in identity.SEEDS
    }
    report = identity.build_report(
        identity.LAB_ROOT,
        manifest=identity.DEFAULT_MANIFEST,
        training_receipts=missing,
        checkpoints=missing,
        nonces={17: "4" * 32, 29: "5" * 32, 43: "6" * 32},
        output_root=tmp_path,
        gpu_rows={gpu: {"total_mib": 49140, "used_mib": 1000, "free_mib": 48140} for gpu in (4, 5, 6)},
        cpu_count=128,
        load_1m=1.0,
        tmp_free_bytes=100 * 1024**3,
        root_free_bytes=100 * 1024**3,
    )
    forged = copy.deepcopy(report)
    forged["process_proofs_verified"] = 1
    assert identity.validate_report(forged)
