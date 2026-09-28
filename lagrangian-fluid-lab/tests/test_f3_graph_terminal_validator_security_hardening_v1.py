"""Adversarial, no-workload tests for the independent F3 validator audit."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path

import h5py
import pytest

from scripts import f3_graph_terminal_validator_security_hardening_v1 as hardening
from scripts import f3_graph_terminal_production_validator_capability_v1 as production_validator


def _hdf5_bytes(*, link_kind: str | None = None) -> bytes:
    stream = io.BytesIO()
    with h5py.File(stream, "w") as handle:
        handle.create_dataset("safe", data=[1])
        if link_kind == "soft":
            handle["unsafe"] = h5py.SoftLink("/safe")
        elif link_kind == "external":
            handle["unsafe"] = h5py.ExternalLink("/outside.h5", "/safe")
    return stream.getvalue()


def _expected() -> hardening.ExpectedExecutionIdentity:
    return hardening.ExpectedExecutionIdentity(
        model_kind="graph_raw",
        seed=17,
        nonce="a" * 32,
        namespace="/tmp/f3-graph_raw500-hidden16-currentmanifest-seed17-full835-nonce" + "a" * 32,
        manifest_sha256="1" * 64,
        training_receipt_sha256="2" * 64,
        checkpoint_path="/tmp/f3-graph_raw500-hidden16-currentmanifest-seed17-checkpoint.pt",
        checkpoint_sha256="3" * 64,
        command=("/lab/.venv/bin/python", "-u", "/lab/scripts/core_learning.py", "evaluate"),
        cwd="/lab",
        env_overrides=(("CUDA_VISIBLE_DEVICES", "4"),),
    )


def _process_declaration(expected: hardening.ExpectedExecutionIdentity) -> dict[str, object]:
    proof: dict[str, object] = {
        "schema": hardening.PROCESS_PROOF_SCHEMA,
        "status": "natural_exit_verified",
        "synthetic_only": False,
        "real_popen_wait": True,
        "real_popen_type": "subprocess.Popen",
        "wait_observed": True,
        "evaluator_returncode": 0,
        "wait_returncode": 0,
        "evaluator_pid": 12345,
        "model_kind": expected.model_kind,
        "seed": expected.seed,
        "nonce": expected.nonce,
        "namespace": expected.namespace,
        "manifest_sha256": expected.manifest_sha256,
        "training_receipt_sha256": expected.training_receipt_sha256,
        "checkpoint_path": expected.checkpoint_path,
        "checkpoint_sha256": expected.checkpoint_sha256,
        "command": list(expected.command),
        "command_sha256": expected.command_sha256,
        "cwd": expected.cwd,
        "env_overrides": dict(expected.env_overrides),
        "identity_sha256": expected.identity_sha256,
    }
    proof["proof_sha256"] = hardening.canonical_digest(proof)
    return proof


def test_secure_reader_binds_bytes_to_directory_fd_and_rejects_links(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "artifact.bin"
    payload = b"bounded-artifact\n"
    target.write_bytes(payload)

    assert hardening.secure_read_regular_file(
        target,
        root_value=root,
        expected_bytes=len(payload),
        expected_sha256=hardening.hashlib.sha256(payload).hexdigest(),
    ) == payload

    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside\n")
    (root / "leaf-link").symlink_to(outside)
    with pytest.raises(hardening.SecurityBoundaryError, match="without following links|hard link"):
        hardening.secure_read_regular_file(root / "leaf-link", root_value=root)

    outside_dir = tmp_path / "outside-dir"
    outside_dir.mkdir()
    (outside_dir / "escaped.bin").write_bytes(b"escaped\n")
    (root / "parent-link").symlink_to(outside_dir, target_is_directory=True)
    with pytest.raises(hardening.SecurityBoundaryError, match="directory component|unsafe"):
        hardening.secure_read_regular_file(root / "parent-link" / "escaped.bin", root_value=root)

    hardlink = root / "hardlink.bin"
    os.link(target, hardlink)
    with pytest.raises(hardening.SecurityBoundaryError, match="hard link"):
        hardening.secure_read_regular_file(hardlink, root_value=root)


def test_hdf5_snapshot_rejects_soft_and_external_links_without_path_open(tmp_path: Path) -> None:
    good = hardening.inspect_hdf5_snapshot(_hdf5_bytes(), required_datasets=("safe",))
    assert good["passed"] is True
    assert good["external_links_rejected"] is True

    for kind in ("soft", "external"):
        with pytest.raises(hardening.SecurityBoundaryError, match="non-hard link"):
            hardening.inspect_hdf5_snapshot(_hdf5_bytes(link_kind=kind), required_datasets=("safe",))


def test_process_declaration_requires_complete_identity_but_never_promotes_it() -> None:
    expected = _expected()
    proof = _process_declaration(expected)
    result = hardening.validate_declared_process_proof(proof, expected)
    assert result["declaration_consistent"] is True
    assert result["real_popen_wait_verified"] is False
    assert result["promotion_allowed"] is False
    assert result["credit"] == 0

    alternate = dict(proof)
    alternate["command"] = ["/bin/other-evaluator"]
    with pytest.raises(hardening.SecurityBoundaryError, match="command"):
        hardening.validate_declared_process_proof(alternate, expected)

    unknown = dict(proof)
    unknown["untrusted_extra"] = True
    with pytest.raises(hardening.SecurityBoundaryError, match="unknown fields"):
        hardening.validate_declared_process_proof(unknown, expected)

    synthetic = dict(proof)
    synthetic["synthetic_only"] = True
    with pytest.raises(hardening.SecurityBoundaryError, match="synthetic_only"):
        hardening.validate_declared_process_proof(synthetic, expected)


def test_execute_is_rejected_in_both_default_and_explicit_modes() -> None:
    dry_run = hardening.reject_execute_request(execute_requested=False)
    assert dry_run["status"] == "dry_run"
    assert dry_run["popen_attempted"] is False
    assert dry_run["credit"] == 0

    with pytest.raises(hardening.SecurityBoundaryError, match="execute"):
        hardening.reject_execute_request(execute_requested=True)
    with pytest.raises(hardening.SecurityBoundaryError, match="self-install"):
        hardening.reject_execute_request(execute_requested=False, capability_admitted=True)


def test_audit_report_is_blocked_zero_credit_and_no_workload() -> None:
    report = hardening.build_audit_report()
    assert hardening.validate_audit_report(report) == []
    assert report["status"] == "blocked_fail_closed"
    assert report["scope"]["workload_started"] is False
    assert report["scope"]["popen_attempted"] is False
    assert report["side_effects"]["popen_attempts"] == 0
    assert report["credit"] == 0
    assert {finding["severity"] for finding in report["findings"]} == {"P1", "P2"}


def test_audit_records_current_target_code_without_importing_execution_paths() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    raw_validator = (
        repo_root
        / "scripts"
        / "f3_graph_raw_hidden16_current_manifest_terminal_artifact_validator_v1.py"
    ).read_text(encoding="utf-8")
    residual = (
        repo_root
        / "scripts"
        / "f3_graph_residual_hidden16_current_manifest_terminal_artifact_identity_v1.py"
    ).read_text(encoding="utf-8")
    capability = (
        repo_root / "scripts" / "f3_graph_terminal_production_validator_capability_v1.py"
    ).read_text(encoding="utf-8")
    assert 'with h5py.File(path, "r")' in raw_validator
    assert 'with h5py.File(path, "r")' in capability
    # The residual P1 hardening removed the injectable capability-token and
    # fake-Popen path; keep the audit test pinned to the repaired boundary.
    assert "_TERMINAL_CAPABILITY_TOKEN" not in residual
    assert "popen_factory(" not in residual
    assert "subprocess.Popen" in residual
    assert "manifest_sha256" not in capability.split("PROCESS_PROOF_FIELDS", 1)[0]


def test_current_production_process_proof_accepts_self_declared_alternate_command() -> None:
    """Pin the P1 finding without starting a process or opening an artifact."""

    identity = {
        "model_kind": "graph_raw",
        "hidden": production_validator.HIDDEN,
        "seed": 17,
        "case_id": production_validator.CASE_ID,
        "split": production_validator.SPLIT,
        "transitions": production_validator.TRANSITIONS,
        "frames": production_validator.FRAMES,
        "nonce": "a" * 32,
        "namespace": "/tmp/f3-graph_raw500-hidden16-currentmanifest-seed17-full835-nonce" + "a" * 32,
        "fresh_namespace": True,
        "identity_sha256": "b" * 64,
    }
    command = ["/bin/alternate-evaluator", "--not-the-audited-command"]
    proof: dict[str, object] = {
        "schema": production_validator.PROCESS_PROOF_SCHEMA,
        "status": "natural_exit_verified",
        "source": "audited_executor",
        "synthetic_only": False,
        "real_popen_wait": True,
        "real_popen_type": True,
        "popen_type": "subprocess.Popen",
        "wait_observed": True,
        "natural_exit": True,
        "evaluator_pid": 321,
        "evaluator_returncode": 0,
        "wait_returncode": 0,
        "model_kind": identity["model_kind"],
        "hidden": identity["hidden"],
        "seed": identity["seed"],
        "case_id": identity["case_id"],
        "split": identity["split"],
        "transitions": identity["transitions"],
        "frames": identity["frames"],
        "nonce": identity["nonce"],
        "namespace": identity["namespace"],
        "identity_sha256": identity["identity_sha256"],
        "artifact_binding_sha256": "c" * 64,
        "namespace_fresh": True,
        "reuse_forbidden": True,
        "command": command,
        "command_sha256": production_validator.canonical_digest(command),
    }
    proof["proof_sha256"] = production_validator.canonical_digest(proof)
    accepted = production_validator._validate_process_proof(
        proof, identity, str(proof["artifact_binding_sha256"])
    )
    assert accepted["command"] == command
    assert accepted["real_popen_wait"] is True
