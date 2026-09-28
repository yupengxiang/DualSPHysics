from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "f3_mlp_hidden16_terminal_runtime_verifier_v1.py"
SPEC = importlib.util.spec_from_file_location("f3_mlp_hidden16_terminal_runtime_verifier_v1", SCRIPT)
assert SPEC and SPEC.loader
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _write(path: Path, value: object) -> tuple[str, int]:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest(), len(data)


def _artifact(path: str, token: str, size: int = 100) -> dict[str, object]:
    return {"path": path, "sha256": _sha(token), "bytes": size}


def _fixture(tmp_path: Path) -> tuple[dict, dict, dict, dict]:
    reports = tmp_path / "reports"
    reports.mkdir()
    manifest_sha = "1" * 64
    training_runs = []
    rollouts: dict[int, Path] = {}
    proofs: dict[int, Path] = {}
    validators: dict[int, Path] = {}
    nonce_by_seed = {17: "a" * 32, 29: "b" * 32, 43: "c" * 32}

    for seed in verifier.SEEDS:
        run_id = verifier._expected_run_id(seed)
        checkpoint_path = f"/tmp/f3-mlp500-hidden16-seed{seed}-20260928-checkpoint.pt"
        checkpoint = _artifact(checkpoint_path, f"checkpoint-{seed}", 60000)
        checkpoint.update({"schema": "core.checkpoint.v1", "update": 500})
        training_path = f"/tmp/f3-mlp500-hidden16-seed{seed}-20260928-training.json"
        training_sha = _sha(f"training-{seed}")
        training_runs.append({
            "seed": seed,
            "status": "bound_complete",
            "source": {"path": training_path, "sha256": training_sha, "bytes": 10000, "schema": "core.training.v1"},
            "evidence": {
                "model_kind": "mlp", "hidden": 16, "updates": 500,
                "run_id": run_id, "evidence_status": "complete",
                "manifest_sha256": manifest_sha, "checkpoint": checkpoint,
            },
        })
        nonce = nonce_by_seed[seed]
        namespace = f"/tmp/f3-mlp500-hidden16-seed{seed}-full835-nonce{nonce}"
        evaluation_path = namespace + "-evaluation.json"
        trajectory_path = namespace + "-trajectory.h5"
        validator_path = reports / f"validator-{seed}.json"
        evaluation = _artifact(evaluation_path, f"evaluation-{seed}", 6400000)
        trajectory = _artifact(trajectory_path, f"trajectory-{seed}", 723148320)
        checkpoint_rollout = dict(checkpoint)
        checkpoint_rollout.update({"model": "mlp", "seed": seed, "hidden": 16})
        rollout = {
            "schema": f"core.f3.mlp.hidden16.seed{seed}.full835_rollout_diagnostic.summary.v1",
            "report_id": f"F3-MLP-SEED{seed}-FIXTURE",
            "status": "completed", "diagnostic_only": True,
            "source": {"manifest": {"sha256": manifest_sha}},
            "protocol": {"model": "mlp", "seed": seed, "hidden": 16, "training_updates": 500,
                         "case_id": verifier.CASE_ID, "split": "test", "maximum_steps": 835,
                         "diagnostic": True, "autonomous": True, "future_state_inputs": False,
                         "namespace": namespace, "namespace_nonce": nonce},
            "checkpoint": checkpoint_rollout,
            "evaluation": {"status": "completed", "execution_complete": True,
                           "finite_rollout_complete": True, "transitions_executed": 835,
                           "expected_transitions": 835, "trajectory_frames_including_initial": 836,
                           "full_registered_denominator_complete": True, "future_state_inputs": False,
                           "failure_category": None, "receipt": evaluation},
            "trajectory": trajectory,
            "artifacts": {},
        }
        rollout_path = reports / f"rollout-{seed}.json"
        _write(rollout_path, rollout)
        rollouts[seed] = rollout_path
        validator = {
            "schema": verifier.VALIDATOR_SCHEMA, "passed": True, "complete": True,
            "fail_closed": False, "diagnostic_only": True, "synthetic_only": False,
            "case_id": verifier.CASE_ID, "expected_transitions": 835, "frames_executed": 835,
            "qualification_credit": 0, "production_artifacts_touched": False,
            "evaluation_json": evaluation_path, "trajectory_hdf5": trajectory_path,
            "checks": {"trajectory_frames": 836, "trajectory_transitions": 835,
                       "tail_frame_count": 0},
        }
        validator_sha, validator_bytes = _write(validator_path, validator)
        validators[seed] = validator_path
        proof = {
            "schema": f"core.f3.mlp.hidden16.seed{seed}.process_exit_proof.v1",
            "report_id": f"mlp-process-proof-{seed}", "status": "exited_successfully",
            "source_bound": True, "diagnostic_only": True, "formal": False,
            "formal_eligible": False, "T1_numerical": False, "T2_macro": False,
            "T2_path": False, "qualification": False, "qualification_credit": 0,
            "credit": 0, "seed": seed, "run_id": run_id, "namespace": namespace,
            "namespace_nonce": nonce, "evaluator_alive": False, "launcher_alive": False,
            "evaluator_returncode": 0, "launcher_returncode": 0, "returncode": 0,
            "evaluator_pid_observed": 1000 + seed, "launcher_pid_observed": 2000 + seed,
            "evaluator_reaped": True, "launcher_reaped": True,
            "command_sha256": "2" * 64, "exit_proof_sha256": "3" * 64,
            "manifest_sha256": manifest_sha, "training_manifest_sha256": manifest_sha,
            "training_receipt_sha256": training_sha, "checkpoint": _artifact(checkpoint_path, f"checkpoint-{seed}", 60000),
            "evaluation": evaluation, "trajectory": trajectory,
            "validator": {"path": str(validator_path), "sha256": validator_sha, "bytes": validator_bytes},
        }
        proof["checkpoint"]["sha256"] = checkpoint["sha256"]
        proof_path = reports / f"proof-{seed}.json"
        _write(proof_path, proof)
        proofs[seed] = proof_path

    training = {
        "schema": verifier.TRAINING_SCHEMA, "report_id": "fixture-training",
        "status": "bound", "fail_closed": False, "source_bound": True,
        "diagnostic_only": True, "formal": False, "formal_eligible": False,
        "qualification": False, "T1_numerical": False, "T2_macro": False,
        "T2_path": False, "qualification_credit": 0, "credit": 0,
        "shared_config": {"model_kind": "mlp", "hidden": 16, "updates": 500},
        "runs": training_runs,
    }
    training_path = reports / "training.json"
    _write(training_path, training)
    return {"training": training_path, "rollouts": rollouts, "proofs": proofs, "validators": validators}


def _build(tmp_path: Path, fixture: dict) -> dict:
    return verifier.build_report(
        tmp_path,
        training_path=fixture["training"],
        rollout_paths=fixture["rollouts"],
        process_paths=fixture["proofs"],
        validator_paths=fixture["validators"],
    )


def test_default_missing_process_proof_is_blocked() -> None:
    report = verifier.build_report()
    assert report["status"] == "blocked_fail_closed"
    assert report["source_bound"] is False
    assert report["credit"] == 0
    assert all(row["status"] == "blocked" for row in report["seed_matrix"])


def test_complete_fixture_requires_all_four_evidence_classes(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    report = _build(tmp_path, fixture)
    assert report["status"] == "independently_terminal_verified"
    assert report["source_bound"] is True
    assert report["independently_terminal_verified"] is True
    assert report["credit"] == 0
    assert verifier.validate_report(report) == []


def test_returncode_mismatch_blocks(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    proof = json.loads(fixture["proofs"][17].read_text())
    proof["returncode"] = 1
    _write(fixture["proofs"][17], proof)
    report = _build(tmp_path, fixture)
    assert report["source_bound"] is False
    assert any("returncode" in reason for reason in report["blocked_reasons"])


def test_training_evaluation_identity_drift_blocks(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    proof = json.loads(fixture["proofs"][29].read_text())
    proof["evaluation"]["sha256"] = "f" * 64
    _write(fixture["proofs"][29], proof)
    report = _build(tmp_path, fixture)
    assert report["source_bound"] is False
    assert any("evaluation" in reason for reason in report["blocked_reasons"])


def test_validator_path_binding_blocks(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    validator = json.loads(fixture["validators"][43].read_text())
    validator["trajectory_hdf5"] = "/tmp/wrong.h5"
    _write(fixture["validators"][43], validator)
    report = _build(tmp_path, fixture)
    assert report["source_bound"] is False
    assert any("artifact paths" in reason for reason in report["blocked_reasons"])


def test_unknown_process_field_blocks(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    proof = json.loads(fixture["proofs"][17].read_text())
    proof["formal_alias"] = False
    _write(fixture["proofs"][17], proof)
    report = _build(tmp_path, fixture)
    assert report["source_bound"] is False
    assert any("unknown fields" in reason for reason in report["blocked_reasons"])


def test_duplicate_key_blocks(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    path = fixture["proofs"][17]
    path.write_text('{"schema":"x","schema":"y"}', encoding="utf-8")
    report = _build(tmp_path, fixture)
    assert report["source_bound"] is False
    assert any("duplicate JSON key" in reason for reason in report["blocked_reasons"])


def test_nonfinite_json_blocks(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    path = fixture["proofs"][17]
    path.write_text('{"value":NaN}', encoding="utf-8")
    report = _build(tmp_path, fixture)
    assert report["source_bound"] is False
    assert any("non-finite" in reason for reason in report["blocked_reasons"])


def test_symlink_process_proof_blocks(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    target = fixture["proofs"][17]
    link = target.with_name("proof-link.json")
    link.symlink_to(target)
    fixture["proofs"][17] = link
    report = _build(tmp_path, fixture)
    assert report["source_bound"] is False
    assert any("single-link regular file" in reason or "No such file" in reason for reason in report["blocked_reasons"])


def test_output_boundary_rejects_arbitrary_path(tmp_path: Path) -> None:
    with pytest.raises(verifier.VerifierError):
        verifier._fixed_output(tmp_path / "escape.json", tmp_path, verifier.REPORT_JSON_FILENAME, b"{}")


def test_report_always_declares_zero_credit(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    report = _build(tmp_path, fixture)
    assert report["formal"] is False
    assert report["formal_eligible"] is False
    assert report["T1_numerical"] is False
    assert report["T2_macro"] is False
    assert report["qualification"] is False
    assert report["credit"] == 0
