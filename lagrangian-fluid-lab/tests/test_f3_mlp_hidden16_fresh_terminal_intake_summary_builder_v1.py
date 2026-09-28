from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "f3_mlp_hidden16_fresh_terminal_intake_summary_builder_v1.py"
SPEC = importlib.util.spec_from_file_location("f3_mlp_hidden16_fresh_terminal_intake_summary_builder_v1", SCRIPT)
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = builder
SPEC.loader.exec_module(builder)


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_text(value: str) -> str:
    return _sha_bytes(value.encode())


def _write_json(path: Path, value: object) -> dict[str, object]:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {"sha256": _sha_bytes(raw), "bytes": len(raw)}


def _nonce(tmp_path: Path, seed: int) -> str:
    return _sha_text(f"{tmp_path}:{seed}")[:32]


def _fixture(tmp_path: Path, *, with_proofs: bool = True) -> tuple[dict, dict[int, builder.SeedInputs], Path]:
    reports = tmp_path / "reports"
    reports.mkdir()
    training_runs = []
    inputs: dict[int, builder.SeedInputs] = {}
    proof_payloads: dict[int, Path] = {}
    namespace_paths: dict[int, Path] = {}
    checkpoint_by_seed: dict[int, tuple[Path, str, int]] = {}

    for seed in builder.SEEDS:
        checkpoint_path = Path(f"/tmp/f3-mlp500-hidden16-seed{seed}-20260928-checkpoint.pt")
        checkpoint_bytes = 60000 + seed
        checkpoint_sha = _sha_text(f"checkpoint-{seed}")
        checkpoint_by_seed[seed] = (checkpoint_path, checkpoint_sha, checkpoint_bytes)
        training_runs.append({
            "seed": seed,
            "status": "bound_complete",
            "model_kind": "mlp",
            "hidden": 16,
            "completed_updates": 500,
            "run_id": builder._expected_run_id(seed),
            "checkpoint_path": checkpoint_path.name,
            "checkpoint_sha256": checkpoint_sha,
            "checkpoint_verified": True,
        })

        nonce = _nonce(tmp_path, seed)
        namespace = builder._expected_namespace(seed, nonce)
        namespace_paths[seed] = namespace
        evaluation_path = Path(str(namespace) + "-evaluation.json")
        trajectory_path = Path(str(namespace) + "-trajectory.h5")
        validator_path = Path(str(namespace) + "-hdf5-validation.json")
        metadata_path = tmp_path / f"trajectory-metadata-{seed}.json"
        history_path = reports / f"history-{seed}.json"
        for path in (evaluation_path, trajectory_path, validator_path):
            path.unlink(missing_ok=True)

        evaluation = {
            "schema": "core.evaluation.v1",
            "evaluation_mode": "diagnostic",
            "diagnostic": True,
            "formal_eligible": False,
            "autonomous": True,
            "future_state_inputs": False,
            "maximum_steps": 835,
            "registered_case_ids": [builder.CASE_ID],
            "selected_case_ids": [builder.CASE_ID],
            "expected_frames": {builder.CASE_ID: 835},
            "cases": {
                builder.CASE_ID: {
                    "case_id": builder.CASE_ID,
                    "frames_expected": 835,
                    "expected_frames": 835,
                    "frames_executed": 835,
                    "frames_predicted": 835,
                    "executed": True,
                    "failure_category": None,
                    "first_failure_frame": None,
                    "execution_complete": True,
                    "finite_rollout_complete": True,
                    "future_state_inputs": False,
                    "metrics": [0.1] * 835,
                    "score": {
                        "expected_frames": 835,
                        "finite_prefix_frames": 835,
                        "executed": True,
                        "complete": True,
                        "failure_category": None,
                        "raw_error_coverage": 1.0,
                    },
                }
            },
        }
        _write_json(evaluation_path, evaluation)
        trajectory_bytes = 4096 + seed
        trajectory_raw = b"synthetic HDF5 bytes are not opened by this builder" + bytes([seed])
        trajectory_path.write_bytes(trajectory_raw)
        trajectory_sha = _sha_bytes(trajectory_raw)
        metadata = {
            "schema": builder.TRAJECTORY_METADATA_SCHEMA,
            "seed": seed,
            "model": "mlp",
            "hidden": 16,
            "updates": 500,
            "case_id": builder.CASE_ID,
            "split": "test",
            "transitions": 835,
            "frames": 836,
            "namespace": str(namespace),
            "namespace_nonce": nonce,
            "diagnostic_only": True,
            "source_bound": True,
            "future_state_inputs": False,
            "trajectory": {"path": str(trajectory_path), "sha256": trajectory_sha, "bytes": len(trajectory_raw)},
            "stream_hash": {"algorithm": "sha256", "sha256": trajectory_sha, "bytes": len(trajectory_raw)},
        }
        _write_json(metadata_path, metadata)
        validator = {
            "schema": builder.VALIDATOR_SCHEMA,
            "passed": True,
            "complete": True,
            "incomplete": False,
            "diagnostic_only": True,
            "synthetic_only": False,
            "fail_closed": False,
            "production_artifacts_touched": False,
            "qualification_credit": 0,
            "case_id": builder.CASE_ID,
            "expected_transitions": 835,
            "frames_executed": 835,
            "failure_category": None,
            "evaluation_json": str(evaluation_path),
            "trajectory_hdf5": str(trajectory_path),
            "checks": {"trajectory_frames": 836, "trajectory_transitions": 835, "executed_frame_count": 836, "tail_frame_count": 0, "future_state_inputs": False},
        }
        validator_meta = _write_json(validator_path, validator)
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
            "protocol": {"model": "mlp", "seed": seed, "training_updates": 500, "hidden": 16, "case_id": builder.CASE_ID, "split": "test", "maximum_steps": 835, "diagnostic": True, "autonomous": True, "future_state_inputs": False},
            "evaluation": {"status": "completed", "transitions_executed": 835, "trajectory_frames_including_initial": 836, "finite_rollout_complete": True, "future_state_inputs": False},
            "checkpoint": {"path": str(checkpoint_path), "sha256": checkpoint_sha, "bytes": checkpoint_bytes},
        }
        _write_json(history_path, history)
        if with_proofs:
            proof = {
                "schema": f"{builder.PROCESS_SCHEMA_PREFIX}{seed}{builder.PROCESS_SCHEMA_SUFFIX}",
                "report_id": f"proof-{seed}",
                "status": "exited_successfully",
                "source_bound": True,
                "diagnostic_only": True,
                "formal": False,
                "formal_eligible": False,
                "T1_numerical": False,
                "T2_macro": False,
                "T2_path": False,
                "qualification": False,
                "qualification_credit": 0,
                "credit": 0,
                "seed": seed,
                "run_id": builder._expected_run_id(seed),
                "namespace": str(namespace),
                "namespace_nonce": nonce,
                "evaluator_alive": False,
                "launcher_alive": False,
                "evaluator_returncode": 0,
                "launcher_returncode": 0,
                "returncode": 0,
                "evaluator_pid_observed": 1000 + seed,
                "launcher_pid_observed": 2000 + seed,
                "evaluator_reaped": True,
                "launcher_reaped": True,
                "command_sha256": "1" * 64,
                "evaluator_start_identity": {"proc_starttime_ticks": 100 + seed},
                "evaluator_end_identity": {"proc_starttime_ticks": 100 + seed},
                "launcher_start_identity": {"proc_starttime_ticks": 200 + seed},
                "launcher_end_identity": {"proc_starttime_ticks": 200 + seed},
                "manifest_sha256": "2" * 64,
                "training_manifest_sha256": "3" * 64,
                "training_receipt_sha256": "4" * 64,
                "checkpoint": {"path": str(checkpoint_path), "sha256": checkpoint_sha, "bytes": checkpoint_bytes},
                "evaluation": {"path": str(evaluation_path), "sha256": "0" * 64, "bytes": evaluation_path.stat().st_size},
                "trajectory": {"path": str(trajectory_path), "sha256": trajectory_sha, "bytes": len(trajectory_raw)},
                "validator": {"path": str(validator_path), "sha256": str(validator_meta["sha256"]), "bytes": int(validator_meta["bytes"])},
            }
            proof["evaluation"]["sha256"] = _sha_bytes(evaluation_path.read_bytes())
            proof["exit_proof_sha256"] = builder._canonical_digest(proof)
            proof_path = reports / f"process-proof-{seed}.json"
            _write_json(proof_path, proof)
            proof_payloads[seed] = proof_path

        inputs[seed] = builder.SeedInputs(evaluation_path, metadata_path, validator_path, history_path, proof_payloads.get(seed))

    training = {
        "schema": "core.f3.mlp.hidden16.training_matrix.v1",
        "model": "mlp",
        "diagnostic_only": True,
        "formal_eligible": False,
        "manifest_sha256": "5" * 64,
        "qualification": {"credit": 0, "full_rollout_evaluations": "pending", "qualification": False, "t1": False, "t2": False, "training_evidence_complete": True},
        "shared_config": {"model_kind": "mlp", "hidden": 16, "updates": 500},
        "runs": training_runs,
    }
    training_path = reports / "training-matrix.json"
    _write_json(training_path, training)
    return {"root": tmp_path, "namespace_paths": namespace_paths}, inputs, training_path


def _build(fixture: tuple[dict, dict[int, builder.SeedInputs], Path]) -> dict[int, dict]:
    meta, inputs, training = fixture
    return builder.build_summaries(inputs, training_matrix=training, root=meta["root"])


def test_missing_process_proof_has_exact_blocked_status_and_zero_credit(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, with_proofs=False)
    summaries = _build(fixture)
    for row in summaries.values():
        assert row["status"] == "blocked_missing_process_proof"
        assert row["source_bound"] is False
        assert row["credit"] == 0
        assert "process-exit proof is missing" in " ".join(row["blocked_reasons"])
        assert row["rollout_identity"] is None


def test_complete_fixture_binds_each_identity_without_opening_hdf5(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    summaries = _build(fixture)
    for seed, row in summaries.items():
        assert row["status"] == "fresh_terminal_identity_bound"
        assert row["source_bound"] is True
        assert row["credit"] == 0
        assert row["rollout_identity"]["namespace"].endswith(f"seed{seed}-full835-nonce{row['namespace_nonce']}")
        assert row["input_boundary"]["trajectory_hdf5_opened"] is False
        assert row["input_boundary"]["trajectory_hdf5_hashed"] is False
        assert row["input_boundary"]["evaluation_full_object_loaded"] is False
        assert row["sources"]["training_matrix"]["opened"] is True
        assert row["sources"]["history_summary"]["opened"] is True


def test_progress_file_cannot_substitute_for_process_proof(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, with_proofs=False)
    meta, inputs, _training = fixture
    seed = 17
    progress = Path(str(meta["namespace_paths"][seed]) + "-evaluation-progress.json")
    _write_json(progress, {"status": "completed", "transitions_executed": 835, "pid": 1234})
    inputs[seed] = builder.SeedInputs(inputs[seed].evaluation, inputs[seed].trajectory_metadata, inputs[seed].validator, inputs[seed].history_summary, progress)
    row = _build(fixture)[seed]
    assert row["status"] == "blocked_fail_closed"
    assert row["source_bound"] is False
    assert any("process_exit_proof" in reason or "process proof" in reason for reason in row["blocked_reasons"])


def test_nonexistent_process_proof_path_is_missing_evidence(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    meta, inputs, training = fixture
    seed = 17
    missing = tmp_path / "reports" / "does-not-exist-process-proof.json"
    inputs[seed] = builder.SeedInputs(inputs[seed].evaluation, inputs[seed].trajectory_metadata, inputs[seed].validator, inputs[seed].history_summary, missing)
    row = builder.build_summaries(inputs, training_matrix=training, root=meta["root"])[seed]
    assert row["status"] == "blocked_missing_process_proof"
    assert row["source_bound"] is False
    assert row["credit"] == 0


def test_wrong_evaluation_path_namespace_is_fail_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    meta, inputs, training = fixture
    seed = 29
    wrong = tmp_path / "alias-evaluation.json"
    wrong.write_bytes(inputs[seed].evaluation.read_bytes())
    inputs[seed] = builder.SeedInputs(wrong, inputs[seed].trajectory_metadata, inputs[seed].validator, inputs[seed].history_summary, inputs[seed].process_exit_proof)
    row = builder.build_summaries(inputs, training_matrix=training, root=meta["root"])[seed]
    assert row["source_bound"] is False
    assert any("canonical fresh" in reason for reason in row["blocked_reasons"])


def test_evaluation_hash_is_streamed_and_path_bytes_are_bound(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    summaries = _build(fixture)
    seed = 43
    evaluation = summaries[seed]["sources"]["evaluation"]
    assert evaluation["bytes"] == fixture[1][seed].evaluation.stat().st_size
    assert evaluation["sha256"] == _sha_bytes(fixture[1][seed].evaluation.read_bytes())
    assert summaries[seed]["rollout_identity"]["evaluation"] == evaluation


def test_trajectory_stream_hash_or_stat_drift_blocks(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    meta, inputs, training = fixture
    seed = 17
    metadata = json.loads(inputs[seed].trajectory_metadata.read_text())
    metadata["stream_hash"]["bytes"] += 1
    _write_json(inputs[seed].trajectory_metadata, metadata)
    row = builder.build_summaries(inputs, training_matrix=training, root=meta["root"])[seed]
    assert row["source_bound"] is False
    assert any("stream hash/bytes" in reason for reason in row["blocked_reasons"])


def test_validator_path_drift_blocks(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    meta, inputs, training = fixture
    seed = 29
    validator = json.loads(inputs[seed].validator.read_text())
    validator["trajectory_hdf5"] = "/tmp/wrong-trajectory.h5"
    _write_json(inputs[seed].validator, validator)
    row = builder.build_summaries(inputs, training_matrix=training, root=meta["root"])[seed]
    assert row["source_bound"] is False
    assert any("trajectory_hdf5" in reason for reason in row["blocked_reasons"])


def test_training_history_checkpoint_sha_drift_blocks(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    meta, inputs, training = fixture
    seed = 43
    history = json.loads(inputs[seed].history_summary.read_text())
    history["checkpoint"]["sha256"] = "f" * 64
    _write_json(inputs[seed].history_summary, history)
    row = builder.build_summaries(inputs, training_matrix=training, root=meta["root"])[seed]
    assert row["source_bound"] is False
    assert any("checkpoint identity drift" in reason for reason in row["blocked_reasons"])


def test_forged_process_digest_blocks(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    meta, inputs, training = fixture
    seed = 17
    proof = json.loads(inputs[seed].process_exit_proof.read_text())
    proof["returncode"] = 1
    _write_json(inputs[seed].process_exit_proof, proof)
    row = builder.build_summaries(inputs, training_matrix=training, root=meta["root"])[seed]
    assert row["source_bound"] is False
    assert any("returncode" in reason or "exit_proof_sha256" in reason for reason in row["blocked_reasons"])


def test_symlink_input_is_rejected(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    meta, inputs, training = fixture
    seed = 29
    link = tmp_path / "history-link.json"
    link.symlink_to(inputs[seed].history_summary)
    inputs[seed] = builder.SeedInputs(inputs[seed].evaluation, inputs[seed].trajectory_metadata, inputs[seed].validator, link, inputs[seed].process_exit_proof)
    row = builder.build_summaries(inputs, training_matrix=training, root=meta["root"])[seed]
    assert row["source_bound"] is False
    assert any("symlink" in reason for reason in row["blocked_reasons"])


def test_nonfinite_evaluation_scalar_is_rejected_by_stream_parser(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    meta, inputs, training = fixture
    seed = 43
    path = inputs[seed].evaluation
    text = path.read_text()
    path.write_text(text.replace('"raw_error_coverage":1.0', '"raw_error_coverage":NaN'))
    row = builder.build_summaries(inputs, training_matrix=training, root=meta["root"])[seed]
    assert row["source_bound"] is False
    assert any("non-finite" in reason or "invalid evaluation" in reason for reason in row["blocked_reasons"])


def test_cli_returns_blocked_batch_without_process_proof(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fixture = _fixture(tmp_path, with_proofs=False)
    meta, inputs, training = fixture
    argv = ["--root", str(meta["root"]), "--training-matrix", str(training)]
    for seed in builder.SEEDS:
        argv.extend(["--evaluation", f"{seed}={inputs[seed].evaluation}"])
        argv.extend(["--trajectory-metadata", f"{seed}={inputs[seed].trajectory_metadata}"])
        argv.extend(["--validator", f"{seed}={inputs[seed].validator}"])
        argv.extend(["--history-summary", f"{seed}={inputs[seed].history_summary}"])
    assert builder.main(argv) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "blocked_fail_closed"
    assert [row["status"] for row in output["seeds"]] == ["blocked_missing_process_proof"] * 3
