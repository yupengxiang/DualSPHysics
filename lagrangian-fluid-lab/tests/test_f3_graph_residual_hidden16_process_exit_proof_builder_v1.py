"""Residual process-proof hardening tests.

All artifacts are temporary synthetic files. No Popen, evaluator, worker,
GPU, or queue is started.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import h5py
import pytest

from scripts import f3_graph_residual_hidden16_process_exit_proof_builder_v1 as builder


def _attestation(path: Path, digest: str, byte_count: int) -> dict[str, object]:
    producer = {
        "role": "producer",
        "identity": f"producer:{path.name}",
        "source": "producer_receipt",
        "independent": False,
        "artifact_path": str(path),
        "artifact_sha256": digest,
        "artifact_bytes": byte_count,
    }
    producer["binding_sha256"] = builder._canonical_digest(producer)
    validator = {
        "role": "validator",
        "identity": f"validator:{path.name}",
        "source": "independent_validator_receipt",
        "independent": True,
        "artifact_path": str(path),
        "artifact_sha256": digest,
        "artifact_bytes": byte_count,
    }
    validator["binding_sha256"] = builder._canonical_digest(validator)
    outer = {
        "schema": builder.ARTIFACT_ATTESTATION_SCHEMA,
        "mode": builder.ARTIFACT_ATTESTATION_MODE,
        "artifact_path": str(path),
        "artifact_sha256": digest,
        "artifact_bytes": byte_count,
        "producer_binding_sha256": producer["binding_sha256"],
        "validator_binding_sha256": validator["binding_sha256"],
        "producer": producer,
        "validator": validator,
    }
    outer["binding_sha256"] = builder._canonical_digest(
        {
            key: outer[key]
            for key in (
                "schema",
                "mode",
                "artifact_path",
                "artifact_sha256",
                "artifact_bytes",
                "producer_binding_sha256",
                "validator_binding_sha256",
            )
        }
    )
    return outer


def _write_artifact(path: Path, content: bytes, *, hdf5: bool = False) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if hdf5:
        with h5py.File(path, "w") as handle:
            handle.create_dataset("positions", data=[0.0, 1.0])
        content = path.read_bytes()
    else:
        path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    return {
        "path": str(path),
        "sha256": digest,
        "bytes": len(content),
        "content_opened": False,
        "stat_only": True,
        "attestation": _attestation(path, digest, len(content)),
    }


def _observation(root: Path, *, seed: int = 17, nonce: str = "17" * 16) -> dict[str, object]:
    artifacts = root / "artifacts"
    run_id = f"f3-graph-residual500-hidden16-seed{seed}-20260928"
    namespace = artifacts / f"f3-graph-residual500-hidden16-seed{seed}-full835-nonce{nonce}"
    checkpoint = _write_artifact(artifacts / f"{run_id}-checkpoint.pt", b"checkpoint")
    training = _write_artifact(artifacts / f"{run_id}-training.json", b"training")
    trajectory = _write_artifact(Path(str(namespace) + "-trajectory.h5"), b"unused", hdf5=True)
    evaluation = _write_artifact(Path(str(namespace) + "-evaluation.json"), b"evaluation")
    evaluator_command = [
        builder.CANONICAL_INTERPRETER,
        builder.CANONICAL_CORE_LEARNING,
        "evaluate",
        "--manifest",
        "campaigns/core-v1/f3-dataset-v2.json",
        "--data-root",
        ".",
        "--checkpoint",
        checkpoint["path"],
        "--case-id",
        builder.CASE_ID,
        "--split",
        builder.SPLIT,
        "--maximum-steps",
        str(builder.TRANSITIONS),
        "--chunk-size",
        "34560",
        "--device",
        "cuda:0",
        "--progress-every",
        "25",
        "--trajectory-output",
        trajectory["path"],
        "--progress-output",
        str(namespace) + "-evaluation-progress.json",
        "--output",
        evaluation["path"],
        "--diagnostic",
    ]
    launcher_command = ["/usr/bin/env", "PYTHONDONTWRITEBYTECODE=1", *evaluator_command]
    command_binding = builder._command_binding(
        evaluator=evaluator_command,
        evaluator_sha256=builder._command_sha256(evaluator_command),
        launcher=launcher_command,
        launcher_sha256=builder._command_sha256(launcher_command),
        manifest_sha256=builder._sha("dataset-v2-manifest") if hasattr(builder, "_sha") else hashlib.sha256(b"dataset-v2-manifest").hexdigest(),
    )
    checkpoint_normalized = {**checkpoint, "snapshot_verified": True}
    plan_binding = {
        "schema": builder.PROCESS_PLAN_BINDING_SCHEMA,
        "seed": seed,
        "run_id": run_id,
        "namespace": str(namespace),
        "namespace_nonce": nonce,
        "manifest_sha256": hashlib.sha256(b"dataset-v2-manifest").hexdigest(),
        "training_receipt_sha256": training["sha256"],
        "checkpoint": checkpoint_normalized,
        "command_binding": command_binding,
        "cwd": builder.EXPECTED_CWD,
        "env": dict(builder.EXPECTED_ENV),
    }
    plan_digest = builder._canonical_digest(plan_binding)
    process_binding_payload = {
        **plan_binding,
        "evaluator_command_sha256": builder._command_sha256(evaluator_command),
        "launcher_command_sha256": builder._command_sha256(launcher_command),
    }
    process_binding = {
        **process_binding_payload,
        "binding_sha256": builder._canonical_digest(process_binding_payload),
    }
    lifecycle_payload = {
        "schema": builder.SEALED_LIFECYCLE_SCHEMA,
        "producer": "audited_runtime_sealed_witness",
        "sealed": True,
        "evaluator_popen_called": True,
        "evaluator_wait_called": True,
        "launcher_popen_called": True,
        "launcher_wait_called": True,
        "evaluator_returncode": 0,
        "launcher_returncode": 0,
        "natural_exit": True,
        "plan_digest": plan_digest,
        "manifest_sha256": plan_binding["manifest_sha256"],
        "training_receipt_sha256": training["sha256"],
        "checkpoint": checkpoint_normalized,
        "namespace": str(namespace),
        "namespace_nonce": nonce,
        "evaluator_command_sha256": process_binding_payload["evaluator_command_sha256"],
        "launcher_command_sha256": process_binding_payload["launcher_command_sha256"],
        "cwd": builder.EXPECTED_CWD,
        "env": dict(builder.EXPECTED_ENV),
    }
    lifecycle = {
        **{key: lifecycle_payload[key] for key in builder.SEALED_LIFECYCLE_KEYS if key != "binding_sha256"},
        "binding_sha256": builder._canonical_digest(lifecycle_payload),
    }
    return {
        "schema": builder.INPUT_SCHEMA,
        "report_id": builder.INPUT_REPORT_ID,
        "status": "post_terminal_observed",
        "seed": seed,
        "run_id": run_id,
        "namespace": str(namespace),
        "namespace_nonce": nonce,
        "model_kind": builder.MODEL_KIND,
        "hidden": builder.HIDDEN,
        "updates": builder.UPDATES,
        "case_id": builder.CASE_ID,
        "split": builder.SPLIT,
        "transitions": builder.TRANSITIONS,
        "frames": builder.FRAMES,
        "manifest_sha256": plan_binding["manifest_sha256"],
        "training_receipt": training,
        "checkpoint": checkpoint,
        "trajectory": trajectory,
        "evaluation_artifact": evaluation,
        "process": {
            "binding": process_binding,
            "sealed_lifecycle": lifecycle,
            "evaluator": {
                "alive": False,
                "returncode": 0,
                "reaped": True,
                "cwd": builder.EXPECTED_CWD,
                "env": dict(builder.EXPECTED_ENV),
                "command": evaluator_command,
                "command_sha256": builder._command_sha256(evaluator_command),
            },
            "launcher": {
                "alive": False,
                "returncode": 0,
                "reaped": True,
                "cwd": builder.EXPECTED_CWD,
                "env": dict(builder.EXPECTED_ENV),
                "command": launcher_command,
                "command_sha256": builder._command_sha256(launcher_command),
            },
        },
        "exit_observation": {"natural_exit": True, "observed_after_exit": True},
    }


def test_complete_json_proof_is_rejected_without_a_real_sealed_witness(tmp_path: Path) -> None:
    with pytest.raises(builder.BuilderError, match="declaration-only|sealed real Popen/wait"):
        builder.build_envelope(_observation(tmp_path))


def test_unknown_fields_fail_closed(tmp_path: Path) -> None:
    payload = _observation(tmp_path)
    payload["process"]["unexpected"] = True  # type: ignore[index]
    with pytest.raises(builder.BuilderError, match="unknown field"):
        builder.build_envelope(payload)


@pytest.mark.parametrize(
    ("component", "field", "value"),
    [("evaluator", "alive", True), ("evaluator", "returncode", 1), ("launcher", "reaped", False)],
)
def test_nonterminal_process_observations_fail_closed(tmp_path: Path, component: str, field: str, value: object) -> None:
    payload = _observation(tmp_path)
    payload["process"][component][field] = value  # type: ignore[index]
    with pytest.raises(builder.BuilderError):
        builder.build_envelope(payload)


def test_namespace_nonce_and_command_identity_are_bound(tmp_path: Path) -> None:
    payload = _observation(tmp_path)
    payload["namespace_nonce"] = "0" * 32
    with pytest.raises(builder.BuilderError, match="non-zero"):
        builder.build_envelope(payload)

    payload = _observation(tmp_path / "second")
    payload["process"]["evaluator"]["command"][12] = "834"  # type: ignore[index]
    payload["process"]["evaluator"]["command_sha256"] = builder._command_sha256(payload["process"]["evaluator"]["command"])  # type: ignore[index]
    with pytest.raises(builder.BuilderError, match="canonical evaluator argv|token/flag/path drift"):
        builder.build_envelope(payload)


@pytest.mark.parametrize("artifact_key", ["checkpoint", "trajectory", "evaluation_artifact", "training_receipt"])
def test_symlink_and_hardlink_artifacts_are_rejected(tmp_path: Path, artifact_key: str) -> None:
    payload = _observation(tmp_path)
    original = Path(payload[artifact_key]["path"])  # type: ignore[index]
    if artifact_key == "trajectory":
        target = tmp_path / "symlink-target.h5"
        target.write_bytes(original.read_bytes())
        original.unlink()
        original.symlink_to(target)
    else:
        os.link(original, tmp_path / f"{artifact_key}-hardlink.bin")
    with pytest.raises(builder.BuilderError, match="symbolic|symlink|hard link"):
        builder.build_envelope(payload)


def test_observation_reader_rejects_symlink_hardlink_and_traversal(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    real = root / "post_terminal_observation.json"
    real.write_text(builder.canonical_json({"schema": builder.INPUT_SCHEMA}), encoding="utf-8")
    assert builder.load_observation(root, real)["schema"] == builder.INPUT_SCHEMA
    link = root / "observation-link.json"
    link.symlink_to(real)
    with pytest.raises(builder.BuilderError, match="symlink"):
        builder.load_observation(root, link)
    hardlink = root / "observation-hardlink.json"
    os.link(real, hardlink)
    with pytest.raises(builder.BuilderError, match="hard-linked"):
        builder.load_observation(root, hardlink)
    with pytest.raises(builder.BuilderError, match="traversal|escapes"):
        builder.load_observation(root, Path("../post_terminal_observation.json"))


def test_hdf5_external_soft_vds_and_external_storage_are_rejected(tmp_path: Path) -> None:
    variants: list[Path] = []
    soft = tmp_path / "soft.h5"
    with h5py.File(soft, "w") as handle:
        handle["bad"] = h5py.SoftLink("/missing")
    variants.append(soft)
    external = tmp_path / "external.h5"
    with h5py.File(external, "w") as handle:
        handle["bad"] = h5py.ExternalLink("outside.h5", "/data")
    variants.append(external)
    for path in variants:
        raw = path.read_bytes()
        with pytest.raises((builder.BuilderError, builder.residual_identity.IdentityError), match="physical-link|non-hard"):
            builder.residual_identity.read_bound_artifact(
                path,
                expected_sha256=hashlib.sha256(raw).hexdigest(),
                expected_bytes=len(raw),
                name=path.name,
                hdf5=True,
            )


def test_attestation_unknown_fields_fail_closed(tmp_path: Path) -> None:
    payload = _observation(tmp_path)
    payload["checkpoint"]["attestation"]["unexpected"] = True  # type: ignore[index]
    with pytest.raises(builder.BuilderError, match="unknown field"):
        builder.build_envelope(payload)


def test_default_report_is_blocked_and_zero_credit(tmp_path: Path) -> None:
    report = builder.build_default_blocked_report()
    assert report["status"] == "blocked_fail_closed"
    assert report["process_exit_proof"] is None
    assert report["credit"] == 0
    assert builder.validate_blocked_report(report) == []
    root = tmp_path / "root"
    (root / "reports").mkdir(parents=True)
    output = builder.write_default_blocked_report(root)
    assert builder.validate_blocked_report(json.loads(output.read_text(encoding="utf-8"))) == []
