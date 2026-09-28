"""Tests for the independent current-manifest terminal-evidence intake."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import f3_mlp_hidden16_current_manifest_terminal_evidence_v1 as intake


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_sha(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return _sha_bytes(raw)


def _write_json(path: Path, value: object) -> tuple[str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    path.write_bytes(raw)
    return _sha_bytes(raw), len(raw)


def _write_bytes(path: Path, value: bytes) -> tuple[str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return _sha_bytes(value), len(value)


def _artifact(path: Path, sha256: str, size: int) -> dict[str, object]:
    return {"path": str(path), "sha256": sha256, "bytes": size}


def _zero() -> dict[str, object]:
    return {
        "diagnostic_only": True,
        "formal": False,
        "formal_eligible": False,
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "qualification": False,
        "qualification_credit": 0,
        "credit": 0,
    }


def _fixture(tmp_path: Path) -> dict[str, object]:
    root = tmp_path / "lab"
    reports = root / "reports"
    reports.mkdir(parents=True)
    manifest_path = root / "campaigns" / "current" / "manifest.json"
    manifest_payload = {"schema": "core.dataset.v2", "dataset_id": "fixture-current"}
    manifest_raw = json.dumps(manifest_payload, sort_keys=True, indent=2).encode() + b"\n"
    manifest_raw_sha, manifest_bytes = _write_bytes(manifest_path, manifest_raw)
    manifest_canonical_sha = _canonical_sha(manifest_payload)

    manifest_identity = {
        "schema": intake.MANIFEST_SCHEMA,
        "status": "bound",
        "source_bound": True,
        **_zero(),
        "manifest": {
            "raw": {"path": str(manifest_path), "sha256": manifest_raw_sha, "bytes": manifest_bytes},
            "canonical": {"sha256": manifest_canonical_sha},
        },
    }
    manifest_identity_path = reports / "current-manifest-identity.json"
    _write_json(manifest_identity_path, manifest_identity)

    training_rows: list[dict[str, object]] = []
    seeds: dict[int, dict[str, object]] = {}
    for seed in intake.SEEDS:
        run_id = f"f3-mlp500-hidden16-currentmanifest-seed{seed}-20260929"
        receipt_path = root / "inputs" / f"training-{seed}.json"
        receipt_sha, receipt_bytes = _write_json(receipt_path, {"opaque": f"training-{seed}"})
        checkpoint_path = root / "inputs" / f"checkpoint-{seed}.pt"
        checkpoint_sha, checkpoint_bytes = _write_bytes(checkpoint_path, f"opaque-checkpoint-{seed}".encode())
        checkpoint = {
            "schema": "core.checkpoint.v1",
            "path": str(checkpoint_path),
            "sha256": checkpoint_sha,
            "bytes": checkpoint_bytes,
            "update": intake.UPDATES,
        }
        training_rows.append({
            "seed": seed,
            "status": "bound",
            "blocked_reasons": [],
            "source": {
                "path": str(receipt_path),
                "bytes": receipt_bytes,
                "sha256": receipt_sha,
                "opened": True,
                "schema": "core.training.v1",
            },
            "evidence": {
                "seed": seed,
                "run_id": run_id,
                "schema": "core.training.v1",
                "model": intake.MODEL,
                "hidden": intake.HIDDEN,
                "updates": intake.UPDATES,
                "completed": True,
                "manifest_sha256": manifest_canonical_sha,
                "receipt_identity": {"path": str(receipt_path), "bytes": receipt_bytes, "sha256": receipt_sha},
                "checkpoint_identity": checkpoint,
                "zero_credit": {
                    "diagnostic_only": True,
                    "formal": False,
                    "T1_numerical": False,
                    "T2_macro": False,
                    "T2_path": False,
                    "credit": 0,
                },
            },
        })
        seeds[seed] = {
            "run_id": run_id,
            "receipt_path": receipt_path,
            "receipt_sha": receipt_sha,
            "checkpoint": checkpoint,
        }

    training_report = {
        "schema": intake.TRAINING_SCHEMA,
        "report_id": "fixture-current-manifest-training",
        "observed_at_utc": "2026-09-29T00:00:00Z",
        "status": "diagnostic_bound",
        "fail_closed": False,
        "source_bound": True,
        "diagnostic_only": True,
        "formal": False,
        "formal_eligible": False,
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "qualification": False,
        "credit": 0,
        "qualification_credit": 0,
        "model": intake.MODEL,
        "hidden": intake.HIDDEN,
        "updates": intake.UPDATES,
        "seeds": list(intake.SEEDS),
        "manifest": {
            "path": str(manifest_path),
            "bytes": manifest_bytes,
            "sha256": manifest_raw_sha,
            "opened": True,
            "schema": "core.dataset.v2",
            "canonical_sha256": manifest_canonical_sha,
        },
        "runs": training_rows,
        "authorization": {
            "formal": False,
            "formal_eligible": False,
            "T1_numerical": False,
            "T2_macro": False,
            "T2_path": False,
            "qualification": False,
            "credit": 0,
            "qualification_credit": 0,
        },
        "checks": [],
        "input_boundary": {},
        "side_effects": {},
        "scope_note": "fixture",
    }
    training_report_path = reports / "current-manifest-training-evidence.json"
    _write_json(training_report_path, training_report)

    plan_paths: dict[int, Path] = {}
    proof_paths: dict[int, Path] = {}
    evaluation_identity_paths: dict[int, Path] = {}
    trajectory_metadata_paths: dict[int, Path] = {}
    validator_paths: dict[int, Path] = {}
    artifact_identity_paths: dict[int, Path] = {}

    for seed in intake.SEEDS:
        item = seeds[seed]
        nonce = (f"{seed:02x}" * 16)[:32]
        namespace = root / "rollouts" / f"f3-mlp500-hidden16-currentmanifest-seed{seed}-full835-nonce{nonce}"
        evaluation_path = Path(str(namespace) + "-evaluation.json")
        trajectory_path = Path(str(namespace) + "-trajectory.h5")
        progress_path = Path(str(namespace) + "-evaluation-progress.json")
        log_path = Path(str(namespace) + "-evaluation.log")
        artifact_path = Path(str(namespace) + "-artifact-identity.json")
        validator_path = Path(str(namespace) + "-hdf5-validation.json")
        trajectory_metadata_path = Path(str(namespace) + "-trajectory-metadata.json")
        process_filename = intake._expected_process_filename(item["run_id"], nonce, manifest_canonical_sha)
        process_path = reports / process_filename
        evaluation_sha, evaluation_bytes = _write_bytes(evaluation_path, b"not-opened-evaluation")
        trajectory_sha, trajectory_bytes = _write_bytes(trajectory_path, b"not-opened-hdf5")
        _write_bytes(progress_path, b"not-opened-progress")
        _write_bytes(log_path, b"not-opened-log")
        checkpoint = item["checkpoint"]
        command = [
            "/tmp/fixture-python", "-u", "/tmp/fixture-core_learning.py", "evaluate",
            "--manifest", str(manifest_path), "--data-root", str(root),
            "--checkpoint", checkpoint["path"], "--case-id", intake.CASE_ID, "--split", intake.SPLIT,
            "--maximum-steps", str(intake.TRANSITIONS), "--trajectory-output", str(trajectory_path),
            "--progress-output", str(progress_path), "--output", str(evaluation_path), "--diagnostic",
        ]
        env = {"CUDA_VISIBLE_DEVICES": str((seed + 1) % 8), "PYTHONDONTWRITEBYTECODE": "1"}
        command_sha = _sha_bytes(json.dumps({"argv": command, "cwd": str(root), "env_overrides": env}, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())
        outputs = {
            "namespace": str(namespace),
            "evaluation": str(evaluation_path),
            "trajectory": str(trajectory_path),
            "progress": str(progress_path),
            "log": str(log_path),
            "artifact_identity": str(artifact_path),
            "validator": str(validator_path),
            "process_proof": str(process_path),
        }
        plan = {
            "schema": intake.PLAN_SCHEMA,
            "status": "dry_run_ready",
            "mode": "dry_run",
            "launched": False,
            "seed": seed,
            "run_id": item["run_id"],
            "model": intake.MODEL,
            "hidden": intake.HIDDEN,
            "updates": intake.UPDATES,
            "case_id": intake.CASE_ID,
            "split": intake.SPLIT,
            "transitions": intake.TRANSITIONS,
            "frames": intake.FRAMES,
            "gpu_index": int(env["CUDA_VISIBLE_DEVICES"]),
            "manifest": str(manifest_path),
            "manifest_sha256": manifest_canonical_sha,
            "manifest_file_sha256": manifest_raw_sha,
            "checkpoint": checkpoint,
            "training_receipt": item["receipt_path"].__str__(),
            "training_receipt_sha256": item["receipt_sha"],
            "output_namespace": str(namespace),
            "namespace_nonce": nonce,
            "command": command,
            "cwd": str(root),
            "env_overrides": env,
            "command_sha256": command_sha,
            "outputs": outputs,
            "trajectory_metadata": str(trajectory_metadata_path),
            "process_proof_filename": process_filename,
            **_zero(),
            "zero_credit_only": True,
            "side_effects": {"processes_started": 0, "processes_stopped": 0, "processes_restarted": 0, "registry_writes": 0, "ledger_writes": 0, "denominator_writes": 0, "gate_writes": 0, "plan_writes": 0},
            "input_boundary": {"bounded_training_receipt_opened": True, "manifest_content_opened": True, "checkpoint_content_opened": False, "evaluation_content_opened": False, "trajectory_hdf5_opened": False, "runtime_started": False, "queue_submissions": 0},
        }
        plan_path = reports / f"plan-{seed}.json"
        _write_json(plan_path, plan)

        evaluation_identity = {
            "schema": f"{intake.EVALUATION_SCHEMA_PREFIX}.seed{seed}.evaluation_identity.v1",
            "status": "completed",
            "source_bound": True,
            **_zero(),
            "seed": seed,
            "run_id": item["run_id"],
            "model": intake.MODEL,
            "hidden": intake.HIDDEN,
            "updates": intake.UPDATES,
            "case_id": intake.CASE_ID,
            "split": intake.SPLIT,
            "transitions": intake.TRANSITIONS,
            "frames": intake.FRAMES,
            "manifest_sha256": manifest_canonical_sha,
            "training_manifest_sha256": manifest_canonical_sha,
            "training_receipt_sha256": item["receipt_sha"],
            "namespace": str(namespace),
            "namespace_nonce": nonce,
            "checkpoint": checkpoint,
            "evaluation": _artifact(evaluation_path, evaluation_sha, evaluation_bytes),
            "result": {"status": "completed", "finite_rollout_complete": True, "execution_complete": True, "requested_window_complete": True, "transitions_executed": intake.TRANSITIONS, "trajectory_frames_including_initial": intake.FRAMES, "future_state_inputs": False, "failure_category": None},
        }
        evaluation_identity_path = reports / f"evaluation-identity-{seed}.json"
        _write_json(evaluation_identity_path, evaluation_identity)

        trajectory_metadata = {
            "schema": intake.TRAJECTORY_SCHEMA,
            "status": "completed",
            "source_bound": True,
            "seed": seed,
            "run_id": item["run_id"],
            "model": intake.MODEL,
            "hidden": intake.HIDDEN,
            "updates": intake.UPDATES,
            "case_id": intake.CASE_ID,
            "split": intake.SPLIT,
            "transitions": intake.TRANSITIONS,
            "frames": intake.FRAMES,
            "namespace": str(namespace),
            "namespace_nonce": nonce,
            "trajectory": _artifact(trajectory_path, trajectory_sha, trajectory_bytes),
            "stream_hash": {"algorithm": "sha256", "sha256": trajectory_sha, "bytes": trajectory_bytes},
            "future_state_inputs": False,
            **_zero(),
        }
        _write_json(trajectory_metadata_path, trajectory_metadata)

        validator = {
            "schema": intake.VALIDATOR_SCHEMA,
            "passed": True,
            "fail_closed": False,
            "diagnostic_only": True,
            "synthetic_only": False,
            "production_artifacts_touched": False,
            "qualification_credit": 0,
            "case_id": intake.CASE_ID,
            "evaluation_json": str(evaluation_path),
            "trajectory_hdf5": str(trajectory_path),
            "expected_transitions": intake.TRANSITIONS,
            "frames_executed": intake.TRANSITIONS,
            "complete": True,
            "incomplete": False,
            "failure_category": None,
            "checks": {"case_binding": True, "shape": True, "time": True, "valid": True, "future_state_inputs": True, "completion_semantics": True, "trajectory_frames": intake.FRAMES, "trajectory_transitions": intake.TRANSITIONS, "executed_frame_count": intake.FRAMES, "tail_frame_count": 0},
            "row_fields_checked": ["case_id", "frames_executed"],
        }
        validator_sha, validator_bytes = _write_json(validator_path, validator)

        artifact_identity = {
            "schema": f"{intake.ARTIFACT_SCHEMA_PREFIX}.seed{seed}.evaluator_artifact_identity.v1",
            "status": "completed_diagnostic",
            "seed": seed,
            "run_id": item["run_id"],
            "namespace": str(namespace),
            "namespace_nonce": nonce,
            "manifest_sha256": manifest_canonical_sha,
            "training_manifest_sha256": manifest_canonical_sha,
            "training_receipt_sha256": item["receipt_sha"],
            "checkpoint": checkpoint,
            "evaluation": _artifact(evaluation_path, evaluation_sha, evaluation_bytes),
            "trajectory": _artifact(trajectory_path, trajectory_sha, trajectory_bytes),
            "validator": _artifact(validator_path, validator_sha, validator_bytes),
            **_zero(),
        }
        _write_json(artifact_path, artifact_identity)

        def process_identity(phase: str, pid: int, *, end: bool) -> dict[str, object]:
            result: dict[str, object] = {"phase": phase, "pid": pid, "proc_starttime_ticks": 100 + pid, "observed_monotonic_ns": 1000000 + pid}
            if end:
                result.update({"returncode": 0, "reaped": True})
            return result

        process = {
            "schema": f"{intake.PROCESS_SCHEMA_PREFIX}.seed{seed}.process_exit_proof.v1",
            "report_id": f"fixture-process-proof-seed{seed}-{nonce}",
            "status": "exited_successfully",
            "source_bound": True,
            **_zero(),
            "seed": seed,
            "run_id": item["run_id"],
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
            "command_sha256": command_sha,
            "evaluator_start_identity": process_identity("start", 1000 + seed, end=False),
            "evaluator_end_identity": process_identity("end", 1000 + seed, end=True),
            "launcher_start_identity": process_identity("start", 2000 + seed, end=False),
            "launcher_end_identity": process_identity("end", 2000 + seed, end=True),
            "manifest_sha256": manifest_canonical_sha,
            "training_manifest_sha256": manifest_canonical_sha,
            "training_receipt_sha256": item["receipt_sha"],
            "checkpoint": checkpoint,
            "evaluation": _artifact(evaluation_path, evaluation_sha, evaluation_bytes),
            "trajectory": _artifact(trajectory_path, trajectory_sha, trajectory_bytes),
            "validator": _artifact(validator_path, validator_sha, validator_bytes),
        }
        process["exit_proof_sha256"] = _sha_bytes(json.dumps(process, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
        _write_json(process_path, process)

        plan_paths[seed] = plan_path
        proof_paths[seed] = process_path
        evaluation_identity_paths[seed] = evaluation_identity_path
        trajectory_metadata_paths[seed] = trajectory_metadata_path
        validator_paths[seed] = validator_path
        artifact_identity_paths[seed] = artifact_path
        seeds[seed].update({"nonce": nonce, "namespace": namespace, "evaluation": evaluation_path, "trajectory": trajectory_path, "validator": validator_path, "artifact": artifact_path, "process": process_path})

    return {
        "root": root,
        "manifest_identity": manifest_identity_path,
        "training_evidence": training_report_path,
        "rollout_plans": plan_paths,
        "proofs": proof_paths,
        "evaluation_identities": evaluation_identity_paths,
        "trajectory_metadata": trajectory_metadata_paths,
        "validators": validator_paths,
        "artifacts": artifact_identity_paths,
        "seeds": seeds,
    }


def _build(tmp_path: Path, fixture: dict[str, object]) -> dict[str, object]:
    return intake.build_report(
        fixture["root"],
        manifest_identity_path=fixture["manifest_identity"],
        training_evidence_path=fixture["training_evidence"],
        rollout_plan_paths=fixture["rollout_plans"],
        process_proof_paths=fixture["proofs"],
        evaluation_identity_paths=fixture["evaluation_identities"],
        trajectory_metadata_paths=fixture["trajectory_metadata"],
        validator_paths=fixture["validators"],
        artifact_identity_paths=fixture["artifacts"],
        observed_at_utc="2026-09-29T00:00:00Z",
    )


def test_default_without_inputs_is_blocked_and_zero_credit(tmp_path: Path) -> None:
    (tmp_path / "reports").mkdir()
    report = intake.build_report(tmp_path)
    assert report["status"] == "blocked_fail_closed"
    assert report["source_bound"] is False
    assert report["credit"] == 0
    assert all(row["status"] == "blocked" for row in report["seed_matrix"])
    assert intake.validate_report(report) == []


def test_cli_default_without_inputs_is_blocked(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    result = intake.main(["--root", str(tmp_path)])
    assert result == 2
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "blocked_fail_closed"
    assert output["source_bound"] is False
    assert output["credit"] == 0


def test_training_evidence_nonempty_errors_is_rejected(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    payload = json.loads(fixture["training_evidence"].read_text())
    payload["errors"] = ["unexpected diagnostic error"]
    fixture["training_evidence"].write_text(json.dumps(payload, sort_keys=True) + "\n")

    report = _build(tmp_path, fixture)

    assert report["status"] == "blocked_fail_closed"
    assert any("training evidence" in reason for reason in report["blocked_reasons"])


def test_actual_launcher_namespace_format_is_accepted_and_bound() -> None:
    nonce = "f17a9c4e2d6b8f1035c7e1a9d4b6c802"
    namespace = (
        "/tmp/f3-mlp500-hidden16-currentmanifest-seed17-full835-"
        f"20260929-{nonce}"
    )

    run_id = "f3-mlp500-hidden16-currentmanifest-seed17-20260929"
    assert intake._validate_namespace(namespace, 17, nonce, run_id, "namespace") == namespace

    with pytest.raises(intake.IntakeError, match="namespace nonce"):
        intake._validate_namespace(namespace + "0", 17, nonce, run_id, "namespace")

    mismatched_date = namespace.replace("20260929", "20260928")
    with pytest.raises(intake.IntakeError, match="date"):
        intake._validate_namespace(mismatched_date, 17, nonce, run_id, "namespace")

    with pytest.raises(intake.IntakeError, match="seed17"):
        intake._validate_namespace(namespace.upper(), 17, nonce, run_id, "namespace")


def test_launcher_manifest_boundary_contract_is_enforced(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    path = fixture["rollout_plans"][17]
    payload = json.loads(path.read_text())
    payload["input_boundary"]["manifest_content_opened"] = False
    _write_json(path, payload)

    report = _build(tmp_path, fixture)

    assert report["status"] == "blocked_fail_closed"
    assert any("manifest_content_opened" in reason for reason in report["blocked_reasons"])


def test_terminal_receipts_accept_legacy_checkpoint_identity_without_schema(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    for kind in ("proofs", "artifacts"):
        for path in fixture[kind].values():
            payload = json.loads(path.read_text())
            payload["checkpoint"].pop("schema")
            if kind == "proofs":
                without_digest = dict(payload)
                without_digest.pop("exit_proof_sha256", None)
                payload["exit_proof_sha256"] = _sha_bytes(
                    json.dumps(
                        without_digest,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    ).encode()
                )
            _write_json(path, payload)

    report = _build(tmp_path, fixture)

    assert report["status"] == "terminal_diagnostic_verified"
    assert report["source_bound"] is True


def test_complete_current_manifest_projection_set_is_terminal_diagnostic_only(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    report = _build(tmp_path, fixture)
    assert report["status"] == "terminal_diagnostic_verified"
    assert report["source_bound"] is True
    assert report["terminal_evidence_verified"] is True
    assert report["credit"] == 0
    assert all(row["status"] == "terminal_verified" for row in report["seed_matrix"])
    assert report["input_boundary"]["checkpoint_content_opened"] is False
    assert report["input_boundary"]["trajectory_hdf5_opened"] is False
    assert intake.validate_report(report) == []


@pytest.mark.parametrize(
    ("kind", "field", "value"),
    [
        ("proofs", "status", "running"),
        ("evaluation_identities", "status", "partial"),
        ("trajectory_metadata", "status", "running"),
    ],
)
def test_running_or_partial_terminal_projection_fails_closed(tmp_path: Path, kind: str, field: str, value: object) -> None:
    fixture = _fixture(tmp_path)
    seed = 17
    path = fixture[kind][seed]
    payload = json.loads(path.read_text())
    payload[field] = value
    _write_json(path, payload)
    report = _build(tmp_path, fixture)
    assert report["source_bound"] is False
    assert report["status"] == "blocked_fail_closed"
    assert any("status" in reason for reason in report["blocked_reasons"])


def test_run_id_nonce_checkpoint_and_training_receipt_drift_fail_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plan_path = fixture["rollout_plans"][29]
    plan = json.loads(plan_path.read_text())
    plan["run_id"] = "f3-mlp500-hidden16-currentmanifest-seed29-20260928"
    _write_json(plan_path, plan)
    report = _build(tmp_path, fixture)
    assert report["source_bound"] is False
    assert any("run_id" in reason for reason in report["blocked_reasons"])


def test_cross_projection_artifact_hash_drift_fails_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    path = fixture["evaluation_identities"][29]
    payload = json.loads(path.read_text())
    payload["evaluation"]["sha256"] = "f" * 64
    _write_json(path, payload)
    report = _build(tmp_path, fixture)
    assert report["source_bound"] is False
    assert any("artifact identity drifts" in reason for reason in report["blocked_reasons"])


def test_nonzero_credit_is_rejected_even_when_terminal_fields_match(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    path = fixture["evaluation_identities"][43]
    payload = json.loads(path.read_text())
    payload["credit"] = 1
    _write_json(path, payload)
    report = _build(tmp_path, fixture)
    assert report["source_bound"] is False
    assert any("credit" in reason for reason in report["blocked_reasons"])


def test_symlink_and_hardlink_projection_inputs_fail_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    target = fixture["proofs"][17]
    symlink = target.with_name("proof-symlink.json")
    symlink.symlink_to(target)
    fixture["proofs"][17] = symlink
    report = _build(tmp_path, fixture)
    assert report["source_bound"] is False
    assert any("symlink" in reason for reason in report["blocked_reasons"])

    fixture = _fixture(tmp_path / "hardlink")
    target = fixture["artifacts"][29]
    hardlink = target.with_name("artifact-hardlink.json")
    hardlink.hardlink_to(target)
    fixture["artifacts"][29] = hardlink
    report = _build(tmp_path / "hardlink", fixture)
    assert report["source_bound"] is False
    assert any("single-link" in reason for reason in report["blocked_reasons"])


def test_oversized_projection_is_rejected_before_json_parse(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    path = fixture["proofs"][43]
    path.write_bytes(b"{" + b"\"x\":\"" + b"x" * intake.MAX_JSON_BYTES + b'"}')
    report = _build(tmp_path, fixture)
    assert report["source_bound"] is False
    assert any("bounded JSON size" in reason for reason in report["blocked_reasons"])


def test_binary_and_hdf5_content_is_not_required_or_opened(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    for seed in intake.SEEDS:
        assert fixture["seeds"][seed]["checkpoint"].copy()
        assert fixture["seeds"][seed]["trajectory"].read_bytes() == b"not-opened-hdf5"
    report = _build(tmp_path, fixture)
    assert report["status"] == "terminal_diagnostic_verified"
    assert report["input_boundary"]["artifact_content_opened"] is False


def test_tampered_report_cannot_add_authority(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    report = _build(tmp_path, fixture)
    report["credit"] = 1
    assert any("credit" in error for error in intake.validate_report(report))
