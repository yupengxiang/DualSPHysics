from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

import pytest


LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import f3_graph_raw_hidden16_terminal_runtime_verifier_v1 as verifier


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(verifier.canonical_json(value) + "\n", encoding="utf-8")


def _training_matrix() -> dict[str, object]:
    source = LAB_ROOT / "reports" / verifier.TRAINING_MATRIX_FILENAME
    return json.loads(source.read_text(encoding="utf-8"))


def _terminal_matrix(training: dict[str, object]) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for training_row in training["runs"]:  # type: ignore[index]
        seed = int(training_row["seed"])
        evidence = training_row["evidence"]
        source = training_row["source"]
        prefix = f"/tmp/f3-graph-raw500-hidden16-seed{seed}-full835-nonce{seed:032x}"
        checkpoint_path = evidence["checkpoint"]["path"]
        checkpoint_sha = evidence["checkpoint"]["sha256"]
        training_path = source["path"]
        training_sha = source["sha256"]
        trajectory_sha = _sha(f"raw-trajectory-{seed}")
        projection = {
            "seed": seed,
            "model_kind": verifier.MODEL_KIND,
            "hidden": verifier.HIDDEN,
            "updates": verifier.UPDATES,
            "case_id": verifier.CASE_ID,
            "split": verifier.SPLIT,
            "transitions": verifier.TRANSITIONS,
            "frames": verifier.FRAMES,
            "diagnostic_only": True,
            "formal_eligible": False,
            "qualification_credit": 0,
            "credit": 0,
            "config": {
                "model_kind": verifier.MODEL_KIND,
                "hidden": verifier.HIDDEN,
                "updates": verifier.UPDATES,
                "case_id": verifier.CASE_ID,
                "split": verifier.SPLIT,
                "maximum_steps": verifier.TRANSITIONS,
                "diagnostic": True,
                "future_state_inputs": False,
            },
            "checkpoint": {
                "path": checkpoint_path,
                "sha256": checkpoint_sha,
                "bytes": 152000 + seed,
                "update": verifier.UPDATES,
            },
            "manifest": {
                "path": verifier._canonical_manifest_path(),
                "sha256": training_row["evidence"]["manifest_sha256"],
                "bytes": 4096,
            },
            "training": {
                "path": training_path,
                "sha256": training_sha,
                "bytes": source["bytes"],
                "schema": "core.training.v1",
            },
            "evaluation": {
                "path": prefix + "-evaluation.json",
                "sha256": _sha(f"raw-evaluation-{seed}"),
                "bytes": 6400000 + seed,
                "schema": "core.evaluation.v1",
                # The historical raw matrix projection records transition
                # frames here; the independent rollout identity below binds
                # the terminal 836-frame contract.
                "frames": verifier.TRANSITIONS,
            },
            "trajectory": {
                "path": prefix + "-trajectory.h5",
                "sha256": trajectory_sha,
                "bytes": 723148320,
                "content_opened": False,
            },
            "validator": {
                "passed": True,
                "complete": True,
                "trajectory_transitions": verifier.TRANSITIONS,
                "trajectory_frames": verifier.FRAMES,
            },
            "terminal_markers": {
                "terminal": True,
                "execution_complete": True,
                "finite_rollout_complete": True,
                "terminal_status": "completed",
            },
            "output_namespace": prefix,
        }
        rows.append({"seed": seed, "status": "bound_terminal_diagnostic", "blocked_reasons": [], "projection": projection})
    return {
        "schema": verifier.TERMINAL_MATRIX_SCHEMA,
        "report_id": "f3-graph-raw-hidden16-terminal-completion-receipt-matrix-v1",
        "status": "bound_terminal_diagnostic",
        "fail_closed": False,
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
        "expected_contract": {
            "model_kind": verifier.MODEL_KIND,
            "hidden": verifier.HIDDEN,
            "updates": verifier.UPDATES,
            "seeds": list(verifier.SEEDS),
            "case_id": verifier.CASE_ID,
            "split": verifier.SPLIT,
            "transitions": verifier.TRANSITIONS,
            "frames": verifier.FRAMES,
            "terminal_status": "completed",
            "progress_or_pid_is_not_completion": True,
        },
        "seed_matrix": rows,
        "blocked_reasons": [],
        "checks": [{"check": "receipt_matrix_fixture", "passed": True}],
        "terminal_sources": {},
        "side_effects": {},
        "input_boundary": {},
    }


def _envelopes(training: dict[str, object], terminal: dict[str, object]) -> dict[str, dict[int, dict[str, object]]]:
    result: dict[str, dict[int, dict[str, object]]] = {"rollout": {}, "process": {}, "validator": {}}
    for terminal_row in terminal["seed_matrix"]:  # type: ignore[index]
        seed = int(terminal_row["seed"])
        projection = terminal_row["projection"]
        training_row = next(row for row in training["runs"] if int(row["seed"]) == seed)  # type: ignore[index]
        manifest_sha = training_row["evidence"]["manifest_sha256"]
        common = {
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
            "run_id": verifier._run_id(seed),
            "namespace": projection["output_namespace"],
            "namespace_nonce": f"{seed:032x}",
            "model_kind": verifier.MODEL_KIND,
            "hidden": verifier.HIDDEN,
            "updates": verifier.UPDATES,
            "case_id": verifier.CASE_ID,
            "split": verifier.SPLIT,
            "transitions": verifier.TRANSITIONS,
            "frames": verifier.FRAMES,
            "manifest": {"path": "/tmp/f3-graph-raw500-hidden16-20260928-manifest.json", "sha256": manifest_sha, "bytes": 4096},
            "training_receipt": {key: projection["training"][key] for key in ("path", "sha256", "bytes")},
            "checkpoint": {key: projection["checkpoint"][key] for key in ("path", "sha256", "bytes")},
            "trajectory": {key: projection["trajectory"][key] for key in ("path", "sha256", "bytes")},
        }
        evaluator_command = [
            verifier.CANONICAL_INTERPRETER,
            verifier.CANONICAL_CORE_LEARNING,
            "evaluate",
            "--manifest", verifier.CANONICAL_MANIFEST,
            "--data-root", verifier.CANONICAL_DATA_ROOT,
            "--checkpoint", projection["checkpoint"]["path"],
            "--case-id", verifier.CASE_ID,
            "--split", verifier.SPLIT,
            "--maximum-steps", str(verifier.TRANSITIONS),
            "--chunk-size", verifier.CANONICAL_CHUNK_SIZE,
            "--device", verifier.CANONICAL_DEVICE,
            "--progress-every", verifier.CANONICAL_PROGRESS_EVERY,
            "--trajectory-output", projection["trajectory"]["path"],
            "--progress-output", projection["output_namespace"] + "-evaluation-progress.json",
            "--output", projection["evaluation"]["path"],
            "--diagnostic",
        ]
        launcher_command = [
            verifier.CANONICAL_ENV,
            verifier.CANONICAL_ENV_ASSIGNMENT,
            "CUDA_VISIBLE_DEVICES=2",
            *evaluator_command,
        ]
        evaluator = {
            "alive": False,
            "returncode": 0,
            "reaped": True,
            "command": evaluator_command,
            "command_sha256": verifier._command_sha256(evaluator_command),
        }
        launcher = {
            "alive": False,
            "returncode": 0,
            "reaped": True,
            "command": launcher_command,
            "command_sha256": verifier._command_sha256(launcher_command),
        }
        bindings = {
            "seed": seed,
            "run_id": verifier._run_id(seed),
            "namespace": projection["output_namespace"],
            "namespace_nonce": f"{seed:032x}",
            "checkpoint": common["checkpoint"],
            "training_receipt": common["training_receipt"],
            "manifest": common["manifest"],
            "evaluation_artifact": {key: projection["evaluation"][key] for key in ("path", "sha256", "bytes")},
            "trajectory": common["trajectory"],
        }
        evaluation_artifact = {key: projection["evaluation"][key] for key in ("path", "sha256", "bytes")}
        plan_sha256 = verifier._process_plan_digest(
            common,
            evaluation_artifact,
            evaluator["command_sha256"],
            launcher["command_sha256"],
        )
        gpu_core = {
            "physical_index": 2,
            "uuid": "GPU-12345678-90ab-cdef-1234-567890abcdef",
            "pci_bus_id": "0000:02:00.0",
            "logical_device": verifier.CANONICAL_DEVICE,
            "cuda_visible_devices": "2",
            "cuda_device_order": "PCI_BUS_ID",
            "memory_total_mib": 49152,
            "memory_used_mib": 1024,
            "memory_free_mib": 48128,
        }
        gpu = {**gpu_core, "identity_sha256": verifier._digest(gpu_core)}
        runtime_core = {
            "schema": verifier.RUNTIME_IDENTITY_SCHEMA,
            "status": "observed",
            "source": "scheduler_owned_live_probe",
            "external_observation": True,
            "scheduler_owned": True,
            "observed_during_execution": True,
            "observed_after_exit": True,
            "plan_sha256": plan_sha256,
            "namespace": common["namespace"],
            "namespace_nonce": common["namespace_nonce"],
            "gpu": gpu,
            "child": {
                "observed": True,
                "child_runtime_attested": True,
                "gpu_uuid": gpu["uuid"],
                "logical_device": verifier.CANONICAL_DEVICE,
                "probe_tool": "nvidia-smi",
                "process_identity_sha256": _sha(f"raw-process-identity-{seed}"),
            },
            "terminal": {
                "observed": True,
                "status": "completed",
                "transitions": verifier.TRANSITIONS,
                "frames": verifier.FRAMES,
                "namespace": common["namespace"],
                "namespace_nonce": common["namespace_nonce"],
                "evaluation_sha256": evaluation_artifact["sha256"],
                "trajectory_sha256": common["trajectory"]["sha256"],
            },
            "observed_at_utc": "2026-09-29T00:00:00Z",
        }
        runtime_identity = {
            **runtime_core,
            "identity_sha256": verifier._digest(runtime_core),
        }
        scheduler_core = {
            "schema": verifier.SCHEDULER_ATTESTATION_SCHEMA,
            "status": "authorized",
            "external_scheduler": True,
            "one_shot": True,
            "authority_id": _sha(f"raw-authority-{seed}"),
            "trust_anchor_sha256": _sha("raw-scheduler-trust-anchor"),
            "signature_algorithm": "ed25519",
            "signature_sha256": _sha(f"raw-scheduler-signature-{seed}"),
            "signature_verified": True,
            "plan_sha256": plan_sha256,
            "namespace": common["namespace"],
            "namespace_nonce": common["namespace_nonce"],
            "resource_snapshot_sha256": _sha(f"raw-resource-snapshot-{seed}"),
            "gpu_identity_sha256": gpu["identity_sha256"],
            "observed_at_utc": "2026-09-29T00:00:00Z",
            "local_self_attestation_accepted": False,
        }
        scheduler_attestation = {
            **scheduler_core,
            "digest": verifier._digest(scheduler_core),
        }
        consume_core = {
            "schema": verifier.ONE_SHOT_CONSUME_SCHEMA,
            "status": "consumed",
            "external_scheduler": True,
            "one_shot": True,
            "replay_free": True,
            "atomic_compare_and_swap": True,
            "authority_id": scheduler_attestation["authority_id"],
            "trust_anchor_sha256": scheduler_attestation["trust_anchor_sha256"],
            "scheduler_attestation_sha256": scheduler_attestation["digest"],
            "plan_sha256": plan_sha256,
            "namespace": common["namespace"],
            "namespace_nonce": common["namespace_nonce"],
            "gpu_identity_sha256": gpu["identity_sha256"],
            "consume_id": _sha(f"raw-consume-{seed}"),
            "reservation_sha256": _sha(f"raw-reservation-{seed}"),
            "previous_state": "reserved",
            "new_state": "consumed",
            "observed_at_utc": "2026-09-29T00:00:00Z",
            "local_self_attestation_accepted": False,
        }
        one_shot_consume_witness = {
            **consume_core,
            "digest": verifier._digest(consume_core),
        }
        producer_core = {
            "schema": verifier.PROCESS_PRODUCER_SCHEMA,
            "id": verifier.PROCESS_PRODUCER_ID,
            "version": 1,
            "source_bound": True,
            "synthetic_only": False,
        }
        producer = {**producer_core, "digest": verifier._digest(producer_core)}
        attestation_core = {
            "schema": verifier.PROCESS_ATTESTATION_SCHEMA,
            "status": "exited_successfully",
            "source_bound": True,
            "synthetic_only": False,
            "natural_exit": True,
            "observed_after_exit": True,
            "producer_digest": producer["digest"],
            "evaluator": evaluator,
            "launcher": launcher,
            "artifact_bindings": bindings,
            "artifact_bindings_sha256": verifier._digest(bindings),
            "runtime_identity": runtime_identity,
            "scheduler_attestation": scheduler_attestation,
            "one_shot_consume_witness": one_shot_consume_witness,
        }
        attestation = {**attestation_core, "digest": verifier._digest(attestation_core)}
        rollout = {
            **common,
            "schema": f"core.f3.graph_raw.hidden16.seed{seed}.rollout_identity.v1",
            "report_id": f"f3-graph-raw-hidden16-seed{seed}-full835-rollout-identity-v1",
            "status": "completed_diagnostic",
            "evaluation_artifact": evaluation_artifact,
            "terminal_markers": {"terminal": True, "execution_complete": True, "finite_rollout_complete": True, "terminal_status": "completed", "future_state_inputs": False},
        }
        process = {
            **common,
            "schema": f"core.f3.graph_raw.hidden16.seed{seed}.process_exit_proof.v1",
            "report_id": f"f3-graph-raw-hidden16-seed{seed}-process-exit-proof-v1",
            "status": "exited_successfully",
            "evaluator_alive": False,
            "launcher_alive": False,
            "evaluator_returncode": 0,
            "launcher_returncode": 0,
            "returncode": 0,
            "evaluation_artifact": evaluation_artifact,
            "producer": producer,
            "exit_attestation": attestation,
        }
        validator = {
            **common,
            "schema": f"core.f3.graph_raw.hidden16.seed{seed}.hdf5_validator_receipt.v1",
            "report_id": f"f3-graph-raw-hidden16-seed{seed}-hdf5-validator-receipt-v1",
            "status": "validated",
            "validator_schema": verifier.VALIDATOR_SCHEMA,
            "passed": True,
            "complete": True,
            "expected_transitions": verifier.TRANSITIONS,
            "frames_executed": verifier.FRAMES,
            "trajectory_transitions": verifier.TRANSITIONS,
            "trajectory_frames": verifier.FRAMES,
            "tail_frame_count": 0,
            "production_artifacts_touched": False,
            "actual_future_state_inputs": False,
            "synthetic_only": False,
        }
        result["rollout"][seed] = rollout
        result["process"][seed] = process
        result["validator"][seed] = validator
    return result


def _build_complete(root: Path) -> tuple[dict[str, object], dict[str, dict[int, Path]], dict[str, object]]:
    root.mkdir(parents=True, exist_ok=True)
    training = _training_matrix()
    training_path = root / "inputs" / "training-matrix.json"
    _write_json(training_path, training)
    terminal = _terminal_matrix(training)
    terminal_path = root / "inputs" / "terminal-matrix.json"
    _write_json(terminal_path, terminal)
    envelopes = _envelopes(training, terminal)
    paths: dict[str, dict[int, Path]] = {"rollout": {}, "process": {}, "validator": {}}
    for kind, payloads in envelopes.items():
        for seed, payload in payloads.items():
            path = root / "inputs" / f"seed{seed}-{kind}.json"
            _write_json(path, payload)
            paths[kind][seed] = path
    report = verifier.build_report(
        root,
        training_matrix_path=training_path,
        terminal_matrix_path=terminal_path,
        rollout_paths=paths["rollout"],
        process_paths=paths["process"],
        validator_paths=paths["validator"],
    )
    return report, paths, {"training": training, "terminal": terminal, "training_path": training_path, "terminal_path": terminal_path}


def test_default_report_is_blocked_and_zero_credit() -> None:
    report = verifier.build_report()
    assert report["status"] == "blocked_fail_closed"
    assert report["source_bound"] is False
    assert report["credit"] == 0
    assert report["formal"] is False
    assert verifier.validate_report(report) == []


def test_complete_positive_binds_all_required_classes_without_hdf5(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report, _paths, _payloads = _build_complete(tmp_path)
    assert report["source_bound"] is True
    assert report["status"] == "independently_terminal_verified"
    original_open = verifier.os.open

    def guarded_open(path: object, *args: object, **kwargs: object) -> int:
        if isinstance(path, (str, bytes, os.PathLike)) and ".h5" in os.fspath(path):
            raise AssertionError("runtime verifier must not open HDF5/trajectory")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(verifier.os, "open", guarded_open)
    report, _paths, _payloads = _build_complete(tmp_path / "guarded")
    assert report["source_bound"] is True
    assert report["side_effects"]["hdf5_opened"] is False
    assert verifier.validate_report(report) == []


def test_missing_process_proof_is_not_terminal_verified(tmp_path: Path) -> None:
    _report, paths, payloads = _build_complete(tmp_path)
    paths["process"][17].unlink()
    report = verifier.build_report(tmp_path, training_matrix_path=payloads["training_path"], terminal_matrix_path=payloads["terminal_path"], rollout_paths=paths["rollout"], process_paths=paths["process"], validator_paths=paths["validator"])
    assert report["source_bound"] is False
    assert any("process_exit_proof" in reason or "missing required" in reason for reason in report["blocked_reasons"])


@pytest.mark.parametrize("field", ["scheduler_attestation", "one_shot_consume_witness", "runtime_identity"])
def test_external_scheduler_and_runtime_witnesses_are_required(tmp_path: Path, field: str) -> None:
    _report, paths, payloads = _build_complete(tmp_path)
    process = json.loads(paths["process"][17].read_text(encoding="utf-8"))
    process["exit_attestation"].pop(field)
    _write_json(paths["process"][17], process)
    report = verifier.build_report(
        tmp_path,
        training_matrix_path=payloads["training_path"],
        terminal_matrix_path=payloads["terminal_path"],
        rollout_paths=paths["rollout"],
        process_paths=paths["process"],
        validator_paths=paths["validator"],
    )
    assert report["source_bound"] is False
    assert any(field in reason for reason in report["blocked_reasons"])


def test_gpu_and_terminal_identity_observations_are_cross_bound(tmp_path: Path) -> None:
    _report, paths, payloads = _build_complete(tmp_path)
    process = json.loads(paths["process"][17].read_text(encoding="utf-8"))
    process["exit_attestation"]["runtime_identity"]["gpu"]["pci_bus_id"] = "0000:03:00.0"
    _write_json(paths["process"][17], process)
    report = verifier.build_report(
        tmp_path,
        training_matrix_path=payloads["training_path"],
        terminal_matrix_path=payloads["terminal_path"],
        rollout_paths=paths["rollout"],
        process_paths=paths["process"],
        validator_paths=paths["validator"],
    )
    assert report["source_bound"] is False
    assert any("identity_sha256" in reason or "pci_bus_id" in reason for reason in report["blocked_reasons"])

    _report, paths, payloads = _build_complete(tmp_path / "terminal")
    process = json.loads(paths["process"][17].read_text(encoding="utf-8"))
    process["exit_attestation"]["runtime_identity"]["terminal"]["evaluation_sha256"] = _sha("drifted-evaluation")
    _write_json(paths["process"][17], process)
    report = verifier.build_report(
        tmp_path / "terminal",
        training_matrix_path=payloads["training_path"],
        terminal_matrix_path=payloads["terminal_path"],
        rollout_paths=paths["rollout"],
        process_paths=paths["process"],
        validator_paths=paths["validator"],
    )
    assert report["source_bound"] is False
    assert any("evaluation_sha256" in reason or "terminal" in reason for reason in report["blocked_reasons"])


@pytest.mark.parametrize("field", ["evaluator_alive", "launcher_alive", "returncode", "evaluator_returncode", "launcher_returncode"])
def test_running_or_nonzero_process_proof_fails_closed(tmp_path: Path, field: str) -> None:
    _report, paths, payloads = _build_complete(tmp_path)
    value = json.loads(paths["process"][17].read_text(encoding="utf-8"))
    value[field] = True if field.endswith("alive") else 1
    _write_json(paths["process"][17], value)
    report = verifier.build_report(tmp_path, training_matrix_path=payloads["training_path"], terminal_matrix_path=payloads["terminal_path"], rollout_paths=paths["rollout"], process_paths=paths["process"], validator_paths=paths["validator"])
    assert report["source_bound"] is False
    assert any(field in reason for reason in report["blocked_reasons"])


def test_cross_file_identity_drift_fails_closed(tmp_path: Path) -> None:
    _report, paths, payloads = _build_complete(tmp_path)
    value = json.loads(paths["rollout"][29].read_text(encoding="utf-8"))
    value["checkpoint"]["sha256"] = _sha("drifted-checkpoint")
    _write_json(paths["rollout"][29], value)
    report = verifier.build_report(tmp_path, training_matrix_path=payloads["training_path"], terminal_matrix_path=payloads["terminal_path"], rollout_paths=paths["rollout"], process_paths=paths["process"], validator_paths=paths["validator"])
    assert report["source_bound"] is False
    assert any("checkpoint" in reason for reason in report["blocked_reasons"])


@pytest.mark.parametrize("alias", ["formal_status", "formal_claim", "pid", "process_id", "credit_points", "credit_delta"])
def test_unknown_formal_pid_and_credit_aliases_fail_closed(tmp_path: Path, alias: str) -> None:
    _report, paths, payloads = _build_complete(tmp_path)
    value = json.loads(paths["rollout"][17].read_text(encoding="utf-8"))
    value[alias] = False if "formal" in alias else 0
    _write_json(paths["rollout"][17], value)
    report = verifier.build_report(tmp_path, training_matrix_path=payloads["training_path"], terminal_matrix_path=payloads["terminal_path"], rollout_paths=paths["rollout"], process_paths=paths["process"], validator_paths=paths["validator"])
    assert report["source_bound"] is False
    assert any(alias in reason for reason in report["blocked_reasons"])


def test_old_namespace_nonce_and_frame_drift_fail_closed(tmp_path: Path) -> None:
    _report, paths, payloads = _build_complete(tmp_path)
    matrix = json.loads(payloads["terminal_path"].read_text(encoding="utf-8"))
    matrix["seed_matrix"][0]["projection"]["output_namespace"] = "/tmp/f3-graph-raw500-hidden16-seed17-full835-20260928"
    _write_json(payloads["terminal_path"], matrix)
    report = verifier.build_report(tmp_path, training_matrix_path=payloads["training_path"], terminal_matrix_path=payloads["terminal_path"], rollout_paths=paths["rollout"], process_paths=paths["process"], validator_paths=paths["validator"])
    assert report["source_bound"] is False
    assert any("canonical" in reason or "namespace" in reason for reason in report["blocked_reasons"])


def test_path_traversal_symlink_and_hardlink_are_rejected(tmp_path: Path) -> None:
    _report, paths, payloads = _build_complete(tmp_path)
    outside = tmp_path.parent / "outside-rollout.json"
    outside.write_text(paths["rollout"][17].read_text(encoding="utf-8"), encoding="utf-8")
    paths["rollout"][17] = Path("../outside-rollout.json")
    report = verifier.build_report(tmp_path, training_matrix_path=payloads["training_path"], terminal_matrix_path=payloads["terminal_path"], rollout_paths=paths["rollout"], process_paths=paths["process"], validator_paths=paths["validator"])
    assert report["source_bound"] is False
    assert any("traversal" in reason or "escapes" in reason for reason in report["blocked_reasons"])

    _report, paths, payloads = _build_complete(tmp_path / "symlink")
    real = paths["rollout"][17]
    moved = real.with_name("rollout-real.json")
    real.rename(moved)
    link = real.with_name("rollout-link.json")
    link.symlink_to(moved)
    paths["rollout"][17] = link
    report = verifier.build_report(tmp_path / "symlink", training_matrix_path=payloads["training_path"], terminal_matrix_path=payloads["terminal_path"], rollout_paths=paths["rollout"], process_paths=paths["process"], validator_paths=paths["validator"])
    assert report["source_bound"] is False
    assert any("symlink" in reason for reason in report["blocked_reasons"])

    _report, paths, payloads = _build_complete(tmp_path / "hardlink")
    hardlink = tmp_path / "hardlink" / "inputs" / "rollout-hardlink.json"
    os.link(paths["rollout"][17], hardlink)
    paths["rollout"][17] = hardlink
    report = verifier.build_report(tmp_path / "hardlink", training_matrix_path=payloads["training_path"], terminal_matrix_path=payloads["terminal_path"], rollout_paths=paths["rollout"], process_paths=paths["process"], validator_paths=paths["validator"])
    assert report["source_bound"] is False
    assert any("hard-linked" in reason for reason in report["blocked_reasons"])


def test_duplicate_nonfinite_and_oversize_json_are_rejected(tmp_path: Path) -> None:
    _report, paths, payloads = _build_complete(tmp_path)
    paths["rollout"][17].write_bytes(b'{"schema":"x","schema":"y"}')
    report = verifier.build_report(tmp_path, training_matrix_path=payloads["training_path"], terminal_matrix_path=payloads["terminal_path"], rollout_paths=paths["rollout"], process_paths=paths["process"], validator_paths=paths["validator"])
    assert any("duplicate JSON" in reason for reason in report["blocked_reasons"])

    _report, paths, payloads = _build_complete(tmp_path / "nan")
    paths["rollout"][17].write_bytes(b'{"value":NaN}')
    report = verifier.build_report(tmp_path / "nan", training_matrix_path=payloads["training_path"], terminal_matrix_path=payloads["terminal_path"], rollout_paths=paths["rollout"], process_paths=paths["process"], validator_paths=paths["validator"])
    assert any("non-finite" in reason for reason in report["blocked_reasons"])

    _report, paths, payloads = _build_complete(tmp_path / "oversize")
    paths["rollout"][17].write_bytes(b"{" + b" " * verifier.MAX_JSON_BYTES + b"}")
    report = verifier.build_report(tmp_path / "oversize", training_matrix_path=payloads["training_path"], terminal_matrix_path=payloads["terminal_path"], rollout_paths=paths["rollout"], process_paths=paths["process"], validator_paths=paths["validator"])
    assert any("exceeds bounded" in reason for reason in report["blocked_reasons"])


def test_report_validation_rejects_unknown_top_level_alias(tmp_path: Path) -> None:
    report = verifier.build_report(tmp_path)
    report["formal_status"] = False
    errors = verifier.validate_report(report)
    assert errors
    assert any("formal_status" in reason for reason in errors)


def test_report_validation_rejects_empty_nested_evidence_and_forged_positive(tmp_path: Path) -> None:
    report, _paths, _payloads = _build_complete(tmp_path)
    report["seed_matrix"][0]["evidence"] = {}
    assert verifier.validate_report(report)

    blocked = verifier.build_report(tmp_path / "blocked")
    blocked["source_bound"] = True
    blocked["fail_closed"] = False
    blocked["independently_terminal_verified"] = True
    blocked["status"] = "independently_terminal_verified"
    assert verifier.validate_report(blocked)


def test_report_validation_rejects_forged_check_and_source_metadata(tmp_path: Path) -> None:
    report, _paths, _payloads = _build_complete(tmp_path)
    report["checks"][0]["passed"] = False
    assert verifier.validate_report(report)

    report, _paths, _payloads = _build_complete(tmp_path / "source")
    report["seed_matrix"][0]["sources"]["process_exit_proof"]["sha256"] = _sha("tampered-source")
    assert verifier.validate_report(report)


def test_write_report_revalidates_nested_evidence_before_publication(tmp_path: Path) -> None:
    report, _paths, _payloads = _build_complete(tmp_path)
    report["seed_matrix"][0]["evidence"]["process_exit_proof"]["exit_attestation"]["digest"] = _sha("tampered-attestation")
    assert verifier.validate_report(report)
    (tmp_path / "reports").mkdir()
    with pytest.raises(verifier.VerifierError, match="refusing to write invalid report"):
        verifier.write_report(report, tmp_path / "reports" / verifier.REPORT_JSON_FILENAME, root=tmp_path)


def test_process_attestation_digest_command_and_artifact_binding_fail_closed(tmp_path: Path) -> None:
    _report, paths, payloads = _build_complete(tmp_path)
    process = json.loads(paths["process"][17].read_text(encoding="utf-8"))
    process["exit_attestation"]["artifact_bindings_sha256"] = _sha("tampered-bindings")
    _write_json(paths["process"][17], process)
    report = verifier.build_report(tmp_path, training_matrix_path=payloads["training_path"], terminal_matrix_path=payloads["terminal_path"], rollout_paths=paths["rollout"], process_paths=paths["process"], validator_paths=paths["validator"])
    assert report["source_bound"] is False
    assert any("artifact_bindings" in reason or "exit_attestation" in reason for reason in report["blocked_reasons"])

    _report, paths, payloads = _build_complete(tmp_path / "command")
    process = json.loads(paths["process"][17].read_text(encoding="utf-8"))
    process["exit_attestation"]["evaluator"]["command"][2] = "inspect"
    _write_json(paths["process"][17], process)
    report = verifier.build_report(paths["process"][17].parents[1], training_matrix_path=payloads["training_path"], terminal_matrix_path=payloads["terminal_path"], rollout_paths=paths["rollout"], process_paths=paths["process"], validator_paths=paths["validator"])
    assert report["source_bound"] is False
    assert any("command_sha256" in reason or "evaluate" in reason for reason in report["blocked_reasons"])


@pytest.mark.parametrize("mutation", ["arbitrary_script_path", "different_chunk_size"])
def test_process_rejects_self_consistent_noncanonical_complete_argv(tmp_path: Path, mutation: str) -> None:
    _report, paths, payloads = _build_complete(tmp_path)
    process = json.loads(paths["process"][17].read_text(encoding="utf-8"))
    attestation = process["exit_attestation"]
    evaluator = attestation["evaluator"]
    original_evaluator = list(evaluator["command"])
    mutated_evaluator = list(original_evaluator)
    if mutation == "arbitrary_script_path":
        mutated_evaluator[1] = "/tmp/attacker/core_learning.py"
    else:
        chunk_index = mutated_evaluator.index("--chunk-size") + 1
        mutated_evaluator[chunk_index] = "1"
    evaluator["command"] = mutated_evaluator
    evaluator["command_sha256"] = verifier._command_sha256(mutated_evaluator)

    launcher = attestation["launcher"]
    original_launcher = list(launcher["command"])
    prefix = original_launcher[: -len(original_evaluator)]
    mutated_launcher = [*prefix, *mutated_evaluator]
    launcher["command"] = mutated_launcher
    launcher["command_sha256"] = verifier._command_sha256(mutated_launcher)
    attestation_core = {key: value for key, value in attestation.items() if key != "digest"}
    attestation["digest"] = verifier._digest(attestation_core)
    _write_json(paths["process"][17], process)

    report = verifier.build_report(
        tmp_path,
        training_matrix_path=payloads["training_path"],
        terminal_matrix_path=payloads["terminal_path"],
        rollout_paths=paths["rollout"],
        process_paths=paths["process"],
        validator_paths=paths["validator"],
    )
    assert report["source_bound"] is False
    assert any("canonical evaluator argv" in reason for reason in report["blocked_reasons"])


def test_process_attestation_rejects_synthetic_or_missing_producer_chain(tmp_path: Path) -> None:
    _report, paths, payloads = _build_complete(tmp_path)
    process = json.loads(paths["process"][17].read_text(encoding="utf-8"))
    process["exit_attestation"]["synthetic_only"] = True
    _write_json(paths["process"][17], process)
    report = verifier.build_report(tmp_path, training_matrix_path=payloads["training_path"], terminal_matrix_path=payloads["terminal_path"], rollout_paths=paths["rollout"], process_paths=paths["process"], validator_paths=paths["validator"])
    assert report["source_bound"] is False
    assert any("synthetic_only" in reason or "digest" in reason for reason in report["blocked_reasons"])

    _report, paths, payloads = _build_complete(tmp_path / "missing")
    process = json.loads(paths["process"][17].read_text(encoding="utf-8"))
    process.pop("producer")
    _write_json(paths["process"][17], process)
    report = verifier.build_report(paths["process"][17].parents[1], training_matrix_path=payloads["training_path"], terminal_matrix_path=payloads["terminal_path"], rollout_paths=paths["rollout"], process_paths=paths["process"], validator_paths=paths["validator"])
    assert report["source_bound"] is False
    assert any("producer" in reason for reason in report["blocked_reasons"])


@pytest.mark.parametrize("artifact", ["manifest", "checkpoint"])
def test_manifest_and_checkpoint_path_drift_fail_closed(tmp_path: Path, artifact: str) -> None:
    _report, paths, payloads = _build_complete(tmp_path)
    value = json.loads(paths["rollout"][17].read_text(encoding="utf-8"))
    value[artifact]["path"] = f"/var/tmp/{Path(value[artifact]['path']).name}"
    _write_json(paths["rollout"][17], value)
    report = verifier.build_report(tmp_path, training_matrix_path=payloads["training_path"], terminal_matrix_path=payloads["terminal_path"], rollout_paths=paths["rollout"], process_paths=paths["process"], validator_paths=paths["validator"])
    assert report["source_bound"] is False
    assert any(artifact in reason for reason in report["blocked_reasons"])


def test_walk_json_rejects_oversized_arrays() -> None:
    with pytest.raises(verifier.VerifierError, match="maximum JSON array length"):
        verifier._walk_json([None] * (verifier.MAX_JSON_ARRAY_ITEMS + 1))
