"""Synthetic bounded tests for the common F3 production-validator contract."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import h5py
import numpy as np
import pytest

from scripts import f3_full_rollout_receipt_hdf5_validator_v1 as base_validator
from scripts import f3_graph_terminal_production_validator_capability_v1 as validator


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _identity(root: Path, *, model: str = "graph_raw", seed: int = 17) -> dict[str, object]:
    nonce = f"{seed:032x}"
    core: dict[str, object] = {
        "model_kind": model,
        "hidden": validator.HIDDEN,
        "seed": seed,
        "case_id": validator.CASE_ID,
        "split": validator.SPLIT,
        "transitions": validator.TRANSITIONS,
        "frames": validator.FRAMES,
        "nonce": nonce,
        "run_id": f"f3-{model}500-hidden16-currentmanifest-seed{seed}-20260929-v3",
        "namespace": str(root / validator._identity_namespace_name(model, seed, nonce)),
        "fresh_namespace": True,
    }
    return {**core, "identity_sha256": validator.canonical_digest(core)}


def _write_complete_hdf5(path: Path, identity: dict[str, object]) -> None:
    frames = validator.FRAMES
    particles = 2
    with h5py.File(path, "w") as handle:
        handle.create_dataset("time", data=np.arange(frames, dtype=np.float64))
        handle.create_dataset("position", data=np.zeros((frames, particles, 3), dtype=np.float32))
        handle.create_dataset("velocity", data=np.ones((frames, particles, 3), dtype=np.float32))
        handle.create_dataset("particle_id", data=np.array([101, 202], dtype=np.int64))
        handle.create_dataset("particle_zone", data=np.array([0, 1], dtype=np.int32))
        handle.create_dataset("mass", data=np.ones(particles, dtype=np.float64))
        handle.create_dataset("valid", data=np.ones((frames, particles), dtype=np.bool_))
        attrs: dict[str, object] = {
            "model_kind": identity["model_kind"],
            "hidden": validator.HIDDEN,
            "seed": identity["seed"],
            "case_id": validator.CASE_ID,
            "split": validator.SPLIT,
            "transitions": validator.TRANSITIONS,
            "frames": validator.FRAMES,
            "nonce": identity["nonce"],
            "future_state_inputs": False,
            "autonomous_prediction": True,
            "synthetic_fixture": False,
        }
        for key, value in attrs.items():
            handle.attrs[key] = value


def _write_evaluation(path: Path, trajectory: Path, identity: dict[str, object]) -> None:
    expected = validator.TRANSITIONS
    values = [0.001] * expected
    row = {
        "case_id": validator.CASE_ID,
        "frames_predicted": expected,
        "frames_expected": expected,
        "frames_executed": expected,
        "expected_frames": expected,
        "executed": True,
        "position_rmse": values,
        "velocity_rmse": values,
        "position_ade": values,
        "velocity_ade": values,
        "failure_category": None,
        "first_failure_frame": None,
        "execution_complete": True,
        "finite_rollout_complete": True,
        "scientific_status": "not_assessed",
        "scientific_failure_category": None,
        "scientific_first_failure_frame": None,
        "future_state_inputs": False,
        "trajectory_output": str(trajectory),
        "score": {
            "expected_frames": expected,
            "finite_prefix_frames": expected,
            "executed": True,
            "complete": True,
            "failure_category": None,
            "raw_error_coverage": 1.0,
            "selection_score": 0.0,
        },
    }
    payload = {
        "schema": base_validator.EVALUATION_SCHEMA,
        "evaluation_mode": "diagnostic",
        "diagnostic": True,
        "formal_eligible": False,
        "registered_case_ids": [validator.CASE_ID],
        "selected_case_ids": [validator.CASE_ID],
        "expected_frames": {validator.CASE_ID: expected},
        "cases": {validator.CASE_ID: row},
        "maximum_steps": None,
        "autonomous": True,
        "future_state_inputs": False,
        "f3_identity": identity,
        "identity_sha256": identity["identity_sha256"],
        "model_kind": identity["model_kind"],
        "hidden": validator.HIDDEN,
        "seed": identity["seed"],
        "split": validator.SPLIT,
        "transitions": validator.TRANSITIONS,
        "frames": validator.FRAMES,
        "nonce": identity["nonce"],
        "synthetic_only": False,
    }
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _write_progress(path: Path, identity: dict[str, object], artifacts: dict[str, Path]) -> None:
    payload = {
        "schema": validator.PROGRESS_SCHEMA,
        "status": "completed",
        "synthetic_only": False,
        "f3_identity": identity,
        "identity_sha256": identity["identity_sha256"],
        "model_kind": identity["model_kind"],
        "hidden": validator.HIDDEN,
        "seed": identity["seed"],
        "case_id": validator.CASE_ID,
        "split": validator.SPLIT,
        "transitions": validator.TRANSITIONS,
        "frames": validator.FRAMES,
        "nonce": identity["nonce"],
        "evaluation_path": str(artifacts["evaluation"]),
        "trajectory_path": str(artifacts["trajectory"]),
        "progress_path": str(artifacts["progress"]),
        "validator_path": str(artifacts["validator"]),
        "frames_executed": validator.TRANSITIONS,
        "trajectory_transitions": validator.TRANSITIONS,
        "trajectory_frames": validator.FRAMES,
        "terminal": True,
        "execution_complete": True,
        "finite_rollout_complete": True,
        "future_state_inputs": False,
    }
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _artifact_ref(path: Path, identity_sha256: str) -> dict[str, object]:
    raw = path.read_bytes()
    return {
        "path": str(path),
        "sha256": _sha_bytes(raw),
        "bytes": len(raw),
        "identity_sha256": identity_sha256,
    }


def _refresh_receipt_bindings(receipt: dict[str, object]) -> None:
    identity = receipt["identity"]
    artifacts = receipt["artifacts"]
    assert isinstance(identity, dict)
    assert isinstance(artifacts, dict)
    for name, item in artifacts.items():
        assert isinstance(item, dict)
        path = Path(str(item["path"]))
        artifacts[name] = _artifact_ref(path, str(identity["identity_sha256"]))
    binding = validator.canonical_digest(artifacts)
    receipt["artifact_binding_sha256"] = binding
    proof = receipt["process_proof"]
    assert isinstance(proof, dict)
    proof["artifact_binding_sha256"] = binding
    proof_core = dict(proof)
    proof_core.pop("proof_sha256", None)
    proof["proof_sha256"] = validator.canonical_digest(proof_core)


def _refresh_binding_digest_only(receipt: dict[str, object]) -> None:
    artifacts = receipt["artifacts"]
    assert isinstance(artifacts, dict)
    binding = validator.canonical_digest(artifacts)
    receipt["artifact_binding_sha256"] = binding
    proof = receipt["process_proof"]
    assert isinstance(proof, dict)
    proof["artifact_binding_sha256"] = binding
    proof_core = dict(proof)
    proof_core.pop("proof_sha256", None)
    proof["proof_sha256"] = validator.canonical_digest(proof_core)


def _fixture(
    tmp_path: Path,
    *,
    model: str = "graph_raw",
    seed: int = 17,
) -> tuple[Path, dict[str, object], dict[str, Path]]:
    root = tmp_path / "bounded-fixture"
    root.mkdir()
    (root / validator.FIXTURE_MARKER_NAME).write_text(
        validator.FIXTURE_MARKER_CONTENT, encoding="utf-8"
    )
    identity = _identity(root, model=model, seed=seed)
    namespace = Path(str(identity["namespace"]))
    artifacts = {
        name: Path(str(namespace) + suffix)
        for name, suffix in validator.ARTIFACT_SUFFIX_NAMES.items()
    }
    _write_complete_hdf5(artifacts["trajectory"], identity)
    _write_evaluation(artifacts["evaluation"], artifacts["trajectory"], identity)
    _write_progress(artifacts["progress"], identity, artifacts)
    base_result = base_validator.run_validation(
        artifacts["evaluation"],
        artifacts["trajectory"],
        case_id=validator.CASE_ID,
        expected_transitions=validator.TRANSITIONS,
    )
    assert base_result["passed"] is True
    validator_payload = {
        **base_result,
        "f3_identity": identity,
        "identity_sha256": identity["identity_sha256"],
        "progress_path": str(artifacts["progress"]),
        "validator_artifact_path": str(artifacts["validator"]),
        "synthetic_only": False,
    }
    artifacts["validator"].write_text(
        json.dumps(validator_payload, sort_keys=True) + "\n", encoding="utf-8"
    )
    refs = {
        name: _artifact_ref(path, str(identity["identity_sha256"]))
        for name, path in artifacts.items()
    }
    binding = validator.canonical_digest(refs)
    command = ["audited-f3-evaluator", "--model", model, "--seed", str(seed)]
    proof_core: dict[str, object] = {
        "schema": validator.PROCESS_PROOF_SCHEMA,
        "status": "natural_exit_verified",
        "source": "audited_executor",
        "synthetic_only": False,
        "real_popen_wait": True,
        "real_popen_type": True,
        "popen_type": "subprocess.Popen",
        "wait_observed": True,
        "natural_exit": True,
        "evaluator_pid": 4217,
        "evaluator_returncode": 0,
        "wait_returncode": 0,
        "model_kind": identity["model_kind"],
        "hidden": validator.HIDDEN,
        "seed": identity["seed"],
        "case_id": validator.CASE_ID,
        "split": validator.SPLIT,
        "transitions": validator.TRANSITIONS,
        "frames": validator.FRAMES,
        "nonce": identity["nonce"],
        "namespace": identity["namespace"],
        "identity_sha256": identity["identity_sha256"],
        "artifact_binding_sha256": binding,
        "namespace_fresh": True,
        "reuse_forbidden": True,
        "command": command,
        "command_sha256": validator.canonical_digest(command),
    }
    proof = {**proof_core, "proof_sha256": validator.canonical_digest(proof_core)}
    receipt: dict[str, object] = {
        "schema": validator.INPUT_SCHEMA,
        "synthetic_only": False,
        "identity": identity,
        "artifacts": refs,
        "artifact_binding_sha256": binding,
        "process_proof": proof,
    }
    return root, receipt, artifacts


def test_default_capability_is_ungranted_and_zero_credit() -> None:
    report = validator.build_report()
    assert report["status"] == "blocked_fail_closed"
    assert report["capability_admitted"] is False
    assert report["production_validator_capability_installed"] is False
    assert report["launch_allowed"] is False
    assert report["credit"] == 0
    assert report["input_boundary"]["popen_attempted"] is False
    assert validator.validate_report(report) == []


def test_production_shaped_fixture_wraps_existing_validator_but_stays_blocked(tmp_path: Path) -> None:
    root, receipt, _ = _fixture(tmp_path)
    report = validator.build_report(receipt, fixture_root=root)
    assert report["status"] == "blocked_fail_closed"
    assert report["source_bound"] is True
    assert report["structural_validation"]["status"] == "structurally_validated_bounded_fixture"
    assert report["structural_validation"]["base_validator_result"]["passed"] is True
    assert report["hdf5_validation"]["trajectory_frames"] == validator.FRAMES
    assert report["hdf5_validation"]["trajectory_transitions"] == validator.TRANSITIONS
    assert report["real_popen_wait_proof_present"] is True
    assert report["real_popen_wait_verified"] is False
    assert report["credit"] == 0
    assert report["input_boundary"]["temporary_fixture_artifacts_opened"] is True
    assert report["input_boundary"]["production_artifacts_opened"] is False
    assert report["side_effects"]["processes_started"] == 0
    assert validator.validate_report(report) == []


def test_shared_contract_accepts_residual_identity_shape_without_authorizing(tmp_path: Path) -> None:
    root, receipt, _ = _fixture(tmp_path, model="graph_residual", seed=29)
    report = validator.build_report(receipt, fixture_root=root)
    assert report["source_bound"] is True
    assert report["identity"]["model_kind"] == "graph_residual"
    assert report["identity"]["seed"] == 29
    assert report["capability_admitted"] is False
    assert report["credit"] == 0


def test_synthetic_only_receipt_is_rejected_before_any_artifact_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, receipt, _ = _fixture(tmp_path)
    receipt["synthetic_only"] = True
    monkeypatch.setattr(
        validator,
        "_inspect_bounded_fixture",
        lambda *args, **kwargs: pytest.fail("synthetic-only receipt must not open artifacts"),
    )
    report = validator.build_report(receipt, fixture_root=root)
    assert report["source_bound"] is False
    assert report["synthetic_only_receipt_rejected"] is True
    assert report["hdf5_validation"]["status"] == "not_run"
    assert report["input_boundary"]["trajectory_hdf5_opened"] is False


def test_synthetic_process_proof_is_rejected_before_any_artifact_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, receipt, _ = _fixture(tmp_path)
    proof = receipt["process_proof"]
    assert isinstance(proof, dict)
    proof["synthetic_only"] = True
    core = dict(proof)
    core.pop("proof_sha256")
    proof["proof_sha256"] = validator.canonical_digest(core)
    monkeypatch.setattr(
        validator,
        "_inspect_bounded_fixture",
        lambda *args, **kwargs: pytest.fail("invalid process proof must not open artifacts"),
    )
    report = validator.build_report(receipt, fixture_root=root)
    assert report["synthetic_only_receipt_rejected"] is True
    assert report["input_boundary"]["evaluation_json_opened"] is False
    assert any("process_proof.synthetic_only" in reason for reason in report["blocked_reasons"])


def test_valid_receipt_without_fixture_root_never_reads_production_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, receipt, _ = _fixture(tmp_path)
    monkeypatch.setattr(
        validator,
        "_inspect_bounded_fixture",
        lambda *args, **kwargs: pytest.fail("ungranted capability must not read production paths"),
    )
    report = validator.build_report(receipt)
    assert report["source_bound"] is False
    assert report["hdf5_validation"]["status"] == "not_run"
    assert report["input_boundary"]["production_artifacts_opened"] is False
    assert any("capability is not installed" in reason for reason in report["blocked_reasons"])


def test_artifact_sha_drift_fails_closed(tmp_path: Path) -> None:
    root, receipt, _ = _fixture(tmp_path)
    mutated = copy.deepcopy(receipt)
    artifacts = mutated["artifacts"]
    assert isinstance(artifacts, dict)
    progress = artifacts["progress"]
    assert isinstance(progress, dict)
    progress["sha256"] = _sha_bytes(b"wrong-progress-identity")
    _refresh_binding_digest_only(mutated)
    report = validator.build_report(mutated, fixture_root=root)
    assert report["source_bound"] is False
    assert report["structural_validation"]["status"] == "not_run"
    assert any("SHA-256" in reason for reason in report["blocked_reasons"])


def test_artifact_bytes_drift_fails_closed(tmp_path: Path) -> None:
    root, receipt, _ = _fixture(tmp_path)
    mutated = copy.deepcopy(receipt)
    artifacts = mutated["artifacts"]
    assert isinstance(artifacts, dict)
    progress = artifacts["progress"]
    assert isinstance(progress, dict)
    progress["bytes"] = int(progress["bytes"]) + 1
    _refresh_binding_digest_only(mutated)
    report = validator.build_report(mutated, fixture_root=root)
    assert report["source_bound"] is False
    assert any("bytes" in reason for reason in report["blocked_reasons"])


def test_evaluator_identity_drift_fails_closed(tmp_path: Path) -> None:
    root, receipt, artifacts = _fixture(tmp_path)
    evaluation = json.loads(artifacts["evaluation"].read_text(encoding="utf-8"))
    evaluation["f3_identity"]["seed"] = 29
    artifacts["evaluation"].write_text(json.dumps(evaluation, sort_keys=True) + "\n", encoding="utf-8")
    mutated = copy.deepcopy(receipt)
    _refresh_receipt_bindings(mutated)
    report = validator.build_report(mutated, fixture_root=root)
    assert report["structural_validation"]["status"] == "not_run"
    assert any("f3_identity" in reason for reason in report["blocked_reasons"])


def test_progress_cross_binding_path_drift_fails_closed(tmp_path: Path) -> None:
    root, receipt, artifacts = _fixture(tmp_path)
    progress = json.loads(artifacts["progress"].read_text(encoding="utf-8"))
    progress["validator_path"] = str(artifacts["evaluation"])
    artifacts["progress"].write_text(json.dumps(progress, sort_keys=True) + "\n", encoding="utf-8")
    mutated = copy.deepcopy(receipt)
    _refresh_receipt_bindings(mutated)
    report = validator.build_report(mutated, fixture_root=root)
    assert report["structural_validation"]["status"] == "not_run"
    assert any("progress.validator_path" in reason for reason in report["blocked_reasons"])


def test_hdf5_identity_drift_fails_closed(tmp_path: Path) -> None:
    root, receipt, artifacts = _fixture(tmp_path)
    with h5py.File(artifacts["trajectory"], "r+") as handle:
        handle.attrs["seed"] = 29
    mutated = copy.deepcopy(receipt)
    _refresh_receipt_bindings(mutated)
    report = validator.build_report(mutated, fixture_root=root)
    assert report["structural_validation"]["status"] == "not_run"
    assert any("seed" in reason for reason in report["blocked_reasons"])


def test_fresh_nonce_namespace_is_required(tmp_path: Path) -> None:
    root, receipt, _ = _fixture(tmp_path)
    mutated = copy.deepcopy(receipt)
    identity = mutated["identity"]
    assert isinstance(identity, dict)
    identity["nonce"] = "0" * 32
    report = validator.build_report(mutated, fixture_root=root)
    assert report["source_bound"] is False
    assert any("nonce" in reason for reason in report["blocked_reasons"])


def test_real_popen_wait_fields_are_mandatory(tmp_path: Path) -> None:
    root, receipt, _ = _fixture(tmp_path)
    mutated = copy.deepcopy(receipt)
    proof = mutated["process_proof"]
    assert isinstance(proof, dict)
    proof["wait_observed"] = False
    core = dict(proof)
    core.pop("proof_sha256")
    proof["proof_sha256"] = validator.canonical_digest(core)
    report = validator.build_report(mutated, fixture_root=root)
    assert report["source_bound"] is False
    assert any("wait_observed" in reason for reason in report["blocked_reasons"])


def test_report_validator_rejects_forged_authorization(tmp_path: Path) -> None:
    root, receipt, _ = _fixture(tmp_path)
    report = validator.build_report(receipt, fixture_root=root)
    forged = copy.deepcopy(report)
    forged["launch_allowed"] = True
    assert validator.validate_report(forged)
    forged = copy.deepcopy(report)
    forged["credit"] = 1
    assert validator.validate_report(forged)
    forged = copy.deepcopy(report)
    forged["real_popen_wait_verified"] = True
    assert validator.validate_report(forged)


def test_cli_default_report_and_report_verify_are_zero_credit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    report_path = tmp_path / "report.json"
    assert validator.main(["--report-output", str(report_path)]) == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "blocked_fail_closed"
    assert report["credit"] == 0
    assert validator.main(["--verify-report", str(report_path)]) == 0
    output = capsys.readouterr().out
    assert '"valid":true' in output
