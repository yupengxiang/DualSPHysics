"""Fail-closed tests for the residual terminal execution bridge."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path

import h5py
import pytest

from scripts import f3_graph_residual_hidden16_current_manifest_terminal_execution_bridge_v1 as bridge


def _admission(gpu: int = 4) -> dict[str, object]:
    return bridge.identity.probe_resource_admission(
        gpu,
        gpu_rows={gpu: {"total_mib": 49140, "used_mib": 1000, "free_mib": 48140}},
        cpu_count=128,
        load_1m=1.0,
        tmp_free_bytes=100 * 1024**3,
        root_free_bytes=100 * 1024**3,
    )


@pytest.fixture()
def current_plan(tmp_path: Path) -> bridge.BridgePlan:
    required = [bridge.DEFAULT_MANIFEST, *bridge.DEFAULT_RECEIPTS.values(), *bridge.DEFAULT_CHECKPOINTS.values()]
    if not all(path.exists() for path in required):
        pytest.skip("current diagnostic residual receipts are not present")
    seed = 17
    nonce = "a" * 32
    namespace = tmp_path / f"f3-graph-residual500-hidden16-currentmanifest-seed{seed}-full835-nonce{nonce}"
    return bridge.build_bridge_plan(
        bridge.LAB_ROOT,
        seed=seed,
        manifest=bridge.DEFAULT_MANIFEST,
        training_receipt=bridge.DEFAULT_RECEIPTS[seed],
        checkpoint=bridge.DEFAULT_CHECKPOINTS[seed],
        nonce=nonce,
        output_namespace=namespace,
        gpu_index=4,
        admission=_admission(),
    )


def _artifact(path: Path, raw: bytes) -> dict[str, object]:
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _terminal_identity(plan: bridge.BridgePlan) -> dict[str, object]:
    evaluation_path = plan.audited.outputs["evaluation"]
    evaluation_path.write_bytes(b'{"diagnostic":true}\n')
    evaluation = _artifact(evaluation_path, evaluation_path.read_bytes())
    trajectory_path = plan.audited.outputs["trajectory"]
    with h5py.File(trajectory_path, "w") as handle:
        handle.create_dataset("positions", data=[0.0, 1.0])
    trajectory = _artifact(trajectory_path, trajectory_path.read_bytes())
    checkpoint = {key: plan.audited.base.checkpoint[key] for key in ("path", "sha256", "bytes")}
    lifecycle_binding = {
        "schema": bridge.identity.SEALED_LIFECYCLE_SCHEMA,
        "producer": "audited_runtime_sealed_witness",
        "sealed": True,
        "popen_called": True,
        "wait_called": True,
        "wait_returncode": 0,
        "reaped": True,
        "natural_exit": True,
        "argv": list(plan.audited.base.command),
        "cwd": str(plan.audited.base.cwd),
        "env": dict(plan.audited.base.env),
        "plan_digest": plan.plan_digest,
        "manifest_sha256": plan.audited.base.manifest_binding["canonical_sha256"],
        "training_receipt_sha256": plan.audited.base.training_binding["sha256"],
        "checkpoint": checkpoint,
        "namespace": str(plan.namespace),
        "namespace_nonce": plan.nonce,
    }
    lifecycle = {
        **{key: lifecycle_binding[key] for key in ("schema", "producer", "sealed", "popen_called", "wait_called", "wait_returncode", "reaped", "natural_exit", "argv", "cwd", "env")},
        "binding_sha256": bridge.identity.canonical_digest(lifecycle_binding),
    }
    return {
        "schema": bridge.identity.SCHEMA,
        "status": "terminal_identity_candidate",
        "seed": plan.seed,
        "run_id": plan.audited.base.run_id,
        "namespace": str(plan.namespace),
        "namespace_nonce": plan.nonce,
        "namespace_fresh": True,
        "model_kind": bridge.MODEL,
        "hidden": bridge.HIDDEN,
        "updates": bridge.UPDATES,
        "case_id": bridge.CASE_ID,
        "split": bridge.SPLIT,
        "transitions": bridge.TRANSITIONS,
        "frames": bridge.FRAMES,
        "plan_digest": plan.plan_digest,
        "manifest_sha256": plan.audited.base.manifest_binding["canonical_sha256"],
        "training_receipt_sha256": plan.audited.base.training_binding["sha256"],
        "checkpoint": {**checkpoint, "schema": bridge.identity.launcher.CHECKPOINT_SCHEMA, "update": bridge.UPDATES},
        "command_sha256": plan.audited.base.command_sha256,
        "process_proof": {
            "schema": bridge.identity.PROCESS_PROOF_SCHEMA,
            "producer": "subprocess.Popen",
            "evidence_kind": "runtime_process_observation",
            "synthetic": False,
            "popen_called": True,
            "wait_called": True,
            "wait_returncode": 0,
            "exit_status_verified": True,
            "plan_digest": plan.plan_digest,
            "manifest_sha256": plan.audited.base.manifest_binding["canonical_sha256"],
            "training_receipt_sha256": plan.audited.base.training_binding["sha256"],
            "checkpoint": checkpoint,
            "namespace": str(plan.namespace),
            "namespace_nonce": plan.nonce,
            "command_sha256": plan.audited.base.command_sha256,
            "cwd": str(plan.audited.base.cwd),
            "env": dict(plan.audited.base.env),
            "argv": list(plan.audited.base.command),
            "sealed_lifecycle": lifecycle,
        },
        "evaluation_artifact": evaluation,
        "trajectory_artifact": trajectory,
        "hdf5_validator": {
            "schema": bridge.identity.HDF5_VALIDATOR_SCHEMA,
            "producer": "independent_hdf5_validator",
            "independent": True,
            "synthetic": False,
            "passed": True,
            "complete": True,
            "hdf5_content_opened": True,
            "trajectory_content_opened": True,
            "expected_transitions": bridge.TRANSITIONS,
            "frames_executed": bridge.FRAMES,
            "trajectory_transitions": bridge.TRANSITIONS,
            "trajectory_frames": bridge.FRAMES,
            "tail_frame_count": 1,
            "trajectory_artifact": trajectory,
            "evaluation_artifact": evaluation,
            "validator_returncode": 0,
        },
    }


def _receipt(plan: bridge.BridgePlan) -> dict[str, object]:
    identity = _terminal_identity(plan)
    checkpoint = {key: plan.audited.base.checkpoint[key] for key in ("path", "sha256", "bytes")}
    return {
        "schema": bridge.RECEIPT_SCHEMA,
        "status": "terminal_execution_verified_diagnostic_only",
        "seed": plan.seed,
        "plan_digest": plan.plan_digest,
        "manifest_sha256": plan.audited.base.manifest_binding["canonical_sha256"],
        "training_receipt_sha256": plan.audited.base.training_binding["sha256"],
        "namespace": str(plan.namespace),
        "namespace_nonce": plan.nonce,
        "model_kind": bridge.MODEL,
        "hidden": bridge.HIDDEN,
        "updates": bridge.UPDATES,
        "case_id": bridge.CASE_ID,
        "split": bridge.SPLIT,
        "transitions": bridge.TRANSITIONS,
        "frames": bridge.FRAMES,
        "runtime_verifier_binding": bridge._runtime_binding(plan),
        "execution_observation": {
            "schema": bridge.OBSERVATION_SCHEMA,
            "producer": "audited_terminal_producer",
            "synthetic": False,
            "popen_called": True,
            "wait_observed": True,
            "wait_returncode": 0,
            "plan_digest": plan.plan_digest,
            "manifest_sha256": plan.audited.base.manifest_binding["canonical_sha256"],
            "training_receipt_sha256": plan.audited.base.training_binding["sha256"],
            "checkpoint": checkpoint,
            "namespace": str(plan.namespace),
            "namespace_nonce": plan.nonce,
            "command_sha256": plan.audited.base.command_sha256,
            "argv": list(plan.audited.base.command),
            "cwd": str(plan.audited.base.cwd),
            "env": dict(plan.audited.base.env),
            "independent_validator_passed": True,
            "validator_returncode": 0,
            "transitions": bridge.TRANSITIONS,
            "frames": bridge.FRAMES,
        },
        "terminal_artifact_identity": identity,
        **bridge.ZERO_CREDIT,
    }


def test_contract_review_remains_non_authorizing() -> None:
    review = bridge._review_contracts()
    assert review["terminal_runtime_verifier"]["direct_current_manifest_admission"] is False
    assert review["current_bridge"]["terminal_producer_admitted"] is False


def test_bridge_has_no_injectable_popen_surface(current_plan: bridge.BridgePlan) -> None:
    assert "popen_factory" not in inspect.signature(bridge.execute_bridge).parameters
    boundary = bridge.execute_bridge(current_plan)
    assert boundary["mode"] == "dry_run"
    assert boundary["launch_allowed"] is False
    assert boundary["popen_called"] is False
    assert boundary["wait_observed"] is False


def test_explicit_execute_request_is_rejected_before_any_runtime(current_plan: bridge.BridgePlan) -> None:
    with pytest.raises(bridge.BridgeError, match="not implemented/admitted"):
        bridge.execute_bridge(current_plan, execution_requested=True)


def test_complete_receipt_is_rejected_without_sealed_runtime_witness(current_plan: bridge.BridgePlan) -> None:
    with pytest.raises((bridge.BridgeError, bridge.identity.IdentityError), match="declaration-only|sealed real Popen/wait"):
        bridge.validate_terminal_execution_receipt(_receipt(current_plan), current_plan)


@pytest.mark.parametrize(
    "path, value, message",
    [
        (("plan_digest",), "f" * 64, "plan_digest"),
        (("execution_observation", "synthetic"), True, "synthetic"),
        (("execution_observation", "wait_returncode"), 1, "wait_returncode"),
        (("execution_observation", "command_sha256"), "e" * 64, "command_sha256"),
        (("runtime_verifier_binding", "direct_current_manifest_admission"), True, "direct_current_manifest_admission"),
        (("terminal_artifact_identity", "hdf5_validator", "independent"), False, "independent"),
        (("terminal_artifact_identity", "hdf5_validator", "trajectory_frames"), bridge.FRAMES - 1, "trajectory_frames"),
    ],
)
def test_receipt_drift_is_fail_closed(current_plan: bridge.BridgePlan, path, value, message: str) -> None:
    payload = _receipt(current_plan)
    target: object = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises((bridge.BridgeError, bridge.identity.IdentityError), match=message):
        bridge.validate_terminal_execution_receipt(payload, current_plan)


def test_unknown_receipt_fields_fail_closed(current_plan: bridge.BridgePlan) -> None:
    payload = _receipt(current_plan)
    payload["unexpected"] = True
    with pytest.raises(bridge.BridgeError, match="unknown fields"):
        bridge.validate_terminal_execution_receipt(payload, current_plan)


def test_missing_source_report_is_zero_credit_and_valid(tmp_path: Path) -> None:
    missing = {seed: tmp_path / f"missing-{seed}.json" for seed in bridge.SEEDS}
    report = bridge.build_report(
        bridge.LAB_ROOT,
        training_receipts=missing,
        checkpoints={seed: tmp_path / f"missing-{seed}.pt" for seed in bridge.SEEDS},
        nonces={17: "1" * 32, 29: "2" * 32, 43: "3" * 32},
        output_root=tmp_path,
        gpu_rows={gpu: {"total_mib": 49140, "used_mib": 1000, "free_mib": 48140} for gpu in (4, 5, 6)},
        cpu_count=128,
        load_1m=1.0,
        tmp_free_bytes=100 * 1024**3,
        root_free_bytes=100 * 1024**3,
    )
    assert report["source_bound"] is False
    assert report["launch_allowed"] is False
    assert report["process_proofs_verified"] == 0
    assert bridge.validate_report(report) == []


def test_current_source_report_remains_dry_run_only(tmp_path: Path) -> None:
    required = [bridge.DEFAULT_MANIFEST, *bridge.DEFAULT_RECEIPTS.values(), *bridge.DEFAULT_CHECKPOINTS.values()]
    if not all(path.exists() for path in required):
        pytest.skip("current diagnostic residual receipts are not present")
    report = bridge.build_report(
        bridge.LAB_ROOT,
        nonces={17: "4" * 32, 29: "5" * 32, 43: "6" * 32},
        output_root=tmp_path,
        gpu_rows={gpu: {"total_mib": 49140, "used_mib": 1000, "free_mib": 48140} for gpu in (4, 5, 6)},
        cpu_count=128,
        load_1m=1.0,
        tmp_free_bytes=100 * 1024**3,
        root_free_bytes=100 * 1024**3,
    )
    assert report["source_bound"] is True
    assert report["terminal_source_bound"] is False
    assert report["launch_allowed"] is False
    assert report["side_effects"]["processes_started"] == 0
    assert bridge.validate_report(report) == []
    assert all(not Path(row["namespace"]).exists() for row in report["seed_rows"])


def test_report_validator_rejects_forged_counts(tmp_path: Path) -> None:
    report = bridge.build_report(
        bridge.LAB_ROOT,
        training_receipts={seed: tmp_path / f"missing-{seed}.json" for seed in bridge.SEEDS},
        checkpoints={seed: tmp_path / f"missing-{seed}.pt" for seed in bridge.SEEDS},
        nonces={17: "7" * 32, 29: "8" * 32, 43: "9" * 32},
        output_root=tmp_path,
        gpu_rows={gpu: {"total_mib": 49140, "used_mib": 1000, "free_mib": 48140} for gpu in (4, 5, 6)},
        cpu_count=128,
        load_1m=1.0,
        tmp_free_bytes=100 * 1024**3,
        root_free_bytes=100 * 1024**3,
    )
    forged = deepcopy(report)
    forged["launch_allowed"] = True
    assert bridge.validate_report(forged)
    forged = deepcopy(report)
    forged["process_proofs_verified"] = 1
    assert bridge.validate_report(forged)


def test_cli_verify_report_remains_fail_closed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    report = bridge.build_report(
        bridge.LAB_ROOT,
        training_receipts={seed: tmp_path / f"missing-{seed}.json" for seed in bridge.SEEDS},
        checkpoints={seed: tmp_path / f"missing-{seed}.pt" for seed in bridge.SEEDS},
        nonces={17: "a" * 32, 29: "b" * 32, 43: "c" * 32},
        output_root=tmp_path,
        gpu_rows={gpu: {"total_mib": 49140, "used_mib": 1000, "free_mib": 48140} for gpu in (4, 5, 6)},
        cpu_count=128,
        load_1m=1.0,
        tmp_free_bytes=100 * 1024**3,
        root_free_bytes=100 * 1024**3,
    )
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    assert bridge.main(["--verify-report", str(report_path)]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True
