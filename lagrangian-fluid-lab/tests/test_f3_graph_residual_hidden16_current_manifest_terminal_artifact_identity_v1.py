"""Residual terminal identity P1 hardening tests.

These tests use only temporary synthetic files. They never call Popen, start
an evaluator, touch a GPU, or read a production trajectory.
"""

from __future__ import annotations

import hashlib
import inspect
import os
from pathlib import Path

import h5py
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


def _write_outputs(plan) -> tuple[dict[str, object], dict[str, object]]:
    evaluation_path = plan.outputs["evaluation"]
    evaluation_path.write_bytes(b'{"diagnostic":true}\n')
    evaluation_bytes = evaluation_path.read_bytes()

    trajectory_path = plan.outputs["trajectory"]
    with h5py.File(trajectory_path, "w") as handle:
        handle.create_dataset("positions", data=[0.0, 1.0])
    trajectory_bytes = trajectory_path.read_bytes()

    def artifact(path: Path, raw: bytes) -> dict[str, object]:
        return {
            "path": str(path),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        }

    return artifact(evaluation_path, evaluation_bytes), artifact(trajectory_path, trajectory_bytes)


def _sealed_lifecycle(plan, checkpoint: dict[str, object]) -> dict[str, object]:
    binding = {
        "schema": identity.SEALED_LIFECYCLE_SCHEMA,
        "producer": "audited_runtime_sealed_witness",
        "sealed": True,
        "popen_called": True,
        "wait_called": True,
        "wait_returncode": 0,
        "reaped": True,
        "natural_exit": True,
        "argv": list(plan.base.command),
        "cwd": str(plan.base.cwd),
        "env": dict(plan.base.env),
        "plan_digest": plan.plan_digest,
        "manifest_sha256": plan.base.manifest_binding["canonical_sha256"],
        "training_receipt_sha256": plan.base.training_binding["sha256"],
        "checkpoint": checkpoint,
        "namespace": str(plan.namespace),
        "namespace_nonce": plan.nonce,
    }
    return {
        **{key: binding[key] for key in ("schema", "producer", "sealed", "popen_called", "wait_called", "wait_returncode", "reaped", "natural_exit", "argv", "cwd", "env")},
        "binding_sha256": identity.canonical_digest(binding),
    }


def _terminal_evidence(plan) -> dict[str, object]:
    evaluation, trajectory = _write_outputs(plan)
    checkpoint = {key: plan.base.checkpoint[key] for key in ("path", "sha256", "bytes")}
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
        "plan_digest": plan.plan_digest,
        "manifest_sha256": plan.base.manifest_binding["canonical_sha256"],
        "training_receipt_sha256": plan.base.training_binding["sha256"],
        "checkpoint": {**checkpoint, "schema": identity.launcher.CHECKPOINT_SCHEMA, "update": identity.UPDATES},
        "command_sha256": plan.base.command_sha256,
        "process_proof": {
            "schema": identity.PROCESS_PROOF_SCHEMA,
            "producer": "subprocess.Popen",
            "evidence_kind": "runtime_process_observation",
            "synthetic": False,
            "popen_called": True,
            "wait_called": True,
            "wait_returncode": 0,
            "exit_status_verified": True,
            "plan_digest": plan.plan_digest,
            "manifest_sha256": plan.base.manifest_binding["canonical_sha256"],
            "training_receipt_sha256": plan.base.training_binding["sha256"],
            "checkpoint": checkpoint,
            "namespace": str(plan.namespace),
            "namespace_nonce": plan.nonce,
            "command_sha256": plan.base.command_sha256,
            "cwd": str(plan.base.cwd),
            "env": dict(plan.base.env),
            "argv": list(plan.base.command),
            "sealed_lifecycle": _sealed_lifecycle(plan, checkpoint),
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


def test_plan_digest_binds_sources_namespace_and_environment(current_plan) -> None:
    assert current_plan.plan_digest == identity._plan_digest(
        current_plan.base, current_plan.gpu_index, current_plan.admission
    )
    assert current_plan.base.manifest_binding["canonical_sha256"]
    assert current_plan.base.training_binding["sha256"]
    assert current_plan.base.checkpoint["sha256"]
    assert current_plan.base.env == {"CUDA_VISIBLE_DEVICES": "4", "PYTHONDONTWRITEBYTECODE": "1"}
    assert not current_plan.namespace.exists()


def test_complete_json_process_proof_is_rejected_without_sealed_runtime_witness(current_plan) -> None:
    with pytest.raises(identity.IdentityError, match="declaration-only|sealed real Popen/wait"):
        identity.validate_terminal_artifact_identity(_terminal_evidence(current_plan), current_plan)


def test_unknown_process_fields_fail_closed(current_plan) -> None:
    evidence = _terminal_evidence(current_plan)
    evidence["process_proof"]["unexpected"] = True  # type: ignore[index]
    with pytest.raises(identity.IdentityError, match="unknown fields"):
        identity.validate_terminal_artifact_identity(evidence, current_plan)


def test_nonce_and_command_drift_fail_closed(current_plan) -> None:
    evidence = _terminal_evidence(current_plan)
    evidence["namespace_nonce"] = "b" * 32
    with pytest.raises(identity.IdentityError, match="namespace_nonce"):
        identity.validate_terminal_artifact_identity(evidence, current_plan)

    evidence = _terminal_evidence(current_plan)
    evidence["process_proof"]["command_sha256"] = "1" * 64  # type: ignore[index]
    with pytest.raises(identity.IdentityError, match="command_sha256"):
        identity.validate_terminal_artifact_identity(evidence, current_plan)


def test_hdf5_artifact_identity_is_verified_from_one_stable_descriptor(current_plan) -> None:
    _evaluation, trajectory = _write_outputs(current_plan)
    result = identity.read_bound_artifact(
        trajectory["path"],
        expected_sha256=trajectory["sha256"],  # type: ignore[arg-type]
        expected_bytes=trajectory["bytes"],  # type: ignore[arg-type]
        name="synthetic.trajectory",
        hdf5=True,
    )
    assert result["sha256"] == trajectory["sha256"]
    assert result["bytes"] == trajectory["bytes"]
    assert result["hdf5"]["virtual_datasets_rejected"] is True  # type: ignore[index]
    assert result["identity"]["st_nlink"] == 1  # type: ignore[index]


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "parent_symlink"])
def test_artifact_path_links_are_rejected(tmp_path: Path, kind: str) -> None:
    root = tmp_path / "root"
    root.mkdir()
    real = root / "artifact.bin"
    raw = b"stable-artifact"
    real.write_bytes(raw)
    if kind == "symlink":
        candidate = root / "link.bin"
        candidate.symlink_to(real)
    elif kind == "hardlink":
        candidate = root / "hardlink.bin"
        os.link(real, candidate)
    else:
        parent = tmp_path / "parent-link"
        parent.symlink_to(root, target_is_directory=True)
        candidate = parent / "artifact.bin"
    with pytest.raises(identity.IdentityError, match="symlink|hard link|unsafe directory"):
        identity.read_bound_artifact(
            candidate,
            expected_sha256=hashlib.sha256(raw).hexdigest(),
            expected_bytes=len(raw),
            name=f"{kind}.artifact",
        )


def _malicious_hdf5(path: Path, kind: str) -> None:
    if kind == "soft":
        with h5py.File(path, "w") as handle:
            handle["bad"] = h5py.SoftLink("/missing")
    elif kind == "external":
        with h5py.File(path, "w") as handle:
            handle["bad"] = h5py.ExternalLink("outside.h5", "/data")
    elif kind == "vds":
        source = path.with_name("source.h5")
        with h5py.File(source, "w") as handle:
            handle.create_dataset("data", data=[1.0])
        layout = h5py.VirtualLayout(shape=(1,), dtype="f8")
        layout[:] = h5py.VirtualSource(source, "data", shape=(1,))
        with h5py.File(path, "w") as handle:
            handle.create_virtual_dataset("bad", layout)
    else:
        with h5py.File(path, "w") as handle:
            handle.create_dataset("bad", shape=(1,), dtype="u1", external=[("outside.raw", 0, 1)])


@pytest.mark.parametrize("kind", ["soft", "external", "vds", "external_storage"])
def test_hdf5_external_soft_vds_and_external_storage_are_rejected(tmp_path: Path, kind: str) -> None:
    path = tmp_path / f"{kind}.h5"
    _malicious_hdf5(path, kind)
    raw = path.read_bytes()
    with pytest.raises(identity.IdentityError, match="non-hard|virtual|externally stored|physical-link"):
        identity.read_bound_artifact(
            path,
            expected_sha256=hashlib.sha256(raw).hexdigest(),
            expected_bytes=len(raw),
            name=f"{kind}.hdf5",
            hdf5=True,
        )


def test_execute_plan_has_no_capability_or_injectable_popen_surface(current_plan) -> None:
    signature = inspect.signature(identity.execute_plan)
    assert "terminal_capability" not in signature.parameters
    assert "popen_factory" not in signature.parameters
    assert "_TERMINAL_CAPABILITY_TOKEN" not in vars(identity)
    with pytest.raises(identity.IdentityError, match="not implemented/admitted"):
        identity.execute_plan(current_plan)


def test_report_writer_rejects_leaf_and_parent_symlink_destinations(tmp_path: Path) -> None:
    target = tmp_path / "sentinel.txt"
    target.write_text("sentinel", encoding="utf-8")
    leaf = tmp_path / "report.json"
    leaf.symlink_to(target)
    with pytest.raises(identity.IdentityError, match="symlink"):
        identity._write_json(leaf, {"must": "not follow"})
    assert target.read_text(encoding="utf-8") == "sentinel"

    outside = tmp_path / "outside"
    outside.mkdir()
    parent_link = tmp_path / "parent-link"
    parent_link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(identity.IdentityError, match="symlink|unsafe directory"):
        identity._write_json(parent_link / "report.json", {"must": "not escape"})
    assert not (outside / "report.json").exists()


def test_report_writer_rejects_leaf_created_after_preflight(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "report.json"
    target = tmp_path / "sentinel.txt"
    target.write_text("sentinel", encoding="utf-8")
    original_link = identity.os.link
    injected = False

    def link_and_inject(source: object, destination: object, *args: object, **kwargs: object) -> object:
        nonlocal injected
        if not injected:
            output.symlink_to(target)
            injected = True
        return original_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(identity.os, "link", link_and_inject)
    with pytest.raises(identity.IdentityError, match="appeared during atomic publication"):
        identity._write_json(output, {"must": "not follow"})
    assert target.read_text(encoding="utf-8") == "sentinel"
