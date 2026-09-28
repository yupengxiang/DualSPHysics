"""Fail-closed tests for the graph_raw terminal execution bridge."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys

import pytest

from scripts import f3_graph_raw_hidden16_current_manifest_terminal_artifact_validator_v1 as synthetic_validator
from scripts import f3_graph_raw_hidden16_current_manifest_terminal_execution_bridge_v1 as bridge


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_json(path: Path, value: object) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    path.write_bytes(raw)
    return raw


def _admission(gpu: int = 5, *, admitted: bool = True) -> dict[str, object]:
    return bridge.executor.probe_resource_admission(
        gpu,
        gpu_rows={
            gpu: {
                "total_mib": 49140,
                "used_mib": 1000 if admitted else 48000,
                "free_mib": 48140 if admitted else 1140,
            }
        },
        cpu_count=128 if admitted else 1,
        load_1m=1.0 if admitted else 999.0,
        tmp_free_bytes=100 * 1024**3 if admitted else 1,
        root_free_bytes=100 * 1024**3 if admitted else 1,
    )


def _fixture_set(tmp_path: Path) -> dict[str, object]:
    root = tmp_path / "lab"
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "reports").mkdir()
    (root / "campaigns" / "core-v1").mkdir(parents=True)

    python = root / ".venv" / "bin" / "python"
    python.write_bytes(Path(sys.executable).resolve().read_bytes())
    python.chmod(0o755)
    (root / "scripts" / "core_learning.py").write_text(
        "raise SystemExit(0)\n", encoding="utf-8"
    )
    manifest_payload = {
        "schema": bridge.executor.identity.MANIFEST_SCHEMA,
        "case_count": 32,
        "dataset_id": "F3_registered32_core_native_v2",
        "formal_release": False,
        "source_manifest_sha256": "b" * 64,
    }
    manifest = root / "campaigns" / "core-v1" / "f3-dataset-v2.json"
    _write_json(manifest, manifest_payload)
    manifest_sha = bridge.executor.identity.canonical_digest(manifest_payload)

    receipts: dict[int, Path] = {}
    checkpoints: dict[int, Path] = {}
    for seed in bridge.SEEDS:
        checkpoint = root / "inputs" / (
            f"f3-graph_raw500-hidden16-currentmanifest-seed{seed}-20260929-v3-checkpoint.pt"
        )
        checkpoint_raw = f"checkpoint-{seed}".encode()
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_bytes(checkpoint_raw)
        checkpoint_meta = {
            "schema": bridge.executor.identity.CHECKPOINT_SCHEMA,
            "path": str(checkpoint),
            "sha256": _sha_bytes(checkpoint_raw),
            "bytes": len(checkpoint_raw),
            "update": bridge.UPDATES,
        }
        run_id = f"f3-graph_raw500-hidden16-currentmanifest-seed{seed}-20260929-v3"
        receipt = tmp_path / (
            f"f3-graph_raw500-hidden16-currentmanifest-seed{seed}-20260929-v3-training.json"
        )
        receipt_payload = {
            "schema": bridge.executor.identity.TRAINING_SCHEMA,
            "evidence_status": "complete",
            "model_kind": bridge.MODEL,
            "seed": seed,
            "run_id": run_id,
            "completed_updates": bridge.UPDATES,
            "checkpoint_verified": True,
            "checkpoint": checkpoint_meta,
            "checkpoints": [checkpoint_meta],
            "config": {
                "manifest_sha256": manifest_sha,
                "model_kind": bridge.MODEL,
                "hidden": bridge.HIDDEN,
                "updates": bridge.UPDATES,
                "run_id": run_id,
                "seed": seed,
                "manifest_formal_release": False,
                "validation_formal_eligible": False,
            },
            **bridge.executor.ZERO_CREDIT,
        }
        _write_json(receipt, receipt_payload)
        receipts[seed] = receipt
        checkpoints[seed] = checkpoint
    return {
        "root": root,
        "manifest": manifest,
        "receipts": receipts,
        "checkpoints": checkpoints,
    }


def _plan(tmp_path: Path, *, seed: int = 17) -> tuple[dict[str, object], bridge.BridgePlan]:
    fixture = _fixture_set(tmp_path)
    nonce = "a" * 32
    output_root = tmp_path / "bridge-output"
    output_root.mkdir()
    namespace = output_root / (
        f"f3-graph_raw500-hidden16-currentmanifest-seed{seed}-full835-nonce{nonce}"
    )
    plan = bridge.build_bridge_plan(
        fixture["root"],
        seed=seed,
        manifest=fixture["manifest"],
        training_receipt=fixture["receipts"][seed],
        checkpoint=fixture["checkpoints"][seed],
        nonce=nonce,
        output_namespace=namespace,
        gpu_index=5,
        admission=_admission(),
    )
    return fixture, plan


def _production_shaped_attestation(plan: bridge.BridgePlan) -> dict[str, object]:
    artifacts: dict[str, dict[str, object]] = {}
    payloads = {
        "trajectory": b"real-read-only-trajectory-bytes\n",
        "evaluation": b'{"status":"completed"}\n',
        "progress": b'{"frames":836}\n',
    }
    for name, payload in payloads.items():
        path = plan.outputs[name]
        path.write_bytes(payload)
        artifacts[name] = {
            "path": str(path),
            "sha256": _sha_bytes(payload),
            "bytes": len(payload),
        }
    core: dict[str, object] = {
        "schema": bridge.TERMINAL_ATTESTATION_SCHEMA,
        "status": "validated_real_evaluator_artifacts",
        "validator_id": "independent-production-hdf5-validator-v1",
        "validator_version": "bounded-read-only-v1",
        "independent_validator": True,
        "production_artifact_opened": True,
        "synthetic_only": False,
        "real_producer_proof": True,
        "real_terminal_proof": True,
        "model_kind": bridge.MODEL,
        "hidden": bridge.HIDDEN,
        "seed": plan.audited_plan.identity_plan.seed,
        "case_id": bridge.CASE_ID,
        "split": bridge.SPLIT,
        "transitions": bridge.TRANSITIONS,
        "frames": bridge.FRAMES,
        "namespace": str(plan.namespace),
        "namespace_nonce": plan.audited_plan.identity_plan.nonce,
        "manifest_sha256": plan.audited_plan.identity_plan.manifest_sha256,
        "training_receipt_sha256": plan.audited_plan.identity_plan.training_receipt_sha256,
        "checkpoint_sha256": plan.audited_plan.identity_plan.checkpoint["sha256"],
        "audited_plan_digest": plan.audited_plan.audited_plan_digest,
        "command_sha256": plan.audited_plan.exact_command_digest,
        "artifacts": artifacts,
        "hdf5_binding": {
            "path": artifacts["trajectory"]["path"],
            "sha256": artifacts["trajectory"]["sha256"],
            "bytes": artifacts["trajectory"]["bytes"],
            "transitions": bridge.TRANSITIONS,
            "frames": bridge.FRAMES,
            "nonce": plan.audited_plan.identity_plan.nonce,
            "case_id": bridge.CASE_ID,
        },
    }
    return {**core, "validator_attestation_sha256": bridge.canonical_digest(core)}


def test_build_bridge_plan_is_fresh_and_non_authorizing(tmp_path: Path) -> None:
    _fixture, plan = _plan(tmp_path)

    assert plan.namespace.exists() is False
    assert plan.audited_plan.identity_plan.launch_allowed is False
    assert plan.as_dict()["launch_allowed"] is False
    assert plan.as_dict()["production_validator_capability_admitted"] is False
    assert plan.audited_plan.exact_command_digest
    assert plan.bridge_plan_digest


def test_default_report_is_blocked_zero_credit_and_has_no_side_effects(tmp_path: Path) -> None:
    fixture = _fixture_set(tmp_path)
    report = bridge.build_report(
        fixture["root"],
        manifest=fixture["manifest"],
        training_receipts=fixture["receipts"],
        checkpoints=fixture["checkpoints"],
        nonces={17: "1" * 32, 29: "2" * 32, 43: "3" * 32},
        gpu_indices={17: 4, 29: 5, 43: 6},
        output_root=tmp_path / "bridge-output",
        gpu_rows={
            4: {"total_mib": 49140, "used_mib": 1000, "free_mib": 48140},
            5: {"total_mib": 49140, "used_mib": 1000, "free_mib": 48140},
            6: {"total_mib": 49140, "used_mib": 1000, "free_mib": 48140},
        },
        cpu_count=128,
        load_1m=1.0,
        tmp_free_bytes=100 * 1024**3,
        root_free_bytes=100 * 1024**3,
    )

    assert bridge.validate_report(report) == []
    assert report["status"] == "blocked_fail_closed"
    assert report["launch_allowed"] is False
    assert report["popen_attempts"] == 0
    assert report["process_evidence_verified"] == 0
    assert report["terminal_evidence_verified"] == 0
    assert report["credit"] == 0
    assert report["side_effects"]["processes_stopped"] == 0
    assert report["side_effects"]["processes_restarted"] == 0
    assert report["side_effects"]["registry_writes"] == 0
    assert report["side_effects"]["ledger_writes"] == 0
    assert report["side_effects"]["plan_writes"] == 0


def test_explicit_execute_rejects_before_fake_popen(tmp_path: Path) -> None:
    _fixture, plan = _plan(tmp_path)
    calls: list[tuple[object, ...]] = []

    def fake_popen(*args: object, **kwargs: object) -> object:
        calls.append(args)
        raise AssertionError("fake Popen must never be called")

    with pytest.raises(bridge.BridgeError, match="fake/injectable Popen"):
        bridge.execute_diagnostic_one_shot(
            plan,
            popen_factory=fake_popen,
            admission_probe=lambda _gpu: _admission(),
        )
    assert calls == []
    assert not plan.namespace.exists()


def test_real_popen_entry_is_blocked_by_unadmitted_synthetic_validator(
    tmp_path: Path,
) -> None:
    _fixture, plan = _plan(tmp_path)

    with pytest.raises(bridge.BridgeError, match="synthetic-only.*Popen was not attempted"):
        bridge.execute_diagnostic_one_shot(
            plan,
            popen_factory=bridge.subprocess.Popen,
            admission_probe=lambda _gpu: _admission(),
        )
    assert not plan.namespace.exists()
    assert not plan.outputs["log"].exists()


def test_resource_readmission_blocks_before_fake_popen(tmp_path: Path) -> None:
    _fixture, plan = _plan(tmp_path)
    calls: list[object] = []

    def fake_popen(*args: object, **kwargs: object) -> object:
        calls.append(args)
        raise AssertionError("Popen must not be called after resource failure")

    with pytest.raises(bridge.executor.ExecutorError, match="resource admission"):
        bridge.execute_diagnostic_one_shot(
            plan,
            popen_factory=fake_popen,
            admission_probe=lambda _gpu: _admission(admitted=False),
        )
    assert calls == []


def test_input_identity_drift_blocks_before_fake_popen(tmp_path: Path) -> None:
    fixture, plan = _plan(tmp_path)
    receipt = fixture["receipts"][17]
    receipt.write_bytes(receipt.read_bytes() + b"drift")
    calls: list[object] = []

    def fake_popen(*args: object, **kwargs: object) -> object:
        calls.append(args)
        raise AssertionError("Popen must not be called after identity drift")

    with pytest.raises(bridge.executor.ExecutorError, match="training_receipt changed"):
        bridge.execute_diagnostic_one_shot(
            plan,
            popen_factory=fake_popen,
            admission_probe=lambda _gpu: _admission(),
        )
    assert calls == []


def test_existing_namespace_is_rejected_and_not_reused(tmp_path: Path) -> None:
    _fixture, plan = _plan(tmp_path)
    plan.namespace.mkdir()
    with pytest.raises(bridge.executor.ExecutorError, match="output namespace"):
        bridge.execute_diagnostic_one_shot(
            plan,
            popen_factory=lambda *args, **kwargs: pytest.fail("Popen must not run"),
            admission_probe=lambda _gpu: _admission(),
        )


def test_synthetic_validator_report_cannot_be_terminal_attestation(
    tmp_path: Path,
) -> None:
    _fixture, plan = _plan(tmp_path)
    synthetic = synthetic_validator.build_report()
    with pytest.raises(bridge.BridgeError, match="unsupported keys"):
        bridge.validate_terminal_attestation(plan, synthetic)


def test_production_shaped_attestation_binds_artifacts_but_cannot_mint_evidence(
    tmp_path: Path,
) -> None:
    _fixture, plan = _plan(tmp_path)
    attestation = _production_shaped_attestation(plan)
    normalized = bridge.validate_terminal_attestation(plan, attestation)
    assert normalized["hdf5_binding"]["transitions"] == bridge.TRANSITIONS
    assert normalized["hdf5_binding"]["frames"] == bridge.FRAMES
    assert normalized["hdf5_binding"]["nonce"] == plan.audited_plan.identity_plan.nonce
    assert normalized["hdf5_binding"]["case_id"] == bridge.CASE_ID

    forged_process = {
        "schema": bridge.PROCESS_EVIDENCE_SCHEMA,
        "status": "natural_exit_verified",
        "model": bridge.MODEL,
        "seed": plan.audited_plan.identity_plan.seed,
        "namespace": str(plan.namespace),
        "namespace_nonce": plan.audited_plan.identity_plan.nonce,
        "audited_plan_digest": plan.audited_plan.audited_plan_digest,
        "command": list(plan.audited_plan.identity_plan.command),
        "command_sha256": plan.audited_plan.exact_command_digest,
        "cwd": str(plan.audited_plan.identity_plan.root),
        "env_overrides": dict(plan.audited_plan.identity_plan.env),
        "evaluator_pid": 12345,
        "evaluator_returncode": 0,
        "wait_returncode": 0,
        "wait_observed": True,
        "real_popen_type": True,
        "diagnostic_only": True,
        "credit": 0,
    }
    with pytest.raises(bridge.BridgeError, match="capability is not admitted"):
        bridge.build_diagnostic_evidence(plan, forged_process, normalized)


def test_attestation_digest_and_hdf5_identity_mutations_fail_closed(tmp_path: Path) -> None:
    _fixture, plan = _plan(tmp_path)
    attestation = _production_shaped_attestation(plan)

    wrong_sha = copy.deepcopy(attestation)
    wrong_sha["artifacts"]["trajectory"]["sha256"] = "a" * 64
    with pytest.raises(bridge.BridgeError, match="placeholder|sha256"):
        bridge.validate_terminal_attestation(plan, wrong_sha)

    wrong_frames = copy.deepcopy(attestation)
    wrong_frames["hdf5_binding"]["frames"] = bridge.FRAMES - 1
    wrong_frames["validator_attestation_sha256"] = bridge.canonical_digest(
        {key: value for key, value in wrong_frames.items() if key != "validator_attestation_sha256"}
    )
    with pytest.raises(bridge.BridgeError, match="frames must be"):
        bridge.validate_terminal_attestation(plan, wrong_frames)

    wrong_nonce = copy.deepcopy(attestation)
    wrong_nonce["hdf5_binding"]["nonce"] = "b" * 32
    wrong_nonce["validator_attestation_sha256"] = bridge.canonical_digest(
        {key: value for key, value in wrong_nonce.items() if key != "validator_attestation_sha256"}
    )
    with pytest.raises(bridge.BridgeError, match="nonce must be"):
        bridge.validate_terminal_attestation(plan, wrong_nonce)
